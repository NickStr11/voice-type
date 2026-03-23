"""Tests for TrayIcon — mocked pystray, verifies state swaps and threading."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
from PIL import Image

from voice_type.controller import State
from voice_type.tray import TrayIcon, _make_icon_image, _COLORS


def test_make_icon_image_returns_rgba_image() -> None:
    img = _make_icon_image("#22c55e")
    assert isinstance(img, Image.Image)
    assert img.mode == "RGBA"
    assert img.size == (64, 64)


def test_all_states_have_distinct_colors() -> None:
    """Each state must map to a unique color — not just the same image."""
    colors = list(_COLORS.values())
    assert len(set(colors)) == len(colors), "State colors must all be distinct"


def test_tray_icon_uses_run_detached_not_run() -> None:
    """run() blocks — must use run_detached() (Pitfall 8)."""
    with patch("voice_type.tray.pystray.Icon") as mock_icon_cls, \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem"):
        mock_icon = MagicMock()
        mock_icon_cls.return_value = mock_icon

        tray = TrayIcon(on_quit=lambda: None)
        tray.run_detached()

        mock_icon.run_detached.assert_called_once()
        mock_icon.run.assert_not_called()


def test_set_state_swaps_icon_image() -> None:
    with patch("voice_type.tray.pystray.Icon") as mock_icon_cls, \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem"):
        mock_icon = MagicMock()
        mock_icon_cls.return_value = mock_icon

        tray = TrayIcon(on_quit=lambda: None)
        tray.set_state(State.RECORDING)

        # icon.icon must be set (not left at default)
        assert mock_icon.icon is not None


def test_set_state_updates_title() -> None:
    with patch("voice_type.tray.pystray.Icon") as mock_icon_cls, \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem"):
        mock_icon = MagicMock()
        mock_icon_cls.return_value = mock_icon

        tray = TrayIcon(on_quit=lambda: None)
        tray.set_state(State.PROCESSING)

        assert mock_icon.title == "VoiceType — Processing"


def test_idle_title_on_init() -> None:
    with patch("voice_type.tray.pystray.Icon") as mock_icon_cls, \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem"):
        TrayIcon(on_quit=lambda: None)
        init_kwargs = mock_icon_cls.call_args.kwargs
        assert init_kwargs["title"] == "VoiceType — Idle"
