"""What the patient's own screen and care-steps text say.

  * GET /public-patients follows a bedside re-check that raised the level (never
    lower than the check-in level), with the label, explanation, care card and
    comfort cards for the new level, and says a nurse re-checked them.
  * The wait estimate counts only earlier arrivals at the same or a more urgent
    level, and ESI 1 and 2 and the crisis card get no minutes at all.
  * The care-steps text is written in all 20 languages, greets the parent of a
    child under 12, and says which language and direction it is in.
  * The private-sandbox creation limit is a sliding hour, not the clock hour.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from db import storage  # noqa: E402
from lib import claude, comfort_i18n, sandbox, sms_i18n  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from routers import patients as patients_router  # noqa: E402
from services import sms, triage_ml, wait_time  # noqa: E402

H = "demo"
SHOCK_VITALS = {"systolic_bp": 88, "diastolic_bp": 54, "heart_rate": 124, "spo2": 91,
                "respiratory_rate": 24, "mental_status": "alert"}
DASHES = re.compile("[–—]| - ")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "solace_mode", "local", raising=False)
    monkeypatch.setattr(settings, "solace_seed_demo", True, raising=False)
    monkeypatch.setattr(settings, "solace_warm_model", False, raising=False)
    monkeypatch.delenv("SOLACE_SEED_BACKGROUND", raising=False)
    monkeypatch.setattr(claude, "available", lambda: False)  # the same with or without a key
    storage._reset_for_tests()
    with TestClient(app) as c:
        yield c
    storage._reset_for_tests()


@pytest.fixture
def auth(client):
    r = client.post(f"/api/{H}/auth/login", json={"clinician_name": "Dr. Chen", "pin": "224466"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _example(name: str) -> dict:
    found = [p for p in storage.list_patients_for_hospital(H, "all") if p.get("name") == name]
    assert found, f"example patient {name} was not seeded"
    return found[0]


def _seed(**over) -> str:
    pid = f"s-{uuid.uuid4().hex[:10]}"
    patient = {
        "patient_id": pid, "hospital_id": H, "name": "Test Patient", "language": "en",
        "transcript": "my ankle hurts after soccer", "medical_info": json.dumps({"age": 30}),
        "esi_level": 4, "esi_label": "Less Urgent", "explanation_key": "esi4", "explanation_language": "en",
        "patient_explanation": "Your wait may be longer because sicker people go first.",
        "comfort_protocol": json.dumps([{"title": "Stay Seated", "instruction": "Remain in your seat."}]),
        "status": "waiting", "created_at": _iso(datetime.now(timezone.utc)),
    }
    patient.update(over)
    storage.put_patient(patient)
    return pid


def _public(client, pid: str) -> dict:
    r = client.get(f"/api/{H}/public-patients/{pid}")
    assert r.status_code == 200, r.text
    return r.json()


# ---- 1. a bedside re-check that raised the level reaches the patient's screen ------------
def test_james_raised_to_esi_2_sees_esi_2_with_the_tell_staff_card(client, auth, monkeypatch):
    monkeypatch.setattr(triage_ml, "predict", lambda patient, vitals: None)  # rules only, model or not
    james = _example("James")
    pid = james["patient_id"]
    before = _public(client, pid)
    assert before["esi_level"] == 4 and before["rechecked_by_nurse"] is False
    assert before["wait_kind"] == "estimate" and isinstance(before["wait_estimate_minutes"], int)

    r = client.post(f"/api/{H}/patients/{pid}/refine-triage", headers=auth, json=SHOCK_VITALS)
    assert r.status_code == 200, r.text
    assert r.json()["refinement"]["esi_level"] == 2

    body = _public(client, pid)
    assert body["esi_level"] == 2 and body["checkin_esi_level"] == 4
    assert body["rechecked_by_nurse"] is True and body["raised_by_recheck"] is True and body["rechecked_at"]
    assert body["esi_label"] == "Emergent"
    assert body["explanation_key"] == "esi2"
    assert "high priority" in body["patient_explanation"]
    care = body["care_recommendation"]
    assert care["kind"] == "high" and care["label"] == "Tell the front desk now"
    assert any("tell staff right away" in s.lower() for s in care["next_steps"])
    expected_cards, _ = comfort_i18n.cards_for("en", "esi2")
    assert body["comfort_protocol"] == expected_cards and body["comfort_ready"] is True
    # The spoken audio was made for the old level, so it is not offered.
    assert body["audio_url"] is None
    # ESI 2: a sentence on screen, no minutes.
    assert body["wait_kind"] == "now"
    assert body["wait_estimate_minutes"] is None and body["wait_estimate_range"] is None
    assert "transcript" not in body and "refined_safety_floor_reasons" not in body


def test_a_lower_recheck_never_drops_the_screen_below_the_check_in_level(client):
    pid = _seed(esi_level=2, esi_label="Emergent", explanation_key="esi2",
                patient_explanation="You are a high priority.", refined_esi_level=4, refined_at="2026-10-19T10:00:00Z")
    body = _public(client, pid)
    assert body["esi_level"] == 2 and body["checkin_esi_level"] == 2
    assert body["rechecked_by_nurse"] is True and body["raised_by_recheck"] is False
    assert body["esi_label"] == "Emergent" and body["explanation_key"] == "esi2"
    assert body["comfort_protocol"] == [{"title": "Stay Seated", "instruction": "Remain in your seat."}]
    assert body["wait_kind"] == "now"


def test_raised_spanish_patient_gets_spanish_words_for_the_new_level(client):
    pid = _seed(language="es", explanation_language="es", refined_esi_level=2)
    body = _public(client, pid)
    assert body["esi_level"] == 2 and body["explanation_language"] == "es"
    assert body["patient_explanation"].startswith("Usted tiene prioridad alta")
    assert body["care_recommendation"]["language"] == "es" and body["care_recommendation"]["kind"] == "high"
    assert body["comfort_protocol"] == comfort_i18n.cards_for("es", "esi2")[0]


def test_raised_child_gets_the_parent_cards(client):
    pid = _seed(transcript="fever and very sleepy", medical_info=json.dumps({"age": 3}), refined_esi_level=2)
    body = _public(client, pid)
    care = body["care_recommendation"]
    assert care["audience"] == "parent" and "your child" in care["rationale"]
    assert body["comfort_protocol"] == comfort_i18n.cards_for("en", "child2")[0]


def test_raised_crisis_patient_keeps_the_988_card(client):
    pid = _seed(transcript="I want to end my life", crisis=True, esi_level=3, refined_esi_level=2)
    body = _public(client, pid)
    assert body["explanation_key"] == "crisis" and "988" in body["patient_explanation"]
    assert body["care_recommendation"]["kind"] == "crisis"
    assert body["wait_kind"] == "now"


# ---- 2. the wait estimate ---------------------------------------------------------------
def test_later_arrivals_do_not_grow_the_estimate(client):
    now = datetime.now(timezone.utc)
    pid = _seed(esi_level=4, created_at=_iso(now - timedelta(minutes=5)))
    first = _public(client, pid)
    for i in range(6):  # six more urgent patients check in after this one
        _seed(esi_level=2 + i % 2, created_at=_iso(now + timedelta(seconds=i + 1)))
    again = _public(client, pid)
    assert again["wait_estimate_minutes"] == first["wait_estimate_minutes"]
    assert again["wait_estimate_range"] == first["wait_estimate_range"]


def test_earlier_arrivals_at_the_same_or_more_urgent_level_count():
    me = "2026-10-19T10:00:00Z"
    queue = [
        {"status": "waiting", "esi_level": 3, "created_at": "2026-10-19T09:00:00Z"},   # ahead
        {"status": "waiting", "esi_level": 4, "created_at": "2026-10-19T09:30:00Z"},   # ahead (same level)
        {"status": "waiting", "esi_level": 5, "created_at": "2026-10-19T09:10:00Z"},   # less urgent: not ahead
        {"status": "waiting", "esi_level": 1, "created_at": "2026-10-19T10:05:00Z"},   # arrived later: not ahead
        {"status": "seen", "esi_level": 2, "created_at": "2026-10-19T08:00:00Z"},      # already seen: not ahead
    ]
    out = wait_time.estimate_breakdown(4, queue, arrived_at=me)
    assert out["ahead_count"] == 2
    # Without an arrival time every waiting patient at the level or above counts (older callers).
    assert wait_time.estimate_breakdown(4, queue)["ahead_count"] == 3


@pytest.mark.parametrize("esi,crisis,kind", [(1, False, "now"), (2, False, "now"), (3, True, "now"),
                                             (3, False, "estimate"), (4, False, "estimate"), (5, False, "estimate")])
def test_wait_kind(esi, crisis, kind):
    out = wait_time.patient_wait(esi, [], arrived_at="2026-10-19T10:00:00Z", crisis=crisis)
    assert out["wait_kind"] == kind
    if kind == "now":
        assert out["minutes"] is None and out["range"] is None
    else:
        assert isinstance(out["minutes"], int) and out["range"]


def test_esi_2_check_in_gets_no_minutes(client):
    body = _public(client, _seed(esi_level=2, esi_label="Emergent", explanation_key="esi2"))
    assert body["wait_kind"] == "now" and body["wait_estimate_minutes"] is None


# ---- 3. the care-steps text in every language -------------------------------------------
EN = sms_i18n.TEXT["en"]


@pytest.mark.parametrize("lang", comfort_i18n.LANGUAGES)
@pytest.mark.parametrize("for_parent", (False, True))
def test_care_text_frame_is_in_the_patients_language(lang, for_parent):
    assert set(sms_i18n.TEXT[lang]) == set(EN)
    for steps in (["Step one: Do this."], []):
        body = sms.render_care_message(patient_name="Omar Haddad", hospital_name="Demo Medical Center",
                                       care_instructions=steps, language=lang, for_parent=for_parent)
        full = sms.full_message(body, lang)
        assert "911" in full and "STOP" in full and "Solace" in full
        assert not DASHES.search(full), full
        assert "Demo Medical Center" in full
        if lang != "en":
            frame = full.replace("Step one: Do this.", "")
            for key in ("worse", "return", "footer", "parent_worse", "parent_return"):
                assert EN[key] not in frame, (lang, key)
            for words in ("care steps", "right away", "opt out", "your child", "message from"):
                assert words not in frame, (lang, words)
        if for_parent:
            assert not full.startswith("Omar"), full  # the parent is greeted, not the child
        else:
            assert "Omar" in full.splitlines()[0]


def test_formal_register():
    vi = " ".join(sms_i18n.TEXT["vi"].values())
    assert "bạn" not in vi and "quý vị" in vi
    assert " tu " not in " ".join(sms_i18n.TEXT["fr"].values())
    assert " du " not in " ".join(sms_i18n.TEXT["de"].values()).replace(" du Personal", "")


def test_missing_name_uses_the_greeting_without_a_name_suffix():
    first = sms.render_care_message(patient_name="", hospital_name="X", care_instructions=["a"], language="ja")
    assert first.startswith("こんにちは、") and "様" not in first.splitlines()[0]
    named = sms.render_care_message(patient_name="Yuki Sato", hospital_name="X", care_instructions=["a"], language="ja")
    assert named.startswith("Yuki様、")


@pytest.mark.parametrize("lang,direction", [("ar", "rtl"), ("fa", "rtl"), ("ur", "rtl"), ("en", "ltr"),
                                            ("zh", "ltr"), ("xx", "ltr")])
def test_direction(lang, direction):
    assert sms.text_direction(lang) == direction


def test_arabic_preview_is_all_arabic_and_says_rtl(client):
    pid = _seed(name="Omar Haddad", language="ar", comfort_protocol=json.dumps(comfort_i18n.cards_for("ar", "esi4")[0]))
    body = client.post(f"/api/{H}/sms/care-instructions", json={"patient_id": pid, "phone": ""}).json()
    assert body["reason"] == "sms_off" and body["language"] == "ar" and body["dir"] == "rtl"
    preview = body["preview"]
    assert sms_i18n.TEXT["ar"]["worse"] in preview and sms_i18n.TEXT["ar"]["footer"] in preview
    assert "tell the staff" not in preview and "Reply STOP to opt out" not in preview


def test_child_text_greets_the_parent(client):
    pid = _seed(name="Mia Lopez", transcript="fever 104 and very sleepy", medical_info=json.dumps({"age": 3}))
    body = client.post(f"/api/{H}/sms/care-instructions", json={"patient_id": pid}).json()
    preview = body["preview"]
    assert preview.startswith("Hello. Here are your child's care steps from Demo Medical Center:")
    assert "Mia," not in preview
    assert EN["parent_worse"] in preview and EN["worse"] not in preview
    assert body["language"] == "en" and body["dir"] == "ltr"


def test_text_follows_a_raised_screen(client):
    pid = _seed(refined_esi_level=2)
    preview = client.post(f"/api/{H}/sms/care-instructions", json={"patient_id": pid}).json()["preview"]
    cards = comfort_i18n.cards_for("en", "esi2")[0]
    assert f"1. {cards[0]['title']}: {cards[0]['instruction']}" in preview
    assert "Stay Seated" not in preview


def test_screen_helper_matches_the_endpoint(client):
    pid = _seed(refined_esi_level=3)
    screen = patients_router.patient_screen(storage.get_patient(pid))
    body = _public(client, pid)
    for key in ("esi_level", "esi_label", "explanation_key", "comfort_protocol", "care_recommendation"):
        assert screen[key] == body[key]


# ---- 4. sandbox creations per client: the last 60 minutes, not the clock hour ----------
@pytest.fixture
def clean_sandbox(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_creates_per_client_hour", 2)
    monkeypatch.setattr(settings, "sandbox_live_per_client", 100)
    monkeypatch.setattr(settings, "sandbox_max", 100)
    sandbox._reset_for_tests()
    yield
    sandbox._reset_for_tests()


def test_allowance_does_not_refill_at_the_top_of_the_hour(clean_sandbox):
    top = 1_800_000_000 - (1_800_000_000 % 3600) + 3600  # a clock-hour boundary
    with sandbox._lock:
        assert sandbox._no_room_locked("client-a", top - 30) is None
        assert sandbox._no_room_locked("client-a", top - 1) is None
        assert sandbox._no_room_locked("client-a", top - 1) is not None   # limit reached
        assert sandbox._no_room_locked("client-a", top + 5) is not None   # a new clock hour: still limited
        assert sandbox._no_room_locked("client-b", top + 5) is None       # another client is not affected
        assert sandbox._no_room_locked("client-a", top + 3569) is not None
        assert sandbox._no_room_locked("client-a", top + 3570) is None    # the first one is an hour old
        assert sandbox._no_room_locked("client-a", top + 3571) is not None


def test_sweep_forgets_clients_with_no_recent_creations(clean_sandbox):
    with sandbox._lock:
        assert sandbox._no_room_locked("client-c", 1000.0) is None
        sandbox._sweep_locked(1000.0 + 3600)
    assert "client-c" not in sandbox._created_at
