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


def test_formula_pieces_join_into_one_box() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "A paragraph with enough words to count as text.", fontsize=10)
    for x, piece in [(150, "f* <- argmin"), (230, "sum"), (262, "L(f(x), y)   (1)")]:  # one equation, three blocks
        page.insert_text((x, 160), piece, fontsize=10)
    pid = library.create(doc.tobytes(), "f.pdf")
    boxes = marks.blocks(pid, 1)["blocks"]
    assert len(boxes) == 2 and boxes[1][0] < 151 and boxes[1][2] > 300
    text, png = marks.boxed(pid, 1, boxes[1])
    assert "argmin" in text and "(1)" in text and png.startswith("data:image/png;base64,")


def test_box_grows_and_ai_sees_a_picture(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import openai

    class NoImages(openai.APIStatusError):  # what a text-only server sends back
        def __init__(self) -> None:
            self.status_code, self.message = 400, "image input is not supported"

    from workbench import llm
    calls = []

    def create(**kw):
        calls.append(kw)
        if len(calls) == 1 and isinstance(kw["messages"][1]["content"], list):
            raise NoImages()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="It is the training objective."))])
    monkeypatch.setattr(llm, "pick_model", lambda s: "m")
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    pid = _paper()
    c = TestClient(main.app)
    mid = c.post(f"/papers/{pid}/marks", json={"page": 1, "rect": [70, 90, 400, 110]}).json()["id"]
    assert c.put(f"/papers/{pid}/marks/{mid}", json={"text": "", "rect": [70, 90, 400, 310]}).json() == {"ok": True}
    assert c.get(f"/papers/{pid}/marks").json()["marks"][0]["rect"] == [70, 90, 400, 310]
    r = c.post(f"/papers/{pid}/marks/{mid}/ask", json={"question": "What is this?"}).json()
    assert r["ok"] and r["text"] == "It is the training objective."
    first, second = calls[0]["messages"][1]["content"], calls[1]["messages"][1]["content"]
    assert first[1]["image_url"]["url"].startswith("data:image/png") and "second paragraph" in first[0]["text"]
    assert isinstance(second, str)  # a text-only model gets asked again without the picture
    assert c.post(f"/papers/{pid}/marks/999/ask", json={"question": "x"}).status_code == 404


def test_explain_sends_a_picture_of_the_marked_area(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from workbench import llm
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="A claim."))])
    monkeypatch.setattr(llm, "pick_model", lambda s: "m")
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    pid = _paper()
    c = TestClient(main.app)
    assert c.post(f"/papers/{pid}/explain", json={"words": "first paragraph", "page": 1, "rect": [70, 88, 300, 106]}).json()["ok"]
    assert c.post(f"/papers/{pid}/explain", json={"words": "first paragraph", "page": 1}).json()["ok"]
    assert calls[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png")
    assert isinstance(calls[1]["messages"][1]["content"], str)
    assert c.post(f"/papers/{pid}/explain", json={"words": "x", "rect": [300, 88, 70, 106]}).status_code == 422


def test_paragraphs_have_text_in_block_order() -> None:
    pid = _paper()
    paras = marks.paragraphs(pid, 1)
    assert [r for r, _ in paras] == marks.blocks(pid, 1)["blocks"]
    assert "first paragraph" in paras[0][1] and "second paragraph" in paras[1][1]
    assert marks.paragraphs(pid, 2) is None


def test_a_page_with_no_text_has_no_paragraphs() -> None:
    doc = pymupdf.open()
    doc.new_page()
    pid = library.create(doc.tobytes(), "blank.pdf")
    assert marks.paragraphs(pid, 1) == []


def test_highlights_round_trip() -> None:
    pid = _paper()
    c = TestClient(main.app)
    h = c.post(f"/papers/{pid}/highlights", json={"page": 1, "text": "first paragraph", "rects": [[90, 92, 160, 102]]}).json()
    assert h["kind"] == "me" and c.get(f"/papers/{pid}/highlights").json()["highlights"] == [h]
    assert c.post(f"/papers/{pid}/highlights", json={"page": 1, "rects": [[400, 90, 70, 110]]}).status_code == 422
    assert c.post(f"/papers/{pid}/highlights", json={"page": 1, "rects": []}).status_code == 422
    d = c.post(f"/papers/{pid}/highlights", json={"page": 1, "kind": "dot", "rects": [[90, 92, 160, 102]]}).json()
    assert c.put(f"/papers/{pid}/highlights/{d['id']}", json={"kind": "me"}).json()["kind"] == "me"
    assert c.delete(f"/papers/{pid}/highlights/{h['id']}").json() == {"ok": True}
    assert c.delete(f"/papers/{pid}/highlights/{h['id']}").status_code == 404
    assert c.get("/papers/nope/highlights").status_code == 404
