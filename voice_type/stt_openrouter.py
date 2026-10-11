"""Cloud STT rescue via an audio-capable model on OpenRouter.

Only used as the fallback when local Whisper returns nothing (server cold,
stuck after resume, or GPU path dead) and VOICETYPE_CLOUD_FALLBACK=1. Gemini
2.5 Flash-Lite transcribed the Russian TTS corpus with 0 WER in 1.1s (5s clip)
to 7s (28s clip) on 2026-10-11 — slower than hot Whisper, but far better than
the minutes-long whisper-cli ladder. Model is overridable with
VOICETYPE_CLOUD_STT_MODEL.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import time
import wave
from typing import Final

from loguru import logger

from voice_type import openrouter

_DEFAULT_MODEL: Final[str] = "google/gemini-2.5-flash-lite"
_TIMEOUT_S: Final[float] = 25.0
_PROMPT: Final[str] = (
    "Transcribe this voice recording verbatim in its original language "
    "(usually Russian, with English technical terms written in Latin script). "
    "Output only the transcript: no comments, no translation, no summary. "
    "If there is no speech, output nothing."
)


class OpenRouterSTTClient:
    """One-shot audio -> text through OpenRouter chat completions."""

    def __init__(self) -> None:
        self._model = os.environ.get("VOICETYPE_CLOUD_STT_MODEL", "").strip() or _DEFAULT_MODEL
        logger.info(f"OpenRouter cloud STT ready — model: {self._model}")

    async def recognize(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""
        return await asyncio.to_thread(self._recognize_sync, audio_bytes)

    def _recognize_sync(self, audio_bytes: bytes) -> str:
        content = [
            {"type": "text", "text": _PROMPT},
            {"type": "input_audio", "input_audio": {"data": _wav_base64(audio_bytes), "format": "wav"}},
        ]
        t0 = time.perf_counter()
        try:
            text = openrouter.chat(self._model, content, _TIMEOUT_S)
        except (openrouter.OpenRouterError, TimeoutError) as exc:
            logger.warning(f"OpenRouter STT {self._model} failed: {exc}")
            return ""
        logger.info(f"OpenRouter STT done in {time.perf_counter() - t0:.2f}s — {len(text)} chars")
        return text


def _wav_base64(pcm16_mono_16k: bytes) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm16_mono_16k)
    return base64.b64encode(buf.getvalue()).decode("ascii")
