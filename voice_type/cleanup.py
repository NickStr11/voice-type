"""Fast text cleanup — regex-based, no LLM, ~0ms.

Removes filler words, splits into paragraphs by sentence groups,
formats lists. Zero network latency.
"""
from __future__ import annotations

import re

# === Filler patterns — case-insensitive, word boundaries ===
# Only pure fillers that are NEVER meaningful in context.
# Words like "ну", "вот", "смотри", "слушай", "значит", "блин" are
# often intentional — removing them butchers natural speech.
_FILLERS_RU = [
    r"\bкороче\b", r"\bтипа\b", r"\bкак бы\b",
    r"\bэто самое\b", r"\bтак сказать\b",
    r"\bэм\b", r"\bэээ+\b", r"\bааа+\b", r"\bммм+\b",
]
_FILLERS_EN = [
    r"\bum\b", r"\buh\b", r"\buhh+\b", r"\bumm+\b",
    r"\byou know\b", r"\bi mean\b",
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
_MISSING_SPACE_AFTER_SENTENCE_PUNCT = re.compile(r"(?<=[.!?…])(?=[A-Za-zА-Яа-яЁё])")
_MISSING_SPACE_BEFORE_UPPER = re.compile(r"(?<=[a-zа-яё])(?=[A-ZА-ЯЁ])")
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
    """Group long runs of sentences into paragraphs.

    Runs *within* each existing paragraph, so it composes with the topic-marker
    splits from _split_paragraphs instead of being switched off by them (the old
    version bailed out entirely the moment any "\\n\\n" was present). A wall of
    more than `group_size` sentences becomes one paragraph per `group_size`
    sentences — the regex equivalent of "don't paste a 600-char monolith".
    """
    out: list[str] = []
    for para in text.split("\n\n"):
        if _count_sentences(para) <= group_size:
            out.append(para.strip())
            continue

        parts = re.split(r'([.!?]+\s*)', para)
        chunk: list[str] = []
        sentence_count = 0
        for part in parts:
            chunk.append(part)
            if re.match(r'[.!?]+', part):
                sentence_count += 1
                if sentence_count % group_size == 0:
                    chunk.append("\n\n")
        out.append("".join(chunk).strip())

    return "\n\n".join(out)


def fast_clean(text: str) -> str:
    """Remove filler words, normalize whitespace, split into paragraphs. Zero latency."""
    if not text.strip():
        return text

    # Step 0: Collapse segment-level linebreaks from Whisper. whisper.cpp
    # returns one \n per internal 30s window, which used to be smoothed
    # out by the Gemini round-trip. Now that more long phrases route to
    # fast_clean, we must normalize them here — paragraphs are
    # reintroduced later at real topic transitions only.
    result = re.sub(r"\s*\n+\s*", " ", text)

    # Step 1: Remove fillers
    result = _FILLER_PATTERN.sub("", result)

    # Step 2: Fix punctuation artifacts
    result = _DOUBLE_COMMA.sub(",", result)
    result = _MISSING_SPACE_AFTER_SENTENCE_PUNCT.sub(" ", result)
    result = _MISSING_SPACE_BEFORE_UPPER.sub(" ", result)
    result = _MULTI_SPACE.sub(" ", result)
    result = result.strip()

    # Step 3: Split into paragraphs (topic markers)
    result = _split_paragraphs(result)

    # Step 4: Group remaining long runs into paragraphs (composes with Step 3)
    result = _split_by_sentence_groups(result, group_size=3)

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
