"""Fast text cleanup — regex-based, no LLM, ~0ms.

Removes common Russian and English filler words and normalizes whitespace.
Used in fast mode as a lightweight alternative to Gemini cleanup.
"""
from __future__ import annotations

import re

# Filler patterns — case-insensitive, word boundaries
_FILLERS_RU = [
    r"\bну\b", r"\bвот\b", r"\bкороче\b", r"\bтипа\b", r"\bкак бы\b",
    r"\bв общем\b", r"\bв принципе\b", r"\bтак сказать\b", r"\bзначит\b",
    r"\bэто самое\b", r"\bэм\b", r"\bэээ\b", r"\bааа\b", r"\bммм\b",
    r"\bслушай\b", r"\bсмотри\b", r"\bблин\b",
]
_FILLERS_EN = [
    r"\bum\b", r"\buh\b", r"\blike\b(?!\s+(?:this|that|a|the|it))",
    r"\byou know\b", r"\bi mean\b", r"\bbasically\b", r"\bactually\b",
    r"\bliterally\b", r"\bhonestly\b", r"\bkind of\b", r"\bsort of\b",
]

_FILLER_PATTERN = re.compile(
    "|".join(_FILLERS_RU + _FILLERS_EN),
    re.IGNORECASE,
)
_MULTI_SPACE = re.compile(r"\s{2,}")
_LEADING_COMMA = re.compile(r"^\s*,\s*")
_DOUBLE_COMMA = re.compile(r",\s*,")


def fast_clean(text: str) -> str:
    """Remove filler words and normalize whitespace. Zero latency."""
    if not text.strip():
        return text

    result = _FILLER_PATTERN.sub("", text)
    result = _DOUBLE_COMMA.sub(",", result)
    result = _LEADING_COMMA.sub("", result)
    result = _MULTI_SPACE.sub(" ", result)
    result = result.strip()

    # Capitalize first letter if needed
    if result and result[0].islower():
        result = result[0].upper() + result[1:]

    return result
