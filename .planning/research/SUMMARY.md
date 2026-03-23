# Project Research Summary

**Project:** VoiceType — Windows voice-to-text desktop app
**Domain:** Push-to-talk dictation, cloud STT + LLM cleanup, system tray utility
**Researched:** 2026-03-23
**Confidence:** HIGH

## Executive Summary

VoiceType is a push-to-talk dictation tool for Windows: user presses a global hotkey, speaks, presses again, transcribed text appears in whatever window was active. This is a solved domain — Superwhisper, Wispr Flow, and open-source projects all demonstrate the same core pipeline: hotkey → audio capture → cloud STT → LLM cleanup → clipboard paste. The recommended approach follows this pipeline using GCP Chirp 2 (Speech-to-Text V2) for bilingual Russian+English auto-detection and Gemini 2.5 Flash for cleanup, connected via a thread-per-subsystem architecture with asyncio for I/O. The full stack is Python 3.12 + uv, matching project conventions.

The key differentiator over Windows Voice Typing (Win+H) is seamless Russian/English auto-detection without mode switching — Chirp 2 handles this natively with `language_codes: ["ru-RU", "en-US"]`. The key differentiator over paid tools (Superwhisper at $8.50/mo, Wispr Flow at $10-15/mo) is cost: free on GCP credits. The end-to-end latency target of under 2 seconds is achievable: Chirp 2 batch recognize ~300-500ms, Gemini Flash with thinking disabled ~400ms, paste ~50ms.

The main risks are threading and paste correctness, not API complexity. Eight critical pitfalls are documented — all hit Phase 1. The highest-risk items are: paste landing in the wrong window when focus shifts during processing (must capture window handle at hotkey-release, not at paste time), Gemini Flash hanging indefinitely without triggering timeouts (requires concurrent.futures wall-clock timeout), and pynput hotkey conflicts with system-reserved Win+key combinations (use Ctrl+Alt+key default, avoid Win+key). Every pitfall has a known fix; none require architectural rethinking if addressed from day one.

## Key Findings

### Recommended Stack

All versions verified from PyPI and official docs. The stack maps directly onto project conventions (Python 3.12+, uv, pyright strict, ruff).

**Core technologies:**
- `sounddevice 0.5.5`: mic capture as NumPy arrays — no binary wheel pain unlike PyAudio, ships PortAudio internally
- `pynput 1.8.1`: global hotkeys — only well-maintained cross-platform keyboard listener; use `GlobalHotKeys` for toggle mode
- `pystray 0.19.5` + `Pillow 12.1.1`: system tray icon with state images — run via `run_detached()` to avoid main-thread deadlock
- `pywin32 311`: clipboard write + paste simulation — more reliable than pyautogui for Unicode/Russian text, also needed for `GetForegroundWindow`/`SetForegroundWindow`
- `google-cloud-speech 2.37.0`: GCP STT V2 client — import via `speech_v2`, NOT `speech` (different modules)
- `google-genai 1.68.0`: Gemini Flash cleanup — replaces EOL `google-generativeai`; supports `gemini-2.5-flash`

**Critical version notes:**
- `google-genai` requires Python 3.10+ minimum
- `google-generativeai` reached EOL Nov 2025 — do not use
- `gemini-2.0-flash-001` unavailable for new GCP projects — use `gemini-2.5-flash`
- Chirp 2 requires explicit regional endpoint (`us-central1-speech.googleapis.com`) — global endpoint does not support V2

### Expected Features

Competitor analysis covers Superwhisper, Wispr Flow, WhisperTyping, Windows Voice Typing. Full matrix in FEATURES.md.

**Must have (table stakes):**
- Global hotkey (toggle mode recommended over push-to-talk hold) — without this, app is unusable
- Auto-paste into active window via clipboard — core value delivery
- Chirp 2 bilingual Russian+English auto-detect — primary differentiator vs Win+H
- Gemini Flash cleanup (filler words, punctuation) — raw Chirp 2 output is not acceptable
- System tray icon with 3 states (idle/recording/processing) — without feedback app feels broken
- Audio cues on start/stop — low effort, high UX impact
- Configurable hotkey via config file — hardcoded hotkey is a dealbreaker

**Should have (v1.x, after core loop validated):**
- Transcription history panel (SQLite) — trigger: happens 3+ times that user wants to re-use output
- Custom LLM modes (3 named system prompt presets) — zero extra architecture cost once LLM call exists
- Floating overlay near cursor — tray icon feels too far from work area
- Voice shortcuts / text expansion — high utility, minimal code (string replacement map)
- Silent mode toggle — needed for non-home contexts

**Defer (v2+):**
- Full settings UI window — JSON config is fine for personal tool
- Offline Whisper.cpp fallback — defer until GCP credits run out
- Per-mode hotkey variants — single hotkey + tray menu covers the need

**Anti-features (do not build):**
- Real-time streaming transcription — complexity explodes, fast batch achieves same perceived speed
- Per-app automatic mode switching via screenshots — privacy nightmare, Wispr Flow users complain about it
- Voice commands for editing — scope creep, different product category
- Always-on wake word — mic always on, CPU cost, privacy red flag

### Architecture Approach

Single-process app, thread-per-subsystem model with asyncio for I/O. Three concurrent threads: pystray tray icon (run via `run_detached()`), pynput hotkey listener (daemon thread), asyncio event loop (drives STT + LLM + paste pipeline). Cross-thread communication via `loop.call_soon_threadsafe()` + asyncio Queue. State machine with explicit IDLE/RECORDING/PROCESSING states guards against race conditions from rapid hotkey presses.

**Major components:**
1. `HotkeyListener` (hotkey.py) — pynput GlobalHotKeys, fires events into asyncio queue via thread-safe bridge
2. `TrayIcon` (tray.py) — pystray wrapper, pre-renders 3 Pillow images at startup, swaps on state change
3. `AppController` (controller.py) — state machine, orchestrates recording → STT → LLM → paste pipeline
4. `AudioRecorder` (audio.py) — sounddevice InputStream at 16kHz mono int16, collects numpy buffer
5. `STTClient` (stt.py) — GCP Speech-to-Text V2 batch recognize, Chirp 2, `us-central1` regional endpoint
6. `LLMClient` (llm.py) — Gemini Flash via google-genai, thinking disabled, 8s wall-clock timeout
7. `PasteService` (paste.py) — captures HWND at recording stop, restores focus before Ctrl+V, saves/restores clipboard

**Build order matches dependency graph:** config → audio → stt → llm → paste → controller → hotkey+tray → main

### Critical Pitfalls

All 8 pitfalls are Phase 1 items. All have known fixes. Retrofitting is painful — must address from day one.

1. **Paste lands in wrong window** — capture `GetForegroundWindow()` hwnd at hotkey-release, restore with `SetForegroundWindow(hwnd)` + 50ms sleep before Ctrl+V; if window gone, surface tray notification
2. **Gemini Flash hangs indefinitely** — confirmed active bug: socket stays open without error; wrap every call with `concurrent.futures` Future with `result(timeout=8)`; disable thinking via `thinking_budget: 0`; fallback: paste raw STT output on timeout
3. **Chirp 2 wrong/global endpoint** — always use `ClientOptions(api_endpoint="us-central1-speech.googleapis.com")`; global endpoint silently fails or routes to V1
4. **pynput suppress trap** — `suppress=True` freezes all OS keyboard input; use `win32_event_filter` for selective suppression; Win+key combinations intercepted by Windows shell before pynput hook
5. **Windows microphone permission silent crash** — PortAudio returns `-9999` with no explanation; add first-launch permission check via 0.1s test stream; surface actionable tray notification
6. **Clipboard clobbering** — save clipboard before paste with `pyperclip.paste()`, restore after 100ms delay; skip restoration for rich content, notify via tray
7. **Audio device channels crash** — always `channels=1`; stereo fails on mono-only mics with `PortAudioError -9998`
8. **pystray main-thread deadlock** — use `Icon.run_detached()`, not `Icon.run()` on main thread alongside asyncio

## Implications for Roadmap

All research points to a single critical dependency chain: the core paste pipeline must work correctly before any other feature is useful. Architecture is straightforward once threading model is established. Features naturally layer on top of the working pipeline.

### Phase 1: Foundation and Core Pipeline

**Rationale:** Every other feature depends on this working correctly. Eight pitfalls all land here — must be built right from the start. This is the hardest phase architecturally despite being the smallest in features.
**Delivers:** Working app — press hotkey, speak, text appears in active window. System tray icon shows states. Audio feedback on start/stop.
**Addresses:** All P1 features (global hotkey, bilingual Chirp 2, Gemini cleanup, auto-paste, tray icon states, audio cues, configurable hotkey)
**Avoids:** All 8 critical pitfalls — threading model, window focus capture, Gemini timeout, regional endpoint, mic permissions, clipboard restore, mono audio, suppress trap

### Phase 2: Polish and Daily-Use Features

**Rationale:** Once core pipeline is validated through daily use, pain points become clear. SQLite is the only new dependency; all other features (LLM modes, voice shortcuts) layer onto existing components at near-zero architectural cost.
**Delivers:** Transcription history panel, 3 named LLM mode presets, voice shortcuts / text expansion, floating overlay near cursor, silent mode toggle
**Uses:** SQLite (new), existing LLM client (modes = different system prompts), existing paste pipeline (shortcuts = pre-paste string replacement)
**Implements:** v1.x feature set from FEATURES.md

### Phase 3: Settings and Distribution

**Rationale:** Personal tool doesn't need a UI until config file creates real friction. Packaging (PyInstaller or similar) is a distinct effort with its own pitfalls (resource paths in onefile mode). Defer until product is stable.
**Delivers:** Settings UI window, proper packaging/installer, microphone device selection
**Avoids:** PyInstaller onefile resource path issues (documented in PITFALLS sources)

### Phase Ordering Rationale

- Architecture research explicitly provides a build order (config → audio → stt → llm → paste → controller → hotkey+tray → main) that maps directly to Phase 1 sequencing
- FEATURES.md dependency graph confirms pipeline is a chain — no feature can bypass it
- PITFALLS.md maps all 8 critical pitfalls to "Phase 1" explicitly — confirms concentration of risk in first phase
- Phase 2 features are explicitly gated on "trigger conditions" in FEATURES.md (e.g., transcription history: "happens 3+ times that user wants it")
- Phase 3 (packaging) is a known separate effort category with distinct failure modes

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (packaging):** PyInstaller onefile with pywin32 + pynput + sounddevice is known to have resource path issues; research before committing to distribution approach

Phases with standard patterns (skip research-phase):
- **Phase 1:** Architecture is well-documented (official pynput/pystray/sounddevice docs, GCP STT V2 docs); pitfalls are enumerated with confirmed fixes from issue trackers
- **Phase 2:** SQLite is trivial; LLM mode presets are just system prompt strings; no unknowns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified from PyPI; alternatives explicitly ruled out with documented reasons |
| Features | HIGH | 5 competitor products analyzed; feature matrix covers market; competitor source quality is good |
| Architecture | HIGH | All major patterns from official docs; threading model confirmed against pystray/pynput official FAQs |
| Pitfalls | HIGH | 7 of 8 pitfalls backed by GitHub issues or production bug reports; 1 (clipboard clobber) is inference from common patterns |

**Overall confidence:** HIGH

### Gaps to Address

- **GCP cost per use:** Research notes "document cost per use for user awareness" but doesn't quantify. Check Chirp 2 + Gemini Flash pricing before first use at scale; both have generous free tiers for personal use.
- **Gemini timeout value (8s):** Chosen as reasonable default; actual production tuning needed. May need adjustment based on observed p95 latency in practice.
- **SetForegroundWindow reliability:** Research notes Windows restrictions on when it works; edge cases (elevated privilege apps, UAC dialogs, exclusive fullscreen games) may not be fixable without matching privilege level. Document as known limitation.
- **Packaging approach:** Phase 3 approach (PyInstaller vs nuitka vs direct uv run) not researched; defer until needed.

## Sources

### Primary (HIGH confidence)
- PyPI release pages: sounddevice 0.5.5, pynput 1.8.1, pystray 0.19.5, google-cloud-speech 2.37.0, google-genai 1.68.0, pywin32 311, Pillow 12.1.1
- [GCP Speech-to-Text V2 / Chirp 2 docs](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2) — model name, regional availability, language_codes parameter
- [pynput GlobalHotKeys docs](https://pynput.readthedocs.io/en/latest/keyboard.html) — threading model, suppress behavior
- [pystray docs + threading FAQ](https://pystray.readthedocs.io/en/latest/faq.html) — run_detached, Windows threading
- [sounddevice docs v0.5.3](https://python-sounddevice.readthedocs.io/) — InputStream, dtype, channels
- [google-generativeai EOL](https://github.com/googleapis/python-genai) — confirmed EOL Nov 2025
- [pywin32 SetForegroundWindow docs](https://timgolden.me.uk/pywin32-docs/win32gui__SetForegroundWindow_meth.html)

### Secondary (MEDIUM confidence)
- [Gemini python-genai socket stall bug](https://github.com/googleapis/python-genai/issues/1893) — indefinite hang confirmed in issue tracker
- [Chirp 2 latency/region issue](https://github.com/livekit/agents/issues/4417) — us-central1 latency confirmed via third-party reports
- [pynput suppress bug](https://github.com/moses-palmer/pynput/issues/232) — global suppress freezes keyboard
- [pystray threading](https://github.com/moses-palmer/pystray/issues/94) — run() blocking, run_detached workaround
- [Superwhisper Windows paste failures](https://feedback.superwhisper.com/board/p/windows-version) — production evidence
- [push-to-talk reference project](https://github.com/yixin0829/push-to-talk) — real-world pynput + sounddevice pattern
- Competitor analysis: Superwhisper, Wispr Flow, WhisperTyping, Voibe, Windows Voice Typing

### Tertiary (LOW confidence)
- `asyncio.to_thread` for sounddevice — standard Python asyncio guidance, no single authoritative source for this specific combination

---
*Research completed: 2026-03-23*
*Ready for roadmap: yes*
