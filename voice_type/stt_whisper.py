"""Local Whisper STT backend via faster-whisper (CTranslate2).

Design decisions:
- device="cpu" + compute_type="int8": AMD RX 7800 XT has no CUDA; int8 is
  significantly faster than float32 (default) on CPU.
- Lazy model loading: WhisperModel loads on first recognize() call (~3-10s),
  not at __init__, to avoid blocking startup.
- Thread-safe lazy init: double-checked locking with threading.Lock.
- language=None: auto-detect — handles ru/en mixed input without config.
- vad_filter=True: removes silence segments, improves accuracy and speed.
- asyncio.to_thread: transcribe() is CPU-bound; offloaded to thread pool to
  keep the event loop unblocked.
"""
from __future__ import annotations

import asyncio
import threading

import numpy as np
from faster_whisper import WhisperModel
from loguru import logger

from voice_type.config import AppConfig


class WhisperSTTClient:
    """Local Whisper STT backend via faster-whisper (CTranslate2).

    Model loads lazily on first recognize() call to avoid blocking startup.
    Thread-safe initialization via double-checked locking.
    """

    def __init__(self, config: AppConfig) -> None:
        self._model_name = config.whisper_model
        self._model: WhisperModel | None = None
        self._lock = threading.Lock()
        logger.info(f"WhisperSTTClient ready (model={self._model_name}, load deferred)")

    def _get_model(self) -> WhisperModel:
        """Return loaded model, initializing on first call (double-checked locking)."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info(f"Loading Whisper model: {self._model_name} ...")
                    self._model = WhisperModel(
                        self._model_name,
                        device="cpu",
                        compute_type="int8",
                    )
                    logger.info(f"Whisper model loaded: {self._model_name}")
        return self._model

    async def recognize(self, audio_bytes: bytes) -> str:
        """Transcribe LINEAR16 int16 audio bytes via local Whisper.

        Args:
            audio_bytes: Raw int16 bytes at 16kHz mono (same format as STTClient).

        Returns:
            Transcribed text, or empty string if audio is empty or no speech detected.
        """
        if not audio_bytes:
            return ""

        audio_float32 = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        def _transcribe() -> str:
            model = self._get_model()
            segments, info = model.transcribe(
                audio_float32,
                language=None,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text = " ".join(seg.text.strip() for seg in segments)
            logger.info(f"Whisper detected language: {info.language} ({info.language_probability:.2f})")
            return text

        raw_text = await asyncio.to_thread(_transcribe)
        logger.info(f"Whisper STT result: {len(raw_text)} chars")
        return raw_text
