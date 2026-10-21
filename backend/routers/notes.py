"""Clinician notes, and publishing a plain-language summary to the patient's phone.

The summary is always built from the clinician's own note: with an AI key Claude
rewrites it in plain words; without one, or when that call fails, the note is sent
word for word with the standard safety wording
(services/patient_education.template_summary). The AI
rewrite is checked before it is stored for the patient, and a check-in whose words
matched the prompt-injection filter never goes to the AI at all.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict

from db import storage
from lib.auth import audit, require_clinician
from services import patient_education

log = logging.getLogger(__name__)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any) -> str:
    """Request text, tolerating odd types so the answer is always a plain message."""
    return "" if value is None or isinstance(value, (dict, list)) else str(value)


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: Any = ""
    author: Any = "Clinician"


@router.post("/patients/{patient_id}/notes")
def create_note(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: NoteBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "notes.create", patient_id=patient_id)
    text = _text(body.text if body else "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Write something in the note before saving.")
    if len(text) > 20_000:
        raise HTTPException(status_code=400, detail="That note is too long. Keep it under 20,000 characters.")
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="This patient is no longer on the board.")

    # Prefer the signed-in clinician's name; fall back to the body.
    author = caller.get("name") if caller.get("auth_method") == "jwt" else (_text(body.author).strip()[:200] or "Clinician")
    note = {
        "note_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "text": text.strip(),
        "author": author,
        "clinician_id": caller.get("clinician_id"),
        "created_at": _now_iso(),
    }
    storage.add_note(note)
    return {"success": True, "note": note}


@router.get("/patients/{patient_id}/notes")
def list_notes(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "notes.list", patient_id=patient_id)
    return {"notes": storage.list_notes(patient_id)}


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Either pass a specific note_id or let the server combine every note.
    note_id: Any = None


@router.post("/patients/{patient_id}/publish-summary")
def publish_summary(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: PublishBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "notes.publish_summary", patient_id=patient_id)
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="This patient is no longer on the board.")

    notes = storage.list_notes(patient_id)
    selected_text = ""
    note_id = _text(body.note_id if body else "")[:64]
    if note_id:
        for n in notes:
            if n.get("note_id") == note_id:
                selected_text = str(n.get("text") or "")
                break
    if not selected_text.strip() and notes:
        # Default: combine every note, most recent last.
        selected_text = "\n\n".join(str(n.get("text") or "") for n in notes if n.get("text"))
    if not selected_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Write a note first. The summary sent to the patient is built from your note.",
        )

    result = patient_education.generate_summary(
        clinician_note=selected_text,
        scribe_note=str(patient.get("clinical_scribe_note") or ""),
        transcript=str(patient.get("transcript") or ""),
        patient_language=str(patient.get("language") or "en"),
        comfort_protocol=patient.get("comfort_protocol"),
        allow_ai=not patient.get("content_flag"),
    )
    if result.get("error"):
        log.warning("publish-summary could not build a summary: %s", result["error"])
        raise HTTPException(
            status_code=400,
            detail="Write a note first. The summary sent to the patient is built from your note.",
        )

    message = result.pop("message", None)
    storage.update_patient(
        patient_id,
        {
            "patient_education": json.dumps(result),
            "patient_education_published_at": _now_iso(),
        },
    )
    # ai_available is True only for an AI rewrite. The word-for-word summary (AI off, not
    # allowed for this patient, or the AI call failed: source "ai_failed") says False and
    # always carries a message with the real reason.
    out = {
        "success": True,
        "summary": result,
        "ai_available": bool(result.get("ai_available")),
        "source": result.get("source", ""),
    }
    if message:
        out["message"] = message
    return out
