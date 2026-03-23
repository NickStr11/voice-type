# Requirements: VoiceType

**Defined:** 2026-03-23
**Core Value:** Press a key, speak, get clean text in the active window — as fast as Superwhisper

## v1 Requirements

### Recording

- [ ] **REC-01**: Global hotkey toggles recording start/stop
- [ ] **REC-02**: Audio captured via sounddevice at 16kHz mono int16 (LINEAR16)
- [ ] **REC-03**: System tray icon changes state during recording
- [ ] **REC-04**: Active window hwnd captured at recording stop (before processing)

### Transcription

- [ ] **STT-01**: Audio sent to Google Cloud STT V2 (Chirp 2) batch recognize
- [ ] **STT-02**: Russian and English auto-detected without manual language switching
- [ ] **STT-03**: Regional endpoint (us-central1-speech.googleapis.com) for minimum latency

### Cleanup

- [ ] **LLM-01**: Transcribed text cleaned via Gemini Flash (punctuation, grammar, filler removal)
- [ ] **LLM-02**: Wall-clock timeout on LLM call with fallback to raw STT text

### Paste

- [ ] **PST-01**: Clean text pasted into saved active window via pywin32
- [ ] **PST-02**: Target window focus restored via SetForegroundWindow before paste

### System

- [ ] **SYS-01**: System tray icon with states (idle/recording/processing)
- [ ] **SYS-02**: Microphone access check on first launch with clear error message
- [ ] **SYS-03**: Configuration via .env or JSON (hotkey, GCP credentials path)

## v2 Requirements

### Modes

- **MODE-01**: Named LLM modes (chat, formal, code) with custom system prompts
- **MODE-02**: Mode selection via tray menu or hotkey

### History

- **HIST-01**: Transcription history stored in SQLite
- **HIST-02**: History viewer with search

### UX

- **UX-01**: Floating overlay showing transcription result
- **UX-02**: Voice commands (cancel, retry)
- **UX-03**: Settings UI (tkinter or PySide6)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Streaming STT | 10x complexity, marginal gain for push-to-talk UX |
| Offline mode | Cloud-only, $300 GCP credits available |
| Screen context capture | Privacy red flag (Wispr Flow approach) |
| Mobile app | Desktop only |
| Packaging/installer | v1 runs from terminal via `uv run` |
| Multi-user / SaaS | Personal tool |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| REC-01 | Phase 1 | Pending |
| REC-02 | Phase 1 | Pending |
| REC-03 | Phase 2 | Pending |
| REC-04 | Phase 1 | Pending |
| STT-01 | Phase 2 | Pending |
| STT-02 | Phase 2 | Pending |
| STT-03 | Phase 2 | Pending |
| LLM-01 | Phase 2 | Pending |
| LLM-02 | Phase 2 | Pending |
| PST-01 | Phase 2 | Pending |
| PST-02 | Phase 2 | Pending |
| SYS-01 | Phase 2 | Pending |
| SYS-02 | Phase 1 | Pending |
| SYS-03 | Phase 1 | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-03-23 — traceability filled after roadmap creation*
