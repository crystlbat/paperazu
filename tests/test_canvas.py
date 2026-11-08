import pymupdf
import pytest
from fastapi.testclient import TestClient

from workbench import canvas, db, library, main


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
    return library.create(doc.tobytes(), "p.pdf")


def _three(pid, c):
    a = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "answer", "question": "Why?", "text": "Because.", "x": 10, "y": 20, "w": 240}).json()
    s = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "source", "text": "Gist.", "x": 10, "y": 90, "w": 240, "page": 1, "rect": [70, 90, 400, 110], "parent": a["id"]}).json()
    n = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "note", "entries": [{"who": "me", "text": "Mine."}], "x": 300, "y": 20, "w": 240}).json()
    return a, s, n


def test_cards_and_links_round_trip() -> None:
    pid = _paper(); c = TestClient(main.app)
    a, s, n = _three(pid, c)
    l = c.post(f"/papers/{pid}/canvas/links", json={"from_card": n["id"], "to_card": a["id"]}).json()
    got = c.get(f"/papers/{pid}/canvas").json()
    assert [x["id"] for x in got["cards"]] == [a["id"], s["id"], n["id"]] and got["links"] == [l]
    assert s["rect"] == [70, 90, 400, 110] and s["parent"] == a["id"] and n["entries"][0]["who"] == "me" and a["rect"] is None
    assert c.put(f"/papers/{pid}/canvas/cards/{n['id']}", json={"x": 50, "hidden": True}).json()["x"] == 50
    assert c.get(f"/papers/{pid}/canvas").json()["cards"][2]["hidden"] is True
    assert c.delete(f"/papers/{pid}/canvas/links/{l['id']}").json() == {"ok": True}


def test_deleting_a_card_keeps_its_children_and_drops_its_links() -> None:
    pid = _paper(); c = TestClient(main.app)
    a, s, n = _three(pid, c)
    c.post(f"/papers/{pid}/canvas/links", json={"from_card": n["id"], "to_card": a["id"]})
    assert c.delete(f"/papers/{pid}/canvas/cards/{a['id']}").json() == {"ok": True}
    got = c.get(f"/papers/{pid}/canvas").json()
    assert [x["id"] for x in got["cards"]] == [s["id"], n["id"]]
    assert got["cards"][0]["parent"] is None and got["links"] == []


def test_bad_cards_and_links_are_refused() -> None:
    pid = _paper(); c = TestClient(main.app)
    assert c.post(f"/papers/{pid}/canvas/cards", json={"kind": "poem", "x": 0, "y": 0, "w": 240}).status_code == 422
    assert c.post(f"/papers/{pid}/canvas/cards", json={"kind": "note", "x": 0, "y": 0, "w": 50}).status_code == 422
    a = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "note", "x": 0, "y": 0, "w": 240}).json()
    assert c.post(f"/papers/{pid}/canvas/links", json={"from_card": a["id"], "to_card": a["id"]}).status_code == 422
    assert c.post(f"/papers/{pid}/canvas/links", json={"from_card": a["id"], "to_card": 999}).status_code == 404
    assert c.get("/papers/nope/canvas").status_code == 404
    assert c.put(f"/papers/{pid}/canvas/cards/999", json={"x": 1}).status_code == 404


def test_chain_walks_up_the_parents() -> None:
    pid = _paper(); c = TestClient(main.app)
    ids = []
    for _ in range(3):
        ids.append(c.post(f"/papers/{pid}/canvas/cards", json={"kind": "answer", "x": 0, "y": 0, "w": 240, "parent": ids[-1] if ids else None}).json()["id"])
    assert [x["id"] for x in canvas.chain(pid, ids[2])] == [ids[2], ids[1], ids[0]]
    assert len(canvas.chain(pid, ids[2], most=2)) == 2
