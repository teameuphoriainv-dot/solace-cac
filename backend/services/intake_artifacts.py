"""Deferred artifact generation for intake.

The patient-facing intake path (routers/intake.py) returns fast: transcription,
content guard, rule-based triage, the plain-language explanation and care
routing. It saves the patient with ``artifacts_status="pending"`` and empty
placeholders, then hands off to this module (a background thread here, see
``lib.async_invoke``), which fills in the slower pieces:

  * clinician-only: the prebrief, intake scribe note, differential, workup
    orders and disposition (the dashboard polls for these);
  * patient-facing: the comfort steps the patient reads and the spoken audio.

With no AI key every generator returns its deterministic version, so the record
still reaches "ready" in milliseconds. A check-in whose words matched the
prompt-injection filter (``content_flag`` on the record) always gets the
deterministic versions, so none of its words reach an AI service. With a key the independent AI calls run
side by side, and the patient's comfort steps are saved the moment they are done
instead of waiting behind the clinician notes (the patient's phone only polls
for about 45 seconds). Consent and the content guard already ran in the intake
path; this module only reads the stored record.
"""
from __future__ import annotations

import contextvars
import json
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from db import storage
from services import (
    comfort_protocol,
    differential,
    disposition,
    prebrief,
    scribe,
    tts,
    workup,
)

log = logging.getLogger(__name__)

# Artifact-status lifecycle stored on the patient record.
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# The clinician-artifact field names this module owns on the patient record.
# intake.py seeds these as empty placeholders; we overwrite them here.
ARTIFACT_FIELDS = (
    "clinician_prebrief",
    "clinical_scribe_note",
    "differential",
    "workup_orders",
    "disposition",
)


def empty_artifacts() -> dict[str, Any]:
    """Placeholder values intake.py persists alongside artifacts_status="pending".

    Mirrors the JSON-encoded shapes the dashboard expects so a poll that lands
    before generation finishes renders an empty-but-valid record instead of
    erroring on a missing key. Includes the patient-facing comfort_protocol
    (empty list) and audio_url (None).
    """
    return {
        "clinician_prebrief": "",
        "clinical_scribe_note": "",
        "differential": json.dumps([]),
        "workup_orders": json.dumps({}),
        "disposition": json.dumps({}),
        "comfort_protocol": json.dumps([]),
        "audio_url": None,
    }


def _parse_json(raw: Any, default: Any) -> Any:
    """Decode a JSON-string field off the stored patient record, tolerating
    already-decoded values (local mode keeps native dicts/lists in memory)."""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _as_dict(raw: Any) -> dict[str, Any] | None:
    val = _parse_json(raw, None)
    return val if isinstance(val, dict) else None


def _as_list(raw: Any) -> list[Any]:
    val = _parse_json(raw, [])
    return val if isinstance(val, list) else []


def _esi(raw: Any) -> int:
    try:
        level = int(float(raw))
    except (TypeError, ValueError):
        return 3
    return level if 1 <= level <= 5 else 3


def inputs(patient: dict[str, Any]) -> dict[str, Any]:
    """The generation inputs, read defensively from whatever shape is stored."""
    qa = [q for q in _as_list(patient.get("followup_qa")) if isinstance(q, dict)]
    return {
        "transcript": str(patient.get("transcript") or ""),
        "esi_level": _esi(patient.get("esi_level")),
        "language": str(patient.get("language") or "en"),
        "name": str(patient.get("name") or ""),
        "explanation": str(patient.get("patient_explanation") or ""),
        "photo_analysis": _as_dict(patient.get("photo_analysis")) or {},
        "medical_info": _as_dict(patient.get("medical_info")),
        "followup_qa": qa,
        "shortcut_reason": patient.get("triage_shortcut_reason") or None,
        "clinical_flags": _as_list(patient.get("clinical_flags")),
        "pain_flagged": bool(patient.get("pain_flagged")),
        # The stored check-in decision, so the comfort cards agree with the badge even
        # when the checklist or the AI red-flag check (not the rules) set it.
        "crisis": bool(patient.get("crisis")),
        "needs_reading": bool(patient.get("needs_reading")),
        "rule_name": str(patient.get("triage_rule_name") or ""),
        "checked_reasons": [str(r) for r in _as_list(patient.get("safety_floor_reasons"))
                            if str(r).startswith(("Patient checked:", "AI red-flag check:"))],
        "ai_allowed": not patient.get("content_flag"),
    }


def _submit(pool: ThreadPoolExecutor, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """Run ``fn`` on the pool inside a copy of this thread's context, so spend
    tracking and the AI log behave exactly as they would inline."""
    return pool.submit(contextvars.copy_context().run, fn, *args, **kwargs)


def clinician_artifacts(inp: dict[str, Any]) -> dict[str, Any]:
    """Prebrief, scribe note, differential, workup and disposition.

    The first three are independent and run together; workup and disposition
    both read the differential, so they run together after it. Raises if any
    generator raises (each one already falls back on its own when AI fails).
    """
    transcript = inp["transcript"]
    info = inp["medical_info"]
    qa = inp["followup_qa"]
    photo = inp["photo_analysis"]
    esi = inp["esi_level"]

    red_flags = _red_flags(inp)
    with ThreadPoolExecutor(max_workers=3) as pool:
        brief_f = _submit(
            pool, prebrief.generate, transcript, photo, esi, info, qa,
            red_flags=red_flags, pain_flagged=inp["pain_flagged"],
        )
        note_f = _submit(pool, scribe.generate_clinical_note, transcript, info, qa, photo)
        ddx_list = _submit(pool, differential.generate, transcript, esi, info, qa, photo, None).result()
        workup_f = _submit(pool, workup.generate, transcript, esi, ddx_list, info, None)
        dispo_f = _submit(pool, disposition.generate, transcript, esi, ddx_list, info, None)
        return {
            "clinician_prebrief": brief_f.result(),
            "clinical_scribe_note": note_f.result(),
            "differential": json.dumps(ddx_list),
            "workup_orders": json.dumps(workup_f.result()),
            "disposition": json.dumps(dispo_f.result()),
        }


def _red_flags(inp: dict[str, Any]) -> list[str]:
    """Red-flag words for the clinician summary: the fixed rules, plus the rule that
    set the score and every checklist or AI red-flag reason. No AI."""
    flags = prebrief.red_flag_words(
        inp["transcript"],
        shortcut_reason=inp["shortcut_reason"],
        clinical_flags=inp["clinical_flags"],
    )
    if inp.get("rule_name") and inp["esi_level"] <= 3 and inp["rule_name"] not in flags:
        flags.insert(0, inp["rule_name"])
    for reason in inp.get("checked_reasons") or []:
        if reason not in flags:
            flags.append(reason)
    return flags


def deterministic_artifacts(inp: dict[str, Any]) -> dict[str, Any]:
    """The no-AI version of everything this worker makes. Never calls an AI or the
    network. Used for the example patients and for flagged check-ins."""
    out: dict[str, Any] = {**empty_artifacts()}
    words, info, qa = inp["transcript"], inp["medical_info"], inp["followup_qa"]
    try:
        out["clinician_prebrief"] = prebrief.deterministic_summary(
            words, info, red_flags=_red_flags(inp), pain_flagged=inp["pain_flagged"])["summary"]
    except Exception as e:  # noqa: BLE001 (the no-AI path must never fail)
        log.warning("no-AI artifacts: prebrief skipped (%s)", type(e).__name__)
    try:
        out["clinical_scribe_note"] = scribe.deterministic_note(words, info, qa)
    except Exception as e:  # noqa: BLE001
        log.warning("no-AI artifacts: scribe note skipped (%s)", type(e).__name__)
    try:
        out["workup_orders"] = json.dumps(workup.pending(ai_available=False))
        out["disposition"] = json.dumps(disposition.pending(ai_available=False))
    except Exception as e:  # noqa: BLE001
        log.warning("no-AI artifacts: orders skipped (%s)", type(e).__name__)
    try:
        out["comfort_protocol"] = json.dumps(comfort_protocol.fallback_cards(
            words, inp["esi_level"], inp["language"], info,
            crisis=inp.get("crisis"), needs_reading=bool(inp.get("needs_reading"))))
    except Exception as e:  # noqa: BLE001
        log.warning("no-AI artifacts: comfort cards skipped (%s)", type(e).__name__)
    out["audio_url"] = None
    return out


def patient_artifacts(inp: dict[str, Any], patient_id: str) -> dict[str, Any]:
    """Comfort steps, then the spoken audio built from them."""
    protocol = comfort_protocol.generate(
        inp["transcript"], inp["photo_analysis"], inp["esi_level"], inp["language"],
        inp["medical_info"], inp["followup_qa"],
        crisis=inp.get("crisis"), needs_reading=bool(inp.get("needs_reading")),
    )
    audio_script = tts.compose_script(
        inp["explanation"], protocol, patient_name=inp["name"],
    )
    audio_url = tts.generate_and_upload(audio_script, inp["language"], patient_id)
    return {"comfort_protocol": json.dumps(protocol), "audio_url": audio_url}


def _patient_artifacts_saved(inp: dict[str, Any], patient_id: str) -> dict[str, Any]:
    """Make the patient half and save it right away. Comfort steps and audio
    are written together because the phone stops polling once the steps arrive."""
    out = patient_artifacts(inp, patient_id)
    storage.update_patient(patient_id, out)
    return out


def generate_clinician_artifacts(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Generate the deferred artifacts for one stored patient, patch them onto
    the record, and flip ``artifacts_status`` to "ready".

    The clinician and patient halves run at the same time, and a failure in one
    still saves the other. The patient half is saved as soon as it is done, so
    the comfort steps never wait for the clinician notes. Any failure marks the
    record "failed" (a terminal status the screens understand) and is logged
    with the hospital id only, never patient data. Never raises.
    """
    patient = storage.get_patient(patient_id)
    if not patient or patient.get("hospital_id") != hospital_id:
        log.warning(
            "deferred artifacts: patient not found or hospital mismatch for hospital=%s",
            hospital_id,
        )
        return {"artifacts_status": STATUS_FAILED}

    artifacts: dict[str, Any] = {}
    failed = False
    try:
        inp = inputs(patient)
    except Exception as e:  # noqa: BLE001
        log.warning("deferred artifacts: unreadable record for hospital=%s: %s", hospital_id, type(e).__name__)
        inp = None
        failed = True

    if inp is not None and not inp["ai_allowed"]:
        # The words matched the prompt-injection filter: no AI, and no voice service.
        artifacts.update(deterministic_artifacts(inp))
    elif inp is not None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            clinician_f = _submit(pool, clinician_artifacts, inp)
            patient_f = _submit(pool, _patient_artifacts_saved, inp, patient_id)
            for half, future in (("patient", patient_f), ("clinician", clinician_f)):
                try:
                    artifacts.update(future.result())
                except Exception as e:  # noqa: BLE001
                    log.warning("deferred %s artifacts failed for hospital=%s: %s", half, hospital_id, type(e).__name__)
                    failed = True

    artifacts["artifacts_status"] = STATUS_FAILED if failed else STATUS_READY
    try:
        storage.update_patient(patient_id, artifacts)
    except Exception as e:  # noqa: BLE001
        log.warning("could not save deferred artifacts for hospital=%s: %s", hospital_id, type(e).__name__)
        return {"artifacts_status": STATUS_FAILED}
    if not failed:
        log.info("deferred artifacts ready for hospital=%s", hospital_id)
    return artifacts
