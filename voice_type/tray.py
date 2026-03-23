"""System tray icon — pystray wrapper with idle/recording/processing states.

Design decisions:
- Pre-generate icons at init: PIL image generation is slow (~5ms each).
  Generating on every state change would add visible lag. Three icons at
  startup, then just swap the reference.
- run_detached(): On Windows, pystray is safe to run in any thread.
  run_detached() starts the icon in its own thread and returns immediately,
  letting main.py own the event loop. Do NOT use run() — it blocks.
- set_state() is thread-safe: pystray icon.icon property assignment is
  documented as thread-safe on Windows. No lock needed.
- Quit menu item: the only menu action in Phase 1. Calls the on_quit callback
  which enqueues 'shutdown' into the controller queue.
"""
from __future__ import annotations

from typing import Callable

import pystray  # type: ignore[import-untyped]
from PIL import Image, ImageDraw
from loguru import logger

from voice_type.states import State

# Icon size in pixels (system tray uses 16x16 or 32x32 — we generate larger
# and let Windows scale down; avoids blurriness on high-DPI displays)
_ICON_SIZE: int = 64

# State colors
_COLORS: dict[State, str] = {
    State.IDLE: "#22c55e",       # green — ready
    State.RECORDING: "#ef4444",  # red — recording in progress
    State.PROCESSING: "#eab308", # yellow — STT + LLM in progress
}


def _make_icon_image(color: str) -> Image.Image:
    """Create a filled circle on transparent background."""
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        (margin, margin, _ICON_SIZE - margin, _ICON_SIZE - margin),
        fill=color,
    )
    return img


class TrayIcon:
    """System tray icon with three visual states (SYS-01, REC-03).

    Usage (from main.py):
        tray = TrayIcon(on_quit=controller.shutdown)
        tray.run_detached()   # non-blocking
        # ... later, state changes ...
        tray.set_state(State.RECORDING)
    """

    def __init__(self, on_quit: Callable[[], None], on_set_mode: Callable[[str], None] | None = None) -> None:
        # Pre-generate all state icons at startup
        self._icons: dict[State, Image.Image] = {
            state: _make_icon_image(color)
            for state, color in _COLORS.items()
        }
        self._current_mode = "full"

        def _set_mode(mode: str) -> Callable:
            def handler(_: object) -> None:
                self._current_mode = mode
                if on_set_mode is not None:
                    on_set_mode(mode)
                logger.info(f"Mode: {mode}")
            return handler

        menu = pystray.Menu(
            pystray.MenuItem("Fast (regex)", _set_mode("fast"), checked=lambda _: self._current_mode == "fast"),
            pystray.MenuItem("Local (Ollama)", _set_mode("local"), checked=lambda _: self._current_mode == "local"),
            pystray.MenuItem("Full (Gemini)", _set_mode("full"), checked=lambda _: self._current_mode == "full"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit VoiceType", lambda: on_quit()),
        )

        self._icon = pystray.Icon(
            name="VoiceType",
            icon=self._icons[State.IDLE],
            title="VoiceType — Idle",
            menu=menu,
        )
        logger.info("TrayIcon initialized")

    def run_detached(self) -> None:
        """Start the tray icon in its own thread. Non-blocking."""
        self._icon.run_detached()  # pyright: ignore[reportUnknownMemberType]
        logger.info("TrayIcon running (detached)")

    def set_state(self, state: State) -> None:
        """Swap the tray icon to reflect the new pipeline state.

        Thread-safe — can be called from any thread.

        Args:
            state: New application state (IDLE / RECORDING / PROCESSING).
        """
        self._icon.icon = self._icons[state]
        self._icon.title = f"VoiceType — {state.name.capitalize()}"
        logger.debug(f"TrayIcon state: {state.name}")

    def stop(self) -> None:
        """Stop the tray icon. Called during shutdown."""
        self._icon.stop()
        logger.info("TrayIcon stopped")
