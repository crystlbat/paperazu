from types import SimpleNamespace
from typing import Any

import pytest
from openai import APIStatusError

from pdf_research import jobs, primer
from shared import llm
from shared.settings import Settings


class TooLong(APIStatusError):
    def __init__(self, sent: int, size: int) -> None:
        self.status_code, self.body = 400, None
        self.message = f"Message too long: {sent} tokens exceeds the {size}-token context window."


def _server(monkeypatch: pytest.MonkeyPatch, size: int) -> list[dict[str, Any]]:
    """A fake server with a `size`-token window that counts 3 characters a token."""
    calls: list[dict[str, Any]] = []

    def create(**kw: Any) -> Any:
        calls.append(kw)
        used = sum(len(llm._text(m)) for m in kw["messages"]) // 3
        if used + kw["max_tokens"] > size:
            raise TooLong(used, size)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": 1}'), finish_reason="stop")])

    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return calls


def test_a_creature_fits_a_smaller_window_and_remembers_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _server(monkeypatch, 2048)
    s = Settings(model_name="m")
    msgs = [{"role": "system", "content": "Follow it."}, {"role": "user", "content": "Instruction: sum up\n\n" + "word " * 6000 + "\nEND"}]
    assert jobs.complete(s, msgs) == '{"ok": 1}'
    assert len(calls) == 2 and llm.window(s) == 2048
    sent = calls[1]["messages"][1]["content"]
    assert sent.startswith("Instruction: sum up") and sent.endswith("END")  # the middle goes, the ends stay
    jobs.complete(s, msgs)
    assert len(calls) == 3  # the next call is cut before it is sent


def test_json_calls_get_the_same_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(primer, "_json_schema_ok", True)
    calls = _server(monkeypatch, 1024)
    assert primer._complete(Settings(model_name="m"), [{"role": "user", "content": "x " * 5000}]) == '{"ok": 1}'
    assert primer._json_schema_ok is True and len(calls) == 2  # a long prompt is not a schema problem


def test_cut_off_json_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": "hal'), finish_reason="length")])
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: reply))))
    with pytest.raises(llm.ModelError, match="Max output tokens"):
        llm.chat(Settings(model_name="m"), [{"role": "user", "content": "hi"}], response_format={"type": "json_object"})
    assert llm.chat(Settings(model_name="m"), [{"role": "user", "content": "hi"}]) == '{"a": "hal'  # prose: keep what came


def test_pick_model_prefers_a_loaded_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = [SimpleNamespace(id="ollama/nomic-embed-text", loaded=True), SimpleNamespace(id="a", loaded=False),
              SimpleNamespace(id="b", loaded=True)]
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(models=SimpleNamespace(list=lambda: listed)))
    assert llm.pick_model(Settings()) == "b"
