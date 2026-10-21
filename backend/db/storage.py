"""Storage layer for hospitals, patients, prescriptions and clinician notes.

Local mode (the default, and what the demo runs) keeps everything in memory, so a
restart starts clean. SOLACE_MODE=aws switches the same calls to DynamoDB tables.
Callers never touch the underlying store directly.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

# ---- In-memory stores (local mode) --------------------------------------------------
_patients: dict[str, dict[str, Any]] = {}
_hospitals: dict[str, dict[str, Any]] = {}
_prescriptions: dict[str, list[dict[str, Any]]] = {}  # patient_id -> list
_notes: dict[str, list[dict[str, Any]]] = {}  # patient_id -> list


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _default_ttl() -> int:
    return int(time.time()) + 24 * 3600  # 24h


# ---- DynamoDB float/Decimal conversion ---------------------------------------------
def _to_ddb(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_ddb(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_to_ddb(v) for v in obj]
    return obj


def _from_ddb(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


# ---- Hospital helpers ---------------------------------------------------------------
def seed_demo_hospital() -> None:
    """Ensure the demo hospital exists. Called on app startup."""
    hospital_id = settings.demo_hospital_id
    if get_hospital(hospital_id):
        return
    put_hospital(
        {
            "hospital_id": hospital_id,
            "name": settings.demo_hospital_name,
            "created_at": _now_iso(),
        }
    )
    log.info("Seeded demo hospital '%s'", hospital_id)


def get_hospital(hospital_id: str) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        return _ddb_get_hospital(hospital_id)
    return _hospitals.get(hospital_id)


def put_hospital(hospital: dict[str, Any]) -> None:
    if settings.solace_mode == "aws":
        _ddb_put_hospital(hospital)
        return
    _hospitals[hospital["hospital_id"]] = hospital


def delete_hospital(hospital_id: str) -> int:
    """Remove a hospital with all its patients, prescriptions and notes (local mode only).

    Used when a judge's sandbox hospital expires. Returns how many patients were removed.
    """
    if settings.solace_mode == "aws":
        log.warning("delete_hospital is not supported in aws mode")
        return 0
    ids = [pid for pid, p in _patients.items() if p.get("hospital_id") == hospital_id]
    for pid in ids:
        delete_patient(pid)
    _hospitals.pop(hospital_id, None)
    return len(ids)


# ---- Patient helpers ----------------------------------------------------------------
def put_patient(patient: dict[str, Any]) -> None:
    patient.setdefault("created_at", _now_iso())
    patient.setdefault("ttl", _default_ttl())
    if settings.solace_mode == "aws":
        _ddb_put_patient(patient)
        return
    _patients[patient["patient_id"]] = patient


def get_patient(patient_id: str) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        return _ddb_get_patient(patient_id)
    return _patients.get(patient_id)


def update_patient(patient_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    if settings.solace_mode == "aws":
        return _ddb_update_patient(patient_id, updates)
    existing = _patients.get(patient_id)
    if not existing:
        return None
    existing.update(updates)
    return existing


def delete_patient(patient_id: str) -> bool:
    """Remove one patient and their prescriptions and notes (local mode only)."""
    if settings.solace_mode == "aws":
        log.warning("delete_patient is not supported in aws mode")
        return False
    _prescriptions.pop(patient_id, None)
    _notes.pop(patient_id, None)
    return _patients.pop(patient_id, None) is not None


def current_esi(p: dict[str, Any]) -> int:
    """The score the queue should act on: the bedside re-check when there is one."""
    for key in ("refined_esi_level", "esi_level"):
        try:
            value = int(p.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if 1 <= value <= 5:
            return value
    return 5


def list_patients_for_hospital(hospital_id: str, status: str | None = None) -> list[dict[str, Any]]:
    """Patients for one hospital, most urgent first, then longest waiting."""
    if settings.solace_mode == "aws":
        rows = _ddb_query_patients_by_hospital(hospital_id)
    else:
        rows = [p for p in _patients.values() if p.get("hospital_id") == hospital_id]
    if status and status != "all":
        rows = [p for p in rows if p.get("status") == status]
    rows.sort(key=lambda p: (current_esi(p), p.get("created_at", "")))
    return rows


# ---- DynamoDB implementations (SOLACE_MODE=aws) -------------------------------------
def _boto_table(name: str):  # pragma: no cover - aws mode only
    import boto3

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def invoke_lambda_async(function_name: str, payload: dict[str, Any]) -> None:  # pragma: no cover - aws mode only
    """Fire-and-forget async invocation used by lib.async_invoke in aws mode.

    Errors are logged with the function name only (the payload carries a patient id)
    and re-raised so the caller can fall back to generating inline.
    """
    import boto3  # noqa: PLC0415

    client = boto3.client("lambda", region_name=settings.aws_region)
    client.invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps(payload).encode(),
    )


def _ddb_get_hospital(hospital_id: str) -> dict[str, Any] | None:
    resp = _boto_table(settings.dynamodb_table_hospitals).get_item(Key={"hospital_id": hospital_id})
    item = resp.get("Item")
    return _from_ddb(item) if item else None


def _ddb_put_hospital(hospital: dict[str, Any]) -> None:
    _boto_table(settings.dynamodb_table_hospitals).put_item(Item=_to_ddb(hospital))


def _ddb_get_patient(patient_id: str) -> dict[str, Any] | None:
    resp = _boto_table(settings.dynamodb_table_patients).get_item(Key={"patient_id": patient_id})
    item = resp.get("Item")
    return _from_ddb(item) if item else None


def _ddb_put_patient(patient: dict[str, Any]) -> None:
    _boto_table(settings.dynamodb_table_patients).put_item(Item=_to_ddb(patient))


def _ddb_update_patient(patient_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    # A None value means "clear this attribute". _to_ddb drops None, so SET alone
    # could never remove a field; split into SET for values and REMOVE for the Nones
    # so both modes agree (the pain-flag re-arm depends on clearing acknowledged_*).
    set_items = _to_ddb({k: v for k, v in updates.items() if v is not None})
    remove_keys = [k for k, v in updates.items() if v is None]
    if not set_items and not remove_keys:
        return get_patient(patient_id)

    names: dict[str, str] = {}
    values: dict[str, Any] = {}
    clauses: list[str] = []
    idx = 0
    if set_items:
        assigns = []
        for k, v in set_items.items():
            names[f"#{idx}"] = k
            values[f":{idx}"] = v
            assigns.append(f"#{idx}=:{idx}")
            idx += 1
        clauses.append("SET " + ", ".join(assigns))
    if remove_keys:
        removes = []
        for k in remove_keys:
            names[f"#{idx}"] = k
            removes.append(f"#{idx}")
            idx += 1
        clauses.append("REMOVE " + ", ".join(removes))

    kwargs: dict[str, Any] = {
        "Key": {"patient_id": patient_id},
        "UpdateExpression": " ".join(clauses),
        "ExpressionAttributeNames": names,
        "ReturnValues": "ALL_NEW",
    }
    if values:
        kwargs["ExpressionAttributeValues"] = values
    resp = _boto_table(settings.dynamodb_table_patients).update_item(**kwargs)
    return _from_ddb(resp.get("Attributes"))


def _ddb_query_patients_by_hospital(hospital_id: str) -> list[dict[str, Any]]:
    resp = _boto_table(settings.dynamodb_table_patients).query(
        IndexName="hospital_id-created_at-index",
        KeyConditionExpression="hospital_id = :h",
        ExpressionAttributeValues={":h": hospital_id},
    )
    return [_from_ddb(i) for i in resp.get("Items", [])]


# ---- Prescription helpers -----------------------------------------------------------
def add_prescription(record: dict[str, Any]) -> None:
    record.setdefault("ttl", _default_ttl())
    if settings.solace_mode == "aws":
        _boto_table(settings.dynamodb_table_prescriptions).put_item(Item=_to_ddb(record))
        return
    _prescriptions.setdefault(record["patient_id"], []).append(record)


def list_prescriptions(patient_id: str) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        resp = _boto_table(settings.dynamodb_table_prescriptions).query(
            KeyConditionExpression="patient_id = :p",
            ExpressionAttributeValues={":p": patient_id},
        )
        items = [_from_ddb(i) for i in resp.get("Items", [])]
        items.sort(key=lambda r: r.get("created_at", ""))
        return items
    return list(_prescriptions.get(patient_id, []))


# ---- Clinician note helpers ---------------------------------------------------------
def add_note(record: dict[str, Any]) -> None:
    record.setdefault("ttl", _default_ttl())
    if settings.solace_mode == "aws":
        _boto_table(settings.dynamodb_table_notes).put_item(Item=_to_ddb(record))
        return
    _notes.setdefault(record["patient_id"], []).append(record)


def list_notes(patient_id: str) -> list[dict[str, Any]]:
    if settings.solace_mode == "aws":
        resp = _boto_table(settings.dynamodb_table_notes).query(
            KeyConditionExpression="patient_id = :p",
            ExpressionAttributeValues={":p": patient_id},
        )
        items = [_from_ddb(i) for i in resp.get("Items", [])]
        items.sort(key=lambda r: r.get("created_at", ""))
        return items
    return list(_notes.get(patient_id, []))


# ---- Test helpers -------------------------------------------------------------------
def _reset_for_tests() -> None:
    _patients.clear()
    _hospitals.clear()
    _prescriptions.clear()
    _notes.clear()
