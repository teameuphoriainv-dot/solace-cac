"""End-to-end judge flow, run in-process with no API keys and no network.

A patient checks in by text, a nurse signs in with a demo PIN, sees the patient in
the queue, enters bedside vitals, and the trained model re-checks the score. The
bedside safety floor must raise the score for danger-zone vitals and never lower it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from db import storage  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from services import triage_ml, triage_rules  # noqa: E402

HOSPITAL = "demo"
SHOCK_VITALS = {"systolic_bp": 88, "diastolic_bp": 54, "heart_rate": 124, "spo2": 91, "respiratory_rate": 24}
CALM_VITALS = {"systolic_bp": 122, "diastolic_bp": 78, "heart_rate": 76, "spo2": 99, "respiratory_rate": 14,
               "temperature_c": 36.8, "pain_score": 2, "gcs_total": 15, "mental_status": "alert"}

needs_model = pytest.mark.skipif(triage_ml._load() is None, reason="model files not downloaded (scripts/fetch_models.sh)")


@pytest.fixture
def client():
    settings.solace_mode = "local"
    storage._reset_for_tests()
    with TestClient(app) as c:  # the context manager runs startup, which seeds the demo hospital and clinicians
        yield c
    storage._reset_for_tests()


def _check_in(client: TestClient, text: str, age: int = 58) -> str:
    token = client.post(f"/api/{HOSPITAL}/start-intake").json()["token"]
    r = client.post(
        f"/api/{HOSPITAL}/intake",
        data={
            "patient_name": "Test Patient",
            "pre_transcribed_text": text,
            "medical_info": json.dumps({"age": age, "sex": "M", "conditions": ["hypertension"]}),
            "intake_token": token,
            "consent_granted": "true",
            "preferred_language": "en",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["patient_id"]


def _sign_in(client: TestClient) -> dict:
    r = client.post(f"/api/{HOSPITAL}/auth/login", json={"clinician_name": "Dr. Chen", "pin": "224466"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_patient_check_in_lands_in_the_nurse_queue(client):
    pid = _check_in(client, "I have crushing chest pain going down my left arm")
    headers = _sign_in(client)
    queue = client.get(f"/api/{HOSPITAL}/patients", headers=headers)
    assert queue.status_code == 200, queue.text
    body = queue.json()
    rows = body if isinstance(body, list) else body.get("patients", [])
    assert pid in {p["patient_id"] for p in rows}


def test_chest_pain_is_never_triaged_below_esi_2(client):
    pid = _check_in(client, "I have crushing chest pain going down my left arm")
    detail = client.get(f"/api/{HOSPITAL}/patients/{pid}", headers=_sign_in(client)).json()
    assert detail["esi_level"] <= 2


def test_queue_requires_sign_in(client):
    assert client.get(f"/api/{HOSPITAL}/patients").status_code == 401


def test_wrong_pin_is_rejected(client):
    r = client.post(f"/api/{HOSPITAL}/auth/login", json={"clinician_name": "Dr. Chen", "pin": "000000"})
    assert r.status_code == 401


def test_intake_without_consent_is_refused(client):
    token = client.post(f"/api/{HOSPITAL}/start-intake").json()["token"]
    r = client.post(
        f"/api/{HOSPITAL}/intake",
        data={"patient_name": "No Consent", "pre_transcribed_text": "my ankle hurts", "intake_token": token},
    )
    assert r.status_code == 403


@needs_model
def test_refine_triage_raises_shock_vitals_to_esi_2(client):
    """Regression: medical_info is stored as a JSON string, and refine-triage used to 500 on it."""
    pid = _check_in(client, "I have crushing chest pain going down my left arm")
    r = client.post(f"/api/{HOSPITAL}/patients/{pid}/refine-triage", json=SHOCK_VITALS, headers=_sign_in(client))
    assert r.status_code == 200, r.text
    ref = r.json()["refinement"]
    assert ref["esi_level"] <= 2
    if ref.get("model_esi_level", ref["esi_level"]) > 2:
        assert ref["safety_floor_reasons"], "the floor raised the score, so it must say why"


@needs_model
def test_refine_triage_stores_the_measured_vitals(client):
    pid = _check_in(client, "I twisted my ankle playing soccer and it is swollen", age=16)
    headers = _sign_in(client)
    r = client.post(f"/api/{HOSPITAL}/patients/{pid}/refine-triage", json=CALM_VITALS, headers=headers)
    assert r.status_code == 200, r.text
    assert 1 <= r.json()["refinement"]["esi_level"] <= 5
    detail = client.get(f"/api/{HOSPITAL}/patients/{pid}", headers=headers).json()
    assert detail.get("refined_esi_level") == r.json()["refinement"]["esi_level"]


def test_refine_triage_requires_sign_in(client):
    pid = _check_in(client, "my ankle hurts")
    assert client.post(f"/api/{HOSPITAL}/patients/{pid}/refine-triage", json=CALM_VITALS).status_code == 401


# ---- Safety floor unit checks ---------------------------------------------------------

def test_floor_raises_danger_zone_vitals_to_esi_2():
    esi, why = triage_rules.apply_floor(3, "my stomach hurts", SHOCK_VITALS, age=40)
    assert esi == 2 and why


def test_floor_never_lowers_the_model():
    esi, why = triage_rules.apply_floor(1, "my ankle hurts", CALM_VITALS, age=30)
    assert esi == 1 and why == []


def test_floor_leaves_normal_vitals_alone():
    assert triage_rules.apply_floor(4, "my ankle hurts", CALM_VITALS, age=30) == (4, [])


def test_floor_unresponsive_is_esi_1():
    esi, _ = triage_rules.apply_floor(3, "", {"gcs_total": 7}, age=50)
    assert esi == 1


def test_floor_skips_adult_heart_rate_for_young_children():
    # A heart rate of 120 is normal for a 2 year old, so it must not trigger the adult rule.
    assert triage_rules.apply_floor(4, "", {"heart_rate": 120}, age=2) == (4, [])
    assert triage_rules.apply_floor(4, "", {"heart_rate": 120}, age=30)[0] == 2


def test_floor_complaint_keywords_raise_acuity():
    esi, why = triage_rules.apply_floor(4, "sudden face droop and slurred speech", {}, age=70)
    assert esi == 1 and why


# ---- Check-in: the "Try an example" phrases, crisis wording, example patients ----------

C9_EXAMPLES = [
    ("Crushing chest pain down my left arm and I'm sweating", "en", 58, (1, 2)),
    ("I twisted my ankle playing soccer and it's swollen", "en", 16, (4, 5)),
    ("Me duele mucho el pecho y no puedo respirar", "es", 61, (1, 2)),
    ("My 3 year old has a fever of 104 and is very sleepy", "en", 3, (1, 2)),
    ("I need a refill of my blood pressure pills", "en", 67, (4, 5)),
]
OFFSITE_DESTINATIONS = {"telehealth", "self_care", "schedule"}


def _intake(client: TestClient, text: str, language: str = "en", age: int = 40) -> dict:
    token = client.post(f"/api/{HOSPITAL}/start-intake").json()["token"]
    r = client.post(
        f"/api/{HOSPITAL}/intake",
        data={
            "patient_name": "Example",
            "pre_transcribed_text": text,
            "medical_info": json.dumps({"age": age, "sex": "female"}),
            "intake_token": token,
            "consent_granted": "true",
            "preferred_language": language,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def no_ai(monkeypatch):
    monkeypatch.setattr("lib.claude.available", lambda: False)


@needs_model
@pytest.mark.parametrize("text,language,age,expected", C9_EXAMPLES)
def test_try_an_example_phrases_get_the_right_score(client, no_ai, text, language, age, expected):
    body = _intake(client, text, language, age)
    lo, hi = expected
    assert lo <= body["esi_level"] <= hi, body
    assert body["confidence_band"] is None, "the patient's screen never gets model numbers"
    assert body["explanation_key"] and body["patient_explanation"]
    assert body["care_recommendation"]["destination"] not in OFFSITE_DESTINATIONS


def test_suicidal_check_in_gets_988_and_a_high_score(client, no_ai):
    body = _intake(client, "I feel like I want to end my life", age=17)
    assert body["esi_level"] <= 2
    assert body["explanation_key"] == "crisis" and "988" in body["patient_explanation"]
    assert "988" in body["care_recommendation"]["rationale"]


@needs_model  # without the model files the rules alone set the score, so there is no model score to compare (H06)
def test_rule_raised_score_is_explained_to_the_nurse(client, no_ai):
    pid = _intake(client, "I can't breathe")["patient_id"]
    detail = client.get(f"/api/{HOSPITAL}/patients/{pid}", headers=_sign_in(client)).json()
    assert detail["esi_level"] <= 2
    assert detail["triage_source"].startswith("rule:")
    stored = storage.get_patient(pid)
    assert json.loads(stored["safety_floor_reasons"]) and stored["model_esi_level"] >= detail["esi_level"]


def test_no_follow_up_questions_when_the_rules_say_esi_2(client, no_ai):
    r = client.post(f"/api/{HOSPITAL}/transcribe", data={
        "pre_transcribed_text": "I feel like I want to end my life", "consent_granted": "true", "preferred_language": "en",
    })
    assert r.status_code == 200, r.text
    assert r.json()["followups"] == []


def test_spanish_follow_up_questions_without_ai(client, no_ai):
    r = client.post(f"/api/{HOSPITAL}/transcribe", data={
        "pre_transcribed_text": "Me duele la cabeza", "consent_granted": "true", "preferred_language": "es",
    })
    assert r.status_code == 200, r.text
    assert r.json()["followups"][0]["question"] == "¿Desde cuándo tiene esto?"


def test_startup_adds_the_five_example_patients(client):
    rows = storage.list_patients_for_hospital(HOSPITAL, status="all")
    examples = sorted((p["esi_level"], p["name"]) for p in rows if p.get("seed"))
    assert [e[1] for e in examples] == ["Marcus", "Elena", "Priya", "James", "Sofia"]
    if triage_ml._load() is not None:
        assert [e[0] for e in examples] == [1, 2, 3, 4, 5]
    by_name = {p["name"]: p for p in rows if p.get("seed")}
    assert by_name["Elena"]["language"] == "es" and by_name["Priya"]["pain_flagged"] is True
    assert all(p["artifacts_status"] == "ready" and json.loads(p["comfort_protocol"]) for p in by_name.values())


def test_example_seed_is_idempotent_and_never_calls_ai(client, monkeypatch):
    from services import demo_seed  # noqa: PLC0415

    def boom(*_a, **_k):
        raise AssertionError("the example seed must not call an AI service")

    monkeypatch.setattr("lib.claude.available", lambda: True)
    monkeypatch.setattr("lib.claude.messages_create", boom)
    assert demo_seed.seed_canonical_patients(HOSPITAL) == []  # already there from startup
    for p in storage.list_patients_for_hospital(HOSPITAL, status="all"):
        storage.delete_patient(p["patient_id"])
    assert len(demo_seed.seed_canonical_patients(HOSPITAL)) == 5
