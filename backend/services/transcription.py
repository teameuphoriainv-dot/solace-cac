"""Server speech-to-text for uploaded audio.

Most patients never need this: the check-in page uses the browser's own live
dictation. This is the fallback for browsers without it.

Local mode uses OpenAI Whisper when OPENAI_API_KEY is set. Without the key,
is_configured() is False and transcribe() raises TranscriptionError right away,
with no network call. aws mode uses Amazon Transcribe.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass

from lib.config import settings

log = logging.getLogger(__name__)


# Hard cap on the Amazon Transcribe batch poll, so the follow-up questions that run
# after it still fit inside one request.
_MAX_POLL_SECONDS = 22


class TranscriptionError(RuntimeError):
    """The message is plain English and safe to show (it never carries audio content)."""


NOT_CONFIGURED_MESSAGE = "this server has no speech-to-text key. Please type your answer instead."
FAILED_MESSAGE = "the speech-to-text service did not answer. Please try again or type your answer."


@dataclass
class Transcription:
    text: str
    language: str  # ISO 639-1


def _provider() -> str:
    # Local mode always uses OpenAI Whisper and never touches AWS.
    if settings.solace_mode != "aws":
        return "openai"
    return os.environ.get("TRANSCRIPTION_PROVIDER", "aws").lower()


def is_configured() -> bool:
    """True when an uploaded recording can be turned into text on this server."""
    if _provider() == "aws":
        return bool(settings.s3_bucket_media)
    return bool(settings.openai_api_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transcribe(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    language_hint: str | None = None,
) -> Transcription:
    """Send audio bytes for transcription. Returns transcript + detected language code.

    `language_hint`: ISO-639-1 code (e.g. "ur", "it"). When provided, forces
    decoding in that language, since auto-detect on short clips can guess wrong.
    """
    from lib import ai_log  # noqa: PLC0415

    if not is_configured():
        raise TranscriptionError(NOT_CONFIGURED_MESSAGE)
    prov = _provider()
    try:
        if prov == "aws":
            result = _aws_transcribe(audio_bytes, filename, language_hint)
        else:
            result = _openai_transcribe(audio_bytes, filename, language_hint)
    except TranscriptionError:
        raise
    except Exception as e:
        ai_log.record(
            provider=prov, model="aws-transcribe" if prov == "aws" else "whisper-1",
            purpose="transcription",
            input_bytes=len(audio_bytes), output_bytes=0,
            success=False, error=str(e)[:200],
        )
        log.exception("Transcription failure (%s)", prov)
        raise TranscriptionError(FAILED_MESSAGE) from e

    if not result.text:
        ai_log.record(
            provider=prov, model="aws-transcribe" if prov == "aws" else "whisper-1",
            purpose="transcription",
            input_bytes=len(audio_bytes), output_bytes=0,
            success=False, error="empty_transcript",
        )
        raise TranscriptionError("no speech was heard in that recording. Please try again closer to the microphone.")

    ai_log.record(
        provider=prov, model="aws-transcribe" if prov == "aws" else "whisper-1",
        purpose="transcription",
        input_bytes=len(audio_bytes), output_bytes=len(result.text.encode()),
        success=True,
    )
    return result


# ---------------------------------------------------------------------------
# Amazon Transcribe (aws mode only)
# ---------------------------------------------------------------------------

_AWS_TRANSCRIBE_LANG_MAP: dict[str, str] = {
    "en": "en-US", "es": "es-US", "fr": "fr-FR", "de": "de-DE",
    "pt": "pt-BR", "it": "it-IT", "vi": "vi-VN", "zh": "zh-CN",
    "ja": "ja-JP", "ko": "ko-KR", "ar": "ar-SA", "hi": "hi-IN",
    "ru": "ru-RU", "nl": "nl-NL", "pl": "pl-PL", "sv": "sv-SE",
    "da": "da-DK", "fi": "fi-FI", "he": "he-IL", "id": "id-ID",
    "ms": "ms-MY", "th": "th-TH", "tr": "tr-TR", "uk": "uk-UA",
    "ur": "ur-PK", "bn": "bn-IN", "ta": "ta-IN", "te": "te-IN",
    "mr": "mr-IN", "kn": "kn-IN", "ml": "ml-IN", "gu": "gu-IN",
    "af": "af-ZA", "cy": "cy-GB", "hr": "hr-HR", "bg": "bg-BG",
    "cs": "cs-CZ", "el": "el-GR", "hu": "hu-HU", "ro": "ro-RO",
    "sk": "sk-SK", "sl": "sl-SI", "sr": "sr-RS", "sw": "sw-KE",
    "tl": "tl-PH", "ca": "ca-ES", "gl": "gl-ES", "eu": "eu-ES",
    "fa": "fa-IR", "no": "no-NO", "et": "et-EE", "lv": "lv-LV",
    "lt": "lt-LT",
}

# Map file extensions to MediaFormat values accepted by AWS Transcribe
_MEDIA_FORMAT_MAP: dict[str, str] = {
    "webm": "webm", "mp3": "mp3", "mp4": "mp4", "m4a": "mp4",
    "wav": "wav", "flac": "flac", "ogg": "ogg", "amr": "amr",
}


def _aws_transcribe(
    audio_bytes: bytes,
    filename: str,
    language_hint: str | None,
) -> Transcription:
    """Transcribe with an Amazon Transcribe batch job (upload to S3, start, poll).
    Jobs finish in 5 to 15 seconds for typical check-in clips."""
    import boto3  # noqa: PLC0415

    region = settings.aws_region
    bucket = settings.s3_bucket_media
    if not bucket:
        raise TranscriptionError(NOT_CONFIGURED_MESSAGE)

    s3 = boto3.client("s3", region_name=region)
    transcribe_client = boto3.client("transcribe", region_name=region)

    # Determine media format from filename extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    media_format = _MEDIA_FORMAT_MAP.get(ext, "webm")

    # Upload audio to S3 (temporary prefix, auto-cleaned by lifecycle rule)
    job_name = f"solace-{uuid.uuid4().hex[:16]}"
    s3_key = f"transcribe-tmp/{job_name}.{ext}"
    s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=audio_bytes,
        ContentType=f"audio/{media_format}",
        ServerSideEncryption="aws:kms",
    )

    try:
        # Build transcription job config
        job_config: dict = {
            "TranscriptionJobName": job_name,
            "Media": {"MediaFileUri": f"s3://{bucket}/{s3_key}"},
            "MediaFormat": media_format,
            "OutputBucketName": bucket,
            "OutputKey": f"transcribe-tmp/{job_name}-output.json",
            "Settings": {"ShowSpeakerLabels": False},
        }

        # Language: use hint if provided, otherwise auto-detect
        normalized_hint = (language_hint or "").strip().lower()[:2] or None
        if normalized_hint and normalized_hint in _AWS_TRANSCRIBE_LANG_MAP:
            job_config["LanguageCode"] = _AWS_TRANSCRIBE_LANG_MAP[normalized_hint]
        else:
            # Auto-detect from common ER languages
            job_config["IdentifyLanguage"] = True
            job_config["LanguageOptions"] = ",".join([
                "en-US", "es-US", "fr-FR", "zh-CN", "vi-VN", "ar-SA",
                "hi-IN", "ko-KR", "pt-BR", "ur-PK", "tl-PH", "de-DE",
            ])

        transcribe_client.start_transcription_job(**job_config)

        # Poll for completion, capped so a slow job becomes a clean error (the
        # page then offers typing) instead of a request that hangs.
        for _ in range(_MAX_POLL_SECONDS):
            time.sleep(1)
            status = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )
            job_status = status["TranscriptionJob"]["TranscriptionJobStatus"]
            if job_status == "COMPLETED":
                break
            if job_status == "FAILED":
                reason = status["TranscriptionJob"].get("FailureReason", "unknown")
                log.warning("Amazon Transcribe job failed: %s", reason)
                raise TranscriptionError(FAILED_MESSAGE)
        else:
            log.warning("Amazon Transcribe did not finish within %ds", _MAX_POLL_SECONDS)
            raise TranscriptionError(FAILED_MESSAGE)

        # Read result from S3
        output_key = f"transcribe-tmp/{job_name}-output.json"
        result_obj = s3.get_object(Bucket=bucket, Key=output_key)
        result_data = json.loads(result_obj["Body"].read())

        transcript_text = (
            result_data.get("results", {})
            .get("transcripts", [{}])[0]
            .get("transcript", "")
            .strip()
        )

        # Detected language
        detected_lang = "en"
        if normalized_hint:
            detected_lang = normalized_hint
        elif "LanguageCode" in status.get("TranscriptionJob", {}):
            lc = status["TranscriptionJob"]["LanguageCode"]  # e.g. "en-US"
            detected_lang = lc.split("-")[0]
        detected_lang = _normalize_language(detected_lang)

        return Transcription(text=transcript_text, language=detected_lang)

    finally:
        # Clean up temporary S3 objects
        for key in [s3_key, f"transcribe-tmp/{job_name}-output.json"]:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass  # best-effort cleanup


# ---------------------------------------------------------------------------
# OpenAI Whisper (local mode)
# ---------------------------------------------------------------------------

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        if not settings.openai_api_key:
            raise TranscriptionError(NOT_CONFIGURED_MESSAGE)
        from openai import OpenAI  # noqa: PLC0415

        _openai_client = OpenAI(api_key=settings.openai_api_key, timeout=30.0, max_retries=1)
    return _openai_client


def _openai_transcribe(
    audio_bytes: bytes,
    filename: str,
    language_hint: str | None,
) -> Transcription:
    """OpenAI Whisper speech-to-text."""
    client = _get_openai_client()
    buf = io.BytesIO(audio_bytes)
    buf.name = filename
    kwargs: dict = {
        "model": "whisper-1",
        "file": buf,
        "response_format": "verbose_json",
    }
    normalized_hint = (language_hint or "").strip().lower()[:2] or None
    if normalized_hint and normalized_hint in _WHISPER_LANG_CODES:
        kwargs["language"] = normalized_hint
    resp = client.audio.transcriptions.create(**kwargs)
    text = getattr(resp, "text", "").strip()
    language = getattr(resp, "language", None) or normalized_hint or "en"
    language = _normalize_language(language)
    return Transcription(text=text, language=language)


# Whisper ISO-639-1 codes
_WHISPER_LANG_CODES: set[str] = {
    "af", "ar", "az", "be", "bg", "bn", "bs", "ca", "cs", "cy", "da", "de", "el",
    "en", "es", "et", "fa", "fi", "fr", "gl", "he", "hi", "hr", "hu", "hy", "id",
    "is", "it", "ja", "kk", "kn", "ko", "lt", "lv", "mi", "mk", "mr", "ms", "ne",
    "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sr", "sv", "sw", "ta", "th",
    "tl", "tr", "uk", "ur", "vi", "zh",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_LANG_MAP = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "portuguese": "pt", "italian": "it", "vietnamese": "vi",
    "haitian creole": "ht", "chinese": "zh", "japanese": "ja",
    "korean": "ko", "arabic": "ar", "hindi": "hi", "russian": "ru",
}


def _normalize_language(lang: str) -> str:
    key = lang.lower().strip()
    if key in _LANG_MAP:
        return _LANG_MAP[key]
    if len(key) == 2:
        return key
    return "en"
