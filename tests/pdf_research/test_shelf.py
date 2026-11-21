import json
import re
import sys
from array import array
from pathlib import Path

import pymupdf
import pytest

from shared import db, llm
from pdf_research import framework, graph, library, primer, shelf
from pdf_research.shelf import WORDS_ONLY
from shared.settings import Settings

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
    def boom(s: Settings, probe: bool = True) -> str:
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


@pytest.mark.parametrize("text", ["hi", "Hi!", "hello.", "hey...", "  Thanks! ", "ok", "okay.", "thank you", "Good morning, Dot!"])
def test_greeting_is_none_even_if_model_says_summarize(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    def fake(*a: object, **k: object) -> str:
        return '{"reply": "Keep this page open while I work.", "kind": "summarize", "papers": [{"p": "P1", "why": "x"}]}'
    monkeypatch.setattr(primer, "_complete", fake)
    out = shelf.ask(S, text, [])
    assert out["action"] == {"kind": "none", "paper_ids": []} and out["papers"] == []
    low = out["reply"].lower()
    assert "summar" not in low and "page open" not in low and "\u2014" not in out["reply"]


def test_greeting_is_none_offline(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*a: object, **k: object) -> str:
        raise primer.PrimerError("Could not reach the model.")
    monkeypatch.setattr(primer, "_complete", down)
    out = shelf.ask(S, "hi", [])
    assert out["action"]["kind"] == "none" and not out["action"]["paper_ids"] and not out.get("offline")


def test_real_summarize_request_still_summarizes(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*a: object, **k: object) -> str:
        return '{"reply": "I will summarize them.", "kind": "summarize", "papers": [{"p": "P1", "why": "asked"}]}'
    monkeypatch.setattr(primer, "_complete", fake)
    for q in ("Summarize my papers", "hi, summarize my papers", "what is dimensionality reduction?"):
        assert shelf._small_talk(q) is None
    out = shelf.ask(S, "Summarize my papers", [])
    assert out["action"]["kind"] == "summarize" and out["action"]["paper_ids"]


class _FakeChat:
    def __init__(self, text: str | None, seen: dict[str, object]) -> None:
        self.text, self.seen = text, seen

    def create(self, **kw: object) -> object:
        from types import SimpleNamespace as NS
        if self.text is None:
            from openai import APIError
            raise APIError("down", request=None, body=None)  # type: ignore[arg-type]
        self.seen.update(kw)
        return NS(choices=[NS(message=NS(content=self.text))])


def _fake_llm(monkeypatch: pytest.MonkeyPatch, text: str | None, seen: dict[str, object]) -> None:
    from types import SimpleNamespace as NS
    monkeypatch.setattr(llm, "client", lambda s, timeout=None, base_url=None: NS(chat=NS(completions=_FakeChat(text, seen))))
    monkeypatch.setattr(llm, "pick_model", lambda s: "m")

    def no_json(*a: object, **k: object) -> str:
        raise AssertionError("who-are-you must not go through the paper search")
    monkeypatch.setattr(primer, "_complete", no_json)


@pytest.mark.parametrize("q", ["who are you", "Who are you?", "what's your name?", "What can you do?", "hey, who is Dot"])
def test_who_is_dot_goes_to_the_model(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch, q: str) -> None:
    seen: dict[str, object] = {}
    _fake_llm(monkeypatch, "I am Dot. I help you read. Ask me about your papers.", seen)
    out = shelf.ask(S.model_copy(update={"dot_persona": "a pirate"}), q, [])
    assert out["reply"] == "I am Dot. I help you read. Ask me about your papers."
    assert out["action"] == {"kind": "none", "paper_ids": []} and out["papers"] == []
    system = seen["messages"][0]["content"]  # type: ignore[index]
    assert "reading companion" in system and "a pirate" in system


def test_who_is_dot_model_down(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_llm(monkeypatch, None, {})
    out = shelf.ask(S, "who are you", [])
    assert out["reply"] == "I am Dot. I live in this library with your papers. I can't reach the model right now."
    assert out["action"] == {"kind": "none", "paper_ids": []} and out["papers"] == []


def test_real_questions_are_not_about_dot() -> None:
    for q in ("Summarize my papers", "what is dimensionality reduction?", "who wrote the street privacy paper"):
        assert shelf._about_dot(S, q) is None


# ---------- Ask uses the indexed papers: search, concepts, words-only ----------

@pytest.fixture
def bias_lib(lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(sys.modules[__name__], "WORDS", WORDS + ["bias"])
    ids = {"bias": library.create(_pdf("Bias in hiring data. Bias and fairness, bias again. " * 30), "fairness.pdf")}
    graph.index_paper(S, ids["bias"], "fake-embed")  # the other papers were indexed before "bias" was a word; that is fine
    return {**lib, **ids}


def _model(monkeypatch: pytest.MonkeyPatch, **reply: object) -> None:
    body = {"reply": "", "kind": "find", "papers": [], **reply}
    monkeypatch.setattr(primer, "_complete", lambda *a, **k: json.dumps(body))


def test_find_on_bias_is_a_sentence_plus_the_matching_paper(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _model(monkeypatch, reply="P1", papers=[{"p": "P1", "why": ""}])  # a title echo from a weak model
    out = shelf.ask(S, "find out papers on bias", [])
    assert out["action"]["kind"] == "find" and out["action"]["paper_ids"][0] == bias_lib["bias"]
    assert out["papers"][0]["id"] == bias_lib["bias"] and out["papers"][0]["why"]
    assert '"bias"' in out["reply"] and len(out["reply"].split()) > 8 and not re.search(r"\bP\d+\b", out["reply"])
    assert WORDS_ONLY not in out["reply"]


def test_find_drops_unrelated_picks_and_ranks_matches_first(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    pids = [p["id"] for p in library.list_papers(framework.load_all())]
    _model(monkeypatch, reply="Two papers fit.", papers=[{"p": f"P{i + 1}", "why": "x"} for i in range(len(pids))])
    out = shelf.ask(S, "papers on bias", [])
    assert out["action"]["paper_ids"] == [bias_lib["bias"]]


def test_similar_concepts_uses_the_graph_and_says_when_none_fits(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    graph.add_concept("Statistical bias", [{"paper_id": bias_lib["bias"], "page": 1, "snippet": "bias", "score": 0.9}])
    graph.add_concept("Orphan idea about bias", [])  # no paper left: not offered
    _model(monkeypatch, reply="Some papers are alike.", papers=[])
    out = shelf.ask(S, "can you find similar concepts?", [{"q": "papers on bias", "a": "ok"}])
    assert [c["label"] for c in out["concepts"]] == ["Statistical bias"] and out["concepts"][0]["paper_ids"] == [bias_lib["bias"]]
    assert "Statistical bias" in out["reply"]
    none = shelf.ask(S, "does this match the idea of protein?", [])
    assert none["concepts"] == [] and "No concept in your graph is close" in none["reply"]


def test_concept_search_never_invents(bias_lib: dict[str, str]) -> None:
    assert graph.concept_search(S, "bias")["concepts"] == []  # the graph has none yet
    graph.add_concept("Statistical bias", [{"paper_id": bias_lib["bias"], "page": 1, "snippet": "b", "score": 0.9}])
    assert {c["label"] for c in graph.concept_search(S, "bias")["concepts"]} == {"Statistical bias"}


def test_question_about_papers_is_not_a_job(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _model(monkeypatch, reply="They talk about bias [S1].", kind="summarize", papers=[{"p": "P1", "why": "bias"}])
    out = shelf.ask(S, "what do these say about bias", [])
    assert out["action"]["kind"] in ("answer", "find")
    _model(monkeypatch, reply="I will summarize them.", kind="summarize", papers=[{"p": "P1", "why": "bias"}])
    assert shelf.ask(S, "summarize the bias papers", [])["action"]["kind"] == "summarize"


def test_search_by_words_when_the_embedding_model_is_down(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    def down(s: Settings) -> str:
        raise graph.GraphError("No embedding model found.")
    monkeypatch.setattr(graph, "embed_model", down)
    _model(monkeypatch, reply="P1", papers=[])
    out = shelf.ask(S, "find papers on bias", [])
    assert out["action"]["paper_ids"][0] == bias_lib["bias"]
    assert "matching words, not meaning" in out["reply"]


def test_chat_model_down_still_searches_and_says_so(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*a: object, **k: object) -> str:
        raise primer.PrimerError("Could not reach the model.")
    monkeypatch.setattr(primer, "_complete", down)
    out = shelf.ask(S, "papers on bias", [])
    assert out["offline"] and out["action"]["paper_ids"][0] == bias_lib["bias"] and "plain search" in out["reply"]


def test_greeting_still_has_no_papers_with_a_loaded_library(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _model(monkeypatch, reply="bias", kind="find", papers=[{"p": "P1", "why": "x"}])
    out = shelf.ask(S, "hi", [])
    assert out["papers"] == [] and out["action"] == {"kind": "none", "paper_ids": []} and "match" not in out["reply"]


def test_clean_swaps_labels_for_titles() -> None:
    alias = {"P1": {"id": "x1", "title": "Fairness under randomness: a study"}}
    out = shelf.clean({"reply": "P1: Fairness under randomness: a study fits.", "kind": "find", "papers": [{"p": "Fairness under randomness", "why": "x [S1]"}]}, alias)
    assert "P1" not in out["reply"] and out["reply"].startswith('"Fairness under randomness"')
    assert out["papers"] == [{"id": "x1", "why": "x"}]


def test_nothing_on_the_shelf_offers_the_web(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _model(monkeypatch, reply="No concept is close to that.", kind="none")
    monkeypatch.setattr(shelf, "passages", lambda *a, **k: [])  # the fake embedder calls every paper close
    out = shelf.ask(S, "who is abraham lincoln", [])
    assert out.get("web") == "who is abraham lincoln", out
    assert "web" in out["reply"] and not out["papers"]


def test_library_questions_never_go_to_the_web(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _model(monkeypatch, reply="You have a few.", kind="none")
    assert "web" not in shelf.ask(S, "how many papers do I have", [])


def test_stray_concept_reply_on_a_find_becomes_the_plain_summary(bias_lib: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _model(monkeypatch, reply="No concept is close to bias.", kind="find", papers=[{"p": "P1", "why": ""}])
    out = shelf.ask(S, "can you find bias", [])
    assert "concept" not in out["reply"].lower() and "matches" in out["reply"]
