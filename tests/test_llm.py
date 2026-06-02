"""Tests for LLMClient — mocked Gemini, verifies timeout fallback and prompt."""
from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from voice_type.cleanup import fast_clean
from voice_type.llm import LLMClient


@pytest.fixture(autouse=True)
def _gemini_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default tests through the AI Studio (api_key) backend so the mocked
    genai.Client gets constructed. Individual tests override as needed."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def test_clean_returns_cleaned_text() -> None:
    with patch("voice_type.llm.genai.Client") as mock_cls:
        response = MagicMock()
        response.text = "Привет, мир."
        mock_cls.return_value.models.generate_content.return_value = response

        client = LLMClient()
        result = client.clean("привет мир ну вот")
        assert result == "Привет, мир."


def test_clean_timeout_falls_back_to_fast_clean() -> None:
    """When Gemini stalls, fall back to the regex fast_clean (LLM-02)."""
    with patch("voice_type.llm.genai.Client"):
        client = LLMClient()

        # Patch concurrent.futures to simulate timeout
        with patch.object(concurrent.futures.Future, "result") as mock_result:
            mock_result.side_effect = concurrent.futures.TimeoutError()
            result = client.clean("raw stt text")
            assert result == fast_clean("raw stt text")


def test_clean_exception_falls_back_to_fast_clean() -> None:
    """Any Gemini exception falls back to the regex fast_clean."""
    with patch("voice_type.llm.genai.Client") as mock_cls:
        mock_cls.return_value.models.generate_content.side_effect = RuntimeError("API error")

        client = LLMClient()
        result = client.clean("some text")
        assert result == fast_clean("some text")


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


def test_uses_api_key_backend_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """A GEMINI_API_KEY routes through the free AI Studio backend, not Vertex."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-fake-key")
    with patch("voice_type.llm.genai.Client") as mock_cls:
        client = LLMClient()
        assert client.available is True
        assert mock_cls.call_args.kwargs.get("api_key") == "AIza-fake-key"


def test_unavailable_without_key_or_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """No GEMINI_API_KEY and no GCP project → cleanup disabled; clean() returns
    raw text unchanged so the caller can fall back to regex fast_clean."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    with patch("voice_type.llm.genai.Client") as mock_cls:
        client = LLMClient()
        assert client.available is False
        # No client → cleanup still formats locally via regex fast_clean.
        assert client.clean("раз два три") == fast_clean("раз два три")
        mock_cls.assert_not_called()
