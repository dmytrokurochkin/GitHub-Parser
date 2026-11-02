from services.trending import parse_search, parse_trending
from tests.conftest import FIXTURES


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_daily_page():
    repos = parse_trending(load("trending_daily.html"))
    assert len(repos) == 15
    first = repos[0]
    assert first.name == "thedotmack/claude-mem"
    assert first.url == "https://github.com/thedotmack/claude-mem"
    assert first.language == "TypeScript"
    assert first.stars == 106041
    assert first.forks == 9340
    assert first.stars_gained == 1145
    assert first.description.startswith("Persistent Context Across Sessions")


def test_weekly_page_counts_stars_this_week():
    repos = parse_trending(load("trending_weekly.html"))
    assert repos[0].name == "cloudflare/security-audit-skill"
    assert repos[0].stars_gained == 14320
    assert all(repo.stars_gained is not None for repo in repos)


def test_optional_fields_may_be_missing():
    repos = parse_trending(load("trending_daily.html"))
    by_name = {repo.name: repo for repo in repos}
    # No description on GitHub, no language detected
    assert by_name["pingdotgg/t3code"].description == ""
    assert by_name["togg53192-cmd/jailbreaks"].language == ""


def test_changed_layout_gives_nothing():
    assert parse_trending("<html><body><div class='Box'>new layout</div></body></html>") == []


def test_row_without_repository_link_is_dropped():
    page = """
    <article class="Box-row"><h2><a href="/someone">x</a></h2></article>
    <article class="Box-row"><p>no heading at all</p></article>
    <article class="Box-row"><h2><a href="/a/b">a / b</a></h2>
      <a href="/a/b/stargazers">1,234</a><span>12 stars today</span></article>
    """
    repos = parse_trending(page)
    assert [repo.name for repo in repos] == ["a/b"]
    assert repos[0].stars == 1234
    assert repos[0].stars_gained == 12


def test_search_answer():
    data = {
        "items": [
            {"full_name": "a/b", "description": "  Some\n tool ", "language": "Go",
             "stargazers_count": 500, "forks_count": 7},
            {"full_name": "c/d", "description": None, "language": None,
             "stargazers_count": 3, "forks_count": 0},
        ]
    }
    repos = parse_search(data)
    assert [repo.name for repo in repos] == ["a/b", "c/d"]
    assert repos[0].description == "Some tool"
    assert repos[0].stars_gained is None
    assert repos[1].description == "" and repos[1].language == ""
