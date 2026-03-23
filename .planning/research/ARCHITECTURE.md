# Architecture Research

**Domain:** Voice-to-text desktop app (Windows, cloud STT + LLM)
**Researched:** 2026-03-23
**Confidence:** HIGH (all major claims verified via official docs or multiple sources)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         MAIN PROCESS                             │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐ │
│  │  HotkeyListener│  │   TrayIcon     │  │  AppController     │ │
│  │  (pynput,      │  │  (pystray,     │  │  (orchestrates     │ │
│  │   background   │  │   main thread  │  │   state machine)   │ │
│  │   thread)      │  │   on Windows)  │  │                    │ │
│  └───────┬────────┘  └───────┬────────┘  └─────────┬──────────┘ │
│          │  hotkey event     │  menu action         │            │
│          └───────────────────┴──────────────────────┘            │
│                                    │                             │
│                         ┌──────────▼──────────┐                  │
│                         │    asyncio event     │                  │
│                         │    loop (thread)     │                  │
│                         └──────────┬──────────┘                  │
│              ┌──────────────────┬──┴───────────────┐             │
│              │                  │                  │             │
│   ┌──────────▼───────┐  ┌───────▼──────┐  ┌───────▼──────────┐  │
│   │  AudioRecorder   │  │  STTClient   │  │  LLMClient       │  │
│   │  (sounddevice,   │  │  (GCP STT V2 │  │  (Gemini Flash)  │  │
│   │  numpy arrays)   │  │   Chirp 2)   │  │                  │  │
│   └──────────┬───────┘  └───────┬──────┘  └───────┬──────────┘  │
│              │                  │                  │             │
│              └──────────────────┴──────────────────┘             │
│                                    │                             │
│                         ┌──────────▼──────────┐                  │
│                         │    PasteService      │                  │
│                         │  (pyperclip +        │                  │
│                         │   keyboard Ctrl+V)   │                  │
│                         └─────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| HotkeyListener | Global hotkey capture, start/stop recording events | pynput `GlobalHotKeys`, runs in daemon thread |
| TrayIcon | System tray icon, status icon swap, menu actions | pystray `Icon`, runs in thread on Windows (safe) |
| AppController | State machine (idle → recording → processing → idle), routes events between components | Python class with asyncio queue |
| AudioRecorder | Capture mic audio as numpy array, silence-aware buffering | sounddevice `InputStream`, 16kHz mono int16 |
| STTClient | Send audio to GCP STT V2, get raw transcript | `google-cloud-speech` v2 client, batch recognize |
| LLMClient | Clean up raw transcript via Gemini Flash | `google-generativeai` SDK, async call |
| PasteService | Write text to clipboard, send Ctrl+V to previously active window | pyperclip + pynput keyboard controller |

## Recommended Project Structure

```
voice_type/
├── main.py               # entry point — starts tray + asyncio loop
├── controller.py         # AppController — state machine, event routing
├── hotkey.py             # HotkeyListener — pynput wrapper
├── tray.py               # TrayIcon — pystray wrapper, icon images
├── audio.py              # AudioRecorder — sounddevice capture
├── stt.py                # STTClient — GCP Speech-to-Text V2
├── llm.py                # LLMClient — Gemini Flash cleanup
├── paste.py              # PasteService — clipboard + Ctrl+V
├── config.py             # Settings dataclass, load from env/.env
├── assets/
│   ├── idle.png          # tray icons (16x16 or 32x32)
│   ├── recording.png
│   └── processing.png
└── pyproject.toml
```

### Structure Rationale

- **One file per component:** Each file has a single clear purpose. Keeps files small (well under 700-line limit), easy to test in isolation.
- **main.py as thin wiring:** Only starts the three root objects (tray, asyncio loop, hotkey listener). No business logic.
- **assets/ for icons:** pystray uses PIL `Image` objects. Pre-rendered PNGs are simplest.
- **config.py:** Single place for GCP credentials path, hotkey binding, model IDs — no magic strings scattered around.

## Architectural Patterns

### Pattern 1: Thread-per-subsystem with asyncio core

**What:** Run blocking subsystems (tray, hotkey) in threads. Run async I/O (STT, LLM, clipboard) in a single asyncio event loop on a dedicated thread. Communicate via `asyncio.Queue` + `loop.call_soon_threadsafe()`.

**When to use:** When you have mixed blocking and async I/O concerns — which this app has exactly. pystray and pynput are blocking/callback-based; GCP clients are best used async.

**Trade-offs:** Correct approach for this use case. More complex than pure threading but avoids blocking GCP API calls. Pure asyncio would require thread executors for audio capture anyway.

**Example:**
```python
# main.py
import asyncio, threading
from voice_type.tray import TrayIcon
from voice_type.controller import AppController

async def main():
    controller = AppController()
    await controller.run()  # drives STT, LLM, paste pipeline

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    controller_thread = threading.Thread(
        target=loop.run_until_complete,
        args=(main(),),
        daemon=True
    )
    controller_thread.start()

    # pystray must own a thread; on Windows, any thread is fine
    tray = TrayIcon(event_callback=lambda e: loop.call_soon_threadsafe(controller.on_event, e))
    tray.run()  # blocks main thread — correct on Windows
```

### Pattern 2: State Machine for Recording Lifecycle

**What:** Explicit states — IDLE, RECORDING, PROCESSING — with guarded transitions. Prevents race conditions (e.g., two hotkey presses mid-process).

**When to use:** Any UI with async background work and user-initiated transitions. Essential here because hotkey can fire at any time.

**Trade-offs:** Small overhead to implement. Pays off immediately when debugging.

**Example:**
```python
from enum import Enum, auto

class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()

class AppController:
    def __init__(self):
        self._state = State.IDLE

    def on_hotkey(self):
        if self._state == State.IDLE:
            self._start_recording()
        elif self._state == State.RECORDING:
            self._stop_and_process()
        # PROCESSING: ignore hotkey — already busy
```

### Pattern 3: Batch STT over Streaming

**What:** Record the full utterance into a buffer, then send a single Recognize request. Do not use StreamingRecognize.

**When to use:** Push-to-talk model (press to start, release/press to stop). The user stops speaking before transcription begins — no need for real-time partial results.

**Trade-offs:** Adds latency equal to network RTT (typically 200-600ms). But simpler: no streaming state, no partial result merging, no reconnection logic. For under-2s total latency goal this is fine — STT latency on a 5-10s clip is ~300ms, Gemini Flash is ~400ms, leaving margin.

## Data Flow

### Primary Flow: Hotkey → Text in Window

```
[User presses hotkey]
        ↓
HotkeyListener.on_activate()
        ↓  (call_soon_threadsafe)
AppController.on_event(HOTKEY_PRESS)
        ↓  state: IDLE → RECORDING
AudioRecorder.start() — sounddevice opens InputStream, chunks go into buffer
        ↓
[User presses hotkey again]
        ↓
AppController.on_event(HOTKEY_PRESS)
        ↓  state: RECORDING → PROCESSING
AudioRecorder.stop() → returns numpy array
        ↓  encode to LINEAR16 bytes
STTClient.recognize(audio_bytes) → raw_text   [~200-500ms, GCP batch]
        ↓
LLMClient.clean(raw_text) → clean_text        [~300-500ms, Gemini Flash]
        ↓
PasteService.paste(clean_text)
    1. pyperclip.copy(clean_text)
    2. pynput keyboard.press(Ctrl+V)            [<50ms]
        ↓
[Text appears in previously active window]
        ↓  state: PROCESSING → IDLE
TrayIcon.set_icon(idle)
```

### Tray Icon State Sync

```
AppController.state changes
        ↓  (direct call, tray object ref)
TrayIcon.update_icon(state)
        ↓
pystray Icon.icon = PIL.Image (idle/recording/processing png)
```

### Error Flow

```
Any await raises exception
        ↓
AppController catches, logs
        ↓
state → IDLE (reset, don't hang)
        ↓
TrayIcon shows idle icon
        ↓
(Optional: tray notification via icon.notify())
```

## Key Data Decisions

### Audio Format

Use 16kHz, mono, int16 (LINEAR16). This is:
- What GCP STT expects natively (no transcoding needed)
- What sounddevice can capture directly (`dtype='int16'`, `samplerate=16000`, `channels=1`)
- Smallest possible payload for network upload

Do **not** use float32 or stereo — doubles payload size for no benefit.

### Active Window Tracking

**Problem:** After calling `pyperclip.copy()` + `keyboard.send('ctrl+v')`, the focus may have shifted to VoiceType's own process.

**Solution:** Before starting recording, capture the foreground window handle using `ctypes.windll.user32.GetForegroundWindow()`. After processing, restore focus before sending Ctrl+V.

```python
import ctypes

def capture_active_window() -> int:
    return ctypes.windll.user32.GetForegroundWindow()

def restore_and_paste(hwnd: int, text: str):
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    pyperclip.copy(text)
    # small sleep needed — SetForegroundWindow is async
    time.sleep(0.05)
    keyboard_controller.press(Key.ctrl)
    keyboard_controller.press('v')
    keyboard_controller.release('v')
    keyboard_controller.release(Key.ctrl)
```

Note: `SetForegroundWindow` has Windows restrictions — it only works reliably if the calling process is the foreground process or has `FOREGROUND_LOCK_TIMEOUT` elapsed. Capturing the HWND at hotkey-press time (while the original app is still foreground) sidesteps this.

## Suggested Build Order

Dependencies between components determine order:

1. **config.py + assets/** — zero deps, needed by everything
2. **audio.py** — no external deps beyond sounddevice, testable standalone (record to file)
3. **stt.py** — depends on audio format from step 2, testable with a WAV file
4. **llm.py** — independent of audio/STT, testable with hardcoded strings
5. **paste.py** — independent, testable by running in any text editor
6. **controller.py** — wires steps 2-5 together with state machine
7. **hotkey.py + tray.py** — UI shell around controller
8. **main.py** — final wiring of all threads

This order means each phase produces a working, testable artifact before the next begins. MVP = steps 1-6 with a test harness instead of hotkey/tray.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| GCP Speech-to-Text V2 | `google-cloud-speech` Python SDK, batch `recognize()` | Auth via `GOOGLE_APPLICATION_CREDENTIALS` env var pointing to service account JSON |
| Gemini Flash | `google-generativeai` SDK, `generate_content_async()` | Same GCP project, API key or service account |
| System clipboard | pyperclip (cross-platform, no pywin32 dep) | Falls back to `xclip`/`xsel` on Linux but irrelevant here |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| HotkeyListener → AppController | `loop.call_soon_threadsafe(queue.put_nowait, event)` | Thread-safe bridge from pynput thread to asyncio loop |
| TrayIcon → AppController | Same call_soon_threadsafe pattern | Menu actions (quit, open settings) |
| AppController → TrayIcon | Direct method call on tray object | Controller holds tray ref; tray update is non-blocking |
| AudioRecorder → Controller | Returns complete numpy array (sync) | Recording is blocking within its own thread via asyncio.to_thread |

## Anti-Patterns

### Anti-Pattern 1: Blocking asyncio loop with audio I/O

**What people do:** Call `sounddevice.rec()` directly inside `async def`.
**Why it's wrong:** Blocks the event loop for the duration of recording. STT and LLM calls can't fire during that time.
**Do this instead:** Use `asyncio.to_thread(recorder.record_sync)` — sounddevice is I/O-bound but not awaitable natively.

### Anti-Pattern 2: Using StreamingRecognize for push-to-talk

**What people do:** Open a streaming STT session and pipe audio chunks as they come in.
**Why it's wrong:** StreamingRecognize adds connection management complexity (reconnect on timeout, partial result handling). For push-to-talk with a fixed endpoint, you have the full audio before you need the transcript.
**Do this instead:** Batch `recognize()` — simpler, same accuracy for Chirp 2, adequate latency for < 2s goal.

### Anti-Pattern 3: Saving clipboard to restore it

**What people do:** Read clipboard before paste, write text, send Ctrl+V, restore original clipboard.
**Why it's wrong:** Clipboard operations have race conditions with other apps. Users find clipboard restoration surprising when it fails.
**Do this instead:** Accept overwriting clipboard. This is what Superwhisper and most voice tools do. Document it as known behavior. If it matters in v2, add a setting.

### Anti-Pattern 4: pystray `run()` on main thread with asyncio on main thread

**What people do:** Try to run both `asyncio.run()` and `tray.run()` on the main thread.
**Why it's wrong:** Both are blocking. One will never start.
**Do this instead:** On Windows, pystray is safe to run in a non-main thread. Run asyncio loop on main thread OR run tray on main thread and asyncio in a thread. Either works; pick one consistently.

## Scaling Considerations

This is a single-user desktop tool. "Scaling" means handling longer audio and faster iteration:

| Concern | Now (MVP) | If Needed Later |
|---------|-----------|-----------------|
| Long recordings (>30s) | GCP batch limit is 60s synchronous | Switch to BatchRecognize for async long-form |
| Startup time | Import all deps at start | Lazy-load STT/LLM clients on first use |
| Offline fallback | Not in scope | Add local Whisper.cpp as optional engine |
| Settings persistence | Hard-coded config | SQLite or JSON settings file |

## Sources

- [pynput GlobalHotKeys docs](https://pynput.readthedocs.io/en/latest/keyboard.html) — HIGH confidence
- [pystray usage and threading FAQ](https://pystray.readthedocs.io/en/latest/faq.html) — HIGH confidence (official docs)
- [sounddevice docs v0.5.3](https://python-sounddevice.readthedocs.io/) — HIGH confidence
- [GCP Speech-to-Text V2 Chirp 2 model page](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2) — HIGH confidence
- [win32gui SetForegroundWindow docs](https://timgolden.me.uk/pywin32-docs/win32gui__SetForegroundWindow_meth.html) — HIGH confidence
- [pywin32 clipboard module](https://timgolden.me.uk/pywin32-docs/win32clipboard.html) — HIGH confidence
- Community pattern: asyncio.to_thread for sounddevice — MEDIUM confidence (no single authoritative source, but standard Python asyncio guidance)

---
*Architecture research for: voice-to-text desktop app (Windows 11, Python, GCP)*
*Researched: 2026-03-23*
