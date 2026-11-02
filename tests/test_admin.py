from aiogram.filters import CommandObject

from handlers.admin import cmd_pause, cmd_post, cmd_preview, cmd_resume, cmd_status, cmd_test


class FakeMessage:
    def __init__(self):
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


def command(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="x", args=args)


async def test_status_before_any_post(make_service):
    message = FakeMessage()
    await cmd_status(message, make_service())
    text = message.answers[0]
    assert "▶️" in text
    assert "<b>#day</b>: наступний 31.10.2026 06:00" in text
    assert "<b>#week</b>: наступний 01.11.2026 06:00" in text
    assert "ще не публікувався" in text


async def test_status_shows_the_error(make_service, publisher):
    service = make_service()
    await service.db.start("day:2026-10-30", "day", "2026-10-30")
    await service.db.finish("day:2026-10-30", "unknown", error="Request timeout <x>")
    message = FakeMessage()
    await cmd_status(message, service)
    assert "❓ 2026-10-30: unknown" in message.answers[0]
    assert "Request timeout &lt;x&gt;" in message.answers[0]


async def test_preview_goes_to_the_admin_only(make_service, publisher):
    message = FakeMessage()
    await cmd_preview(message, command("week"), make_service())
    assert publisher.posts == []
    assert len(publisher.previews) == 1 and publisher.previews[0].endswith("#week")


async def test_ukrainian_alias_and_default_period(make_service, publisher):
    service = make_service()
    await cmd_preview(FakeMessage(), command("місяць"), service)
    await cmd_preview(FakeMessage(), command(None), service)
    assert [text.rsplit("\n", 1)[1] for text in publisher.previews] == ["#month", "#day"]


async def test_test_sends_all_three_to_the_admin(make_service, publisher):
    service = make_service()
    message = FakeMessage()
    await cmd_test(message, service)
    assert [text.rsplit("\n", 1)[1] for text in publisher.previews] == ["#day", "#week", "#month"]
    assert publisher.posts == []
    assert message.answers[-1] == "✅ Тест завершено: усі 3 пости зібрано."
    # Nothing is recorded: the schedule still posts today's top, all repositories still 🆕
    assert await service.db.get_run("day:2026-10-30") is None
    await service.run_due()
    assert len(publisher.posts) == 1 and "🆕" in publisher.posts[0][0]


async def test_test_reports_failures(make_service, publisher, github):
    github.pages = {}
    message = FakeMessage()
    await cmd_test(message, make_service())
    assert publisher.previews == []
    assert sum("❌" in answer for answer in message.answers) == 3
    assert message.answers[-1] == "⚠️ Тест завершено: зібрано 0 з 3, помилки вище."


async def test_unknown_period(make_service, publisher):
    message = FakeMessage()
    await cmd_post(message, command("year"), make_service())
    assert message.answers == ["Період: day, week або month."]
    assert publisher.posts == []


async def test_post_publishes(make_service, publisher):
    message = FakeMessage()
    await cmd_post(message, command("day"), make_service())
    assert len(publisher.posts) == 1
    assert message.answers[-1] == "✅ Опубліковано в канал #day."


async def test_post_reports_an_empty_top(make_service, publisher, github):
    github.pages = {}
    message = FakeMessage()
    await cmd_post(message, command("day"), make_service())
    assert publisher.posts == []
    assert "GitHub не віддав жодного репозиторію" in message.answers[-1]


async def test_pause_and_resume(make_service):
    service = make_service()
    await cmd_pause(FakeMessage(), service)
    assert await service.paused()
    await cmd_resume(FakeMessage(), service)
    assert not await service.paused()
