"""Plain-language patient education.

1. generate_summary(): the summary a clinician publishes to the patient's phone.
   With an AI key, Claude rewrites the clinician's note in plain words. Without
   one, template_summary() publishes the clinician's note word for word, the
   comfort steps the patient already has, and fixed "tell staff / come back"
   guidance. Both shapes are identical and carry ``source`` and ``ai_available``.
   The AI rewrite is checked in every language before it is stored: food, drink
   or medicine advice the clinician's note does not contain sends the note word
   for word instead, and "when to come back" must still say to tell staff.
2. generate_handout(): a condition-specific teaching handout (reading-level and
   language aware), plus generate_handout_batch() for several conditions at once.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lib import claude
from lib.config import settings
from lib.content_guard import strip_dashes_deep

log = logging.getLogger(__name__)

_MODEL = settings.model_utility
_MAX_BATCH_WORKERS = 6

# Reading-level presets — drives target grade + sentence guidance.
READING_LEVELS: dict[str, str] = {
    "basic": "3rd-4th grade. Very short sentences. Only the most common words.",
    "standard": "6th grade. Short sentences. Everyday words, no medical jargon.",
    "advanced": "9th-10th grade. Plain but may use a defined medical term once.",
}
_DEFAULT_READING_LEVEL = "standard"


_SYSTEM = """You are explaining an ER encounter to the patient in plain language. \
Target 6th-grade reading level. Empathetic but honest. No medical jargon.

You receive three sources of information:
- The clinician's note: what the care team thinks and plans. This is the source of truth.
- The scribe's clinical summary: background only.
- The patient's original words: for tone only.

Synthesize these into a single patient-friendly summary.

Return JSON ONLY, no preamble, no markdown fence:
{
  "headline": "one short sentence on what the doctor thinks is happening",
  "what_we_are_doing": "2-3 short sentences explaining the plan in plain language",
  "things_to_do_at_home": ["short action", "short action", "short action"],
  "when_to_come_back": "2-3 short sentences listing specific red flags",
  "closing": "one sentence of calm reassurance"
}

Rules:
- No medical abbreviations: write 'blood pressure' not 'BP', 'heart tracing' not 'ECG'.
- Prefer 'your care team' over 'the doctor'.
- Say only what the clinician's note supports. Do not add a diagnosis, test or plan the note does not mention.
- Only mention medications if the clinician explicitly prescribed them.
- The patient may still be in the emergency room. Never tell them to leave or skip being seen.
- "when_to_come_back" must say to tell the staff right away if they feel worse while here.
- Total across all fields: under 150 words. Short sentences.
- Never use em dashes or en dashes."""


# Fixed wording for the no-AI summary. Only clinician text and this static copy
# reach the patient; nothing clinical is generated.
_TEMPLATE_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "headline": "Your care team wrote you a note.",
        "when_to_come_back": (
            "If you feel worse while you are here, tell the staff right away. "
            "After you go home, come back or call 911 if you feel much worse, have "
            "trouble breathing, have chest pain, faint, or notice anything new that worries you."
        ),
        "closing": "Ask your care team if anything is unclear.",
    },
    "es": {
        "headline": "Su equipo médico le escribió una nota.",
        "when_to_come_back": (
            "Si se siente peor mientras está aquí, avise al personal de inmediato. "
            "Después de irse a casa, regrese o llame al 911 si se siente mucho peor, "
            "le cuesta respirar, tiene dolor de pecho, se desmaya o nota algo nuevo que le preocupe."
        ),
        "closing": "Pregunte a su equipo médico si algo no está claro.",
    },
}


def _template_lang(language: str | None) -> str:
    code = (language or "en").strip().lower().split("-")[0]
    return code if code in _TEMPLATE_TEXT else "en"


def comfort_steps(comfort_protocol: Any, limit: int = 4) -> list[str]:
    """The stored comfort cards as short "Title: instruction" steps."""
    cards = comfort_protocol
    if isinstance(cards, str):
        try:
            cards = json.loads(cards)
        except (json.JSONDecodeError, TypeError):
            cards = []
    steps: list[str] = []
    for card in cards if isinstance(cards, list) else []:
        if not isinstance(card, dict):
            continue
        title = str(card.get("title", "")).strip()
        inst = str(card.get("instruction", "")).strip()
        if title and inst:
            steps.append(f"{title}: {inst}")
        elif inst:
            steps.append(inst)
        if len(steps) >= limit:
            break
    return steps


def template_summary(
    clinician_note: str,
    comfort_protocol: Any = None,
    patient_language: str = "en",
    *,
    source: str = "clinician_note_template",
) -> dict[str, Any]:
    """No-AI patient summary: the clinician's note word for word, the comfort
    steps already on the record, and the standard safety wording.

    The published summary replaces the "while you wait" card on the patient's
    screen, so the comfort steps are carried over. They are waiting-room steps,
    which ``steps_heading`` tells the screen. No AI wrote it, so ``ai_available``
    is False; ``source`` is "ai_failed" when an AI rewrite was tried and the call
    failed."""
    copy = _TEMPLATE_TEXT[_template_lang(patient_language)]
    return {
        "headline": copy["headline"],
        "what_we_are_doing": clinician_note.strip(),
        "things_to_do_at_home": comfort_steps(comfort_protocol),
        "steps_heading": "while_you_wait",
        "when_to_come_back": copy["when_to_come_back"],
        "closing": copy["closing"],
        "source": source,
        "ai_available": False,
    }


_WORD_FOR_WORD = ("the patient sees your note word for word, plus their comfort steps and "
                  "the standard safety advice.")


def _not_rewritten_message(allow_ai: bool) -> str:
    """Why the note went out word for word when no AI rewrite was tried."""
    if not allow_ai:
        return ("AI rewording is off for this patient because some of their words matched the "
                "filter for instructions aimed at the AI, so " + _WORD_FOR_WORD)
    if claude.off_kind() == "no_key":
        return "AI rewording is off on this server, so " + _WORD_FOR_WORD
    return f"{claude.off_reason()} So " + _WORD_FOR_WORD


def generate_summary(
    clinician_note: str = "",
    scribe_note: str = "",
    transcript: str = "",
    patient_language: str = "en",
    *,
    comfort_protocol: Any = None,
    allow_ai: bool = True,
) -> dict[str, Any]:
    """Patient summary for publishing. Returns {"error": "no_clinician_note"}
    when there is no clinician note to build from; otherwise always returns a
    summary (the template when AI is off, not allowed for this patient, or fails),
    with a ``message`` for the clinician whenever the note went out word for word."""
    clinician_note = (clinician_note or "").strip()
    if not clinician_note:
        return {"error": "no_clinician_note"}
    if not allow_ai or not claude.available():
        out = template_summary(clinician_note, comfort_protocol, patient_language)
        out["message"] = _not_rewritten_message(allow_ai)
        return out
    call_failed = False
    try:
        lang_hint = (
            "" if patient_language == "en" else f"\n\nOutput entirely in language code: {patient_language}."
        )
        user = f"""Clinician note:
\"\"\"
{clinician_note}
\"\"\"

Scribe's clinical summary:
\"\"\"
{(scribe_note or '').strip() or '(not available)'}
\"\"\"

Patient's original words (tone reference only):
\"\"\"
{(transcript or '').strip()[:800]}
\"\"\"{lang_hint}

Return the JSON now."""
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=700,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="patient_education",
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        parsed = _parse(raw)
    except Exception as e:  # noqa: BLE001
        log.warning("Patient education generation failed: %s", type(e).__name__)
        parsed, call_failed = {"error": "generation_failed"}, True
    summary = None if parsed.get("error") else _normalize_summary(parsed, patient_language)
    if summary is None or not summary["what_we_are_doing"].strip():
        out = template_summary(clinician_note, comfort_protocol, patient_language,
                               source="ai_failed" if call_failed else "clinician_note_template")
        out["message"] = ("The AI did not answer this time, so your note was sent word for word."
                          if call_failed else
                          "The AI rewrite did not work, so your note was sent word for word.")
        return out
    if _adds_unsafe_advice(summary, clinician_note, patient_language):
        out = template_summary(clinician_note, comfort_protocol, patient_language)
        out["message"] = ("The AI rewrite added food, drink or medicine advice that is not in your note, "
                          "so your note was sent word for word.")
        return out
    return _keep_tell_staff(summary, patient_language)


_ADVICE_FIELDS = ("headline", "what_we_are_doing", "closing")


def _adds_unsafe_advice(summary: dict[str, Any], clinician_note: str, language: str) -> bool:
    """True when the rewrite brings in food, drink, a medicine or a dose that the
    clinician's note does not mention. The note stays the source of truth.

    "When to come back" may describe a warning sign ("you cannot keep fluids
    down"), so only a medicine name or a dose counts there."""
    from services import comfort_protocol  # noqa: PLC0415 (keeps this module light to import)

    note_medicine = comfort_protocol.mentions_medicine(clinician_note)
    note_food = comfort_protocol.mentions_food(clinician_note, "en") or comfort_protocol.mentions_food(clinician_note, language)
    advice = [str(summary.get(k) or "") for k in _ADVICE_FIELDS] + [str(x) for x in summary.get("things_to_do_at_home") or []]
    for text in advice:
        if not note_medicine and comfort_protocol.mentions_medicine(text):
            return True
        if not note_food and comfort_protocol.mentions_food(text, language):
            return True
    return not note_medicine and comfort_protocol.names_medicine_or_dose(str(summary.get("when_to_come_back") or ""))


def _keep_tell_staff(summary: dict[str, Any], language: str) -> dict[str, Any]:
    """"When to come back" must still tell the patient to tell staff while they are here."""
    from services import comfort_protocol  # noqa: PLC0415

    if not comfort_protocol.says_tell_staff(str(summary.get("when_to_come_back") or ""), language):
        summary["when_to_come_back"] = _TEMPLATE_TEXT[_template_lang(language)]["when_to_come_back"]
    return summary


def _normalize_summary(parsed: dict[str, Any], patient_language: str = "en") -> dict[str, Any]:
    """Coerce the model's JSON into the exact summary shape the screens read.
    Missing safety or headline text falls back to the fixed wording in the
    patient's language."""
    copy = _TEMPLATE_TEXT[_template_lang(patient_language)]
    steps = parsed.get("things_to_do_at_home")
    if isinstance(steps, str):
        steps = [steps]
    out = {
        "headline": str(parsed.get("headline") or copy["headline"]),
        "what_we_are_doing": str(parsed.get("what_we_are_doing") or ""),
        "things_to_do_at_home": [str(x) for x in (steps or []) if str(x).strip()][:5],
        "when_to_come_back": str(parsed.get("when_to_come_back") or copy["when_to_come_back"]),
        "closing": str(parsed.get("closing") or ""),
    }
    out = strip_dashes_deep(out)
    out["steps_heading"] = "at_home"
    out["source"] = "claude"
    out["ai_available"] = True
    return out


def _parse(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {"error": "parse_failed"}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        log.warning("Patient ed parse fail (len=%d, content redacted)", len(raw))
        return {"error": "parse_failed"}
    if not isinstance(parsed, dict):
        return {"error": "parse_failed"}
    return parsed


# ---- Condition-specific teaching handout -------------------------------------------

_HANDOUT_SYSTEM = """You write a patient teaching handout about ONE medical condition.

The handout is given to a patient (or caregiver) to take home. It must be
trustworthy, calm, and easy to act on. It is NOT a substitute for the patient's
own care plan. It explains the condition in general terms.

You receive a target reading level and a target language. Honor BOTH exactly:
write the entire handout AT that reading level and IN that language.

Return JSON ONLY, no preamble, no markdown fence:
{
  "title": "the condition in plain words",
  "overview": "2-3 short sentences: what this condition is, in plain language",
  "why_it_happens": "1-2 short sentences on common causes (general, not the patient's specific cause)",
  "what_to_expect": "2-3 short sentences on the usual course and recovery",
  "self_care": ["short action", "short action", "short action", "short action"],
  "medication_notes": "1-2 sentences on how related medicines are usually taken; say 'follow your care team' for specifics",
  "red_flags": ["specific warning sign that means come back now", "...", "..."],
  "when_to_seek_care": "one sentence: where to go for the red flags above (ER vs call clinic)",
  "follow_up": "one sentence on typical follow-up",
  "closing": "one sentence of calm, honest reassurance"
}

Rules:
- No medical abbreviations. Write 'blood pressure', not 'BP'.
- red_flags must be concrete and observable by a non-medical person.
- Never invent medication doses. Defer dose/timing specifics to the care team.
- Do not diagnose or contradict the patient's clinician. This is general teaching.
- Keep the whole handout under 320 words.
- Never use em dashes or en dashes."""


def generate_handout(
    condition: str,
    patient_context: str = "",
    reading_level: str = _DEFAULT_READING_LEVEL,
    patient_language: str = "en",
) -> dict[str, Any]:
    """Generate a condition-specific, plain-language teaching handout.

    Args:
      condition: the condition/diagnosis to teach about (e.g. "type 2 diabetes").
      patient_context: optional free text to tailor tone (age, caregiver, etc.).
                       Kept brief and used only to adjust tone, not to diagnose.
      reading_level: one of READING_LEVELS keys; unknown values fall back to standard.
      patient_language: ISO language code; output is written entirely in it.

    Returns a dict with the handout fields plus echoed metadata:
      {
        "condition": str, "reading_level": str, "language": str,
        "title", "overview", "why_it_happens", "what_to_expect",
        "self_care": [...], "medication_notes", "red_flags": [...],
        "when_to_seek_care", "follow_up", "closing",
      }
    On failure returns {"error": "...", "condition": ..., ...metadata}.
    """
    level_key = reading_level if reading_level in READING_LEVELS else _DEFAULT_READING_LEVEL
    meta = {
        "condition": condition,
        "reading_level": level_key,
        "language": patient_language,
    }
    if not condition or not condition.strip():
        return {**meta, "error": "no_condition"}
    if not claude.available():
        return {**meta, "error": "anthropic_key_missing"}
    try:
        lang_hint = (
            "Write the handout in English."
            if patient_language == "en"
            else f"Write the ENTIRE handout in language code: {patient_language}."
        )
        user = f"""Condition to teach about:
\"\"\"
{condition.strip()}
\"\"\"

Patient context (tone reference only, do not diagnose from this):
\"\"\"
{patient_context.strip()[:600] or '(none provided)'}
\"\"\"

Target reading level: {level_key}: {READING_LEVELS[level_key]}
{lang_hint}

Return the JSON now."""
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1100,
            system=_HANDOUT_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="patient_handout",
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        parsed = _parse(raw)
        if parsed.get("error"):
            return {**meta, **parsed}
        return {**meta, **parsed}
    except Exception as e:
        log.exception("Patient handout generation failed: %s", e)
        return {**meta, "error": "generation_failed"}


def generate_handout_batch(
    conditions: list[str | dict[str, Any]],
    reading_level: str = _DEFAULT_READING_LEVEL,
    patient_language: str = "en",
) -> list[dict[str, Any]]:
    """Generate handouts for several conditions in parallel.

    Each item may be a plain condition string, or a dict
    {"condition": str, "patient_context": str, "reading_level": str,
     "patient_language": str} to override the shared defaults per item.

    Returns a list aligned with input order; per-item failures are captured
    in the result dict (never raised).
    """
    if not conditions:
        return []

    def _norm(item: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, dict):
            return {
                "condition": item.get("condition", ""),
                "patient_context": item.get("patient_context", ""),
                "reading_level": item.get("reading_level", reading_level),
                "patient_language": item.get("patient_language", patient_language),
            }
        return {
            "condition": str(item),
            "patient_context": "",
            "reading_level": reading_level,
            "patient_language": patient_language,
        }

    def _one(item: str | dict[str, Any]) -> dict[str, Any]:
        args = _norm(item)
        try:
            return generate_handout(**args)
        except Exception as e:  # keep the batch resilient
            log.warning("generate_handout_batch item failed: %s", e)
            return {
                "condition": args["condition"],
                "reading_level": args["reading_level"],
                "language": args["patient_language"],
                "error": "generation_failed",
            }

    workers = min(_MAX_BATCH_WORKERS, len(conditions))
    # Pool threads start with empty context variables, so each call runs in its own
    # copy of this request's context and counts against the visitor's AI limit.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(contextvars.copy_context().run, _one, item) for item in conditions]
        return [f.result() for f in futures]
