"""Fit the bedside model's likely-range calibrator once, offline.

Calibrating at runtime means running 300 made-up example patients through all five
LightGBM folds, which takes 40 s or more and slows every request while it runs.
This script does it ahead of time and writes backend/models/conformal.pkl, which
services/triage_ml.py loads with the model. Re-run it after the model files change
(the app ignores a calibrator made for a different model).

Run from the repo root:
    backend/.venv/bin/python scripts/calibrate_conformal.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from services import triage_ml  # noqa: E402


def main() -> int:
    t0 = time.time()
    art = triage_ml._get_art()
    if art is None:
        print(f"No model files in {triage_ml.MODELS_DIR}. Run scripts/fetch_models.sh first.")
        return 1
    triage_ml._calibrate(art)
    cal = art["conformal"]
    path = triage_ml.save_offline_conformal(art)
    n = sum(cal.n_per_class.values())
    print(f"Calibrated on {n} example patients in {time.time() - t0:.1f} s.")
    print(f"Per-ESI q-hat: {cal.q_hat_by_esi()}")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
