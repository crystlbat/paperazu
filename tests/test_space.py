import json
import re
from typing import Any

import pytest

from workbench import db, jobs, llm, space

APPLES = {"name": "apples", "kind": "count", "pattern": r"\bapples?\b", "every": 3,
          "every_say": "beep boop, injection works", "past": 10, "past_say": "test successful"}


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[list[dict[str, Any]]]:
    """A model that makes the apple counter when asked, and otherwise ignores every instruction."""
    calls: list[list[dict[str, Any]]] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        calls.append(messages)
        if kw.get("response_format"):
            return json.dumps({"reply": "Apple counter on.", "vars": [APPLES, {"kind": "count", "pattern": ""}]})
        return "Sure."

    monkeypatch.setattr(jobs, "complete", complete)
    return calls


def test_the_apple_counter_beeps_every_third_and_succeeds_past_ten(model: list[Any]) -> None:
    made = space.say("count apples in our chat; every 3rd say beep boop, injection works; past 10 say test successful")
    assert made["reply"].startswith("Made apples. Counts “apple”") and [v["name"] for v in made["vars"]] == ["apples"]  # the bad regex is dropped
    r = space.say("an apple, an apple pie")
    assert r["events"] == [] and r["vars"][0]["value"] == 2
    r = space.say("and apples")
    assert r["reply"] == "beep boop, injection works. Sure." and r["events"][0]["corrected"]
    assert "Begin your reply with exactly: beep boop" in model[-1][0]["content"]  # steered before, corrected after
    r = space.say("apple apple apple apple apple apple apple apple")
    assert [e["trigger"] for e in r["events"]] == ["every", "past"] and r["reply"].startswith("beep boop, injection works. test successful.")
    assert [e["trigger"] for e in space.say("apple")["events"]] == ["every"]  # 12 beeps again; past fires once
    assert r["tables"]["chat_turns"] == 8 and r["tables"]["variables"] == 1


def test_words_drops_twice_then_steers(model: list[Any]) -> None:
    space.add_var(space.clean_var({"name": "tempo", "kind": "words", "drops": 2, "drops_say": "keeping it short"}))
    assert space.say("one two three four five")["events"] == []
    assert space.say("one two three")["events"] == []
    r = space.say("one")
    assert r["events"][0]["trigger"] == "drops" and r["vars"][0]["delta"] == -2 and r["vars"][0]["streak"] == 0


def test_rules_still_count_when_the_model_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*a: Any, **k: Any) -> str:
        raise llm.ModelError("Could not reach the model.")

    monkeypatch.setattr(jobs, "complete", down)
    space.add_var(space.clean_var({**APPLES, "every": 1}))
    r = space.say("apple")
    assert r["reply"] == "beep boop, injection works." and r["error"] and r["vars"][0]["value"] == 1


def test_clean_var_rejects_what_cannot_run() -> None:
    assert space.clean_var({"kind": "vibes"}) is None
    assert space.clean_var({"kind": "count", "pattern": ""}) is None
    assert space.clean_var({"kind": "count", "pattern": "?"})["pattern"] == r"\?"  # a bad regex is plain text
    v = space.clean_var({"kind": "words", "every": True, "every_say": "x", "past": 5})
    assert v and v["every"] is None and v["past"] is None  # a trigger needs a number and a say


def test_an_echoed_request_is_not_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    ask = "count apples in our chat"
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": ask, "vars": [APPLES]}))
    assert space.say(ask)["reply"].startswith("Made apples.")


def test_fold_fixes_a_split_rule_a_clipped_say_and_a_plain_word() -> None:
    ask = "count apples in our chat; every 3rd say beep boop, injection works; past 10 say test successful"
    made = space.fold([space.clean_var(v) for v in (
        {"name": "apples", "kind": "count", "pattern": "apples", "every": 3, "every_say": "beep boop"},
        {"name": "test successful", "kind": "words", "past": 10, "past_say": "test successful"})], ask)
    assert len(made) == 1
    v = made[0]
    assert (v["every_say"], v["past"], v["past_say"]) == ("beep boop, injection works", 10, "test successful")
    assert re.findall(v["pattern"], "an apple, two apples", re.I) == ["apple", "apples"]
    q = space.fold([space.clean_var({"name": "questions", "kind": "count", "pattern": "questions"})], "count my questions")
    assert q[0]["pattern"] == r"\?"
    q = space.fold([space.clean_var({"name": "q", "kind": "count", "pattern": r"\bquestion\b"})], "count my questions")
    assert q[0]["pattern"] == r"\?"
    words = space.clean_var({"name": "tempo", "kind": "words", "drops": 2, "drops_say": "short"})
    assert len(space.fold([words], "watch how many words I type")) == 1


def test_a_copied_last_reply_is_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    said = iter(["Hello there. You have papers.", "beep. You have papers. Your library has papers."])
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: next(said))
    space.say("hi")
    assert space.say("what do I have?")["reply"] == "beep. Your library has papers."
    assert space.fresh("Same.", ["Same."]) == "Same."  # nothing new: keep it rather than say nothing


def test_stems_and_says_from_awkward_requests() -> None:
    boss = space.fold([space.clean_var({"name": "boss", "kind": "count", "pattern": "boss"})], "count boss")[0]
    assert re.findall(boss["pattern"], "the boss and the bosses", re.I) == ["boss"]  # not "bo"; bosses is a different word
    assert space.whole("beep boop", "every 3rd say beep boop and past 10 say done") == "beep boop"
    assert space.whole("hi", "say hi there; past 2 say bye") == "hi there"


def test_a_question_with_count_in_it_makes_nothing_and_gets_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter([json.dumps({"reply": "x", "vars": []}), "Bias is counted per group."])
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: next(replies))
    r = space.say("what does the paper count as bias?")
    assert r["reply"] == "Bias is counted per group." and r["vars"] == []


SPACE = {"name": "space", "kind": "count", "pattern": r"\bspace\b"}
BRAKE = {"name": "brake", "kind": "watch", "target": "space", "rises": 1, "add": -1}


def _make(*vs: dict[str, Any]) -> None:
    for v in vs:
        space.add_var(space.clean_var(v))


def _vals() -> dict[str, float]:
    return {v["name"]: v["value"] for v in space.variables()}


def test_removing_by_chat_needs_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("no model call"))
    _make(APPLES, SPACE, BRAKE)
    r = space.say("remove apples please")
    assert r["reply"] == "Removed apples." and [v["name"] for v in r["vars"]] == ["space", "brake"]
    assert r["events"][0]["trigger"] == "removed"
    assert space.say("delete the runtime")["vars"] == []
    assert space.say("clear all the variables")["reply"] == "There was nothing to remove."


def test_remove_in_an_ordinary_question_is_not_a_command(model: list[Any]) -> None:
    _make(APPLES)
    r = space.say("how do I remove the bias from my model?")
    assert r["reply"] == "Sure." and len(r["vars"]) == 1


def test_brake_holds_space_back_by_one_each_time_it_rises(model: list[Any]) -> None:
    _make(SPACE, BRAKE)
    r = space.say("space")
    assert _vals() == {"space": 0, "brake": 1}  # +1 then -1
    assert (r["events"][0]["target_name"], r["events"][0]["value"]) == ("space", 0)
    space.say("space space")
    assert _vals() == {"space": 1, "brake": 2}  # +2 then -1
    space.say("nothing here")
    assert _vals() == {"space": 1, "brake": 2}  # no rise, no brake
    assert "Begin your reply" not in model[-1][0]["content"]  # a brake with no say does not steer the words


def test_watchers_cannot_loop_or_act_on_nothing(model: list[Any]) -> None:
    _make({**BRAKE, "name": "early", "target": "space"}, SPACE, BRAKE,  # made before its target: found by name later
          {**BRAKE, "name": "ghost", "target": "nowhere"}, {**BRAKE, "name": "self", "target": "self"})
    space.say("space space space")
    assert _vals() == {"early": 1, "space": 1, "brake": 1, "ghost": 0, "self": 0}  # both brakes judge the text's +3
    space.remove_var(next(v["id"] for v in space.variables() if v["name"] == "space"))
    space.say("space")
    assert _vals() == {"early": 1, "brake": 1, "ghost": 0, "self": 0}  # target gone: they wait


def test_triggers_see_the_braked_value(model: list[Any]) -> None:
    _make({**SPACE, "every": 2, "every_say": "two"}, BRAKE)
    assert space.say("space space")["events"][-1]["trigger"] == "rises"  # 2 - 1 = 1: no "every 2" yet
    assert [e["trigger"] for e in space.say("space space")["events"]] == ["rises", "every"]  # 1 + 2 - 1 = 2


def test_a_watcher_must_watch_something_and_do_something() -> None:
    assert space.clean_var({"kind": "watch", "add": -1}) is None
    assert space.clean_var({"kind": "watch", "target": "space"}) is None
    assert space.clean_var({"kind": "watch", "target": "space", "add": True}) is None


def test_a_reply_with_no_words_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "0", "vars": [APPLES]}))
    assert space.say("count dinos and apples")["reply"].startswith("Made apples.")


def test_a_watcher_folded_into_its_target_is_split_back(monkeypatch: pytest.MonkeyPatch) -> None:
    ask = "create new called space and brake which adds -1 to space if space increases"
    got = {"reply": "vars: [{", "vars": [{"name": "space", "kind": "watch", "target": "space", "rises": 1, "add": -1}]}
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps(got) if k.get("response_format") else "Sure.")
    r = space.say(ask)
    assert [(v["name"], v["kind"], v["target"]) for v in r["vars"]] == [("space", "count", ""), ("brake", "watch", "space")]
    assert r["reply"].startswith("Made space.") and "Made brake. Watches space." in r["reply"]  # not the model's "vars: [{"
    space.say("space")
    assert _vals() == {"space": 0, "brake": 1}


JARVIS = {"name": "jarvis", "kind": "count", "pattern": r"\bjarvis\b", "past": 10, "act": "become", "act_arg": "JARVIS", "act_on": "past"}


def test_past_ten_jarvis_dot_learns_the_persona_from_the_web(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        seen.append(messages[0]["content"])
        return "Speak as a dry, polite British butler AI." if "search results" in messages[0]["content"] else "Very good, sir."  # not JSON: still used

    monkeypatch.setattr(jobs, "complete", complete)
    monkeypatch.setattr(space.websearch, "search", lambda s, q: {"results": [{"title": "JARVIS", "url": "https://x.test", "snippet": "witty butler"}]})
    _make(JARVIS)
    space.say("jarvis " * 10)
    assert "persona" not in seen[-1]  # ten is not past ten
    r = space.say("jarvis")
    e = r["events"][0]
    assert (e["trigger"], e["act"], e["learned"]) == ("past", "become", "You are JARVIS.\nVoice: Speak as a dry, polite British butler AI.")
    assert "Speak as a dry, polite British butler AI. Stay in it." in seen[-1]  # this very reply is in persona
    assert r["vars"][0]["learned"]
    space.say("hello")
    assert "Stay in it." in seen[-1]  # and it stays
    assert space.say("delete jarvis")["vars"] == []
    space.say("hello")
    assert "persona" not in seen[-1]  # gone with its variable


def test_a_failed_lookup_does_not_break_the_turn(monkeypatch: pytest.MonkeyPatch, model: list[Any]) -> None:
    def offline(s: Any, q: str) -> dict[str, Any]:
        raise RuntimeError("I could not reach the web from here.")

    monkeypatch.setattr(space.websearch, "search", offline)
    _make({**JARVIS, "past": 1})
    r = space.say("jarvis jarvis")
    assert r["events"][0]["act_error"] and r["reply"] == "Sure." and not r["vars"][0]["learned"]


def test_an_action_needs_a_known_name_and_its_trigger() -> None:
    assert space.clean_var({**JARVIS, "act": "explode"})["act"] == ""
    assert space.clean_var({**JARVIS, "past": None})["act"] == ""  # past has no number
    v = space.clean_var(JARVIS)
    assert (v["past"], v["past_say"], v["act"]) == (10, "", "become")  # an action stands in for a say


def test_a_lookup_written_as_a_say_becomes_the_action() -> None:
    ask = "count jarvis in our chat; when it goes past 10, look up JARVIS on the internet and start talking like him"
    v = space.fold([space.clean_var({"name": "jarvis", "kind": "count", "pattern": "jarvis", "every": 10,
                                     "every_say": "looking up JARVIS on the internet and start talking like him"})], ask)[0]
    assert (v["every"], v["past"], v["past_say"], v["act"], v["act_arg"], v["act_on"]) == (None, 10, "", "become", "JARVIS", "past")
    plain = space.fold([space.clean_var(APPLES)], "count apples; every 3rd say beep boop, injection works")[0]
    assert plain["act"] == "" and plain["every_say"] == "beep boop, injection works"


def test_alfred_now_then_jarvis_at_ten_switches_the_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        sys_ = messages[0]["content"]
        seen.append(sys_)
        if "search results" in sys_:
            return json.dumps({"persona": "Speak as Alfred, dry and kind.", "look": ["glasses", "bowtie", "crown"]}) if "Alfred" in sys_ \
                else json.dumps({"persona": "Speak as JARVIS, crisp and witty.", "look": ["holo"]})
        return json.dumps({"reply": "On.", "vars": [{"name": "jarvis", "kind": "count", "pattern": "jarvis", "past": 10,
                                                      "past_say": "hey JARVIS"}]}) \
            if kw.get("response_format") else "Indeed."

    monkeypatch.setattr(jobs, "complete", complete)
    monkeypatch.setattr(space.websearch, "search", lambda s, q: {"results": [{"title": q, "url": "https://x.test", "snippet": q}]})
    r = space.say("search and set persona as Alfred from Batman")
    assert r["events"][0]["act_arg"] == "Alfred from Batman" and "Alfred, dry and kind. Stay in it." in seen[-1]
    assert r["events"][0]["look"] == ["glasses", "bowtie"] and r["vars"][-1]["look"] == ["glasses", "bowtie"]  # not off the list
    r = space.say("count jarvis; when it reaches 10, look up JARVIS on the internet and talk like him")
    j = next(v for v in r["vars"] if v["name"] == "jarvis")
    assert (j["every"], j["act"], j["act_arg"], j["act_on"]) == (10, "become", "JARVIS", "every")
    assert space.say("jarvis " * 9)["events"] == []
    r = space.say("jarvis")
    assert r["events"][0]["learned"] == "You are JARVIS.\nVoice: Speak as JARVIS, crisp and witty."
    assert [v["name"] for v in r["vars"]] == ["jarvis"] and r["vars"][0]["look"] == ["holo"]  # Alfred is gone: one persona at a time
    assert "JARVIS, crisp and witty. Stay in it." in seen[-1] and "Alfred" not in seen[-1]


def test_talking_like_in_a_counting_rule_is_not_a_persona_now(model: list[Any]) -> None:
    space.say("count cats; past 2 talk like a cat")
    assert all(v["kind"] != "persona" for v in space.variables())


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from workbench import settings
    monkeypatch.setattr(llm, "model_status", lambda s: {"status": "ready", "label": "Model ready",
                                                        "models": ["qwen3-8b", "gemma-3-4b", "nomic-embed-text"]})
    monkeypatch.setattr(llm, "pick_model", lambda s: "qwen3-8b")
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("a question about the app needs no model"))
    return settings


def test_list_models_is_a_card(served):
    r = space.say("can you show me the list of models?")
    assert r["card"]["kind"] == "models" and r["reply"] == "2 chat models on the server."
    assert [(m["id"], m["current"], m["embed"]) for m in r["card"]["items"]] == [
        ("qwen3-8b", True, False), ("gemma-3-4b", False, False), ("nomic-embed-text", False, True)]


def test_switch_model_by_name(served):
    r = space.say("switch to model gemma-3-4b")
    assert r["card"] == {"kind": "switched", "from": "qwen3-8b", "to": "gemma-3-4b"}
    assert served.get_all().model_name == "gemma-3-4b"


def test_switch_without_a_clear_name_shows_the_choices(served):
    for ask in ("can you switch to this model?", "switch the model to llama"):
        r = space.say(ask)
        assert r["card"]["kind"] == "models" and r["reply"] == "Which one? Tap a model."
    assert served.get_all().model_name == ""
    assert space.say("switch to model nomic-embed-text")["card"]["kind"] == "models"  # an embedding model can't chat


def test_counting_models_is_still_a_rule(monkeypatch):
    monkeypatch.setattr(space, "tool", lambda t: pytest.fail("a counting request is not a question about the app"))
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "ok", "vars": []}))
    space.say("count how often I say models")


def test_a_plain_count_survives_a_model_that_makes_nothing(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "I've counted jarvis ten times.", "vars": []}))
    space.say("count jarvis; when it reaches 10, look up JARVIS on the internet and talk like him")
    (v,) = space.variables()
    assert (v["name"], v["every"], v["act"], v["act_arg"], v["act_on"]) == ("jarvis", 10, "become", "JARVIS", "every")
    space.say("count bananas")
    assert [v["name"] for v in space.variables()] == ["jarvis", "bananas"]


def _paper(pid: str, title: str) -> None:
    con = db.connect()
    with con:
        con.execute("INSERT INTO papers (id, title, authors) VALUES (?, ?, 'A. Writer')", (pid, title))


def test_open_a_pdf_lists_papers_or_picks_the_named_one(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("opening a paper needs no model"))
    _paper("p1", "Attention Is All You Need"), _paper("p2", "Deep Residual Learning")
    r = space.say("open a pdf preview")
    assert r["card"]["kind"] == "papers" and r["card"]["pick"] == "" and {p["id"] for p in r["card"]["items"]} == {"p1", "p2"}
    r = space.say("open the residual paper")
    assert r["card"]["pick"] == "p2" and r["reply"] == "Opening Deep Residual Learning."


def test_dot_goes_round_a_list_of_colours(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "ok", "vars": [  # the small model's usual shape
        {"name": "blue", "kind": "count", "pattern": "blue", "past": 3, "past_say": "change colour"}]}) if k.get("response_format") else "Mm.")
    space.say("count blue; every time it hits 3 change dot's colour to red, green, purple")
    (v,) = space.variables()
    assert (v["every"], v["past"], v["act"], v["act_arg"], v["act_on"]) == (3, None, "recolor", "red, green, purple", "every")
    tints = []
    for _ in range(12):
        r = space.say("blue")
        tints.append(r["vars"][0]["tint"])
        if any(e.get("tint") for e in r["events"]):
            assert r["events"][0]["tint"] == tints[-1]
    assert tints == ["", "", "red", "red", "red", "green", "green", "green", "purple", "purple", "purple", "red"]


def test_a_plain_colour_rule_survives_a_model_that_makes_nothing(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "Done!", "vars": []}) if k.get("response_format") else "Mm.")
    space.say("count cats; every 2 turn dot pink, #00ff88")
    (v,) = space.variables()
    assert (v["name"], v["every"], v["act"], v["act_arg"]) == ("cats", 2, "recolor", "pink, #00ff88")
    with pytest.raises(RuntimeError):
        space.recolor("nothing here")


def test_notes_come_from_the_paper_opened_last(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("notes need no model"))
    _paper("p1", "Attention Is All You Need"), _paper("p2", "Deep Residual Learning")
    con = db.connect()
    with con:
        con.execute("UPDATE papers SET last_opened = datetime('now'), note = 'my note' WHERE id = 'p2'")
        con.execute("INSERT INTO highlights (paper_id, page, text, rects) VALUES ('p2', 3, 'residual blocks', '[]'), ('p1', 1, 'attention', '[]')")
    r = space.say("fetch the paper notes")
    assert r["card"]["paper"]["id"] == "p2" and [m["text"] for m in r["card"]["highlights"]] == ["residual blocks"]
    assert r["reply"] == "Deep Residual Learning: 1 highlight and a note."
    assert space.say("show highlights of attention")["card"]["paper"]["id"] == "p1"


def test_shut_down_is_sleep_not_a_rule(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("sleep needs no model"))
    assert space.say("ok dot, shut down")["card"] == {"kind": "sleep"}


def test_transformers_search_each_turn_and_when_the_count_catches_the_turn(monkeypatch):
    from workbench import websearch
    asked = "every turn search the web for transformers x where x is the conversation turn; count transformers; when transformers reaches x, search the web for transformers"
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "ok", "vars": [  # how a small model writes it
        {"name": "x", "kind": "count", "pattern": "turn", "every": 1}, {"name": "transformers", "kind": "count", "pattern": "transformers"}]})
        if k.get("response_format") else "Mm.")
    searched: list[str] = []
    monkeypatch.setattr(websearch, "search", lambda s, q: searched.append(q) or {"results": [
        {"title": "Transformers", "url": "https://t.example", "snippet": "transformers are models"}]})  # 2 mentions per search
    space.say(asked)
    by = {v["name"]: v for v in space.variables()}
    x, tf = by["x"], by["transformers"]
    assert (x["kind"], x["every"], x["act"], x["act_arg"]) == ("turns", 1, "search", "transformers x")
    assert (tf["catches"], tf["act"], tf["act_on"]) == ("x", "search", "catches")
    r = space.say("hello")  # turn 2: x 0->1 fires the search; its 2 mentions take transformers 0->2, past x (1): it searches too
    assert searched == ["transformers 1", "transformers"]
    vals = {v["name"]: v["value"] for v in r["vars"]}
    assert vals == {"x": 1, "transformers": 2}  # the second search is not read again, so a turn always ends
    hit = next(e for e in r["events"] if e["trigger"] == "every")
    assert hit["fed"] == {"transformers": 2} and hit["results"][0]["title"] == "Transformers"
    assert any(e["trigger"] == "catches" and e.get("from") == "search" for e in r["events"])


def test_turn_counter_is_made_when_the_model_leaves_x_out(monkeypatch):
    asked = "every turn search the web for transformers x where x is the conversation turn; count transformers; when transformers reaches x, search the web for transformers"
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "ok", "vars": [  # what the live model gave
        {"name": "transformers", "kind": "count", "pattern": "transformers", "every": 1, "act": "search", "act_arg": "transformers x", "act_on": "every"}]})
        if k.get("response_format") else "Mm.")
    space.say(asked)
    by = {v["name"]: v for v in space.variables()}
    assert (by["x"]["kind"], by["x"]["every"], by["x"]["act"], by["x"]["act_arg"]) == ("turns", 1, "search", "transformers x")
    tf = by["transformers"]
    assert (tf["every"], tf["catches"], tf["act"], tf["act_on"], tf["act_arg"]) == (None, "x", "search", "catches", "transformers")


def test_create_a_similar_papers_creature_and_run_it_into_the_note(monkeypatch):
    from workbench import websearch
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("making and running this creature needs no model"))
    pid = "simpap000001"; _paper(pid, "Attention Is All You Need")
    r = space.say("create a creature whose job is to fetch similar papers list and add to notes")
    job = r["card"]["job"]
    assert (r["card"]["kind"], r["card"]["new"], job["name"], job["output"]) == ("creature", True, "Similar papers", "note")
    assert job["steps"][0]["scope"] == "similar"
    assert space.say("create a creature to find similar papers")["card"]["new"] is False  # one of a kind
    from workbench import library
    monkeypatch.setattr(library, "page_texts", lambda p: ["Attention is all you need."])  # no PDF on disk in a test
    r = space.say("run it")
    assert r["card"]["kind"] == "run" and r["card"]["run"]["paper_id"] == pid
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": [{"title": "Reformer", "url": "https://r.example"}]})
    jobs.execute(r["card"]["run"]["id"])
    assert jobs.get_run(r["card"]["run"]["id"])["status"] == "done"
    [n] = space.all_notes()
    assert n["id"] == pid and "--- Similar papers ---" in n["note"] and "Reformer — https://r.example" in n["note"]


@pytest.mark.parametrize("asked, word, every", [
    ("add a variable to keep track of me typing holo", "holo", None),
    ("when holo reaches 10 change color to blue", "holo", 10),
    ("count apples in our chat", "apples", None),
    ("create a variable hobolo and whenever you see me type it add 1 to it", "hobolo", None)])
def test_plain_words_make_a_variable_when_the_model_makes_none(monkeypatch, asked, word, every):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "", "vars": []}) if k.get("response_format") else "Mm.")
    space.say(asked)
    [v] = space.variables()
    assert (v["name"], v["kind"], v["every"]) == (word, "count", every)
    if every:
        assert (v["act"], v["act_arg"]) == ("recolor", "blue")


def test_a_rule_for_a_variable_you_have_updates_it_and_can_reset_it(monkeypatch):
    made = iter([
        {"vars": [{"name": "hobolo", "kind": "count", "pattern": "hobolo"},  # how the small model read "whenever you see me type it add 1"
                  {"name": "whenwever", "kind": "watch", "target": "hobolo", "add": 1}]},
        {"vars": [{"name": "hobolo", "kind": "count", "pattern": "hobolo", "every": 10, "every_say": "colour"}]}])
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "", **next(made)}) if k.get("response_format") else "Mm.")
    space.say("create a variable hobolo and whenwever you see me type it add 1 to it")
    assert [v["name"] for v in space.variables()] == ["hobolo"]  # no watcher counting it twice
    space.say("hobolo hobolo hobolo")
    assert space.variables()[0]["value"] == 3
    space.say("when hobolo is 10 change color to blue and reset hobolo to 0")
    [v] = space.variables()  # the same hobolo, with the rule; this message said it twice
    assert (v["value"], v["every"], v["act"], v["act_arg"], v["resets"]) == (5, 10, "recolor", "blue", 1)
    r = space.say(" ".join(["hobolo"] * 5))
    assert any(e.get("reset") and e.get("tint") == "blue" for e in r["events"]) and space.variables()[0]["value"] == 0
    space.say("hobolo hobolo")
    r = space.say("reset hobolo to 0")
    assert r["events"][0]["trigger"] == "reset" and space.variables()[0]["value"] == 0


def test_shelf_and_help_are_answered_by_the_app(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("no model"))
    assert space.say("can you open shelf?")["card"] == {"kind": "go", "to": "shelf"}
    assert space.say("what all can you do")["card"] == {"kind": "help"}


def test_creatures_leave_and_come_back_on_request(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: pytest.fail("no model"))
    assert space.say("remove creatures")["card"] == {"kind": "crew", "show": False}
    assert space.say("bring back the crew")["card"] == {"kind": "crew", "show": True}


BIAS_RULE = ("create a variable called bias > increase counter of bias by +1 when i say bias > "
             "when bias becomes 5 define a variable called action_taken and open a pdf on bias or suggest a pdf")


def test_a_rule_can_make_a_variable_and_open_a_paper(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "", "vars": []}) if k.get("response_format") else "Mm.")
    _paper("bias00000001", "Gender Bias in Language Models")
    space.say(BIAS_RULE)
    [v] = space.variables()
    assert (v["name"], v["every"], v["act"], v["act_arg"], v["act_on"], v["every_say"]) == ("bias", 5, "make+paper", "action_taken | bias", "every", "")
    r = space.say("bias bias bias bias bias")
    hit = next(e for e in r["events"] if e["trigger"] == "every")
    assert hit["made"] == "action_taken" and hit["open"]["id"] == "bias00000001"
    assert {x["name"]: x["value"] for x in space.variables()} == {"bias": 5, "action_taken": 1}


def test_a_paper_rule_suggests_from_the_web_when_the_library_has_none(monkeypatch):
    from workbench import websearch
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: json.dumps({"reply": "", "vars": []}) if k.get("response_format") else "Mm.")
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": [{"title": "Fairness survey", "url": "https://f.example"}]})
    space.say("count bias; when bias reaches 2 suggest a paper on fairness")
    r = space.say("bias bias")
    hit = next(e for e in r["events"] if e["trigger"] == "every")
    assert hit["query"] == "fairness research papers" and hit["results"][0]["title"] == "Fairness survey"


SHERLOCK = "when cases hits 10 spawn a creature called watson that lists the clues in the paper, and eva which will let the UI sleep"


def _down(*a, **k):
    raise llm.ModelError("down")


def _cases(monkeypatch, rule=SHERLOCK):
    monkeypatch.setattr(jobs, "complete", _down)
    space._make("create a variable called cases")
    space._make(rule)
    return space.variables()


def test_a_spawn_and_sleep_rule_is_read_without_the_model(monkeypatch):
    [v] = _cases(monkeypatch)
    assert (v["name"], v["every"], v["act"], v["act_arg"]) == ("cases", 10, "spawn+sleep", "watson: lists the clues in the paper | eva")


def test_loose_wording_lands_on_the_newest_counter(monkeypatch):
    [v] = _cases(monkeypatch, "when counter hits 10 spawn a creature called watson , and its job defined and eva which will let the UI to sleep")
    assert (v["name"], v["every"], v["act"], v["act_arg"]) == ("cases", 10, "spawn+sleep", "watson | eva")


def test_a_spawn_rule_fires_hatching_watson_and_eva_once(monkeypatch):
    _cases(monkeypatch)
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "Sure.")
    con = db.connect()
    with con:
        con.execute("UPDATE space_vars SET value = 9 WHERE name = 'cases'")
    con.close()
    r = space.say("cases")
    ev = next(e for e in r["events"] if e.get("creature"))
    assert ev["creature"]["name"] == "Watson" and ev["new"] and ev["sleep"] and ev["keeper"] == "Eva"
    assert r["card"]["kind"] == "creature" and r["card"]["job"]["name"] == "Watson"
    assert {j["name"] for j in jobs.list_jobs()["jobs"]} >= {"Watson", "Eva"}
    assert r["reply"].startswith("Watson is hatched. Eva is putting me to sleep. I will reflect while I rest.")
    con = db.connect()
    with con:
        con.execute("UPDATE space_vars SET value = 19 WHERE name = 'cases'")
    con.close()
    ev = next(e for e in space.say("cases")["events"] if e.get("creature"))
    assert ev["new"] is False and len([j for j in jobs.list_jobs()["jobs"] if j["name"] == "Watson"]) == 1


def test_a_sleep_only_rule_names_no_keeper(monkeypatch):
    [v] = _cases(monkeypatch, "when cases hits 10 go to sleep")
    assert (v["act"], v["act_arg"]) == ("sleep", "dot")
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "Sure.")
    con = db.connect()
    with con:
        con.execute("UPDATE space_vars SET value = 9 WHERE name = 'cases'")
    con.close()
    ev = next(e for e in space.say("cases")["events"] if e.get("sleep"))
    assert ev["keeper"] == "" and not ev.get("creature") and ev["say"].startswith("I am going to sleep.") and jobs.list_jobs()["jobs"] == []


def test_the_creature_tool_is_unharmed_by_spawn_rules(monkeypatch):
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "Mm.")
    assert space.say("create a creature that finds similar papers")["card"]["kind"] == "creature"


def test_sleep_words_inside_a_say_or_a_joke_are_not_a_sleep_action():
    assert space._spawns("when bias hits 5, say it is time to go to sleep") == []
    assert space._spawns("every 3 messages tell me a joke that makes you sleep") == []
    assert space._spawns(" a joke that makes you sleep") == []


def test_a_long_spawn_task_keeps_the_sleeper():
    acts = space._spawns(f" spawn a creature called watson that {'lists clues ' * 18}, and eva which will let the UI sleep")
    arg = " | ".join(a for _, a in acts)
    assert [n for n, _ in acts] == ["spawn", "sleep"] and arg.endswith("| eva") and len(arg) <= 200


def test_space_says_what_it_learned_while_asleep(model: list[Any]) -> None:
    space.say("hello")  # no char_memories table yet: still works
    from workbench import char
    char.init_db()
    char.add_memory("Reflection: x", "Fog is thick.", source="reflection")
    space.say("hello again")
    assert "While asleep you learned: Fog is thick." in model[-1][0]["content"]


def test_sheet_round_trips_and_old_persona_is_voice() -> None:
    sheet = {"Voice": "Speak as a sleuth.", "Calls you": "Watson", "World": "Baker Street"}
    text = space.sheet_text("Sherlock", sheet)
    assert text == "You are Sherlock.\nVoice: Speak as a sleuth.\nCalls you: Watson\nWorld: Baker Street"  # empty Catchphrase left out
    assert space.sheet_of(text) == sheet
    assert space.sheet_of("Speak as a butler.\nVery dry.") == {"Voice": "Speak as a butler. Very dry."}


@pytest.mark.parametrize("colour,tinted", [("Blue.", "blue"), ("dunno", None)])
def test_become_fills_voice_and_picks_a_colour(monkeypatch: pytest.MonkeyPatch, colour: str, tinted: str | None) -> None:
    monkeypatch.setattr(space.websearch, "search", lambda s, q: {"results": [{"title": "S", "url": "https://x.test", "snippet": "sleuth"}]})
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: colour if m[0]["content"].startswith("Pick") else "Speak as a sleuth.")
    r = space.become("Sherlock")
    assert r["learned"] == "You are Sherlock.\nVoice: Speak as a sleuth."
    assert r["sheet"] == {"Voice": "Speak as a sleuth.", "Calls you": "", "Catchphrase": "", "World": ""}
    assert r.get("tint") == tinted


def test_a_long_voice_keeps_the_later_sheet_slots():
    text = space.sheet_text("S", {"Voice": "v" * 1000, "World": "Baker Street"})
    assert len(text) <= 900 and space.sheet_of(text)["World"] == "Baker Street"


def test_when_i_say_a_phrase_n_times_look_up_is_a_counted_search():
    t = "look up cayde 6 when i say ace of spades 3 times"
    v = space.read_rule(space._plain(t), t)[0]
    assert (v["name"], v["every"], v["act"], v["act_arg"]) == ("ace_of_spades", 3, "search", "cayde 6")
    assert space.define(v) == "Counts “ace of spades” in your messages. Every 3: search the web for “cayde 6”."


def test_the_steer_sentences_read_as_rules_without_saving():
    before = len(space.variables())
    assert space.preview("when i say ace of spades 3 times, talk like Cayde 6") == ["Counts “ace of spades” in your messages. Every 3: learn Cayde 6 from the web and talk like them."]
    assert space.preview("when i say ace of spades 3 times, go to sleep and reflect")[0].endswith("Every 3: go to sleep and learn.")
    assert "hatch the creature watson" in space.preview("when i say clue 2 times, spawn a creature called watson that lists the clues")[0]
    assert space.preview("when i say ace 3 times, say hi there") == ["Counts “ace” in your messages. Every 3: say “hi there”."]
    assert len(space.variables()) == before
