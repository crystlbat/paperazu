from types import SimpleNamespace
from typing import Any

import pytest

from workbench import context, llm
from workbench.settings import Settings


def test_whole_paper_when_it_fits() -> None:
    assert context.fit_pages(["a" * 35] * 5, 1000, around=3) == [0, 1, 2, 3, 4]


def test_grows_outward_from_marked_page() -> None:
    pages = ["a" * 350] * 10  # about 101 tokens each
    assert context.fit_pages(pages, 310, around=5) == [4, 5, 6]
    assert context.fit_pages(pages, 310, around=0) == [0, 1, 2]


def test_marked_page_always_goes() -> None:
    assert context.fit_pages(["a" * 5000, "b"], 10, around=0) == [0]


class _Fake:
    def __init__(self, reply: str) -> None:
        self.sent: list[dict[str, str]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.reply = reply

    def _create(self, **kw: Any) -> Any:
        self.sent = kw["messages"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


def _run(monkeypatch: pytest.MonkeyPatch, reply: str, pages: list[str], **s: Any) -> tuple[dict[str, Any], _Fake]:
    fake = _Fake(reply)
    monkeypatch.setattr(llm, "client", lambda *a, **k: fake)
    return llm.explain(Settings(model_name="m", **s), "group privacy", "T", pages, 1), fake


def test_sends_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [f"page {i} text" for i in range(18)]
    out, fake = _run(monkeypatch, "<think>hmm</think> It means X.", pages)
    prompt = fake.sent[1]["content"]
    assert all(p in prompt for p in pages) and '"group privacy"' in prompt and "page 2" in prompt
    assert out == {"ok": True, "text": "It means X.", "pages": [1, 18], "whole": True, "total": 18, "seconds": out["seconds"]}


def test_trims_to_budget_around_marked_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = ["x" * 7000] * 20  # about 2000 tokens a page, 40k in all
    out, fake = _run(monkeypatch, "ok", pages, max_context_tokens=8192, max_output_tokens=1024)
    assert not out["whole"] and out["pages"][0] <= 2 <= out["pages"][1]
    assert context.tokens(fake.sent[1]["content"]) < 8192 - 1024


def test_unfinished_thinking_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    out, _ = _run(monkeypatch, "<think>still going", ["p"])
    assert out["ok"] is False and "Max output tokens" in out["error"]


def test_ask_sends_question_and_page(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake("Because of X (page 3).")
    monkeypatch.setattr(llm, "client", lambda *a, **k: fake)
    out = llm.ask(Settings(model_name="m"), "why does it fail?", "T", ["a", "b", "c"], 2)
    assert out["ok"] and out["text"] == "Because of X (page 3)."
    assert "why does it fail?" in fake.sent[1]["content"] and "page 3" in fake.sent[1]["content"]
    assert fake.sent[0]["content"] == llm.ASK_SYSTEM
