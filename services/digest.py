import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)

from core.utils import redact
from database import Database
from services.formatter import fit_post
from services.github import GitHubClient
from services.llm import Describer
from services.periods import ORDER, PERIODS, Period, Schedule
from services.publisher import Publisher
from services.trending import Repo

log = logging.getLogger(__name__)

# Telegram said no: the message is surely not in the channel, so a retry cannot duplicate it
REFUSED = (TelegramBadRequest, TelegramForbiddenError, TelegramUnauthorizedError, TelegramNotFound)
# Seconds between schedule checks; a check is one SQLite read per period
TICK = 30
RETRY_AFTER = timedelta(minutes=15)
# Telegram caches link previews by URL, so a redrawn header under the same file
# name would keep showing the old picture: bump this whenever assets/*.png change
IMAGES_VERSION = 3


class NoTop(RuntimeError):
    pass


@dataclass
class Digest:
    period: Period
    slot: datetime
    text: str
    repos: list[Repo]
    source: str  # "trending" or "search" (the fallback)

    @property
    def key(self) -> str:
        return f"{self.period.key}:{self.slot.date().isoformat()}"


@dataclass
class Outcome:
    status: str  # posted / failed / unknown / skipped (someone else already claimed the run)
    message_id: int | None = None
    error: str = ""


class DigestService:
    def __init__(
        self,
        db: Database,
        github: GitHubClient,
        describer: Describer,
        publisher: Publisher,
        schedule: Schedule,
        tz: tzinfo,
        *,
        catch_up: timedelta,
        top_size: int,
        images_url: str,
        channel_link: str = "",
        clock=None,
        retry_after: timedelta = RETRY_AFTER,
    ):
        self.db = db
        self.github = github
        self.describer = describer
        self.publisher = publisher
        self.schedule = schedule
        self.tz = tz
        self.catch_up = catch_up
        self.top_size = top_size
        self.images_url = images_url
        self.channel_link = channel_link
        # Replaced in tests to move through days without waiting for them
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.retry_after = retry_after
        # One post at a time: the schedule and /post must not build and send the same run twice
        self._lock = asyncio.Lock()
        self._retry_at: dict[str, datetime] = {}
        # Runs the admin was told about: one message per failing run, not one per retry
        self._alerted: set[str] = set()

    def now(self) -> datetime:
        return self.clock().astimezone(self.tz)

    def image_url(self, key: str) -> str:
        return f"{self.images_url}/{key}.png?v={IMAGES_VERSION}" if self.images_url else ""

    async def paused(self) -> bool:
        return await self.db.get_setting("paused") == "1"

    async def set_paused(self, paused: bool) -> None:
        await self.db.set_setting("paused", "1" if paused else "0")

    def next_posts(self) -> list[tuple[Period, datetime]]:
        now = self.now()
        return [(PERIODS[key], self.schedule.next_slot(key, now)) for key in ORDER]

    async def fetch(self, period: Period, slot: datetime) -> tuple[list[Repo], str]:
        try:
            repos = await self.github.trending(period.since)
        except Exception as exc:
            log.warning("trending page for %s failed: %s", period.key, redact(str(exc)))
            repos = []
        if repos:
            # GitHub orders the page by its own score, so #3 may have gained more
            # stars than #1; the post ranks by the "+N stars" readers see next to it
            repos.sort(key=lambda repo: repo.stars_gained or 0, reverse=True)
            return repos[: self.top_size], "trending"
        # An empty list means the page changed its layout, not that nothing is trending
        log.warning("trending page for %s gave no repositories, falling back to search", period.key)
        repos = await self.github.new_popular(period.days, slot.date(), self.top_size)
        return repos[: self.top_size], "search"

    async def build(self, key: str, slot: datetime | None = None) -> Digest:
        period = PERIODS[key]
        slot = slot or self.schedule.last_slot(key, self.now())
        repos, source = await self.fetch(period, slot)
        if not repos:
            raise NoTop("GitHub не віддав жодного репозиторію")
        descriptions = await self.describer.describe_all(repos)
        history = await self.db.history(key, slot.date().isoformat(), [repo.name for repo in repos])
        # Dates in the post are those of the data, not of the slot: /post week on a
        # Friday shows the last seven days, while its run is still last Sunday's
        text = fit_post(period, self.now().date(), repos, descriptions, history, self.channel_link)
        return Digest(period, slot, text, repos, source)

    async def recover(self) -> None:
        for key in await self.db.recover():
            await self.publisher.notify(
                f"❓ Бот зупинився, поки надсилав пост {html.escape(key)}. Перевір канал: якщо поста немає, "
                f"надішли /post {html.escape(key.split(':')[0])}."
            )

    async def run(self) -> None:
        await self.recover()
        while True:
            await self.run_due()
            await asyncio.sleep(TICK)

    async def run_due(self) -> None:
        for key in ORDER:
            try:
                await self.post_scheduled(key)
            except Exception:
                log.exception("scheduled %s post failed", key)

    async def post_scheduled(self, key: str) -> None:
        if await self.paused():
            return
        now = self.now()
        slot = self.schedule.last_slot(key, now)
        if now - slot > self.catch_up:
            return
        run_key = f"{key}:{slot.date().isoformat()}"
        if not await self._due(run_key) or self._retry_at.get(run_key, slot) > now:
            return
        period = PERIODS[key]
        async with self._lock:
            # /post may have published this run while the tick waited for the lock
            if not await self._due(run_key):
                return
            try:
                digest = await self.build(key, slot)
            except Exception as exc:
                log.warning("cannot build %s: %s", run_key, redact(str(exc)))
                self._retry_at[run_key] = now + self.retry_after
                await self._alert(run_key, (
                    f"⚠️ Не вдалося зібрати топ {period.hashtag}: {html.escape(redact(str(exc)))}\n"
                    f"Спробую ще раз через {self._minutes()} хв."
                ))
                return
            outcome = await self._send(digest, force=False)
        if outcome.status == "posted":
            if run_key in self._alerted:
                self._alerted.discard(run_key)
                await self.publisher.notify(f"✅ Топ {period.hashtag} все ж опубліковано.")
            if digest.source == "search":
                await self.publisher.notify(
                    f"ℹ️ Сторінка github.com/trending не віддала репозиторіїв, топ {period.hashtag} зібрано з пошуку "
                    "GitHub: нові репозиторії з найбільшою кількістю зірок. Можливо, змінилась верстка сторінки."
                )
        elif outcome.status == "failed":
            await self._alert(run_key, (
                f"❌ Telegram не прийняв пост {period.hashtag}: {html.escape(outcome.error)}\n"
                f"Перевір, що бот адміністратор каналу з правом публікації. Спробую ще раз через {self._minutes()} хв."
            ))
        elif outcome.status == "unknown":
            await self.publisher.notify(
                f"❓ Не знаю, чи вийшов пост {period.hashtag}: {html.escape(outcome.error)}\n"
                f"Перевір канал. Якщо поста немає, надішли /post {key}."
            )

    async def post_now(self, key: str) -> tuple[Digest, Outcome]:
        """/post: builds and sends the current run of the period whatever its status."""
        async with self._lock:
            digest = await self.build(key)
            outcome = await self._send(digest, force=True)
        if outcome.status == "posted":
            self._alerted.discard(digest.key)
        return digest, outcome

    async def _due(self, run_key: str) -> bool:
        run = await self.db.get_run(run_key)
        return run is None or run.status == "failed"

    async def _send(self, digest: Digest, force: bool) -> Outcome:
        key = digest.key
        slot = digest.slot.date().isoformat()
        if not await self.db.start(key, digest.period.key, slot, force=force):
            return Outcome("skipped")
        try:
            message_id = await self.publisher.publish(digest.text, self.image_url(digest.period.key))
        except TelegramRetryAfter as exc:
            error = redact(str(exc))
            await self.db.finish(key, "failed", error=error)
            self._retry_at[key] = self.now() + timedelta(seconds=exc.retry_after)
            return Outcome("failed", error=error)
        except REFUSED as exc:
            error = redact(str(exc))
            await self.db.finish(key, "failed", error=error)
            self._retry_at[key] = self.now() + self.retry_after
            return Outcome("failed", error=error)
        except Exception as exc:
            # Timeout, lost connection, 5xx: the post may already be in the channel,
            # a retry could publish it twice, so the admin decides
            error = redact(str(exc)) or type(exc).__name__
            await self.db.finish(key, "unknown", error=error)
            log.warning("%s: send result unknown: %s", key, error)
            return Outcome("unknown", error=error)
        await self.db.finish(key, "posted", message_id=message_id)
        await self.db.add_appearances(digest.period.key, slot, [repo.name for repo in digest.repos])
        log.info("%s posted from %s, message %s", key, digest.source, message_id)
        return Outcome("posted", message_id=message_id)

    async def _alert(self, run_key: str, text: str) -> None:
        if run_key in self._alerted:
            return
        self._alerted.add(run_key)
        await self.publisher.notify(text)

    def _minutes(self) -> int:
        return int(self.retry_after.total_seconds() // 60)
