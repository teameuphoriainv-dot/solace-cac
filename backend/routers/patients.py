"""Clinician-facing patient endpoints: list, detail, mark-seen."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from db import storage
from db.constants import STATUS_SEEN, STATUS_WAITING
from lib.auth import audit, require_clinician
from services import disposition as disposition_svc
from services import triage_ml
from services import workup as workup_svc

router = APIRouter()


def _minutes_since(iso_ts: str) -> int:
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds() // 60))


def _checkin_model_pick(p: dict[str, Any]) -> int | None:
    """The check-in model's own ESI: the stored pick (it uses the model's tuned
    thresholds, so it can differ from the top probability), else the top of its five
    stored probabilities (older records)."""
    try:
        stored = int(p.get("model_esi_level") or 0)
    except (TypeError, ValueError):
        stored = 0
    if 1 <= stored <= 5:
        return stored
    probs = _maybe_json(p.get("probabilities"))
    if not isinstance(probs, list) or len(probs) != 5:
        return None
    try:
        values = [float(x) for x in probs]
    except (TypeError, ValueError):
        return None
    if max(values) <= 0:
        return None
    return values.index(max(values)) + 1


def _checkin_set_by_rules(p: dict[str, Any], model_pick: int | None) -> bool:
    """True when the check-in score is not the model's pick (a safety rule set it)."""
    try:
        esi = int(p.get("esi_level") or 0)
    except (TypeError, ValueError):
        return False
    if model_pick is not None:
        return model_pick != esi
    return str(p.get("triage_source") or "").startswith("safety_floor") or bool(p.get("triage_shortcut_reason"))


def _checkin_rule_name(p: dict[str, Any]) -> str | None:
    """Plain name of the safety rule that set the check-in score ("Chest pain or pressure")."""
    stored = str(p.get("triage_rule_name") or "").strip()
    if stored:
        return stored
    code = p.get("triage_shortcut_reason")
    if not code:
        return None
    try:
        from services import triage_rules  # noqa: PLC0415

        return triage_rules.rule_name(str(code)) or None
    except Exception:  # noqa: BLE001 (a label must never break the queue)
        return None


def _summary(p: dict[str, Any]) -> dict[str, Any]:
    model_pick = _checkin_model_pick(p)
    set_by_rules = _checkin_set_by_rules(p, model_pick)
    return {
        "patient_id": p["patient_id"],
        "name": p.get("name", ""),
        "esi_level": p.get("esi_level"),
        "esi_label": p.get("esi_label"),
        # A percentage belongs to the model's own pick; it is hidden when a rule set the score.
        "esi_confidence": None if set_by_rules else p.get("esi_confidence"),
        "checkin_model_esi_level": model_pick,
        "checkin_set_by_rules": set_by_rules,
        "checkin_rule_name": _checkin_rule_name(p) if set_by_rules else None,
        "confidence_band": p.get("confidence_band"),
        "clinician_prebrief": p.get("clinician_prebrief", ""),
        "language": p.get("language", "en"),
        "pain_flagged": bool(p.get("pain_flagged")),
        "pain_flagged_at": p.get("pain_flagged_at"),
        "pain_flag_acknowledged_at": p.get("pain_flag_acknowledged_at"),
        "pain_flag_acknowledged_by": p.get("pain_flag_acknowledged_by"),
        "status": p.get("status", STATUS_WAITING),
        "seen_by": p.get("seen_by"),
        "seen_at": p.get("seen_at"),
        "created_at": p.get("created_at"),
        "waited_minutes": _minutes_since(p.get("created_at", "")),
        "refined_esi_level": p.get("refined_esi_level"),
        "refined_confidence": p.get("refined_confidence"),
        "refined_at": p.get("refined_at"),
        "current_esi_level": storage.current_esi(p),
        "refined_model_esi_level": p.get("refined_model_esi_level"),
        "refined_safety_floor_reasons": _maybe_json(p.get("refined_safety_floor_reasons")) or [],
    }


@router.get("/patients")
def list_patients(
    hospital_id: str = Path(...),
    status: str = Query("waiting"),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "patients.list")
    rows = storage.list_patients_for_hospital(hospital_id, status=status)
    return {"patients": [_summary(p) for p in rows]}


@router.get("/patients/{patient_id}")
def get_patient_detail(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    caller: dict = Depends(require_clinician),
) -> dict:
    audit(caller, "patients.detail", patient_id=patient_id)
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="Patient not found.")
    notes = storage.list_notes(patient_id)
    vitals = _maybe_json(p.get("measured_vitals")) or {}
    medical_info = _maybe_json(p.get("medical_info"))
    differential = _maybe_json(p.get("differential")) or []
    esi_now = storage.current_esi(p)
    has_input = bool(vitals) or bool(notes)
    return {
        **_summary(p),
        "transcript": p.get("transcript", ""),
        # English translation used by the rules and model (None when none was made).
        "transcript_english": p.get("transcript_english"),
        # True when the patient wrote in a language the offline rules could not read.
        "needs_reading": bool(p.get("needs_reading")),
        "triage_rule_name": _checkin_rule_name(p),
        "safety_floor_reasons": _maybe_json(p.get("safety_floor_reasons")) or [],
        # The red-flag checklist ids the patient tapped (None when it was not shown).
        "red_flags_checked": _maybe_json(p.get("red_flags_checked")),
        # What the AI red-flag check found: {"source": "ai_red_flag", "ids": [...]} (None when it did not run).
        "ai_red_flags": _maybe_json(p.get("ai_red_flags")),
        # Set when the patient's words matched the prompt-injection filter, so AI was off for this check-in.
        "content_flag": p.get("content_flag"),
        "photo_url": _photo_url(p),
        "photo_analysis": _maybe_json(p.get("photo_analysis")),
        "shap_values": _clinical_factors(_maybe_json(p.get("shap_values"))),
        "comfort_protocol": _maybe_json(p.get("comfort_protocol")) or [],
        "patient_explanation": p.get("patient_explanation", ""),
        "audio_url": _audio_url(p),
        "triage_source": p.get("triage_source"),
        "clinical_flags": _maybe_json(p.get("clinical_flags")) or [],
        "composites": _maybe_json(p.get("composites")) or {},
        "triage_recommendation": p.get("triage_recommendation", ""),
        "probabilities": _maybe_json(p.get("probabilities")) or [],
        "medical_info": medical_info,
        "followup_qa": _maybe_json(p.get("followup_qa")) or [],
        "insurance_info": _maybe_json(p.get("insurance_info")),
        "prescriptions": storage.list_prescriptions(patient_id),
        "clinical_scribe_note": p.get("clinical_scribe_note", ""),
        "differential": differential,
        # Recomputed on every read so they always match the latest score, vitals and notes.
        "workup_orders": workup_svc.for_display(
            _maybe_json(p.get("workup_orders")), esi_now, vitals,
            p.get("transcript") or "", medical_info if isinstance(medical_info, dict) else None,
            has_clinical_input=has_input,
        ),
        "disposition": disposition_svc.for_display(
            _maybe_json(p.get("disposition")), esi_now, vitals,
            has_clinical_input=has_input, differential=differential,
        ),
        "notes": notes,
        "patient_education": _maybe_json(p.get("patient_education")),
        "patient_education_published_at": p.get("patient_education_published_at"),
        "refined_esi_level": p.get("refined_esi_level"),
        "refined_confidence": p.get("refined_confidence"),
        "refined_probabilities": p.get("refined_probabilities"),
        "refined_conformal_set": p.get("refined_conformal_set"),
        "refined_top_features": p.get("refined_top_features"),
        "refined_source": p.get("refined_source"),
        "refined_at": p.get("refined_at"),
        "refined_model_confidence": p.get("refined_model_confidence"),
        "refined_model_conformal_set": _maybe_json(p.get("refined_model_conformal_set")) or [],
        "refined_safety_rules_agree": _maybe_json(p.get("refined_safety_rules_agree")) or [],
        "refined_model_card": _maybe_json(p.get("refined_model_card")),
        "refined_note": p.get("refined_note"),
        "measured_vitals": p.get("measured_vitals"),
        "consent_granted_at": p.get("consent_granted_at"),
        "consent_version": p.get("consent_version"),
        "ai_processing_log": _maybe_json(p.get("ai_processing_log")) or [],
    }


def _level(raw: Any) -> int | None:
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 5 else None


def patient_screen(p: dict[str, Any]) -> dict[str, Any]:
    """What the patient's own screen (and the care-steps text) should say right now.

    The level is the more urgent of the check-in score and the bedside re-check: a
    nurse's re-check can raise what the patient sees, never lower it below what they
    were told at check-in. When the re-check raised it, the label, the explanation,
    the care card and the comfort cards are rebuilt for the new level with the same
    fixed functions the check-in uses (no AI, so it works the same with or without a
    key), and the spoken audio, made for the old level, is not offered.
    """
    from lib import fallbacks  # noqa: PLC0415
    from services import care_routing, comfort_protocol, triage_rules  # noqa: PLC0415

    checkin = _level(p.get("esi_level"))
    rechecked = _level(p.get("refined_esi_level"))
    known = [x for x in (checkin, rechecked) if x is not None]
    level = min(known) if known else 3
    raised = rechecked is not None and (checkin is None or rechecked < checkin)
    # The stored check-in decision (older records only have the explanation key).
    crisis = bool(p.get("crisis")) or p.get("explanation_key") == "crisis"
    comfort = _maybe_json(p.get("comfort_protocol")) or []
    out: dict[str, Any] = {
        "esi_level": level,
        "checkin_esi_level": checkin,
        "rechecked_by_nurse": rechecked is not None,
        "raised_by_recheck": raised,
        "rechecked_at": p.get("refined_at") if rechecked is not None else None,
        "crisis": crisis,
        "esi_label": p.get("esi_label", ""),
        "patient_explanation": p.get("patient_explanation", ""),
        "explanation_key": p.get("explanation_key"),
        "explanation_language": p.get("explanation_language"),
        "care_recommendation": _maybe_json(p.get("care_recommendation")),
        "comfort_protocol": comfort,
        "audio_url": _audio_url(p),
    }
    if not raised:
        return out

    lang = str(p.get("language") or "en")
    info = _maybe_json(p.get("medical_info"))
    info = info if isinstance(info, dict) else {}
    needs_reading = bool(p.get("needs_reading"))
    words = f"{p.get('transcript') or ''} {p.get('transcript_english') or ''}".strip()
    expl_lang = p.get("explanation_language") or (lang if lang in ("en", "es") else "en")
    age = info.get("age")
    pregnant = bool(info.get("pregnant"))
    child = care_routing.young_child(words, age, pregnant=pregnant)
    # The comfort cards add the rules' own crisis check; the words and the care card match them.
    crisis = crisis or triage_rules.assess(words, age=_age(age), pregnant=pregnant).crisis
    out["crisis"] = crisis
    out.update({
        "esi_label": fallbacks.ESI_LABELS.get(level, str(level)),
        "patient_explanation": fallbacks.patient_explanation(level, expl_lang, crisis=crisis, needs_reading=needs_reading),
        "explanation_key": fallbacks.explanation_key(level, crisis=crisis, needs_reading=needs_reading),
        "explanation_language": expl_lang,
        "care_recommendation": care_routing.serialize(care_routing.recommend(
            esi_level=level, transcript=words, patient_age=_age(age), language=lang, crisis=crisis, child=child,
        )),
        "comfort_protocol": comfort_protocol.fallback_cards(
            p.get("transcript") or "", level, lang, info, crisis=crisis, needs_reading=needs_reading,
        ),
        "audio_url": None,
    })
    return out


def _age(raw: Any) -> int | None:
    try:
        return int(float(raw)) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


# Public patient endpoint, no clinician sign-in. The patient's own phone polls this
# to see education updates published by the clinician. Returns only patient-safe fields.
@router.get("/public-patients/{patient_id}")
def get_public_patient(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
) -> dict:
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="Patient not found.")
    from services import wait_time as _wt  # noqa: PLC0415

    screen = patient_screen(p)
    # Everyone else counts at the score the queue acts on (the bedside re-check when
    # there is one). Only earlier arrivals count as ahead (services/wait_time.py).
    queue = storage.list_patients_for_hospital(hospital_id, status="waiting")
    queue = [{**q, "esi_level": storage.current_esi(q)} for q in queue if q.get("patient_id") != patient_id]
    wait = _wt.patient_wait(screen["esi_level"], queue, arrived_at=p.get("created_at"), crisis=screen["crisis"])
    # comfort_protocol and audio_url are made after the fast intake response returns,
    # so the result screen polls this until comfort_ready is true. Patient-safe fields
    # only: no transcript, no clinician artifacts, no model factors, no consent metadata.
    comfort = screen["comfort_protocol"]
    return {
        "patient_id": p["patient_id"],
        # The level the patient should act on now (never below the check-in level).
        "esi_level": screen["esi_level"],
        "esi_label": screen["esi_label"],
        # What the patient was told at check-in, and whether a nurse re-checked them.
        "checkin_esi_level": screen["checkin_esi_level"],
        "rechecked_by_nurse": screen["rechecked_by_nurse"],
        "raised_by_recheck": screen["raised_by_recheck"],
        "rechecked_at": screen["rechecked_at"],
        "language": p.get("language", "en"),
        "patient_explanation": screen["patient_explanation"],
        # Lets the result page show its own translation of the explanation after a refresh.
        "explanation_key": screen["explanation_key"],
        "explanation_language": screen["explanation_language"],
        "comfort_protocol": comfort,
        "audio_url": screen["audio_url"],
        "artifacts_status": p.get("artifacts_status"),
        # Convenience flag for the poller: true once the deferred worker has
        # produced the patient-facing comfort guidance (audio may legitimately be
        # null if TTS is disabled for the hospital, so it does not gate this).
        "comfort_ready": bool(comfort),
        "patient_education": _maybe_json(p.get("patient_education")),
        "patient_education_published_at": p.get("patient_education_published_at"),
        "status": p.get("status"),
        # "now" (ESI 1 or 2, or the crisis card): no minutes, the screen shows a sentence.
        "wait_kind": wait["wait_kind"],
        "wait_estimate_minutes": wait["minutes"],
        "wait_estimate_range": wait["range"],
        "care_recommendation": screen["care_recommendation"],
    }


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clinician_name: str = Field(..., max_length=200)


@router.patch("/patients/{patient_id}/resolve")
def resolve_patient(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: ResolveBody | None = None,
    caller: dict = Depends(require_clinician),
) -> dict:
    """Mark a patient as seen by a clinician and shorten how long the record is kept
    (from 24 hours to 30 minutes), so fewer details linger after the visit."""
    import time as _time  # noqa: PLC0415
    audit(caller, "patients.resolve", patient_id=patient_id)
    if body is None:
        raise HTTPException(status_code=400, detail="Enter the clinician's name.")
    p = storage.get_patient(patient_id)
    if not p or p.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="Patient not found.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    short_ttl = int(_time.time()) + 30 * 60  # 30 minutes
    storage.update_patient(
        patient_id,
        {
            "status": STATUS_SEEN,
            "seen_by": body.clinician_name.strip(),
            "seen_at": now,
            "ttl": short_ttl,
        },
    )


    return {"success": True, "seen_at": now, "local_retention_until": short_ttl}


# --- helpers -------------------------------------------------------------------------
def _photo_url(p: dict[str, Any]) -> str | None:
    key = p.get("photo_s3_key")
    if not key:
        return None
    # key format: "photos/<filename>"
    _, _, filename = key.partition("/")
    from db import media

    return media.presigned_get("photos", filename)


def _audio_url(p: dict[str, Any]) -> str | None:
    """Build the media URL on every read; a stored one could be stale."""
    if not p.get("audio_url"):
        return None
    from db import media

    return media.presigned_get("audio", f"{p['patient_id']}.mp3")


def _clinical_factors(raw: Any) -> dict[str, float] | None:
    """Intake model factors without administrative context (arrival time, site, nurse id)."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for name, value in raw.items():
        try:
            if triage_ml.shown_to_clinicians(str(name)):
                out[str(name)] = float(value)
        except (TypeError, ValueError):
            continue
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
