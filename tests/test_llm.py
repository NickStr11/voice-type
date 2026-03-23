"""Tests for LLMClient — mocked Gemini, verifies timeout fallback and prompt."""
from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from voice_type.llm import LLMClient


def test_clean_returns_cleaned_text() -> None:
    with patch("voice_type.llm.genai.Client") as mock_cls:
        response = MagicMock()
        response.text = "Привет, мир."
        mock_cls.return_value.models.generate_content.return_value = response

        client = LLMClient()
        result = client.clean("привет мир ну вот")
        assert result == "Привет, мир."


def test_clean_timeout_returns_raw_text() -> None:
    """When Gemini stalls, fallback to raw STT text (LLM-02)."""
    with patch("voice_type.llm.genai.Client"):
        client = LLMClient()

        # Patch concurrent.futures to simulate timeout
        with patch.object(concurrent.futures.Future, "result") as mock_result:
            mock_result.side_effect = concurrent.futures.TimeoutError()
            result = client.clean("raw stt text")
            assert result == "raw stt text"


def test_clean_exception_returns_raw_text() -> None:
    """Any Gemini exception falls back to raw text."""
    with patch("voice_type.llm.genai.Client") as mock_cls:
        mock_cls.return_value.models.generate_content.side_effect = RuntimeError("API error")

        client = LLMClient()
        result = client.clean("some text")
        assert result == "some text"


def test_clean_empty_string_returns_empty() -> None:
    """Empty input bypasses API call entirely."""
    with patch("voice_type.llm.genai.Client") as mock_cls:
        client = LLMClient()
        result = client.clean("")
        mock_cls.return_value.models.generate_content.assert_not_called()
        assert result == ""


def test_clean_whitespace_only_returns_unchanged() -> None:
    with patch("voice_type.llm.genai.Client") as mock_cls:
        client = LLMClient()
        result = client.clean("   ")
        mock_cls.return_value.models.generate_content.assert_not_called()
        assert result == "   "


def test_clean_thinking_budget_zero() -> None:
    """Verify thinking is disabled — saves 1-3s latency (Pitfall 5)."""
    with patch("voice_type.llm.genai.Client") as mock_cls:
        response = MagicMock()
        response.text = "cleaned"
        mock_cls.return_value.models.generate_content.return_value = response

        client = LLMClient()
        client.clean("test input")

        call_kwargs = mock_cls.return_value.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.thinking_config.thinking_budget == 0
