import os
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Variables set by docker compose (or the shell) win over .env
load_dotenv(BASE_DIR / ".env", override=False)

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _chat_id(value: str) -> int | str:
    value = value.strip()
    return int(value) if value.lstrip("-").isdigit() else value


def _int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _time(value: str) -> time | None:
    try:
        hours, minutes = value.strip().split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        return None


def _zone(value: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = _chat_id(os.getenv("CHANNEL_ID", ""))
# The only person the bot answers; errors go to this chat too
ADMIN_ID = _int(os.getenv("ADMIN_ID", "").strip(), 0)
# Footer link; empty means "@username of the channel" when the channel is public
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip() or None
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com").strip().rstrip("/")
# The trending page has no API; overridden only by tests
GITHUB_WEB_URL = os.getenv("GITHUB_WEB_URL", "https://github.com").strip().rstrip("/")

# Same OpenAI-compatible provider as AI-Bot-v2. Without a key the posts carry
# the original English description from GitHub
LLM_API_KEY = os.getenv("LAPATHONIA_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LAPATHONIA_BASE_URL", "https://api.lapathoniia.top/v1").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "MamayLM-Gemma-3-27B-IT-v2.0").strip()

TIMEZONE = _zone(os.getenv("TIMEZONE", "Europe/Warsaw"))
POST_TIME = _time(os.getenv("POST_TIME", "06:00"))
WEEKLY_DAY = WEEKDAYS.get(os.getenv("WEEKLY_DAY", "sunday").strip().lower())
# Capped at 28 so every month has the day
MONTHLY_DAY = min(max(_int(os.getenv("MONTHLY_DAY", "1"), 1), 1), 28)
# A post missed while the server was off still goes out if the bot starts
# within this many hours after the scheduled time
CATCH_UP_HOURS = max(0, _int(os.getenv("CATCH_UP_HOURS", "12"), 12))
TOP_SIZE = min(max(_int(os.getenv("TOP_SIZE", "10"), 10), 1), 25)

# Header images are shown as the link preview, so Telegram must be able to
# download them: by default they come from this repository on GitHub
IMAGES_URL = os.getenv(
    "IMAGES_URL", "https://raw.githubusercontent.com/dmytrokurochkin/GitHub-Parser/main/assets"
).strip().rstrip("/")

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "bot.db"


def missing() -> list[str]:
    names = []
    if not BOT_TOKEN:
        names.append("BOT_TOKEN")
    if CHANNEL_ID == "":
        names.append("CHANNEL_ID")
    if not ADMIN_ID:
        names.append("ADMIN_ID")
    if TIMEZONE is None:
        names.append("TIMEZONE")
    if POST_TIME is None:
        names.append("POST_TIME")
    if WEEKLY_DAY is None:
        names.append("WEEKLY_DAY")
    return names
