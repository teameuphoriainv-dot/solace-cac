"""Bedside triage model: a 5-fold LightGBM ensemble trained on synthetic ER visits.

What ships: five LightGBM boosters (backend/models/lgbm_fold0..4.txt, one per
cross-validation fold) whose class probabilities are averaged, plus artifacts.pkl,
which holds the feature pipeline (label encoders, TF-IDF vocabularies, medians).
The stacking code further down (XGBoost, CatBoost, an MLP and a meta-learner) is
inactive in this build: those packages and model files are not installed, so
status() reports mode "lgbm_5fold".

The model was trained on about 80,000 synthetic (made-up) ER visits from the
Kaggle Triagegeist competition. It scores near-perfect on its own synthetic test
folds, which says more about how clean that data is than about real patients, so
the deterministic safety rules in services/triage_rules.py always get the last word.

Likely range: a Mondrian (per-ESI-class) split-conformal prediction set, see
lib/conformal.py. scripts/calibrate_conformal.py fits it offline and writes
backend/models/conformal.pkl, which _load() picks up, so a request never pays for
calibration. Without that file the set falls back to the single global q-hat
stored in the pickle, which on this clean data is almost always one class.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import re
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import hstack as sp_hstack

from lib import conformal

log = logging.getLogger(__name__)

# The trained files are too large for git; scripts/fetch_models.sh downloads them.
# Without them predict() returns None and the bedside re-check uses the safety rules alone.
MODELS_DIR = Path(os.environ.get("SOLACE_MODELS_DIR") or Path(__file__).resolve().parent.parent / "models")
CONFORMAL_FILE = "conformal.pkl"

_LOAD_LOCK = threading.Lock()


def _resolve_model_path(fold: int, model_type: str) -> Path | None:
    path = MODELS_DIR / f"{model_type}_fold{fold}.txt"
    return path if path.exists() else None


def _get_art() -> dict | None:
    """The loaded artifacts, or None."""
    return _load()


def _load() -> dict | None:
    """Load all artifacts once per process. The lock stops the startup warm-up and a
    first request from loading the 300 MB model twice at the same time."""
    with _LOAD_LOCK:
        return _load_files()


@lru_cache(maxsize=1)
def _load_files() -> dict | None:
    art_path = MODELS_DIR / "artifacts.pkl"
    if not art_path.exists():
        log.warning("triage_ml: artifacts.pkl not present at %s", art_path)
        return None

    with art_path.open("rb") as f:
        art = pickle.load(f)

    n_folds = art["n_folds"]

    try:
        import lightgbm as lgb
        boosters = []
        for i in range(n_folds):
            path = _resolve_model_path(i, "lgbm")
            if path is None:
                log.warning("triage_ml: could not load lgbm fold %d", i)
                return None
            boosters.append(lgb.Booster(model_file=str(path)))
        art["boosters"] = boosters
    except ImportError:
        log.warning("triage_ml: lightgbm not installed")
        return None

    # Optional stacking layers. Not shipped in this build, so these stay None.
    try:
        import xgboost as xgb
        xgb_models = []
        for i in range(n_folds):
            path = _resolve_model_path(i, "xgb")
            if path is None:
                art["xgb_models"] = None
                break
            m = xgb.Booster()
            m.load_model(str(path))
            xgb_models.append(m)
        else:
            art["xgb_models"] = xgb_models
    except ImportError:
        art["xgb_models"] = None

    try:
        from catboost import CatBoostClassifier
        cat_models = []
        for i in range(n_folds):
            path = _resolve_model_path(i, "cat")
            if path is None:
                art["cat_models"] = None
                break
            m = CatBoostClassifier()
            m.load_model(str(path))
            cat_models.append(m)
        else:
            art["cat_models"] = cat_models
    except ImportError:
        art["cat_models"] = None

    art.setdefault("mlp_models", None)
    art.setdefault("mlp_scalers", None)
    art.setdefault("meta_learner", None)
    art.setdefault("opt_thresholds", None)

    art["_stacking_enabled"] = all([
        art.get("xgb_models"),
        art.get("cat_models"),
        art.get("mlp_models"),
        art.get("mlp_scalers"),
        art.get("meta_learner"),
    ])

    # The calibrator is installed by _ensure_calibrated(), from conformal.pkl when present.
    art["conformal"] = None
    art["_conformal_pending"] = True
    art["_conformal_offline"] = _load_offline_conformal(art)

    log.info(
        "triage_ml: loaded %d folds, %d features, mode=%s, offline conformal=%s",
        n_folds, len(art["feature_names"]),
        "stacked" if art["_stacking_enabled"] else "lgbm_5fold",
        art["_conformal_offline"] is not None,
    )
    return art


# Callers that peek at the cache (routers/public.py) or build a fresh, uncached copy
# (tests, via __wrapped__) keep working.
_load.cache_info = _load_files.cache_info  # type: ignore[attr-defined]
_load.cache_clear = _load_files.cache_clear  # type: ignore[attr-defined]
_load.__wrapped__ = _load_files.__wrapped__  # type: ignore[attr-defined]


def status() -> dict[str, Any]:
    """Contract C2: what the bedside model is doing on this server."""
    try:
        art = _get_art()
    except Exception as e:  # noqa: BLE001 (callers report this, they must not crash)
        log.warning("triage_ml: status check failed (%s)", e)
        art = None
    if art is None:
        return {"loaded": False, "mode": "rules_only", "folds": 0}
    return {"loaded": True, "mode": "lgbm_5fold", "folds": len(art.get("boosters") or [])}


# ---------------------------------------------------------------------------
# Model card (plain words for clinicians and judges, technical terms kept apart)
# ---------------------------------------------------------------------------
MODEL_CARD_DATASET = (
    "About 80,000 synthetic (made-up) ER visits from a Kaggle competition called Triagegeist."
)
MODEL_CARD_ACCURACY = (
    "It scores near-perfect on its own synthetic test set. That mostly shows the made-up "
    "data is too clean, so its accuracy on real patients is unknown. That is why the "
    "safety rules always get the last word."
)


def model_card(art: dict | None, conformal_note: str | None = None) -> dict[str, Any]:
    qwk = art.get("oof_qwk") if art else None
    acc = art.get("oof_accuracy") if art else None
    technical = [
        "Five LightGBM gradient-boosted tree models, one per cross-validation fold; their "
        "probabilities are averaged.",
        "The factor list uses SHAP contributions from the first fold model. It leaves out "
        "administrative fields (arrival time, site, nurse id), vitals that were not "
        "measured, a default age when none was given, and history or words the patient "
        "did not report, even though the model reads all of them. Warning words the "
        "patient did not use are added up into one line, \"No warning signs mentioned\".",
    ]
    if qwk is not None and acc is not None:
        technical.append(
            f"Out-of-fold scores on the synthetic data: quadratic weighted kappa {qwk:.3f}, "
            f"accuracy {acc:.3f}. These are unrealistically high; real-world ESI models "
            "usually score far lower."
        )
    technical.append(
        "Likely range: Mondrian (per-class) split-conformal prediction at a 90% target, "
        "always including the model's own pick. The made-up calibration patients include "
        "ESI 2 cases the model scored as ESI 3, so the range rarely rules out ESI 2 or 3."
    )
    return {
        "name": "Bedside model (5-fold LightGBM)",
        "dataset": MODEL_CARD_DATASET,
        "accuracy_note": MODEL_CARD_ACCURACY,
        "range_note": conformal_note or "",
        "technical": technical,
    }


# ---------------------------------------------------------------------------
# Conformal calibration
# ---------------------------------------------------------------------------
def _model_probs(art: dict, X: pd.DataFrame) -> np.ndarray:
    """Softmax rows for a feature matrix using the active ensemble mode."""
    if art.get("_stacking_enabled"):
        probs = _stacked_predict(art, X)
    else:
        probs = _predict_lgb(art, X)
    return np.atleast_2d(np.asarray(probs, dtype=np.float64))


def _synthetic_calibration_profiles(n_per_class: int = 30) -> list[tuple[dict, dict, int]]:
    """Build a labeled (patient, vitals, esi_0based) synthetic calibration set.

    Each profile pairs a chief complaint and vitals with a fixed ESI label from
    standard triage logic (life threat is ESI 1, high risk or severe vitals is ESI 2,
    and so on down to ESI 5 for minor problems). It is made-up data, which the model
    card says. recalibrate_from_outcomes() replaces it once real outcomes exist.
    """
    rng = np.random.default_rng(7)
    # (chief_complaint, base_vitals, esi_level 1..5)
    archetypes: list[tuple[str, dict, int]] = [
        ("cardiac arrest, not breathing, CPR in progress",
         {"systolic_bp": 60, "heart_rate": 140, "respiratory_rate": 4, "spo2": 78,
          "gcs_total": 3, "pain_score": -1, "mental_status": "unresponsive"}, 1),
        ("unresponsive after major trauma, massive hemorrhage",
         {"systolic_bp": 70, "heart_rate": 135, "respiratory_rate": 30, "spo2": 84,
          "gcs_total": 6, "pain_score": -1, "mental_status": "unresponsive"}, 1),
        ("severe chest pain radiating to left arm, diaphoretic",
         {"systolic_bp": 150, "heart_rate": 112, "respiratory_rate": 22, "spo2": 94,
          "gcs_total": 15, "pain_score": 9, "mental_status": "alert"}, 2),
        ("acute stroke symptoms, slurred speech, facial droop",
         {"systolic_bp": 178, "heart_rate": 96, "respiratory_rate": 18, "spo2": 95,
          "gcs_total": 13, "pain_score": 2, "mental_status": "confused"}, 2),
        ("moderate abdominal pain, vomiting, stable vitals",
         {"systolic_bp": 124, "heart_rate": 92, "respiratory_rate": 18, "spo2": 97,
          "gcs_total": 15, "pain_score": 6, "mental_status": "alert"}, 3),
        ("fever and cough for three days, feeling weak",
         {"systolic_bp": 118, "heart_rate": 98, "respiratory_rate": 20, "spo2": 96,
          "gcs_total": 15, "pain_score": 4, "mental_status": "alert"}, 3),
        ("minor laceration on forearm, controlled bleeding",
         {"systolic_bp": 122, "heart_rate": 78, "respiratory_rate": 16, "spo2": 99,
          "gcs_total": 15, "pain_score": 3, "mental_status": "alert"}, 4),
        ("sprained ankle, able to bear weight, mild swelling",
         {"systolic_bp": 120, "heart_rate": 76, "respiratory_rate": 15, "spo2": 99,
          "gcs_total": 15, "pain_score": 4, "mental_status": "alert"}, 4),
        ("medication refill request, no acute complaint",
         {"systolic_bp": 118, "heart_rate": 72, "respiratory_rate": 14, "spo2": 99,
          "gcs_total": 15, "pain_score": 0, "mental_status": "alert"}, 5),
        ("mild sore throat, wants to be checked, otherwise well",
         {"systolic_bp": 116, "heart_rate": 70, "respiratory_rate": 14, "spo2": 99,
          "gcs_total": 15, "pain_score": 1, "mental_status": "alert"}, 5),
    ]

    profiles: list[tuple[dict, dict, int]] = []
    for cc, base, esi in archetypes:
        for _ in range(n_per_class):
            # Jitter vitals and demographics so calibration scores have spread.
            vitals = dict(base)
            for k in ("systolic_bp", "heart_rate", "respiratory_rate", "spo2"):
                if vitals.get(k) is not None:
                    vitals[k] = float(vitals[k]) + float(rng.normal(0, 3))
            vitals["diastolic_bp"] = (vitals.get("systolic_bp") or 120) * 0.65
            vitals["temperature_c"] = float(36.8 + rng.normal(0, 0.5))
            age = int(np.clip(rng.normal(55, 18), 18, 95))
            sex = "male" if rng.random() < 0.5 else "female"
            patient = {
                "patient_id": "cal",
                "transcript": cc,
                "language": "en",
                "medical_info": {"age": age, "sex": sex, "conditions": []},
            }
            profiles.append((patient, vitals, esi - 1))
    return profiles


def _conformal_note(alpha: float, n: int, source: str = "synthetic_calibration") -> str:
    pct = int(round((1 - alpha) * 100))
    if source == "clinician_confirmed_outcomes":
        return (
            f"The likely range is calibrated on {n} clinician-confirmed outcomes, "
            f"aiming to include the right score {pct}% of the time."
        )
    return (
        f"The likely range is calibrated on {n} made-up example patients, not real "
        f"outcomes, so treat it as a rough guide, not a guarantee."
    )


_UNCALIBRATED_NOTE = (
    "The likely range is not calibrated on this server, so it usually shows only the "
    "model's top pick."
)


def _feature_fingerprint(art: dict) -> str:
    return hashlib.sha256("\n".join(art["feature_names"]).encode()).hexdigest()[:16]


def _load_offline_conformal(art: dict) -> dict | None:
    """Read the calibrator written by scripts/calibrate_conformal.py, if it matches this model."""
    path = MODELS_DIR / CONFORMAL_FILE
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            saved = pickle.load(f)
        if saved.get("feature_fingerprint") != _feature_fingerprint(art):
            log.warning("triage_ml: %s was made for a different model, ignoring it", CONFORMAL_FILE)
            return None
        cal = conformal.MondrianConformal(
            alpha=float(saved["alpha"]),
            q_hat={int(k): float(v) for k, v in saved["q_hat"].items()},
            global_q_hat=float(saved["global_q_hat"]),
            n_per_class={int(k): int(v) for k, v in saved["n_per_class"].items()},
            source=str(saved.get("source") or "synthetic_calibration"),
        )
        n = int(sum(cal.n_per_class.values()))
        return {"calibrator": cal, "note": _conformal_note(cal.alpha, n, cal.source)}
    except Exception as e:  # noqa: BLE001 (a bad file must not stop the model loading)
        log.warning("triage_ml: could not read %s (%s)", CONFORMAL_FILE, e)
        return None


def save_offline_conformal(art: dict, path: Path | None = None) -> Path:
    """Write art["conformal"] as plain data so _load() can reuse it without refitting."""
    cal: conformal.MondrianConformal | None = art.get("conformal")
    if cal is None:
        raise RuntimeError("no calibrator to save; run _calibrate(art) first")
    path = path or (MODELS_DIR / CONFORMAL_FILE)
    payload = {
        "version": 1,
        "feature_fingerprint": _feature_fingerprint(art),
        "alpha": float(cal.alpha),
        "q_hat": {int(k): float(v) for k, v in cal.q_hat.items()},
        "global_q_hat": float(cal.global_q_hat),
        "n_per_class": {int(k): int(v) for k, v in cal.n_per_class.items()},
        "source": cal.source,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with path.open("wb") as f:
        pickle.dump(payload, f)
    return path


def _ensure_calibrated(art: dict, alpha: float = conformal.DEFAULT_ALPHA, *, block: bool = True) -> None:
    """Install the Mondrian calibrator.

    Uses the offline file when it exists (instant). Otherwise, with block=True
    (tests, scripts/calibrate_conformal.py) it fits one now, which takes 40 s or more.
    With block=False (the request path) it never fits: the prediction set falls
    back to the global q-hat until the offline file exists.
    """
    if not art.get("_conformal_pending"):
        return
    offline = art.get("_conformal_offline")
    if offline is not None:
        art["conformal"] = offline["calibrator"]
        art["conformal_note"] = offline["note"]
        art["_conformal_pending"] = False
        return
    if not block:
        return
    art["_conformal_pending"] = False  # one attempt, even if it fails
    try:
        _calibrate(art, alpha)
    except Exception as e:  # noqa: BLE001
        log.warning("triage_ml: conformal calibration failed (%s), using the global q-hat", e)
        art["conformal"] = None


def _calibrate(art: dict, alpha: float = conformal.DEFAULT_ALPHA) -> None:
    """Fit the Mondrian calibrator on the synthetic labeled set and store it on art."""
    profiles = _synthetic_calibration_profiles()
    probs_rows: list[np.ndarray] = []
    labels: list[int] = []
    for patient, vitals, esi0 in profiles:
        try:
            X = _build_feature_matrix(art, patient, vitals)
            probs_rows.append(_model_probs(art, X)[0])
            labels.append(esi0)
        except Exception:  # noqa: BLE001 (skip any row that fails to featurize)
            continue
    if not probs_rows:
        raise RuntimeError("no calibration rows produced")

    probs = np.vstack(probs_rows)
    y = np.asarray(labels, dtype=np.int64)
    cal = conformal.MondrianConformal.fit(
        probs, y, alpha=alpha, source="synthetic_calibration"
    )
    art["conformal"] = cal
    art["conformal_note"] = _conformal_note(alpha, int(probs.shape[0]))
    log.info(
        "triage_ml: Mondrian conformal fit n=%d per-class q-hat=%s",
        probs.shape[0], cal.q_hat_by_esi(),
    )


def recalibrate_from_outcomes(
    outcomes: list[dict[str, Any]],
    *,
    alpha: float = conformal.DEFAULT_ALPHA,
    weights: list[float] | None = None,
) -> dict[str, Any]:
    """Recompute per-ESI-class q-hat from clinician-confirmed outcomes.

    Each outcome is a dict with either ``probabilities`` ({"1": p1, ..., "5": p5})
    or ``patient`` + ``vitals`` (the model is re-run), plus ``confirmed_esi`` (1..5).
    ``weights`` (optional, parallel to ``outcomes``) gives importance-weighted
    conformal (Tibshirani et al. 2019).

    Updates the live calibrator in place. Keeps the current one if no outcome is usable.
    """
    art = _get_art()
    if art is None:
        return {"updated": False, "reason": "artifacts_not_loaded"}

    probs_rows: list[np.ndarray] = []
    labels: list[int] = []
    used_weights: list[float] = []
    for i, oc in enumerate(outcomes or []):
        esi = oc.get("confirmed_esi")
        if esi is None or not (1 <= int(esi) <= 5):
            continue
        row: np.ndarray | None = None
        probs_map = oc.get("probabilities")
        if isinstance(probs_map, dict):
            try:
                row = np.array([float(probs_map[str(k)]) for k in range(1, 6)], dtype=np.float64)
            except (KeyError, TypeError, ValueError):
                row = None
        if row is None and oc.get("patient") is not None:
            try:
                X = _build_feature_matrix(art, oc["patient"], oc.get("vitals") or {})
                row = _model_probs(art, X)[0]
            except Exception:  # noqa: BLE001
                row = None
        if row is None:
            continue
        probs_rows.append(row)
        labels.append(int(esi) - 1)
        if weights is not None and i < len(weights):
            used_weights.append(float(weights[i]))

    if not probs_rows:
        return {
            "updated": False,
            "reason": "no_usable_outcomes",
            "n_outcomes": len(outcomes or []),
            "q_hat_by_class": (
                art["conformal"].q_hat_by_esi() if art.get("conformal") else None
            ),
        }

    probs = np.vstack(probs_rows)
    y = np.asarray(labels, dtype=np.int64)
    w = (
        np.asarray(used_weights, dtype=np.float64)
        if weights is not None and len(used_weights) == len(labels)
        else None
    )
    cal = conformal.MondrianConformal.fit(
        probs, y, alpha=alpha, weights=w, source="clinician_confirmed_outcomes"
    )
    art["conformal"] = cal
    art["_conformal_pending"] = False
    art["conformal_note"] = _conformal_note(alpha, int(probs.shape[0]), cal.source)
    log.info(
        "triage_ml: recalibrated conformal from %d outcomes, q-hat=%s",
        probs.shape[0], cal.q_hat_by_esi(),
    )
    return {
        "updated": True,
        "n_outcomes_used": int(probs.shape[0]),
        "weighted": w is not None,
        "alpha": alpha,
        "q_hat_by_class": cal.q_hat_by_esi(),
        "source": cal.source,
    }


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def _safe_encode(le, value: Any, modal_fallback: str | None = None) -> int:
    v = str(value) if value is not None else "unknown"
    if v in le.classes_:
        return int(le.transform([v])[0])
    if modal_fallback is not None and modal_fallback in le.classes_:
        return int(le.transform([modal_fallback])[0])
    return 0


def _apply_clinical_features(df: pd.DataFrame, keywords: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    for col in ["systolic_bp", "diastolic_bp", "respiratory_rate", "temperature_c", "spo2"]:
        df[f"miss_{col}"] = df[col].isnull().astype(np.int8)
    df["miss_pain"] = (df["pain_score"] == -1).astype(np.int8)
    df["pain_score"] = df["pain_score"].replace(-1, np.nan)
    df["total_missing"] = df[[c for c in df.columns if c.startswith("miss_")]].sum(axis=1)

    df["flag_hypotension"] = (df["systolic_bp"] < 90).astype(np.int8)
    df["flag_hypertensive"] = (df["systolic_bp"] >= 180).astype(np.int8)
    df["flag_tachycardia"] = (df["heart_rate"] > 100).astype(np.int8)
    df["flag_bradycardia"] = (df["heart_rate"] < 50).astype(np.int8)
    df["flag_hypoxia"] = (df["spo2"] < 94).astype(np.int8)
    df["flag_severe_hypoxia"] = (df["spo2"] < 88).astype(np.int8)
    df["flag_tachypnea"] = (df["respiratory_rate"] > 20).astype(np.int8)
    df["flag_fever"] = (df["temperature_c"] > 38.0).astype(np.int8)
    df["flag_hypothermia"] = (df["temperature_c"] < 36.0).astype(np.int8)
    df["flag_severe_gcs"] = (df["gcs_total"] <= 8).astype(np.int8)
    df["flag_altered_mental"] = df["mental_status_triage"].isin(
        ["confused", "drowsy", "agitated", "unresponsive"]
    ).astype(np.int8)
    df["flag_shock_idx"] = (df["shock_index"] > 1.0).astype(np.int8)
    df["flag_severe_tachycardia"] = (df["heart_rate"] > 130).astype(np.int8)
    df["flag_severe_hypotension"] = (df["systolic_bp"] < 70).astype(np.int8)

    hx_cols = [c for c in df.columns if c.startswith("hx_")]
    df["comorbidity_burden"] = df[hx_cols].sum(axis=1) if hx_cols else 0
    df["high_comorbidity"] = (df["comorbidity_burden"] >= 3).astype(np.int8)

    df["qsofa"] = (
        (df["systolic_bp"] <= 100).astype(int)
        + (df["respiratory_rate"] >= 22).astype(int)
        + (df["gcs_total"] < 15).astype(int)
    )
    df["sirs"] = (
        ((df["temperature_c"] > 38.3) | (df["temperature_c"] < 36)).astype(int)
        + (df["heart_rate"] > 90).astype(int)
        + (df["respiratory_rate"] > 20).astype(int)
    ).astype(np.int8)
    df["cv_risk_composite"] = (
        (df["systolic_bp"] < 90).astype(int)
        + (df["heart_rate"] > 100).astype(int)
        + (df["shock_index"] > 1.0).astype(int)
        + (df["spo2"] < 94).astype(int)
    ).astype(np.int8)

    df["is_night"] = ((df["arrival_hour"] >= 22) | (df["arrival_hour"] <= 6)).astype(np.int8)
    df["is_weekend"] = df["arrival_day"].isin(["Saturday", "Sunday"]).astype(np.int8)
    df["hour_sin"] = np.sin(2 * np.pi * df["arrival_hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["arrival_hour"] / 24)

    df["age_x_gcs"] = df["age"] * df["gcs_total"]
    df["age_x_news2"] = df["age"] * df["news2_score"]
    df["age_x_shock_idx"] = df["age"] * df["shock_index"]
    df["age_x_hr"] = df["age"] * df["heart_rate"]

    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    df["num_abnormal_vitals"] = df[flag_cols].sum(axis=1).astype(np.int8)

    cc_lower = df["chief_complaint_raw"].fillna("").str.lower()
    for col, pat in keywords.items():
        df[col] = cc_lower.str.contains(pat, regex=True).astype(np.int8)
    df["kw_total"] = df[list(keywords.keys())].sum(axis=1)
    return df


_HX_MAP = {
    r"hypertens|high.?blood.?pressure|\bhtn\b|elevated.?bp": "hx_hypertension",
    r"(type.?2.?diab|t2dm|dm.?2\b|diabetes mellitus type 2|non.?insulin.?dep)": "hx_diabetes_type2",
    r"(type.?1.?diab|t1dm|dm.?1\b|juvenile.?diabetes|insulin.?dep.?diab)": "hx_diabetes_type1",
    r"asthma|reactive.?airway": "hx_asthma",
    r"copd|emphysema|chronic.?bronchitis|pulmonary.?disease": "hx_copd",
    r"(heart.?failure|\bchf\b|hfref|hfpef|cardiomyopathy)": "hx_heart_failure",
    r"(atrial.?fib|\bafib\b|a.?fib|arrhythm)": "hx_atrial_fibrillation",
    r"(\bckd\b|chronic.?kidney|renal.?failure|dialysis|esrd)": "hx_ckd",
    r"(liver|cirrhosis|hepatitis|hepatic|fatty.?liver)": "hx_liver_disease",
    r"(cancer|malignan|tumor|oncolog|carcinoma|sarcoma|lymphoma|leukemia|chemotherap)": "hx_malignancy",
    r"(obesity|obese|morbid.?obes|bmi.?[>\s]3[0-9]|overweight)": "hx_obesity",
    r"(depress|\bmdd\b|mood.?disorder|dysthymi)": "hx_depression",
    r"(anxiety|\bgad\b|panic|ptsd|post.?trauma)": "hx_anxiety",
    r"(dementia|alzheimer|cognitive.?decline|memory.?loss)": "hx_dementia",
    r"(epileps|seizure.?disorder|convulsive)": "hx_epilepsy",
    r"hypothyroid|low.?thyroid|hashimoto": "hx_hypothyroidism",
    r"hyperthyroid|graves|overactive.?thyroid": "hx_hyperthyroidism",
    r"(\bhiv\b|\baids\b|immunodefic)": "hx_hiv",
    r"(coagulopath|warfarin|coumadin|eliquis|apixaban|rivaroxaban|xarelto|anticoag|blood.?thinner|factor.?v|bleeding.?disorder)": "hx_coagulopathy",
    r"(immunosuppress|transplant|prednisone|steroid|chemo|biologic|rheumatoid.?arthritis.*infliximab)": "hx_immunosuppressed",
    r"(pregnan|gestation|gravid|1st.?trimester|2nd.?trimester|3rd.?trimester)": "hx_pregnant",
    r"(substance|alcohol.?use|opioid|heroin|cocaine|amphetamine|meth|addiction|iv.?drug)": "hx_substance_use_disorder",
    r"(\bcad\b|coronary|angina|stent|cabg|\bmi\b|myocardial|heart.?attack)": "hx_coronary_artery_disease",
    r"(stroke|\bcva\b|\btia\b|cerebrovascular|brain.?bleed)": "hx_stroke_prior",
    r"(\bpvd\b|peripheral.?vascular|claudication|limb.?ischemia)": "hx_peripheral_vascular_disease",
}
_ALL_HX = list(_HX_MAP.values())


def _derive_hx(conditions: list[str]) -> dict[str, int]:
    flags = {h: 0 for h in _ALL_HX}
    text = " ".join(str(c).lower() for c in (conditions or []))
    for pat, flag in _HX_MAP.items():
        if re.search(pat, text):
            flags[flag] = 1
    return flags


# The training data spells these the dataset's way ("M", "English"); map the app's values
# so they do not silently fall back to the most common training value.
_SEX_CODES = {"m": "M", "male": "M", "f": "F", "female": "F", "other": "Other"}
_LANGUAGE_NAMES = {"en": "English", "ar": "Arabic", "ru": "Russian", "so": "Somali",
                   "sv": "Swedish", "fi": "Finnish", "et": "Estonian"}
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_SEASONS = ["winter", "winter", "spring", "spring", "spring", "summer",
            "summer", "summer", "autumn", "autumn", "autumn", "winter"]


def _medical_info(patient: dict) -> dict:
    info = patient.get("medical_info") or {}
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            info = {}
    return info if isinstance(info, dict) else {}


def _given_age(patient: dict) -> float | None:
    """The age on the patient's form, or None when they did not give one."""
    try:
        age = _medical_info(patient).get("age")
        return float(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _age_group(age: float) -> str:
    if age < 18:
        return "pediatric"
    if age < 40:
        return "young_adult"
    if age < 65:
        return "middle_aged"
    return "elderly"


def _arrival_fields(patient: dict, now: datetime | None = None) -> dict[str, Any]:
    """Arrival time features from the check-in time (or now), in the server's local time."""
    ts = now
    raw = patient.get("created_at")
    if ts is None and isinstance(raw, str) and raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            ts = None
    if ts is None:
        ts = datetime.now(timezone.utc)
    local = ts.astimezone() if ts.tzinfo else ts
    h = local.hour
    if h < 6 or h >= 22:
        shift = "night"
    elif h < 12:
        shift = "morning"
    elif h < 18:
        shift = "afternoon"
    else:
        shift = "evening"
    return {
        "arrival_hour": h,
        "arrival_month": local.month,
        "arrival_day": _DAYS[local.weekday()],
        "arrival_season": _SEASONS[local.month - 1],
        "shift": shift,
    }


def build_row(patient: dict, vitals: dict, now: datetime | None = None) -> dict:
    """Build a single-row dict matching the training schema."""
    info = _medical_info(patient)
    conditions = info.get("conditions") or []
    hx_flags = _derive_hx(conditions)

    sbp = vitals.get("systolic_bp")
    dbp = vitals.get("diastolic_bp")
    hr = vitals.get("heart_rate")
    map_val = vitals.get("mean_arterial_pressure")
    if map_val is None and sbp is not None and dbp is not None:
        map_val = (sbp + 2 * dbp) / 3
    pp = vitals.get("pulse_pressure")
    if pp is None and sbp is not None and dbp is not None:
        pp = sbp - dbp
    shock = vitals.get("shock_index")
    if shock is None and hr is not None and sbp not in (None, 0):
        shock = hr / sbp
    news2 = vitals.get("news2_score", 0)

    given_age = _given_age(patient)
    age = 35.0 if given_age is None else given_age  # a baby's age can be 0
    sex = _SEX_CODES.get(str(info.get("sex") or "").strip().lower(), "unknown")
    lang = str(patient.get("language") or "en").strip().lower()[:2]

    row = {
        "patient_id": patient.get("patient_id", "unknown"),
        "chief_complaint_raw": patient.get("transcript", ""),
        "age": age,
        "sex": sex,
        "language": _LANGUAGE_NAMES.get(lang, "Other"),
        "insurance_type": "unknown",
        "age_group": _age_group(age),
        "arrival_mode": "walk-in",
        "mental_status_triage": vitals.get("mental_status") or "alert",
        "transport_origin": "home",
        "pain_location": info.get("pain_location") or "unknown",
        "chief_complaint_system": "unspecified",
        "triage_nurse_id": "unknown",
        "site_id": "demo",
        **_arrival_fields(patient, now),
        "num_prior_ed_visits_12m": 0,
        "num_prior_admissions_12m": 0,
        "num_active_medications": len(info.get("medications") or []),
        "num_comorbidities": sum(hx_flags.values()),
        "systolic_bp": sbp,
        "diastolic_bp": dbp,
        "mean_arterial_pressure": map_val,
        "pulse_pressure": pp,
        "heart_rate": hr,
        "respiratory_rate": vitals.get("respiratory_rate"),
        "temperature_c": vitals.get("temperature_c"),
        "spo2": vitals.get("spo2"),
        "gcs_total": vitals.get("gcs_total") or 15,
        "pain_score": vitals.get("pain_score") if vitals.get("pain_score") is not None else -1,
        "weight_kg": vitals.get("weight_kg") or 70,
        "height_cm": vitals.get("height_cm") or 170,
        "bmi": vitals.get("bmi") or 24,
        "shock_index": shock if shock is not None else 0.8,
        "news2_score": news2,
        **hx_flags,
    }
    return row


def _build_feature_matrix(art: dict, patient: dict, vitals: dict) -> pd.DataFrame:
    """Shared feature construction for all model types."""
    row = build_row(patient, vitals)
    df = pd.DataFrame([row])

    for col, med in art["imputation_medians"].items():
        if col in df.columns:
            if df[col].dtype == object:  # an all-None column; make it numeric before filling
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].fillna(med)

    df = _apply_clinical_features(df, art["keywords"])

    modal = art.get("modal_defaults", {})
    for col, le in art["label_encoders"].items():
        if col in df.columns:
            df[col + "_le"] = _safe_encode(le, df[col].iloc[0], modal_fallback=modal.get(col))

    cc = df["chief_complaint_raw"].fillna("unknown").iloc[0:1]
    tw = art["tfidf_word"].transform(cc)
    tc = art["tfidf_char"].transform(cc)
    tfidf_arr = sp_hstack([tw, tc]).toarray()
    tfidf_df = pd.DataFrame(tfidf_arr, columns=art["tfidf_names"]).astype(np.float32)

    struct_cols = art["struct_cols"]
    for c in struct_cols:
        if c not in df.columns:
            df[c] = 0.0
    X_struct = df[struct_cols].astype(np.float32).reset_index(drop=True)
    X = pd.concat([X_struct, tfidf_df.reset_index(drop=True)], axis=1)

    for c in X.columns:
        if X[c].isnull().any():
            X[c] = X[c].fillna(art["imputation_medians"].get(c, 0.0))

    X = X[art["feature_names"]]
    return X


def _predict_lgb(art: dict, X: pd.DataFrame) -> np.ndarray:
    return np.mean([b.predict(X) for b in art["boosters"]], axis=0)


def _predict_xgb(art: dict, X: pd.DataFrame) -> np.ndarray:
    import xgboost as xgb
    dmat = xgb.DMatrix(X)
    preds = [m.predict(dmat).reshape(-1, 5) for m in art["xgb_models"]]
    return np.mean(preds, axis=0)


def _predict_cat(art: dict, X: pd.DataFrame) -> np.ndarray:
    preds = [m.predict_proba(X) for m in art["cat_models"]]
    return np.mean(preds, axis=0)


def _predict_mlp(art: dict, X: pd.DataFrame) -> np.ndarray:
    preds = []
    for model, scaler in zip(art["mlp_models"], art["mlp_scalers"]):
        X_scaled = scaler.transform(X.fillna(0))
        preds.append(model.predict_proba(X_scaled))
    return np.mean(preds, axis=0)


def _stacked_predict(art: dict, X: pd.DataFrame) -> np.ndarray:
    """Inactive in this build: four base models, then a meta-learner."""
    lgb_p = _predict_lgb(art, X)
    xgb_p = _predict_xgb(art, X)
    cat_p = _predict_cat(art, X)
    mlp_p = _predict_mlp(art, X)

    weights = art.get("ensemble_weights") or [0.25, 0.25, 0.25, 0.25]
    wavg_p = (
        weights[0] * lgb_p
        + weights[1] * xgb_p
        + weights[2] * cat_p
        + weights[3] * mlp_p
    )
    meta_learner = art.get("meta_learner")
    if meta_learner is not None:
        return meta_learner.predict_proba(np.hstack([lgb_p, xgb_p, cat_p, mlp_p]))
    return wavg_p


def _apply_threshold_opt(art: dict, probs: np.ndarray) -> tuple[int, float]:
    """Apply ordinal threshold optimization if available."""
    opt_thresh = art.get("opt_thresholds")
    if opt_thresh is not None:
        ev = probs @ np.arange(1, 6)
        esi_level = int(np.digitize(ev, sorted(opt_thresh)) + 1)
        esi_level = max(1, min(5, esi_level))
        confidence = float(probs[esi_level - 1])
    else:
        pred_idx = int(np.argmax(probs))
        esi_level = pred_idx + 1
        confidence = float(probs[pred_idx])
    return esi_level, confidence


def predict(patient: dict, vitals: dict) -> dict[str, Any] | None:
    art = _get_art()
    if art is None:
        return None
    try:
        X = _build_feature_matrix(art, patient, vitals)

        if art["_stacking_enabled"]:
            probs_2d = _stacked_predict(art, X)
            source = "stacked_ensemble_v1"
        else:
            probs_2d = _predict_lgb(art, X)
            source = "lgbm_5fold_v2"
        probs = probs_2d[0] if probs_2d.ndim == 2 else probs_2d

        esi_level, confidence = _apply_threshold_opt(art, probs)

        _ensure_calibrated(art, block=False)  # never fits on a request
        cal: conformal.MondrianConformal | None = art.get("conformal")
        if cal is not None:
            # The model's own pick is always in its range (this only widens the set).
            conformal_set = sorted(set(cal.predict_set(probs)) | {esi_level})
            q_hat = cal.representative_q_hat()
            q_hat_by_class = cal.q_hat_by_esi()
            conformal_method = f"mondrian_class_conditional ({cal.source})"
            conformal_note = art.get("conformal_note")
        else:
            q_hat = float(art.get("conformal_q_hat_noisy", art.get("conformal_q_hat", 0.5)))
            conformal_set = sorted({int(i + 1) for i, p in enumerate(probs) if (1 - p) <= q_hat} | {esi_level})
            q_hat_by_class = None
            conformal_method = "split_conformal (global_scalar)"
            conformal_note = _UNCALIBRATED_NOTE

        measured = {k for k, v in (vitals or {}).items() if v is not None}
        if _given_age(patient) is not None:
            measured.add("age")
        top_features = _shap_top_features(
            art["boosters"], X, esi_level - 1, art["feature_names"], art=art, measured=measured,
        )

        return {
            "esi_level": esi_level,
            "confidence": confidence,
            "probabilities": {str(i + 1): float(p) for i, p in enumerate(probs)},
            "conformal_set": conformal_set,
            "conformal_q_hat": q_hat,
            "conformal_q_hat_by_class": q_hat_by_class,
            "conformal_method": conformal_method,
            "conformal_note": conformal_note,
            "top_features": top_features,
            "source": source,
            "model_metrics": {
                "oof_qwk": art.get("oof_qwk"),
                "oof_accuracy": art.get("oof_accuracy"),
            },
            "dataset": MODEL_CARD_DATASET,
            "model_card": model_card(art, conformal_note),
        }
    except Exception as e:
        log.exception("triage_ml predict failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Factors shown to clinicians
# ---------------------------------------------------------------------------
# Context the model saw that is not about the patient's body. It stays in the model
# (removing it would mean retraining) but is never shown as a reason for a score.
_HIDDEN_PREFIXES = (
    "triage_nurse_id", "site_id", "arrival_", "shift", "hour_", "is_night", "is_weekend",
    "transport_origin", "insurance_type", "language", "miss_", "total_missing",
    "num_prior_", "patient_id", "chief_complaint_system", "tfidf_c",
)

# A vital-sign feature is only a reason when that vital was actually measured;
# otherwise the model used a typical value, not this patient's.
_NEEDS_VITALS: dict[str, tuple[str, ...]] = {
    "systolic_bp": ("systolic_bp",), "flag_hypotension": ("systolic_bp",),
    "flag_hypertensive": ("systolic_bp",), "flag_severe_hypotension": ("systolic_bp",),
    "diastolic_bp": ("diastolic_bp",),
    "mean_arterial_pressure": ("systolic_bp", "diastolic_bp"),
    "pulse_pressure": ("systolic_bp", "diastolic_bp"),
    "heart_rate": ("heart_rate",), "flag_tachycardia": ("heart_rate",),
    "flag_bradycardia": ("heart_rate",), "flag_severe_tachycardia": ("heart_rate",),
    "age_x_hr": ("heart_rate", "age"),
    "shock_index": ("heart_rate", "systolic_bp"), "flag_shock_idx": ("heart_rate", "systolic_bp"),
    "age_x_shock_idx": ("heart_rate", "systolic_bp", "age"),
    "respiratory_rate": ("respiratory_rate",), "flag_tachypnea": ("respiratory_rate",),
    "temperature_c": ("temperature_c",), "flag_fever": ("temperature_c",),
    "flag_hypothermia": ("temperature_c",),
    "spo2": ("spo2",), "flag_hypoxia": ("spo2",), "flag_severe_hypoxia": ("spo2",),
    "gcs_total": ("gcs_total",), "flag_severe_gcs": ("gcs_total",), "age_x_gcs": ("gcs_total", "age"),
    "pain_score": ("pain_score",),
    "news2_score": ("news2_score",), "age_x_news2": ("news2_score", "age"),
    "flag_altered_mental": ("mental_status",), "mental_status_triage_le": ("mental_status",),
    "weight_kg": ("weight_kg",), "height_cm": ("height_cm",), "bmi": ("bmi",),
    # Without an age on the form the model assumes 35; that is not this patient's age.
    "age": ("age",), "age_group_le": ("age",),
}
_NEEDS_ANY_VITAL = {"qsofa", "sirs", "cv_risk_composite", "num_abnormal_vitals"}
_VITAL_KEYS = {"systolic_bp", "diastolic_bp", "heart_rate", "respiratory_rate",
               "temperature_c", "spo2", "gcs_total"}

_FLAG_LABELS: dict[str, tuple[str, str]] = {  # (when true, when false)
    "flag_tachycardia": ("Heart rate over 100", "Heart rate 100 or lower"),
    "flag_severe_tachycardia": ("Heart rate over 130", "Heart rate 130 or lower"),
    "flag_bradycardia": ("Heart rate under 50", "Heart rate 50 or higher"),
    "flag_hypotension": ("Systolic blood pressure under 90", "Systolic blood pressure 90 or higher"),
    "flag_severe_hypotension": ("Systolic blood pressure under 70", "Systolic blood pressure 70 or higher"),
    "flag_hypertensive": ("Systolic blood pressure 180 or higher", "Systolic blood pressure under 180"),
    "flag_hypoxia": ("Oxygen level under 94%", "Oxygen level 94% or higher"),
    "flag_severe_hypoxia": ("Oxygen level under 88%", "Oxygen level 88% or higher"),
    "flag_tachypnea": ("Breathing rate over 20", "Breathing rate 20 or lower"),
    "flag_fever": ("Temperature over 38 C", "Temperature 38 C or lower"),
    "flag_hypothermia": ("Temperature under 36 C", "Temperature 36 C or higher"),
    "flag_severe_gcs": ("GCS 8 or lower", "GCS above 8"),
    "flag_altered_mental": ("Not fully alert", "Fully alert"),
    "flag_shock_idx": ("Shock index over 1", "Shock index 1 or lower"),
    "high_comorbidity": ("Three or more health conditions", "Fewer than three health conditions"),
}
_KW_LABELS = {
    "kw_chest_pain": "chest pain", "kw_resp": "trouble breathing",
    "kw_neuro": "confusion or not responding", "kw_stroke": "stroke signs",
    "kw_seizure": "a seizure", "kw_trauma": "a serious injury",
    "kw_overdose": "an overdose or poisoning", "kw_pain": "severe pain",
    "kw_syncope": "fainting", "kw_bleed": "heavy bleeding", "kw_sepsis": "sepsis",
    "kw_cardiac": "a heart problem", "kw_anaphylaxis": "a severe allergic reaction",
    "kw_psych": "thoughts of self-harm or harming others", "kw_mild": "a mild or routine problem",
}
_HX_LABELS = {
    "hx_hypertension": "high blood pressure", "hx_diabetes_type2": "type 2 diabetes",
    "hx_diabetes_type1": "type 1 diabetes", "hx_asthma": "asthma", "hx_copd": "COPD (lung disease)",
    "hx_heart_failure": "heart failure", "hx_atrial_fibrillation": "an irregular heartbeat",
    "hx_ckd": "kidney disease", "hx_liver_disease": "liver disease", "hx_malignancy": "cancer",
    "hx_obesity": "obesity", "hx_depression": "depression", "hx_anxiety": "anxiety",
    "hx_dementia": "dementia", "hx_epilepsy": "epilepsy", "hx_hypothyroidism": "low thyroid",
    "hx_hyperthyroidism": "overactive thyroid", "hx_hiv": "HIV",
    "hx_coagulopathy": "a bleeding disorder or blood thinners",
    "hx_immunosuppressed": "a weak immune system", "hx_pregnant": "pregnancy",
    "hx_substance_use_disorder": "substance use", "hx_coronary_artery_disease": "heart artery disease",
    "hx_stroke_prior": "a past stroke", "hx_peripheral_vascular_disease": "poor leg circulation",
}
_MEASURE_LABELS = {
    "age": "Age", "heart_rate": "Heart rate", "systolic_bp": "Systolic blood pressure",
    "diastolic_bp": "Diastolic blood pressure", "mean_arterial_pressure": "Mean arterial pressure",
    "pulse_pressure": "Pulse pressure", "respiratory_rate": "Breathing rate",
    "temperature_c": "Temperature (C)", "spo2": "Oxygen level (%)",
    "gcs_total": "GCS (alertness, 3 to 15)", "pain_score": "Pain score (0 to 10)",
    "news2_score": "NEWS2 score", "shock_index": "Shock index (heart rate / systolic pressure)",
    "qsofa": "qSOFA score", "sirs": "SIRS score",
    "cv_risk_composite": "Heart and circulation warning signs",
    "num_abnormal_vitals": "Number of abnormal vital signs",
    "num_comorbidities": "Number of health conditions",
    "comorbidity_burden": "Number of health conditions",
    "num_active_medications": "Number of medicines",
    "age_x_gcs": "Age and GCS together", "age_x_news2": "Age and NEWS2 together",
    "age_x_shock_idx": "Age and shock index together", "age_x_hr": "Age and heart rate together",
    "weight_kg": "Weight (kg)", "height_cm": "Height (cm)", "bmi": "BMI",
    "kw_total": "Number of warning words in the complaint",
}
_CATEGORY_LABELS = {
    "sex_le": "Sex", "age_group_le": "Age group", "pain_location_le": "Where the pain is",
    "mental_status_triage_le": "Mental status",
}


def shown_to_clinicians(name: str, measured: set[str] | None = None) -> bool:
    """False for administrative context, and for vitals (or an age) that were never given."""
    if name.startswith(_HIDDEN_PREFIXES):
        return False
    if measured is None:
        return True
    needs = _NEEDS_VITALS.get(name)
    if needs is not None and not all(k in measured for k in needs):
        return False
    if name in _NEEDS_ANY_VITAL and not (measured & _VITAL_KEYS):
        return False
    return True


def _category_value(name: str, value: float, art: dict | None) -> str | None:
    le = (art or {}).get("label_encoders", {}).get(name[:-3])
    try:
        return str(le.classes_[int(value)])
    except Exception:  # noqa: BLE001 (no encoder, or an out-of-range code)
        return None


# Tiny words that carry no clinical meaning on their own.
_FILLER_WORDS = {
    "a", "an", "and", "the", "of", "to", "in", "on", "at", "for", "with", "my", "i", "im",
    "is", "it", "its", "was", "have", "has", "had", "me", "been", "this", "that", "since", "so",
}
_MIN_CONTRIBUTION = 0.005  # SHAP (log-odds); smaller than this changes nothing visible


def describes_patient(name: str, value: float, art: dict | None = None) -> bool:
    """False for factors that are about what the patient did NOT report.

    The model leans on absent warning words because the synthetic complaints are
    templated, but "does not mention a seizure" is not a reason a nurse can act on.
    """
    if name in _KW_LABELS or name in _HX_LABELS or name in ("high_comorbidity", "kw_total"):
        return value >= 0.5
    if name.startswith("tfidf_w"):
        return value > 0
    if name in _CATEGORY_LABELS:
        category = (_category_value(name, value, art) or "").strip().lower()
        return category not in ("", "unknown", "unspecified")
    return True


def factor_label(name: str, value: float, art: dict | None = None) -> tuple[str, str]:
    """(plain label, kind) for one model feature. kind is measure, flag, category or text."""
    present = value >= 0.5
    if name in _FLAG_LABELS:
        yes, no = _FLAG_LABELS[name]
        return (yes if present else no), "flag"
    if name in _KW_LABELS:
        what = _KW_LABELS[name]
        return (f"Mentions {what}" if present else f"Does not mention {what}"), "flag"
    if name in _HX_LABELS:
        what = _HX_LABELS[name]
        return (f"History of {what}" if present else f"No reported history of {what}"), "flag"
    if name in _MEASURE_LABELS:
        return _MEASURE_LABELS[name], "measure"
    if name in _CATEGORY_LABELS:
        label = _CATEGORY_LABELS[name]
        category = _category_value(name, value, art)
        if category:
            category = {"M": "male", "F": "female", "Other": "other"}.get(category, category)
            label = f"{label}: {category.replace('_', ' ')}"
        return label, "category"
    word = _word(name, art)
    if word is not None:
        return (f'Says "{word}"' if value > 0 else f'Does not say "{word}"'), "text"
    return name.replace("_", " ").strip().capitalize(), "measure"


def _word(name: str, art: dict | None) -> str | None:
    """The complaint word (or two-word phrase) behind a tfidf_w<n> feature."""
    m = re.match(r"tfidf_w(\d+)$", name)
    if not m or art is None or "tfidf_word" not in art:
        return None
    try:
        vocab = art["tfidf_word"].get_feature_names_out()
        idx = int(m.group(1))
        return str(vocab[idx]) if idx < len(vocab) else None
    except Exception:  # noqa: BLE001
        return None


def _shap_top_features(
    boosters: list, X: pd.DataFrame, pred_class: int, feature_names: list[str],
    k: int = 5, art: dict | None = None, measured: set[str] | None = None,
) -> list[dict]:
    """Per-patient SHAP (LightGBM pred_contrib) for the model's own pick, in plain words."""
    n_features = len(feature_names)
    raw = boosters[0].predict(X, pred_contrib=True)
    arr = np.asarray(raw).reshape(1, n_features + 1, 5)
    shap_values = arr[0, :-1, pred_class]

    row = X.iloc[0]

    def item(code: str, label: str, kind: str, value: float, shap: float) -> dict:
        return {"feature": label, "code": code, "kind": kind, "value": value, "shap": shap,
                "direction": "increases" if shap > 0 else "decreases"}

    clinical: list[dict] = []
    words: list[dict] = []
    # Warning words the patient did not use are summed into one honest line instead
    # of five "does not mention ..." rows.
    absent_total = 0.0
    any_warning = False
    for i in np.argsort(np.abs(shap_values))[::-1]:
        name = feature_names[i]
        value = float(row.iloc[i])
        shap = float(shap_values[i])
        if name in _KW_LABELS:
            if value >= 0.5:
                any_warning = True
            else:
                absent_total += shap
                continue
        if abs(shap) < _MIN_CONTRIBUTION or not shown_to_clinicians(name, measured):
            continue
        if not describes_patient(name, value, art):
            continue
        label, kind = factor_label(name, value, art)
        if name.startswith("tfidf_w"):
            if (_word(name, art) or "").strip().lower() not in _FILLER_WORDS:
                words.append(item(name, label, kind, value, shap))
        else:
            clinical.append(item(name, label, kind, value, shap))

    if abs(absent_total) >= _MIN_CONTRIBUTION:
        label = "No other warning signs mentioned" if any_warning else "No warning signs mentioned"
        clinical.append(item("kw_none_mentioned", label, "flag", 0.0, absent_total))
        clinical.sort(key=lambda f: abs(f["shap"]), reverse=True)

    # Up to k-1 clinical factors, then the strongest words, then more clinical ones.
    n_clinical = min(len(clinical), max(k - 1, 0))
    out = clinical[:n_clinical]
    out.extend(words[: k - len(out)])
    out.extend(clinical[n_clinical: n_clinical + k - len(out)])
    return out
