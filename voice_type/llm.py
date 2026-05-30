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
    "You format a raw voice transcription. You are a FORMATTER, not an editor.\n"
    "Return the SAME text with formatting fixes ONLY:\n"
    "1. Fix punctuation, capitalization and obvious grammar.\n"
    "2. Remove only pure filler words (um, uh, ну, эм, короче, вот, типа, "
    "как бы, в общем).\n"
    "3. Split into paragraphs at topic shifts — separate paragraphs with a "
    "blank line.\n"
    "4. When the speaker enumerates (во-первых/во-вторых, 1/2/3, first/second), "
    "put each item on its own new line.\n"
    "5. Do NOT paraphrase, summarize, shorten, reorder or invent anything. "
    "Keep every word the speaker said, in the original language.\n"
    "6. Output only the formatted text, nothing else.\n\n{text}"
)
_MODEL: Final[str] = "gemini-2.5-flash"
_TIMEOUT_S: Final[float] = 8.0


class LLMClient:
    """Gemini Flash client for voice transcription cleanup."""

    def __init__(self, project: str | None = None) -> None:
        import os

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        project = (project or os.environ.get("GCP_PROJECT_ID", "") or "").strip()

        if api_key:
            # Public path: a free AI Studio key (https://aistudio.google.com/apikey).
            # Audio never reaches Gemini — only the short transcript for cleanup —
            # so the free tier covers normal personal use easily.
            self._client: genai.Client | None = genai.Client(api_key=api_key)
            self.available = True
            backend = "AI Studio (GEMINI_API_KEY)"
        elif project:
            # Vertex path: service account via GOOGLE_APPLICATION_CREDENTIALS,
            # billed to the GCP project (e.g. a free Vertex credit).
            self._client = genai.Client(vertexai=True, project=project, location="us-central1")
            self.available = True
            backend = f"Vertex (project={project})"
        else:
            # No credentials — cleanup is disabled and the caller falls back to
            # the regex fast_clean, so VoiceType still runs fully offline.
            self._client = None
            self.available = False
            backend = "disabled (set GEMINI_API_KEY to enable Gemini cleanup)"

        logger.info(f"LLMClient {backend} — model: {_MODEL}, timeout: {_TIMEOUT_S}s")

    def clean(self, raw_text: str) -> str:
        """Clean up raw STT transcription text via Gemini Flash.

        Applies punctuation, grammar fixes and filler word removal.
        Falls back to raw_text if Gemini times out or raises an exception.

        Args:
            raw_text: Raw transcription string from STTClient.

        Returns:
            Cleaned text, or raw_text unchanged on timeout/error.
        """
        if not raw_text.strip() or self._client is None:
            return raw_text

        client = self._client
        prompt = _CLEANUP_PROMPT_TEMPLATE.format(text=raw_text)

        def _sync_call() -> str:
            response = client.models.generate_content(
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
                logger.info(f"LLM cleanup complete — chars: {len(raw_text)} -> {len(cleaned)}")
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
