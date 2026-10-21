"""The "what to do next" card for a patient who is already in the ER waiting room.

It must never send anyone away, must match the visible score, and must give the
988 line for suicidal thoughts.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from services import care_routing  # noqa: E402

LEVELS = (1, 2, 3, 4, 5)
LANGS = ("en", "es")
# Words that would send a patient who is already here somewhere else.
OFFSITE = re.compile(
    r"virtual visit|telehealth|from home|at home|go home|book a|schedule|come back|another time|urgent care|"
    r"visita virtual|desde casa|en casa|vuelva|regrese|otro d[ií]a",
    re.IGNORECASE,
)
LEAVE = re.compile(r"\bleave\b|\bse vaya\b", re.IGNORECASE)
ALLOWED_LEAVE = re.compile(r"(?:do not|don't|please do not) leave|no se vaya", re.IGNORECASE)


def _all_text(rec: care_routing.CareRecommendation) -> str:
    return " ".join([rec.label, rec.rationale, rec.action_cta, rec.capacity_note, *rec.next_steps])


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("esi", LEVELS)
def test_card_never_sends_a_waiting_patient_away(esi, lang):
    rec = care_routing.recommend(esi, "my ankle hurts", 30, department_load=0.95, waiting_count=40, language=lang)
    text = _all_text(rec)
    assert not OFFSITE.search(text), text
    for m in LEAVE.finditer(text):
        window = text[max(0, m.start() - 16): m.end()]
        assert ALLOWED_LEAVE.search(window), window


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("esi", LEVELS)
def test_no_911_for_someone_already_at_the_hospital(esi, lang):
    assert "911" not in _all_text(care_routing.recommend(esi, "", 40, language=lang))


@pytest.mark.parametrize("esi,destination,kind", [
    (1, "ed_now", "now"), (2, "ed", "high"), (3, "urgent", "today"), (4, "urgent", "wait"), (5, "urgent", "wait"),
])
def test_destination_matches_the_score(esi, destination, kind):
    rec = care_routing.recommend(esi, "", 40)
    assert (rec.destination, rec.kind) == (destination, kind)


@pytest.mark.parametrize("esi", (2, 3, 4, 5))
@pytest.mark.parametrize("lang", LANGS)
def test_every_level_says_to_tell_staff_if_worse(esi, lang):
    text = _all_text(care_routing.recommend(esi, "", 40, language=lang)).lower()
    assert ("worse" in text) if lang == "en" else ("peor" in text)


@pytest.mark.parametrize("lang", LANGS)
def test_suicidal_thoughts_get_the_crisis_card_with_988(lang):
    rec = care_routing.recommend(4, "I feel like I want to end my life", 17, language=lang)
    assert rec.kind == "crisis" and rec.destination == "ed_now" and rec.severity == "critical"
    assert "988" in rec.rationale and any("988" in s for s in rec.next_steps)


def test_esi_1_is_tell_staff_now_even_with_crisis_words():
    rec = care_routing.recommend(1, "he tried to hang himself and is not breathing", 30)
    assert rec.kind == "now"


def test_a_stale_low_score_still_gets_the_urgent_card():
    assert care_routing.recommend(5, "I can't breathe", 40).kind == "high"


def test_busy_note_only_for_lower_urgency():
    assert care_routing.recommend(2, "", 40, department_load=0.9).capacity_note == ""
    assert care_routing.recommend(4, "", 40, department_load=0.9).capacity_note


def test_spanish_card_has_accents():
    rec = care_routing.recommend(3, "", 40, language="es")
    assert rec.language == "es" and "Quédese" in rec.label


def test_other_languages_get_english_and_say_so():
    rec = care_routing.recommend(3, "", 40, language="zh")
    assert rec.language == "en"


def test_serialized_shape():
    out = care_routing.serialize(care_routing.recommend(2, "", 40))
    assert set(out) == {"destination", "label", "rationale", "action_cta", "severity", "next_steps",
                        "capacity_note", "kind", "language", "audience"}
    assert isinstance(out["next_steps"], list) and all("—" not in s and "–" not in s for s in out["next_steps"])
    assert out["audience"] == "patient"


# ---- a child under 12: the card speaks to the parent ------------------------------------
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("esi", LEVELS)
def test_child_card_speaks_to_the_parent(esi, lang):
    rec = care_routing.recommend(esi, "fever and very sleepy", 3, department_load=0.95, language=lang)
    text = _all_text(rec)
    assert rec.audience == "parent" and rec.language == lang
    assert ("your child" in text) if lang == "en" else ("su niño" in text)
    # Never "if you feel worse" or "do not eat or drink" said to the child.
    assert "you feel worse" not in text and "Do not eat or drink" not in text
    assert "se siente peor" not in text
    assert not OFFSITE.search(text), text
    for m in LEAVE.finditer(text):
        window = text[max(0, m.start() - 16): m.end()]
        assert ALLOWED_LEAVE.search(window), window
    assert "911" not in text and "—" not in text and "–" not in text


@pytest.mark.parametrize("esi", (2, 3, 4, 5))
@pytest.mark.parametrize("lang", LANGS)
def test_child_card_says_to_tell_staff_if_the_child_seems_worse(esi, lang):
    text = _all_text(care_routing.recommend(esi, "", 5, language=lang))
    assert ("your child seems worse" in text) if lang == "en" else ("su niño parece estar peor" in text)


def test_child_crisis_card_keeps_988():
    rec = care_routing.recommend(3, "my son says he wants to kill himself", 10)
    assert rec.kind == "crisis" and rec.audience == "parent"
    assert "988" in rec.rationale and any("988" in s for s in rec.next_steps)


@pytest.mark.parametrize("words,age,child", [
    ("", 11, True), ("", 12, False), ("", 0, True), ("my 3 year old has a fever", None, True),
    ("my baby has a fever", None, True), ("my ankle hurts", None, False),
    # The form's age is the age of the person who is sick; it wins over the words.
    ("my baby kept me up and now my chest hurts", 34, False),
])
def test_young_child(words, age, child):
    assert care_routing.young_child(words, age) is child


def test_pregnant_patient_is_not_a_child():
    assert care_routing.young_child("the baby is not moving", None, pregnant=True) is False
