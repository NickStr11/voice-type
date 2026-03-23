"""Paste service — delivers transcribed text into the originally active window.

Design decisions:
- pywin32 (NOT pyautogui): pyautogui adds 200ms+ delay and fails silently
  with Unicode/Russian text in some apps. pywin32 is lower-latency and
  handles CF_UNICODETEXT natively.
- SetForegroundWindow + 50ms sleep: the Win32 focus change is asynchronous —
  keystrokes sent immediately after SetForegroundWindow go to the wrong window.
  50ms is the minimum reliable wait confirmed in Superwhisper production reports.
- Clipboard save/restore: preserves user's clipboard content (PST-02 / Pitfall 6).
  GetClipboardData raises TypeError if clipboard has non-text content (images,
  files) — catch it and skip restoration for those cases.
- hwnd=0: indicates window tracking failed or window is gone. Log and skip.
"""
from __future__ import annotations

import time

import win32api  # type: ignore[import-untyped]
import win32clipboard  # type: ignore[import-untyped]
import win32con  # type: ignore[import-untyped]
import win32gui  # type: ignore[import-untyped]
from loguru import logger


class PasteService:
    """Delivers text into a target window via clipboard + Ctrl+V."""

    def paste(self, text: str, hwnd: int) -> None:
        """Paste text into the window identified by hwnd.

        Sequence:
            1. Save clipboard
            2. Restore focus to hwnd via SetForegroundWindow
            3. Write text to clipboard
            4. Send Ctrl+V
            5. Restore original clipboard

        Args:
            text: Text to paste. Must be non-empty.
            hwnd: Window handle captured at recording stop (REC-04).
                  Use 0 to skip paste (window not available).
        """
        if not text:
            logger.warning("PasteService.paste() called with empty text — skipping")
            return

        if hwnd == 0:
            logger.warning(
                "PasteService.paste(): hwnd=0 — no target window captured. "
                f"Text was: {repr(text[:60])}"
            )
            return

        # Step 1: Save existing clipboard content
        original_clip: str | None = _get_clipboard_text()

        try:
            # Step 2: Restore focus to the original window (PST-02)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.05)  # focus propagation — SetForegroundWindow is async

            # Step 3+4: Paste text block by block, using Shift+Enter for newlines
            # This prevents Telegram/Discord/etc from sending on Enter
            parts = text.split("\n")
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                _set_clipboard_text(part)
                # Ctrl+V to paste this block
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)  # pyright: ignore[reportUnknownMemberType]
                win32api.keybd_event(ord("V"), 0, 0, 0)  # pyright: ignore[reportUnknownMemberType]
                win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)  # pyright: ignore[reportUnknownMemberType]
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)  # pyright: ignore[reportUnknownMemberType]
                time.sleep(0.03)
                # Shift+Enter for newline (not Enter which sends message)
                if i < len(parts) - 1:
                    win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)  # pyright: ignore[reportUnknownMemberType]
                    win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)  # pyright: ignore[reportUnknownMemberType]
                    win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)  # pyright: ignore[reportUnknownMemberType]
                    win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)  # pyright: ignore[reportUnknownMemberType]
                    time.sleep(0.02)
            time.sleep(0.05)

            logger.info(f"Pasted into HWND {hwnd}: {repr(text[:60])}")

        finally:
            # Step 5: Restore original clipboard (always attempt, even on error)
            if original_clip is not None:
                _set_clipboard_text(original_clip)
            # If original was None (non-text content), leave clipboard as-is.
            # The user's image/file reference is already gone — no way to restore.


def _get_clipboard_text() -> str | None:
    """Return current clipboard text, or None if clipboard has non-text content."""
    try:
        win32clipboard.OpenClipboard()  # pyright: ignore[reportUnknownMemberType]
        try:
            return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))  # pyright: ignore[reportUnknownMemberType]
        except TypeError:
            # No text in clipboard (image, file, or empty)
            return None
    except Exception as exc:
        logger.debug(f"Could not read clipboard: {exc}")
        return None
    finally:
        try:
            win32clipboard.CloseClipboard()  # pyright: ignore[reportUnknownMemberType]
        except Exception:
            pass


def _set_clipboard_text(text: str) -> None:
    """Write text to clipboard as CF_UNICODETEXT."""
    win32clipboard.OpenClipboard()  # pyright: ignore[reportUnknownMemberType]
    try:
        win32clipboard.EmptyClipboard()  # pyright: ignore[reportUnknownMemberType]
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)  # pyright: ignore[reportUnknownMemberType]
    finally:
        win32clipboard.CloseClipboard()  # pyright: ignore[reportUnknownMemberType]
