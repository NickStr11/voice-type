"""Tests for main-process logging setup."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from voice_type.main import configure_logging, effective_file_log_level


def test_configure_logging_defaults_to_info_with_rotation(tmp_path: Path) -> None:
    with patch("voice_type.main.logger.add") as mock_add:
        configure_logging(tmp_path, log_level="INFO")

    mock_add.assert_called_once()
    _, kwargs = mock_add.call_args
    assert kwargs["level"] == "INFO"
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["rotation"] == "5 MB"
    assert kwargs["retention"] == "14 days"


def test_transcript_logging_forces_debug_file_log_level() -> None:
    assert effective_file_log_level("INFO", log_transcripts=True) == "DEBUG"
    assert effective_file_log_level("WARNING", log_transcripts=False) == "WARNING"
