"""Platform checks: capabilities, health, the AI spend cap, private demo hospitals,
sign-in blocking, log redaction and serving the built frontend.

Everything runs in-process with no API keys and no network. The Claude client is
replaced by a fake that returns canned token counts.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import types
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import services  # noqa: E402
from db import media, storage  # noqa: E402
from lib import accounts, blocklist, claude, jwt_auth, local_table, log_redaction, quota, sandbox, spend  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402

EM, EN = chr(0x2014), chr(0x2013)


def _clear_security_tables() -> None:
    # Quota and block-list counters live in process memory; start each test clean.
    for name in ("solace-quotas", "solace-blocklist"):
        table = local_table._TABLES.get(name)
        if table is not None:
            table._items.clear()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(settings, "solace_mode", "local", raising=False)
    monkeypatch.setattr(settings, "solace_warm_model", False, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    storage._reset_for_tests()
    sandbox._reset_for_tests()
    spend._reset_for_tests()
    _clear_security_tables()
    yield
    for h in {c.get("hospital_id") for c in list(accounts._clinicians.values())}:
        if sandbox.is_sandbox(h):
            accounts.remove_hospital_accounts(h)
    storage._reset_for_tests()
    sandbox._reset_for_tests()
    spend._reset_for_tests()
    _clear_security_tables()


@pytest.fixture
def fake_seed(monkeypatch):
    """Stand-in for services.demo_seed so these tests do not depend on its contents."""
    calls: list[str] = []

    def seed_canonical_patients(hospital_id: str) -> list[str]:
        calls.append(hospital_id)
        ids = []
        for i, name in enumerate(["Ava", "Ben", "Cruz", "Dee", "Eli"], start=1):
            if any(p.get("name") == name for p in storage.list_patients_for_hospital(hospital_id, "all")):
                continue
            pid = str(uuid.uuid4())
            storage.put_patient({"patient_id": pid, "hospital_id": hospital_id, "name": name,
                                 "esi_level": i, "status": "waiting", "seed": True})
            ids.append(pid)
        return ids

    fake = types.ModuleType("services.demo_seed")
    fake.seed_canonical_patients = seed_canonical_patients
    monkeypatch.setitem(sys.modules, "services.demo_seed", fake)
    monkeypatch.setattr(services, "demo_seed", fake, raising=False)
    return calls


@pytest.fixture
def client(fake_seed):
    with TestClient(app) as c:
        yield c


def _ua() -> dict:
    return {"user-agent": f"platform-test-{uuid.uuid4().hex[:8]}"}


def _check_in(c: TestClient, hospital: str, text: str = "my ankle hurts after soccer") -> str:
    token = c.post(f"/api/{hospital}/start-intake").json()["token"]
    r = c.post(f"/api/{hospital}/intake", data={
        "patient_name": "Walk In", "pre_transcribed_text": text, "intake_token": token,
        "consent_granted": "true", "preferred_language": "en",
        "medical_info": json.dumps({"age": 30, "sex": "F"}),
    })
    assert r.status_code == 200, r.text
    return r.json()["patient_id"]


def _login(c: TestClient, hospital: str, name: str = "Dr. Chen", pin: str = "224466", headers=None):
    return c.post(f"/api/{hospital}/auth/login", json={"clinician_name": name, "pin": pin}, headers=headers)


def _auth(c: TestClient, hospital: str) -> dict:
    r = _login(c, hospital)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _queue_ids(c: TestClient, hospital: str, headers: dict) -> set[str]:
    body = c.get(f"/api/{hospital}/patients", params={"status": "all"}, headers=headers).json()
    rows = body if isinstance(body, list) else body.get("patients", [])
    return {p["patient_id"] for p in rows}


# ---- capabilities + health ---------------------------------------------------------------
def test_capabilities_shape_matches_the_frontend_contract(client):
    body = client.get("/api/demo/capabilities").json()
    assert set(body) == {"llm", "ocr", "transcription", "tts", "sms", "triage_model"}
    for key in ("llm", "ocr", "transcription", "tts", "sms"):
        assert body[key] is False, key  # no keys in tests
    tm = body["triage_model"]
    assert set(tm) == {"loaded", "mode", "folds"}
    assert tm["mode"] in {"lgbm_5fold", "rules_only"}
    assert isinstance(tm["loaded"], bool) and isinstance(tm["folds"], int)


def test_capabilities_survive_a_broken_model_status(client, monkeypatch):
    from services import triage_ml

    monkeypatch.setattr(triage_ml, "status", lambda: 1 / 0)
    tm = client.get("/api/demo/capabilities").json()["triage_model"]
    installed = (Path(triage_ml.MODELS_DIR) / "artifacts.pkl").exists()
    assert tm["loaded"] is installed
    assert tm["mode"] == ("lgbm_5fold" if installed else "rules_only")


def test_capabilities_llm_on_with_a_key(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test", raising=False)
    body = client.get("/api/demo/capabilities").json()
    assert body["llm"] is True and body["ocr"] is True


def test_sms_capability_never_follows_aws_region(client, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("SMS_PROVIDER", raising=False)
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TWILIO_SMS_FROM_NUMBER"):
        monkeypatch.delenv(k, raising=False)
    assert client.get("/api/demo/capabilities").json()["sms"] is False


def test_health_reports_capabilities_and_budget(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["capabilities"]["llm"] is False
    assert body["ai_budget"]["budget_left"] is True
    assert body["triage"] in {"lgbm_5fold", "rules_only"}
    assert body["seeding"]["state"] == "done" and body["seeding"]["clinicians_ready"] is True


# ---- Claude adapter: spend cap, request shaping, dash cleanup ---------------------------
class _FakeAnthropic:
    def __init__(self, text="ok", input_tokens=10_000, output_tokens=2_000):
        self.requests: list[dict] = []
        self.text, self.i, self.o = text, input_tokens, output_tokens
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        usage = types.SimpleNamespace(input_tokens=self.i, output_tokens=self.o,
                                      cache_creation_input_tokens=0, cache_read_input_tokens=0)
        block = types.SimpleNamespace(type="text", text=self.text)
        return types.SimpleNamespace(content=[block], stop_reason="end_turn", usage=usage)


@pytest.fixture
def fake_claude(monkeypatch):
    fake = _FakeAnthropic()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test", raising=False)
    monkeypatch.setattr(claude, "_anthropic_client", lambda: fake)
    return fake


def _call(model="claude-haiku-5-5", **kw):
    return claude.messages_create(model=model, max_tokens=500, system="sys",
                                  messages=[{"role": "user", "content": "hi"}], purpose="test", **kw)


def test_no_key_means_no_call(monkeypatch):
    def boom():
        raise AssertionError("no client may be built without a key")

    monkeypatch.setattr(claude, "_anthropic_client", boom)
    assert claude.available() is False
    with pytest.raises(claude.ClaudeUnavailable):
        _call()


def test_daily_budget_trips_and_turns_ai_off(fake_claude, monkeypatch, client, caplog):
    # 10K input + 2K output tokens on Haiku 5.5 is $0.002, over a $0.001 budget.
    monkeypatch.setattr(settings, "ai_daily_budget_usd", 0.001, raising=False)
    assert claude.available() is True
    with caplog.at_level(logging.WARNING, logger="lib.spend"):
        resp = _call()
    assert resp.cost_usd == pytest.approx(0.002)
    assert spend.spent_today() == pytest.approx(0.002)
    assert "daily budget reached" in caplog.text
    assert claude.available() is False
    with pytest.raises(claude.ClaudeUnavailable):
        _call()
    assert len(fake_claude.requests) == 1
    assert client.get("/api/demo/capabilities").json()["llm"] is False
    assert client.get("/health").json()["ai_budget"]["budget_left"] is False
    spend._reset_for_tests()
    monkeypatch.setattr(settings, "ai_daily_budget_usd", 0.0, raising=False)
    assert claude.available() is False  # a budget of 0 turns AI off


def test_per_visitor_hourly_limit(fake_claude, monkeypatch):
    monkeypatch.setattr(settings, "ai_calls_per_visitor_hour", 2, raising=False)
    token = spend.set_visitor("visitor-a")
    try:
        _call(), _call()
        assert claude.available() is False
        with pytest.raises(claude.ClaudeUnavailable):
            _call()
    finally:
        spend.reset_visitor(token)
    token = spend.set_visitor("visitor-b")
    assert claude.available() is True
    spend.reset_visitor(token)


def test_visitor_limit_reaches_requests_through_the_middleware(client, monkeypatch):
    # The middleware tags each /api request with the visitor, and the tag must reach
    # the endpoint's worker thread, or the hourly limit would never apply.
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "ai_calls_per_visitor_hour", 0, raising=False)
    assert client.get("/api/demo/capabilities").json()["llm"] is False
    # /health is not a visitor request, so only the daily budget applies there.
    assert client.get("/health").json()["capabilities"]["llm"] is True


def test_new_models_drop_temperature_and_turn_thinking_off(fake_claude):
    _call("claude-haiku-5-5", temperature=0)
    req = fake_claude.requests[-1]
    assert "temperature" not in req
    assert req["extra_body"]["thinking"] == {"type": "disabled"}
    assert req["max_tokens"] == 650  # scaled for the newer tokenizer

    _call("claude-haiku-4-5", temperature=0)
    req = fake_claude.requests[-1]
    assert req["temperature"] == 0 and "extra_body" not in req and req["max_tokens"] == 500

    # Overrides through MODEL_CLINICAL / MODEL_UTILITY get a request each model accepts.
    _call("claude-sonnet-4-20250514", temperature=0)
    assert fake_claude.requests[-1]["temperature"] == 0
    _call("claude-opus-4-8", temperature=0)
    req = fake_claude.requests[-1]
    assert "temperature" not in req and "extra_body" not in req
    _call("claude-opus-5-5", temperature=0)
    req = fake_claude.requests[-1]
    assert req["extra_body"] == {"output_config": {"effort": "low"}} and req["max_tokens"] > 650
    _call("claude-sonnet-5-5")
    assert fake_claude.requests[-1]["extra_body"]["thinking"] == {"type": "between_tools"}
    # Both tiers default to the newest low-cost Haiku.
    assert settings.model_clinical == settings.model_utility == "claude-haiku-5-5"


def test_dashes_are_removed_from_replies(fake_claude):
    fake_claude.text = f"Rest{EM}then drink water. Wait 3{EN}5 minutes {EM} then call."
    out = _call().content[0].text
    assert EM not in out and EN not in out
    assert "3-5 minutes" in out
    assert claude.strip_dashes(f"{EM} first step") == "- first step"
    assert claude.strip_dashes('{"a": "' + EM + ' note"}') == '{"a": "note"}'
    minus = chr(0x2212)
    assert claude.strip_dashes(f"{minus}3") == f"{minus}3"


def test_cost_estimate_uses_the_price_table():
    assert spend.estimate_cost("claude-haiku-5-5", 100_000, 0) == pytest.approx(0.01)
    assert spend.estimate_cost("claude-haiku-5-5", 200_000, 0) == pytest.approx(0.10)  # long-prompt rate
    assert spend.estimate_cost("claude-haiku-4-5-20251001", 0, 1_000_000) == pytest.approx(5.00)
    assert spend.estimate_cost("some-future-model", 1_000_000, 0) == pytest.approx(spend.UNKNOWN_PRICE[0])


# ---- private demo hospitals ----------------------------------------------------------------
def test_sandbox_is_created_on_first_use_with_examples(client, fake_seed):
    assert client.get("/api/demo-aaaaaa/capabilities").status_code == 200  # never builds one
    assert "demo-aaaaaa" not in fake_seed and not sandbox.is_live("demo-aaaaaa")
    headers = _auth(client, "demo-aaaaaa")  # the first real request builds it, usual PINs
    assert "demo-aaaaaa" in fake_seed and storage.get_hospital("demo-aaaaaa") is not None
    assert len(_queue_ids(client, "demo-aaaaaa", headers)) == 5


def test_sandboxes_are_isolated(client):
    pid = _check_in(client, "demo-aaaaaa")
    a_headers = _auth(client, "demo-aaaaaa")
    b_headers = _auth(client, "demo-bbbbbb")
    assert pid in _queue_ids(client, "demo-aaaaaa", a_headers)
    assert pid not in _queue_ids(client, "demo-bbbbbb", b_headers)
    assert client.get(f"/api/demo-bbbbbb/patients/{pid}", headers=b_headers).status_code in (403, 404)
    # A token from one sandbox does not open another.
    assert client.get("/api/demo-bbbbbb/patients", headers=a_headers).status_code == 403


def test_idle_sandbox_is_purged(client):
    pid = _check_in(client, "demo-cccccc")
    assert storage.get_patient(pid)
    sandbox._last_seen["demo-cccccc"] = time.time() - 3 * 3600
    assert "demo-cccccc" in sandbox.sweep()
    assert storage.get_patient(pid) is None
    assert storage.get_hospital("demo-cccccc") is None
    assert not [c for c in accounts._clinicians.values() if c.get("hospital_id") == "demo-cccccc"]
    # The next visit gets a fresh sandbox.
    assert client.post("/api/demo-cccccc/start-intake").status_code == 200
    assert storage.get_hospital("demo-cccccc") is not None


def test_old_check_ins_leave_the_shared_demo_hospital(client):
    fresh = _check_in(client, "demo")
    old = _check_in(client, "demo")
    examples = [p["patient_id"] for p in storage.list_patients_for_hospital("demo", "all") if p.get("seed")]
    assert len(examples) == 5
    # A fixed created_at in the past (as other tests use) does not count as old.
    storage.update_patient(fresh, {"created_at": "2020-01-01T00:00:00Z"})
    assert sandbox.prune_shared_demo() == 0
    sandbox._demo_first_seen[old] = time.time() - 7 * 3600
    assert sandbox.prune_shared_demo() == 1
    assert storage.get_patient(old) is None and storage.get_patient(fresh) is not None
    assert all(storage.get_patient(pid) for pid in examples)


def test_full_sandbox_pool_serves_the_shared_demo_not_an_error(client, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_max", 1, raising=False)
    assert client.post("/api/demo-dddddd/start-intake").status_code == 200 and sandbox.is_live("demo-dddddd")
    # No slot left: the new id works, served from the shared demo hospital.
    pid = _check_in(client, "demo-eeeeee")
    assert not sandbox.is_live("demo-eeeeee") and sandbox.alias_of("demo-eeeeee") == "demo"
    assert storage.get_patient(pid)["hospital_id"] == "demo"
    assert pid in _queue_ids(client, "demo-eeeeee", _auth(client, "demo-eeeeee"))


def test_unknown_hospital_is_a_plain_404(client):
    for path in ("/api/clinician/capabilities", "/api/demo-TOOLONG1/start-intake", "/api/demo-abc/patients"):
        r = client.get(path) if path.endswith("capabilities") or path.endswith("patients") else client.post(path)
        assert r.status_code == 404, path
        assert r.json() == {"detail": "Unknown hospital"}


@pytest.mark.parametrize("seed_on", [True, False])
def test_startup_seeds_the_demo_hospital_unless_turned_off(fake_seed, monkeypatch, seed_on):
    monkeypatch.setattr(settings, "solace_seed_demo", seed_on, raising=False)
    with TestClient(app):
        pass
    assert ("demo" in fake_seed) is seed_on


def test_reset_demo_removes_walk_ins_and_restores_examples(client):
    headers = _auth(client, "demo-ffffff")
    walk_in = _check_in(client, "demo-ffffff")
    before = _queue_ids(client, "demo-ffffff", headers)
    assert walk_in in before and len(before) == 6
    body = client.post("/api/demo-ffffff/admin/reset-demo", headers=headers).json()
    assert body["restored_patients"] == 5 and "restored the 5 example patients" in body["message"]
    after = _queue_ids(client, "demo-ffffff", headers)
    assert walk_in not in after and len(after) == 5


# ---- sign-in abuse never blocks patients ---------------------------------------------------
def test_wrong_pins_do_not_block_patient_check_in(client):
    hospital = "demo-lockaa"
    for _ in range(5):
        assert _login(client, hospital, pin="123456").status_code == 401
    # Same device (TestClient's IP and User-Agent): check-in still works.
    assert client.post(f"/api/{hospital}/start-intake").status_code == 200
    # The account itself is locked for a while, with a plain message.
    locked = _login(client, hospital)
    assert locked.status_code == 429
    assert "locked" in locked.json()["detail"]
    # Another clinician can still sign in from this device.
    assert _login(client, hospital, name="Dr. Patel", pin="113355").status_code == 200
    # Once the lockout time has passed, the right PIN works again.
    rec = jwt_auth.find_clinician(hospital, "Dr. Chen")
    rec["locked_until"] = int(time.time()) - 1
    assert _login(client, hospital).status_code == 200
    # Both blocks are short on the demo: 5 minutes.
    assert blocklist.block_seconds() == jwt_auth.lockout_seconds() == 300


def test_guessing_across_accounts_blocks_sign_in_only(client):
    hospital = "demo-lockbb"
    ua = _ua()
    for name in ("Dr. Chen", "Dr. Patel", "Dr. Kim"):
        for _ in range(4):
            _login(client, hospital, name=name, pin="000000", headers=ua)
    r = _login(client, hospital, name="Dr. Kim", pin="667788", headers=ua)
    assert r.status_code == 429
    assert "wait" in r.json()["detail"]
    assert client.post(f"/api/{hospital}/start-intake", headers=ua).status_code == 200


# ---- logging, secrets, media -----------------------------------------------------------------
def test_redaction_keeps_uvicorn_access_log_formatting():
    from uvicorn.logging import AccessFormatter

    pid = str(uuid.uuid4())
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5555", "GET", f"/api/demo/public-patients/{pid}", "1.1", 200), None,
    )
    assert log_redaction.RedactPatientUUIDsFilter().filter(record)
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert pid not in line and "[PID]" in line and "200" in line


def test_redaction_of_plain_log_lines():
    pid = str(uuid.uuid4())
    record = logging.LogRecord("solace", logging.INFO, __file__, 1, "patient %s token %s",
                               (pid, "Bearer abc.def.ghi"), None)
    log_redaction.RedactPatientUUIDsFilter().filter(record)
    assert pid not in record.getMessage() and "abc.def" not in record.getMessage()


def test_jwt_secret_comes_from_env_or_is_random(monkeypatch):
    raw = jwt_auth._auth_secret.__wrapped__
    monkeypatch.setenv("SOLACE_JWT_SECRET", "from-env")
    assert raw()["JWT_SIGNING_KEY"] == "from-env"
    monkeypatch.delenv("SOLACE_JWT_SECRET")
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    a, b = raw()["JWT_SIGNING_KEY"], raw()["JWT_SIGNING_KEY"]
    assert a != b and len(a) >= 32
    assert "local-dev-only" not in a


def test_media_urls_are_relative(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "local_media_dir", str(tmp_path), raising=False)
    url = media.save("audio", "x.mp3", b"123")
    assert url == "/media/audio/x.mp3"


def test_speech_services_make_no_calls_without_keys(monkeypatch):
    from services import transcription, tts

    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "", raising=False)

    for module, name in ((transcription, "_openai_transcribe"), (tts, "_elevenlabs_synthesize")):
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail("no network call without a key"))
    assert transcription.is_configured() is False and tts.is_configured() is False
    with pytest.raises(transcription.TranscriptionError) as e:
        transcription.transcribe(b"audio")
    assert "type" in str(e.value)
    assert tts.generate_and_upload("hello", "en", "p-1") is None


def test_sms_quota_limit_exists():
    assert quota.LIMITS["sms.self_serve"].per_hour == 10
    assert quota.try_consume("sms-test", "sms.self_serve")


# ---- the built frontend ------------------------------------------------------------------------
@pytest.fixture
def dist(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>solace app</html>")
    (tmp_path / "assets" / "app-123.js").write_text("console.log(1)")
    (tmp_path / "config.json").write_text('{"apiBaseUrl": ""}')
    monkeypatch.setattr(settings, "solace_static_dir", str(tmp_path), raising=False)
    return tmp_path


def test_spa_routes_fall_back_to_index(client, dist):
    for path in ("/", "/demo", "/demo/clinician", "/showcase"):
        r = client.get(path)
        assert r.status_code == 200 and "solace app" in r.text, path
        assert r.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_and_missing_files_404(client, dist):
    r = client.get("/assets/app-123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert client.get("/assets/old-999.js").status_code == 404
    assert client.get("/config.json").json() == {"apiBaseUrl": ""}
    assert client.get("/../main.py").status_code == 404


def test_api_media_and_health_win_over_the_frontend(client, dist):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/api/demo/no-such-endpoint")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert client.get("/api/demo/capabilities").json()["llm"] is False
    assert client.get("/media/audio/none.mp3").status_code == 404
