"""The harness cycle: a planner model picks commands, the controller (plain code) checks them, the executor runs them through
char's own step code, and the Verifier judges this cycle's trace. Its feedback goes into the next planner prompt."""
import json
import re
import threading
from typing import Any

from . import char, db, jobs, llm, settings

DOES = {"plan": "write a short research plan (three topics) from what it has read",
        "bake": "consolidate: freeze the answer counts maturity is read from",
        "want": "ask the person for something it lacks: a source on a guess that was far off, or a topic the web had nothing on",
        "journal": "write a page of its study journal from what it studied, guessed wrong and was taught since the last page",
        "goal": "turn the oldest open plan line into one question",
        "ask": "turn names in the graph into new questions",
        "wonder": "ask one follow-up question about the newest note",
        "speculate": "guess something its summaries and notes do not say, and ask the question that would prove the guess right or wrong",
        "fill": "fill one empty slot of its sheet (world, what it calls you, catchphrase)",
        "reflect": "look a topic up on the web and write a note (default: the first open question)",
        "extract": "read the newest note for names",
        "ideas": "read a named note for the ideas around its names",
        "practise": "check its last reply sounds like itself, rewrite it if not",
        "sort": "read one chat message for names",
        "fold": "fold a name with three or more notes into one summary",
        "check": "verify one unchecked note: on topic and grounded (default: the oldest)",
        "review": "reread one of its own replies and flag a mistake",
        "tune": "hold a reply to its grown traits; if it missed, rewrite the tone section, run it, and keep it only if it works"}
COMMANDS: dict[str, dict[str, Any]] = {k: {"name": k, "args": char.TARGETS.get(k, ""), "does": DOES[k], "system": n,
                                           "role": None if k in char.NO_MODEL else "chat"}
                                       for n, (_, _, ks) in char.SYSTEMS.items() for k in ks}
BUDGET = 4
_lock = threading.Lock()  # one cycle at a time: a second caller is turned away, not queued


def _rows(title_like: str, limit: int = 1) -> list[Any]:
    con = db.connect()
    rows = con.execute("SELECT id, title, content FROM char_memories WHERE source = 'sheet' AND title LIKE ? AND id > ? ORDER BY id DESC LIMIT ?",
                       (title_like, char._start(), limit)).fetchall()
    con.close()
    return rows


def _unchecked() -> list[Any]:
    start = char._start()
    con = db.connect()
    rows = con.execute("SELECT id, title FROM char_memories WHERE source = 'reflection' AND id > ? AND CAST(id AS TEXT) NOT IN "
                       "(SELECT substr(title, 10) FROM char_memories WHERE source = 'sheet' AND title LIKE 'Checked: %') ORDER BY id", (start,)).fetchall()
    con.close()
    return rows


def stale() -> set[str]:
    """Commands whose last run was skipped with nothing new since: run again, they skip again. Any row but the harness's own bookkeeping counts as new."""
    con = db.connect()
    rows = con.execute("SELECT title, content, MAX(id) AS id FROM char_memories WHERE source = 'sheet' AND title LIKE 'Run: %' AND id > ? GROUP BY title", (char._start(),)).fetchall()
    new = con.execute("SELECT COALESCE(MAX(id), 0) AS m FROM char_memories WHERE NOT (source = 'sheet' AND (title LIKE 'Run: %' OR title = 'Tick' OR title LIKE 'Cycle: %' OR title LIKE 'Feedback: %' OR title LIKE 'Stuck: %' OR title LIKE 'Fail: %' OR title LIKE 'Correction: %'))").fetchone()["m"]
    con.close()
    return {r["title"].removeprefix("Run: ") for r in rows if r["id"] > new and '"outcome": "skipped"' in r["content"]}


STUCK_AFTER = 3  # cycles in a row that kept nothing: it is going round in circles
UNSTICK = ("reflect", "goal", "plan", "ask", "wonder", "speculate", "extract")  # answering what is open first, then the steps that make new work; none waits on you


def notice(n: int, plan: list[dict[str, Any]], rejected: list[dict[str, str]], force: bool = False) -> dict[str, Any]:
    """Its picture of itself, no model: is it stuck, on what, and what it will try instead. Stuck: nothing in this plan can run,
    or the last STUCK_AFTER cycles kept nothing. A way out it tried in the last two times it was stuck is not tried again."""
    fb = [json.loads(r["content"]) for r in _rows("Feedback: %", STUCK_AFTER)]
    dry = len(fb) == STUCK_AFTER and not any(v["keep"] for vs in fb for v in vs)
    if plan and not dry:
        return {"stuck": False}
    walls: dict[str, int] = {}
    for r in _rows("Run: %", 12):
        c = json.loads(r["content"])
        if c.get("outcome") == "skipped":
            w = f"{r['title'].removeprefix('Run: ')}: {c.get('detail', '').removesuffix(' (arg ignored)')[:90]}"
            walls[w] = walls.get(w, 0) + 1
    for x in rejected:
        walls[x["why"]] = walls.get(x["why"], 0) + 1
    on = max(walls, key=walls.get) if walls else "nothing in its plan could run"
    tried = {json.loads(r["content"]).get("try") for r in _rows("Stuck: %", 2)}
    _, blocked = char._blocks(True, force)
    idle, have = stale(), {p["name"] for p in plan}
    nxt = next((k for k in UNSTICK if k not in idle and not blocked.get(k) and k not in have and k not in tried), "")
    said = (f"I keep hitting the same wall ({on}). " +
            (f"So I will {DOES[nxt]} instead." if nxt else "I have tried every way to make new work on my own and none can run now. I will rest until something new comes in."))
    me = {"stuck": True, "on": on, "try": nxt, "said": said, "spent": not nxt}
    char.add_memory(f"Stuck: {n}", json.dumps(me), source="sheet")
    return me


def prompt(budget: int = BUDGET) -> list[dict[str, str]]:
    """The planner's messages: goal (open plan lines), the command catalogue, a state summary and the last Verifier feedback."""
    who = char.get_profile()["name"]
    d = char.disposition()
    plans = [r["content"] for r in _rows("Plan: %", 5)]
    names = [n["name"] for n in char.graph()["nodes"] if n["kind"] == "concrete"][:12]
    fb = _rows("Feedback: %")
    cat = "\n".join(f"- {c['name']}{' <' + c['args'] + '>' if c['args'] else ''}: {c['does']}" for c in COMMANDS.values())
    state = [f"curiosity {d['curiosity']}, maturity {d['maturity']}, frontier per layer {json.dumps(d['frontier']['layers'])}",
             "open questions: " + ("; ".join(char._open_questions(char._start())[:5]) or "none"),
             "unchecked notes: " + (", ".join(f"{r['id']} ({r['title'].removeprefix('Reflection: ')[:50]})" for r in _unchecked()[:5]) or "none"),
             "names in its graph: " + (", ".join(names) or "none"),
             "needs (0 to 1; a low one says what to do first): " + ", ".join(f"{k} {v:.2f}" for k, v in char.needs().items())]
    if idle := sorted(stale()):  # in plain words, not command syntax: a small planner copied "cmd: drop (why)" lines back as its next commands
        state.append("nothing to do for these until something new comes in (do not pick them): " + ", ".join(idle))
    if fb:
        vs = json.loads(fb[0]["content"])
        if worked := sorted({v["cmd"].split()[0] for v in vs if v["keep"]}):
            state.append("worked last cycle: " + ", ".join(worked))
    useful = [f'reflect "{qs[0]}"' for qs in [char._open_questions(char._start())] if qs] + \
             [f"check {u[0]['id']}" for u in [_unchecked()] if u]
    state.append("most useful now: " + ("; ".join(useful) or "plan, then goal, to make new questions"))
    if sp := char.speculations():
        state.append(f"its speculations: {sum(x['held'] for x in sp)} of {len(sp)} held up when checked" + "".join(f"; held: {x['guess'][:90]}" for x in sp if x["held"])[:400])
    if (last := cycles(1)) and last[0].get("self", {}).get("stuck"):
        state.append("what it noticed about itself last cycle: " + last[0]["self"]["said"])
    return [{"role": "system", "content": f"You plan the next steps of {who}'s learning. Pick at most {budget} commands from the catalogue. "
                                          "Reply with commands only, one per line, like: reflect \"a topic\" or check 12. No other text." + char._fix("planner")},
            {"role": "user", "content": "Goal:\n" + ("\n".join(f"- {p}" for p in plans) or f"- learn about {who}'s world") +
                                        f"\n\nCommands:\n{cat}\n\nState:\n" + "\n".join(f"- {x}" for x in state)}]


LINE = re.compile(r"^([A-Za-z_]+)\s*[:(]?\s*(.*?)\)?$")


def parse(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """Commands from a planner reply, leniently: a JSON list (of strings or {cmd, arg} objects), or one command per line
    (`reflect "x"`, `reflect: x`, `check(12)`, bullets and numbering stripped). Returns (commands, lines it could not read)."""
    body = re.sub(r"^```\w*|```$", "", (text or "").strip()).strip()
    items: list[Any] = []
    if body.startswith("["):
        try:
            items = json.loads(body)
        except ValueError:
            items = []
    if not isinstance(items, list) or not items:
        items = [ln for ln in (text or "").splitlines() if ln.strip()]
    cmds, bad = [], []
    for it in items:
        if isinstance(it, dict):
            name, arg = it.get("cmd") or it.get("command") or it.get("name") or "", it.get("arg", it.get("args", ""))
            arg = " ".join(map(str, arg)) if isinstance(arg, list) else str(arg or "")
            if not name:
                bad.append(json.dumps(it)[:80])
                continue
            cmds.append({"name": str(name).strip().lower(), "arg": arg.strip().strip("\"'` ")})
            continue
        line = re.sub(r"^[\s\-*•\d.)]+", "", str(it)).strip().strip("`").strip()
        if not (mm := LINE.match(line)):
            bad.append(str(it)[:80])
            continue
        cmds.append({"name": mm[1].lower(), "arg": mm[2].strip().strip("\"'` ")})
    return cmds, bad


def _text(c: dict[str, str]) -> str:
    return c["name"] + (f' "{c["arg"]}"' if c.get("arg") else "")


def starved(proposed: list[dict[str, str]], force: bool = False) -> str:
    """The step that has waited longest, when the planner left it out: none of the last 12 runs was it. A small planner
    recites the same few commands, so without this, names never get pulled from notes and notes never get checked."""
    runs = [r["title"].removeprefix("Run: ") for r in _rows("Run: %", 12)]
    if len(runs) < 12:
        return ""
    _, blocked = char._blocks(True, force)
    asked = {c["name"] for c in proposed}
    waiting = [k for k in COMMANDS if k not in asked and k not in runs and not blocked.get(k)]
    order = ("check", "extract", "review", "sort", "fold", "ideas", "wonder", "fill", "practise", "tune", "journal", "want")  # checking and reading for names first: the rest builds on them
    return next((k for k in order if k in waiting), waiting[0] if waiting else "")


def validate(cmds: list[dict[str, str]], budget: int = BUDGET, force: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The controller, no model: each command must exist, point at real things, have its system on and not be blocked, and fit the budget.
    Note ids and names are repaired where the intent is plain (#12 → 12, a name in the wrong case). Returns (plan grouped by model, rejected)."""
    _, blocked = char._blocks(True, force)
    notes = {str(r["id"]) for r in _unchecked()}
    names = {n["name"].lower(): n["name"] for n in char.graph()["nodes"]}
    plan: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    idle = stale()
    ready = {"reflect"} if char._open_questions(char._start()) else set()
    ready |= {"check"} if _unchecked() else set()
    cmds = sorted(cmds, key=lambda c: c["name"] not in ready)  # a small planner recites the catalogue in order; work that can happen now goes first
    for c in cmds:
        spec, arg = COMMANDS.get(c["name"]), re.split(r"[\"']\s*:\s", c.get("arg", ""))[0].strip("\"' ")  # repair: a small planner glues the catalogue text after the topic
        why = ""
        if not spec:
            why = "unknown command"
        elif re.search(r"did not do anything|\bdrop \(|\bkeep \(", arg):
            why = "copied last cycle's feedback, not a command"
        elif c["name"] in idle and c["name"] not in ready:
            why = "skipped last time and nothing has changed for it"
        elif blocked.get(c["name"]):
            why = blocked[c["name"]]
        elif spec["args"] == "note id" and arg:
            arg = re.sub(r"\D", "", arg)
            why = "" if arg in notes else f"no unchecked note {c['arg']} in the live persona"
        elif spec["args"] == "name" and arg:
            arg = names.get(arg.lower(), "")
            why = "" if arg else f"no name {c['arg']} in its graph"
        if not why and any(p["name"] == c["name"] and p["arg"] == arg for p in plan):
            why = "duplicate"
        if not why and len(plan) >= budget:
            why = f"over budget ({budget})"
        if why:
            rejected.append({"cmd": _text(c), "why": why})
        else:
            plan.append({"name": c["name"], "arg": arg, "role": spec["role"]})
    plan.sort(key=lambda p: p["role"] or "")  # stable: same-model commands sit together, so each model loads at most once
    return plan, rejected


def _role_settings(s: settings.Settings, role: str) -> settings.Settings:
    m = getattr(s, f"{role}_model")
    return s.model_copy(update={"model_name": m}) if m else s


CANCEL = threading.Event()  # a training run being stopped: the cycle drops the commands it has not started


def execute(plan: list[dict[str, Any]], s: settings.Settings, swaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run each command through char.rest's own step code; each run writes its "Run: <kind>" row as before."""
    out = []
    for p in plan:
        if CANCEL.is_set():
            out.append({"cmd": _text(p), "name": p["name"], "outcome": "skipped", "detail": "stopped before it ran", "made": []})
            continue
        if p["role"] and (sw := llm.ensure(s, getattr(s, f"{p['role']}_model"))):
            swaps.append(sw)
        e = char.ENGINES.get(p["name"]) or {}
        runs = e.get("runs", 0)
        con = db.connect()
        top = con.execute("SELECT COALESCE(MAX(id), 0) AS m FROM char_memories").fetchone()["m"]
        con.close()
        char.rest(True, only=p["name"], target=p["arg"] or None, force=True)
        e = char.ENGINES.get(p["name"]) or {}
        ran = e.get("runs", 0) > runs
        con = db.connect()
        made = [dict(r) for r in con.execute("SELECT id, title, source FROM char_memories WHERE id > ? AND title NOT LIKE 'Run: %' AND title != 'Tick'", (top,))]
        con.close()
        ignored = bool(p["arg"]) and p["name"] not in char.TARGETS
        out.append({"cmd": _text(p), "name": p["name"], "outcome": e.get("outcome", "blocked") if ran else "blocked",
                    "detail": (e.get("detail", "") if ran else e.get("blocked", "did not run")) + (" (arg ignored)" if ignored else ""), "made": made})
    return out


def verify(executed: list[dict[str, Any]], s: settings.Settings, swaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exact checks first; whatever they leave open goes to one judging call on the judge model."""
    verdicts: list[dict[str, Any] | None] = []
    for x in executed:
        v = None
        if x["outcome"] != "ok":
            v = {"keep": False, "why": f"did not do anything: {x['detail'][:80]}"}
        elif x["name"] == "reflect":
            grounds = [r for r in x["made"] if r["title"].startswith("Ground: ")]
            con = db.connect()
            g = [float(con.execute("SELECT content FROM char_memories WHERE id = ?", (r["id"],)).fetchone()["content"] or 1) for r in grounds]
            con.close()
            if g and g[0] < 0.5:
                v = {"keep": False, "why": f"grounding {g[0]:.2f}: names things its sources do not"}
        elif x["name"] in char.NO_MODEL or x["name"] == "check":
            v = {"keep": True, "why": "ran and did what it says"}
        verdicts.append(v)
    open_ = [i for i, v in enumerate(verdicts) if v is None]
    if open_:
        if sw := llm.ensure(s, s.judge_model):
            swaps.append(sw)
        msgs = [{"role": "system", "content": "You judge the steps of a learning agent. For each numbered step reply on its own line: the number, KEEP or DROP, then a few words why."},
                {"role": "user", "content": "\n".join(f"{n + 1}. {executed[i]['cmd']} -> {executed[i]['detail'][:200]}" for n, i in enumerate(open_))}]
        try:
            said = jobs.complete(_role_settings(s, "judge"), msgs, max_tokens=40 * len(open_)) or ""
        except Exception as e:
            said = ""
            char._log("judge", msgs, f"(failed: {e})")
        else:
            char._log("judge", msgs, said)
        got = {int(m[1]): (m[2].upper() == "KEEP", m[3].strip(" .-:") or m[2].lower()) for m in re.finditer(r"(?im)^\D*?(\d+)\W+(KEEP|DROP)\b\W*(.*)$", said)}
        for n, i in enumerate(open_):
            keep, why = got.get(n + 1, (True, "judge gave no verdict; it ran"))
            verdicts[i] = {"keep": keep, "why": why[:100]}
    return [{"cmd": x["cmd"], **v} for x, v in zip(executed, verdicts)]  # type: ignore[dict-item]


def cycle(budget: int = BUDGET, force: bool = False, wait: float = 0) -> dict[str, Any]:
    """One full cycle: planner → controller → executor → Verifier. Persisted as "Cycle: n" and "Feedback: n" sheet rows.
    wait: seconds to wait for a cycle already running (a training run waits its turn; a click does not)."""
    if not (_lock.acquire(timeout=wait) if wait > 0 else _lock.acquire(blocking=False)):
        raise RuntimeError("a cycle is already running")
    try:
        char.init_db()
        s = settings.get_all()
        n = len(_rows("Cycle: %", 10**9)) + 1
        failed = ""
        swaps: list[dict[str, Any]] = []
        if sw := llm.ensure(s, s.planner_model):
            swaps.append(sw)
        msgs = prompt(budget)
        char.NOW.update(sys=2, kind="planner")
        try:
            text = jobs.complete(_role_settings(s, "planner"), msgs, max_tokens=120) or ""
        except Exception as e:
            text, failed = "", str(e)[:300]
            char._log("planner", msgs, f"(failed: {e})")
        else:
            char._log("planner", msgs, text)
        finally:
            char.NOW.clear()
        proposed, bad = parse(text)
        if bad or not proposed:  # a self-correction: two of these and the Verifier proposes the planner fix
            char._fail("planner")
        if (k := starved(proposed, force)):
            proposed = [{"name": k, "arg": ""}, *proposed]  # one per cycle, up front, so the budget does not cut it
        plan, rejected = validate(proposed, budget, force)
        rejected += [{"cmd": b, "why": "could not read it as a command"} for b in bad]
        me = notice(n, plan, rejected, force)
        if me.get("try"):  # its own way out goes in, in place of the last pick if the plan is full
            plan = plan[:budget - 1] + [{"name": me["try"], "arg": "", "role": COMMANDS[me["try"]]["role"]}]
        executed = execute(plan, s, swaps)
        verdicts = [] if CANCEL.is_set() else verify(executed, s, swaps)
        out = {"cycle": n, "plan_text": text, "proposed": [_text(c) for c in proposed], "rejected": rejected,
               "executed": [{k: x[k] for k in ("cmd", "outcome", "detail")} for x in executed], "verdicts": verdicts,
               "swaps": [{k: w[k] for k in ("from", "to", "seconds")} for w in swaps], "self": me, **({"planner_failed": failed} if failed else {})}
        char.add_memory(f"Feedback: {n}", json.dumps(verdicts), source="sheet")
        char.add_memory(f"Cycle: {n}", json.dumps(out), source="sheet")
        kept = sum(v["keep"] for v in verdicts)
        char._engine("cycle", "ok" if executed else "skipped", f"cycle {n}: {len(proposed)} proposed, {len(rejected)} rejected, {len(executed)} run, {kept} kept")
        return out
    finally:
        _lock.release()


def cycles(limit: int = 20) -> list[dict[str, Any]]:
    return [json.loads(r["content"]) for r in _rows("Cycle: %", limit)]


def totals() -> dict[str, Any]:
    """The /char/report "harness_loop" block, counted from the live persona's Cycle rows."""
    cs = cycles(10**9)
    sw = [w for c in cs for w in c["swaps"]]
    return {"cycles_run": len(cs), "proposed": sum(len(c["proposed"]) for c in cs), "rejected": sum(len(c["rejected"]) for c in cs),
            "executed": sum(len(c["executed"]) for c in cs), "kept": sum(v["keep"] for c in cs for v in c["verdicts"]),
            "dropped": sum(not v["keep"] for c in cs for v in c["verdicts"]), "swaps": len(sw), "swap_seconds": round(sum(w["seconds"] for w in sw), 1)}

