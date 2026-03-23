# Feature Research

**Domain:** Voice-to-text desktop dictation app (Windows, personal use)
**Researched:** 2026-03-23
**Confidence:** HIGH (reference products analyzed: Superwhisper, Wispr Flow, Voibe, WhisperTyping, Windows Voice Typing)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete or broken.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Global hotkey (push-to-talk) | Every competitor uses it; no hotkey = useless | LOW | Hold-to-record OR single-press toggle, both are valid. Push-to-talk preferred for speed |
| Auto-paste into active window | Core value prop — speak, text appears where cursor is | MEDIUM | Requires clipboard + simulated Ctrl+V or direct input injection |
| Works in any app | Users expect universal coverage (Slack, browser, VS Code, Telegram) | MEDIUM | Clipboard paste approach covers 99% of apps without per-app integrations |
| Filler word removal | Raw transcription has "uh", "um", "so" — users expect clean output | LOW | LLM post-processing, trivial with a prompt |
| Punctuation and capitalization | Whisper/Chirp often omits punctuation | LOW | LLM handles this in same pass as filler removal |
| Status feedback (idle/recording/processing) | Without feedback, user doesn't know if it's working | LOW | System tray icon state changes; optional sound cues |
| Configurable hotkey | Users have different keyboards and habits | LOW | Store in config file, validate on startup |
| Basic settings persistence | Hotkey, model preferences, language — must survive restart | LOW | JSON config file is sufficient |
| Audio acknowledgment (start/stop sound) | Immediate confirmation the hotkey registered | LOW | 2 short WAV files, optional in settings |

### Differentiators (Competitive Advantage)

Features that set the product apart. Aligned with project's core value: bilingual, free, fast.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Russian+English auto-detect with no mode switching | Win+H breaks on language switch — this is the #1 pain point. Chirp 2 handles mixed-language natively | MEDIUM | No UI needed; just pass `language_codes: ["ru-RU", "en-US"]` to Chirp 2. Validate accuracy on mixed speech |
| Under 2 seconds end-to-end | Superwhisper is fast; users expect near-instant | HIGH | Parallel STT + LLM calls help. Chirp 2 streaming reduces wait. Critical path to optimize early |
| Custom LLM modes (per-context prompts) | "Email mode", "Code mode", "Chat mode" — different cleanup behavior per context | MEDIUM | Dict of named system prompts. User picks in tray menu or via separate hotkeys |
| Transcription history with quick re-use | See last N dictations, copy or re-paste any of them | MEDIUM | SQLite table, tray menu or floating panel. Solves "I said something and it got overwritten" |
| Voice shortcuts / text expansion | Say "my email" → expands to full address. Reduces repetitive dictation | LOW | Simple string replacement map before paste. High utility, minimal code |
| Floating overlay during recording | Visual recording indicator near cursor, not just tray icon | MEDIUM | Frameless window with waveform or pulse animation. Wispr Flow does this well |
| Silent mode (no sounds, minimal UI) | Office/public spaces where sound feedback is disruptive | LOW | Config toggle disables sounds and overlay; tray-only feedback |
| $0 ongoing cost | Superwhisper charges $8.50/month. Free is a hard differentiator for personal tool | N/A (architecture decision) | Requires GCP credits; document cost per use for user awareness |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Offline/local model (Whisper.cpp) | Privacy, no internet dependency | High complexity: model download (1-3GB), GPU management, worse Russian accuracy than cloud, slow on CPU | Use cloud STT with explicit privacy note in README. Revisit if GCP credits run out |
| Real-time streaming transcription (words appear as you speak) | Feels more responsive, used in Dragon and Windows Voice Typing | Complexity explodes: chunked audio, partial results, cursor management, correction UX. Easy to ship 80% that frustrates users | Fast post-speech transcription (< 2s) achieves same perceived speed with 1/10th the complexity |
| Meeting / continuous recording mode | Useful for long recordings | Completely different UX and architecture from dictation. Out of scope in PROJECT.md | Single-utterance dictation only; note it explicitly |
| Per-app automatic mode switching (screen context) | Wispr Flow sends screenshots to detect context | Privacy nightmare, high latency, complex. Wispr Flow does this via cloud screenshots — users have complained | Manual mode selection via hotkey variant or tray menu |
| Voice commands for editing (select, delete, undo) | Dragon NaturallySpeaking does this | Requires deep OS input control, accessibility APIs, huge test surface | Not a dictation-speed-improvement tool; scope creep |
| Team features / shared vocabulary | Wispr Flow has this | This is a personal tool. Multi-user = auth, sync, billing — completely different product | Keep it single-user, local config |
| Custom wake word ("Hey Cortex") | Hands-free activation | Always-on microphone, high CPU, privacy red flag | Global hotkey is faster and more deliberate |

---

## Feature Dependencies

```
[Global hotkey]
    └──enables──> [Recording]
                      └──requires──> [STT (Chirp 2)]
                                         └──feeds──> [LLM cleanup (Gemini Flash)]
                                                          └──enables──> [Auto-paste]

[System tray icon]
    └──requires──> [Recording state machine]
                       └──drives──> [Floating overlay]  (optional enhancement)

[Transcription history]
    └──requires──> [SQLite setup]
    └──requires──> [LLM cleanup output]

[Custom LLM modes]
    └──requires──> [LLM cleanup] (same call, different system prompt)
    └──enhances──> [Transcription history] (store which mode was used)

[Voice shortcuts]
    └──requires──> [LLM cleanup output]  (apply substitution after LLM, before paste)

[Russian+English auto-detect]
    └──requires──> [Chirp 2 multi-language config]  (pass both language codes, not separate)

[Audio feedback (sounds)]
    └──independent of all above, pure UX enhancement
```

### Dependency Notes

- **Recording requires STT requires LLM requires paste:** This is the critical path. Every other feature wraps around this pipeline. Ship this chain first, everything else is additive.
- **Custom modes require LLM cleanup:** Modes are just different system prompts — zero extra architecture cost once LLM call exists.
- **Transcription history requires SQLite:** Adds one dependency but opens several features (history, re-use, stats). Worth the cost in phase 2.
- **Floating overlay conflicts with silent mode:** Implement as a config toggle; they share the same code path with different display rules.

---

## MVP Definition

### Launch With (v1)

Minimum viable product — validates the core loop.

- [ ] Global hotkey (push-to-talk, configurable) — without this, nothing works
- [ ] Audio recording to temp file — prerequisite for STT
- [ ] Chirp 2 transcription with Russian+English auto-detect — the core differentiator
- [ ] Gemini Flash cleanup (filler words, punctuation) — raw transcription is not acceptable output
- [ ] Auto-paste into active window via clipboard — delivery mechanism
- [ ] System tray icon with idle/recording/processing states — without feedback the app feels broken
- [ ] Audio cues on start/stop — low effort, high UX impact
- [ ] Config file for hotkey — hardcoded hotkey is a dealbreaker for many keyboards

### Add After Validation (v1.x)

Add once core loop is working and daily use confirms the approach.

- [ ] Transcription history panel — trigger: "I wish I could see what I said earlier" happens 3+ times
- [ ] Custom LLM modes (2-3 named presets) — trigger: using for both messaging and professional writing
- [ ] Floating overlay near cursor — trigger: tray icon feels too far from work area
- [ ] Voice shortcuts / text expansion — trigger: repeating the same phrases daily
- [ ] Silent mode toggle — trigger: using in non-home context

### Future Consideration (v2+)

Defer until product-market fit on personal use is confirmed.

- [ ] Settings UI (full window) — JSON config is fine for personal tool; invest in UI when it creates real friction
- [ ] Offline fallback model — defer until GCP credits run out or privacy becomes a concern
- [ ] Per-mode hotkey variants — defer; single hotkey + tray menu covers the need

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Global hotkey + push-to-talk | HIGH | LOW | P1 |
| Chirp 2 STT with bilingual auto-detect | HIGH | MEDIUM | P1 |
| Gemini Flash LLM cleanup | HIGH | LOW | P1 |
| Auto-paste into active window | HIGH | MEDIUM | P1 |
| System tray icon with states | HIGH | LOW | P1 |
| Audio feedback (start/stop sounds) | MEDIUM | LOW | P1 |
| Configurable hotkey (config file) | MEDIUM | LOW | P1 |
| Transcription history | MEDIUM | MEDIUM | P2 |
| Custom LLM modes | MEDIUM | LOW | P2 |
| Floating overlay near cursor | MEDIUM | MEDIUM | P2 |
| Voice shortcuts / text expansion | MEDIUM | LOW | P2 |
| Silent mode toggle | LOW | LOW | P2 |
| Full settings UI window | LOW | HIGH | P3 |
| Offline Whisper.cpp fallback | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

| Feature | Superwhisper | Wispr Flow | WhisperTyping | Windows Voice Typing | Our Approach |
|---------|--------------|------------|---------------|---------------------|--------------|
| Recording mode | Push-to-talk + toggle | Hold-to-talk | Push-to-talk | Toggle (Win+H) | Push-to-talk (hold) as default, toggle as option |
| Platform | macOS + Windows (new) | macOS + Windows | Windows-first | Windows only | Windows only |
| Russian support | Yes (100+ languages) | Yes (claimed) | Unverified | Breaks on language switch | Chirp 2 bilingual, auto-detect — core feature |
| LLM cleanup | Yes, multiple models | Yes, proprietary | Yes (AI modes) | Basic grammar only | Gemini Flash, configurable prompts |
| Custom modes | Yes, 40+ presets | Limited | Yes | None | Start with 3 named modes (default, formal, chat) |
| Offline | Yes (core differentiator) | No | Partial | Partial | No (cloud only, noted as deliberate) |
| Transcription history | Unclear | No | Limited | No | v1.x — SQLite-backed |
| Cost | $8.50/month | $10-15/month | One-time/subscription | Free (Windows built-in) | Free (GCP credits) |
| Privacy | Local processing | Cloud + screenshots (!!!) | Cloud | Cloud (Microsoft) | Cloud STT/LLM, no screenshots |
| System tray | Yes | Yes | Yes | Floating bar | System tray primary |
| Voice shortcuts | No | Yes (team-oriented) | Yes | No | Yes (personal dict, simple map) |

---

## Sources

- [Superwhisper official site](https://superwhisper.com/) — feature list, platform support
- [Wispr Flow review 2026](https://max-productive.ai/ai-tools/wispr-flow/) — detailed feature breakdown including privacy concerns (screenshots)
- [WhisperTyping best STT for Windows](https://whispertyping.com/best-speech-to-text-software/) — Windows-focused feature comparison
- [Voibe vs Wispr Flow comparison](https://www.getvoibe.com/blog/compare/voibe-vs-wispr-flow/) — offline vs cloud tradeoffs
- [Best voice input apps 2026](https://www.opentypeless.com/best-voice-input-apps-2026) — market overview
- [Push-to-talk GitHub project](https://github.com/yixin0829/push-to-talk) — open source implementation patterns
- [HyperVoice Windows](https://hypervoice.app/) — Windows-native app, mode system reference
- [Wispr Flow privacy concerns (zackproser)](https://zackproser.com/blog/wisprflow-review) — 800MB RAM, screenshots to cloud, 8-10s startup

---
*Feature research for: voice-to-text desktop dictation (Windows, bilingual Russian+English)*
*Researched: 2026-03-23*
