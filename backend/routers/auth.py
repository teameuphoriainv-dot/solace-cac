"""Clinician sign-in: name + PIN -> bcrypt check -> JWT.

Brute-force protection has two layers:
  - per account: 5 wrong PINs in 15 minutes locks that account (jwt_auth),
  - per device: many failures across accounts block sign-in from that device.
The device block uses its own key ("<device hash>#auth"), so wrong PINs on the
nurse screen never block a patient check-in from the same laptop.
"""

from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel
from lib import audit as _audit
from lib import blocklist, jwt_auth, quota


log = logging.getLogger(__name__)


router = APIRouter()


class LoginBody(BaseModel):
    clinician_name: str
    pin: str
    # Optional TOTP second factor, required only for clinicians who confirmed
    # MFA enrollment. The demo clinicians sign in with a PIN only.
    mfa_code: str | None = None


@router.post("/auth/login")
def login(
    hospital_id: str = Path(...),
    body: LoginBody | None = None,
    request: Request = None,
) -> dict:
    if body is None or not body.clinician_name.strip() or not body.pin:
        raise HTTPException(status_code=400, detail="Please choose your name and enter your PIN.")

    source_ip = None
    user_agent = None
    if request is not None:
        source_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")

    # Device-level limits run before any lookup or bcrypt work. The per-account
    # lockout below only protects one known account; this caps guessing that
    # rotates across many accounts from one device.
    identity_hash = quota.identity_of(source_ip, user_agent)
    auth_identity = f"{identity_hash}#auth"
    blocklist.enforce(auth_identity, source_ip=source_ip)
    quota.check_and_consume(identity_hash, "auth.login", source_ip=source_ip)

    clinician = jwt_auth.find_clinician(hospital_id, body.clinician_name)
    if not clinician:
        # Burn a bcrypt-equivalent slice of CPU so an attacker cannot tell an
        # unknown clinician from a bad-PIN-on-known-clinician via timing.
        jwt_auth.dummy_verify()
        blocklist.record_abuse(auth_identity, "auth.login_unknown_clinician",
                               threshold=blocklist.AUTH_ABUSE_THRESHOLD)
        # Same 401 for an unknown name and a wrong PIN, so names cannot be probed.
        _audit.record(
            clinician_id=None,
            clinician_name=body.clinician_name,
            action="auth.login_failed",
            source_ip=source_ip,
            status_code=401,
            extra={"reason": "unknown_clinician"},
        )
        raise HTTPException(status_code=401, detail="Incorrect name or PIN.")

    # Brute-force lockout check
    if jwt_auth.check_lockout(clinician["clinician_id"]):
        _audit.record(
            clinician_id=clinician["clinician_id"],
            clinician_name=clinician["name"],
            action="auth.login_locked_out",
            source_ip=source_ip,
            status_code=429,
            extra={"reason": "brute_force_lockout"},
        )
        minutes = max(1, jwt_auth.lockout_seconds() // 60)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many wrong PINs for {clinician['name']}. This account is locked for "
                f"{minutes} minutes. You can sign in as another clinician in the meantime."
            ),
        )

    if not jwt_auth.verify_pin(body.pin, clinician.get("pin_hash", "")):
        # May lock this account; the device counter catches guesses spread thinly
        # across many accounts.
        jwt_auth.record_failed_attempt(clinician["clinician_id"])
        blocklist.record_abuse(auth_identity, "auth.login_bad_pin",
                               threshold=blocklist.AUTH_ABUSE_THRESHOLD)
        _audit.record(
            clinician_id=clinician["clinician_id"],
            clinician_name=clinician["name"],
            action="auth.login_failed",
            source_ip=source_ip,
            status_code=401,
            extra={"reason": "bad_pin"},
        )
        raise HTTPException(status_code=401, detail="Incorrect name or PIN.")

    # Second factor (TOTP), only for clinicians who confirmed MFA enrollment. A wrong
    # or missing code counts as a failed sign-in and no token is issued. The code is
    # never logged.
    if jwt_auth.mfa_enabled(clinician):
        if not jwt_auth.verify_mfa_code(clinician, body.mfa_code):
            jwt_auth.record_failed_attempt(clinician["clinician_id"])
            blocklist.record_abuse(auth_identity, "auth.login_bad_mfa",
                                   threshold=blocklist.AUTH_ABUSE_THRESHOLD)
            _audit.record(
                clinician_id=clinician["clinician_id"],
                clinician_name=clinician["name"],
                action="auth.login_failed",
                source_ip=source_ip,
                status_code=401,
                extra={"reason": "mfa_required" if not body.mfa_code else "bad_mfa_code"},
            )
            # 401 with a distinct detail so the frontend can prompt for a code,
            # but the audit reason above stays internal.
            raise HTTPException(
                status_code=401,
                detail="A valid authenticator code is required.",
            )

    # Success: clear the failed-attempt counter and issue a token.
    jwt_auth.clear_failed_attempts(clinician["clinician_id"])
    token, sess = jwt_auth.issue_token(clinician)
    jwt_auth.update_last_login(clinician["clinician_id"])
    _audit.record(
        clinician_id=clinician["clinician_id"],
        clinician_name=clinician["name"],
        action="auth.login_success",
        source_ip=source_ip,
        status_code=200,
    )
    return {
        "token": token,
        "clinician_id": sess.clinician_id,
        "name": sess.name,
        "role": sess.role,
        "hospital_id": sess.hospital_id,
        "expires_at": sess.exp,
    }
