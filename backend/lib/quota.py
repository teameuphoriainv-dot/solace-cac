"""Per-visitor rate limits.

Each visitor gets an "identity": a keyed hash of their IP address and browser
(User-Agent), so the raw values are never stored. Every limited action (start a
check-in, upload audio, call the AI, ...) adds to an hourly counter for that
identity, and a request that goes over the limit gets a 429 with a plain message.

Counters live in memory locally (lib/local_table.py) and in DynamoDB in aws mode.

The IP address is the one the trusted proxy saw (client_ip below): on the hosted demo
the AWS proxy appends the real client address as the LAST X-Forwarded-For entry, so
only that entry is trusted. Any earlier entry was sent by the client and is ignored.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException

from lib import audit as _audit
from lib import local_table
from lib.config import settings

log = logging.getLogger(__name__)

TABLE = "solace-quotas"
BUCKET_SECONDS = 3600  # 1-hour buckets
TTL_GRACE = 300        # keep buckets 5 min after window closes for audit trail


@dataclass(frozen=True)
class Limit:
    action: str         # e.g. "intake.start", "intake.submit", "audio.seconds"
    per_hour: int       # units (req-count OR cost-units) allowed in a rolling hour


# Many real patients can share one hospital network, so ceilings are generous.
# They stop runaway loops and scripted abuse without tripping on retries.
LIMITS: dict[str, Limit] = {
    "intake.start":      Limit("intake.start", per_hour=2000),
    "intake.submit":     Limit("intake.submit", per_hour=500),
    "transcribe":        Limit("transcribe", per_hour=2000),
    "scan_insurance":    Limit("scan_insurance", per_hour=500),
    "audio.seconds":     Limit("audio.seconds", per_hour=120000),
    "pain_flag":         Limit("pain_flag", per_hour=30),
    # Sign-in attempts from one device. The per-account lockout in jwt_auth is
    # the main brute-force guard; this caps sweeps across many accounts.
    "auth.login":        Limit("auth.login", per_hour=60),
    # identity/lookup can reveal whether a record exists, so it stays tight.
    "identity.lookup":   Limit("identity.lookup", per_hour=120),
    # Claude calls made for one visitor. Keeps one visitor from spending the whole
    # daily AI budget (lib/spend.py). Over the limit, features use their no-AI version.
    "ai.call":           Limit("ai.call", per_hour=settings.ai_calls_per_visitor_hour),
    # Patient self-serve "text me my care instructions" (routers/sms.py).
    "sms.self_serve":    Limit("sms.self_serve", per_hour=10),
}

# Per-upload absolute caps (checked before charging the hourly quota)
MAX_AUDIO_SECONDS = 300  # 5 minutes per upload covers even a long description


def _limit(action: str) -> Limit | None:
    # Read live so the setting can change without a restart (and in tests).
    if action == "ai.call":
        return Limit("ai.call", per_hour=int(settings.ai_calls_per_visitor_hour))
    # New private demo hospitals per client are limited in lib/sandbox.py, over the
    # last 60 minutes rather than these clock-hour buckets.
    return LIMITS.get(action)


def _table():
    if settings.solace_mode != "aws":
        return local_table.get(TABLE, key=("bucket_key",))
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(TABLE)


# ---- who is asking ---------------------------------------------------------------------
# The client address of the request being handled, resolved once by the middleware in
# main.py from the socket peer and X-Forwarded-For (see client_ip).
_request_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_ip", default=None)


def trusted_proxy_hops() -> int:
    try:
        return max(0, int(settings.solace_trusted_proxy_hops))
    except (TypeError, ValueError):
        return 1


def _forwarded_entries(forwarded_for: str | None) -> list[str]:
    return [e.strip() for e in (forwarded_for or "").split(",") if e.strip()][:64]


def client_ip(forwarded_for: str | None, peer: str | None) -> str:
    """The client address to key limits on.

    With N trusted proxies (SOLACE_TRUSTED_PROXY_HOPS, default 1) the address is the
    Nth X-Forwarded-For entry from the end: each proxy appends the address it saw, so
    those last N entries are the only ones the client cannot write. With 0, or with no
    header, it is the connection's own address.
    """
    hops = trusted_proxy_hops()
    entries = _forwarded_entries(forwarded_for)
    if hops == 0 or not entries:
        return (peer or "unknown").strip()[:64] or "unknown"
    return (entries[-hops] if len(entries) >= hops else entries[0])[:64]


def set_request_ip(ip: str | None) -> contextvars.Token:
    return _request_ip.set(ip)


def reset_request_ip(token: contextvars.Token) -> None:
    _request_ip.reset(token)


def current_request_ip() -> str | None:
    return _request_ip.get()


def identity_of(source_ip: str | None, user_agent: str | None) -> str:
    """Stable 24-char identity hash from IP + UA. Reuses the clinician-auth HMAC key.

    Inside a request the IP is always the one the middleware resolved, whatever the
    caller passes (callers hand in the raw X-Forwarded-For header). Outside a request
    `source_ip` is read like an X-Forwarded-For value with no socket peer known.
    """
    from lib.intake_nonce import _hmac_key  # noqa: PLC0415 (shared salt)

    ip = _request_ip.get()
    if not ip:
        entries = _forwarded_entries(source_ip)
        # No socket peer is known here, so with 0 hops the last entry stands in for it.
        hops = max(1, trusted_proxy_hops())
        ip = (entries[-hops] if len(entries) >= hops else entries[0])[:64] if entries else "unknown"
    ua = (user_agent or "unknown").strip()[:256]
    combined = f"{ip}|{ua}".encode()
    return hmac.new(_hmac_key(), combined, hashlib.sha256).hexdigest()[:24]


def client_key() -> str:
    """Identity of the current client address alone (no browser), for limits a visitor
    must not get around by changing their User-Agent."""
    return identity_of(None, "#client-address")


def _bucket_key(identity: str, action: str, now: int) -> str:
    bucket_start = (now // BUCKET_SECONDS) * BUCKET_SECONDS
    return f"{identity}#{action}#{bucket_start}"


def _add(identity: str, action: str, units: int, now: int) -> int | None:
    """Add units to this hour's counter. Returns the new count, or None if the store failed."""
    bucket_end = ((now // BUCKET_SECONDS) + 1) * BUCKET_SECONDS
    try:
        resp = _table().update_item(
            Key={"bucket_key": _bucket_key(identity, action, now)},
            UpdateExpression="ADD #c :u SET #i = if_not_exists(#i, :i), #a = :a, #ttl = :ttl",
            ExpressionAttributeNames={"#c": "count", "#i": "identity", "#a": "action", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":u": units,
                ":i": identity,
                ":a": action,
                ":ttl": bucket_end + TTL_GRACE,
            },
            ReturnValues="UPDATED_NEW",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("quota update failed, failing open: %s", e)
        return None  # fail open so a storage blip never blocks a real patient
    return int(resp["Attributes"]["count"])


def used(identity: str, action: str) -> int:
    """How many units this identity has used for `action` in the current hour."""
    try:
        item = _table().get_item(Key={"bucket_key": _bucket_key(identity, action, int(time.time()))}).get("Item")
    except Exception as e:  # noqa: BLE001
        log.warning("quota read failed: %s", e)
        return 0
    return int((item or {}).get("count", 0) or 0)


def remaining(identity: str, action: str) -> int:
    limit = _limit(action)
    if limit is None:
        return 1 << 30
    return max(0, limit.per_hour - used(identity, action))


def try_consume(identity: str, action: str, *, units: int = 1) -> bool:
    """Like check_and_consume, but returns False instead of raising when over the limit."""
    limit = _limit(action)
    if limit is None:
        return True
    count = _add(identity, action, units, int(time.time()))
    return count is None or count <= limit.per_hour


def _wait_message(wait_seconds: int) -> str:
    minutes = max(1, round(wait_seconds / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return f"Too many requests from this device. Please wait about {minutes} {unit} and try again."


def check_and_consume(
    identity: str,
    action: str,
    *,
    units: int = 1,
    source_ip: str | None = None,
) -> None:
    """Atomically add `units` to the identity's hourly counter for `action`.

    Raises 429 with a plain message and a Retry-After header when this push goes over
    the hourly limit. Cost tracking (audio seconds) passes `units > 1`.
    """
    limit = _limit(action)
    if limit is None:
        return  # action is not limited

    now = int(time.time())
    new_count = _add(identity, action, units, now)
    if new_count is None or new_count <= limit.per_hour:
        return

    _audit.record(
        clinician_id=None, clinician_name=None,
        action=f"abuse.quota_exceeded.{action}",
        source_ip=source_ip, status_code=429,
        extra={
            "identity": identity,
            "current": new_count,
            "limit_per_hour": limit.per_hour,
            "units_added": units,
        },
    )
    wait_seconds = ((now // BUCKET_SECONDS) + 1) * BUCKET_SECONDS - now
    raise HTTPException(
        status_code=429,
        detail=_wait_message(wait_seconds),
        headers={"Retry-After": str(wait_seconds)},
    )


def check_audio_duration(
    seconds: float,
    identity: str,
    *,
    source_ip: str | None = None,
) -> None:
    """Enforce the per-upload cap and the per-identity hourly audio budget."""
    if seconds > MAX_AUDIO_SECONDS:
        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.audio_too_long",
            source_ip=source_ip, status_code=413,
            extra={
                "duration_seconds": round(seconds, 2),
                "cap_seconds": MAX_AUDIO_SECONDS,
                "identity": identity,
            },
        )
        raise HTTPException(
            status_code=413,
            detail=f"That recording is too long. Please keep it under {MAX_AUDIO_SECONDS // 60} minutes.",
        )
    check_and_consume(identity, "audio.seconds", units=int(seconds) or 1, source_ip=source_ip)
