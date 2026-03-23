"""LLM client — Gemini Flash text cleanup with mandatory wall-clock timeout.

Design decisions:
- concurrent.futures wall-clock timeout: Gemini 2.5 Flash has a confirmed
  socket stall bug (googleapis/python-genai#1893) where the connection hangs
  indefinitely without raising a network error. asyncio.wait_for() does NOT
  catch this — the socket stays open. Only a ThreadPoolExecutor future with
  Future.result(timeout=N) provides true wall-clock cancellation.
- thinking_budget=0: 2.5 Flash enables thinking by default, adding 1-3s
  latency. Cleanup is a simple rewrite task — no benefit from thinking.
- Fallback: if Gemini times out or raises, return raw STT text unchanged.
  The user gets their words, just without cleanup. Silent degradation is
  better than blocking indefinitely.
"""
from __future__ import annotations

import concurrent.futures
from typing import Final

from google import genai
from google.genai import types
from loguru import logger

_CLEANUP_PROMPT_TEMPLATE: Final[str] = (
    "Clean up this voice transcription. Fix punctuation, capitalization, and grammar. "
    "Remove filler words (um, uh, ну, эм, короче, вот). "
    "Output only the corrected text, nothing else.\n\n{text}"
)
_MODEL: Final[str] = "gemini-2.5-flash"
_TIMEOUT_S: Final[float] = 8.0


class LLMClient:
    """Gemini Flash client for voice transcription cleanup."""

    def __init__(self) -> None:
        # genai.Client reads GOOGLE_APPLICATION_CREDENTIALS from env.
        # Initialized once — reused across calls.
        self._client = genai.Client()
        logger.info(f"LLMClient ready — model: {_MODEL}, timeout: {_TIMEOUT_S}s")

    def clean(self, raw_text: str) -> str:
        """Clean up raw STT transcription text via Gemini Flash.

        Applies punctuation, grammar fixes and filler word removal.
        Falls back to raw_text if Gemini times out or raises an exception.

        Args:
            raw_text: Raw transcription string from STTClient.

        Returns:
            Cleaned text, or raw_text unchanged on timeout/error.
        """
        if not raw_text.strip():
            return raw_text

        prompt = _CLEANUP_PROMPT_TEMPLATE.format(text=raw_text)

        def _sync_call() -> str:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    temperature=0.0,
                ),
            )
            result = response.text
            if result is None:
                return raw_text
            return result.strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_sync_call)
            try:
                cleaned = future.result(timeout=_TIMEOUT_S)
                logger.info(
                    f"LLM cleaned: {repr(raw_text[:40])} -> {repr(cleaned[:40])}"
                )
                return cleaned
            except concurrent.futures.TimeoutError:
                logger.warning(
                    f"LLMClient.clean() timed out after {_TIMEOUT_S}s — "
                    "using raw STT text as fallback"
                )
                return raw_text
            except Exception as exc:
                logger.warning(f"LLMClient.clean() error: {exc} — using raw STT text")
                return raw_text
