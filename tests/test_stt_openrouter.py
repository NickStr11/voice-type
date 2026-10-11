"""Tests for the OpenRouter cloud STT rescue path."""
from __future__ import annotations

import base64
import io
import wave
from unittest.mock import patch

from voice_type.openrouter import OpenRouterError
from voice_type.stt_openrouter import OpenRouterSTTClient


async def test_recognize_sends_wav_and_returns_text() -> None:
    audio = b"\x01\x00" * 16000
    with patch("voice_type.stt_openrouter.openrouter.chat", return_value="привет") as mock_chat:
        result = await OpenRouterSTTClient().recognize(audio)

    assert result == "привет"
    model, content, _timeout = mock_chat.call_args.args
    assert model == "google/gemini-2.5-flash-lite"
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
