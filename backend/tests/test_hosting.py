"""Hosted-demo plumbing: the Secrets Manager key read, the plain 422 message, the absolute
share-preview links, and the patient fields the result page and the record view read.

No network and no AWS: every Secrets Manager client here is a stub, and boto3 itself is
replaced by a tripwire wherever a test promises that no client is made.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import main  # noqa: E402
from db import storage  # noqa: E402
from lib import config  # noqa: E402
from lib.config import settings  # noqa: E402

FAKE_KEY = "sk-ant-test-0123456789abcdef"


class _StubSecrets:
    """Stands in for boto3's secretsmanager client."""

    def __init__(self, secret_string: str | None = None, error: Exception | None = None):
        self.secret_string = secret_string
        self.error = error
        self.calls: list[str] = []

    def get_secret_value(self, SecretId):  # noqa: N803 (boto3 casing)
        self.calls.append(SecretId)
        if self.error:
            raise self.error
        return {"SecretString": self.secret_string}


@pytest.fixture
def keys(monkeypatch):
    """Clean key settings, and boto3 that fails the test if a real client is made."""
    for attr in ("anthropic_api_key", "openai_api_key", "elevenlabs_api_key"):
        monkeypatch.setattr(settings, attr, "", raising=False)
    monkeypatch.setattr(settings, "solace_mode", "local", raising=False)
    monkeypatch.setattr(settings, "solace_keys_secret", "", raising=False)
    monkeypatch.setattr(config, "_hydrated", False)
    for var in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(var, raising=False)
    made: list[tuple] = []

    def _no_real_client(*args, **kwargs):
        made.append((args, kwargs))
        raise AssertionError("a real boto3 client was created")

    import boto3  # noqa: PLC0415

    monkeypatch.setattr(boto3, "client", _no_real_client)
    monkeypatch.setattr(boto3, "resource", _no_real_client)
    return made


# ---- Secrets Manager key read -----------------------------------------------------------
def test_no_secret_configured_means_no_aws_at_all(keys):
    assert config.hydrate_from_secrets_manager() == []
    assert keys == []
    assert settings.anthropic_api_key == ""


def test_hosted_secret_sets_only_the_anthropic_key(keys, monkeypatch, caplog):
    monkeypatch.setattr(settings, "solace_keys_secret", "solace/api-keys")
    stub = _StubSecrets(json.dumps({
        "ANTHROPIC_API_KEY": FAKE_KEY,
        "OPENAI_API_KEY": "sk-openai-should-not-be-used",
        "ELEVENLABS_API_KEY": "el-should-not-be-used",
    }))
    with caplog.at_level(logging.DEBUG):
        filled = config.hydrate_from_secrets_manager(client=stub)
    assert filled == ["anthropic_api_key"]
    assert stub.calls == ["solace/api-keys"]
    assert settings.anthropic_api_key == FAKE_KEY
    # Uncapped providers are never picked up by the hosted demo.
    assert settings.openai_api_key == "" and settings.elevenlabs_api_key == ""
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert FAKE_KEY not in logged and "should-not-be-used" not in logged


def test_lowercase_key_and_bare_string_are_accepted(keys, monkeypatch):
    monkeypatch.setattr(settings, "solace_keys_secret", "solace/api-keys")
    assert config.hydrate_from_secrets_manager(
        client=_StubSecrets(json.dumps({"anthropic_api_key": FAKE_KEY})), force=True) == ["anthropic_api_key"]
    assert settings.anthropic_api_key == FAKE_KEY

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert config.hydrate_from_secrets_manager(client=_StubSecrets(FAKE_KEY), force=True) == ["anthropic_api_key"]
    assert settings.anthropic_api_key == FAKE_KEY


def test_missing_or_empty_key_changes_nothing(keys, monkeypatch):
    monkeypatch.setattr(settings, "solace_keys_secret", "solace/api-keys")
    monkeypatch.setattr(settings, "anthropic_api_key", "from-env")
    assert config.hydrate_from_secrets_manager(
        client=_StubSecrets(json.dumps({"ANTHROPIC_API_KEY": "  ", "OTHER": "x"}))) == []
    assert settings.anthropic_api_key == "from-env"


def test_secret_is_read_once(keys, monkeypatch):
    monkeypatch.setattr(settings, "solace_keys_secret", "solace/api-keys")
    stub = _StubSecrets(json.dumps({"ANTHROPIC_API_KEY": FAKE_KEY}))
    config.hydrate_from_secrets_manager(client=stub)
    config.hydrate_from_secrets_manager(client=stub)
    assert stub.calls == ["solace/api-keys"]


def test_read_failure_leaves_ai_off_and_logs_no_secret(keys, monkeypatch, caplog):
    monkeypatch.setattr(settings, "solace_keys_secret", "solace/api-keys")
    err = RuntimeError("denied")
    err.response = {"Error": {"Code": "AccessDeniedException"}}  # type: ignore[attr-defined]
    with caplog.at_level(logging.WARNING):
        assert config.hydrate_from_secrets_manager(client=_StubSecrets(error=err)) == []
    assert settings.anthropic_api_key == ""
    assert "AccessDeniedException" in " ".join(r.getMessage() for r in caplog.records)


def test_default_client_uses_the_env_region_or_the_arn_region(keys, monkeypatch):
    import boto3  # noqa: PLC0415

    regions: list[str] = []
    stub = _StubSecrets(json.dumps({"ANTHROPIC_API_KEY": FAKE_KEY}))

    def _client(service, region_name=None, **_kw):
        assert service == "secretsmanager"
        regions.append(region_name)
        return stub

    monkeypatch.setattr(boto3, "client", _client)
    monkeypatch.setattr(settings, "solace_keys_secret", "solace/api-keys")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    config.hydrate_from_secrets_manager(force=True)
    monkeypatch.setattr(settings, "solace_keys_secret",
                        "arn:aws:secretsmanager:eu-west-1:123456789012:secret:solace/api-keys-AbCdEf")
    config.hydrate_from_secrets_manager(force=True)
    assert regions == ["us-west-2", "eu-west-1"]
    assert settings.anthropic_api_key == FAKE_KEY


# ---- app-level checks -------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    saved = (settings.solace_mode, settings.solace_seed_demo, settings.solace_warm_model)
    settings.solace_mode, settings.solace_seed_demo, settings.solace_warm_model = "local", False, False
    with TestClient(main.app) as c:
        yield c
    settings.solace_mode, settings.solace_seed_demo, settings.solace_warm_model = saved


def test_malformed_body_gets_one_plain_sentence(client):
    r = client.post("/api/demo/auth/login", json=["not", "an", "object"])
    assert r.status_code == 422
    assert r.json() == {"detail": main.VALIDATION_MESSAGE}
    r = client.post("/api/demo/auth/login", json={"wrong_field": 1})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


_INDEX = """<!doctype html><html><head>
    <meta property="og:type" content="website" />
    <meta property="og:image" content="/og.png" />
    <meta name="twitter:image" content="/og.png" />
</head><body><div id="root"></div></body></html>"""


@pytest.fixture
def dist(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(_INDEX, encoding="utf-8")
    monkeypatch.setattr(settings, "solace_static_dir", str(tmp_path))
    main._index_cache.clear()
    yield tmp_path
    main._index_cache.clear()


def test_index_unchanged_without_public_url(client, dist, monkeypatch):
    monkeypatch.setattr(settings, "solace_public_url", "")
    body = client.get("/").text
    assert 'property="og:image" content="/og.png"' in body and "og:url" not in body


def test_public_url_makes_share_links_absolute(client, dist, monkeypatch):
    monkeypatch.setattr(settings, "solace_public_url", "https://solace.example.org/")
    for path in ("/", "/demo/clinician", "/index.html"):
        body = client.get(path).text
        assert 'property="og:image" content="https://solace.example.org/og.png"' in body, path
        assert 'name="twitter:image" content="https://solace.example.org/og.png"' in body, path
        assert body.count('<meta property="og:url" content="https://solace.example.org/" />') == 1, path


def test_bad_public_url_is_ignored(client, dist, monkeypatch):
    monkeypatch.setattr(settings, "solace_public_url", 'javascript:alert(1)"')
    body = client.get("/").text
    assert 'content="/og.png"' in body and "javascript" not in body


def _record(**over) -> str:
    pid = f"h-{uuid.uuid4().hex[:10]}"
    storage.put_patient({
        "patient_id": pid, "hospital_id": "demo", "name": "Test", "language": "es",
        "transcript": "Me duele el pecho", "status": "waiting", "created_at": "2026-10-18T10:00:00Z",
        "esi_level": 2, "esi_label": "Emergent", "patient_explanation": "Pronto le atenderan.",
        **over,
    })
    return pid


def test_public_patient_returns_the_explanation_key(client):
    pid = _record(explanation_key="needs_reading", explanation_language="es")
    body = client.get(f"/api/demo/public-patients/{pid}").json()
    assert body["explanation_key"] == "needs_reading" and body["explanation_language"] == "es"


def test_detail_uses_the_stored_model_pick_and_rule_fields(client):
    login = client.post("/api/demo/auth/login", json={"clinician_name": "Dr. Chen", "pin": "224466"})
    assert login.status_code == 200, login.text
    auth = {"Authorization": f"Bearer {login.json()['token']}"}
    # The top probability says ESI 3, but the model's tuned pick (stored) was ESI 4.
    pid = _record(
        probabilities=json.dumps([0.0, 0.1, 0.5, 0.4, 0.0]), model_esi_level=4,
        triage_shortcut_reason="rule.esi2.chest_pain", triage_source="rule:rule.esi2.chest_pain",
        triage_rule_name="Chest pain or pressure", safety_floor_reasons=json.dumps(["Chest pain or pressure"]),
        transcript_english="My chest hurts", needs_reading=False,
    )
    body = client.get(f"/api/demo/patients/{pid}", headers=auth).json()
    assert body["checkin_model_esi_level"] == 4
    assert body["checkin_set_by_rules"] is True and body["esi_confidence"] is None
    assert body["checkin_rule_name"] == "Chest pain or pressure"
    assert body["triage_rule_name"] == "Chest pain or pressure"
    assert body["safety_floor_reasons"] == ["Chest pain or pressure"]
    assert body["transcript_english"] == "My chest hurts" and body["needs_reading"] is False

    # An older record with no stored pick or name falls back to the probabilities and the rule id.
    old = _record(probabilities=json.dumps([0.0, 0.1, 0.5, 0.4, 0.0]),
                  triage_shortcut_reason="rule.esi2.breathing")
    body = client.get(f"/api/demo/patients/{old}", headers=auth).json()
    assert body["checkin_model_esi_level"] == 3
    assert body["triage_rule_name"] == "Cannot breathe or very hard to breathe"
    assert body["safety_floor_reasons"] == [] and body["needs_reading"] is False
