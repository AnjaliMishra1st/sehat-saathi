"""Gnani.ai speech APIs (Vachana): text-to-speech (Timbre) and speech-to-text (Prisma).

Docs: https://docs.gnani.ai/api/introduction/introduction.md
  TTS  POST {base}/api/v1/tts/inference   (JSON, returns audio bytes)
  STT  POST {base}/stt/v3                 (multipart, audio up to 60 s, returns JSON transcript)
Auth: header X-API-Key-ID.
"""
import httpx

from . import config

LANG_CODE = {"hi": "hi-IN", "pa": "pa-IN", "en": "en-IN"}


class GnaniError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(config.GNANI_API_KEY)


def _headers() -> dict:
    return {"X-API-Key-ID": config.GNANI_API_KEY}


def _check(r: httpx.Response):
    if r.status_code == 200:
        return
    try:
        msg = r.json().get("error", {}).get("message") or r.text
    except Exception:
        msg = r.text
    if r.status_code == 403:
        msg = f"Gnani refused the request (check API key and credits). {msg}"
    raise GnaniError(f"Gnani error {r.status_code}: {msg}"[:300], r.status_code)


def synthesize(text: str, lang: str = "hi") -> bytes:
    """Text -> WAV audio bytes."""
    lang = lang if lang in LANG_CODE else "hi"
    body = {
        "text": text,
        "voice": config.GNANI_VOICES[lang],
        "model": "timbre-v2.5",
        "language": LANG_CODE[lang],
        "speed": 1.0,
        "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"},
    }
    try:
        r = httpx.post(f"{config.GNANI_BASE_URL}/api/v1/tts/inference", json=body, headers=_headers(), timeout=30)
    except httpx.HTTPError as e:
        raise GnaniError(f"Could not reach Gnani: {e}") from e
    _check(r)
    return r.content


def transcribe(audio: bytes, lang: str = "hi", filename: str = "reply.wav", content_type: str = "audio/wav") -> str:
    """Audio bytes (WAV/MP3/OGG/FLAC/AAC/M4A, <= 60 s) -> transcript text."""
    lang = lang if lang in LANG_CODE else "hi"
    # format=transcribe turns spoken numbers into digits ("one eighty" -> 180), handy for BP/sugar readings
    data = {"language_code": LANG_CODE[lang], "format": "transcribe"}
    try:
        r = httpx.post(f"{config.GNANI_BASE_URL}/stt/v3", headers=_headers(), data=data,
                       files={"audio_file": (filename, audio, content_type)}, timeout=60)
    except httpx.HTTPError as e:
        raise GnaniError(f"Could not reach Gnani: {e}") from e
    _check(r)
    return (r.json().get("transcript") or "").strip()
