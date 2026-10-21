"""Log redaction: strip patient ids and tokens from log lines.

uvicorn logs every request line with its path, for example
`GET /api/demo/patients/fbc01b0a-.../refine-triage 200`. That UUID points at a
patient record, so it is replaced with [PID] before the line is written. Bearer
tokens and intake tokens that sneak into a message are replaced too.

The filter edits the record's arguments in place and keeps their number, because
uvicorn's access-log formatter unpacks exactly five arguments from every record.
"""
from __future__ import annotations

import logging
import re

# UUID4 shape: 8-4-4-4-12 hex
_UUID_RX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# Bearer tokens in Authorization headers that might sneak into traceback dumps
_BEARER_RX = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
# Nonce tokens (secrets.token_urlsafe produces A-Z a-z 0-9 _ -, 32 chars)
_NONCE_RX = re.compile(r"(intake_token[=:]\s*)[A-Za-z0-9_\-]{20,}")
_PATTERNS = (_UUID_RX, _BEARER_RX, _NONCE_RX)


def redact(text: str) -> str:
    text = _UUID_RX.sub("[PID]", text)
    text = _BEARER_RX.sub("Bearer [REDACTED]", text)
    return _NONCE_RX.sub(r"\1[REDACTED]", text)


def _needs_redaction(text: str) -> bool:
    return any(rx.search(text) for rx in _PATTERNS)


def _clean(value):
    return redact(value) if isinstance(value, str) and _needs_redaction(value) else value


class RedactPatientUUIDsFilter(logging.Filter):
    """Redact UUIDs and tokens in a record's msg and args without changing their shape."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _clean(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_clean(a) for a in args)
        elif isinstance(args, dict):
            record.args = {k: _clean(v) for k, v in args.items()}

        # A non-string argument (an exception, a dict) can still carry a secret in
        # its str(). Then flatten the message, except for uvicorn's access log,
        # whose formatter needs its five arguments (they are always strings/ints).
        if record.name == "uvicorn.access":
            return True
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 (a bad format string is not ours to fix)
            return True
        if _needs_redaction(msg):
            record.msg = redact(msg)
            record.args = ()
        return True


def install() -> None:
    """Attach the redaction filter to uvicorn's loggers, the root logger and ours."""
    f = RedactPatientUUIDsFilter()
    for name in ("uvicorn.access", "uvicorn.error", "solace", ""):
        logger = logging.getLogger(name)
        # Avoid stacking duplicate filters if install() runs twice.
        if not any(isinstance(h, RedactPatientUUIDsFilter) for h in logger.filters):
            logger.addFilter(f)
