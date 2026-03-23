"""Global hotkey listener for VoiceType.

Uses pynput GlobalHotKeys for toggle-mode hotkey (press once to start,
press again to stop). This is simpler than push-to-talk and better for
long dictation sessions where holding a key is awkward.

CRITICAL: suppress=True is NOT used and MUST NOT be added.
  suppress=True on a pynput Listener freezes ALL keyboard input OS-wide
  (confirmed bug: https://github.com/moses-palmer/pynput/issues/232).
  The hotkey will pass through to other applications — this is intentional.
  Ctrl+Alt+R is chosen as default precisely because it does not conflict
  with common application shortcuts.

Win+key hotkeys are NOT supported:
  Windows shell intercepts Win+key combinations before pynput's low-level
  keyboard hook receives them. Use Ctrl+Alt+key combinations only.
  (See STATE.md — Hotkey: Use Ctrl+Alt+key default decision)
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Optional

from pynput import keyboard  # type: ignore[import-untyped]

from voice_type.config import AppConfig


class HotkeyListener:
    """Listens for a global hotkey and fires a toggle callback on each press.

    Runs pynput GlobalHotKeys in a daemon thread. The callback is called
    from the pynput listener thread — callers must be thread-safe.

    Usage:
        def on_toggle() -> None:
            print("hotkey pressed")

        listener = HotkeyListener(config, on_toggle)
        listener.start()
        # ... app runs ...
        listener.stop()
    """

    def __init__(self, config: AppConfig, on_toggle: Callable[[], None]) -> None:
        """Initialise the listener.

        Args:
            config: AppConfig instance. config.hotkey must be a pynput
                    GlobalHotKeys-compatible key combination string,
                    e.g. "<ctrl>+<alt>+r".
            on_toggle: Callable with no arguments. Called each time the
                       hotkey is pressed. Must be thread-safe — it is
                       invoked from pynput's internal listener thread.
        """
        self._config = config
        self._on_toggle = on_toggle
        self._hotkeys: Optional[keyboard.GlobalHotKeys] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the hotkey listener in a daemon background thread.

        Raises:
            RuntimeError: If the listener is already running.
            ValueError: If config.hotkey is not a valid pynput key combination.
        """
        if self._hotkeys is not None:
            raise RuntimeError("HotkeyListener.start() called while already running")

        # GlobalHotKeys accepts a dict mapping key-combo string -> callback.
        # IMPORTANT: suppress is not passed -- default is False.
        # Do NOT add suppress=True here. See module docstring.
        hotkeys = keyboard.GlobalHotKeys(
            {self._config.hotkey: self._on_toggle}
        )
        self._hotkeys = hotkeys

        thread = threading.Thread(
            target=hotkeys.run,  # blocks until hotkeys.stop() is called
            daemon=True,
            name="HotkeyListener",
        )
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        """Stop the hotkey listener and release resources.

        No-op if the listener is not running.
        """
        if self._hotkeys is not None:
            self._hotkeys.stop()
            self._hotkeys = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
