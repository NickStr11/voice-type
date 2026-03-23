---
phase: 01-foundation
plan: "02"
subsystem: audio
tags: [sounddevice, numpy, portaudio, microphone, windows-permissions]

# Dependency graph
requires:
  - phase: 01-01
    provides: AppConfig dataclass and project scaffold structure
provides:
  - AudioRecorder class capturing 16kHz mono int16 via sounddevice InputStream
  - check_microphone_access() translating PortAudio -9999 to Windows Privacy settings path
  - MicrophoneError exception type for permission/device failures
affects: [01-03, 01-04, 02-stt-integration]

# Tech tracking
tech-stack:
  added: [sounddevice 0.5.5, numpy int16 arrays, threading.Lock for callback safety]
  patterns: [TDD RED-GREEN, PortAudio error translation, thread-safe callback with indata.copy()]

key-files:
  created:
    - voice_type/audio.py
    - tests/__init__.py
    - tests/test_audio.py
  modified: []

key-decisions:
  - "channels=1 always — stereo causes PortAudioError -9998 on mono-only mics (Pitfall 7)"
  - "device=None — use OS default, stable across USB/BT/built-in changes without code changes"
  - "PortAudio -9999 translated to human-readable Windows Privacy & Security path (Pitfall 3 / SYS-02)"
  - "indata.copy() in callback — prevents ring buffer aliasing, thread-safe"
  - "BLOCKSIZE=0 — lets PortAudio choose optimal buffer; explicit blocksize causes WASAPI errors"

patterns-established:
  - "PortAudio error translation: check str(exc) for -9999 or 'unanticipated host error'"
  - "Thread-safe audio collection: threading.Lock + indata.copy() in InputStream callback"
  - "TDD with mock sounddevice: patch sounddevice.InputStream, capture callback via side_effect"

requirements-completed: [SYS-02, REC-02]

# Metrics
duration: 3min
completed: 2026-03-23
---

# Phase 01 Plan 02: Audio Capture Summary

**AudioRecorder class + check_microphone_access() capturing 16kHz mono int16 via sounddevice, with PortAudio -9999 translated to Windows Privacy & Security settings path**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-23T14:54:15Z
- **Completed:** 2026-03-23T14:57:00Z
- **Tasks:** 1 (TDD: 2 commits — RED then GREEN)
- **Files modified:** 3 (audio.py, tests/__init__.py, tests/test_audio.py)

## Accomplishments
- AudioRecorder captures 16kHz mono int16 via sounddevice InputStream with thread-safe callback
- check_microphone_access() translates opaque PortAudio -9999 error to actionable Windows Privacy settings path
- 17 pytest tests cover constants, error translation, state guards, chunk concatenation, LINEAR16 bytes, ring buffer safety

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: failing tests for AudioRecorder** - `fe09b32` (test)
2. **Task 1 GREEN: implement voice_type/audio.py** - `f4a3747` (feat)

_Note: TDD tasks have two commits (test → feat)_

## Files Created/Modified
- `voice_type/audio.py` - AudioRecorder class + check_microphone_access() + MicrophoneError
- `tests/__init__.py` - Test package init
- `tests/test_audio.py` - 17 tests covering all specified behaviors

## Decisions Made
- `channels=1` always (not configurable) — stereo causes PortAudioError -9998 on mono-only mics, speech has no benefit from stereo
- `device=None` — OS default mic, user controls via Windows Sound settings, no code change needed when swapping mics
- PortAudio -9999 ("unanticipated host error") is the Windows 11 microphone permission denial signal — translated to exact Settings path
- `indata.copy()` in callback mandatory — indata is a view into PortAudio's ring buffer, mutated before next callback fires

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All 17 tests passed on first run of GREEN implementation.

## User Setup Required

None - no external service configuration required for this plan. Actual microphone hardware test requires a real device but all logic paths are covered by mocks.

## Next Phase Readiness
- `AudioRecorder` and `check_microphone_access` ready for import in main.py and hotkey flow
- LINEAR16 bytes from `audio.stop().tobytes()` ready for GCP STT V2 streaming upload
- Blocker from STATE.md (Gemini Flash socket stall) unrelated to this plan — audio subsystem complete

---
*Phase: 01-foundation*
*Completed: 2026-03-23*
