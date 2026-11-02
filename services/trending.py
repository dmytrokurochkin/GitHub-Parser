import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class Repo:
    name: str  # owner/repo
    description: str
    language: str
    stars: int
    forks: int
    # Stars gained in the period; None when the source does not know it (search fallback)
    stars_gained: int | None

    @property
    def url(self) -> str:
        return f"https://github.com/{self.name}"


_NUMBER = re.compile(r"\d[\d,]*")
_GAINED = re.compile(r"\d[\d,]*\s+stars?\s+(today|this week|this month)")


def _number(text: str | None) -> int:
    match = _NUMBER.search(text or "")
    return int(match.group().replace(",", "")) if match else 0


def parse_trending(page: str) -> list[Repo]:
    """Repositories of github.com/trending in page order.

    There is no API for this page, so the parser leans on the few things that
    have stayed put for years: one article.Box-row per repository, the h2 link
    to /owner/repo, the /stargazers and /forks links and the "N stars today"
    text. Everything else is optional, and a row without the name is dropped.
    """
    soup = BeautifulSoup(page, "html.parser")
    repos = []
    for row in soup.select("article.Box-row"):
        link = row.select_one("h2 a[href]")
        if link is None:
            continue
        name = link["href"].strip("/")
        if name.count("/") != 1:
            continue
        description = row.select_one("p")
        language = row.select_one('[itemprop="programmingLanguage"]')
        stars = row.select_one('a[href$="/stargazers"]')
        forks = row.select_one('a[href$="/forks"]')
        gained = next((span for span in row.find_all("span") if _GAINED.search(span.get_text())), None)
        repos.append(Repo(
            name=name,
            description=" ".join(description.get_text().split()) if description else "",
            language=language.get_text(strip=True) if language else "",
            stars=_number(stars.get_text() if stars else None),
            forks=_number(forks.get_text() if forks else None),
            stars_gained=_number(gained.get_text()) if gained else None,
        ))
    return repos


def parse_search(data: dict) -> list[Repo]:
    """Repositories of a GitHub search API answer."""
    return [
        Repo(
            name=item["full_name"],
            description=" ".join((item.get("description") or "").split()),
            language=item.get("language") or "",
            stars=int(item.get("stargazers_count") or 0),
            forks=int(item.get("forks_count") or 0),
            stars_gained=None,
        )
        for item in data.get("items", [])
        if item.get("full_name")
    ]
