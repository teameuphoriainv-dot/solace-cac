"""JWT sign/verify, clinician PIN check (bcrypt) and brute-force lockout.

- Clinician records with bcrypt-hashed PINs live in lib/accounts.py locally
  (DynamoDB `solace-clinicians` in aws mode).
- JWT: HS256, 30-minute expiry, sub=clinician_id, plus name, role and hospital.
- Signing key: SOLACE_JWT_SECRET. If it is not set, each server start makes a random
  key, so sign-ins do not survive a restart (fine for a demo, and nobody can forge a
  token from a key printed in public code).
- Lockout: 5 wrong PINs in 15 minutes locks that account (5 minutes in local mode,
  30 minutes in aws mode).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

ACCESS_TTL_SECONDS = 30 * 60  # 30 minutes absolute
MAX_FAILED_ATTEMPTS = 5       # lock after this many failures
LOCKOUT_WINDOW_SECONDS = 900  # 15-minute window for counting failures
LOCKOUT_DURATION_SECONDS = 1800  # 30-minute lockout in aws mode
LOCAL_LOCKOUT_SECONDS = 300      # 5 minutes on the demo, where the PINs are public anyway


def lockout_seconds() -> int:
    return LOCKOUT_DURATION_SECONDS if settings.solace_mode == "aws" else LOCAL_LOCKOUT_SECONDS

# JWT algorithm confusion hardening: the accepted algorithm set is a fixed
# constant and is NEVER read from the secret payload or the token header.
# Allowing the token to dictate its own algorithm enables the classic
# "alg":"none" bypass and HS/RS key-confusion attacks. HS256 is the only
# algorithm Solace ever signs with, so it is the only one we will verify.
JWT_ALGORITHMS = ["HS256"]

# A throwaway bcrypt hash used to burn a constant amount of CPU when a
# clinician record is missing, so an attacker cannot distinguish "unknown
# clinician" from "bad PIN" via response timing (username-enumeration oracle).
# Generated once with bcrypt.gensalt(); value is not a real credential.
_DUMMY_PIN_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO6PqkN5lF.B6Z6dQ8x9zXq0pY3uVwT1m"


@dataclass
class Session:
    clinician_id: str
    name: str
    role: str
    hospital_id: str
    exp: int


class AuthError(Exception):
    """Raised for any auth failure (bad PIN, expired token, unknown clinician)."""


@lru_cache(maxsize=1)
def _auth_secret() -> dict:
    """The JWT signing key, read once per process.

    Local mode: SOLACE_JWT_SECRET (or the older JWT_SIGNING_KEY) from the
    environment, else a random key made at startup. aws mode reads the
    `solace/clinician-auth` secret from Secrets Manager.
    """
    if settings.solace_mode != "aws":
        key = os.environ.get("SOLACE_JWT_SECRET") or os.environ.get("JWT_SIGNING_KEY")
        if not key:
            key = secrets.token_urlsafe(32)
            if "pytest" not in sys.modules:
                log.warning(
                    "SOLACE_JWT_SECRET is not set: using a random signing key for this run. "
                    "Clinicians will need to sign in again after a restart. Run a single "
                    "worker, or set SOLACE_JWT_SECRET so every worker shares one key."
                )
        return {"JWT_SIGNING_KEY": key, "JWT_ALGORITHM": "HS256", "DEMO_CLINICIANS": {}}
    import boto3  # noqa: PLC0415

    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    resp = client.get_secret_value(SecretId="solace/clinician-auth")
    return json.loads(resp["SecretString"])


def _table(name: str):
    import boto3  # noqa: PLC0415

    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def find_clinician(hospital_id: str, name: str) -> dict | None:
    """Look up a clinician by their display name within a hospital."""
    if settings.solace_mode != "aws":
        # Local mode: clinicians live in the in-memory accounts store. Mirror the
        # accounts.py local/aws split so PIN + MFA flows run on a laptop without
        # AWS, exactly like the magic-link path already does.
        from lib import accounts  # noqa: PLC0415 (avoid import cycle at module load)

        wanted = name.lower().strip()
        for rec in accounts._clinicians.values():
            if rec.get("hospital_id") == hospital_id and rec.get("name_lower") == wanted:
                return rec
        return None
    resp = _table("solace-clinicians").query(
        IndexName="hospital_name-index",
        KeyConditionExpression="hospital_id = :h AND name_lower = :n",
        ExpressionAttributeValues={":h": hospital_id, ":n": name.lower().strip()},
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def get_clinician(clinician_id: str) -> dict | None:
    """Fetch a single clinician record by id (local in-memory or DDB)."""
    if settings.solace_mode != "aws":
        from lib import accounts  # noqa: PLC0415

        return accounts._clinicians.get(clinician_id)
    resp = _table("solace-clinicians").get_item(
        Key={"clinician_id": clinician_id}, ConsistentRead=True
    )
    return resp.get("Item")


def verify_pin(plain_pin: str, stored_hash: str) -> bool:
    import bcrypt  # noqa: PLC0415

    try:
        return bcrypt.checkpw(plain_pin.encode(), stored_hash.encode())
    except Exception:  # noqa: BLE001
        return False


def dummy_verify() -> None:
    """Burn a bcrypt-equivalent amount of CPU without revealing anything.

    Called on the "unknown clinician" path so login latency is statistically
    indistinguishable from the "known clinician, bad PIN" path. Closes the
    username-enumeration timing oracle. Result is intentionally discarded.
    """
    import bcrypt  # noqa: PLC0415

    try:
        bcrypt.checkpw(b"timing-equalizer", _DUMMY_PIN_HASH.encode())
    except Exception:  # noqa: BLE001
        pass


def _local_clinician(clinician_id: str) -> dict | None:
    """Local mode keeps lockout counters on the in-memory account record itself."""
    from lib import accounts  # noqa: PLC0415 (avoid import cycle at module load)

    return accounts._clinicians.get(clinician_id)


def check_lockout(clinician_id: str) -> bool:
    """Return True if the clinician is currently locked out due to too many failed attempts."""
    if settings.solace_mode != "aws":
        rec = _local_clinician(clinician_id) or {}
        return int(rec.get("locked_until", 0) or 0) > int(time.time())
    try:
        tbl = _table("solace-clinicians")
        resp = tbl.get_item(
            Key={"clinician_id": clinician_id},
            ProjectionExpression="failed_attempts, locked_until",
            ConsistentRead=True,
        )
        item = resp.get("Item")
        if not item:
            return False
        locked_until = int(item.get("locked_until", 0))
        if locked_until and int(time.time()) < locked_until:
            return True
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("lockout check failed for %s: %s", clinician_id, e)
        return False  # fail open: don't block legitimate login on DDB errors


def record_failed_attempt(clinician_id: str) -> None:
    """Increment failed login counter. Triggers lockout at MAX_FAILED_ATTEMPTS."""
    if settings.solace_mode != "aws":
        rec = _local_clinician(clinician_id)
        if rec is None:
            return
        now = int(time.time())
        if now - int(rec.get("last_failed_at", 0) or 0) > LOCKOUT_WINDOW_SECONDS:
            rec["failed_attempts"] = 0  # the sliding window expired, start a fresh count
        rec["failed_attempts"] = int(rec.get("failed_attempts", 0) or 0) + 1
        rec["last_failed_at"] = now
        if rec["failed_attempts"] >= MAX_FAILED_ATTEMPTS:
            rec["locked_until"] = now + lockout_seconds()
        return
    try:
        now = int(time.time())
        tbl = _table("solace-clinicians")

        # Read the prior counter first so we can honor the sliding window. If the
        # last failure is older than LOCKOUT_WINDOW_SECONDS, this failure starts a
        # fresh window (count = 1) instead of adding to a stale tally. Otherwise a
        # monotonic counter would eventually lock out a clinician who never made 5
        # mistakes inside any 15-minute window (the documented policy).
        prior = tbl.get_item(
            Key={"clinician_id": clinician_id},
            ProjectionExpression="failed_attempts, last_failed_at",
        ).get("Item", {})
        prior_last = int(prior.get("last_failed_at", 0) or 0)
        window_expired = prior_last and (now - prior_last) > LOCKOUT_WINDOW_SECONDS

        if window_expired:
            resp = tbl.update_item(
                Key={"clinician_id": clinician_id},
                UpdateExpression="SET failed_attempts = :one, last_failed_at = :now",
                ExpressionAttributeValues={":one": 1, ":now": now},
                ReturnValues="ALL_NEW",
            )
        else:
            resp = tbl.update_item(
                Key={"clinician_id": clinician_id},
                UpdateExpression=(
                    "SET failed_attempts = if_not_exists(failed_attempts, :zero) + :one, "
                    "last_failed_at = :now"
                ),
                ExpressionAttributeValues={":zero": 0, ":one": 1, ":now": now},
                ReturnValues="ALL_NEW",
            )
        attrs = resp.get("Attributes", {})
        attempts = int(attrs.get("failed_attempts", 0))

        if attempts >= MAX_FAILED_ATTEMPTS:
            # Lock the account
            tbl.update_item(
                Key={"clinician_id": clinician_id},
                UpdateExpression="SET locked_until = :until",
                ExpressionAttributeValues={
                    ":until": now + LOCKOUT_DURATION_SECONDS,
                },
            )
            log.warning(
                "clinician %s locked out for %d minutes after %d failed attempts",
                clinician_id, LOCKOUT_DURATION_SECONDS // 60, attempts,
            )
    except Exception as e:  # noqa: BLE001
        log.warning("failed to record login failure for %s: %s", clinician_id, e)


def clear_failed_attempts(clinician_id: str) -> None:
    """Reset failed login counter on successful login."""
    if settings.solace_mode != "aws":
        rec = _local_clinician(clinician_id)
        if rec is not None:
            rec["failed_attempts"] = 0
            rec.pop("locked_until", None)
        return
    try:
        _table("solace-clinicians").update_item(
            Key={"clinician_id": clinician_id},
            UpdateExpression="SET failed_attempts = :zero REMOVE locked_until",
            ExpressionAttributeValues={":zero": 0},
        )
    except Exception as e:  # noqa: BLE001
        log.warning("could not clear failed attempts for %s: %s", clinician_id, e)


def issue_token(clinician: dict) -> tuple[str, Session]:
    import jwt  # noqa: PLC0415

    now = int(time.time())
    sess = Session(
        clinician_id=clinician["clinician_id"],
        name=clinician["name"],
        role=clinician.get("role", "clinician"),
        hospital_id=clinician["hospital_id"],
        exp=now + ACCESS_TTL_SECONDS,
    )
    claims = {
        "sub": sess.clinician_id,
        "name": sess.name,
        "role": sess.role,
        "hid": sess.hospital_id,
        "iat": now,
        "exp": sess.exp,
    }
    token = jwt.encode(claims, _auth_secret()["JWT_SIGNING_KEY"], algorithm=JWT_ALGORITHMS[0])
    return token, sess


def verify_token(token: str) -> Session:
    import jwt  # noqa: PLC0415

    secret = _auth_secret()
    try:
        # Algorithm allowlist is the fixed JWT_ALGORITHMS constant, never the
        # secret payload, never the token header. This blocks "alg":"none" and
        # HS/RS key-confusion attacks. `require=["exp"]` rejects tokens that
        # omit an expiry; `verify_exp` enforces it. Existing 30-min demo tokens
        # already carry `exp` (see issue_token), so they keep validating until
        # they naturally expire, so there is no mass 401 on deploy.
        claims = jwt.decode(
            token,
            secret["JWT_SIGNING_KEY"],
            algorithms=JWT_ALGORITHMS,
            options={"require": ["exp"], "verify_exp": True},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("token expired") from e
    except jwt.MissingRequiredClaimError as e:
        raise AuthError("token missing required claim") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}") from e
    try:
        return Session(
            clinician_id=claims["sub"],
            name=claims.get("name", ""),
            role=claims.get("role", "clinician"),
            hospital_id=claims["hid"],
            exp=claims["exp"],
        )
    except KeyError as e:
        raise AuthError(f"token missing required claim: {e}") from e


# ---- TOTP MFA (RFC 6238 second factor) ---------------------------------------------
# The TOTP secret is stored as `totp_secret` on the clinician record. `mfa_enabled`
# gates enforcement: an enrolled-but-unconfirmed clinician still signs in with a PIN
# only, so the demo sign-in never breaks. None of these helpers log the secret or the
# code; the secret leaves the system once, as the return value of enroll_mfa().


def _persist_clinician_fields(clinician_id: str, fields: dict[str, Any]) -> None:
    """Write the given attributes onto a clinician record (local or DDB)."""
    if settings.solace_mode != "aws":
        from lib import accounts  # noqa: PLC0415

        rec = accounts._clinicians.get(clinician_id)
        if rec is None:
            raise AuthError("unknown clinician")
        rec.update(fields)
        return
    expr = "SET " + ", ".join(f"{k} = :{k}" for k in fields)
    values = {f":{k}": v for k, v in fields.items()}
    _table("solace-clinicians").update_item(
        Key={"clinician_id": clinician_id},
        UpdateExpression=expr,
        ExpressionAttributeValues=values,
    )


def mfa_enabled(clinician: dict) -> bool:
    """True only when the clinician has confirmed a TOTP enrollment."""
    return bool(clinician.get("mfa_enabled")) and bool(clinician.get("totp_secret"))


def enroll_mfa(clinician_id: str, account: str, *, issuer: str = "Solace") -> dict:
    """Provision a fresh TOTP secret for a clinician (does NOT enable MFA yet).

    Returns {"secret", "otpauth_uri"}, surfaced to the client exactly once so
    the user can scan the QR / key it into an authenticator app. MFA only turns
    on after confirm_mfa() validates a live code, proving the secret was stored.
    Re-enrolling overwrites any prior unconfirmed secret and resets the flag.
    """
    from lib import mfa  # noqa: PLC0415

    secret = mfa.generate_secret()
    _persist_clinician_fields(
        clinician_id, {"totp_secret": secret, "mfa_enabled": False}
    )
    return {
        "secret": secret,
        "otpauth_uri": mfa.provisioning_uri(secret, account=account, issuer=issuer),
    }


def confirm_mfa(clinician_id: str, code: str) -> bool:
    """Verify a code against the provisioned secret and, on success, enable MFA.

    Returns True and sets mfa_enabled=True iff the code is valid. Returns False
    (without enabling) if no secret is provisioned or the code is wrong.
    """
    from lib import mfa  # noqa: PLC0415

    clinician = get_clinician(clinician_id)
    if not clinician:
        return False
    secret = clinician.get("totp_secret")
    if not secret or not mfa.verify(secret, code):
        return False
    _persist_clinician_fields(clinician_id, {"mfa_enabled": True})
    return True


def verify_mfa_code(clinician: dict, code: str | None) -> bool:
    """Constant-time check of a login-time TOTP code for an MFA-enabled clinician.

    Returns False when no code is supplied or the secret is missing, so the
    caller rejects the login with 401 and never issues a JWT without the factor.
    """
    from lib import mfa  # noqa: PLC0415

    if not code:
        return False
    secret = clinician.get("totp_secret")
    if not secret:
        return False
    return mfa.verify(secret, code)


def disable_mfa(clinician_id: str) -> None:
    """Turn off MFA and drop the stored secret (e.g. admin reset)."""
    if settings.solace_mode != "aws":
        from lib import accounts  # noqa: PLC0415

        rec = accounts._clinicians.get(clinician_id)
        if rec is not None:
            rec["mfa_enabled"] = False
            rec.pop("totp_secret", None)
        return
    _table("solace-clinicians").update_item(
        Key={"clinician_id": clinician_id},
        UpdateExpression="SET mfa_enabled = :f REMOVE totp_secret",
        ExpressionAttributeValues={":f": False},
    )


def update_last_login(clinician_id: str) -> None:
    """Best-effort update of the clinician's last_login_at."""
    from datetime import datetime, timezone  # noqa: PLC0415

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if settings.solace_mode != "aws":
        rec = _local_clinician(clinician_id)
        if rec is not None:
            rec["last_login_at"] = now_iso
        return
    try:
        _table("solace-clinicians").update_item(
            Key={"clinician_id": clinician_id},
            UpdateExpression="SET last_login_at = :ts",
            ExpressionAttributeValues={":ts": now_iso},
        )
    except Exception as e:  # noqa: BLE001
        log.warning("could not update last_login_at for %s: %s", clinician_id, e)
