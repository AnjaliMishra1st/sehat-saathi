import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv():
    """Tiny .env reader so beginners can keep GNANI_API_KEY in a file (never commit it)."""
    f = Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sehat.db")
GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")
GNANI_BASE_URL = os.getenv("GNANI_BASE_URL") or "https://api.vachana.ai"
# Voices from the Gnani Timbre v2.5 catalog (docs.gnani.ai/api/TTS/available-voices)
GNANI_VOICES = {
    "hi": os.getenv("GNANI_VOICE_HI") or "Nalini",
    "pa": os.getenv("GNANI_VOICE_PA") or "Mehuli",
    "en": os.getenv("GNANI_VOICE_EN") or "Kaveri",
}
RETRY_MINUTES = int(os.getenv("RETRY_MINUTES", "10"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "2"))
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"
NOTIFY_AHEAD = int(os.getenv("NOTIFY_AHEAD", "10"))  # call the patient when this many people (or fewer) are ahead
DEFAULT_HOSPITAL = "City Hospital"
REMINDER_WINDOW_MIN = 60  # a dose reminder is only created within 60 min of its due time
TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Kolkata"))


def now() -> datetime:
    """Current local time (naive, in the configured timezone)."""
    return datetime.now(TZ).replace(tzinfo=None)
