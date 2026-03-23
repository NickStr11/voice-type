"""Shared test fixtures and early mock setup for voice_type tests.

Win32 modules (win32api, win32clipboard, win32con, win32gui) are Windows-only
and don't exist in the test environment. We mock them in sys.modules BEFORE
any test module imports voice_type.paste or voice_type.tray, so that module-level
imports in those files resolve to the shared mocks.

All test modules that need to assert on win32 calls should import from here:
    from tests.conftest import WIN32_MOCKS
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# Install win32 mocks early -- before any test file imports paste.py or tray.py
WIN32_MOCKS: dict[str, MagicMock] = {}
for _mod in ("win32api", "win32clipboard", "win32con", "win32gui"):
    if _mod not in sys.modules:
        mock = MagicMock()
        sys.modules[_mod] = mock
        WIN32_MOCKS[_mod] = mock
    else:
        WIN32_MOCKS[_mod] = sys.modules[_mod]  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def reset_win32_mocks() -> None:
    """Reset all win32 mocks before each test to prevent state leakage."""
    for mock in WIN32_MOCKS.values():
        mock.reset_mock()
