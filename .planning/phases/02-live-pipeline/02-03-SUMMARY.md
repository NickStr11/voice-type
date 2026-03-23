---
phase: 02-live-pipeline
plan: 03
subsystem: integration
tags: [asyncio, pystray, state-machine, pipeline, tdd, circular-import]

# Dependency graph
requires:
  - phase: 02-01
    provides: STTClient.recognize() async + LLMClient.clean() sync with timeout
  - phase: 02-02
    provides: PasteService.paste() + TrayIcon with run_detached/set_state/stop

provides:
  - AppController with full STT->LLM->paste pipeline in _stop_and_process()
  - TrayIcon wired to state transitions (IDLE/RECORDING/PROCESSING)
  - main.py with TrayIcon startup and clean Ctrl+C shutdown
  - State enum extracted to voice_type/states.py (breaks circular import)
  - tests/conftest.py shared win32 mock setup for test isolation

affects:
  - phase-03 (future): end-to-end integration, any controller extensions

# Tech tracking
tech-stack:
  added: []
  patterns:
    - State enum in dedicated states.py to prevent circular imports
    - conftest.py installs shared mocks before any module imports them
    - asyncio.to_thread for all blocking calls (recorder.stop, llm.clean, paste.paste)
    - finally block guarantees IDLE reset even on pipeline error
    - mutable list container for forward reference to controller in on_quit closure

key-files:
  created:
    - voice_type/states.py
    - tests/conftest.py
    - tests/test_controller.py
  modified:
    - voice_type/controller.py
    - voice_type/tray.py
    - voice_type/main.py
    - tests/test_paste.py

key-decisions:
  - "State enum moved to voice_type/states.py to break controller<->tray circular import"
  - "conftest.py installs win32 mocks before any test file imports paste.py -- prevents test ordering failures"
  - "mutable list (controller_ref) for forward reference in on_quit closure -- cleanest pattern without global"
  - "finally block in _stop_and_process always resets to IDLE -- stuck-in-PROCESSING is never possible"
  - "tray=None default in AppController.__init__ -- enables testing without pystray"

patterns-established:
  - "Pipeline error recovery: try/except + finally always resets state to IDLE"
  - "Test isolation: conftest.py as single source of truth for platform mocks"
  - "Forward reference via mutable list: controller_ref: list[AppController] = []"

requirements-completed: [STT-01, STT-02, STT-03, LLM-01, LLM-02, PST-01, PST-02, SYS-01, REC-03]

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 02 Plan 03: Controller Integration Summary

**AppController wired with full STT->LLM->paste pipeline, tray state transitions on each stage, and clean Ctrl+C shutdown -- end-to-end voice-type pipeline complete**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-23T15:42:54Z
- **Completed:** 2026-03-23T15:47:11Z
- **Tasks:** 2 (+ TDD RED commit)
- **Files modified:** 7

## Accomplishments

- AppController now runs STTClient.recognize() -> LLMClient.clean() -> PasteService.paste() on each recording cycle
- TrayIcon transitions: IDLE (green) -> RECORDING (red) -> PROCESSING (yellow) -> IDLE (green)
- Pipeline errors caught and state always reset to IDLE via finally block
- main.py: TrayIcon starts via run_detached(), quit from tray menu calls controller.shutdown(), Ctrl+C handled cleanly
- 45 tests pass (up from 40 -- 5 new controller integration tests)

## Task Commits

1. **[RED] test(02-03): failing tests** - `a13f40b` (test)
2. **Task 1: Wire pipeline + tray states** - `f0d8872` (feat)
3. **Task 2: Update main.py** - `c1efd03` (feat)

_TDD plan: RED commit first, GREEN in Task 1 feat commit._

## Files Created/Modified

- `voice_type/states.py` - State enum extracted here (breaks circular import)
- `voice_type/controller.py` - Full pipeline wiring, tray integration, pipeline error recovery
- `voice_type/tray.py` - Import updated to use states.py instead of controller.py
- `voice_type/main.py` - TrayIcon startup, on_quit callback, clean Ctrl+C shutdown
- `tests/conftest.py` - Shared win32 mock setup before any test imports paste.py
- `tests/test_controller.py` - 5 integration tests for pipeline and tray states
- `tests/test_paste.py` - Updated to use shared WIN32_MOCKS from conftest

## Decisions Made

- State enum moved to `voice_type/states.py` to break circular import between `controller.py` (which imports TrayIcon) and `tray.py` (which needs State)
- `conftest.py` installs win32 mocks before any module imports them, fixing test ordering failure where `test_controller.py` (alphabetically first) installed anonymous mocks that `test_paste.py` couldn't track
- `tray=None` default in AppController constructor enables testing without pystray overhead
- `finally` block in `_stop_and_process` ensures IDLE reset even if STT, LLM, or paste raises
- Mutable list `controller_ref: list[AppController] = []` for forward reference in `on_quit` closure

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Circular import between controller.py and tray.py**
- **Found during:** Task 1 (GREEN phase -- running tests against updated controller)
- **Issue:** controller.py imported TrayIcon from tray.py; tray.py imported State from controller.py -- circular import caused ImportError on collection
- **Fix:** Extracted State enum to voice_type/states.py; both files now import from there
- **Files modified:** voice_type/states.py (created), voice_type/controller.py, voice_type/tray.py
- **Verification:** 45 tests pass, no import errors
- **Committed in:** f0d8872 (Task 1 feat commit)

**2. [Rule 1 - Bug] Test ordering failure -- win32 mock isolation**
- **Found during:** Task 1 (full test suite after GREEN)
- **Issue:** test_controller.py installed anonymous MagicMock() for win32gui in sys.modules; paste.py imported and bound to that mock; test_paste.py installed different named mocks in sys.modules but paste.py's already-imported win32gui reference didn't update -- SetForegroundWindow assertion failed
- **Fix:** Created tests/conftest.py that installs named WIN32_MOCKS before any test file imports; updated test_paste.py to use WIN32_MOCKS from conftest; removed redundant autouse fixture from test_paste.py
- **Files modified:** tests/conftest.py (created), tests/test_paste.py, tests/test_controller.py
- **Verification:** 45 tests pass in all orderings
- **Committed in:** f0d8872 (Task 1 feat commit)

---

**Total deviations:** 2 auto-fixed (1 blocking circular import, 1 bug in test isolation)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered

- Pre-existing pyright error in `voice_type/window.py`: `reportUnusedImport` for `ctypes.wintypes` -- out of scope, logged as deferred

## Next Phase Readiness

- Full pipeline is live: press hotkey -> speak -> stop -> text appears in active window
- Tray icon reflects each stage visually
- Clean shutdown via Ctrl+C or tray quit menu
- 45 tests green, 0 pyright errors in changed files
- End-to-end smoke test requires real GCP credentials + mic (not automated)

---
*Phase: 02-live-pipeline*
*Completed: 2026-03-23*
