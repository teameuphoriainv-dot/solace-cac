"""POST /api/{hospital_id}/intake: the patient's check-in, called after /transcribe.

The patient's words are never refused because they look like a prompt injection:
the check-in is kept, scored by the rules, the model and the red-flag checklist,
marked for clinicians, and kept away from every AI service (see
services/intake_pipeline.screen_patient_text).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Path, Request, UploadFile

from db import media, storage
from db.constants import STATUS_WAITING
from lib import ai_log, async_invoke, blocklist, idempotency, quota, uploads
from services import intake_artifacts, intake_pipeline, red_flag_checklist, transcription, vision

CONSENT_VERSION_CURRENT = "1.0"


def _source_ip(req: Request | None) -> str | None:
    if req is None:
        return None
    return req.headers.get("x-forwarded-for", req.client.host if req.client else None)


log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/intake")
async def create_intake(
    hospital_id: str = Path(...),
    audio_file: UploadFile | None = File(None),
    image_file: UploadFile | None = File(None),
    patient_name: str = Form(..., max_length=200),
    pre_transcribed_text: str | None = Form(None, max_length=20_000),
    # Structured fields (JSON-encoded arrays/objects)
    medical_info: str | None = Form(None, max_length=50_000),
    followup_qa: str | None = Form(None, max_length=50_000),
    insurance_info: str | None = Form(None, max_length=10_000),
    intake_token: str | None = Form(None, max_length=256),
    idempotency_key: str | None = Form(None, max_length=128),
    consent_granted: str | None = Form(None, max_length=16),
    consent_version: str | None = Form(None, max_length=16),
    preferred_language: str | None = Form(None, max_length=16),
    # The red-flag checklist: a JSON array of ids (services/red_flag_checklist.IDS).
    red_flags: str | None = Form(None, max_length=2_000),
    # When the patient was matched to an EHR record at check-in, carry that id
    # forward so the clinician-side lookup fetches the same record.
    ehr_fhir_id: str | None = Form(None, max_length=128),
    ehr_match_source: str | None = Form(None, max_length=64),
    request: Request = None,
) -> dict[str, Any]:
    src_ip = _source_ip(request)
    ua = request.headers.get("user-agent") if request else None
    identity = quota.identity_of(src_ip, ua)

    blocklist.enforce(identity, source_ip=src_ip)

    # The patient must agree before their words, voice or photo are processed.
    if str(consent_granted or "").lower() not in {"true", "1", "yes"}:
        from lib import audit as _audit  # noqa: PLC0415

        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.intake_no_consent",
            source_ip=src_ip, status_code=403,
            extra={"identity": identity},
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Consent required. You must agree to AI processing of your voice, symptoms,"
                " and photos before submitting intake."
            ),
        )

    # Services append to this log; it is saved on the patient record at the end.
    ai_log.new_log()

    # A network retry with the same key gets the first response back instead of a duplicate patient.
    if not idempotency_key and request is not None:
        idempotency_key = request.headers.get("idempotency-key")
    if idempotency_key:
        cached = idempotency.get_cached(idempotency_key, scope="intake")
        if cached:
            log.info("intake: idempotency replay for key %s", idempotency_key[:8])
            return cached

    # One-use check-in token, bound to the caller (see lib/intake_nonce.py).
    from lib import intake_nonce  # noqa: PLC0415

    intake_nonce.require(hospital_id, intake_token, source_ip=src_ip, user_agent=ua)
    quota.check_and_consume(identity, "intake.submit", source_ip=src_ip)

    hospital = storage.get_hospital(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail=f"Unknown hospital '{hospital_id}'")

    patient_id = str(uuid.uuid4())

    # 1. The patient's words: typed (or already transcribed) text, or a fresh recording.
    # The language the patient picked wins over the speech service's guess.
    selected_lang = (preferred_language or "en").strip().lower()[:2] or "en"
    findings: dict[str, list[str]] = {}
    if pre_transcribed_text:
        transcript_text = pre_transcribed_text.strip()
        language = selected_lang
        label = "intake.pre_transcribed"
    else:
        if not audio_file:
            raise HTTPException(status_code=400, detail="audio_file or pre_transcribed_text is required")
        if not transcription.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Voice check-in is not turned on for this server. Please type what is wrong instead.",
            )
        audio_bytes = await uploads.read_and_validate(audio_file, "audio", source_ip=src_ip)
        duration = getattr(audio_file, "duration_seconds", 0.0) or 0.0
        quota.check_audio_duration(duration, identity, source_ip=src_ip)
        try:
            t = transcription.transcribe(audio_bytes, filename=audio_file.filename or "audio.webm")
            transcript_text = t.text
            language = selected_lang or t.language
        except transcription.TranscriptionError as e:
            # The error text can carry transcript fragments, so it stays in the server log.
            log.warning("intake: transcription failed: %s", e)
            raise HTTPException(
                status_code=503,
                detail="We could not turn the recording into text. Please try again, or type what is wrong instead.",
            )
        label = "intake.whisper"
    # Never refused: a match keeps the words for the nurse and turns AI off for this check-in.
    transcript_text, findings["transcript"] = intake_pipeline.screen_patient_text(
        transcript_text, label=label, source_ip=src_ip, user_agent=ua
    )

    # 2. Structured context. The answers and form text reach AI prompts too, so they are screened the same way.
    info_dict = _parse_json_blob(medical_info)
    qa_list = _parse_json_blob(followup_qa) or []
    insurance_dict = _parse_json_blob(insurance_info)
    checked = red_flag_checklist.parse(red_flags)
    answers = [qa.get("answer") for qa in qa_list if isinstance(qa, dict)] if isinstance(qa_list, list) else []
    _, findings["followup_qa"] = intake_pipeline.screen_patient_text(
        intake_pipeline.form_strings(answers), label="intake.followup_qa", source_ip=src_ip, user_agent=ua
    )
    _, findings["medical_info"] = intake_pipeline.screen_patient_text(
        intake_pipeline.form_strings(info_dict), label="intake.medical_info", source_ip=src_ip, user_agent=ua
    )
    _, findings["name"] = intake_pipeline.screen_patient_text(
        patient_name, label="intake.name", source_ip=src_ip, user_agent=ua
    )
    allow_ai = not any(findings.values())

    # 3. Photo (EXIF-stripped, re-encoded JPEG)
    photo_s3_key: str | None = None
    image_bytes: bytes | None = None
    if image_file is not None:
        image_bytes = await uploads.read_and_validate(image_file, "image", source_ip=src_ip)
        filename = f"{patient_id}-photo.jpg"
        media.save("photos", filename, image_bytes, content_type="image/jpeg")
        photo_s3_key = f"photos/{filename}"
    photo_analysis = (
        await asyncio.to_thread(vision.analyze_photo, image_bytes, "image/jpeg") if image_bytes and allow_ai else {}
    )

    # 4. The score and everything the patient reads with it (services/intake_pipeline.py).
    # Comfort cards and audio come later from the deferred worker (step 6).
    decision = await asyncio.to_thread(
        intake_pipeline.triage_check_in,
        transcript_text,
        medical_info=info_dict if isinstance(info_dict, dict) else None,
        language=language,
        photo_analysis=photo_analysis,
        allow_ai=allow_ai,
        red_flags=checked,
        followup_qa=qa_list if isinstance(qa_list, list) else None,
    )

    # 5. Persist
    patient: dict[str, Any] = {
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "name": patient_name.strip(),
        "language": language,
        "transcript": transcript_text,
        "medical_info": json.dumps(info_dict) if info_dict else None,
        "followup_qa": json.dumps(qa_list) if qa_list else None,
        "insurance_info": json.dumps(insurance_dict) if insurance_dict else None,
        "photo_s3_key": photo_s3_key,
        "photo_analysis": json.dumps(photo_analysis) if photo_analysis else None,
        **decision.record_fields(),
        # Set when the content filter matched: the nurse sees why AI is off for this patient.
        **intake_pipeline.content_flag_fields(findings),
        # Empty but valid placeholders until the deferred worker fills them in.
        **intake_artifacts.empty_artifacts(),
        "artifacts_status": intake_artifacts.STATUS_PENDING,
        "pain_flagged": False,
        "status": STATUS_WAITING,
        "consent_granted_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "consent_version": consent_version or CONSENT_VERSION_CURRENT,
        "ai_processing_log": json.dumps((ai_log.current() or ai_log.AILog()).serialize()),
        "ai_cost_usd": float((ai_log.current() or ai_log.AILog()).total_cost_usd()),
        "ai_cost_breakdown": json.dumps((ai_log.current() or ai_log.AILog()).cost_breakdown()),
    }
    if ehr_fhir_id:
        patient["ehr_fhir_id"] = ehr_fhir_id.strip()
        patient["ehr_match_source"] = (ehr_match_source or "fhir").strip()
    storage.put_patient(patient)

    # 6. Clinician artifacts, comfort cards and audio are made in the background.
    # This never blocks or fails the patient's response.
    async_invoke.dispatch_deferred_artifacts(hospital_id, patient_id)

    # The patient's screen gets the score and the words, never the model's numbers.
    response = {
        "patient_id": patient_id,
        **decision.patient_fields(),
        "comfort_protocol": [],
        "audio_url": None,
        "artifacts_status": intake_artifacts.STATUS_PENDING,
        "language": language,
    }
    if idempotency_key:
        idempotency.save(idempotency_key, scope="intake", response=response)
    return response


def _parse_json_blob(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Failed to parse JSON blob (len=%d, content redacted)", len(raw))
        return None
