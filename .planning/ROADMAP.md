# Roadmap: VoiceType

## Overview

VoiceType ships in two phases. Phase 1 establishes the project scaffold and the recording subsystem — microphone works, hotkey works, audio captured, active window tracked. Phase 2 completes the full pipeline: audio flows through STT, then LLM cleanup, then pastes into the saved window, with tray icon reflecting state throughout. After Phase 2, the core value is delivered: press a key, speak, get clean bilingual text in the active window.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Project scaffold, hotkey + audio capture, active window tracking, config
- [ ] **Phase 2: Live Pipeline** - STT + LLM cleanup + paste + tray feedback — full loop end-to-end

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
- [ ] 01-01-PLAN.md — Project scaffold: pyproject.toml deps + AppConfig dataclass with .env validation
- [ ] 01-02-PLAN.md — AudioRecorder (16kHz mono int16) + microphone permission check
- [ ] 01-03-PLAN.md — HotkeyListener (pynput GlobalHotKeys, no suppress) + window HWND capture
- [ ] 01-04-PLAN.md — AppController state machine + main.py entry point wiring all components

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
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/4 | Not started | - |
| 2. Live Pipeline | 0/TBD | Not started | - |
