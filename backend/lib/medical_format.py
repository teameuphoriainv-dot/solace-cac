"""Shared medical-info formatting.

``format_medical_info`` renders the patient's medical info as one compact,
clinical-shorthand line for Claude prompts (prebrief, scribe, comfort protocol,
differential, workup, disposition, prescription).

The other helpers build the deterministic, no-AI summaries the clinician sees
when no AI key is configured: the patient's own first sentence, demographics,
and the medication, allergy and condition lists, each labeled honestly.
"""
from __future__ import annotations

import re
from typing import Any


def format_medical_info(info: dict[str, Any] | None) -> str:
    """Render `medical_info` as one short clinical-shorthand line.

    Output shape:
        "38yo female; pregnant; allergies: Penicillin (anaphylaxis); meds: Insulin; hx: Diabetes"

    Returns "none reported" when the dict is empty / sentinel-only — callers
    can drop that line from their prompt without parsing.
    """
    if not info:
        return "none reported"

    parts: list[str] = []

    # Demographics
    if info.get("age") not in (None, 0, ""):
        parts.append(f"{info['age']}yo")
    if info.get("sex"):
        parts.append(str(info["sex"]))
    if info.get("pregnant"):
        weeks = info.get("gestational_weeks")
        parts.append(f"pregnant{f' {weeks}w' if weeks else ''}")
    if info.get("smoker"):
        parts.append("smoker")

    # Allergies (with severity if known)
    allergies = _filter_none(info.get("allergies"))
    if allergies:
        sev_map = info.get("allergy_severity") or {}
        labeled = [f"{a} ({sev_map[a]})" if sev_map.get(a) else a for a in allergies]
        parts.append(f"allergies: {', '.join(labeled)}")

    # Meds (with blood thinner specifier)
    meds = _filter_none(info.get("medications"))
    if meds:
        bt = info.get("blood_thinner_name")
        labeled = [f"{m} ({bt})" if m == "Blood thinners" and bt else m for m in meds]
        parts.append(f"meds: {', '.join(labeled)}")

    # Conditions (with diabetes type / NYHA class specifiers)
    conds = _filter_none(info.get("conditions"))
    if conds:
        dtype = info.get("diabetes_type")
        nyha = info.get("heart_failure_class")
        labeled = []
        for c in conds:
            if c == "Diabetes" and dtype:
                labeled.append(f"{c} ({dtype})")
            elif c == "Heart failure" and nyha:
                labeled.append(f"{c} (NYHA {nyha})")
            else:
                labeled.append(c)
        parts.append(f"hx: {', '.join(labeled)}")

    return "; ".join(parts) or "none reported"


def _filter_none(arr: Any) -> list[str]:
    """Drop the literal sentinel 'None' that the patient form sends when nothing applies."""
    if not isinstance(arr, list):
        return []
    return [str(x) for x in arr if x and str(x).lower() != "none"]


def as_dict(info: Any) -> dict[str, Any]:
    """medical_info arrives as a dict, a JSON string, or nothing."""
    if isinstance(info, dict):
        return info
    if isinstance(info, str) and info.strip():
        import json  # noqa: PLC0415

        try:
            parsed = json.loads(info)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def first_sentence(text: str, limit: int = 160) -> str:
    """The patient's opening sentence, trimmed to ``limit`` characters."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    m = re.search(r"^(.+?[.!?])(\s|$)", t)
    sentence = m.group(1) if m else t
    if len(sentence) > limit:
        sentence = sentence[: limit - 3].rstrip() + "..."
    return sentence


def _list_or_none(info: dict[str, Any], key: str, *, absent: str) -> str:
    raw = info.get(key)
    if not isinstance(raw, list):
        return absent
    items = _filter_none(raw)
    if items:
        return ", ".join(items)
    return "none reported" if raw else absent


def demographics(info: Any) -> str:
    """e.g. "58yo male" or "" when nothing is known."""
    d = as_dict(info)
    bits: list[str] = []
    if d.get("age") not in (None, 0, ""):
        bits.append(f"{d['age']}yo")
    sex = str(d.get("sex") or "").strip()
    if sex:
        bits.append({"m": "male", "f": "female"}.get(sex.lower(), sex.lower()))
    if d.get("pregnant"):
        bits.append("pregnant")
    return " ".join(bits)


def history_fields(info: Any) -> dict[str, str]:
    """Conditions, medications and allergies as display strings.

    "not provided" means the patient skipped the form; "none reported" means
    they said there were none.
    """
    d = as_dict(info)
    absent = "not provided" if not d else "not recorded"
    meds = _list_or_none(d, "medications", absent=absent)
    bt = d.get("blood_thinner_name")
    if bt and "Blood thinners" in meds:
        meds = meds.replace("Blood thinners", f"Blood thinners ({bt})")
    return {
        "conditions": _list_or_none(d, "conditions", absent=absent),
        "medications": meds,
        "allergies": _list_or_none(d, "allergies", absent=absent),
    }
