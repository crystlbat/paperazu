import pymupdf
import pytest

import json

from shared import db
from pdf_research import guide, library, primer


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()


def test_stops_follow_the_headings_and_fall_back_to_a_page() -> None:
    doc = pymupdf.open()
    for head in ["Abstract", "1 Introduction", "2 Related Work", "3 Method", "4 Results", "5 Conclusion"]:
        page = doc.new_page()
        page.insert_text((72, 100), head, fontsize=16)
        page.insert_text((72, 140), "Body text that is long enough to read as a paragraph.", fontsize=10)
    pid = library.create(doc.tobytes(), "p.pdf")
    out = guide.stops(pid)
    by = {}
    for s in out:
        by.setdefault(s["step_id"], []).append((s["heading"], s["page"]))
    assert by["problem"] == [("Introduction", 2)]  # numbering dropped, page kept
    assert ("Conclusion", 6) in by["first"]
    assert all(s["page"] >= 1 for s in out) and out[0]["look_for"]
    assert guide.stops("nope") is None


def _paper() -> str:
    doc = pymupdf.open()
    for head in ["Abstract", "1 Introduction", "2 Method", "3 Results", "4 Conclusion", "References"]:
        page = doc.new_page()
        page.insert_text((72, 100), head, fontsize=16)
        page.insert_text((72, 140), "Body text that is long enough to read as a paragraph.", fontsize=10)
        if head == "2 Method":
            page.insert_text((72, 300), "Figure 1: Accuracy by group", fontsize=10)
    return library.create(doc.tobytes(), "p.pdf")


def test_stages_without_a_model_go_abstract_conclusion_figures_then_the_headings() -> None:
    out = guide.stages(_paper())
    assert [s["kind"] for s in out["stages"]] == ["abstract", "conclusion", "figures", "section", "section", "section"]
    assert out["source"] == "headings"
    st = out["stages"]
    assert (st[0]["page"], st[1]["page"], st[2]["page"]) == (1, 5, 3)
    assert st[2]["heading"] == "Figure 1" and "page 3" in st[2]["why"]
    assert [s["title"] for s in st[3:]] == ["Introduction", "Method", "Results"]  # page order, references left out
    assert all(s["why"] for s in st)
    assert guide.stages("nope") is None


def test_the_model_picks_the_other_sections_and_says_why(monkeypatch) -> None:
    seen = {}

    def fake(s, messages, schema=None, name="primer"):
        seen["list"] = messages[-1]["content"]
        return json.dumps({"stages": [{"n": 3, "why": "Check the numbers."}, {"n": 9, "why": "no such section"}, {"n": 1, "why": "See the problem."}]})

    monkeypatch.setattr(primer, "_complete", fake)
    out = guide.stages(_paper(), object())
    assert out["source"] == "model"
    assert [s["kind"] for s in out["stages"][:3]] == ["abstract", "conclusion", "figures"]  # the order does not depend on the model
    assert [(s["title"], s["why"]) for s in out["stages"][3:]] == [("Results", "Check the numbers."), ("Introduction", "See the problem.")]
    assert "References" not in seen["list"] and "Conclusion" not in seen["list"]  # only the paper's headings, never its text


def test_stages_fall_back_to_the_headings_when_the_model_fails(monkeypatch) -> None:
    def down(*a, **k):
        raise primer.PrimerError("Could not reach the model. Is Unsloth running?")

    monkeypatch.setattr(primer, "_complete", down)
    out = guide.stages(_paper(), object())
    assert out["source"] == "headings" and "Unsloth" in out["note"]
    assert [s["title"] for s in out["stages"]] == ["Abstract", "Conclusion", "Figures", "Introduction", "Method", "Results"]
    monkeypatch.setattr(primer, "_complete", lambda *a, **k: "not json")
    out = guide.stages(_paper(), object())
    assert out["source"] == "headings" and out["note"]


def test_every_figure_and_table_once_with_captions_over_mentions() -> None:
    pages = ["Intro.\nFig. 2. We plot the gap here.\nmore", "Figure 1: Accuracy by group", "Table 1: Results\nFigure 2: The gap",
             "Fig. 2 again in text", "Table 1. Here we measure it."]
    assert [(f["label"], f["page"], f["caption"]) for f in guide.figures(pages)] == [
        ("Figure 1", 2, "Accuracy by group"), ("Table 1", 3, "Results"), ("Figure 2", 3, "The gap")]
