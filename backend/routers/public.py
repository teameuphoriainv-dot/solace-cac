"""Unauthenticated patient-facing endpoints that live outside /intake itself.

- POST /start-intake: issues the one-use token the check-in page must get before
  it can submit /intake.
- GET /capabilities: which optional features (AI, voice, texts, bedside model) are
  on for this server, so screens can say what is off instead of failing.
"""
from __future__ import annotations

import logging
from pathlib import Path as FsPath

from fastapi import APIRouter, Path, Request, Response

from lib import blocklist, intake_nonce, quota

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/start-intake")
def start_intake(hospital_id: str = Path(...), request: Request = None) -> dict:
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")
    identity = quota.identity_of(source_ip, user_agent)
    blocklist.enforce(identity, source_ip=source_ip)
    quota.check_and_consume(identity, "intake.start", source_ip=source_ip)
    return intake_nonce.issue(hospital_id, source_ip=source_ip, user_agent=user_agent)


@router.get("/capabilities")
def capabilities(response: Response, hospital_id: str = Path(...)) -> dict:
    """The shape of Capabilities in frontend/src/lib/capabilities.ts."""
    response.headers["Cache-Control"] = "no-store"
    return build_capabilities()


def build_capabilities() -> dict:
    from lib import claude  # noqa: PLC0415

    llm = _safe(claude.available, False)
    return {
        "llm": llm,
        "ocr": llm,
        "transcription": _safe(_transcription_on, False),
        "tts": _safe(_tts_on, False),
        "sms": _safe(_sms_on, False),
        "triage_model": triage_model_status(),
    }


MODEL_LOADED = "loaded"            # in memory and in use
MODEL_LOADING = "loading"          # a load is running right now (the startup warm-up)
MODEL_FILES_PRESENT = "files_present"  # on disk, not loaded yet (the first use loads it)
MODEL_NOT_INSTALLED = "not_installed"  # files missing, or the load failed


def model_state() -> tuple[str, int]:
    """(state, folds) for the bedside model. Never waits on a load and never starts one.

    triage_ml.status() takes the load lock and loads the model when it has not run
    yet, so asking it right after a deploy makes the visitor wait many seconds. This
    only peeks: at the finished load when there is one, else at the lock and the files.
    """
    from services import triage_ml  # noqa: PLC0415

    try:
        if triage_ml._load_files.cache_info().currsize:
            art = triage_ml._load_files()  # already cached, so this returns at once
            if art is not None:
                return MODEL_LOADED, len(art.get("boosters") or [])
            return MODEL_NOT_INSTALLED, 0
    except Exception:  # noqa: BLE001 (fall back to the files on disk)
        pass
    try:
        models = FsPath(triage_ml.MODELS_DIR)
        folds = len(list(models.glob("lgbm_fold*.txt")))
        if not ((models / "artifacts.pkl").exists() and folds > 0):
            return MODEL_NOT_INSTALLED, 0
    except Exception:  # noqa: BLE001
        return MODEL_NOT_INSTALLED, 0
    try:
        loading = triage_ml._LOAD_LOCK.locked()
    except Exception:  # noqa: BLE001
        loading = False
    return (MODEL_LOADING if loading else MODEL_FILES_PRESENT), folds


def triage_model_status() -> dict:
    """{"loaded", "mode", "folds"} for the bedside model, without loading it.

    "loaded" means the trained model is installed and in use or about to be (the
    frontend contract in lib/capabilities.ts): true when it is in memory, loading, or
    its files are on disk; false when the files are missing or failed to load.
    """
    state, folds = model_state()
    if state == MODEL_NOT_INSTALLED:
        return {"loaded": False, "mode": "rules_only", "folds": 0}
    return {"loaded": True, "mode": "lgbm_5fold", "folds": folds}


def _transcription_on() -> bool:
    from services import transcription  # noqa: PLC0415

    return transcription.is_configured()


def _tts_on() -> bool:
    from services import tts  # noqa: PLC0415

    return tts.is_configured()


def _sms_on() -> bool:
    from services import sms  # noqa: PLC0415

    return bool(sms.is_configured())


def _safe(fn, default):
    try:
        return bool(fn())
    except Exception as e:  # noqa: BLE001 (a capability check must never fail the page)
        log.warning("capability check %s failed: %s", getattr(fn, "__name__", fn), e)
        return default
