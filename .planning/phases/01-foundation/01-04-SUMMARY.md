---
phase: 01-foundation
plan: "04"
subsystem: infra
tags: [asyncio, pynput, sounddevice, state-machine, hotkey, audio, window-capture]

# Dependency graph
requires:
  - phase: 01-foundation/01-02
    provides: AudioRecorder (16kHz mono int16), check_microphone_access, MicrophoneError
  - phase: 01-foundation/01-03
    provides: HotkeyListener (pynput GlobalHotKeys, no suppress), capture_active_window (ctypes HWND)
  - phase: 01-foundation/01-01
    provides: AppConfig frozen dataclass, load_config (exits 1 on bad config)
provides:
  - AppController state machine (IDLE/RECORDING/PROCESSING) in voice_type/controller.py
  - Entry point main() in voice_type/main.py that wires config + mic check + controller
  - Thread-safe hotkey dispatch via loop.call_soon_threadsafe from pynput thread to asyncio
  - Runnable app: uv run python -m voice_type.main starts, hotkey toggles recording, clean Ctrl+C exit
affects:
  - phase: 02-live-pipeline (extends _process() with STT + LLM + paste)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "State machine: IDLE -> RECORDING -> PROCESSING -> IDLE with guard on PROCESSING (hotkey ignored)"
    - "Thread-safe bridge: loop.call_soon_threadsafe() from pynput thread to asyncio queue"
    - "Async recorder: asyncio.to_thread() for AudioRecorder.start() and stop() (non-blocking event loop)"
    - "HWND capture at stop time: capture_active_window() called immediately on RECORDING->PROCESSING transition"
    - "Phase 2 stub: _process() logs stub message where STT+LLM+paste will plug in"

key-files:
  created:
    - voice_type/controller.py
    - voice_type/main.py
  modified: []

key-decisions:
  - "AppController owns the asyncio event loop reference — passed in from main() so loop lifecycle is clear"
  - "Queue-based event dispatch (asyncio.Queue) instead of direct coroutine calls — cleanly separates pynput thread from asyncio"
  - "HWND captured at RECORDING->PROCESSING boundary, before async recorder.stop() — guarantees original window identity even if user switches apps during stop"

patterns-established:
  - "Pattern: State machine enum + asyncio.Queue for event dispatch — extend in Phase 2 by replacing _process() stub"
  - "Pattern: All blocking I/O (recorder.start, recorder.stop) wrapped in asyncio.to_thread"

requirements-completed: [SYS-02, SYS-03, REC-01, REC-02, REC-04]

# Metrics
duration: ~15min
completed: "2026-03-23"
---

# Phase 01 Plan 04: AppController + main.py Summary

**IDLE/RECORDING/PROCESSING state machine wired to AudioRecorder + pynput hotkey + ctypes HWND capture, with asyncio event loop entry point and clean Ctrl+C shutdown**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-23T15:00:00Z
- **Completed:** 2026-03-23T15:21:32Z
- **Tasks:** 2 auto + 1 checkpoint (human-verify, approved)
- **Files modified:** 2

## Accomplishments

- AppController state machine: IDLE/RECORDING/PROCESSING with PROCESSING guard preventing double-hotkey during pipeline
- Thread-safe hotkey dispatch: pynput listener thread bridges to asyncio via loop.call_soon_threadsafe + asyncio.Queue
- Full startup sequence: load_config -> check_microphone_access -> controller -> hotkey listener -> asyncio loop
- End-to-end verified by user: 6/6 tests passed including recording toggle, HWND capture (19467058), audio (7.96s / 254592 bytes), clean shutdown

## Task Commits

1. **Task 1: AppController state machine** - `ba4786d` (feat)
2. **Task 2: main.py entry point** - `dc47ab7` (feat)
3. **Task 3: Human-verify checkpoint** - approved, no files modified

## Files Created/Modified

- `voice_type/controller.py` - AppController (IDLE/RECORDING/PROCESSING), thread-safe hotkey dispatch, HWND capture at stop time, Phase 2 stub in _process()
- `voice_type/main.py` - Entry point: load_config, check_microphone_access, AppController, asyncio event loop, KeyboardInterrupt handler

## Decisions Made

- AppController receives the event loop as a constructor argument — main() owns loop creation, controller doesn't create its own
- asyncio.Queue as event bus between pynput thread and controller coroutines — cleaner than direct callbacks, enables future "shutdown" event injection
- HWND captured before await asyncio.to_thread(recorder.stop) — guarantees original foreground window captured even if user switches during stop

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. GCP credentials + .env already covered in Plan 01-01.

## Next Phase Readiness

- All Phase 1 requirements satisfied: SYS-02, SYS-03, REC-01, REC-02, REC-04
- Phase 2 plug-in point: replace `_process()` stub in controller.py with STT (Chirp 2) + LLM (Gemini Flash) + paste (SetForegroundWindow + SendInput)
- Known concern: Gemini Flash socket stall bug requires concurrent.futures wall-clock timeout in Phase 2
- Known limitation: SetForegroundWindow may fail for elevated apps / UAC dialogs — document as known limitation in Phase 2

---
*Phase: 01-foundation*
*Completed: 2026-03-23*
