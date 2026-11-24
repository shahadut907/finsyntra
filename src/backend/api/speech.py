"""Voice dictation: short recorded audio -> editable composer text.

This is dictation only. The transcript is returned to the browser for the
user to review and edit; nothing is sent to chat and nothing is persisted.

* Auth: the same cookie/JWT dependency as chat; CSRF is enforced by the
  security middleware for this cookie-authenticated POST.
* Limits: request size (``speech_max_bytes``), recognised audio duration
  (``speech_max_seconds``, also enforced by the client recorder), and a
  per-user rate limit in addition to the middleware's per-client bucket.
* Privacy: audio is held in memory only for the provider call, never written
  to disk, logged, or stored. Transcript text is never logged.
* Credentials stay server-side; the provider URL is fixed configuration.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from src.backend.api.auth_deps import get_current_user, get_visitor_session_id
from src.backend.middleware.security import rate_limiter
from src.backend.services.model_catalog import availability
from src.config.settings import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Groq lists flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm. Browsers record
# webm (Chrome/Edge/Firefox) or mp4 (Safari).
_ALLOWED_TYPES = {
    "audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav",
    "audio/x-wav", "audio/wave", "audio/flac", "audio/x-m4a", "audio/m4a",
    "video/webm",  # some browsers label audio-only webm as video/webm
}
_EXTENSIONS = {
    "audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4",
    "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav",
    "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac",
}
# Whisper's own language codes (ISO-639-1). "auto" lets the model detect.
LANGUAGES = {"en": "English", "bn": "বাংলা"}
# Segments the model itself flags as probably-not-speech are dropped, which
# stops Whisper's well-known "Thank you." hallucination on silent clips.
_NO_SPEECH_THRESHOLD = 0.6
DISCLOSURE = (
    "Your recording is sent to Groq for transcription and is not stored by FinSyntra. "
    "You can edit the text before sending."
)


def _looks_like_audio(data: bytes) -> bool:
    head = data[:12]
    return (
        head.startswith(b"\x1a\x45\xdf\xa3")      # WebM / Matroska
        or head.startswith(b"OggS")               # Ogg
        or (head.startswith(b"RIFF") and data[8:12] == b"WAVE")
        or data[4:8] == b"ftyp"                   # MP4 / M4A
        or head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")  # MP3
        or head.startswith(b"fLaC")
    )


def dictation_capability() -> Dict[str, Any]:
    """What the composer may offer. Never claims availability it lacks."""
    if not settings.speech_enabled:
        return {"available": False, "reason": "Voice dictation is turned off on this server."}
    if not settings.groq_api_key.strip():
        return {"available": False, "reason": "No transcription provider is configured."}
    served = availability.served_models()
    if served is not None and settings.speech_model not in served:
        return {"available": False, "reason": "The transcription model is not available."}
    return {
        "available": True,
        "languages": [{"id": "auto", "label": "Auto"}]
        + [{"id": code, "label": label} for code, label in LANGUAGES.items()],
        "max_seconds": settings.speech_max_seconds,
        "max_bytes": settings.speech_max_bytes,
        "disclosure": DISCLOSURE,
    }


def _error(status: int, code: str, message: str, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message}, headers=headers)


def _call_provider(data: bytes, content_type: str, language: Optional[str]) -> requests.Response:
    files = {"file": (f"dictation.{_EXTENSIONS.get(content_type, 'webm')}", data, content_type)}
    form = {"model": settings.speech_model, "response_format": "verbose_json", "temperature": "0"}
    if language:
        form["language"] = language
    return requests.post(
        f"{settings.groq_base_url.rstrip('/')}/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        files=files,
        data=form,
        timeout=settings.speech_timeout_seconds,
    )


@router.post("/speech/transcribe")
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str = Form("auto"),
):
    user = await get_current_user(request)

    capability = dictation_capability()
    if not capability.get("available"):
        return _error(503, "dictation_unavailable", capability.get("reason", "Voice dictation is unavailable."))

    # Per-identity limit (the middleware's bucket is per client address, and
    # public-demo visitors share one account, so include the visitor too).
    identity = f"{user.get('id')}:{get_visitor_session_id(request) or ''}"
    key = hashlib.sha256(f"speech-user:{identity}".encode()).hexdigest()
    if not rate_limiter.is_allowed(key, settings.speech_rate_limit_per_minute):
        return _error(429, "rate_limited", "Too many dictations. Please wait a minute and try again.",
                      headers={"Retry-After": "60"})

    lang = (language or "auto").strip().lower()
    if lang != "auto" and lang not in LANGUAGES:
        return _error(400, "invalid_language", "Unsupported dictation language.")

    content_type = (audio.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _ALLOWED_TYPES:
        return _error(415, "unsupported_audio", "Unsupported audio format.")

    # Bounded read: never buffer more than the limit.
    data = await audio.read(settings.speech_max_bytes + 1)
    await audio.close()
    if len(data) > settings.speech_max_bytes:
        return _error(413, "audio_too_large", "The recording is too long. Please keep dictation under a minute.")
    if len(data) < 512 or not _looks_like_audio(data):
        return _error(422, "empty_audio", "No audio was captured. Please try again.")

    try:
        response = await asyncio.to_thread(_call_provider, data, content_type, None if lang == "auto" else lang)
    except requests.exceptions.Timeout:
        logger.warning("SPEECH_TIMEOUT model=%s bytes=%d", settings.speech_model, len(data))
        return _error(504, "transcription_timeout", "Transcription took too long. Please try again.")
    except requests.exceptions.RequestException:
        logger.error("SPEECH_UNAVAILABLE model=%s", settings.speech_model, exc_info=True)
        return _error(502, "transcription_failed", "The transcription service is unavailable.")
    finally:
        del data  # audio is not retained beyond the provider call

    if response.status_code == 429:
        return _error(503, "provider_busy", "The transcription service is busy. Please try again shortly.",
                      headers={"Retry-After": response.headers.get("Retry-After", "30")})
    if response.status_code != 200:
        logger.error("SPEECH_PROVIDER_ERROR status=%s model=%s", response.status_code, settings.speech_model)
        return _error(502, "transcription_failed", "Transcription failed. Please try again.")

    try:
        payload = response.json()
    except ValueError:
        return _error(502, "transcription_failed", "Transcription failed. Please try again.")

    duration = float(payload.get("duration") or 0)
    if duration > settings.speech_max_seconds + 2:
        return _error(413, "audio_too_long", "The recording is too long. Please keep dictation under a minute.")

    segments = payload.get("segments")
    if isinstance(segments, list) and segments:
        kept = [
            (seg.get("text") or "").strip()
            for seg in segments
            if isinstance(seg, dict) and float(seg.get("no_speech_prob") or 0) < _NO_SPEECH_THRESHOLD
        ]
        text = " ".join(t for t in kept if t).strip()
    else:
        text = (payload.get("text") or "").strip()

    logger.info("SPEECH_OK model=%s lang=%s duration=%.1fs chars=%d",
                settings.speech_model, lang, duration, len(text))
    if not text:
        return _error(422, "no_speech", "No speech was detected. Please try again.")
    return {"text": text, "language": payload.get("language") or lang, "duration": round(duration, 1)}
