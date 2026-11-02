import json

from core.loader import create_bot
from services.publisher import preview_options

TOKEN = "123456:TEST-token_value"


async def sent(options) -> dict:
    """What Telegram receives: the options after the bot's defaults are filled in."""
    bot = create_bot(TOKEN)
    try:
        return json.loads(bot.session.prepare_value(options, bot=bot, files={}))
    finally:
        await bot.session.close()


async def test_image_preview_is_enabled_despite_the_bot_default():
    data = await sent(preview_options("https://img.example/day.png"))
    assert data == {
        "is_disabled": False,
        "url": "https://img.example/day.png",
        "prefer_large_media": True,
        "show_above_text": True,
    }


async def test_no_image_means_no_preview():
    assert (await sent(preview_options(""))) == {"is_disabled": True}
