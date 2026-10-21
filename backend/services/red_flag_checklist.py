"""The red-flag checklist the patient taps after describing what is wrong.

Keyword rules miss many emergencies written in fresh words, in English and in
other languages. A short list of warning signs the patient taps does not depend
on wording or language, so it is a second safety net under the rules:

  * every box except "None of these" puts the visible ESI at 2 or more urgent
    (it never lowers a score),
  * "Thinking about hurting yourself" also shows the 988 crisis card
    ("Swallowed something dangerous" does not by itself),
  * the clinician sees "Patient checked: <label>" next to the score.

The ids and their order are fixed and shared with the frontend
(frontend/src/lib/api-patient.ts RED_FLAG_IDS). services/ai_red_flags.py returns
the same ids, so both feed the score the same way.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from services import triage_rules

NONE = "none"
IDS: tuple[str, ...] = (
    "breathing", "chest", "faint", "confusion", "bleeding",
    "self_harm", "ingestion", "pregnancy", "stroke", "infant_fever", NONE,
)
# English labels. The patient's screen shows its own translation of each one.
LABELS: dict[str, str] = {
    "breathing": "Hard to breathe",
    "chest": "Chest pain, pressure or tightness",
    "faint": "Fainted or passed out",
    "confusion": "New confusion, or not acting like themselves",
    "bleeding": "Bleeding that will not stop",
    "self_harm": "Thinking about hurting yourself or ending your life",
    "ingestion": "Swallowed something dangerous, like pills, poison or a battery",
    "pregnancy": "Pregnant, with bleeding, leaking fluid or bad belly pain",
    "stroke": "Sudden weakness, numbness, a drooping face or trouble talking",
    "infant_fever": "A baby under 3 months with a fever",
    NONE: "None of these",
}
TITLE = "Is any of this happening right now?"
SUBTITLE = "Tap all that apply. It helps the nurse see you sooner if you need it."

FLOOR_ESI = 2
_NOTE = "Do not let this patient wait. Bed and clinician promptly."


def parse(raw: Any) -> list[str] | None:
    """The valid ids from the intake form field (a JSON array), in K1 order.

    Returns None when the field was not sent, so a record can tell "not asked"
    apart from "answered None of these". Unknown ids and bad JSON are ignored.
    """
    if raw is None:
        return None
    value: Any = raw
    if isinstance(raw, (bytes, str)):
        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
        if not text.strip():
            return None
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
    return clean(value)


def clean(ids: Any) -> list[str]:
    """Known ids only, deduplicated, in K1 order. Anything that is not a list is []."""
    if not isinstance(ids, (list, tuple)):
        return []
    given = {str(i).strip().lower() for i in ids if isinstance(i, str)}
    return [i for i in IDS if i in given]


def flagged(ids: Iterable[str] | None) -> list[str]:
    """The ids that raise the score: every known id except "none"."""
    return [i for i in clean(list(ids or [])) if i != NONE]


def _result(prefix: str, rid: str, name: str, recommendation: str) -> triage_rules.ShortcutResult:
    # The reason keeps an "esi2." part so the bedside re-check (routers/triage.py
    # checkin_rule) keeps it as a floor, like any other check-in rule.
    return triage_rules.ShortcutResult(
        FLOOR_ESI, f"{prefix}.esi{FLOOR_ESI}.{rid}", recommendation,
        name=name, crisis=(rid == "self_harm"),
    )


def checklist_results(ids: Iterable[str] | None) -> list[triage_rules.ShortcutResult]:
    """One ESI 2 result per box the patient checked (none for "None of these")."""
    return [
        _result("checklist", rid, f"Patient checked: {LABELS[rid]}",
                f'ESI {FLOOR_ESI}: the patient checked "{LABELS[rid]}" on the red-flag list. {_NOTE}')
        for rid in flagged(ids)
    ]


def ai_results(ids: Iterable[str] | None) -> list[triage_rules.ShortcutResult]:
    """One ESI 2 result per warning sign the AI red-flag check read in the words."""
    return [
        _result("ai_red_flag", rid, f"AI red-flag check: {LABELS[rid]}",
                f'ESI {FLOOR_ESI}: the AI red-flag check read the patient\'s words as "{LABELS[rid]}". '
                f"A nurse should confirm. {_NOTE}")
        for rid in flagged(ids)
    ]


def merge(decision: triage_rules.Decision, extra: list[triage_rules.ShortcutResult]) -> triage_rules.Decision:
    """Add the checklist and AI results to the most-urgent-wins decision.

    They can only raise the visible level (to ESI 2), never lower it. The rule
    that already set the level keeps it on a tie, so the stored rule stays the
    one that fired first.
    """
    if not extra:
        return decision
    level, rule = decision.esi_level, decision.rule
    best = min(extra, key=lambda r: r.esi_level)
    if best.esi_level < level:
        level, rule = best.esi_level, best
    fired = list(decision.fired)
    for r in extra:
        if r.esi_level <= level and all(f.reason != r.reason for f in fired):
            fired.append(r)
    fired.sort(key=lambda r: r.esi_level)
    crisis = (decision.crisis or any(r.crisis for r in extra)) and level >= 2
    return triage_rules.Decision(level, decision.model_esi_level, rule, tuple(fired), crisis)
