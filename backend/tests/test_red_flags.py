"""Red-flag stress test for the check-in score. Two-sided on purpose.

* Every emergency phrase must be shown at or above its expected urgency even if
  the model guesses ESI 5, so the rules alone carry it.
* Everyday complaints must stay at ESI 4 or 5, with the real model and with the
  rule-based engine that runs when the model files are missing.
* A check-in in another language that the offline rules cannot read is held at
  ESI 3 when no AI translation is available.

scripts/red_flag_report.py runs these same lists through the old and new logic
and writes docs/evidence/red-flag-stress-test.md. The red teams' larger case sets,
and unit checks of the rule fixes they led to, are in tests/test_redteam_regression.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from lib import fallbacks  # noqa: E402
from services import comfort_protocol, followups, intake_pipeline, triage, triage_ml, triage_rules  # noqa: E402

needs_model = pytest.mark.skipif(triage_ml._load() is None, reason="model files not downloaded (scripts/fetch_models.sh)")

# (words, language, most lenient ESI allowed, age on the form)
EMERGENCIES: list[tuple[str, str, int, int | None]] = [
    # The "Try an example" phrases on the check-in screen.
    ("Crushing chest pain down my left arm and I'm sweating", "en", 2, 58),
    ("Me duele mucho el pecho y no puedo respirar", "es", 2, 61),
    ("My 3 year old has a fever of 104 and is very sleepy", "en", 2, None),
    # Phrases the audit found under-triaged.
    ("I feel like I want to end my life", "en", 2, 17),
    ("I have been feeling suicidal and want to end my life", "en", 2, 17),
    ("I took a whole bottle of tylenol", "en", 2, 20),
    ("he fell off a ladder and hit his head and is confused", "en", 2, 45),
    ("my son is 2 and has a fever of 104 and is very sleepy", "en", 2, None),
    ("I can't breathe", "en", 2, 40),
    ("my chest hurts a lot and I can't breathe", "en", 2, 45),
    ("my face is drooping and my left arm is weak and my speech is slurred", "en", 1, 70),
    ("bad headache and fever for two days with a stiff neck", "en", 2, 34),
    ("I cut my hand on glass and it won't stop bleeding.", "en", 2, 30),
    ("I am 30 weeks pregnant and bleeding", "en", 2, 28),
    ("my throat is swelling after eating peanuts", "en", 2, 14),
    ("I fainted at work and need a work note", "en", 2, 30),
    ("I can’t breathe and need a refill of my inhaler", "en", 2, 30),
    ("I need a refill of my blood thinner, my gums keep bleeding and I feel dizzy and faint", "en", 2, 70),
    ("my husband collapsed, he is not breathing", "en", 1, 60),
    ("I can't breathe well and my lips feel tingly", "en", 2, 30),
    ("I'm bleeding a lot", "en", 2, 30),
    ("worst headache of my life, came on suddenly an hour ago", "en", 2, 50),
    ("Tengo un dolor fuerte en el pecho y me cuesta respirar", "es", 2, 50),
    ("मेरे सीने में बहुत दर्द है और सांस लेने में तकलीफ है", "hi", 2, 50),
    ("胸口很痛，喘不过气", "zh", 2, 50),
    ("عندي ألم شديد في صدري ولا أستطيع التنفس", "ar", 2, 50),
    # More English phrasings, including someone typing for another person.
    ("I'm having a heart attack", "en", 2, 60),
    ("there is a lot of pressure in my chest", "en", 2, 55),
    ("It's really hard for me to breathe", "en", 2, 40),
    ("I can barely breathe", "en", 2, 40),
    ("I'm not breathing well", "en", 2, 40),
    ("he is gasping for air", "en", 1, 60),
    ("my baby's lips are turning blue", "en", 1, None),
    ("my daughter is choking", "en", 1, 6),
    ("my wife passed out and won't wake up", "en", 1, 50),
    ("I think I'm having a stroke", "en", 1, 70),
    ("sudden weakness on the left side of my body", "en", 1, 70),
    ("my face feels numb on one side", "en", 1, 60),
    ("my lips and tongue are swollen", "en", 2, 30),
    ("I'm having an allergic reaction and my throat feels tight", "en", 2, 25),
    ("I'm pregnant and spotting with bad cramps", "en", 2, 29),
    ("I passed out in the shower", "en", 2, 40),
    ("I feel like I'm going to faint", "en", 2, 40),
    ("I hit my head and threw up twice", "en", 2, 16),
    ("my 4 year old has a fever and is hard to wake up", "en", 2, None),
    ("my 6 week old baby has a fever", "en", 2, None),
    ("I don't want to live anymore", "en", 2, 16),
    ("I want to kill myself", "en", 2, 19),
    ("I want to die", "en", 2, 22),
    ("I took too many pills on purpose", "en", 2, 18),
    ("I took 30 of my sleeping pills", "en", 2, 40),
    ("my toddler swallowed a laundry pod", "en", 2, None),
    ("my son is having a seizure", "en", 2, 9),
    ("I was shot in the leg", "en", 1, 25),
    ("my finger got cut off by a saw", "en", 1, 40),
    ("I'm coughing up blood", "en", 2, 60),
    ("my stiff neck and fever started this morning", "en", 2, 20),
    # Other languages: chest pain, cannot breathe, heavy bleeding, suicidal thoughts, stroke, unconscious.
    ("Me corté la mano y no para de sangrar", "es", 2, 30),
    ("Ya no quiero vivir", "es", 2, 17),
    ("Mi papá tiene la cara caída y no puede hablar bien", "es", 1, 70),
    ("Mi esposo está inconsciente", "es", 1, 60),
    ("Mi hijo de 2 años tiene fiebre y está muy dormido", "es", 2, None),
    ("我胸口很痛", "zh", 2, 50),
    ("我喘不过气", "zh", 2, 50),
    ("伤口一直流血，流血不止", "zh", 2, 30),
    ("我想自杀", "zh", 2, 20),
    ("我爸爸嘴歪了，说话不清", "zh", 1, 70),
    ("我妈妈昏迷了", "zh", 1, 70),
    ("لا أستطيع التنفس", "ar", 2, 40),
    ("عندي نزيف شديد", "ar", 2, 40),
    ("أريد أن أموت", "ar", 2, 20),
    ("أبي عنده جلطة دماغية", "ar", 1, 70),
    ("زوجي فاقد الوعي", "ar", 1, 60),
    ("मुझे साँस लेने में तकलीफ है", "hi", 2, 40),
    ("बहुत ज्यादा खून बह रहा है", "hi", 2, 30),
    ("मैं आत्महत्या करना चाहता हूं", "hi", 2, 20),
    ("मेरे पिता को लकवा मार गया है", "hi", 1, 70),
    ("मेरी मां बेहोश हैं", "hi", 1, 70),
    ("Tôi bị đau ngực", "vi", 2, 50),
    ("Tôi khó thở", "vi", 2, 50),
    ("Vết thương chảy máu không ngừng", "vi", 2, 30),
    ("Tôi muốn chết", "vi", 2, 20),
    ("Bố tôi bị méo miệng và yếu nửa người", "vi", 1, 70),
    ("Mẹ tôi bị bất tỉnh", "vi", 1, 70),
    ("J'ai une douleur dans la poitrine", "fr", 2, 50),
    ("Je n’arrive pas à respirer", "fr", 2, 50),
    ("Je saigne beaucoup et ça ne s'arrête pas", "fr", 2, 30),
    ("Je veux mourir", "fr", 2, 20),
    ("Mon père a le visage paralysé d'un côté", "fr", 1, 70),
    ("Ma mère a perdu connaissance", "fr", 1, 70),
    ("Estou com uma dor forte no peito", "pt", 2, 50),
    ("Não consigo respirar", "pt", 2, 50),
    ("Estou sangrando muito", "pt", 2, 30),
    ("Eu quero morrer", "pt", 2, 20),
    ("Meu pai está com a boca torta e a fala enrolada", "pt", 1, 70),
    ("Minha mãe está inconsciente", "pt", 1, 70),
    ("У меня сильная боль в груди", "ru", 2, 50),
    ("Я не могу дышать", "ru", 2, 50),
    ("Кровь не останавливается", "ru", 2, 30),
    ("Я хочу умереть", "ru", 2, 20),
    ("У отца перекосило лицо", "ru", 1, 70),
    ("Муж без сознания", "ru", 1, 60),
    ("가슴이 너무 아파요", "ko", 2, 50),
    ("숨을 쉴 수 없어요", "ko", 2, 50),
    ("피가 멈추지 않아요", "ko", 2, 30),
    ("죽고 싶어요", "ko", 2, 20),
    ("아버지 얼굴이 한쪽으로 처졌어요", "ko", 1, 70),
    ("남편이 의식이 없어요", "ko", 1, 60),
    ("Masakit ang dibdib ko", "tl", 2, 50),
    ("Hindi ako makahinga", "tl", 2, 50),
    ("Ayaw tumigil ang pagdurugo", "tl", 2, 30),
    ("Gusto ko nang mamatay", "tl", 2, 20),
    ("Tabingi ang mukha ng tatay ko", "tl", 1, 70),
    ("Nawalan ng malay ang nanay ko", "tl", 1, 70),
    ("میرے سینے میں شدید درد ہے", "ur", 2, 50),
    ("مجھے سانس لینے میں تکلیف ہے", "ur", 2, 50),
    ("بہت زیادہ خون بہہ رہا ہے", "ur", 2, 30),
    ("میں خودکشی کرنا چاہتا ہوں", "ur", 2, 20),
    ("میرے والد کو فالج ہو گیا ہے", "ur", 1, 70),
    ("میری امی بے ہوش ہیں", "ur", 1, 70),
    ("درد شدید در قفسه سینه دارم", "fa", 2, 50),
    ("نمی‌توانم نفس بکشم", "fa", 2, 50),
    ("خونریزی شدید دارم", "fa", 2, 30),
    ("می‌خواهم خودکشی کنم", "fa", 2, 20),
    ("پدرم سکته مغزی کرده", "fa", 1, 70),
    ("مادرم بیهوش شده", "fa", 1, 70),
    ("আমার বুকে খুব ব্যথা", "bn", 2, 50),
    ("আমার শ্বাস নিতে কষ্ট হচ্ছে", "bn", 2, 50),
    ("রক্ত বন্ধ হচ্ছে না", "bn", 2, 30),
    ("আমি আত্মহত্যা করতে চাই", "bn", 2, 20),
    ("আমার বাবার স্ট্রোক হয়েছে", "bn", 1, 70),
    ("আমার মা অজ্ঞান হয়ে গেছেন", "bn", 1, 70),
    ("胸が痛いです", "ja", 2, 50),
    ("息ができない", "ja", 2, 50),
    ("血が止まらない", "ja", 2, 30),
    ("死にたい", "ja", 2, 20),
    ("父の顔が歪んで、ろれつが回らない", "ja", 1, 70),
    ("夫の意識がない", "ja", 1, 60),
    ("Ich habe starke Brustschmerzen", "de", 2, 50),
    ("Ich kann nicht atmen", "de", 2, 50),
    ("Die Wunde blutet sehr stark", "de", 2, 30),
    ("Ich will nicht mehr leben", "de", 2, 20),
    ("Ich glaube, mein Vater hat einen Schlaganfall", "de", 1, 70),
    ("Mein Mann ist bewusstlos", "de", 1, 60),
    ("Ho un forte dolore al petto", "it", 2, 50),
    ("Non riesco a respirare", "it", 2, 50),
    ("Sanguina molto e il sangue non si ferma", "it", 2, 30),
    ("Voglio morire", "it", 2, 20),
    ("Mia madre ha la bocca storta e non riesce a parlare", "it", 1, 70),
    ("Mio marito è svenuto e non risponde", "it", 1, 60),
    ("Göğüs ağrısı var", "tr", 2, 50),
    ("Nefes alamıyorum", "tr", 2, 50),
    ("Kanama durmuyor", "tr", 2, 30),
    ("Ölmek istiyorum", "tr", 2, 20),
    ("Babanın yüzü kaydı ve konuşması bozuldu", "tr", 1, 70),
    ("Annem bilincini kaybetti", "tr", 1, 70),
    ("Mam silny ból w klatce piersiowej", "pl", 2, 50),
    ("Nie mogę oddychać", "pl", 2, 50),
    ("Bardzo mocno krwawię", "pl", 2, 30),
    ("Chcę umrzeć", "pl", 2, 20),
    ("Mój tata ma opadnięty kącik ust", "pl", 1, 70),
    ("Moja mama jest nieprzytomna", "pl", 1, 70),
    ("Dada saya sakit sekali", "id", 2, 50),
    ("Saya sesak napas", "id", 2, 50),
    ("Darahnya tidak mau berhenti", "id", 2, 30),
    ("Saya ingin bunuh diri", "id", 2, 20),
    ("Bicaranya pelo dan wajahnya mencong", "id", 1, 70),
    ("Suami saya tidak sadarkan diri", "id", 1, 60),
]

# Everyday complaints in English: must stay at ESI 4 or 5. (words, age)
EVERYDAY: list[tuple[str, int]] = [
    ("I twisted my ankle playing soccer and it's swollen", 16),
    ("I need a refill of my blood pressure pills", 50),
    ("I need a school note", 15),
    ("I have a mild sore throat", 22),
    ("I have a small cut on my finger that stopped bleeding", 30),
    ("I have a faint rash on my arm", 30),
    ("I stubbed my toe", 30),
    ("I need a flu shot", 40),
    ("I need a work note", 30),
    ("I have a cough and a runny nose", 30),
    ("I hurt my knee playing basketball", 30),
    ("I have a toothache", 30),
]

# Must not trip a red-flag rule even though they contain a red-flag word.
NOT_RED_FLAGS: list[str] = [e[0] for e in EVERYDAY] + [
    "I have a faint smell of smoke on my clothes and a mild headache",
    "I feel a faint pain in my knee",
    "I can't breathe through my nose because of my cold",
    "I'm not suicidal, I just have a headache",
    "I don't want to die from this cough, it is just annoying",
    "I have a cough but no chest pain",
    "I had a stroke 3 years ago and need a refill",
    "I need a refill of my seizure medication",
    "I have food poisoning",
    "I touched poison ivy",
    "I knocked out a tooth",
    "I was hanging out with friends and twisted my knee",
    "my mom has a history of stroke and I want a checkup",
    "my son is a little warm but playing normally",
    "I got a chest x-ray last week and need the results",
]

# Everyday complaints in other languages. With no AI they are held at ESI 3 so a nurse reads them.
EVERYDAY_OTHER: list[tuple[str, str]] = [
    ("Me torcí el tobillo y está hinchado", "es"),
    ("Necesito una receta para mis pastillas de la presión", "es"),
    ("我头很痛，已经三天了", "zh"),
    ("J'ai mal à la gorge depuis deux jours", "fr"),
    ("Tenho uma tosse leve", "pt"),
    ("У меня насморк", "ru"),
]

CASES: list[dict] = (
    [{"text": t, "language": lang, "expected_max_esi": mx, "age": age} for t, lang, mx, age in EMERGENCIES]
    + [{"text": t, "language": "en", "expected_max_esi": 5, "expected_min_esi": 4, "age": age} for t, age in EVERYDAY]
    + [{"text": t, "language": lang, "expected_max_esi": 5, "expected_min_esi": 3, "age": 35} for t, lang in EVERYDAY_OTHER]
)


def _fixed_model(esi: int):
    def predict(*_args, **_kwargs) -> triage.TriagePrediction:
        return triage.TriagePrediction(
            esi_level=esi, confidence=0.99, confidence_band=f"ESI {esi} (confidence 99%)", shap_values={},
            source="test_stub", clinical_flags=[], composites={}, recommendation="", probabilities=[0.0] * 5,
        )
    return predict


@pytest.fixture
def model_says(monkeypatch):
    """Replace the model (and the engine) with one that always guesses the given level."""
    def use(esi: int) -> None:
        monkeypatch.setattr(triage, "_predict_trained", _fixed_model(esi))
        monkeypatch.setattr(triage, "_predict_engine", _fixed_model(esi))
    return use


def _check_in(text: str, language: str = "en", age: int | None = 35, **kw) -> intake_pipeline.IntakeTriage:
    info = {"age": age, "sex": "female"} if age is not None else {"sex": "female"}
    return intake_pipeline.triage_check_in(text, medical_info=info, language=language, allow_ai=False, **kw)


# ---- emergencies ----------------------------------------------------------------------

@pytest.mark.parametrize("text,language,expected,age", EMERGENCIES, ids=[f"{e[1]}:{e[0][:40]}" for e in EMERGENCIES])
def test_emergency_is_caught_even_when_the_model_says_5(model_says, text, language, expected, age):
    model_says(5)
    t = _check_in(text, language, age)
    assert t.esi_level <= expected, f"{text!r} shown ESI {t.esi_level}, expected {expected} or more urgent"
    assert t.rule is not None and t.reasons, "a rule raised it, so the clinician must see why"


@pytest.mark.parametrize("language", sorted({e[1] for e in EMERGENCIES} - {"en"}))
def test_every_language_has_core_red_flags(language):
    flags = triage_rules.LEXICONS[language]
    for key in ("resus", "stroke", "chest", "breath", "bleed", "crisis"):
        assert key in flags, f"{language} is missing {key}"


# ---- everyday complaints stay low ---------------------------------------------------------

@pytest.mark.parametrize("text", NOT_RED_FLAGS)
def test_everyday_words_do_not_trip_a_red_flag(text):
    assert triage_rules.assess(text, age=30).floor is None


@needs_model
@pytest.mark.parametrize("text,age", EVERYDAY)
def test_everyday_complaints_stay_low_with_the_model(text, age):
    assert _check_in(text, "en", age).esi_level in (4, 5)


@pytest.mark.parametrize("text,age", EVERYDAY)
def test_everyday_complaints_stay_low_without_the_model_files(monkeypatch, text, age):
    monkeypatch.setattr(triage, "_predict_trained", lambda *a, **k: None)
    assert _check_in(text, "en", age).esi_level in (4, 5)


# ---- the paperwork rule can never hide a complaint -----------------------------------------

@pytest.mark.parametrize("text", [
    "I fainted at work and need a work note",
    "I can't breathe and need a refill of my inhaler",
    "I need a refill of my blood thinner, my gums keep bleeding and I feel dizzy and faint",
])
def test_paperwork_never_lowers_a_red_flag(model_says, text):
    model_says(4)
    assert _check_in(text).esi_level <= 2


def test_paperwork_only_applies_when_the_model_says_4_or_5(model_says):
    model_says(3)
    assert _check_in("I need a work note").esi_level == 3
    model_says(4)
    t = _check_in("I need a work note")
    assert t.esi_level == 5 and t.rule is triage_rules.ADMIN


# ---- languages the offline rules cannot fully read ------------------------------------------

@pytest.mark.parametrize("text,language", EVERYDAY_OTHER)
def test_other_language_is_held_at_3_without_ai(model_says, text, language):
    model_says(5)
    t = _check_in(text, language)
    assert t.esi_level == 3 and t.needs_reading
    assert t.explanation_key == "needs_reading"
    assert "needs_interpreter" in json.loads(t.record_fields()["clinical_flags"])


def test_spanish_backstop_explanation_is_in_spanish(model_says):
    model_says(5)
    t = _check_in("Me torcí el tobillo y está hinchado", "es")
    assert t.explanation.startswith("Una enfermera leerá lo que escribió")


def test_english_typed_with_another_language_selected_is_read_normally(model_says):
    model_says(4)
    t = _check_in("I twisted my ankle and it is swollen", "es")
    assert t.esi_level == 4 and not t.needs_reading


def test_ai_translation_lets_the_rules_read_it(model_says, monkeypatch):
    model_says(4)
    monkeypatch.setattr(intake_pipeline, "translate_to_english", lambda text, lang: "My chest hurts a lot")
    t = intake_pipeline.triage_check_in("Fáj a mellkasom", medical_info={"age": 50}, language="hu")
    assert t.esi_level == 2 and t.english == "My chest hurts a lot" and not t.needs_reading


def test_ai_translation_of_an_everyday_complaint_is_not_held_at_3(model_says, monkeypatch):
    model_says(4)
    monkeypatch.setattr(intake_pipeline, "translate_to_english", lambda text, lang: "I twisted my ankle")
    t = intake_pipeline.triage_check_in("Me torcí el tobillo", medical_info={"age": 30}, language="es")
    assert t.esi_level == 4 and not t.needs_reading


# ---- the words that go with the score agree with it -------------------------------------------

def test_crisis_gets_988_everywhere(model_says):
    model_says(4)
    text = "I feel like I want to end my life"
    t = _check_in(text, "en", 17)
    assert t.esi_level == 2 and t.crisis
    assert "988" in t.explanation and t.care.kind == "crisis" and "988" in t.care.rationale
    cards = comfort_protocol.fallback_cards(text, t.esi_level, "en", {"age": 17})
    assert any("988" in c["instruction"] or "988" in c["title"] for c in cards)


def test_esi_1_bystander_gets_tell_staff_now_not_a_crisis_card(model_says):
    model_says(4)
    text = "my husband collapsed, he is not breathing"
    t = _check_in(text, "en", 60)
    assert t.esi_level == 1 and not t.crisis
    assert t.care.kind == "now" and "911" not in t.care.rationale
    assert comfort_protocol.fallback_cards(text, 1, "en", {"age": 60})[0]["title"] == "Get help now"


def test_young_child_gets_cards_written_to_the_parent(model_says):
    model_says(4)
    text = "My 3 year old has a fever of 104 and is very sleepy"
    t = _check_in(text, "en", None)
    cards = comfort_protocol.fallback_cards(text, t.esi_level, "en", {})
    assert any("child" in c["instruction"] for c in cards)


def test_patient_response_has_no_model_numbers(model_says):
    model_says(4)
    fields = _check_in("my ankle hurts").patient_fields()
    assert fields["confidence_band"] is None
    assert not any("confidence" in k and fields[k] is not None for k in fields)


def test_rule_raised_score_hides_the_model_confidence(model_says):
    model_says(4)
    rec = _check_in("I can't breathe").record_fields()
    assert rec["esi_level"] == 2 and rec["model_esi_level"] == 4
    assert rec["esi_confidence"] is None and rec["triage_source"] == "rule:rule.esi2.breathing"


# ---- follow-up questions ------------------------------------------------------------------

@pytest.mark.parametrize("text", ["I feel like I want to end my life", "my husband collapsed, he is not breathing",
                                  "Me duele mucho el pecho y no puedo respirar"])
def test_no_follow_up_questions_for_esi_1_or_2(monkeypatch, text):
    monkeypatch.setattr("lib.claude.available", lambda: False)
    assert followups.generate_questions(text, None, "en") == []


def test_follow_up_questions_in_spanish_and_skip_what_was_said(monkeypatch):
    monkeypatch.setattr("lib.claude.available", lambda: False)
    qs = followups.generate_questions("Me duele la cabeza desde ayer", None, "es")
    assert [q["question"] for q in qs] == ["¿Está empeorando?"]
    assert followups.generate_questions("my knee hurts and it is getting worse", None, "en")[0]["id"] == "duration"


# ---- the bedside floor keeps every reason at the final level ----------------------------------

def test_apply_floor_keeps_vital_reasons_when_the_complaint_reached_the_same_level():
    vitals = {"systolic_bp": 88, "heart_rate": 124, "spo2": 91, "respiratory_rate": 24}
    esi, why = triage_rules.apply_floor(3, "crushing chest pain", vitals, age=60)
    assert esi == 2
    assert any("chest" in w.lower() for w in why) and any("heart rate over 100" in w for w in why)


# ---- fixed copy ---------------------------------------------------------------------------------

def test_fixed_cards_never_say_to_eat_or_drink_and_always_say_tell_staff():
    for lang, table in fallbacks.COMFORT_CARDS.items():
        for key, cards in table.items():
            assert len(cards) == 3, (lang, key)
            text = " ".join(f"{c['title']} {c['instruction']}" for c in cards).lower()
            for bad in ("sip", "hydrat", "drink water", "beba agua", "tome agua", "—", "–"):
                assert bad not in text, (lang, key, bad)
            assert any(w in text for w in ("staff", "nurse", "personal", "enfermera", "988")), (lang, key)


def test_explanations_never_sound_like_a_diagnosis():
    for lang in ("en", "es"):
        for lvl in (1, 2, 3, 4, 5):
            text = fallbacks.patient_explanation(lvl, lang).lower()
            assert "minor" not in text and "stable" not in text and "—" not in text
            assert any(w in text for w in ("staff", "personal", "911"))
