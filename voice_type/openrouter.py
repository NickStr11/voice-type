"""Minimal OpenRouter chat-completions client shared by cleanup and cloud STT.

- TLS goes through the Windows trust store (truststore). Antivirus HTTPS
  scanning (Kaspersky here) re-signs openrouter.ai with its own root; Windows
  trusts it, the certifi bundle does not, so plain httpx fails intermittently
  with CERTIFICATE_VERIFY_FAILED. Verification stays on.
- Provider routing: sort=latency alone did not stick to the fastest host. In
  Nov 2026 it mostly routed Llama 3.3 70B to CoreWeave (cleanup median 1.25s in
  the live log). A direct benchmark on 2026-11-16 (real cleanup prompt, 12
  calls each): Groq 0.37s median / 0.66 p90, sort=latency 1.24 / 1.41,
  DeepInfra 3.07 / 5.50. So models in _PREFERRED_PROVIDERS name their host
  first. Fallbacks stay on, so a Groq outage still lands on a slower host
  instead of failing the request.
"""
from __future__ import annotations

import os
import ssl
import threading
from typing import Any, Final, cast

import httpx
import truststore
from loguru import logger

_URL: Final[str] = "https://openrouter.ai/api/v1/chat/completions"

_PREFERRED_PROVIDERS: Final[dict[str, tuple[str, ...]]] = {
    "meta-llama/llama-3.3-70b-instruct": ("Groq",),
}

_client: httpx.Client | None = None
_client_lock = threading.Lock()


class OpenRouterError(Exception):
    """HTTP or API-level failure. `code` is the HTTP-style status when known."""

    def __init__(self, code: int | None, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(f"{code} {message}" if code else message)
        self.code = code
        self.message = message
        self.retry_after_s = retry_after_s


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def is_openrouter_model(model: str) -> bool:
    """OpenRouter ids are vendor-qualified ("meta-llama/..."); Gemini ids are not."""
    return "/" in model and not model.startswith("models/")


def _http() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            # Reused across dictations: keeps the TLS connection warm.
            _client = httpx.Client(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
        return _client


def chat(model: str, content: str | list[dict[str, Any]], timeout_s: float) -> str:
    """Single-turn completion. Returns the stripped text ("" when empty)."""
    key = api_key()
    if not key:
        raise OpenRouterError(None, "OPENROUTER_API_KEY is not set")

    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "provider": provider_preferences(model),
    }
    if model.startswith("google/"):
        # Formatting/transcription gains nothing from thinking; it only adds latency.
        body["reasoning"] = {"enabled": False}

    try:
        response = _http().post(
            _URL,
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=timeout_s,
        )
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"OpenRouter {model} timed out") from exc
    except httpx.HTTPError as exc:
        raise OpenRouterError(None, f"{type(exc).__name__}: {str(exc)[:160]}") from exc

    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = {}
    data = cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}
    error: Any = data.get("error")
    if response.status_code >= 400 or error:
        code = response.status_code if response.status_code >= 400 else None
        if isinstance(error, dict):
            err = cast(dict[str, Any], error)
            err_code = err.get("code")
            code = err_code if isinstance(err_code, int) else code
            message = str(err.get("message", ""))[:160]
        else:
            message = response.reason_phrase
        retry = response.headers.get("retry-after")
        retry_s = float(retry) if retry and retry.replace(".", "", 1).isdigit() else None
        raise OpenRouterError(code, message, retry_s)

    try:
        text: Any = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(None, "malformed response") from exc

    preferred = _PREFERRED_PROVIDERS.get(model)
    served_by = data.get("provider")
    if preferred and isinstance(served_by, str) and served_by not in preferred:
        # Silent fallback to a slow host is how cleanup drifted to ~1.2s before.
        logger.info(f"OpenRouter {model} served by {served_by}, not {'/'.join(preferred)}")
    return str(text).strip()


def provider_preferences(model: str) -> dict[str, Any]:
    """OpenRouter `provider` block: pinned host first when known, else fastest."""
    preferred = _PREFERRED_PROVIDERS.get(model)
    if preferred:
        return {"order": list(preferred), "allow_fallbacks": True, "sort": "latency"}
    return {"sort": "latency"}
