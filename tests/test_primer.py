import json
import re
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from openai import APIStatusError

from workbench import db, framework, library, llm, primer
from workbench.settings import Settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    monkeypatch.setattr(primer, "_json_schema_ok", True)
    primer._jobs.clear()
    db.init()


def _paper() -> str:
    doc = pymupdf.open()
    for i, head in enumerate(["Abstract", "1 Introduction", "2 Related Work", "3 Method", "4 Results", "5 Conclusion", "References"]):
        doc.new_page().insert_text((72, 100), f"{head}\nBody text for part {i}.", fontsize=12)
    return library.create(doc.tobytes(), "p.pdf")


def _good(step_id: str) -> str:
    st = next(s for s in framework.load().steps if s.id == step_id)
    return json.dumps({"step_id": step_id, "where_to_look": "Read [p. 2].",
                       "fields": [{"field_id": f.id, "summary": f"About {f.id} [p. 2].", "pages": [2]} for f in st.fields]})


class _Fake:
    """Answers each step with valid JSON unless `replies` says otherwise; records the calls."""
    def __init__(self, replies: list[Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.replies = replies or []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        reply = self.replies.pop(0) if self.replies else _good(re.search(r'step_id "(\w+)"', kw["messages"][1]["content"])[1])
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def _use(monkeypatch: pytest.MonkeyPatch, fake: _Fake) -> None:
    monkeypatch.setattr(llm, "client", lambda *a, **k: fake)
    monkeypatch.setattr(primer, "get_all", lambda: Settings(model_name="m"))


def _step(sid: str) -> framework.Step:
    return next(s for s in framework.load().steps if s.id == sid)


def test_steps_one_to_seven_that_read_the_paper() -> None:
    assert all(1 <= s.n <= 7 and not s.paper_hidden for s in primer.steps_for(framework.load()))
    slides = [s.id for s in primer.steps_for(framework.load_template("slides"))]
    assert "quiz" not in slides and "unclear" not in slides and "map" in slides


def test_parse_keeps_only_the_steps_fields() -> None:
    raw = json.dumps({"step_id": "x", "where_to_look": "", "fields": [
        {"field_id": "wrong", "summary": "Old tools fail [p. 1].", "pages": [1]},
        {"field_id": "made_up", "summary": "no", "pages": []}]})
    out = primer.parse("```json\n" + raw + "\n```", _step("problem"))
    assert out.step_id == "problem" and [f.field_id for f in out.fields] == ["wrong"]
    with pytest.raises(ValueError):
        primer.parse(json.dumps({"step_id": "problem", "where_to_look": "", "fields": [{"field_id": "nope", "summary": "x"}]}), _step("problem"))


def test_retries_once_with_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake(["not json", _good("problem")])
    _use(monkeypatch, fake)
    out = primer.make_step(Settings(model_name="m"), _step("problem"), "T", ["page one"], [])
    assert out.fields and len(fake.calls) == 2 and "not valid" in fake.calls[1]["messages"][-1]["content"]
    assert fake.calls[0]["response_format"]["type"] == "json_schema"


def test_two_bad_answers_give_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _Fake(["nope", "{}"]))
    with pytest.raises(primer.PrimerError, match="did not return a valid answer"):
        primer.make_step(Settings(model_name="m"), _step("problem"), "T", ["p"], [])


def test_falls_back_to_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    refused = APIStatusError.__new__(APIStatusError)  # what the SDK raises when the server refuses json_schema
    refused.status_code, refused.message = 400, "no schema"
    fake = _Fake([refused, _good("problem")])
    _use(monkeypatch, fake)
    primer.make_step(Settings(model_name="m"), _step("problem"), "T", ["p"], [])
    assert fake.calls[1]["response_format"] == {"type": "json_object"}


def test_references_are_dropped_and_pages_are_marked() -> None:
    pages = ["intro", "method", "results", "end\nReferences\n[1] A. Author"]
    assert primer.drop_references(pages) == ["intro", "method", "results", "end\n"]
    assert primer.labelled(pages, [0, 2]).startswith("[p. 1]\nintro\n\n[p. 3]")


def test_long_papers_send_the_steps_own_pages() -> None:
    heads = [(1, "1 Introduction", 1), (1, "2 Related Work", 3), (1, "3 Method", 4), (1, "4 Results", 6)]
    assert primer.step_pages(_step("gap"), 8, heads) == [2]
    assert primer.step_pages(_step("method"), 8, heads) == [3, 4]
    pages = ["x" * 4000] * 8  # about 9000 tokens, more than 60% of a 8192-token budget
    text = primer.step_context(_step("method"), pages, heads, Settings(max_context_tokens=8192, max_output_tokens=512), "")
    assert re.findall(r"\[p\. (\d+)\]", text) == ["4", "5"]


def test_job_saves_every_step_then_marks_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _paper()
    fake = _Fake()
    _use(monkeypatch, fake)
    primer._jobs[pid] = {"state": "making", "done": 0, "total": 0, "step": "", "error": ""}
    primer._run(pid)
    out = primer.load(pid)
    ids = [s.id for s in primer.steps_for(framework.load())]
    assert out["progress"]["state"] == "ready" and sorted(out["steps"]) == sorted(ids)
    assert library.get(framework.load_all(), pid)["primer_status"] == "ready"
    assert "References" not in "".join(c["messages"][1]["content"] for c in fake.calls)


def test_a_failed_run_keeps_the_old_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _paper()
    _use(monkeypatch, _Fake())
    primer._jobs[pid] = {"state": "making"}
    primer._run(pid)
    _use(monkeypatch, _Fake([_good("first"), "bad", "bad"]))
    primer._jobs[pid] = {"state": "making"}
    primer._run(pid)
    out = primer.load(pid)
    assert out["progress"]["state"] == "failed" and "Try again" in out["progress"]["error"]
    assert len(out["steps"]) == len(primer.steps_for(framework.load()))  # the first run's summary is still there


def test_one_field_step_split_into_rows_is_joined() -> None:
    step = next(x for x in framework.load_template("slides").steps if x.id == "ideas")
    raw = json.dumps({"step_id": "ideas", "where_to_look": "", "fields": [
        {"field_id": "1", "summary": "Collect data [p. 5].", "pages": [5]}, {"field_id": "2", "summary": "Clean it [p. 6].", "pages": [6]}]})
    out = primer.parse(raw, step)
    assert [(f.field_id, f.summary, f.pages) for f in out.fields] == [("ideas", "Collect data [p. 5]. Clean it [p. 6].", [5, 6])]
    assert primer.schema_for(step)["properties"]["fields"]["items"]["properties"]["field_id"]["enum"] == ["ideas"]


def test_printed_page_numbers_map_to_pdf_pages() -> None:
    pages = [f"Title line\nBody text {i}.\n{1788 + i}" for i in range(1, 13)]  # a journal paper: p. 1789 to 1800
    assert primer.printed_offset(pages) == 1788
    assert primer.printed_offset(["Slide 1\nHello", "Slide 2\nMore"]) == 0
    data = {"fields": [{"field_id": "a", "summary": "See [p. 1791] and p. 1797, page 2, in 2023 for $1790.", "pages": [1791, 2, 9999]}],
            "where_to_look": "1797"}
    out = primer.fix_pages(data, 12, 1788)
    assert out["fields"][0]["pages"] == [3, 2]  # 9999 is no page at all, so it goes
    assert out["fields"][0]["summary"] == "See [p. 3] and p. 9, page 2, in 2023 for $1790."
    assert out["where_to_look"] == "p. 9"
