# Stack Research

**Domain:** Voice-to-text desktop app, Windows 11, Python
**Researched:** 2026-03-23
**Confidence:** HIGH (all versions verified from PyPI / official docs)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12+ | Runtime | Project constraint. 3.12 is the current stable with best perf for asyncio. |
| uv | latest | Dependency management | Project constraint. Fastest resolver, compatible with pyproject.toml. |
| sounddevice | 0.5.5 | Microphone capture | PortAudio bindings that return NumPy arrays — easiest to feed directly to cloud STT. No binary wheel pain unlike PyAudio. Released 2026-01-23. |
| pynput | 1.8.1 | Global hotkeys | Active (released 2025-03-17). `GlobalHotKeys` class handles combos cleanly. Supports `win32_event_filter` for key suppression on Windows. The only well-maintained cross-platform keyboard listener for Python. |
| pystray | 0.19.5 | System tray icon | De facto standard for Python system tray on Windows. No dependencies beyond Pillow. Last release 2023-09-17 — but the Windows WINAPI backend is stable and doesn't need updates. |
| Pillow | 12.1.1 | Tray icon rendering | Required by pystray for icon images. Latest release 2026-02-11. Use to draw colored circles for idle/recording/processing states. |
| pywin32 | 311 | Clipboard write + paste simulation | Native Windows clipboard access via `win32clipboard` and Ctrl+V simulation via `win32api.keybd_event`. More reliable than pyautogui for Unicode (Russian) text. Released 2025-07-14. |
| google-cloud-speech | 2.37.0 | Speech-to-Text V2 | Official Google client. V2 API is required for Chirp 2. Import via `google.cloud.speech_v2`. Released 2026-02-27. |
| google-genai | 1.68.0 | Gemini Flash text cleanup | New official SDK (replaces dead `google-generativeai`). Supports `gemini-2.5-flash` model. GA since May 2025. Released 2026-03-18. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | >=1.24 | Audio buffer handling | Needed alongside sounddevice — STT API expects bytes, numpy array needs `.tobytes()` conversion. |
| google-auth | latest (transitive) | GCP credentials | Auto-installed with google-cloud-speech. Use Application Default Credentials via `gcloud auth application-default login`. |
| loguru | >=0.7 | Logging | Simpler than stdlib logging for a personal tool. Single-line setup, colored output, file rotation. |
| python-dotenv | >=1.0 | Env config | API keys, GCP project ID, hotkey config in `.env`. Keep out of source. |
| asyncio (stdlib) | — | Pipeline concurrency | Run STT and Gemini calls concurrently to hit <2s target. No extra install needed. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pyright (strict) | Type checking | Project convention per CLAUDE.md. Catches pynput callback signature issues early. |
| ruff | Linting + formatting | Project convention. |
| pytest | Tests | Unit-testable parts: text cleanup prompt, audio byte conversion, tray state machine. |

---

## Installation

```bash
# Core runtime
uv add sounddevice numpy pynput pystray Pillow pywin32
uv add google-cloud-speech google-genai
uv add loguru python-dotenv

# Dev
uv add --dev pyright ruff pytest
```

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| sounddevice | PyAudio | PyAudio requires pre-compiled PortAudio binaries, frequent wheel breakage on Python 3.12+. sounddevice wraps same PortAudio but ships its own wheel cleanly. |
| sounddevice | SoundCard (WASAPI) | SoundCard is lower-level WASAPI — better for exclusive mode audio, overkill here. WASAPI exclusive mode can block other apps from using the mic. |
| pynput | keyboard (0.13.5) | `keyboard` library last released 2020-03-23. Abandonware. Requires admin on some Windows configs. Not safe for new projects. |
| pywin32 for paste | pyautogui | pyautogui's `hotkey('ctrl','v')` works but adds 200ms+ delay and sometimes fails with Unicode characters in non-Latin apps. pywin32 is lower-latency and handles Russian text reliably. |
| pywin32 for paste | pyperclip + pynput | pyperclip handles clipboard writes but not paste simulation. Still need pywin32 for the keybd_event. Adding pyperclip is redundant. |
| google-genai | google-generativeai | `google-generativeai` reached EOL on 2025-11-30. No new features, critical fixes only. Migrate to `google-genai`. |
| pystray | Qt/wx tray | Qt (PySide6) and wx system tray work but pull in 50-100MB of GUI framework. pystray is 50KB. For a tray-only app, that's absurd overhead. |
| asyncio | threading | Threading works but asyncio's `gather()` makes the STT + Gemini parallel call pattern cleaner. sounddevice callbacks are sync but audio collection is fast — no blocker. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `keyboard` (PyPI) | Last release 2020. Uses undocumented Windows driver hooks on some setups, requires admin rights, breaks on Windows 11 updates. | `pynput` 1.8.1 |
| `google-generativeai` | EOL since Nov 2025. No new models, no gemini-2.5-flash support. | `google-genai` |
| `SpeechRecognition` (PyPI) | Wraps Google STT V1 (deprecated). No V2/Chirp 2 support. | `google-cloud-speech` with `speech_v2` |
| `pyaudio` | Binary wheel breaks frequently with new Python versions. PortAudio DLL must be present on Windows. `uv` can't guarantee DLL install. | `sounddevice` |
| `win32com.client.Dispatch("WScript.Shell").SendKeys` | Notoriously unreliable — SendKeys fires into whatever window has focus at the moment of the call, with no guarantee of timing. | `win32api.keybd_event` after explicit clipboard write |
| `gemini-2.0-flash-001` | As of 2026-03-06, unavailable for new GCP projects. Only existing customers retain access. | `gemini-2.5-flash` (current default) |

---

## Stack Patterns by Variant

**For the hotkey: push-to-talk (hold to record, release to stop):**
- Use `pynput.keyboard.Listener` with `on_press` / `on_release` callbacks
- Track a boolean `recording` flag, start/stop sounddevice stream on transitions
- Do not use `GlobalHotKeys` for this — it fires on press only, not release

**For the hotkey: toggle (press once to start, press again to stop):**
- Use `pynput.keyboard.GlobalHotKeys` with a single combo mapped to a toggle callback
- Simpler state machine, but user must remember to press again to stop

**Recommended: toggle mode.** Push-to-talk requires holding a key while speaking, which is awkward for long dictation. Toggle fits the Superwhisper UX.

**For tray icon state changes (idle / recording / processing):**
- Pre-generate 3 Pillow images at startup (green circle, red circle, yellow circle)
- Call `icon.icon = new_image` to swap — pystray updates the tray immediately
- Do not regenerate images on every state change — it's slow

**For the STT + Gemini pipeline to hit <2s:**
- Record into a numpy buffer (sounddevice `InputStream` with callback)
- On stop: convert buffer to `bytes`, fire `asyncio.gather(stt_call, ...)` — but STT must complete before Gemini (sequential, not parallel)
- Target: STT ~800ms (Chirp 2 regional endpoint), Gemini Flash ~400ms, paste ~50ms = ~1.25s total
- Use `us-central1` or `europe-west4` endpoints for Chirp 2 — latency is region-sensitive

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| sounddevice 0.5.5 | Python 3.7-3.13 | Ships PortAudio wheels for Windows. No extra DLL needed. |
| pynput 1.8.1 | Python 3.8+ | Requires `pyobjc` on macOS (not our problem). Windows backend is pure Win32 API. |
| pystray 0.19.5 | Pillow 9.x-12.x | pystray updated image flags for Pillow compatibility in this release. |
| google-cloud-speech 2.37.0 | Python 3.7-3.14 | V2 API (`speech_v2` module) is distinct from V1 (`speech` module) — different import paths. |
| google-genai 1.68.0 | Python 3.10+ | Note: requires Python 3.10 minimum — bump project minimum from 3.7 if needed. |
| pywin32 311 | Python 3.8-3.14 | Windows-only. Will cause import errors on other platforms — guard with `sys.platform`. |

---

## Sources

- PyPI: sounddevice 0.5.5 — version/date verified directly
- PyPI: pynput 1.8.1 — version/date verified directly
- PyPI: pystray 0.19.5 — version/date verified directly
- PyPI: google-cloud-speech 2.37.0 — version/date verified directly
- PyPI: google-genai 1.68.0 — version/date verified directly (replaces google-generativeai)
- PyPI: pywin32 311 — version/date verified directly
- PyPI: Pillow 12.1.1 — version/date verified directly
- PyPI: keyboard 0.13.5 — confirmed last release 2020, classified as abandonware
- [Google Cloud Chirp 2 docs](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2) — V2 API confirmed, model name `chirp_2`, regional availability
- [google-generativeai EOL announcement](https://github.com/googleapis/python-genai) — confirmed EOL Nov 2025
- [push-to-talk reference project](https://github.com/yixin0829/push-to-talk) — real-world Python voice dictation, confirmed pynput + pyaudio pattern
- [pynput GlobalHotKeys docs](https://pynput.readthedocs.io/en/latest/keyboard.html) — suppression via win32_event_filter confirmed

---
*Stack research for: VoiceType — Windows voice-to-text desktop app*
*Researched: 2026-03-23*
