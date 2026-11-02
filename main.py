import asyncio
import contextlib
import html
import logging
import sys
from datetime import timedelta

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand
from openai import AsyncOpenAI

from core import config
from core.loader import create_bot
from core.utils import RedactFilter, add_secret, redact
from database import Database
from handlers.admin import admin_router
from services.digest import DigestService
from services.github import GitHubClient
from services.llm import Describer
from services.periods import Schedule
from services.publisher import Publisher

log = logging.getLogger("github-parser")

COMMANDS = [
    BotCommand(command="status", description="Останні пости і наступні"),
    BotCommand(command="preview", description="Показати пост тут: day, week, month"),
    BotCommand(command="post", description="Опублікувати зараз: day, week, month"),
    BotCommand(command="pause", description="Зупинити розклад"),
    BotCommand(command="resume", description="Відновити розклад"),
]


def setup_logging() -> None:
    add_secret(config.BOT_TOKEN)
    add_secret(config.GITHUB_TOKEN)
    add_secret(config.LLM_API_KEY)
    # Messages for the admin are logged too, and a Windows console is not UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # Every getUpdates and every LLM request at INFO would drown the bot's own lines
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def check_channel(bot: Bot) -> tuple[str, list[str]]:
    """The footer link of the channel and the problems with the bot's rights there."""
    problems = []
    link = config.CHANNEL_LINK
    try:
        chat = await bot.get_chat(config.CHANNEL_ID)
        if not link and chat.username:
            link = f"@{chat.username}"
        me = await bot.get_me()
        member = await bot.get_chat_member(config.CHANNEL_ID, me.id)
        if member.status != "administrator" or not getattr(member, "can_post_messages", False):
            problems.append("бот не адміністратор каналу з правом «Публікація повідомлень»")
        if not link:
            problems.append("канал приватний і CHANNEL_LINK порожній: у пості не буде посилання на канал")
    except Exception as exc:
        problems.append(f"канал {config.CHANNEL_ID} недоступний: {redact(str(exc))}")
    return link, problems


async def run() -> None:
    db = Database(config.DB_PATH)
    await db.init()
    llm = AsyncOpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL, timeout=90, max_retries=1) \
        if config.LLM_API_KEY else None
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        github = GitHubClient(http, config.GITHUB_API_URL, config.GITHUB_WEB_URL, config.GITHUB_TOKEN)
        bot = create_bot(config.BOT_TOKEN)
        try:
            publisher = Publisher(bot, config.CHANNEL_ID, config.ADMIN_ID)
            channel_link, problems = await check_channel(bot)
            service = DigestService(
                db=db,
                github=github,
                describer=Describer(llm, config.LLM_MODEL, github, db),
                publisher=publisher,
                schedule=Schedule(config.POST_TIME, config.WEEKLY_DAY, config.MONTHLY_DAY),
                tz=config.TIMEZONE,
                catch_up=timedelta(hours=config.CATCH_UP_HOURS),
                top_size=config.TOP_SIZE,
                images_url=config.IMAGES_URL,
                channel_link=channel_link,
            )
            await announce(service, publisher, problems)
            try:
                await bot.set_my_commands(COMMANDS)
            except Exception as exc:
                # After a reboot the network may come up later than the container;
                # polling waits for it on its own, the command menu is not worth a crash
                log.warning("cannot set the command menu: %s", redact(str(exc)))
            dp = Dispatcher(service=service)
            dp.include_router(admin_router)
            loop_task = asyncio.create_task(service.run())
            try:
                await dp.start_polling(bot, allowed_updates=["message"])
            finally:
                loop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await loop_task
        finally:
            await bot.session.close()
            if llm is not None:
                await llm.close()


async def announce(service: DigestService, publisher: Publisher, problems: list[str]) -> None:
    lines = ["🚀 Бот запущено. Наступні пости:"]
    lines += [f"{period.hashtag}: {slot:%d.%m.%Y %H:%M}" for period, slot in service.next_posts()]
    if await service.paused():
        lines.append("⏸ Розклад на паузі: /resume")
    if not config.LLM_API_KEY:
        lines.append("ℹ️ LAPATHONIA_API_KEY порожній: описи будуть оригінальні, англійською")
    if not config.GITHUB_TOKEN:
        lines.append("ℹ️ GITHUB_TOKEN порожній: ліміт GitHub 60 запитів на годину")
    if problems:
        lines.append("")
        lines += [f"⚠️ {html.escape(problem)}" for problem in problems]
    for problem in problems:
        log.warning(problem)
    await publisher.notify("\n".join(lines))


def main() -> int:
    setup_logging()
    missing = config.missing()
    if missing:
        log.error("not set or invalid in .env: %s", ", ".join(missing))
        return 2
    try:
        asyncio.run(run())
    except TelegramUnauthorizedError:
        log.error("Telegram rejected BOT_TOKEN: check it in .env (./deploy.sh --reconfigure)")
        return 2
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
