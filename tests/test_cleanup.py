from __future__ import annotations

from voice_type.cleanup import fast_clean


def test_fast_clean_inserts_space_after_sentence_punctuation() -> None:
    text = "можем ли мы сейчас все сделать?И какие есть идеи?"
    assert fast_clean(text) == "Можем ли мы сейчас все сделать? И какие есть идеи?"


def test_fast_clean_splits_lower_upper_word_glue() -> None:
    text = "дать обратнуюСвязь и написать вМаксе"
    assert fast_clean(text) == "Дать обратную Связь и написать в Максе"


def test_fast_clean_breaks_long_monologue_into_paragraphs() -> None:
    """A long unbroken dictation must be split into paragraphs (regex grouping
    every ~3 sentences) — and never lose any of the user's words."""
    text = (
        "Мама мыла раму утром. Кот спал на окне весь день. "
        "Солнце светило ярко сегодня. Дождь пошёл только к вечеру. "
        "Ветер стих совсем ночью. Звёзды появились над городом."
    )
    out = fast_clean(text)

    assert "\n\n" in out  # not one giant block
    paragraphs = [p for p in out.split("\n\n") if p.strip()]
    assert len(paragraphs) >= 2
    for word in ("Мама", "Кот", "Солнце", "Дождь", "Ветер", "Звёзды"):
        assert word in out
