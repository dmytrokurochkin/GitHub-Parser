import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
# handlers.admin reads config on import; the tests never use a real .env
os.environ.setdefault("ADMIN_ID", "42")

from database import Database  # noqa: E402
from services.digest import DigestService  # noqa: E402
from services.llm import Describer  # noqa: E402
from services.periods import Schedule  # noqa: E402
from services.trending import Repo  # noqa: E402

WARSAW = ZoneInfo("Europe/Warsaw")


def repo(name: str, gained: int | None = 100, stars: int = 1000, description: str = "", language: str = "Python") -> Repo:
    return Repo(name=name, description=description or f"About {name}", language=language,
                stars=stars, forks=10, stars_gained=gained)


def at(year: int, month: int, day: int, hour: int = 6, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=WARSAW)


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class FakeGitHub:
    def __init__(self):
        # since (daily/weekly/monthly) -> repositories of the trending page
        self.pages: dict[str, list[Repo]] = {}
        self.search: list[Repo] = []
        self.readmes: dict[str, str] = {}
        self.search_calls = 0

    def set_all(self, repos: list[Repo]) -> None:
        self.pages = {since: list(repos) for since in ("daily", "weekly", "monthly")}

    async def trending(self, since: str) -> list[Repo]:
        return list(self.pages.get(since, []))

    async def new_popular(self, days, today, limit) -> list[Repo]:
        self.search_calls += 1
        return list(self.search)

    async def readme(self, name: str) -> str | None:
        return self.readmes.get(name)


class FakePublisher:
    def __init__(self):
        self.posts: list[tuple[str, str]] = []
        self.previews: list[str] = []
        self.notes: list[str] = []
        self.fail: Exception | None = None

    async def publish(self, text: str, image_url: str) -> int:
        if self.fail is not None:
            raise self.fail
        self.posts.append((text, image_url))
        return 100 + len(self.posts)

    async def preview(self, text: str, image_url: str) -> None:
        self.previews.append(text)

    async def notify(self, text: str) -> None:
        self.notes.append(text)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "bot.db")
    await database.init()
    return database


@pytest.fixture
def github():
    fake = FakeGitHub()
    fake.set_all([repo(f"owner/repo{i}", gained=1000 - i) for i in range(12)])
    return fake


@pytest.fixture
def publisher():
    return FakePublisher()


@pytest.fixture
def clock():
    return Clock(at(2026, 10, 30, 6, 1))


@pytest.fixture
def make_service(db, github, publisher, clock):
    """A service over the shared fakes; call it again to simulate a restart."""
    def factory(**kwargs) -> DigestService:
        options = {
            "db": db,
            "github": github,
            "describer": Describer(None, "", github, db),
            "publisher": publisher,
            "schedule": Schedule(time(6, 0), 6, 1),
            "tz": WARSAW,
            "catch_up": timedelta(hours=12),
            "top_size": 10,
            "images_url": "https://img.example",
            "channel_link": "@chan",
            "clock": clock,
        }
        options.update(kwargs)
        return DigestService(**options)

    return factory
