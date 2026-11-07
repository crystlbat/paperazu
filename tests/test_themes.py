import pymupdf
import pytest

from workbench import db, framework, library, themes


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()


def _pdf(wide: bool, toc: list | None = None) -> bytes:
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page(width=960 if wide else 612, height=540 if wide else 792)
        page.insert_text((72, 100), f"Some title words here {i}", fontsize=20)
    if toc:
        doc.set_toc(toc)
    return doc.tobytes()


def test_template_is_picked_on_upload() -> None:
    assert library.get(framework.load_all(), library.create(_pdf(False), "p.pdf"))["template"] == "paper"
    assert library.get(framework.load_all(), library.create(_pdf(True), "s.pdf"))["template"] == "slides"
    tall_deck = library.create(_pdf(False, [[1, "Slide 1", 1], [1, "Slide 2: Intro", 2], [1, "Slide 3", 3]]), "d.pdf")
    p = library.get(framework.load_all(), tall_deck)
    assert p["template"] == "slides" and len(p["progress"]) == len(framework.load_template("slides").steps)


def test_old_papers_get_a_template_once() -> None:
    pid = library.create(_pdf(True), "s.pdf")
    con = db.connect()
    with con:
        con.execute("UPDATE papers SET template = '' WHERE id = ?", (pid,))
    con.close()
    library.pick_missing_templates()
    assert library.get(framework.load_all(), pid)["template"] == "slides"


def test_themes_group_and_filter_papers() -> None:
    a, b = library.create(_pdf(False), "a.pdf"), library.create(_pdf(False), "b.pdf")
    ds = themes.create("Data  science")
    priv = themes.create("Privacy")
    assert ds["name"] == "Data science" and ds["color"] != priv["color"]
    with pytest.raises(ValueError):
        themes.create("data science")  # names are unique, ignoring case
    with pytest.raises(ValueError):
        themes.create("   ")
    assert themes.set_for_paper(a, [ds["id"], priv["id"], ds["id"]])
    assert not themes.set_for_paper(a, ["nope"])  # a bad id changes nothing
    assert not themes.set_for_paper("nope", [ds["id"]])
    fws = framework.load_all()
    assert set(library.get(fws, a)["themes"]) == {ds["id"], priv["id"]}
    assert [p["id"] for p in library.list_papers(fws, theme=priv["id"])] == [a]
    assert [p["id"] for p in library.list_papers(fws, theme="none")] == [b]
    assert {t["name"]: t["papers"] for t in themes.list_all()} == {"Data science": 1, "Privacy": 1}
    themes.delete(priv["id"])
    assert library.get(fws, a)["themes"] == [ds["id"]]


def test_plain_note_saves_and_is_searchable() -> None:
    from fastapi.testclient import TestClient
    from workbench.main import app
    pid = library.create(_pdf(False), "p.pdf")
    c = TestClient(app)
    assert c.get(f"/papers/{pid}/note").json() == {"text": ""}
    assert c.put(f"/papers/{pid}/note", json={"text": "zebracrossing idea"}).json() == {"ok": True}
    assert c.get(f"/papers/{pid}/note").json() == {"text": "zebracrossing idea"}
    assert [p["id"] for p in library.list_papers(framework.load_all(), "zebracrossing")] == [pid]
    assert c.put("/papers/nope/note", json={"text": "x"}).status_code == 404
    assert c.put(f"/papers/{pid}/note", json={"text": "x", "extra": 1}).status_code == 422
