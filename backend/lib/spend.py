"""Daily AI spend cap for the public demo.

Every Claude call adds its estimated cost here, worked out from the token counts the
API sends back and the price table below. When today's total (UTC) reaches
AI_DAILY_BUDGET_USD, lib.claude.available() turns False and every AI feature switches
to its no-AI version until the day rolls over.

Two guards do not depend on who is asking, so one burst (or many made-up visitors)
cannot switch AI off for everyone until midnight:
  - an hourly slice: at most AI_HOURLY_BUDGET_FRACTION of the daily budget is spent in
    one clock hour (UTC); past it, AI is off until the next hour starts,
  - a per-minute ceiling: at most AI_CALLS_PER_MINUTE calls start in any 60 seconds.

This module also remembers which visitor the current request belongs to (set by the
middleware in main.py), so one visitor cannot use up the whole day's budget: each
visitor gets AI_CALLS_PER_VISITOR_HOUR calls an hour (the "ai.call" limit in quota.py).
Work started by a request (the background clinician summaries, thread pools) carries
the visitor with it, so those calls count too.

Failed calls are counted on their own (record_failure). A refusal that a retry cannot
fix (no credit left, a key the AI service does not accept, no permission) also pauses
every AI call for PAUSE_SECONDS (provider_pause), so screens switch to their no-AI
versions instead of failing one call at a time. The next call after the pause checks
again.

Totals live in memory, so a restart starts the day's count again. That is fine for a
demo with a small budget; the provider's own spend limit is the hard backstop.
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone

from lib.config import settings

log = logging.getLogger(__name__)

# USD per million tokens (input, output). Anthropic list prices for the models this
# app may be pointed at with MODEL_CLINICAL / MODEL_UTILITY.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
}
# A model missing from the table is priced like Opus so the cap never undercounts.
UNKNOWN_PRICE = (5.00, 25.00)
# Haiku 5.5 bills prompts over 100K tokens at a higher rate.
_HAIKU_55_LONG_PROMPT = 100_000
_HAIKU_55_LONG_PRICE = (0.50, 2.50)
# Prompt-cache writes cost 1.25x the input rate; cache reads cost 0.1x.
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10

_lock = threading.Lock()
_day = ""
_spent_usd = 0.0
_calls = 0
_cap_logged = False
# The current clock hour's spend, and the start times of recent calls.
_hour = ""
_hour_spent = 0.0
_hour_logged = False
_recent_starts: deque[float] = deque()
_minute_logged_at = 0.0
MINUTE_SECONDS = 60.0
# Failed calls today, the last failure, and the pause a refused call starts.
PAUSE_SECONDS = 600.0
_failed = 0
_last_error_kind: str | None = None
_last_error_at: float | None = None
_pause_kind: str | None = None
_pause_until = 0.0

# Time source; tests replace it to move the clock.
_clock = time.time

# Identity hash of the visitor whose request is running (see main.py middleware).
_visitor: contextvars.ContextVar[str | None] = contextvars.ContextVar("ai_visitor", default=None)


def model_family(model: str) -> str:
    """'us.anthropic.claude-haiku-4-5-20251001-v1:0' -> 'claude-haiku-4-5'."""
    m = (model or "").strip().lower()
    m = re.sub(r"^(?:[a-z]+\.)?anthropic\.", "", m)
    m = re.sub(r"-v\d+(?::\d+)?$", "", m)
    m = re.sub(r"[-@]\d{8}$", "", m)
    return m


def price_for(model: str) -> tuple[float, float]:
    return PRICE_PER_MTOK.get(model_family(model), UNKNOWN_PRICE)


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    in_rate, out_rate = price_for(model)
    prompt_tokens = input_tokens + cache_write_tokens + cache_read_tokens
    if model_family(model) == "claude-haiku-5-5" and prompt_tokens > _HAIKU_55_LONG_PROMPT:
        in_rate, out_rate = _HAIKU_55_LONG_PRICE
    usd = (
        input_tokens * in_rate
        + cache_write_tokens * in_rate * _CACHE_WRITE_MULT
        + cache_read_tokens * in_rate * _CACHE_READ_MULT
        + output_tokens * out_rate
    )
    return usd / 1_000_000


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def _today() -> str:
    return _utc(_clock()).strftime("%Y-%m-%d")


def _roll_day_locked() -> None:
    global _day, _spent_usd, _calls, _cap_logged, _hour, _hour_spent, _hour_logged, _failed
    now = _clock()
    today = _utc(now).strftime("%Y-%m-%d")
    if today != _day:
        _day, _spent_usd, _calls, _cap_logged, _failed = today, 0.0, 0, False, 0
    hour = _utc(now).strftime("%Y-%m-%dT%H")
    if hour != _hour:
        _hour, _hour_spent, _hour_logged = hour, 0.0, False
    while _recent_starts and now - _recent_starts[0] >= MINUTE_SECONDS:
        _recent_starts.popleft()


def budget_usd() -> float:
    return float(settings.ai_daily_budget_usd)


def hour_cap_usd() -> float:
    """The most that may be spent in one clock hour. A fraction outside (0, 1) means
    no hourly slice (the daily budget alone applies)."""
    try:
        fraction = float(settings.ai_hourly_budget_fraction)
    except (TypeError, ValueError):
        fraction = 0.35
    if not 0 < fraction < 1:
        return budget_usd()
    return budget_usd() * fraction


def minute_cap() -> int:
    """Most Claude calls that may start in any 60 seconds; 0 means no ceiling."""
    try:
        return max(0, int(settings.ai_calls_per_minute))
    except (TypeError, ValueError):
        return 40


def record(model: str, input_tokens: int, output_tokens: int,
           cache_write_tokens: int = 0, cache_read_tokens: int = 0) -> float:
    """Add one finished call to today's total. Returns that call's estimated cost."""
    global _spent_usd, _calls, _cap_logged, _hour_spent, _hour_logged
    cost = estimate_cost(model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)
    with _lock:
        _roll_day_locked()
        _spent_usd += cost
        _hour_spent += cost
        _calls += 1
        if _spent_usd >= budget_usd() and not _cap_logged:
            _cap_logged = True
            log.warning(
                "AI daily budget reached: $%.4f of $%.2f after %d calls. "
                "AI features are off until midnight UTC.",
                _spent_usd, budget_usd(), _calls,
            )
        elif _hour_spent >= hour_cap_usd() and not _hour_logged:
            _hour_logged = True
            log.warning(
                "AI hourly share reached: $%.4f of $%.2f this hour. "
                "AI features are off until the next hour starts.",
                _hour_spent, hour_cap_usd(),
            )
    return cost


def _busy_locked(now: float) -> str | None:
    if _hour_spent >= hour_cap_usd():
        return "hour"
    cap = minute_cap()
    if cap and len(_recent_starts) >= cap:
        return "minute"
    return None


def busy_reason() -> str | None:
    """"hour" or "minute" while a global guard holds AI off, else None. Uses nothing up."""
    with _lock:
        _roll_day_locked()
        return _busy_locked(_clock())


def try_start_call() -> str | None:
    """Claim a slot for one Claude call. None when it may go ahead (the slot is taken),
    else the guard that refused it ("hour" or "minute")."""
    global _minute_logged_at
    with _lock:
        _roll_day_locked()
        now = _clock()
        busy = _busy_locked(now)
        if busy is None:
            _recent_starts.append(now)
            return None
        if busy == "minute" and now - _minute_logged_at >= MINUTE_SECONDS:
            _minute_logged_at = now
            log.warning("AI per-minute ceiling reached (%d calls in 60 seconds); "
                        "AI features are paused briefly", minute_cap())
        return busy


def record_failure(kind: str, *, pause: bool) -> None:
    """Count one failed call. With ``pause``, hold every AI call off for PAUSE_SECONDS.

    ``kind`` is a short code from lib.claude.error_kind ("billing", "timeout", ...),
    never the provider's own message."""
    global _failed, _last_error_kind, _last_error_at, _pause_kind, _pause_until
    with _lock:
        _roll_day_locked()
        now = _clock()
        _failed += 1
        _last_error_kind, _last_error_at = kind, now
        newly_paused = pause and now >= _pause_until
        if pause:
            _pause_kind, _pause_until = kind, now + PAUSE_SECONDS
    if newly_paused:
        log.warning("The AI service refused a call (%s). AI features are paused for %d minutes.",
                    kind, int(PAUSE_SECONDS // 60))


def provider_pause() -> str | None:
    """The error kind that paused AI calls, while that pause lasts; else None."""
    with _lock:
        return _pause_kind if _clock() < _pause_until else None


def _iso(ts: float | None) -> str | None:
    return _utc(ts).isoformat(timespec="seconds").replace("+00:00", "Z") if ts else None


def failure_status() -> dict:
    """Failed calls today and the last failure, for /health. Codes and times only."""
    with _lock:
        _roll_day_locked()
        paused = _clock() < _pause_until
        return {
            "calls_failed_today": _failed,
            "last_error_kind": _last_error_kind,
            "last_error_at": _iso(_last_error_at),
            "paused_until": _iso(_pause_until) if paused else None,
        }


def spent_today() -> float:
    with _lock:
        _roll_day_locked()
        return _spent_usd


def exhausted() -> bool:
    """True once today's spend reaches the budget. A budget of 0 turns AI off."""
    return spent_today() >= budget_usd()


def status() -> dict:
    with _lock:
        _roll_day_locked()
        return {
            "budget_usd": round(budget_usd(), 2),
            "spent_today_usd": round(_spent_usd, 4),
            "calls_today": _calls,
            "calls_failed_today": _failed,
            "budget_left": _spent_usd < budget_usd(),
            "hour_cap_usd": round(hour_cap_usd(), 4),
            "spent_this_hour_usd": round(_hour_spent, 4),
            "calls_last_minute": len(_recent_starts),
            "calls_per_minute_cap": minute_cap(),
            "paused": _busy_locked(_clock()),
        }


# ---- per-visitor limit ---------------------------------------------------------------
def set_visitor(identity: str | None) -> contextvars.Token:
    return _visitor.set(identity)


def reset_visitor(token: contextvars.Token) -> None:
    _visitor.reset(token)


def current_visitor() -> str | None:
    return _visitor.get()


def visitor_allowed() -> bool:
    """False when the current visitor has used up their AI calls for this hour.

    Calls made outside a request (startup, background threads) have no visitor and
    are only limited by the daily budget.
    """
    identity = _visitor.get()
    if not identity:
        return True
    from lib import quota  # noqa: PLC0415 (quota imports config; keep this module light)

    return quota.remaining(identity, "ai.call") > 0


def note_visitor_call() -> None:
    identity = _visitor.get()
    if not identity:
        return
    from lib import quota  # noqa: PLC0415

    quota.try_consume(identity, "ai.call")


def _reset_for_tests() -> None:
    global _day, _spent_usd, _calls, _cap_logged, _hour, _hour_spent, _hour_logged, _minute_logged_at
    global _failed, _last_error_kind, _last_error_at, _pause_kind, _pause_until
    with _lock:
        _day, _spent_usd, _calls, _cap_logged = _today(), 0.0, 0, False
        _hour, _hour_spent, _hour_logged = "", 0.0, False
        _recent_starts.clear()
        _minute_logged_at = 0.0
        _failed, _last_error_kind, _last_error_at, _pause_kind, _pause_until = 0, None, None, None, 0.0
