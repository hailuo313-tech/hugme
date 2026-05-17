from __future__ import annotations

from services.emotion_lexicon import (
    detect_language_from_text,
    infer_emotion_tags,
    language_name,
    normalize_language,
)


def test_normalize_language_aliases():
    assert normalize_language("zh-CN") == "zh"
    assert normalize_language("en_US") == "en"
    assert normalize_language("es-MX") == "es"
    assert normalize_language("unknown") == "zh"


def test_detect_language_from_text():
    assert detect_language_from_text("我今天很开心") == "zh"
    assert detect_language_from_text("Estoy muy triste") == "es"
    assert detect_language_from_text("Je suis très seul") == "fr"
    assert detect_language_from_text("Ich bin so einsam") == "de"
    assert detect_language_from_text("I feel lonely") == "en"


def test_infer_emotion_tags_multilingual():
    assert "lonely" in infer_emotion_tags("Ich bin so einsam")
    assert "sad" in infer_emotion_tags("Estoy muy triste")
    assert "anxious" in infer_emotion_tags("Je suis anxieuse")
    assert "happy" in infer_emotion_tags("我今天很开心")


def test_infer_emotion_tags_caps_distinct_tags():
    tags = infer_emotion_tags("I am lonely, sad, anxious, angry, happy", max_tags=3)
    assert len(tags) == 3
    assert len(set(tags)) == 3


def test_language_name_defaults_to_chinese():
    assert language_name("fr") == "French"
    assert language_name("bad") == "Chinese"
