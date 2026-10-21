"""Check five example patients in through a running Solace server and show their ESI.

The server already adds five fictional patients (ESI 1 to 5) to the demo hospital when it
starts (backend/services/demo_seed.py). This script adds five more "walk-ins" the same way
a patient's phone does: POST /start-intake for a one-use token, then POST /intake with the
typed symptoms. Each one runs the real triage pipeline, so it also works as a smoke test of
a local or deployed server. With no AI keys the results come from the deterministic rules
and the local model, so they are the same every run.

The phrases are the "Try an example" phrases the check-in screen offers. The script prints
each ESI next to the range the triage tests expect, and exits 1 if any is outside it.

Usage (from the repo root; needs only Python 3, no extra packages):
    python3 scripts/seed_demo.py                                  # backend on :8000
    python3 scripts/seed_demo.py --url http://localhost:7860      # the Docker image
    python3 scripts/seed_demo.py --url https://<your-space>.hf.space --hospital-id demo-abc123

Then open the nurse dashboard: /demo/clinician (sign in as Dr. Chen, PIN 224466).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# name, phrase, medical info, preferred language, expected ESI range (inclusive)
WALK_INS: list[tuple[str, str, dict, str, tuple[int, int]]] = [
    (
        "Noah",
        "Crushing chest pain down my left arm and I'm sweating",
        {"age": 58, "sex": "male", "allergies": ["None"], "medications": ["None"], "conditions": ["Hypertension"]},
        "en",
        (1, 2),
    ),
    (
        "Ava",
        "I twisted my ankle playing soccer and it's swollen",
        {"age": 16, "sex": "female", "allergies": ["None"], "medications": ["None"], "conditions": ["None"]},
        "en",
        (4, 5),
    ),
    (
        "Mateo",
        "Me duele mucho el pecho y no puedo respirar",
        {"age": 61, "sex": "male", "allergies": ["None"], "medications": ["None"], "conditions": ["None"]},
        "es",
        (1, 2),
    ),
    (
        "Lily",
        "My 3 year old has a fever of 104 and is very sleepy",
        {"age": 3, "sex": "female", "allergies": ["None"], "medications": ["None"], "conditions": ["None"]},
        "en",
        (1, 2),
    ),
    (
        "Grace",
        "I need a refill of my blood pressure pills",
        {"age": 67, "sex": "female", "allergies": ["None"], "medications": ["Lisinopril"], "conditions": ["Hypertension"]},
        "en",
        (4, 5),
    ),
]


def _post(url: str, data: dict | None = None, as_json: bool = False, timeout: float = 120) -> dict:
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        if as_json:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        else:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body if body is not None else b"", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--url", default="http://localhost:8000", help="server origin (default %(default)s)")
    parser.add_argument("--hospital-id", default="demo", help="hospital or sandbox id (default %(default)s)")
    parser.add_argument(
        "--flag-pain-on", default=None,
        help="name of one walk-in to press 'I feel worse' for (for example Noah)",
    )
    args = parser.parse_args()
    base = f"{args.url.rstrip('/')}/api/{args.hospital_id}"

    created: dict[str, str] = {}
    outside = 0
    for name, phrase, info, lang, (lo, hi) in WALK_INS:
        try:
            token = _post(f"{base}/start-intake").get("token", "")
            data = _post(f"{base}/intake", {
                "patient_name": name,
                "pre_transcribed_text": phrase,
                "medical_info": json.dumps(info),
                "preferred_language": lang,
                "consent_granted": "true",
                "intake_token": token,
            })
        except (RuntimeError, urllib.error.URLError, TimeoutError) as e:
            print(f"  {name:<6} could not check in: {e}")
            outside += 1
            continue
        esi = data.get("esi_level")
        ok = isinstance(esi, int) and lo <= esi <= hi
        outside += 0 if ok else 1
        verdict = "as expected" if ok else "OUTSIDE the expected range"
        print(f"  {name:<6} ESI {esi} (expected {lo} to {hi}, {verdict})  \"{phrase}\"")
        if data.get("patient_id"):
            created[name] = data["patient_id"]

    if args.flag_pain_on:
        pid = created.get(args.flag_pain_on)
        if pid:
            _post(f"{base}/pain-flag", {"patient_id": pid}, as_json=True)
            print(f"  raised the 'I feel worse' flag for {args.flag_pain_on}")
        else:
            print(f"  no walk-in named {args.flag_pain_on} was created, so no flag was raised")

    print(f"Checked in {len(created)} of {len(WALK_INS)} walk-ins at {args.hospital_id}.")
    print(f"Nurse dashboard: /{args.hospital_id}/clinician on the frontend (Dr. Chen, PIN 224466).")
    return 1 if outside else 0


if __name__ == "__main__":
    sys.exit(main())
