---
phase: 03-local-whisper-stt-backend
plan: 02
subsystem: stt
tags: [whisper, pystray, tray-menu, radio-button, provider-selection, python]

requires:
  - phase: 03-01
    provides: WhisperSTTClient with async recognize interface, AppConfig.stt_provider field

provides:
  - TrayIcon with STT Provider submenu (Local Whisper / Cloud Chirp 3 radio items)
  - AppController._transcribe() dispatch method routing to active STT provider at runtime
  - AppController.stt_provider attribute settable at runtime from tray callback
  - on_set_stt_provider wiring in main.py connecting tray to controller
  - STTClient only instantiated when GCP credentials are present

affects:
  - Phase 04+ (provider selection is complete end-to-end feature)

tech-stack:
  added: []
  patterns:
    - "Runtime provider dispatch: _transcribe() reads self.stt_provider per-call, enabling hot-switching without restart"
    - "STTClient conditional init: created only when gcp_credentials_path is not None — prevents crash for local-only users"
    - "TDD RED/GREEN per task: failing tests first, then minimal implementation"

key-files:
  created: []
  modified:
    - voice_type/tray.py
    - voice_type/controller.py
    - voice_type/main.py
    - tests/test_tray.py
    - tests/test_controller.py

key-decisions:
  - "STTClient conditional on gcp_credentials_path: prevents AttributeError/crash when user runs local-only mode without GCP configured"
  - "_transcribe() method not inline in _stop_and_process: cleaner delegation point, easier to test in isolation"
  - "STTClient None check raises RuntimeError with clear message at transcription time, not at init time: fail-fast with actionable error"

patterns-established:
  - "Conditional client init: if config.credential is not None check before creating cloud-dependent clients"
  - "Provider dispatch via self.attribute: check attribute per-call rather than per-init, enables runtime switching"

requirements-completed: [PROV-01, PROV-02, TRAY-01, STT-LOCAL-04]

duration: 2min
completed: 2026-03-28
---

# Phase 03 Plan 02: Provider Selection Wiring — Tray + Controller + main.py Summary

**STT provider radio-button submenu in tray, runtime dispatch via _transcribe(), on_set_stt_provider callback wired end-to-end through main.py — user can now switch Local/Cloud without restart**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-28T19:33:10Z
- **Completed:** 2026-03-28T19:35:59Z
- **Tasks:** 2
- **Files modified:** 5 (0 created, 5 modified)

## Accomplishments

- Added STT Provider submenu to tray with "Local (Whisper)" and "Cloud (Chirp 3)" radio items; on_set_stt_provider callback fires on selection
- Added _transcribe() dispatch method to controller routing to WhisperSTTClient or STTClient based on self.stt_provider; STTClient now conditionally initialized only when GCP credentials are present
- Wired on_set_stt_provider and initial_stt_provider into main.py TrayIcon constructor; 8 new tests (72 total, all green)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add STT Provider submenu to tray** - `26ebbc7` (feat)
2. **Task 2: Wire provider delegation into controller and main.py** - `4d9f66d` (feat)

_Note: TDD tasks — tests written first (RED), then implementation (GREEN)._

## Files Created/Modified

- `voice_type/tray.py` - Added on_set_stt_provider/initial_stt_provider params, _current_stt_provider var, _set_stt_provider/_is_stt_provider helpers, STT Provider submenu with radio items
- `voice_type/controller.py` - Added WhisperSTTClient import, _stt_whisper instance, stt_provider attribute, _transcribe() dispatch method; STTClient made conditional on gcp_credentials_path
- `voice_type/main.py` - Added on_set_stt_provider callback function; TrayIcon now receives on_set_stt_provider and initial_stt_provider kwargs
- `tests/test_tray.py` - 4 new tests: submenu_exists, callback_called_local, default_cloud, radio_true
- `tests/test_controller.py` - Updated config fixture (stt_provider/whisper_model), updated controller fixture (patches WhisperSTTClient); 4 new tests: provider_local, provider_cloud, provider_switch_at_runtime, initializes_both_clients

## Decisions Made

- **STTClient conditional on gcp_credentials_path**: If user sets VOICETYPE_STT_PROVIDER=local without GCP credentials, `config.gcp_credentials_path` is None. Previously this would crash at controller init. Now STTClient is only created when credentials exist; RuntimeError with clear message is raised at transcription time if cloud is somehow selected without credentials.
- **_transcribe() as separate method**: Makes provider dispatch testable in isolation and keeps `_stop_and_process` focused on orchestration. The indirection cost is zero at runtime.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required for this plan. Provider selection is now fully operational; default provider comes from VOICETYPE_STT_PROVIDER in .env.

## Next Phase Readiness

- Provider selection end-to-end complete: tray radio buttons -> controller.stt_provider -> _transcribe() -> WhisperSTTClient or STTClient
- Phase 03 fully complete: WhisperSTTClient (03-01) + provider wiring (03-02)
- Model download happens lazily on first local recording (~1.6GB for large-v3-turbo) — no blocking at startup
- No blockers

---

*Phase: 03-local-whisper-stt-backend*
*Completed: 2026-03-28*
