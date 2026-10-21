"""Bedside re-check: queue order, the safety floor on screen, rules-only mode, factors.

Most tests stub the model so they run the same with or without the model files.
The ones marked needs_model use the real 5-fold LightGBM.
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
from lib import claude  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from routers import triage as triage_router  # noqa: E402
from services import disposition, triage_ml, workup  # noqa: E402

HOSPITAL = "demo"
SHOCK_VITALS = {"systolic_bp": 88, "diastolic_bp": 54, "heart_rate": 124, "spo2": 91,
                "respiratory_rate": 24, "mental_status": "alert"}
CALM_VITALS = {"systolic_bp": 122, "diastolic_bp": 78, "heart_rate": 76, "spo2": 99, "respiratory_rate": 14,
               "temperature_c": 36.8, "pain_score": 2, "gcs_total": 15, "mental_status": "alert"}

needs_model = pytest.mark.skipif(triage_ml._get_art() is None, reason="model files not downloaded (scripts/fetch_models.sh)")


@pytest.fixture
def client(monkeypatch):
    settings.solace_mode = "local"
    monkeypatch.setattr(claude, "available", lambda: False)  # these tests are about the no-key path
    storage._reset_for_tests()
    with TestClient(app) as c:
        yield c
    storage._reset_for_tests()


@pytest.fixture
def headers(client):
    r = client.post(f"/api/{HOSPITAL}/auth/login", json={"clinician_name": "Dr. Chen", "pin": "224466"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _add_patient(pid: str, esi: int, created_at: str, transcript: str = "my stomach hurts", age: int = 45) -> str:
    storage.put_patient({
        "patient_id": pid,
        "hospital_id": HOSPITAL,
        "name": f"Test {pid}",
        "esi_level": esi,
        "status": "waiting",
        "created_at": created_at,
        "transcript": transcript,
        "language": "en",
        "medical_info": json.dumps({"age": age, "sex": "female", "conditions": []}),
    })
    return pid


def _fake_model(esi: int = 3, confidence: float = 0.67):
    def predict(patient, vitals):
        probs = {str(i): 0.0 for i in range(1, 6)}
        probs[str(esi)] = confidence
        probs[str(min(esi + 1, 5))] = round(1 - confidence, 6)
        return {
            "esi_level": esi, "confidence": confidence, "probabilities": probs,
            "conformal_set": [esi], "conformal_q_hat": 0.3, "conformal_q_hat_by_class": None,
            "conformal_method": "test", "conformal_note": "test note",
            "top_features": [{"feature": "Age", "code": "age", "kind": "measure", "value": 45.0,
                              "shap": 0.1, "direction": "increases"}],
            "source": "lgbm_5fold_v2", "model_metrics": {}, "dataset": triage_ml.MODEL_CARD_DATASET,
            "model_card": triage_ml.model_card(None, "test note"),
        }
    return predict


def _queue_ids(client, headers) -> list[str]:
    r = client.get(f"/api/{HOSPITAL}/patients", headers=headers)
    assert r.status_code == 200, r.text
    return [p["patient_id"] for p in r.json()["patients"]]


# ---- Queue order ------------------------------------------------------------------------

def test_queue_sorts_by_bedside_score_when_present():
    rows = [
        {"esi_level": 3, "created_at": "2026-10-18T10:00:00Z", "patient_id": "early"},
        {"esi_level": 4, "refined_esi_level": 2, "created_at": "2026-10-18T10:05:00Z", "patient_id": "late"},
        {"esi_level": 2, "created_at": "2026-10-18T10:10:00Z", "patient_id": "later_two"},
    ]
    rows.sort(key=lambda p: (storage.current_esi(p), p["created_at"]))
    assert [r["patient_id"] for r in rows] == ["late", "later_two", "early"]


def test_refined_patient_moves_up_the_queue(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=4, confidence=0.9))
    _add_patient("p-early", 3, "2026-10-18T09:00:00Z")
    _add_patient("p-late", 4, "2026-10-18T09:30:00Z", transcript="I cut my finger")
    before = _queue_ids(client, headers)
    assert before.index("p-early") < before.index("p-late")

    r = client.post(f"/api/{HOSPITAL}/patients/p-late/refine-triage", json=SHOCK_VITALS, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["refinement"]["esi_level"] == 2

    after = _queue_ids(client, headers)
    assert after.index("p-late") < after.index("p-early")


# ---- The safety floor on screen ---------------------------------------------------------

def test_floored_result_keeps_the_model_guess_and_drops_the_confidence(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=3, confidence=0.67))
    _add_patient("p-1", 4, "2026-10-18T09:00:00Z")
    r = client.post(f"/api/{HOSPITAL}/patients/p-1/refine-triage", json=SHOCK_VITALS, headers=headers)
    assert r.status_code == 200, r.text
    ref = r.json()["refinement"]
    assert ref["esi_level"] == 2
    assert ref["model_esi_level"] == 3
    assert ref["model_confidence"] == pytest.approx(0.67)
    assert ref["confidence"] is None
    assert ref["raised_by_safety_rules"] is True
    assert ref["conformal_set"] == [2]
    assert ref["source"] == "safety_floor+lgbm_5fold_v2"
    reasons = ref["safety_floor_reasons"]
    assert "heart rate over 100" in reasons
    assert any("92%" in x for x in reasons)
    assert all(not x.startswith("ESI") for x in reasons), reasons
    assert ref["safety_rules_agree"] == []


def test_vital_reasons_are_kept_when_the_complaint_rule_reached_the_same_level(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=3))
    _add_patient("p-chest", 2, "2026-10-18T09:00:00Z", transcript="chest pain since this morning")
    ref = client.post(f"/api/{HOSPITAL}/patients/p-chest/refine-triage", json=SHOCK_VITALS,
                      headers=headers).json()["refinement"]
    assert ref["esi_level"] == 2
    reasons = ref["safety_floor_reasons"]
    assert any("chest pain" in x.lower() for x in reasons), reasons
    assert "heart rate over 100" in reasons
    assert all(not x.startswith("ESI") for x in reasons), reasons


def test_unraised_result_keeps_its_confidence(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=4, confidence=0.91))
    _add_patient("p-calm", 4, "2026-10-18T09:00:00Z", transcript="I twisted my ankle")
    ref = client.post(f"/api/{HOSPITAL}/patients/p-calm/refine-triage", json=CALM_VITALS,
                      headers=headers).json()["refinement"]
    assert ref["esi_level"] == 4
    assert ref["confidence"] == pytest.approx(0.91)
    assert ref["raised_by_safety_rules"] is False
    assert ref["safety_floor_reasons"] == []


def test_refinement_survives_a_reload(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=3, confidence=0.67))
    _add_patient("p-2", 4, "2026-10-18T09:00:00Z")
    client.post(f"/api/{HOSPITAL}/patients/p-2/refine-triage", json=SHOCK_VITALS, headers=headers)
    d = client.get(f"/api/{HOSPITAL}/patients/p-2", headers=headers).json()
    assert d["refined_esi_level"] == 2
    assert d["current_esi_level"] == 2
    assert d["refined_confidence"] is None
    assert d["refined_model_esi_level"] == 3
    assert d["refined_model_confidence"] == pytest.approx(0.67)
    assert "heart rate over 100" in d["refined_safety_floor_reasons"]
    card = d["refined_model_card"]
    assert "synthetic" in card["dataset"] and card["accuracy_note"]
    assert json.loads(d["measured_vitals"])["heart_rate"] == 124


def test_refine_needs_at_least_one_vital(client, headers):
    _add_patient("p-empty", 4, "2026-10-18T09:00:00Z")
    for body in ({"mental_status": "alert"}, {}):
        r = client.post(f"/api/{HOSPITAL}/patients/p-empty/refine-triage", json=body, headers=headers)
        assert r.status_code == 400
        assert isinstance(r.json()["detail"], str)


@pytest.mark.parametrize("body, expected", [
    ({"heart_rate": 300}, "Heart rate must be 250 or less."),
    ({"systolic_bp": 20}, "Blood pressure (top number) must be 40 or more."),
    ({"temperature_c": 101}, "Temperature (C) must be 43 or less."),
    ({"heart_rate": "fast"}, "Heart rate must be a number."),
    ({"gcs_total": 14.5}, "GCS must be a whole number."),
    ({"o2": 90}, "Unknown vital sign: o2."),
])
def test_bad_vitals_get_one_plain_sentence(client, headers, body, expected):
    _add_patient("p-bad", 4, "2026-10-18T09:00:00Z")
    r = client.post(f"/api/{HOSPITAL}/patients/p-bad/refine-triage", json=body, headers=headers)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == expected


def test_a_rule_that_set_the_check_in_score_stays_a_floor(client, headers, monkeypatch):
    # The check-in rule fired on words the bedside re-run does not see (say, a translation).
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=4, confidence=0.9))
    _add_patient("p-tr", 2, "2026-10-18T09:00:00Z", transcript="dolor fuerte")
    storage.update_patient("p-tr", {"triage_shortcut_reason": "rule.esi2.chest_pain"})
    ref = client.post(f"/api/{HOSPITAL}/patients/p-tr/refine-triage", json=CALM_VITALS,
                      headers=headers).json()["refinement"]
    assert ref["esi_level"] == 2 and ref["model_esi_level"] == 4
    assert ref["safety_floor_reasons"] == ["chest pain or pressure"]


def test_pregnancy_from_the_form_reaches_the_bedside_rules(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=4, confidence=0.9))
    storage.put_patient({
        "patient_id": "p-preg", "hospital_id": HOSPITAL, "name": "Test", "esi_level": 4,
        "status": "waiting", "created_at": "2026-10-18T09:00:00Z", "language": "en",
        "transcript": "I am bleeding a lot", "medical_info": json.dumps({"age": 29, "pregnant": True}),
    })
    ref = client.post(f"/api/{HOSPITAL}/patients/p-preg/refine-triage", json=CALM_VITALS,
                      headers=headers).json()["refinement"]
    assert ref["esi_level"] <= 2, ref


def test_check_in_confidence_is_hidden_when_a_rule_set_the_score(client, headers):
    _add_patient("p-ci", 2, "2026-10-18T09:00:00Z", transcript="chest pain")
    storage.update_patient("p-ci", {
        "esi_confidence": 0.97, "probabilities": json.dumps([0.0, 0.02, 0.9, 0.07, 0.01]),
        "triage_shortcut_reason": "rule.esi2.chest_pain",
    })
    _add_patient("p-ok", 4, "2026-10-18T09:05:00Z", transcript="ankle")
    storage.update_patient("p-ok", {"esi_confidence": 0.88, "probabilities": json.dumps([0, 0, 0.1, 0.88, 0.02])})
    d = client.get(f"/api/{HOSPITAL}/patients/p-ci", headers=headers).json()
    assert d["esi_confidence"] is None and d["checkin_set_by_rules"] is True
    assert d["checkin_model_esi_level"] == 3 and d["checkin_rule_name"] == "Chest pain or pressure"
    ok = client.get(f"/api/{HOSPITAL}/patients/p-ok", headers=headers).json()
    assert ok["esi_confidence"] == pytest.approx(0.88) and ok["checkin_set_by_rules"] is False


# ---- Rules-only mode (model files missing) ----------------------------------------------

def test_rules_only_when_the_model_is_missing(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "_load", lambda: None)
    assert triage_ml.status() == {"loaded": False, "mode": "rules_only", "folds": 0}
    _add_patient("p-ro", 4, "2026-10-18T09:00:00Z", transcript="I cut my finger")

    calm = client.post(f"/api/{HOSPITAL}/patients/p-ro/refine-triage", json=CALM_VITALS, headers=headers)
    assert calm.status_code == 200, calm.text
    ref = calm.json()["refinement"]
    assert ref["source"] == triage_router.SOURCE_RULES_ONLY == "rules_only_model_not_installed"
    assert ref["esi_level"] == 4 and ref["confidence"] is None and ref["model_esi_level"] is None
    assert "not installed" in ref["note"]

    shock = client.post(f"/api/{HOSPITAL}/patients/p-ro/refine-triage", json=SHOCK_VITALS, headers=headers)
    ref = shock.json()["refinement"]
    assert ref["esi_level"] == 2 and ref["raised_by_safety_rules"] is True
    assert "heart rate over 100" in ref["safety_floor_reasons"]
    d = client.get(f"/api/{HOSPITAL}/patients/p-ro", headers=headers).json()
    assert d["refined_source"] == "rules_only_model_not_installed" and d["refined_model_card"] is None


def test_rules_that_agree_are_shown_when_nothing_was_raised(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "_load", lambda: None)
    _add_patient("p-agree", 2, "2026-10-18T09:00:00Z", transcript="chest pain since this morning")
    ref = client.post(f"/api/{HOSPITAL}/patients/p-agree/refine-triage", json=SHOCK_VITALS,
                      headers=headers).json()["refinement"]
    assert ref["esi_level"] == 2 and ref["raised_by_safety_rules"] is False
    assert ref["safety_floor_reasons"] == []
    assert "heart rate over 100" in ref["safety_rules_agree"]
    assert any("chest pain" in x for x in ref["safety_rules_agree"])
    d = client.get(f"/api/{HOSPITAL}/patients/p-agree", headers=headers).json()
    assert "heart rate over 100" in d["refined_safety_rules_agree"]


def test_runtime_never_calibrates_without_the_offline_file():
    art = {"_conformal_pending": True, "_conformal_offline": None, "conformal": None}
    triage_ml._ensure_calibrated(art, block=False)
    assert art["conformal"] is None and art["_conformal_pending"] is True


# ---- Factors shown to clinicians --------------------------------------------------------

@pytest.mark.parametrize("name", [
    "arrival_hour", "arrival_month", "arrival_day_le", "triage_nurse_id_le", "site_id_le", "shift_le",
    "hour_sin", "is_night", "is_weekend", "transport_origin_le", "insurance_type_le", "language_le",
    "miss_spo2", "total_missing", "tfidf_c12",
])
def test_administrative_features_are_hidden(name):
    assert not triage_ml.shown_to_clinicians(name, measured={"heart_rate"})


def test_unmeasured_vitals_are_not_reasons():
    assert not triage_ml.shown_to_clinicians("heart_rate", measured=set())
    assert not triage_ml.shown_to_clinicians("shock_index", measured={"heart_rate"})
    assert triage_ml.shown_to_clinicians("shock_index", measured={"heart_rate", "systolic_bp"})
    assert triage_ml.shown_to_clinicians("kw_chest_pain", measured=set())
    # No age on the form means the model assumed 35, which is not this patient's age.
    assert not triage_ml.shown_to_clinicians("age", measured=set())
    assert triage_ml.shown_to_clinicians("age", measured={"age"})
    assert not triage_ml.shown_to_clinicians("age_x_hr", measured={"heart_rate"})


def test_factors_are_about_what_the_patient_reported():
    assert triage_ml.describes_patient("kw_chest_pain", 1.0)
    assert not triage_ml.describes_patient("kw_seizure", 0.0)  # "does not mention a seizure"
    assert not triage_ml.describes_patient("hx_asthma", 0.0)
    assert not triage_ml.describes_patient("kw_total", 0.0)
    assert not triage_ml.describes_patient("tfidf_w12", 0.0)
    assert triage_ml.describes_patient("flag_tachycardia", 0.0)  # a measured "heart rate 100 or lower"


def test_factor_labels_are_plain_words():
    assert triage_ml.factor_label("flag_tachycardia", 1.0)[0] == "Heart rate over 100"
    assert triage_ml.factor_label("flag_tachycardia", 0.0)[0] == "Heart rate 100 or lower"
    assert triage_ml.factor_label("kw_chest_pain", 1.0)[0] == "Mentions chest pain"
    assert triage_ml.factor_label("age", 40.0) == ("Age", "measure")
    assert triage_ml.factor_label("hx_hypertension", 1.0)[0] == "History of high blood pressure"


def test_arrival_fields_follow_the_check_in_time():
    row = triage_ml.build_row({"transcript": "x", "created_at": "2026-10-18T15:30:00+00:00"}, {})
    assert row["arrival_month"] == 10 and row["arrival_season"] == "autumn"
    assert row["arrival_day"] in {"Saturday", "Sunday"}  # the 18th, in any server timezone
    assert row["sex"] == "unknown" and row["language"] == "English"
    assert triage_ml.build_row({"medical_info": {"sex": "male", "age": 3}}, {})["sex"] == "M"


@needs_model
def test_real_model_factors_are_clinical():
    patient = {"transcript": "chest pain going down my left arm", "language": "en",
               "medical_info": {"age": 58, "sex": "male"}, "created_at": "2026-10-18T03:00:00Z"}
    for vitals in ({}, SHOCK_VITALS):
        res = triage_ml.predict(patient, vitals)
        assert res is not None
        measured = {k for k, v in vitals.items() if v is not None} | {"age"}
        assert res["top_features"], res
        for f in res["top_features"]:
            assert triage_ml.shown_to_clinicians(f["code"], measured), f
            assert not f["code"].startswith("tfidf_c")
            assert f["feature"] and "_" not in f["feature"], f
            assert not f["feature"].startswith(("Does not", "No reported")), f
            assert f["feature"] not in ('Says "and"', 'Says "my"'), f
            assert abs(f["shap"]) >= 0.005, f
        assert res["esi_level"] in res["conformal_set"]  # the model's pick is always in its own range
        assert res["model_card"]["dataset"].startswith("About 80,000 synthetic")
    no_age = triage_ml.predict({**patient, "medical_info": {"sex": "male"}}, SHOCK_VITALS)
    assert all(not f["code"].startswith(("age", "age_x")) for f in no_age["top_features"]), no_age["top_features"]


@needs_model
def test_absent_warning_words_are_one_line():
    patient = {"transcript": "I twisted my ankle playing soccer and it's swollen", "language": "en",
               "medical_info": {"age": 16}, "created_at": "2026-10-18T15:00:00Z"}
    feats = triage_ml.predict(patient, SHOCK_VITALS)["top_features"]
    labels = [f["feature"] for f in feats]
    assert labels.count("No warning signs mentioned") == 1, labels
    assert not any(x.startswith("Does not mention") for x in labels), labels


@needs_model
def test_status_reports_the_five_fold_model():
    assert triage_ml.status() == {"loaded": True, "mode": "lgbm_5fold", "folds": 5}


@needs_model
def test_offline_calibrator_is_used_when_present():
    if not (triage_ml.MODELS_DIR / triage_ml.CONFORMAL_FILE).exists():
        pytest.skip("run scripts/calibrate_conformal.py first")
    art = triage_ml._load.__wrapped__()  # a fresh copy, not the shared one
    assert art["_conformal_offline"] is not None
    triage_ml._ensure_calibrated(art, block=False)
    assert art["conformal"] is not None and art["_conformal_pending"] is False


# ---- Disposition and workup labels ------------------------------------------------------

def test_no_discharge_before_anyone_has_seen_the_patient(client, headers):
    _add_patient("p-new", 5, "2026-10-18T09:00:00Z", transcript="I need a work note")
    d = client.get(f"/api/{HOSPITAL}/patients/p-new", headers=headers).json()
    assert d["disposition"]["status"] == "pending" and d["disposition"]["disposition"] == ""
    assert d["workup_orders"]["status"] == "pending"


def test_rule_based_suggestion_after_vitals(client, headers, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", _fake_model(esi=3))
    _add_patient("p-cp", 2, "2026-10-18T09:00:00Z", transcript="chest pain")
    client.post(f"/api/{HOSPITAL}/patients/p-cp/refine-triage", json=CALM_VITALS, headers=headers)
    d = client.get(f"/api/{HOSPITAL}/patients/p-cp", headers=headers).json()
    dispo = d["disposition"]
    assert dispo["status"] == "suggested" and dispo["basis"] == "rules"
    assert dispo["label"] == disposition.LABEL_RULES
    assert dispo["rationale"].startswith("Default for ESI 2 from the safety rules; no AI reasoning is configured")
    assert dispo["disposition"] == "admit"
    orders = d["workup_orders"]
    assert orders["basis"] == "rules" and "12-lead ECG" in orders["imaging"]


def test_note_alone_unlocks_the_rule_based_suggestion():
    out = disposition.for_display({}, 4, {}, has_clinical_input=True)
    assert out["disposition"] == "discharge" and out["label"] == disposition.LABEL_RULES
    assert "Default for ESI 4" in out["rationale"]


def test_ai_draft_is_labeled_and_still_floored():
    draft = {"disposition": "discharge", "level_of_care": "home", "expected_los_hours": 2,
             "rationale": "Likely viral.", "discharge_criteria": [], "return_precautions": [],
             "consult_services": []}
    record = {**draft, "basis": "ai_draft", "ai_draft": draft}
    out = disposition.for_display(record, 3, {"systolic_bp": 82}, has_clinical_input=True)
    assert out["label"] == disposition.LABEL_AI
    assert out["disposition"] == "admit"  # the safety net still wins
    ai_orders = workup.for_display({"labs": ["CBC"], "basis": "ai_draft"}, 3, {}, has_clinical_input=False)
    assert ai_orders["label"] == workup.LABEL_AI and ai_orders["before_exam"] is True


def test_generate_without_a_key_stores_pending(monkeypatch):
    monkeypatch.setattr(claude, "available", lambda: False)
    assert disposition.generate("ankle", 4, [])["status"] == "pending"
    assert workup.generate("ankle", 4, [])["status"] == "pending"
