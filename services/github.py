from datetime import date, timedelta

import aiohttp

from services.trending import Repo, parse_search, parse_trending

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "github-parser-bot",
}
# github.com/trending is a page for browsers, not an API
PAGE_HEADERS = {
    "Accept": "text/html",
    "User-Agent": "Mozilla/5.0 (compatible; github-parser-bot)",
}
# The LLM reads only the start of a README; some are megabytes of generated docs
README_BYTES = 64 * 1024


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, session: aiohttp.ClientSession, api_url: str, web_url: str, token: str | None = None):
        self.session = session
        self.api_url = api_url.rstrip("/")
        self.web_url = web_url.rstrip("/")
        self.token = token

    def _api_headers(self) -> dict[str, str]:
        headers = dict(API_HEADERS)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def trending(self, since: str) -> list[Repo]:
        """github.com/trending?since=daily|weekly|monthly, in page order."""
        async with self.session.get(f"{self.web_url}/trending", params={"since": since}, headers=PAGE_HEADERS) as resp:
            if resp.status != 200:
                raise GitHubError(f"trending page: HTTP {resp.status}")
            return parse_trending(await resp.text())

    async def new_popular(self, days: int, today: date, limit: int) -> list[Repo]:
        """The most starred repositories created in the last days.

        Fallback for a broken trending page: the API has no "stars gained in a
        period", so this is the closest it offers. The search API allows 10
        requests a minute without a token, one request per post is far below that.
        """
        since = today - timedelta(days=days)
        params = {"q": f"created:>={since.isoformat()}", "sort": "stars", "order": "desc", "per_page": str(limit)}
        async with self.session.get(f"{self.api_url}/search/repositories", params=params,
                                    headers=self._api_headers()) as resp:
            await self._check(resp, "search")
            return parse_search(await resp.json())

    async def readme(self, name: str) -> str | None:
        """The start of the README as raw text, None when the repository has none."""
        headers = {**self._api_headers(), "Accept": "application/vnd.github.raw+json"}
        async with self.session.get(f"{self.api_url}/repos/{name}/readme", headers=headers) as resp:
            if resp.status == 404:
                return None
            await self._check(resp, f"readme of {name}")
            return (await resp.content.read(README_BYTES)).decode("utf-8", errors="replace")

    @staticmethod
    async def _check(resp: aiohttp.ClientResponse, what: str) -> None:
        if resp.status == 200:
            return
        if resp.status in (403, 429) and resp.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubError(f"{what}: GitHub rate limit, set GITHUB_TOKEN")
        raise GitHubError(f"{what}: HTTP {resp.status}")
