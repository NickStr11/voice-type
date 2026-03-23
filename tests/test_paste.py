"""Tests for PasteService -- mocked win32 modules (Windows-only at runtime)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.conftest import WIN32_MOCKS

from voice_type.paste import PasteService, _get_clipboard_text, _set_clipboard_text  # noqa: E402


def test_paste_empty_text_skips(caplog: pytest.LogCaptureFixture) -> None:
    svc = PasteService()
    svc.paste("", hwnd=12345)
    WIN32_MOCKS["win32clipboard"].OpenClipboard.assert_not_called()
    WIN32_MOCKS["win32gui"].SetForegroundWindow.assert_not_called()


def test_paste_hwnd_zero_skips(caplog: pytest.LogCaptureFixture) -> None:
    svc = PasteService()
    svc.paste("hello", hwnd=0)
    WIN32_MOCKS["win32gui"].SetForegroundWindow.assert_not_called()


def test_paste_calls_set_foreground_window() -> None:
    WIN32_MOCKS["win32clipboard"].GetClipboardData.return_value = "original"
    svc = PasteService()
    with patch("voice_type.paste.time.sleep"):
        svc.paste("new text", hwnd=99999)
    WIN32_MOCKS["win32gui"].SetForegroundWindow.assert_called_once_with(99999)


def test_paste_restores_clipboard_after_paste() -> None:
    """Clipboard content must be restored after paste (PST-02 / Pitfall 6)."""
    WIN32_MOCKS["win32clipboard"].GetClipboardData.return_value = "original url"
    svc = PasteService()
    set_calls: list[str] = []

    def capture_set(text: str) -> None:
        set_calls.append(text)

    with patch("voice_type.paste._set_clipboard_text", side_effect=capture_set), \
         patch("voice_type.paste._get_clipboard_text", return_value="original url"), \
         patch("voice_type.paste.time.sleep"):
        svc.paste("transcribed text", hwnd=12345)

    # First call sets new text; second call restores original
    assert set_calls[0] == "transcribed text"
    assert set_calls[1] == "original url"


def test_paste_skips_restore_when_clipboard_was_non_text() -> None:
    """If clipboard had non-text content, don't attempt restore."""
    set_calls: list[str] = []

    def capture_set(text: str) -> None:
        set_calls.append(text)

    with patch("voice_type.paste._set_clipboard_text", side_effect=capture_set), \
         patch("voice_type.paste._get_clipboard_text", return_value=None), \
         patch("voice_type.paste.time.sleep"):
        PasteService().paste("hello", hwnd=12345)

    # Only one set call -- no restore
    assert len(set_calls) == 1
    assert set_calls[0] == "hello"
