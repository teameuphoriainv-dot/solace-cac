"""Demo reset: remove every check-in and restore the five example patients.

Works for the shared "demo" hospital and for private demo hospitals (demo-xxxxxx).
A real hospital can never be reset.
"""

from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Path
from db import storage
from lib import sandbox
from lib.auth import audit, require_clinician
from lib.config import settings


log = logging.getLogger(__name__)


router = APIRouter()


def _delete_patient(patient_id: str) -> None:
    if settings.solace_mode != "aws":
        storage.delete_patient(patient_id)
        return
    import boto3  # noqa: PLC0415

    dynamo = boto3.resource("dynamodb", region_name=settings.aws_region)
    dynamo.Table(settings.dynamodb_table_patients).delete_item(Key={"patient_id": patient_id})
    # Prescriptions and notes are keyed on patient_id + a sort key.
    for (table_name, sk_name) in [
        (settings.dynamodb_table_prescriptions, "prescription_id"),
        (settings.dynamodb_table_notes, "note_id"),
    ]:
        t = dynamo.Table(table_name)
        resp = t.query(
            KeyConditionExpression="patient_id = :p",
            ExpressionAttributeValues={":p": patient_id},
        )
        for item in resp.get("Items", []):
            sk_value = item.get(sk_name)
            if sk_value is None:
                continue
            t.delete_item(Key={"patient_id": patient_id, sk_name: sk_value})


@router.post("/admin/reset-demo")
def reset_demo(
    hospital_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    if not (sandbox.is_demo_id(hospital_id) or hospital_id == settings.demo_hospital_id):
        raise HTTPException(status_code=403, detail="Reset is only available in the demo hospital.")
    audit(caller, "admin.reset_demo")
    try:
        rows = storage.list_patients_for_hospital(hospital_id, status="all")
    except Exception as e:  # noqa: BLE001
        log.exception("reset-demo: failed to list patients: %s", e)
        raise HTTPException(status_code=502, detail="Could not load the patient list. Please try again.")

    # Delete everyone, examples included, then re-create the examples. That also
    # clears any vitals, notes, prescriptions or published summaries added to them.
    walk_ins: list[str] = []
    examples: list[str] = []
    failed: list[str] = []
    for p in rows:
        pid = p.get("patient_id")
        if not pid:
            continue
        label = (p.get("name") or "").strip() or pid[:8]
        try:
            _delete_patient(pid)
            (examples if sandbox.is_example(p) else walk_ins).append(label)
        except Exception as e:  # noqa: BLE001
            log.exception("reset-demo: failed for patient %s: %s", pid[:8], e)
            failed.append(label)

    restored = sandbox.seed_examples(hospital_id)
    log.info("reset-demo %s: removed=%d restored=%d failed=%d",
             hospital_id, len(walk_ins) + len(examples), len(restored), len(failed))

    removed_text = f"Removed {len(walk_ins)} check-in{'' if len(walk_ins) == 1 else 's'}"
    if restored:
        message = f"Demo reset. {removed_text} and restored the {len(restored)} example patients."
    else:
        message = f"Demo reset. {removed_text}. The example patients could not be restored."
    return {
        "success": not failed,
        "message": message,
        "restored_patients": len(restored),
        "restored_patient_ids": restored,
        "seeded_patients": restored,
        # Older field names, kept so existing screens keep working.
        "deleted_test_patients": walk_ins,
        "cleared_canonical_patients": examples,
        "failed_patients": failed,
    }
