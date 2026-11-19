import pymupdf
import pytest
from fastapi.testclient import TestClient

from pdf_research import answers, canvas, library
from shared import db
import app as main


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

    from pdf_research import graph
    from shared import llm

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
    from pdf_research import marks
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
    from pdf_research import graph
    from shared import settings

    def boom(s):
        raise graph.GraphError("none")
    monkeypatch.setattr(graph, "embed_model", boom)
    pid = _paper()
    assert graph.pages_for(settings.get_all(), pid, "q") == []


def test_a_page_with_no_text_still_gets_an_answer(monkeypatch) -> None:
    import pymupdf

    from pdf_research import library
    _fake_model(monkeypatch, ["A plain answer."])
    doc = pymupdf.open(); doc.new_page()
    pid, c = library.create(doc.tobytes(), "blank.pdf"), TestClient(main.app)
    r = _ask(c, pid)
    assert r["ok"] and r["sources"] == [] and r["answer"]["text"].endswith("No exact lines found.")


def test_follow_up_gets_the_chain_and_branches(monkeypatch) -> None:
    ok = '{"answer": "Noise on small groups.", "sources": []}'
    prompts: list[str] = []
    _fake_model(monkeypatch, [ok, '{"answer": "Few samples per group.", "sources": []}'], prompts)
    pid, c = _paper(), TestClient(main.app)
    first = _ask(c, pid)
    second = _ask(c, pid, from_card=first["answer"]["id"])
    assert second["answer"]["parent"] == first["answer"]["id"] and first["answer"]["text"] in prompts[-1]


def test_model_unreachable_saves_nothing(monkeypatch) -> None:
    import openai
    _fake_model(monkeypatch, openai.APIConnectionError(request=None))
    pid, c = _paper(), TestClient(main.app)
    r = _ask(c, pid)
    assert r["ok"] is False and r["error"] == "Could not reach the model. Is Unsloth running?" and "model error" in r["trace"][-1]
    assert c.get(f"/papers/{pid}/canvas").json()["cards"] == []


# ---------- Dot answers inside notes ----------

@pytest.mark.parametrize("line,dot", [("explain this formula", True), ("Why does it vary?", True), ("@ai what is f*", True),
    ("What a result", True), ("my own thought", False), ("howdy", False), ("  ", False)])
def test_which_lines_go_to_dot(line, dot) -> None:
    assert canvas.for_dot(line) is dot


def _recording_model(monkeypatch, reply="It means the spread."):
    from types import SimpleNamespace

    from shared import llm
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

    from shared import llm
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



# ---------- better sources ----------

def test_odd_ids_are_read_duplicates_dropped_and_formula_gists_reworded(monkeypatch) -> None:
    import json
    reply = {"answer": "The second paragraph sits far below the first one.", "sources": [
        {"block": "P1_B1", "gist": "F1(f, D) := 2TP P+ PP= 2 Í De1[f(x)=y∧y=1] (3)"},
        {"block": "p1-b1", "gist": "Again the second one."},
        {"block": "p1-b0 (page 1)", "gist": "Where the first paragraph is."},
        {"block": 7}]}
    _fake_model(monkeypatch, [json.dumps(reply)])
    pid, c = _paper(), TestClient(main.app)
    r = _ask(c, pid)
    assert [s["text"] for s in r["sources"]] == ["The second paragraph sits far below the first one.", "Where the first paragraph is."]
    assert "No exact lines found" not in r["answer"]["text"]


def test_an_answer_with_no_named_lines_gets_the_lines_it_comes_from(monkeypatch) -> None:
    from pdf_research import marks
    _fake_model(monkeypatch, ['{"answer": "The second paragraph sits far below the first one.", "sources": []}'])
    pid, c = _paper(), TestClient(main.app)
    r = _ask(c, pid)
    assert [s["rect"] for s in r["sources"]] == [marks.blocks(pid, 1)["blocks"][1]]
    assert "No exact lines found" not in r["answer"]["text"]


def test_the_plain_fallback_also_finds_its_lines(monkeypatch) -> None:
    _fake_model(monkeypatch, ["not json", "still not json", "The second paragraph sits far below the first one."])
    pid, c = _paper(), TestClient(main.app)
    assert len(_ask(c, pid)["sources"]) == 1


def test_the_paragraph_list_fits_the_context_budget() -> None:
    from shared.settings import Settings
    paras = [(f"p{i}-b0", i, [0, 0, 1, 1], "word " * 200) for i in (3, 1, 2)]
    kept = answers._fit(Settings(max_context_tokens=2048, max_output_tokens=1024), paras, "")
    assert [p[1] for p in kept] == [1, 3]  # the first pages given win; the list is in page order


def test_a_follow_up_on_a_source_card_sends_what_it_says(monkeypatch) -> None:
    prompts: list[str] = []
    _fake_model(monkeypatch, ['{"answer": "More on that.", "sources": []}'], prompts)
    pid, c = _paper(), TestClient(main.app)
    a, s, n = _three(pid, c)
    r = _ask(c, pid, from_card=s["id"])
    assert r["answer"]["parent"] == s["id"] and "Earlier source (page 1): Gist." in prompts[-1] and "Earlier answer: Because." in prompts[-1]


def test_the_selected_part_goes_with_the_question(monkeypatch) -> None:
    prompts: list[str] = []
    _fake_model(monkeypatch, ['{"answer": "F1 is a score.", "sources": []}'] * 2, prompts)
    pid, c = _paper(), TestClient(main.app)
    _ask(c, pid, question="simplify this term by term", quote="F1(f, D) := 2TP / (P + PP)")
    r = _ask(c, pid, question="again", quote="x")
    assert "The part I selected on page 1" in prompts[0] and "2TP / (P + PP)" in prompts[0]
    assert r["trace"][0] == "your selection, 1 characters" and any(t.endswith("round your selection") for t in r["trace"])
    assert "About the part I selected only" in prompts[0]  # a selection stays the subject, not the whole paper


def test_a_follow_up_that_repeats_the_answer_is_asked_again(monkeypatch) -> None:
    same = "The equation defines how the neural network model is trained at every step from the previous model."
    _fake_model(monkeypatch, [f'{{"answer": "{same}", "sources": []}}'] * 2 + ['{"answer": "Each round, the model takes a small step to fix its mistakes.", "sources": []}'])
    pid, c = _paper(), TestClient(main.app)
    first = _ask(c, pid)
    r = _ask(c, pid, question="simplify it", from_card=first["answer"]["id"])
    assert r["answer"]["text"].startswith("Each round") and "first reply repeated the earlier answer, asked again" in r["trace"]


def test_a_section_or_summary_question_reads_the_right_page() -> None:
    texts = ["Abstract\nWe study noise.", "1 Intro\ntext", "7.2 Results\nMore.", "see section 7.2 above"]
    assert canvas._also("explain section 7.2", texts) == [3]
    assert canvas._also("summary", texts) == [1] and canvas._also("Why?", texts) == []


def test_an_ai_request_is_sent_without_the_tag(monkeypatch) -> None:
    calls = _recording_model(monkeypatch)
    pid, c = _paper(), TestClient(main.app)
    n = _note(c, pid)
    c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "@ai simplify"})
    assert calls[0]["messages"][1]["content"].endswith("My question: simplify")


def test_quotes_in_fences_or_as_one_string_are_read(monkeypatch) -> None:
    from shared import settings
    from pdf_research import primer
    monkeypatch.setattr(primer, "_complete", lambda *a, **k: '```json\n{"quotes": "enough words to count"}\n```')
    assert answers.pick_quotes(settings.get_all(), "text", "t") == ["enough words to count"]


def test_a_failed_json_object_retry_keeps_json_schema_on(monkeypatch) -> None:
    from types import SimpleNamespace

    import openai

    from shared import llm, settings
    from pdf_research import primer

    def create(**kw):
        raise openai.APIStatusError("too long", response=SimpleNamespace(status_code=400, headers={}, request=None), body=None)
    monkeypatch.setattr(llm, "pick_model", lambda s: "m")
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(primer, "_json_schema_ok", True)
    with pytest.raises(primer.PrimerError):
        primer._complete(settings.get_all(), [{"role": "user", "content": "x"}])
    assert primer._json_schema_ok is True


def test_a_marked_formula_gets_the_term_by_term_prompt(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(answers, "_answer", lambda s, system, q, *a, **k: seen.update(system=system, q=q) or {"ok": True, "text": ""})
    answers.explain(None, "F 1 ( f , D ) : = 2 T P P + P P = 2 ∑ D e 1 [ f ( x ) = y ∧ y = 1 ]", "T", ["x"], 0)
    assert seen["system"] is answers.FORMULA_SYSTEM and "term by term" in seen["q"]
    answers.explain(None, "group fairness", "T", ["x"], 0)
    assert seen["system"] is answers.EXPLAIN_SYSTEM


def test_a_looping_answer_is_cut_where_it_goes_round() -> None:
    text = "Intro.\n- a — one\n- b — two\n- a — one\n- b — two\n- c — three"
    assert answers._no_loops(text) == "Intro.\n- a — one\n- b — two"


def test_a_selection_reads_its_paragraphs_and_one_either_side() -> None:
    paras = [(f"p1-b{i}", 1, [0, 0, 1, 1], t) for i, t in enumerate([
        "Abstract about fairness variance overall.", "Background on bias mitigation algorithms.",
        "The standard solution executes many training runs with different randomness, costing huge compute budgets.",
        "Our paper answers this critical unsolved question about efficient alternatives measuring variance cheaply.",
        "Keywords: training randomness.", "References list."])]
    quote = ("The standard solution executes many training runs with different randomness, costing huge compute budgets. "
             "Our paper answers this critical unsolved question about efficient alternatives measuring variance cheaply.")
    assert [p[0] for p in canvas._around(paras, quote)] == ["p1-b1", "p1-b2", "p1-b3", "p1-b4"]
    assert canvas._around(paras, "nothing alike") == paras
