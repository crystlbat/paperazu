from array import array
from pathlib import Path

import pymupdf
import pytest

from workbench import db, graph, library, primer, shelf
from workbench.settings import Settings

S = Settings(model_name="m", embed_model="fake-embed")
WORDS = ["privacy", "street", "graph", "protein"]


def _fake_embed(s: Settings, texts: list[str], model: str) -> list[array]:
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
    texts = {"a": "Street privacy. " * 40, "b": "Privacy on the street, street privacy again. " * 20,
             "c": "Protein folding protein graph. " * 30, "d": "Protein graph protein. " * 30,
             "e": "Street privacy street. " * 30}
    ids = {k: library.create(_pdf(t), f"{k}.pdf") for k, t in texts.items()}
    for pid in ids.values():
        graph.index_paper(S, pid, "fake-embed")
    return ids


def test_kmeans_small() -> None:
    assert shelf.kmeans({}, {}) == []
    v = {k: graph._unit([1.0, i]) for i, k in enumerate("xyz")}
    assert shelf.kmeans(v, {}) == [["x", "y", "z"]]


def test_kmeans_splits_topics(lib: dict[str, str]) -> None:
    con = db.connect()
    cents = shelf._centroids(con, "fake-embed")
    con.close()
    vecs, w = {p: v for p, (v, _) in cents.items()}, {p: n for p, (_, n) in cents.items()}
    groups = shelf.kmeans(vecs, w)
    assert groups == shelf.kmeans(vecs, w)
    where = {p: i for i, g in enumerate(groups) for p in g}
    assert where[lib["a"]] == where[lib["b"]] == where[lib["e"]]
    assert where[lib["c"]] == where[lib["d"]] != where[lib["a"]]


def test_map_groups_and_names(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(shelf, "_ask_names", lambda s, groups, titles: calls.append(1) or [f"N{i}" for i in range(len(groups))])
    out = shelf.library_map(S)
    assert sorted(p for g in out["groups"] for p in g["paper_ids"]) == sorted(lib.values())
    assert [g["name"] for g in out["groups"]] == ["N0", "N1"] and out["unread"] == []
    assert shelf.library_map(S)["groups"][0]["name"] == "N0" and len(calls) == 1


def test_map_without_embeddings(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(s: Settings) -> str:
        raise graph.GraphError("No embedding model.")
    monkeypatch.setattr(graph, "embed_model", boom)
    out = shelf.library_map(S)
    assert out["groups"] == [] and sorted(out["unread"]) == sorted(lib.values()) and out["reason"]


ALIAS = {"P1": {"id": "x1"}, "P2": {"id": "x2"}}


def test_clean_drops_unknown_and_bad_date() -> None:
    out = shelf.clean({"reply": "Ok", "kind": "find", "papers": [{"p": "P9", "why": "no"}, {"p": "p2", "why": "a b"}]}, ALIAS)
    assert out["action"] == {"kind": "find", "paper_ids": ["x2"]} and out["papers"] == [{"id": "x2", "why": "a b"}]
    out = shelf.clean({"reply": "Ok", "kind": "set_date", "papers": [{"p": "P1", "why": ""}], "date": "next tuesday"}, ALIAS)
    assert out["action"]["kind"] == "none" and "date" in out["reply"].lower()
    out = shelf.clean({"reply": "Ok", "kind": "set_date", "papers": [{"p": "P1", "why": ""}], "date": "2026-11-12"}, ALIAS)
    assert out["action"] == {"kind": "set_date", "paper_ids": ["x1"], "date": "2026-11-12"}


def test_clean_job_without_papers_is_none() -> None:
    out = shelf.clean({"reply": "Deleting", "kind": "delete", "papers": []}, ALIAS)
    assert out["action"] == {"kind": "none", "paper_ids": []}
    assert shelf.clean({"reply": "x", "kind": "explode", "papers": []}, ALIAS)["action"]["kind"] == "none"


def test_ask_offline_falls_back_to_find(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*a: object, **k: object) -> str:
        raise primer.PrimerError("Could not reach the model.")
    monkeypatch.setattr(primer, "_complete", down)
    out = shelf.ask(S, "papers about protein", [])
    assert out["offline"] and out["action"]["kind"] == "find" and out["action"]["paper_ids"]
    assert set(out["action"]["paper_ids"][:2]) == {lib["c"], lib["d"]}


def test_passages_two_levels(lib: dict[str, str]) -> None:
    out = shelf.passages(S, "protein")
    assert out and {x["paper_id"] for x in out} <= {lib["c"], lib["d"]}
    assert all(x["score"] >= out[-1]["score"] for x in out) and all(len(x["text"]) <= shelf.PASSAGE_CHARS for x in out)


def test_clean_answer_keeps_real_citations() -> None:
    srcs = {"S1": {"paper_id": "x1", "page": 3, "text": "aaa"}, "S2": {"paper_id": "x2", "page": 5, "text": "bbb"}}
    out = shelf.clean({"reply": "Noise hurts small groups [S2]. Seeds matter [S1, S9].", "kind": "answer", "papers": [], "sources": ["S2", "S7"]},
                      ALIAS, srcs)
    assert out["reply"] == "Noise hurts small groups [1]. Seeds matter [2]."
    assert [(s["n"], s["paper_id"], s["page"]) for s in out["sources"]] == [(1, "x2", 5), (2, "x1", 3)]
    assert out["action"] == {"kind": "answer", "paper_ids": ["x2", "x1"]}


def test_ask_sends_passages_and_persona(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake(s: Settings, msgs: list[dict[str, str]], *a: object) -> str:
        seen["system"], seen["user"] = msgs[0]["content"], msgs[-1]["content"]
        return '{"reply": "Folding [S1].", "kind": "answer", "papers": [], "sources": ["S1"]}'
    monkeypatch.setattr(primer, "_complete", fake)
    out = shelf.ask(S.model_copy(update={"dot_persona": "a pirate"}), "what about protein?", [])
    assert "Passages:" in seen["user"] and "S1 (P" in seen["user"] and "a pirate" in seen["system"]
    assert out["reply"] == "Folding [1]." and out["sources"][0]["paper_id"] in (lib["c"], lib["d"])
