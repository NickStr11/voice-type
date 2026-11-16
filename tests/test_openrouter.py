"""Tests for OpenRouter provider routing."""
from __future__ import annotations

from voice_type import openrouter


def test_llama_cleanup_pins_groq_with_fallbacks() -> None:
    prefs = openrouter.provider_preferences("meta-llama/llama-3.3-70b-instruct")
    assert prefs["order"] == ["Groq"]
    assert prefs["allow_fallbacks"] is True


def test_unpinned_model_uses_latency_sort() -> None:
    assert openrouter.provider_preferences("google/gemini-3.1-flash-lite") == {"sort": "latency"}
