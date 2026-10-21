"""Patient ID scan and returning-patient lookup.

Powers the optional first step in the patient flow:
  - POST /api/{hospital_id}/scan-id           read a driver's license photo (needs an AI key)
  - POST /api/{hospital_id}/scan-id/sample    the fictional sample license, no camera or key
  - POST /api/{hospital_id}/identity/lookup   match name + date of birth (or an insurance
                                              member id) against the demo's fictional
                                              returning-patient records

All are unauthenticated (patients use them) and throttled per visitor.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, Path, Request, UploadFile
from pydantic import BaseModel, ConfigDict

from lib import blocklist, claude, quota, uploads
from services import demo_records, id_ocr

log = logging.getLogger(__name__)

router = APIRouter()

# What the patient reads for each scan outcome. The code stays in `error` so
# the screen can branch on it.
SCAN_MESSAGES = {
    "ocr_unavailable": (
        "Card reading is off in this demo. Type your details, or use the sample card to see how it works."
    ),
    "not_an_id_card": "That photo does not look like a driver's license or state ID. Try again, or skip this step.",
    "not_an_insurance_card": "That photo does not look like an insurance card. Try again, or type the details.",
    "needs_rescan": "We could not read that photo. Try again in good light with the whole card in view.",
    "empty_image": "The photo was empty. Please take it again.",
    "ocr_failed": "We could not read the card this time. Try again, or type your details.",
    "ocr_parse_failed": "We could not read the card this time. Try again, or type your details.",
    "parse_failed": "We could not read the card this time. Try again, or type your details.",
}

# "ocr_unavailable" because the AI call failed: the photo was never read.
AI_FAILED_MESSAGE = (
    "Card reading is not working right now. Type your details, or use the sample card to see how it works."
)

_UPLOAD_MESSAGES = {
    400: "The photo was empty. Please take it again.",
    413: "That photo is too large. Move a little closer to the card and try again.",
    415: "That file is not a photo we can read. Use a JPEG or PNG picture.",
    422: "That photo could not be opened. Please take it again.",
}


def client_identity(request: Request | None) -> tuple[str, str | None]:
    """(quota identity, source ip) for an unauthenticated patient request."""
    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
    return quota.identity_of(source_ip, user_agent), source_ip


async def read_card_photo(image_file: UploadFile, source_ip: str | None) -> bytes:
    """Validate the uploaded photo, with patient-friendly error text."""
    try:
        return await uploads.read_and_validate(image_file, "image", source_ip=source_ip)
    except HTTPException as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=_UPLOAD_MESSAGES.get(e.status_code, "That photo could not be used. Please take it again."),
        ) from None


def scan_failure(code: str, reason: str | None = None) -> dict[str, Any]:
    """A failed scan. "ocr_unavailable" (AI off, or the AI call failed) tells the
    screen to switch to typing and the sample card instead of asking for a retake."""
    off = code == "ocr_unavailable"
    out = {
        "success": False,
        "error": code,
        "message": (AI_FAILED_MESSAGE if off and reason == "ai_failed"
                    else SCAN_MESSAGES.get(code, SCAN_MESSAGES["ocr_failed"])),
        "ai_available": False if off else claude.available(),
    }
    if off and reason == "ai_failed":
        out["reason"] = "ai_failed"
    return out


def off_reason() -> str | None:
    """"ai_failed" while the AI service's refusal holds AI off, else None (no key, or a
    budget pause), for scan_failure's wording."""
    return "ai_failed" if claude.off_kind() == "provider_error" else None


@router.post("/scan-id")
async def scan_id(
    hospital_id: str = Path(...),
    image_file: UploadFile = File(...),
    request: Request = None,
) -> dict:
    """Read a US driver's license or state ID with Claude vision."""
    identity_hash, source_ip = client_identity(request)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    if not claude.available():
        # Nothing can read the photo, so do not make the patient retake it.
        return scan_failure("ocr_unavailable", off_reason())
    quota.check_and_consume(identity_hash, "scan_insurance", source_ip=source_ip)
    raw_bytes = await read_card_photo(image_file, source_ip)
    fields = id_ocr.extract(raw_bytes, mime_type="image/jpeg")
    if "error" in fields:
        out = scan_failure(str(fields["error"]), fields.get("reason"))
        if fields.get("error") == "needs_rescan" and fields.get("message"):
            out["message"] = str(fields["message"])
        return out
    return {"success": True, "fields": fields, "ai_available": True, "source": "ocr"}


@router.post("/scan-id/sample")
def scan_id_sample(
    hospital_id: str = Path(...),
    request: Request = None,
) -> dict:
    """The fictional sample license, in the same shape as a successful scan."""
    identity_hash, source_ip = client_identity(request)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    return {
        "success": True,
        "fields": demo_records.sample_id_fields(),
        "ai_available": claude.available(),
        "source": "sample",
        "sample": True,
        "message": "This is a sample license for a made-up person, Jordan Rivera.",
    }


class IdentityLookupBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Loose types so an odd value gets a plain answer, not a validation error.
    first_name: Any = ""
    last_name: Any = ""
    dob: Any = ""                     # YYYY-MM-DD
    license_number: Any = ""
    issuing_state: Any = ""
    insurance_member_id: Any = ""
    insurance_provider: Any = ""


@router.post("/identity/lookup")
def identity_lookup(
    hospital_id: str = Path(...),
    body: IdentityLookupBody | None = None,
    request: Request = None,
) -> dict[str, Any]:
    """Look up a returning patient in the demo's fictional records. Returns the
    record and a prefill payload so the intake form can pre-populate.

    Match order: first + last name with date of birth, then insurance member id.
    No match returns ``{"matched": false}`` so the flow continues normally.
    """
    # Unauthenticated and returns health details, so blocklist and quota run
    # before anything else.
    identity_hash, source_ip = client_identity(request)
    blocklist.enforce(identity_hash, source_ip=source_ip)
    quota.check_and_consume(identity_hash, "identity.lookup", source_ip=source_ip)

    b = body or IdentityLookupBody()

    def text(v: Any) -> str:
        return "" if v is None or isinstance(v, (dict, list)) else str(v).strip()

    first = text(b.first_name)[:100]
    last = text(b.last_name)[:100]
    member_id = text(b.insurance_member_id)[:64]
    if not ((first and last) or member_id):
        raise HTTPException(
            status_code=400,
            detail="Enter your first and last name, or the member ID on your insurance card.",
        )

    record = demo_records.match(
        first_name=first,
        last_name=last,
        dob=text(b.dob)[:10],
        member_id=member_id,
    )
    method = record.pop("_match_method", "") if record else ""

    if not record:
        return {"matched": False, "reason": "no returning-patient record matched"}

    return {
        "matched": True,
        "match_method": method,
        "ehr_record": record,
        "prefill": _record_to_prefill(record),
    }


# --- helpers -------------------------------------------------------------------


def _record_to_prefill(record: dict) -> dict:
    """Map the record into the medical_info shape the patient intake form
    expects, so the form arrives pre-filled with known allergies, medicines and
    conditions."""
    def _filter_none(arr):
        return [str(x) for x in (arr or []) if x and str(x).lower() != "none"]

    age = None
    dob = record.get("dob") or ""
    if dob:
        try:
            from datetime import date  # noqa: PLC0415
            y, m, d = (int(x) for x in dob.split("-"))
            today = date.today()
            age = today.year - y - ((today.month, today.day) < (m, d))
        except Exception:  # noqa: BLE001
            age = None

    return {
        "age": age,
        "sex": _normalize_sex(record.get("sex", "")),
        "allergies": _filter_none(record.get("allergies")),
        "medications": _filter_none(record.get("medications")),
        "conditions": _filter_none(record.get("conditions")),
        "insurance_hint": record.get("insurance", ""),
        "emergency_contact": record.get("emergency_contact", ""),
        "primary_care_provider": record.get("primary_care_provider", ""),
        "prior_visits_count": len(record.get("prior_visits") or []),
    }


def _normalize_sex(s: str) -> str | None:
    if not s:
        return None
    s = s.lower()
    if s in ("m", "male"):
        return "male"
    if s in ("f", "female"):
        return "female"
    return "other"
