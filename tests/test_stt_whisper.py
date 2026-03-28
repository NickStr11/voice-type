"""Tests for WhisperSTTClient — mocked faster-whisper, verifies lazy loading and audio conversion."""
# pyright: reportPrivateUsage=false
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from voice_type.config import AppConfig
from voice_type.stt_whisper import WhisperSTTClient


@pytest.fixture()
def config() -> AppConfig:
    return AppConfig(
        hotkey="<ctrl>+<alt>+r",
        gcp_credentials_path=None,
        gcp_project_id="",
        stt_provider="local",
        whisper_model="large-v3-turbo",
    )


@pytest.fixture()
def mock_whisper_model():  # type: ignore[no-untyped-def]
    with patch("voice_type.stt_whisper.WhisperModel") as MockModel:
        model_instance = MagicMock()
        MockModel.return_value = model_instance
        # segments is a generator-like iterable
        seg1 = MagicMock()
        seg1.text = " Hello "
        seg2 = MagicMock()
        seg2.text = " world "
        info = MagicMock()
        info.language = "en"
        info.language_probability = 0.95
        model_instance.transcribe.return_value = (iter([seg1, seg2]), info)
        yield MockModel, model_instance


def test_model_not_loaded_at_init(config: AppConfig) -> None:
    """WhisperSTTClient.__init__ must NOT load the model — lazy loading only."""
    with patch("voice_type.stt_whisper.WhisperModel") as MockModel:
        client = WhisperSTTClient(config)
        MockModel.assert_not_called()
        assert client._model is None


async def test_recognize_empty_returns_empty(config: AppConfig) -> None:
    """Empty audio bytes returns empty string without error."""
    with patch("voice_type.stt_whisper.WhisperModel"):
        client = WhisperSTTClient(config)
        result = await client.recognize(b"")
    assert result == ""


async def test_recognize_returns_transcript(
    config: AppConfig, mock_whisper_model: tuple[MagicMock, MagicMock]
) -> None:
    """recognize() returns joined text from transcribe() segments."""
    _, model_instance = mock_whisper_model
    client = WhisperSTTClient(config)
    audio_bytes = np.zeros(16000, dtype=np.int16).tobytes()
    result = await client.recognize(audio_bytes)
    assert result == "Hello world"


def test_audio_conversion_correct() -> None:
    """int16 max maps to ~1.0, int16 min maps to -1.0 float32."""
    max_int16 = np.array([32767], dtype=np.int16).tobytes()
    min_int16 = np.array([-32768], dtype=np.int16).tobytes()

    float_max = np.frombuffer(max_int16, dtype=np.int16).astype(np.float32) / 32768.0
    float_min = np.frombuffer(min_int16, dtype=np.int16).astype(np.float32) / 32768.0

    assert abs(float_max[0] - 1.0) < 0.001
    assert abs(float_min[0] - (-1.0)) < 0.001


async def test_transcribe_called_with_auto_detect(
    config: AppConfig, mock_whisper_model: tuple[MagicMock, MagicMock]
) -> None:
    """transcribe() must be called with language=None for auto-detection."""
    _, model_instance = mock_whisper_model
    client = WhisperSTTClient(config)
    audio_bytes = np.zeros(16000, dtype=np.int16).tobytes()
    await client.recognize(audio_bytes)
    call_kwargs = model_instance.transcribe.call_args.kwargs
    assert call_kwargs.get("language") is None


async def test_transcribe_called_with_vad_filter(
    config: AppConfig, mock_whisper_model: tuple[MagicMock, MagicMock]
) -> None:
    """transcribe() must be called with vad_filter=True."""
    _, model_instance = mock_whisper_model
    client = WhisperSTTClient(config)
    audio_bytes = np.zeros(16000, dtype=np.int16).tobytes()
    await client.recognize(audio_bytes)
    call_kwargs = model_instance.transcribe.call_args.kwargs
    assert call_kwargs.get("vad_filter") is True
