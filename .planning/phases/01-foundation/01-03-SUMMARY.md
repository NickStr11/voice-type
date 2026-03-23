---
phase: 01-foundation
plan: 03
subsystem: hotkey
tags: [pynput, GlobalHotKeys, ctypes, win32, window-capture, hotkey]

# Dependency graph
requires:
  - phase: 01-01
    provides: AppConfig dataclass with hotkey field

provides:
  - HotkeyListener class — pynput GlobalHotKeys toggle hotkey, daemon thread, on_toggle callback
  - capture_active_window() — returns foreground HWND int via ctypes

affects:
  - 01-04 (audio recording — hotkey triggers recording start/stop)
  - future paste module (needs HWND from capture_active_window at recording-stop)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - GlobalHotKeys daemon thread pattern (suppress=False enforced, never suppress=True)
    - ctypes GetForegroundWindow for HWND capture without pywin32 dependency

key-files:
  created:
    - voice_type/hotkey.py
    - voice_type/window.py
  modified: []

key-decisions:
  - "suppress=True never used in HotkeyListener — Pitfall 4 prevention (freezes all OS keyboard input)"
  - "HWND captured at recording-stop time, not at paste time — prevents Pitfall 1 (paste in wrong window)"
  - "ctypes used in window.py instead of win32gui — avoids pywin32 import in this module, pywin32 reserved for paste.py"
  - "Verify script string-match check was buggy (matched warning text in docstring) — fixed with AST-level check"

patterns-established:
  - "Hotkey pattern: GlobalHotKeys({combo: callback}) in daemon thread, no suppress"
  - "Window capture: call capture_active_window() immediately at recording stop, pass HWND to paste service"

requirements-completed: [REC-01, REC-04]

# Metrics
duration: 1min
completed: 2026-03-23
---

# Phase 01 Plan 03: Hotkey Listener and Active Window Capture Summary

**pynput GlobalHotKeys toggle listener in daemon thread + ctypes GetForegroundWindow for HWND capture at recording-stop time**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-23T14:54:16Z
- **Completed:** 2026-03-23T14:55:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- capture_active_window() returns foreground HWND as int — called at recording-stop to lock target window before STT/LLM delay
- HotkeyListener wraps pynput GlobalHotKeys in a daemon background thread with start()/stop() lifecycle
- suppress=True explicitly prevented (both in code and with AST verification) — Pitfall 4 directly addressed

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement window capture utility** - `5848895` (feat)
2. **Task 2: Implement HotkeyListener with pynput GlobalHotKeys** - `f8715f3` (feat)

## Files Created/Modified

- `voice_type/window.py` - capture_active_window() via ctypes.windll.user32.GetForegroundWindow
- `voice_type/hotkey.py` - HotkeyListener class wrapping GlobalHotKeys in daemon thread

## Decisions Made

- suppress=True is never passed to GlobalHotKeys — Pitfall 4 prevention. The warning text in the docstring itself caused the plan's verify script to false-positive; fixed with AST parsing to check actual keyword arguments.
- HWND captured at recording-stop time (not paste time) — directly addresses Pitfall 1 (paste lands in wrong window after user switches focus during processing).
- ctypes in window.py instead of pywin32 — keeps this module testable without full Win32 stack; pywin32 reserved for paste.py which needs SetForegroundWindow.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan verify script false-positive on suppress=True string match**
- **Found during:** Task 2 (hotkey.py verify step)
- **Issue:** The plan's verify script used `'suppress=True' not in src` (raw string match). The module docstring contains `"suppress=True is NOT used"` as a warning — triggering the assertion on correct code.
- **Fix:** Replaced naive string check with AST walk that inspects actual keyword arguments in Call nodes, ensuring suppress=True is never passed as a function argument.
- **Files modified:** N/A (verification script only, not checked in)
- **Verification:** AST check passes; suppress safety confirmed as keyword-arg level
- **Committed in:** f8715f3 (Task 2 commit — file itself is correct, verification logic fixed inline)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug in verify script)
**Impact on plan:** Verification fixed to correctly detect the actual problem. Hotkey implementation unchanged and correct.

## Issues Encountered

None — both files implemented and verified cleanly.

## Next Phase Readiness

- HotkeyListener and capture_active_window() ready for use by AppController
- Plan 01-04 (audio recording) can now wire up HotkeyListener to trigger recording start/stop
- Paste module (later phase) should call capture_active_window() at recording-stop and store HWND

---
*Phase: 01-foundation*
*Completed: 2026-03-23*

## Self-Check: PASSED

- FOUND: voice_type/window.py
- FOUND: voice_type/hotkey.py
- FOUND: .planning/phases/01-foundation/01-03-SUMMARY.md
- FOUND commit 5848895 (Task 1: window.py)
- FOUND commit f8715f3 (Task 2: hotkey.py)
