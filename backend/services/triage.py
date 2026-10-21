"""Check-in triage: the trained model plus the red-flag rules.

The patient has no vitals yet, so the model reads the complaint, age, sex and
history, with normal vitals filled in. When the model files are missing, the
rule-based simulation engine (services/triage_engine.py) stands in for it.

Either way the red-flag rules in services/triage_rules.py get the last word:
the visible score is the most urgent of the model and the rules. The model's
own guess and confidence are kept next to it for clinicians.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from services import triage_rules
from services.triage_engine import predict_triage

log = logging.getLogger(__name__)

# Normal vitals, used because nobody has measured the patient yet.
_DEFAULT_VITALS = {
    "heart_rate": 80.0,
    "sbp": 120.0,
    "dbp": 80.0,
    "o2_sat": 98.0,
    "resp_rate": 16.0,
    "temperature": 98.6,
    "gcs": 15,
}


@dataclass
class TriagePrediction:
    esi_level: int                  # visible level: most urgent of the model and the rules
    confidence: float               # the model's confidence in ITS OWN level
    confidence_band: str
    shap_values: dict[str, float]
    source: str
    clinical_flags: list[str]
    composites: dict[str, float]
    recommendation: str
    probabilities: list[float]
    model_esi_level: int | None = None
    decision: triage_rules.Decision | None = None


def predict(
    transcript: str,
    photo_analysis: dict[str, Any] | None = None,
    medical_info: dict[str, Any] | None = None,
    *,
    english: str | None = None,
) -> TriagePrediction:
    """Triage one check-in. `english` is an optional English translation of the
    patient's words; the model reads it and the rules read both."""
    info = dict(medical_info or {})
    text = english.strip() if english and english.strip() else (transcript or "")
    raw = _predict_trained(text, photo_analysis, info) or _predict_engine(text, photo_analysis, info)

    assessment = triage_rules.assess(
        _with_photo(transcript, photo_analysis), age=info.get("age"),
        pregnant=bool(info.get("pregnant")), english=_with_photo(english or "", photo_analysis),
        on_blood_thinner=on_blood_thinner(info),
    )
    decision = triage_rules.most_urgent(raw.esi_level, assessment)
    raw.model_esi_level = raw.esi_level
    raw.decision = decision
    if decision.rule is not None:
        rule = decision.rule
        raw.esi_level = decision.esi_level
        raw.recommendation = rule.recommendation
        raw.confidence_band = (
            f"ESI {decision.esi_level} (set by a safety rule: {rule.name}; "
            f"the model said ESI {decision.model_esi_level} at {int(round(raw.confidence * 100))}%)"
        )
    for r in decision.fired:
        if r.reason not in raw.clinical_flags:
            raw.clinical_flags.append(r.reason)
    return raw


# Common blood thinner names (generic and brand) a patient may type on the form.
_THINNER_NAMES = re.compile(
    r"blood[\s-]*thinner|anticoag|warfarin|coumadin|jantoven|apixaban|eliquis|rivaroxaban|xarelto"
    r"|dabigatran|pradaxa|edoxaban|savaysa|lixiana|heparin|enoxaparin|lovenox|dalteparin|fragmin"
    r"|fondaparinux|arixtra",
    re.IGNORECASE,
)
_NO_ANSWER = {"", "none", "no", "n/a", "na"}


def on_blood_thinner(medical_info: dict[str, Any] | None) -> bool:
    """True when the medical form says the patient takes a blood thinner: a picked
    blood thinner, or a medicine whose name is a common blood thinner."""
    info = medical_info if isinstance(medical_info, dict) else {}
    picked = info.get("blood_thinner_name")
    if isinstance(picked, str) and picked.strip().lower() not in _NO_ANSWER:
        return True
    meds = info.get("medications")
    if isinstance(meds, str):
        meds = [meds]
    if not isinstance(meds, (list, tuple)):
        return False
    return any(isinstance(m, str) and _THINNER_NAMES.search(m) for m in meds)


def _with_photo(text: str, photo_analysis: dict[str, Any] | None) -> str:
    text = (text or "").strip()
    if photo_analysis and photo_analysis.get("description"):
        return f"{text}. {photo_analysis['description']}" if text else str(photo_analysis["description"])
    return text


def _predict_engine(transcript: str, photo_analysis: dict[str, Any] | None, medical_info: dict[str, Any]) -> TriagePrediction:
    result = predict_triage(_build_payload(transcript, photo_analysis, medical_info))
    confidence = float(result["confidence"])
    # The engine's risk factors become a {name: importance} dict for the dashboard chart.
    shap_values = {
        str(rf.get("name", "")).strip(): float(rf.get("importance", 0.0))
        for rf in result["risk_factors"] if str(rf.get("name", "")).strip()
    }
    return TriagePrediction(
        esi_level=int(result["esi_level"]),
        confidence=confidence,
        confidence_band=_format_confidence_band(result["conformal_set"], result["esi_level"], confidence),
        shap_values=shap_values,
        source="triageist_simulation",
        clinical_flags=list(result.get("clinical_flags", [])),
        composites=dict(result.get("composites", {})),
        recommendation=str(result.get("recommendation", "")),
        probabilities=list(result.get("probabilities", [])),
    )


def _predict_trained(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    medical_info: dict[str, Any] | None,
    vitals: dict[str, Any] | None = None,
) -> TriagePrediction | None:
    """The trained 5-fold model, or None when its files are not on this server."""
    try:
        from services import triage_ml  # noqa: PLC0415 (heavy import, on demand)
    except Exception:  # noqa: BLE001
        return None

    info = dict(medical_info or {})
    cc = _with_photo(transcript, photo_analysis)
    patient = {
        "patient_id": info.get("patient_id", "intake"),
        "transcript": cc or "unspecified",
        "language": info.get("language") or "en",
        "medical_info": info,
    }
    res = triage_ml.predict(patient, vitals or {})
    if res is None:
        return None

    esi = int(res["esi_level"])
    confidence = float(res["confidence"])
    conformal = res.get("conformal_set") or [esi]
    return TriagePrediction(
        esi_level=esi,
        confidence=confidence,
        confidence_band=_format_confidence_band(conformal, esi, confidence),
        shap_values={f["feature"]: float(f.get("shap", 0.0)) for f in res.get("top_features", []) if f.get("feature")},
        source=res.get("source", "lgbm_5fold_v2"),
        clinical_flags=[],
        composites={},
        recommendation="",
        probabilities=[res["probabilities"].get(str(i), 0.0) for i in range(1, 6)],
    )


def _build_payload(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    medical_info: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        age = int(float((medical_info or {}).get("age") or 35))
    except (TypeError, ValueError):
        age = 35
    sex_raw = (medical_info or {}).get("sex")
    sex = {"male": "Male", "female": "Female", "other": "Other", "m": "Male", "f": "Female"}.get(
        str(sex_raw).lower() if sex_raw else "", "Other"
    )
    conditions = (medical_info or {}).get("conditions") or []
    n_comorbidities = sum(1 for c in conditions if str(c).lower() != "none")
    return {
        **_DEFAULT_VITALS,
        "age": age,
        "sex": sex,
        "chief_complaint": _with_photo(transcript, photo_analysis) or "unspecified",
        "arrival_mode": "Walk-in",
        "n_comorbidities": n_comorbidities,
    }


def _format_confidence_band(conformal: list[int], predicted: int, confidence: float) -> str:
    if len(conformal) == 1:
        return f"ESI {predicted} (confidence {int(round(confidence * 100))}%)"
    lo, hi = conformal[0], conformal[-1]
    return f"ESI {lo} to {hi} (confidence {int(round(confidence * 100))}% at ESI {predicted})"
