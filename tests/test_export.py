import json
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest

from workbench import db, export, framework, library, llm, notes, primer
from workbench.settings import Settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    monkeypatch.setattr(primer, "_json_schema_ok", True)
    db.init()


class _Fake:
    def __init__(self, *replies: str) -> None:
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))])


def _paper() -> str:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Abstract\nBody.", fontsize=12)
    pid = library.create(doc.tobytes(), "p.pdf")
    con = db.connect()
    with con:
        con.execute("UPDATE papers SET title = 'Fast Tools', presenters = 'Ana' WHERE id = ?", (pid,))
    con.close()
    return pid


def _write(pid: str, step: str, fields: dict[str, Any]) -> None:
    notes.save(framework.load(), pid, step, json.dumps({"fields": fields, "gate": [False] * 3, "seconds": 0}).encode())


def test_markdown_has_tables_and_my_words() -> None:
    pid = _paper()
    _write(pid, "problem", {"wrong": "Old tools are slow."})
    _write(pid, "method", {"steps": [["text", "a | b", "c"], ["", "", ""]]})
    md = export.markdown(pid)
    assert md.startswith("# Fast Tools\n") and "- Presenters: Ana" in md
    assert "Old tools are slow." in md
    assert "| # | What goes in | What happens | What comes out |" in md and "| 1 | text | a \\| b | c |" in md
    assert "| 2 |" not in md  # the empty row is left out
    assert "_Not written yet._" in md
    assert export.markdown("nope") is None


def test_reflection_copies_notes_verbatim_and_model_only_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _paper()
    _write(pid, "problem", {"wrong": "Old tools are slow.", "matters": "Labs wait days."})
    reply = json.dumps({"sections": [{"section": 2, "note_ids": ["n1", "made_up", "n1"]}, {"section": 9, "note_ids": ["n2"]}]})
    fake = _Fake("oops", reply)  # one bad reply, then a retry
    monkeypatch.setattr(llm, "client", lambda *a, **k: fake)
    md = export.reflection(Settings(model_name="m"), pid)
    two = md.split("## 2.")[1].split("## 3.")[0]
    assert two.count("Old tools are slow.") == 1 and "made_up" not in md
    assert "## Notes not placed" in md and "Labs wait days." in md.split("## Notes not placed")[1]
    assert "- Presenters: Ana" in md and "## 5. Feedback for presenters" in md
    assert fake.calls[0]["response_format"]["json_schema"]["schema"]["properties"]["sections"]["items"]["properties"]["note_ids"]["items"]["enum"] == ["n1", "n2"]


def test_reflection_needs_notes_and_skips_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _paper()
    monkeypatch.setattr(llm, "client", lambda *a, **k: pytest.fail("the model was called"))
    with pytest.raises(primer.PrimerError, match="Write some notes"):
        export.reflection(Settings(model_name="m"), pid)
