"""Bedside re-check: the nurse enters measured vitals and the score is recomputed.

The trained model (services/triage_ml.py) makes a guess from the complaint, history
and vitals. The deterministic safety rules (services/triage_rules.py) then get the
last word: they can raise the score, never lower it. When the model files are not
installed, the re-check still works on the rules alone, starting from the check-in
score. Everything is stored on the patient so the detail page shows the same result
after a reload.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from db import storage
from lib.auth import audit, require_clinician
from services import triage_ml, triage_rules

log = logging.getLogger(__name__)

router = APIRouter()

SOURCE_RULES_ONLY = "rules_only_model_not_installed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class VitalsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    systolic_bp: float | None = Field(None, ge=40, le=260)
    diastolic_bp: float | None = Field(None, ge=20, le=160)
    heart_rate: float | None = Field(None, ge=20, le=250)
    respiratory_rate: float | None = Field(None, ge=4, le=60)
    temperature_c: float | None = Field(None, ge=28, le=43)
    spo2: float | None = Field(None, ge=40, le=100)
    gcs_total: int | None = Field(None, ge=3, le=15)
    pain_score: int | None = Field(None, ge=0, le=10)
    weight_kg: float | None = Field(None, ge=1, le=500)
    height_cm: float | None = Field(None, ge=30, le=250)
    mental_status: str | None = Field(None, max_length=40)  # alert/confused/drowsy/agitated/unresponsive
    news2_score: int | None = Field(None, ge=0, le=20)


_FIELD_NAMES = {
    "systolic_bp": "Blood pressure (top number)", "diastolic_bp": "Blood pressure (bottom number)",
    "heart_rate": "Heart rate", "respiratory_rate": "Breaths per minute",
    "temperature_c": "Temperature (C)", "spo2": "Oxygen level", "gcs_total": "GCS",
    "pain_score": "Pain score", "weight_kg": "Weight", "height_cm": "Height",
    "mental_status": "Mental status", "news2_score": "NEWS2 score",
}


def _plain_validation_error(err: ValidationError) -> str:
    """One sentence for the first problem, e.g. "Heart rate must be 250 or less."."""
    first = (err.errors() or [{}])[0]
    field = str((first.get("loc") or ["value"])[-1])
    name = _FIELD_NAMES.get(field, field.replace("_", " ").capitalize())
    ctx = first.get("ctx") or {}
    kind = str(first.get("type") or "")
    if kind == "extra_forbidden":
        return f"Unknown vital sign: {field}."
    if "le" in ctx:
        return f"{name} must be {float(ctx['le']):g} or less."
    if "ge" in ctx:
        return f"{name} must be {float(ctx['ge']):g} or more."
    if "max_length" in ctx:
        return f"{name} is too long."
    if kind.startswith("int"):
        return f"{name} must be a whole number."
    return f"{name} must be a number."


def _medical_info(patient: dict[str, Any]) -> dict[str, Any]:
    # Intake stores medical_info as a JSON string.
    info = patient.get("medical_info") or {}
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            info = {}
    return info if isinstance(info, dict) else {}


def _patient_age(patient: dict[str, Any]) -> int | None:
    age = _medical_info(patient).get("age")
    try:
        return int(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        return None


def checkin_rule(patient: dict[str, Any]) -> Any | None:
    """The safety rule that set the check-in score, if one did.

    The bedside re-run of the rules sees only the English words; this keeps a rule
    that fired at check-in (for example on a translation) as a floor.
    """
    code = str(patient.get("triage_shortcut_reason") or "")
    m = re.search(r"\besi([1-5])\.", code)
    if not m or m.group(1) == "5":  # the paperwork rule is never a floor
        return None
    known = {v.reason: v for v in vars(triage_rules).values() if isinstance(v, triage_rules.ShortcutResult)}
    rule = known.get(code)
    if rule is not None:
        return rule
    return triage_rules.ShortcutResult(
        esi_level=int(m.group(1)), reason=code,
        recommendation=f"ESI {m.group(1)}: flagged by the safety rules at check-in.",
        name="Flagged by the safety rules at check-in",
    )


def _short(recommendation: str) -> str:
    """'ESI 2: heart rate over 100. Do not let...' -> 'heart rate over 100'."""
    text = re.sub(r"^\s*ESI\s*\d\s*:\s*", "", recommendation or "")
    return text.split(". ")[0].strip().rstrip(".")


def _phrase(rule: Any) -> str:
    """A rule's plain name, lowercased to sit inside a sentence ("chest pain or pressure")."""
    name = getattr(rule, "name", "") or _short(rule.recommendation)
    return name[:1].lower() + name[1:] if name[1:2].islower() else name


def _complaint_matches(transcript: str, age: int | None, pregnant: bool = False) -> list[Any]:
    try:
        return list(triage_rules.assess(transcript or "", age=age, pregnant=pregnant).matches)
    except TypeError:  # a rules module without the pregnant flag
        return list(triage_rules.assess(transcript or "", age=age).matches)
    except AttributeError:  # an older rules module without assess()
        rule = triage_rules.evaluate(transcript)
        return [rule] if rule is not None else []


def _floor(
    start_esi: int, transcript: str, vitals: dict, age: int | None,
    *, pregnant: bool = False, checkin: Any | None = None,
) -> tuple[int, list[str], list[str]]:
    """Apply the safety rules. Returns (final ESI, why it went up, rules that agree).

    "Why it went up" lists every rule that would have raised the starting score on its
    own, so a vital-sign reason still shows when the complaint already reached the same
    level. "Rules that agree" lists the rules that fired at the starting level when
    nothing was raised, so danger-zone vitals are never silently ignored on screen.
    """
    final, rule_reasons = triage_rules.apply_floor(start_esi, transcript, vitals, age=age)
    matches = _complaint_matches(transcript, age, pregnant)
    if checkin is not None and all(m.reason != checkin.reason for m in matches):
        matches.append(checkin)
    final = min([final] + [m.esi_level for m in matches])
    vit = triage_rules.vitals_floor(vitals, age)

    def phrases(keep) -> list[str]:
        out: list[str] = []

        def add(text: str) -> None:
            text = text.strip()
            if text and text not in out:
                out.append(text)

        for rule in sorted(matches, key=lambda r: r.esi_level):
            if keep(rule.esi_level):
                add(_phrase(rule))
        if vit is not None and keep(vit.esi_level):
            if vit.esi_level == 1:
                add(_phrase(vit))
            else:
                for part in _short(vit.recommendation).split(","):
                    add(part)
        return out

    if final >= start_esi:
        return start_esi, [], phrases(lambda level: level == start_esi)

    reasons = phrases(lambda level: level < start_esi)
    named = [m.esi_level for m in matches] + ([vit.esi_level] if vit is not None else [])
    # A rule this router cannot see by name still gets its say.
    if not any(level <= final for level in named):
        for rec in rule_reasons:
            text = _short(rec)
            if text and text not in reasons:
                reasons.append(text)
    return final, reasons, []


def refine(patient: dict[str, Any], vitals: dict[str, Any]) -> dict[str, Any]:
    """The bedside re-check for one patient. Pure apart from the model call."""
    transcript = patient.get("transcript") or ""
    age = _patient_age(patient)
    rules = {"pregnant": bool(_medical_info(patient).get("pregnant")), "checkin": checkin_rule(patient)}
    try:
        intake_esi = int(patient.get("esi_level") or 3)
    except (TypeError, ValueError):
        intake_esi = 3

    result = triage_ml.predict(patient, vitals)
    if result is None:
        final, reasons, agree = _floor(intake_esi, transcript, vitals, age, **rules)
        return {
            "esi_level": final,
            "confidence": None,
            "model_esi_level": None,
            "model_confidence": None,
            "raised_by_safety_rules": final < intake_esi,
            "safety_floor_reasons": reasons,
            "safety_rules_agree": agree,
            "starting_esi_level": intake_esi,
            "intake_esi_level": intake_esi,
            "probabilities": {},
            "conformal_set": [final],
            "model_conformal_set": [],
            "conformal_q_hat": None,
            "top_features": [],
            "source": SOURCE_RULES_ONLY,
            "note": (
                "The trained model is not installed on this server, so this re-check used "
                f"the safety rules only, starting from the check-in score (ESI {intake_esi})."
            ),
            "model_card": None,
        }

    model_esi = int(result["esi_level"])
    model_conf = float(result["confidence"])
    final, reasons, agree = _floor(model_esi, transcript, vitals, age, **rules)
    raised = final < model_esi
    return {
        **result,
        "esi_level": final,
        # A percentage next to a score the model did not pick would contradict itself.
        "confidence": None if raised else model_conf,
        "model_esi_level": model_esi,
        "model_confidence": model_conf,
        "raised_by_safety_rules": raised,
        "safety_floor_reasons": reasons,
        "safety_rules_agree": agree,
        "starting_esi_level": model_esi,
        "intake_esi_level": intake_esi,
        "conformal_set": [final] if raised else list(result.get("conformal_set") or [final]),
        "model_conformal_set": list(result.get("conformal_set") or [model_esi]),
        "source": f"safety_floor+{result['source']}" if raised else result["source"],
        "note": None,
    }


@router.post("/patients/{patient_id}/refine-triage")
def refine_triage(
    hospital_id: str = Path(...),
    patient_id: str = Path(...),
    body: Any = Body(None),
    caller: dict = Depends(require_clinician),
) -> dict[str, Any]:
    audit(caller, "triage.refine", patient_id=patient_id)
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="Patient not found.")
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="Enter at least one vital sign first.")
    # Validated here, not in the signature, so a bad number gets a sentence, not a 422 list.
    try:
        parsed = VitalsBody.model_validate(body)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=_plain_validation_error(e)) from None

    vitals = parsed.model_dump(exclude_none=False)
    measured = {k: v for k, v in vitals.items() if v is not None}
    if not any(k != "mental_status" for k in measured) and str(vitals.get("mental_status") or "alert") == "alert":
        raise HTTPException(status_code=400, detail="Enter at least one vital sign first.")

    refinement = refine(patient, vitals)
    applied_at = _now_iso()
    storage.update_patient(patient_id, {
        "refined_esi_level": refinement["esi_level"],
        "refined_confidence": refinement["confidence"],
        "refined_model_esi_level": refinement["model_esi_level"],
        "refined_model_confidence": refinement["model_confidence"],
        "refined_safety_floor_reasons": json.dumps(refinement["safety_floor_reasons"]),
        "refined_safety_rules_agree": json.dumps(refinement["safety_rules_agree"]),
        "refined_probabilities": json.dumps(refinement["probabilities"]),
        "refined_conformal_set": json.dumps(refinement["conformal_set"]),
        "refined_model_conformal_set": json.dumps(refinement["model_conformal_set"]),
        "refined_top_features": json.dumps(refinement["top_features"]),
        "refined_source": refinement["source"],
        "refined_note": refinement["note"],
        "refined_model_card": json.dumps(refinement["model_card"]) if refinement["model_card"] else None,
        "refined_at": applied_at,
        "measured_vitals": json.dumps(measured),
    })
    return {"success": True, "refinement": refinement, "applied_at": applied_at}
