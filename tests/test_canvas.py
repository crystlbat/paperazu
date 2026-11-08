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
    page.insert_text((72, 300), "A second paragraph, far below the first one on the page.", fontsize=10)
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


# ---------- ask with sources ----------

def _fake_model(monkeypatch, replies, prompts=None):
    from types import SimpleNamespace

    from workbench import graph, llm

    def create(**kw):
        if prompts is not None:
            prompts.append(kw["messages"][-1]["content"])
        if isinstance(replies, Exception):
            raise replies
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=replies.pop(0)))])
    monkeypatch.setattr(llm, "pick_model", lambda s: "m")
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(graph, "pages_for", lambda *a, **k: [])


def _ask(c, pid, **kw):
    return c.post(f"/papers/{pid}/canvas/ask", json={"question": "Why?", "page": 1, "at": [20, 20], **kw}).json()


def test_ask_saves_sources_that_point_at_real_paragraphs(monkeypatch) -> None:
    from workbench import marks
    _fake_model(monkeypatch, ['{"answer": "Noise on small groups.", "sources": [{"block": "p1-b1", "gist": "Second paragraph says it."}, {"block": "p9-b9", "gist": "Made up."}]}'])
    pid, c = _paper(), TestClient(main.app)
    r = _ask(c, pid)
    assert r["ok"] and r["answer"]["question"] == "Why?" and len(r["sources"]) == 1
    assert r["sources"][0]["rect"] == marks.blocks(pid, 1)["blocks"][1] and r["sources"][0]["parent"] == r["answer"]["id"]
    assert len(c.get(f"/papers/{pid}/canvas").json()["cards"]) == 2


def test_broken_json_is_asked_again_then_falls_back(monkeypatch) -> None:
    _fake_model(monkeypatch, ["not json", "still not json", "A plain answer."])
    pid, c = _paper(), TestClient(main.app)
    r = _ask(c, pid)
    assert r["ok"] and r["sources"] == [] and r["answer"]["text"].endswith("No exact lines found.")


def test_no_embedding_model_falls_back_to_nearby_pages(monkeypatch) -> None:
    from workbench import graph, settings

    def boom(s):
        raise graph.GraphError("none")
    monkeypatch.setattr(graph, "embed_model", boom)
    pid = _paper()
    assert graph.pages_for(settings.get_all(), pid, "q") == []


def test_a_page_with_no_text_still_gets_an_answer(monkeypatch) -> None:
    import pymupdf

    from workbench import library
    _fake_model(monkeypatch, ["A plain answer."])
    doc = pymupdf.open(); doc.new_page()
    pid, c = library.create(doc.tobytes(), "blank.pdf"), TestClient(main.app)
    r = _ask(c, pid)
    assert r["ok"] and r["sources"] == [] and r["answer"]["text"].endswith("No exact lines found.")


def test_follow_up_gets_the_chain_and_branches(monkeypatch) -> None:
    ok = '{"answer": "Noise on small groups.", "sources": []}'
    prompts: list[str] = []
    _fake_model(monkeypatch, [ok, ok], prompts)
    pid, c = _paper(), TestClient(main.app)
    first = _ask(c, pid)
    second = _ask(c, pid, from_card=first["answer"]["id"])
    assert second["answer"]["parent"] == first["answer"]["id"] and first["answer"]["text"] in prompts[-1]


def test_model_unreachable_saves_nothing(monkeypatch) -> None:
    import openai
    _fake_model(monkeypatch, openai.APIConnectionError(request=None))
    pid, c = _paper(), TestClient(main.app)
    assert _ask(c, pid) == {"ok": False, "error": "Could not reach the model. Is Unsloth running?"}
    assert c.get(f"/papers/{pid}/canvas").json()["cards"] == []


# ---------- Dot answers inside notes ----------

@pytest.mark.parametrize("line,dot", [("explain this formula", True), ("Why does it vary?", True), ("@ai what is f*", True),
    ("What a result", True), ("my own thought", False), ("howdy", False), ("  ", False)])
def test_which_lines_go_to_dot(line, dot) -> None:
    assert canvas.for_dot(line) is dot


def _recording_model(monkeypatch, reply="It means the spread."):
    from types import SimpleNamespace

    from workbench import llm
    calls: list[dict] = []

    def create(**kw):
        calls.append(kw)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])
    monkeypatch.setattr(llm, "pick_model", lambda s: "m")
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return calls


def _note(c, pid, **kw):
    return c.post(f"/papers/{pid}/canvas/cards", json={"kind": "note", "x": 0, "y": 0, "w": 240, **kw}).json()


def test_a_question_in_a_note_is_answered_in_the_note_with_a_picture(monkeypatch) -> None:
    calls = _recording_model(monkeypatch, "It means the spread.")
    pid, c = _paper(), TestClient(main.app)
    n = _note(c, pid, page=1, rect=[60, 80, 420, 120], entries=[{"who": "me", "text": "Look at this."}])
    r = c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "@ai explain this"}).json()
    assert r["ok"] and [e["who"] for e in r["card"]["entries"]] == ["me", "me", "dot"]
    assert r["card"]["entries"][-1]["text"] == "It means the spread."
    assert calls[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png")
    prompt = calls[0]["messages"][1]["content"][0]["text"]
    assert "explain this" in prompt and "@ai" not in prompt.split("My question:")[1] and "Look at this." in prompt
    assert c.get(f"/papers/{pid}/canvas").json()["cards"][0]["entries"] == r["card"]["entries"]


def test_a_note_with_no_box_gets_no_picture(monkeypatch) -> None:
    calls = _recording_model(monkeypatch)
    pid, c = _paper(), TestClient(main.app)
    n = _note(c, pid)
    r = c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "Why?"}).json()
    assert r["ok"] and [e["who"] for e in r["card"]["entries"]] == ["me", "dot"]
    assert isinstance(calls[0]["messages"][1]["content"], str)


def test_a_text_only_model_is_asked_again_without_the_picture(monkeypatch) -> None:
    from types import SimpleNamespace

    import openai

    from workbench import llm
    calls = _recording_model(monkeypatch)
    real = llm.client(None).chat.completions.create

    def create(**kw):
        if isinstance(kw["messages"][1]["content"], list):
            calls.append(kw)
            raise openai.APIStatusError("no images", response=SimpleNamespace(status_code=400, headers={}, request=None), body=None)
        return real(**kw)
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    pid, c = _paper(), TestClient(main.app)
    n = _note(c, pid, page=1, rect=[60, 80, 420, 120])
    r = c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "Why?"}).json()
    assert r["ok"] and r["card"]["entries"][-1]["who"] == "dot" and len(calls) == 2


def test_a_plain_line_is_just_kept(monkeypatch) -> None:
    calls = _recording_model(monkeypatch)
    pid, c = _paper(), TestClient(main.app)
    n = _note(c, pid)
    r = c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "my own thought"}).json()
    assert r["ok"] and [e["who"] for e in r["card"]["entries"]] == ["me"] and calls == []


def test_your_line_is_kept_when_the_model_fails(monkeypatch) -> None:
    import openai
    _recording_model(monkeypatch, openai.APIConnectionError(request=None))
    pid, c = _paper(), TestClient(main.app)
    n = _note(c, pid)
    r = c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "Why?"}).json()
    assert r["ok"] is False and r["error"] == "Could not reach the model. Is Unsloth running?"
    assert [e["text"] for e in r["card"]["entries"]] == ["Why?"]


def test_a_long_reply_is_cut_to_fit_the_note(monkeypatch) -> None:
    _recording_model(monkeypatch, "x" * 5000)
    pid, c = _paper(), TestClient(main.app)
    n = _note(c, pid)
    r = c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "Why?"}).json()
    assert r["ok"] and len(r["card"]["entries"][-1]["text"]) == 4000


def test_say_needs_a_note_on_this_paper() -> None:
    pid, c = _paper(), TestClient(main.app)
    a, s, n = _three(pid, c)
    other = _paper()
    assert c.post(f"/papers/{pid}/canvas/cards/{a['id']}/say", json={"text": "Why?"}).status_code == 404
    assert c.post(f"/papers/{pid}/canvas/cards/999/say", json={"text": "Why?"}).status_code == 404
    assert c.post(f"/papers/{other}/canvas/cards/{n['id']}/say", json={"text": "Why?"}).status_code == 404
    assert c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": ""}).status_code == 422
    assert c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "   "}).status_code == 422
    assert c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "x" * 1001}).status_code == 422

