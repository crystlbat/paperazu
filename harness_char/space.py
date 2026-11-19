"""The Dot space: chat with Dot while variables count things in the chat and steer its next reply.

A turn runs in order: every variable measures the user's text, the triggers that fire become instructions
for the reply, the model replies with the library as its data source, and a check puts any required phrase
the model left out at the front. New ways to measure go in KINDS, and new ways to steer go in TRIGGERS."""
import json
import re
import sqlite3
from collections.abc import Callable
from typing import Any

from shared import db, llm, settings, websearch
from pdf_research import jobs

# kind -> (value before, user text, pattern) -> new value
KINDS: dict[str, Callable[[float, str, str], float]] = {
    "count": lambda v, text, pat: v + len(re.findall(pat, text, re.I)),
    "words": lambda v, text, pat: float(len(text.split())),
    "watch": lambda v, text, pat: v,  # reads no text: it counts how often it acted on its target
    "persona": lambda v, text, pat: v,  # reads no text: it holds the persona Dot was told to take on
    "turns": lambda v, text, pat: v + 1,  # the conversation turn: x in "search transformers x"
}
PERSONA = re.compile(r"\b(?:set (?:your |the |dot'?s )?persona (?:as|to)|become|became|speak like|talk like|act like|pretend to be|be like|turn into|switch to)\s+"
                     r"(?:an? |the )?(.+?)[\s.!?]*$", re.I)
COUNTING = re.compile(r"\b(count|track|every|past|reach(?:es)?|hits?|whenever|times)\b", re.I)


def _every(v: dict[str, Any], before: float) -> bool:
    return bool(v["every"]) and int(v["value"] // v["every"]) > int(before // v["every"])


def _past(v: dict[str, Any], before: float) -> bool:
    return bool(v["past"]) and not v["passed"] and v["value"] > v["past"]


def _drops(v: dict[str, Any], before: float) -> bool:
    return bool(v["drops"]) and v["streak"] >= v["drops"]


def _catches(v: dict[str, Any], before: float) -> bool:
    """Rose to meet or pass the variable it is chasing (catches names it; measure puts its value in _chased)."""
    c = v.get("_chased")
    return bool(v["catches"]) and c is not None and before < c <= v["value"]


def _at(v: dict[str, Any], before: float) -> bool:
    """Reached its number from either side: "when sad reaches 0" fires on the way down too."""
    a = v.get("at")
    return a is not None and before != a and min(before, v["value"]) <= a <= max(before, v["value"])


# trigger -> (did it fire, what it changes on the variable once it has fired)
TRIGGERS: dict[str, tuple[Callable[[dict[str, Any], float], bool], dict[str, Any]]] = {
    "every": (_every, {}),
    "past": (_past, {"passed": 1}),
    "drops": (_drops, {"streak": 0}),
    "catches": (_catches, {}),  # its number is another variable's name
    "at": (_at, {}),
}
FIELDS = ("kind", "pattern", "every", "every_say", "past", "past_say", "drops", "drops_say", "catches", "catches_say", "target", "rises",
          "rises_say", "add_n", "act", "act_arg", "act_on", "resets", "step", "at", "at_say", "low_say", "high_say")


# the fixed list of things Dot can put on for a persona, in the order the model picks; the page draws each one
LOOKS = ("glasses", "monocle", "bowtie", "holo", "visor")
PERSONA_SCHEMA = {"type": "object", "required": ["persona", "look"], "properties": {
    "persona": {"type": "string"}, "look": {"type": "array", "items": {"enum": list(LOOKS)}, "maxItems": 3}}}


COLORS = ("red", "orange", "yellow", "gold", "green", "lime", "teal", "cyan", "blue", "navy", "purple", "violet", "magenta",
          "pink", "brown", "white", "black", "gray", "grey", "silver", "coral", "salmon", "crimson", "indigo", "turquoise", "mint")
COLOR = re.compile(rf"#[0-9a-f]{{6}}\b|#[0-9a-f]{{3}}\b|\b(?:{'|'.join(COLORS)})\b", re.I)
COLORISH = re.compile(r"\b(colou?rs?|turns?|paint|tint|change|switch(?:es)?|goes|becomes?)\b", re.I)


def recolor(arg: str, fired: dict[str, Any] | None = None) -> dict[str, Any]:
    """Each firing turns Dot the next colour in the list: the 1st firing the 1st colour, and round again after the last."""
    colors = [c.lower() for c in COLOR.findall(arg)]
    if not colors:
        raise RuntimeError(f"There is no colour I know in {arg!r}.")
    f = fired or {}
    i = int((f.get("value") or 1) // (f.get("n") or 1)) - 1 if f.get("trigger") == "every" else 0
    return {"tint": colors[i % len(colors)], "colors": colors}


X = re.compile(r"\{(?:x|turn|n)\}|\((?:x|turn)\)|\bx\b", re.I)


def web(query: str, fired: dict[str, Any] | None = None) -> dict[str, Any]:
    """Search the web; x in the query is the x variable, else the conversation turn. What comes back is fed to the counters (say feeds it)."""
    x = next((v["value"] for v in variables() if v["name"].lower() == "x"), None)  # the x on the board, when there is one
    turn = x if x is not None else _rows("SELECT COUNT(*) AS n FROM space_turns WHERE role = 'user'")[0]["n"]
    q = " ".join(X.sub(str(int(turn)), query).split())
    found = websearch.search(settings.get_all(), q)["results"][:5]
    if not found:
        raise RuntimeError(f"The web had nothing on {q}.")
    results = [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")[:300]} for r in found]
    return {"query": q, "results": results, "feed": "\n".join(f"{r['title']} {r['snippet']}" for r in results)}


SLOTS = ("Voice", "Calls you", "Catchphrase", "World")


def sheet_of(text: str) -> dict[str, str]:
    """The character sheet in a persona text: its `Label: value` lines; an old unlabelled persona is all Voice."""
    found = {}
    for line in text.splitlines():
        label, _, value = line.partition(":")
        slot = next((s for s in SLOTS if s.lower() == label.strip().lower()), None)
        if slot and value.strip():
            found[slot] = value.strip()
    return found or {"Voice": " ".join(text.split())}


def sheet_text(who: str, sheet: dict[str, str]) -> str:
    # each slot has its own cut, so a long Voice never pushes the later slots out of the 900
    return "\n".join([f"You are {who}.", *(f"{s}: {' '.join(sheet[s].split())[:500 if s == 'Voice' else 110]}" for s in SLOTS if sheet.get(s, "").strip())])[:900]


def become(who: str, fired: dict[str, Any] | None = None) -> dict[str, Any]:
    """Look `who` up on the web, boil it down to how they talk, and pick what Dot wears. Raises RuntimeError."""
    if who.strip().lower() in ("gidian", "gideon"):
        who = "Gideon from The Flash"
    s = settings.get_all()
    found = websearch.search(s, f"{who} personality how they talk")["results"][:6]
    notes = "\n".join(f"- {r['title']}: {r['snippet']}" for r in found)
    if not notes:
        raise RuntimeError(f"The web had nothing on {who}.")
    raw = jobs.complete(s, [{"role": "system", "content": (
        f"From these search results, describe how {who} talks, as instructions to someone playing {who}: tone, habits, "
        "typical phrases, in three short sentences starting with 'Speak as'. Then pick one to three things for a small "
        f"yellow character to wear as {who}, from: {', '.join(LOOKS)} (holo means it turns into a glowing AI hologram). "
        "A human wears glasses, monocle or bowtie, never holo or visor; only an AI or a robot is holo or visor. "
        'Reply with JSON only: {"persona": "...", "look": [...]}.')},
        {"role": "user", "content": notes}], max_tokens=300,
        response_format={"type": "json_schema", "json_schema": {"name": "persona", "schema": PERSONA_SCHEMA}})
    try:
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
        persona, look = str(data["persona"]).strip(), [x for x in data.get("look") or [] if x in LOOKS][:3]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        persona, look = raw.strip(), []  # a reply that is not JSON is still a description
    if not persona:
        raise RuntimeError(f"I could not make out how {who} talks.")
    learned = sheet_text(who, {"Voice": persona})
    out = {"learned": learned, "sheet": {k: sheet_of(learned).get(k, "") for k in SLOTS}, "look": list(dict.fromkeys(look)),
           "sources": [r["url"] for r in found if r.get("url")][:3]}
    try:  # the one tiny colour call; no answer, no tint
        word = jobs.complete(s, [{"role": "system", "content": f"Pick the one colour that fits {who} best. Answer with one word from: {', '.join(COLORS)}."},
                                 {"role": "user", "content": who}], max_tokens=8)
        if hue := next((w for w in re.findall(r"[a-z]+", word.lower()) if w in COLORS), None):
            out["tint"] = hue
    except Exception:
        pass
    return out


def make(name: str, fired: dict[str, Any] | None = None) -> dict[str, Any]:
    """"define a variable called action_taken": a counter of that name, made the first time and one more each time after."""
    name = re.sub(r"[^\w-]", "", name)[:24]
    if not name:
        raise RuntimeError("That variable has no name.")
    have = _rows("SELECT id FROM space_vars WHERE lower(name) = lower(?)", (name,))
    con = db.connect()
    with con:
        if have:
            con.execute("UPDATE space_vars SET value = value + 1 WHERE id = ?", (have[0]["id"],))
        else:
            v = clean_var({"name": name, "kind": "count", "pattern": rf"\b{re.escape(name)}\b"})
            con.execute(f"INSERT INTO space_vars (name, value, {', '.join(FIELDS)}) VALUES (?, 1{', ?' * len(FIELDS)})", (name, *(v[f] for f in FIELDS)))
    con.close()
    return {"made": name}


def paper(topic: str, fired: dict[str, Any] | None = None) -> dict[str, Any]:
    """"open a pdf on bias or suggest one": the paper in the library that is about it, else papers from the web."""
    like = f"%{topic}%"
    hit = _rows("""SELECT id, title, authors FROM papers WHERE title LIKE ? OR note LIKE ? OR tags LIKE ?
                   ORDER BY (title LIKE ?) DESC, COALESCE(last_opened, created_at) DESC LIMIT 1""", (like, like, like, like))
    if hit:
        return {"open": hit[0]}
    q = f"{topic} research papers"
    found = websearch.search(settings.get_all(), q)["results"][:5]
    if not found:
        raise RuntimeError(f"No paper on {topic} here or on the web.")
    return {"query": q, "results": [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")[:300]} for r in found]}


def _hatch(name: str, out: str, steps: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    """The creature of that name (case-insensitive), made when you have none: (job, new)."""
    have = _rows("SELECT * FROM jobs WHERE lower(name) = lower(?)", (name,))
    if have:
        return jobs._job(have[0]), False
    color = _rows("SELECT COUNT(*) AS n FROM jobs")[0]["n"] % 8
    return jobs.create_job(jobs.JobIn(name=name, color=color, output=out, steps=steps)), True


def spawn(arg: str, fired: dict[str, Any] | None = None) -> dict[str, Any]:
    """"watson: lists the clues in the paper" (or just "watson"): a creature that does that on a paper."""
    who, _, task = arg.partition(":")
    name = re.sub(r"[^\w\- ]", "", who).strip().capitalize()[:40]
    if not name:
        raise RuntimeError("That creature has no name.")
    job, new = _hatch(name, "doc", [{"scope": "paper", "prompt": (task.strip() or "Summarise the key findings of this paper in five short bullet points.")[:4000]}])
    return {"creature": job, "new": new}


def sleep(arg: str, fired: dict[str, Any] | None = None) -> dict[str, Any]:
    """The page goes to sleep; "eva" is the keeper, a creature that reflects, and "dot" means nobody was named."""
    if arg.strip().lower() == "dot":
        return {"sleep": True, "keeper": ""}
    job = spawn(f"{arg}: Write a short reflection on what this paper teaches about its world and setting.")["creature"]
    return {"sleep": True, "keeper": job["name"], "keeper_job": job}


# action -> (the argument, e.g. who to become) -> {"learned": what Dot now carries, ...}
# A rule may run several: act "make+paper" with act_arg "action_taken | bias".
ACTIONS: dict[str, Callable[..., dict[str, Any]]] = {"become": become, "recolor": recolor, "search": web, "make": make, "paper": paper, "spawn": spawn, "sleep": sleep}

DOT = ("You are Dot, a small yellow research buddy inside a paper-reading app. Reply in one to three short "
       "sentences of plain text, no markdown. Answer or react in your own words; never repeat the user's message back. "
       "You can see the user's library below. The app around you keeps variables: counters the user sets up in this chat "
       "that go up by themselves when their word is said, and can change your colour or search the web. They are real; "
       "when asked about one, say its value as given below and never claim you cannot count, track or change it.\n")
MAKE = (
    "The user may want Dot to keep an eye on something in the chat. Turn it into variables. Reply with JSON only: "
    '{"reply": "one short sentence in your own words saying what is now on (never repeat the request)", "vars": [variable, ...]}. '
    "A variable has name (one or two words), kind (\"count\": adds up matches of pattern in each message, or "
    "\"words\": the number of words in each message, or \"turns\": the conversation turn, one more each message), pattern (a Python regex for count, \"\" for words), and any of: "
    "every (n) with every_say (what Dot says each time the count passes a multiple of n), past (n) with past_say "
    "(what Dot says once when the value first goes past n), drops (k) with drops_say (what Dot says after the value "
    "falls k messages in a row), catches (the name of another variable) with catches_say (when this value rises to meet that one). Any variable may also do something when one of its triggers fires: act (\"become\": look a person or character up on the web and start talking like them, act_arg is who; or \"recolor\": Dot turns a colour each time, act_arg is the list of colours in order, e.g. \"red, green, blue\"; or \"search\": search the web, act_arg is the query, x in it stands for the turn number, and the counters also count what comes back), and act_on (the trigger: every, past or drops; that trigger then needs no say). A third kind, \"watch\", reads no text and acts on another variable: target (that variable's name), rises (n: it fires when the target went up by at least n this message), add (a number added to the target each time it fires, negative to hold it back), and optionally rises_say. Leave out triggers nobody asked for. If the user is not asking you to count or watch something in the chat (a question about a paper, say), reply with \"vars\": []. Copy each say word for word from the user, the whole phrase. "
    'Example: count apples, every 3rd say hi, past 10 say done -> {"name": "apples", "kind": "count", '
    '"pattern": "\\\\bapples?\\\\b", "every": 3, "every_say": "hi", "past": 10, "past_say": "done"}. '
    "A variable named after a word, with nothing else said, counts that word. "
    'Example: make rain, and a brake that adds -1 to rain when rain goes up -> "vars": [{"name": "rain", "kind": "count", '
    '"pattern": "\\\\brain\\\\b"}, {"name": "brake", "kind": "watch", "target": "rain", "rises": 1, "add": -1}].'
)
ASKS_FOR_VARS = re.compile(r"\b(count|track|watch|keep (?:an eye|count)|every\w{0,4} ?time|each time|whenever|create|make|new|variable|counter|rule)\b|\bwhen(?:ever)? i (?:say|type|write|mention|use)\b.+?\b\d+\s+times\b"
                           r"|\bwhen\s+\S+\s+(?:reach(?:es)?|hits?|gets to|is(?: at)?|becomes?|equals|passes)\s+\d", re.I)
REMOVE = re.compile(r"\b(delete|remove|drop|clear|reset|get rid of|forget)\b", re.I)
ALL = re.compile(r"\b(all|every(?:thing| variable| counter| rule)|runtime|them)\b", re.I)


def _rows(sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in jobs._all(sql, args)]


def variables() -> list[dict[str, Any]]:
    vs = _rows("SELECT * FROM space_vars ORDER BY id")
    for v in vs:
        v["look"] = json.loads(v.get("look") or "[]")
        v["about"] = define(v)
    return vs


DOING = {"recolor": "turn Dot {}", "search": "search the web for “{}”", "become": "learn {} from the web and talk like them", "make": "make the variable {}",
         "paper": "open or suggest a {} paper", "spawn": "hatch the creature {}", "sleep": "let {} put Dot to sleep, and reflect"}


def define(v: dict[str, Any]) -> str:
    """What a variable counts and what it does, in one plain sentence made from its stored fields: what the engine will really do."""
    if v["kind"] == "persona":
        return f"Dot talks like {v.get('act_arg') or v['name']}."
    bare = re.sub(r"\\b|\\(?=\s)|s\?", "", v.get("pattern") or "").replace("\\?", "?")
    what = {"count": f"Counts “{bare}” in your messages" if bare else "A counter you set", "turns": "Counts the turns of the chat",
            "words": "Counts the words of each message", "watch": f"Watches {v.get('target')}"}.get(v["kind"], f"A {v['kind']}")
    acts = list(zip((v.get("act") or "").split("+"), (v.get("act_arg") or "").split(" | "))) if v.get("act") else []
    does = ", ".join("go to sleep and learn" if a == "sleep" and arg.strip().lower() == "dot" else DOING.get(a, a + " {}").format(arg.split(":")[0].strip()) for a, arg in acts)
    parts = []
    if v.get("step") and v["kind"] == "count":
        what += f", each one {'adding' if v['step'] > 0 else 'taking'} {abs(v['step']):g}"
    for t in ("every", "past", "drops", "catches", "at"):
        n = v.get(t)
        if (n is None) if t == "at" else (not n or (t == "past" and n < 0)):
            continue
        todo = [x for x in (f"say “{v[f'{t}_say']}”" if v.get(f"{t}_say") else "", does if v.get("act_on") == t else "") if x]
        if t == "at" and not todo:  # a mark that only holds moods: they are said below
            continue
        n = f"{n:g}" if isinstance(n, (int, float)) else n  # "catches" holds another variable's name
        when = {"every": f"at {n}" if v.get("past") == -1 else f"every {n}", "past": f"once past {n}", "drops": f"when it drops {n}", "catches": f"when it meets {n}", "at": f"when it reaches {n}"}[t]
        parts.append(f"{when}: {', and '.join(todo) or 'nothing yet'}")
    if v.get("at") is not None and (v.get("low_say") or v.get("high_say")):  # a lasting mood: it steers every reply, not one
        a = f"{v['at']:g}"
        does = lambda say: f"system {say} (learning)" if GATE.match(say) else f"every reply starts “{say}”"
        parts.append(" and ".join(x for x in (f"while it is {a} or less, {does(v['low_say'])}" if v.get("low_say") else "",
                                              f"while it is above {a}, {does(v['high_say'])}" if v.get("high_say") else "") if x))
    if v["kind"] == "watch" and v.get("add_n"):
        parts.append(f"when {v.get('target')} rises: {'+' if v['add_n'] > 0 else '−'}{abs(v['add_n']):g}")
    if v.get("resets") and parts:
        parts[-1] += ", then back to 0"
    return f"{what}. " + ("; ".join(p[0].upper() + p[1:] for p in parts) + "." if parts else "It does nothing yet: tell me what to do when it reaches a number.")


def _learned(source: str = "reflection", n: int = 3) -> list[str]:
    """What Dot noted while asleep (or the lessons it practised); char_memories may not exist yet."""
    try:
        return [r["content"] for r in _rows("SELECT content FROM char_memories WHERE source = ? ORDER BY id DESC LIMIT ?", (source, n))]
    except sqlite3.OperationalError:
        return []


def tables() -> dict[str, int]:
    """Row counts of the tables Dot reads and writes, drawn as stacks of dots."""
    names = {"papers": "papers", "highlights": "highlights", "chat_turns": "space_turns",
             "variables": "space_vars", "cards": "canvas_cards"}
    return {k: jobs._one(f"SELECT count(*) FROM {t}")[0] for k, t in names.items()}


def state() -> dict[str, Any]:
    turns = _rows("SELECT * FROM (SELECT * FROM space_turns ORDER BY id DESC LIMIT 40) ORDER BY id")
    for t in turns:
        t["events"] = json.loads(t["events"])
    papers = _rows("SELECT id, title, authors FROM papers ORDER BY COALESCE(last_opened, created_at) DESC LIMIT 8")  # float round the rings
    return {"turns": turns, "vars": variables(), "tables": tables(), "papers": papers}


def clean_var(raw: Any) -> dict[str, Any] | None:
    """A variable the model proposed, checked; None when it cannot work."""
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    v: dict[str, Any] = {"name": str(raw.get("name") or raw["kind"]).strip()[:24] or raw["kind"], "kind": raw["kind"],
                         "pattern": str(raw.get("pattern") or "")[:200]}
    if v["kind"] == "count":
        try:
            re.compile(v["pattern"])
        except re.error:  # "?" for questions: match it as plain text
            v["pattern"] = re.escape(v["pattern"])
        if not v["pattern"]:
            return None
    act, on = str(raw.get("act") or ""), str(raw.get("act_on") or "")
    v["act"], v["act_arg"], v["act_on"] = (act, str(raw.get("act_arg") or "").strip()[:200], on) if act in ACTIONS and on in TRIGGERS else ("", "", "")
    if v["act"] and not v["act_arg"]:
        v["act"] = v["act_on"] = ""
    for t in TRIGGERS:
        n, say = raw.get(t), str(raw.get(f"{t}_say") or "").strip()[:200]
        if t == "catches":  # the name of the variable it chases
            name = str(n or "").strip()[:24]
            v[t], v[f"{t}_say"] = (name, say) if name and (say or v["act_on"] == t) else (None, "")
            continue
        ok = _num(n) and 1 <= n <= 10000 and (say or v["act_on"] == t)
        v[t], v[f"{t}_say"] = (int(n), say) if ok else (None, "")
    v["target"], v["rises"], v["rises_say"], v["add_n"], v["resets"] = "", None, "", 0.0, 0
    v["step"], v["low_say"], v["high_say"] = 0.0, "", ""
    if v["kind"] == "watch":
        add, rises = raw.get("add", raw.get("add_n")), raw.get("rises", 1)
        v["target"] = str(raw.get("target") or "").strip()[:24]
        v["rises_say"] = str(raw.get("rises_say") or "").strip()[:200]
        v["add_n"] = float(add) if _num(add) and -1000 <= add <= 1000 else 0.0
        v["rises"] = int(rises) if _num(rises) and 1 <= rises <= 10000 else 1
        if not v["target"] or not (v["add_n"] or v["rises_say"]):
            return None  # a watcher with nothing to watch or nothing to do
    if v["act_on"] and not v[v["act_on"]]:
        v["act"] = v["act_on"] = v["act_arg"] = ""  # the trigger it hangs on was not given a number
    return v


def _num(n: Any) -> bool:
    return isinstance(n, (int, float)) and not isinstance(n, bool)


MARKS = {"question": r"\?", "exclamation": "!"}
LENGTH = re.compile(r"\b(words?|long|length|short|typ\w*)\b", re.I)


def fold(made: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Fix what small models get wrong when they make variables from `text`:
    a plain word only counts its exact form, a say gets cut short, and one rule gets split into two."""
    for v in made:
        bare = re.sub(r"\\b|s\?|[()^$]", "", v["pattern"])  # \bapples?\b -> apple
        if v["kind"] == "count" and re.fullmatch(r"\w+", bare):
            word = bare.lower()
            stem = word[:-1] if word.endswith("s") and not word.endswith("ss") else word
            # shortcut: a few words mean a mark, not the word itself; grow MARKS when another comes up
            v["pattern"] = MARKS.get(stem, rf"\b{stem}s?\b")
        for t in TRIGGERS:
            if v[f"{t}_say"]:
                v[f"{t}_say"] = whole(v[f"{t}_say"], text)
    made = [_acting(v, text) for v in _turns(_watched(made, text), text)]
    counted = {v["name"].lower() for v in made if v["kind"] == "count"}
    # "whenever you see me type it add 1 to it" is the counter itself, not a watcher that counts it a second time
    made = [v for v in made if not (v["kind"] == "watch" and v["target"].lower() in counted and v["add_n"] == 1 and not v["rises_say"])]
    if RESET_RULE.search(text):
        for v in made:
            v["resets"] = int(any(v[t] for t in TRIGGERS))
    counts = [v for v in made if v["kind"] == "count"]
    if counts and not LENGTH.search(text):  # nobody asked about length, so a words variable is a split-off trigger
        for v in [v for v in made if v["kind"] == "words"]:
            for t in TRIGGERS:
                if v[t] and not counts[0][t]:
                    counts[0][t], counts[0][f"{t}_say"] = v[t], v[f"{t}_say"]
        made = counts + [v for v in made if v["kind"] != "words" and v not in counts]
    return made


LOOKUP = re.compile(r"\b(look(?:s|ing)? (?:\w+ )?up|search|learn|become|talk(?:s|ing)? like|act(?:s|ing)? like|personality)\b", re.I)
SEARCHY = re.compile(r"\bsearch(?:es|ing)?\s+(?:the web |online |the internet )?(?:for|about|on)\s+(.+?)(?=\s*[;.!?]|,?\s+(?:and|when|where|then|every|each|if)\b|$)", re.I)
BECOMING = re.compile(r"\b(?:talk|speak|act)(?:s|ing)? like|\bbecome\b|\bpersonality\b", re.I)
TURNISH = re.compile(r"\b(?:x\s*(?:=|is|as)\s*(?:the\s+)?(?:conversation|convo|chat)?\s*turns?|turn number|conversation turns?|convo turns?)\b", re.I)
CATCH = re.compile(r"\b(?:catches(?: up with)?|reaches|equals|matches|meets|hits)\s+(?:the\s+)?(?:value of\s+)?([a-z_]\w*)", re.I)
SAYS = re.compile(r"(?<![Ii] )\b[Ss][Aa][Yy]\b")  # "when i say bias" names the word to count; it is not something to say
HELD = "\x00"  # a say held for _acting to turn into an action
PAPERISH = re.compile(r"\b(?:open|suggest|find|show|pull up)\s+(?:me\s+)?(?:a\s+|the\s+|some\s+)?(?:pdfs?|papers?)(?:\s+(?:on|about)\s+([\w-]+))?", re.I)
MAKEVAR = re.compile(r"\b(?:define|make|create|add|start)\s+(?:a\s+|another\s+)?(?:new\s+)?(?:variable|counter)\s+(?:called\s+|named\s+)?[\"'“]?([\w-]+)", re.I)
RESET_RULE = re.compile(r"\breset\b[^.?!]*?\b(?:to\s+(?:0|zero)|back)\b|\bback to (?:0|zero)\b|\bstart (?:it |\w+ )?over\b", re.I)
TRIGGER_WORDS = re.compile(r"\b(?:when(?:ever)?|every|past|reach(?:es)?|hits?|gets to|after)\b", re.I)


SPAWN = re.compile(r"\b(?:spawn|hatch|summon|create|make|add|build)\s+(?:(?:a|an|another|new)\s+)*creature\s*(?:(?:called|named)\s+)?(?!(?:that|to|which|who|whose|and|its)\b)([\w-]+)", re.I)
SLEEPER = re.compile(r"(?:^|[,;]\s*|\band\s+)(?!(?:and|then|it|you|that|this|me|i|a|the|dot)\b)([\w-]+)\s+(?:which|who|that)\s+(?:(?:will|can)\s+)?(?:let|put|send|make)s?\s+(?:the\s+)?(?:ui|dot|app|you|it|screen|page)\s+(?:(?:go\s+)?to\s+)?sleep\b", re.I)
NOBODY = re.compile(r"\bgo(?:es)?\s+to\s+sleep\b|\bputs?\b[^.;]*?\bto\s+sleep\b|\bfalls?\s+asleep\b", re.I)
JOBIS = re.compile(r"[\s,;]*(?:and\s+)?(?:(?:its|whose)\s+job\s+is(?:\s+to)?|that|to|which|who)\s+(.+)", re.I)


def _spawns(tail: str) -> list[tuple[str, str]]:
    """"spawn a creature called watson that lists clues, and eva which will let the UI sleep": its spawn and sleep actions."""
    tail = re.split(r"\b(?:says?|tell me|reply|respond)\b", tail, maxsplit=1, flags=re.I)[0]  # a sleep inside the words to say is only words
    sp, sl = SPAWN.search(tail), SLEEPER.search(tail)
    nb = NOBODY.search(tail, sp.end() if sp else 0)
    acts = []
    if sp:
        rest = tail[sp.end():min([m.start() for m in (sl, nb) if m and m.start() >= sp.end()], default=None)]
        job = JOBIS.match(re.split(r"[.;]", rest)[0])
        task = re.sub(r"(?:[\s,;]+and)?[\s,;]*$", "", job.group(1)).replace("|", " ").strip()[:120] if job else ""
        acts.append(("spawn", sp.group(1).lower() + (f": {task}" if task else "")))
    if sl or nb:
        acts.append(("sleep", sl.group(1).lower() if sl else "dot"))
    return acts


def _unheld(made: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A held say nothing claimed: that trigger had nothing to say or do after all."""
    for v in made:
        for t in TRIGGERS:
            if v[f"{t}_say"] == HELD:
                v[t], v[f"{t}_say"] = None, ""
                if v["act_on"] == t:
                    v["act"] = v["act_arg"] = v["act_on"] = ""
    return [v for v in made if v["kind"] != "count" or v["pattern"]]


def _turns(made: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """"x = the conversation turn": a variable named x or turn counts turns, whatever kind the model gave it.
    And "when transformers reaches x": a count that chases another variable."""
    names = {v["name"].lower() for v in made} | {v["name"].lower() for v in variables()}
    turnish = re.compile(r"x|turns?|conversation turns?|convo turns?")
    if TURNISH.search(text) and made and not any(turnish.fullmatch(n) for n in names):  # the model left x out: make it
        x = clean_var({"name": "x", "kind": "turns", "every": 1, "every_say": HELD})
        for v in made:
            if v["every"] == 1 and re.search(r"\b(?:each|every)\s+turn\b", text, re.I):  # "every turn ..." belongs to x
                v["every"], v["every_say"], v["act"], v["act_arg"], v["act_on"] = None, "", "", "", ""
        made, names = [x, *made], names | {"x"}
    for v in made:
        if TURNISH.search(text) and re.fullmatch(r"x|turns?|conversation turns?|convo turns?", v["name"].lower()):
            v["kind"], v["pattern"] = "turns", ""
            if re.search(r"\b(?:each|every)\s+(?:turn|message|time)\b", text, re.I) and not v["every"] and not v["catches"]:
                v["every"], v["every_say"] = 1, v["every_say"] or HELD
        c = CATCH.search(text)
        if v["kind"] == "count" and not v["catches"] and c and c.group(1).lower() in names - {v["name"].lower()}:
            v["catches"], v["catches_say"] = c.group(1).lower(), HELD
    return made


def _acting(v: dict[str, Any], text: str) -> dict[str, Any]:
    """Small models write "look up JARVIS and talk like him" as a say. Turn it into the become action, on the
    trigger the user named ("past 10" rather than the model's "every 10")."""
    if v["act"]:
        return v
    qs = list(SEARCHY.finditer(text))
    if qs and not BECOMING.search(text):  # "search the web for transformers x": a search, not a persona
        for t in TRIGGERS:
            if v[t] and (v[f"{t}_say"] == HELD or not re.search(r"\bsay\b", text, re.I)):
                c = CATCH.search(text) if t == "catches" else None  # "when it reaches x, search for ...": the search after it
                q = next((m for m in qs if c and m.start() > c.start()), qs[0])
                v[f"{t}_say"] = ""
                v["act"], v["act_arg"], v["act_on"] = "search", q.group(1).strip(" \"'")[:60], t
                return v
    colors = [c for c in COLOR.findall(text) if c.lower() not in v["name"].lower() and not re.search(re.escape(c), v["pattern"], re.I)]
    if colors and COLORISH.search(text):  # "every 3 turn Dot red, green, blue": colours, not words to say
        for t in TRIGGERS:
            if v[t]:
                if not re.search(r"\bsay\b", text, re.I):
                    v[f"{t}_say"] = ""
                if t == "past" and not v["every"]:  # a list of colours goes round, so it fires at every multiple
                    v["every"], v["past"], v["every_say"], v["past_say"], t = v["past"], None, v["past_say"], "", "every"
                v["act"], v["act_arg"], v["act_on"] = "recolor", ", ".join(c.lower() for c in colors)[:60], t
                return v
    after = WHEN.search(text) or TRIGGER_WORDS.search(text)  # "when bias becomes 5 define … and open a pdf": what follows the trigger
    tail = text[after.end():] if after else ""
    mk = [m.group(1).lower() for m in MAKEVAR.finditer(tail) if m.group(1).lower() != v["name"].lower()]
    pp = PAPERISH.search(tail)
    sps = _spawns(tail)
    if mk or pp or sps:
        for t in TRIGGERS:
            if v[t]:
                acts = sps + ([("make", mk[0])] if mk else []) + ([("paper", (pp.group(1) or v["name"]).lower())] if pp else [])
                if v[f"{t}_say"] == HELD or not SAYS.search(text):
                    v[f"{t}_say"] = ""
                v["act"], v["act_arg"], v["act_on"] = "+".join(a for a, _ in acts), " | ".join(x for _, x in acts)[:200], t
                return v
    if not LOOKUP.search(text):
        return v
    up = re.search(r"\blook(?:s|ing)?\s+(?:\w+\s+)?up\s+(.+?)(?=\s+(?:when|whenever|every|each|if|and|after)\b|\s*[;,.!?]|$)", text, re.I)
    if up and not BECOMING.search(text):
        for t in TRIGGERS:
            if v[t] and (LOOKUP.search(v[f"{t}_say"]) or not re.search(r"\bsay\b", text, re.I)):
                v[f"{t}_say"] = ""
                v["act"], v["act_arg"], v["act_on"] = "search", up.group(1).strip(" \"'")[:60], t
                return v
    for t in TRIGGERS:
        if v[t] and (LOOKUP.search(v[f"{t}_say"]) or not re.search(r"\bsay\b", text, re.I)):  # no "say": the model made it up
            who = re.search(r"\b(?:up|like|become|search(?: for)?)\s+([A-Z][\w.-]*(?:\s+(?:[A-Z][\w.-]*|\d+\b))*)", text) \
                or re.search(r"\b(?:become|(?:talk|speak|act)s? like)\s+(?:an?\s+|the\s+)?([\w.-]+(?:\s+[\w.-]+){0,3}?)(?=\s+(?:when|whenever|every|each|if|and|after)\b|\s*[;,.!?]|$)", text, re.I)  # "become navi": a name typed in lower case  # "Cayde 6": a number may end a name or re.search(r"\b([A-Z]{2,}\w*)\b", text)
            if not who:
                return v
            on = t
            if t == "every" and re.search(rf"\bpast {v[t]}\b", text) and not v["past"]:  # the user said past
                v["past"], v["every"], on = v[t], None, "past"
            if t == "past" and re.search(rf"\b(?:reach(?:es)?|hits?|at) {v[t]}\b", text) and not v["every"]:  # at 10, not after it
                v["every"], v["past"], on = v[t], None, "every"
            v[f"{t}_say"] = ""
            v["act"], v["act_arg"], v["act_on"] = "become", who.group(1)[:60], on
            return v
    return v


def _watched(made: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """A watcher needs something to watch. Small models fold "space, and a brake on space" into one watcher named
    space that watches itself: split it back into a space counter and a watcher named as the user named it."""
    have = {v["name"].lower() for v in variables()} | {v["name"].lower() for v in made if v["kind"] != "watch"}
    out = list(made)
    for w in [v for v in made if v["kind"] == "watch"]:
        t = w["target"].lower()
        if w["name"].lower() == t:
            others = [x for x in re.findall(r"\b[a-z]{3,}\b", text.lower()) if x not in STOP and x != t and x not in have]
            w["name"] = others[0] if others else f"{t} watch"
        if t not in have and re.fullmatch(r"\w+", t):
            out.insert(0, {"name": t, "kind": "count", "pattern": rf"\b{t}s?\b", **{k: None for k in TRIGGERS},
                           **{f"{k}_say": "" for k in TRIGGERS}, "target": "", "rises": None, "rises_say": "", "add_n": 0.0,
                           "act": "", "act_arg": "", "act_on": ""})
            have.add(t)
    return out


STOP = set("create make new called named and which that adds add adding every each time when whenever if then the "
           "variable variables counter counters rule rules watch watches count counts increases increase goes rises "
           "with for from into one also please can you".split())


def whole(say: str, text: str) -> str:
    """The full phrase the user asked for, when the model kept only its start."""
    found = re.search(re.escape(say) + r"[^;.\n]*?(?=\s*(?:[;.\n]|\b(?:past|every|after|and then)\b|$))", text, re.I)
    return re.sub(r"\s+(?:and|then|,)$", "", found.group(0).strip(" ,"), flags=re.I) if found else say


def add_var(v: dict[str, Any]) -> dict[str, Any]:
    """A new variable; one with the name and kind of one you have changes that one's rule and keeps its value."""
    v = {"resets": 0, "at": None, "at_say": "", "step": 0.0, "low_say": "", "high_say": "", **v}  # made outside clean_var (a persona, a split-off watcher): no reset
    same = _rows("SELECT id FROM space_vars WHERE lower(name) = lower(?) AND kind = ?", (v["name"], v["kind"]))
    con = db.connect()
    if same:
        with con:
            con.execute(f"UPDATE space_vars SET {', '.join(f'{f} = ?' for f in FIELDS)} WHERE id = ?", (*(v[f] for f in FIELDS), same[0]["id"]))
        con.close()
        return _rows("SELECT * FROM space_vars WHERE id = ?", (same[0]["id"],))[0]
    with con:
        cur = con.execute(f"INSERT INTO space_vars (name, {', '.join(FIELDS)}) VALUES (?{', ?' * len(FIELDS)})",
                          (v["name"], *(v[f] for f in FIELDS)))
    con.close()
    return _rows("SELECT * FROM space_vars WHERE id = ?", (cur.lastrowid,))[0]


def remove_var(var_id: int) -> bool:
    con = db.connect()
    with con:
        n = con.execute("DELETE FROM space_vars WHERE id = ?", (var_id,)).rowcount
    con.close()
    return bool(n)


def clear() -> None:
    con = db.connect()
    with con:
        con.execute("DELETE FROM space_turns")
        con.execute("DELETE FROM space_vars")
    con.close()


def measure(text: str, feed: bool = False) -> list[dict[str, Any]]:
    """Update every variable from one user message and save it. Returns what fired.

    In order: each variable measures the text; then each watcher acts on its target, judged by how the target
    moved on the text alone, so watchers cannot set each other off in a loop; then the triggers see the final values.
    feed: text that came back from an action (web results), not a turn: only counters read it, and no turn passes."""
    fired: list[dict[str, Any]] = []
    vs = variables()
    before = {v["id"]: v["value"] for v in vs}
    for v in vs:
        if not feed or v["kind"] == "count":
            v["value"] = KINDS[v["kind"]](v["value"], text, v["pattern"])
            if v["kind"] == "count" and v.get("step"):  # "each happy takes 1 off sad": a step other than +1
                v["value"] = before[v["id"]] + v["step"] * (v["value"] - before[v["id"]])
    rose = {v["id"]: v["value"] - before[v["id"]] for v in vs}
    named = {v["name"].lower(): v for v in vs}
    for w in vs:
        t = named.get(w["target"].lower()) if w["kind"] == "watch" else None
        if t is None or t is w or rose[t["id"]] < (w["rises"] or 1):
            continue
        t["value"] += w["add_n"]
        w["value"] += 1
        fired.append({"var": w["id"], "name": w["name"], "trigger": "rises", "n": w["rises"], "say": w["rises_say"],
                      "target": t["id"], "target_name": t["name"], "add": w["add_n"], "value": t["value"]})
    con = db.connect()
    with con:
        for v in vs:
            b = before[v["id"]]
            if not feed:
                v["delta"] = v["value"] - b if v["turns"] or v["kind"] != "words" else 0
                v["streak"] = v["streak"] + 1 if v["delta"] < 0 else 0
                v["turns"] += 1
            v["_chased"] = named[v["catches"].lower()]["value"] if v["catches"] and v["catches"].lower() in named else None
            for t, (fires, after) in TRIGGERS.items():
                if fires(v, b):
                    fired.append({"var": v["id"], "name": v["name"], "trigger": t, "n": v[t], "say": v[f"{t}_say"], "value": v["value"],
                                  **({"act": v["act"], "act_arg": v["act_arg"]} if v["act"] and v["act_on"] == t else {})})
                    v.update(after)
            if v["resets"] and any(f["var"] == v["id"] and f["trigger"] in TRIGGERS for f in fired):
                v["value"], v["passed"] = 0.0, 0  # the rule fired: start over
                for f in fired:
                    if f["var"] == v["id"]:
                        f["reset"] = True
            con.execute("UPDATE space_vars SET value = ?, delta = ?, streak = ?, passed = ?, turns = ? WHERE id = ?",
                        (v["value"], v["delta"], v["streak"], v["passed"], v["turns"], v["id"]))
    con.close()
    return fired


def forget(text: str) -> list[dict[str, Any]] | None:
    """Variables removed by asking in the chat, or None when the message is not asking to remove any."""
    if not REMOVE.search(text) or RESET_RULE.search(text):
        return None
    vs = variables()
    low = text.lower()
    gone = vs if ALL.search(text) else [v for v in vs if re.search(rf"\b{re.escape(v['name'].lower())}\b", low)]
    if not gone and not re.search(r"\b(variables?|counters?|rules?)\b", low):
        return None  # "remove the bias from the model" is a question, not a request
    for v in gone:
        remove_var(v["id"])
    return gone


def library() -> str:
    papers = jobs._all("SELECT title FROM papers ORDER BY created_at DESC LIMIT 30")
    n = tables()
    titles = "\n".join(f"- {p['title'] or 'Untitled'}" for p in papers) or "- none yet"
    return (f"Library: {n['papers']} papers, {n['highlights']} highlights, {n['cards']} canvas cards.\n"
            f"Recent papers:\n{titles}\n")


_S, _N = {"type": "string"}, {"type": "integer"}
SCHEMA = {"type": "object", "required": ["reply", "vars"], "properties": {"reply": _S, "vars": {"type": "array", "items": {
    "type": "object", "required": ["name", "kind"], "properties": {
        "name": _S, "kind": {"enum": list(KINDS)}, "pattern": _S, "every": _N, "every_say": _S, "past": _N, "past_say": _S,
        "drops": _N, "drops_say": _S, "catches": _S, "catches_say": _S, "target": _S, "rises": _N, "add": {"type": "number"}, "rises_say": _S,
        "act": {"enum": ["", *ACTIONS]}, "act_arg": _S, "act_on": {"enum": ["", *TRIGGERS]}}}}}}


def read_rule(got: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """The rules as they will be saved. "when i say X 3 times, do Y" is read as "every 3 do Y", so the "say" in it is not taken for a say."""
    return _unheld(fold(got, TIMES.sub(lambda m: f"every {m.group(2)}", text)))


# a rule can hold one of the character's three learning systems on or off: "when focus = 0, turn S2 off", "while energy is above 3 switch system 0 on"
SYSWORD = re.compile(r"\b(?:system\s*|s)([012])\b", re.I)
GATE = re.compile(r"S([012]) (on|off)$")  # how a held switch is kept, in the variable's lasting slot
STEP = re.compile(r"\b(?:each|every|(?:every|each) ?time i say|whenever i say)\s+[\"'“]?([\w-]+)[\"'”]?,?\s+(?:takes?|knocks?|removes?|adds?|puts?)\s+(\d+)\s+(off|from|to|on)\s+([\w-]+)", re.I)
GOES = re.compile(r"\b(?:every|each) ?time i say\s+[\"'“]?([\w-]+)[\"'”]?,?\s+([\w-]+)\s+goes\s+(down|up)(?:\s+by)?\s+(\d+)", re.I)
START = re.compile(r"\bset\s+(?:the\s+)?(?:variable\s+)?([\w-]+)\s+(?:to|=)\s*(-?\d+)|\b([\w-]+)\s+(?:starts?|begins?)\s+(?:at|from)\s+(-?\d+)", re.I)
END = r"(.*?)(?=\s*(?:;|,?\s*\band\s+when\b|,?\s*\bwhen\b|$))"
ABOVE = re.compile(r"\bwh(?:en(?:ever)?|ile)\s+([\w-]+)\s+is\s+(?:above|over|more than|greater than|>)\s*(-?\d+)\b,?\s*" + END, re.I)
AT = re.compile(r"\bwh(?:en(?:ever)?|ile)\s+([\w-]+)\s+(=+|is|equals|reaches|hits|gets to|becomes)\s*(-?\d+)\b,?\s*" + END, re.I)
SAYN = re.compile(r"\bsay\s+[\"'“]?([\w-]+)[\"'”]?\s+(\d+)\s+times\b", re.I)


def steady(text: str) -> list[tuple[dict[str, Any], float | None]]:
    """Rules that hold a value rather than only count up: a start ("set sad to 3"), a step ("each happy takes 1 off sad"),
    a mark from either side ("when sad = 0, turn blue") and a lasting mood ("while sad is above 0 say oh").
    Each comes back merged onto the variable of that name, so a rule can be built one sentence at a time. [] when none of this is asked."""
    out: dict[str, dict[str, Any]] = {}
    start: dict[str, float] = {}

    def var(name: str) -> dict[str, Any]:
        key = name.lower()
        if key not in out:
            row = _rows("SELECT * FROM space_vars WHERE lower(name) = ? AND kind = 'count' ORDER BY id DESC LIMIT 1", (key,))
            out[key] = dict(row[0]) if row else {"name": key[:24], "kind": "count", "pattern": rf"\b{re.escape(key)}\b", **{k: None for k in TRIGGERS},
                                                  **{f"{k}_say": "" for k in TRIGGERS}, "target": "", "rises": None, "rises_say": "", "add_n": 0.0,
                                                  "act": "", "act_arg": "", "act_on": "", "resets": 0, "step": 0.0, "low_say": "", "high_say": ""}
        return out[key]

    def clause(v: dict[str, Any], words: str, lasting: str) -> None:
        said = re.match(r"(?i)(?:then\s+)?say\s+[\"'“]?(.+?)[\"'”]?\s*$", words.strip(" ,."))
        if (sy := SYSWORD.search(words)) and (to := re.search(r"(?i)\b(on|off)\b", words)):
            v[lasting] = f"S{sy.group(1)} {to.group(1).lower()}"  # shortcut: it takes the lasting-mood slot, so one side of a mark holds a mood or a switch, not both; give switches their own column if you need both
        elif said:
            v[lasting] = said.group(1)[:200]
        elif (c := COLOR.search(words)) and COLORISH.search(words):
            v["act"], v["act_arg"], v["act_on"] = "recolor", c.group(0), "at"
    for m in STEP.finditer(text):
        v = var(m.group(4)); v["pattern"], v["step"] = rf"\b{re.escape(m.group(1).lower())}\b", float(m.group(2)) * (-1 if m.group(3).lower() in ("off", "from") else 1)
    for m in GOES.finditer(text):
        v = var(m.group(2)); v["pattern"], v["step"] = rf"\b{re.escape(m.group(1).lower())}\b", float(m.group(4)) * (-1 if m.group(3).lower() == "down" else 1)
    for m in START.finditer(text):
        start[(m.group(1) or m.group(3)).lower()] = float(m.group(2) or m.group(4))
    for m in ABOVE.finditer(text):
        v = var(m.group(1)); v["at"] = v["at"] if v.get("at") is not None else float(m.group(2)); clause(v, m.group(3), "high_say")
    for m in AT.finditer(text):
        down = any(x.group(4 if x.re is STEP else 2).lower() == m.group(1).lower() for x in [*STEP.finditer(text), *GOES.finditer(text)]) \
            or SAYN.search(text) or _rows("SELECT 1 FROM space_vars WHERE lower(name) = lower(?) AND step != 0", (m.group(1),))
        if int(m.group(3)) > 0 and not down:
            continue  # "when hobolo is 10 ...": counting up to a mark is the every rule's
        v = var(m.group(1)); v["at"] = float(m.group(3)); clause(v, m.group(4), "low_say")
    for name, v in out.items():  # "say happy 3 times and when sad = 0": three happies bring sad down to 0
        n = SAYN.search(text)
        if n and v.get("at") == 0 and not v["step"] and n.group(1).lower() != name:
            v["pattern"], v["step"] = rf"\b{re.escape(n.group(1).lower())}\b", -1.0
            start.setdefault(name, float(n.group(2)))
    for name in start:
        if name not in out and name not in ("it", "dot"):
            var(name)
    return [(v, start.get(k)) for k, v in out.items() if k not in ("it", "dot")]


def lasting(vs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The moods your rules hold right now: each steers every reply while its variable sits on that side of its mark."""
    return [{"var": v["id"], "name": v["name"], "trigger": "mood", "say": s, "value": v["value"]} for v in vs
            if v.get("at") is not None and (s := v.get("low_say") if v["value"] <= v["at"] else v.get("high_say")) and not GATE.match(s)]


def gates(vs: list[dict[str, Any]]) -> dict[int, tuple[bool, str]]:
    """The learning systems your rules hold right now: system number -> (on, the rule's name). A later rule wins."""
    held = [(GATE.match(s), v["name"]) for v in vs if v.get("at") is not None and (s := v.get("low_say") if v["value"] <= v["at"] else v.get("high_say"))]
    return {int(m.group(1)): (m.group(2) == "on", name) for m, name in held if m}


def _settle(v: dict[str, Any], start: float | None) -> dict[str, Any]:
    saved = add_var({k: v[k] for k in ("name", *FIELDS) if k in v})
    if start is not None:
        con = db.connect()
        with con:
            con.execute("UPDATE space_vars SET value = ? WHERE id = ?", (start, saved["id"]))
        con.close()
        saved["value"] = start
    return saved


def preview(text: str) -> list[str]:
    """What a sentence would make, without saving it: the Steer builder shows this before you send."""
    if held := steady(text):
        return [define(v) + (f" Starts at {s:g}." if s is not None else "") for v, s in held]
    return [define(v) for v in read_rule(_plain(text), text)]


def _make(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    if held := steady(text):  # values that go down, marks from either side and lasting moods are read exactly, never by the model
        made = [_settle(v, s) for v, s in held]
        return " ".join(f"{v['name']}: {define(v)} It is {v['value']:g} now." for v in made), made
    # no chat history: small models copy old replies instead of answering this one
    msgs = [{"role": "system", "content": MAKE}, {"role": "user", "content": text}]
    try:
        try:  # the schema holds a small model to the shape; a server that refuses it gets plain JSON mode
            raw = jobs.complete(settings.get_all(), msgs, response_format={"type": "json_schema", "json_schema": {"name": "vars", "schema": SCHEMA}})
        except llm.ModelError as e:
            if e.status not in (400, 422, 500, 501):
                raise
            raw = jobs.complete(settings.get_all(), msgs, response_format={"type": "json_object"})
    except llm.ModelError:
        raw = "{}"  # model down: a plain sentence is still read without it (_plain below)
    try:
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
    except json.JSONDecodeError:
        data = {}
    data = data if isinstance(data, dict) else {}
    if SEARCHY.search(text) or LOOKUP.search(text) or (COLOR.search(text) and COLORISH.search(text)) or _does(text):
        for raw in [r for r in data.get("vars") or [] if isinstance(r, dict)]:
            for t in TRIGGERS:  # small models leave the say empty when the trigger should do something: hold it for _acting
                if raw.get(t) and not raw.get(f"{t}_say") and not raw.get("act"):
                    raw[f"{t}_say"] = HELD
    # "when i say X 3 times" is read exactly; small models misread the phrase and the number ("cayde, every 6")
    got = (_plain(text) if TIMES.search(text) else []) or [v for v in map(clean_var, data.get("vars") or []) if v] or _plain(text)
    made = [add_var(v) for v in read_rule(got, text)]
    if not made:
        return None
    # the reply reads back what the engine understood, from the saved rule: a model's reply could claim what was not made
    reply = " ".join(f"Made {v['name']}. {define(v)}" for v in made)
    return reply, made


PLAIN = re.compile(r"\b(?:count(?:\s+of)?|track(?:\s+of)?|watch(?:\s+for)?)\s+(?:how (?:often|many times) (?:i (?:say|type|write)\s+)?|(?:me|my)\s+(?:typing|saying|writing|using)\s+|(?:the )?word\s+)?[\"'“]?([\w-]+)[\"'”]?"
                   r"(?:.*?\b(?:reach(?:es)?|hits?|at|every|past)\s+(\d+))?", re.I)


SAID = re.compile(r"\b(?:every\w{0,4} ?time|each time|when(?:ever)?)\s+(?:i|you see me)\s+(?:say|type|write|ask|mention|use)\s+"
                  r"(?:a question with\s+|the word\s+)?[\"'“]?([\w-]+)", re.I)  # "every time i say wow": the word that is counted
ADDS_TO = re.compile(r"\b(?:add\s+\+?\d+\s+to|increase|bump|raise)\s+(?:the\s+)?(?:count(?:er)? of\s+)?[\"'“]?([\w-]+)", re.I)  # "increase laughs by 1": the variable's name
TIMES = re.compile(r"\bwhen(?:ever)?\s+(?:i|you hear me)\s+(?:say|type|write|mention|use)\s+[\"'“]?(.+?)[\"'”]?\s+(\d+)\s+times\b", re.I)  # "when i say ace of spades 3 times": a phrase and a mark
AUX = {"can", "could", "do", "does", "did", "will", "would", "should", "is", "are", "thank", "how", "why", "let"}  # no counter alone: "can you"
NAMED = re.compile(r"\b(?:variable|counter)\s+(?:called\s+|named\s+|for\s+)?[\"'“]?([\w-]+)", re.I)  # "create a variable hobolo"
WHEN = re.compile(r"\bwhen\s+[\"'“]?([\w-]+)[\"'”]?\s+(?:reach(?:es)?|hits?|gets to|is at|is|becomes?|equals|passes)\s+(\d+)", re.I)


def _does(text: str) -> bool:
    """A trigger that makes a variable or opens a paper, rather than saying something."""
    after = WHEN.search(text) or TRIGGER_WORDS.search(text)
    tail = text[after.end():] if after else ""
    return bool(PAPERISH.search(tail) or MAKEVAR.search(tail) or _spawns(tail))


def _plain(text: str) -> list[dict[str, Any]]:
    """When the model makes nothing of a plain "count jarvis; when it reaches 10 ...", "keep track of me typing holo"
    or "when holo reaches 10 turn Dot blue", read it without the model."""
    if text.rstrip().endswith("?") and not re.search(r"\b(?:variable|counter|rule)\b", text, re.I):
        return []  # "what does the paper count as bias?" asks; it does not set up a counter
    vague = {"as", "it", "that", "this", "they", "them", "the", "of", "how", "me", "my", "what", "a", "an", "to", "for", "and", "which", "called", "named"}
    def word_of(x: re.Match[str] | None) -> str:  # the word a pattern found, "" when it is too vague to count
        got = x.group(1).lower() if x else ""
        more = re.match(r"\s+([\w-]+)", text[x.end(1):]) if got in AUX else None  # "count can you in our chats": the phrase
        return "" if got in vague else f"{got} {more.group(1).lower()}" if more else got
    if (t := TIMES.search(text)) and (phrase := " ".join(t.group(1).lower().split()[:4])):  # the whole phrase is counted, the number is the mark
        rest = (text[:t.start()] + " " + text[t.end():]).strip(" ,;.")
        v = clean_var({"name": phrase.replace(" ", "_")[:24], "kind": "count", "pattern": rf"\b{re.escape(phrase)}\b", "every": int(t.group(2)), "past": -1,  # -1: the first time it is reached
                       "every_say": sa.group(1) if (sa := re.match(r"(?i)say\s+[\"'“]?(.+?)[\"'”]?$", rest)) else HELD})  # anything but a say is an action: _acting reads it
        return [v] if v else []
    m, when = PLAIN.search(text), WHEN.search(text)  # "count jarvis; when it reaches 10": the word from one, the number from either
    said = word_of(SAID.search(text))  # "a variable sleep, +1 each time i say tired": named sleep, counts tired
    word = word_of(NAMED.search(text)) or word_of(ADDS_TO.search(text)) or said or word_of(m) or word_of(when)
    named = NAMED.search(text)
    if when and when.group(1).lower() in ("counter", "it") and not m and not (named and named.start() < when.start()) \
            and re.match(r"\s*(?:hits?|reach(?:es)?|gets to)\b", text[when.end(1):], re.I):
        last = _rows("SELECT name FROM space_vars WHERE kind = 'count' ORDER BY id DESC LIMIT 1")  # "when counter hits 10": the newest counter
        word = last[0]["name"] if last else ""
    if not word:
        return []
    said, n = said or word_of(m) or word, (m and m.group(2)) or (when and when.group(2))
    say = re.search(r"(?<![Ii] )\b[Ss][Aa][Yy]\s+[\"'“]?(.+?)[\"'”]?\s*$", text)
    v = clean_var({"name": word, "kind": "count", "pattern": rf"\b{re.escape(said)}\b",
                   **({"every": int(n), "every_say": say.group(1) if say else (look.group(0) if (look := LOOKUP.search(text)) else
                    "colour" if COLOR.search(text) and COLORISH.search(text) else HELD if _does(text) else "")} if n else {})})  # a lookup rides as the say; _acting makes it the action
    if not v and n:  # a trigger with nothing to say or do: still a counter
        v = clean_var({"name": word, "kind": "count", "pattern": rf"\b{re.escape(said)}\b"})
    return [v] if v else []


def correct(reply: str, fired: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Put in front any phrase a trigger asked for that the model left out."""
    missing = [f for f in fired if f["say"].lower().rstrip(".!") not in reply.lower()]
    for f in fired:
        f["corrected"] = f in missing
    lead = " ".join(f["say"].rstrip(".!") + "." for f in missing)
    return (f"{lead} {reply}".strip() if lead else reply), fired


def fresh(reply: str, said: list[str]) -> str:
    """Drop sentences Dot already said: small models copy their old replies before adding to them."""
    old = {x.lower() for t in said for x in SENTENCE.split(t.strip())}
    kept = [x for x in SENTENCE.split(reply.strip()) if x.lower() not in old]
    return " ".join(kept) if kept else reply


SENTENCE = re.compile(r"(?<=[.!?])\s+")


def tint(var_id: int, color: str) -> None:
    """Dot wears one colour at a time: the rule that fired last."""
    con = db.connect()
    with con:
        con.execute("UPDATE space_vars SET tint = CASE WHEN id = ? THEN ? ELSE '' END", (var_id, color))
    con.close()


def take_on(var_id: int, persona: str, look: list[str] | None = None) -> None:
    """One persona at a time: a new one replaces the last, and a persona set by hand goes with it."""
    con = db.connect()
    with con:
        con.execute("DELETE FROM space_vars WHERE kind = 'persona' AND id != ?", (var_id,))
        con.execute("UPDATE space_vars SET learned = '', look = '' WHERE id != ?", (var_id,))
        con.execute("UPDATE space_vars SET learned = ?, look = ? WHERE id = ?", (persona, json.dumps(look or []), var_id))
    con.close()


def _save(role: str, text: str, events: list[dict[str, Any]] | None = None) -> None:
    con = db.connect()
    with con:
        con.execute("INSERT INTO space_turns (role, text, events) VALUES (?, ?, ?)", (role, text, json.dumps(events or [])))
    con.close()


MODELS = re.compile(r"\b(?:list|show|which|what|see|change|switch|swap|pick|choose)\b[^.?!]*\bmodels\b", re.I)
SWITCH = re.compile(r"\b(?:switch|change|swap|move)\b[^.?!]*?\b(?:to|into)\s+(?:the\s+|this\s+)?(?:model\s+)?([\w./:@-]+(?:\s+[\w./:@-]+)?)", re.I)


def models_card() -> dict[str, Any]:
    s = settings.get_all()
    st = llm.model_status(s)
    now = s.model_name or llm.pick_model(s)
    return {"kind": "models", "status": st["label"], "current": now,
            "items": [{"id": m, "current": m == now, "embed": "embed" in m.lower()} for m in st["models"]]}


OPEN = re.compile(r"\b(?:open|show|preview|read|list|see)\b[^.?!]*?\b(?:pdfs?|papers?|documents?|reader)\b", re.I)
RULEISH = re.compile(r"\b(count|track|watch|every\w{0,4} ?time|each time|whenever|variable|counter|rule)\b|\b\d+\s+times\b"
                     r"|\bwhen\s+\S+\s+(?:reach(?:es)?|hits?|gets to|is|becomes?|equals|passes)\s+\d", re.I)  # a rule, even with "open a pdf" in it


def papers_card(text: str) -> dict[str, Any]:
    rows = _rows("SELECT id, title, authors FROM papers ORDER BY COALESCE(last_opened, created_at) DESC LIMIT 40")
    words = [w for w in re.findall(r"[a-z0-9]{4,}", text.lower())
             if w not in {"open", "show", "preview", "read", "list", "papers", "paper", "pdfs", "documents", "reader", "please", "with", "that", "this", "about", "called", "named", "from", "fetch", "notes", "note", "highlights", "highlight", "bring", "pull", "mine"}]
    hit = [r["id"] for r in rows if words and all(w in (r["title"] + " " + r["authors"]).lower() for w in words)]
    return {"kind": "papers", "items": [{"id": r["id"], "title": r["title"] or "Untitled", "authors": r["authors"]} for r in rows],
            "pick": hit[0] if len(hit) == 1 else ""}


NOTES = re.compile(r"\b(?:fetch|show|get|open|read|see|list|bring|pull)\b[^.?!]*\b(?:notes?|highlights?)\b", re.I)
SLEEP = re.compile(r"\b(?:shut ?(?:yourself )?down|power (?:off|down)|go to sleep|sleep|turn (?:yourself )?off|nap)\b", re.I)


def notes_card(text: str) -> dict[str, Any]:
    """The named paper's highlights and note, else the paper opened last."""
    card = papers_card(text)
    last = _rows("SELECT id FROM papers ORDER BY last_opened IS NULL, last_opened DESC, created_at DESC LIMIT 1")
    pid = card["pick"] or (last[0]["id"] if last else "")
    if not pid:
        return {"kind": "notes", "paper": None, "highlights": [], "note": ""}
    p = _rows("SELECT id, title, note FROM papers WHERE id = ?", (pid,))[0]
    marks = _rows("SELECT id, page, text FROM highlights WHERE paper_id = ? AND text != '' ORDER BY page, id", (pid,))
    return {"kind": "notes", "paper": {"id": p["id"], "title": p["title"] or "Untitled"}, "highlights": marks[:40], "note": (p["note"] or "")[:2000]}


CREW = re.compile(r"\b(?:(remove|hide|dismiss|recall|clear|send away)|(bring back|call back|show|return))\b[^.?!]*?\b(?:creatures?|cretures?|crew)\b", re.I)
SHELF = re.compile(r"\b(?:open|show|go to|take me to)\s+(?:the\s+|my\s+)?shelf\b", re.I)
HELP = re.compile(r"\bwhat (?:all |else )?(?:can|do) (?:you|i) do\b|\bwhat are you for\b|^\s*help\b", re.I)
CREATE = re.compile(r"\b(?:create|make|hatch|build|spawn|add)\b[^.?!]*?\bcreature\b", re.I)
RUN = re.compile(r"\b(?:run|start|wake up|send)\b", re.I)
SIMILAR = re.compile(r"\b(?:similar|related|like (?:this|it))\b", re.I)
TASK = re.compile(r"\b(?:that|to|which|whose job is(?: to)?|its job is(?: to)?|job is(?: to)?)\s+(.+)$", re.I)


def _last_paper(text: str) -> str:
    pick = papers_card(text)["pick"]
    last = _rows("SELECT id FROM papers ORDER BY last_opened IS NULL, last_opened DESC, created_at DESC LIMIT 1")
    return pick or (last[0]["id"] if last else "")


def create_creature(text: str) -> tuple[str, dict[str, Any]]:
    """"create a creature that finds similar papers and adds them to my notes": a creature, made from the words, no model."""
    task = TASK.search(text[CREATE.search(text).end():])  # the words after "creature" say what it does
    task_text = (task.group(1) if task else text).strip(" .!?")
    near = bool(SIMILAR.search(text))
    name = "Similar papers" if near else " ".join(task_text.split()[:3]).capitalize()[:40] or "Helper"
    have = _rows("SELECT * FROM jobs WHERE lower(name) = lower(?)", (name,))
    if have:
        return f"You already have {name}. Say run {name.lower()} to send it.", {"kind": "creature", "job": jobs._job(have[0]), "new": False}
    out = "note" if re.search(r"\bnotes?\b", text, re.I) else "doc"
    steps = [{"scope": "similar", "prompt": "List papers similar to this one."}] if near else [{"scope": "paper", "prompt": task_text[:4000]}]
    color = _rows("SELECT COUNT(*) AS n FROM jobs")[0]["n"] % 8
    job = jobs.create_job(jobs.JobIn(name=name, color=color, output=out, steps=steps))
    where = "your notes" if out == "note" else "a document"
    return f"Hatched {name}. It {'finds papers like the one you read' if near else 'reads the paper and does that'}, and leaves {where}. Say run it.", {"kind": "creature", "job": job, "new": True}


def run_creature(text: str) -> tuple[str, dict[str, Any]] | None:
    """"run similar papers" or "run it": the creature named (else the newest) on the paper named (else the last one opened)."""
    js = _rows("SELECT * FROM jobs ORDER BY id DESC")
    low = text.lower()
    named = [j for j in js if j["name"] and j["name"].lower() in low]
    if not named and not re.search(r"\b(?:it|the creature|that creature)\b", low):
        return None
    job = (named or js or [None])[0]
    if not job:
        return "There are no creatures yet. Say create a creature that…", None
    pid = _last_paper(text)
    if not pid:
        return "There are no papers to run it on.", None
    try:
        run, _ = jobs.enqueue(job["id"], jobs.RunIn(paper_id=pid))
    except jobs.Reject as e:
        return e.message, None
    except jobs.QueueFull:
        return "Too many creatures are waiting. Try again soon.", None
    return f"{job['name']} is off to {run['paper'] or 'the paper'}.", {"kind": "run", "run": run, "job": jobs._job(job)}


def all_notes() -> list[dict[str, Any]]:
    """Every paper that has a note, newest first: the notes drawer."""
    return _rows("""SELECT p.id, p.title, p.note, (SELECT COUNT(*) FROM highlights h WHERE h.paper_id = p.id AND h.text != '') AS highlights
                    FROM papers p WHERE trim(COALESCE(p.note, '')) != '' ORDER BY COALESCE(p.last_opened, p.created_at) DESC""")


def tool(text: str) -> tuple[str, dict[str, Any]] | None:
    """Asks about the app itself are answered from the app, no model: a card the page can show and click."""
    want = SWITCH.search(text)
    if want and re.search(r"\bmodel", text, re.I):
        card, name = models_card(), want.group(1).lower().strip()
        pick = [m["id"] for m in card["items"] if not m["embed"] and name not in ("model", "it", "one") and name.replace(" ", "") in m["id"].lower().replace(" ", "")]
        if len(pick) != 1:  # none or several match: show them, so a click picks one
            return ("Which one? Tap a model." if card["items"] else f"I can't list models: {card['status']}."), card
        before = card["current"]
        settings.update({"model_name": pick[0]})
        return f"Switched to {pick[0]}.", {"kind": "switched", "from": before, "to": pick[0]}
    if (crew := CREW.search(text)) and not CREATE.search(text):
        back = bool(crew.group(2))
        return ("Here they come." if back else "Off they go, up the ladder."), {"kind": "crew", "show": back}
    if SHELF.search(text):
        return "Opening your shelf.", {"kind": "go", "to": "shelf"}
    if HELP.search(text):
        return "Here is what I can do. Tap one to try it.", {"kind": "help"}
    if CREATE.search(text):
        return create_creature(text)
    if RUN.search(text) and (done := run_creature(text)):
        return done
    if SLEEP.search(text):
        return "Shutting down. Knock on me three times to wake me.", {"kind": "sleep"}
    if NOTES.search(text):
        card = notes_card(text)
        if not card["paper"]:
            return "There are no papers yet.", card
        n = len(card["highlights"])
        return f"{card['paper']['title']}: {n} highlight{'s' * (n != 1)}{' and a note' if card['note'] else ''}.", card
    if OPEN.search(text) and not re.search(r"\bmodels?\b", text, re.I):
        card = papers_card(text)
        if card["pick"]:
            title = next(p["title"] for p in card["items"] if p["id"] == card["pick"])
            return f"Opening {title}.", card
        return (f"{len(card['items'])} papers. Tap one to open it." if card["items"] else "There are no papers yet."), card
    if MODELS.search(text):
        card = models_card()
        n = sum(not m["embed"] for m in card["items"])
        return (f"{n} chat model{'s' * (n != 1)} on the server." if card["items"] else f"I can't list models: {card['status']}."), card
    return None


def act(fired: list[dict[str, Any]], depth: int = 0) -> None:
    """Run the actions of the triggers that fired. What a search brings back is read by the counters, and the
    triggers that sets off act too, once: their own searches are not read again, so a turn always ends."""
    for f in [f for f in fired if f.get("act") and "_ran" not in f]:
        f["_ran"] = 1
        for name, arg in zip(f["act"].split("+"), f["act_arg"].split(" | ")):
            _act_one(f, name, arg.strip(), depth, fired)
        said = [f"{f['creature']['name']} is {'hatched' if f['new'] else 'already here'}."] if f.get("creature") else []
        if f.get("sleep"):
            said.append(f"{f['keeper']} is putting me to sleep. I will reflect while I rest." if f["keeper"] else "I am going to sleep. I will reflect while I rest.")
        if said and not f.get("say"):  # small models need not describe it
            f["say"] = " ".join(said)
    for f in fired:
        f.pop("_ran", None)


def _act_one(f: dict[str, Any], name: str, arg: str, depth: int, fired: list[dict[str, Any]]) -> None:
    """One action of a rule that fired; what it brings back goes on the event."""
    try:
        done = ACTIONS[name](arg, f)
    except RuntimeError as e:
        f["act_error"] = str(e)
        if f["trigger"] == "set":
            remove_var(f["var"])
        return
    f.update({k: v for k, v in done.items() if k != "feed"})
    if name == "become":
        take_on(f["var"], done.get("learned", ""), done.get("look", []))
        if done.get("tint"):
            tint(f["var"], done["tint"])
    elif name == "recolor":
        tint(f["var"], done["tint"])
    elif done.get("feed") and depth == 0:
        was = {v["id"]: v["value"] for v in variables()}
        more = measure(done["feed"], feed=True)
        f["fed"] = {v["name"]: v["value"] - was.get(v["id"], 0) for v in variables() if v["value"] != was.get(v["id"], 0)}
        for m in more:
            m["from"] = "search"
        fired.extend(more)
        act(more, depth + 1)


def reset_now(text: str) -> tuple[str, list[dict[str, Any]]] | None:
    """"reset hobolo to 0": done now, not kept as a rule. The reply and its events, or None when the message asks no such thing."""
    if not RESET_RULE.search(text) or TRIGGER_WORDS.search(text):
        return None
    low = text.lower()
    hit = [v for v in variables() if re.search(rf"\b{re.escape(v['name'].lower())}\b", low)]
    if not hit:
        return None
    con = db.connect()
    with con:
        con.executemany("UPDATE space_vars SET value = 0, passed = 0 WHERE id = ?", [(v["id"],) for v in hit])
    con.close()
    return (f"{', '.join(v['name'] for v in hit)} {'is' if len(hit) == 1 else 'are'} back to 0.",
            [{"var": v["id"], "name": v["name"], "trigger": "reset", "say": ""} for v in hit])


def say(text: str) -> dict[str, Any]:
    """One user turn. Rules run without the model, so they still count and fire when the model is down."""
    text = text.strip()[:4000]
    past = [{"role": "assistant" if t["role"] == "dot" else "user", "content": t["text"]}
            for t in _rows("SELECT role, text FROM (SELECT * FROM space_turns ORDER BY id DESC LIMIT 10) ORDER BY id")]
    _save("user", text)
    zeroed = reset_now(text)
    if zeroed:
        _save("dot", zeroed[0], zeroed[1])
        return {"reply": zeroed[0], "events": zeroed[1], "error": "", **state()}
    gone = forget(text)
    if gone is not None:  # a request to remove variables: no counting, no model
        reply = f"Removed {', '.join(v['name'] for v in gone)}." if gone else "There was nothing to remove."
        events = [{"var": v["id"], "name": v["name"], "trigger": "removed", "say": ""} for v in gone]
        _save("dot", reply, events)
        return {"reply": reply, "events": events, "error": "", **state()}
    done = None if RULEISH.search(text) else tool(text)
    if done:  # a question about the app: answered as a card
        _save("dot", done[0])
        return {"reply": done[0], "events": [], "card": done[1], "error": "", **state()}
    fired, made, error = measure(text), [], ""
    fired += lasting(variables())  # a rule's lasting mood steers every reply while it holds
    who = PERSONA.search(text)
    if who and not COUNTING.search(text):  # "set persona as Alfred": no counter, it happens now
        v = add_var({"name": who.group(1).strip()[:24], "kind": "persona", "pattern": "", **{k: None for k in TRIGGERS},
                     **{f"{k}_say": "" for k in TRIGGERS}, "target": "", "rises": None, "rises_say": "", "add_n": 0.0,
                     "act": "become", "act_arg": who.group(1).strip()[:60], "act_on": ""})
        fired.append({"var": v["id"], "name": v["name"], "trigger": "set", "say": "", "act": "become", "act_arg": v["act_arg"]})
    act(fired)  # actions run before the reply, so it already shows what they did
    try:
        tried = bool(ASKS_FOR_VARS.search(text) or steady(text)) and not (who and not COUNTING.search(text))
        got = _make(text) if tried else None
        if got:
            reply, made = got
        else:
            steer = "".join(f"\nThis turn, the rule {f['name']} fired. Begin your reply with exactly: {f['say']}" for f in fired if f["say"])
            if tried:  # the maker found nothing to make, so the reply must not claim it did
                steer += "\nNo variable was made this turn; never say you created, added or set up one."
            known = "".join(f"\nVariable {v['name']} is now {v['value']:g}" + (f" (it went up {v['delta']:g} with this message)" if v["delta"] > 0 else "") + "."
                            for v in variables() if v["kind"] != "persona")  # so Dot does not count by itself
            known += "".join(f"\nYou have taken on a persona from the variable {v['name']}. {v['learned']} Stay in it."
                             for v in variables() if v["learned"])
            known += "".join(f"\nWhile asleep you learned: {c}" for c in _learned())
            known += "".join(f"\nSpeak like this example: {c}" for c in _learned("lesson", 2))
            reply = jobs.complete(settings.get_all(), [{"role": "system", "content": DOT + library() + known + steer}, *past,
                                                       {"role": "user", "content": text}], max_tokens=300).strip()
    except llm.ModelError as e:
        reply, error = "", str(e)
    reply = fresh(reply, [m["content"] for m in past if m["role"] == "assistant"][-3:])
    reply, fired = correct(reply, fired)
    reply = reply or "I can't reach the model right now."
    events = fired + [{"var": v["id"], "name": v["name"], "trigger": "made", "say": ""} for v in made]
    _save("dot", reply, events)
    made_one = next((f for f in events if f.get("creature")), None)
    card = {"card": {"kind": "creature", "job": made_one["creature"], "new": made_one["new"]}} if made_one else {}
    return {"reply": reply, "events": events, "error": error, **card, **state()}
