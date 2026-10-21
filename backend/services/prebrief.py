"""Clinician pre-brief: the one-paragraph summary on each queue card.

With an AI key, Claude writes a dense clinical paragraph. Without one (or if the
call fails), ``deterministic_summary`` builds a labeled summary from the stored
facts only: the patient's own first sentence, red-flag words found in it, age and
sex, conditions, medications, allergies, and the "I feel worse" flag.

``generate_structured()`` returns the same content as labeled sections.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from lib import claude, json_extract
from lib.config import settings
from lib.content_guard import strip_dashes
from lib.medical_format import demographics, first_sentence, format_medical_info, history_fields

log = logging.getLogger(__name__)

_MODEL = settings.model_utility

AUTO_LABEL = "Auto summary (no AI)"

# Complaint groups from the shared red-flag list, in words a nurse reads at a glance.
_GROUP_WORDS = {
    "chest_pain": "chest pain",
    "stroke": "stroke signs",
    "sepsis": "infection with warning signs",
    "abdominal": "abdominal pain",
    "headache": "headache",
    "dyspnea": "trouble breathing",
    "peds_fever": "fever in a young child",
    "testicular_torsion": "testicular pain",
    "ectopic": "bleeding in pregnancy",
    "cauda_equina": "back pain with nerve signs",
    "airway": "airway warning signs",
}

# Triage shortcut rules (services/triage_rules.py) that mean a red flag fired.
_RULE_WORDS = {
    "rule.esi1.life_threatening_keywords": "life-threatening words",
    "rule.esi1.catastrophic_trauma": "major trauma or bleeding",
    "rule.esi1.stroke_symptoms": "stroke words",
    "rule.esi2.high_risk_presentation": "high-risk words",
    "rule.esi2.crisis": "crisis or self-harm words",
}

# Rules that say the same thing as one of the complaint groups above, so a summary
# that has both lists the red flag once.
_RULE_GROUPS = {
    "rule.esi1.stroke_symptoms": "stroke",
    "rule.esi2.one_sided_weakness": "stroke",
    "rule.esi2.chest_pain": "chest_pain",
    "rule.esi2.breathing": "dyspnea",
    "rule.esi2.airway_swelling": "airway",
    "rule.esi2.child_fever_lethargy": "peds_fever",
    "rule.esi2.infant_fever": "peds_fever",
    "rule.esi2.pregnancy_bleeding": "ectopic",
}


_SYSTEM = """You are writing a structured ER pre-brief for an attending clinician. \
Be dense, clinical, accurate. No fluff, no greetings, no preamble.

Output a single paragraph (1 to 3 sentences total), in this structure:
"[age]yo [sex], [chief complaint] [duration], [key associated symptoms], [relevant negatives if any], [pertinent hx/allergies/meds]. Photo: [1 sentence or 'none']."

Rules:
- Use medical shorthand (hx, c/o, pt, SOB, n/v, denies) where natural.
- Include allergies only if patient reported any (not 'none').
- Include medications only if relevant to complaint (e.g. blood thinners with bleeding).
- Do NOT invent details. Do NOT include the ESI level.
- Never use em dashes or en dashes."""


_SYSTEM_STRUCTURED = """You are writing a structured ER pre-brief for an attending clinician. \
Be dense, clinical, accurate. No fluff, no greetings, no preamble.

Output JSON ONLY (no markdown fence, no preamble):
{
  "one_liner": "[age]yo [sex] c/o [chief complaint] x[duration]",
  "hpi": "2 to 4 clause history of present illness in clinical shorthand",
  "pertinent_positives": ["finding 1", "finding 2"],
  "pertinent_negatives": ["denies X", "denies Y"],
  "history": "relevant PMHx, allergies, meds, or empty string if none reported",
  "photo_note": "1 sentence on the photo, or 'none'",
  "action_cue": "1 short clause on the most time-sensitive next step"
}

Rules:
- Use medical shorthand (hx, c/o, pt, SOB, n/v, denies) where natural.
- Include allergies and meds only if reported and relevant.
- Do NOT invent details. Do NOT include the ESI level in any field.
- Never use em dashes or en dashes."""


def red_flag_words(
    transcript: str,
    *,
    shortcut_reason: str | None = None,
    clinical_flags: list[Any] | None = None,
) -> list[str]:
    """Red flags found by fixed rules: triage shortcut, red-flag keyword groups,
    and any vital-sign flags already on the record. No AI."""
    from services.differential import match_red_flags  # noqa: PLC0415

    words: list[str] = []

    def add(w: str) -> None:
        if w and w not in words:
            words.append(w)

    if shortcut_reason:
        reason = str(shortcut_reason)
        word = _RULE_WORDS.get(reason, "")
        if not word and reason.startswith(("rule.esi1.", "rule.esi2.")):
            # Newer rule ids: use the rule's own plain name ("Chest pain or pressure").
            from services import triage_rules  # noqa: PLC0415

            word = triage_rules.rule_name(reason)
        add(word)
    for rf in match_red_flags(transcript or ""):
        add(_GROUP_WORDS.get(str(rf.get("group", "")), ""))
    for flag in clinical_flags or []:
        f = str(flag or "").strip()
        if f and not f.startswith("rule."):
            add(f)
    return words


@lru_cache(maxsize=1)
def _rule_ids_by_name() -> dict[str, str]:
    """Lowercased plain rule name ("chest pain or pressure") -> rule id."""
    from services import triage_rules  # noqa: PLC0415

    out: dict[str, str] = {}
    for rule in getattr(triage_rules, "RULES", []) or []:
        result = getattr(rule, "result", None)
        name = str(getattr(result, "name", "") or "").strip().lower()
        if name and getattr(result, "reason", None):
            out.setdefault(name, result.reason)
    return out


def _flag_key(word: str) -> str:
    """One key per red flag: the complaint group or the rule id the words come from."""
    low = " ".join(str(word).split()).lower()
    rule_id = next((rid for rid, w in _RULE_WORDS.items() if w == low), None) or _rule_ids_by_name().get(low)
    if rule_id:
        group = _RULE_GROUPS.get(rule_id)
        return f"group:{group}" if group else f"rule:{rule_id}"
    group = next((g for g, w in _GROUP_WORDS.items() if w == low), None)
    return f"group:{group}" if group else f"text:{low}"


def unique_red_flags(flags: list[str] | None) -> list[str]:
    """The red flags with each rule or complaint group listed once, keeping the first
    wording (callers put the rule's plain name first). Never raises."""
    out: list[str] = []
    seen: set[str] = set()
    for flag in flags or []:
        word = str(flag or "").strip()
        if not word:
            continue
        try:
            key = _flag_key(word)
        except Exception:  # noqa: BLE001 (a lookup problem must not drop a red flag)
            key = f"text:{word.lower()}"
        if key not in seen:
            seen.add(key)
            out.append(word)
    return out


def deterministic_summary(
    transcript: str,
    medical_info: dict[str, Any] | str | None = None,
    *,
    red_flags: list[str] | None = None,
    pain_flagged: bool = False,
) -> dict[str, Any]:
    """Structured no-AI summary from stored facts only. Never raises."""
    said = first_sentence(transcript)
    who = demographics(medical_info)
    hx = history_fields(medical_info)
    flags = unique_red_flags(red_flags if red_flags is not None else red_flag_words(transcript))

    parts = [f"{AUTO_LABEL}:"]
    if who:
        parts.append(f"{who}.")
    parts.append(f'Says: "{said}"' if said else "No description given yet.")
    if flags:
        # Semicolons, because some rule names have commas of their own.
        parts.append(f"Red-flag words: {'; '.join(flags)}.")
    parts.append(f"Hx: {hx['conditions']}. Meds: {hx['medications']}. Allergies: {hx['allergies']}.")
    if pain_flagged:
        parts.append('Patient pressed "I feel worse".')
    summary = " ".join(parts)
    return {
        "one_liner": " ".join(p for p in (who, f'"{said}"' if said else "") if p),
        "hpi": said,
        "pertinent_positives": flags,
        "pertinent_negatives": [],
        "history": f"Hx: {hx['conditions']}. Meds: {hx['medications']}. Allergies: {hx['allergies']}.",
        "photo_note": "none",
        "action_cue": "",
        "pain_flagged": bool(pain_flagged),
        "summary": summary,
        "label": AUTO_LABEL,
        "source": "auto_no_ai",
    }


def generate(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    *,
    red_flags: list[str] | None = None,
    pain_flagged: bool = False,
) -> str:
    def fallback() -> str:
        return deterministic_summary(
            transcript, medical_info, red_flags=red_flags, pain_flagged=pain_flagged
        )["summary"]

    if not claude.available():
        return fallback()
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=300,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _build_user(transcript, photo_analysis, esi_level, medical_info, followup_qa)}],
            purpose="prebrief",
        )
        text = strip_dashes("".join(getattr(b, "text", "") for b in resp.content).strip())
        return text or fallback()
    except Exception as e:  # noqa: BLE001
        log.warning("Pre-brief generation failed: %s", type(e).__name__)
        return fallback()


def generate_structured(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
) -> dict:
    """Sectioned pre-brief for the clinician panel.

    Returns a dict with keys: one_liner, hpi, pertinent_positives,
    pertinent_negatives, history, photo_note, action_cue, summary, source.
    `summary` is the flattened one-paragraph form. Always returns; never raises.
    """
    if not claude.available():
        return deterministic_summary(transcript, medical_info)
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=500,
            system=_SYSTEM_STRUCTURED,
            messages=[{"role": "user", "content": _build_user(transcript, photo_analysis, esi_level, medical_info, followup_qa)}],
            purpose="prebrief",
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        return _parse_structured(raw, transcript, medical_info)
    except Exception as e:  # noqa: BLE001
        log.warning("Structured pre-brief generation failed: %s", type(e).__name__)
        # Still the no-AI summary, marked so nobody reads it as an AI draft.
        return {**deterministic_summary(transcript, medical_info), "source": "ai_failed"}


def _build_user(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    medical_info: dict[str, Any] | None,
    followup_qa: list[dict] | None,
) -> str:
    user_parts = [f'Patient transcript:\n"""\n{(transcript or "").strip()}\n"""']
    if medical_info:
        user_parts.append(f"Medical history: {format_medical_info(medical_info)}")
    if followup_qa:
        from services.followups import format_qa_for_prompts  # noqa: PLC0415

        qa = format_qa_for_prompts(followup_qa)
        if qa:
            user_parts.append(f"Follow-up Q&A:\n{qa}")
    user_parts.append(f"Photo analysis: {(photo_analysis or {}).get('description') or 'none'}")
    user_parts.append(f"Triage ESI (context, do not include in output): {esi_level}")
    return "\n\n".join(user_parts)


def _parse_structured(raw: str, transcript: str, medical_info: dict[str, Any] | None) -> dict:
    obj = json_extract.extract_obj(raw)
    if not obj:
        return deterministic_summary(transcript, medical_info)

    def _s(key: str) -> str:
        return strip_dashes(str(obj.get(key, "")).strip())

    def _l(key: str) -> list[str]:
        val = obj.get(key) or []
        if not isinstance(val, list):
            return []
        return [strip_dashes(str(x).strip()) for x in val if str(x).strip()][:6]

    sections = {
        "one_liner": _s("one_liner"),
        "hpi": _s("hpi"),
        "pertinent_positives": _l("pertinent_positives"),
        "pertinent_negatives": _l("pertinent_negatives"),
        "history": _s("history"),
        "photo_note": _s("photo_note") or "none",
        "action_cue": _s("action_cue"),
        "source": "claude",
    }
    sections["summary"] = _flatten(sections)
    return sections


def _flatten(s: dict) -> str:
    """Collapse the structured sections into the one-paragraph form."""
    bits: list[str] = []
    if s.get("one_liner"):
        bits.append(s["one_liner"].rstrip("."))
    if s.get("hpi"):
        bits.append(s["hpi"].rstrip("."))
    pos = s.get("pertinent_positives") or []
    if pos:
        bits.append("+ " + ", ".join(pos))
    neg = s.get("pertinent_negatives") or []
    if neg:
        bits.append("denies " + ", ".join(x.replace("denies ", "") for x in neg))
    if s.get("history"):
        bits.append(s["history"].rstrip("."))
    para = ". ".join(b for b in bits if b)
    if para:
        para += "."
    photo = s.get("photo_note") or "none"
    return (para + f" Photo: {photo}.").strip()
