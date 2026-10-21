"""One check-in, from the patient's words to the stored record.

routers/intake.py (a real check-in) and services/demo_seed.py (the example
patients) both use this, so an example patient is scored exactly like a walk-in.

The visible ESI is decided once, here:
  1. the most urgent of the model and the red-flag rules (services/triage.py);
  2. the paperwork rule (ESI 5) only when nothing else is urgent;
  3. the red-flag checklist the patient tapped and, with an AI key, the AI
     red-flag check: each can only raise the score, to ESI 2
     (services/red_flag_checklist.py, services/ai_red_flags.py);
  4. a check-in the offline rules cannot fully read is never shown below ESI 3
     when no AI translation was made, so a nurse reads it soon. That is when the
     patient picked another language, wrote mostly in another script, or typed
     another language in Latin letters with English picked.
The badge, the explanation, the care card and the comfort cards all follow it.

Patient words that match the prompt-injection filter are never refused
(screen_patient_text): the check-in is still scored by the rules, the model and
the checklist, a note is stored for clinicians, and no AI service sees any of it.
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

from lib import claude, content_guard
from lib.config import settings
from lib.content_guard import strip_dashes
from lib.fallbacks import ESI_LABELS, explanation_key, patient_explanation
from services import ai_red_flags, care_routing, red_flag_checklist, triage, triage_rules

log = logging.getLogger(__name__)

_TRANSLATE_TIMEOUT_S = 6.0
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="intake-translate")

_TRANSLATE_SYSTEM = """Translate what a patient in an emergency room waiting area wrote into plain English.

Rules:
- Translate faithfully. Do not add, remove, soften, or explain anything.
- Keep every number, age, time, body part, and medicine name exactly.
- If the text is already English, return it unchanged.
- Output only the English text. No notes, no quotes, and never use em dashes or en dashes."""


@dataclass
class IntakeTriage:
    esi_level: int
    esi_label: str
    explanation: str
    explanation_key: str
    explanation_language: str
    crisis: bool
    needs_reading: bool
    english: str | None
    prediction: triage.TriagePrediction
    rule: triage_rules.ShortcutResult | None
    reasons: list[str] = field(default_factory=list)
    care: care_routing.CareRecommendation | None = None
    red_flags_checked: list[str] | None = None   # the patient's checklist taps (None: not asked)
    ai_red_flags: list[str] | None = None        # what the AI red-flag check found (None: it did not run)

    def record_fields(self) -> dict[str, Any]:
        """Triage fields for the stored patient record (clinician side)."""
        p = self.prediction
        model_esi = p.model_esi_level or p.esi_level
        flags = list(p.clinical_flags)
        if self.needs_reading and "needs_interpreter" not in flags:
            flags.append("needs_interpreter")
        band = p.confidence_band
        if self.rule is triage_rules.NEEDS_READING:
            band = (f"ESI 3 (set because no AI translation was available; "
                    f"the model said ESI {model_esi} at {int(round(p.confidence * 100))}%)")
        return {
            "esi_level": self.esi_level,
            "esi_label": self.esi_label,
            # The model's confidence only describes its own level; hide it when a rule moved the score.
            "esi_confidence": float(p.confidence) if self.esi_level == model_esi else None,
            "model_esi_level": model_esi,
            "model_confidence": float(p.confidence),
            "confidence_band": band,
            "shap_values": json.dumps(p.shap_values),
            "triage_source": f"rule:{self.rule.reason}" if self.rule else p.source,
            "model_source": p.source,
            "clinical_flags": json.dumps(flags),
            "composites": json.dumps(p.composites),
            "triage_recommendation": self.rule.recommendation if self.rule else p.recommendation,
            "triage_shortcut_reason": self.rule.reason if self.rule else None,
            "triage_rule_name": self.rule.name if self.rule else None,
            "safety_floor_reasons": json.dumps(self.reasons),
            "probabilities": json.dumps(p.probabilities),
            "transcript_english": self.english,
            "needs_reading": self.needs_reading,
            "crisis": self.crisis,
            "patient_explanation": self.explanation,
            "explanation_key": self.explanation_key,
            "explanation_language": self.explanation_language,
            "care_recommendation": json.dumps(care_routing.serialize(self.care)) if self.care else None,
            "red_flags_checked": json.dumps(self.red_flags_checked) if self.red_flags_checked is not None else None,
            "ai_red_flags": (json.dumps({"source": ai_red_flags.SOURCE, "ids": self.ai_red_flags})
                             if self.ai_red_flags is not None else None),
        }

    def patient_fields(self) -> dict[str, Any]:
        """What the patient's own screen gets back. No model numbers."""
        return {
            "esi_level": self.esi_level,
            "esi_label": self.esi_label,
            "patient_explanation": self.explanation,
            "explanation_key": self.explanation_key,
            "explanation_language": self.explanation_language,
            "confidence_band": None,
            "care_recommendation": care_routing.serialize(self.care) if self.care else None,
        }


def _lang(language: str | None) -> str:
    return (language or "en").strip().lower().split("-")[0][:2] or "en"


def _age(info: dict[str, Any]) -> int | None:
    try:
        return int(float(info["age"])) if info.get("age") not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _foreign_latin(transcript: str) -> bool:
    """triage_rules.foreign_latin(), when that version of the rules is installed."""
    check = getattr(triage_rules, "foreign_latin", None)
    if check is None:
        return False
    try:
        return bool(check(transcript))
    except Exception as e:  # noqa: BLE001 (a language guess must never break a check-in)
        log.warning("foreign_latin failed (%s); treating the words as English", type(e).__name__)
        return False


def readable_offline(transcript: str, language: str) -> bool:
    """Can the offline rules and the model read all of these words?

    No when the text is mostly in another script, when it is another language
    typed in Latin letters (even with English picked), or when the patient picked
    another language and the words do not read as English."""
    if triage_rules.mostly_non_latin(transcript) or _foreign_latin(transcript):
        return False
    if triage_rules.looks_english(transcript):
        return True
    return _lang(language) == "en"


def translate_to_english(transcript: str, language: str) -> str | None:
    """English translation of the patient's words, or None (no AI, too slow, or it failed)."""
    if not (transcript or "").strip() or not claude.available():
        return None
    # Run in this request's context so the call is logged on this patient's AI log.
    future = _POOL.submit(contextvars.copy_context().run, _translate_call, transcript, _lang(language))
    try:
        return future.result(timeout=_TRANSLATE_TIMEOUT_S)
    except FutureTimeout:
        log.warning("intake translation timed out; using the language backstop")
    except Exception as e:  # noqa: BLE001
        log.warning("intake translation failed (%s); using the language backstop", type(e).__name__)
    return None


def _translate_call(transcript: str, language: str) -> str | None:
    resp = claude.messages_create(
        model=settings.model_utility,
        max_tokens=500,
        system=_TRANSLATE_SYSTEM,
        messages=[{"role": "user", "content": f"Language code: {language}\n\n{transcript.strip()}"}],
        purpose="intake_translate",
        temperature=0,
    )
    text = strip_dashes("".join(getattr(b, "text", "") for b in resp.content).strip())
    return text or None


def _rules_say_urgent(transcript: str, age: int | None, pregnant: bool) -> bool:
    floor = triage_rules.assess(transcript or "", age=age, pregnant=pregnant).floor
    return floor is not None and floor.esi_level <= 2


def triage_check_in(
    transcript: str,
    *,
    medical_info: dict[str, Any] | None,
    language: str,
    photo_analysis: dict[str, Any] | None = None,
    allow_ai: bool = True,
    red_flags: list[str] | None = None,
    followup_qa: list[dict] | None = None,
) -> IntakeTriage:
    """Score one check-in and pick the words that go with the score.

    `red_flags` are the checklist ids the patient tapped (None when the checklist
    was not shown). With allow_ai=False nothing here calls an AI service (the
    example patients and check-ins the content filter flagged use this).
    """
    info = medical_info if isinstance(medical_info, dict) else {}
    lang = _lang(language)
    age, pregnant = _age(info), bool(info.get("pregnant"))
    checked = red_flag_checklist.clean(red_flags) if red_flags is not None else None
    tapped = red_flag_checklist.checklist_results(checked)
    readable = readable_offline(transcript, lang)

    # The AI red-flag check starts first, so it runs while the words are translated.
    # It can only raise the score to ESI 2, so it is skipped when the rules or the
    # checklist already put the check-in there (an obvious emergency is not slowed down).
    ai_future, ai_started = None, 0.0
    if allow_ai and not tapped and not _rules_say_urgent(transcript, age, pregnant):
        ai_future = ai_red_flags.start(_with_answers(transcript, followup_qa), info)
        ai_started = time.monotonic()
    english = translate_to_english(transcript, lang) if (not readable and allow_ai) else None

    pred = triage.predict(transcript, photo_analysis, info, english=english)
    decision = pred.decision or triage_rules.most_urgent(
        pred.esi_level, triage_rules.assess(transcript, age=age, pregnant=pregnant))

    ai_ids = None
    if ai_future is not None:
        ai_ids = ai_red_flags.result(ai_future, ai_red_flags.TIMEOUT_S - (time.monotonic() - ai_started))
    found = red_flag_checklist.ai_results(ai_ids)
    before = decision.rule
    decision = red_flag_checklist.merge(decision, tapped + found)
    esi, rule = decision.esi_level, decision.rule
    reasons = [r.name for r in decision.fired]
    for r in tapped + found:  # the clinician always sees what was checked, even when it did not move the score
        if r.name not in reasons:
            reasons.append(r.name)
    if rule is not before and rule is not None:
        pred.esi_level, pred.recommendation = esi, rule.recommendation
        pred.confidence_band = (f"ESI {esi} (set by {rule.name}; the model said ESI "
                                f"{decision.model_esi_level} at {int(round(pred.confidence * 100))}%)")

    unreadable = not readable and english is None
    if unreadable and esi > 3:
        esi, rule = 3, triage_rules.NEEDS_READING
        reasons.append(triage_rules.NEEDS_READING.name)
    needs_reading = unreadable and esi >= 3
    crisis = decision.crisis and esi >= 2

    expl_lang = lang if lang in ("en", "es") else "en"
    result = IntakeTriage(
        esi_level=esi,
        esi_label=ESI_LABELS.get(esi, str(esi)),
        explanation=patient_explanation(esi, expl_lang, crisis=crisis, needs_reading=needs_reading),
        explanation_key=explanation_key(esi, crisis=crisis, needs_reading=needs_reading),
        explanation_language=expl_lang,
        crisis=crisis,
        needs_reading=needs_reading,
        english=english,
        prediction=pred,
        rule=rule,
        reasons=reasons,
        red_flags_checked=checked,
        ai_red_flags=ai_ids,
    )
    result.care = care_routing.recommend(
        esi_level=esi, transcript=f"{transcript} {english or ''}", patient_age=age, language=lang, crisis=crisis,
    )
    if rule is not None:
        log.info("intake: %s set the visible ESI to %d (model said %d)", rule.reason, esi, decision.model_esi_level)
    return result


def _with_answers(transcript: str, followup_qa: list[dict] | None) -> str:
    """The patient's words plus their follow-up answers, for the AI red-flag check."""
    lines = []
    for qa in followup_qa if isinstance(followup_qa, list) else []:
        if isinstance(qa, dict):
            q, a = str(qa.get("question") or "").strip(), str(qa.get("answer") or "").strip()
            if q and a:
                lines.append(f"{q} {a}")
    return f"{transcript}\n\nFollow-up answers:\n" + "\n".join(lines) if lines else transcript


# ---- patient words that match the prompt-injection filter ------------------------------
CONTENT_FLAG_NOTE = (
    "Some of the patient's words matched the filter for instructions aimed at the AI, so AI was "
    "turned off for this check-in. The rules, the model and the checklist still scored it."
)


def screen_patient_text(
    text: str, *, label: str, source_ip: str | None = None, user_agent: str | None = None,
) -> tuple[str, list[str]]:
    """Run the content filter on a patient's own words without ever refusing them.

    Returns (text to use, prompt-injection findings). With no findings the text is
    the filter's cleaned copy (control tokens removed, identifiers redacted). With
    findings the patient's words are kept as written for the nurse, and the caller
    must keep every AI service away from this check-in.

    A real emergency can read like an injection ("I forget the instructions for my
    inhaler and now I can't breathe"), so a match here is not counted as abuse and
    never blocks the patient's device. It is still logged with the caller's address.
    """
    if not text:
        return text, []
    ok, cleaned, findings = content_guard.scan(text, label=label)
    if ok:
        return cleaned, []
    rejected = [f for f in findings if f.startswith("reject:")] or list(findings)
    try:
        from lib import audit as _audit  # noqa: PLC0415
        from lib.quota import identity_of  # noqa: PLC0415

        extra: dict[str, Any] = {"label": label, "findings": rejected}
        if source_ip or user_agent:
            extra["identity"] = identity_of(source_ip, user_agent)
        _audit.record(clinician_id=None, clinician_name=None, action="intake.content_flagged",
                      source_ip=source_ip, status_code=200, extra=extra)
    except Exception as e:  # noqa: BLE001 (logging must never fail a check-in)
        log.warning("could not log a content flag (%s)", type(e).__name__)
    return text, rejected


def form_strings(value: Any) -> str:
    """Every string inside a parsed form blob, for the content filter. The " | " between
    them keeps a pattern from matching across two separate answers."""
    out: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            if v.strip():
                out.append(v)
        elif isinstance(v, dict):
            for item in v.values():
                walk(item)
        elif isinstance(v, list):
            for item in v:
                walk(item)

    walk(value)
    return " | ".join(out)


def content_flag_fields(findings: dict[str, list[str]]) -> dict[str, Any]:
    """Record fields for clinicians. Empty findings mean no flag."""
    hits = {where: f for where, f in findings.items() if f}
    if not hits:
        return {"content_flag": None, "content_flag_findings": None}
    return {"content_flag": CONTENT_FLAG_NOTE, "content_flag_findings": json.dumps(hits)}
