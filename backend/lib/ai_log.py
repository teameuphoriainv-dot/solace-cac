"""Per-patient AI-call log.

Every outside model call (Claude, OpenAI speech-to-text, ElevenLabs voice) appends
an entry, so the clinician view can show which service saw how much data, when, and
for what purpose.

Shape of each entry:
  {provider, model, purpose, ts, input_bytes, output_bytes, success, error, cost_usd}

Entries are collected in memory during a request via `new_log()` / `record()` and
saved onto the patient record at the end of the request.
"""
from __future__ import annotations

import contextvars
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AIEvent:
    provider: str              # "anthropic" | "openai" | "elevenlabs"
    model: str                 # e.g. "claude-haiku-5-5" / "whisper-1" / "eleven_multilingual_v2"
    purpose: str               # "prebrief" | "scribe" | "comfort" | "vision" | "transcription" | "tts" ...
    ts: str                    # ISO8601 UTC
    input_bytes: int = 0
    output_bytes: int = 0
    success: bool = True
    error: str | None = None
    cost_usd: float = 0.0      # from the API's token counts when known (lib/spend.py)


# Rough per-1K-token prices in USD, used only when an event has no cost_usd (calls
# that are not Claude). Bytes are turned into tokens with the 1 token = 4 bytes rule.
_PRICING_USD: dict[tuple[str, str], tuple[float, float]] = {
    ("openai",    "whisper-1"):         (0.006 / 60, 0.0),  # whisper bills per minute of audio
    ("elevenlabs","eleven_multilingual_v2"): (0.000033, 0.0),  # about $0.33 per 10K characters
}


def _estimate_cost_usd(provider: str, model: str, input_bytes: int, output_bytes: int) -> float:
    if provider == "anthropic":
        from lib import spend  # noqa: PLC0415

        return spend.estimate_cost(model, input_bytes // 4, output_bytes // 4)
    rates = _PRICING_USD.get((provider, model))
    if not rates:
        return 0.0
    in_rate, out_rate = rates
    # Whisper and ElevenLabs are not billed by token.
    if provider == "openai" and model == "whisper-1":
        # Whisper bills $0.006 a minute. Compressed browser audio is roughly
        # 8 KB a second, so seconds = bytes / 8000.
        seconds = input_bytes / 8000.0
        return (seconds / 60.0) * 0.006
    if provider == "elevenlabs":
        chars = input_bytes  # the script's byte count is about its character count
        return chars * 0.000033
    in_tokens = input_bytes / 4.0
    out_tokens = output_bytes / 4.0
    return (in_tokens / 1000.0) * in_rate + (out_tokens / 1000.0) * out_rate


def _event_cost(e: AIEvent) -> float:
    if e.cost_usd:
        return e.cost_usd
    return _estimate_cost_usd(e.provider, e.model, e.input_bytes, e.output_bytes)


@dataclass
class AILog:
    events: list[AIEvent] = field(default_factory=list)

    def record(self, provider: str, model: str, purpose: str, *,
               input_bytes: int = 0, output_bytes: int = 0,
               success: bool = True, error: str | None = None,
               cost_usd: float = 0.0) -> None:
        self.events.append(AIEvent(
            provider=provider, model=model, purpose=purpose,
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            input_bytes=input_bytes, output_bytes=output_bytes,
            success=success, error=error, cost_usd=round(cost_usd, 6),
        ))

    def serialize(self) -> list[dict[str, Any]]:
        return [asdict(e) for e in self.events]

    def total_cost_usd(self) -> float:
        """Estimated spend for this encounter: the sum of per-event costs."""
        return sum(_event_cost(e) for e in self.events if e.success)

    def cost_breakdown(self) -> dict[str, float]:
        """Per-purpose cost split (e.g. {prebrief: 0.012, scribe: 0.018, ...})."""
        out: dict[str, float] = {}
        for e in self.events:
            if not e.success:
                continue
            out[e.purpose] = round(out.get(e.purpose, 0.0) + _event_cost(e), 5)
        return out


# Context variable so nested service calls share the same log without threading it
# through every function signature. Routers call `new_log()` at the top of their
# handler; services call `current()` to append.
_current: contextvars.ContextVar[AILog | None] = contextvars.ContextVar("ai_log", default=None)


def new_log() -> AILog:
    log = AILog()
    _current.set(log)
    return log


def current() -> AILog | None:
    return _current.get()


def record(**kwargs: Any) -> None:
    """Append to the active log. Does nothing when no log is active (startup, tests)."""
    log = _current.get()
    if log is not None:
        log.record(**kwargs)
