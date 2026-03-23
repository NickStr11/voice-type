"""Fast text cleanup — regex-based, no LLM, ~0ms.

Removes filler words, splits into paragraphs by sentence groups,
formats lists. Zero network latency.
"""
from __future__ import annotations

import re

# === Filler patterns — case-insensitive, word boundaries ===
_FILLERS_RU = [
    r"\bну\b", r"\bвот\b", r"\bкороче\b", r"\bтипа\b", r"\bкак бы\b",
    r"\bв общем\b", r"\bв принципе\b", r"\bтак сказать\b", r"\bзначит\b",
    r"\bэто самое\b", r"\bэм\b", r"\bэээ\b", r"\bааа\b", r"\bммм\b",
    r"\bслушай\b", r"\bсмотри\b", r"\bблин\b", r"\bблядь\b",
    r"\bпонял\b(?=\s*[.?!])", r"\bда\b(?=\s*[.?!])",  # trailing "понял." "да."
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

# === Paragraph split markers ===
# Sentences that start with these indicate a new topic/paragraph
_PARAGRAPH_STARTERS = re.compile(
    r'(?<=\.)\s+(?='
    r'(?:А |Но |И ещё|Ещё |Потом |Дальше |Далее |Также |Плюс |'
    r'Кстати |Короче |По поводу |Насчёт |Что касается |'
    r'Во-первых|Во-вторых|В-третьих|В-четвёртых|'
    r'Первое|Второе|Третье|Четвёртое|'
    r'But |And also|Also |Plus |By the way |Regarding |'
    r'First|Second|Third|Next )'
    r')',
    re.IGNORECASE,
)

# === List item patterns — put on new line ===
_LIST_MARKERS = re.compile(
    r'(?<=[\.\!\?])\s*'
    r'((?:Во-первых|Во-вторых|В-третьих|В-четвёртых|'
    r'Первое|Второе|Третье|Четвёртое|'
    r'First(?:ly)?|Second(?:ly)?|Third(?:ly)?|'
    r'1[\.\):]|2[\.\):]|3[\.\):]|4[\.\):]|5[\.\):])'
    r')',
    re.IGNORECASE,
)

# === Cleanup patterns ===
_MULTI_SPACE = re.compile(r" {2,}")
_LEADING_COMMA = re.compile(r"^\s*,\s*")
_DOUBLE_COMMA = re.compile(r",\s*,")
_LEADING_PUNCT = re.compile(r"^\s*[,;]\s*", re.MULTILINE)
_EMPTY_LINES = re.compile(r"\n{3,}")

# Long text threshold — split into paragraphs only for texts > N sentences
_MIN_SENTENCES_FOR_PARAGRAPHS = 3


def _count_sentences(text: str) -> int:
    """Count approximate sentence count."""
    return len(re.findall(r'[.!?]+', text))


def _split_paragraphs(text: str) -> str:
    """Insert paragraph breaks at topic transitions."""
    # Only split if text is long enough
    if _count_sentences(text) < _MIN_SENTENCES_FOR_PARAGRAPHS:
        return text

    # Split at paragraph starters
    result = _PARAGRAPH_STARTERS.sub("\n\n", text)

    # Put list items on new lines
    result = _LIST_MARKERS.sub(r"\n\1", result)

    return result


def _split_by_sentence_groups(text: str, group_size: int = 3) -> str:
    """Split long text into paragraph groups of N sentences.

    Fallback for texts without explicit topic markers.
    Groups every `group_size` sentences into a paragraph.
    """
    if _count_sentences(text) < group_size * 2:
        return text

    # Check if _split_paragraphs already added breaks
    if "\n\n" in text:
        return text

    # Split by sentence endings, group by N
    parts = re.split(r'([.!?]+\s*)', text)
    result = []
    sentence_count = 0

    for part in parts:
        result.append(part)
        if re.match(r'[.!?]+', part):
            sentence_count += 1
            if sentence_count % group_size == 0:
                result.append("\n\n")

    return "".join(result)


def fast_clean(text: str) -> str:
    """Remove filler words, normalize whitespace, split into paragraphs. Zero latency."""
    if not text.strip():
        return text

    # Step 1: Remove fillers
    result = _FILLER_PATTERN.sub("", text)

    # Step 2: Fix punctuation artifacts
    result = _DOUBLE_COMMA.sub(",", result)
    result = _MULTI_SPACE.sub(" ", result)
    result = result.strip()

    # Step 3: Split into paragraphs (topic markers)
    result = _split_paragraphs(result)

    # Step 4: Fallback paragraph split for long texts without markers
    result = _split_by_sentence_groups(result, group_size=4)

    # Step 5: Clean up paragraph formatting
    result = _LEADING_PUNCT.sub("", result)
    result = _EMPTY_LINES.sub("\n\n", result)
    result = result.strip()

    # Step 6: Capitalize first letter of each paragraph
    lines = result.split("\n")
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped and stripped[0].islower():
            indent = line[:len(line) - len(stripped)]
            lines[i] = indent + stripped[0].upper() + stripped[1:]
    result = "\n".join(lines)

    return result
