from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

SCHEMA = """
-- One row per scheduled post: key is "day:2026-10-30"
CREATE TABLE IF NOT EXISTS runs (
    key TEXT PRIMARY KEY,
    period TEXT NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL,
    message_id INTEGER,
    error TEXT,
    updated_at TEXT NOT NULL
);
-- Which repositories a posted top held: the 🆕 and 🔁 marks come from here
CREATE TABLE IF NOT EXISTS appearances (
    period TEXT NOT NULL,
    slot TEXT NOT NULL,
    repo TEXT NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY (period, slot, repo)
);
-- LLM descriptions: a repository stays in the trends for days, it is described once
CREATE TABLE IF NOT EXISTS descriptions (
    repo TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Run statuses:
#   posting  claimed, the message is being sent
#   posted   in the channel
#   failed   Telegram refused (or the top could not be built), retried later
#   unknown  the send broke off mid-way: the post may or may not be in the channel,
#            never retried automatically (see CLAUDE.md, "Дублі")


@dataclass
class Run:
    key: str
    period: str
    slot: str
    status: str
    message_id: int | None
    error: str | None
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(SCHEMA)
            await db.commit()

    async def get_run(self, key: str) -> Run | None:
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall("SELECT * FROM runs WHERE key = ?", (key,))
        return Run(*rows[0]) if rows else None

    async def start(self, key: str, period: str, slot: str, force: bool = False) -> bool:
        """Claims the run for sending; False when it is already posted, posting or unknown.

        force (the /post command) claims it whatever the status: the admin asked
        for a post right now.
        """
        condition = "" if force else "WHERE runs.status = 'failed'"
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                f"""INSERT INTO runs (key, period, slot, status, updated_at) VALUES (?, ?, ?, 'posting', ?)
                    ON CONFLICT(key) DO UPDATE SET status = 'posting', error = NULL, updated_at = excluded.updated_at
                    {condition}""",
                (key, period, slot, _now()),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def finish(self, key: str, status: str, message_id: int | None = None, error: str | None = None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE runs SET status = ?, message_id = COALESCE(?, message_id), error = ?, updated_at = ? WHERE key = ?",
                (status, message_id, error, _now(), key),
            )
            await db.commit()

    async def recover(self) -> list[str]:
        """Runs left in posting by a crash or a restart become unknown."""
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall("SELECT key FROM runs WHERE status = 'posting'")
            await db.execute(
                "UPDATE runs SET status = 'unknown', error = 'бот зупинився під час надсилання', updated_at = ? "
                "WHERE status = 'posting'",
                (_now(),),
            )
            await db.commit()
        return [row[0] for row in rows]

    async def last_run(self, period: str) -> Run | None:
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall(
                "SELECT * FROM runs WHERE period = ? ORDER BY slot DESC LIMIT 1", (period,)
            )
        return Run(*rows[0]) if rows else None

    async def add_appearances(self, period: str, slot: str, names: list[str]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                "INSERT OR IGNORE INTO appearances (period, slot, repo, rank) VALUES (?, ?, ?, ?)",
                [(period, slot, name, rank) for rank, name in enumerate(names, start=1)],
            )
            await db.commit()

    async def history(self, period: str, before: str, names: list[str]) -> dict[str, int | None]:
        """For each name: None if it was never in a posted top of this period before the slot,
        otherwise how many of the latest posted tops in a row held it (0: not the last one).
        """
        if not names:
            return {}
        marks = ",".join("?" * len(names))
        async with aiosqlite.connect(self.path) as db:
            slots = [row[0] for row in await db.execute_fetchall(
                "SELECT DISTINCT slot FROM appearances WHERE period = ? AND slot < ? ORDER BY slot DESC",
                (period, before),
            )]
            seen = {(row[0], row[1]) for row in await db.execute_fetchall(
                f"SELECT repo, slot FROM appearances WHERE period = ? AND slot < ? AND repo IN ({marks})",
                (period, before, *names),
            )}
        known = {repo for repo, _ in seen}
        result: dict[str, int | None] = {}
        for name in names:
            if name not in known:
                result[name] = None
                continue
            streak = 0
            for slot in slots:
                if (name, slot) not in seen:
                    break
                streak += 1
            result[name] = streak
        return result

    async def get_description(self, repo: str, max_age: timedelta) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall("SELECT text, created_at FROM descriptions WHERE repo = ?", (repo,))
        if not rows:
            return None
        text, created_at = rows[0]
        if datetime.now(timezone.utc) - datetime.fromisoformat(created_at) > max_age:
            return None
        return text

    async def set_description(self, repo: str, text: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO descriptions (repo, text, created_at) VALUES (?, ?, ?)",
                (repo, text, _now()),
            )
            await db.commit()

    async def get_setting(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0][0] if rows else default

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            await db.commit()
