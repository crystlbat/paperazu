import pymupdf
import pytest
from fastapi.testclient import TestClient

from workbench import db, export, library, main, marks


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()


def _paper() -> str:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "A first paragraph with enough words to count as text.", fontsize=10)
    page.insert_text((72, 300), "A second paragraph, far below the first one on the page.", fontsize=10)
    return library.create(doc.tobytes(), "p.pdf")


def test_blocks_are_the_paragraphs() -> None:
    pid = _paper()
    out = marks.blocks(pid, 1)
    assert out["w"] > 500 and len(out["blocks"]) == 2 and out["blocks"][0][1] < 100 < out["blocks"][1][1]
    assert marks.blocks(pid, 2) is None and marks.blocks("nope", 1) is None


def test_margin_notes_round_trip_and_export() -> None:
    pid = _paper()
    c = TestClient(main.app)
    r = c.post(f"/papers/{pid}/marks", json={"page": 1, "rect": [70, 90, 400, 110], "text": ""})
    mid = r.json()["id"]
    assert c.put(f"/papers/{pid}/marks/{mid}", json={"text": "Key claim. Check it."}).json() == {"ok": True}
    assert c.get(f"/papers/{pid}/marks").json()["marks"][0]["text"] == "Key claim. Check it."
    assert "- p. 1: Key claim. Check it." in export.markdown(pid)
    bad = c.post(f"/papers/{pid}/marks", json={"page": 1, "rect": [400, 90, 70, 110]})
    assert bad.status_code == 422
    assert c.delete(f"/papers/{pid}/marks/{mid}").json() == {"ok": True}
    assert c.delete(f"/papers/{pid}/marks/{mid}").status_code == 404
    library.delete(pid)
    assert c.get(f"/papers/{pid}/marks").status_code == 404
