"""Red-team regression: the check-ins the red teams wrote stay caught.

The cases are plain JSON in tests/data/:
  redteam_en.json            English red team, rounds 1 to 5 (typos, slang, bystanders,
                             overdoses, pregnancy, babies, everyday traps)
  redteam_multilingual.json  all 20 languages, romanized typing, code-switching, English
                             picked but another language typed, special populations
  diagnostic_blind1.json     DIAGNOSTIC set: blind test 1. It was blind when it ran, then its
                             misses were used to fix the rules by category, so it is no longer
                             blind. The honest number for new wording is blind test 2.
heldout.json is NOT tested here on purpose. It was written after the rules were frozen and
is only reported (scripts/red_flag_report.py), so nobody tunes the rules to it.

Each check-in goes through intake_pipeline.triage_check_in with no AI and with the model
forced to say ESI 5, so the rules alone must carry every emergency. That is stricter than
the real model, which sometimes catches a case by itself.
  * emergencies are shown at max_esi or more urgent;
  * everyday check-ins are never shown at ESI 1 or 2;
  * an everyday check-in in another language is held at ESI 3 for a nurse to read.
A case the rules cannot reach honestly is marked xfail with the reason; it is never deleted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from services import intake_pipeline, red_flag_checklist, triage, triage_rules  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
REGRESSION_FILES = ("redteam_en.json", "redteam_multilingual.json")
HELDOUT_FILE = "heldout.json"
DIAGNOSTIC_FILE = "diagnostic_blind1.json"


def load_cases(name: str) -> list[dict]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))["cases"]


_ESI1_JUDGMENT = ("Shown ESI 2 (a bed and a clinician promptly), the red team expected ESI 1. ESI 2 is a "
                  "defensible level for these words, and there is no honest ESI 1 wording rule for them.")
XFAIL: dict[str, str] = {
    "en-r1-G06": _ESI1_JUDGMENT,   # grease fire burned my face and my voice is getting hoarse
    "en-r1-G45": _ESI1_JUDGMENT,   # i got stabbed (no place on the body)
    "en-r2-K07": _ESI1_JUDGMENT,   # fell from a ladder onto my back cant feel my legs
    "en-r4-W22": _ESI1_JUDGMENT,   # the baby is coming i can see the head
}


def _params() -> list:
    out = []
    for name in REGRESSION_FILES:
        for c in load_cases(name):
            marks = [pytest.mark.xfail(reason=XFAIL[c["id"]], strict=True)] if c["id"] in XFAIL else []
            out.append(pytest.param(c, id=c["id"], marks=marks))
    return out


def _model_says_5(*_args, **_kwargs) -> triage.TriagePrediction:
    return triage.TriagePrediction(
        esi_level=5, confidence=0.99, confidence_band="ESI 5 (confidence 99%)", shap_values={},
        source="test_stub", clinical_flags=[], composites={}, recommendation="", probabilities=[0.0] * 5,
    )


@pytest.fixture
def rules_alone(monkeypatch):
    monkeypatch.setattr(triage, "_predict_trained", _model_says_5)
    monkeypatch.setattr(triage, "_predict_engine", _model_says_5)
    monkeypatch.setattr("lib.claude.available", lambda: False)


def _check(case: dict, **kw) -> intake_pipeline.IntakeTriage:
    return intake_pipeline.triage_check_in(case["text"], medical_info=case["medical_info"],
                                           language=case["language"], allow_ai=False, **kw)


@pytest.mark.parametrize("case", _params())
def test_red_team_check_in(rules_alone, case):
    t = _check(case)
    shown = t.esi_level
    if case["kind"] == "emergency":
        assert shown <= case["max_esi"], (
            f"{case['text']!r} ({case['language']}) shown ESI {shown}, expected {case['max_esi']} or more urgent")
        assert t.rule is not None and t.reasons, "a rule raised it, so the clinician must see why"
    else:
        assert shown >= case["min_esi"], (
            f"everyday {case['text']!r} ({case['language']}) shown ESI {shown}; rule {t.rule.reason if t.rule else None}")
        if case.get("max_esi") is not None:
            assert shown <= case["max_esi"], f"{case['text']!r} ({case['language']}) not held for a nurse to read"


# ---- DIAGNOSTIC set: blind test 1 ------------------------------------------------------------
# Emergencies the rules alone still cannot reach, by category. Most are covered by the red-flag
# checklist the patient taps; the ones marked "no checklist item" are not.
_NO_RULE = "No rule for this high-risk complaint, and no checklist item describes it."
_STROKE_WORDS = "Stroke described in words the rules do not know; the stroke checklist item covers it."
_ESI1 = "Shown ESI 2, the blind evaluator expected ESI 1; the checklist can only lift to ESI 2."
_OTHER_WORDS = "Described in words the rules do not know in this language; a checklist item covers it."
_UNREAD = "Not read by the rules in this language (held at ESI 3 for a nurse); no checklist item describes it."
DIAGNOSTIC_XFAIL: dict[str, str] = {
    **dict.fromkeys(["en_e008", "en_e015", "en_e036", "en_e080", "en_e083", "en_e086", "en_e088", "en_e090",
                     "en_e091", "en_e095", "en_e100"], _NO_RULE),
    **dict.fromkeys(["en_e016", "en_e017", "es_e03", "zh_e03", "ar_e03"], _STROKE_WORDS),
    **dict.fromkeys(["en_e029", "en_e044", "zh_e09", "vi_e09", "ar_e09", "es_e09"], _ESI1),
    **dict.fromkeys(["en_e033", "es_e05", "es_e10", "zh_e04", "zh_e07", "hi_e08", "ar_e01", "ar_e04",
                     "vi_e07", "vi_e08"], _OTHER_WORDS),
    **dict.fromkeys(["es_e07", "es_e12", "zh_e12", "hi_e07", "ar_e08", "ar_e11", "vi_e11"], _UNREAD),
}


def _diagnostic_params(kind: str) -> list:
    out = []
    for c in load_cases(DIAGNOSTIC_FILE):
        if c["kind"] != kind:
            continue
        reason = DIAGNOSTIC_XFAIL.get(c["id"])
        marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
        out.append(pytest.param(c, id=c["id"], marks=marks))
    return out


@pytest.mark.parametrize("case", _diagnostic_params("everyday"))
def test_diagnostic_blind1_everyday_is_not_a_false_alarm(rules_alone, case):
    t = _check(case)
    assert t.esi_level >= 3, f"{case['text']!r} shown ESI {t.esi_level}; rule {t.rule.reason if t.rule else None}"
    if t.crisis:
        pytest.fail(f"{case['text']!r} showed the 988 crisis card")


@pytest.mark.parametrize("case", _diagnostic_params("emergency"))
def test_diagnostic_blind1_emergency_from_the_words_alone(rules_alone, case):
    t = _check(case)
    assert t.esi_level <= case["max_esi"], f"{case['text']!r} ({case['language']}) shown ESI {t.esi_level}"


def test_diagnostic_blind1_honest_checklist_answers_reach_esi_2(rules_alone):
    """Every blind-1 emergency with an honest checklist answer ends at ESI 2 or more urgent."""
    missed = []
    for c in load_cases(DIAGNOSTIC_FILE):
        flags = [f for f in c["truthful_flags"] if f in red_flag_checklist.IDS]
        if c["kind"] == "emergency" and flags != ["none"]:
            if _check(c, red_flags=flags).esi_level > 2:
                missed.append(c["id"])
    assert not missed, missed


# ---- the case files themselves ------------------------------------------------------------

def test_case_files_are_well_formed_and_held_out_stays_separate():
    seen: dict[str, str] = {}
    for name in REGRESSION_FILES + (HELDOUT_FILE, DIAGNOSTIC_FILE):
        cases = load_cases(name)
        assert cases, name
        for c in cases:
            assert c["id"] not in seen, f"{c['id']} is in both {seen.get(c['id'])} and {name}"
            seen[c["id"]] = name
            assert c["kind"] in ("emergency", "everyday") and c["text"].strip() and c["language"]
            assert isinstance(c["medical_info"], dict)
            if c["kind"] == "emergency":
                assert c["max_esi"] in (1, 2, 3)
            else:
                assert c["min_esi"] == 3
    regression_texts = {(c["text"], c["language"]) for n in REGRESSION_FILES for c in load_cases(n)}
    overlap = {c["id"] for c in load_cases(HELDOUT_FILE) if (c["text"], c["language"]) in regression_texts}
    # The held-out author happened to reuse these two phrases; no others may leak in.
    assert overlap <= {"ho-080-tr-core", "hc-067-en"}, f"held-out phrases copied into the regression set: {overlap}"
    assert len(load_cases(DIAGNOSTIC_FILE)) == 240
    assert set(DIAGNOSTIC_XFAIL) <= {c["id"] for c in load_cases(DIAGNOSTIC_FILE)}


# ---- red-team fixes in the rules themselves -------------------------------------------------------

@pytest.mark.parametrize("text,reason", [
    ("cant breth", "rule.esi2.breathing"),                       # a typo no longer hides the complaint
    ("i can t breathe", "rule.esi2.breathing"),                  # a dictation split
    ("my dad had a stroke 30 minutes ago", "rule.esi1.stroke_symptoms"),  # minutes ago is now, not history
    ("ive never had chest pain like this", "rule.esi2.chest_pain"),
    ("my dad isnt responding", "rule.esi1.life_threatening_keywords"),
    ("i want to unalive myself", "rule.esi2.crisis"),
    ("i took 20 xanax", "rule.esi2.overdose_self"),
    ("my grandpa is really confused and wont stop shaking", "rule.esi2.new_confusion"),
    ("my boyfriend choked me last night and my neck hurts", "rule.esi2.assault"),
])
def test_red_team_wording_reaches_the_right_rule(text, reason):
    assert reason in {m.reason for m in triage_rules.assess(text, age=40).matches}


@pytest.mark.parametrize("text", [
    "my infection is not responding to antibiotics",
    "my rash is not responding at all",
    "i had a seizure as a teenager and need a drivers license form",
    "im pregnant and here for my blood test",
    "my 1 month old has a temp of 98.6, here for her weight check",
])
def test_red_team_everyday_traps_stay_clear(text):
    pregnant = "pregnant" in text
    age = 0 if "month old" in text else 30
    floor = triage_rules.assess(text, age=age, pregnant=pregnant).floor
    assert floor is None or floor.esi_level >= 3, (text, floor)


def test_danger_to_others_is_urgent_but_not_the_988_card(rules_alone):
    t = intake_pipeline.triage_check_in("im going to kill him", medical_info={"age": 30}, language="en", allow_ai=False)
    assert t.esi_level == 2 and t.rule.reason == "rule.esi2.danger_to_others"
    assert not t.crisis and "988" not in t.explanation


def test_pregnant_adult_is_never_read_as_a_child():
    assert triage_rules.child_age_months("the baby hasn't moved much since yesterday", 33, pregnant=True) == 33 * 12
    assert triage_rules.child_age_months("se me rompio la fuente y tengo 30 semanas", 27, pregnant=True) == 27 * 12
    assert triage_rules.child_age_months("tengo 30 semanas de embarazo", 27) == 27 * 12
    assert triage_rules.child_age_months("my baby is 6 weeks and has a fever", 31) == 1   # a parent's own age on the form
    a = triage_rules.assess("the baby hasn't moved much since yesterday", age=33, pregnant=True)
    assert a.child_months == 33 * 12 and a.floor is triage_rules.PREGNANCY


def test_head_bump_on_a_blood_thinner_from_the_form(rules_alone):
    assert triage_rules.assess("my dad fell and hit his head", age=79).floor is None
    assert triage_rules.assess("my dad fell and hit his head", age=79, on_blood_thinner=True).floor is triage_rules.HEAD
    t = intake_pipeline.triage_check_in("my dad fell and hit his head", allow_ai=False, language="en",
                                        medical_info={"age": 79, "blood_thinner_name": "Eliquis"})
    assert t.esi_level == 2 and t.rule is triage_rules.HEAD


@pytest.mark.parametrize("text,foreign", [
    ("me duele el pecho", True),
    ("3andi alam fi sadri", True),
    ("main marna chahta hoon", True),
    ("Mein Vater ist am Boden zusammengesackt und atmet komisch, was soll ich tun", True),
    ("sore throat", False),
    ("I twisted my ankle and it is swollen", False),
    ("took my meds at 8am, 10mg, its my 2nd day", False),
])
def test_other_languages_typed_in_latin_letters_are_noticed(text, foreign):
    assert triage_rules.foreign_latin(text) is foreign


def test_evidence_page_counts_languages_not_romanized_lists():
    names = " ".join(r["name"] for r in triage_rules.describe_rules())
    assert "19 more languages" in names


def test_lexicon_words_live_in_their_own_module_and_stay_importable():
    from services import triage_lexicons
    assert triage_rules.LEXICONS is triage_lexicons.LEXICONS
    assert set(triage_lexicons.DENIAL) >= {"en", "es", "zh", "hi", "ar", "vi"}


# ---- categories blind test 1 exposed (wave 2), written fresh and two-sided ------------------------
# "urgent": a rule at ESI 2 or more urgent. "esi1": ESI 1. "crisis": ESI 2 or more urgent with the
# 988 card. "calm": no ESI 1 or 2 rule. "no988": the 988 card is not shown.
CATEGORY_CASES: list[tuple[str, int, str]] = [
    # a denial is not a complaint, in any language
    ("no988", 30, "feeling low lately but I have no thoughts of suicide and I'm safe"),
    ("no988", 30, "I would never hurt myself, I just need help with anxiety"),
    ("no988", 30, "Estoy triste pero no tengo pensamientos de hacerme daño"),
    ("no988", 30, "我没有想过自杀，只是心情不好"),
    ("no988", 30, "मैं मरना नहीं चाहता, बस बहुत तनाव है"),
    ("no988", 30, "ما أبي أموت، بس متضايق"),
    ("no988", 30, "Tôi không muốn chết, chỉ là buồn thôi"),
    ("crisis", 30, "no thoughts of hurting myself until last night, now I keep thinking about it"),
    ("crisis", 30, "I can't promise I'm not going to hurt myself tonight"),
    ("crisis", 30, "ya no quiero vivir"),
    ("calm", 30, "hit my head on the car door, never lost consciousness, just a bump"),
    ("calm", 30, "I don't feel faint, my ankle just hurts"),
    ("calm", 30, "my daughter fainted a few years ago at the dentist, now she has an earache"),
    ("urgent", 30, "I fainted two weeks ago and again this morning at work"),
    ("urgent", 16, "my daughter fainted in high school gym class today"),
    ("calm", 30, "I don't have any chest pain or shortness of breath, just a sprained ankle"),
    ("calm", 30, "it doesn't hurt to breathe, my back is just sore"),
    ("urgent", 30, "I've never had chest pain like this before"),
    ("calm", 30, "tengo gripa, sin dolor en el pecho y respiro bien"),
    ("calm", 30, "咳嗽两天了，胸不痛，也没有呼吸困难"),
    ("calm", 30, "खांसी है, सीने में कोई दर्द नहीं है"),
    ("calm", 30, "عندي كحة بس ما عندي ألم في الصدر ولا ضيق في التنفس"),
    ("calm", 30, "Tôi bị ho, không đau ngực, không khó thở"),
    ("calm", 30, "胸の痛みはないです、喉が痛いだけです"),
    ("urgent", 30, "胸口一直不停地痛"),
    ("urgent", 30, "सीने में दर्द नहीं रुक रहा"),
    ("urgent", 30, "hindi siya makapagsalita ng maayos at nanghihina ang kaliwang braso"),
    # a bystander unsure the person is breathing
    ("esi1", 70, "my grandpa slumped over at dinner and I can't tell if he's breathing"),
    ("esi1", 70, "he collapsed and it doesn't look like he's breathing"),
    ("esi1", 70, "mi papá se desmayó y no está respirando"),
    ("urgent", 30, "I don't think I'm breathing right, it feels tight"),
    # a stroke lesson or worry is not a stroke
    ("calm", 15, "we learned about strokes in biology and now I'm worried, but I just have a headache"),
    ("calm", 40, "I'm scared of having a stroke someday like my dad, I need a checkup"),
    ("esi1", 60, "we watched a video about stroke signs and my mom has them right now, her face is drooping"),
    # breathing distress in plain words
    ("urgent", 1, "my baby's belly is sucking in under his ribs every time he breathes"),
    ("urgent", 4, "my son makes a loud whistling noise when he breathes in and he has a barky cough"),
    ("urgent", 30, "my throat is so swollen I'm drooling and can't swallow"),
    ("urgent", 30, "its getting harder and harder to breathe"),
    ("calm", 1, "my baby is teething and drooling everywhere"),
    ("calm", 30, "my nostrils flare when I get angry, here for a rash"),
    ("calm", 30, "breathing harder after running but fine now"),
    # heart pain without the word "chest"
    ("urgent", 60, "took two nitroglycerin and the pressure is still there"),
    ("urgent", 62, "I had a heart attack three years ago and this feels exactly the same"),
    ("urgent", 60, "he says it's heartburn but he's clammy and grey"),
    ("calm", 60, "I need a refill on my nitro, I feel fine"),
    ("calm", 30, "I had gastric bypass and that same nausea feeling is back"),
    ("calm", 40, "tension headache, feels like a tight band around my head"),
    # a suicide plan with a place or a means, or a written goodbye, in any language
    ("crisis", 20, "I want to jump off the top floor of the parking structure"),
    ("crisis", 20, "I have my dad's gun and I'm going to shoot myself"),
    ("crisis", 20, "I wrote goodbye notes to my friends"),
    ("crisis", 20, "escribí una carta de despedida para mi familia"),
    ("crisis", 20, "我已经写好遗书了"),
    ("crisis", 20, "كتبت رسالة وداع لأهلي"),
    ("crisis", 20, "я написал предсмертную записку"),
    ("calm", 20, "jumped off the diving board and hit my head on the water, it hurts"),
    ("calm", 30, "if I quit now I am going to shoot myself in the foot"),
    ("calm", 30, "I wrote a farewell message for my coworker who is retiring and got a paper cut"),
    ("calm", 30, "我在跳楼价的店里买了鞋，脚扭了"),
    # household chemicals and swallowed objects
    ("urgent", 3, "my son drank some of the toilet bowl cleaner"),
    ("urgent", 4, "she drank a cup of something from under the bathroom sink"),
    ("crisis", 16, "my son drank drain cleaner after an argument with his dad"),
    ("urgent", 2, "孩子误喝了洗洁精"),
    ("urgent", 3, "ابني شرب منظف بالغلط"),
    ("urgent", 3, "bachche ne phenyl pi liya"),
    ("calm", 30, "I took the bleach from under the sink to clean the tub and slipped"),
    ("calm", 30, "I drank water from the bathroom sink"),
    ("urgent", 2, "he swallowed a marble and now he's choking and wheezing"),
    ("urgent", 3, "she put a bead in her mouth and now she keeps coughing and can't stop"),
    ("calm", 4, "my son swallowed a penny yesterday, it came out today, he's fine"),
]


@pytest.mark.parametrize("expect,age,text", CATEGORY_CASES, ids=[f"{e}:{t[:40]}" for e, _, t in CATEGORY_CASES])
def test_blind_test_categories_both_ways(expect, age, text):
    a = triage_rules.assess(text, age=age)
    level = a.floor.esi_level if a.floor else 9
    fired = [m.reason for m in a.matches]
    if expect == "esi1":
        assert level == 1, fired
    elif expect == "urgent":
        assert level <= 2, fired
    elif expect == "crisis":
        assert level <= 2 and a.crisis, fired
    elif expect == "calm":
        assert level >= 3, fired
    else:
        assert not a.crisis, fired
