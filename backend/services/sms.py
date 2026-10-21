"""Outbound text messages for the patient's "text me my care steps" button.

A real text is sent only when a provider is explicitly configured:

  * ``SMS_PROVIDER=twilio`` plus ``TWILIO_ACCOUNT_SID``, ``TWILIO_AUTH_TOKEN``
    and ``TWILIO_SMS_FROM_NUMBER`` (or ``TWILIO_FROM_NUMBER``), or
  * ``SMS_PROVIDER=sns`` while running with ``SOLACE_MODE=aws``.

Anything else (including a stray ``AWS_REGION`` on a laptop) means texting is
off, and callers show the patient a preview of the exact message instead.
Every function returns a dict and never raises. Phone numbers are never logged
in plain text: logs carry a salted hash plus the last four digits.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re

import httpx

from lib import sms_i18n

log = logging.getLogger(__name__)

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

# Inbound keywords that mean opt-out / opt-in (Twilio Advanced
# Opt-Out mirrors this list; we honor it locally too for non-Twilio paths).
_OPT_OUT_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
_OPT_IN_KEYWORDS = {"start", "yes", "unstop"}
_HELP_KEYWORDS = {"help", "info"}

# --- config -----------------------------------------------------------------


def _twilio_account_sid() -> str:
    return os.environ.get("TWILIO_ACCOUNT_SID", "")


def _twilio_auth_token() -> str:
    return os.environ.get("TWILIO_AUTH_TOKEN", "")


def _twilio_from_number() -> str:
    # Accept either an explicit name or the generic voice "from" number so a
    # deployment that already set TWILIO_FROM_NUMBER for voice works for SMS.
    return os.environ.get("TWILIO_SMS_FROM_NUMBER") or os.environ.get("TWILIO_FROM_NUMBER", "")


def _twilio_configured() -> bool:
    return bool(_twilio_account_sid() and _twilio_auth_token() and _twilio_from_number())


def _requested_provider() -> str:
    return os.environ.get("SMS_PROVIDER", "").strip().lower()


def _provider() -> str:
    """The active SMS backend: 'twilio' | 'sns' | 'none'. Never guessed from
    ambient cloud settings."""
    requested = _requested_provider()
    if requested == "twilio" and _twilio_configured():
        return "twilio"
    if requested == "sns":
        from lib.config import settings  # noqa: PLC0415

        if settings.solace_mode == "aws":
            return "sns"
    return "none"


def is_configured() -> bool:
    """True only when a provider is explicitly set up (see module docstring)."""
    try:
        return _provider() != "none"
    except Exception:  # noqa: BLE001 - a config read must never break a caller
        return False


# --- PHI-safe logging --------------------------------------------------------


def hash_phone(raw: str | None) -> str:
    """HMAC-SHA256 a phone number for log use; never log it in plain text.

    Reuses ``lib.intake_nonce._hmac_key`` as the salt, like
    ``lib.quota.identity_of``. Format: ``last4:hash`` so a person can still
    match a number by eye while the rest stays opaque.
    """
    phone = (raw or "").strip()
    if not phone:
        return "none"
    last4 = re.sub(r"\D", "", phone)[-4:] or "????"
    try:
        from lib.intake_nonce import _hmac_key  # noqa: PLC0415 - shared salt, avoid import cycle

        digest = hmac.new(_hmac_key(), phone.encode(), hashlib.sha256).hexdigest()
    except Exception:  # noqa: BLE001 - degrade gracefully, still no plaintext
        digest = hashlib.sha256(phone.encode()).hexdigest()
    return f"{last4}:{digest[:16]}"


def normalize_phone(raw: str | None) -> str:
    """Strip everything except digits and a leading +. Accepts US-formatted
    numbers and converts (555) 555-0123 -> +15555550123."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return ""  # unknown shape: caller treats as invalid


# --- opt-out keywords --------------------------------------------------------


def classify_inbound(body: str | None) -> str:
    """Classify an inbound SMS body as ``opt_out`` | ``opt_in`` | ``help`` |
    ``message``."""
    word = (body or "").strip().lower()
    # Keep only the first token: carriers send "STOP" but users send "stop please".
    word = word.split()[0] if word else ""
    if word in _OPT_OUT_KEYWORDS:
        return "opt_out"
    if word in _OPT_IN_KEYWORDS:
        return "opt_in"
    if word in _HELP_KEYWORDS:
        return "help"
    return "message"


def is_opted_out(phone: str | None) -> bool:
    """Whether a number has texted STOP. Twilio enforces opt-outs at the
    carrier edge; this build keeps no opt-out store, so it returns False and
    callers that know better pass ``send(..., opted_out=True)``."""
    return False


# --- message templates -------------------------------------------------------

# The frame around the care steps in all 20 languages lives in lib/sms_i18n.py.
_TEXT = sms_i18n.TEXT
_ADDRESS = sms_i18n.ADDRESS
RTL_LANGUAGES = sms_i18n.RTL_LANGUAGES

# Older names, kept for imports: one table per line of the frame.
_FOOTERS: dict[str, str] = {lang: "\n\n" + t["footer"] for lang, t in _TEXT.items()}
_CARE_INTRO: dict[str, str] = {lang: t["intro"] for lang, t in _TEXT.items()}
_CARE_INTRO_NO_STEPS: dict[str, str] = {lang: t["intro_none"] for lang, t in _TEXT.items()}
_CARE_WORSE: dict[str, str] = {lang: t["worse"] for lang, t in _TEXT.items()}
_CARE_RETURN: dict[str, str] = {lang: t["return"] for lang, t in _TEXT.items()}

_REMINDER_BODY: dict[str, str] = {
    "en": (
        "{name}, reminder: your visit at {hospital} is {when}. "
        "Confirmation: {code}. Reply CANCEL to reschedule."
    ),
    "es": (
        "{name}, recordatorio: su cita en {hospital} es {when}. "
        "Confirmación: {code}. Responda CANCEL para reprogramar."
    ),
    "zh": (
        "{name}，提醒：您在 {hospital} 的预约"
        "时间为 {when}。确认码：{code}。"
        "回复 CANCEL 可重新安排。"
    ),
    "vi": (
        "{name}, nhắc nhở: cuộc hẹn của bạn tại {hospital} là {when}. "
        "Mã xác nhận: {code}. Trả lời CANCEL để đổi lịch."
    ),
}

_DEFAULT_GREETING: dict[str, str] = {lang: t["hello"] for lang, t in _TEXT.items()}


def _lang(language: str | None) -> str:
    """Resolve a language tag to a supported template key; default English."""
    code = (language or "en").strip().lower().split("-")[0]
    return code if code in _TEXT else "en"


def message_language(language: str | None) -> str:
    """The language the care-steps text is written in (English when not supported)."""
    return _lang(language)


def text_direction(language: str | None) -> str:
    """"rtl" for Arabic, Persian and Urdu, else "ltr"."""
    return "rtl" if _lang(language) in RTL_LANGUAGES else "ltr"


def footer(language: str | None = "en") -> str:
    """The sender line and STOP instructions in the patient's language."""
    return _FOOTERS[_lang(language)]


# --- send --------------------------------------------------------------------


def send(
    to: str,
    body: str,
    *,
    append_footer: bool = True,
    language: str | None = "en",
    opted_out: bool = False,
) -> dict:
    """Send one SMS via the configured provider. Returns:
      {success: bool, sid?: str, status?: str, reason?: str, message?: str}
    Reasons: "sms_off" | "invalid_number" | "twilio_error"
             | "sns_error" | "empty_body" | "opted_out"

    ``language`` selects the footer language. The ``to`` number is never
    logged in plain text, only its hash.
    """
    if not is_configured():
        return {"success": False, "reason": "sms_off",
                "message": "Texting is off in this demo."}
    if not body or not body.strip():
        return {"success": False, "reason": "empty_body"}

    e164 = normalize_phone(to)
    if not e164 or not _E164_RE.match(e164):
        # Do not echo the raw number: log the hash, return a generic message.
        log.info("sms send rejected: invalid number %s", hash_phone(to))
        return {"success": False, "reason": "invalid_number",
                "message": "The phone number provided is not valid."}

    if opted_out or is_opted_out(e164):
        log.info("sms send skipped: %s has opted out", hash_phone(e164))
        return {"success": False, "reason": "opted_out",
                "message": "This number has opted out of text messages."}

    final_body = body.strip()
    if append_footer:
        final_body = final_body + footer(language)

    if _provider() == "sns":
        return _send_via_sns(e164, final_body)
    return _send_via_twilio(e164, final_body)


def _send_via_sns(e164: str, final_body: str) -> dict:
    """Send via AWS SNS as a Transactional message. Only reachable when
    ``SMS_PROVIDER=sns`` in aws mode."""
    try:
        import boto3  # noqa: PLC0415 - optional dep, only needed on the SNS path

        region = os.environ.get("AWS_REGION", "us-east-1")
        sns = boto3.client("sns", region_name=region)
        attrs = {
            "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
        }
        sender_id = os.environ.get("SNS_SMS_SENDER_ID")
        if sender_id:
            attrs["AWS.SNS.SMS.SenderID"] = {"DataType": "String", "StringValue": sender_id}
        resp = sns.publish(PhoneNumber=e164, Message=final_body, MessageAttributes=attrs)
        message_id = resp.get("MessageId", "")
        log.info("sns sms accepted for %s id=%s", hash_phone(e164), message_id or "unknown")
        return {
            "success": True,
            "sid": message_id,
            "status": "queued",
            "to_hash": hash_phone(e164),
        }
    except Exception as e:  # noqa: BLE001 - never raise; SMS is a nice-to-have
        # Exception text can include the number: log only the type.
        log.warning("sns sms exception for %s: %s", hash_phone(e164), type(e).__name__)
        return {"success": False, "reason": "sns_error",
                "message": "The text message could not be sent."}


def _send_via_twilio(e164: str, final_body: str) -> dict:
    account_sid = _twilio_account_sid()
    auth_token = _twilio_auth_token()
    from_number = _twilio_from_number()

    # Twilio outbound SMS REST API: basic-auth with account SID + auth token.
    auth_b64 = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                url,
                data={"To": e164, "From": from_number, "Body": final_body},
                headers={"Authorization": f"Basic {auth_b64}"},
            )
            if resp.status_code >= 400:
                # resp.text may contain the To number: never log it raw.
                log.warning("twilio sms %d for %s", resp.status_code, hash_phone(e164))
                return {"success": False, "reason": "twilio_error",
                        "message": "The text message could not be sent."}
            payload = resp.json()
            status = str(payload.get("status", "")).lower()
            log.info("twilio sms accepted for %s status=%s", hash_phone(e164), status or "unknown")
            return {
                "success": True,
                "sid": payload.get("sid", ""),
                "status": status or "queued",
                "to_hash": hash_phone(e164),
            }
    except Exception as e:  # noqa: BLE001
        # Exception text can include the URL/number: log only the type.
        log.warning("twilio sms exception for %s: %s", hash_phone(e164), type(e).__name__)
        return {"success": False, "reason": "twilio_error",
                "message": "The text message could not be sent."}


# --- templates ---------------------------------------------------------------


def _who(patient_name: str, lang: str) -> str:
    first = (patient_name or "").strip().split(" ")[0]
    if not first:
        return _TEXT[lang]["hello"]
    return _ADDRESS.get(lang, "{name}").format(name=first)


def render_care_message(
    *, patient_name: str, hospital_name: str,
    care_instructions: list[str], when_to_return: str = "",
    language: str | None = "en", for_parent: bool = False,
) -> str:
    """The care-steps text the patient asked for, without the footer.

    ``when_to_return`` is the care team's own wording (a full sentence) when
    they published a summary; otherwise the standard safety lines are used.
    ``for_parent`` (a child under 12) greets the parent instead of the child and
    talks about "your child".
    """
    lang = _lang(language)
    text = _TEXT[lang]
    prefix = "parent_" if for_parent else ""
    intro = text[f"{prefix}intro" if care_instructions else f"{prefix}intro_none"]
    lines = [intro.format(who=_who(patient_name, lang), hospital=hospital_name)]
    for i, step in enumerate(care_instructions[:4], 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    if when_to_return and when_to_return.strip():
        lines.append(when_to_return.strip())
    else:
        lines.append(text[f"{prefix}worse"])
        lines.append(text[f"{prefix}return"])
    return "\n".join(lines)


def full_message(body: str, language: str | None = "en") -> str:
    """Exactly what the phone would receive: the body plus the footer."""
    return body.strip() + footer(language)


def render_appointment_reminder(
    *, patient_name: str, hospital_name: str,
    when_human: str, confirmation_code: str,
    language: str | None = "en",
) -> str:
    lang = _lang(language)
    if lang not in _REMINDER_BODY:  # reminders are written in four languages so far
        lang = "en"
    first = patient_name.split(" ")[0] if patient_name else _DEFAULT_GREETING[lang]
    return _REMINDER_BODY[lang].format(
        name=first, hospital=hospital_name, when=when_human, code=confirmation_code,
    )
