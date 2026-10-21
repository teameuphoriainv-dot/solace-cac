"""Possible diagnoses for the clinician (the ``/ddx/v2`` endpoint).

With an AI key, Claude drafts a short ranked list of considerations for the
clinician. The red-flag list and the coverage sets come from the shared,
deterministic helpers in ``services/differential.py``:

  - ``differential.match_red_flags``: keyword match against the don't-miss list.
  - ``differential.conformal_sets``: the 90% and 95% coverage sets.
  - ``differential.counterfactual_prompts``: "what would change the ranking"
    questions, merged with the model's own.

Without a key nothing is drafted: the response says AI reasoning is off and
still returns the keyword red-flag matches, which need no AI. When the AI call
itself fails the answer has the same no-AI shape with ``source`` "ai_failed" and
``ai_available`` False, so no screen labels it an AI draft. Nothing here ever
acts on its own or replaces the triage score.
"""
from __future__ import annotations

import contextvars
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lib import claude, json_extract
from lib.content_guard import strip_dashes_deep
from lib.config import settings
from services import differential

log = logging.getLogger(__name__)

_MODEL = settings.model_clinical

# The red-flag library itself lives in services/differential.py.
RED_FLAGS = differential.RED_FLAG_LIBRARY


_SYSTEM = """You are an experienced ED attending. Draft a short list of possible diagnoses \
for the treating clinician to consider. The clinician decides; you only list considerations.

Return JSON ONLY (no markdown):
{
  "differential": [
    {
      "diagnosis": "short Dx name",
      "icd10": "best-guess ICD-10",
      "weight": 0.0-1.0,
      "supporting": ["clinical feature arguing FOR this Dx", "..."],
      "refuting": ["what argues against / what is missing", "..."],
      "discriminator": "single best discriminating test or maneuver",
      "reasoning": "1-2 sentence clinical rationale tying the case to this Dx",
      "must_not_miss": false,
      "evidence_quote": "verbatim short snippet from the transcript that anchored this Dx"
    }
  ],
  "counterfactuals": [
    {
      "question": "what additional history/finding would change the ranking?",
      "discriminates": ["Dx A", "Dx B"],
      "why": "which Dx rises/falls and why"
    }
  ]
}

Rules:
- Return 3 to 5 entries. weight is your pretest probability; weights sum to about 1.0.
- Bias pretest probabilities toward the SPECIALTY context provided.
- Anchor every entry to at least one fact from the transcript in "supporting". Never invent findings.
- Keep every string short: phrases, not paragraphs. "reasoning" is one sentence.
- "discriminator": one concrete next step, not a list.
- counterfactuals: 2 to 3 entries on what would change the ranking.
- Set must_not_miss true ONLY for life or limb threats with at least one supporting feature.
- Never use em dashes or en dashes.
"""


def _build_prompt(
    transcript: str,
    chief_complaint: str,
    medical_info: dict[str, Any] | None,
    specialty: str,
    vitals: dict[str, Any] | None,
) -> str:
    parts = [
        f"Specialty context: {specialty.upper()}",
        f"Chief complaint: {chief_complaint or '(infer from transcript)'}",
        f'Transcript:\n"""\n{transcript[:8000]}\n"""',
    ]
    if medical_info:
        parts.append(f"Medical history: {json.dumps(medical_info)[:1200]}")
    if vitals:
        v = ", ".join(f"{k}={val}" for k, val in vitals.items() if val is not None)
        if v:
            parts.append(f"Bedside vitals: {v}")
    parts.append("Return JSON now.")
    return "\n\n".join(parts)


def _call_llm(prompt: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Run the specialty-biased Claude call. Returns ``(differential, cf, failed)``;
    ``failed`` is True when the call itself did not come back."""
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=2000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            purpose="ddx_v2",
        )
    except Exception as e:  # noqa: BLE001 - decision support degrades gracefully
        log.warning("ddx_v2 LLM call failed: %s", type(e).__name__)
        return [], [], True
    try:
        text = "".join(getattr(b, "text", "") for b in resp.content)
        # Tolerant parse: handles markdown fences and output truncated at the
        # token ceiling (which silently broke this on the chattier model).
        parsed = json_extract.extract_obj(text)
        if not parsed:
            return [], [], False
        parsed = strip_dashes_deep(parsed)
        return _clean_differential(parsed.get("differential")), _clean_counterfactuals(
            parsed.get("counterfactuals")
        ), False
    except Exception as e:  # noqa: BLE001
        log.warning("ddx_v2 reply could not be read: %s", type(e).__name__)
        return [], [], False


def _clean_differential(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        dx = str(item.get("diagnosis", "")).strip()
        if not dx:
            continue
        try:
            weight = float(item.get("weight", 0.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        out.append(
            {
                "diagnosis": dx,
                "icd10": str(item.get("icd10", "")).strip(),
                "weight": max(0.0, min(1.0, weight)),
                "supporting": _str_list(item.get("supporting") or item.get("rule_in")),
                "refuting": _str_list(item.get("refuting") or item.get("rule_out")),
                "discriminator": str(
                    item.get("discriminator") or item.get("next_step") or ""
                ).strip(),
                "reasoning": str(item.get("reasoning", "")).strip(),
                "must_not_miss": bool(item.get("must_not_miss")),
                "evidence_quote": str(item.get("evidence_quote", "")).strip(),
            }
        )
        if len(out) >= 6:
            break
    return out


def _clean_counterfactuals(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        # Accept both the new {question,...} schema and the legacy
        # {if_true, would_change} schema.
        question = str(item.get("question") or item.get("if_true") or "").strip()
        if not question:
            continue
        out.append(
            {
                "question": question,
                "discriminates": _str_list(item.get("discriminates")),
                "why": str(item.get("why") or item.get("would_change") or "").strip(),
            }
        )
    return out


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()][:4]


_OFF_MESSAGE = (
    "AI reasoning is off on this server, so no list of possible diagnoses was drafted. "
    "Nothing here is made up to fill the gap."
)
_NOT_DRAFTED = "No list of possible diagnoses was drafted, and nothing here is made up to fill the gap."
_FAILED_MESSAGE = (
    "The AI did not answer this time, so no list of possible diagnoses was drafted. "
    "Try again in a few minutes. Nothing here is made up to fill the gap."
)
_OFF_RED_FLAGS = (
    " The don't-miss list below is a fixed keyword check of the patient's words, not AI."
)


def _without_ai(red_flags: list[dict[str, Any]], *, source: str, message: str) -> dict[str, Any]:
    """The answer when no AI list was drafted: the keyword red flags only."""
    return {
        "differential": [],
        "counterfactuals": [],
        "red_flags": red_flags,
        "conformal": differential.conformal_sets([]),
        "ai_available": False,
        "source": source,
        "message": message + (_OFF_RED_FLAGS if red_flags else ""),
    }
_EMPTY_MESSAGE = (
    "The AI did not return any possible diagnoses for this visit. "
    "Try again, or reason from the chart directly."
)


def generate(
    transcript: str,
    chief_complaint: str = "",
    *,
    medical_info: dict[str, Any] | None = None,
    specialty: str = "ed",
    vitals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Specialty-biased considerations with coverage sets and the red-flag list.

    Output shape:
        {
          "differential":    [ {diagnosis, icd10, weight, supporting, refuting,
                                 discriminator, reasoning, must_not_miss,
                                 evidence_quote, rule_in, rule_out, next_step}, ... ],
          "counterfactuals": [ {question, discriminates, why, if_true, would_change}, ... ],
          "red_flags":       [ {diagnosis, icd10, group, must_not_miss}, ... ],
          "conformal":       {set_90, set_95, nonconformity, threshold_90, threshold_95},
          "ai_available":    bool,
          "message":         str (only when there is something to explain),
        }
    ``rule_in`` / ``rule_out`` / ``next_step`` and ``if_true`` / ``would_change``
    repeat the same values under the names the clinician screen reads.
    """
    red_flag_text = f"{transcript} {chief_complaint}"

    if not claude.available():
        red_flags = differential.match_red_flags(red_flag_text)
        kind = claude.off_kind()
        if kind == "provider_error":
            return _without_ai(red_flags, source="ai_failed", message=_FAILED_MESSAGE)
        message = _OFF_MESSAGE if kind == "no_key" else f"{claude.off_reason()} {_NOT_DRAFTED}"
        return _without_ai(red_flags, source="no_ai", message=message)

    prompt = _build_prompt(transcript, chief_complaint, medical_info, specialty, vitals)

    # The LLM call and the cheap red-flag scan are independent, so the scan
    # never waits behind the network round trip. Pool threads start with empty
    # context variables, so the call runs in a copy of this request's context and
    # counts against the visitor's hourly AI limit (lib/spend.py).
    with ThreadPoolExecutor(max_workers=2) as pool:
        llm_future = pool.submit(contextvars.copy_context().run, _call_llm, prompt)
        rf_future = pool.submit(differential.match_red_flags, red_flag_text)
        diff, llm_counterfactuals, failed = llm_future.result()
        red_flags = rf_future.result()
    if failed:
        return _without_ai(red_flags, source="ai_failed", message=_FAILED_MESSAGE)
    model_returned = bool(diff)

    # Fold any missing don't-miss diagnoses into the list.
    diff_names = {d["diagnosis"].lower() for d in diff}
    for rf in red_flags:
        if rf["diagnosis"].lower() in diff_names:
            for d in diff:
                if d["diagnosis"].lower() == rf["diagnosis"].lower():
                    d["must_not_miss"] = True
            continue
        group = str(rf.get("group", "")).replace("_", " ")
        diff.append(
            {
                "diagnosis": rf["diagnosis"],
                "icd10": rf["icd10"],
                "weight": 0.05,
                "supporting": ["red-flag keyword match: verify by exam or test"],
                "refuting": [],
                "discriminator": "rule out per local pathway",
                "reasoning": f"Don't-miss condition for a {group} complaint, from the fixed red-flag list.",
                "must_not_miss": True,
                "evidence_quote": "",
            }
        )

    diff.sort(key=lambda d: d.get("weight", 0.0), reverse=True)
    for d in diff:
        d["rule_in"] = d.get("supporting", [])
        d["rule_out"] = d.get("refuting", [])
        d["next_step"] = d.get("discriminator", "")

    conformal = differential.conformal_sets(diff)
    counterfactuals = _merge_counterfactuals(
        llm_counterfactuals, differential.counterfactual_prompts(diff)
    )
    for c in counterfactuals:
        c.setdefault("if_true", c.get("question", ""))
        c.setdefault("would_change", c.get("why", ""))

    out: dict[str, Any] = {
        "differential": diff,
        "counterfactuals": counterfactuals,
        "red_flags": red_flags,
        "conformal": conformal,
        "ai_available": True,
        "source": "claude",
        "label": "Considerations for the clinician to review. Not a diagnosis.",
    }
    if not model_returned:
        out["message"] = _EMPTY_MESSAGE
    return out


def _merge_counterfactuals(
    llm: list[dict[str, Any]], baseline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(llm) + list(baseline):
        q = str(item.get("question", "")).strip()
        if not q:
            continue
        norm = q.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(item)
    return out[:6]
