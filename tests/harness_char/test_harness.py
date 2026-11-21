import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harness_char import char, harness
from shared import db, llm, settings, websearch
from pdf_research import jobs
import app as main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    char.init_db()
    char.TRACE.clear()  # clears ENGINES too
    char.update_profile("Sherlock", "a detective", [], "#fff")

    def no_http(*a: Any, **k: Any) -> Any:
        raise AssertionError("no HTTP to the model server in tests")

    monkeypatch.setattr(llm, "_api", no_http)
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": [{"title": "Fog", "snippet": "London fog over Baker Street"}]})


def _sheet(title_like: str) -> list[Any]:
    con = db.connect()
    rows = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE ? ORDER BY id", (title_like,)).fetchall()
    con.close()
    return rows


def test_parse_is_lenient():
    cmds, bad = harness.parse('1. reflect "Vanguard-class Titans"\n- check 431\nfold: Cooper\n`wonder`\ncheck(12)\n{oops')
    assert cmds == [{"name": "reflect", "arg": "Vanguard-class Titans"}, {"name": "check", "arg": "431"}, {"name": "fold", "arg": "Cooper"},
                    {"name": "wonder", "arg": ""}, {"name": "check", "arg": "12"}]
    assert bad == ["{oops"]
    assert harness.parse('```json\n["reflect \\"fog\\"", {"cmd": "check", "arg": 5}]\n```')[0] == [{"name": "reflect", "arg": "fog"}, {"name": "check", "arg": "5"}]
    assert harness.parse("") == ([], [])


def test_controller_rejects_with_reasons():
    char.set_system(1, False)  # marks the persona's start, so the note comes after it
    note = char.add_memory("Reflection: fog", "Fog lies over London.", source="reflection")["id"]
    cmds, _ = harness.parse(f"dance\ncheck 99999\ncheck #{note}\nwonder\nfold Nobody\nreflect fog\nreflect fog\nbake\nextract\nsort")
    plan, rejected = harness.validate(cmds, budget=3)
    assert [(p["name"], p["arg"], p["role"]) for p in plan] == [("bake", "", None), ("check", str(note), "chat"), ("reflect", "fog", "chat")]  # grouped by model
    why = {r["cmd"]: r["why"] for r in rejected}
    assert why["dance"] == "unknown command"
    assert why['check "99999"'].startswith("no unchecked note 99999")
    assert why["wonder"] == "system S1 off"
    assert why['fold "Nobody"'] == "no name Nobody in its graph"
    assert why['reflect "fog"'] == "duplicate"
    assert why["extract"] == why["sort"] == "over budget (3)"


def _models(monkeypatch, planner: str, judge: str = "1 KEEP useful\n2 DROP repeats itself") -> list[list[dict[str, Any]]]:
    calls: list[list[dict[str, Any]]] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        calls.append(messages)
        sys_msg = messages[0]["content"]
        if "You plan the next steps" in sys_msg:
            return planner
        if "You judge the steps" in sys_msg:
            return judge
        if "Reply KEEP or DROP" in sys_msg:
            return "KEEP"
        return "Remember the London fog."

    monkeypatch.setattr(jobs, "complete", complete)
    return calls


def test_full_cycle_runs_records_and_feeds_back(monkeypatch):
    note = char.add_memory("Reflection: fog", "Fog lies over London.", source="reflection")["id"]
    calls = _models(monkeypatch, f'check {note}\nreflect "Baker Street"\nteleport now')
    r = client.post("/char/cycle", json={}).json()
    assert r["cycle"] == 1 and r["proposed"] == [f'check "{note}"', 'reflect "Baker Street"', 'teleport "now"']
    assert r["rejected"] == [{"cmd": 'teleport "now"', "why": "unknown command"}]
    assert [(x["cmd"], x["outcome"]) for x in r["executed"]] == [(f'check "{note}"', "ok"), ('reflect "Baker Street"', "ok")]
    assert r["executed"][0]["detail"].endswith("verified")
    v = {x["cmd"]: x for x in r["verdicts"]}
    assert v[f'check "{note}"']["keep"] is True  # exact check, no judge needed
    assert v['reflect "Baker Street"'] == {"cmd": 'reflect "Baker Street"', "keep": True, "why": "useful"}  # the one judge call
    assert sum("You judge the steps" in c[0]["content"] for c in calls) == 1 and r["swaps"] == []
    assert {t["title"] for t in _sheet("Run: %")} >= {"Run: check", "Run: reflect", "Run: cycle"}
    assert json.loads(_sheet("Feedback: 1")[0]["content"]) == r["verdicts"]
    assert _sheet("Fail: planner") == []
    # the next planner prompt carries the verdicts
    calls2 = _models(monkeypatch, "{{ not a command")
    r2 = harness.cycle()
    assert "worked last cycle: check, reflect" in calls2[0][1]["content"] and ": keep (" not in calls2[0][1]["content"]  # plain words, nothing to copy back as a command
    assert r2["executed"] == [] and r2["rejected"] == [{"cmd": "{{ not a command", "why": "could not read it as a command"}]
    assert len(_sheet("Fail: planner")) == 1  # a parse failure is a self-correction
    got = client.get("/char/cycles").json()["cycles"]
    assert [c["cycle"] for c in got] == [2, 1]
    loop = harness.totals()
    assert loop == {"cycles_run": 2, "proposed": 3, "rejected": 2, "executed": 2, "kept": 2, "dropped": 0, "swaps": 0, "swap_seconds": 0}


def test_arg_ignored_and_planner_mode_rest(monkeypatch):
    char.add_memory("Reflection: fog", "Fog lies over London.", source="reflection")
    _models(monkeypatch, 'extract "the fog"')
    char.set_mode("planner")
    r = client.post("/char/rest", json={"char": True}).json()
    assert r["kind"] == "cycle" and r["cycle"]["executed"][0]["detail"].endswith("(arg ignored)")
    assert char.ENGINES["cycle"]["outcome"] == "ok"
    assert [e["kind"] for e in client.get("/char/engines").json()["engines"]][-2:] == ["model", "cycle"]


def _server(monkeypatch, states: list[dict[str, Any]]) -> list[tuple[str, str, Any]]:
    calls: list[tuple[str, str, Any]] = []

    def api(s: Any, method: str, path: str, body: Any = None, timeout: float = 10) -> Any:
        calls.append((method, path, body))
        if path == "status":
            return states.pop(0) if len(states) > 1 else states[0]
        if path == "load-progress":
            return {"phase": "loading", "fraction": 0.5}
        return {}

    monkeypatch.setattr(llm, "_api", api)
    return calls


def test_ensure_swaps_and_records(monkeypatch):
    calls = _server(monkeypatch, [{"active_model": "A", "loaded": ["A"], "loading": []},
                                  {"active_model": "", "loaded": [], "loading": ["B"]},
                                  {"active_model": "B", "loaded": ["B"], "loading": []}])
    sw = llm.ensure(settings.get_all(), "B", poll=0)
    assert sw["from"] == "A" and sw["to"] == "B" and sw["ok"] is True
    assert ("POST", "unload", {"model_path": "A"}) in calls and ("POST", "load", {"model_path": "B"}) in calls
    assert llm.SWAP["busy"] is False and llm.SWAP["phase"] == "ready" and (llm.SWAP["from"], llm.SWAP["to"]) == ("A", "B")
    assert char.ENGINES["model"]["outcome"] == "ok" and "A → B" in char.ENGINES["model"]["detail"]
    assert json.loads(_sheet("Run: model")[0]["content"])["outcome"] == "ok"
    assert client.get("/model/swap").json().keys() == {"busy", "from", "to", "phase", "fraction", "started"}
    assert llm.ensure(settings.get_all(), "B", poll=0) is None  # already active: nothing to do


def test_ensure_noop_and_unknown_shape(monkeypatch):
    assert llm.ensure(settings.get_all(), "") is None  # empty setting: whatever is loaded, and no HTTP (the fixture would raise)
    _server(monkeypatch, [{"model": "x"}])
    assert llm.ensure(settings.get_all(), "B") is None
    assert char.ENGINES["model"]["outcome"] == "skipped" and char.ENGINES["model"]["detail"] == "unknown status shape"


def test_cycle_swaps_per_role(monkeypatch):
    settings.update({"planner_model": "P", "chat_model": "C", "judge_model": "J"})
    char.add_memory("Reflection: fog", "Fog lies over London.", source="reflection")
    _models(monkeypatch, 'reflect "Baker Street"\nbake')
    active = {"m": "C"}

    def api(s: Any, method: str, path: str, body: Any = None, timeout: float = 10) -> Any:
        if path == "load":
            active["m"] = body["model_path"]
        return {"active_model": active["m"], "loaded": [active["m"]], "loading": []} if path == "status" else {}

    monkeypatch.setattr(llm, "_api", api)
    r = harness.cycle()
    assert [(w["from"], w["to"]) for w in r["swaps"]] == [("C", "P"), ("P", "C"), ("C", "J")]
    assert harness.totals()["swaps"] == 3



def test_the_controller_rejects_feedback_copied_back_as_a_command():
    _, rejected = harness.validate([{"name": "bake", "arg": "consolidate: drop (did not do anything: 2 new answers)"}])
    assert rejected and rejected[0]["why"] == "copied last cycle's feedback, not a command"


def test_the_controller_puts_ready_work_first_and_repairs_a_glued_topic(monkeypatch):
    monkeypatch.setattr(harness.char, "_open_questions", lambda since=0: ["Who is Cooper?"])
    plan, rejected = harness.validate([{"name": n, "arg": ""} for n in ("plan", "bake", "goal", "ask")] + [{"name": "reflect", "arg": 'Who is Cooper?": look a topic up'}])
    assert {"name": "reflect", "arg": "Who is Cooper?", "role": "chat"} in plan
    assert [r["cmd"].split()[0] for r in rejected] == ["ask"]  # the budget cuts the last of the catalogue, not the work that can happen


def test_a_named_step_runs_even_in_planner_mode(monkeypatch):
    char.set_mode("planner")
    monkeypatch.setattr(char, "rest", lambda on_char, n=None, force=False, only=None: {"done": True, "kind": "", "why": f"ran {only}"})
    r = client.post("/char/rest", json={"char": True, "only": "journal"}).json()
    assert r["kind"] != "cycle" and r["why"] == "ran journal"


def test_a_step_the_planner_keeps_leaving_out_is_added_to_the_cycle():
    for _ in range(12):
        char.add_memory("Run: reflect", json.dumps({"outcome": "ok", "detail": ""}), source="sheet")
    assert harness.starved([{"name": "reflect", "arg": ""}]) in harness.COMMANDS
    assert harness.starved([{"name": "reflect", "arg": ""}]) != "reflect"
    assert harness.starved([]) != "" and harness.starved([{"name": k, "arg": ""} for k in harness.COMMANDS]) == ""


def test_a_planner_that_recites_the_catalogue_still_answers_the_open_questions(monkeypatch):
    qs = ["Who is Cooper?", "Who is Laura?", "What is the Lodge?"]
    monkeypatch.setattr(harness.char, "_open_questions", lambda since=0: qs)
    _models(monkeypatch, "plan: research the town\nbake: consolidate\njournal: write a page\ngoal: turn a plan line into a question")
    r = harness.cycle()
    assert r["proposed"][0] == 'reflect "Who is Cooper?"'  # the work that can happen now leads, though the planner left it out
    assert ('reflect "Who is Cooper?"', "ok") in [(x["cmd"], x["outcome"]) for x in r["executed"]]
    why = {x["cmd"].split()[0]: x["why"] for x in r["rejected"]}
    assert why["plan"] == why["goal"] == "3 questions already open: answer them first"
