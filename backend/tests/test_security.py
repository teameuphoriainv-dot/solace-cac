"""Abuse guards for the hosted demo: who a client is, sandbox limits with the shared-demo
fallback, the global AI guards, visitor tags in background work, security headers, and a
startup that answers health checks at once.

Everything runs in-process with no keys and no network: the Claude client is a fake.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import main  # noqa: E402
import services  # noqa: E402
from db import storage  # noqa: E402
from lib import accounts, async_invoke, claude, local_table, quota, sandbox, spend  # noqa: E402
from lib.config import settings  # noqa: E402

app = main.app


def _clear_counters() -> None:
    for name in ("solace-quotas", "solace-blocklist"):
        table = local_table._TABLES.get(name)
        if table is not None:
            table._items.clear()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(settings, "solace_mode", "local", raising=False)
    monkeypatch.setattr(settings, "solace_warm_model", False, raising=False)
    monkeypatch.setattr(settings, "solace_seed_demo", True, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(settings, "solace_trusted_proxy_hops", 1, raising=False)
    monkeypatch.delenv("SOLACE_SEED_BACKGROUND", raising=False)
    storage._reset_for_tests()
    sandbox._reset_for_tests()
    spend._reset_for_tests()
    _clear_counters()
    yield
    for h in {c.get("hospital_id") for c in list(accounts._clinicians.values())}:
        if sandbox.is_sandbox(h):
            accounts.remove_hospital_accounts(h)
    storage._reset_for_tests()
    sandbox._reset_for_tests()
    spend._reset_for_tests()
    _clear_counters()


@pytest.fixture
def fake_seed(monkeypatch):
    """Five example patients per hospital, without the real seeding pipeline."""
    def seed_canonical_patients(hospital_id: str) -> list[str]:
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


@pytest.fixture
def client(fake_seed):
    with TestClient(app) as c:
        yield c


def _xff(*hops: str, ua: str | None = None) -> dict:
    h = {"x-forwarded-for": ", ".join(hops)}
    if ua:
        h["user-agent"] = ua
    return h


def _check_in(c: TestClient, hospital: str, headers: dict | None = None) -> str:
    token = c.post(f"/api/{hospital}/start-intake", headers=headers).json()["token"]
    r = c.post(f"/api/{hospital}/intake", headers=headers, data={
        "patient_name": "Walk In", "pre_transcribed_text": "my ankle hurts after soccer",
        "intake_token": token, "consent_granted": "true", "preferred_language": "en",
        "medical_info": json.dumps({"age": 30, "sex": "F"}),
    })
    assert r.status_code == 200, r.text
    return r.json()["patient_id"]


def _auth(c: TestClient, hospital: str, headers: dict | None = None) -> dict:
    r = c.post(f"/api/{hospital}/auth/login", json={"clinician_name": "Dr. Chen", "pin": "224466"},
               headers=headers)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", **(headers or {})}


def _queue_ids(c: TestClient, hospital: str, headers: dict) -> set[str]:
    body = c.get(f"/api/{hospital}/patients", params={"status": "all"}, headers=headers).json()
    rows = body if isinstance(body, list) else body.get("patients", [])
    return {p["patient_id"] for p in rows}


# ---- 1. client identity: only the last X-Forwarded-For entry is trusted -----------------
def test_client_ip_trusts_the_last_hop(monkeypatch):
    assert quota.client_ip("6.6.6.6, 203.0.113.7", "10.0.0.2") == "203.0.113.7"
    assert quota.client_ip(" 203.0.113.7 ", "10.0.0.2") == "203.0.113.7"
    assert quota.client_ip(None, "10.0.0.2") == "10.0.0.2"
    assert quota.client_ip("", None) == "unknown"
    monkeypatch.setattr(settings, "solace_trusted_proxy_hops", 2)
    assert quota.client_ip("6.6.6.6, 203.0.113.7, 10.1.1.1", "10.0.0.2") == "203.0.113.7"
    monkeypatch.setattr(settings, "solace_trusted_proxy_hops", 0)
    assert quota.client_ip("6.6.6.6, 203.0.113.7", "10.0.0.2") == "10.0.0.2"


def test_identity_of_a_raw_header_uses_the_last_hop():
    ua = "Mozilla/5.0 test"
    assert quota.identity_of("9.9.9.9, 203.0.113.7", ua) == quota.identity_of("203.0.113.7", ua)
    assert quota.identity_of("9.9.9.9, 203.0.113.7", ua) != quota.identity_of("9.9.9.9", ua)


def test_rotating_the_spoofable_part_does_not_reset_limits(client, monkeypatch):
    monkeypatch.setitem(quota.LIMITS, "intake.start", quota.Limit("intake.start", per_hour=2))
    ua = "same-browser"
    for fake in ("1.1.1.1", "2.2.2.2"):
        assert client.post("/api/demo/start-intake", headers=_xff(fake, "203.0.113.7", ua=ua)).status_code == 200
    # A third made-up first entry is the same client: over the limit.
    r = client.post("/api/demo/start-intake", headers=_xff("3.3.3.3", "203.0.113.7", ua=ua))
    assert r.status_code == 429
    # A really different client (different last hop) is not affected.
    assert client.post("/api/demo/start-intake", headers=_xff("3.3.3.3", "198.51.100.4", ua=ua)).status_code == 200


def test_visitor_tag_follows_the_last_hop(client, monkeypatch):
    seen: list[str | None] = []
    real = spend.visitor_allowed

    def spy():
        seen.append(spend.current_visitor())
        return real()

    monkeypatch.setattr(spend, "visitor_allowed", spy)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test", raising=False)
    for fake in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        client.get("/api/demo/capabilities", headers=_xff(fake, "203.0.113.7", ua="b"))
    client.get("/api/demo/capabilities", headers=_xff("198.51.100.4", ua="b"))
    assert len(seen) == 4 and None not in seen
    assert seen[0] == seen[1] == seen[2] != seen[3]


# ---- 2. sandbox limits and the shared-demo alias ------------------------------------------
def test_capabilities_never_builds_a_sandbox(client):
    for i in range(40):
        r = client.get(f"/api/demo-p{i:05d}/capabilities")
        assert r.status_code == 200 and "llm" in r.json()
    assert sandbox.stats()["live"] == 0 and sandbox.stats()["shared_aliases"] == 0


def test_creation_limit_falls_back_to_the_shared_demo(client, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_creates_per_client_hour", 1)
    me = _xff("203.0.113.7", ua="judge-browser")
    assert client.post("/api/demo-first1/start-intake", headers=me).status_code == 200
    assert sandbox.is_live("demo-first1")

    # Same client address (another browser, so another User-Agent): no new sandbox, but
    # the id works, served from the shared demo hospital. Never a 503.
    other_ua = _xff("203.0.113.7", ua="second-browser")
    pid = _check_in(client, "demo-second", other_ua)
    assert not sandbox.is_live("demo-second") and sandbox.alias_of("demo-second") == "demo"
    assert storage.get_patient(pid)["hospital_id"] == "demo"

    # Sign-in works through the alias, and shows the same patients as the shared demo.
    via_alias = _auth(client, "demo-second", other_ua)
    ids = _queue_ids(client, "demo-second", via_alias)
    assert pid in ids
    assert ids == _queue_ids(client, "demo", _auth(client, "demo"))
    # The patient's result page keeps polling through the same id.
    assert client.get(f"/api/demo-second/public-patients/{pid}", headers=other_ua).status_code == 200

    # The alias is remembered: once the hourly allowance is back, the id stays shared,
    # so the judge's check-ins and sign-in do not vanish.
    _clear_counters()
    assert client.post("/api/demo-second/start-intake", headers=other_ua).status_code == 200
    assert sandbox.alias_of("demo-second") == "demo" and not sandbox.is_live("demo-second")
    assert pid in _queue_ids(client, "demo-second", via_alias)

    # Another client still gets a private sandbox.
    assert client.post("/api/demo-third3/start-intake", headers=_xff("198.51.100.4")).status_code == 200
    assert sandbox.is_live("demo-third3")


def test_live_sandboxes_per_client_are_capped(client, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_live_per_client", 2)
    me = _xff("6.6.6.6", "203.0.113.9")
    for sid in ("demo-live01", "demo-live02", "demo-live03"):
        assert client.post(f"/api/{sid}/start-intake", headers=me).status_code == 200
    assert sandbox.is_live("demo-live01") and sandbox.is_live("demo-live02")
    assert sandbox.alias_of("demo-live03") == "demo"
    # When one of them expires, the client may make a new one.
    sandbox._last_seen["demo-live01"] = time.time() - 3 * 3600
    sandbox.sweep()
    assert client.post("/api/demo-live04/start-intake", headers=me).status_code == 200
    assert sandbox.is_live("demo-live04")


def test_alias_is_forgotten_after_the_idle_time(client, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_max", 0)
    assert client.post("/api/demo-idle01/start-intake").status_code == 200
    assert sandbox.alias_of("demo-idle01") == "demo"
    sandbox._aliases["demo-idle01"] = time.time() - 3 * 3600
    sandbox.sweep()
    assert sandbox.alias_of("demo-idle01") is None


# ---- 3. global AI guards ------------------------------------------------------------------
class _FakeAnthropic:
    def __init__(self, input_tokens=10_000, output_tokens=2_000):
        self.requests: list[dict] = []
        self.i, self.o = input_tokens, output_tokens
        self.messages = self
        self._lock = threading.Lock()

    def create(self, **kw):
        with self._lock:
            self.requests.append(kw)
        usage = types.SimpleNamespace(input_tokens=self.i, output_tokens=self.o,
                                      cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")],
                                     stop_reason="end_turn", usage=usage)


@pytest.fixture
def clock(monkeypatch):
    now = [datetime(2026, 10, 20, 14, 0, 5, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(spend, "_clock", lambda: now[0])
    spend._reset_for_tests()
    return now


def _with_fake(monkeypatch, **kw) -> _FakeAnthropic:
    fake = _FakeAnthropic(**kw)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test", raising=False)
    monkeypatch.setattr(claude, "_anthropic_client", lambda: fake)
    return fake


def _call():
    return claude.messages_create(model="claude-haiku-5-5", max_tokens=100, system="s",
                                  messages=[{"role": "user", "content": "hi"}], purpose="test")


def test_hourly_slice_pauses_ai_until_the_next_hour(monkeypatch, clock):
    monkeypatch.setattr(settings, "ai_daily_budget_usd", 3.0)
    monkeypatch.setattr(settings, "ai_hourly_budget_fraction", 0.35)
    # 100K input + 1.1M output tokens on Haiku 5.5 is $0.56 a call: two calls pass $1.05.
    fake = _with_fake(monkeypatch, input_tokens=100_000, output_tokens=1_100_000)
    assert spend.status()["hour_cap_usd"] == pytest.approx(1.05)
    _call(), _call()
    assert spend.status()["spent_this_hour_usd"] == pytest.approx(1.12)
    assert spend.status()["paused"] == "hour"
    assert not spend.exhausted()  # the day's $3 is not used up...
    assert claude.available() is False  # ...but this hour's share is
    assert "next hour" in claude.unavailable_reason()
    with pytest.raises(claude.ClaudeUnavailable):
        _call()
    assert len(fake.requests) == 2

    clock[0] += 3600  # the next clock hour
    assert claude.available() is True
    _call()
    assert spend.spent_today() == pytest.approx(1.68) and len(fake.requests) == 3


def test_daily_cap_is_still_the_hard_stop(monkeypatch, clock):
    monkeypatch.setattr(settings, "ai_daily_budget_usd", 1.0)
    monkeypatch.setattr(settings, "ai_hourly_budget_fraction", 0.9)
    fake = _with_fake(monkeypatch, input_tokens=100_000, output_tokens=1_100_000)
    _call()
    clock[0] += 3600
    _call()  # $1.12 > $1.00 for the day
    clock[0] += 3600
    assert spend.exhausted() and claude.available() is False
    assert "today" in claude.unavailable_reason()
    with pytest.raises(claude.ClaudeUnavailable):
        _call()
    assert len(fake.requests) == 2


def test_per_minute_ceiling(monkeypatch, clock):
    monkeypatch.setattr(settings, "ai_calls_per_minute", 3)
    fake = _with_fake(monkeypatch)
    for _ in range(3):
        _call()
    assert claude.available() is False and "minute" in claude.unavailable_reason()
    with pytest.raises(claude.ClaudeUnavailable):
        _call()
    assert len(fake.requests) == 3 and spend.status()["calls_last_minute"] == 3
    clock[0] += 61
    assert claude.available() is True
    _call()
    assert len(fake.requests) == 4


def test_per_minute_ceiling_holds_under_a_burst(monkeypatch, clock):
    monkeypatch.setattr(settings, "ai_calls_per_minute", 5)
    fake = _with_fake(monkeypatch)
    start = threading.Barrier(20)
    refused: list[int] = []

    def burst():
        start.wait()
        try:
            _call()
        except claude.ClaudeUnavailable:
            refused.append(1)

    threads = [threading.Thread(target=burst) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(fake.requests) == 5 and len(refused) == 15


def test_guards_do_not_depend_on_who_is_asking(monkeypatch, clock):
    monkeypatch.setattr(settings, "ai_calls_per_minute", 2)
    _with_fake(monkeypatch)
    for visitor in ("made-up-1", "made-up-2"):
        token = spend.set_visitor(visitor)
        try:
            _call()
        finally:
            spend.reset_visitor(token)
    token = spend.set_visitor("made-up-3")
    try:
        assert claude.available() is False
    finally:
        spend.reset_visitor(token)


# ---- 4. the visitor tag reaches deferred work ---------------------------------------------
def test_deferred_thread_runs_with_the_visitor(monkeypatch):
    from services import intake_artifacts

    seen: list[str | None] = []
    done = threading.Event()

    def fake_generate(hospital_id, patient_id):
        seen.append(spend.current_visitor())
        done.set()
        return {}

    monkeypatch.setattr(intake_artifacts, "generate_clinician_artifacts", fake_generate)
    token = spend.set_visitor("visitor-xyz")
    try:
        assert async_invoke.dispatch_deferred_artifacts("demo", "p-1") == "thread"
    finally:
        spend.reset_visitor(token)
    assert done.wait(5)
    assert seen == ["visitor-xyz"]


def test_check_in_background_work_carries_the_request_visitor(client, monkeypatch):
    from services import intake_artifacts

    seen: list[str | None] = []
    done = threading.Event()

    def fake_generate(hospital_id, patient_id):
        seen.append(spend.current_visitor())
        done.set()
        return {}

    monkeypatch.setattr(intake_artifacts, "generate_clinician_artifacts", fake_generate)
    _check_in(client, "demo", _xff("203.0.113.7", ua="judge"))
    assert done.wait(5)
    expected = quota.identity_of("203.0.113.7", "judge")
    assert seen == [expected]


def test_ddx_pool_call_runs_with_the_visitor(monkeypatch):
    from services import ddx_v2

    seen: list[str | None] = []

    def fake_create(**kw):
        seen.append(spend.current_visitor())
        return claude.Response(content=[claude.TextBlock(text=json.dumps({"differential": [
            {"diagnosis": "Ankle sprain", "weight": 0.8, "supporting": ["twisted ankle"]}]}))])

    monkeypatch.setattr(claude, "available", lambda: True)
    monkeypatch.setattr(claude, "messages_create", fake_create)
    token = spend.set_visitor("visitor-ddx")
    try:
        out = ddx_v2.generate("I twisted my ankle playing soccer", "ankle pain")
    finally:
        spend.reset_visitor(token)
    assert out["source"] == "claude" and seen == ["visitor-ddx"]


# ---- 5. security headers -------------------------------------------------------------------
@pytest.fixture
def dist(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>solace app</html>")
    monkeypatch.setattr(settings, "solace_static_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "solace_public_url", "", raising=False)
    return tmp_path


def _assert_security_headers(r, csp: bool = True):
    h = r.headers
    assert h["x-frame-options"] == "SAMEORIGIN"
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert "camera=(self)" in h["permissions-policy"] and "microphone=(self)" in h["permissions-policy"]
    if csp:
        policy = h["content-security-policy"]
        for part in ("default-src 'self'", "frame-ancestors 'self'", "connect-src 'self'",
                     "img-src 'self' data: blob:", "media-src 'self' data: blob:",
                     "https://fonts.googleapis.com", "https://fonts.gstatic.com"):
            assert part in policy, part
        assert "'unsafe-eval'" not in policy and "script-src 'self'" in policy


def test_security_headers_on_every_kind_of_response(client, dist):
    _assert_security_headers(client.get("/"))                      # the app shell
    _assert_security_headers(client.get("/demo-abcdef/clinician"))  # a client route
    _assert_security_headers(client.get("/showcase"))
    _assert_security_headers(client.get("/health"))
    _assert_security_headers(client.get("/api/demo/capabilities"))
    _assert_security_headers(client.get("/api/clinician/capabilities"))  # the gate's own 404
    _assert_security_headers(client.get("/assets/missing.js"))
    # FastAPI's docs page loads its scripts from a CDN, so it keeps the others but no CSP.
    docs = client.get("/docs")
    _assert_security_headers(docs, csp=False)
    assert "content-security-policy" not in docs.headers


# ---- 6. startup answers health checks at once ----------------------------------------------
def test_background_startup_answers_health_at_once(monkeypatch, fake_seed):
    monkeypatch.setenv("SOLACE_SEED_BACKGROUND", "1")
    release = threading.Event()
    real_clinicians = accounts.seed_demo_clinicians

    def slow_clinicians(hospital_id):
        release.wait(10)
        real_clinicians(hospital_id)

    real_seed = main._seed_demo

    def slow_seed():
        time.sleep(0.5)
        return real_seed()

    monkeypatch.setattr(accounts, "seed_demo_clinicians", slow_clinicians)
    monkeypatch.setattr(main, "_seed_demo", slow_seed)
    started = time.monotonic()
    try:
        with TestClient(app) as c:
            r = c.get("/health")
            assert r.status_code == 200 and time.monotonic() - started < 2
            seeding = r.json()["seeding"]
            assert seeding["state"] == "running" and seeding["background"] is True
            assert seeding["clinicians_ready"] is False and seeding["step"] == "clinicians"

            # A sign-in sent now waits for the clinicians instead of failing.
            threading.Timer(0.3, release.set).start()
            login = c.post("/api/demo/auth/login", json={"clinician_name": "Dr. Chen", "pin": "224466"})
            assert login.status_code == 200, login.text

            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                seeding = c.get("/health").json()["seeding"]
                if seeding["state"] != "running":
                    break
                time.sleep(0.05)
            assert seeding["state"] == "done" and seeding["clinicians_ready"] is True
            assert seeding["example_patients"] == 5 and seeding["seconds"] >= 0.5
    finally:
        release.set()
