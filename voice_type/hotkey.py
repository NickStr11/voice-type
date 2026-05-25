"""Global hotkey listener for VoiceType.

Uses Win32 RegisterHotKey API — the most reliable way to capture global
hotkeys on Windows. pynput GlobalHotKeys has issues with modifier combos
on Windows (keys leak through, hotkeys don't fire reliably).

RegisterHotKey:
- Natively supported by Windows, no third-party lib needed
- Works regardless of keyboard layout or active window
- Does NOT pass the hotkey through to the active application
- Runs a message loop in a daemon thread
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from collections.abc import Callable
from typing import Final

from loguru import logger

from voice_type.config import AppConfig

# Win32 constants
MOD_CTRL: Final[int] = 0x0002
MOD_SHIFT: Final[int] = 0x0004
MOD_ALT: Final[int] = 0x0001
MOD_NOREPEAT: Final[int] = 0x4000
WM_HOTKEY: Final[int] = 0x0312
VK_SPACE: Final[int] = 0x20
HOTKEY_ID: Final[int] = 1

# Map of pynput-style key names to (modifiers, vk_code)
_HOTKEY_MAP: dict[str, tuple[int, int]] = {
    "<ctrl>+<shift>+<space>": (MOD_CTRL | MOD_SHIFT | MOD_NOREPEAT, VK_SPACE),
    "<ctrl>+<alt>+r": (MOD_CTRL | MOD_ALT | MOD_NOREPEAT, ord("R")),
    "<ctrl>+<alt>+v": (MOD_CTRL | MOD_ALT | MOD_NOREPEAT, ord("V")),
    "<ctrl>+<shift>+r": (MOD_CTRL | MOD_SHIFT | MOD_NOREPEAT, ord("R")),
}

user32 = ctypes.windll.user32  # type: ignore[attr-defined]


def _parse_hotkey(hotkey_str: str) -> tuple[int, int]:
    """Parse a pynput-style hotkey string into (modifiers, vk_code).

    Falls back to Ctrl+Shift+Space if the hotkey is not recognized.
    """
    key = hotkey_str.strip().lower()
    if key in _HOTKEY_MAP:
        return _HOTKEY_MAP[key]

    logger.warning(f"Unknown hotkey '{hotkey_str}', falling back to Ctrl+Shift+Space")
    return MOD_CTRL | MOD_SHIFT | MOD_NOREPEAT, VK_SPACE


class HotkeyRegistrationError(RuntimeError):
    """Raised when RegisterHotKey fails — e.g. combo taken by another app."""


class HotkeyListener:
    """Listens for a global hotkey via Win32 RegisterHotKey.

    Runs a Win32 message loop in a daemon thread. The callback is called
    from that thread — callers must be thread-safe.
    """

    _REGISTRATION_TIMEOUT_S: float = 2.0

    def __init__(self, config: AppConfig, on_toggle: Callable[[], None]) -> None:
        self._config = config
        self._on_toggle = on_toggle
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._running = False
        self._registered = threading.Event()
        self._registration_error: str | None = None

    def _loop(self) -> None:
        """Win32 message loop — runs in daemon thread."""
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()  # type: ignore[attr-defined]

        modifiers, vk_code = _parse_hotkey(self._config.hotkey)

        if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers, vk_code):
            self._registration_error = (
                f"Failed to register hotkey '{self._config.hotkey}' "
                f"— combo likely taken by another running app"
            )
            logger.error(self._registration_error)
            self._registered.set()
            return

        logger.info(f"Hotkey registered: {self._config.hotkey}")
        self._registered.set()

        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:  # WM_QUIT or error
                break
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._on_toggle()

        user32.UnregisterHotKey(None, HOTKEY_ID)

    def start(self) -> None:
        """Start the hotkey listener and wait for RegisterHotKey to succeed.

        Raises:
            HotkeyRegistrationError: If Win32 RegisterHotKey returns false
                (e.g. another running app has already grabbed the combo).
                Caller should surface this to the user — silent failure
                means a dead tray icon.
            RuntimeError: If start() is called twice without stop() between.
        """
        if self._thread is not None:
            raise RuntimeError("HotkeyListener.start() called while already running")

        self._running = True
        self._registered.clear()
        self._registration_error = None
        thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="HotkeyListener",
        )
        self._thread = thread
        thread.start()

        # Block until the worker thread has either succeeded with
        # RegisterHotKey or filled in the error string. Without this
        # synchronisation, callers see a "hotkey listener started" log
        # while the actual registration may have failed silently.
        if not self._registered.wait(self._REGISTRATION_TIMEOUT_S):
            raise HotkeyRegistrationError(
                f"Hotkey listener did not become ready within "
                f"{self._REGISTRATION_TIMEOUT_S}s — message loop may be stuck"
            )
        if self._registration_error is not None:
            raise HotkeyRegistrationError(self._registration_error)

    def stop(self) -> None:
        """Stop the hotkey listener."""
        self._running = False
        if self._thread_id is not None:
            # Post WM_QUIT to break GetMessageW loop
            ctypes.windll.user32.PostThreadMessageW(  # type: ignore[attr-defined]
                self._thread_id, 0x0012, 0, 0  # WM_QUIT
            )
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
            self._thread_id = None
