"""Ambient scribe: turns a recorded clinician and patient conversation into a
SOAP-style note where every line links back to what was said.

The clinician records in chunks (start, append, pause, resume, finalize). On
finalize:

* With an AI key, one Claude call splits the conversation into segments and
  writes the note sections, each line citing the segments that support it. A
  second, optional pass tidies the style without adding facts.
* Without a key (or if the AI call fails or the text is blocked by the content
  guard), the note is built from exactly what was captured: each captured chunk
  becomes one Subjective line linked to itself, and Assessment and Plan say the
  clinician must complete them. Nothing is invented.

Every line's ``evidence_segments`` ids are resolved into renderable evidence
(``linked_evidence`` and ``evidence_span``), and each section reports how many
of its lines carry a citation (``evidence_coverage``). Each section's lines are
returned under both ``summary`` and ``lines``.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from lib import claude, content_guard, json_extract
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = settings.model_clinical

# Canonical SOAP section names the pipeline knows how to render.
_KNOWN_SECTIONS = (
    "SUBJECTIVE", "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
    "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    "DISPOSITION",
)

# Specialty-aware section ordering. Each entry lists the sections in the order
# a clinician of that specialty expects to read them. SUBJECTIVE is only used by
# the verbatim note, so it leads every order.
_SPECIALTY_SECTION_ORDER: dict[str, tuple[str, ...]] = {
    "emergency": (
        "SUBJECTIVE", "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
        "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
        "DISPOSITION",
    ),
    "primary_care": (
        "SUBJECTIVE", "CHIEF_COMPLAINT", "HPI", "PAST_MEDICAL_HISTORY", "MEDICATIONS",
        "ALLERGIES", "REVIEW_OF_SYSTEMS", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    ),
    "cardiology": (
        "SUBJECTIVE", "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
        "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    ),
    "pediatrics": (
        "SUBJECTIVE", "CHIEF_COMPLAINT", "HPI", "REVIEW_OF_SYSTEMS", "PAST_MEDICAL_HISTORY",
        "MEDICATIONS", "ALLERGIES", "PHYSICAL_EXAM", "ASSESSMENT", "PLAN",
    ),
}
_DEFAULT_SPECIALTY = "emergency"

# Per-specialty guidance injected into the synthesis system prompt so the model
# emphasizes the fields that specialty cares about most.
_SPECIALTY_GUIDANCE: dict[str, str] = {
    "emergency": (
        "Specialty: Emergency Medicine. Lead the assessment with acuity and the "
        "must-not-miss differential. Populate DISPOSITION (admit, observe, "
        "discharge or transfer) only if it was discussed, and red-flag return "
        "precautions in PLAN."
    ),
    "primary_care": (
        "Specialty: Primary Care. Emphasize chronic disease context, preventive "
        "care gaps, and medication reconciliation. DISPOSITION is usually routine "
        "follow-up; omit it unless escalation is discussed."
    ),
    "cardiology": (
        "Specialty: Cardiology. Capture cardiac risk factors, exertional symptoms, "
        "NYHA or CCS class where stated, and prior cardiac workup. PHYSICAL_EXAM "
        "should foreground cardiopulmonary findings."
    ),
    "pediatrics": (
        "Specialty: Pediatrics. Note weight-based dosing context, immunization "
        "status, developmental milestones, and caregiver-reported history; the "
        "historian is often a parent, not the patient."
    ),
}

# What the verbatim note says, by why AI drafting did not run. "verbatim_no_ai" with a
# key set (a budget or rate pause) uses the "paused" wording and the pause's reason.
_VERBATIM: dict[str, dict[str, str]] = {
    "verbatim_no_ai": {
        "placeholder": "Clinician to complete (AI drafting is off on this server)",
        "message": (
            "AI drafting is off on this server, so this note lists exactly what was "
            "captured. Write the assessment and plan yourself."
        ),
    },
    "paused": {
        "placeholder": "Clinician to complete (AI drafting is paused right now)",
        "message": "This note lists exactly what was captured. Write the assessment and plan yourself.",
    },
    "verbatim_ai_failed": {
        "placeholder": "Clinician to complete (the AI draft did not come back)",
        "message": (
            "The AI could not draft this note, so it lists exactly what was "
            "captured. Try finalizing again later, or finish the note by hand."
        ),
    },
    "verbatim_guard": {
        "placeholder": "Clinician to complete (AI drafting was skipped for this text)",
        "message": (
            "Part of the conversation looked like instructions to the AI, so AI "
            "drafting was skipped. The note lists exactly what was captured."
        ),
    },
}

_REGEN_OFF_MESSAGE = (
    "AI drafting is off on this server, so sections cannot be redone automatically. "
    "Edit the note text directly."
)
_REGEN_FAILED_MESSAGE = (
    "The AI could not redo that section this time, so the note is unchanged. "
    "Try again in a few minutes, or edit the text yourself."
)


def _resolve_specialty(specialty: str | None) -> str:
    """Map a free-form specialty hint to a known key, defaulting to emergency."""
    if not specialty:
        return _DEFAULT_SPECIALTY
    key = specialty.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ed": "emergency", "er": "emergency", "emergency_medicine": "emergency",
        "family_medicine": "primary_care", "internal_medicine": "primary_care",
        "gp": "primary_care", "peds": "pediatrics", "cards": "cardiology",
    }
    key = aliases.get(key, key)
    return key if key in _SPECIALTY_SECTION_ORDER else _DEFAULT_SPECIALTY


def _section_order(specialty: str | None) -> tuple[str, ...]:
    return _SPECIALTY_SECTION_ORDER[_resolve_specialty(specialty)]


_SYNTH_SYSTEM = """You convert a doctor and patient conversation transcript into a clinical \
note with Linked Evidence: every line of the note cites the transcript segments that support it.

Return JSON ONLY (no markdown, no preamble):
{
  "sections": [
    {
      "name": "CHIEF_COMPLAINT" | "HPI" | "REVIEW_OF_SYSTEMS" | "PAST_MEDICAL_HISTORY" | "MEDICATIONS" | "ALLERGIES" | "PHYSICAL_EXAM" | "ASSESSMENT" | "PLAN" | "DISPOSITION",
      "summary": [
        {"text": "one sentence of the section in clinical shorthand", "evidence_segments": [3, 5]}
      ]
    }
  ],
  "transcript_segments": [
    {"id": 0, "speaker": "CLINICIAN" | "PATIENT", "begin_ms": 0, "end_ms": 4000, "content": "the utterance"}
  ]
}

Rules:
- Split the transcript into utterance-level segments, about 3 to 8 seconds each.
- The speaker tag is your best inference (clinician asks or orders, patient describes or answers).
- evidence_segments must reference REAL segment ids in transcript_segments.
- EVERY summary line MUST cite at least one evidence segment.
- Use clinical shorthand: c/o, hx, sx, SOB, N/V, abd, NKDA, etc. Keep lines short.
- NEVER invent facts not present in the transcript. Omit a section that has no support.
- ASSESSMENT lines start with 'AI draft: '. PLAN: one short sentence per line.
- Never use em dashes or en dashes.
"""

_REGEN_SECTION_SYSTEM = """You are a medical scribe regenerating ONE section of an existing \
clinical note from the conversation transcript. The transcript segments are given with their \
integer ids. Re-derive ONLY the requested section.

Return JSON ONLY:
{"name": "<SECTION_NAME>", "summary": [{"text": "...", "evidence_segments": [int, ...]}]}

Rules:
- evidence_segments must reference REAL segment ids from the supplied transcript.
- EVERY summary line MUST cite at least one evidence segment.
- Clinical shorthand, short lines. Never invent facts absent from the transcript.
- ASSESSMENT lines start with 'AI draft: '. PLAN as short sentences.
- Never use em dashes or en dashes.
"""


def _claude_json(*, system: str, user: str, max_tokens: int, purpose: str) -> dict[str, Any]:
    """Single synchronous Claude call returning parsed JSON. Raises on failure."""
    resp = claude.messages_create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        purpose=purpose,
    )
    text = "".join(getattr(b, "text", "") for b in resp.content)
    data = json_extract.extract_obj(text)
    if data is None:
        raise ValueError("model did not return a JSON object")
    return content_guard.strip_dashes_deep(data)


# ---- Linked Evidence resolution --------------------------------------------------
def _segment_index(structured: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map segment id -> segment dict for O(1) evidence lookups."""
    index: dict[int, dict[str, Any]] = {}
    for seg in structured.get("transcript_segments", []) or []:
        if not isinstance(seg, dict):
            continue
        try:
            index[int(seg.get("id"))] = seg
        except (TypeError, ValueError):
            continue
    return index


def _snippet(content: str, limit: int = 180) -> str:
    content = (content or "").strip()
    return content if len(content) <= limit else content[: limit - 1].rstrip() + "…"


def _section_lines(section: dict[str, Any]) -> list[dict[str, Any]]:
    """A section's lines, whether they arrive as ``summary`` or ``lines``."""
    raw = section.get("summary")
    if not isinstance(raw, list) or not raw:
        raw = section.get("lines")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, dict):
            out.append(entry)
        elif isinstance(entry, str) and entry.strip():
            out.append({"text": entry.strip(), "evidence_segments": []})
    return out


def resolve_linked_evidence(structured: dict[str, Any]) -> dict[str, Any]:
    """Resolve each note line's ``evidence_segments`` ids into concrete evidence.

    For every line this adds ``linked_evidence`` (``{segment_id, begin_ms,
    end_ms, speaker, snippet}`` in transcript order) and ``evidence_span``
    (``{begin_ms, end_ms, segment_ids}`` or None). Each section gets
    ``evidence_coverage``, the share of its lines with at least one resolvable
    citation, and its lines under both ``summary`` and ``lines``. Mutates and
    returns ``structured``.
    """
    index = _segment_index(structured)
    sections = [s for s in (structured.get("sections") or []) if isinstance(s, dict)]
    for section in sections:
        summary = _section_lines(section)
        cited_lines = 0
        for entry in summary:
            raw_ids = entry.get("evidence_segments", []) or []
            if not isinstance(raw_ids, list):
                raw_ids = []
            linked: list[dict[str, Any]] = []
            seen: set[int] = set()
            for rid in raw_ids:
                try:
                    sid = int(rid)
                except (TypeError, ValueError):
                    continue
                seg = index.get(sid)
                if seg is None or sid in seen:
                    continue
                seen.add(sid)
                linked.append({
                    "segment_id": sid,
                    "begin_ms": int(seg.get("begin_ms", 0) or 0),
                    "end_ms": int(seg.get("end_ms", 0) or 0),
                    "speaker": seg.get("speaker", "") or "",
                    "snippet": _snippet(seg.get("content", "")),
                })
            linked.sort(key=lambda e: (e["begin_ms"], e["segment_id"]))
            entry["text"] = str(entry.get("text", ""))
            entry["linked_evidence"] = linked
            if linked:
                cited_lines += 1
                entry["evidence_span"] = {
                    "begin_ms": min(e["begin_ms"] for e in linked),
                    "end_ms": max(e["end_ms"] for e in linked),
                    "segment_ids": [e["segment_id"] for e in linked],
                }
            else:
                entry["evidence_span"] = None
        section["name"] = str(section.get("name", "")).upper().replace(" ", "_")
        section["summary"] = summary
        section["lines"] = summary
        section["evidence_coverage"] = round(cited_lines / len(summary), 3) if summary else 0.0
    structured["sections"] = sections
    return structured


# ---- Verbatim note (no AI) -------------------------------------------------------
def verbatim_note(transcript: str, *, specialty: str | None = None, source: str = "verbatim_no_ai") -> dict[str, Any]:
    """Build the note from exactly what was captured, with no AI.

    Each non-empty line of the transcript (one per captured chunk) becomes a
    segment and one Subjective line citing it. Assessment and Plan carry a
    single "clinician to complete" line. No AI wrote any of it, so ``ai_available``
    is always False.
    """
    copy = dict(_VERBATIM.get(source, _VERBATIM["verbatim_no_ai"]))
    if source == "verbatim_no_ai" and claude.configured():
        copy = dict(_VERBATIM["paused"])
        copy["message"] = f"{claude.off_reason()} {copy['message']}"
    chunks = [c.strip() for c in (transcript or "").splitlines() if c.strip()]
    segments = [
        {"id": i, "speaker": "UNLABELED", "begin_ms": 0, "end_ms": 0, "content": chunk}
        for i, chunk in enumerate(chunks)
    ]
    sections = [
        {
            "name": "SUBJECTIVE",
            "summary": [{"text": chunk, "evidence_segments": [i]} for i, chunk in enumerate(chunks)],
        },
        {"name": "ASSESSMENT", "summary": [{"text": copy["placeholder"], "evidence_segments": []}]},
        {"name": "PLAN", "summary": [{"text": copy["placeholder"], "evidence_segments": []}]},
    ]
    structured = {
        "sections": sections,
        "transcript_segments": segments,
        "specialty": _resolve_specialty(specialty),
        "source": source,
        "ai_available": False,
        "message": copy["message"],
    }
    return resolve_linked_evidence(structured)


# ---- Synthesis -------------------------------------------------------------------
def synthesize_from_transcript(
    transcript: str,
    *,
    specialty: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """One Claude call returns segments, sections and evidence links.

    Falls back to :func:`verbatim_note` when there is no key, when the content
    guard blocks the text, or when the call fails or returns nothing usable.
    """
    spec = _resolve_specialty(specialty)
    if not claude.available():
        # A refusal from the AI service pauses AI: say the draft did not come back.
        failed = claude.off_kind() == "provider_error"
        return verbatim_note(transcript, specialty=spec,
                             source="verbatim_ai_failed" if failed else "verbatim_no_ai")

    safe, cleaned, findings = content_guard.scan(
        transcript, label="ambient_scribe", source_ip=source_ip, user_agent=user_agent
    )
    if not safe:
        log.warning("scribe synth blocked by content_guard: %s", findings)
        return verbatim_note(transcript, specialty=spec, source="verbatim_guard")

    system = _SYNTH_SYSTEM + "\n\n" + _SPECIALTY_GUIDANCE.get(spec, "")
    user = (
        f'Transcript:\n"""\n{cleaned[:14000]}\n"""\n\n'
        "Return the JSON now."
    )
    try:
        data = _claude_json(
            system=system, user=user, max_tokens=3000, purpose="ambient_scribe_synth"
        )
        structured = _finalize_structured(data, specialty=spec)
    except Exception as e:  # noqa: BLE001 - fall back to the verbatim note
        log.warning("scribe synth failed: %s", type(e).__name__)
        return verbatim_note(transcript, specialty=spec, source="verbatim_ai_failed")
    if not any(_section_lines(s) for s in structured.get("sections", [])):
        return verbatim_note(transcript, specialty=spec, source="verbatim_ai_failed")
    structured["source"] = "claude"
    structured["ai_available"] = True
    return structured


def _finalize_structured(data: dict[str, Any], *, specialty: str) -> dict[str, Any]:
    """Normalize ids, drop dangling evidence refs, order sections, resolve evidence."""
    segments = [s for s in (data.get("transcript_segments") or []) if isinstance(s, dict)]
    sections = [s for s in (data.get("sections") or []) if isinstance(s, dict)]
    data["transcript_segments"] = segments
    data["sections"] = sections

    ids = {int(s.get("id", -1)) for s in segments if str(s.get("id", "")).lstrip("-").isdigit()}
    for sec in sections:
        sec["name"] = str(sec.get("name", "")).upper().replace(" ", "_")
        lines = _section_lines(sec)
        for entry in lines:
            raw = entry.get("evidence_segments", []) or []
            entry["evidence_segments"] = [
                int(i) for i in (raw if isinstance(raw, list) else [])
                if str(i).lstrip("-").isdigit() and int(i) in ids
            ]
        sec["summary"] = lines

    order = _section_order(specialty)
    rank = {name: i for i, name in enumerate(order)}
    sections.sort(key=lambda s: rank.get(s.get("name", ""), len(order)))
    data["specialty"] = specialty
    return resolve_linked_evidence(data)


# ---- Refinement layer (style transfer) -------------------------------------------
_REFINE_SYSTEM = """Refine an AI-generated clinical note in a consistent house style WITHOUT \
introducing any new facts. Preserve the section structure and the evidence_segments arrays exactly.

Style:
- Clinical shorthand (c/o, hx, sx, SOB, N/V, abd, NKDA, etc.)
- HPI 60 words or fewer
- ASSESSMENT lines start with 'AI draft: '
- PLAN as short sentences
- No invented vitals, exam findings, labs, or doses
- Never use em dashes or en dashes

Return JSON in the exact same shape received. Keep every summary entry's \
evidence_segments array EXACTLY as received. Do not modify transcript_segments.
"""


def refine(structured: dict[str, Any]) -> dict[str, Any]:
    """Style-transfer pass. Preserves transcript_segments and re-resolves Linked
    Evidence afterward (refine may not echo the resolved fields). Skipped for
    the verbatim note, which must stay exactly as captured."""
    if not claude.available() or not structured.get("sections"):
        return structured
    if str(structured.get("source", "")).startswith("verbatim"):
        return structured
    try:
        slim = {
            "sections": [
                {
                    "name": s.get("name"),
                    "summary": [
                        {"text": e.get("text", ""), "evidence_segments": e.get("evidence_segments", [])}
                        for e in _section_lines(s)
                    ],
                }
                for s in structured.get("sections", [])
            ],
            "transcript_segments": structured.get("transcript_segments", []),
        }
        out = _claude_json(
            system=_REFINE_SYSTEM, user=json.dumps(slim), max_tokens=2200,
            purpose="ambient_scribe_refine",
        )
        if not any(_section_lines(s) for s in (out.get("sections") or []) if isinstance(s, dict)):
            return structured
        out["transcript_segments"] = structured["transcript_segments"]
        out = _finalize_structured(out, specialty=structured.get("specialty", _DEFAULT_SPECIALTY))
        out["source"] = structured.get("source", "claude")
        out["ai_available"] = True
        return out
    except Exception as e:  # noqa: BLE001 - keep the unrefined note
        log.warning("scribe refine failed: %s", type(e).__name__)
        return structured


# ---- Regenerate a single section (no re-recording) -------------------------------
def _regenerate_section_payload(
    structured: dict[str, Any], section_name: str, specialty: str | None
) -> dict[str, Any] | None:
    """Run one Claude call to re-derive ``section_name`` from the transcript.
    Returns a section dict or None on failure."""
    segments = [s for s in (structured.get("transcript_segments") or []) if isinstance(s, dict)]
    if not segments:
        return None
    spec = _resolve_specialty(specialty or structured.get("specialty"))
    transcript_lines = "\n".join(
        f'[{s.get("id")}] {s.get("speaker", "?")}: {s.get("content", "")}'
        for s in segments
    )
    user = (
        f"{_SPECIALTY_GUIDANCE.get(spec, '')}\n\n"
        f"Section to regenerate: {section_name}\n\n"
        f"Transcript segments:\n{transcript_lines[:14000]}\n\n"
        "Return the JSON for that one section now."
    )
    data = _claude_json(
        system=_REGEN_SECTION_SYSTEM, user=user, max_tokens=900,
        purpose="ambient_scribe_regen_section",
    )
    ids = {int(s.get("id", -1)) for s in segments if str(s.get("id", "")).lstrip("-").isdigit()}
    lines = _section_lines(data)
    for entry in lines:
        raw = entry.get("evidence_segments", []) or []
        entry["evidence_segments"] = [
            int(i) for i in (raw if isinstance(raw, list) else [])
            if str(i).lstrip("-").isdigit() and int(i) in ids
        ]
    if not lines:
        return None
    return {"name": str(data.get("name", section_name)).upper().replace(" ", "_"),
            "summary": lines}


def regenerate_section(
    structured: dict[str, Any], section_name: str, *, specialty: str | None = None
) -> dict[str, Any]:
    """Re-derive ONE section from the existing transcript without touching the
    rest of the note and without re-recording audio.

    Returns the updated ``structured`` dict (other sections untouched, Linked
    Evidence re-resolved). Without a key, or on failure, the note comes back
    unchanged with ``ai_available`` False and a ``message`` saying why; when the AI
    call itself failed, ``regen_status`` is "ai_failed" (the note's own ``source``
    still says how it was first built).
    """
    structured = dict(structured or {})
    structured.setdefault("sections", [])
    structured.setdefault("transcript_segments", [])
    if not claude.available():
        structured = resolve_linked_evidence(structured)
        structured["ai_available"] = False
        structured["regen_status"] = "no_ai"
        structured["message"] = (_REGEN_OFF_MESSAGE if claude.off_kind() == "no_key"
                                 else f"{claude.off_reason()} Edit the note text directly.")
        return structured
    name = str(section_name).upper().replace(" ", "_")
    try:
        regenerated = _regenerate_section_payload(structured, name, specialty)
    except Exception as e:  # noqa: BLE001
        log.warning("regenerate_section %s failed: %s", name, type(e).__name__)
        structured = resolve_linked_evidence(structured)
        structured["ai_available"] = False
        structured["regen_status"] = "ai_failed"
        structured["message"] = _REGEN_FAILED_MESSAGE
        return structured
    if regenerated is None:
        structured = resolve_linked_evidence(structured)
        structured["ai_available"] = True
        structured["message"] = "That section could not be redone right now. The note is unchanged."
        return structured
    by_name = {
        str(s.get("name", "")).upper(): s
        for s in structured.get("sections", []) if isinstance(s, dict)
    }
    by_name[name] = regenerated
    spec = _resolve_specialty(specialty or structured.get("specialty"))
    order = _section_order(spec)
    rank = {n: i for i, n in enumerate(order)}
    structured["sections"] = sorted(
        by_name.values(), key=lambda s: rank.get(s.get("name", ""), len(order))
    )
    structured["specialty"] = spec
    structured["ai_available"] = True
    structured.pop("message", None)
    structured.pop("regen_status", None)
    return resolve_linked_evidence(structured)


# ---- Pause / resume: chunked recording sessions ----------------------------------
# A long encounter is recorded in pieces. The clinician can pause (stop sending
# chunks) and resume (send more) without losing prior text. Sessions live in
# process memory, so a server restart ends them.
_SESSIONS: dict[str, dict[str, Any]] = {}
_MAX_SESSIONS = 500


def start_session(*, specialty: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    """Open a chunked-recording session. Returns ``{session_id, specialty, status}``."""
    if session_id and session_id in _SESSIONS:
        sess = _SESSIONS[session_id]
        return {"session_id": session_id, "specialty": sess["specialty"], "status": sess["status"]}
    if len(_SESSIONS) >= _MAX_SESSIONS:
        oldest = min(_SESSIONS, key=lambda k: _SESSIONS[k]["updated_ms"])
        _SESSIONS.pop(oldest, None)
    sid = session_id or f"scribe-sess-{uuid.uuid4().hex[:12]}"
    now = int(time.time() * 1000)
    _SESSIONS[sid] = {
        "session_id": sid,
        "specialty": _resolve_specialty(specialty),
        "chunks": [],
        "status": "recording",
        "created_ms": now,
        "updated_ms": now,
    }
    return {"session_id": sid, "specialty": _SESSIONS[sid]["specialty"], "status": "recording"}


def append_transcript_chunk(session_id: str, chunk: str) -> dict[str, Any]:
    """Append a transcript chunk to an in-progress session. No model call here:
    chunks just accumulate so the clinician can pause and resume freely."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"status": "unknown_session", "session_id": session_id}
    if chunk and chunk.strip():
        sess["chunks"].append(" ".join(chunk.split()))
    sess["updated_ms"] = int(time.time() * 1000)
    sess["status"] = "recording"
    return {"session_id": session_id, "status": "recording", "chunk_count": len(sess["chunks"])}


def pause_session(session_id: str) -> dict[str, Any]:
    """Mark a session paused. Text captured so far is kept."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"status": "unknown_session", "session_id": session_id}
    sess["status"] = "paused"
    sess["updated_ms"] = int(time.time() * 1000)
    return {"session_id": session_id, "status": "paused", "chunk_count": len(sess["chunks"])}


def resume_session(session_id: str) -> dict[str, Any]:
    """Resume a paused session so further chunks can be appended."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"status": "unknown_session", "session_id": session_id}
    sess["status"] = "recording"
    sess["updated_ms"] = int(time.time() * 1000)
    return {"session_id": session_id, "status": "recording", "chunk_count": len(sess["chunks"])}


def session_transcript(session_id: str) -> str:
    """Return the concatenated transcript accumulated for a session."""
    sess = _SESSIONS.get(session_id)
    return "\n".join(sess["chunks"]) if sess else ""


def finalize_session(
    session_id: str, *, source_ip: str | None = None, user_agent: str | None = None,
    refine_note: bool = True,
) -> dict[str, Any]:
    """Close a chunked session: build the full note from all chunks in one
    pass. Marks the session ``finalized`` and returns the structured note."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"sections": [], "transcript_segments": [], "error": "unknown_session"}
    transcript = "\n".join(sess["chunks"])
    if not transcript.strip():
        return {"sections": [], "transcript_segments": [], "error": "empty_session"}
    structured = synthesize_from_transcript(
        transcript, specialty=sess["specialty"], source_ip=source_ip, user_agent=user_agent
    )
    if refine_note and structured.get("source") == "claude":
        structured = refine(structured)
    sess["status"] = "finalized"
    sess["updated_ms"] = int(time.time() * 1000)
    structured["session_id"] = session_id
    return structured


# ---- Convenience: render to plain SOAP text --------------------------------------
def to_soap_text(structured: dict[str, Any]) -> str:
    """Render the structured note to plain SOAP text, ordered for its specialty."""
    order = _section_order(structured.get("specialty"))
    by_name = {
        str(s.get("name", "")): s
        for s in (structured.get("sections") or []) if isinstance(s, dict)
    }
    lines: list[str] = []
    names = [n for n in order if n in by_name] + [n for n in by_name if n not in order]
    for name in names:
        sec = by_name[name]
        lines.append(f"{name.replace('_', ' ').title()}:")
        for entry in _section_lines(sec):
            lines.append(f"  - {entry.get('text', '')}")
        lines.append("")
    return "\n".join(lines).strip()
