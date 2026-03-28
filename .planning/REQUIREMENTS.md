# Requirements: VoiceType

**Defined:** 2026-03-23
**Core Value:** Press a key, speak, get clean text in the active window — as fast as Superwhisper

## v1 Requirements

### Recording

- [x] **REC-01**: Global hotkey toggles recording start/stop
- [x] **REC-02**: Audio captured via sounddevice at 16kHz mono int16 (LINEAR16)
- [x] **REC-03**: System tray icon changes state during recording
- [x] **REC-04**: Active window hwnd captured at recording stop (before processing)

### Transcription

- [x] **STT-01**: Audio sent to Google Cloud STT V2 (Chirp 2) batch recognize
- [x] **STT-02**: Russian and English auto-detected without manual language switching
- [x] **STT-03**: Regional endpoint (us-central1-speech.googleapis.com) for minimum latency

### Cleanup

- [x] **LLM-01**: Transcribed text cleaned via Gemini Flash (punctuation, grammar, filler removal)
- [x] **LLM-02**: Wall-clock timeout on LLM call with fallback to raw STT text

### Paste

- [x] **PST-01**: Clean text pasted into saved active window via pywin32
- [x] **PST-02**: Target window focus restored via SetForegroundWindow before paste

### System

- [x] **SYS-01**: System tray icon with states (idle/recording/processing)
- [x] **SYS-02**: Microphone access check on first launch with clear error message
- [x] **SYS-03**: Configuration via .env or JSON (hotkey, GCP credentials path)

## Phase 3 Requirements — Local Whisper STT

### Local STT

- [x] **STT-LOCAL-01**: WhisperSTTClient with async recognize(audio_bytes) -> str interface matching STTClient
- [x] **STT-LOCAL-02**: Model loads lazily on first recognize() call (not at __init__)
- [x] **STT-LOCAL-03**: int16 audio bytes converted to float32 normalized [-1, 1] before transcription
- [x] **STT-LOCAL-04**: vad_filter=True and language=None (auto-detect) used in transcription
- [ ] **PROV-01**: User can select STT provider (cloud/local) from tray menu
- [ ] **PROV-02**: Provider selection persists across app restart
- [ ] **TRAY-01**: Tray menu has STT Provider submenu with checkmarks showing active provider

### Config

- [x] **CONFIG-01**: AppConfig accepts stt_provider and whisper_model fields; GCP credentials optional when provider=local

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
| REC-01 | Phase 1 | Complete |
| REC-02 | Phase 1 | Complete |
| REC-03 | Phase 2 | Complete |
| REC-04 | Phase 1 | Complete |
| STT-01 | Phase 2 | Complete |
| STT-02 | Phase 2 | Complete |
| STT-03 | Phase 2 | Complete |
| LLM-01 | Phase 2 | Complete |
| LLM-02 | Phase 2 | Complete |
| PST-01 | Phase 2 | Complete |
| PST-02 | Phase 2 | Complete |
| SYS-01 | Phase 2 | Complete |
| SYS-02 | Phase 1 | Complete |
| SYS-03 | Phase 1 | Complete |

| STT-LOCAL-01 | Phase 3 Plan 01 | Complete |
| STT-LOCAL-02 | Phase 3 Plan 01 | Complete |
| STT-LOCAL-03 | Phase 3 Plan 01 | Complete |
| STT-LOCAL-04 | Phase 3 Plan 01 | Complete |
| CONFIG-01 | Phase 3 Plan 01 | Complete |
| PROV-01 | Phase 3 Plan 02 | Pending |
| PROV-02 | Phase 3 Plan 02 | Pending |
| TRAY-01 | Phase 3 Plan 02 | Pending |

**Coverage:**
- v1 requirements: 14 total — all complete
- Phase 3 requirements: 8 total — 5 complete (Plan 01 done), 3 pending (Plan 02)
- Unmapped: 0

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-03-28 — Phase 3 Plan 01 requirements added and marked complete*
