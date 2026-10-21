"""POST /api/{hospital_id}/pain-flag: the patient's "I feel worse" button.

Lifecycle:
  - Patient taps "I feel worse" -> POST /pain-flag (anonymous, no auth).
    Sets pain_flagged=True + pain_flagged_at, clears any prior acknowledgement.
  - Clinician dashboard polls /patients, detects an un-acknowledged flag, raises
    an audible alarm.
  - Clinician taps Acknowledge -> POST /pain-flag/acknowledge (clinician auth).
    Stamps pain_flag_acknowledged_at + pain_flag_acknowledged_by; the alarm
    silences across every connected dashboard.

Guards: 30 presses an hour per device (so the alarm cannot be flooded), the
device block list is checked first, and both the press and the acknowledgement
are written to the audit log.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from db import storage
from lib import audit as _audit
from lib import blocklist, quota
from lib.auth import audit, require_clinician

router = APIRouter()


class PainFlagBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., max_length=64)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@router.post("/pain-flag")
def flag(
    hospital_id: str = Path(...),
    body: PainFlagBody | None = None,
    request: Request = None,
) -> dict:
    # The block list check comes first, before any other work.
    source_ip = None
    user_agent = None
    if request:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "pain_flag", source_ip=source_ip)

    if body is None:
        raise HTTPException(status_code=400, detail="Missing patient id.")

    patient = storage.get_patient(body.patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="We could not find that check-in.")
    now = _now_iso()
    # Re-pressing the button should re-arm the alarm even if a clinician already
    # acknowledged a previous escalation -- this is a NEW worsening event.
    storage.update_patient(
        body.patient_id,
        {
            "pain_flagged": True,
            "pain_flagged_at": now,
            "pain_flag_acknowledged_at": None,
            "pain_flag_acknowledged_by": None,
        },
    )
    # Audit log the patient action
    _audit.record(
        clinician_id=None,
        clinician_name=None,
        action="pain_flag.triggered",
        patient_id=body.patient_id,
        source_ip=source_ip,
        status_code=200,
    )

    return {"success": True, "pain_flagged_at": now}


class AcknowledgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(..., max_length=64)


@router.post("/pain-flag/acknowledge")
def acknowledge(
    hospital_id: str = Path(...),
    body: AcknowledgeBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    if body is None:
        raise HTTPException(status_code=400, detail="Missing patient id.")
    patient = storage.get_patient(body.patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="Patient not found.")
    if not patient.get("pain_flagged"):
        # No-op rather than 400 -- concurrent clinicians both ack'ing a flag is a
        # normal race and shouldn't surface a scary error in either UI.
        return {"success": True, "already_clear": True}
    now = _now_iso()
    storage.update_patient(
        body.patient_id,
        {
            "pain_flag_acknowledged_at": now,
            "pain_flag_acknowledged_by": caller.get("name") or caller.get("clinician_id") or "clinician",
        },
    )
    audit(caller, "pain_flag.acknowledge", patient_id=body.patient_id)
    return {"success": True, "pain_flag_acknowledged_at": now}
