"""Deliver dictation with checked focus and a reversible clipboard swap.

A successful result means Ctrl+V was sent, not that the destination consumed it.
Snapshots retain text, HTML/RTF and DIB image bytes. Unsupported handle-based
formats are left untouched and reported to the caller for manual recovery.
"""
from __future__ import annotations

import threading
import time
from typing import cast

import win32api  # type: ignore[import-untyped]
import win32clipboard  # type: ignore[import-untyped]
import win32con  # type: ignore[import-untyped]
import win32gui  # type: ignore[import-untyped]
from loguru import logger

_ClipboardSnapshot = list[tuple[int, str | bytes]]
_CLIPBOARD_LOCK = threading.Lock()


class _UnsupportedClipboard(Exception):
    pass


class PasteService:
    """Deliver text and expose a recoverable outcome without logging content."""

    def __init__(self) -> None:
        self.last_error: str | None = None

    def paste(self, text: str, hwnd: int) -> bool:
        """Send Ctrl+V to the captured window, preserving paragraph boundaries."""
        with _CLIPBOARD_LOCK:
            return self._paste(text, hwnd)

    def _paste(self, text: str, hwnd: int) -> bool:
        self.last_error = None
        if not text.strip():
            return self._fail("empty_text")
        try:
            if not hwnd or not win32gui.IsWindow(hwnd):
                return self._fail("no_target")
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.05)
            if win32gui.GetForegroundWindow() != hwnd:
                return self._fail("focus_failed")
        except Exception:
            return self._fail("focus_failed")

        try:
            snapshot, sequence = _replace_clipboard(text)
        except _UnsupportedClipboard:
            return self._fail("unsupported_clipboard")
        except Exception:
            return self._fail("clipboard_unavailable")

        try:
            # Focus can change while waiting for another clipboard owner.
            if win32gui.GetForegroundWindow() != hwnd:
                return self._fail("focus_failed")
            try:
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord("V"), 0, 0, 0)
            finally:
                # Release both keys even when injection fails halfway through.
                try:
                    win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)
                finally:
                    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.15)
            logger.info(f"Paste shortcut sent to HWND {hwnd} — chars: {len(text)}")
            return True
        except Exception:
            return self._fail("paste_failed")
        finally:
            try:
                _restore_clipboard(snapshot, sequence)
            except Exception:
                # Do not report injection failure after sending Ctrl+V: retrying
                # could duplicate text. The recovery text stays with the caller.
                self.last_error = self.last_error or "clipboard_restore_failed"
                logger.warning("Could not restore clipboard after paste")

    def copy(self, text: str) -> bool:
        """Explicit user action: replace clipboard with the retained transcript."""
        with _CLIPBOARD_LOCK:
            self.last_error = None
            if not text.strip():
                return self._fail("empty_text")
            try:
                _set_clipboard_text(text)
            except Exception:
                return self._fail("clipboard_unavailable")
            return True

    def _fail(self, reason: str) -> bool:
        self.last_error = reason
        logger.warning(f"PasteService: {reason}")
        return False


def _snapshot_clipboard() -> _ClipboardSnapshot:
    """Snapshot while clipboard is open; never retain native object handles."""
    formats: list[int] = []
    fmt = cast(int, win32clipboard.EnumClipboardFormats(0))
    while fmt:
        formats.append(fmt)
        fmt = cast(int, win32clipboard.EnumClipboardFormats(fmt))

    snapshot: _ClipboardSnapshot = []
    has_dib = win32con.CF_DIB in formats or win32con.CF_DIBV5 in formats
    for fmt in formats:
        # Windows can regenerate bitmap/palette formats from the preserved DIB.
        if has_dib and fmt in (win32con.CF_BITMAP, win32con.CF_PALETTE):
            continue
        if fmt in (
            win32con.CF_BITMAP, win32con.CF_PALETTE, win32con.CF_METAFILEPICT,
            win32con.CF_ENHMETAFILE, win32con.CF_OWNERDISPLAY,
            win32con.CF_DSPBITMAP, win32con.CF_DSPMETAFILEPICT, win32con.CF_DSPENHMETAFILE,
        ):
            # Even when Get returns metafile bytes, Set expects a native handle,
            # not a global-memory buffer. Refuse before emptying the clipboard.
            raise _UnsupportedClipboard()
        data = win32clipboard.GetClipboardData(fmt)
        if not isinstance(data, (str, bytes)):
            # CF_BITMAP/metafiles return borrowed handles invalid after Empty.
            # CF_HDROP returns paths instead of the original DROPFILES block.
            raise _UnsupportedClipboard()
        snapshot.append((fmt, data))
    return snapshot


def _replace_clipboard(text: str) -> tuple[_ClipboardSnapshot, int]:
    """Snapshot and swap under one clipboard lock to avoid overwriting a copy."""
    win32clipboard.OpenClipboard()
    try:
        snapshot = _snapshot_clipboard()
        win32clipboard.EmptyClipboard()
        try:
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        except Exception:
            _write_snapshot(snapshot)
            raise
        sequence = cast(int, win32clipboard.GetClipboardSequenceNumber())
        return snapshot, sequence
    finally:
        win32clipboard.CloseClipboard()


def _write_snapshot(snapshot: _ClipboardSnapshot) -> None:
    """Caller holds the clipboard lock."""
    win32clipboard.EmptyClipboard()
    for fmt, data in snapshot:
        win32clipboard.SetClipboardData(fmt, data)


def _restore_clipboard(snapshot: _ClipboardSnapshot, sequence: int) -> None:
    win32clipboard.OpenClipboard()
    try:
        # Check while locked: another application may have copied something
        # during the paste delay, even text identical to the dictated text.
        if win32clipboard.GetClipboardSequenceNumber() == sequence:
            _write_snapshot(snapshot)
    finally:
        win32clipboard.CloseClipboard()


def _set_clipboard_text(text: str) -> None:
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()
