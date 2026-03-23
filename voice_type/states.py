"""Application states shared across controller and tray modules.

Placed in a separate module to avoid circular imports between
controller.py (which imports TrayIcon) and tray.py (which needs State).
"""
from __future__ import annotations

from enum import Enum, auto


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()
