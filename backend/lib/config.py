"""Settings, read from environment variables and .env files.

Both <repo>/.env and <repo>/backend/.env are read (backend/.env wins when a key is in
both), so a judge can drop a .env in either place. Every key is optional: with none
set, Solace runs fully offline and each AI feature shows its no-AI version.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT / ".env"), str(ROOT / "backend" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        # model_clinical / model_utility intentionally start with "model_";
        # opt out of pydantic's protected-namespace warning for them.
        protected_namespaces=(),
    )

    # "local" keeps everything in memory on this machine (also used by the Docker
    # demo). "aws" is the older cloud setup and needs AWS credentials.
    solace_mode: Literal["local", "aws"] = "local"

    # Optional AI keys. Each one turns on a feature; nothing breaks without them.
    anthropic_api_key: str = ""       # Claude: notes, reasoning, card reading, comfort text
    openai_api_key: str = ""          # server speech-to-text for audio uploads
    elevenlabs_api_key: str = ""      # spoken audio of the patient's guidance
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # Which Claude model each kind of task uses.
    #   model_clinical: clinical drafting (differential, disposition, workup, scribe).
    #   model_utility: structured or short tasks (follow-up questions, card reading).
    # Both default to the newest low-cost Haiku model. Override with MODEL_CLINICAL
    # or MODEL_UTILITY; lib/claude.py adapts the request to the model.
    model_clinical: str = "claude-haiku-5-5"
    model_utility: str = "claude-haiku-5-5"

    # Spend guard for a public demo with a real key (lib/spend.py). Once the day's
    # estimated Claude spend (UTC) reaches the budget, AI features switch to their
    # no-AI versions until midnight UTC. 0 turns AI off. Each visitor (IP + browser)
    # also gets a fixed number of AI calls per hour.
    ai_daily_budget_usd: float = 3.0
    # Counts every Claude call made for a visitor, including the clinician summaries
    # made in the background after a check-in (about 8 calls per check-in).
    ai_calls_per_visitor_hour: int = 120
    # Guards that do not depend on who is asking, so one burst cannot switch AI off
    # for everyone for the rest of the day: at most this share of the daily budget
    # in one clock hour (UTC), and at most this many Claude calls in any 60 seconds
    # (0 turns the per-minute ceiling off). Over either one, features use their
    # no-AI version until the hour or minute is up.
    ai_hourly_budget_fraction: float = 0.35
    ai_calls_per_minute: int = 40

    # How many proxies in front of this server add an X-Forwarded-For entry. The AWS
    # App Runner proxy appends the real client address as the LAST entry, so 1 (the
    # default) trusts only that entry; anything before it was sent by the client and
    # can be made up. 0 ignores the header and uses the connection's own address
    # (right when nothing sits in front of the server).
    solace_trusted_proxy_hops: int = 1

    # Text messages. "none" (default) never sends: the app shows a preview of the
    # text instead. "twilio" or "sns" must be chosen explicitly (services/sms.py).
    sms_provider: str = "none"

    # Demo data. SOLACE_SEED_DEMO=0 skips the five example patients at startup.
    # SOLACE_WARM_MODEL=0 skips loading the bedside model in the background at startup.
    solace_seed_demo: bool = True
    solace_warm_model: bool = True

    # Private demo hospitals (lib/sandbox.py): ids like demo-k3x9q2, made on first use.
    sandbox_idle_minutes: int = 120
    sandbox_max: int = 300
    # One client address may create this many new private hospitals per hour and keep
    # this many alive at once. Past either limit, or when all sandbox_max are in use,
    # the visitor's id is served from the shared "demo" hospital instead (never an error).
    sandbox_creates_per_client_hour: int = 5
    sandbox_live_per_client: int = 10
    # Check-ins in the shared "demo" hospital are removed after this many hours, so a
    # hosted demo does not fill up with old visitors' patients. 0 keeps them.
    demo_walkin_max_hours: float = 6

    # Built frontend to serve from the same origin. Empty means <repo>/frontend/dist
    # when that folder exists (the Docker image builds it there).
    solace_static_dir: str = ""

    # Public address of a hosted demo (e.g. https://abc123.us-east-1.awsapprunner.com).
    # When set, the served index.html gets absolute og:image / twitter:image links and
    # an og:url, which some link-preview scrapers need. Empty leaves the page as built.
    solace_public_url: str = ""

    # Hosted demo only: the id or ARN of an AWS Secrets Manager secret that holds the
    # Anthropic key as JSON, e.g. {"ANTHROPIC_API_KEY": "..."}. It is read once at
    # startup (hydrate_from_secrets_manager). Empty (the default, and the judge's
    # laptop) means Solace never contacts AWS at all.
    solace_keys_secret: str = ""

    # aws mode only
    aws_secret_name: str = "solace/api-keys"
    aws_region: str = "us-east-1"
    dynamodb_table_patients: str = "solace-patients"
    dynamodb_table_hospitals: str = "solace-hospitals"
    dynamodb_table_prescriptions: str = "solace-prescriptions"
    dynamodb_table_notes: str = "solace-notes"
    s3_bucket_media: str = ""

    # Local media (audio, photos): written here, served at /media. The URL is
    # relative so it works from any device that can reach the server.
    local_media_dir: str = str(ROOT / "backend" / "tmp" / "media")
    local_media_base_url: str = "/media"

    # Demo hospital
    demo_hospital_id: str = "demo"
    demo_hospital_name: str = "Demo Medical Center"

    # Sign-in links (lib/accounts.py). Nothing is emailed in this build.
    email_from: str = "Solace Demo <no-reply@example.com>"
    magic_link_ttl_seconds: int = 900  # 15-minute single-use links


@lru_cache(maxsize=1)
def _load() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = _load()


# Keys the hosted demo takes from SOLACE_KEYS_SECRET. Only the Anthropic key: it is
# the only provider behind the daily spend cap (lib/spend.py), so a hosted demo never
# picks up an uncapped speech or voice key by accident.
_HOSTED_SECRET_FIELDS = {"ANTHROPIC_API_KEY": "anthropic_api_key"}

# The older aws mode reads every provider key from settings.aws_secret_name.
_AWS_MODE_SECRET_FIELDS = {
    "OPENAI_API_KEY": "openai_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "ELEVENLABS_API_KEY": "elevenlabs_api_key",
    "ELEVENLABS_VOICE_ID": "elevenlabs_voice_id",
}

_hydrated = False


def _secret_region(secret_id: str) -> str:
    """The region to read the secret from: the ARN's own region, else the env's."""
    parts = secret_id.split(":")
    if secret_id.startswith("arn:") and len(parts) > 3 and parts[3]:
        return parts[3]
    return (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
            or settings.aws_region or "us-east-1")


def _secret_payload(raw: str) -> dict:
    """The secret as a dict. A bare key (not JSON) is read as the Anthropic key."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        raw = (raw or "").strip()
        return {"ANTHROPIC_API_KEY": raw} if raw.startswith("sk-ant-") else {}
    return payload if isinstance(payload, dict) else {}


def hydrate_from_secrets_manager(*, client: Any = None, force: bool = False) -> list[str]:
    """Copy API keys from AWS Secrets Manager into settings, once per process.

    - SOLACE_KEYS_SECRET set (the hosted demo, any mode): read that secret and set
      the Anthropic key from ANTHROPIC_API_KEY (or anthropic_api_key).
    - Otherwise, aws mode: read settings.aws_secret_name for every provider key.
    - Otherwise (local, the judge's laptop): return at once. boto3 is not even
      imported, so no AWS call can happen.

    Only keys present in the secret with a non-empty value are set. Values are never
    logged. A failed read is logged by error type and the app runs without AI.
    Returns the names of the settings that were filled.
    """
    global _hydrated
    secret_id = (settings.solace_keys_secret or "").strip()
    if secret_id:
        fields = _HOSTED_SECRET_FIELDS
    elif settings.solace_mode == "aws":
        secret_id, fields = settings.aws_secret_name, _AWS_MODE_SECRET_FIELDS
    else:
        return []
    if _hydrated and not force:
        return []
    _hydrated = True

    log = logging.getLogger(__name__)
    region = _secret_region(secret_id)
    try:
        if client is None:
            import boto3  # noqa: PLC0415 (only on the hosted / aws path)

            client = boto3.client("secretsmanager", region_name=region)
        resp = client.get_secret_value(SecretId=secret_id)
        payload = _secret_payload(resp.get("SecretString") or "")
    except Exception as e:  # noqa: BLE001 (a missing key means no-AI mode, not a crash)
        err = getattr(e, "response", None)
        code = err.get("Error", {}).get("Code") if isinstance(err, dict) else None
        log.warning("Secrets Manager: could not read the keys secret (%s); AI features stay off",
                    code or type(e).__name__)
        return []

    filled: list[str] = []
    for secret_key, attr in fields.items():
        value = payload.get(secret_key) or payload.get(secret_key.lower())
        if isinstance(value, str) and value.strip():
            object.__setattr__(settings, attr, value.strip())
            filled.append(attr)
    log.info("Secrets Manager: filled %d setting(s) from the keys secret in %s", len(filled), region)
    return filled
