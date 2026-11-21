"""The harness cycle: a planner model picks commands, the controller (plain code) checks them, the executor runs them through
char's own step code, and the Verifier judges this cycle's trace. Its feedback goes into the next planner prompt."""
import json
import random
import re
import threading
from typing import Any

from harness_char import char, rehearse
from shared import db, llm, settings
from shared import steer as steering  # harness.steer is the drive
from pdf_research import jobs

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


CHAT_FED = ("review", "sort", "practise")  # these read the chat: only a new turn gives them work


def stale() -> set[str]:
    """Commands whose last run was skipped with nothing new for them since: run again, they skip again.
    New for a step is what feeds it: a step upstream of it in char.TOOL_FLOW that did something, or a new chat turn for the steps that read the chat.
    A step nothing feeds counts any row but bookkeeping as new (its mood rows and the judge's probes are bookkeeping too: every step writes them)."""
    con = db.connect()
    start = char._start()
    runs = con.execute("SELECT title, content, id, created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Run: %' AND id > ? ORDER BY id", (start,)).fetchall()
    new = con.execute("SELECT COALESCE(MAX(id), 0) AS m FROM char_memories WHERE NOT (source = 'sheet' AND (title LIKE 'Run: %' OR title IN ('Tick', 'Needs', 'Judge') OR title LIKE 'Cycle: %' OR title LIKE 'Feedback: %' OR title LIKE 'Stuck: %' OR title LIKE 'Fail: %' OR title LIKE 'Correction: %'))").fetchone()["m"]
    last_turn = con.execute("SELECT COALESCE(MAX(created_at), '') AS t FROM char_turns").fetchone()["t"]
    con.close()
    last: dict[str, Any] = {}
    ok_at: dict[str, int] = {}
    for r in runs:
        k = r["title"].removeprefix("Run: ")
        last[k] = r
        if '"outcome": "ok"' in r["content"]:
            ok_at[k] = r["id"]
    feeds: dict[str, set[str]] = {}
    for a, b in char.TOOL_FLOW:
        feeds.setdefault(b, set()).add(a)
    out = set()
    for k, r in last.items():
        if '"outcome": "skipped"' not in r["content"]:
            continue
        if k in CHAT_FED:
            fresh = last_turn > r["created_at"]
        elif k in feeds:
            fresh = any(ok_at.get(a, 0) > r["id"] for a in feeds[k])
        else:
            fresh = new > r["id"]
        if not fresh:
            out.add(k)
    return out


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
        if c.get("outcome") == "skipped" and r["title"] not in ("Run: cycle", "Run: model"):  # its own bookkeeping is not a wall
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
            (f"So I will {DOES[nxt]} instead." if nxt else "I will run what my plan has and see what it turns up." if plan
             else "I have tried every way to make new work on my own and none can run now. I will rest until something new comes in."))
    me = {"stuck": True, "on": on, "try": nxt, "said": said, "spent": not nxt and not plan}  # with steps still to run, what they turn up may open the way
    char.add_memory(f"Stuck: {n}", json.dumps(me), source="sheet")
    return me


def _ready() -> set[str]:
    """Steps with work waiting for them now: these run even after a skip."""
    return ({"reflect"} if char._open_questions(char._start()) else set()) | ({"check"} if _unchecked() else set())


def unavailable(force: bool = False) -> set[str]:
    """Steps the controller would turn away right now: skipped with nothing new for them, or blocked."""
    _, blocked = char._blocks(True, force)
    ready = _ready()
    return {k for k in stale() if k not in ready} | {k for k in COMMANDS if blocked.get(k)}


def prompt(budget: int = BUDGET, force: bool = False) -> list[dict[str, str]]:
    """The planner's messages: goal (open plan lines), the command catalogue, a state summary and the last Verifier feedback."""
    who = char.get_profile()["name"]
    d = char.disposition()
    plans = [r["content"] for r in _rows("Plan: %", 5)]
    names = [n["name"] for n in char.graph()["nodes"] if n["kind"] == "concrete"][:12]
    fb = _rows("Feedback: %")
    hide = unavailable(force)  # left out of the catalogue: a small planner kept picking steps the state line told it not to
    cat = "\n".join(f"- {c['name']}{' <' + c['args'] + '>' if c['args'] else ''}: {c['does']}" for c in COMMANDS.values() if c["name"] not in hide)
    state = [f"curiosity {d['curiosity']}, maturity {d['maturity']}, frontier per layer {json.dumps(d['frontier']['layers'])}",
             "open questions: " + ("; ".join(char._open_questions(char._start())[:5]) or "none"),
             "unchecked notes: " + (", ".join(f"{r['id']} ({r['title'].removeprefix('Reflection: ')[:50]})" for r in _unchecked()[:5]) or "none"),
             "names in its graph: " + (", ".join(names) or "none"),
             "needs (0 to 1; a low one says what to do first): " + ", ".join(f"{k} {v:.2f}" for k, v in char.needs().items())]
    if fb:
        vs = json.loads(fb[0]["content"])
        if worked := sorted({v["cmd"].split()[0] for v in vs if v["keep"]}):
            state.append("worked last cycle: " + ", ".join(worked))
    sc, g = d["score"], char.gains()
    state.append(f"its score J = {sc['J']} (0 to 1, push it up: how much it has answered {sc['know']} times how often its guesses come out right {round(1 - sc['surprise'], 3)})")
    if g:
        state.append("what each command did to J on average (pick the ones that raised it): " + ", ".join(f"{k} {v['gain']:+.3f} over {v['runs']}" for k, v in list(g.items())[:8]))
    useful = [f'reflect "{qs[0]}"' for qs in [char._open_questions(char._start())] if qs] + \
             [f"check {u[0]['id']}" for u in [_unchecked()] if u]
    if (sg := char.signals())["frustration"] or sg["voice"] < 1:  # rising frustration or a slipping voice says review and tune come first
        state.append(f"frustration {sg['frustration']:g} (bad past {sg['frustration_mark']:g}), voice {sg['voice']:g} (good above {sg['voice_mark']:g})"
                     + (f"; missed: {sg['missed']}" if sg["missed"] else ""))
    if r := rehearse.summary():  # how well its voice holds on fixed questions: a weak trait says tune is worth a pick
        state.append("last personality rehearsal (share of traits held, 0 to 1): " + r)
    makers = [k for k in ("plan", "goal", "ask", "wonder", "speculate") if k not in hide]
    state.append("most useful now: " + ("; ".join(useful) or (", ".join(makers[:2]) + ", to make new questions" if makers else "none")))
    if sp := char.speculations():
        state.append(f"its speculations: {sum(x['held'] for x in sp)} of {len(sp)} held up when checked" + "".join(f"; held: {x['guess'][:90]}" for x in sp if x["held"])[:400])
    if (last := cycles(1)) and last[0].get("self", {}).get("stuck"):
        state.append("what it noticed about itself last cycle: " + last[0]["self"]["said"])
    dv = char.drive(d)
    state.append(f"drive: explore {dv['E']} vs check {dv['C']} ({dv['open']} questions and notes waiting, judge trusted {dv['judge']['value']}); it {'explores' if dv['p_explore'] >= 0.5 else 'checks'} with chance {max(dv['p_explore'], 1 - dv['p_explore']):.2f}")
    return [{"role": "system", "content": f"You plan the next steps of {who}'s learning. Pick at most {budget} commands from the catalogue. "
                                          "First line: why: then one short reason that names the numbers you went by. Then commands only, one per line, like: reflect \"a topic\". No other text." + char._fix("planner")},
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
    asked, off = {c["name"] for c in proposed}, unavailable(force)
    waiting = [k for k in COMMANDS if k not in asked and k not in runs and k not in off]  # a step that would be turned away is not starved, just idle
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
    ready = _ready()
    asked = set(char._open_questions(char._start()))
    cmds = sorted(cmds, key=lambda c: c["name"] not in ready)  # a small planner recites the catalogue in order; work that can happen now goes first
    for c in cmds:
        spec, arg = COMMANDS.get(c["name"]), re.split(r"[\"']\s*:\s", c.get("arg", ""))[0].strip("\"' ")  # repair: a small planner glues the catalogue text after the topic
        if len(arg) > 12 and any(arg.lower() in x["does"].lower() for x in COMMANDS.values()):  # or hands a step its own description as the topic
            arg = ""
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
        elif c["name"] == "reflect" and arg and arg not in asked and not char.on_world(arg):  # its own question came from its notes: it is about its world even when it names nothing the check knows
            why = "off its world: sets it in another work or names nothing from it"
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
        gold = next((i for i, v in enumerate(verdicts) if v is not None and executed[i]["outcome"] == "ok"), None)  # one step an exact check already settled, shown blind: how often the judge agrees is how far to trust it
        ask = open_ + ([gold] if gold is not None else [])
        msgs = [{"role": "system", "content": "You judge the steps of a learning agent. For each numbered step reply on its own line: the number, KEEP or DROP, then a few words why."},
                {"role": "user", "content": "\n".join(f"{n + 1}. {executed[i]['cmd']} -> {executed[i]['detail'][:200]}" for n, i in enumerate(ask))}]
        try:
            said = jobs.complete(_role_settings(s, "judge"), msgs, max_tokens=40 * len(ask)) or ""
        except Exception as e:
            said = ""
            char._log("judge", msgs, f"(failed: {e})")
        else:
            char._log("judge", msgs, said)
        got = {int(m[1]): (m[2].upper() == "KEEP", m[3].strip(" .-:") or m[2].lower()) for m in re.finditer(r"(?im)^\D*?(\d+)\W+(KEEP|DROP)\b\W*(.*)$", said)}
        for n, i in enumerate(open_):
            keep, why = got.get(n + 1, (True, "judge gave no verdict; it ran"))
            verdicts[i] = {"keep": keep, "why": why[:100]}
        if gold is not None and len(ask) in got:
            char.add_memory("Judge", "1" if got[len(ask)][0] == verdicts[gold]["keep"] else "0", source="sheet")
    return [{"cmd": x["cmd"], **v} for x, v in zip(executed, verdicts)]  # type: ignore[dict-item]


llm.busy.append(lambda: "A harness cycle is running. Switch when it ends." if _lock.locked() else "")


def steer(plan: list[dict[str, Any]], rejected: list[dict[str, str]], budget: int = BUDGET, force: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    """The two drives decide this cycle: one draw against p_explore says explore or check. Checking holds back reaching for the new
    while questions are open; either way, a plan with nothing of the winning kind gets the step Thompson sampling picks from it."""
    dv = char.drive()
    mode = "explore" if random.random() < dv["p_explore"] else "check"
    group = char.EXPLORE if mode == "explore" else char.CHECK
    if mode == "check" and dv["open"]:
        held = [p for p in plan if p["name"] in char.EXPLORE]
        plan = [p for p in plan if p["name"] not in char.EXPLORE]
        rejected = rejected + [{"cmd": _text(p), "why": f"checking first: {dv['open']} questions and notes waiting, explore {dv['E']} lost to check {dv['C']}"} for p in held]
    if not any(p["name"] in group for p in plan):
        _, blocked = char._blocks(True, force)
        idle, have = stale(), {p["name"] for p in plan}
        ok = [k for k in group if k in COMMANDS and not blocked.get(k) and k not in idle and k not in have]
        if pick := char.thompson(ok):
            plan = [{"name": pick, "arg": "", "role": COMMANDS[pick]["role"]}, *plan][:budget]
    return plan, rejected, {**dv, "mode": mode}


def steerable(s: settings.Settings) -> bool:
    """The character's steps run on an in-process MLX model, the steer engine or another (its chat model, or the model when no chat model is set): pick dory or an Unsloth model and nothing is steered."""
    return llm.is_steer(s.chat_model or s.model_name) and steering.available()


def steer_arms() -> dict[float, tuple[float, float]]:
    """A Beta(a, b) per steering strength from the cycles it was used in: it pays when the cycle raised J. Discounted like the step arms."""
    con = db.connect()
    rows = [json.loads(r["content"]) for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Steer' AND id > ? ORDER BY id DESC LIMIT 100", (char._start(),))]
    rows = [r for r in rows if r.get("model", steering.MODEL) == steering.current()]  # a strength's effect is one model's own
    con.close()
    out = {}
    for e in steering.LEVELS:
        a = b = 1.0
        for i, x in enumerate(r["dJ"] for r in rows if r["eps"] == e):
            w = char.DISCOUNT ** i
            a, b = (a + w, b) if x > 1e-4 else (a, b + w) if x < -1e-4 else (a, b + char.STILL * w)
        out[e] = (round(a, 3), round(b, 3))
    return out


def pick_steer(s: settings.Settings) -> tuple[str, float, str]:
    """The controller's steering for this cycle: its world's concept, at the strength one Thompson draw picks, and the truth concept (\"\" if too few facts)."""
    if not steerable(s):
        return "", 0.0, ""
    llm.ensure(s, s.chat_model or s.model_name)  # before the fit reads its hidden states: one model in memory at a time
    if not (concept := steering.world_concept()):
        return "", 0.0, ""
    A = steer_arms()
    eps = max(steering.LEVELS, key=lambda e: random.betavariate(*A[e]))
    return concept, eps, steering.truth_concept() if eps > 0 else ""  # the truth fit is only needed when it will steer


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
        msgs = prompt(budget, force)
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
        why = (m[1].strip()[:200] if (m := re.search(r"(?im)^\W*why\W+(.+)$", text)) else "")
        proposed, bad = parse(re.sub(r"(?im)^\W*why\W.*$", "", text))
        if bad or not proposed:  # a self-correction: two of these and the Verifier proposes the planner fix
            char._fail("planner", text or "no reply")
        if (k := starved(proposed, force)):
            proposed = [{"name": k, "arg": ""}, *proposed]  # one per cycle, up front, so the budget does not cut it
        plan, rejected = validate(proposed, budget, force)
        rejected += [{"cmd": b, "why": "could not read it as a command"} for b in bad]
        plan, rejected, dv = steer(plan, rejected, budget, force)
        me = notice(n, plan, rejected, force)
        if me.get("try"):  # its own way out goes in, in place of the last pick if the plan is full
            plan = plan[:budget - 1] + [{"name": me["try"], "arg": "", "role": COMMANDS[me["try"]]["role"]}]
        concept, eps, truth = pick_steer(s)
        j0 = char.disposition()["score"]["J"] if concept else 0.0
        steering.ON.clear()
        if concept:
            steering.ON[concept] = eps  # at 0 too: the steps still run on the steer engine, unsteered, so the arms compare like with like
            if truth:  # every eps > 0 arm also carries the truth push; eps 0 stays the unsteered baseline (pick_steer gives no truth then)
                steering.ON[truth] = steering.TRUTH_EPS
        try:
            executed = execute(plan, s, swaps)
        finally:
            steering.ON.clear()  # the judge and the next planner call are never steered
        verdicts = [] if CANCEL.is_set() else verify(executed, s, swaps)
        sv = {}
        if concept:
            sv = {"concept": concept, "eps": eps, "truth": truth, "model": steering.current(), "dJ": round(char.disposition()["score"]["J"] - j0, 4)}
            char.add_memory("Steer", json.dumps(sv), source="sheet")
        out = {"cycle": n, "plan_text": text, "proposed": [_text(c) for c in proposed], "rejected": rejected,
               "executed": [{k: x[k] for k in ("cmd", "outcome", "detail")} for x in executed], "verdicts": verdicts,
               "swaps": [{k: w[k] for k in ("from", "to", "seconds")} for w in swaps], "self": me, "why": why, "drive": dv, "steer": sv,
               "reason": "; ".join(x for x in ((f"{dv['mode']}: explore {dv['E']} vs check {dv['C']} at τ {dv['tau']}, P explore {dv['p_explore']}" if dv.get("mode") else ""),
                                              (f"steered toward its world at ε {eps}" + (f", truth {steering.TRUTH_EPS}" if truth else "") if concept else ""), (f"planner: {why}" if why else "")) if x), **({"planner_failed": failed} if failed else {})}
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

