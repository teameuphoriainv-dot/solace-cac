"""Spoken audio of the patient's guidance.

Local mode uses ElevenLabs when ELEVENLABS_API_KEY is set. Without the key,
is_configured() is False and generate_and_upload() returns None with no network
call; the result page then offers the browser's own read-aloud. aws mode uses
Amazon Polly.

The script is intentionally short. The screen carries the full guidance; the voice
just reassures and orients.
"""
from __future__ import annotations

import logging
import os
import time

from db import media
from lib.config import settings

log = logging.getLogger(__name__)

_MAX_SCRIPT_CHARS = 350

# Retry with backoff for brief Polly failures (throttling, a passing 5xx).
_TTS_MAX_ATTEMPTS = 3
_TTS_BACKOFF_BASE = 0.25       # seconds: 0.25, 0.5, 1.0


def compose_script(patient_explanation: str, comfort_protocol: list[dict], patient_name: str = "") -> str:
    """Short voice script. Full guidance stays on screen."""
    first = (comfort_protocol[0]["title"].rstrip(".") if comfort_protocol else "").strip()
    name_greeting = f"{patient_name.strip()}, " if patient_name else ""

    parts = [
        f"{name_greeting}{patient_explanation.strip()}",
        "Read the screen for three ways to feel better right now." if not first else
        f"Read the screen for three ways to feel better, starting with: {first}.",
        "We will alert a clinician if anything changes.",
    ]
    script = " ".join(p for p in parts if p).strip()
    if len(script) > _MAX_SCRIPT_CHARS:
        script = script[:_MAX_SCRIPT_CHARS].rsplit(". ", 1)[0] + "."
    return script


def _provider() -> str:
    # Local mode always uses ElevenLabs and never touches AWS.
    if settings.solace_mode != "aws":
        return "elevenlabs"
    return os.environ.get("TTS_PROVIDER", "aws").lower()


def is_configured() -> bool:
    """True when the server can make spoken audio."""
    if _provider() == "aws":
        return True
    return bool(settings.elevenlabs_api_key)


def generate_and_upload(script: str, language: str, patient_id: str) -> str | None:
    """Make the audio and save it to media storage. Returns its URL, or None."""
    from lib import ai_log  # noqa: PLC0415

    if not is_configured() or not (script or "").strip():
        return None
    prov = _provider()
    model_name = "aws-polly" if prov == "aws" else "eleven_multilingual_v2"
    try:
        if prov == "aws":
            mp3_bytes = _aws_polly_synthesize(script, language)
        else:
            mp3_bytes = _elevenlabs_synthesize(script, language)

        if mp3_bytes is None:
            return None

        ai_log.record(
            provider=prov, model=model_name, purpose="tts",
            input_bytes=len(script.encode()),
            output_bytes=len(mp3_bytes), success=True,
        )
        filename = f"{patient_id}.mp3"
        return media.save("audio", filename, mp3_bytes, content_type="audio/mpeg")

    except Exception as e:
        ai_log.record(
            provider=prov, model=model_name, purpose="tts",
            input_bytes=len(script.encode()), output_bytes=0,
            success=False, error=str(e)[:200],
        )
        log.exception("TTS failure (%s): %s", prov, e)
        return None


# ---------------------------------------------------------------------------
# Amazon Polly (aws mode only)
# ---------------------------------------------------------------------------

# Neural voices by language, with standard voices where neural is missing.
_POLLY_VOICE_MAP: dict[str, tuple[str, str]] = {
    # (VoiceId, Engine)
    "en": ("Joanna", "neural"),
    "es": ("Lupe", "neural"),
    "fr": ("Lea", "neural"),
    "de": ("Vicki", "neural"),
    "pt": ("Camila", "neural"),
    "it": ("Bianca", "neural"),
    "ja": ("Kazuha", "neural"),
    "ko": ("Seoyeon", "neural"),
    "zh": ("Zhiyu", "neural"),
    "hi": ("Kajal", "neural"),
    "ar": ("Hala", "neural"),
    "nl": ("Laura", "neural"),
    "pl": ("Ola", "neural"),
    "sv": ("Elin", "neural"),
    "da": ("Sofie", "neural"),
    "no": ("Ida", "neural"),
    "fi": ("Suvi", "neural"),
    "tr": ("Burcu", "neural"),
    "ru": ("Tatyana", "standard"),
    "ro": ("Carmen", "standard"),
    "cy": ("Gwyneth", "standard"),
    "vi": ("Joanna", "neural"),      # no Polly voice: English voice
    "ur": ("Joanna", "neural"),      # no Polly voice: English voice
    "tl": ("Joanna", "neural"),      # no Polly voice: English voice
}


def _aws_polly_synthesize(script: str, language: str) -> bytes | None:
    """Synthesize speech with Amazon Polly, retrying brief failures. Returns MP3 bytes."""
    import boto3  # noqa: PLC0415

    polly = boto3.client("polly", region_name=settings.aws_region)

    lang_key = (language or "en").strip().lower()[:2]
    voice_id, engine = _POLLY_VOICE_MAP.get(lang_key, ("Joanna", "neural"))

    def _attempt(use_engine: str) -> bytes:
        resp = polly.synthesize_speech(
            Text=script,
            OutputFormat="mp3",
            VoiceId=voice_id,
            Engine=use_engine,
            TextType="text",
        )
        return resp["AudioStream"].read()

    # Try the preferred engine, then the standard engine.
    engines = [engine] if engine == "standard" else [engine, "standard"]
    last_exc: Exception | None = None
    for use_engine in engines:
        for attempt in range(_TTS_MAX_ATTEMPTS):
            try:
                return _attempt(use_engine)
            except Exception as e:  # noqa: BLE001
                last_exc = e
                if attempt < _TTS_MAX_ATTEMPTS - 1:
                    delay = _TTS_BACKOFF_BASE * (2 ** attempt)
                    log.warning(
                        "Polly %s/%s attempt %d failed, retrying in %.2fs: %s",
                        voice_id, use_engine, attempt + 1, delay, e,
                    )
                    time.sleep(delay)
                else:
                    log.warning(
                        "Polly %s/%s exhausted %d attempts: %s",
                        voice_id, use_engine, _TTS_MAX_ATTEMPTS, e,
                    )
    if last_exc:
        raise last_exc
    return None


# ---------------------------------------------------------------------------
# ElevenLabs (local mode)
# ---------------------------------------------------------------------------

_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


def _elevenlabs_synthesize(script: str, language: str) -> bytes | None:
    """ElevenLabs text to speech. Returns MP3 bytes, or None with no key."""
    if not settings.elevenlabs_api_key:
        return None
    import httpx  # noqa: PLC0415

    url = f"{_ELEVENLABS_BASE}/text-to-speech/{settings.elevenlabs_voice_id}"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": script,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    if language and len(language) == 2:
        payload["language_code"] = language

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.content
