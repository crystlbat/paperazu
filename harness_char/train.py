"""Training runs: the live persona learns by itself until a target, and its progress is kept as a fine-tuning dataset.

You set how long it may run, the range curiosity should come down into, and a step budget. A background thread runs one
learning step at a time (a harness cycle in planner mode, else the Verifier's pick) and records curiosity, maturity and
its needs after each. Whenever curiosity falls or maturity rises by enough, it takes a snapshot: its reply prompt then,
what is working (notes let in, replies the Verifier passed, tones that met its traits, guesses that came out right),
what is not (notes turned away, mistakes, tones that missed, guesses far off), and the examples a fine-tune can learn from.
The dataset is JSONL in the shape Anthropic's Claude fine-tuning takes: {"system": ..., "messages": [user, assistant]}.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from harness_char import char
from shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS train_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, persona TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL,
  why TEXT NOT NULL DEFAULT '', log TEXT NOT NULL DEFAULT '[]', started_at TEXT DEFAULT (datetime('now')), ended_at TEXT);
CREATE TABLE IF NOT EXISTS train_snaps (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, step INTEGER NOT NULL, why TEXT NOT NULL,
  data TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));
"""
DEFAULTS = {"minutes": 20.0, "lo": 0.0, "hi": 1.0, "max_steps": 60, "drop": 0.5, "rise": 0.05}
IDLE_STOP = 6  # this many steps in a row that do nothing: there is nothing left to learn right now
FAIL_STOP = 3  # this many failures in a row: stop rather than spin
RUN: dict[str, Any] = {}  # the run in this process: id, its pause and stop flags, the thread
_lock = threading.Lock()


def _con() -> Any:
    con = db.connect()
    con.executescript(SCHEMA)
    return con


def active() -> bool:
    return bool(RUN.get("thread") and RUN["thread"].is_alive())


def _top() -> int:
    con = db.connect()
    try:
        return con.execute("SELECT COALESCE(MAX(id), 0) AS m FROM char_memories").fetchone()["m"]
    finally:
        con.close()


def _set(run_id: int, **cols: Any) -> None:
    con = _con()
    with con:
        con.execute(f"UPDATE train_runs SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", (*cols.values(), run_id))
    con.close()


def _rows(title_like: str, start: int) -> list[Any]:
    con = db.connect()
    rows = con.execute("SELECT id, title, content FROM char_memories WHERE source = 'sheet' AND title LIKE ? AND id > ? ORDER BY id", (title_like, start)).fetchall()
    con.close()
    return rows


def snapshot(run_id: int, step: int, why: str) -> dict[str, Any]:
    """What it is now: its prompt, what works and what does not, its numbers, and the examples a fine-tune learns from."""
    start, system = char._start(), char.prompt_now()
    con = db.connect()
    notes = {r["id"]: r for r in con.execute("SELECT id, title, content, source FROM char_memories WHERE title LIKE 'Reflection: %' AND id > ?", (start,))}
    turns = [dict(r) for r in con.execute("SELECT id, role, text FROM char_turns WHERE id IN (SELECT id FROM char_turns ORDER BY id DESC LIMIT 400) ORDER BY id")]
    con.close()
    checked = {int(r["title"].removeprefix("Checked: ")): r["content"] for r in _rows("Checked: %", start) if r["title"].removeprefix("Checked: ").isdigit()}
    reviewed = {int(r["title"].removeprefix("Reviewed: ")): r["content"] for r in _rows("Reviewed: %", start) if r["title"].removeprefix("Reviewed: ").isdigit()}
    tones = [json.loads(r["content"]) for r in _rows("Tone tried: %", start)]
    guesses = [(int(r["title"].removeprefix("Guess: ")), *r["content"].split("|", 1)) for r in _rows("Guess: %", start) if "|" in r["content"] and r["title"].removeprefix("Guess: ").isdigit()]
    asks = [json.loads(r["content"]) for r in _rows("A%: %", start) if r["title"].startswith(("Asking: ", "Answered: "))]
    topic = lambda i: notes[i]["title"].removeprefix("Reflection: ") if i in notes else str(i)
    works = {"notes let in": [topic(i) for i, v in checked.items() if v == "keep"],
             "replies passed": [t["text"][:200] for t in turns if t["role"] == "dot" and reviewed.get(t["id"]) == "ok"],
             "tones that met its traits": [t["tone"][:300] for t in tones if t.get("met")],
             "guesses that came out right": [f"{topic(i)}: {g[:160]}" for i, s, g in guesses if float(s) < 0.3]}
    fails = {"notes turned away": [topic(i) for i, v in checked.items() if v == "drop"],
             "mistakes": [f"asked {a.get('asked', '')[:120]!r}, said {a.get('said', '')[:160]!r}: {a.get('why', '')}" for a in asks],
             "tones that missed": [f"{t.get('why', '')}: {t['tone'][:200]}" for t in tones if not t.get("met")],
             "guesses far off": [f"{topic(i)}: {g[:160]} ({round(float(s) * 100)}% off)" for i, s, g in guesses if float(s) >= 0.5]}
    examples = []
    for i, t in enumerate(turns):  # what it said well: a reply the Verifier passed, with what you asked
        if t["role"] == "dot" and reviewed.get(t["id"]) == "ok" and i and turns[i - 1]["role"] == "user":
            examples.append({"kind": "reply", "user": turns[i - 1]["text"], "assistant": t["text"]})
    for t in tones:  # a better reply the tune step wrote and scored as meeting every trait
        if t.get("met") and t.get("trial") and t.get("asked"):
            examples.append({"kind": "tuned", "user": t["asked"], "assistant": t["trial"]})
    for i, v in checked.items():  # what it knows: a question it asked itself, answered by a note its Verifier let in
        if v == "keep" and i in notes and notes[i]["source"] == "reflection":
            q = topic(i)
            examples.append({"kind": "knowledge", "user": q if q.endswith("?") else f"Tell me about {q}.", "assistant": notes[i]["content"][:1500]})
    d = char.disposition()
    data = {"why": why, "step": step, "prompt": system, "works": works, "fails": fails, "examples": [e | {"system": system} for e in examples],
            "numbers": {"curiosity": d["curiosity"], "maturity": d["maturity"], "needs": char.needs(), "trust": char.trust()["value"]}}
    con = _con()
    with con:
        con.execute("INSERT INTO train_snaps (run_id, step, why, data) VALUES (?, ?, ?, ?)", (run_id, step, why, json.dumps(data)))
    con.close()
    return data


def _vars(d: dict[str, Any]) -> dict[str, float]:
    """Every number that moves while it learns, for the Story charts: its needs, trust and frontier beside curiosity and maturity."""
    return {**{k: round(v, 3) for k, v in char.needs().items()}, "trust": char.trust()["value"], **({"frontier": round(d["frontier"]["term"], 3)} if isinstance(d.get("frontier"), dict) and "term" in d["frontier"] else {})}


WAIT_TURN = 300.0  # seconds a run step waits for a cycle already running


def _one_step() -> tuple[str, str]:
    """One learning step, the way idle time runs them: a harness cycle in planner mode, else the Verifier's pick. Forced: a run ignores tiredness and quiet."""
    if char.mode() == "planner":
        from harness_char import harness  # harness imports char
        until = time.time() + WAIT_TURN  # idle learning may be mid-cycle when the run starts: wait for it (stop still works), do not count it as a failure
        while harness._lock.locked() and time.time() < until and not RUN["stop"].is_set():
            time.sleep(0.5)
        if RUN["stop"].is_set():
            return "skipped", "stopped while waiting its turn"
        c = harness.cycle(force=True, wait=5)
        did = [x for x in c.get("executed", []) if x.get("outcome") == "ok"]
        return ("ok" if did else "skipped"), " · ".join(x["cmd"] for x in did) or "cycle did nothing"
    r = char.rest(True, None, force=True)
    return ("skipped", r.get("why") or "nothing to do") if r.get("done") else ("ok", f"{r['kind']}: {r['topic']}")


def _loop(run_id: int, cfg: dict[str, Any]) -> None:
    log: list[dict[str, Any]] = []
    steps = idle = fails = 0
    spent, t_last = 0.0, time.time()
    d = char.disposition()
    mark = {"curiosity": d["curiosity"], "maturity": d["maturity"]}
    peaked = d["curiosity"] > cfg["hi"]  # "came down into the range": a fresh persona starts low, rises as it meets names, then settles
    log.append({"step": 0, "t": 0, "curiosity": d["curiosity"], "maturity": d["maturity"], **_vars(d), "kind": "start", "outcome": "", "snap": True})
    snapshot(run_id, 0, "start")
    _set(run_id, log=json.dumps(log))  # the start point shows at once, not after the first whole cycle
    status, why = "done", ""
    while True:
        now = time.time()
        if not RUN["pause"].is_set():
            spent += now - t_last
        t_last = now
        if RUN["stop"].is_set():
            status, why = "stopped", "you stopped it"
            break
        if RUN["pause"].is_set():
            _set(run_id, status="paused")
            time.sleep(0.5)
            continue
        if spent >= cfg["minutes"] * 60:
            why = f"time ran out ({cfg['minutes']:g} min)"
            break
        if steps >= cfg["max_steps"]:
            why = f"used all {cfg['max_steps']} steps"
            break
        if steps and peaked and cfg["lo"] <= d["curiosity"] <= cfg["hi"]:
            why = f"reached the target: curiosity {d['curiosity']} settled between {cfg['lo']:g} and {cfg['hi']:g}"
            break
        if idle >= IDLE_STOP:
            why = f"{IDLE_STOP} steps in a row did nothing: nothing left to learn right now"
            break
        if fails >= FAIL_STOP:
            status, why = "failed", f"{FAIL_STOP} steps in a row failed"
            break
        _set(run_id, status="running")
        try:
            outcome, detail = _one_step()
            fails = 0
        except Exception as e:  # noqa: BLE001 — a run keeps going past one bad step, and stops after a few
            outcome, detail = "failed", str(e)[:200]
            fails += 1
        steps += 1
        idle = idle + 1 if outcome == "skipped" else 0
        d = char.disposition()
        peaked = peaked or d["curiosity"] > cfg["hi"]
        snap = ""
        if d["curiosity"] <= mark["curiosity"] - cfg["drop"]:
            snap = f"curiosity fell to {d['curiosity']}"
        elif d["maturity"] >= mark["maturity"] + cfg["rise"]:
            snap = f"maturity rose to {d['maturity']}"
        if snap:
            snapshot(run_id, steps, snap)
            mark = {"curiosity": d["curiosity"], "maturity": d["maturity"]}
        log.append({"step": steps, "t": round(spent), "curiosity": d["curiosity"], "maturity": d["maturity"], **_vars(d), "kind": outcome, "outcome": detail[:120], "snap": bool(snap)})
        _set(run_id, log=json.dumps(log))
    from harness_char import harness
    harness.CANCEL.clear()  # idle learning after the run is not cancelled
    snapshot(run_id, steps, f"end: {why}")
    cfg["mem1"] = _top()
    char.prune_questions()  # the letter that follows asks you only what is left
    if log:
        log[-1]["snap"] = True  # the closing checkpoint shows on the trace too
    _set(run_id, status=status, why=why, log=json.dumps(log), config=json.dumps(cfg), ended_at=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))


def start(cfg: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        if active():
            raise RuntimeError("A run is already going: pause or stop it first.")
        c = {k: type(v)(cfg.get(k, v)) for k, v in DEFAULTS.items()}
        if c["lo"] > c["hi"]:
            c["lo"], c["hi"] = c["hi"], c["lo"]
        c["minutes"], c["max_steps"] = max(0.5, min(c["minutes"], 600)), max(1, min(c["max_steps"], 2000))
        char._since(True, char.get_profile()["name"])
        c["mem0"] = _top()  # what it knew before: every mesh node past this id was made by this run
        con = _con()
        with con:
            run_id = con.execute("INSERT INTO train_runs (persona, config, status) VALUES (?, ?, 'running')", (char.get_profile()["name"], json.dumps(c))).lastrowid
        con.close()
        RUN.clear()
        RUN.update(id=run_id, pause=threading.Event(), stop=threading.Event())
        RUN.update(lanes=[], clock=0.0)
        RUN["thread"] = threading.Thread(target=_loop, args=(run_id, c), daemon=True, name=f"train-{run_id}")
        RUN["thread"].start()
        threading.Thread(target=_sample, daemon=True, name=f"train-{run_id}-lanes").start()
    return status()


def _sample(every: float = 1.0) -> None:
    """While the run lives, once a second: the run's clock, and which system is at work, as lanes [sys, kind, t0, t1] the Story draws growing.
    shortcut: lanes live in memory, so a past run's lanes are gone after a restart; store them on the run row if that matters."""
    last = time.time()
    while active():
        time.sleep(every)
        now = time.time()
        if RUN["pause"].is_set():
            last = now
            continue
        RUN["clock"] += now - last
        last = now
        lanes, w, t = RUN["lanes"], dict(char.NOW), round(RUN["clock"], 1)
        if lanes and lanes[-1][0] == w.get("sys") and lanes[-1][1] == w.get("kind") and lanes[-1][3] >= t - every * 1.5:
            lanes[-1][3] = t
        elif w.get("sys") is not None:
            lanes.append([w["sys"], w["kind"], round(t - every, 1), t])


def control(action: str) -> dict[str, Any]:
    if not active():
        raise RuntimeError("No run is going.")
    from harness_char import harness  # harness imports char
    if action == "stop":
        harness.CANCEL.set()  # the cycle in hand skips what it has not started, so stop lands within one command
    {"pause": RUN["pause"].set, "resume": RUN["pause"].clear, "stop": RUN["stop"].set}[action]()
    return status()


def status() -> dict[str, Any]:
    """The persona's runs, newest first, each with its log and snapshot count; a run a restart cut short says so."""
    con = _con()
    rows = con.execute("SELECT r.*, (SELECT COUNT(*) FROM train_snaps s WHERE s.run_id = r.id) AS snaps, "
                       "(SELECT COALESCE(SUM(json_array_length(json_extract(s.data, '$.examples'))), 0) FROM train_snaps s WHERE s.run_id = r.id) AS examples "
                       "FROM train_runs r WHERE persona = ? ORDER BY id DESC LIMIT 20", (char.get_profile()["name"],)).fetchall()
    con.close()
    out = []
    for r in rows:
        live = active() and RUN.get("id") == r["id"]
        st = r["status"] if live or r["status"] not in ("running", "paused") else "stopped"  # its thread died with the server
        out.append({"id": r["id"], "status": ("paused" if live and RUN["pause"].is_set() else st), "why": r["why"] or ("the app restarted" if st != r["status"] else ""),
                    "config": json.loads(r["config"]), "log": json.loads(r["log"]), "snaps": r["snaps"], "examples": r["examples"], "started": r["started_at"], "ended": r["ended_at"],
                    **({"lanes": RUN.get("lanes", []), "clock": round(RUN.get("clock", 0), 1)} if RUN.get("id") == r["id"] else {})})
    return {"active": active(), "runs": out, "defaults": DEFAULTS}


def snapshots(run_id: int) -> list[dict[str, Any]]:
    con = _con()
    rows = con.execute("SELECT step, why, data, created_at FROM train_snaps WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    con.close()
    return [{"step": r["step"], "why": r["why"], "at": r["created_at"], **json.loads(r["data"])} for r in rows]


def dataset(run_id: int) -> str:
    """The run's examples as JSONL for a Claude fine-tune: one {"system", "messages"} per line; the same exchange once, from its latest snapshot."""
    seen: dict[str, dict[str, Any]] = {}
    words = char.world_words()
    for s in snapshots(run_id):
        for e in s["examples"]:
            if not (char.on_world(e["user"], words) or sum(bool(re.search(rf"\b{re.escape(w)}\b", e["assistant"])) for w in words) >= 3):
                continue  # drift a note kept before the world check must not be taught: a news story that names its game once is not its world
            seen[e["user"].strip().lower()] = {"system": e["system"], "messages": [{"role": "user", "content": e["user"]}, {"role": "assistant", "content": e["assistant"]}]}
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in seen.values())
