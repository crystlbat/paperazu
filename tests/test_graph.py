from array import array
from pathlib import Path

import pymupdf
import pytest

from workbench import db, graph, library
from workbench.settings import Settings

S = Settings(model_name="m", embed_model="fake-embed")
WORDS = ["privacy", "street", "graph", "protein"]


def _fake_embed(s: Settings, texts: list[str], model: str) -> list[array]:
    """Bag of four keywords, so similarity is predictable."""
    return [graph._unit([t.lower().count(w) + 0.01 for w in WORDS]) for t in texts]


def _pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 540, 760), text, fontsize=11)
    return doc.tobytes()


@pytest.fixture
def lib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    monkeypatch.setattr(graph, "embed", _fake_embed)
    db.init()
    return {k: library.create(_pdf(t), f"{k}.pdf") for k, t in {
        "a": "Street privacy. " * 40, "b": "Privacy on the street, street privacy again. " * 20,
        "c": "Protein folding protein graph. " * 30}.items()}


def test_split_keeps_pages_and_overlaps() -> None:
    parts = graph.split(["word " * 400, "", "short page with enough words to keep it here"])
    assert {n for n, _ in parts} == {1, 3}
    assert all(len(t) <= graph.CHUNK_CHARS for _, t in parts)
    assert len([p for p in parts if p[0] == 1]) >= 3


def test_index_and_suggested_links(lib: dict[str, str]) -> None:
    assert graph.index_missing(S) == {"model": "fake-embed", "indexed": 3}
    assert graph.index_missing(S)["indexed"] == 0  # already read
    g = graph.read(S)
    pairs = {frozenset((l["a"], l["b"])) for l in g["suggested"]}
    assert frozenset((lib["a"], lib["b"])) in pairs
    assert frozenset((lib["a"], lib["c"])) not in pairs
    assert sorted(g["indexed"]) == sorted(lib.values())


def test_search_ranks_by_meaning_and_auto_picks(lib: dict[str, str]) -> None:
    graph.index_missing(S)
    res = graph.search(S, "protein")["results"]
    assert res[0]["paper_id"] == lib["c"] and res[0]["pick"] is True
    assert res[0]["page"] == 1 and "rotein" in res[0]["snippet"]
    assert [r["pick"] for r in res[1:]] == [False, False]


def test_concepts_link_and_cascade(lib: dict[str, str]) -> None:
    cid = graph.add_concept("street privacy", [{"paper_id": lib["a"], "page": 1, "snippet": "x", "score": 0.9}])
    assert graph.read(S)["concepts"] == [{"id": cid, "label": "street privacy"}]
    library.delete(lib["a"])
    assert graph.read(S)["links"] == []  # deleting the paper drops its links
    assert graph.delete_concept(cid) and not graph.delete_concept(cid)
