"""Clinician and paid-service features, with and without an AI key.

No-key mode is the judge setup: every feature must answer with something useful
and honest, never a dead button, and never call out to the network. With-key
mode is exercised by swapping ``lib.claude.messages_create`` for a canned
response, so these tests never reach a real model either.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from db import storage  # noqa: E402
from lib import claude, quota  # noqa: E402
from lib.config import settings  # noqa: E402
from lib.content_guard import strip_dashes  # noqa: E402
from main import app  # noqa: E402
from services import (  # noqa: E402
    ambient_scribe,
    demo_records,
    drug_interactions,
    intake_artifacts,
    prebrief,
    sms,
    vision,
)

H = "demo"
DASHES = ("—", "–")


# ---- fixtures ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    settings.solace_mode = "local"
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post(f"/api/{H}/auth/login", json={"clinician_name": "Dr. Chen", "pin": "224466"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    """Default: no AI key, no SMS, and a tripwire on the model call."""
    monkeypatch.setattr(settings, "solace_mode", "local", raising=False)
    monkeypatch.setattr(claude, "available", lambda: False)

    def _tripwire(**_kw):
        raise AssertionError("a model call was made with no key configured")

    monkeypatch.setattr(claude, "messages_create", _tripwire)
    for var in ("SMS_PROVIDER", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                "TWILIO_SMS_FROM_NUMBER", "TWILIO_FROM_NUMBER", "AWS_REGION"):
        monkeypatch.delenv(var, raising=False)


def with_key(monkeypatch, replies: dict[str, str]):
    """Turn the AI on, answering each call by its ``purpose`` with canned text."""
    calls: list[str] = []

    def fake(**kw):
        purpose = kw.get("purpose", "")
        calls.append(purpose)
        if purpose not in replies:
            raise RuntimeError(f"no canned reply for {purpose}")
        return claude.Response(content=[claude.TextBlock(text=replies[purpose])])

    monkeypatch.setattr(claude, "available", lambda: True)
    monkeypatch.setattr(claude, "messages_create", fake)
    return calls


def seed_patient(**over) -> str:
    pid = f"t-{uuid.uuid4().hex[:10]}"
    patient = {
        "patient_id": pid,
        "hospital_id": H,
        "name": "Test Patient",
        "language": "en",
        "transcript": "I have crushing chest pain going down my left arm and I'm sweating.",
        "medical_info": json.dumps({"age": 58, "sex": "M", "conditions": ["Hypertension"],
                                    "medications": ["Lisinopril"], "allergies": ["Penicillin"]}),
        "followup_qa": json.dumps([]),
        "photo_analysis": json.dumps({}),
        "esi_level": 2,
        "esi_label": "Emergent",
        "patient_explanation": "You will be seen very soon.",
        "status": "waiting",
        "created_at": "2026-10-18T10:00:00Z",
        **intake_artifacts.empty_artifacts(),
        "artifacts_status": intake_artifacts.STATUS_PENDING,
    }
    patient.update(over)
    storage.put_patient(patient)
    return pid


def plain_detail(r) -> str:
    detail = r.json().get("detail")
    assert isinstance(detail, str), f"detail should be a plain string, got {detail!r}"
    return detail


def assert_no_dashes(value):
    text = json.dumps(value, ensure_ascii=False)
    assert not any(d in text for d in DASHES), text


def jpeg_bytes() -> bytes:
    from PIL import Image  # noqa: PLC0415

    img = Image.new("RGB", (320, 200), (240, 240, 240))
    for x in range(0, 320, 8):
        for y in range(0, 200, 8):
            if (x // 8 + y // 8) % 2:
                img.putpixel((x, y), (10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---- 1. Early warning -------------------------------------------------------------
# Exactly what EarlyWarningTab.tsx posts: chart vitals plus the four inputs the
# chart cannot know. Missing values are left out, as JSON.stringify drops them.
UI_PAYLOAD = {
    "hr": 132, "rr": 26, "temp_c": 39.2, "sbp": 88, "spo2": 91, "gcs": 15,
    "mental_status": "alert", "wbc": 15.2, "lactate": 4.1,
    "on_oxygen": True, "suspected_infection": True,
}


def test_ews_both_engines_accept_the_flat_ui_payload(client, auth):
    s = client.post(f"/api/{H}/ews/sepsis", json=UI_PAYLOAD, headers=auth)
    d = client.post(f"/api/{H}/ews/deterioration", json=UI_PAYLOAD, headers=auth)
    assert s.status_code == 200, s.text
    assert d.status_code == 200, d.text
    assert s.json()["band"] == "critical"
    body = d.json()
    assert body["band"] in ("high", "critical")
    features = {c["feature"] for c in body["contributions"]}
    assert {"hr_abs", "sbp_abs", "rr", "spo2", "temp", "on_o2", "lactate"} <= features
    assert "one set of vitals" in body["calibration_note"]
    assert "Epic" not in s.json()["calibration_note"]


def test_ews_deterioration_accepts_vitals_now_and_nulls(client, auth):
    r = client.post(f"/api/{H}/ews/deterioration", headers=auth,
                    json={"vitals_now": {"hr": 135, "sbp": None, "spo2": "90"}, "hr": None, "wbc": None})
    assert r.status_code == 200, r.text
    assert r.json()["score"] >= 24


def test_ews_uses_gcs_when_mental_status_is_missing(client, auth):
    r = client.post(f"/api/{H}/ews/sepsis", headers=auth, json={"rr": 24, "sbp": 98, "gcs": 13})
    assert r.status_code == 200
    q = r.json()["qsofa"]
    assert q["count"] == 3 and any("GCS 13" in c for c in q["criteria_met"])


def test_ews_deterioration_without_any_vitals_is_a_plain_400(client, auth):
    r = client.post(f"/api/{H}/ews/deterioration", headers=auth,
                    json={"wbc": 12, "on_oxygen": False, "suspected_infection": False})
    assert r.status_code == 400
    assert "vital sign" in plain_detail(r)


def test_ews_requires_sign_in(client):
    assert client.post(f"/api/{H}/ews/deterioration", json=UI_PAYLOAD).status_code == 401


# ---- 2. Reasoning (ddx v2) --------------------------------------------------------
def test_ddx_without_key_drafts_nothing_but_keeps_keyword_red_flags(client, auth):
    r = client.post(f"/api/{H}/ddx/v2", headers=auth,
                    json={"transcript": "Crushing chest pain down my left arm and I'm sweating"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_available"] is False
    assert body["differential"] == []
    assert "off" in body["message"] and "keyword" in body["message"]
    assert "Acute coronary syndrome" in {rf["diagnosis"] for rf in body["red_flags"]}


def test_ddx_short_transcript_is_a_plain_400(client, auth):
    r = client.post(f"/api/{H}/ddx/v2", headers=auth, json={"transcript": "hi"})
    assert r.status_code == 400
    plain_detail(r)


DDX_REPLY = json.dumps({
    "differential": [
        {"diagnosis": "Acute coronary syndrome", "icd10": "I20.9", "weight": 0.6,
         "supporting": ["crushing chest pain — radiating"], "refuting": [],
         "discriminator": "12-lead ECG", "reasoning": "Classic story.", "must_not_miss": True,
         "evidence_quote": "crushing chest pain"},
        {"diagnosis": "GERD", "icd10": "K21.9", "weight": 0.4, "supporting": ["burning"],
         "refuting": ["sweating"], "discriminator": "trial of antacid", "reasoning": "Less likely."},
    ],
    "counterfactuals": [{"question": "Is the pain exertional?", "discriminates": ["ACS", "GERD"], "why": "ACS rises"}],
})


def test_ddx_with_key_returns_labeled_considerations(client, auth, monkeypatch):
    calls = with_key(monkeypatch, {"ddx_v2": DDX_REPLY})
    r = client.post(f"/api/{H}/ddx/v2", headers=auth,
                    json={"transcript": "Crushing chest pain down my left arm and I'm sweating"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert calls == ["ddx_v2"]
    assert body["ai_available"] is True
    assert "clinician" in body["label"].lower()
    top = body["differential"][0]
    assert top["diagnosis"] == "Acute coronary syndrome"
    assert top["rule_in"] == top["supporting"] and top["next_step"] == "12-lead ECG"
    assert body["counterfactuals"][0]["if_true"]
    assert_no_dashes(body["differential"])


# ---- 3. Ambient scribe ------------------------------------------------------------
def _scribe_session(client, auth, chunks):
    sid = client.post(f"/api/{H}/scribe/session/start", headers=auth, json={"specialty": "ed"}).json()["session_id"]
    for chunk in chunks:
        r = client.post(f"/api/{H}/scribe/session/append", headers=auth, json={"session_id": sid, "chunk": chunk})
        assert r.status_code == 200, r.text
    return sid


def test_scribe_without_key_returns_a_verbatim_linked_note(client, auth):
    sid = _scribe_session(client, auth, ["The pain started two hours ago.", "It is on the left side of my chest."])
    assert client.post(f"/api/{H}/scribe/session/pause", headers=auth, json={"session_id": sid}).status_code == 200
    assert client.post(f"/api/{H}/scribe/session/resume", headers=auth, json={"session_id": sid}).status_code == 200
    r = client.post(f"/api/{H}/scribe/session/finalize", headers=auth, json={"session_id": sid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_available"] is False and body["source"] == "verbatim_no_ai"
    assert "off" in body["message"]
    sections = {s["name"]: s for s in body["structured"]["sections"]}
    subj = sections["SUBJECTIVE"]["lines"]
    assert [l["text"] for l in subj] == ["The pain started two hours ago.", "It is on the left side of my chest."]
    assert subj[0]["linked_evidence"][0]["snippet"] == "The pain started two hours ago."
    assert sections["SUBJECTIVE"]["evidence_coverage"] == 1.0
    for name in ("ASSESSMENT", "PLAN"):
        assert sections[name]["lines"][0]["text"] == "Clinician to complete (AI drafting is off on this server)"
    assert body["soap_text"].startswith("Subjective:")

    regen = client.post(f"/api/{H}/scribe/regenerate-section", headers=auth,
                        json={"structured": body["structured"], "section_name": "PLAN"})
    assert regen.status_code == 200
    assert regen.json()["ai_available"] is False
    assert regen.json()["message"]
    assert regen.json()["structured"]["sections"]


def test_scribe_finalize_with_nothing_captured_is_a_plain_400(client, auth):
    sid = _scribe_session(client, auth, [])
    r = client.post(f"/api/{H}/scribe/session/finalize", headers=auth, json={"session_id": sid})
    assert r.status_code == 400
    assert "Nothing was captured" in plain_detail(r)


def test_scribe_unknown_session_is_a_plain_404(client, auth):
    r = client.post(f"/api/{H}/scribe/session/append", headers=auth, json={"session_id": "nope", "chunk": "x"})
    assert r.status_code == 404
    plain_detail(r)


SYNTH_REPLY = json.dumps({
    "sections": [
        {"name": "HPI", "summary": [{"text": "c/o CP x2h — L sided", "evidence_segments": [0, 1]}]},
        {"name": "ASSESSMENT", "summary": [{"text": "AI draft: r/o ACS", "evidence_segments": [1, 99]}]},
    ],
    "transcript_segments": [
        {"id": 0, "speaker": "PATIENT", "begin_ms": 0, "end_ms": 3000, "content": "The pain started two hours ago."},
        {"id": 1, "speaker": "PATIENT", "begin_ms": 3000, "end_ms": 6000, "content": "It is on the left side."},
    ],
})


def test_scribe_with_key_uses_the_model_note(client, auth, monkeypatch):
    with_key(monkeypatch, {"ambient_scribe_synth": SYNTH_REPLY, "ambient_scribe_refine": SYNTH_REPLY})
    sid = _scribe_session(client, auth, ["The pain started two hours ago.", "It is on the left side."])
    body = client.post(f"/api/{H}/scribe/session/finalize", headers=auth, json={"session_id": sid}).json()
    assert body["ai_available"] is True and body["source"] == "claude"
    sections = {s["name"]: s for s in body["structured"]["sections"]}
    assert sections["ASSESSMENT"]["lines"][0]["evidence_segments"] == [1]  # dangling id dropped
    assert_no_dashes(sections)


def test_scribe_with_key_falls_back_to_verbatim_when_the_model_fails(client, auth, monkeypatch):
    with_key(monkeypatch, {})  # every call raises
    sid = _scribe_session(client, auth, ["Patient reports a headache."])
    body = client.post(f"/api/{H}/scribe/session/finalize", headers=auth, json={"session_id": sid}).json()
    assert body["source"] == "verbatim_ai_failed"
    assert body["structured"]["sections"][0]["lines"][0]["text"] == "Patient reports a headache."


# ---- 4. Publish summary to the patient --------------------------------------------
def test_publish_needs_a_clinician_note(client, auth):
    pid = seed_patient()
    r = client.post(f"/api/{H}/patients/{pid}/publish-summary", headers=auth, json={})
    assert r.status_code == 400
    assert "Write a note first" in plain_detail(r)


def test_publish_without_key_sends_the_note_word_for_word(client, auth):
    cards = [{"title": "Stay Seated", "instruction": "Remain in your seat."}]
    pid = seed_patient(comfort_protocol=json.dumps(cards))
    note = "ECG normal so far. Waiting on blood tests. Tell us if the pain changes."
    assert client.post(f"/api/{H}/patients/{pid}/notes", headers=auth, json={"text": note}).status_code == 200
    r = client.post(f"/api/{H}/patients/{pid}/publish-summary", headers=auth, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_available"] is False and body["source"] == "clinician_note_template"
    summary = body["summary"]
    assert summary["what_we_are_doing"] == note
    assert summary["things_to_do_at_home"] == ["Stay Seated: Remain in your seat."]
    assert summary["steps_heading"] == "while_you_wait"  # waiting-room steps, not "at home"
    assert "tell the staff right away" in summary["when_to_come_back"]
    public = client.get(f"/api/{H}/public-patients/{pid}").json()
    assert public["patient_education"]["what_we_are_doing"] == note


def test_publish_with_key_uses_the_ai_rewrite(client, auth, monkeypatch):
    reply = json.dumps({"headline": "Your heart tests look okay so far.",
                        "what_we_are_doing": "We are waiting on blood tests — about an hour.",
                        "things_to_do_at_home": ["Rest."],
                        "when_to_come_back": "Tell the staff right away if you feel worse.",
                        "closing": "We are here for you."})
    with_key(monkeypatch, {"patient_education": reply})
    pid = seed_patient()
    client.post(f"/api/{H}/patients/{pid}/notes", headers=auth, json={"text": "ECG ok, trop pending"})
    body = client.post(f"/api/{H}/patients/{pid}/publish-summary", headers=auth, json={}).json()
    assert body["ai_available"] is True and body["source"] == "claude"
    assert body["summary"]["headline"] == "Your heart tests look okay so far."
    assert body["summary"]["steps_heading"] == "at_home"
    assert_no_dashes(body["summary"])


def test_publish_with_key_never_sends_an_empty_summary(client, auth, monkeypatch):
    with_key(monkeypatch, {"patient_education": json.dumps({"headline": "", "what_we_are_doing": ""})})
    pid = seed_patient(language="es")
    client.post(f"/api/{H}/patients/{pid}/notes", headers=auth, json={"text": "Esperamos los análisis."})
    body = client.post(f"/api/{H}/patients/{pid}/publish-summary", headers=auth, json={}).json()
    assert body["source"] == "clinician_note_template" and body["message"]
    assert body["summary"]["what_we_are_doing"] == "Esperamos los análisis."
    assert "avise al personal de inmediato" in body["summary"]["when_to_come_back"]


# ---- 5. Prescriptions -------------------------------------------------------------
def test_manual_prescription_flags_a_penicillin_allergy(client, auth):
    pid = seed_patient()
    r = client.post(f"/api/{H}/patients/{pid}/prescriptions", headers=auth,
                    json={"drug": "Amoxicillin", "dose": "500 mg", "source": "manual"})
    assert r.status_code == 200, r.text
    safety = r.json()["safety"]
    assert safety["any_high"] is True
    assert safety["drug_allergy"][0]["med"] == "amoxicillin"
    assert "allergy" in safety["alerts"][0]["message"].lower()
    assert r.json()["prescription"]["safety_highest"] == "high"


def test_manual_prescription_flags_an_interaction(client, auth):
    info = {"age": 70, "medications": ["Blood thinners"], "blood_thinner_name": "Warfarin", "allergies": ["None"]}
    pid = seed_patient(medical_info=json.dumps(info))
    r = client.post(f"/api/{H}/patients/{pid}/prescriptions", headers=auth, json={"drug": "Ibuprofen 600 mg"})
    safety = r.json()["safety"]
    pairs = {(a["a"], a["b"], a["severity"]) for a in safety["drug_drug"]}
    assert ("warfarin", "ibuprofen", "high") in pairs
    assert safety["checked_against"]["medications"] == ["Warfarin"]


def test_manual_prescription_checks_other_prescriptions_too(client, auth):
    pid = seed_patient(medical_info=json.dumps({"medications": ["None"], "allergies": ["None"]}))
    client.post(f"/api/{H}/patients/{pid}/prescriptions", headers=auth, json={"drug": "Sildenafil"})
    r = client.post(f"/api/{H}/patients/{pid}/prescriptions", headers=auth, json={"drug": "Nitroglycerin"})
    assert r.json()["safety"]["summary"]["highest_severity"] == "contraindicated"


def test_prescription_without_a_drug_is_a_plain_400(client, auth):
    pid = seed_patient()
    r = client.post(f"/api/{H}/patients/{pid}/prescriptions", headers=auth, json={"drug": ""})
    assert r.status_code == 400
    plain_detail(r)


def test_suggest_without_key_says_what_is_off(client, auth):
    pid = seed_patient()
    r = client.post(f"/api/{H}/patients/{pid}/prescriptions/suggest", headers=auth)
    assert r.status_code == 200
    assert r.json() == {
        "suggestions": [],
        "ai_available": False,
        "message": "AI suggestions are off in this demo. Prescriptions you type are still checked for allergies and drug interactions.",
    }


def test_suggest_with_key_checks_every_suggestion(client, auth, monkeypatch):
    reply = json.dumps([
        {"drug": "amoxicillin", "dose": "500 mg", "route": "PO", "frequency": "q8h",
         "duration": "7 days", "indication": "infection — likely", "cautions": ""},
        {"drug": "acetaminophen", "dose": "1 g", "route": "PO", "frequency": "q6h PRN",
         "duration": "3 days", "indication": "pain", "cautions": ""},
    ])
    with_key(monkeypatch, {"prescription": reply})
    pid = seed_patient()
    body = client.post(f"/api/{H}/patients/{pid}/prescriptions/suggest", headers=auth).json()
    assert body["ai_available"] is True
    amox, apap = body["suggestions"]
    assert amox["safety"]["any_high"] is True and amox["review_note"]
    assert "allergy" in amox["cautions"].lower()
    assert apap["safety"]["alerts"] == []
    assert_no_dashes(body["suggestions"])
    # Accepting a suggestion posts it back with its extra keys; that must work.
    accepted = {**apap, "source": "ai_suggested_accepted"}
    assert client.post(f"/api/{H}/patients/{pid}/prescriptions", headers=auth, json=accepted).status_code == 200


# ---- 6. SMS -----------------------------------------------------------------------
FOOTER = "Sent by the Solace student demo. Reply STOP to opt out."


def test_sms_off_returns_the_exact_preview(client):
    pid = seed_patient(comfort_protocol=json.dumps([{"title": "Stay Seated", "instruction": "Remain in your seat."}]))
    r = client.post(f"/api/{H}/sms/care-instructions", json={"patient_id": pid, "phone": "512-555-0177"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] is False and body["reason"] == "sms_off"
    assert body["preview"].endswith(FOOTER)
    assert "1. Stay Seated: Remain in your seat." in body["preview"]
    assert "tell the staff right away" in body["preview"]
    assert "protected health" not in body["preview"].lower()
    assert "5125550177" not in json.dumps(body)


def test_sms_never_sends_just_because_aws_region_is_set(client, monkeypatch):
    import boto3  # noqa: PLC0415

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("boto3 used")))
    assert sms.is_configured() is False
    pid = seed_patient()
    r = client.post(f"/api/{H}/sms/care-instructions", json={"patient_id": pid, "phone": "5125550177"})
    assert r.json()["reason"] == "sms_off"


def test_sms_is_configured_only_when_explicit(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "t")
    monkeypatch.setenv("TWILIO_SMS_FROM_NUMBER", "+15555550100")
    assert sms.is_configured() is False  # creds alone are not a choice
    monkeypatch.setenv("SMS_PROVIDER", "twilio")
    assert sms.is_configured() is True
    monkeypatch.setenv("SMS_PROVIDER", "sns")
    assert sms.is_configured() is False  # sns only in aws mode
    monkeypatch.setattr(settings, "solace_mode", "aws", raising=False)
    assert sms.is_configured() is True


def test_sms_real_sends_are_validated_and_throttled(client, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(sms, "is_configured", lambda: True)
    monkeypatch.setattr(sms, "send", lambda **kw: sent.append(kw["to"]) or {"success": True})
    monkeypatch.setitem(quota.LIMITS, "sms.self_serve", quota.Limit("sms.self_serve", per_hour=2))
    headers = {"User-Agent": f"sms-throttle-{uuid.uuid4().hex}"}
    pid = seed_patient()

    bad = client.post(f"/api/{H}/sms/care-instructions", headers=headers, json={"patient_id": pid, "phone": "12"})
    assert bad.status_code == 400 and "phone number" in plain_detail(bad)
    for _ in range(2):
        ok = client.post(f"/api/{H}/sms/care-instructions", headers=headers, json={"patient_id": pid, "phone": "5125550177"})
        assert ok.status_code == 200 and ok.json()["sent"] is True
    limited = client.post(f"/api/{H}/sms/care-instructions", headers=headers, json={"patient_id": pid, "phone": "5125550177"})
    assert limited.status_code == 429
    plain_detail(limited)
    assert len(sent) == 2


def test_sms_unknown_patient_is_a_plain_404(client):
    r = client.post(f"/api/{H}/sms/care-instructions", json={"patient_id": "missing", "phone": "5125550177"})
    assert r.status_code == 404
    plain_detail(r)


# ---- 7. ID and insurance scans ----------------------------------------------------
def _upload(client, path, **data):
    files = {"image_file": ("card.jpg", jpeg_bytes(), "image/jpeg")}
    return client.post(f"/api/{H}{path}", files=files, data=data)


def test_scans_without_key_say_card_reading_is_off(client):
    for path in ("/scan-id", "/scan-insurance"):
        r = _upload(client, path, consent_granted="true")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is False and body["error"] == "ocr_unavailable"
        assert body["ai_available"] is False
        assert "sample" in body["message"] and "Retake" not in body["message"]


def test_sample_id_matches_the_returning_patient(client):
    r = client.post(f"/api/{H}/scan-id/sample")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["source"] == "sample"
    f = body["fields"]
    for key in ("first_name", "last_name", "dob", "license_number", "issuing_state", "address", "city", "state", "zip", "expiry", "sex"):
        assert key in f
    lk = client.post(f"/api/{H}/identity/lookup",
                     json={"first_name": f["first_name"], "last_name": f["last_name"], "dob": f["dob"]}).json()
    assert lk["matched"] is True and lk["match_method"] == "name+dob"
    assert lk["prefill"]["allergies"] == ["Penicillin"]


def test_sample_insurance_card_matches_by_member_id(client):
    body = client.post(f"/api/{H}/scan-insurance/sample").json()
    f = body["fields"]
    for key in ("provider", "plan_name", "member_id", "group_number", "name_on_card", "bin", "pcn", "rx_group", "effective_date", "phone"):
        assert key in f
    lk = client.post(f"/api/{H}/identity/lookup", json={"insurance_member_id": f["member_id"]}).json()
    assert lk["matched"] is True and lk["ehr_record"]["name"] == demo_records.SAMPLE_PERSON["name"]


def test_identity_lookup_without_name_or_member_id_is_a_plain_400(client):
    r = client.post(f"/api/{H}/identity/lookup", json={"dob": "1990-01-01"})
    assert r.status_code == 400
    plain_detail(r)


def test_scans_with_key_read_the_card(client, monkeypatch):
    monkeypatch.setattr(claude, "available", lambda: True)
    monkeypatch.setattr(vision, "image_quality_gate", lambda b: {"ok": True, "metrics": {}})
    id_reply = {"is_id_card": True, "first_name": "Jordan", "last_name": "Rivera", "dob": "03/14/1987",
                "issuing_state": "IL", "license_number": "DL: D000-1234"}
    card_reply = {"is_insurance_card": True, "provider": "Demo Health", "member_id": "ID: DEMO100200300",
                  "rx_bin": "999001", "customer_service_phone": "1-800-555-0100"}
    monkeypatch.setattr(vision, "vision_extract", lambda *a, **k: dict(id_reply if k.get("purpose") == "id_ocr" else card_reply))

    idr = _upload(client, "/scan-id").json()
    assert idr["success"] is True and idr["ai_available"] is True
    assert idr["fields"]["dob"] == "1987-03-14" and idr["fields"]["license_number"] == "D000-1234"

    ins = _upload(client, "/scan-insurance", consent_granted="true").json()
    assert ins["success"] is True
    assert ins["fields"]["member_id"] == "DEMO100200300"
    assert ins["fields"]["bin"] == "999001" and ins["fields"]["phone"] == "1-800-555-0100"

    no_consent = _upload(client, "/scan-insurance", consent_granted="false")
    assert no_consent.status_code == 403
    plain_detail(no_consent)


# ---- 8. Prebrief and deferred artifacts -------------------------------------------
def test_deferred_artifacts_without_key_give_a_structured_auto_summary(client):
    pid = seed_patient(triage_shortcut_reason="rule.esi2.high_risk_presentation")
    result = intake_artifacts.generate_clinician_artifacts(H, pid)
    assert result["artifacts_status"] == intake_artifacts.STATUS_READY
    p = storage.get_patient(pid)
    brief = p["clinician_prebrief"]
    assert brief.startswith("Auto summary (no AI):")
    assert '"I have crushing chest pain going down my left arm and I\'m sweating."' in brief
    assert "chest pain" in brief and "high-risk words" in brief
    assert "58yo male" in brief and "Lisinopril" in brief and "Penicillin" in brief
    assert brief != p["transcript"]
    note = p["clinical_scribe_note"]
    assert note.startswith("Auto summary (no AI)") and "Assessment: for the clinician to write." in note
    assert "in this build" not in note
    assert json.loads(p["comfort_protocol"])


@pytest.mark.parametrize("weird", [
    {"medical_info": "[1, 2]", "followup_qa": json.dumps({"q": "a"}), "esi_level": "abc"},
    {"medical_info": None, "followup_qa": None, "transcript": None, "photo_analysis": "not json"},
    {"medical_info": json.dumps({"medications": "Aspirin", "allergies": None}), "clinical_flags": "{}"},
])
def test_deferred_artifacts_survive_odd_field_shapes(client, weird):
    pid = seed_patient(**weird)
    result = intake_artifacts.generate_clinician_artifacts(H, pid)
    assert result["artifacts_status"] == intake_artifacts.STATUS_READY
    assert storage.get_patient(pid)["clinician_prebrief"].startswith("Auto summary (no AI):")


def test_comfort_steps_do_not_wait_for_the_clinician_notes(client, monkeypatch):
    """The patient's phone polls for about 45 seconds, so the comfort steps must be
    saved while a slow clinician call is still running."""
    pid = seed_patient()
    saved = threading.Event()
    real_update = storage.update_patient

    def update(patient_id, updates):
        out = real_update(patient_id, updates)
        if "comfort_protocol" in updates:
            saved.set()
        return out

    real_ddx = intake_artifacts.differential.generate

    def slow_ddx(*a, **k):
        assert saved.wait(5), "the comfort steps waited for the differential"
        return real_ddx(*a, **k)

    monkeypatch.setattr(storage, "update_patient", update)
    monkeypatch.setattr(intake_artifacts.differential, "generate", slow_ddx)
    result = intake_artifacts.generate_clinician_artifacts(H, pid)
    assert result["artifacts_status"] == intake_artifacts.STATUS_READY
    assert json.loads(storage.get_patient(pid)["comfort_protocol"])


def test_deferred_artifacts_with_key_use_the_model_and_still_finish(client, monkeypatch):
    brief = "58yo M c/o CP radiating to L arm, diaphoretic."
    calls = with_key(monkeypatch, {"prebrief": brief})  # every other call raises
    pid = seed_patient()
    result = intake_artifacts.generate_clinician_artifacts(H, pid)
    assert result["artifacts_status"] == intake_artifacts.STATUS_READY
    p = storage.get_patient(pid)
    assert p["clinician_prebrief"] == brief
    # The calls with no canned reply failed, and each fell back on its own.
    assert p["clinical_scribe_note"].startswith("Auto summary (no AI)")
    assert json.loads(p["differential"]) == []
    assert json.loads(p["comfort_protocol"])
    assert {"prebrief", "scribe", "differential", "comfort_protocol"} <= set(calls)


def test_odd_value_types_get_plain_answers_not_validation_errors(client, auth):
    odd = {"hr": "132", "rr": None, "sbp": "eighty", "on_oxygen": "false",
           "suspected_infection": "yes", "mental_status": 5, "vitals_now": "not a dict"}
    for path in ("/ews/sepsis", "/ews/deterioration"):
        r = client.post(f"/api/{H}{path}", headers=auth, json=odd)
        assert r.status_code == 200, r.text
    sepsis = client.post(f"/api/{H}/ews/sepsis", headers=auth, json=odd).json()
    assert "oxygen" not in {c["feature"] for c in sepsis["contributions"]}  # "false" means no

    ddx = client.post(f"/api/{H}/ddx/v2", headers=auth,
                      json={"transcript": "Crushing chest pain down my left arm", "medical_info": "{}", "vitals": [1]})
    assert ddx.status_code == 200, ddx.text

    pid = seed_patient()
    rx = client.post(f"/api/{H}/patients/{pid}/prescriptions", headers=auth, json={"drug": "Acetaminophen", "dose": 500})
    assert rx.status_code == 200, rx.text
    assert rx.json()["prescription"]["dose"] == "500"
    assert client.post(f"/api/{H}/patients/{pid}/notes", headers=auth, json={"text": 12345}).status_code == 200
    pub = client.post(f"/api/{H}/patients/{pid}/publish-summary", headers=auth, json={"note_id": "x" * 200})
    assert pub.status_code == 200, pub.text
    assert pub.json()["summary"]["what_we_are_doing"] == "12345"

    text = client.post(f"/api/{H}/sms/care-instructions", json={"patient_id": pid, "phone": 5125550177})
    assert text.status_code == 200 and text.json()["reason"] == "sms_off"
    lookup = client.post(f"/api/{H}/identity/lookup", json={"insurance_member_id": 12345})
    assert lookup.status_code == 200 and lookup.json()["matched"] is False

    for path, body in (
        ("/scribe/session/append", {"session_id": 123, "chunk": {"a": 1}}),
        ("/scribe/regenerate-section", {"structured": "x", "section_name": ["PLAN"]}),
        ("/ews/deterioration", {"vitals_now": [], "on_oxygen": "maybe"}),
    ):
        r = client.post(f"/api/{H}{path}", headers=auth, json=body)
        assert r.status_code in (400, 404), r.text
        plain_detail(r)


def test_prebrief_reports_the_pain_flag_and_no_ai_label():
    out = prebrief.deterministic_summary("My ankle hurts.", {"age": 15}, pain_flagged=True)
    assert out["source"] == "auto_no_ai" and out["label"] == "Auto summary (no AI)"
    assert 'pressed "I feel worse"' in out["summary"]
    assert "Red-flag" not in out["summary"]


def test_prebrief_with_key_uses_the_model(monkeypatch):
    with_key(monkeypatch, {"prebrief": "58yo M c/o CP — radiating to L arm."})
    text = prebrief.generate("chest pain", {}, 2, {"age": 58})
    assert text == "58yo M c/o CP, radiating to L arm."


# ---- shared pieces ----------------------------------------------------------------
def test_strip_dashes_keeps_ranges_and_minus():
    assert strip_dashes("Rest — then sip water") == "Rest, then sip water"
    assert strip_dashes("3–5 days") == "3-5 days"
    assert strip_dashes("x − y") == "x − y"


def test_drug_names_resolve_with_doses_and_form_words():
    assert drug_interactions._canon("Lisinopril 10 mg") == "lisinopril"
    assert drug_interactions._canon("Sulfa") == "sulfonamide"
    r = drug_interactions.check_prescription("Bactrim DS", medical_info={"allergies": ["Sulfa"]})
    assert r["any_high"] is True


def test_verbatim_note_never_invents_content():
    note = ambient_scribe.verbatim_note("first line\n\nsecond line")
    texts = [l["text"] for s in note["sections"] for l in s["lines"]]
    assert texts[:2] == ["first line", "second line"]
    assert all(t in ("first line", "second line") or t.startswith("Clinician to complete") for t in texts)
