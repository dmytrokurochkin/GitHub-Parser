import html

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from core import config
from core.utils import redact
from services.digest import DigestService
from services.periods import ALIASES, ORDER, PERIODS

admin_router = Router()
# Everyone else gets no answer at all: the bot serves one channel of one person
admin_router.message.filter(F.from_user.id == config.ADMIN_ID)

STATUS_ICONS = {
    "posting": "⏳",
    "posted": "✅",
    "failed": "❌",
    "unknown": "❓",
}

HELP = (
    "Бот сам публікує топ-10 репозиторіїв GitHub у канал за розкладом.\n\n"
    "/status: останні пости і коли наступні\n"
    "/preview day|week|month: показати пост тут, у канал нічого не йде\n"
    "/test: надіслати сюди всі три пости (день, тиждень, місяць)\n"
    "/post day|week|month: опублікувати в канал зараз\n"
    "/pause: зупинити публікації за розкладом\n"
    "/resume: відновити публікації"
)


def _period(command: CommandObject) -> str | None:
    arg = (command.args or "day").strip().lower()
    return ALIASES.get(arg)


async def _send_preview(message: Message, service: DigestService, key: str) -> bool:
    """Builds the post of the period and sends it to the admin chat; False when it failed."""
    hashtag = PERIODS[key].hashtag
    try:
        digest = await service.build(key)
        await service.publisher.preview(digest.text, service.image_url(key))
    except Exception as exc:
        await message.answer(f"❌ {hashtag}: не вийшло: {html.escape(redact(str(exc)))}")
        return False
    if digest.source == "search":
        await message.answer(f"ℹ️ {hashtag}: сторінка trending не віддала репозиторіїв, топ зібрано з пошуку GitHub.")
    return True


@admin_router.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@admin_router.message(Command("status"))
async def cmd_status(message: Message, service: DigestService) -> None:
    lines = ["⏸ Публікації на паузі (/resume)" if await service.paused() else "▶️ Публікації за розкладом увімкнені"]
    next_posts = {period.key: slot for period, slot in service.next_posts()}
    for key in ORDER:
        period = PERIODS[key]
        run = await service.db.last_run(key)
        lines.append("")
        lines.append(f"<b>{period.hashtag}</b>: наступний {next_posts[key]:%d.%m.%Y %H:%M}")
        if run is None:
            lines.append("    ще не публікувався")
            continue
        lines.append(f"    {STATUS_ICONS.get(run.status, '•')} {run.slot}: {run.status}")
        if run.error and run.status != "posted":
            lines.append(f"    {html.escape(run.error[:300])}")
    await message.answer("\n".join(lines))


@admin_router.message(Command("preview"))
async def cmd_preview(message: Message, command: CommandObject, service: DigestService) -> None:
    key = _period(command)
    if key is None:
        await message.answer("Період: day, week або month.")
        return
    await message.answer("⏳ Збираю топ, це може зайняти хвилину.")
    await _send_preview(message, service, key)


@admin_router.message(Command("test"))
async def cmd_test(message: Message, service: DigestService) -> None:
    # The same posts the schedule would publish, but in this chat: nothing is
    # recorded, so the channel's 🆕/🔁 marks and the schedule are untouched
    await message.answer("⏳ Збираю всі три пости (день, тиждень, місяць) і надішлю сюди. У канал нічого не йде.")
    done = 0
    for key in ORDER:
        done += await _send_preview(message, service, key)
    if done == len(ORDER):
        await message.answer(f"✅ Тест завершено: усі {done} пости зібрано.")
    else:
        await message.answer(f"⚠️ Тест завершено: зібрано {done} з {len(ORDER)}, помилки вище.")


@admin_router.message(Command("post"))
async def cmd_post(message: Message, command: CommandObject, service: DigestService) -> None:
    key = _period(command)
    if key is None:
        await message.answer("Період: day, week або month.")
        return
    await message.answer("⏳ Збираю топ і публікую.")
    try:
        _, outcome = await service.post_now(key)
    except Exception as exc:
        await message.answer(f"❌ Не вдалося зібрати топ: {html.escape(redact(str(exc)))}")
        return
    if outcome.status == "posted":
        await message.answer(f"✅ Опубліковано в канал {PERIODS[key].hashtag}.")
    elif outcome.status == "unknown":
        await message.answer(f"❓ Невідомо, чи вийшов пост: {html.escape(outcome.error)}\nПеревір канал.")
    else:
        await message.answer(f"❌ Telegram не прийняв пост: {html.escape(outcome.error)}")


@admin_router.message(Command("pause"))
async def cmd_pause(message: Message, service: DigestService) -> None:
    await service.set_paused(True)
    await message.answer("⏸ Публікації за розкладом зупинено. /post працює й далі. Увімкнути: /resume")


@admin_router.message(Command("resume"))
async def cmd_resume(message: Message, service: DigestService) -> None:
    await service.set_paused(False)
    # The schedule does not tell a pause from a powered-off server: a slot skipped
    # less than CATCH_UP_HOURS ago goes out on the next tick
    await message.answer(
        "▶️ Публікації за розкладом відновлено. Пост, пропущений на паузі менше ніж "
        f"{config.CATCH_UP_HOURS} год тому, вийде зараз."
    )
