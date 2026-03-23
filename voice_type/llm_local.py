"""Local LLM client — Ollama for zero-latency text cleanup.

Uses qwen2.5:1.5b via Ollama HTTP API (localhost:11434).
No cloud, no cost, ~0.3s response time on RX 7800 XT.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Final

from loguru import logger

_OLLAMA_URL: Final[str] = "http://localhost:11434/api/generate"
_MODEL: Final[str] = "qwen2.5:1.5b"
_TIMEOUT_S: Final[float] = 5.0

_CLEANUP_PROMPT: Final[str] = (
    "Очисти эту голосовую транскрипцию. Правила:\n"
    "1. Исправь пунктуацию, заглавные буквы, грамматику.\n"
    "2. Удали слова-паразиты: ну, вот, короче, типа, как бы, в общем, блин, эм.\n"
    "3. Разбей на абзацы по смыслу — пустая строка между блоками.\n"
    "4. Перечисления (во-первых, во-вторых, 1, 2, 3) — каждый пункт с новой строки.\n"
    "5. НЕ переводи текст. Сохрани язык оригинала.\n"
    "6. Выведи ТОЛЬКО исправленный текст, ничего больше.\n\n"
)


class LocalLLMClient:
    """Ollama-based local LLM for text cleanup."""

    def __init__(self) -> None:
        self._available: bool | None = None

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False
        logger.info(f"LocalLLM (Ollama): {'available' if self._available else 'not available'}")
        return self._available

    def clean(self, raw_text: str) -> str:
        """Clean transcription via local Ollama model.

        Returns raw_text unchanged on any error.
        """
        if not raw_text.strip():
            return raw_text

        payload = json.dumps({
            "model": _MODEL,
            "prompt": _CLEANUP_PROMPT + raw_text,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": len(raw_text) * 2,
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            _OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
                result = data.get("response", "").strip()
                if not result:
                    return raw_text
                logger.info(f"LocalLLM cleaned: {repr(raw_text[:40])} -> {repr(result[:40])}")
                return result
        except urllib.error.URLError:
            logger.warning("LocalLLM: Ollama not reachable — using raw text")
            return raw_text
        except Exception as exc:
            logger.warning(f"LocalLLM error: {exc} — using raw text")
            return raw_text
