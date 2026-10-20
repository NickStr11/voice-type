"""Cloud STT rescue via audio-capable models on OpenRouter.

Only used as the fallback when local Whisper returns nothing (server cold,
stuck after resume, model unreachable, GPU path dead) and
VOICETYPE_CLOUD_FALLBACK=1. Models are tried in order; a rate-limited model is
paused so the next dictation goes straight to the following one.

2026-10-20 on the TTS corpus (14-60 s clips, with the vocabulary hint):
gemini-3.1-flash-lite WER 0-5% in 1.5-1.9 s, mimo-v2.6-flash 0-4% in
1.0-2.9 s, gpt-audio-mini 0-10% in 1.3-2.7 s. The previous single model,
gemini-2.5-flash-lite, returned 429 on most calls that day and dictations were
lost. Override the chain with VOICETYPE_CLOUD_STT_MODEL (comma-separated).
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

_DEFAULT_MODELS: Final[tuple[str, ...]] = (
    "google/gemini-3.1-flash-lite",
    "xiaomi/mimo-v2.6-flash",
    "openai/gpt-audio-mini",
)
_MODEL_TIMEOUT_S: Final[float] = 12.0
_TOTAL_BUDGET_S: Final[float] = 25.0
# Pause after a rate limit / payment error when the API gives no retry hint.
_DEFAULT_PAUSE_S: Final[float] = 60.0
_PROMPT: Final[str] = (
    "Transcribe this voice recording verbatim in its original language "
    "(usually Russian, with English technical terms written in Latin script). "
    "Output only the transcript: no comments, no translation, no summary. "
    "If there is no speech, output nothing."
)


class OpenRouterSTTClient:
    """One-shot audio -> text through a chain of OpenRouter audio models."""

    def __init__(self, vocabulary: str = "") -> None:
        raw = os.environ.get("VOICETYPE_CLOUD_STT_MODEL", "")
        self._models = [m.strip() for m in raw.split(",") if m.strip()] or list(_DEFAULT_MODELS)
        self._paused_until: dict[str, float] = {}
        self._prompt = _PROMPT
        if vocabulary.strip():
            self._prompt += f" Spell these names and terms exactly like this when they occur: {vocabulary.strip()}"
        logger.info(f"OpenRouter cloud STT ready — models: {', '.join(self._models)}")

    async def recognize(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""
        return await asyncio.to_thread(self._recognize_sync, audio_bytes)

    def _recognize_sync(self, audio_bytes: bytes) -> str:
        content = [
            {"type": "text", "text": self._prompt},
            {"type": "input_audio", "input_audio": {"data": _wav_base64(audio_bytes), "format": "wav"}},
        ]
        t0 = time.perf_counter()
        now = time.monotonic()
        ready = [m for m in self._models if self._paused_until.get(m, 0.0) <= now]
        # If every model is paused, still try them all rather than drop the dictation.
        for model in ready or self._models:
            remaining = _TOTAL_BUDGET_S - (time.perf_counter() - t0)
            if remaining <= 1.0:
                break
            try:
                text = openrouter.chat(model, content, min(_MODEL_TIMEOUT_S, remaining))
            except (openrouter.OpenRouterError, TimeoutError) as exc:
                logger.warning(f"OpenRouter STT {model} failed: {exc}")
                code = getattr(exc, "code", None)
                if code is not None and 400 <= code < 500:
                    pause = getattr(exc, "retry_after_s", None) or _DEFAULT_PAUSE_S
                    self._paused_until[model] = time.monotonic() + pause
                continue
            if text.strip():
                logger.info(
                    f"OpenRouter STT {model} done in {time.perf_counter() - t0:.2f}s — {len(text)} chars"
                )
                return text
            logger.warning(f"OpenRouter STT {model} returned empty text")
        return ""


def _wav_base64(pcm16_mono_16k: bytes) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm16_mono_16k)
    return base64.b64encode(buf.getvalue()).decode("ascii")
