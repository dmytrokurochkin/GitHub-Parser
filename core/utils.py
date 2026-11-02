import html
import logging
import re

_secrets: set[str] = set()


def add_secret(value: str | None) -> None:
    if value:
        _secrets.add(value)


def redact(text: str) -> str:
    """Hides the bot token, the GitHub token and the LLM key in text that goes to logs or to Telegram."""
    for secret in _secrets:
        text = text.replace(secret, "***")
    return text


class RedactFilter(logging.Filter):
    # aiohttp errors may carry a request URL, and the Bot API URL holds the token
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
            record.exc_text = None
            record.msg = f"{record.msg}\n{redact(exc_text)}"
        return True


def utf16_len(text: str) -> int:
    # Telegram counts message length in UTF-16 code units
    return len(text.encode("utf-16-le")) // 2


_TAG = re.compile(r"<[^>]+>")


def visible_len(html_text: str) -> int:
    """Length of an HTML message as Telegram counts it: after the tags are parsed out."""
    return utf16_len(html.unescape(_TAG.sub("", html_text)))
