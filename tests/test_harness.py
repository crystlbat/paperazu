import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from workbench import char, db, harness, jobs, llm, main, settings, websearch

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
    monkeypatch.setattr(harness, "steer", lambda plan, rejected, budget=harness.BUDGET, force=False: (plan, rejected, {}))  # the drive has its own tests; the rest pin the planner's plan


_steer = harness.steer.__wrapped__ if hasattr(harness.steer, "__wrapped__") else harness.steer


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


def test_a_skipped_command_stays_off_the_plan_until_something_new_comes_in():
    char._engine("tune", "skipped", "no grown traits to meet")
    char._engine("tune", "skipped", "no grown traits to meet")
    assert "tune" in harness.stale()
    harness.char.add_memory("Feedback: 1", "[]", source="sheet")  # its own bookkeeping is not news
    plan, rejected = harness.validate([{"name": "tune", "arg": ""}])
    assert not plan and rejected[0]["why"] == "skipped last time and nothing has changed for it"
    char.add_memory("Reflection: fog", "Fog lies over London.", source="reflection")
    char.add_memory("Needs", "{}", source="sheet")  # its mood, written after every step, is not news either
    assert "tune" in harness.stale()  # a note is not what tune works on: only review feeds it
    char._engine("review", "ok", "a reply judged")
    assert "tune" not in harness.stale()


def test_a_step_that_reads_the_chat_waits_for_a_new_turn():
    char._engine("review", "skipped", "no new reply to review")
    char._engine("reflect", "ok", "a note")  # busy elsewhere: still nothing for review
    assert "review" in harness.stale()
    con = db.connect()
    with con:
        con.execute("INSERT INTO char_turns (role, text, created_at) VALUES ('dot', 'A new reply.', datetime('now', '+1 second'))")
    con.close()
    assert "review" not in harness.stale()


def test_stuck_it_names_the_wall_tries_a_way_out_and_then_rests_without_you(monkeypatch):
    calls = _models(monkeypatch, "{{ not a command")  # a planner that gives it nothing to run
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": []})  # and a web with nothing on it, so it does run out
    r = harness.cycle()
    me = r["self"]
    assert me["stuck"] and me["try"] == harness.UNSTICK[0] and me["said"].startswith("I keep hitting the same wall")
    assert [x["cmd"] for x in r["executed"]] == [me["try"]]  # its own way out ran
    assert "what it noticed about itself last cycle: I keep hitting" in harness.prompt()[1]["content"]
    for _ in range(40):  # it answers what it can first, then each way out is tried and goes stale, until none is left
        r = harness.cycle()
        if r["self"].get("spent"):
            break
    assert r["self"]["spent"] and r["self"]["try"] == "" and "I will rest until something new comes in" in r["self"]["said"]
    assert _sheet("Stuck: %")


def test_not_stuck_when_the_plan_has_work():
    char.add_memory("Reflection: fog", "Fog lies over London.", source="reflection")
    assert harness.notice(1, [{"name": "check", "arg": "", "role": "chat"}], []) == {"stuck": False}
    assert _sheet("Stuck: %") == []


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
    calls = _models(monkeypatch, f'why: 1 unchecked note, so check first\ncheck {note}\nreflect "Baker Street"\nteleport now')
    r = client.post("/char/cycle", json={}).json()
    assert r["why"] == "1 unchecked note, so check first"  # its reason, kept with the cycle and never run as a command
    assert r["reason"] == "planner: 1 unchecked note, so check first"  # steering is off in this test: no numbers of its own to give
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
    assert [x["cmd"] for x in r2["executed"]] == [r2["self"]["try"]] and r2["self"]["stuck"]  # nothing to run: it picks its own way out
    assert r2["rejected"] == [{"cmd": "{{ not a command", "why": "could not read it as a command"}]
    assert len(_sheet("Fail: planner")) == 1  # a parse failure is a self-correction
    got = client.get("/char/cycles").json()["cycles"]
    assert [c["cycle"] for c in got] == [2, 1]
    loop = harness.totals()
    assert loop == {"cycles_run": 2, "proposed": 3, "rejected": 2, "executed": 3, "kept": 3, "dropped": 0, "swaps": 0, "swap_seconds": 0}  # its own way out (reflect) ran and found something


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


def test_a_failed_load_puts_the_old_model_back(monkeypatch):
    calls = _server(monkeypatch, [{"active_model": "A", "loaded": ["A"], "loading": []}])
    real = llm._api
    def api(s, method, path, body=None, timeout=10):
        if path == "load" and body == {"model_path": "dory"}:
            raise RuntimeError("Some Ollama models do not work with llama.cpp")
        return real(s, method, path, body, timeout)
    monkeypatch.setattr(llm, "_api", api)
    sw = llm.ensure(settings.get_all(), "dory", poll=0)
    assert sw["ok"] is False and ("POST", "load", {"model_path": "A"}) in calls  # not left with nothing loaded
    assert "A loaded back" in char.ENGINES["model"]["detail"]


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


class _FakeProc:
    def __init__(self, *a, **k):
        self.alive, self.cmd = True, a[0]
    def poll(self):
        return None if self.alive else 0
    def terminate(self):
        self.alive = False
    def wait(self, timeout=None):
        return 0


def _engines(monkeypatch, dory_starts=True):
    """Unsloth with A loaded on 8888, and a dory llama-server that answers on 8080 once this app has started it."""
    settings.update({"base_url": "http://127.0.0.1:8888/v1", "dory_cmd": "~/llama.cpp-dory/build/bin/llama-server -m dory.gguf --alias dory --port 8080"})
    calls: list[tuple[str, str, Any]] = []
    state = {"active": "A"}
    def api(s, method, path, body=None, timeout=10):  # a stateful Unsloth: unload empties it, load makes the model active
        calls.append((method, path, body))
        if path == "unload":
            state["active"] = ""
        elif path == "load":
            state["active"] = body["model_path"]
        return {"active_model": state["active"], "loaded": [state["active"]] if state["active"] else [], "loading": []} if path == "status" else {}
    monkeypatch.setattr(llm, "_api", api)
    started: list[_FakeProc] = []
    def popen(*a, **k):
        p = _FakeProc(*a, **k)
        p.alive = dory_starts
        started.append(p)
        return p
    monkeypatch.setattr(llm.subprocess, "Popen", popen)
    monkeypatch.setattr(llm, "_up", lambda url, timeout=3: url.startswith("http://127.0.0.1:8080") and any(p.alive for p in started))
    llm._dory["proc"] = None
    return calls, started


def test_dory_swaps_unsloth_out_starts_its_server_and_takes_the_calls(monkeypatch):
    calls, started = _engines(monkeypatch)
    sent: list[tuple[str, str]] = []
    def client(s, timeout=None, base_url=None):
        from types import SimpleNamespace as NS
        def create(model, **kw):
            sent.append((base_url, model))
            return NS(choices=[NS(message=NS(content="ok"))])
        return NS(chat=NS(completions=NS(create=create)))
    monkeypatch.setattr(llm, "client", client)
    s = settings.get_all().model_copy(update={"model_name": "dory"})
    assert llm.chat(s, [{"role": "user", "content": "hi"}]) == "ok"
    assert ("POST", "unload", {"model_path": "A"}) in calls and len(started) == 1 and started[0].cmd[0].endswith("llama.cpp-dory/build/bin/llama-server")
    assert sent == [("http://127.0.0.1:8080/v1", "dory")]  # the call went to the dory engine
    llm.chat(s, [{"role": "user", "content": "again"}])
    assert len(started) == 1  # up already: no second start
    # back to Unsloth: our dory stops first, then Unsloth loads the model
    u = s.model_copy(update={"model_name": "B"})
    llm.chat(u, [{"role": "user", "content": "now B"}])
    assert not started[0].alive and ("POST", "load", {"model_path": "B"}) in calls and sent[-1] == ("http://127.0.0.1:8888/v1", "B")
    assert "dory engine stopped for Unsloth" in [json.loads(r["content"])["detail"] for r in _sheet("Run: model")]


def test_a_dory_that_will_not_start_puts_unsloths_model_back(monkeypatch):
    calls, started = _engines(monkeypatch, dory_starts=False)
    sw = llm.ensure(settings.get_all(), "dory", poll=0)
    assert sw["ok"] is False and ("POST", "load", {"model_path": "A"}) in calls
    assert "the dory server exited" in char.ENGINES["model"]["detail"] and "A loaded back" in char.ENGINES["model"]["detail"]


def test_without_a_dory_command_dory_is_just_a_name_on_unsloth(monkeypatch):
    settings.update({"dory_cmd": ""})
    s = settings.get_all()
    assert not llm.is_dory(s, "dory") and llm.url_for(s, "dory") == s.base_url


def test_with_steps_still_to_run_it_is_never_spent_and_bookkeeping_is_no_wall(monkeypatch):
    for _ in range(harness.STUCK_AFTER):
        char.add_memory(f"Feedback: {_}", json.dumps([{"cmd": "reflect", "keep": False, "why": "x"}]), source="sheet")
    char._engine("cycle", "skipped", "cycle 9: 1 proposed, 1 rejected, 0 run, 0 kept")
    me = harness.notice(10, [{"name": "reflect", "arg": "", "role": "chat"}], [])
    assert me["stuck"] and not me["spent"] and "cycle 9" not in me["on"]


def test_checking_holds_back_reaching_while_questions_are_open_and_thompson_fills_an_empty_side(monkeypatch):
    monkeypatch.setattr(char, "drive", lambda d=None: {"E": 0.2, "C": 0.6, "p_explore": 0.1, "open": 2, "tau": 0.5, "DF": 0.5, "rest": False, "judge": {"value": 0.5, "probes": 0}})
    monkeypatch.setattr(harness.random, "random", lambda: 0.5)  # 0.5 >= p_explore: check
    plan = [{"name": "speculate", "arg": "", "role": "planner"}, {"name": "wonder", "arg": "", "role": "planner"}]
    got, rejected, dv = _steer(plan, [], 3, True)
    assert dv["mode"] == "check" and all(p["name"] in char.CHECK for p in got) and len(got) == 1  # both explore steps held back, one check step put in
    assert [r["why"].startswith("checking first") for r in rejected] == [True, True]
    monkeypatch.setattr(harness.random, "random", lambda: 0.05)  # explore wins: the plan is left alone when it already reaches out
    got, rejected, dv = _steer(plan, [], 3, True)
    assert dv["mode"] == "explore" and got == plan and rejected == []


def test_the_judge_is_shown_one_settled_step_blind_and_its_agreement_is_its_trust(monkeypatch):
    monkeypatch.setattr(llm, "ensure", lambda s, m: None)
    monkeypatch.setattr(jobs, "complete", lambda s, msgs, max_tokens=0: "1 KEEP fine\n2 DROP looks off")
    executed = [{"cmd": "wonder", "name": "wonder", "outcome": "ok", "detail": "a question", "made": []},
                {"cmd": "journal", "name": "journal", "outcome": "ok", "detail": "wrote", "made": []}]
    monkeypatch.setattr(char, "NO_MODEL", {"journal"})
    v = harness.verify(executed, settings.get_all(), [])
    assert [x["keep"] for x in v] == [True, True]  # the probe never changes the settled verdict
    assert char.judge_trust() == {"value": round(1 / 3, 3), "probes": 1}  # it said DROP to a step the exact check kept: one miss


def test_the_reason_carries_the_drive_numbers_even_when_the_planner_gives_none(monkeypatch):
    monkeypatch.setattr(harness, "steer", _steer)
    monkeypatch.setattr(char, "drive", lambda d=None: {"E": 0.6, "C": 0.2, "tau": 0.3, "p_explore": 0.79, "DF": 0.5, "rest": False, "open": 0, "unchecked": 0, "judge": {"value": 0.5, "probes": 0}})
    monkeypatch.setattr(harness.random, "random", lambda: 0.1)  # explore
    _models(monkeypatch, 'reflect "fog"')  # a planner that skips the why line
    r = harness.cycle()
    assert r["reason"] == "explore: explore 0.6 vs check 0.2 at τ 0.3, P explore 0.79" and r["why"] == ""


def test_the_controller_turns_away_other_work_and_drops_a_copied_description(monkeypatch):
    monkeypatch.setattr(char, "world_words", lambda: {"Sagira", "Osiris", "Vex", "Destiny"})
    plan, rejected = harness.validate([{"name": "reflect", "arg": "Vex in *Mass Effect*"}, {"name": "reflect", "arg": "Osiris in ancient Egyptian mythology"},
                                       {"name": "reflect", "arg": "Where is Sagira in Destiny?"}, {"name": "goal", "arg": "turn the oldest open plan line into one question"}])
    assert [r["why"].startswith("off its world") for r in rejected] == [True, True]  # run 18 searched both, and the gate had to throw one away
    assert [(p["name"], p["arg"]) for p in plan] == [("reflect", "Where is Sagira in Destiny?"), ("goal", "")]  # its own description is not a topic
