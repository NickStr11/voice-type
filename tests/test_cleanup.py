from __future__ import annotations

from voice_type.cleanup import fast_clean


def test_fast_clean_inserts_space_after_sentence_punctuation() -> None:
    text = "можем ли мы сейчас все сделать?И какие есть идеи?"
    assert fast_clean(text) == "Можем ли мы сейчас все сделать? И какие есть идеи?"


def test_fast_clean_splits_lower_upper_word_glue() -> None:
    text = "дать обратнуюСвязь и написать вМаксе"
    assert fast_clean(text) == "Дать обратную Связь и написать в Максе"
