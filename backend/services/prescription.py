"""AI prescription suggestions for the clinician to review.

Only runs with an AI key. Every suggestion goes through the deterministic
checker in services/drug_interactions against the patient's medicines, allergies
and other prescriptions, and carries those alerts in ``safety`` (and in its
``cautions`` text). The clinician writes the final prescription.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings
from lib.content_guard import strip_dashes
from lib.medical_format import format_medical_info
from services import drug_interactions

log = logging.getLogger(__name__)

_MODEL = settings.model_utility


_SYSTEM = """You are an ER prescribing reference. Given a patient's symptoms, ESI, and history,
suggest 1 to 3 standard ER prescriptions a physician might consider.

Rules:
- NEVER present these as definitive. They are suggestions the physician will verify.
- Respect the patient's allergies. If a standard suggestion is contraindicated, SKIP it or substitute.
- Flag interactions with the patient's existing medications in the "cautions" field.
- Use generic drug names (ibuprofen, not Advil).
- Keep each suggestion to a standard ER dose + course. No exotic/off-label.
- If the complaint is clearly non-pharmacologic (sprain, minor cut, refill of unrelated med), return [].
- Keep "indication" and "cautions" to one short phrase each. Never use em dashes or en dashes.

Return JSON ONLY, no preamble, no markdown fence:
[
  {
    "drug": "generic name",
    "dose": "e.g. 600 mg",
    "route": "PO | IV | IM | SL | PR",
    "frequency": "e.g. q6h PRN",
    "duration": "e.g. 5 days",
    "indication": "one-line rationale",
    "cautions": "interaction or allergy note specific to this patient, else empty string"
  }
]"""


REVIEW_LABEL = "AI suggestion for the clinician to review"


def suggest(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    *,
    other_drugs: list[str] | None = None,
) -> list[dict]:
    """Up to three suggestions, each checked for allergies and interactions.
    Returns [] with no key or on any failure."""
    return suggest_with_source(transcript, esi_level, medical_info, followup_qa, photo_analysis,
                               other_drugs=other_drugs)[0]


def suggest_with_source(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    *,
    other_drugs: list[str] | None = None,
) -> tuple[list[dict], str]:
    """``(suggestions, source)``: source is "claude" when the AI answered (its list may
    be empty), "ai_failed" when the call itself failed, and "no_ai" with AI off."""
    if not claude.available():
        return [], "no_ai"
    try:
        from services.followups import format_qa_for_prompts

        parts = [f'Transcript:\n"""\n{transcript.strip()}\n"""', f"ESI: {esi_level}"]
        if medical_info:
            parts.append(f"Medical info: {format_medical_info(medical_info)}")
        if followup_qa:
            qa = format_qa_for_prompts(followup_qa)
            if qa:
                parts.append(f"Follow-up Q&A:\n{qa}")
        if photo_analysis and photo_analysis.get("description"):
            parts.append(f"Photo: {photo_analysis['description']}")
        parts.append("Return the JSON array now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="prescription",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Prescription suggestion call failed: %s", type(e).__name__)
        return [], "ai_failed"
    try:
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        suggestions = _parse(raw)
        suggestions = _apply_interaction_checks(suggestions, medical_info, transcript)
    except Exception as e:  # noqa: BLE001
        log.warning("Prescription suggestion could not be read: %s", type(e).__name__)
        return [], "claude"
    for s in suggestions:
        try:
            s["safety"] = drug_interactions.check_prescription(
                s["drug"], medical_info=medical_info, other_drugs=other_drugs, complaint=transcript,
            )
        except Exception as e:  # noqa: BLE001 - a check failure must not drop the suggestion
            log.warning("Interaction check failed: %s", type(e).__name__)
            s["safety"] = None
        s["review_note"] = REVIEW_LABEL
    return suggestions, "claude"


def _patient_meds(medical_info: dict[str, Any] | None) -> list[str]:
    return drug_interactions.patient_medications(medical_info)


def _patient_allergies(medical_info: dict[str, Any] | None) -> list[str]:
    return drug_interactions.patient_allergies(medical_info)


def _format_alert(alert: dict[str, Any]) -> str:
    """Render one drug_interactions alert as a short physician-facing line."""
    sev = (alert.get("severity") or "").lower()
    prefix = sev.upper() if sev else "ALERT"
    reason = alert.get("reason") or alert.get("guidance") or ""
    if "a" in alert and "b" in alert:          # drug-drug
        return f"[{prefix}] {alert['a']} + {alert['b']}: {reason}"
    if "child_pugh" in alert:                  # hepatic
        return f"[{prefix}] hepatic ({alert['med']}): {reason}"
    if "threshold" in alert or "crcl" in alert:  # renal
        return f"[{prefix}] renal ({alert['med']}): {reason}"
    if "med" in alert:                         # drug-allergy
        return f"[{prefix}] allergy ({alert['med']}): {reason}"
    if "drug_class" in alert:                  # duplicate therapy
        return f"[{prefix}] duplicate {alert['drug_class']}: {reason}"
    return f"[{prefix}] {reason}".strip()


def _apply_interaction_checks(
    suggestions: list[dict],
    medical_info: dict[str, Any] | None,
    transcript: str,
) -> list[dict]:
    """Run each Claude-suggested drug through drug_interactions.check() against
    the patient's known meds + allergies, and merge any surfaced alerts into
    that suggestion's `cautions` field.

    The drug under evaluation is added to the patient's current med list so
    drug-drug, drug-allergy, renal, hepatic and duplicate-therapy checks all
    fire for the proposed prescription. Gating is delegated to check() via the
    chief complaint, so trivial-visit noise is suppressed automatically.
    """
    if not suggestions:
        return suggestions

    patient_meds = _patient_meds(medical_info)
    allergies = _patient_allergies(medical_info)
    egfr = None
    child_pugh = None
    if medical_info:
        egfr = medical_info.get("egfr") or medical_info.get("crcl")
        child_pugh = medical_info.get("child_pugh")

    for s in suggestions:
        drug = s.get("drug", "")
        if not drug:
            continue
        try:
            result = drug_interactions.check(
                patient_meds + [drug],
                allergies=allergies,
                egfr=egfr,
                child_pugh=child_pugh,
                complaint=transcript,
            )
        except Exception as e:  # never let a check failure drop a suggestion
            log.warning("Interaction check failed: %s", type(e).__name__)
            continue

        drug_canon = drug_interactions._canon(drug)
        lines: list[str] = []
        for alert in result.get("drug_drug", []):
            if drug_canon in (alert.get("a"), alert.get("b")):
                lines.append(_format_alert(alert))
        for category in ("drug_allergy", "renal", "hepatic"):
            for alert in result.get(category, []):
                if alert.get("med") == drug_canon:
                    lines.append(_format_alert(alert))
        for alert in result.get("duplicate_therapy", []):
            if drug_canon in (alert.get("members") or []):
                lines.append(_format_alert(alert))

        if lines:
            existing = s.get("cautions", "").strip()
            merged = "; ".join(lines)
            s["cautions"] = f"{existing}; {merged}" if existing else merged

    return suggestions


def _parse(raw: str) -> list[dict]:
    raw = raw.strip()
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        arr = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    cleaned: list[dict] = []
    for item in arr if isinstance(arr, list) else []:
        if not isinstance(item, dict):
            continue
        drug = str(item.get("drug", "")).strip()
        if not drug:
            continue
        cleaned.append(
            {
                "drug": strip_dashes(drug)[:200],
                "dose": strip_dashes(str(item.get("dose", "")).strip())[:100],
                "route": strip_dashes(str(item.get("route", "")).strip())[:100],
                "frequency": strip_dashes(str(item.get("frequency", "")).strip())[:100],
                "duration": strip_dashes(str(item.get("duration", "")).strip())[:100],
                "indication": strip_dashes(str(item.get("indication", "")).strip())[:500],
                "cautions": strip_dashes(str(item.get("cautions", "")).strip())[:1000],
            }
        )
        if len(cleaned) >= 3:
            break
    return cleaned
