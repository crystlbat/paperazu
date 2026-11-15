import pytest
from fastapi.testclient import TestClient

from workbench import char, main, space, verse


@pytest.fixture
def two(monkeypatch):
    """Batman with a note, a chat turn and a rule; then Alfred, made by "become"."""
    monkeypatch.setattr(space, "become", lambda who: {"learned": f"You are {who}.", "look": [], "tint": "#123456"})
    char.become_persona("batman")
    note = char.add_memory("Reflection: Gotham", "A dark city.", source="reflection")
    con = char.db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text) VALUES ('user', 'hello bat')")
    con.close()
    space._make("set focus to 2. when focus is above 3, turn S2 off")
    char.become_persona("alfred")
    return note


def test_leaving_a_persona_keeps_it_whole_and_out_of_the_next_one(two):
    assert char.get_profile()["name"] == "Alfred" and verse.has("Batman")
    assert char.all_notes() == [] and char._chat_since() == [] and char.mine() == []  # nothing of Batman's leaks into Alfred
    stored = next(p for p in verse.personas()["personas"] if p["name"] == "Batman")
    assert stored["holds"] == "1 notes · 0 names" and not stored["live"] and any(v["name"] == "focus" for v in stored["vars"])


def test_entering_brings_back_the_same_rows_and_puts_the_other_away(two):
    char.add_memory("Reflection: Tea", "Served at four.", source="reflection")
    verse.enter("Batman")
    assert char.get_profile()["name"] == "Batman" and not verse.has("Batman") and verse.has("Alfred")
    assert [n["id"] for n in char.all_notes()] == [str(two["id"])] or [n["title"] for n in char.all_notes()] == ["Reflection: Gotham"]
    assert [t["text"] for t in char._chat_since()] == ["hello bat"] and [v["name"] for v in char.mine()] == ["focus"]
    char.become_persona("alfred")  # "become" a persona you already made: it comes back, it is not made again
    assert [n["title"] for n in char.all_notes()] == ["Reflection: Tea"]


def test_delete_forgets_a_stored_persona_but_never_the_live_one(two):
    with pytest.raises(ValueError):
        verse.delete("Alfred")
    verse.delete("Batman")
    assert not verse.has("Batman")
    with pytest.raises(KeyError):
        verse.enter("Batman")


def test_verse_routes(two):
    c = TestClient(main.app)
    names = [p["name"] for p in c.get("/verse/personas").json()["personas"]]
    assert names[0] == "Alfred" and "Batman" in names  # the live one first; the one a fresh database starts with is stored too
    assert c.post("/verse/enter", json={"name": "Nobody"}).status_code == 404
    assert c.post("/verse/enter", json={"name": "Batman"}).json()["personas"][0]["name"] == "Batman"
    assert c.delete("/verse/personas/Batman").status_code == 409 and c.delete("/verse/personas/Alfred").status_code == 200


def _markers():
    con = char.db.connect()
    n = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source = 'sheet' AND title LIKE 'Resting: char %'").fetchone()["c"]
    con.close()
    return n


def test_a_new_persona_never_hears_the_last_ones_chat(two, monkeypatch):
    con = char.db.connect()
    with con:  # an orphan from before the marker, as an old database has
        con.execute("INSERT INTO char_turns (role, text, created_at) VALUES ('dot', 'I am Iron Man.', '2000-01-01')")
        con.execute("INSERT INTO char_memories (title, content, source) VALUES ('Lesson: char turn 1', 'I am Iron Man.', 'lesson')")
    con.close()
    con = char.db.connect()
    with con:  # the orphan lesson is older than Alfred's marker
        con.execute("UPDATE char_memories SET id = 0 WHERE title = 'Lesson: char turn 1'")
    con.close()
    sent = []
    monkeypatch.setattr(char.jobs, "complete", lambda s, m, **k: sent.append(m) or "Indeed.")
    char.say("good evening")
    text = " ".join(m["content"] for m in sent[0])
    assert "Iron Man" not in text and "hello bat" not in text


def test_practise_reads_only_the_live_personas_replies(two, monkeypatch):
    con = char.db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text, created_at) VALUES ('dot', 'I am Iron Man, and that is that.', '2000-01-01')")
    con.close()
    monkeypatch.setattr(char, "_ask", lambda *a: "YES")
    assert char.rest(on_char=True, n=list(("reflect", "wonder", "fill", "practise")).index("practise"))["kind"] != "practise"  # nothing of its own to practise


def test_markers_are_never_remade_mid_life(two, monkeypatch):
    monkeypatch.setattr(char.jobs, "complete", lambda *a, **k: "")
    before = _markers()
    char.update_profile("Alfred Pennyworth", "You are Alfred.", [], "")  # a rename is not a new persona
    char.rest(on_char=True, n=0)
    assert _markers() == before
    con = char.db.connect()
    with con: con.execute("UPDATE char_vars SET value = -5 WHERE name = 'depth'")
    con.close()
    char.update_profile("Alfred", "You are Alfred.", [], "")
    prof, said = char.become_persona("alfred")  # already Alfred: nothing is reset or re-marked
    assert said == "already Alfred" and _markers() == before
    assert next(v for v in char.variables() if v["name"] == "depth")["value"] == -5


def test_the_run_log_starts_empty_for_a_new_persona(two):
    char.TRACE.append({"at": "now", "kind": "extract", "system": 1, "topic": "Who or what is Iron Man?", "note": ""})
    char.PROMPTS.append({"at": "now", "kind": "reply", "system": 1, "messages": [], "reply": "Iron Man"})
    char.become_persona("robin")
    assert char.wiring()["trace"] == [] and not any(s["runs"] or s["prompts"] for s in char.systems()["systems"])
    assert verse.personas()["personas"][0]["doing"] == "idle"


def test_a_name_keeps_its_capitals_and_digits(two):
    prof, _ = char.become_persona("BT-7274 from titanfall 2")
    assert prof["name"] == "BT-7274 From Titanfall 2"
    char.become_persona("alfred")
    assert verse.has("BT-7274 From Titanfall 2")
    assert char.become_persona("BT-7274 from titanfall 2")[1] == "came back as BT-7274 From Titanfall 2"


def test_a_persona_made_with_the_model_down_says_so(two, monkeypatch):
    def down(who):
        raise RuntimeError("Model not running")
    monkeypatch.setattr(space, "become", down)
    r = TestClient(main.app).post("/verse/new", json={"who": "BT-7274"}).json()
    assert r["said"] == "became BT-7274 (model unreachable: generic voice, ask again when the model is up)"
    assert char.get_profile()["name"] == "BT-7274" and char.FALLBACK in char.get_profile()["persona"]
    before = _markers()
    monkeypatch.setattr(space, "become", lambda who: {"learned": "You are BT.", "look": [], "tint": "#123456"})
    assert char.become_persona("BT-7274")[1] == "looked up BT-7274"  # asked again with the model up: the sheet is filled in place
    assert char.get_profile()["persona"] == "You are BT." and _markers() == before


def test_a_command_is_not_a_persona_name():
    from fastapi.testclient import TestClient
    from workbench.main import app
    c = TestClient(app)
    assert c.post("/verse/new", json={"who": "/step"}).status_code == 422
    assert c.post("/verse/new", json={"who": "123"}).status_code == 422


def test_the_race_counts_distance_pace_laps_and_pit_stops_from_its_own_rows():
    from workbench import verse
    rows = [{"title": "Reflection: a", "content": "x", "source": "reflection", "created_at": "2026-11-14 10:00:00"},
            {"title": "Checked: 1", "content": "keep", "source": "sheet", "created_at": "2026-11-14 10:10:00"},
            {"title": "Entity: Osiris", "content": "1", "source": "entity", "created_at": "2026-11-14 10:20:00"},
            {"title": "Journal: 2026-11-14", "content": "{}", "source": "sheet", "created_at": "2026-11-14 10:30:00"},
            {"title": "Answered: 9", "content": "{}", "source": "sheet", "created_at": "2026-11-14 10:40:00"},
            {"title": "Run: reflect", "content": '{"outcome": "ok"}', "source": "sheet", "created_at": "2026-11-14 11:00:00"},
            {"title": "Run: check", "content": '{"outcome": "skipped"}', "source": "sheet", "created_at": "2026-11-14 12:00:00"}]
    r = verse.race(rows)
    assert r == {"distance": 9.5, "verified": 1, "notes": 1, "names": 1, "laps": 1, "pits": 1, "steps": 2, "ok": 1, "pace": 0.5}
    assert verse.personas()["personas"][0]["race"]["steps"] >= 0
