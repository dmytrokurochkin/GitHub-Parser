from datetime import timedelta
from types import SimpleNamespace

from services.llm import MAX_CHARS, Describer, clean_answer, clean_readme
from tests.conftest import repo


class FakeLLM:
    def __init__(self, answer: str = "Інструмент для швидкого пошуку файлів у терміналі.", error: Exception | None = None):
        self.answer = answer
        self.error = error
        self.prompts: list[list[dict]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.prompts.append(kwargs["messages"])
        if self.error is not None:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))])


def test_clean_answer():
    assert clean_answer('\n"**Бібліотека для графіків.**"\nДругий рядок') == "Бібліотека для графіків."
    assert clean_answer("«Сервіс»") == "Сервіс"
    long = clean_answer("слово " * 100)
    assert len(long) <= MAX_CHARS + 1 and long.endswith("…")


def test_clean_readme_drops_badges_and_html():
    text = clean_readme('<p align="center"><img src="x.png"></p>\n![badge](https://b)\n# Tool\n\n\n\nDoes things')
    assert "img" not in text and "badge" not in text
    assert text == "# Tool\n\nDoes things"


async def test_llm_off_gives_the_original(db, github):
    describer = Describer(None, "", github, db)
    assert await describer.describe(repo("a/a", description="Fast tool")) == "Fast tool"


async def test_description_is_cached(db, github):
    llm = FakeLLM()
    github.readmes["a/a"] = "# A\nREADME text"
    describer = Describer(llm, "model", github, db)
    first = await describer.describe(repo("a/a"))
    second = await describer.describe(repo("a/a"))
    assert first == second == "Інструмент для швидкого пошуку файлів у терміналі."
    assert len(llm.prompts) == 1
    assert "README text" in llm.prompts[0][1]["content"]


async def test_llm_error_falls_back(db, github):
    describer = Describer(FakeLLM(error=RuntimeError("502")), "model", github, db)
    assert await describer.describe(repo("a/a", description="Fast tool")) == "Fast tool"
    # A failure is not cached: next time the LLM is asked again
    assert await db.get_description("a/a", timedelta(days=30)) is None


async def test_too_short_answer_falls_back(db, github):
    describer = Describer(FakeLLM(answer="Так"), "model", github, db)
    assert await describer.describe(repo("a/a", description="Fast tool")) == "Fast tool"


async def test_describe_all(db, github):
    describer = Describer(FakeLLM(), "model", github, db)
    result = await describer.describe_all([repo("a/a"), repo("b/b")])
    assert set(result) == {"a/a", "b/b"}
