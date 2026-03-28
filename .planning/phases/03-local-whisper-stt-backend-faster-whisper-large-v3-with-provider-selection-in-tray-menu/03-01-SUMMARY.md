---
phase: 03-local-whisper-stt-backend
plan: 01
subsystem: stt
tags: [whisper, faster-whisper, ctranslate2, stt, config, python]

requires:
  - phase: 02-live-pipeline
    provides: STTClient interface (async recognize) and AppConfig frozen dataclass

provides:
  - WhisperSTTClient with async recognize(audio_bytes) -> str interface
  - AppConfig extended with stt_provider and whisper_model fields
  - GCP credentials optional when stt_provider="local"
  - faster-whisper==1.2.1 dependency installed

affects:
  - 03-02-PLAN (wires WhisperSTTClient into controller and tray menu)

tech-stack:
  added:
    - faster-whisper==1.2.1
    - ctranslate2==4.7.1 (transitive)
    - onnxruntime==1.24.4 (transitive)
  patterns:
    - TDD with load_dotenv patching to isolate config tests from real .env
    - Double-checked locking for lazy model initialization
    - asyncio.to_thread for CPU-bound transcription (same pattern as STTClient)

key-files:
  created:
    - voice_type/stt_whisper.py
    - tests/test_stt_whisper.py
    - tests/test_config.py
  modified:
    - voice_type/config.py
    - .env.example
    - pyproject.toml
    - uv.lock

key-decisions:
  - "device='cpu' + compute_type='int8': AMD RX 7800 XT has no CUDA; int8 explicit avoids float32 default (slow on CPU)"
  - "language=None: auto-detect handles ru/en without config"
  - "Lazy model loading: WhisperModel init takes 3-10s, must not block app startup"
  - "load_dotenv patched in tests: prevents real .env from polluting isolated config tests"

patterns-established:
  - "Lazy init with threading.Lock double-checked locking for shared model resource"
  - "Patch load_dotenv in config tests to prevent disk .env from leaking into test environment"

requirements-completed: [STT-LOCAL-01, STT-LOCAL-02, STT-LOCAL-03, STT-LOCAL-04, CONFIG-01]

duration: 3min
completed: 2026-03-28
---

# Phase 03 Plan 01: Local Whisper STT Backend — Config + Client Summary

**WhisperSTTClient with lazy model loading (int8/CPU), AppConfig extended with stt_provider + whisper_model, GCP credentials made optional for local provider**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-28T19:25:31Z
- **Completed:** 2026-03-28T19:28:56Z
- **Tasks:** 2
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments

- Extended AppConfig with `stt_provider` (default "cloud") and `whisper_model` (default "large-v3-turbo") fields; GCP credentials now optional when provider is "local"
- Created WhisperSTTClient with async recognize() matching STTClient interface, lazy model loading via double-checked locking
- Added faster-whisper==1.2.1 dependency; 14 new unit tests (8 config + 6 whisper), full suite 64/64 green

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend AppConfig with stt_provider + whisper_model** - `c1a1595` (feat)
2. **Task 2: Create WhisperSTTClient with lazy model loading** - `4bc00ca` (feat)

_Note: TDD tasks — tests written first (RED), then implementation (GREEN)._

## Files Created/Modified

- `voice_type/stt_whisper.py` - WhisperSTTClient: lazy init, async recognize, int16→float32, vad_filter
- `tests/test_stt_whisper.py` - 6 unit tests: lazy init, empty audio, transcript, audio conversion, language=None, vad_filter
- `tests/test_config.py` - 8 unit tests: provider default, local/cloud behavior, whisper_model override, GCP optional
- `voice_type/config.py` - Added stt_provider + whisper_model fields; gcp_credentials_path now Path | None; GCP validation conditional on provider
- `.env.example` - Added VOICETYPE_STT_PROVIDER and VOICETYPE_WHISPER_MODEL vars with comments
- `pyproject.toml` - Added faster-whisper==1.2.1 dependency
- `uv.lock` - Updated lockfile

## Decisions Made

- **compute_type="int8"**: AMD RX 7800 XT has no CUDA; explicit int8 avoids the float32 default which is 3-5x slower on CPU
- **language=None**: auto-detect handles mixed ru/en input without requiring config
- **load_dotenv patched in config tests**: the real `.env` at project root has GOOGLE_APPLICATION_CREDENTIALS set; without patching, cloud-provider tests would pass even with cleared env

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Patched load_dotenv in config tests to prevent real .env from leaking**

- **Found during:** Task 1 (config tests RED/GREEN cycle)
- **Issue:** `test_cloud_provider_no_gcp_credentials_fails` was not raising SystemExit because `load_dotenv(override=False)` loaded `GOOGLE_APPLICATION_CREDENTIALS` from the real `.env` file even when `patch.dict(os.environ, ..., clear=True)` was used. The `clear=True` empties the env before the test, but `load_dotenv` then refills it from disk during `load_config()`.
- **Fix:** Added `patch("voice_type.config.load_dotenv", _no_dotenv)` to all config tests that need isolated env control
- **Files modified:** `tests/test_config.py`
- **Verification:** `uv run pytest tests/test_config.py -x -q` — 8/8 pass
- **Committed in:** c1a1595 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test isolation)
**Impact on plan:** Essential for test correctness. The fix is contained to test code only; production config.py behavior is unchanged.

## Issues Encountered

None in production code. One test isolation issue resolved via load_dotenv patching (documented above).

## User Setup Required

None - no external service configuration required for this plan. Plan 02 will wire the provider selection into the running application.

## Next Phase Readiness

- `WhisperSTTClient` ready for Plan 02 to import and use in controller
- `AppConfig.stt_provider` ready for Plan 02 to branch on ("cloud" vs "local")
- faster-whisper installed, model download will happen lazily on first use (~1.6GB for large-v3-turbo)
- No blockers

---

*Phase: 03-local-whisper-stt-backend*
*Completed: 2026-03-28*
