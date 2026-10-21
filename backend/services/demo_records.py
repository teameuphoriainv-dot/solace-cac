"""Fictional "returning patient" records for the demo hospital.

A real hospital would answer this from its own records system. The demo keeps a
few made-up people in memory so the returning-patient flow (scan your ID, and
the form arrives pre-filled with your allergies and medications) works with no
outside system. None of these people exist.

``sample_id_fields`` and ``sample_insurance_fields`` return a sample driver's
license and insurance card for Jordan Rivera, in the same shape a real scan
returns, so the flow can be tried with no camera and no AI key.
"""
from __future__ import annotations

import copy

_RECORDS: list[dict] = [
    {
        "name": "Jordan Rivera",
        "mrn": "DEMO-1001",
        "dob": "1987-03-14",
        "sex": "female",
        "member_id": "DEMO100200300",
        "allergies": ["Penicillin"],
        "medications": ["Albuterol inhaler"],
        "conditions": ["Asthma"],
        "insurance": "Demo Health PPO",
        "primary_care_provider": "Dr. Alvarez",
        "prior_visits": ["2025-11-02 asthma flare"],
        "source": "demo",
    },
    {
        "name": "Sam Okafor",
        "mrn": "DEMO-1002",
        "dob": "1958-09-30",
        "sex": "male",
        "member_id": "DEMO400500600",
        "allergies": ["Sulfa drugs"],
        "medications": ["Metformin", "Lisinopril"],
        "conditions": ["Type 2 diabetes", "Hypertension"],
        "insurance": "Demo Medicare Advantage",
        "primary_care_provider": "Dr. Nguyen",
        "prior_visits": ["2026-01-19 chest tightness", "2026-04-07 dizziness"],
        "source": "demo",
    },
]


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def match(
    *,
    first_name: str = "",
    last_name: str = "",
    dob: str = "",
    member_id: str = "",
) -> dict | None:
    """Return a copy of the matching record, tagged with how it matched, or None.

    Name plus date of birth is tried first because it is the most specific.
    The insurance member ID is the fallback for patients who only scanned a card.
    """
    full = _norm(f"{first_name} {last_name}")
    for rec in _RECORDS:
        if full.strip() and dob and _norm(rec["name"]) == full and rec["dob"] == dob:
            return {**copy.deepcopy(rec), "_match_method": "name+dob"}
    if member_id:
        for rec in _RECORDS:
            if _norm(rec["member_id"]) == _norm(member_id):
                return {**copy.deepcopy(rec), "_match_method": "member_id"}
    return None


# The sample cards both belong to the first record, so a sample scan always
# finds the returning patient.
SAMPLE_PERSON = _RECORDS[0]


def sample_id_fields() -> dict:
    """A fictional driver's license, shaped like services/id_ocr.extract output."""
    first, last = SAMPLE_PERSON["name"].split(" ", 1)
    return {
        "first_name": first,
        "middle_name": "",
        "last_name": last,
        "dob": SAMPLE_PERSON["dob"],
        "license_number": "D000-1234-5678",
        "issuing_state": "IL",
        "address": "123 Sample Street",
        "city": "Sampletown",
        "state": "IL",
        "zip": "60000",
        "issue_date": "2024-03-14",
        "expiry": "2030-03-14",
        "sex": "F",
        "height": "5-06",
        "eye_color": "BRN",
        "document_type": "drivers_license",
        "_completeness": 1.0,
        "_partial": False,
        "_warnings": [],
    }


def sample_insurance_fields() -> dict:
    """A fictional insurance card, shaped like services/insurance_ocr.extract
    output (with the short key names the patient screen reads)."""
    fields = {
        "provider": "Demo Health",
        "plan_name": SAMPLE_PERSON["insurance"],
        "plan_type": "PPO",
        "member_id": SAMPLE_PERSON["member_id"],
        "group_number": "DEMO-GRP-01",
        "name_on_card": SAMPLE_PERSON["name"],
        "dependents": [],
        "rx_bin": "999001",
        "rx_pcn": "DEMO",
        "rx_group": "DEMORX",
        "payer_id": "DEMO1",
        "effective_date": "2026-01-01",
        "copay_pcp": "$20",
        "copay_specialist": "$40",
        "copay_er": "$150",
        "customer_service_phone": "1-800-555-0100",
        "claims_address": None,
        "card_side": "front",
        "_completeness": 1.0,
    }
    fields["bin"] = fields["rx_bin"]
    fields["pcn"] = fields["rx_pcn"]
    fields["phone"] = fields["customer_service_phone"]
    return fields
