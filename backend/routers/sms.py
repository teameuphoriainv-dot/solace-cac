"""Patient self-serve text: POST /sms/care-instructions.

Public (no sign-in) but scoped to a patient id. It always answers 200 with
``{sent, preview, language, dir, reason?}`` for a valid request: ``preview`` is
the exact text the phone would get, ``language`` the language it is written in
and ``dir`` ("rtl" for Arabic, Persian and Urdu) the direction to show it in. A
real text goes out only when SMS is explicitly configured
(services/sms.is_configured); otherwise ``reason`` is "sms_off" and the screen
shows the preview instead. Real sends are throttled per visitor.

The steps are the ones the patient's own screen shows (routers/patients.py
patient_screen, so a nurse's re-check that raised the level is followed), and for
a child under 12 the text greets the parent.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict

from db import storage
from lib import blocklist, quota
from services import sms


log = logging.getLogger(__name__)


router = APIRouter()


class CareInstructionsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patient_id: Any = ""
    # The patient types their own number. Optional while texting is off.
    phone: Any = ""


@router.post("/sms/care-instructions")
def send_self_serve_instructions(
    request: Request,
    hospital_id: str = Path(...),
    body: CareInstructionsBody | None = None,
) -> dict[str, Any]:
    source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
    identity = quota.identity_of(source_ip, request.headers.get("user-agent"))
    blocklist.enforce(identity, source_ip=source_ip)

    patient_id = str((body.patient_id if body else "") or "").strip()[:64]
    if not patient_id:
        raise HTTPException(status_code=400, detail="We could not tell which visit this is. Reload the page and try again.")
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=404, detail="We could not find this visit. Reload the page and try again.")

    hospital = storage.get_hospital(hospital_id) or {}
    language = str(patient.get("language") or "en")
    text = sms.render_care_message(
        patient_name=str(patient.get("name") or ""),
        hospital_name=str(hospital.get("name") or "the clinic"),
        care_instructions=_care_steps_from_patient(patient),
        when_to_return=_when_to_return_from_patient(patient),
        language=language,
        for_parent=_is_young_child(patient),
    )
    preview = sms.full_message(text, language)
    written_in = {"language": sms.message_language(language), "dir": sms.text_direction(language)}

    if not sms.is_configured():
        return {"sent": False, "preview": preview, "reason": "sms_off", "success": False, **written_in}

    phone = str((body.phone if body else "") or "").strip()[:32]
    if not sms.normalize_phone(phone):
        raise HTTPException(status_code=400, detail="Enter a 10-digit US phone number, like 555-555-0123.")
    quota.check_and_consume(identity, "sms.self_serve", source_ip=source_ip)
    result = sms.send(to=phone, body=text, language=language)
    sent = bool(result.get("success"))
    out: dict[str, Any] = {"sent": sent, "preview": preview, "success": sent, **written_in}
    if not sent:
        # Never echo the number back; only the reason code.
        out["reason"] = str(result.get("reason") or "send_failed")
    return out


def _is_young_child(p: dict) -> bool:
    """A patient under 12 (the form's age, else the patient's own words)."""
    from services import care_routing  # noqa: PLC0415

    info = _maybe_json(p.get("medical_info"))
    info = info if isinstance(info, dict) else {}
    words = f"{p.get('transcript') or ''} {p.get('transcript_english') or ''}"
    try:
        return care_routing.young_child(words, info.get("age"), pregnant=bool(info.get("pregnant")))
    except Exception:  # noqa: BLE001 (a greeting must never fail the text)
        return False


def _care_steps_from_patient(p: dict) -> list[str]:
    """Up to four home-care steps from the published summary (preferred) or the
    comfort steps the result screen shows right now."""
    edu = _maybe_json(p.get("patient_education"))
    if isinstance(edu, dict):
        steps = edu.get("things_to_do_at_home")
        if isinstance(steps, list) and steps:
            return [str(s) for s in steps[:4] if str(s).strip()]
    from routers.patients import patient_screen  # noqa: PLC0415

    proto = patient_screen(p)["comfort_protocol"]
    if isinstance(proto, list):
        out = []
        for item in proto[:4]:
            if isinstance(item, dict):
                title = str(item.get("title", "")).strip()
                inst = str(item.get("instruction", "")).strip()
                if title and inst:
                    out.append(f"{title}: {inst}")
        if out:
            return out
    return []


def _when_to_return_from_patient(p: dict) -> str:
    edu = _maybe_json(p.get("patient_education"))
    if isinstance(edu, dict) and edu.get("when_to_come_back"):
        return str(edu["when_to_come_back"])
    return ""


def _maybe_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
