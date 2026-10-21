"""The five example patients every demo hospital starts with (ESI 1 to 5).

Each one is scored by the same check-in pipeline as a real walk-in
(services/intake_pipeline.py), so the queue shows what the app really does with
these words. Nothing here calls an AI service or the network, even when keys are
set: the clinician summaries, comfort cards and orders are the built-in no-AI
versions. All names and stories are made up.

Called at startup, when a private demo hospital is created, and by reset-demo.
"""
from __future__ import annotations

import contextvars
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from db import storage
from db.constants import STATUS_WAITING
from services import intake_artifacts, intake_pipeline

log = logging.getLogger(__name__)

_NONE = ["None"]

# name, language, words, medical form, minutes waiting, "I feel worse" pressed, follow-up answers
CANONICAL: list[dict[str, Any]] = [
    {
        "name": "Marcus", "language": "en", "waited": 4, "pain_flagged": False, "qa": [],
        "transcript": ("My face started drooping on the left side about 30 minutes ago, my speech is slurred, "
                       "and my left arm feels weak."),
        "info": {"age": 67, "sex": "male", "pregnant": None, "allergies": _NONE,
                 "medications": ["Lisinopril"], "conditions": ["Hypertension", "High cholesterol"]},
    },
    {
        "name": "Elena", "language": "es", "waited": 11, "pain_flagged": False, "qa": [],
        "transcript": "Tengo un dolor muy fuerte en el pecho que me baja por el brazo izquierdo y estoy sudando.",
        "info": {"age": 58, "sex": "female", "pregnant": False, "allergies": _NONE,
                 "medications": ["Metformin"], "conditions": ["Diabetes"]},
    },
    {
        "name": "Priya", "language": "en", "waited": 27, "pain_flagged": True, "qa": [],
        "transcript": ("I have a severe headache with vomiting for two days. Light makes it worse. "
                       "I have a history of migraines but this one is different, more intense. Pain is 8 out of 10."),
        "info": {"age": 34, "sex": "female", "pregnant": False, "allergies": ["Penicillin"],
                 "medications": _NONE, "conditions": ["Migraines"]},
    },
    {
        "name": "James", "language": "en", "waited": 42, "pain_flagged": False,
        "qa": [{"id": "worsening", "question": "Is it getting worse?", "answer": "No"}],
        "transcript": ("I sprained my ankle playing basketball yesterday. It's swollen and bruised, "
                       "but I can walk on it. Pain is about 4 out of 10."),
        "info": {"age": 29, "sex": "male", "pregnant": None, "allergies": _NONE,
                 "medications": _NONE, "conditions": _NONE},
    },
    {
        "name": "Sofia", "language": "en", "waited": 55, "pain_flagged": False, "qa": [],
        "transcript": "I need a refill of my birth control prescription. I feel fine and have no pain.",
        "info": {"age": 26, "sex": "female", "pregnant": False, "allergies": _NONE,
                 "medications": ["Birth control"], "conditions": _NONE},
    },
]
CANONICAL_NAMES = frozenset(p["name"] for p in CANONICAL)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _build(hospital_id: str, spec: dict[str, Any], now: datetime) -> dict[str, Any]:
    t = intake_pipeline.triage_check_in(
        spec["transcript"], medical_info=spec["info"], language=spec["language"], allow_ai=False,
    )
    created = _iso(now - timedelta(minutes=spec["waited"]))
    record: dict[str, Any] = {
        # Same id every time for the same hospital, so a reset brings back the same patients.
        "patient_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"solace-demo/{hospital_id}/{spec['name']}")),
        "hospital_id": hospital_id,
        "name": spec["name"],
        "language": spec["language"],
        "transcript": spec["transcript"],
        "medical_info": json.dumps(spec["info"]),
        "followup_qa": json.dumps(spec["qa"]) if spec["qa"] else None,
        "insurance_info": None,
        "photo_s3_key": None,
        "photo_analysis": None,
        **t.record_fields(),
        "status": STATUS_WAITING,
        "created_at": created,
        "consent_granted_at": created,
        "consent_version": "1.0",
        "ai_processing_log": json.dumps([]),
        "ai_cost_usd": 0.0,
        "ai_cost_breakdown": json.dumps({}),
        "seed": True,
        "canonical": True,
        "pain_flagged": bool(spec["pain_flagged"]),
        "pain_flagged_at": _iso(now - timedelta(minutes=3)) if spec["pain_flagged"] else None,
        "pain_flag_acknowledged_at": None,
        "pain_flag_acknowledged_by": None,
    }
    # The no-AI versions of everything the background worker would make.
    record.update(intake_artifacts.deterministic_artifacts(intake_artifacts.inputs(record)))
    record["artifacts_status"] = intake_artifacts.STATUS_READY
    return record


def seed_canonical_patients(hospital_id: str) -> list[str]:
    """Add the five example patients to a hospital and return their ids.

    Skips any example already there, so calling it twice adds nothing.
    """
    try:
        existing = storage.list_patients_for_hospital(hospital_id, status="all")
    except Exception as e:  # noqa: BLE001
        log.warning("demo seed: could not list patients for %s (%s)", hospital_id, type(e).__name__)
        existing = []
    present = {
        p.get("name") for p in existing
        if p.get("name") in CANONICAL_NAMES and (p.get("seed") or p.get("canonical"))
    }
    todo = [spec for spec in CANONICAL if spec["name"] not in present]
    if not todo:
        return []

    now = datetime.now(timezone.utc)
    # Scoring runs the local model; five at once takes about a second once it is loaded.
    # Each build runs in its own copy of the caller's context, so anything it counts
    # (the visitor's AI limit, the request's address) stays tied to the visitor.
    with ThreadPoolExecutor(max_workers=len(todo), thread_name_prefix="demo-seed") as pool:
        futures = [pool.submit(contextvars.copy_context().run, _build, hospital_id, spec, now) for spec in todo]
        records = [f.result() for f in futures]

    ids: list[str] = []
    for record in records:
        storage.put_patient(record)
        ids.append(record["patient_id"])
    log.info("demo seed: added %d example patients to %s", len(ids), hospital_id)
    return ids
