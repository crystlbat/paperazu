import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from shared import db
from pdf_research import framework, library, notes

FW = framework.load()
STEP = FW.steps[2]  # text-only step: easy to fill


def _body(fields: dict[str, Any], gate: list[Any] | None = None, seconds: Any = 5) -> bytes:
    return json.dumps({"fields": fields, "gate": [False] * len(STEP.gate) if gate is None else gate,
                       "seconds": seconds}).encode()


def _fill(f: Any) -> Any:
    return "x" if f.type in ("text", "long", "date", "choice") else ([["a"]] if f.type == "rows" else ["a"])


@pytest.fixture
def paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "A Test Paper About Graphs", fontsize=20)
    return library.create(doc.tobytes(), "t.pdf")


def test_round_trip(paper: str) -> None:
    fid = STEP.fields[0].id
    notes.save(FW, paper, STEP.id, _body({fid: "hello"}, seconds=42))
    got = notes.load(FW, paper)
    assert got["steps"][STEP.id]["fields"] == {fid: "hello"}
    assert got["steps"][STEP.id]["seconds"] == 42
    assert got["total_steps"] == len(FW.steps)
    assert list(got["steps"]) == [STEP.id]


def test_merge_keeps_omitted_and_unknown_fields(paper: str) -> None:
    a, b = STEP.fields[0].id, STEP.fields[1].id
    notes.save(FW, paper, STEP.id, _body({a: "one", "old_field": "kept"}))
    notes.save(FW, paper, STEP.id, _body({b: "two"}))
    assert notes.load(FW, paper)["steps"][STEP.id]["fields"] == {a: "one", "old_field": "kept", b: "two"}


@pytest.mark.parametrize("step_id, body", [
    ("nope", _body({})),
    (STEP.id, _body({}, seconds=-1)),
    (STEP.id, _body({}, seconds=86401)),
    (STEP.id, _body({}, seconds=1.5)),
    (STEP.id, _body({}, gate=[1])),
    (STEP.id, b'{"fields": [], "gate": [], "seconds": 0}'),
    (STEP.id, _body({"f": 3})),
    (STEP.id, _body({"f": [[1]]})),
    (STEP.id, _body({"f": "x" * 210_000})),
    (STEP.id, b"not json"),
])
def test_bad_input_rejected(paper: str, step_id: str, body: bytes) -> None:
    with pytest.raises(notes.NoteError) as e:
        notes.save(FW, paper, step_id, body)
    assert e.value.errors
    assert notes.load(FW, paper)["steps"] == {}


def test_unknown_paper(paper: str) -> None:
    assert notes.save(FW, "missing", STEP.id, _body({})) is None
    assert notes.load(FW, "missing") is None


def test_state_transitions_and_steps_done(paper: str) -> None:
    assert notes.save(FW, paper, STEP.id, _body({}))["state"] == "empty"
    first = STEP.fields[0].id
    assert notes.save(FW, paper, STEP.id, _body({first: _fill(STEP.fields[0])}))["state"] == "partial"
    full = {f.id: _fill(f) for f in STEP.fields}
    assert notes.save(FW, paper, STEP.id, _body(full))["state"] == "partial"  # gate not ticked
    done = notes.save(FW, paper, STEP.id, _body(full, gate=[True] * len(STEP.gate)))
    assert (done["state"], done["steps_done"], done["total_steps"]) == ("done", 1, len(FW.steps))
    assert notes.load(FW, paper)["steps_done"] == 1


def test_search_finds_saved_notes(paper: str) -> None:
    assert library.list_papers(FW, q="zebrafish") == []
    notes.save(FW, paper, STEP.id, _body({STEP.fields[0].id: "the zebrafish result"}))
    assert [p["id"] for p in library.list_papers(FW, q="zebrafish")] == [paper]
