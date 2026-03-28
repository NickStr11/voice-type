# Roadmap: VoiceType

## Overview

VoiceType ships in two phases. Phase 1 establishes the project scaffold and the recording subsystem — microphone works, hotkey works, audio captured, active window tracked. Phase 2 completes the full pipeline: audio flows through STT, then LLM cleanup, then pastes into the saved window, with tray icon reflecting state throughout. After Phase 2, the core value is delivered: press a key, speak, get clean bilingual text in the active window.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - Project scaffold, hotkey + audio capture, active window tracking, config (completed 2026-03-23)
- [x] **Phase 2: Live Pipeline** - STT + LLM cleanup + paste + tray feedback — full loop end-to-end (completed 2026-03-23)

## Phase Details

### Phase 1: Foundation
**Goal**: The recording infrastructure is working — user can trigger a hotkey, audio is captured at correct spec, active window is saved, and the app starts with sane configuration and a mic check.
**Depends on**: Nothing (first phase)
**Requirements**: SYS-02, SYS-03, REC-01, REC-02, REC-04
**Success Criteria** (what must be TRUE):
  1. App starts, checks microphone access, and surfaces a clear error if mic is unavailable
  2. Global hotkey (configurable via config file) toggles recording on/off without consuming other keypresses
  3. Audio is captured at 16kHz mono int16 while hotkey is active
  4. Active window handle is captured at hotkey-release (not at paste time)
  5. Config file controls hotkey and GCP credentials path; app fails clearly if credentials are missing
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md — Project scaffold: pyproject.toml deps + AppConfig dataclass with .env validation
- [x] 01-02-PLAN.md — AudioRecorder (16kHz mono int16) + microphone permission check
- [x] 01-03-PLAN.md — HotkeyListener (pynput GlobalHotKeys, no suppress) + window HWND capture
- [x] 01-04-PLAN.md — AppController state machine + main.py entry point wiring all components

### Phase 2: Live Pipeline
**Goal**: The full pipeline runs end-to-end — recorded audio is transcribed via Chirp 2, cleaned by Gemini Flash, and pasted into the saved active window, while the tray icon reflects idle/recording/processing state throughout.
**Depends on**: Phase 1
**Requirements**: STT-01, STT-02, STT-03, LLM-01, LLM-02, PST-01, PST-02, SYS-01, REC-03
**Success Criteria** (what must be TRUE):
  1. After stopping recording, clean text appears in the originally active window within 2 seconds
  2. Russian and English are auto-detected and transcribed correctly without manual language switching
  3. Gemini cleanup removes filler words and adds punctuation; raw STT text is used as fallback if LLM times out
  4. Tray icon shows distinct states for idle, recording, and processing — updates reflect real pipeline state
  5. Clipboard contents are preserved (restored after paste)
**Plans**: 3 plans

Plans:
- [ ] 02-01-PLAN.md — STTClient (Chirp 2 regional) + LLMClient (Gemini Flash with wall-clock timeout)
- [ ] 02-02-PLAN.md — PasteService (SetForegroundWindow + clipboard save/restore + Ctrl+V) + TrayIcon (3-state pystray)
- [ ] 02-03-PLAN.md — Wire pipeline into AppController + update main.py with tray startup

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 4/4 | Complete   | 2026-03-23 |
| 2. Live Pipeline | 3/3 | Complete   | 2026-03-23 |
| 3. Local Whisper STT | 1/2 | Executing | — |

### Phase 3: Local Whisper STT backend (faster-whisper large-v3) with provider selection in tray menu

**Goal:** Local Whisper STT backend works as an alternative to Google Cloud Chirp 3 — user selects provider from tray menu, recordings are transcribed locally via faster-whisper large-v3-turbo with auto language detection, and GCP credentials are no longer required when using local mode.
**Requirements**: STT-LOCAL-01, STT-LOCAL-02, STT-LOCAL-03, STT-LOCAL-04, PROV-01, PROV-02, TRAY-01, CONFIG-01
**Depends on:** Phase 2
**Plans:** 2 plans

Plans:
- [x] 03-01-PLAN.md — AppConfig extension (stt_provider, whisper_model, optional GCP) + WhisperSTTClient module
- [ ] 03-02-PLAN.md — Tray STT Provider submenu + controller provider delegation + main.py wiring
