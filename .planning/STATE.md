---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
stopped_at: Completed 02-live-pipeline/02-02-PLAN.md
last_updated: "2026-03-23T15:41:24.950Z"
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 7
  completed_plans: 6
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-23)

**Core value:** Press a key, speak, get clean text in the active window — as fast as Superwhisper
**Current focus:** Phase 02 — live-pipeline

## Current Position

Phase: 02 (live-pipeline) — EXECUTING
Plan: 2 of 3

## Performance Metrics

**Velocity:**

- Total plans completed: 3
- Average duration: ~1.5min
- Total execution time: ~4min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3 | ~4min | ~1.5min |

**Recent Trend:**

- Last 5 plans: 2min
- Trend: —

*Updated after each plan completion*
| Phase 01-foundation P04 | 15 | 2 tasks | 2 files |
| Phase 02-live-pipeline P01 | 3 | 2 tasks | 4 files |
| Phase 02-live-pipeline P02 | 3 | 2 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Stack: Google Cloud STT V2 (Chirp 2) + Gemini Flash, all on $300 GCP credits
- Architecture: Single-process, thread-per-subsystem (pystray + pynput + asyncio event loop)
- Phase 1: All 8 critical pitfalls land here — must be addressed from day one, not retrofitted
- Hotkey: Use Ctrl+Alt+key default; Win+key intercepted by Windows shell before pynput
- [01-01] AppConfig as frozen dataclass not pydantic — zero extra deps, sufficient for config
- [01-01] *.json blanket-excluded from git — protects GCP service account keys; explicit exceptions as needed
- [01-01] Hotkey default is <ctrl>+<alt>+r — avoids Win+key interception per PITFALLS.md research
- [01-03] suppress=True never used in HotkeyListener — Pitfall 4 prevention (freezes all OS keyboard input)
- [01-03] HWND captured at recording-stop time, not at paste time — prevents Pitfall 1 (paste in wrong window)
- [01-03] ctypes used in window.py instead of win32gui — keeps module testable without full Win32 stack
- [Phase 01-02]: channels=1 always — stereo causes PortAudioError -9998 on mono-only mics (Pitfall 7)
- [Phase 01-02]: device=None — use OS default mic, stable across USB/BT/built-in changes
- [Phase 01-02]: PortAudio -9999 translated to Windows Privacy & Security Microphone settings path (SYS-02)
- [Phase 01-foundation]: AppController receives event loop as constructor arg — main() owns lifecycle
- [Phase 01-foundation]: asyncio.Queue as event bus between pynput thread and controller — clean shutdown via enqueued 'shutdown' event
- [Phase 01-foundation]: HWND captured before recorder.stop() await — guarantees original foreground window even if user switches during stop
- [Phase 02-live-pipeline]: asyncio.to_thread for STT blocking GCP call — keeps event loop unblocked
- [Phase 02-live-pipeline]: concurrent.futures wall-clock timeout for LLM — asyncio.wait_for cannot catch socket stalls
- [Phase 02-live-pipeline]: thinking_budget=0 on Gemini 2.5 Flash — saves 1-3s latency on simple rewrite task
- [02-02] pywin32 over pyautogui for paste — lower latency, reliable Unicode/Russian, CF_UNICODETEXT native
- [02-02] 50ms sleep after SetForegroundWindow — Win32 focus change is async, keystrokes land in wrong window without delay
- [02-02] Pre-generate pystray icons at TrayIcon init — PIL generation ~5ms each, too slow on state change
- [02-02] run_detached() not run() — run() blocks calling thread (Pitfall 8)

### Pending Todos

None yet.

### Blockers/Concerns

- Gemini Flash socket stall bug (confirmed in issue tracker) — requires concurrent.futures wall-clock timeout in Phase 2
- SetForegroundWindow reliability: elevated privilege apps, UAC dialogs, exclusive fullscreen games may not be fixable without matching privilege level — document as known limitation

## Session Continuity

Last session: 2026-03-23T15:40:30Z
Stopped at: Completed 02-live-pipeline/02-02-PLAN.md
Resume file: None
