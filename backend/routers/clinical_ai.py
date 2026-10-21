"""Clinician-side reasoning endpoints: possible diagnoses (ddx v2), the two
early-warning scores, and the ambient scribe sessions.

Every endpoint requires clinician sign-in. The early-warning scores are fixed
formulas and never call an AI. Reasoning and the scribe use Claude when a key is
configured and say plainly what is off when it is not.

A patient whose check-in words matched the prompt-injection filter (the record's
content_flag) never reaches the AI from here either: reasoning screens the words it
is sent and takes the no-AI path for a flagged patient or a match.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict

from db import storage
from lib import claude, content_guard
from lib.auth import audit, require_clinician
from services import ambient_scribe, ddx_v2, differential, early_warning


log = logging.getLogger(__name__)


router = APIRouter()


# Request fields are typed loosely (Any) and coerced here, so an odd value from
# the screen gets a plain-English answer instead of a raw validation error.
def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value)


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return value is True or (isinstance(value, (int, float)) and value == 1)


def _obj(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


# ---- Patient words the content filter flagged ------------------------------------
def patient_record(hospital_id: str, patient_id: str | None) -> dict[str, Any] | None:
    """The patient's record when it belongs to this hospital, else None."""
    if not patient_id:
        return None
    try:
        p = storage.get_patient(patient_id)
    except Exception as e:  # noqa: BLE001 (a lookup failure only skips the record check)
        log.warning("patient lookup for the content check failed (%s)", type(e).__name__)
        return None
    return p if isinstance(p, dict) and p.get("hospital_id") == hospital_id else None


def patient_words_flagged(patient: dict[str, Any] | None, *parts: Any, label: str) -> bool:
    """True when this patient's words must stay away from the AI.

    That is when the record carries the check-in's content flag, or when the words
    sent now (strings, or form blobs whose strings are read) match the filter for
    instructions aimed at the AI. These are the patient's words, not the clinician's,
    so the label starts with "patient_text" and a match never counts toward the
    blocklist (lib/audit.py), and no address is passed for the same reason.
    """
    if patient and patient.get("content_flag"):
        return True
    from services.intake_pipeline import form_strings  # noqa: PLC0415 (heavy module, on demand)

    texts = [p if isinstance(p, str) else form_strings(p) for p in parts if p]
    joined = " | ".join(t for t in texts if t and t.strip())
    if not joined:
        return False
    safe, _cleaned, _findings = content_guard.scan(joined, label=label)
    return not safe


# ---- Ddx v2 -----------------------------------------------------------------------
class DdxV2Body(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcript: Any = ""
    chief_complaint: Any = ""
    specialty: Any = "ed"
    medical_info: Any = None
    vitals: Any = None
    # Optional: lets the server check the record's content flag too.
    patient_id: Any = None


_FLAGGED_DDX_MESSAGE = (
    "AI reasoning is off for this patient. Some of their words matched the filter for "
    "instructions aimed at the AI, so nothing from this check-in is sent to the AI and no "
    "list of possible diagnoses was drafted."
)
_FLAGGED_DDX_RED_FLAGS = " The don't-miss list below is a fixed keyword check of the patient's words, not AI."


def _ddx_without_ai(transcript: str, chief_complaint: str) -> dict[str, Any]:
    """The same shape as ddx_v2.generate with AI off, for a flagged patient."""
    red_flags = differential.match_red_flags(f"{transcript} {chief_complaint}")
    return {
        "differential": [],
        "counterfactuals": [],
        "red_flags": red_flags,
        "conformal": differential.conformal_sets([]),
        "ai_available": False,
        "source": "no_ai_content_flag",
        "content_flag": True,
        "message": _FLAGGED_DDX_MESSAGE + (_FLAGGED_DDX_RED_FLAGS if red_flags else ""),
    }


@router.post("/ddx/v2")
def ddx_v2_endpoint(
    hospital_id: str = Path(...),
    body: DdxV2Body | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    patient_id = _text(body.patient_id if body else "").strip()[:64] or None
    audit(caller, "ddx.v2", patient_id=patient_id)
    transcript = _text(body.transcript if body else "")
    if len(transcript.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Reasoning needs the patient's own description of the problem, and this chart does not have one yet.",
        )
    transcript = transcript[:20_000]
    chief_complaint = _text(body.chief_complaint)[:500]
    medical_info = _obj(body.medical_info)
    if patient_words_flagged(
        patient_record(hospital_id, patient_id), transcript, chief_complaint, medical_info,
        label="patient_text.ddx",
    ):
        return _ddx_without_ai(transcript, chief_complaint)
    return ddx_v2.generate(
        transcript,
        chief_complaint,
        medical_info=medical_info,
        specialty=_text(body.specialty)[:40] or "ed",
        vitals=_obj(body.vitals),
    )


# ---- Sepsis EWS + Deterioration Index -------------------------------------------
def _num(value: Any) -> float | None:
    """A finite number, or None for blanks, text and booleans."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


class SepsisBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hr: Any = None
    rr: Any = None
    temp_c: Any = None
    sbp: Any = None
    dbp: Any = None
    map_mm_hg: Any = None
    mental_status: Any = None
    gcs: Any = None
    spo2: Any = None
    on_oxygen: Any = False
    wbc: Any = None
    lactate: Any = None
    suspected_infection: Any = False


@router.post("/ews/sepsis")
def ews_sepsis(
    hospital_id: str = Path(...),
    body: SepsisBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ews.sepsis")
    b = body or SepsisBody()
    return early_warning.sepsis_ews(
        hr=_num(b.hr),
        rr=_num(b.rr),
        temp_c=_num(b.temp_c),
        sbp=_num(b.sbp),
        dbp=_num(b.dbp),
        map_mm_hg=_num(b.map_mm_hg),
        mental_status=_text(b.mental_status).strip() or None,
        gcs=_num(b.gcs),
        spo2=_num(b.spo2),
        on_oxygen=_flag(b.on_oxygen),
        wbc=_num(b.wbc),
        lactate=_num(b.lactate),
        suspected_infection=_flag(b.suspected_infection),
    )


# The deterioration index reads vitals under these keys. The card on the patient
# page sends them flat (the same payload as the sepsis score), older callers wrap
# them in vitals_now.
_VITAL_KEYS = ("hr", "rr", "sbp", "spo2", "temp_c", "gcs")


class DeteriorationBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vitals_now: Any = None
    vitals_4h_ago: Any = None
    hr: Any = None
    rr: Any = None
    sbp: Any = None
    spo2: Any = None
    temp_c: Any = None
    gcs: Any = None
    mental_status: Any = None
    on_oxygen: Any = False
    new_oxygen_requirement: Any = False
    gcs_drop_at_least_2: Any = False
    new_arrhythmia: Any = False
    wbc: Any = None
    wbc_now: Any = None
    wbc_baseline: Any = None
    lactate: Any = None


def _vitals_dict(raw: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (_obj(raw) or {}).items():
        n = _num(value)
        if n is not None:
            out[str(key)] = n
    return out


@router.post("/ews/deterioration")
def ews_deterioration(
    hospital_id: str = Path(...),
    body: DeteriorationBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "ews.deterioration")
    b = body or DeteriorationBody()
    vitals_now = _vitals_dict(b.vitals_now)
    for key in _VITAL_KEYS:
        n = _num(getattr(b, key))
        if n is not None and key not in vitals_now:
            vitals_now[key] = n
    if not any(k in vitals_now for k in _VITAL_KEYS):
        raise HTTPException(
            status_code=400,
            detail="Record at least one vital sign (heart rate, breathing rate, blood pressure, oxygen level, temperature or GCS) to score deterioration.",
        )
    return early_warning.deterioration_index(
        vitals_now=vitals_now,
        vitals_4h_ago=_vitals_dict(b.vitals_4h_ago) or None,
        new_oxygen_requirement=_flag(b.new_oxygen_requirement),
        on_oxygen=_flag(b.on_oxygen),
        mental_status=_text(b.mental_status).strip() or None,
        gcs_drop_at_least_2=_flag(b.gcs_drop_at_least_2),
        new_arrhythmia=_flag(b.new_arrhythmia),
        wbc_now=_num(b.wbc_now) if _num(b.wbc_now) is not None else _num(b.wbc),
        wbc_baseline=_num(b.wbc_baseline),
        lactate=_num(b.lactate),
    )


# ---- Ambient scribe: chunked pause/resume recording sessions --------------------
_UNKNOWN_SESSION = (
    "This scribe session is no longer open (the server may have restarted). "
    "Start a new session to keep recording."
)


class ScribeSessionStartBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    specialty: Any = None
    session_id: Any = None


@router.post("/scribe/session/start")
def scribe_session_start(
    hospital_id: str = Path(...),
    body: ScribeSessionStartBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.session.start")
    b = body or ScribeSessionStartBody()
    result = ambient_scribe.start_session(
        specialty=_text(b.specialty)[:64] or None,
        session_id=_text(b.session_id)[:64] or None,
    )
    result["ai_available"] = claude.available()
    return result


class ScribeChunkBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: Any = ""
    chunk: Any = ""


@router.post("/scribe/session/append")
def scribe_session_append(
    hospital_id: str = Path(...),
    body: ScribeChunkBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    b = body or ScribeChunkBody()
    session_id = _text(b.session_id)[:64]
    audit(caller, "scribe.session.append", patient_id=session_id)
    result = ambient_scribe.append_transcript_chunk(session_id, _text(b.chunk)[:20_000])
    if result.get("status") == "unknown_session":
        raise HTTPException(status_code=404, detail=_UNKNOWN_SESSION)
    return result


class ScribeSessionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: Any = ""


@router.post("/scribe/session/pause")
def scribe_session_pause(
    hospital_id: str = Path(...),
    body: ScribeSessionBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    session_id = _text(body.session_id if body else "")[:64]
    audit(caller, "scribe.session.pause", patient_id=session_id)
    result = ambient_scribe.pause_session(session_id)
    if result.get("status") == "unknown_session":
        raise HTTPException(status_code=404, detail=_UNKNOWN_SESSION)
    return result


@router.post("/scribe/session/resume")
def scribe_session_resume(
    hospital_id: str = Path(...),
    body: ScribeSessionBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    session_id = _text(body.session_id if body else "")[:64]
    audit(caller, "scribe.session.resume", patient_id=session_id)
    result = ambient_scribe.resume_session(session_id)
    if result.get("status") == "unknown_session":
        raise HTTPException(status_code=404, detail=_UNKNOWN_SESSION)
    return result


class ScribeFinalizeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: Any = ""
    refine_note: Any = True


@router.post("/scribe/session/finalize")
def scribe_session_finalize(
    request: Request,
    hospital_id: str = Path(...),
    body: ScribeFinalizeBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    b = body or ScribeFinalizeBody()
    session_id = _text(b.session_id)[:64]
    audit(caller, "scribe.session.finalize", patient_id=session_id)
    structured = ambient_scribe.finalize_session(
        session_id,
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        refine_note=b.refine_note is not False and str(b.refine_note).lower() != "false",
    )
    error = structured.get("error")
    if error == "unknown_session":
        raise HTTPException(status_code=404, detail=_UNKNOWN_SESSION)
    if error == "empty_session":
        raise HTTPException(
            status_code=400,
            detail="Nothing was captured yet. Speak near the microphone (or type a line), then finalize the note.",
        )
    return _scribe_response(structured)


class ScribeRegenerateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    structured: Any = None
    section_name: Any = ""
    specialty: Any = None


@router.post("/scribe/regenerate-section")
def scribe_regenerate_section(
    hospital_id: str = Path(...),
    body: ScribeRegenerateBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "scribe.regenerate_section")
    b = body or ScribeRegenerateBody()
    section_name = _text(b.section_name).strip()[:64]
    if not section_name:
        raise HTTPException(status_code=400, detail="Choose which section of the note to redo.")
    structured = ambient_scribe.regenerate_section(
        _obj(b.structured) or {}, section_name, specialty=_text(b.specialty)[:64] or None
    )
    return _scribe_response(structured)


def _scribe_response(structured: dict[str, Any]) -> dict[str, Any]:
    """``ai_available`` says whether AI made what this answer carries: False for a
    verbatim note and for a redo that did not run or whose AI call failed (then
    ``source`` is "ai_failed"), never inferred from the server's AI switch."""
    regen_status = structured.pop("regen_status", None)
    out: dict[str, Any] = {
        "structured": structured,
        "soap_text": ambient_scribe.to_soap_text(structured),
        "ai_available": bool(structured.get("ai_available", False)),
        "source": regen_status or structured.get("source", ""),
    }
    if structured.get("message"):
        out["message"] = structured["message"]
    return out
