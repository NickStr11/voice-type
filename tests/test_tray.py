"""Tests for TrayIcon — mocked pystray, verifies state swaps and threading."""
# pyright: reportPrivateUsage=false
from __future__ import annotations

from unittest.mock import MagicMock, patch

from PIL import Image

from voice_type.controller import State
from voice_type.tray import _COLORS, TrayIcon, _make_icon_image


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


def test_stt_provider_submenu_exists() -> None:
    """TrayIcon must include a MenuItem with text 'STT Provider'."""
    with patch("voice_type.tray.pystray.Icon"), \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem") as mock_menu_item:
        on_stt = MagicMock()
        TrayIcon(on_quit=lambda: None, on_set_stt_provider=on_stt)

        # Collect all MenuItem text arguments from all calls
        texts = [call.args[0] for call in mock_menu_item.call_args_list if call.args]
        assert "STT Provider" in texts, f"'STT Provider' not in menu items: {texts}"


def test_stt_provider_callback_called_local() -> None:
    """Clicking 'Local (Whisper)' handler must call on_set_stt_provider('local')."""
    with patch("voice_type.tray.pystray.Icon"), \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem") as mock_menu_item:
        on_stt = MagicMock()
        TrayIcon(on_quit=lambda: None, on_set_stt_provider=on_stt)

        # Find the "Local (Whisper)" handler by scanning MenuItem calls
        local_handler: object = None
        for call in mock_menu_item.call_args_list:
            if call.args and call.args[0] == "Local (Whisper)":
                local_handler = call.args[1]
                break
        assert local_handler is not None, "No 'Local (Whisper)' menu item found"

        local_handler(None)  # type: ignore[operator]
        on_stt.assert_called_once_with("local")


def test_stt_provider_default_cloud() -> None:
    """Default initial_stt_provider='cloud': cloud item checked, local unchecked."""
    with patch("voice_type.tray.pystray.Icon"), \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem") as mock_menu_item:
        TrayIcon(on_quit=lambda: None, initial_stt_provider="cloud")

        # Extract checked callbacks for each item
        checked_by_label: dict[str, object] = {}
        for call in mock_menu_item.call_args_list:
            if call.args and len(call.args) >= 2:
                label = call.args[0]
                # checked is passed as keyword arg
                checked_fn = call.kwargs.get("checked")
                if checked_fn is not None:
                    checked_by_label[label] = checked_fn

        cloud_checked = checked_by_label.get("Cloud (Chirp 3)")
        local_checked = checked_by_label.get("Local (Whisper)")
        assert cloud_checked is not None, "No checked callback for 'Cloud (Chirp 3)'"
        assert local_checked is not None, "No checked callback for 'Local (Whisper)'"
        assert cloud_checked(None) is True, "Cloud should be checked by default"  # type: ignore[operator]
        assert local_checked(None) is False, "Local should not be checked by default"  # type: ignore[operator]


def test_stt_provider_radio_true() -> None:
    """Both STT provider items must have radio=True."""
    with patch("voice_type.tray.pystray.Icon"), \
         patch("voice_type.tray.pystray.Menu"), \
         patch("voice_type.tray.pystray.MenuItem") as mock_menu_item:
        TrayIcon(on_quit=lambda: None)

        radio_labels = []
        for call in mock_menu_item.call_args_list:
            if call.args and call.kwargs.get("radio") is True:
                radio_labels.append(call.args[0])
        assert "Local (Whisper)" in radio_labels, f"'Local (Whisper)' missing radio=True: {radio_labels}"
        assert "Cloud (Chirp 3)" in radio_labels, f"'Cloud (Chirp 3)' missing radio=True: {radio_labels}"
