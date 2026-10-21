"""Intake scribe note: turns the patient's own words and intake answers into a
short clinical note in standard shorthand (SOAP style).

The clinician sees this on the patient page alongside the raw transcript. It is
always a draft, not the chart. Without an AI key the note is assembled from the
stored facts only (the patient's words, follow-up answers, history lists) and the
assessment is left for the clinician.

The conversation scribe (clinician and patient talking, with linked evidence)
lives in ``services.ambient_scribe``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from lib import claude, content_guard
from lib.config import settings
from lib.medical_format import first_sentence, format_medical_info, history_fields

log = logging.getLogger(__name__)

_MODEL = settings.model_clinical


_SYSTEM = """You are an experienced medical scribe documenting an ER encounter. Convert the \
patient's verbal description and intake data into a dense, professional clinical note using \
standard medical shorthand.

Output format, exactly this structure, plain text, no markdown fences, no preamble:

CC: <chief complaint, 3-7 words>
HPI: <2-4 sentences in clinical shorthand covering onset, location, duration, character, aggravating/relieving factors, radiation, timing, severity (OLD CARTS) where available; use c/o, hx, sx, pt, SOB, N/V, HA, abd, assoc, denies, etc.>
ROS: <relevant positives/negatives from transcript + follow-up answers; pertinent only>
PMHx: <prior conditions or 'none reported'>
Meds: <current medications or 'none reported'>
Allergies: <allergies or 'NKDA'>
Social: <if mentioned in transcript (smoking, alcohol, occupation), else 'not discussed'>
Assessment (AI draft): <1 to 2 line working impression, always starting with 'AI draft: '>

Rules:
- Use standard abbreviations: c/o, hx, PMHx, sx, pt, SOB, N/V, HA, abd, LLQ/RLQ/RUQ/LUQ, BLE/BUE, CP, NKDA, neg, pos, assoc.
- Do NOT invent vitals, physical exam findings, or labs. None are available.
- Do NOT name specific drugs in the assessment. The physician prescribes.
- If patient mentioned pain, include its 0-10 scale and quality (sharp, dull, crushing, etc.).
- Keep HPI under 60 words.
- If context is too thin for a field, write 'not discussed'. Never invent.
- Never use em dashes or en dashes.
"""

# Specialty-aware emphasis appended to the system prompt. Keeps the same plain-text
# SOAP shape but steers which fields the scribe foregrounds.
_SPECIALTY_GUIDANCE: dict[str, str] = {
    "emergency": "Specialty lens: Emergency Medicine: foreground acuity and the must-not-miss differential in the assessment.",
    "primary_care": "Specialty lens: Primary Care: foreground chronic-disease context and medication reconciliation.",
    "cardiology": "Specialty lens: Cardiology: capture cardiac risk factors and exertional symptoms; assessment notes cardiac differential.",
    "pediatrics": "Specialty lens: Pediatrics: note caregiver-reported history and weight/age context.",
}

_SPECIALTY_ALIASES = {
    "ed": "emergency", "er": "emergency", "emergency_medicine": "emergency",
    "family_medicine": "primary_care", "internal_medicine": "primary_care",
    "gp": "primary_care", "peds": "pediatrics", "cards": "cardiology",
}


def _resolve_specialty(specialty: str | None) -> str | None:
    if not specialty:
        return None
    key = specialty.strip().lower().replace("-", "_").replace(" ", "_")
    key = _SPECIALTY_ALIASES.get(key, key)
    return key if key in _SPECIALTY_GUIDANCE else None


def generate_clinical_note(
    transcript: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    *,
    specialty: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Generate the intake-side clinical note.

    ``specialty`` / ``source_ip`` / ``user_agent`` are keyword-only and optional.
    The transcript goes through ``content_guard.scan`` before reaching Claude.
    """
    if not claude.available():
        kind = claude.off_kind()
        reason = {"no_key": "no_key", "provider_error": "ai_failed"}.get(kind or "", "ai_paused")
        return deterministic_note(transcript, medical_info, followup_qa, reason=reason)

    safe, cleaned, findings = content_guard.scan(
        transcript or "", label="scribe", source_ip=source_ip, user_agent=user_agent
    )
    if not safe:
        log.warning("scribe blocked by content_guard: %s", findings)
        return deterministic_note(transcript, medical_info, followup_qa, reason="content_flag")

    try:
        from services.followups import format_qa_for_prompts

        user_parts = [f'Patient transcript (verbatim):\n"""\n{cleaned.strip()}\n"""']
        if medical_info:
            user_parts.append(f"Medical info (structured): {format_medical_info(medical_info)}")
        if followup_qa:
            qa = format_qa_for_prompts(followup_qa)
            if qa:
                user_parts.append(f"Follow-up Q&A:\n{qa}")
        if photo_analysis and photo_analysis.get("description"):
            user_parts.append(f"Photo: {photo_analysis['description']}")

        spec = _resolve_specialty(specialty)
        system = _SYSTEM + ("\n\n" + _SPECIALTY_GUIDANCE[spec] if spec else "")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            purpose="scribe",
        )
        text = content_guard.strip_dashes("".join(getattr(b, "text", "") for b in resp.content).strip())
        return text or deterministic_note(transcript, medical_info, followup_qa, reason="ai_failed")
    except Exception as e:  # noqa: BLE001
        log.warning("Scribe generation failed: %s", type(e).__name__)
        return deterministic_note(transcript, medical_info, followup_qa, reason="ai_failed")


async def generate_clinical_note_async(
    transcript: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    *,
    specialty: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Async wrapper for ``generate_clinical_note``. ``lib.claude.messages_create``
    is synchronous, so this offloads it with ``asyncio.to_thread``, letting a
    router run the scribe alongside other independent AI work under
    ``asyncio.gather`` without blocking the event loop."""
    return await asyncio.to_thread(
        generate_clinical_note,
        transcript, medical_info, followup_qa, photo_analysis,
        specialty=specialty, source_ip=source_ip, user_agent=user_agent,
    )


# The no-AI note's assessment line, by why the note was built without AI. "default"
# covers the notes that are always built this way (the example patients) on a server
# that has a key.
ASSESSMENT_LINES = {
    "default": "Assessment: for the clinician to write. This check-in note is always built "
               "without AI; use Scribe for an AI draft.",
    "no_key": "Assessment: for the clinician to write. AI drafting is off on this server.",
    "content_flag": "Assessment: for the clinician to write. AI drafting was skipped because "
                    "some of the patient's words looked like instructions to the AI.",
    "ai_failed": "Assessment: for the clinician to write. The AI draft of this note did not "
                 "come back, so it lists only what the patient gave.",
    "ai_paused": "Assessment: for the clinician to write. AI drafting was paused when this "
                 "patient checked in; use Scribe for an AI draft.",
}


def _words_flagged(transcript: str, medical_info: Any, followup_qa: Any) -> bool:
    """True when these words match the prompt-injection filter. A pure check: nothing
    is logged or counted (the check-in already logged the match)."""
    from services.intake_pipeline import form_strings  # noqa: PLC0415 (heavy module, on demand)

    text = " | ".join(t for t in (transcript or "", form_strings(medical_info), form_strings(followup_qa)) if t)
    rules = getattr(content_guard, "_REJECT", None) or []
    return bool(text) and any(rx.search(text) for rx, _tag in rules)


def _note_reason(reason: str | None, transcript: str, medical_info: Any, followup_qa: Any) -> str:
    if reason in ASSESSMENT_LINES:
        return reason
    if not claude.configured():
        return "no_key"
    try:
        if _words_flagged(transcript, medical_info, followup_qa):
            return "content_flag"
    except Exception as e:  # noqa: BLE001 (the no-AI note must never fail)
        log.warning("no-AI note: content check skipped (%s)", type(e).__name__)
    return "default"


def deterministic_note(
    transcript: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    *,
    reason: str | None = None,
) -> str:
    """No-AI intake note built from stored facts only. Nothing is inferred.

    ``reason`` picks the assessment line (a key of ASSESSMENT_LINES). Left out, it is
    worked out here: no key on this server, words that match the prompt-injection
    filter, or else a note that is always built without AI.
    """
    t = " ".join((transcript or "").split())
    hx = history_fields(medical_info)
    lines = [
        "Auto summary (no AI)",
        f'CC (patient\'s words): "{first_sentence(t, 120)}"' if t else "CC: no description given",
        f"HPI (verbatim): {t[:600] + ('...' if len(t) > 600 else '')}" if t else "HPI: not discussed",
    ]
    answers = []
    for qa in followup_qa if isinstance(followup_qa, list) else []:
        if not isinstance(qa, dict):
            continue
        q = str(qa.get("question", "")).strip()
        a = str(qa.get("answer", "")).strip()
        if q and a:
            answers.append(f"{q} {a}")
    if answers:
        lines.append("Follow-up answers: " + " | ".join(answers[:6]))
    lines += [
        f"PMHx: {hx['conditions']}",
        f"Meds: {hx['medications']}",
        f"Allergies: {hx['allergies']}",
        ASSESSMENT_LINES[_note_reason(reason, transcript, medical_info, followup_qa)],
    ]
    return "\n".join(lines)
