import json
import threading

import pytest

from workbench import char, llm, settings, steer, train


def _run(monkeypatch, curiosities, cfg):
    it = iter(curiosities)
    level = {"c": next(it)}
    monkeypatch.setattr(char, "disposition", lambda: {"curiosity": level["c"], "maturity": 0.1})
    def step():
        level["c"] = next(it, level["c"])
        return "ok", "reflect: something"
    monkeypatch.setattr(train, "_one_step", step)
    return _run_with(monkeypatch, cfg)


def _run_with(monkeypatch, cfg):
    con = train._con()
    with con:
        run_id = con.execute("INSERT INTO train_runs (persona, config, status) VALUES (?, ?, 'running')", (char.get_profile()["name"], json.dumps(cfg))).lastrowid
    con.close()
    train.RUN.clear(); train.RUN.update(id=run_id, pause=threading.Event(), stop=threading.Event())
    train._loop(run_id, {**train.DEFAULTS, **cfg})
    return run_id


def test_a_run_learns_until_curiosity_reaches_the_target_and_snapshots_as_it_falls(monkeypatch):
    char.update_profile("Sagira", "You are Sagira.", [], "")
    char.add_memory("Resting: char Sagira", "0", source="sheet")
    run_id = _run(monkeypatch, [5.0, 4.4, 3.8, 3.5, 2.9, 0.8], {"lo": 0.0, "hi": 1.0, "max_steps": 50})
    r = train.status()["runs"][0]
    assert r["status"] == "done" and "reached the target" in r["why"] and r["log"][-1]["curiosity"] == 0.8
    snaps = train.snapshots(run_id)
    assert [s["why"].split(" ")[0] for s in snaps] == ["start", "curiosity", "curiosity", "curiosity", "curiosity", "end:"]  # 4.4, 3.8, 2.9, 0.8 each fell by 0.5 or more; 3.5 did not
    assert snaps[0]["prompt"].startswith("You are Sagira.") and "works" in snaps[0] and "fails" in snaps[0]


def test_a_run_stops_at_its_step_budget_and_its_dataset_is_claude_fine_tuning_jsonl(monkeypatch):
    char.update_profile("Sagira", "You are Sagira.", [], "")
    char.add_memory("Resting: char Sagira", "0", source="sheet")
    con = char.db.connect()
    with con:
        u = con.execute("INSERT INTO char_turns (role, text) VALUES ('user', 'Who is Osiris?')").lastrowid
        d = con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', 'My Warlock. Brilliant, stubborn, mine.')").lastrowid
    con.close()
    char.add_memory(f"Reviewed: {d}", "ok", source="sheet")
    n = char.add_memory("Reflection: Who is Xivu Arath?", "The Hive god of war.", source="reflection")["id"]
    char.add_memory(f"Checked: {n}", "keep", source="sheet")
    run_id = _run(monkeypatch, [5.0] * 10, {"lo": 0.0, "hi": 1.0, "max_steps": 3})
    assert train.status()["runs"][0]["why"] == "used all 3 steps"
    lines = [json.loads(x) for x in train.dataset(run_id).splitlines()]
    assert {l["messages"][0]["content"] for l in lines} == {"Who is Osiris?", "Who is Xivu Arath?"}
    assert all(l["system"].startswith("You are Sagira.") and [m["role"] for m in l["messages"]] == ["user", "assistant"] for l in lines)


def test_pause_holds_a_run_and_stop_ends_it(monkeypatch):
    char.update_profile("Sagira", "You are Sagira.", [], "")
    monkeypatch.setattr(train, "_one_step", lambda: ("skipped", "nothing"))
    monkeypatch.setattr(train, "IDLE_STOP", 10_000)
    s = train.start({"minutes": 5, "max_steps": 10_000, "lo": -2, "hi": -1})
    assert s["active"]
    train.control("pause")
    assert train.status()["runs"][0]["status"] == "paused"
    train.control("stop")
    train.RUN["thread"].join(5)
    r = train.status()["runs"][0]
    assert not train.active() and r["status"] == "stopped" and r["why"] == "you stopped it"


def test_each_step_logs_every_variable_the_story_charts(monkeypatch):
    from workbench import char, train
    d = char.disposition()
    v = train._vars(d)
    assert {"fullness", "energy", "wonder", "joy", "calm", "trust"} <= set(v) and all(isinstance(x, (int, float)) for x in v.values())


def test_the_dataset_leaves_out_drift_that_only_names_its_game(monkeypatch):
    import json
    from workbench import char, train
    char.update_profile("Sagira From Destiny 2", "You are Sagira, the Ghost of the Warlock Osiris. You studied the Vex with him.", [], "")
    ex = lambda u, a: {"user": u, "assistant": a, "system": "s"}
    monkeypatch.setattr(train, "snapshots", lambda run_id: [{"examples": [
        ex("Tell me about Osiris.", "He was a Warlock."),
        ex("What is the political landscape?", "Fans of Destiny 2 reacted to a White House post."),
        ex("Who or what is Panoptes?", "A Vex mind that Osiris and his Ghost fought, in Destiny.")]}])
    asked = [json.loads(l)["messages"][0]["content"] for l in train.dataset(1).splitlines()]
    assert asked == ["Tell me about Osiris.", "Who or what is Panoptes?"]


def test_sampler_draws_a_lane_while_a_system_works(monkeypatch):
    import threading, time as _t
    from workbench import char, train
    th = threading.Thread(target=_t.sleep, args=(0.45,)); th.start()
    monkeypatch.setattr(train, "RUN", {"thread": th, "pause": threading.Event(), "lanes": [], "clock": 0.0})
    monkeypatch.setattr(char, "NOW", {"sys": 2, "kind": "planner"})
    train._sample(every=0.1)
    lanes = train.RUN["lanes"]
    assert len(lanes) == 1 and lanes[0][:2] == [2, "planner"] and lanes[0][3] > lanes[0][2]
    assert train.RUN["clock"] > 0.3


def test_stopping_a_run_makes_the_cycle_in_hand_skip_what_it_has_not_started(monkeypatch):
    from workbench import harness
    ran = []
    monkeypatch.setattr(harness.char, "rest", lambda *a, **k: ran.append(k.get("only")))
    harness.CANCEL.set()
    try:
        out = harness.execute([{"name": "reflect", "arg": "", "role": ""}], None, [])
    finally:
        harness.CANCEL.clear()
    assert ran == [] and out[0]["outcome"] == "skipped" and out[0]["detail"] == "stopped before it ran"


def test_a_run_ends_in_its_own_words_when_it_has_nothing_left_to_try(monkeypatch):
    char.update_profile("Sagira", "You are Sagira.", [], "")
    char.add_memory("Resting: char Sagira", "0", source="sheet")
    said = "I keep hitting the same wall (x). I have tried every way to make new work on my own and none can run now. I will rest until something new comes in."
    steps = iter([("ok", "reflect: a"), ("stuck", said), ("ok", "never runs")])
    run_id = _run(monkeypatch, [5.0], {"max_steps": 50, "hi": 1.0})
    assert train.status()["runs"][0]["why"] == "used all 50 steps"  # the plain run, for contrast
    monkeypatch.setattr(train, "_one_step", lambda: next(steps))
    con = train._con()
    with con:
        run_id = con.execute("INSERT INTO train_runs (persona, config, status) VALUES ('Sagira', '{}', 'running')").lastrowid
    con.close()
    train.RUN.clear(); train.RUN.update(id=run_id, pause=threading.Event(), stop=threading.Event())
    train._loop(run_id, {**train.DEFAULTS, "max_steps": 50})
    r = train.status()["runs"][0]
    assert r["status"] == "done" and r["why"] == said and [x["kind"] for x in r["log"]] == ["start", "ok", "stuck"]


def test_a_late_tick_does_not_split_one_stretch_of_work_into_two_lanes(monkeypatch):
    import threading
    from workbench import char, train
    clock, ticks = [100.0], iter([0.1, 0.4, 0.1])  # the second sleep overshoots, as on a busy machine

    def sleep(_):
        clock[0] += next(ticks)
    alive = iter([True, True, True, False])

    class Run:
        is_alive = staticmethod(lambda: next(alive))
    monkeypatch.setattr(train.time, "sleep", sleep)
    monkeypatch.setattr(train.time, "time", lambda: clock[0])
    monkeypatch.setattr(train, "RUN", {"thread": Run(), "pause": threading.Event(), "lanes": [], "clock": 0.0})
    monkeypatch.setattr(char, "NOW", {"sys": 2, "kind": "planner"})
    train._sample(every=0.1)
    assert train.RUN["lanes"] == [[2, "planner", 0.0, 0.6]]


def test_a_sampler_stops_with_its_own_run_not_the_next_one(monkeypatch):
    import threading, time as _t
    from workbench import char, train
    mine = threading.Thread(target=_t.sleep, args=(0.5,)); mine.start()  # still alive when the next run takes RUN over
    old = {"thread": mine, "pause": threading.Event(), "lanes": [], "clock": 0.0}
    monkeypatch.setattr(train, "RUN", old)
    nxt = threading.Thread(target=_t.sleep, args=(0.3,)); nxt.start()
    monkeypatch.setattr(char, "NOW", {"sys": 2, "kind": "planner"})
    sampler = threading.Thread(target=train._sample, kwargs={"every": 0.05}); sampler.start()
    old.clear(); old.update(thread=nxt, pause=threading.Event())  # a new run starts while the old sampler is about: start() refills the same dict
    _t.sleep(0.1)
    old.update(lanes=[], clock=0.0)
    sampler.join(1)
    assert not sampler.is_alive() and old["lanes"] == []  # its run had ended: it drew nothing into the next one, and did not crash on the half-filled dict
    nxt.join()


def test_a_pipeline_run_gathers_fits_then_steers_round_after_round(monkeypatch):
    char.update_profile("Sagira", "You are Sagira.", [], "")
    models, fits = [], []
    monkeypatch.setattr(train, "_one_step", lambda: (models.append(settings.get_all().model_name), ("ok", "x"))[1])
    monkeypatch.setattr(llm, "ensure", lambda s, m, **k: fits.append(m))
    monkeypatch.setattr(steer, "world_concept", lambda: "w")
    monkeypatch.setattr(steer, "truth_concept", lambda: "")
    monkeypatch.setattr(char, "disposition", lambda: {"curiosity": 5.0, "maturity": 0.1})
    run_id = _run_with(monkeypatch, {"gather": "dory", "gather_steps": 2, "steer_steps": 1, "max_steps": 8})
    log = train.status()["runs"][0]["log"][1:]
    assert [e["stage"] for e in log] == ["gather", "gather", "fit", "steer"] * 2
    assert models == ["dory", "dory", llm.STEER, "dory", "dory", llm.STEER]
    assert fits == [llm.STEER, llm.STEER] and "truth not enough facts yet" in log[2]["outcome"]
    assert settings.OVERRIDE == {} and run_id


def test_a_pipeline_run_starts_in_planner_mode_and_needs_a_step_to_run(monkeypatch):
    char.update_profile("Sagira", "You are Sagira.", [], "")
    monkeypatch.setattr(train, "_loop", lambda run_id, c: None)
    monkeypatch.setattr(train, "_sample", lambda *a: None)
    with pytest.raises(ValueError, match="at least one"):
        train.start({"gather": "dory", "gather_steps": 0, "steer_steps": -3})
    assert char.mode() == "curious"
    train.start({"gather": "dory"})
    assert char.mode() == "planner"


def test_a_pipeline_run_refuses_the_steer_engine_to_gather_on():
    with pytest.raises(ValueError, match="server engine"):
        train.start({"gather": llm.STEER})
