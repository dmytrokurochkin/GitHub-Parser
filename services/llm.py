import asyncio
import logging
import re
from datetime import timedelta

from database import Database
from services.github import GitHubClient
from services.trending import Repo

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ти пишеш короткі описи GitHub-репозиторіїв для українського Telegram-каналу про трендові проєкти. "
    "На вході назва, мова програмування, опис з GitHub і початок README. "
    "Відповідай одним реченням українською, до 150 символів: що це за проєкт і навіщо він потрібен. "
    "Не починай з назви репозиторію, без емодзі, лапок, markdown і хештегів. "
    "Назви технологій і продуктів лишай як є (Python, Docker, LLM)."
)
# How much of the README goes into the prompt
README_CHARS = 3000
# Longer answers are cut on a word boundary
MAX_CHARS = 220
# A repository that sits in the trends for weeks is described again once in a while
CACHE_AGE = timedelta(days=30)

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TAG = re.compile(r"<[^>]+>")
_BLANK = re.compile(r"\n\s*\n+")


def clean_readme(text: str) -> str:
    # Badges and HTML banners at the top of a README are noise for the model
    text = _TAG.sub("", _IMAGE.sub("", text))
    return _BLANK.sub("\n\n", text).strip()[:README_CHARS]


def clean_answer(text: str) -> str:
    """The first line of the model's answer without quotes and markdown, cut to MAX_CHARS."""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    line = line.strip("\"'«»“”*_#` ").strip()
    if len(line) > MAX_CHARS:
        line = line[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",.;:—- ") + "…"
    return line


class Describer:
    """One-line Ukrainian descriptions; the original GitHub description when the LLM is off or fails."""

    def __init__(self, llm, model: str, github: GitHubClient, db: Database, concurrency: int = 3):
        # llm: openai.AsyncOpenAI or None
        self.llm = llm
        self.model = model
        self.github = github
        self.db = db
        self._semaphore = asyncio.Semaphore(concurrency)

    async def describe_all(self, repos: list[Repo]) -> dict[str, str]:
        texts = await asyncio.gather(*(self.describe(repo) for repo in repos))
        return {repo.name: text for repo, text in zip(repos, texts)}

    async def describe(self, repo: Repo) -> str:
        if self.llm is None:
            return repo.description
        cached = await self.db.get_description(repo.name, CACHE_AGE)
        if cached:
            return cached
        async with self._semaphore:
            try:
                text = await self._ask(repo)
            except Exception as exc:
                log.warning("LLM description of %s failed: %s", repo.name, exc)
                return repo.description
        # A one-word or empty answer is worse than the English original
        if len(text) < 15:
            log.warning("LLM description of %s is too short: %r", repo.name, text)
            return repo.description
        await self.db.set_description(repo.name, text)
        return text

    async def _ask(self, repo: Repo) -> str:
        try:
            readme = await self.github.readme(repo.name)
        except Exception as exc:
            # The description alone is still enough for one sentence
            log.info("README of %s is not available: %s", repo.name, exc)
            readme = None
        parts = [
            f"Репозиторій: {repo.name}",
            f"Мова: {repo.language or 'невідома'}",
            f"Опис з GitHub: {repo.description or 'немає'}",
        ]
        if readme:
            parts.append(f"README (початок):\n{clean_readme(readme)}")
        response = await self.llm.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(parts)},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        return clean_answer(response.choices[0].message.content or "")
