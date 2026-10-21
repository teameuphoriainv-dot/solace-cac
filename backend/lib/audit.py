"""Fire-and-forget audit log writer: records who accessed what.

Writes to the `solace-audit-log` table without blocking the request (a local
table unless SOLACE_MODE is "aws"). Rows expire from the table after 90 days.
In "aws" mode each record is also copied to S3 as one JSON object; how long
those objects are kept is set by the bucket, not by this code.

Events named "abuse.*" also feed the blocklist counter (lib/blocklist.py),
except the ones listed in `_SKIP` and a patient's own check-in words that
matched the prompt-injection filter (see `_counts_toward_blocklist`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from lib import local_table
from lib.config import settings

log = logging.getLogger(__name__)

AUDIT_TABLE = "solace-audit-log"
AUDIT_TTL_SECONDS = 90 * 24 * 3600  # rows expire from the table after 90 days

# S3 copy: one JSON object per record under a per-day prefix (aws mode only)
_AUDIT_S3_PREFIX = "audit-archive"


def _table():
    if settings.solace_mode != "aws":
        return local_table.get(AUDIT_TABLE, key=("clinician_id", "ts_id"))
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(AUDIT_TABLE)


def _write_sync(item: dict[str, Any]) -> None:
    try:
        _table().put_item(Item=item)
    except Exception as e:  # noqa: BLE001
        log.warning("audit write to DDB failed: %s", e)

    # Copy to S3 (aws mode only)
    _archive_to_s3(item)


def _archive_to_s3(item: dict[str, Any]) -> None:
    """Append audit record as a JSONL line to a daily S3 object.

    Uses S3 PutObject with a unique key per record (append-only pattern).
    Objects are CMK-encrypted at rest via the bucket's default encryption.
    """
    if settings.solace_mode != "aws" or not settings.s3_bucket_media:
        return  # Skip in local mode

    try:
        import boto3  # noqa: PLC0415

        s3 = boto3.client("s3", region_name=settings.aws_region)
        today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        record_id = item.get("ts_id", uuid.uuid4().hex[:12])
        key = f"{_AUDIT_S3_PREFIX}/{today}/{record_id}.json"

        # Serialize — strip None values, convert non-serializable types
        clean = {k: v for k, v in item.items() if v is not None and k != "ttl"}
        s3.put_object(
            Bucket=settings.s3_bucket_media,
            Key=key,
            Body=json.dumps(clean, default=str).encode(),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",
        )
    except Exception as e:  # noqa: BLE001
        # S3 archive failure must not block the request or lose the DDB record
        log.warning("audit S3 archive failed: %s", e)


# Labels (content_guard.scan `label`) for a patient's own check-in words, including
# when a clinician screen sends them back for AI help. A real emergency can read like
# an instruction to the AI ("I forget the instructions for my inhaler and now I can't
# breathe"), so a match there turns AI off for that patient but never counts as abuse.
# Text a clinician writes or dictates (labels "scribe", "ambient_scribe") still counts.
PATIENT_TEXT_LABELS = frozenset({"intake", "transcribe", "patient_text"})

_SKIP = (
    "abuse.blocklist_hit", "abuse.auto_blocked", "abuse.content_sanitized",
    "abuse.intake_nonce_ua_mismatch",
)


def is_patient_text_label(label: object) -> bool:
    """True for a content-filter label that names a patient's own words."""
    return str(label or "").strip().lower().split(".", 1)[0] in PATIENT_TEXT_LABELS


def _counts_toward_blocklist(action: str, extra: dict[str, Any] | None) -> bool:
    if not action.startswith("abuse."):
        return False
    # `abuse.quota_exceeded.*` are rate-limit hits, not malice; counting them toward a
    # 1h auto-block double-punishes real users who reload the page a lot.
    if action in _SKIP or action.startswith("abuse.quota_exceeded"):
        return False
    if action == "abuse.content_prompt_injection" and is_patient_text_label((extra or {}).get("label")):
        return False
    return True


def record(
    *,
    clinician_id: str | None,
    clinician_name: str | None,
    action: str,
    patient_id: str | None = None,
    source_ip: str | None = None,
    request_id: str | None = None,
    status_code: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Enqueue an audit record. Non-blocking in async contexts, synchronous fallback."""
    now = datetime.now(timezone.utc)
    ts_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    ts_unix = int(now.timestamp() * 1000)
    audit_uuid = uuid.uuid4().hex[:12]
    item = {
        "clinician_id": clinician_id or "anonymous",
        "ts_id": f"{ts_unix}#{audit_uuid}",
        "clinician_name": clinician_name,
        "action": action,
        "patient_id": patient_id or "_",
        "ts": ts_iso,
        "source_ip": source_ip,
        "request_id": request_id,
        "status_code": status_code,
        "ttl": int(time.time()) + AUDIT_TTL_SECONDS,
    }
    if extra:
        item["extra"] = extra
    item = {k: v for k, v in item.items() if v is not None}

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _write_sync, item)
    except RuntimeError:
        _write_sync(item)

    # Automated response: feed abuse events into the blocklist counter.
    if _counts_toward_blocklist(action, extra):
        identity = None
        if extra:
            identity = extra.get("identity")
        if not identity and source_ip:
            # Approximate identity from IP when caller didn't pass one
            from lib.quota import identity_of  # noqa: PLC0415

            identity = identity_of(source_ip, None)
        if identity:
            from lib import blocklist  # noqa: PLC0415

            try:
                blocklist.record_abuse(identity, reason=action)
            except Exception as e:  # noqa: BLE001
                log.warning("blocklist increment failed: %s", e)
