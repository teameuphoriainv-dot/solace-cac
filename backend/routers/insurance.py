"""Insurance card scan.

  - POST /api/{hospital_id}/scan-insurance          read a card photo (needs an AI key)
  - POST /api/{hospital_id}/scan-insurance/sample   the fictional sample card, no camera or key

The photo is only sent to the AI service after the patient agrees
(``consent_granted``). With no key nothing is sent and the answer is
``ocr_unavailable``, the same code the ID scan uses.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Path, Request, UploadFile

from lib import blocklist, claude, quota
from routers.identity import client_identity, off_reason, read_card_photo, scan_failure
from services import demo_records, insurance_ocr

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/scan-insurance")
async def scan_insurance(
    hospital_id: str = Path(...),
    image_file: UploadFile = File(...),
    consent_granted: str | None = Form(None),
    request: Request = None,
) -> dict:
    identity, source_ip = client_identity(request)
    blocklist.enforce(identity, source_ip=source_ip)
    if not claude.available():
        return scan_failure("ocr_unavailable", off_reason())

    # The card shows a name and member numbers, so it goes to the AI service
    # only with the patient's agreement.
    if str(consent_granted or "").lower() not in {"true", "1", "yes"}:
        from lib import audit as _audit  # noqa: PLC0415

        _audit.record(
            clinician_id=None, clinician_name=None,
            action="abuse.insurance_scan_no_consent",
            source_ip=source_ip, status_code=403,
            extra={"identity": identity},
        )
        raise HTTPException(
            status_code=403,
            detail="Please agree to the privacy notice before we read your card.",
        )

    quota.check_and_consume(identity, "scan_insurance", source_ip=source_ip)
    bytes_ = await read_card_photo(image_file, source_ip)
    # Always JPEG after sanitizing (EXIF stripped, decoded and re-encoded).
    result = insurance_ocr.extract(bytes_, mime_type="image/jpeg")
    if result.get("error"):
        out = scan_failure(str(result["error"]), result.get("reason"))
        if result.get("error") == "needs_rescan" and result.get("message"):
            out["message"] = str(result["message"])
        return out
    return {"success": True, "fields": result, "ai_available": True, "source": "ocr"}


@router.post("/scan-insurance/sample")
def scan_insurance_sample(
    hospital_id: str = Path(...),
    request: Request = None,
) -> dict:
    """The fictional sample card, in the same shape as a successful scan."""
    identity, source_ip = client_identity(request)
    blocklist.enforce(identity, source_ip=source_ip)
    return {
        "success": True,
        "fields": demo_records.sample_insurance_fields(),
        "ai_available": claude.available(),
        "source": "sample",
        "sample": True,
        "message": "This is a sample card for a made-up person, Jordan Rivera.",
    }
