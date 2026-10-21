"""The fixed comfort cards in all 20 languages the check-in offers (K5).

The backend sends these cards already written in the patient's language, so a
gap here means a patient reads English they may not understand. These tests
check that every language has every set, that the cards follow the same safety
rules as the English source, and that each language really is that language.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from lib import comfort_i18n, fallbacks  # noqa: E402
from services import comfort_protocol  # noqa: E402

LANGS = comfort_i18n.LANGUAGES
SETS = comfort_i18n.SET_NAMES
EN = comfort_i18n.COMFORT_CARDS["en"]
_FRONTEND_I18N = _BACKEND_ROOT.parent / "frontend" / "src" / "lib" / "i18n.ts"

# Every card in a language must be written in that language's script.
_SCRIPT = {
    "zh": r"[一-鿿]", "ja": r"[぀-ヿ]", "ko": r"[가-힯]",
    "ru": r"[Ѐ-ӿ]", "hi": r"[ऀ-ॿ]", "bn": r"[ঀ-৿]",
    "ar": r"[؀-ۿ]", "fa": r"[؀-ۿ]", "ur": r"[؀-ۿ]",
}
# Letters that tell Arabic, Persian and Urdu apart (Arabic yeh and kaf, Farsi yeh and keheh, Urdu yeh barree).
_NOT_IN = {"ar": "یکے", "fa": "يكے", "ur": "يك"}


def _text(cards: list[dict]) -> str:
    return " ".join(f"{c['title']} {c['instruction']}" for c in cards)


def _all_cards():
    for lang in LANGS:
        for name in SETS:
            yield lang, name, comfort_i18n.COMFORT_CARDS[lang][name]


def test_the_languages_match_the_check_in_language_list():
    assert len(LANGS) == 20 and len(set(LANGS)) == 20
    assert set(comfort_i18n.COMFORT_CARDS) == set(LANGS)
    if not _FRONTEND_I18N.exists():
        pytest.skip("frontend source not present")
    block = _FRONTEND_I18N.read_text(encoding="utf-8").split("LANGUAGES", 1)[1].split("];", 1)[0]
    assert re.findall(r'code:\s*"([a-z]{2})"', block) == list(LANGS)


@pytest.mark.parametrize("lang", LANGS)
def test_every_language_has_every_set_with_the_same_number_of_cards(lang):
    sets = comfort_i18n.COMFORT_CARDS[lang]
    assert set(sets) == set(SETS)
    for name in SETS:
        cards = sets[name]
        assert len(cards) == len(EN[name]) == 3, (lang, name)
        for card in cards:
            assert set(card) == {"title", "instruction"}, (lang, name)
            assert isinstance(card["title"], str) and card["title"].strip(), (lang, name)
            assert isinstance(card["instruction"], str) and card["instruction"].strip(), (lang, name)


def test_every_language_counts_as_translated_and_never_falls_back_to_english():
    assert comfort_i18n.translated_languages() == list(LANGS)
    for lang, name, cards in _all_cards():
        got, written_in = comfort_i18n.cards_for(lang, name)
        assert written_in == lang and got == cards, (lang, name)
    got, _ = comfort_i18n.cards_for("ja", "esi2")
    got[0]["title"] = "changed"
    assert comfort_i18n.COMFORT_CARDS["ja"]["esi2"][0]["title"] != "changed"  # callers get copies
    assert comfort_i18n.cards_for("xx", "esi2") == (EN["esi2"], "en")
    assert comfort_i18n.cards_for("pt-BR", "crisis")[1] == "pt"


@pytest.mark.parametrize("lang", LANGS)
def test_every_card_follows_the_safety_rules(lang):
    for name in SETS:
        cards = comfort_i18n.COMFORT_CARDS[lang][name]
        text = _text(cards)
        assert "—" not in text and "–" not in text, (lang, name)
        for card in cards:
            assert len(card["title"]) <= 40, (lang, name, card["title"])
            assert len(card["instruction"]) <= 160, (lang, name, card["instruction"])
            assert not comfort_protocol.names_medicine_or_dose(f"{card['title']} {card['instruction']}"), (lang, name)
        assert comfort_protocol.says_tell_staff(text, lang), (lang, name)
        # The AI cards borrow this last card when theirs forgets to say "tell staff".
        assert comfort_protocol.says_tell_staff(_text(cards[-1:]), lang), (lang, name)


@pytest.mark.parametrize("lang", LANGS)
def test_911_and_988_stay_as_digits_where_the_english_has_them(lang):
    for name in SETS:
        text, en_text = _text(comfort_i18n.COMFORT_CARDS[lang][name]), _text(EN[name])
        for number in ("911", "988"):
            assert (number in text) == (number in en_text), (lang, name, number)
    assert "988" in _text(comfort_i18n.COMFORT_CARDS[lang]["crisis"])
    assert "911" in _text(comfort_i18n.COMFORT_CARDS[lang]["esi1"])


@pytest.mark.parametrize("lang", [lang for lang in LANGS if lang != "en"])
def test_each_language_is_really_translated(lang):
    en_strings = {s for cards in EN.values() for c in cards for s in (c["title"], c["instruction"])}
    for name in SETS:
        for card in comfort_i18n.COMFORT_CARDS[lang][name]:
            assert card["title"] not in en_strings and card["instruction"] not in en_strings, (lang, name, card)
            if lang in _SCRIPT:
                assert re.search(_SCRIPT[lang], card["title"]) and re.search(_SCRIPT[lang], card["instruction"]), (lang, name)
                assert not re.search(r"[A-Za-z]{3,}", card["instruction"]), (lang, name, card)
            for letter in _NOT_IN.get(lang, ""):
                assert letter not in f"{card['title']}{card['instruction']}", (lang, name, f"U+{ord(letter):04X}")


@pytest.mark.parametrize("lang", LANGS)
def test_shared_cards_read_the_same_in_every_set(lang):
    s = comfort_i18n.COMFORT_CARDS[lang]
    assert s["esi2"][1:] == s["esi3"][1:] == s["needs_reading"][1:]
    assert s["esi4"][1:] == s["esi5"][1:]
    assert s["child2"][1] == s["child"][1]
    assert s["esi2"][0]["title"] == s["needs_reading"][0]["title"] == s["child2"][0]["title"]


def test_the_patient_gets_cards_in_their_own_language():
    assert fallbacks.comfort_cards(2, "ko") == comfort_i18n.COMFORT_CARDS["ko"]["esi2"]
    assert fallbacks.comfort_cards(3, "ar", needs_reading=True) == comfort_i18n.COMFORT_CARDS["ar"]["needs_reading"]
    assert fallbacks.comfort_cards(4, "vi", child=True) == comfort_i18n.COMFORT_CARDS["vi"]["child"]
    crisis = comfort_protocol.fallback_cards("my ankle hurts a little", 2, "bn", {"age": 40}, crisis=True)
    assert crisis == comfort_i18n.COMFORT_CARDS["bn"]["crisis"] and "988" in _text(crisis)
    first = comfort_protocol.fallback_cards("my ankle hurts a little", 1, "de", {"age": 40})[0]
    assert first == comfort_i18n.COMFORT_CARDS["de"]["esi1"][0] and "911" in first["instruction"]


def test_a_missing_key_in_a_language_is_caught_at_import():
    cards = {k: ("t", "i") for k in comfort_i18n.CARD_KEYS}
    assert set(comfort_i18n._sets(**cards)) == set(SETS)
    cards.pop("npo")
    with pytest.raises(ValueError):
        comfort_i18n._sets(**cards)
