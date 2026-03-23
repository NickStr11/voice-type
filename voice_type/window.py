"""Active window capture for VoiceType.

Captures the foreground window HWND at recording-stop time so the paste
service can restore focus to the correct window even if the user switches
apps during the STT + LLM processing delay.

Why ctypes instead of win32gui.GetForegroundWindow():
  Both work identically. ctypes avoids a pywin32 import here, keeping
  this module testable without the full Win32 stack. win32gui is used in
  paste.py where we need SetForegroundWindow + more complex API surface.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes


def capture_active_window() -> int:
    """Return the HWND (window handle) of the current foreground window.

    Call this at the moment recording stops — while the user's target app
    is still in the foreground. The returned handle is passed to the paste
    service to restore focus before sending Ctrl+V.

    Returns:
        Integer HWND. Returns 0 if no foreground window exists (rare edge case:
        locked screen, UAC dialog with no foreground window, etc.).

    Note:
        SetForegroundWindow restrictions apply at paste time:
        - Elevated-privilege windows (admin apps, UAC dialogs) may reject focus
          restoration unless VoiceType is also running elevated.
        - Exclusive fullscreen games may not respond to SetForegroundWindow.
        These are documented limitations, not bugs.
    """
    hwnd: int = ctypes.windll.user32.GetForegroundWindow()
    return hwnd
