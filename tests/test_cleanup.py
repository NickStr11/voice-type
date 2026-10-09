from __future__ import annotations

import pytest

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


@pytest.mark.parametrize("text", [
    "Сделай текст короче", "Ошибка типа данных", "Как бы не удалить данные",
    "Это самое важное", "Можно так сказать", "Do you know what I mean?",
    "Не меняй 12,5 мг на 125 мг", "Буква эм и звук эээ",
    "Проверь VoiceType, PharmOrder и getClipboardData",
    "Дозировки 1.5 мг, 2.5 мг, 3.5 мг, 4.5 мг и 5.5 мг",
])
def test_meaningful_words_are_never_removed(text: str) -> None:
    assert fast_clean(text) == text


def test_existing_blank_paragraphs_survive_cleanup() -> None:
    assert fast_clean("Первый абзац.\r\n\r\nВторой абзац.") == "Первый абзац.\n\nВторой абзац."


def test_whisper_segment_breaks_still_join() -> None:
    assert fast_clean("Начало фразы\nи её продолжение") == "Начало фразы и её продолжение"
