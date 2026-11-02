from datetime import timedelta


async def test_start_claims_a_run_once(db):
    assert await db.start("day:2026-10-30", "day", "2026-10-30")
    assert not await db.start("day:2026-10-30", "day", "2026-10-30")
    await db.finish("day:2026-10-30", "posted", message_id=5)
    assert not await db.start("day:2026-10-30", "day", "2026-10-30")
    run = await db.get_run("day:2026-10-30")
    assert run.status == "posted" and run.message_id == 5


async def test_failed_run_can_be_claimed_again(db):
    await db.start("day:2026-10-30", "day", "2026-10-30")
    await db.finish("day:2026-10-30", "failed", error="Bad Request")
    assert await db.start("day:2026-10-30", "day", "2026-10-30")
    run = await db.get_run("day:2026-10-30")
    assert run.status == "posting" and run.error is None


async def test_unknown_run_is_claimed_only_by_force(db):
    await db.start("day:2026-10-30", "day", "2026-10-30")
    await db.finish("day:2026-10-30", "unknown", error="timeout")
    assert not await db.start("day:2026-10-30", "day", "2026-10-30")
    assert await db.start("day:2026-10-30", "day", "2026-10-30", force=True)


async def test_recover_turns_posting_into_unknown(db):
    await db.start("day:2026-10-30", "day", "2026-10-30")
    assert await db.recover() == ["day:2026-10-30"]
    assert (await db.get_run("day:2026-10-30")).status == "unknown"
    assert await db.recover() == []


async def test_history_counts_the_streak(db):
    await db.add_appearances("day", "2026-10-27", ["a/a", "b/b"])
    await db.add_appearances("day", "2026-10-28", ["a/a"])
    await db.add_appearances("day", "2026-10-29", ["a/a", "c/c"])
    # The weekly top is separate
    await db.add_appearances("week", "2026-10-25", ["d/d"])
    history = await db.history("day", "2026-10-30", ["a/a", "b/b", "c/c", "d/d"])
    assert history == {"a/a": 3, "b/b": 0, "c/c": 1, "d/d": None}


async def test_history_ignores_the_slot_itself_and_later(db):
    await db.add_appearances("day", "2026-10-30", ["a/a"])
    assert await db.history("day", "2026-10-30", ["a/a"]) == {"a/a": None}


async def test_descriptions_expire(db):
    await db.set_description("a/a", "Опис")
    assert await db.get_description("a/a", timedelta(days=30)) == "Опис"
    assert await db.get_description("a/a", timedelta(seconds=-1)) is None
    assert await db.get_description("b/b", timedelta(days=30)) is None


async def test_settings(db):
    assert await db.get_setting("paused") == ""
    await db.set_setting("paused", "1")
    assert await db.get_setting("paused") == "1"
