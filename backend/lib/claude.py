"""The one place every Claude call goes through.

Calls the Anthropic API directly with ANTHROPIC_API_KEY. With no key, available() is
False and no request is ever sent, so every feature takes its no-AI path.

Each call:
  - fits the request to the model: newer models reject `temperature` and think by
    default, so sampling options are dropped and thinking is turned off where the
    model allows it (short JSON answers stay short, fast and cheap),
  - adds its estimated cost to today's total (lib/spend.py). Once the daily budget is
    used up, this hour's share of it is used up, too many calls started in the last
    minute, or this visitor has used their AI calls for the hour, available() is
    False and features fall back cleanly,
  - replaces em and en dashes in the reply, so none reach a patient's screen,
  - is recorded in the per-patient AI log (lib/ai_log.py).

A failed call is counted (lib/spend.record_failure) under a short code from
error_kind(). When the AI service refuses the call for a reason a retry cannot fix
(no credit left, a key it does not accept, no permission), available() is False for
the next 10 minutes, so /capabilities says AI is off and every screen shows its
no-AI version. Timeouts, rate limits and server errors never start that pause.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from lib import ai_log, spend

log = logging.getLogger(__name__)


class ClaudeUnavailable(RuntimeError):
    """Raised by messages_create when no call may be made (no key, or a spend limit)."""


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"
    text: str = ""  # kept so consumers can iterate `.text` uniformly without crashing


@dataclass
class Response:
    content: list  # list[TextBlock | ToolUseBlock]
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0


# ---- model quirks ----------------------------------------------------------------------
# Older models accept temperature/top_p/top_k, never think unless asked, and use the
# older tokenizer. Everything else is treated as a newer model.
_LEGACY_FAMILIES = {
    "claude-haiku-4-5",
    "claude-sonnet-4", "claude-sonnet-4-0", "claude-sonnet-4-5", "claude-sonnet-4-6",
    "claude-opus-4", "claude-opus-4-0", "claude-opus-4-1", "claude-opus-4-5", "claude-opus-4-6",
}
# Newer models that think by default but accept thinking turned off.
_THINKING_OFF_OK = {"claude-haiku-5-5", "claude-opus-5", "claude-sonnet-5"}
# Sonnet 5.5 turns thinking off with a different value.
_THINKING_BETWEEN_TOOLS = {"claude-sonnet-5-5"}
# Models that always think: keep effort low and leave room for the thinking tokens.
_ALWAYS_THINK = {"claude-opus-5-5", "claude-fable-5", "claude-fable-5-1"}
_ALWAYS_THINK_HEADROOM = 2048
# The newer tokenizer turns the same text into about 30% more tokens, so the
# max_tokens values written for older models are scaled up to avoid cut-off JSON.
_NEW_TOKENIZER_SCALE = 1.3


def _is_legacy(family: str) -> bool:
    return family.startswith("claude-3") or family in _LEGACY_FAMILIES


def provider() -> str:
    return "anthropic"


def configured() -> bool:
    """A key is set. Says nothing about today's budget (see available())."""
    from lib.config import settings  # noqa: PLC0415

    return bool(settings.anthropic_api_key)


def available() -> bool:
    """True when a Claude call may be made right now.

    False with no key, while the AI service's refusal pauses calls, once today's AI
    budget is spent, while this hour's share of it is spent or too many calls started
    in the last minute, or when the current visitor has used their AI calls for this
    hour. Services check this first and use their no-AI version when it is False.
    """
    return (configured() and spend.provider_pause() is None and not spend.exhausted()
            and spend.busy_reason() is None and spend.visitor_allowed())


_BUSY_REASONS = {
    "hour": "AI features are paused until the next hour starts because the demo has used "
            "this hour's share of its AI budget.",
    "minute": "AI features are paused for about a minute because the demo is getting a lot "
              "of requests right now.",
}
_PAUSE_REASONS = {
    "billing": "AI features are off for now because the AI service says this server's "
               "account has no credit left. The server checks again every 10 minutes.",
    "auth": "AI features are off for now because the AI service did not accept this "
            "server's key. The server checks again every 10 minutes.",
    "permission": "AI features are off for now because the AI service did not allow this "
                  "server's key to make the call. The server checks again every 10 minutes.",
}


def unavailable_reason() -> str | None:
    """Short plain-English reason AI is off right now, or None when it is on."""
    if not configured():
        return "AI features are off because no AI key is set on this server."
    paused = spend.provider_pause()
    if paused:
        return _PAUSE_REASONS.get(paused, _PAUSE_REASONS["auth"])
    if spend.exhausted():
        return "AI features are paused for today because the demo's daily AI budget is used up."
    busy = spend.busy_reason()
    if busy:
        return _BUSY_REASONS[busy]
    if not spend.visitor_allowed():
        return "AI features are paused for this device for a few minutes because of heavy use."
    return None


def off_kind() -> str | None:
    """Why AI is off right now, as a code for choosing a screen's wording:
    "no_key", "provider_error" (the AI service refused this server's calls), "paused"
    (a budget or rate guard), or None when nothing holds it off."""
    if not configured():
        return "no_key"
    if spend.provider_pause():
        return "provider_error"
    return "paused" if unavailable_reason() else None


def off_reason() -> str:
    """One plain sentence on why AI is off right now, for a screen that falls back."""
    return unavailable_reason() or "AI features are paused right now."


def health() -> dict:
    """The AI state for /health: on or off and why, and the last failure as a code.
    Never the key, and never the AI service's own error message."""
    return {"available": available(), "unavailable_reason": unavailable_reason(),
            **spend.failure_status()}


# ---- why a call failed -----------------------------------------------------------------
# Refusals a retry cannot fix: these pause every AI call (lib/spend.record_failure).
PAUSING_ERRORS = frozenset({"billing", "auth", "permission"})
_BILLING_WORDS = re.compile(r"credit|billing|payment", re.IGNORECASE)


def error_kind(e: BaseException) -> str:
    """A short code for why a call failed: "billing", "auth", "permission",
    "rate_limited", "server_error", "timeout", "connection", "http_<status>" or
    "error". Read from the status and error type; the message text is only searched
    for billing words on a 400 and never returned."""
    status = getattr(e, "status_code", None)
    if not isinstance(status, int):
        status = getattr(getattr(e, "response", None), "status_code", None)
    status = status if isinstance(status, int) else None
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else body
    etype = str(err.get("type") or "") if isinstance(err, dict) else ""
    if status == 401 or etype == "authentication_error":
        return "auth"
    if status == 403 or etype == "permission_error":
        return "permission"
    if status == 402 or etype == "billing_error":
        return "billing"
    if status == 400 and _BILLING_WORDS.search(f"{etype} {e}"):
        return "billing"
    if status == 429 or etype == "rate_limit_error":
        return "rate_limited"
    if (status is not None and status >= 500) or etype in ("api_error", "overloaded_error"):
        return "server_error"
    name = type(e).__name__
    if "Timeout" in name:
        return "timeout"
    if "Connection" in name:
        return "connection"
    return f"http_{status}" if status is not None else "error"


@lru_cache(maxsize=1)
def _anthropic_client():
    from anthropic import Anthropic  # noqa: PLC0415
    from lib.config import settings  # noqa: PLC0415

    # Keep a slow call from holding a patient's request for minutes.
    return Anthropic(api_key=settings.anthropic_api_key, timeout=45.0, max_retries=1)


# ---- dash cleanup ----------------------------------------------------------------------
_DASHES = "\u2013\u2014"
_RANGE_DASH = re.compile(r"(\d)\s*[\u2013\u2014]\s*(\d)")
_LEADING_DASH = re.compile(r"^([ \t]*)[\u2013\u2014][ \t]*", re.MULTILINE)
_OPENING_DASH = re.compile(r"([\"(\[])[ \t]*[\u2013\u2014][ \t]*")
_OTHER_DASH = re.compile(r"[ \t]*[\u2013\u2014][ \t]*")
_DOUBLE_PUNCT = re.compile(r",\s*([,.;:!?)])")
_ESCAPED_DASH = re.compile(r"\\u20(?:13|14)")


def strip_dashes(text: str) -> str:
    """Replace em and en dashes: a number range becomes "3-5", a dash that starts a
    line becomes "- ", any other becomes ", ".

    Leaves the minus sign (U+2212) alone. Safe inside JSON strings.
    """
    if not text or not any(ch in text for ch in _DASHES + "\\"):
        return text
    text = _ESCAPED_DASH.sub(", ", text)
    text = _RANGE_DASH.sub(r"\1-\2", text)
    text = _LEADING_DASH.sub(r"\1- ", text)
    text = _OPENING_DASH.sub(r"\1", text)
    text = _OTHER_DASH.sub(", ", text)
    return _DOUBLE_PUNCT.sub(r"\1", text)


def _strip_dashes_deep(value: Any) -> Any:
    if isinstance(value, str):
        return strip_dashes(value)
    if isinstance(value, list):
        return [_strip_dashes_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_dashes_deep(v) for k, v in value.items()}
    return value


# ---- the call --------------------------------------------------------------------------
def messages_create(
    *,
    model: str,
    max_tokens: int,
    system: str = "",
    messages: list[dict[str, Any]],
    purpose: str,
    temperature: float | None = None,
    **kwargs: Any,
) -> Response:
    """Send one Messages API request. Returns `.content` blocks with `.text`.

    Raises ClaudeUnavailable (no request sent) when available() is False, and the
    SDK's errors when the call itself fails; callers fall back on any exception. A
    failure is counted, and a refusal in PAUSING_ERRORS pauses AI (see error_kind).
    """
    reason = unavailable_reason()
    if reason:
        raise ClaudeUnavailable(reason)
    # Claim a slot under the per-minute ceiling atomically: many calls can pass the
    # check above at the same moment, but only the ones that get a slot are sent.
    busy = spend.try_start_call()
    if busy:
        raise ClaudeUnavailable(_BUSY_REASONS[busy])
    spend.note_visitor_call()

    request = _build_request(model, max_tokens, system, messages, temperature, kwargs)
    input_bytes = _estimate_bytes(system) + _estimate_messages(messages)
    try:
        r = _anthropic_client().messages.create(**request)
    except Exception as e:
        kind = error_kind(e)
        spend.record_failure(kind, pause=kind in PAUSING_ERRORS)
        log.warning("Claude call failed (purpose=%s, kind=%s, %s)", purpose, kind, type(e).__name__)
        # The code and class only: the AI service's message stays out of patient records.
        ai_log.record(
            provider="anthropic", model=model, purpose=purpose,
            input_bytes=input_bytes, output_bytes=0, success=False,
            error=f"{kind} ({type(e).__name__})",
        )
        raise

    usage = _usage_of(r)
    cost = spend.record(
        model, usage["input_tokens"], usage["output_tokens"],
        usage["cache_creation_input_tokens"], usage["cache_read_input_tokens"],
    )
    blocks: list = []
    for b in r.content or []:
        btype = getattr(b, "type", None)
        if btype == "text":
            blocks.append(TextBlock(text=strip_dashes(b.text)))
        elif btype == "tool_use":
            blocks.append(ToolUseBlock(id=b.id, name=b.name, input=_strip_dashes_deep(dict(b.input or {}))))
    stop_reason = getattr(r, "stop_reason", None)
    if stop_reason == "refusal":
        log.warning("Claude declined a request (purpose=%s)", purpose)
    elif stop_reason == "max_tokens":
        log.warning("Claude reply hit max_tokens (purpose=%s, max_tokens=%s)", purpose, request["max_tokens"])

    output_bytes = sum(len(getattr(b, "text", "").encode()) for b in blocks)
    ai_log.record(
        provider="anthropic", model=model, purpose=purpose,
        input_bytes=input_bytes, output_bytes=output_bytes, success=True, cost_usd=cost,
    )
    return Response(content=blocks, stop_reason=stop_reason, usage=usage, cost_usd=cost)


def _build_request(model, max_tokens, system, messages, temperature, kwargs) -> dict[str, Any]:
    family = spend.model_family(model)
    legacy = _is_legacy(family)
    extra = dict(kwargs.pop("extra_body", None) or {})

    req: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens if legacy else math.ceil(max_tokens * _NEW_TOKENIZER_SCALE),
        "messages": messages,
    }
    if system:
        req["system"] = _system_blocks(system)
    if legacy:
        if temperature is not None:
            req["temperature"] = temperature
    else:
        for k in ("temperature", "top_p", "top_k"):
            kwargs.pop(k, None)

    # The pinned SDK predates `thinking` and `output_config`, so they go in extra_body.
    for k in ("thinking", "output_config"):
        if k in kwargs:
            extra[k] = kwargs.pop(k)
    if "thinking" not in extra:
        if family in _THINKING_OFF_OK:
            extra["thinking"] = {"type": "disabled"}
        elif family in _THINKING_BETWEEN_TOOLS:
            extra["thinking"] = {"type": "between_tools"}
        elif family in _ALWAYS_THINK:
            extra.setdefault("output_config", {"effort": "low"})
            req["max_tokens"] += _ALWAYS_THINK_HEADROOM

    req.update(kwargs)
    if extra:
        req["extra_body"] = extra
    return req


def _usage_of(r: Any) -> dict[str, int]:
    u = getattr(r, "usage", None)

    def _n(name: str) -> int:
        try:
            return int(getattr(u, name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "input_tokens": _n("input_tokens"),
        "output_tokens": _n("output_tokens"),
        "cache_creation_input_tokens": _n("cache_creation_input_tokens"),
        "cache_read_input_tokens": _n("cache_read_input_tokens"),
    }


def _system_blocks(system: str) -> list[dict]:
    """Wrap the per-service system prompt as a cache-controlled block.

    Repeated calls that share a system prompt then re-read it from the prompt cache
    at a fraction of the price. Below the model's minimum cacheable size the marker
    is ignored, so it is always safe to attach."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _estimate_bytes(s: str | None) -> int:
    return len((s or "").encode())


def _estimate_messages(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c.encode())
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict):
                    if "text" in part:
                        total += len(str(part["text"]).encode())
                    if "source" in part and isinstance(part["source"], dict):
                        data = part["source"].get("data", "")
                        total += len(str(data).encode()) * 3 // 4  # base64 -> bytes
    return total
