"""POST /api/{hospital_id}/transcribe: the patient's words plus follow-up questions.

Split from /intake so the patient can answer a few short questions before the
check-in is saved:
  1. POST /transcribe  returns {transcript, language, followups, red_flag_checklist}
  2. the patient answers the follow-ups and taps the red-flag checklist (neither
     is shown when the red-flag rules already say ESI 1 or 2)
  3. POST /intake      scores and saves the check-in

The patient must agree before any recording is sent to a speech-to-text service.
Words that match the prompt-injection filter are never refused: they get the
fixed follow-up questions, and no AI service sees them.
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, File, Form, HTTPException, Path, Request, UploadFile

from db import storage
from lib import blocklist, quota, uploads
from services import followups, intake_pipeline, transcription

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/transcribe")
async def transcribe_and_ask(
    hospital_id: str = Path(...),
    audio_file: UploadFile | None = File(None),
    pre_transcribed_text: str | None = Form(None),
    medical_info: str | None = Form(None),
    preferred_language: str | None = Form(None),
    consent_granted: str | None = Form(None),
    request: Request = None,
) -> dict:
    if not storage.get_hospital(hospital_id):
        raise HTTPException(status_code=404, detail=f"Unknown hospital '{hospital_id}'")

    source_ip = request.headers.get("x-forwarded-for", request.client.host if request and request.client else None) if request else None
    user_agent = request.headers.get("user-agent") if request else None
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)

    if str(consent_granted or "").lower() not in {"true", "1", "yes"}:
        from lib import audit as _audit  # noqa: PLC0415

        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.transcribe_no_consent",
            source_ip=source_ip, status_code=403,
            extra={"identity": identity},
        )
        raise HTTPException(
            status_code=403,
            detail="Consent required before audio can be processed by AI.",
        )

    quota.check_and_consume(identity, "transcribe", source_ip=source_ip)

    # Keep the whole request under about 28 seconds: the follow-up step only gets
    # the time a slow transcription leaves.
    started = time.monotonic()
    selected_lang = (preferred_language or "").strip().lower()[:2] or None

    # 1. Transcribe (or accept prepared text)
    if pre_transcribed_text:
        transcript = pre_transcribed_text.strip()
        # Typed text: the patient's language pick is all we have.
        language = selected_lang or "en"
        label = "transcribe.pre_transcribed"
    else:
        if not audio_file:
            raise HTTPException(status_code=400, detail="audio_file or pre_transcribed_text required")
        if not transcription.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Voice check-in is not turned on for this server. Please type what is wrong instead.",
            )
        audio_bytes = await uploads.read_and_validate(audio_file, "audio", source_ip=source_ip)
        duration = getattr(audio_file, "duration_seconds", 0.0) or 0.0
        quota.check_audio_duration(duration, identity, source_ip=source_ip)
        try:
            t = transcription.transcribe(
                audio_bytes,
                filename=audio_file.filename or "audio.webm",
                language_hint=selected_lang,
            )
            transcript = t.text
            # The patient's language pick wins over the speech service's guess.
            language = selected_lang or t.language
        except transcription.TranscriptionError as e:
            # The error text can carry transcript fragments, so it stays in the server log.
            log.warning("transcribe: transcription failed: %s", e)
            raise HTTPException(
                status_code=503,
                detail="We could not turn the recording into text. Please try again, or type what is wrong instead.",
            )
        label = "transcribe.whisper"
    # Never refused: a match keeps the words and turns AI off for this step.
    transcript, flagged = intake_pipeline.screen_patient_text(
        transcript, label=label, source_ip=source_ip, user_agent=user_agent
    )

    # 2. Follow-up questions in the patient's language, with a strict time limit.
    # A slow AI reply falls back to the fixed questions so the patient keeps moving.
    import concurrent.futures  # noqa: PLC0415
    info_dict = None
    if medical_info:
        try:
            info_dict = json.loads(medical_info)
        except json.JSONDecodeError:
            log.warning("medical_info JSON parse failed; ignoring")
    # The form's free text reaches the follow-up prompt too.
    _, form_flagged = intake_pipeline.screen_patient_text(
        intake_pipeline.form_strings(info_dict), label="transcribe.medical_info", source_ip=source_ip, user_agent=user_agent
    )
    questions: list[dict] = []
    if flagged or form_flagged:
        questions = followups.fallback_questions(transcript, language, info_dict)
    else:
        followups_budget = max(3.0, min(8.0, 28.0 - (time.monotonic() - started)))
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = ex.submit(followups.generate_questions, transcript, info_dict, language)
            questions = future.result(timeout=followups_budget)
        except concurrent.futures.TimeoutError:
            log.warning("followups generation timed out; using the fixed questions")
            questions = followups.fallback_questions(transcript, language, info_dict)
        except Exception as e:  # noqa: BLE001
            log.warning("followups generation failed (%s); using the fixed questions", type(e).__name__)
            questions = followups.fallback_questions(transcript, language, info_dict)
        finally:
            ex.shutdown(wait=False)  # never wait on a slow AI reply

    # The red-flag checklist is skipped only when the rules already say ESI 1 or 2,
    # so a patient in an obvious emergency gets their result right away.
    show_checklist = not followups.skip_for_red_flags(transcript, info_dict if isinstance(info_dict, dict) else None)
    return {"transcript": transcript, "language": language, "followups": questions,
            "red_flag_checklist": show_checklist}
