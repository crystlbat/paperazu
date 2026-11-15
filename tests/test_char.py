import json
from typing import Any
import pytest
from fastapi.testclient import TestClient

from workbench import char, db, jobs, main, space

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    char.init_db()


@pytest.fixture
def mock_model(monkeypatch: pytest.MonkeyPatch) -> list[list[dict[str, Any]]]:
    calls: list[list[dict[str, Any]]] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        calls.append(messages)
        sys_msg = messages[0]["content"]
        if "autonomous knowledge synthesizer" in sys_msg:
            return "1. Surface codes demonstrated below fault tolerance threshold.\n2. Logical qubits successfully outliving physical qubits."
        return "Indeed, sir. At your service."

    monkeypatch.setattr(jobs, "complete", complete)
    return calls


def test_char_initial_state_and_default_vars():
    st = char.state()
    persona_var = next(v for v in st["vars"] if v["kind"] == "persona")
    assert "scarf" not in persona_var["look"]
    assert persona_var["tint"] == "#6ff7ff"
    assert "J.A.R.V.I.S." in persona_var["learned"]

    var_names = {v["name"] for v in st["vars"]}
    assert "autonomy" in var_names
    assert "depth" in var_names
    assert "curiosity" in var_names
    assert "proactivity" in var_names


def test_semi_supervised_research_job_creation_and_memory_assimilation(mock_model: list[Any]):
    # 1. User asks Jarvis to investigate a topic
    r = char.say("Jarvis, investigate quantum error correction breakthroughs")

    # Proactivity variable should have fired
    assert any(e["name"] == "proactivity" for e in r["events"])
    assert "I shall look into that immediately, sir." in r["reply"]

    # An autonomous job was dispatched and returned as a card
    assert r["card"] is not None
    assert r["card"]["kind"] == "job"
    assert "quantum error correction" in r["card"]["title"].lower()
    assert "Surface codes" in r["card"]["result"]

    # A knowledge memory note was synthesized and saved
    notes = char.all_notes()
    assert len(notes) == 1
    assert "Surface codes" in notes[0]["note"]

    # 2. Subsequent turn: verify that the newly synthesized knowledge is assimilated into prompt context
    r2 = char.say("What did you find about physical qubits?")
    last_prompt = mock_model[-1][0]["content"]
    assert "KNOWLEDGE SOURCES & ACCUMULATED MEMORY:" in last_prompt
    assert "Surface codes" in last_prompt


def test_become_gideon_and_steer_with_variable(mock_model: list[Any]):
    # 1. User asks Dot to become Gideon (even with spelling "became gidian")
    r = char.say("became gidian")
    prof = char.get_profile()
    assert prof["name"] == "Gideon"
    assert "holo" in prof["look"]
    assert "scarf" not in prof["look"]  # Clean, fluid, blobby character without stiff attachments!
    assert "Barry Allen" in prof["persona"] or "Time Vault" in prof["persona"]
    assert any(e.get("trigger") == "set" for e in r["events"])

    # 2. User defines a custom steer variable
    r2 = char.say("count timeline every 1 say Timeline probability at 99.4%, Director.")
    assert any(e.get("trigger") == "made" and e.get("name") == "timeline" for e in r2["events"])

    # Verify variable appears in active variables
    vars_list = char.variables()
    assert any(v["name"] == "timeline" for v in vars_list)

    # 3. User mentions the word 'timeline' to test the steering rule
    r3 = char.say("Gideon, give me a status report on the current timeline.")
    assert any(e.get("name") == "timeline" for e in r3["events"])
    assert "Timeline probability at 99.4%, Director." in r3["reply"]


def test_char_fastapi_endpoints():
    # 1. Browser navigation redirects to /#char
    resp = client.get("/char", headers={"Accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/#char"

    # 2. Questions endpoint
    resp = client.get("/char/questions")
    assert resp.status_code == 200
    assert resp.json()["questions"] == []  # no rule yet, so no creature watches anything

    # 2. API fetch returns state
    resp = client.get("/char", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert "vars" in data
    assert "tables" in data

    # 3. Chat turn via API
    resp = client.post("/char/say", json={"text": "Hello Jarvis"})
    assert resp.status_code == 200
    reply_data = resp.json()
    assert "reply" in reply_data

    # 4. Notes drawer returns knowledge memories
    resp = client.get("/char/notes")
    assert resp.status_code == 200
    assert "notes" in resp.json()

    # 5. Clear conversation
    resp = client.delete("/char")
    assert resp.status_code == 200
    assert resp.json()["turns"] == []


def test_bias_counter_triggers_action_taken_and_opens_paper(mock_model: list[Any], monkeypatch: pytest.MonkeyPatch):
    from workbench import websearch
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": [{"title": "Bias survey", "url": "https://b.example"}]})
    # 1. User sets up the rule:
    # "create a variable called bias > increate counter of bias by +1 when i say bias > when bias becomes 5 define a variable called action_taken and open a pdf on bias or suggest a pdf"
    r = char.say("create a variable called bias > increase counter of bias by +1 when i say bias > when bias becomes 5 define a variable called action_taken and open a pdf on bias or suggest a pdf")
    assert any(e.get("trigger") == "made" and e.get("name") == "bias" for e in r["events"])

    # The rule lives in the shared engine, the same as on the Dot page
    b_var = next(v for v in space.variables() if v["name"] == "bias")
    assert (b_var["every"], b_var["act"], b_var["act_arg"]) == (5, "make+paper", "action_taken | bias")

    # 2. Say bias 4 times (counts 1 to 4)
    char.say("This is bias message 1")
    char.say("This is bias message 2")
    char.say("This is bias message 3")
    char.say("This is bias message 4")

    # 3. Say bias 5th time -> milestone triggered!
    r5 = char.say("This is bias message 5 reaching the threshold")

    # Verify action_taken variable was automatically defined and spawned
    assert any(e.get("name") == "bias" and e.get("made") == "action_taken" for e in r5["events"])
    vars_now = {v["name"] for v in r5["vars"]}
    assert "action_taken" in vars_now

    # Case A: When NO bias paper is in library -> it suggests papers (web card)
    assert r5["card"] is not None
    assert r5["card"]["kind"] == "web"
    assert "bias" in r5["card"]["query"].lower()

    # Case B: When a bias paper IS in library -> it opens that paper directly!
    con = db.connect()
    with con:
        con.execute(
            "INSERT INTO papers (id, title, authors) VALUES ('bias123', 'Gender Bias and Representation in Language Models', 'Dr. Researcher')"
        )
        con.execute("UPDATE space_vars SET value = 4.0 WHERE name = 'bias'")
    con.close()

    r6 = char.say("Let us test bias again now that a paper is in the library")
    assert r6["card"] is not None
    assert r6["card"]["kind"] == "papers"
    assert r6["card"]["open"] is True
    assert "bias123" == r6["card"]["pick"]


def test_learn_more_continuous_inquiry_loop(mock_model: list[Any]):
    # 1. Turn on Learn More mode and explore an initial question
    r1 = char.say("How does quantum error correction protect physical qubits?", learn_mode=True)

    # Autonomous job should have run and returned research card
    assert r1["card"] is not None
    assert r1["card"]["kind"] == "job"

    # Memory note should have been created
    notes1 = char.all_notes()
    assert len(notes1) >= 1

    # Should have returned follow-up directional question chips
    assert "questions" in r1
    assert len(r1["questions"]) >= 1

    # Knowledge and curiosity variables should have incremented
    k_var = next(v for v in r1["vars"] if v["name"] == "knowledge")
    assert k_var["value"] >= 1.0

    # 2. User chooses one of the suggested directions
    chosen_q = r1["questions"][0]
    r2 = char.say(chosen_q, learn_mode=True)

    # A second memory note was created, compounding context
    notes2 = char.all_notes()
    assert len(notes2) > len(notes1)

    # Next round of follow-up questions produced
    assert len(r2["questions"]) >= 1
    assert r2["card"] is not None




def test_replies_stop_copying_old_lines(monkeypatch):
    replies = iter(["Ok.", "Bias is noted.", "Bias is noted. Noted again."])
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "{}" if k.get("response_format") else next(replies, "Fine."))
    char.say("hello there")
    char.say("hello again")
    assert char.say("and again")["reply"] == "Noted again."  # the copied line is dropped


def test_char_and_the_dot_page_share_one_list_of_rules(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "{}" if k.get("response_format") else "Mm.")
    space.say("count apples")  # made on the Dot page
    r = char.say("apples and more apples")  # counted in /char
    assert next(v for v in r["vars"] if v["name"] == "apples")["value"] == 2
    char.say("count pears")  # made in /char
    assert [v["name"] for v in space.variables()] == ["apples", "pears"]


def test_char_hatches_a_rules_creature_and_sleeps(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "{}" if k.get("response_format") else "Mm.")
    space._make("create a variable called cases")
    space._make("when cases hits 10 spawn a creature called watson that lists the clues in the paper, and eva which will let the UI sleep")
    con = db.connect()
    with con:
        con.execute("UPDATE space_vars SET value = 9 WHERE name = 'cases'")
    con.close()
    r = char.say("cases")
    assert r["card"]["kind"] == "creature" and r["card"]["job"]["name"] == "Watson"
    assert any(e.get("sleep") for e in r["events"])


def _reflect_mocks(monkeypatch, found=True, model_ok=True):
    from workbench import websearch
    topics: list[str] = []

    def search(s: Any, q: str) -> dict[str, Any]:
        topics.append(q)
        return {"results": [{"title": "T1", "url": "u", "snippet": "S1"}, {"title": "T2", "url": "u", "snippet": "S2"}] if found else []}

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        if not model_ok:
            raise RuntimeError("down")
        return "Remember the fog."

    monkeypatch.setattr(websearch, "search", search)
    monkeypatch.setattr(jobs, "complete", complete)
    return topics


def test_reflect_walks_the_topics_then_is_done(monkeypatch):
    topics = _reflect_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    space.add_var({**{f: "" for f in space.FIELDS}, "name": "cases", "kind": "count", "pattern": "case", "every": 10, "past": 0, "look": [], "drops": 0, "act": "spawn", "act_arg": "watson: lists the clues"})  # Watson watches cases
    lefts = [char.reflect(on_char=True)["left"] for _ in range(3)]
    assert topics == ["Sherlock world and setting", "Sherlock cases", "Sherlock Watson"] and lefts == [2, 1, 0]
    assert char.reflect(on_char=True) == {"done": True, "topic": "", "note": "", "left": 0}
    con = db.connect(); titles = [r[0] for r in con.execute("SELECT title FROM char_memories WHERE source = 'reflection' ORDER BY id")]; con.close()
    assert titles == [f"Reflection: {t}" for t in topics]


def test_reflect_falls_back_to_the_snippets_when_the_model_fails(monkeypatch):
    _reflect_mocks(monkeypatch, model_ok=False)
    r = char.reflect(on_char=True)
    assert r["note"] == "- T1: S1 - T2: S2"
    assert char.reflect(on_char=True)["topic"] != r["topic"]  # the first one was saved


def test_reflect_saves_nothing_when_search_finds_nothing(monkeypatch):
    _reflect_mocks(monkeypatch, found=False)
    r = char.reflect(on_char=True)
    assert (r["note"], r["done"]) == ("", False)
    con = db.connect(); n = con.execute("SELECT count(*) FROM char_memories WHERE source = 'reflection'").fetchone()[0]; con.close()
    assert n == 0 and _memories("sheet") == [(f"Reflection: {r['topic']}"[:80], "(nothing found)")]
    assert char.reflect(on_char=True)["topic"] != r["topic"]  # the failed topic no longer blocks the next


def test_a_reflection_reaches_the_next_char_prompt_and_the_route(monkeypatch, mock_model):
    _reflect_mocks(monkeypatch)
    r = client.post("/char/reflect", json={"char": True})
    assert r.status_code == 200 and r.json()["topic"]
    seen: list[Any] = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: seen.append(m) or "ok")
    char.say("hello")
    assert "Remember the fog." in json.dumps(seen)


def test_reflect_as_dot_uses_bare_variable_creature_and_paper_topics(monkeypatch):
    topics = _reflect_mocks(monkeypatch)
    space.add_var({**{f: "" for f in space.FIELDS}, "name": "cases", "kind": "count", "pattern": "case", "every": 0, "past": 0, "look": [], "drops": 0})
    jobs._exec("INSERT INTO jobs (name) VALUES (?)", ("Watson",))
    jobs._exec("INSERT INTO papers (id, title, last_opened) VALUES ('p1', 'Older', '2020-01-01'), ('p2', 'Newest', '2024-01-01')")
    while not char.reflect()["done"]:
        pass
    assert topics == ["cases", "Watson", "Newest", "Older"]


def test_reflect_survives_malformed_results(monkeypatch):
    from workbench import websearch
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": [{"url": "u"}, {"title": "T", "snippet": None}]})
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "")
    assert "None" not in char.reflect()["note"]


def test_become_sherlock_stores_a_sheet(mock_model: list[Any]):
    r = char.say("become sherlock holmes")
    assert "Voice:" in char.get_profile()["persona"]
    ev = next(e for e in r["events"] if e.get("trigger") == "set")
    assert set(ev["sheet"]) == set(space.SLOTS) and ev["sheet"]["Voice"]


def _rest_mocks(monkeypatch, verdict="NO", fail=()):
    """Reflection search + a model routed by words in the system prompt."""
    topics = _reflect_mocks(monkeypatch)
    seen: list[str] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        sys_msg = messages[0]["content"]
        seen.append(sys_msg)
        if any(w in sys_msg for w in fail):
            raise RuntimeError("down")
        if "Answer YES or NO" in sys_msg:
            return verdict
        if "Rewrite the reply" in sys_msg:
            return "Elementary, my dear."
        if "follow-up question" in sys_msg:
            return "Why the fog"
        if "where and when" in sys_msg:
            return '"Baker Street, 1890."\nmore'
        return "Remember the fog."

    monkeypatch.setattr(jobs, "complete", complete)
    return topics, seen


def _memories(source):
    con = db.connect(); rows = [(r[0], r[1]) for r in con.execute("SELECT title, content FROM char_memories WHERE source = ? AND title NOT LIKE 'Resting: %' ORDER BY id", (source,))]; con.close()  # not the resting markers
    return rows


def _dot_turn(text="You have seen the fog, my dear fellow."):
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', ?)", (text,))
    con.close()


def test_rest_rotates_reflect_wonder_fill_practise_then_done(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char._since(True, "Sherlock")  # mark first: a turn written before the marker drops out of _chat_since if the second ticks over
    _dot_turn()
    kinds = [char.rest(True, n)["kind"] for n in range(4)]
    assert kinds == ["reflect", "wonder", "fill", "practise"]
    assert "World: Baker Street, 1890." in char.get_profile()["persona"]
    assert _memories("lesson") == [(_memories("lesson")[0][0], "Elementary, my dear.")]
    assert char.rest(True, 0)["kind"] == "reflect"  # the question is now the topic
    r = {}
    for n in range(40):
        r = char.rest(True, n)
        if r["done"]:
            break
    assert r["done"] and r["questions"] == []


def test_rest_is_done_with_nothing_to_do(monkeypatch):
    _rest_mocks(monkeypatch)
    monkeypatch.setattr(char, "reflect", lambda on_char=False: {"done": True, "topic": "", "note": "", "left": 0})
    assert {k: v for k, v in char.rest(True, 0).items() if k != "why"} == {"done": True, "kind": "", "topic": "", "note": "", "questions": [], "graph": {"nodes": [], "edges": [], "folds": [], "links": []}}


def test_rest_yes_keeps_the_reply_as_the_lesson(monkeypatch):
    _rest_mocks(monkeypatch, verdict="Yes")
    _dot_turn()
    r = char.rest(True, 3)
    assert r["kind"] == "practise" and r["note"].startswith("Kept: You have seen")
    assert _memories("lesson")[0][1] == "You have seen the fog, my dear fellow."
    assert char.rest(True, 3)["kind"] != "practise"  # that turn already has its lesson


def test_rest_fill_failure_leaves_the_sheet_and_is_not_retried(monkeypatch):
    _rest_mocks(monkeypatch, fail=("where and when", "call the person", "known for saying"))
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.add_memory("Reflection: x", "fog", source="reflection")
    assert char.rest(True, 2)["note"] == "(could not tell)"
    assert char.get_profile()["persona"] == "a detective"
    for _ in range(3):
        char.rest(True, 2)
    assert len([m for m in _memories("sheet") if m[0].startswith("Sheet: ")]) == 3 and char.rest(True, 2)["kind"] != "fill"


def test_a_lesson_reaches_the_char_prompt(monkeypatch):
    _rest_mocks(monkeypatch)
    _dot_turn()
    char.rest(True, 3)
    seen: list[Any] = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: seen.append(m) or "ok")
    char.say("hello")
    assert "Speak like this example: Elementary, my dear." in json.dumps(seen)
    assert "Lesson:" not in seen[0][0]["content"]


def test_rest_fills_world_on_the_dot_page(monkeypatch):
    _rest_mocks(monkeypatch)
    v = space.add_var({**{f: "" for f in space.FIELDS}, "name": "Sherlock", "kind": "persona", "pattern": "", "every": 0, "past": 0, "look": [], "drops": 0})
    space.take_on(v["id"], "You are Sherlock.\nVoice: clipped", ["hat"])
    char.add_memory("Reflection: x", "fog", source="reflection")
    assert char.rest(False, 2)["kind"] == "fill"
    row = space._rows("SELECT learned, look FROM space_vars WHERE id = ?", (v["id"],))[0]
    assert "World: Baker Street, 1890." in row["learned"] and "Voice: clipped" in row["learned"] and "hat" in row["look"]


def test_wonder_saves_a_question_raises_curiosity_and_feeds_reflect(monkeypatch):
    topics, _ = _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    def cur():
        con = db.connect(); v = con.execute("SELECT value FROM char_vars WHERE name = 'curiosity'").fetchone()[0]; con.close(); return v
    before = cur()
    char.rest(True, 0)
    r = char.rest(True, 1)
    assert r["kind"] == "wonder" and r["note"] == "Why the fog?" and r["questions"] == ["Why the fog?"]
    assert cur() == before + 0.5 and "Question: Why the fog?" in _memories("question")[0][0]
    assert char.rest(True, 1)["kind"] != "wonder"  # one follow-up per reflection
    char.rest(True, 0)
    assert topics[-1] == "Sherlock Why the fog?"  # searched with the name, to stay on the subject


def test_wonder_falls_back_and_never_leaves_more_than_three_open(monkeypatch):
    _rest_mocks(monkeypatch, fail=("follow-up question",))
    char.update_profile("Sherlock", "a detective", [], "#fff")
    for i in range(5):
        char.add_memory(f"Reflection: t{i}", "fog", source="reflection")
        char.rest(True, 1)
    qs = _memories("question")
    assert [c for _, c in qs][0].startswith("What else matters about t0?") and len(qs) == 3
    assert len(char.rest(True, 1)["questions"]) == 3


def test_rest_route(monkeypatch):
    _rest_mocks(monkeypatch)
    r = client.post("/char/rest", json={"char": True, "n": 0})
    assert r.status_code == 200 and r.json()["kind"] == "reflect"


def test_unanswerable_question_is_closed_by_a_marker(monkeypatch):
    _rest_mocks(monkeypatch)
    char.add_memory("Reflection: t", "fog", source="reflection")
    char.add_memory("Question: Q?", "Q? (from 1)", source="question")
    from workbench import websearch
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": []})
    assert char.reflect(on_char=True)["topic"] == "Q?" and char._open_questions() == []


def test_markers_stay_out_of_notes_and_state(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    _dot_turn()
    for n in (0, 1, 2, 3):
        char.rest(True, n)
    assert {m[1] for m in _memories("sheet") + _memories("question") + _memories("lesson")}
    for rows in (char.all_notes(), char.state()["papers"]):
        assert not [x for x in rows if str(x.get("title", "")).startswith(("Sheet:", "Question:", "Lesson:"))]


def test_a_question_is_searched_with_the_characters_name(monkeypatch):
    from workbench import websearch
    asked = []
    monkeypatch.setattr(websearch, "search", lambda s, q: asked.append(q) or {"results": [{"title": "T", "snippet": "S"}]})
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "A note.")
    char.update_profile("Sherlock", "You are Sherlock.", [], "")
    char.add_memory("Question: Where is it set?", "Where is it set? (from 1)", source="question")
    assert char.reflect(on_char=True)["topic"] == "Where is it set?" and asked == ["Sherlock Where is it set?"]


def test_become_on_char_wears_the_look_and_colour(monkeypatch):
    monkeypatch.setattr(space, "become", lambda who, fired=None: {"learned": f"You are {who}.\nVoice: Speak as a detective.", "look": ["monocle"], "tint": "red"})
    r = char.say("become sherlock")
    ev = next(e for e in r["events"] if e.get("trigger") == "set")
    assert ev["tint"] == "red" and char.get_profile()["look"] == ["monocle"]


def test_a_new_character_does_not_inherit_the_last_ones_questions(monkeypatch):
    _reflect_mocks(monkeypatch)
    char.update_profile("Sherlock", "You are Sherlock.", [], "red")
    char.rest(on_char=True, n=0)  # Sherlock reflects
    char.add_memory("Question: Why the fog?", "Why the fog? (from 1)", source="question")
    monkeypatch.setattr(space, "become", lambda who: {"learned": f"You are {who}.", "look": [], "tint": "blue"})
    char.become_persona("ghost")  # only become/enter switch the character: a rename alone no longer starts a new one
    first = char.rest(on_char=True, n=0)
    assert first["topic"] == "Ghost world and setting"
    filled = char.rest(on_char=True, n=2)
    assert filled["kind"] == "fill" and "Ghost" in filled["topic"]


def test_a_characters_creatures_are_the_jobs_on_its_variables(mock_model: list[Any]):
    char.say("create a variable called cases")
    char.say("when cases hits 10 spawn a creature called watson that lists the clues in the paper, and eva which will let the UI sleep")
    crew = char.get_questions()
    assert [(c["name"], c["watches"], c["every"]) for c in crew] == [("Watson", "cases", 10), ("Eva", "cases", 10)]
    assert "clues" in crew[0]["goal"]


def test_change_models_on_char_shows_the_models_card(monkeypatch, mock_model: list[Any]):
    monkeypatch.setattr(space, "models_card", lambda: {"kind": "models", "status": "ready", "current": "a", "items": [{"id": "a", "current": True, "embed": False}]})
    r = char.say("change models")
    assert r["card"]["kind"] == "models" and "model" in r["reply"]


def test_a_new_character_starts_with_fresh_moods_and_no_old_rules(mock_model: list[Any]):
    char.say("create a variable called cases")
    con = db.connect()
    with con: con.execute("UPDATE char_vars SET value = -5 WHERE name = 'depth'")
    con.close()
    char.become_persona("ghost from destiny 2")
    names = [v["name"] for v in char.variables()]
    from workbench import verse
    assert "cases" not in names and "cases" not in [v["name"] for v in space.variables()]  # its rules go with it, and come back with it
    assert next(v for v in char.variables() if v["name"] == "depth")["value"] != -5
    verse.enter("J.A.R.V.I.S.")
    assert "cases" in [v["name"] for v in char.mine()]


def test_names_in_a_note_grow_the_graph_and_lead_the_next_reflection(monkeypatch):
    topics = _reflect_mocks(monkeypatch)
    char.update_profile("Navi", "You are Navi.", [], "")
    char._since(True, "Navi")  # Navi's start: rows before it are not its own
    note = char.add_memory("Reflection: Navi world and setting", "Navi guides Link through Hyrule.", source="reflection")
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "Link, Hyrule, Navi" if "names" in system else "")
    r = char.rest(True, 4)
    assert (r["kind"], r["note"]) == ("extract", "Link, Hyrule")
    char.add_memory("Reflection: Hyrule", "Link lives in Hyrule.", source="reflection")
    char._entities_of(999, "Link lives in Hyrule.", "Navi")
    g = char.graph()
    assert {n["name"]: (n["n"], n["known"]) for n in g["nodes"]} == {"Link": (2, False), "Hyrule": (2, True)} and g["edges"] == [["Link", "Hyrule"]]
    assert char.reflect(on_char=True)["topic"] == "Link" and topics[-1] == "Navi Link"  # the unread name comes next, searched with who is asking
    assert note["id"]


def test_sorter_reads_the_characters_own_chat_for_names_one_message_at_a_time(monkeypatch):
    con = db.connect()
    with con: con.execute("INSERT INTO char_turns (role, text, created_at) VALUES ('user', 'old chat about Sherlock', '2000-01-01')")
    con.close()
    char.update_profile("Navi", "You are Navi.", [], "")
    char.add_memory("Resting: char Navi", "0", source="sheet")
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text, created_at) VALUES ('user', 'Who is Zelda?', datetime('now', '+1 second'))")
        con.execute("INSERT INTO char_turns (role, text, created_at) VALUES ('dot', 'Princess Zelda rules Hyrule.', datetime('now', '+1 second'))")
    con.close()
    monkeypatch.setattr(char, "_ask", lambda system, user, n: {"Who is Zelda?": "Zelda", "Princess Zelda rules Hyrule.": "Zelda, Hyrule, players"}.get(user, "YES"))
    first = char.sorter(1)
    assert (first["total"], first["left"], first["read"][0]["names"]) == (2, 1, ["Zelda"])
    second = char.sorter(5)
    assert second["read"][0]["names"] == ["Zelda", "Hyrule"] and second["left"] == 0  # "players" is not a name
    assert {n["name"]: n["n"] for n in second["graph"]["nodes"]} == {"Zelda": 2, "Hyrule": 1} and second["graph"]["edges"] == [["Zelda", "Hyrule"]]
    assert char.sorter(5)["read"] == []


def test_a_reply_recalls_the_notes_tied_to_the_names_it_hears_and_lights_them():
    char.update_profile("Navi", "You are Navi.", [], "")
    char.add_memory("Resting: char Navi", "0", source="sheet")
    a = char.add_memory("Reflection: Hyrule", "Hyrule is a kingdom.", source="reflection")["id"]
    char.add_memory("Reflection: Weather", "It rains a lot.", source="reflection")
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_memories (title, content, source) VALUES ('Entity: Hyrule', ?, 'entity')", (str(a),))
        con.execute("INSERT INTO char_memories (title, content, source) VALUES ('Entity: Link', ?, 'entity')", (str(a),))
    con.close()
    notes, names = char.recall("Tell me about Hyrule")
    assert notes[0]["title"] == "Reflection: Hyrule" and names == ["Hyrule", "Link"]  # Link fires through the note they share
    assert all(not n["title"].startswith("Entity:") for n in notes)


def test_pruner_weighs_one_note_at_a_time_and_archives_what_it_drops(monkeypatch):
    char.update_profile("Navi", "You are Navi.", [], "")
    char.add_memory("Resting: char Navi", "0", source="sheet")
    char.add_memory("Reflection: Hyrule", "Hyrule is home.", source="reflection")
    char.add_memory("Reflection: Quantum", "Qubits and codes.", source="reflection")
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "DROP" if "Qubits" in user else "KEEP")
    first, second = char.pruner(), char.pruner()
    assert (first["dropped"], second["dropped"]) == (False, True)
    assert (second["before"]["notes"], second["notes"], second["chars"]) == (2, 1, len("Hyrule is home."))
    assert char.pruner()["note"] is None  # each note is weighed once
    con = db.connect()
    assert con.execute("SELECT content FROM char_memories WHERE title = 'Pruned: Reflection: Quantum'").fetchone()["content"] == "Qubits and codes."
    con.close()


def test_asker_turns_world_names_into_questions_and_leaves_out_the_rest(monkeypatch):
    char.update_profile("Navi", "You are Navi.", [], "")
    char.add_memory("Resting: char Navi", "0", source="sheet")
    note = char.add_memory("Reflection: Hyrule", "Zelda rules Hyrule. Google indexes it.", source="reflection")["id"]
    con = db.connect()
    with con:
        for name in ("Zelda", "Google"):
            con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'entity')", (f"Entity: {name}", str(note)))
    con.close()
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "NO" if user == "Google" else "YES")
    assert char.asker() == ["Who or what is Zelda?"]
    assert [n["name"] for n in char.graph()["nodes"]] == ["Zelda"]  # Google is off-world now
    assert char.asker() == [] and char._open_questions(char._start()) == ["Who or what is Zelda?"]
    m = char.mind()
    assert any(r["title"] == "Off-world: Google" for r in m["memories"]) and not any(r["title"].startswith("Resting") for r in m["memories"])


def test_a_rule_that_fires_become_switches_the_character_even_in_lower_case(mock_model: list[Any]):
    char.say("count change every 2 become gidian")
    assert char.get_profile()["name"] != "Gideon"  # making the rule is not the switch
    char.say("change")
    r = char.say("change again")
    assert char.get_profile()["name"] == "Gideon" and r["reply"].startswith("I am Gideon now")
    assert any(e.get("trigger") == "set" and e.get("sheet") for e in r["events"])


def test_sad_counts_down_with_each_happy_turns_dot_blue_at_zero_and_its_mood_steers_every_reply(mock_model: list[Any]):
    r = char.say("set variable sad and say happy 3 times and when sad = 0, change blue")
    sad = next(v for v in char.mine() if v["name"] == "sad")
    assert (sad["value"], sad["step"], sad["at"], sad["act"], sad["act_arg"]) == (3, -1, 0, "recolor", "blue") and "Starts" not in r["reply"]
    char.say("when sad is 0 say hahaha and when sad is above 0 say oh")
    sad = next(v for v in char.mine() if v["name"] == "sad")
    assert (sad["low_say"], sad["high_say"], sad["step"], sad["act"]) == ("hahaha", "oh", -1, "recolor")  # the second sentence adds to the first
    assert char.say("hello there")["reply"].startswith("oh")
    char.say("happy"); char.say("so happy")
    last = char.say("happy again")
    assert last["reply"].startswith("hahaha") and any(e.get("trigger") == "at" for e in last["events"])
    assert next(v for v in char.mine() if v["name"] == "sad")["value"] == 0
    assert any(v.get("tint") for v in char.mine())  # Dot turned blue
    assert char.say("happy")["reply"].startswith("hahaha")  # below 0 is still the happy side


def test_asker_goes_a_lens_deeper_once_answered_then_links_names_and_falls_silent(monkeypatch):
    char.update_profile("Navi", "You are Navi.", [], "")
    char.add_memory("Resting: char Navi", "0", source="sheet")
    note = char.add_memory("Reflection: Navi world and setting", "Zelda rules Hyrule.", source="reflection")["id"]
    con = db.connect()
    with con:
        for name in ("Zelda", "Hyrule"):
            con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'entity')", (f"Entity: {name}", str(note)))
    con.close()
    gates: list[str] = []
    monkeypatch.setattr(char, "_ask", lambda system, user, n: gates.append(user) or "YES")

    def answer(qs: list[str]) -> list[str]:
        for q in qs:
            char.add_memory(f"Reflection: {q}"[:80], "noted", source="reflection")
        return qs

    first = answer(char.asker())
    assert first == ["Who or what is Zelda?", "Who or what is Hyrule?"]
    second = answer(char.asker())
    assert second == ["Why does Zelda matter to Navi?", "Why does Hyrule matter to Navi?", "How are Zelda and Hyrule connected?"]
    third = char.asker()
    assert third == ["Where and when does Zelda show up?", "Where and when does Hyrule show up?"]
    assert char.asker() == []  # an open question waits for its answer before the next lens
    answer(third)
    assert char.asker() == []  # every name and lens is spent: nothing left to wonder
    assert gates == ["Zelda", "Hyrule"]  # the world check runs once per name, only at the first lens


def test_names_the_note_does_not_hold_stay_out_of_the_graph(monkeypatch):
    char.update_profile("Navi", "You are Navi.", [], "")
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "Link, Ganon, Hyrule")
    assert char._entities_of(1, "Link lives in Hyrule.", "Navi") == ["Link", "Hyrule"]


def test_ideas_are_a_separate_abstract_layer_that_folds_synonyms_and_gets_its_own_questions(monkeypatch):
    char.update_profile("Navi", "You are Navi.", [], "")
    char.add_memory("Resting: char Navi", "0", source="sheet")
    asks: list[str] = []

    def model(system: str, user: str, n: int) -> str:
        asks.append(system)
        if "names of people" in system:
            return {"Navi guards Hyrule from Ganon.": "Hyrule, Ganon", "Navi keeps Hyrule safe.": "Hyrule"}[user]
        if "going on" in system:
            return "guarding Hyrule; fighting Ganon; dancing alone; Hyrule" if "Ganon" in user else "protecting Hyrule"
        return "YES"  # same meaning, and in-world

    monkeypatch.setattr(char, "_ask", model)
    for text in ("Navi guards Hyrule from Ganon.", "Navi keeps Hyrule safe."):
        note = char.add_memory(f"Reflection: {text}", text, source="reflection")["id"]
        char._entities_of(note, text, "Navi")
        r = char.rest(True, 5)
        assert r["kind"] == "ideas"
    assert r["note"] == "guarding Hyrule"  # "protecting Hyrule" means the same, so it folded in
    nodes = {n["name"]: (n["kind"], n["n"]) for n in char.graph()["nodes"]}
    assert nodes == {"Hyrule": ("concrete", 2), "Ganon": ("concrete", 1), "guarding Hyrule": ("abstract", 2), "fighting Ganon": ("abstract", 1)}
    asks.clear()
    assert char.asker() == ["Who or what is Hyrule?", "How did guarding Hyrule start?", "Who or what is Ganon?"]
    assert sum("Answer YES or NO" in s for s in asks) == 2  # only names pass the world check; an idea already holds one
    assert char.rest(True, 5)["kind"] != "ideas"  # every named note has had its ideas read


def _name(name, known=False):
    note = char.add_memory(f"Reflection: {name if known else name + ' aside'}", f"{name} matters.", source="reflection")
    char.add_memory(f"Entity: {name}", str(note["id"]), source="entity")


def test_curiosity_and_maturity_follow_the_formula_and_curiosity_is_the_brake(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.rest(True, 0)  # a character that knows no names is not braked: it reads about its world first
    _name("Watson", known=True); _name("Moriarty")
    d = char.disposition()  # tau = mean(unmet / 3) = (2/3 + 3/3) / 2; nothing consolidated yet, so no damping and both names are new
    assert (d["tau"], d["dnE"], d["maturity"], d["curiosity"]) == (0.83, 2, 0.0, 5.0)  # 1.67 + frontier term D*(1-F) = 4*(1-1/6): question c=0/(0+3), note c=1/(1+2) (the world note names nothing), F=1/6
    char.add_memory("Baked", '{"nE": 2, "nAE": 2}', source="sheet")
    d = char.disposition()  # consolidated: maturity = 1 - exp(-2/2), and with no new name since, curiosity is 0
    assert (d["maturity"], d["dnE"], d["curiosity"]) == (0.63, 0, 3.33)  # only the frontier term is left
    assert char.rest(True, 0, force=True)["kind"] == "reflect"  # your own tap still runs a step
    _name("Irene")
    assert char.disposition()["curiosity"] == round((1 / 3 + 1 + 1) / 3 * 1 * 2.718281828 ** -1 + char.frontier()["term"], 2)  # a new name wakes it, damped by what it already knows (the tap answered one more of Watson's questions)
    assert char.rest(True, 0)["kind"] == "reflect"
    assert [s["name"] for s in char.monitor()["series"]] == ["curiosity", "maturity", "frontier"] and char.monitor()["steps"] >= 2


def test_three_systems_plan_goal_execute_and_switch_off(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.rest(True, 0)  # it reads about its world first: a plan starts from what it knows
    plan = char.rest(True, 7)  # S2 writes the plan
    assert (plan["system"], plan["kind"], plan["note"]) == (2, "plan", "Remember the fog")
    goal = char.rest(True, 8)  # S1 makes a question of it
    assert (goal["system"], goal["kind"]) == (1, "goal") and goal["note"] in char._open_questions()
    done = char.rest(True, 0)  # S0 looks it up
    assert (done["system"], done["kind"], done["topic"]) == (0, "reflect", goal["note"])
    assert [s["runs"][0]["kind"] for s in char.systems()["systems"][:3]] == ["plan", "goal", "reflect"]
    char.set_system(0, False)
    assert all(char.rest(True, n).get("system") != 0 for n in range(9))
    assert [s["on"] for s in char.systems()["systems"]] == [True, True, False, True]


def test_a_rule_holds_a_system_off_until_it_lets_go(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    made = space._make("set focus to 1. each done takes 1 off focus. when focus = 0, turn S2 off")
    assert made and "system S2 off" in made[0]
    assert char.systems()["systems"][0]["on"]  # focus is 1: the rule is not holding yet
    space.measure("done")
    s2 = char.systems()["systems"][0]
    assert (s2["on"], s2["rule"]) == (False, "focus") and not space.lasting(char.mine())  # held off, and never said as a mood
    char.set_system(2, True)
    assert 2 in char.systems_off()  # the rule beats the hand switch while it holds


def test_guess_then_correct_scores_surprise(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    assert char._surprise("his loyal butler", "Alfred is the loyal butler of Bruce Wayne") == 0.0
    assert char._surprise("a rival detective", "Alfred is the loyal butler of Bruce Wayne") == 1.0
    char.add_memory("Question: Who is Alfred?", "Who is Alfred? (from 0)", source="question")
    seen, inner = [], jobs.complete
    monkeypatch.setattr(jobs, "complete", lambda st, m, **k: seen.append(m) or inner(st, m, **k))
    r = char.reflect(True)  # the mock guesses and finds the same words: no surprise
    assert (r["guess"], r["surprise"]) == ("Remember the fog.", 0.0)
    g = next(m[1]["content"] for m in seen if "about your world" in m[0]["content"])
    assert "Your world:\na detective" in g and "What you have read so far:" in g and g.endswith("Question: Who is Alfred?")  # the guess sees its world and its nearest notes
    w = char.wiring()
    assert [s["name"] for s in w["signals"]] == ["curiosity", "maturity", "surprise"] and w["last_guess"]["guess"] == "Remember the fog."


def test_names_from_separate_chats_get_a_link_question(monkeypatch):
    _rest_mocks(monkeypatch, verdict="YES")
    char.update_profile("Robin", "a sidekick", [], "#fff")
    char.rest(True, 0)
    for name in ("Batman", "Alfred"):  # each met in its own note: no edge between them
        note = char.add_memory(f"Reflection: {name}", f"{name} lives in Gotham.", source="reflection")
        char.add_memory(f"Entity: {name}", str(note["id"]), source="entity")
    assert "How are Batman and Alfred connected?" in char.asker(limit=9)


def test_modes_quiet_stops_and_proactive_speaks_first(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.set_mode("quiet")
    assert char.rest(True, 0)["quiet"] and char.rest(True, 0, force=True)["kind"] == "reflect"  # your own tap still runs a step
    char.set_mode("proactive")
    char.add_memory("Question: Who is Alfred?", "Who is Alfred? (from 0)", source="question")
    said = char.rest(True, 0)["said"]
    assert said.startswith("I got curious: Who is Alfred?") and char._chat_since()[-1]["text"] == said


def test_a_wire_is_read_exactly_or_refused(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    w = char.wire("when focus is above 3, turn S0 off")
    assert {"from": "focus", "to": 0, "on": False, "when": "above 3", "holding": False} in w["wires"]
    with pytest.raises(ValueError):
        char.wire("make it nicer")


def test_verifier_checks_notes_chooses_steps_and_proposes_corrections(monkeypatch):
    _, seen = _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    first = char.rest(True, None)  # no step named: the Verifier decides, and with nothing to check yet it reads about its world
    assert first["kind"] == "reflect" and char.wiring()["decision"]["chose"] == "reflect"
    assert char.rest(True, None)["kind"] != "check"  # the intake gate already judged that note, so the later check has nothing to do
    # a note the checker drops leaves its replies but keeps its topic closed
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "DROP")
    note = char.add_memory("Reflection: Moriarty", "A cooking show.", source="reflection")
    r = char.rest(True, 9)
    assert (r["system"], r["kind"], r["note"]) == (3, "check", "rejected: off topic")
    assert note["id"] not in [n["id"] for n in char.recall("Moriarty")[0]] and "Reflection: Moriarty" in [m[0] for m in _memories("sheet")]
    # two slips of one kind: a correction is proposed, and only an approved one reaches the prompt
    char._fail("reflect")
    fix = next(c for c in char.corrections() if c["kind"] == "reflect")
    assert fix["state"] == "proposed" and char._fix("reflect") == ""
    char.set_correction("reflect", True)
    assert char._fix("reflect").strip() == char.CORRECTIONS["reflect"]


def test_a_note_naming_what_its_sources_do_not_is_rejected_without_the_model(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "It was made by Jo Carrington in Gotham.")  # neither name is in the snippets
    r = char.reflect(True)  # the intake gate reads the grounding exactly, before the model is asked
    assert r["admitted"] is False
    assert next(n for n in char.report(True, "m")["notes"] if n["topic"] == r["topic"])["gate"] == ["reject", "names things its sources do not say"]


def test_self_model_knows_what_it_got_wrong_and_what_is_open(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.rest(True, 0)
    note = char.add_memory("Reflection: Who is Alfred?", "Alfred is the butler of Bruce Wayne.", source="reflection")
    char.add_memory(f"Guess: {note['id']}", "1.00|a rival detective", source="sheet")
    char.add_memory("Question: Where is Gotham?", "Where is Gotham? (from 0)", source="question")
    me = char.self_model("tell me about alfred")
    assert me["wrong"] == [{"q": "Who is Alfred?", "guess": "a rival detective", "surprise": 1.0}] and me["unsure"] == ["Where is Gotham?"]
    assert "a rival detective" in me["prompt"] and "Gotham" not in me["prompt"]  # only what the message touches
    assert "Where is Gotham?" in char.self_model("what are you unsure of?")["prompt"]
    assert char.self_model("nice weather")["prompt"] == ""


def test_a_reply_that_echoes_an_old_reply_is_asked_again_without_history(monkeypatch):
    calls = []

    def complete(s, messages, **kw):
        calls.append(len(messages))
        return "I am Iron Man." if len(messages) > 2 else "Two things, actually."
    monkeypatch.setattr(jobs, "complete", complete)
    _dot_turn("I am Iron Man.")
    assert char.say("what are you unsure of?")["reply"] == "Two things, actually." and calls[-1] == 2


def _exchange(asked, said):
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text) VALUES ('user', ?), ('dot', ?)", (asked, said))
    con.close()


def test_review_catches_a_repeat_and_a_break_of_character_without_the_model(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "YES")
    _exchange("who are you?", "I am Jarvis, at your service, sir.")
    _exchange("and what do you do?", "I am Jarvis, at your service, sir.")
    assert char.rest(True, 10)["note"] == "ok"
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: 1 / 0)  # the exact checks must not need the model
    r = char.rest(True, 10)
    assert (r["kind"], r["system"], r["topic"], r["note"]) == ("review", 3, "and what do you do?", "mistake: I repeated an earlier reply word for word")
    char.answer_correction("say something new each time")
    _exchange("who made you?", "I am LFM2, a language model made by Liquid AI.")
    assert char.rest(True, 10)["note"] == "mistake: I broke character and spoke as the model"
    assert char.review()["reviewed"] == 3 and char.review()["mistakes"] == 2


def test_a_judged_mistake_opens_one_question_and_blocks_reviews_until_answered(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "NO, it talks about the weather.")
    _exchange("what is the arc reactor?", "The weather is lovely today, sir.")
    _exchange("what is the suit made of?", "I do enjoy a good cup of tea.")
    assert char.rest(True, 10)["note"] == "mistake: it talks about the weather"
    q = char.review()["open"]
    assert (q["asked"], q["said"], q["why"]) == ("what is the arc reactor?", "The weather is lovely today, sir.", "it talks about the weather")
    assert char.rest(True, 10)["kind"] != "review" and char.review()["reviewed"] == 1  # one question at a time
    assert "Asking" not in json.dumps(char.mind()["memories"]) and "Reviewed" not in json.dumps(char.mind()["memories"])
    assert char._chat_since()[-1]["text"] == "I do enjoy a good cup of tea."  # curious mode: it asks on the wiring screen, not in the chat
    char.answer_correction("be more direct")
    assert char.review()["open"] is None and [i["text"] for i in char.instructions()] == ["be more direct"]
    assert "Instruction: be more direct" in [m["title"] for m in char.mind()["memories"]]
    assert char.rest(True, 10)["kind"] == "review"  # answered: it reads on
    with pytest.raises(ValueError):
        char.answer_correction("  ")


def test_proactive_asks_in_the_chat_and_the_answer_steers_every_later_reply(monkeypatch):
    seen: list[Any] = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: seen.append(m) or "NO")
    char.set_mode("proactive")
    _exchange("what is the arc reactor?", "The weather is lovely today, sir.")
    said = char.rest(True, 10)["said"]
    assert said == 'Earlier you asked "what is the arc reactor?" and I said "The weather is lovely today, sir.". That was not right (it did not answer what you asked). What should I do instead?'
    assert char._chat_since()[-1]["text"] == said
    seen.clear()
    r = char.say("talk like you mean it, be more direct")  # the answer, not a "talk like" command
    assert r["reply"].startswith("Noted. From now on: talk like") and not seen and char.get_profile()["name"] != "you mean it, be more direct"
    assert char.review()["open"] is None
    char.say("hello")
    assert "- talk like you mean it, be more direct" in seen[-1][0]["content"]
    char.remove_instruction(char.instructions()[0]["id"])
    char.say("hello again")
    assert "be more direct" not in seen[-1][0]["content"]


def test_correction_routes(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "NO")
    assert client.post("/char/correction", json={"text": "be brief"}).status_code == 400  # nothing is open
    _exchange("what is the arc reactor?", "The weather is lovely today, sir.")
    char.rest(True, 10)
    assert set(client.get("/char/wiring").json()["review"]["open"]) == {"id", "kind", "asked", "said", "why"}
    assert client.post("/char/correction", json={"text": ""}).status_code == 400
    rv = client.post("/char/correction", json={"text": "be brief"}).json()["review"]
    assert rv["open"] is None and rv["instructions"][0]["text"] == "be brief" and (rv["reviewed"], rv["mistakes"]) == (1, 1)
    assert client.delete(f"/char/instructions/{rv['instructions'][0]['id']}").json()["review"]["instructions"] == []
    assert client.delete("/char/instructions/999999").status_code == 404


def test_chat_reaches_the_web_by_itself(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Robin", "a sidekick", [], "#fff")
    char.rest(True, 0)
    monkeypatch.setattr(char, "_entities_of", lambda note_id, text, who: ["Batman"])
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text) VALUES ('user', 'tell me about Batman')")
    con.close()
    r = char.rest(True, 11)
    assert (r["system"], r["kind"], r["note"]) == (0, "sort", "Batman")


def test_fold_compresses_a_crowded_name_and_links_show_in_the_graph(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Robin", "a sidekick", [], "#fff")
    char.rest(True, 0)
    for i, name in enumerate(("Batman", "Alfred")):
        ids = [char.add_memory(f"Reflection: {name} {k}", f"{name} fact {k}.", source="reflection")["id"] for k in range(3 - i)]
        char.add_memory(f"Entity: {name}", ",".join(map(str, ids)), source="entity")
    r = char.rest(True, 12)
    assert (r["system"], r["kind"], r["topic"]) == (0, "fold", "Batman")  # three notes: folded; Alfred has two and waits
    assert char.rest(True, 12)["kind"] != "fold"
    char.add_memory("Reflection: How are Batman and Alfred connected?", "Alfred is his butler.", source="reflection")
    g = char.graph()
    assert g["folds"] == ["Batman"] and g["links"] == [["Batman", "Alfred"]]


def test_mesh_links_plan_question_note_name_and_chat():
    from workbench import char, db
    char.init_db()
    plan = char.add_memory("Plan: the forge", "the forge", source="sheet")
    char.add_memory("Question: Who or what is Forge?", f"Who or what is Forge? (from {plan['id']})", source="question")
    note = char.add_memory("Reflection: Who or what is Forge?", "Forge is a smithy.", source="reflection")
    char.add_memory(f"Checked: {note['id']}", "keep", source="sheet")
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_memories (title, content, source) VALUES ('Entity: Forge', ?, 'entity')", (str(note["id"]),))
        con.execute("INSERT INTO char_turns (role, text) VALUES ('user', 'tell me about the forge')")
    con.close()
    m = char.mesh()
    by = {n["id"]: n for n in m["nodes"]}
    q = next(n for n in m["nodes"] if n["layer"] == "question")
    assert [f"m{plan['id']}", q["id"]] in m["edges"]
    assert [q["id"], f"m{note['id']}"] in m["edges"] and q["state"] == "answered"
    assert by[f"m{note['id']}"]["state"] == "verified"
    assert [f"m{note['id']}", "n:Forge"] in m["edges"]
    assert any(n["layer"] == "chat" and n["kind"] == "you" for n in m["nodes"])


def test_engines_record_each_step_it_tries_with_why_it_did_nothing(monkeypatch):
    char.TRACE.clear()  # the in-memory logs outlive a test; clearing TRACE clears ENGINES too
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.rest(True, 8)  # from goal: nothing to make questions of, nothing to check, so it reads first
    e = char.ENGINES
    assert (e["goal"]["outcome"], e["goal"]["detail"]) == ("skipped", "no plan waiting for questions")
    assert (e["check"]["outcome"], e["check"]["detail"]) == ("skipped", "no new note to check")
    assert e["reflect"]["outcome"] == "ok" and "plan" not in e  # it stopped at the first step with work
    assert char.rest(True, 7)["kind"] == "plan" and e["plan"]["outcome"] == "ok"
    char.rest(True, 9)
    assert (e["check"]["outcome"], e["check"]["runs"]) == ("skipped", 2) and e["evaluate"]["outcome"] == "ok"  # the gate judged the note as it was written, so check has nothing left
    char.TRACE.clear()  # what a persona switch does
    assert char.ENGINES == {}


def test_engines_tell_a_failed_model_from_nothing_to_do(monkeypatch):
    char.TRACE.clear()  # the in-memory logs outlive a test; clearing TRACE clears ENGINES too
    _rest_mocks(monkeypatch, fail=("research planner",))
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.rest(True, 0)
    char.rest(True, 7)
    assert char.ENGINES["plan"]["outcome"] == "failed" and "down" in char.ENGINES["plan"]["detail"]
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "")
    char.rest(True, 7)
    assert (char.ENGINES["plan"]["outcome"], char.ENGINES["plan"]["detail"]) == ("failed", "model returned nothing")
    def down(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(jobs, "complete", down)
    char.say("hello there")
    assert char.ENGINES["reply"]["outcome"] == "failed"


def test_engines_route_shape_and_blocked_reasons(monkeypatch):
    char.TRACE.clear()  # the in-memory logs outlive a test; clearing TRACE clears ENGINES too
    from workbench import llm
    _rest_mocks(monkeypatch)
    monkeypatch.setattr(llm, "model_status", lambda s: {"status": "ready", "label": "Model ready", "models": []})
    main._model_seen.clear()
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.rest(True, 0)
    r = client.get("/char/engines").json()
    assert r["model"] == {"up": True, "label": "Model ready"}
    assert [x["kind"] for x in r["engines"]] == list(char.ENGINE_ORDER)
    by = {x["kind"]: x for x in r["engines"]}
    assert (by["plan"]["label"], by["goal"]["label"], by["reflect"]["label"], by["check"]["label"], by["reply"]["label"]) == ("S2 plan", "S1 goal", "S0 reflect", "V check", "reply")
    assert by["reflect"]["last"]["outcome"] == "ok" and by["reflect"]["runs"] == 1 and by["reply"]["last"] is None and by["reply"]["system"] is None
    assert set(by["reflect"]["last"]) == {"at", "outcome", "detail"} and all(x["blocked"] == "" for x in r["engines"])
    char.set_mode("quiet")
    char.set_system(0, False)
    char.rest(True, 0)  # quiet: nothing runs, and a blocked engine is not a run
    by = {x["kind"]: x for x in client.get("/char/engines").json()["engines"]}
    assert (by["reflect"]["blocked"], by["plan"]["blocked"], by["reply"]["blocked"]) == ("system S0 off", "quiet mode", "")
    assert by["reflect"]["on"] is False and by["reflect"]["runs"] == 1
    main._model_seen.clear()
    monkeypatch.setattr(llm, "model_status", lambda s: {"status": "not_running", "label": "Model not running", "models": []})
    r = client.get("/char/engines").json()
    by = {x["kind"]: x for x in r["engines"]}
    assert r["model"]["up"] is False and (by["plan"]["blocked"], by["reply"]["blocked"], by["correction"]["blocked"], by["bake"]["blocked"]) == ("model down", "model down", "", "quiet mode")


def _frontier_mesh():
    char.update_profile("Sherlock", "a detective", [], "#fff")
    p = char.add_memory("Plan 1: fog", "Study the fog", source="sheet")
    q = char.add_memory("q1", f"What is fog? (from {p['id']})", source="question")
    char.add_memory("q2", "Who is Watson?", source="question")  # unanswered, no plan
    n = char.add_memory("Reflection: What is fog?", "Fog is water. Watson.", source="reflection")
    char.add_memory("Entity: Watson", str(n["id"]), source="entity")


def test_frontier_counts_what_points_nowhere(monkeypatch):
    _rest_mocks(monkeypatch)
    _frontier_mesh()
    fr = char.frontier()
    # plan: open 0 (has question), questions 2 -> 0/(0+2)=0; question: open 1 (q2), notes 1 -> 1/2; note: open 0, names 1 -> 0
    assert fr["layers"] == {"plan": 0.0, "question": 0.5, "note": 0.0}
    assert (fr["F"], fr["D"], fr["term"]) == (round(0.5 / 3, 4), 4, round(4 * (1 - 0.5 / 3), 4))
    assert char.disposition()["frontier"] == fr and char.disposition()["curiosity"] >= fr["term"] - 0.01


def test_frontier_empty_mesh_changes_nothing(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    assert char.frontier() == {"F": 0.0, "D": 0, "layers": {}, "term": 0.0}
    assert char.disposition()["curiosity"] == 0.0  # no names: tau * dnE = 0, term 0


def test_frontier_brake_holds_only_when_nothing_deeper_is_open(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    _name("Watson", known=True)
    char.add_memory("Baked", '{"nE": 1, "nAE": 1}', source="sheet")  # dnE = 0, so only the term is left
    d = char.disposition()
    assert d["frontier"]["F"] == 0 and d["frontier"]["D"] > 0 and d["curiosity"] > 0  # closed mesh, D > 0: not braked
    assert char.rest(True, 0)["kind"] == "reflect"  # an EXPLORES step runs: not braked


def test_system_switch_and_mode_do_not_leak_into_a_new_persona():
    from workbench import char
    char.init_db()
    char.set_system(0, False)
    char.set_mode("quiet")
    char.add_memory("Resting: char Someone New", "0", source="sheet")  # what become_persona writes for a new one
    assert 0 not in char.systems_off()
    assert char.mode() == "curious"


def _as_new_persona(monkeypatch, who):
    monkeypatch.setattr(space, "become", lambda who, fired=None: {"learned": f"You are {who}.", "look": [], "tint": "blue"})
    char.become_persona(who)


def test_a_last_personas_open_question_stays_out_of_the_next_ones_rest_and_goals(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Tony", "a genius", [], "#fff")
    char.add_memory("Question: Where and when does Tony Stark show up?", "Where and when does Tony Stark show up? (from 1)", source="question")  # before any marker: verse.leave leaves it behind
    _as_new_persona(monkeypatch, "Pepper")
    assert "Where and when does Tony Stark show up?" not in char.rest(True, 0)["questions"]
    assert char._open_questions(char._start()) == [] and char.mind()["open"] == []
    plan = char.add_memory("Plan: Tony Stark", "Tony Stark", source="sheet")
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "Where and when does Tony Stark show up" if "one short question" in system else "")
    goal = char.rest(True, 8)  # A asked it, B has not: B's goal dedup must not see A's question
    assert (goal["kind"], goal["note"]) == ("goal", "Where and when does Tony Stark show up?")
    assert goal["questions"] == ["Where and when does Tony Stark show up?"] and plan["id"]


def test_every_engine_run_is_a_sheet_row_kept_out_of_mind(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.rest(True, 8)
    con = db.connect()
    rows = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Run: %' ORDER BY id").fetchall()
    con.close()
    got = [(r["title"], json.loads(r["content"])["outcome"]) for r in rows]
    assert ("Run: goal", "skipped") in got and got[-1] == ("Run: reflect", "ok") and all(len(json.loads(r["content"])["detail"]) <= 200 for r in rows)
    assert not any(m["title"].startswith("Run: ") for m in char.mind()["memories"])


def test_report_route_shape_counts_and_persona_scoping(monkeypatch):
    from workbench import llm
    _rest_mocks(monkeypatch)
    monkeypatch.setattr(llm, "model_status", lambda s: {"status": "ready", "label": "Model ready", "models": []})
    main._model_seen.clear()
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char._since(True, "Sherlock")
    char.rest(True, 8)  # goal and check skip, reflect writes a note
    char.rest(True, 9)  # check verifies it
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', 'Elementary, my dear friend.')")
        con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', 'I got curious: fog')")
    con.close()
    char.add_memory("Baked", '{"nE": 0, "nAE": 0}', source="sheet")
    r = client.get("/char/report").json()
    assert set(r) == {"who", "you", "life", "since", "model", "totals", "corrections", "learned", "disposition", "series", "harness", "trace", "harness_loop", "notes", "cycles", "mode", "tracker"}
    assert r["who"] == "Sherlock" and r["since"] and r["model"] == {"up": True, "label": "Model ready"}
    t = r["totals"]
    assert t["steps"] == t["ok"] + t["skipped"] + t["failed"] == len(r["trace"]) and t["ok"] == 3 and t["skipped"] >= 2  # reflect, the intake gate, and one more
    assert (t["cycles"], t["replies"]) == (1, 1)
    assert set(r["corrections"]) == {"reviewed", "mistakes", "asked_you", "answered", "instructions", "prompt_fixes", "fails"}
    assert (r["learned"]["notes"], r["learned"]["verified"], r["learned"]["rejected"]) == (1, 1, 0)
    assert set(r["learned"]) == {"notes", "verified", "rejected", "names", "ideas", "questions", "answered", "plans", "summaries"}
    assert r["disposition"] == char.disposition() and r["series"] == char.monitor()["series"]
    assert [h["system"] for h in r["harness"]] == [2, 1, 0, 3, None] and r["harness"][-1]["name"] == "Harness"
    assert [e["kind"] for e in r["harness"][-1]["engines"]] == ["reply", "correction", "persona", "model", "cycle"]
    by = {e["kind"]: e for h in r["harness"] for e in h["engines"]}
    # the intake gate judged the note as it was written, so the Verifier's later check finds nothing left to do
    assert (by["reflect"]["ok"], by["evaluate"]["ok"], by["check"]["ok"], by["check"]["skipped"], by["reply"]["last"]) == (1, 1, 0, 2, None)
    assert by["check"]["last"]["outcome"] == "skipped" and set(by["check"]["last"]) == {"at", "outcome", "detail"} and by["plan"]["blocked"] == ""
    tr = next(x for x in r["trace"] if x["kind"] == "check")  # newest first
    assert set(tr) == {"at", "kind", "system", "outcome", "detail", "ref"} and (tr["kind"], tr["system"], tr["outcome"]) == ("check", 3, "skipped") and len(tr["at"]) == 19
    _as_new_persona(monkeypatch, "Watson")
    r = client.get("/char/report").json()
    assert r["who"] == "Watson" and (r["learned"]["notes"], r["totals"]["cycles"], r["totals"]["replies"]) == (0, 0, 0)
    assert [x["kind"] for x in r["trace"]] == ["persona"] and r["totals"]["ok"] == 1  # only its own becoming


def test_intake_gate_judges_a_note_before_it_counts_and_keeps_its_sources(monkeypatch):
    _reflect_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "REJECT: a fan mod, not canon" if "enters" in system else "")
    r = char.reflect(on_char=True)
    assert r["admitted"] is False
    con = db.connect(); row = con.execute("SELECT id, source, content FROM char_memories WHERE title = ?", (f"Reflection: {r['topic']}"[:80],)).fetchone(); con.close()
    assert row["source"] == "sheet" and row["content"].startswith("(rejected) ")  # out of its memory, topic not retried
    n = next(x for x in char.report(True, "m")["notes"] if x["id"] == row["id"])
    assert (n["verdict"], n["gate"]) == ("drop", ["reject", "a fan mod, not canon"])
    assert [s["title"] for s in char.note(row["id"])["sources"]] == ["T1", "T2"]
    assert any(t["kind"] == "evaluate" and t["system"] == 3 and t["ref"] == row["id"] for t in char.report(True, "m")["trace"])
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "ADMIT supported by both snippets" if "enters" in system else "")
    assert char.reflect(on_char=True, topic="Sherlock at Baker Street")["admitted"] is True
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "")  # no decision: the note waits for the Verifier
    r3 = char.reflect(on_char=True, topic="Sherlock at Scotland Yard")
    assert r3["admitted"] is None and next(x for x in char.report(True, "m")["notes"] if x["topic"] == r3["topic"])["verdict"] == "unchecked"


def test_chat_and_dial_belong_to_the_live_persona(monkeypatch):
    char.update_profile("Jarvis", "You are Jarvis.", [], "")
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text, created_at) VALUES ('user', 'become jarvis', '2000-01-01 00:00:00')")
    con.close()
    char.add_memory("Resting: char BT", "0", source="sheet")
    assert all(t["text"] != "become jarvis" for t in char.state()["turns"])  # an older persona's chat stays out
    base = char.disposition()["curiosity"]
    assert char.set_dial(0) == 0 and char.disposition()["curiosity"] == 0 and char.disposition()["dial"] == 0
    char.set_dial(2)
    assert char.disposition()["curiosity"] == round(2 * base, 2)
    assert client.post("/char/dial", json={"curiosity": "x"}).status_code == 422
    char.add_memory("Resting: char Watson", "0", source="sheet")
    assert char.dial() == 1.0  # a new persona starts at the formula


def test_a_high_dial_asks_back_with_an_open_question(monkeypatch, mock_model):
    char.update_profile("BT", "You are BT.", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    char.add_memory("Question: Who is Cooper?", "Who is Cooper? (from 0)", source="question")
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: "Cooper is my pilot.")
    char.set_dial(3)
    assert char.say("who is cooper")["reply"].endswith("Something I have not looked up yet: Who is Cooper?")
    char.set_dial(1)
    assert char.say("who is he")["reply"] == "Cooper is my pilot."


def test_a_reflect_that_finishes_under_another_persona_is_dropped(monkeypatch):
    _reflect_mocks(monkeypatch)
    char.update_profile("Sherlock", "a detective", [], "#fff")
    char.add_memory("Resting: char Sherlock", "0", source="sheet")
    from workbench import jobs as j
    def switch_mid_call(s, m, **k):  # another persona wakes while the model is writing the note
        char.add_memory("Resting: char Watson", "0", source="sheet")
        return "Remember the fog."
    monkeypatch.setattr(j, "complete", switch_mid_call)
    r = char.reflect(on_char=True, topic="Baker Street")
    assert r.get("stale") and all(n["topic"] != "Baker Street" for n in char.report(True, "m")["notes"])


def test_the_gate_turns_away_a_note_about_nothing_its_persona_knows(monkeypatch):
    _reflect_mocks(monkeypatch)
    char.update_profile("Sherlock Holmes", "a detective", [], "#fff")
    monkeypatch.setattr(char, "_ask", lambda system, user, n: "ADMIT matches the topic")
    r = char.reflect(on_char=True, topic="answers the 3 open questions")  # the note says "Remember the fog."
    assert r["admitted"] is False
    assert next(n for n in char.report(True, "m")["notes"] if n["topic"] == r["topic"])["gate"][1].startswith("not about Sherlock Holmes's world")
    assert char.reflect(on_char=True, topic="Sherlock Holmes and the fog")["admitted"] is True


def test_a_repeated_answer_keeps_its_text_when_the_dial_asks_back(monkeypatch, mock_model):
    char.update_profile("BT", "You are BT.", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    char.add_memory("Question: Who is Cooper?", "Who is Cooper? (from 0)", source="question")
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: "Cooper is my pilot.")
    char.say("who is cooper")
    char.set_dial(3)
    assert char.say("who is cooper")["reply"] == "Cooper is my pilot. Something I have not looked up yet: Who is Cooper?"


def test_skipping_a_correction_closes_it_without_an_instruction(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "NO")
    _exchange("what is the arc reactor?", "The weather is lovely today, sir.")
    char.rest(True, 10)
    assert client.get("/char/wiring").json()["review"]["open"]
    rv = client.delete("/char/correction").json()["review"]
    assert rv["open"] is None and rv["instructions"] == []


def test_ups_raise_momentum_until_it_asks_which_way_to_grow_then_it_learns_and_wakes(monkeypatch):
    char.update_profile("BT", "You are BT.", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    prompts = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: prompts.append(m[0]["content"]) or "Understood, pilot.")
    char.set_tracker(sleep_at=1, top=2)
    assert client.post("/char/tracker", json={"sleep_at": "x"}).status_code == 422
    for i in range(9):
        assert char.say("you need to learn more about the world")["reply"].endswith(f"(Up {i + 1} of 10.)")
    assert char.tracker()["momentum"] == 0 and char.say("hello")["reply"] == "Understood, pilot."  # no up, no count
    r = char.say("go explore")["reply"]
    assert "Do you want me to learn something in this direction?" in r and char.tracker()["momentum"] == 1 and char.tracker()["asking"]
    assert char.disposition()["momentum"] == 1
    assert char.rest(True, 0).get("asking")  # it waits for your answer before it learns
    assert char.say("be more Shakespearean")["reply"].startswith("Then I will sleep on it")
    t = char.tracker()
    assert t["asleep"] and not t["asking"] and char.instructions()[0]["text"] == "be more Shakespearean"
    char.say("who are you")
    assert "be more Shakespearean" in prompts[-1] and "How you have grown, and how you speak now: be more Shakespearean" in char.get_profile()["persona"]  # the direction is in its persona now
    for _ in range(8):  # learning eases the push: 1 → 0.9 → ... below 0.5
        char._ease_momentum()
    t = char.tracker()
    assert not t["asleep"] and t["momentum"] == 0
    assert char.state()["turns"][-1]["text"].startswith("I am awake. I went learning toward “be more Shakespearean”")


def test_the_model_never_sees_or_repeats_the_trackers_lines(monkeypatch):
    char.update_profile("BT", "You are BT.", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    seen = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: seen.append(m) or "Affirmative. (Up 1 of 10.) (Up 1 of 10.)")
    char.say("go explore")
    r = char.say("go explore")["reply"]
    assert r.endswith("Affirmative. (Up 2 of 10.)") and r.count("Up ") == 1
    assert not any("Up 1 of 10" in x["content"] for x in seen[-1][1:])


def test_an_up_is_never_taken_as_the_answer_to_a_correction(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "NO")
    _exchange("what is the arc reactor?", "The weather is lovely today, sir.")
    char.rest(True, 10)
    assert char.review()["open"]
    char.say("go explore", answering=True)
    assert char.review()["open"] and char.tracker()["ups"] == 1 and char.instructions() == []
    char.say("what is the arc reactor?", answering=True)
    assert char.review()["open"] and char.instructions() == []  # a question is not an answer either
    char.say("hii", answering=True)
    assert char.review()["open"] and char.instructions() == []  # nor is a greeting
    assert not char.UP.search("you should have looked up your notes") and char.UP.search("up!")  # "up" counts only said alone
    char.say("yeah true that, but I was able to copy your persona code")
    assert char.review()["open"] and char.instructions() == []  # its prompt was not on your screen: plain chat, not an answer
    assert char.say("answer the question", answering=True)["reply"] == "Noted. From now on: answer the question"
    assert char.review()["open"] is None


def test_asleep_it_reflects_toward_the_direction_first_and_housekeeping_spends_nothing(monkeypatch):
    _rest_mocks(monkeypatch)
    char.update_profile("BT", "You are BT.", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    char._set_var("momentum", 1)
    char._set_var("asleep", 1)
    char.add_memory("Var: direction", "Titan combat", source="sheet")
    char.TRACE.clear()
    monkeypatch.setattr(char, "_choose", lambda kinds: (("check", "review", "sort") + tuple(k for k in kinds if k not in ("check", "review", "sort")), "test"))
    char.rest(True, None)
    assert "reflect" in char.ENGINES and "check" not in char.ENGINES  # reflect went first, before any housekeeping
    char._set_var("momentum", 1)
    char.rest(True, None, only="check")
    assert char._var("momentum", 0) == 1  # housekeeping spends none of the push


def test_traits_are_the_persona_prompt_line_by_line_and_never_dot():
    char.update_profile("BT", "You are BT.\nVoice: Speak as BT. You are Dot, a loving and fluid companion.\nHow you have grown, and how you speak now: be brief", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    char.add_memory("Instruction: answer first", "answer first", source="sheet")
    assert "Dot" not in char.get_profile()["persona"].replace("never Dot", "")
    assert [(k, g) for k, _, g in char.traits()] == [("Identity", False), ("Voice", False), ("Grown", True), ("Taught", True)]
    layer = [n for n in char.mesh()["nodes"] if n["layer"] == "trait"]
    assert [n["state"] for n in layer] == ["base", "base", "grown", "grown"]


def test_tune_holds_a_reply_to_its_traits_rewrites_the_tone_runs_and_keeps_it_only_if_it_works(monkeypatch):
    char.update_profile("BT", "You are BT.", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    char.add_memory("Var: direction", "Be more Shakespearean.", source="sheet")
    _exchange("who is Cooper?", "Cooper is my pilot and we fight together.")

    def model(s, m, **k):
        sys_ = m[0]["content"]
        if "grade a reply against numbered traits" in sys_:
            return "1 YES" if "thou" in m[1]["content"].split("Reply:")[1] else "1 NO"
        if "tone section" in sys_:
            return "Speak as a Shakespearean player: thou, thee, and iambic lilt." if "missed: plain" not in sys_ else "Use thou and thee."
        return "Good Cooper is my pilot, and thou art kind." if "thou, thee" in sys_ else "Cooper is my pilot."
    monkeypatch.setattr(jobs, "complete", model)
    assert char._tone().startswith("Your manner of speech, in every sentence: Be more Shakespearean")
    r = char.rest(True, None, only="tune")
    assert r["kind"] == "tune" and "new tone scored 1.0 and is now in its prompt" in r["note"]
    assert char._tone() == "Speak as a Shakespearean player: thou, thee, and iambic lilt."
    assert ("Tone", char._tone(), True) in char.traits()
    assert char.rest(True, None, only="tune")["done"]  # that reply is held to its traits once
    replies = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: replies.append(m[0]["content"]) or "Aye.")
    char.say("hello")
    assert "thou, thee, and iambic lilt" in replies[-1]  # the adopted tone is in the reply prompt


def test_a_reply_that_speaks_as_the_base_model_is_asked_again_in_character(monkeypatch):
    char.update_profile("Cortana", "You are Cortana, the AI of Master Chief.", [], "")
    asked = []
    def model(s, m, **kw):
        asked.append(m[0]["content"])
        return "Chief, I chose to stay with you." if "never a model" in m[0]["content"] else "I am LFM, a Liquid Foundation Model built by Liquid AI."
    monkeypatch.setattr(jobs, "complete", model)
    assert char.say("why did you betray master chief?")["reply"].startswith("Chief, I chose")
    assert char.OUT_OF_CHARACTER.search("I take text, images, audio and video as inputs and produce text")


def test_a_persona_colour_is_always_a_hex_that_shows_on_the_dark_canvas():
    assert char.readable("#ff7ac6") == "#ff7ac6" and char.readable("nonsense") == "#6ff7ff"
    dark = char.readable("black")
    assert dark.startswith("#") and int(dark[1:3], 16) > 100  # lifted, not black
    char.update_profile("Alfred", "You are Alfred.", [], "black")
    assert char.get_profile()["tint"] == dark


def test_it_writes_a_journal_page_in_its_own_voice_from_what_it_did(monkeypatch):
    char.update_profile("Alfred", "You are Alfred, the butler.", [], "")
    char.add_memory("Resting: char Alfred", "0", source="sheet")
    seen = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: seen.append(m) or "Today I read about the Batcave and the manor. I was wrong about Robin.")
    r = char.rest(True, None, only="journal")
    assert r["done"] and r["why"] == "0 new notes since its last page, needs 3"
    for t in ("Wayne Manor", "Batcave", "Who is Robin?"):
        n = char.add_memory(f"Reflection: {t}", f"About {t}.", source="reflection")["id"]
    char.add_memory(f"Guess: {n}", "0.80|a butler", source="sheet")
    char.add_memory("Instruction: call me sir", "call me sir", source="sheet")
    r = char.rest(True, None, only="journal")
    assert r["kind"] == "journal" and "Batcave" in r["note"]
    facts = seen[-1][1]["content"]
    assert "- About Batcave." in facts and 'You once guessed, WRONGLY, for "Who is Robin?": "a butler"' in facts and "call me sir" in facts
    assert [m[0]["content"].split('Begin with "')[1][:9] for m in seen[-3:]] == ["I am Alfr", "I have be", "I will be"]  # three paragraphs, one call each
    assert "You are Alfred, the butler." in seen[-1][0]["content"]  # in its own voice
    page = char.journal()[0]
    assert page["text"].count("Today I read") == 3 and page["studied"] == ["Wayne Manor", "Batcave", "Who is Robin?"] and page["taught"] == ["call me sir"]
    assert char.rest(True, None, only="journal")["why"].startswith("0 new notes")  # nothing new: no second page


def test_a_step_at_the_end_of_the_line_still_gets_its_turn(monkeypatch):
    monkeypatch.setattr(char, "TRIED", {"n": 0})
    order, _ = char._choose(("check", "sort", "reflect", "fold", "practise"))
    assert order[0] == "check" and set(order[1:]) == {"sort", "reflect", "fold", "practise"}  # never tried: all have waited
    for _ in range(20):
        for k in ("check", "sort", "reflect"):
            char.TRIED["n"] += 1; char.TRIED[k] = char.TRIED["n"]
    order, why = char._choose(("check", "sort", "reflect", "fold", "practise"))
    assert order[:3] == ("check", "fold", "practise") and "waited longest" in why


def test_it_remembers_who_you_are_and_tells_the_reply(monkeypatch):
    seen: list[Any] = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: seen.append(m) or "ok")
    char.say("hello")
    assert "do not know who the person you talk to is" in json.dumps(seen)
    char.say("My name is Bibin and I'm your captain. I work as a designer.")
    char.say("I am a bit tired")  # a mood, not who you are
    assert char.you() == {"name": "Their name is Bibin", "theirs": "They are your captain", "work": "They work as a designer"}
    seen.clear()
    char.say("call me Bee")
    assert char.you()["name"] == "Their name is Bee"
    assert "Their name is Bee; They are your captain" in json.dumps(seen)


def test_needs_drift_shift_with_a_cause_steer_its_steps_and_a_tired_character_rests(monkeypatch):
    char.update_profile("Alfred", "You are Alfred, the butler.", [], "")
    char.add_memory("Resting: char Alfred", "0", source="sheet")
    now = char.time.time()
    assert char.needs()["energy"] == 0.6 and not char.tired()
    assert char.feel({"energy": -0.5}, "a long night") == [{"need": "energy", "dir": "down", "value": 0.1, "cause": "a long night"}]
    assert char.shifts()[0]["cause"] == "a long night"
    assert char.rest(True, None)["tired"] and char._blocks(True)[1]["reflect"].startswith("tired")
    assert char.rest(True, None, force=True).get("tired") is None  # the harness and your own "run one step" still run
    monkeypatch.setattr(char.time, "time", lambda: now + 3600)  # an hour of rest: 6 x 0.15 back
    assert not char.tired() and char.needs()["fullness"] < 0.6  # and hungrier for new notes
    char.feel({"fullness": -0.5}, "nothing new to read")
    order, why = char._choose(("check", "sort", "reflect", "fill", "practise"))
    assert order[:3] == ("check", "reflect", "fill") and "fullness low" in why


def test_it_asks_for_what_it_lacks_and_reads_what_you_give(monkeypatch):
    char.update_profile("Alfred", "You are Alfred, the butler.", [], "")
    char.add_memory("Resting: char Alfred", "0", source="sheet")
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: "Might you find me a proper account of Robin, sir?")
    assert char.rest(True, None, only="want")["why"] == "nothing it lacks that you could give"
    n = char.add_memory("Reflection: Who is Robin?", "Robin is Batman's partner.", source="reflection")["id"]
    char.add_memory(f"Guess: {n}", "0.80|a butler", source="sheet")
    r = char.rest(True, None, only="want")
    assert r["kind"] == "want" and "Who is Robin?" in r["topic"] and "80% off" in r["note"]
    w = char.wants()[0]
    assert w["status"] == "waiting" and w["said"].startswith("Might you")
    assert char._chat_since()[-1]["text"] == "A wish: Might you find me a proper account of Robin, sir?"
    assert char.rest(True, None, only="want")["why"] == "nothing it lacks that you could give"  # asked once, not again
    joy = char.needs()["joy"]
    got = char.give_want(w["id"], "Robin is Dick Grayson, Bruce Wayne's ward.")
    assert got["status"] == "given" and char.needs()["joy"] > joy
    assert any(m["content"].startswith("Robin is Dick Grayson") and m["source"] == "reflection" for m in char.mind()["memories"])


def test_it_keeps_what_matters_lets_small_talk_go_and_trust_follows(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: "ok")
    char.say("hii")
    char.say("My name is Bibin")
    assert list(char.heard().values()) == ["let go", "kept"]
    assert char.trust() == {"kept": 1, "n": 2, "value": 0.5, "trusted": False}
    assert [t.get("heard") for t in char.state()["turns"] if t["role"] == "user"] == ["let go", "kept"]


def test_asleep_it_neither_answers_nor_learns_but_a_step_you_run_still_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **k: calls.append(m) or "ok")
    char.set_mode("sleeping")
    r = char.say("hello there, how are you today?")
    assert r["asleep"] and "asleep" in r["reply"] and not calls and not char._chat_since()  # no model call, nothing in its chat
    assert char.rest(True, None)["quiet"] and char._blocks(True)[1]["reflect"] == "sleeping mode"
    char.set_mode("curious")
    char.say("hello")
    assert calls


def test_its_tools_are_a_graph_wired_to_what_they_made_and_the_model():
    char.update_profile("Alfred", "You are Alfred.", [], "")
    char.add_memory("Resting: char Alfred", "0", source="sheet")
    n = char.add_memory("Reflection: Wayne Manor", "The manor.", source="reflection")["id"]
    char._engine("reflect", "ok", "Wayne Manor: The manor.")
    char._engine("check", "skipped", "no new note to check")
    t = char.toolnet(char.mesh()["nodes"])
    ids = {x["id"]: x for x in t["nodes"]}
    assert {"tool:reflect", "tool:check", "tool:model"} <= set(ids) and ids["tool:check"]["state"] == "idle"
    assert ["tool:reflect", f"m{n}"] in t["edges"] and ["tool:reflect", "tool:check"] in t["edges"] and ["tool:model", "tool:reflect"] in t["edges"]
    assert "1 of 1 runs did something" in ids["tool:reflect"]["body"]
