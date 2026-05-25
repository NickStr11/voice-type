"""Speech-to-Text client — Google Cloud STT V2 Chirp 3 batch recognition.

Design decisions:
- Batch (not streaming): full audio available before we need transcript.
- Endpoint prefix comes from AppConfig.stt_region. Default is "us" for Chirp 3.
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
    """Google Cloud STT V2 client using Chirp 3 batch recognition."""

    def __init__(self, config: AppConfig) -> None:
        self._project_id = config.gcp_project_id
        self._region = config.stt_region
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
        logger.info(f"STTClient ready — endpoint: {self._region}-speech.googleapis.com, model: chirp_3")

    async def recognize(self, audio_bytes: bytes) -> str:
        """Transcribe LINEAR16 audio bytes via Chirp 3 batch recognize.

        Automatically splits audio longer than 55 seconds into chunks
        (Recognize API limit is 60s, we use 55s for safety margin).

        Args:
            audio_bytes: Raw LINEAR16 bytes at 16kHz mono int16.

        Returns:
            Transcribed text, or empty string if no speech detected.
        """
        if not audio_bytes:
            logger.warning("STTClient.recognize() called with empty audio")
            return ""

        duration_s = len(audio_bytes) / 32000
        logger.info(f"Sending {len(audio_bytes)} bytes to STT ({duration_s:.2f}s audio)")

        # Split into chunks if longer than 55 seconds
        max_chunk_bytes = 55 * 16000 * 2  # 55s * 16kHz * 2 bytes/sample
        if len(audio_bytes) <= max_chunk_bytes:
            chunks = [audio_bytes]
        else:
            chunks = [audio_bytes[i:i + max_chunk_bytes]
                      for i in range(0, len(audio_bytes), max_chunk_bytes)]
            logger.info(f"Audio split into {len(chunks)} chunks")

        def _call_chunk(chunk: bytes) -> str:
            request = cloud_speech.RecognizeRequest(
                recognizer=self._recognizer,
                config=self._rec_config,
                content=chunk,
            )
            response = self._client.recognize(request=request)
            parts: list[str] = []
            for result in response.results:
                if result.alternatives:
                    parts.append(result.alternatives[0].transcript)
            return " ".join(parts)

        def _call_all() -> str:
            results: list[str] = []
            for i, chunk in enumerate(chunks):
                text = _call_chunk(chunk)
                if text:
                    results.append(text)
                if len(chunks) > 1:
                    logger.info(f"Chunk {i + 1}/{len(chunks)} done")
            return " ".join(results)

        raw_text = await asyncio.to_thread(_call_all)
        logger.info(f"STT result received — chars: {len(raw_text)}")
        return raw_text
