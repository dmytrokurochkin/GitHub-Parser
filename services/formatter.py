import html
from datetime import date, timedelta

from core.utils import visible_len
from services.periods import Period
from services.trending import Repo

# Telegram's limit for a text message, after the HTML is parsed
MAX_LEN = 4096
# Descriptions are cut shorter and shorter until the post fits; 0 drops them
DESCRIPTION_LIMITS = (220, 160, 120, 80, 50, 0)
MONTHS = (
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
)


def compact(number: int) -> str:
    """106041 -> 106k, 12400 -> 12.4k, 1250000 -> 1.2M."""
    if number < 1000:
        return str(number)
    value, suffix = (number / 1000, "k") if number < 999_950 else (number / 1_000_000, "M")
    return f"{value:.1f}".rstrip("0").rstrip(".") + suffix


def grouped(number: int) -> str:
    # No-break space: "+1 145" never wraps between the digits
    return f"{number:,}".replace(",", " ")


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:—- ") + "…"


def period_dates(period: Period, day: date) -> str:
    if period.key == "day":
        return f"{day:%d.%m.%Y}"
    if period.key == "week":
        return f"{day - timedelta(days=6):%d.%m} – {day:%d.%m.%Y}"
    # The monthly top goes out early in a month and covers the 30 days before it
    covered = day - timedelta(days=15)
    return f"{MONTHS[covered.month - 1]} {covered.year}"


def mark(period: Period, streak: int | None) -> str:
    if streak is None:
        return " 🆕"
    if streak > 0:
        return f" 🔁 {streak + 1}-й {period.word} поспіль"
    return ""


def footer_link(channel_link: str) -> str:
    if channel_link.startswith("@"):
        return f"📢 {html.escape(channel_link)}"
    if channel_link.startswith(("http://", "https://")):
        return f'📢 <a href="{html.escape(channel_link)}">Підписатися на канал</a>'
    return ""


def build_post(
    period: Period,
    day: date,
    repos: list[Repo],
    descriptions: dict[str, str],
    history: dict[str, int | None],
    channel_link: str,
    description_limit: int = DESCRIPTION_LIMITS[0],
) -> str:
    lines = [
        f"🔥 <b>Топ-{len(repos)} репозиторіїв GitHub за {period.word}</b>",
        f"📅 {period_dates(period, day)}",
    ]
    for rank, repo in enumerate(repos, start=1):
        stats = [f"⭐ {compact(repo.stars)}"]
        if repo.stars_gained is not None:
            stats.append(f"+{grouped(repo.stars_gained)} за {period.word}")
        if repo.language:
            stats.append(html.escape(repo.language))
        lines.append("")
        lines.append(
            f'<b>{rank}.</b> <a href="{html.escape(repo.url)}">{html.escape(repo.name)}</a>'
            f"{mark(period, history.get(repo.name))}"
        )
        lines.append(" · ".join(stats))
        description = descriptions.get(repo.name) or repo.description
        if description and description_limit:
            lines.append(html.escape(shorten(description, description_limit)))
    lines.append("")
    link = footer_link(channel_link)
    if link:
        lines.append(link)
    lines.append(period.hashtag)
    return "\n".join(lines)


def fit_post(*args, **kwargs) -> str:
    """build_post with descriptions cut until the post fits into one message."""
    for limit in DESCRIPTION_LIMITS:
        text = build_post(*args, **kwargs, description_limit=limit)
        if visible_len(text) <= MAX_LEN:
            break
    return text
