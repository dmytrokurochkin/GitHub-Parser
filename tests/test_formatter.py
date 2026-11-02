from datetime import date

from core.utils import visible_len
from services.formatter import MAX_LEN, build_post, compact, fit_post, footer_link, grouped, period_dates
from services.periods import PERIODS
from tests.conftest import repo

DAY = PERIODS["day"]


def test_compact_numbers():
    assert compact(987) == "987"
    assert compact(1000) == "1k"
    assert compact(12400) == "12.4k"
    assert compact(106041) == "106k"
    assert compact(999_999) == "1M"
    assert compact(1_250_000) == "1.2M"


def test_grouped_uses_no_break_space():
    assert grouped(1145) == "1 145"
    assert grouped(12) == "12"


def test_dates_of_each_period():
    day = date(2026, 11, 1)
    assert period_dates(PERIODS["day"], day) == "01.11.2026"
    assert period_dates(PERIODS["week"], day) == "26.10 – 01.11.2026"
    assert period_dates(PERIODS["month"], day) == "Жовтень 2026"


def test_post_layout():
    repos = [repo("a/one", gained=1145, stars=106041, language="TypeScript"), repo("b/two", gained=10)]
    text = build_post(DAY, date(2026, 10, 30), repos, {"a/one": "Опис першого"}, {"a/one": None, "b/two": 2}, "@chan")
    lines = text.split("\n")
    assert lines[0] == "🔥 <b>Топ-2 репозиторіїв GitHub за день</b>"
    assert lines[1] == "📅 30.10.2026"
    assert '<b>1.</b> <a href="https://github.com/a/one">a/one</a> 🆕' in lines
    assert "⭐ 106k · +1 145 за день · TypeScript" in lines
    assert "Опис першого" in lines
    assert '<b>2.</b> <a href="https://github.com/b/two">b/two</a> 🔁 3-й день поспіль' in lines
    # Without an LLM text the GitHub description is used
    assert "About b/two" in lines
    assert lines[-2:] == ["📢 @chan", "#day"]


def test_repeat_that_skipped_the_last_post_has_no_mark():
    text = build_post(DAY, date(2026, 10, 30), [repo("a/one")], {}, {"a/one": 0}, "")
    assert '<a href="https://github.com/a/one">a/one</a>\n' in text


def test_search_fallback_has_no_gained_stars():
    text = build_post(DAY, date(2026, 10, 30), [repo("a/one", gained=None, stars=500)], {}, {}, "")
    assert "⭐ 500 · Python" in text
    assert "за день ·" not in text


def test_html_is_escaped():
    evil = repo("a/one", description="<script>alert(1)</script> & co", language="C++ <x>")
    text = build_post(DAY, date(2026, 10, 30), [evil], {}, {}, "")
    assert "<script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in text
    assert "C++ &lt;x&gt;" in text


def test_footer_links():
    assert footer_link("@chan") == "📢 @chan"
    assert footer_link("https://t.me/+abc") == '📢 <a href="https://t.me/+abc">Підписатися на канал</a>'
    assert footer_link("") == ""


def test_long_descriptions_are_cut_to_fit_one_message():
    repos = [repo(f"owner-with-long-name/repository-{i}") for i in range(25)]
    descriptions = {r.name: "дуже довгий опис " * 40 for r in repos}
    text = fit_post(DAY, date(2026, 10, 30), repos, descriptions, {}, "@chan")
    assert visible_len(text) <= MAX_LEN
    assert "…" in text
    assert text.endswith("#day")
