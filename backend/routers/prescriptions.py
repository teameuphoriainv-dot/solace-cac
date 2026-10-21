"""Clinician-facing prescription endpoints.

- POST /patients/{id}/prescriptions          the clinician writes one; it is always
                                             checked for allergies and interactions
- POST /patients/{id}/prescriptions/suggest  AI ideas for the clinician to review
                                             (needs an AI key), each one checked too.
                                             Never for a patient whose check-in words
                                             matched the prompt-injection filter.
- GET  /patients/{id}/prescriptions          list for a patient

The checker (services/drug_interactions) is a fixed table and needs no key.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict

from db import storage
from lib import claude
from lib.auth import audit, require_clinician
from routers.clinical_ai import patient_words_flagged
from services import drug_interactions, prescription

router = APIRouter()

_NOT_FOUND = "This patient is no longer on the board."
_FLAGGED = (
    "AI prescription ideas are off for this patient. Some of their words matched the filter "
    "for instructions aimed at the AI, so nothing from this check-in is sent to the AI. "
    "Prescriptions you type are still checked for allergies and drug interactions."
)
_STILL_CHECKED = "Prescriptions you type are still checked for allergies and drug interactions."

# Field length caps. Longer values are trimmed rather than rejected.
_LIMITS = {
    "drug": 200, "dose": 100, "route": 100, "frequency": 100, "duration": 100,
    "indication": 500, "cautions": 1_000, "prescribed_by": 200, "source": 40,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class PrescriptionBody(BaseModel):
    # Accepted AI suggestions are posted back as-is, so extra keys (safety,
    # review_note) are ignored rather than rejected. Fields are loose (a dose
    # typed as a bare number still saves) and turned into text below.
    model_config = ConfigDict(extra="ignore")

    drug: Any = ""
    dose: Any = ""
    route: Any = ""
    frequency: Any = ""
    duration: Any = ""
    indication: Any = ""
    cautions: Any = ""
    prescribed_by: Any = "Clinician"
    source: Any = "manual"  # "manual" | "ai_suggested_accepted"


def _patient_or_404(hospital_id: str, patient_id: str) -> dict:
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return patient


def _other_drugs(patient_id: str) -> list[str]:
    return [str(p.get("drug") or "") for p in storage.list_prescriptions(patient_id) if p.get("drug")]


@router.post("/patients/{patient_id}/prescriptions")
def create_prescription(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: PrescriptionBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "prescriptions.create", patient_id=patient_id)
    fields = {
        k: ("" if v is None or isinstance(v, (dict, list)) else str(v)).strip()[: _LIMITS[k]]
        for k, v in (body.model_dump() if body else {}).items()
        if k in _LIMITS
    }
    if not fields.get("drug"):
        raise HTTPException(status_code=400, detail="Type the name of the medicine first.")
    patient = _patient_or_404(hospital_id, patient_id)

    safety = drug_interactions.check_prescription(
        fields["drug"],
        medical_info=_maybe_json(patient.get("medical_info")),
        other_drugs=_other_drugs(patient_id),
        complaint=str(patient.get("transcript") or ""),
    )
    record = {
        "prescription_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "prescribed_at": _now_iso(),
        "clinician_id": caller.get("clinician_id"),
        **fields,
        "prescribed_by": fields.get("prescribed_by") or "Clinician",
        "source": fields.get("source") or "manual",
        "safety_highest": safety["summary"]["highest_severity"],
        "safety_alerts": [a["message"] for a in safety["alerts"]],
    }
    if caller.get("auth_method") == "jwt" and caller.get("name"):
        record["prescribed_by"] = caller["name"]
    storage.add_prescription(record)
    return {"success": True, "prescription": record, "safety": safety}


@router.get("/patients/{patient_id}/prescriptions")
def list_prescriptions(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "prescriptions.list", patient_id=patient_id)
    _patient_or_404(hospital_id, patient_id)
    return {"prescriptions": storage.list_prescriptions(patient_id)}


@router.post("/patients/{patient_id}/prescriptions/suggest")
def suggest_prescriptions(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "prescriptions.suggest", patient_id=patient_id)
    patient = _patient_or_404(hospital_id, patient_id)

    if not claude.available():
        off = ("AI suggestions are off in this demo." if claude.off_kind() == "no_key"
               else claude.off_reason())
        return {"suggestions": [], "ai_available": False, "message": f"{off} {_STILL_CHECKED}"}

    transcript = str(patient.get("transcript") or "")
    try:
        esi = int(patient.get("esi_level") or 3)
    except (TypeError, ValueError):
        esi = 3
    medical_info = _maybe_json(patient.get("medical_info"))
    followup_qa = _maybe_json(patient.get("followup_qa"))
    photo_analysis = _maybe_json(patient.get("photo_analysis"))

    answers = [qa.get("answer") for qa in followup_qa if isinstance(qa, dict)] if isinstance(followup_qa, list) else []
    if patient_words_flagged(patient, transcript, answers, medical_info, label="patient_text.prescriptions"):
        return {"suggestions": [], "ai_available": False, "content_flag": True, "message": _FLAGGED}

    suggestions, source = prescription.suggest_with_source(
        transcript, esi,
        medical_info if isinstance(medical_info, dict) else {},
        followup_qa if isinstance(followup_qa, list) else [],
        photo_analysis if isinstance(photo_analysis, dict) else {},
        other_drugs=_other_drugs(patient_id),
    )
    if source != "claude":  # the call failed (or AI went off mid-request): nothing was suggested
        return {"suggestions": [], "ai_available": False, "source": "ai_failed",
                "message": f"The AI did not answer this time, so there are no ideas to show. "
                           f"Try again in a few minutes. {_STILL_CHECKED}"}
    out: dict[str, Any] = {
        "suggestions": suggestions,
        "ai_available": True,
        "source": "claude",
        "label": prescription.REVIEW_LABEL,
    }
    if not suggestions:
        out["message"] = ("The AI did not suggest a prescription for this visit. You decide "
                          f"what is needed. {_STILL_CHECKED}")
    return out


def _maybe_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
