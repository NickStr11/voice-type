"""Fast text cleanup — regex-based, no LLM, ~0ms.

Preserves words, splits into paragraphs by sentence groups,
and formats lists. Zero network latency.
"""
from __future__ import annotations

import re

# Regex cannot distinguish a hesitation from an intended word or quotation.
# Leave all words intact; contextual hesitation removal belongs to the LLM.

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
# Repair Cyrillic STT word glue without splitting identifiers like VoiceType.
_MISSING_SPACE_BEFORE_UPPER = re.compile(r"(?<=[а-яё])(?=[А-ЯЁ])")
_LEADING_PUNCT = re.compile(r"^\s*[,;]\s*", re.MULTILINE)
_EMPTY_LINES = re.compile(r"\n{3,}")

# Long text threshold — split into paragraphs only for texts > N sentences
_MIN_SENTENCES_FOR_PARAGRAPHS = 3
_SENTENCE_END = r"[.!?…]+(?=\s|$)"


def _count_sentences(text: str) -> int:
    """Count approximate sentence count."""
    return len(re.findall(_SENTENCE_END, text))


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

        parts = re.split(rf'({_SENTENCE_END}\s*)', para)
        chunk: list[str] = []
        sentence_count = 0
        for part in parts:
            chunk.append(part)
            if re.match(_SENTENCE_END, part):
                sentence_count += 1
                if sentence_count % group_size == 0:
                    chunk.append("\n\n")
        out.append("".join(chunk).strip())

    return "\n\n".join(out)


def fast_clean(text: str) -> str:
    """Normalize formatting without deleting words. Zero network latency."""
    if not text.strip():
        return text

    # Join Whisper segment linebreaks, but preserve deliberate blank paragraphs.
    paragraphs = re.split(r"\n[ \t]*\n+", text.replace("\r\n", "\n"))
    result = "\n\n".join(re.sub(r"[ \t]*\n[ \t]*", " ", p) for p in paragraphs)

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
