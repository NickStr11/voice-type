---
phase: 02-live-pipeline
plan: "02"
subsystem: ui
tags: [pystray, pywin32, pillow, clipboard, tray-icon, paste]

# Dependency graph
requires:
  - phase: 02-live-pipeline/02-01
    provides: nothing direct — parallel plan, independent
  - phase: 01-foundation
    provides: State enum in voice_type/controller.py
provides:
  - PasteService.paste(text, hwnd) in voice_type/paste.py
  - TrayIcon with set_state() and run_detached() in voice_type/tray.py
affects:
  - 02-live-pipeline/02-03 (controller wires PasteService and TrayIcon together)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD: write failing test → import error → commit RED → implement → commit GREEN → fix types"
    - "pyright: ignore[reportUnknownMemberType] on untyped win32/pystray member access"
    - "Win32 clipboard: save → SetForegroundWindow + 50ms → write → Ctrl+V + 50ms → restore"
    - "Pystray: pre-generate 3 icons at init, swap icon.icon on state change (thread-safe)"

key-files:
  created:
    - voice_type/paste.py
    - voice_type/tray.py
    - tests/test_paste.py
    - tests/test_tray.py
  modified: []

key-decisions:
  - "pywin32 over pyautogui for paste: lower latency, reliable Unicode/Russian text, CF_UNICODETEXT native"
  - "50ms sleep after SetForegroundWindow: Win32 focus change is async — keystrokes go to wrong window without delay"
  - "Pre-generate pystray icons at TrayIcon init, not on state change — PIL generation is ~5ms, adds visible lag"
  - "run_detached() not run() for pystray: run() blocks the calling thread (Pitfall 8)"
  - "pyright: ignore[reportUnknownMemberType] on win32/pystray calls — untyped stubs, not code errors"

patterns-established:
  - "PST-02 clipboard save/restore: save before SetForegroundWindow, restore in finally block after paste"
  - "hwnd=0 guard: log warning and skip paste cleanly — do not crash on missing window"
  - "Empty text guard: return before touching clipboard — no side effects for empty STT output"

requirements-completed: [PST-01, PST-02, SYS-01, REC-03]

# Metrics
duration: 3min
completed: 2026-03-23
---

# Phase 02 Plan 02: PasteService and TrayIcon Summary

**PasteService delivering text via clipboard+Ctrl+V with save/restore, and TrayIcon with 3 pre-generated pystray state icons — 11 tests, 0 pyright errors**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-23T15:37:31Z
- **Completed:** 2026-03-23T15:40:30Z
- **Tasks:** 2
- **Files modified:** 4 created

## Accomplishments
- PasteService.paste(text, hwnd) — SetForegroundWindow + 50ms + CF_UNICODETEXT clipboard + Ctrl+V + clipboard restore
- hwnd=0 and empty text guards prevent silent failures and clipboard corruption
- TrayIcon with 3 Pillow circle icons (green/red/yellow) pre-generated at init, set_state() thread-safe swap
- 11 tests pass, 0 pyright errors, win32 modules fully mocked at test time

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: PasteService failing tests** - `61b445b` (test)
2. **Task 1 GREEN: PasteService implementation** - `7a4e2e4` (feat)
3. **Task 2 RED: TrayIcon failing tests** - `aa46fcf` (test)
4. **Task 2 GREEN: TrayIcon implementation** - `0686b07` (feat)
5. **Auto-fix: pyright ignore comments** - `8275983` (fix)

_Note: TDD tasks have multiple commits (test → feat). Pyright fix committed separately._

## Files Created/Modified
- `voice_type/paste.py` — PasteService with clipboard save/restore and Ctrl+V delivery
- `voice_type/tray.py` — TrayIcon with 3 pre-generated icons, run_detached(), set_state()
- `tests/test_paste.py` — 5 tests: empty text guard, hwnd=0, SetForegroundWindow, clipboard restore, non-text clipboard
- `tests/test_tray.py` — 6 tests: icon image, distinct colors, run_detached not run, set_state, title update, idle init title

## Decisions Made
- pywin32 over pyautogui: lower latency, reliable Unicode/Russian text via CF_UNICODETEXT native API
- 50ms sleep after SetForegroundWindow: Win32 focus change is async — without it, keystrokes land in wrong window
- Pre-generate pystray icons at TrayIcon init: PIL generation ~5ms each, too slow to do on every state change
- run_detached() not run(): run() blocks the calling thread (Pitfall 8 prevention)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added pyright ignore comments for untyped win32/pystray member access**
- **Found during:** Task 2 (TrayIcon implementation) — pyright check after both tasks
- **Issue:** pyright strict mode flagged `reportUnknownMemberType` on win32clipboard, win32api, and pystray.Icon.run_detached() — all untyped third-party libraries with `import-untyped` suppression on import but not on member access
- **Fix:** Added `# pyright: ignore[reportUnknownMemberType]` at each affected call site in paste.py and tray.py
- **Files modified:** voice_type/paste.py, voice_type/tray.py
- **Verification:** `uv run pyright voice_type/paste.py voice_type/tray.py` — 0 errors, 0 warnings; 11 tests still pass
- **Committed in:** 8275983

---

**Total deviations:** 1 auto-fixed (Rule 2 — missing critical type correctness)
**Impact on plan:** Required for pyright clean build per project quality gates. No scope creep.

## Issues Encountered
None beyond the pyright deviation above.

## Next Phase Readiness
- Plan 02-03 (controller) can now wire PasteService and TrayIcon into AppController
- Both modules export exactly the interfaces specified in PLAN.md: PasteService, TrayIcon
- State enum import in tray.py is from voice_type.controller — ready for controller integration

---
*Phase: 02-live-pipeline*
*Completed: 2026-03-23*

## Self-Check: PASSED

- FOUND: voice_type/paste.py
- FOUND: voice_type/tray.py
- FOUND: tests/test_paste.py
- FOUND: tests/test_tray.py
- FOUND: .planning/phases/02-live-pipeline/02-02-SUMMARY.md
- Commits verified: 61b445b, 7a4e2e4, aa46fcf, 0686b07, 8275983
