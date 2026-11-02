from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from services.digest import IMAGES_VERSION
from tests.conftest import at, repo

METHOD = SendMessage(chat_id=1, text="x")


def hashtags(publisher) -> list[str]:
    return [text.rsplit("\n", 1)[1] for text, _ in publisher.posts]


async def test_due_post_goes_out_once(make_service, publisher):
    service = make_service()
    await service.run_due()
    await service.run_due()
    # Friday 30.10 06:01: only the daily top is due
    assert hashtags(publisher) == ["#day"]
    text, image = publisher.posts[0]
    assert image == f"https://img.example/day.png?v={IMAGES_VERSION}"
    assert "📅 30.10.2026" in text
    run = await service.db.get_run("day:2026-10-30")
    assert run.status == "posted" and run.message_id == 101


async def test_restart_does_not_repost(make_service, publisher):
    await make_service().run_due()
    await make_service().run_due()
    assert len(publisher.posts) == 1


async def test_nothing_before_the_time(make_service, publisher, clock):
    clock.now = at(2026, 10, 30, 5, 59)
    await make_service().run_due()
    assert publisher.posts == []


async def test_missed_post_is_caught_up_within_the_window(make_service, publisher, clock):
    clock.now = at(2026, 10, 30, 17, 59)
    await make_service().run_due()
    assert hashtags(publisher) == ["#day"]


async def test_missed_post_is_dropped_after_the_window(make_service, publisher, clock):
    clock.now = at(2026, 10, 30, 18, 1)
    await make_service().run_due()
    assert publisher.posts == []


async def test_sunday_the_first_posts_all_three_in_order(make_service, publisher, clock):
    clock.now = at(2026, 11, 1, 6, 0)
    await make_service().run_due()
    assert hashtags(publisher) == ["#day", "#week", "#month"]
    assert [image for _, image in publisher.posts] == [
        f"https://img.example/{key}.png?v={IMAGES_VERSION}" for key in ("day", "week", "month")
    ]
    assert "📅 Жовтень 2026" in publisher.posts[2][0]


async def test_top_is_ranked_by_stars_gained(make_service, publisher, github):
    github.set_all([repo("a/low", gained=5), repo("b/high", gained=500), repo("c/mid", gained=50)])
    await make_service().run_due()
    text = publisher.posts[0][0]
    assert text.index("b/high") < text.index("c/mid") < text.index("a/low")


async def test_top_is_cut_to_top_size(make_service, publisher):
    await make_service(top_size=3).run_due()
    assert "Топ-3" in publisher.posts[0][0]
    assert "<b>4.</b>" not in publisher.posts[0][0]


async def test_falls_back_to_search(make_service, publisher, github):
    github.pages = {}
    github.search = [repo("new/star", gained=None, stars=900)]
    await make_service().run_due()
    assert "new/star" in publisher.posts[0][0]
    assert "+" not in publisher.posts[0][0].split("\n")[4]
    assert any("пошуку" in note for note in publisher.notes)


async def test_no_repositories_alerts_once_and_retries(make_service, publisher, github, clock):
    github.pages = {}
    service = make_service()
    await service.run_due()
    await service.run_due()
    assert publisher.posts == []
    assert len(publisher.notes) == 1 and "Не вдалося зібрати топ #day" in publisher.notes[0]
    assert github.search_calls == 1, "a retry waits RETRY_AFTER, not the next tick"

    github.set_all([repo("back/again")])
    clock.advance(minutes=16)
    await service.run_due()
    assert hashtags(publisher) == ["#day"]
    assert "все ж опубліковано" in publisher.notes[-1]


async def test_telegram_refusal_is_retried(make_service, publisher, clock):
    publisher.fail = TelegramBadRequest(METHOD, "Bad Request: need administrator rights in the channel chat")
    service = make_service()
    await service.run_due()
    assert (await service.db.get_run("day:2026-10-30")).status == "failed"
    assert "Telegram не прийняв пост #day" in publisher.notes[0]

    publisher.fail = None
    clock.advance(minutes=5)
    await service.run_due()
    assert publisher.posts == []
    clock.advance(minutes=11)
    await service.run_due()
    assert hashtags(publisher) == ["#day"]


async def test_retry_after_waits_as_long_as_telegram_asks(make_service, publisher, clock):
    publisher.fail = TelegramRetryAfter(METHOD, "Too Many Requests", retry_after=60)
    service = make_service()
    await service.run_due()
    publisher.fail = None
    clock.advance(seconds=61)
    await service.run_due()
    assert hashtags(publisher) == ["#day"]


async def test_unknown_result_is_never_retried(make_service, publisher, clock):
    publisher.fail = TelegramNetworkError(METHOD, "Request timeout error")
    service = make_service()
    await service.run_due()
    publisher.fail = None
    clock.advance(hours=1)
    await service.run_due()
    assert publisher.posts == []
    assert (await service.db.get_run("day:2026-10-30")).status == "unknown"
    assert "/post day" in publisher.notes[0]


async def test_restart_mid_send_becomes_unknown(make_service, publisher, db):
    await db.start("day:2026-10-30", "day", "2026-10-30")
    service = make_service()
    await service.recover()
    await service.run_due()
    assert publisher.posts == []
    assert (await db.get_run("day:2026-10-30")).status == "unknown"
    assert "/post day" in publisher.notes[0]


async def test_pause_stops_the_schedule(make_service, publisher):
    service = make_service()
    await service.set_paused(True)
    await service.run_due()
    assert publisher.posts == []
    await service.set_paused(False)
    await service.run_due()
    assert hashtags(publisher) == ["#day"]


async def test_post_now_publishes_even_when_already_posted(make_service, publisher):
    service = make_service()
    await service.run_due()
    _, outcome = await service.post_now("day")
    assert outcome.status == "posted"
    assert len(publisher.posts) == 2


async def test_post_now_counts_as_the_scheduled_post(make_service, publisher, clock):
    clock.now = at(2026, 10, 30, 5, 0)
    service = make_service()
    await service.post_now("week")
    # The week slot of 05:00 on Friday is Sunday 25.10, already outside the window anyway;
    # the daily slot is what matters: /post day at 06:30 then the tick must not post again
    clock.now = at(2026, 10, 30, 6, 30)
    await service.post_now("day")
    await service.run_due()
    assert hashtags(publisher) == ["#week", "#day"]


async def test_marks_new_and_repeated_repositories(make_service, publisher, github, clock):
    github.set_all([repo("a/stays", gained=300), repo("b/leaves", gained=200)])
    service = make_service()
    await service.run_due()
    first = publisher.posts[0][0]
    assert "a/stays</a> 🆕" in first and "b/leaves</a> 🆕" in first

    github.set_all([repo("a/stays", gained=300), repo("c/fresh", gained=100)])
    clock.advance(days=1)
    await service.run_due()
    second = publisher.posts[1][0]
    assert "a/stays</a> 🔁 2-й день поспіль" in second
    assert "c/fresh</a> 🆕" in second


async def test_preview_builds_without_touching_the_run(make_service, publisher):
    service = make_service()
    digest = await service.build("day")
    assert digest.key == "day:2026-10-30"
    assert await service.db.get_run("day:2026-10-30") is None
    assert publisher.posts == []
