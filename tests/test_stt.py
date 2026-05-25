"""Tests for STTClient — mocked GCP, verifies config and response parsing."""
# pyright: reportPrivateUsage=false
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voice_type.config import AppConfig
from voice_type.stt import STTClient


@pytest.fixture()
def config() -> AppConfig:
    return AppConfig(
        hotkey="<ctrl>+<alt>+r",
        gcp_credentials_path=Path("/fake/creds.json"),
        gcp_project_id="test-project",
        stt_region="us-central1",
    )


def test_stt_client_uses_regional_endpoint(config: AppConfig) -> None:
    with patch("voice_type.stt.SpeechClient") as mock_cls:
        STTClient(config)
        call_kwargs = mock_cls.call_args.kwargs
        endpoint = call_kwargs["client_options"].api_endpoint
        assert endpoint == "us-central1-speech.googleapis.com"


def test_stt_client_language_codes_plural(config: AppConfig) -> None:
    """V2 API uses language_codes (plural) — easy to get wrong."""
    with patch("voice_type.stt.SpeechClient"):
        client = STTClient(config)
        lang = list(client._rec_config.language_codes)
        assert "ru-RU" in lang
        assert "en-US" in lang


def test_stt_client_model_chirp_3(config: AppConfig) -> None:
    with patch("voice_type.stt.SpeechClient"):
        client = STTClient(config)
        assert client._rec_config.model == "chirp_3"


async def test_recognize_returns_transcript(config: AppConfig) -> None:
    with patch("voice_type.stt.SpeechClient") as mock_cls:
        # Build a mock response structure
        alt = MagicMock()
        alt.transcript = "привет мир"
        result = MagicMock()
        result.alternatives = [alt]
        response = MagicMock()
        response.results = [result]
        mock_cls.return_value.recognize.return_value = response

        client = STTClient(config)
        text = await client.recognize(b"\x00" * 32000)  # 1s of silence bytes
        assert text == "привет мир"


async def test_recognize_empty_audio_returns_empty_string(config: AppConfig) -> None:
    with patch("voice_type.stt.SpeechClient"):
        client = STTClient(config)
        text = await client.recognize(b"")
        assert text == ""


async def test_recognize_no_results_returns_empty_string(config: AppConfig) -> None:
    with patch("voice_type.stt.SpeechClient") as mock_cls:
        response = MagicMock()
        response.results = []
        mock_cls.return_value.recognize.return_value = response

        client = STTClient(config)
        text = await client.recognize(b"\x00" * 100)
        assert text == ""
