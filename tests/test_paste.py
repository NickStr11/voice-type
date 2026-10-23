"""Paste regressions: all clipboard, focus and keyboard calls are mocked."""
# pyright: reportPrivateUsage=false
from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.conftest import WIN32_MOCKS
from voice_type.paste import PasteService


@pytest.fixture(autouse=True)
def clipboard_environment() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    gui = WIN32_MOCKS["win32gui"]
    api = WIN32_MOCKS["win32api"]
    for mock in (clipboard, gui, api):
        mock.reset_mock(return_value=True, side_effect=True)
    for name, value in {
        "CF_UNICODETEXT": 13, "CF_TEXT": 1, "CF_BITMAP": 2, "CF_DIB": 8,
        "CF_DIBV5": 17, "CF_PALETTE": 9, "CF_HDROP": 15,
        "CF_METAFILEPICT": 3, "CF_ENHMETAFILE": 14, "CF_OWNERDISPLAY": 128,
        "CF_DSPBITMAP": 130, "CF_DSPMETAFILEPICT": 131, "CF_DSPENHMETAFILE": 142,
        "VK_CONTROL": 17, "KEYEVENTF_KEYUP": 2,
    }.items():
        setattr(WIN32_MOCKS["win32con"], name, value)
    clipboard.EnumClipboardFormats.side_effect = [13, 0]
    clipboard.GetClipboardData.return_value = "original"
    clipboard.GetClipboardSequenceNumber.return_value = 10
    gui.IsWindow.return_value = True
    gui.GetForegroundWindow.return_value = 12345


def test_empty_text_and_missing_target_do_not_touch_clipboard() -> None:
    svc = PasteService()
    assert svc.paste("", 12345) is False
    assert svc.last_error == "empty_text"
    assert svc.paste("hello", 0) is False
    assert svc.last_error == "no_target"
    WIN32_MOCKS["win32clipboard"].OpenClipboard.assert_not_called()
    WIN32_MOCKS["win32api"].keybd_event.assert_not_called()


def test_destroyed_window_is_reported() -> None:
    WIN32_MOCKS["win32gui"].IsWindow.return_value = False
    svc = PasteService()
    assert svc.paste("hello", 12345) is False
    assert svc.last_error == "no_target"
    WIN32_MOCKS["win32gui"].SetForegroundWindow.assert_not_called()


def test_focus_failure_leaves_clipboard_untouched() -> None:
    WIN32_MOCKS["win32gui"].GetForegroundWindow.return_value = 987
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is False
    assert svc.last_error == "focus_failed"
    WIN32_MOCKS["win32clipboard"].EmptyClipboard.assert_not_called()
    WIN32_MOCKS["win32api"].keybd_event.assert_not_called()


def test_preserves_paragraphs_and_restores_original_clipboard() -> None:
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("First paragraph.\n\nSecond paragraph.", 12345) is True
    WIN32_MOCKS["win32gui"].SetForegroundWindow.assert_called_once_with(12345)
    writes = WIN32_MOCKS["win32clipboard"].SetClipboardData.call_args_list
    assert [call.args for call in writes] == [
        (13, "First paragraph.\n\nSecond paragraph."), (13, "original")
    ]
    assert WIN32_MOCKS["win32api"].keybd_event.call_count == 4
    assert svc.last_error is None


def test_preserves_dib_image_and_html_bytes() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.EnumClipboardFormats.side_effect = [2, 8, 49161, 0]
    clipboard.GetClipboardData.side_effect = [b"dib image bytes", b"html bytes"]
    with patch("voice_type.paste.time.sleep"):
        assert PasteService().paste("hello", 12345) is True
    assert [call.args for call in clipboard.SetClipboardData.call_args_list] == [
        (13, "hello"), (8, b"dib image bytes"), (49161, b"html bytes")
    ]
    assert [call.args for call in clipboard.GetClipboardData.call_args_list] == [(8,), (49161,)]


def test_unreadable_format_is_dropped_instead_of_blocking_paste() -> None:
    # Explorer copy: EnterpriseDataProtectionId has a NULL handle and raises.
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.EnumClipboardFormats.side_effect = [13, 49273, 0]
    clipboard.GetClipboardData.side_effect = ["original", RuntimeError("GetClipboardData")]
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is True
    assert svc.last_error is None
    assert [call.args for call in clipboard.SetClipboardData.call_args_list] == [
        (13, "hello"), (13, "original")
    ]


def test_explorer_file_copy_is_restored_as_dropfiles() -> None:
    # Explorer copy: CF_HDROP reads back as a path tuple, not restorable bytes.
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.EnumClipboardFormats.side_effect = [15, 0]
    clipboard.GetClipboardData.return_value = ("C:\\a.txt", "C:\\б.pdf")
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is True
    assert svc.last_error is None
    expected = (
        b"\x14\x00\x00\x00" + b"\x00" * 12 + b"\x01\x00\x00\x00"
        + "C:\\a.txt\0C:\\б.pdf\0\0".encode("utf-16-le")
    )
    assert [call.args for call in clipboard.SetClipboardData.call_args_list] == [
        (13, "hello"), (15, expected)
    ]


def test_clipboard_briefly_busy_is_retried() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.OpenClipboard.side_effect = [RuntimeError("busy"), None, None]
    with patch("voice_type.paste.time.sleep"):
        assert PasteService().paste("hello", 12345) is True


def test_unsupported_handle_does_not_destroy_existing_clipboard() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.EnumClipboardFormats.side_effect = [2, 0]
    clipboard.GetClipboardData.return_value = 9981  # borrowed native bitmap handle
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is False
    assert svc.last_error == "unsupported_clipboard"
    clipboard.EmptyClipboard.assert_not_called()
    WIN32_MOCKS["win32api"].keybd_event.assert_not_called()


def test_metafile_bytes_are_not_treated_as_restorable_global_memory() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.EnumClipboardFormats.side_effect = [14, 0]
    clipboard.GetClipboardData.return_value = b"metafile bits"
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is False
    assert svc.last_error == "unsupported_clipboard"
    clipboard.EmptyClipboard.assert_not_called()


def test_does_not_restore_over_newer_clipboard_copy() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.GetClipboardSequenceNumber.side_effect = [10, 11]
    with patch("voice_type.paste.time.sleep"):
        assert PasteService().paste("hello", 12345) is True
    clipboard.SetClipboardData.assert_called_once_with(13, "hello")
    assert clipboard.EmptyClipboard.call_count == 1


def test_restores_empty_clipboard_to_empty() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.EnumClipboardFormats.side_effect = [0]
    with patch("voice_type.paste.time.sleep"):
        assert PasteService().paste("hello", 12345) is True
    clipboard.SetClipboardData.assert_called_once_with(13, "hello")
    assert clipboard.EmptyClipboard.call_count == 2


def test_focus_stolen_during_clipboard_swap_never_sends_keys() -> None:
    WIN32_MOCKS["win32gui"].GetForegroundWindow.side_effect = [12345, 678]
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is False
    assert svc.last_error == "focus_failed"
    WIN32_MOCKS["win32api"].keybd_event.assert_not_called()
    WIN32_MOCKS["win32clipboard"].SetClipboardData.assert_any_call(13, "original")


def test_keyboard_failure_releases_modifiers_and_restores_clipboard() -> None:
    api = WIN32_MOCKS["win32api"]
    api.keybd_event.side_effect = [None, RuntimeError("injection failed"), None, None]
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is False
    assert svc.last_error == "paste_failed"
    assert [call.args for call in api.keybd_event.call_args_list][-2:] == [
        (ord("V"), 0, 2, 0), (17, 0, 2, 0)
    ]
    WIN32_MOCKS["win32clipboard"].SetClipboardData.assert_any_call(13, "original")


def test_clipboard_busy_is_recoverable_without_keyboard_input() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.OpenClipboard.side_effect = RuntimeError("busy")
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is False
    assert svc.last_error == "clipboard_unavailable"
    clipboard.EmptyClipboard.assert_not_called()
    WIN32_MOCKS["win32api"].keybd_event.assert_not_called()


def test_failed_clipboard_write_attempts_original_restore() -> None:
    clipboard = WIN32_MOCKS["win32clipboard"]
    clipboard.SetClipboardData.side_effect = [RuntimeError("write failed"), None]
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        assert svc.paste("hello", 12345) is False
    clipboard.SetClipboardData.assert_any_call(13, "original")
    WIN32_MOCKS["win32api"].keybd_event.assert_not_called()


def test_restore_failure_does_not_claim_injection_failed() -> None:
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"), patch(
        "voice_type.paste._restore_clipboard", side_effect=RuntimeError("busy")
    ):
        assert svc.paste("hello", 12345) is True
    assert svc.last_error == "clipboard_restore_failed"


def test_explicit_copy_keeps_transcript_without_keyboard_or_focus() -> None:
    svc = PasteService()
    assert svc.copy("First.\n\nSecond.") is True
    WIN32_MOCKS["win32clipboard"].SetClipboardData.assert_called_once_with(13, "First.\n\nSecond.")
    WIN32_MOCKS["win32gui"].SetForegroundWindow.assert_not_called()
    WIN32_MOCKS["win32api"].keybd_event.assert_not_called()


def test_copy_failure_is_reported() -> None:
    WIN32_MOCKS["win32clipboard"].OpenClipboard.side_effect = RuntimeError("busy")
    svc = PasteService()
    assert svc.copy("hello") is False
    assert svc.last_error == "clipboard_unavailable"
