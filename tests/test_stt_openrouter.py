"""Tests for the OpenRouter cloud STT rescue path."""
from __future__ import annotations

import base64
import io
import wave
from unittest.mock import patch

import pytest

from voice_type.openrouter import OpenRouterError
from voice_type.stt_openrouter import OpenRouterSTTClient


async def test_recognize_sends_wav_and_returns_text() -> None:
    audio = b"\x01\x00" * 16000
    with patch("voice_type.stt_openrouter.openrouter.chat", return_value="привет") as mock_chat:
        result = await OpenRouterSTTClient().recognize(audio)

    assert result == "привет"
    model, content, _timeout = mock_chat.call_args.args
    assert model == "google/gemini-3.1-flash-lite"
    wav_b64 = content[1]["input_audio"]["data"]
    with wave.open(io.BytesIO(base64.b64decode(wav_b64))) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.readframes(wav.getnframes()) == audio


async def test_recognize_failure_returns_empty() -> None:
    with patch("voice_type.stt_openrouter.openrouter.chat", side_effect=OpenRouterError(402, "no credits")):
        assert await OpenRouterSTTClient().recognize(b"\x01\x00" * 1600) == ""


async def test_recognize_empty_audio_skips_request() -> None:
    with patch("voice_type.stt_openrouter.openrouter.chat") as mock_chat:
        assert await OpenRouterSTTClient().recognize(b"") == ""
    mock_chat.assert_not_called()


async def test_rate_limited_model_falls_through_and_is_paused() -> None:
    calls: list[str] = []

    def fake_chat(model: str, _content: object, _timeout: float) -> str:
        calls.append(model)
        if model == "google/gemini-3.1-flash-lite":
            raise OpenRouterError(429, "Provider returned error")
        return "текст"

    client = OpenRouterSTTClient()
    with patch("voice_type.stt_openrouter.openrouter.chat", side_effect=fake_chat):
        assert await client.recognize(b"\x01\x00" * 1600) == "текст"
        assert await client.recognize(b"\x01\x00" * 1600) == "текст"

    # Second dictation skips the paused model and goes straight to the next one.
    assert calls == ["google/gemini-3.1-flash-lite", "xiaomi/mimo-v2.6-flash", "xiaomi/mimo-v2.6-flash"]


async def test_model_chain_from_env_and_vocabulary_in_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICETYPE_CLOUD_STT_MODEL", "a/one, b/two")
    replies = [OpenRouterError(None, "boom"), "ok"]
    with patch("voice_type.stt_openrouter.openrouter.chat", side_effect=replies) as mock_chat:
        assert await OpenRouterSTTClient(vocabulary="PharmOrder, Codex").recognize(b"\x01\x00" * 1600) == "ok"

    assert [c.args[0] for c in mock_chat.call_args_list] == ["a/one", "b/two"]
    assert "PharmOrder, Codex" in mock_chat.call_args.args[1][0]["text"]
