# VoiceType

## What This Is

Desktop voice-to-text app for Windows. Hotkey to record, transcribe via cloud STT, clean up with LLM, paste into active window. Personal Superwhisper alternative — free, fast, bilingual (Russian + English).

## Core Value

Press a key, speak, get clean text in the active window — as fast as Superwhisper.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Global hotkey starts/stops voice recording
- [ ] Audio sent to Google Cloud Speech-to-Text V2 (Chirp 2) for transcription
- [ ] Transcribed text cleaned via Gemini Flash (punctuation, grammar, filler removal)
- [ ] Clean text auto-pasted into currently active window
- [ ] Russian and English auto-detection without manual switching
- [ ] System tray icon with status indication (idle/recording/processing)
- [ ] Minimal latency — under 2 seconds from stop-speaking to text appearing
- [ ] Desktop UI (phase 2) — settings, history, mode selection

### Out of Scope

- Mobile app — desktop only
- Offline mode — cloud APIs only (for now)
- Meeting recording/transcription — single-utterance dictation only
- Custom vocabulary training — use model defaults
- Multi-user / SaaS — personal tool

## Context

- User has $300 Google Cloud credits (expire ~May 2026) — covers both STT and LLM
- Windows 11, daily use for messaging and coding
- Win+H (built-in Windows voice typing) bugs out on language switching — primary pain point
- Superwhisper works well but costs $8.50/month — want free alternative
- OpenRouter available as fallback for LLM if Google credits run out

## Constraints

- **Platform**: Windows 11 (primary and only target)
- **Budget**: $0 ongoing — use Google Cloud credits, then evaluate
- **Stack**: Python (user's primary language), uv for deps
- **Speed**: Must feel instant — comparable to Superwhisper latency
- **Languages**: Russian + English with seamless auto-detection

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Google Cloud STT V2 (Chirp 2) over OpenAI Whisper API | $300 free credits, same account as Gemini, good Russian support | — Pending |
| Gemini Flash for text cleanup | Fast, cheap, covered by same GCP credits | — Pending |
| Python + system tray first, full UI later | Ship working core fast, iterate on UI | — Pending |
| Separate repo (not cortex tool) | Independent project, own lifecycle | — Pending |

---
*Last updated: 2026-03-23 after initialization*
