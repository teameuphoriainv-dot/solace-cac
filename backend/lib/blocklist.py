"""Automatic short block for devices that keep misbehaving.

When the same identity (see quota.identity_of) triggers enough abuse events inside a
10-minute window, it goes on a block list for a while. Patient endpoints check the list
before doing any work and answer 429 with a plain message.

Sign-in uses its own identity key (the device hash plus "#auth", see routers/auth.py),
so a few wrong PINs never block a patient check-in from the same laptop.

The block is 5 minutes in local mode (the demo laptop or hosted demo) and 1 hour in
aws mode. Abuse counters share the quota table but are counted separately from it.
"""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException

from lib import audit as _audit
from lib import local_table
from lib.config import settings

log = logging.getLogger(__name__)

BLOCK_TABLE = "solace-blocklist"
ABUSE_WINDOW_SECONDS = 10 * 60   # abuse events are counted in 10-minute windows
ABUSE_THRESHOLD = 5              # events in one window that trigger a block
# Sign-in gets more room than other endpoints: the per-account lockout (jwt_auth)
# already stops guessing one account, so this only catches guessing across accounts.
AUTH_ABUSE_THRESHOLD = 10


def block_seconds() -> int:
    return 60 * 60 if settings.solace_mode == "aws" else 5 * 60


def _tbl(name: str):
    if settings.solace_mode != "aws":
        # The block list is keyed by identity; the abuse counters share the quota table.
        return local_table.get(name, key=("bucket_key",) if name == "solace-quotas" else ("identity",))
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def _active_block(identity: str) -> dict | None:
    try:
        item = _tbl(BLOCK_TABLE).get_item(Key={"identity": identity}, ConsistentRead=True).get("Item")
    except Exception as e:  # noqa: BLE001
        log.warning("blocklist lookup failed: %s", e)
        return None
    if not item or int(item.get("ttl", 0)) < int(time.time()):
        return None
    return item


def is_blocked(identity: str) -> tuple[bool, str | None]:
    """(blocked, reason) for this identity right now."""
    item = _active_block(identity)
    return (True, item.get("reason")) if item else (False, None)


def enforce(identity: str, *, source_ip: str | None = None) -> None:
    """Raise 429 if the identity is on the block list. Call at the top of public endpoints."""
    item = _active_block(identity)
    if not item:
        return
    _audit.record(
        clinician_id=None, clinician_name=None, action="abuse.blocklist_hit",
        source_ip=source_ip, status_code=429,
        extra={"identity": identity, "reason": item.get("reason")},
    )
    wait = max(1, int(item.get("ttl", 0)) - int(time.time()))
    minutes = max(1, round(wait / 60))
    unit = "minute" if minutes == 1 else "minutes"
    raise HTTPException(
        status_code=429,
        detail=f"Too many failed attempts from this device. Please wait about {minutes} {unit} and try again.",
        headers={"Retry-After": str(wait)},
    )


def record_abuse(identity: str, reason: str, *, threshold: int = ABUSE_THRESHOLD) -> None:
    """Tick the abuse counter. When it reaches `threshold`, block the identity."""
    now = int(time.time())
    bucket_start = (now // ABUSE_WINDOW_SECONDS) * ABUSE_WINDOW_SECONDS
    key = f"{identity}#{bucket_start}"
    try:
        resp = _tbl("solace-quotas").update_item(
            Key={"bucket_key": key},
            UpdateExpression="ADD #c :one SET #i = if_not_exists(#i, :i), #a = :a, #ttl = :ttl",
            ExpressionAttributeNames={"#c": "count", "#i": "identity", "#a": "action", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":i": identity,
                ":a": "abuse_counter",
                ":ttl": bucket_start + ABUSE_WINDOW_SECONDS + 300,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(resp["Attributes"]["count"])
    except Exception as e:  # noqa: BLE001
        log.warning("abuse counter update failed: %s", e)
        return

    if count >= threshold:
        try:
            _tbl(BLOCK_TABLE).put_item(Item={
                "identity": identity,
                "reason": reason,
                "count": count,
                "created_at": now,
                "ttl": now + block_seconds(),
            })
            _audit.record(
                clinician_id=None, clinician_name=None, action="abuse.auto_blocked",
                status_code=429,
                extra={"identity": identity, "reason": reason, "count": count},
            )
            log.warning("auto-blocked identity %s for %ds: %d abuse events (%s)",
                        identity, block_seconds(), count, reason)
        except Exception as e:  # noqa: BLE001
            log.warning("block failed for %s: %s", identity, e)
