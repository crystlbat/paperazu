import pymupdf
import pytest

from workbench import db, guide, library


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
