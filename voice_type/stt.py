"""Speech-to-Text client — Google Cloud STT V2 Chirp 2 batch recognition.

Design decisions:
- Batch (not streaming): full audio available before we need transcript.
- Regional endpoint us-central1: required for Chirp 2 (global endpoint
  does not support V2 API). Configured via AppConfig.stt_region.
- language_codes plural: V2 API parameter name (NOT language_code singular).
- Persistent client: initialized once in __init__, reused per recognize().
  Avoids ~200-500ms connection setup overhead on every request.
"""
from __future__ import annotations

import asyncio

from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
from loguru import logger

from voice_type.config import AppConfig


class STTClient:
    """Google Cloud STT V2 client using Chirp 2 batch recognition."""

    def __init__(self, config: AppConfig) -> None:
        self._project_id = config.gcp_project_id
        # Chirp 3 available in "us" multi-region (GA). Supports multi-language
        # auto-detection and 85+ languages including ru-RU and en-US.
        self._region = "us"
        self._client = SpeechClient(
            client_options=ClientOptions(
                api_endpoint=f"{self._region}-speech.googleapis.com"
            )
        )
        self._recognizer = (
            f"projects/{self._project_id}/locations/{self._region}/recognizers/_"
        )
        self._rec_config = cloud_speech.RecognitionConfig(
            explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16_000,
                audio_channel_count=1,
            ),
            language_codes=["ru-RU", "en-US"],
            model="chirp_3",
        )
        logger.info(f"STTClient ready — endpoint: {self._region}-speech.googleapis.com")

    async def recognize(self, audio_bytes: bytes) -> str:
        """Transcribe LINEAR16 audio bytes via Chirp 2 batch recognize.

        Runs the blocking GCP call in asyncio.to_thread to avoid blocking
        the event loop.

        Args:
            audio_bytes: Raw LINEAR16 bytes at 16kHz mono int16.
                         Obtain from: numpy_array.tobytes()

        Returns:
            Transcribed text, or empty string if no speech detected.
        """
        if not audio_bytes:
            logger.warning("STTClient.recognize() called with empty audio")
            return ""

        logger.info(
            f"Sending {len(audio_bytes)} bytes to STT "
            f"({len(audio_bytes) / 32000:.2f}s audio)"
        )

        def _call() -> str:
            request = cloud_speech.RecognizeRequest(
                recognizer=self._recognizer,
                config=self._rec_config,
                content=audio_bytes,
            )
            response = self._client.recognize(request=request)
            if not response.results:
                return ""
            # Take the top alternative from the first result
            alternatives = response.results[0].alternatives
            if not alternatives:
                return ""
            transcript: str = alternatives[0].transcript
            return transcript

        raw_text = await asyncio.to_thread(_call)
        logger.info(f"STT result: {repr(raw_text[:80])}")
        return raw_text
