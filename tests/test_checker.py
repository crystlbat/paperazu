import json
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest

from workbench import checker, db, framework, library, llm, notes, primer
from workbench.settings import Settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    monkeypatch.setattr(primer, "_json_schema_ok", True)
    db.init()


def _paper() -> str:
    doc = pymupdf.open()
    for head in ["Abstract", "1 Introduction", "2 Method", "References"]:
        doc.new_page().insert_text((72, 100), f"{head}\nBody text.", fontsize=12)
    return library.create(doc.tobytes(), "p.pdf")


def _step(sid: str) -> framework.Step:
    return next(s for s in framework.load().steps if s.id == sid)


class _Fake:
    def __init__(self, *replies: str) -> None:
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))])


def _reply(**verdicts: str) -> str:
    return json.dumps({"step_id": "problem", "overall": "Good start.", "fields": [
        {"field_id": k, "verdict": v, "hint": "Look again at the second paragraph [p. 2].", "pages": [2]} for k, v in verdicts.items()]})


def _write(pid: str, fields: dict[str, Any]) -> None:
    notes.save(framework.load(), pid, "problem", json.dumps({"fields": fields, "gate": [False], "seconds": 0}).encode())


def test_rows_become_lines_and_empty_fields_are_marked() -> None:
    assert checker.note_text([["BERT", "pretrained", ""], ["", "", ""]]) == "BERT | pretrained | "
    text = checker.notes_block(_step("problem"), {"wrong": "Old tools are slow."})
    assert "wrong (What is wrong now?):\nOld tools are slow." in text and "hard (Why is it hard to solve?):\n(empty)" in text


def test_parse_fills_gaps_and_trusts_no_praise_for_empty_notes() -> None:
    out = checker.parse(_reply(wrong="correct", matters="correct", made_up="wrong"), _step("problem"), {"wrong": "x"}, 40)
    v = {f.field_id: f.verdict for f in out.fields}
    assert v == {"wrong": "correct", "matters": "missing", "hurts": "missing", "hard": "missing", "contrib": "missing"}
    assert out.fields[0].hint == ""  # no hint on a correct note


def test_check_saves_history_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _paper()
    _write(pid, {"wrong": "Old tools are slow.", "contrib": [["a"]]})
    fake = _Fake(_reply(wrong="partial"), "not json", _reply(wrong="correct"))
    monkeypatch.setattr(llm, "client", lambda *a, **k: fake)
    s = Settings(model_name="m")
    first = checker.check(s, pid, "problem")
    second = checker.check(s, pid, "problem")  # needs one retry
    assert first["fields"][0]["verdict"] == "partial" and second["fields"][0]["verdict"] == "correct"
    assert "Old tools are slow." in fake.calls[0]["messages"][1]["content"]
    assert fake.calls[0]["response_format"]["json_schema"]["schema"]["properties"]["fields"]["items"]["properties"]["field_id"]["enum"][0] == "wrong"
    hist = checker.history(pid)["problem"]
    assert [h["id"] for h in hist] == [second["id"], first["id"]]


def test_no_notes_no_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _paper()
    monkeypatch.setattr(llm, "client", lambda *a, **k: pytest.fail("the model was called"))
    with pytest.raises(checker.CheckError, match="Write some notes"):
        checker.check(Settings(model_name="m"), pid, "problem")
    with pytest.raises(KeyError):
        checker.check(Settings(model_name="m"), pid, "card")  # the paper card is not checked


def test_cut_hints_end_on_a_full_sentence() -> None:
    assert checker._tidy("Check p. 1 for the title. The note answers a different question (about chess vs") == "Check p. 1 for the title."
    assert checker._tidy("Fine as it is.") == "Fine as it is."
