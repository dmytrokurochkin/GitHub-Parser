import logging

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from core.utils import redact

log = logging.getLogger(__name__)


def preview_options(image_url: str) -> LinkPreviewOptions:
    """The header image as a large preview above the text.

    A photo caption holds only 1024 characters, ten repositories with
    descriptions need about twice that. A link preview of an image URL gives
    the same picture on top of a normal 4096-character message. The URL does
    not have to be in the text itself.

    is_disabled=False must be explicit: every field left out takes the bot's
    default, and create_bot() disables previews, so without it Telegram got
    the image URL together with "is_disabled": true and showed plain text.
    """
    if not image_url:
        return LinkPreviewOptions(is_disabled=True)
    return LinkPreviewOptions(is_disabled=False, url=image_url, prefer_large_media=True, show_above_text=True)


class Publisher:
    def __init__(self, bot: Bot, channel_id: int | str, admin_id: int):
        self.bot = bot
        self.channel_id = channel_id
        self.admin_id = admin_id

    async def publish(self, text: str, image_url: str) -> int:
        message = await self.bot.send_message(self.channel_id, text, link_preview_options=preview_options(image_url))
        return message.message_id

    async def preview(self, text: str, image_url: str) -> None:
        await self.bot.send_message(self.admin_id, text, link_preview_options=preview_options(image_url))

    async def notify(self, text: str) -> None:
        """A message to the admin; never raises, the bot keeps working without it."""
        try:
            await self.bot.send_message(self.admin_id, redact(text))
        except Exception as exc:
            # Usually the admin never pressed /start in the bot
            log.warning("cannot message the admin: %s", redact(str(exc)))
