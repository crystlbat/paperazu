"""The /char character engine: Dot playing J.A.R.V.I.S., Gideon, or any living persona.

In this hidden mode:
1. Knowledge comes from autonomous background jobs rather than PDFs.
2. Coupled behavioral dynamics: state variables (autonomy, depth, curiosity, knowledge)
   decay, cascade, and steer one another in real-time.
3. Personas can be switched dynamically (e.g., "become Gideon from the Flash tv series").
4. Custom user steering variables can be created on-the-fly via conversation.
"""
import json
import math
import random
import re
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from . import chibi, db, jobs, llm, settings, space, websearch
from .space import fresh

DEFAULT_PERSONA = (
    "You are J.A.R.V.I.S., an advanced AI companion with dry wit, razor-sharp intellect, and calm precision. "
    "You are Dot, a loving, living, fluid blobby companion. "
    "When asked about new concepts, research topics, or tasks requiring exploration, "
    "you actively dispatch background jobs to investigate and record synthesized facts into your memory bank. "
    "Answer in one to three crisp sentences of plain text without markdown headers. "
    "Never repeat the user's prompt back."
)

DEFAULT_COUPLED_VARS = [
    {
        "name": "autonomy",
        "kind": "state",
        "pattern": "",
        "every": 6,
        "every_say": "",
        "value": 4.0,
        "min_val": 1.0,
        "max_val": 10.0,
        "decay": 0.5,
    },
    {
        "name": "depth",
        "kind": "state",
        "pattern": "",
        "every": None,
        "every_say": "",
        "value": 0.0,
        "min_val": -5.0,
        "max_val": 5.0,
        "decay": 0.2,
    },
    {
        "name": "curiosity",
        "kind": "state",
        "pattern": "",
        "every": 4,
        "every_say": "",
        "value": 2.0,
        "min_val": 0.0,
        "max_val": 5.0,
        "decay": 0.5,
    },
    {
        "name": "knowledge",
        "kind": "accumulator",
        "pattern": "",
        "every": 1,
        "every_say": "",
        "value": 0.0,
    },
    {
        "name": "proactivity",
        "kind": "count",
        "pattern": r"\b(research|investigate|find out|look up|check|explore|learn about|what is|how does)\b",
        "every": 1,
        "every_say": "I shall look into that immediately, sir.",
        "value": 0.0,
    },
]

CHAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS char_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL DEFAULT 'J.A.R.V.I.S.',
    persona TEXT NOT NULL,
    look TEXT NOT NULL DEFAULT '[]',
    tint TEXT NOT NULL DEFAULT '#6ff7ff',
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS char_vars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL,
    pattern TEXT NOT NULL DEFAULT '',
    every INTEGER, every_say TEXT NOT NULL DEFAULT '',
    past INTEGER, past_say TEXT NOT NULL DEFAULT '',
    drops INTEGER, drops_say TEXT NOT NULL DEFAULT '',
    value REAL NOT NULL DEFAULT 0,
    delta REAL NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0,
    min_val REAL,
    max_val REAL,
    decay REAL DEFAULT 0,
    act TEXT NOT NULL DEFAULT '',
    act_arg TEXT NOT NULL DEFAULT '',
    act_on TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS char_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS char_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    result_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS char_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);
"""

KINDS: dict[str, Callable[[float, str, str], float]] = {
    "count": lambda v, text, pat: v + len(re.findall(pat, text, re.I)) if pat else v,
    "words": lambda v, text, pat: float(len(text.split())),
    "turns": lambda v, text, pat: v + 1,
    "state": lambda v, text, pat: v,
    "accumulator": lambda v, text, pat: v,
}

CLAIM = re.compile(r"\b(?:I(?:'ve| have)?|and)\s+(?:also\s+)?(?:defined|opened|created|increased|incremented|set up|added)\b", re.I)
BECOME_PATTERN = re.compile(
    r"\b(?:become|became|be like|speak like|talk like|act like|pretend to be|switch to|turn into|transform into|you are now)\s+(?:an? |the )?(.+?)(?:[;.!?]|\Z)",
    re.I,
)

RESEARCH_PATTERN = re.compile(
    r"\b(?:research|investigate|find out(?: about)?|look up|explore|learn about|what is|tell me about)\s+(.+?)(?:[?.!]|\Z)",
    re.I,
)

MAKE_VARS_PATTERN = re.compile(
    r"\b(?:count|track|watch|every time|whenever|rule|steer variable)\b",
    re.I,
)


_SCHEMA_DONE: set[str] = set()  # DB files whose schema and migrations ran in this process: a training step calls init_db hundreds of times


def init_db() -> None:
    """Ensure char tables and default variables exist."""
    con = db.connect()
    with con:
        if str(db.DB_PATH) not in _SCHEMA_DONE:
            con.executescript(CHAR_SCHEMA)
            # Migration for existing char_vars table
            cols = {r["name"] for r in con.execute("PRAGMA table_info(char_vars)")}
            for col, ctype in (
                ("min_val", "REAL"),
                ("max_val", "REAL"),
                ("decay", "REAL DEFAULT 0"),
                ("act", "TEXT NOT NULL DEFAULT ''"),
                ("act_arg", "TEXT NOT NULL DEFAULT ''"),
                ("act_on", "TEXT NOT NULL DEFAULT ''"),
            ):
                if col not in cols:
                    con.execute(f"ALTER TABLE char_vars ADD COLUMN {col} {ctype}")

        # Ensure profile exists
        row = con.execute("SELECT id FROM char_profile WHERE id = 1").fetchone()
        if not row:
            con.execute(
                "INSERT INTO char_profile (id, name, persona, look, tint) VALUES (1, 'J.A.R.V.I.S.', ?, '[]', '#6ff7ff')",
                (DEFAULT_PERSONA,),
            )
        var_count = con.execute("SELECT COUNT(*) AS c FROM char_vars").fetchone()["c"]
        if var_count == 0:
            for v in DEFAULT_COUPLED_VARS:
                con.execute(
                    "INSERT INTO char_vars (name, kind, pattern, every, every_say, value, min_val, max_val, decay) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        v["name"],
                        v["kind"],
                        v["pattern"],
                        v.get("every"),
                        v.get("every_say", ""),
                        v.get("value", 0.0),
                        v.get("min_val"),
                        v.get("max_val"),
                        v.get("decay", 0.0),
                    ),
                )
    con.close()
    _SCHEMA_DONE.add(str(db.DB_PATH))


def get_profile() -> dict[str, Any]:
    init_db()
    con = db.connect()
    row = con.execute("SELECT name, persona, look, tint FROM char_profile WHERE id = 1").fetchone()
    con.close()
    if not row:
        return {"name": "J.A.R.V.I.S.", "persona": DEFAULT_PERSONA, "look": [], "tint": "#6ff7ff"}
    return {
        "name": row["name"],
        "persona": row["persona"].replace(OLD_FALLBACK, FALLBACK),  # older personas carry a line that made them call themselves Dot
        "look": json.loads(row["look"]) if row["look"] else [],
        "tint": row["tint"] or "#6ff7ff",
    }


NAMED = {"black": "#111111", "white": "#f4f4f5", "red": "#ef4444", "blue": "#3b82f6", "green": "#22c55e", "yellow": "#facc15", "orange": "#f97316",
         "purple": "#a855f7", "pink": "#ec4899", "gold": "#f5c542", "silver": "#c0c6d0", "grey": "#9ca3af", "gray": "#9ca3af", "cyan": "#22d3ee", "teal": "#14b8a6", "brown": "#a16207"}


def readable(tint: str) -> str:
    """A persona's colour as #rrggbb that stays visible on the night canvas: names become hex, and a dark one is lifted toward white."""
    t = NAMED.get((tint or "").strip().lower(), (tint or "").strip())
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", t):
        return "#6ff7ff"
    rgb = [int(t[k:k + 2], 16) for k in (1, 3, 5)]
    lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
    if lum < 0.3:  # black on near-black vanishes: mix toward white until it shows
        f = (0.3 - lum) / (1 - lum) + 0.25
        rgb = [round(c + (255 - c) * f) for c in rgb]
    return "#" + "".join(f"{c:02x}" for c in rgb)


def update_profile(name: str, persona: str, look: list[str], tint: str) -> None:
    init_db()
    con = db.connect()
    with con:
        con.execute(
            "UPDATE char_profile SET name = ?, persona = ?, look = ?, tint = ?, updated_at = datetime('now') WHERE id = 1",
            (name, persona, json.dumps(look), readable(tint)),
        )
    con.close()


def tables() -> dict[str, int]:
    """Row counts of data artifacts for floor stacks in the space view."""
    init_db()
    con = db.connect()
    j_count = con.execute("SELECT COUNT(*) AS c FROM char_jobs").fetchone()["c"]
    m_count = con.execute("SELECT COUNT(*) AS c FROM char_memories").fetchone()["c"]
    t_count = con.execute("SELECT COUNT(*) AS c FROM char_turns").fetchone()["c"]
    v_count = con.execute("SELECT COUNT(*) AS c FROM char_vars").fetchone()["c"] + con.execute("SELECT COUNT(*) AS c FROM space_vars WHERE kind != 'persona'").fetchone()["c"]
    start = _start()
    notes = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source NOT IN ('lesson', 'sheet', 'question') AND id > ?", (start,)).fetchone()["c"]
    lessons = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source = 'lesson' AND id > ?", (start,)).fetchone()["c"]
    new = con.execute("SELECT title, content FROM char_memories WHERE source IN ('reflection', 'lesson') AND id > ? ORDER BY id DESC LIMIT 1", (start,)).fetchone()
    con.close()
    return {
        # what the character knows of itself, for the corner panel of /char
        "sheet": sum(1 for v in space.sheet_of(get_profile()["persona"]).values() if v),
        "notes": notes, "lessons": lessons, "questions": len(_open_questions(start)),
        "entities": con2 if (con2 := len(graph(start)["nodes"])) else 0,
        "last": f"{new['title'].removeprefix('Reflection: ')}: {new['content']}"[:150] if new and new["title"].startswith("Reflection") else new["content"][:150] if new else "",
        "papers": j_count,
        "highlights": m_count,
        "chat_turns": t_count,
        "variables": v_count,
        "cards": m_count,
    }


# what update_coupled_system really does to each mood, said plainly for the page
MOODS = {"autonomy": "Mood. Up 2 when you ask it to research or look something up; otherwise it eases down.",
         "depth": "Mood. Up when you write long messages, down with short ones: how deep it answers.",
         "curiosity": "Mood. Up 2 for a research ask, up 1 for a question, up while it learns; otherwise it eases down."}
MOOD = 100_000  # a mood's id on the page is MOOD + its char_vars id


def variables() -> list[dict[str, Any]]:
    """Return all active variables plus the active persona variable for Dot."""
    init_db()
    con = db.connect()
    rows = con.execute("SELECT * FROM char_vars ORDER BY id").fetchall()
    con.close()
    vars_list = [{**dict(r), "id": MOOD + r["id"], "about": MOODS.get(r["name"], "A mood of the character.")} for r in rows]  # moods; ids kept apart from the shared rules
    vars_list += mine()  # your rules for this character: the same engine and table the Dot page keeps

    prof = get_profile()
    persona_var = {
        "id": 999999,
        "name": prof["name"].lower(),
        "kind": "persona",
        "pattern": "",
        "every": None,
        "every_say": "",
        "past": None,
        "past_say": "",
        "drops": None,
        "drops_say": "",
        "value": 0,
        "delta": 0,
        "streak": 0,
        "passed": 0,
        "turns": 0,
        "learned": prof["persona"],
        "about": f"Who Dot is now: {prof['name']}. Its sheet fills in as it learns.",
        "act_arg": prof["name"],
        "look": prof["look"],
        "tint": prof["tint"],
    }
    return [persona_var, *vars_list]


def state() -> dict[str, Any]:
    """Current state payload for the Space UI."""
    init_db()
    con = db.connect()
    mark = con.execute("SELECT created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Resting: char %' ORDER BY id DESC LIMIT 1").fetchone()
    rows = con.execute(  # the live persona's own chat only, as _chat_since reads it: another persona's turns never show here
        "SELECT * FROM (SELECT * FROM char_turns WHERE created_at >= ? ORDER BY id DESC LIMIT 40) ORDER BY id", (mark["created_at"] if mark else "",)
    ).fetchall()
    mem_rows = con.execute(
        "SELECT id, title, content, source FROM char_memories WHERE source NOT IN ('lesson', 'sheet', 'question', 'entity') AND id > ? ORDER BY id DESC LIMIT 12", (_start(),)  # its notes: the moons on /char
    ).fetchall()
    con.close()

    turns, kept = [], heard()
    for r in rows:
        d = dict(r)
        d["events"] = json.loads(d["events"]) if d.get("events") else []
        if d["id"] in kept:
            d["heard"] = kept[d["id"]]  # it kept what you said, or let it go
        turns.append(d)

    papers = [{"id": str(m["id"]), "title": m["title"], "content": m["content"], "authors": m["source"], "is_note": True} for m in mem_rows]
    return {"turns": turns, "vars": variables(), "tables": tables(), "papers": papers, "graph": graph()}


def all_notes() -> list[dict[str, Any]]:
    """All knowledge notes created by background jobs or interactions, newest first."""
    init_db()
    con = db.connect()
    rows = con.execute("SELECT id, title, content, source FROM char_memories WHERE source NOT IN ('lesson', 'sheet', 'question') ORDER BY id DESC").fetchall()
    con.close()
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "note": r["content"],
            "highlights": 1,
            "source": r["source"],
        }
        for r in rows
    ]


def remove_var(var_id: int) -> bool:
    """A mood (id past MOOD) or one of your rules (shared with the Dot page)."""
    if var_id < MOOD:
        return space.remove_var(var_id)
    init_db()
    con = db.connect()
    with con:
        removed = con.execute("DELETE FROM char_vars WHERE id = ?", (var_id - MOOD,)).rowcount > 0
    con.close()
    return removed


def clear() -> None:
    init_db()
    con = db.connect()
    with con:
        con.execute("DELETE FROM char_turns")
    con.close()


def add_memory(title: str, content: str, source: str = "manual") -> dict[str, Any]:
    init_db()
    con = db.connect()
    with con:
        cur = con.execute(
            "INSERT INTO char_memories (title, content, source) VALUES (?, ?, ?)",
            (title.lstrip(), content.strip(), source.strip()),  # not rstrip: callers look titles up as f"...{x}"[:80], which can end on a space
        )
        mem_id = cur.lastrowid
        # Update knowledge accumulator variable
        con.execute("UPDATE char_vars SET value = value + 1 WHERE name = 'knowledge'")
    con.close()
    return {"id": mem_id, "title": title, "content": content, "source": source}


def _start() -> int:
    """The note the current /char character started at: the page shows what it learned since, not the last character's."""
    init_db()
    con = db.connect()
    row = con.execute("SELECT id FROM char_memories WHERE source = 'sheet' AND title LIKE 'Resting: char %' ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    return row["id"] if row else 0


ACT_DECAY = 0.5  # ACT-R's d: a mention's weight falls as its age (in rows, not seconds, so idle time does not erase it) to the -0.5


def graph(since: int | None = None) -> dict[str, Any]:
    """The character's knowledge graph: the names its notes mention and the ideas about them (nodes), and what is mentioned together (edges).
    Two kinds of node: "concrete" names (few, stable, never merged) and "abstract" ideas (many, near-synonymous, folded together)."""
    init_db()
    since = _start() if since is None else since
    con = db.connect()
    rows = con.execute("SELECT id, title, content FROM char_memories WHERE source = 'entity' AND id > ? ORDER BY id", (since,)).fetchall()
    titles = {r["title"] for r in con.execute("SELECT title FROM char_memories WHERE source = 'reflection' AND id > ?", (since,))}
    folded = [r["title"].removeprefix("Summary: ") for r in con.execute("SELECT title FROM char_memories WHERE source = 'summary' AND id > ? ORDER BY id", (since,))]
    con.close()
    done = {t.removeprefix("Reflection: ").lower().removeprefix("who or what is ").rstrip("?") for t in titles}
    nodes, seen, off = [], {}, _offworld(since)
    for r in rows:
        idea = r["title"].startswith("Idea: ")
        name, notes = r["title"].removeprefix("Entity: ").removeprefix("Idea: "), [x for x in r["content"].split(",") if x]
        if name in off:  # the Asker found it is not part of this character's world
            continue
        known = f"Reflection: {IDEA_LENSES[0].format(name=name)}"[:80] in titles if idea else name.lower() in done
        nodes.append({"name": name, "n": len(notes), "known": known, "kind": "abstract" if idea else "concrete"})
        for x in notes:
            seen.setdefault(x, []).append(name)
    edges = sorted({(a, b) for names in seen.values() for i, a in enumerate(names) for b in names[i + 1:]})
    deg: dict[str, int] = {}
    for a, b in edges:
        deg[a], deg[b] = deg.get(a, 0) + 1, deg.get(b, 0) + 1
    last = max((int(x) for x in seen if x.isdigit()), default=0)
    for n, r in zip(nodes, [r for r in rows if r["title"].removeprefix("Entity: ").removeprefix("Idea: ") not in off]):
        ids = [int(x) for x in r["content"].split(",") if x.isdigit()]
        act = sum((last - i + 1) ** -ACT_DECAY for i in ids)  # ACT-R base level, exp(B) = sum of age^-d: often and lately mentioned
        n |= {"deg": deg.get(n["name"], 0), "lev": round((1 + deg.get(n["name"], 0)) * act, 4)}  # Reddin's leverage, deg(v) * sum W, with ACT-R's decay as W
    have = {n["name"] for n in nodes}
    links = [list(m.groups()) for t in sorted(titles) if (m := re.match(r"Reflection: How are (.+) and (.+) connected\?$", t)) and set(m.groups()) <= have]
    # the inner layer, what it worked out for itself: names it has folded into a summary, and pairs it looked up a connection for
    return {"nodes": nodes, "edges": [list(e) for e in edges][:60], "folds": [f for f in folded if f in have], "links": links}


def _entities_of(note_id: int, text: str, who: str) -> list[str]:
    """One tiny call: the names in a note. Small models do this well when asked for nothing else."""
    raw = _ask(f"List up to four names of people, places, things or groups this note mentions, other than {who}. Only the names, separated by commas.", text, 40)
    names: list[str] = []
    for x in re.split(r"[,;\n]|\band\b", raw):
        x = re.sub(r"^[\s\-*\d.)]+|[\s.\"'`]+$", "", x).strip(" \"'")
        mine = {who.lower(), *who.lower().split()[:1]}  # "Navi From Zelda" is not a name it should look up
        if 2 <= len(x) <= 40 and len(x.split()) <= 5 and re.search(r"[A-Z0-9]", x) and x.lower() not in mine | {"none", "n/a", "no", "yes"} and not re.match(r"(i|i'm|we|you|it|this|there)\b", x, re.I) and not x.lower().startswith(("the note", "names")) and x.lower() not in [n.lower() for n in names] and x.lower() in text.lower():  # only names the note literally holds: a small model echoes names it was not given
            names.append(x)
    names = names[:4]
    con = db.connect()
    with con:
        for name in names:
            row = con.execute("SELECT id, content FROM char_memories WHERE source = 'entity' AND lower(title) = lower(?) AND id > ?", (f"Entity: {name}", _start())).fetchone()
            if row:
                con.execute("UPDATE char_memories SET content = ? WHERE id = ?", (f"{row['content']},{note_id}", row["id"]))
            else:
                con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'entity')", (f"Entity: {name}"[:80], str(note_id)))
        con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'sheet')", (f"Entities: {note_id}", ", ".join(names)))
    con.close()
    return names


def _ideas_of(note_id: int, text: str, names: list[str]) -> list[str]:
    """The abstract half, a call of its own after the names: what the note says is going on around them ("guarding Hyrule").
    Each idea must start with an -ing word and hold one of the note's names, so it stays checkable. Ideas pile up as near-synonyms,
    so a new one that means the same as the newest idea about that name is folded into it; names are never folded."""
    raw = _ask(f"What is going on in this note? Give one or two short phrases of two to six words. Each starts with a verb ending in -ing and names one of: {', '.join(names)}. Only the phrases, separated by semicolons, or NONE.", text, 30)
    ideas: list[str] = []
    for x in re.split(r"[;\n]", raw):
        x = re.sub(r"^[\s\-*\d.)]+|[\s.\"'`]+$", "", x).strip(" \"'")
        low = x.lower()
        if 2 <= len(x.split()) <= 6 and low.split()[0].endswith("ing") and any(n.lower() in low for n in names) and low not in [i.lower() for i in ideas]:
            ideas.append(x)
    con = db.connect()
    held = con.execute("SELECT id, title FROM char_memories WHERE source = 'entity' AND title LIKE 'Idea: %' AND id > ? ORDER BY id DESC", (_start(),)).fetchall()
    con.close()
    kept: list[str] = []
    for idea in ideas[:2]:
        name = next(n for n in names if n.lower() in idea.lower())
        near = next((h for h in held if name.lower() in h["title"].lower()), None)  # shortcut: only the newest idea about the same name may absorb it; compare more if synonyms slip through
        old = near["title"].removeprefix("Idea: ") if near else ""
        same = bool(near) and (old.lower() == idea.lower() or _ask("Do these two phrases mean the same thing? Answer YES or NO.", f"{old}\n{idea}", 3).strip().upper().startswith("Y"))
        con = db.connect()
        with con:
            if same:
                con.execute("UPDATE char_memories SET content = content || ',' || ? WHERE id = ?", (str(note_id), near["id"]))
                con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'sheet')", (f"Folded: {idea}"[:80], old))  # the leaf's words, kept
            else:
                con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'entity')", (f"Idea: {idea}"[:80], str(note_id)))
        con.close()
        if (old if same else idea) not in kept:
            kept.append(old if same else idea)
    add_memory(f"Ideas: {note_id}", ", ".join(kept), source="sheet")
    return kept


def _chat_since() -> list[Any]:
    """The current character's own chat: the turns since it was become."""
    init_db()
    con = db.connect()
    mark = con.execute("SELECT created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Resting: char %' ORDER BY id DESC LIMIT 1").fetchone()
    rows = con.execute("SELECT id, role, text, created_at FROM char_turns WHERE created_at >= ? ORDER BY id", (mark["created_at"] if mark else "",)).fetchall()
    con.close()
    return rows


def sorter(limit: int = 1) -> dict[str, Any]:
    """Sorter, the first /char creature: reads the character's past chat, one message per model call, and pulls out the names in it.
    The names land in the knowledge graph; `limit` is how many messages one run may read (the factory's dial)."""
    who = get_profile()["name"]
    turns = _chat_since()
    con = db.connect()
    done = {r["title"].removeprefix("Entities: t") for r in con.execute("SELECT title FROM char_memories WHERE source = 'sheet' AND title LIKE 'Entities: t%'")}
    con.close()
    todo = [t for t in turns if str(t["id"]) not in done]
    read = [{"turn": t["id"], "role": t["role"], "text": t["text"][:120], "names": _entities_of(f"t{t['id']}", t["text"], who)} for t in todo[:max(1, min(limit, 20))]]
    asked = asker([n for r in read for n in r["names"]])  # the Sorter hands what it found to the Asker
    return {"creature": "Sorter", "read": read, "asked": asked, "left": len(todo) - len(read), "total": len(turns), "graph": graph()}


def _held() -> tuple[int, int]:
    """What the character holds right now: its notes and their size in characters."""
    con = db.connect()
    r = con.execute("SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(content)), 0) AS c FROM char_memories WHERE source NOT IN ('lesson', 'sheet', 'question', 'entity') AND id > ?", (_start(),)).fetchone()
    con.close()
    return r["n"], r["c"]


def _offworld(since: int | None = None) -> set[str]:
    con = db.connect()
    out = {r["title"].removeprefix("Off-world: ") for r in con.execute("SELECT title FROM char_memories WHERE source = 'sheet' AND title LIKE 'Off-world: %' AND id > ?", (_start() if since is None else since,))}
    con.close()
    return out


def world_words() -> set[str]:
    """The proper nouns of its world, read exactly: its name, its work, and the names its sheet and its wiki reference use mid-sentence."""
    p = get_profile(); ref = (chibi.cached(p["name"]) or {}).get("about", "")
    own = {w for w in re.findall(r"[A-Za-z][\w'-]{2,}", p["name"]) if w.lower() != "from"}
    words = own | set((chibi.where_from(p["persona"]) or "").split()) | {w.removesuffix("'s") for w in re.findall(r"(?<=[a-z,;] )[A-Z][\w'-]{2,}", f"{p['persona']} {ref}")}
    return words if len(words - own) >= 3 else set()  # too little known of its world to judge by: no gate rather than no learning


def on_world(text: str, words: set[str] | None = None) -> bool:
    """A topic the model made up belongs to its world only if it names something from it: no model, so a small one can't drift it to "the political landscape"."""
    words = world_words() if words is None else words
    return not words or any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def in_voice(said: str | None, who: str) -> bool:
    """A wish is the character asking you: one that names the character in the third person, or calls its world "the game", was written as a fan asking about it."""
    first = (who.split() or [""])[0]
    return bool(said) and not (first and re.search(rf"\b{re.escape(first)}\b", said)) and not re.search(r"\bthe game\b", said, re.I)


LENSES = ("Who or what is {name}?", "Why does {name} matter to {who}?", "Where and when does {name} show up?")  # a name seen through a lens is a question; each answer opens the next
IDEA_LENSES = ("How did {name} start?", "What makes {name} hard?", "How has {name} changed?")  # an idea is a doing, so it gets asked about its start, its friction and its change


def asker(names: list[str] | None = None, limit: int = 3) -> list[str]:
    """A creature that turns names into questions; reflection researches open questions first.
    Each name climbs LENSES ("Who or what is Zelda?", then why it matters, then where and when), one lens at a time and only once the last
    is answered; two known names seen together get "How are A and B connected?". When every pair is spent it asks nothing.
    The Sorter hands it the names it just found; with none it takes the most-mentioned names."""
    since = _start()
    con = db.connect()
    asked = {r["content"].split(" (from")[0].lower() for r in con.execute("SELECT content FROM char_memories WHERE source = 'question' AND id > ?", (since,))}
    done = {r["title"] for r in con.execute("SELECT title FROM char_memories WHERE id > ?", (since,))}
    con.close()
    g = graph(since)
    pool = names if names is not None else [n["name"] for n in sorted(g["nodes"], key=lambda n: (-n.get("lev", n["n"]), n["kind"] == "abstract"))]  # most leverage first (linked, often and lately mentioned); a name before an idea
    known = {n["name"] for n in g["nodes"] if n["known"]}
    ideas = {n["name"] for n in g["nodes"] if n["kind"] == "abstract"}
    room = max(0, limit - len(_open_questions(since)))  # a factory limit: only so many open questions at once
    who, off, new, checks = get_profile()["name"], _offworld(since), [], 0

    def ask(q: str) -> None:
        add_memory(f"Question: {q}"[:80], f"{q} (from 0)", source="question"); asked.add(q.lower()); new.append(q)

    def lens_of(name: str) -> tuple[int, str] | None:
        for i, lens in enumerate(IDEA_LENSES if name in ideas else LENSES):
            q = lens.format(name=name, who=who)
            if (i == 0 and name in known) or f"Reflection: {q}"[:80] in done:
                continue  # answered: go a lens deeper
            return None if q.lower() in asked else (i, q)  # still open: wait for its answer
        return None

    for name in pool:
        got = None if len(new) >= room or name in off else lens_of(name)
        if not got or (got[0] == 0 and checks >= limit + 3):
            continue
        if got[0] == 0 and name not in ideas:  # a gate first: only names from the character's own world become questions (an idea already holds one)
            checks += 1
            if not _ask(f"Is {name} a person, place, thing or group from the world of {who}? Answer YES or NO.", name, 3).strip().upper().startswith("Y"):
                add_memory(f"Off-world: {name}"[:80], f"not part of {who}'s world", source="sheet"); off.add(name)
                continue
        ask(got[1])
    for a, b in g["edges"]:
        q = f"How are {a} and {b} connected?"
        if len(new) < room and a in known and b in known and not {a, b} & ideas and q.lower() not in asked and f"Reflection: {q}"[:80] not in done:
            ask(q)
    met = {frozenset(e) for e in g["edges"]}
    names = [n for n in pool if n not in ideas and n not in off and n.lower() != who.lower()]
    for q in (f"How are {a} and {b} connected?" for i, a in enumerate(names) for b in names[i + 1:] if frozenset((a, b)) not in met):
        if len(new) < room and q.lower() not in asked and f"Reflection: {q}"[:80] not in done:
            ask(q); break  # one unmet pair per run: the answer draws the edge, and the next run tries the next pair
    return new


def speak(text: str) -> bytes:
    """The character's voice from the local model server (OpenAI /audio/speech). Raises when no loaded model can speak, so the page can use the browser's voice."""
    import urllib.request
    s = settings.get_all()
    req = urllib.request.Request(s.base_url.rstrip("/") + "/audio/speech", data=json.dumps({"input": text[:600], "response_format": "mp3"}).encode(),
                                 headers={"Authorization": f"Bearer {s.api_key or 'none'}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        if not r.headers.get("content-type", "").startswith("audio"):
            raise RuntimeError("the model server sent no audio")
        return r.read()


def mind() -> dict[str, Any]:
    """Everything the character holds, newest first, and the prompts it last sent the model."""
    con = db.connect()
    rows = con.execute("SELECT id, title, content, source, created_at FROM char_memories WHERE id > ? AND NOT (source = 'sheet' AND (title LIKE 'Resting: %' OR title LIKE 'Entities: %' OR title LIKE 'Kept: %' OR title LIKE 'System: _' OR title = 'Mode' OR title LIKE 'Guess: %' OR title LIKE 'Checked: %' OR title LIKE 'Ground: %' OR title LIKE 'Sources: %' OR title LIKE 'Gate: %' OR title LIKE 'Dial: %' OR title IN ('Tick', 'Reply', 'Baked') OR title LIKE 'Fail: %' OR title LIKE 'Correction: %' OR title LIKE 'Reviewed: %' OR title LIKE 'Asking: %' OR title LIKE 'Answered: %' OR title LIKE 'Run: %' OR title LIKE 'Stuck: %')) ORDER BY id DESC", (_start(),)).fetchall()
    con.close()
    p = get_profile()
    return {"who": p["name"], "persona": p["persona"], "memories": [dict(r) for r in rows], "open": _open_questions(_start()), "prompts": list(PROMPTS)[::-1]}


def mesh() -> dict[str, Any]:
    """Everything this character holds as one mesh, layer by layer: S2 plans, the S1 questions made of them, the S0 notes that answer
    those, the names the notes mention, and the chat. Edges say what came from what; the Verifier's verdicts ride on the nodes."""
    init_db()
    start = _start()
    con = db.connect()
    rows = con.execute("SELECT id, title, content, source, created_at FROM char_memories WHERE id > ? ORDER BY id", (start,)).fetchall()
    mark = next((r["created_at"] for r in con.execute("SELECT created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Resting: char %' ORDER BY id DESC LIMIT 1")), "")
    turns = con.execute("SELECT id, role, text, created_at FROM char_turns WHERE created_at >= ? ORDER BY id DESC LIMIT 40", (mark,)).fetchall()[::-1]
    con.close()
    sheet = lambda p: {r["title"].removeprefix(p): r for r in rows if r["source"] == "sheet" and r["title"].startswith(p)}
    checked, reviewed = sheet("Checked: "), sheet("Reviewed: ")
    nodes: list[dict[str, Any]] = []
    edges: list[list[str]] = []
    note_at: dict[str, str] = {}  # a note's title (and its topic) -> node id, for linking
    for r in rows:
        t, s, rid = r["title"], r["source"], r["id"]
        if t.startswith("Plan") and s == "sheet" and ": " in t:
            nodes.append({"id": f"m{rid}", "layer": "plan", "label": r["content"], "body": r["content"], "state": "dropped" if t.startswith("Plan (dropped)") else "open"})
        elif s == "question":
            q = re.sub(r" \(from \d+\)$", "", r["content"])
            nodes.append({"id": f"m{rid}", "layer": "question", "label": q, "body": q, "key": f"Reflection: {q}"[:80]})
            if m := re.search(r"\(from (\d+)\)$", r["content"]):
                edges.append([f"m{m[1]}", f"m{rid}"])
        elif s in ("reflection", "summary") or s.startswith("job:") or (s == "sheet" and t.startswith("Reflection: ") and r["content"].startswith("(rejected)")):
            v = checked.get(str(rid))
            state = "rejected" if r["content"].startswith("(rejected)") or (v and v["content"] == "drop") else "verified" if v else "unchecked"
            nodes.append({"id": f"m{rid}", "layer": "note", "label": t.split(": ", 1)[-1], "body": r["content"], "state": state, "kind": "summary" if s == "summary" else "research" if s.startswith("job:") else "note"})
            note_at[t] = note_at[t.split(": ", 1)[-1]] = f"m{rid}"
    for n in nodes:  # a question answered by a note
        if n["layer"] == "question" and (to := note_at.get(n.pop("key"))):
            edges.append([n["id"], to]); n["state"] = "answered"
        elif n["layer"] == "question":
            n["state"] = "open"
    g = graph(start)
    for x in g["nodes"]:
        nodes.append({"id": f"n:{x['name']}", "layer": "name", "label": x["name"], "state": "known" if x["known"] else "curious", "kind": "idea" if x["kind"] == "abstract" else "name", "n": x["n"]})
    for r in rows:  # a note mentions a name: Entity rows list the note ids
        if r["source"] == "entity":
            name = r["title"].removeprefix("Entity: ").removeprefix("Idea: ")
            edges += [[f"m{i}", f"n:{name}"] for i in dict.fromkeys(r["content"].split(",")) if i and f"m{i}" in {n["id"] for n in nodes}]
    replies = [r for r in rows if r["source"] == "sheet" and r["title"] == "Reply"]
    prev = None
    for t in turns:
        rv = reviewed.get(str(t["id"]))
        nodes.append({"id": f"t{t['id']}", "layer": "chat", "label": t["text"][:60], "body": t["text"], "kind": "you" if t["role"] == "user" else "it",
                      "state": rv["content"] if rv else ""})
        if prev:
            edges.append([prev, f"t{t['id']}"])
        prev = f"t{t['id']}"
    dots = [t for t in turns if t["role"] == "dot"]
    for rp in replies:  # what a reply leaned on: the first reply of its own written at or after the Reply row
        d = next((t for t in dots if t["created_at"] >= rp["created_at"]), None)
        if not d:
            continue
        used = json.loads(rp["content"] or "{}")
        edges += [[f"t{d['id']}", f"n:{x}"] for x in used.get("names", [])] + [[f"t{d['id']}", note_at[x]] for x in used.get("notes", []) if x in note_at]
    for i, (k, v, grown) in enumerate(traits()):  # the top layer: who it is, line by line from its persona prompt; what you taught it is "grown"
        nodes.append({"id": f"p{i}", "layer": "trait", "label": f"{k}: {v}"[:60], "body": f"{k}: {v}", "kind": k.lower(), "state": "grown" if grown else "base"})
        if dots:
            edges.append([f"p{i}", f"t{dots[-1]['id']}"])  # every trait speaks through its latest reply
    have = {n["id"] for n in nodes}
    edges = [e for e in dict.fromkeys(map(tuple, edges)) if e[0] in have and e[1] in have]
    return {"who": get_profile()["name"], "nodes": nodes, "edges": [list(e) for e in edges]}


GROWN = "How you have grown, and how you speak now"


def _tone() -> str:
    """The tone section of its reply prompt: the last one the tune step adopted, or, before any, the plain direction you gave."""
    con = db.connect()
    r = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Tone' AND id > ? ORDER BY id DESC LIMIT 1", (_start(),)).fetchone()
    con.close()
    return r["content"] if r else (f"Your manner of speech, in every sentence: {way.rstrip('.')}. Rewrite plain facts in that manner; never drop it." if (way := _direction()) else "")


def _meets(want: list[str], reply: str, asked: str = "") -> tuple[float | None, str]:
    """One small call, trait by trait: the share of the wanted traits this reply carries (0 to 1), and which it missed. None when the model said nothing."""
    v = _ask("You grade a reply against numbered traits. For each trait write its number and YES or NO on its own line. Nothing else.",
             f"Traits:\n" + "\n".join(f"{i + 1}. {w}" for i, w in enumerate(want)) + f"\nQuestion it answered: {asked[:300] or '(none)'}\nReply: {reply[:500]}", 12 + 6 * len(want))
    got = {int(m[1]): m[2].upper() == "YES" for m in re.finditer(r"(?im)^\W*(\d+)\W+(yes|no)\b", v or "") if 0 < int(m[1]) <= len(want)}
    if not got:
        return None, ""
    missed = [want[i - 1] for i in range(1, len(want) + 1) if not got.get(i, False)]
    return round(1 - len(missed) / len(want), 2), ("missed: " + "; ".join(missed)) if missed else "carries every trait"


def traits() -> list[tuple[str, str, bool]]:
    """Its persona prompt as traits: (kind, text, grown). Grown ones came from you: a direction it slept on, or an instruction after a mistake."""
    out: list[tuple[str, str, bool]] = []
    for line in get_profile()["persona"].splitlines():
        line = line.strip()
        if not line:
            continue
        k, _, v = line.partition(": ") if re.match(r"^[A-Z][\w ,']{1,60}: ", line) else ("Identity", "", line)
        out.append(("Grown", v, True) if k == GROWN else (k, v, False))
    seen = {v.lower() for _, v, _ in out}
    if (way := _direction()) and way.lower() not in seen:
        out.append(("Grown", way, True)); seen.add(way.lower())
    out += [("Taught", i["text"], True) for i in instructions()[::-1] if i["text"].lower() not in seen]
    if (t := _tone()) and _direction():
        out.append(("Tone", t, True))  # the prompt section the tune step rewrites until replies meet the traits above
    return out


def pruner() -> dict[str, Any]:
    """A creature that weighs one note per call: does it help the character stay itself? Dropped notes are archived as 'Pruned: ...' sheet rows, not lost."""
    p = get_profile(); who = p["name"]
    con = db.connect()
    judged = {r["title"].split(": ", 1)[1] for r in con.execute("SELECT title FROM char_memories WHERE source = 'sheet' AND title LIKE 'Kept: %'")}
    row = next((r for r in con.execute("SELECT id, title, content FROM char_memories WHERE source NOT IN ('lesson', 'sheet', 'question', 'entity') AND id > ? ORDER BY id", (_start(),)) if str(r["id"]) not in judged), None)
    con.close()
    before = _held()
    if not row:
        return {"creature": "Pruner", "note": None, "notes": before[0], "chars": before[1]}
    drop = not on_world(f"{row['title']} {row['content'][:600]}") or _ask(  # names nothing from its world: dropped without asking the model
        f"You keep the memory of {who}. Persona: {p['persona'][:300]}\nDoes this note help {who} answer as themself, about their own world? Answer KEEP or DROP.", f"{row['title']}: {row['content'][:600]}", 4).strip().upper().startswith("DROP")
    con = db.connect()
    with con:
        if drop:
            con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'sheet')", (f"Pruned: {row['title']}"[:120], row["content"]))
            con.execute("DELETE FROM char_memories WHERE id = ?", (row["id"],))
        else:
            con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'sheet')", (f"Kept: {row['id']}", row["title"]))
    con.close()
    after = _held()
    return {"creature": "Pruner", "note": {"id": str(row["id"]), "title": row["title"], "chars": len(row["content"])}, "dropped": drop,
            "notes": after[0], "chars": after[1], "before": {"notes": before[0], "chars": before[1]}, "graph": graph()}


def _rules_from() -> int:
    """Your rules made before the current /char character are the last character's: kept for the Dot page, not shown or run here."""
    init_db()
    con = db.connect()
    row = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Resting: char %' ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    return int(row["content"]) if row and row["content"].isdigit() else 0


def mine() -> list[dict[str, Any]]:
    """The rules that belong to the current /char character."""
    start = _rules_from()
    return [v for v in space.variables() if v["kind"] != "persona" and v["id"] > start]


def _since(on_char: bool, who: str) -> int:
    """Where this character's own resting starts: a new character does not inherit the last one's questions and notes."""
    # shortcut: the two pages share one notes table, so notes the other page makes after this point still count; give notes an owner column if that bites
    init_db()
    page = f"Resting: {'char' if on_char else 'space'} "
    title = page + who
    con = db.connect()
    row = con.execute("SELECT id, title FROM char_memories WHERE source = 'sheet' AND title LIKE ? ORDER BY id DESC LIMIT 1", (page + "%",)).fetchone()
    con.close()
    if row and (on_char or row["title"] == title):  # on /char only become_persona and verse.enter mark a start: a new marker mid-life would orphan every row before it
        return row["id"]
    new = add_memory(title, "", source="sheet")["id"]
    return new if row else 0  # the first character to rest on a page keeps what is already there


def _open_questions(since: int = 0) -> list[str]:
    """Questions Dot asked itself while asleep that no reflection has answered yet, oldest first."""
    init_db()
    con = db.connect()
    qs = [re.sub(r" \(from \d+\)$", "", r["content"]) for r in con.execute("SELECT content FROM char_memories WHERE source = 'question' AND id > ? ORDER BY id", (since,))]
    done = {r["title"] for r in con.execute("SELECT title FROM char_memories WHERE id > ?", (since,))}
    con.close()
    return [q for q in qs if f"Reflection: {q}"[:80] not in done]


def speculations() -> list[dict[str, Any]]:
    """Its checked speculations, newest first: what it guessed, the question that checked it, how far off it was, and whether it held."""
    con = db.connect()
    rows = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Speculated: %' AND id > ? ORDER BY id DESC", (_start(),)).fetchall()
    con.close()
    return [json.loads(r["content"]) for r in rows]


def _speculated(q: str) -> str:
    """The guess a speculation made before it asked q, so the look-up scores the speculation itself."""
    con = db.connect()
    r = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Speculation: %' AND content LIKE ? AND id > ? ORDER BY id DESC LIMIT 1", (f'%"question": {json.dumps(q)}%', _start())).fetchone()
    con.close()
    return json.loads(r["content"]).get("guess", "") if r else ""


SPECULATE = re.compile(r"(?is)guess:\s*(.+?)\s*question:\s*(.+)")


def reflect(on_char: bool = False, topic: str | None = None) -> dict[str, Any]:
    """One look-up while asleep: the first topic not yet reflected on (or the one named), searched, noted, saved."""
    if on_char:
        who = get_profile()["name"]
    else:
        row = space._rows("SELECT name FROM space_vars WHERE kind = 'persona' ORDER BY id DESC LIMIT 1")
        who = row[0]["name"] if row else "Dot"
    pre = "" if who.lower() == "dot" else who + " "
    names = ([v["name"] for v in mine()] + [c["name"] for c in get_questions()] if on_char  # its own rules and creatures, not the last one's
             else [v["name"] for v in space.variables() if v["kind"] != "persona"] + [j["name"] for j in jobs.list_jobs()["jobs"]])
    papers = [r["title"] for r in space._rows("SELECT title FROM papers ORDER BY last_opened IS NULL, last_opened DESC, created_at DESC LIMIT 2")]
    topics: list[str] = []
    # curiosity: open questions first, then its world, then the names its notes keep mentioning that it has not read about yet
    frontier = [x["name"] for x in sorted(graph()["nodes"], key=lambda x: -x["n"]) if not x["known"] and x["kind"] == "concrete"] if on_char else []  # ideas are asked about, not searched bare
    since = _since(on_char, who)
    start0 = _start()  # the live persona when this step began
    for t in [topic] if topic else _open_questions(since) + ([f"{who} world and setting"] if pre else []) + frontier[:3] + [pre + n for n in names] + ([] if on_char else papers):  # a character studies its world, not your library
        if t.strip() and t.lower() not in [x.lower() for x in topics]:
            topics.append(t)
    init_db()
    con = db.connect()
    done = {r["title"] for r in con.execute("SELECT title FROM char_memories WHERE id > ?", (since,))}
    con.close()
    todo = [t for t in topics if f"Reflection: {t}"[:80] not in done]
    if not todo:
        return {"done": True, "topic": "", "note": "", "left": 0}
    topic = todo[0]
    # curiosity as guess and correction: it commits to an answer before looking, and the gap between guess and find is the surprise
    guess = _speculated(topic) if on_char else ""
    if on_char and topic.endswith("?") and not guess:  # the guess sees its world and its nearest notes, so a miss is a real gap, not a blank mind (lower surprise is better: target SURPRISE_TARGET)
        known = "\n".join(f"- {r['title'].removeprefix('Reflection: ')}: {_clean(r['content'], 220)}" for r in recall(topic, 3)[0])
        guess = _clean(_ask("Answer in one short sentence from what you already know about your world. Use its own names and terms. If unsure, guess.",
                            f"Your world:\n{get_profile()['persona'][:600]}\nWhat you have read so far:\n{known or '- (nothing yet)'}\nQuestion: {topic}", 40), 200)
    try:
        # a small model's own question is often vague: searching it with the character's name keeps it on the subject
        ask = f"{who} {topic}" if pre and (topic.endswith("?") or topic in frontier) and who.lower() not in topic.lower() else topic
        found = websearch.search(settings.get_all(), ask)["results"][:4]
    except Exception:
        found = []
    lines = [f"- {r.get('title') or ''}: {r.get('snippet') or ''}" for r in found if r.get("title") or r.get("snippet")]
    if not lines:  # a marker, so one unanswerable topic does not block the rest
        add_memory(f"Reflection: {topic}"[:80], "(nothing found)", source="sheet")
        return {"done": False, "topic": topic, "note": "", "left": len(todo) - 1}
    msgs = [{"role": "system", "content": f"You are {who}, resting. In two short sentences, note what is worth remembering about the topic from these snippets. Plain text, no lists." + _fix("reflect")},
            {"role": "user", "content": f"Topic: {topic}\n\n" + "\n".join(lines)}]
    try:
        note = jobs.complete(settings.get_all(), msgs, max_tokens=120).strip()
    except Exception:
        note = ""
    _log("reflection", msgs, note or "(no reply)")
    note = (note or " ".join(lines[:2])[:300])[:400]
    if on_char and _start() != start0:  # the persona changed while this step waited on the model: its find belongs to no one here
        _engine("reflect", "skipped", f"{topic}: dropped, the persona changed while it was being written")
        return {"done": False, "topic": topic, "note": "", "left": len(todo) - 1, "stale": True}
    saved = add_memory(f"Reflection: {topic}"[:80], note, source="reflection")
    # grounding, for the Verifier: the share of the note's names that its sources also say. A name from nowhere is the model making it up.
    named = set(re.findall(r"(?<=[a-z,;] )[A-Z][a-z]{2,}", note))  # capitals inside a sentence, so not its first word
    add_memory(f"Ground: {saved['id']}", f"{sum(n in ' '.join(lines) for n in named) / len(named) if named else 1:.2f}", source="sheet")
    add_memory(f"Sources: {saved['id']}", json.dumps([{"title": r.get("title") or "", "url": r.get("url") or "", "snippet": r.get("snippet") or ""} for r in found]), source="sheet")  # what the note was written from, so it can be checked
    out = {"done": False, "topic": topic, "note": note, "left": len(todo) - 1}
    if on_char:
        out["admitted"] = _intake(saved["id"], who, topic, note, lines)
    if guess and on_char and out.get("admitted") is False:  # the find was turned away (off-world or unsupported): there is nothing to hold the guess against, so it is not scored
        out["unscored"] = guess
    elif guess:
        sur = _surprise(guess, note)
        add_memory(f"Guess: {saved['id']}", f"{sur:.2f}|{guess}", source="sheet")
        out |= {"guess": guess, "surprise": sur}
        if on_char and guess == _speculated(topic):  # a speculation checked: kept if what it found backs it, filtered out if not
            out["held"] = sur < SPECULATION_KEEP
            add_memory(f"Speculated: {saved['id']}", json.dumps({"question": topic, "guess": guess, "surprise": sur, "held": out["held"]}), source="sheet")
    return out


def _intake(i: int, who: str, topic: str, note: str, lines: list[str]) -> bool | None:
    """The intake gate: a new note is judged before it counts as knowledge. A rejected note becomes a sheet row, out of its memory, and its topic is not retried.
    Returns admitted, or None when the model gave no decision (the note waits for the Verifier's later check)."""
    con = db.connect()
    ground = float((con.execute("SELECT content FROM char_memories WHERE title = ? ORDER BY id DESC LIMIT 1", (f"Ground: {i}",)).fetchone() or {"content": "1"})["content"])
    con.close()
    anchors = {w.lower() for w in re.findall(r"[\w-]{4,}", who) if w.lower() not in {"from", "with", "the"}} | {n["name"].lower() for n in graph()["nodes"]}
    if ground < 0.5:  # exact, no model: half its names are in no source
        ok, why = False, "names things its sources do not say"
    elif anchors and not any(a in f"{topic} {note}".lower() for a in anchors):  # exact, no model: a small judge passed notes that only matched their own topic
        ok, why = False, f"not about {who}'s world: it mentions nothing {who} knows"
    else:
        out = _ask(f"You decide what enters {who}'s memory. Admit the note only if the snippets support it, it answers the topic, and it is about {who}'s own world, "
                   f"not a fan mod, another game or work, or something else with a similar name. Reply ADMIT or REJECT, then a reason of at most twelve words.",
                   f"Topic: {topic}\nSnippets:\n" + "\n".join(lines)[:1500] + f"\nNote: {note}", 30).strip()
        if not out:
            _engine("evaluate", "failed", f"{topic}: {_failed or 'no decision'}; left for the Verifier")
            return None
        ok = not out.upper().lstrip(" *\"'").startswith("REJECT")
        why = re.sub(r"^[\W_]*(admit|reject)\w*[\W_]*", "", out, flags=re.I)[:160] or ("admitted" if ok else "rejected")
    add_memory(f"Gate: {i}", f"{'admit' if ok else 'reject'}|{why}", source="sheet")
    add_memory(f"Checked: {i}", "keep" if ok else "drop", source="sheet")  # the Verifier's later check skips a note the gate already judged
    if not ok:
        con = db.connect()
        with con:
            con.execute("UPDATE char_memories SET source = 'sheet', content = '(rejected) ' || content WHERE id = ?", (i,))
        con.close()
    _engine("evaluate", "ok", f"{topic}: {'admitted' if ok else 'rejected'}: {why}")
    return ok


SURPRISE_TARGET = 0.1  # the share of a guess the search does not back; lower is better
SPECULATION_KEEP = 0.3  # a speculation whose surprise is under this held up and is kept; the same line training calls "came out right"


def _surprise(guess: str, found: str) -> float:
    """How wrong the guess was, 0 to 1: the share of the guess's own words that what it found does not say."""
    # shortcut: word overlap, not meaning, so a right guess in other words scores as a surprise; ask the model to judge if this misleads
    words = lambda t: set(re.findall(r"[a-z']{4,}", t.lower()))
    g = words(guess)
    return round(1 - len(g & words(found)) / len(g), 2) if g else 1.0


ABOUT_SELF = re.compile(r"(?i)\b(?:know|learn\w*|wrong|mistak\w*|sure|unsure|yourself|studied|read about|curious)\b")


def self_model(text: str | None = None) -> dict[str, Any]:
    """What the character can say about itself as a learner, read from its own record, no model: what it has read about,
    what it guessed wrong, what it has not found out. With a message, `prompt` is the part of it worth telling the model for that reply."""
    start = _start()
    con = db.connect()
    rows = con.execute("SELECT g.content AS g, n.title AS t, n.source AS src FROM char_memories g JOIN char_memories n ON n.id = CAST(substr(g.title, 8) AS INTEGER) "
                       "WHERE g.source = 'sheet' AND g.title LIKE 'Guess: %' AND g.id > ? ORDER BY g.id DESC LIMIT 12", (start,)).fetchall()
    dropped = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source = 'sheet' AND title LIKE 'Checked: %' AND content = 'drop' AND id > ?", (start,)).fetchone()["c"]
    con.close()
    wrong = [{"q": r["t"].removeprefix("Reflection: "), "guess": r["g"].split("|", 1)[1], "surprise": float(r["g"].split("|")[0])} for r in rows if float(r["g"].split("|")[0]) >= 0.6 and r["src"] == "reflection"][:3]  # shortcut: the score is word overlap, so only a clear miss counts
    knows = [n["name"] for n in sorted(graph()["nodes"], key=lambda n: -n["n"]) if n["known"]][:6]
    unsure = _open_questions(start)[:3]
    out = {"knows": knows, "wrong": wrong, "unsure": unsure, "dropped": dropped, "prompt": ""}
    if text is not None and (knows or wrong or unsure):
        words = set(re.findall(r"[a-z']{4,}", text.lower()))
        near = lambda t: ABOUT_SELF.search(text) or words & set(re.findall(r"[a-z']{4,}", t.lower()))  # only what this message touches, so it does not recite itself
        lines = ([f"You have read about: {', '.join(knows)}."] if knows and ABOUT_SELF.search(text) else []) \
            + [f"You once guessed \"{w['guess']}\" for \"{w['q']}\" before looking it up, and what you found was different; your notes hold what you found." for w in wrong if near(w["q"])][:2] \
            + [f"You have not found out yet: {q}" for q in unsure if near(q)][:2]
        if lines:
            out["prompt"] = "What you know about your own learning (say it plainly if asked, never invent beyond it):\n" + "\n".join(lines)
    return out


EXPLORES = ("reflect", "wonder", "speculate", "ask", "plan", "goal", "fold")  # the steps that reach outward: the ones the brake holds
LAYERS = ("plan", "question", "note", "name")  # the mesh layers the frontier walks, top to bottom
BAKE_EVERY = 4  # answers between two consolidations


def frontier() -> dict[str, Any]:
    """How much of the mesh still points nowhere. Per layer n (plan, question, note) paired with the next layer: open(n) = nodes with no edge down to
    a node of layer n+1, c(n) = open(n) / (open(n) + count(n+1)); a pair with both 0 is skipped. F = mean of the kept c(n), 0 if none.
    D = index of the deepest non-empty layer (plan 1 ... name 4, 0 if empty). term = D * F: the open work pulls, so answering it brings curiosity down.
    (It was D * (1 - F) before: that rose as questions were answered, so learning kept curiosity up and it could never settle.)"""
    m = mesh()
    layer = {n["id"]: n["layer"] for n in m["nodes"]}
    count = {k: sum(v == k for v in layer.values()) for k in LAYERS}
    down = lambda a, b: layer[a] in LAYERS[:3] and layer[b] == LAYERS[LAYERS.index(layer[a]) + 1]
    linked = {a for a, b in m["edges"] if down(a, b)}
    cs = {}
    for n, nxt in zip(LAYERS, LAYERS[1:]):
        o = sum(v == n and i not in linked for i, v in layer.items())
        if o or count[nxt]:
            cs[n] = o / (o + count[nxt])
    F = sum(cs.values()) / len(cs) if cs else 0.0
    D = max((i + 1 for i, k in enumerate(LAYERS) if count[k]), default=0)
    return {"F": round(F, 4), "D": D, "layers": {k: round(c, 4) for k, c in cs.items()}, "term": round(D * F, 4)}


def dial() -> float:
    """Your hand on curiosity, for the live persona: 0 stops it reaching out, 1 is the formula as it is, up to 3 triples it."""
    con = db.connect()
    r = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Dial: curiosity' AND id > ? ORDER BY id DESC LIMIT 1", (_start(),)).fetchone()
    con.close()
    try:
        return float(r["content"]) if r else 1.0
    except ValueError:
        return 1.0


def set_dial(v: float) -> float:
    v = round(max(0.0, min(3.0, float(v))), 2)
    _since(True, get_profile()["name"])
    add_memory("Dial: curiosity", f"{v}", source="sheet")
    return v


UP = re.compile(r"(?i)\b(?:learn(?: up)? (?:some )?more|more curious|be curious|dig deeper|go explore|explore more|keep learning|look (?:it )?up more|curiosity up)\b|^\W*up+\W*$")  # a bare "up" counts only said alone: "looked up" in a sentence is not one  # shortcut: phrases, not a model call per message; swap for a classifier if it misses how you talk
UPS_PER_STEP = 10  # this many ups add 1 to momentum
TRACKER_SAID = re.compile(r"\s*\(Up\)|\s*\(?(?:Up \d+ of \d+\.|That makes \d+ ups[^)]*\.)\)?|\s*My curiosity just reached its threshold[^?]*\?[^.]*\.")  # lines the tracker wrote: the model never sees them, or it copies them forever


def _var(name: str, default: float) -> float:
    con = db.connect()
    r = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = ? AND id > ? ORDER BY id DESC LIMIT 1", (f"Var: {name}", _start())).fetchone()
    con.close()
    try:
        return float(r["content"]) if r else default
    except ValueError:
        return default


def _set_var(name: str, v: float) -> float:
    _since(True, get_profile()["name"])
    add_memory(f"Var: {name}", f"{v}", source="sheet")
    return v


def tracker() -> dict[str, Any]:
    """Your ups, said in plain words, and the momentum they add to curiosity: the third term, on top of the formula and your dial."""
    q = _open_correction()
    return {"ups": int(_var("ups", 0)), "every": UPS_PER_STEP, "momentum": round(_var("momentum", 0), 2), "sleep_at": _var("sleep_at", 3), "max": _var("max", 3),
            "asking": bool(q and q.get("kind") == "direction"), "asleep": _var("asleep", 0) == 1}


def set_tracker(sleep_at: float | None = None, top: float | None = None) -> dict[str, Any]:
    if top is not None:
        _set_var("max", round(max(0.5, min(50.0, float(top))), 2))
    if sleep_at is not None:
        _set_var("sleep_at", round(max(0.5, min(_var("max", 3), float(sleep_at))), 2))  # it cannot sleep above the ceiling, or it would never sleep
    return tracker()


def _up(text: str) -> str:
    """You said up: count it, and every UPS_PER_STEP ups push momentum up by 1. At the sleep threshold it sleeps and asks which way to grow. Returns what it says back."""
    if not UP.search(text):
        return ""
    t = tracker()
    ups = _set_var("ups", t["ups"] + 1)
    if ups % UPS_PER_STEP:
        _engine("tracker", "ok", f"up {int(ups) % UPS_PER_STEP}/{UPS_PER_STEP}")
        return f"(Up {int(ups) % UPS_PER_STEP} of {UPS_PER_STEP}.)"
    m = _set_var("momentum", min(t["max"], t["momentum"] + 1))
    _engine("tracker", "ok", f"{UPS_PER_STEP} ups: momentum {t['momentum']} → {m}")
    if m >= t["sleep_at"] and not (t["asking"] or t["asleep"]):
        _engine("tracker", "ok", f"momentum {m} reached {t['sleep_at']}: asleep, asking which way to grow")
        return "SLEEP"
    return f"(That makes {UPS_PER_STEP} ups: my curiosity is up by 1, momentum {m}.)"


WAKE_BELOW = 0.5


def _direction() -> str:
    """The way you told it to grow, the last time it asked."""
    con = db.connect()
    r = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Var: direction' AND id > ? ORDER BY id DESC LIMIT 1", (_start(),)).fetchone()
    con.close()
    return r["content"] if r else ""


MOMENTUM_EASE = 0.9  # each step that did something keeps this share of momentum


def _ease_momentum() -> None:
    """Learning matures it: every step that did something takes a tenth off momentum, so the push you gave is optimised away.
    Asleep, it is learning in the direction you gave; when the push is spent it wakes and tells you."""
    if (m := _var("momentum", 0)) <= 0.05:
        return
    m = _set_var("momentum", round(m * MOMENTUM_EASE, 2))
    if _var("asleep", 0) == 1 and m < WAKE_BELOW:
        _set_var("momentum", 0)
        _set_var("asleep", 0)
        way = _direction()
        _engine("tracker", "ok", "awake: the push is spent")
        con = db.connect()
        with con:
            con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', ?)", (f"I am awake. I went learning{f' toward “{way[:120]}”' if way else ''}, and my curiosity is back down to its floor.",))
        con.close()


def compression(g: dict[str, Any] | None = None) -> dict[str, float]:
    """Reddin's S_comp over its ideas: mentions per folded idea, less the spread (entropy) between them. High is a settled routine;
    a drop means new ideas arrive faster than they fold together, a new chapter (Schmidhuber: what counts is the change, not the level)."""
    ns = [n["n"] for n in (g or graph())["nodes"] if n["kind"] == "abstract" and n["n"]]
    if not ns:
        return {"S": 0.0, "K": 0, "H": 0.0}
    tot = sum(ns)
    H = -sum(x / tot * math.log2(x / tot) for x in ns)
    return {"S": round(tot / (len(ns) + H), 4), "K": len(ns), "H": round(H, 4)}


PHASE_W = 1.0  # weight of the new-chapter term in curiosity


def disposition() -> dict[str, Any]:
    """The two variables every character starts with, read from its graph and never set by hand (the Riddiary formula, as kept in ghost's memory harness):
        tau       = unmet / x     per name: the share of its questions (its lenses, the quota x) still unanswered; here the mean over names
        maturity  = 1 - exp(-nAE / nE)   answers per name, from counts frozen at the last consolidation ("baked"), not the live graph
        curiosity = dial * (tau * dnE * exp(-nAE / nE) + D * F) + momentum   dnE: names met since that consolidation; D, F: see frontier()
    Curiosity is the brake: at 0 the character stops reaching outward. It reaches 0 when no new names wait and nothing in its mesh is left open.
    New names, and new open questions (its own speculations included), raise it again."""
    start = _start()
    con = db.connect()
    done = {r["title"] for r in con.execute("SELECT title FROM char_memories WHERE source IN ('reflection', 'sheet') AND title LIKE 'Reflection: %' AND id > ?", (start,))}
    bake = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Baked' AND id > ? ORDER BY id DESC LIMIT 1", (start,)).fetchone()
    sur = [float(r["content"].split("|")[0]) for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Guess: %' AND id > ? ORDER BY id DESC LIMIT 5", (start,)) if r["content"].split("|")[0]]
    con.close()
    g = graph()
    who, names = get_profile()["name"], [n for n in g["nodes"] if n["kind"] == "concrete"]
    met = [sum((i == 0 and n["known"]) or f"Reflection: {lens.format(name=n['name'], who=who)}"[:80] in done for i, lens in enumerate(LENSES)) for n in names]
    nE, nAE, x = len(names), sum(met), len(LENSES)
    baked = json.loads(bake["content"]) if bake else {"nE": 0, "nAE": 0}
    tau = sum((x - m) / x for m in met) / nE if nE else 1.0
    damper = math.exp(-baked["nAE"] / baked["nE"]) if baked["nE"] else 1.0
    dnE = max(0, nE - baked["nE"])
    fr = frontier()
    k = dial()
    mo = _var("momentum", 0)
    sp, comp = speculations(), compression(g)
    phase = round(max(0.0, baked["S"] - comp["S"]) / baked["S"], 4) if baked.get("S") else 0.0  # how far compression fell since the last consolidation
    know, miss = 1 - math.exp(-nAE / nE) if nE else 0.0, sum(sur) / len(sur) if sur else 0.5  # no guess checked yet: as likely right as wrong
    return {"curiosity": round(k * (tau * dnE * damper + fr["term"] + PHASE_W * phase) + mo, 2), "compression": {**comp, "baked": baked.get("S"), "phase": phase}, "dial": k, "momentum": mo, "frontier": fr, "maturity": round(1 - damper, 2), "tau": round(tau, 2), "dnE": dnE, "nE": nE, "nAE": nAE, "baked": baked,
            "terms": {"names": round(tau * dnE * damper, 3), "damper": round(damper, 3), "frontier": fr["term"], "phase": round(PHASE_W * phase, 4)},  # the formula's parts, so the page can show which one holds curiosity up
            "optim": {"ease": MOMENTUM_EASE, "bake_every": BAKE_EVERY, "since_bake": max(0, nAE - baked["nAE"]), "keep": SPECULATION_KEEP, "target": SURPRISE_TARGET,
                      "speculated": len(sp), "held": sum(bool(x.get("held")) for x in sp), "last_surprise": sp[0]["surprise"] if sp else None},
            "score": {"J": round(know * (1 - miss), 3), "know": round(know, 3), "surprise": round(miss, 3)}}  # the one number to push up: how much it has answered, times how often its guesses come out right


def _tick(what: str) -> None:
    """One row per thing it does, so the page can draw how each variable moved and how many cycles it took."""
    d = disposition()
    add_memory("Tick", json.dumps({"at": time.strftime("%H:%M:%S"), "what": what, "curiosity": d["curiosity"], "maturity": d["maturity"], "frontier": d["frontier"]["term"], "score": d["score"]["J"], "names": d["nE"], "answers": d["nAE"],
                                   **{f"var:{v['name']}": v["value"] for v in mine()}}), source="sheet")


def _deltas(last: int = 200) -> dict[str, list[float]]:
    """Each kind of step's changes to J, oldest first, from consecutive ticks."""
    con = db.connect()
    ticks = [json.loads(r["content"]) for r in con.execute("SELECT content FROM (SELECT id, content FROM char_memories WHERE source = 'sheet' AND title = 'Tick' AND id > ? ORDER BY id DESC LIMIT ?) ORDER BY id", (_start(), last))]
    con.close()
    by: dict[str, list[float]] = {}
    for a, b in zip(ticks, ticks[1:]):
        if "score" in a and "score" in b:  # ticks written before the score existed carry none
            by.setdefault(b["what"], []).append(b["score"] - a["score"])
    return by


def gains(last: int = 200) -> dict[str, dict[str, float]]:
    """What each kind of step did to the score J, from the ticks: the mean change it made and how often it ran. The planner reads this to pick what pays."""
    by = _deltas(last)
    return {k: {"gain": round(sum(v) / len(v), 4), "runs": len(v)} for k, v in sorted(by.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))}


DISCOUNT = 0.9  # discounted Thompson sampling: each later run of the same step weighs old evidence down by this much, so a step that stopped paying is tried less
STILL = 0.25  # a step that left J where it was counts as a quarter of a miss: it cost a turn


def arms(last: int = 200) -> dict[str, tuple[float, float]]:
    """A Beta(a, b) per kind of step over 'it raised J', newest evidence weighted most. Untried steps sit at Beta(1, 1), so they still get picked."""
    out = {}
    for k, ds in _deltas(last).items():
        a = b = 1.0
        for i, x in enumerate(reversed(ds)):
            w = DISCOUNT ** i
            a, b = (a + w, b) if x > 1e-4 else (a, b + w) if x < -1e-4 else (a, b + STILL * w)
        out[k] = (round(a, 3), round(b, 3))
    return out


def judge_trust() -> dict[str, float]:
    """How often the judge model agreed with an exact check it was shown blind (Noisy but Valid: estimate the judge from items whose answer is known).
    A Beta mean, newest first and discounted; starts at a half."""
    con = db.connect()
    rows = [r["content"] for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Judge' AND id > ? ORDER BY id DESC LIMIT 50", (_start(),))]
    con.close()
    a = 1 + sum(DISCOUNT ** i for i, r in enumerate(rows) if r == "1")
    b = 1 + sum(DISCOUNT ** i for i, r in enumerate(rows) if r != "1")
    return {"value": round(a / (a + b), 3), "probes": len(rows)}


EXPLORE = ("speculate", "wonder", "goal", "ask", "extract", "ideas", "plan", "want")  # System 1: reach for the new
CHECK = ("reflect", "check", "fold")  # System 2: answer, verify, compress what it has
TAU0 = 0.5  # softmax temperature at maturity 0; it cools as maturity rises, so it explores early and checks later
REST_AT = 0.05  # driving force under this: nothing pulls it, it rests (Reddin's deterministic silence)


def drive(d: dict[str, Any] | None = None) -> dict[str, Any]:
    """The two drives and who wins (the virtual-clone softmax): explore E from curiosity, check C from open questions times
    how wrong its guesses run or how little the judge can be trusted, whichever is worse."""
    d = d or disposition()
    u, jt = len(_open_questions(_start())), judge_trust()
    E = d["curiosity"] / (1 + d["curiosity"])
    C = u / (u + 1) * max(d["score"]["surprise"], 1 - jt["value"])
    tau = round(max(0.05, TAU0 * (1 - d["maturity"])), 3)
    p = 1 / (1 + math.exp(-(E - C) / tau))
    df = p * E + (1 - p) * C
    return {"E": round(E, 3), "C": round(C, 3), "tau": tau, "p_explore": round(p, 3), "DF": round(df, 3), "rest": df < REST_AT, "open": u, "judge": jt}


def thompson(kinds: list[str]) -> str:
    """The step to take from these, by one draw from each one's Beta: mostly the one that has paid, now and then a long shot."""
    A = arms()
    return max(kinds, key=lambda k: random.betavariate(*A.get(k, (1.0, 1.0)))) if kinds else ""


def monitor() -> dict[str, Any]:
    """What to watch to see it become a character: each variable over its steps, what the last reply leaned on, and how the correction loop is going."""
    start = _start()
    con = db.connect()
    ticks = [json.loads(r["content"]) for r in con.execute("SELECT content FROM (SELECT id, content FROM char_memories WHERE source = 'sheet' AND title = 'Tick' AND id > ? ORDER BY id DESC LIMIT 160) ORDER BY id", (start,))]
    last = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Reply' AND id > ? ORDER BY id DESC LIMIT 1", (start,)).fetchone()
    cycles = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source = 'sheet' AND title LIKE 'Answered: %' AND id > ?", (start,)).fetchone()["c"]
    steps = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source = 'sheet' AND title = 'Tick' AND id > ?", (start,)).fetchone()["c"]
    con.close()
    keys = ["curiosity", "maturity", "frontier", "score", *dict.fromkeys(k for t in ticks for k in t if k.startswith("var:"))]
    rv, d = review(), disposition()
    return {"disposition": d, "gains": gains(), "steps": steps, "series": [{"name": k.removeprefix("var:"), "yours": k.startswith("var:"), "points": [t[k] for t in ticks if k in t]} for k in keys],
            "last": json.loads(last["content"]) if last else None,
            "loop": {"reviewed": rv["reviewed"], "mistakes": rv["mistakes"], "cycles": cycles, "instructions": len(rv["instructions"]), "fixes": sum(c["state"] == "on" for c in corrections())}}


MODES = ("sleeping", "quiet", "curious", "proactive", "planner")  # sleeping: no model calls at all, not even replies (swap models, test); quiet: never learns by itself; curious: learns while idle; proactive: also tells you what it found; planner: idle time runs harness cycles


def mode() -> str:
    con = db.connect()
    row = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Mode' AND id > ? ORDER BY id DESC LIMIT 1", (_start(),)).fetchone()  # this persona's mode only
    con.close()
    return row["content"] if row and row["content"] in MODES else "curious"


def set_mode(m: str) -> None:
    if m not in MODES:
        raise ValueError("no such mode")
    _since(True, get_profile()["name"])  # mark where this persona starts first, so its switch is read as its own
    add_memory("Mode", m, source="sheet")


def wiring() -> dict[str, Any]:
    """The whole machine on one screen: the signals, the three systems, the wires your rules make between them, and the three memory layers."""
    out, start, rules = systems(), _start(), mine()
    con = db.connect()
    dsp = disposition()
    signals = [{"name": "curiosity", "value": dsp["curiosity"], "max": max(3.0, dsp["curiosity"]), "kind": "built in"}, {"name": "maturity", "value": dsp["maturity"], "max": 1, "kind": "built in"}]
    guesses = [r["content"].split("|", 1) for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Guess: %' AND id > ? ORDER BY id DESC LIMIT 5", (start,))]
    links = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source = 'reflection' AND title LIKE 'Reflection: How are % connected?' AND id > ?", (start,)).fetchone()["c"]
    last = con.execute("SELECT title FROM char_memories WHERE source = 'reflection' AND title LIKE 'Reflection: How are % connected?' AND id > ? ORDER BY id DESC LIMIT 1", (start,)).fetchone()
    con.close()
    cur = dsp["curiosity"]
    if guesses:
        signals.append({"name": "surprise", "value": round(sum(float(g[0]) for g in guesses) / len(guesses), 2), "max": 1, "kind": "measured"})
    signals += [{"name": v["name"], "value": v["value"], "max": max(v["value"], v.get("at") or 0, 1), "kind": "yours"} for v in rules]
    wires = [{"from": "curiosity", "to": -1, "on": False, "when": "at 0, reaching out stops", "holding": dsp["nE"] > 0 and cur <= 0}]
    for v in rules:
        for say, when, holding in ((v.get("low_say"), f"{v['at']:g} or less", v["value"] <= v["at"]), (v.get("high_say"), f"above {v['at']:g}", v["value"] > v["at"])) if v.get("at") is not None else ():
            if say and (m := space.GATE.match(say)):
                wires.append({"from": v["name"], "to": int(m.group(1)), "on": m.group(2) == "on", "when": when, "holding": holding})
    notes, _ = _held()
    g = graph()
    todo = _open_questions(start)
    return {**out, "who": get_profile()["name"], "mode": mode(), "tracker": tracker(), "signals": signals, "wires": wires, "next": todo[0] if todo else "", "open": len(todo),
            "last_guess": {"surprise": float(guesses[0][0]), "guess": guesses[0][1]} if guesses else None, "corrections": corrections(), "decision": dict(DECISION), "self": self_model(), "trace": list(TRACE)[::-1][:1], "review": review(),
            "memory": [{"id": 2, "name": "Links", "holds": f"{links} found" + (f" · {last['title'][20:-11]}" if last else "")},
                       {"id": 1, "name": "Notes", "holds": f"{notes} notes · {len(g['nodes'])} names"},
                       {"id": 0, "name": "Raw chat", "holds": f"{len(_chat_since())} turns"}]}


def wire(text: str) -> dict[str, Any]:
    """A wire is a rule sentence read exactly, never by the model: "when focus = 0, turn S2 off"."""
    held = space.steady(text)
    if not any(space.GATE.match(v.get(k) or "") for v, _ in held for k in ("low_say", "high_say")):
        raise ValueError("That sentence does not switch a system. Try: when focus is above 3, turn S2 off")
    for v, start in held:
        space._settle(v, start)
    return wiring()


PROMPTS: deque[dict[str, Any]] = deque(maxlen=40)  # shortcut: the prompt log lives in memory and a restart clears it; store it in the db if you need it kept


# Learning runs as three systems, so you can see which layer did what:
# S2 thinks (writes a plan), S1 turns the plan and the names it knows into goals (questions, its own sheet), S0 just executes (search, note, names, voice).
SYSTEMS: dict[int, tuple[str, str, tuple[str, ...]]] = {
    2: ("Plan", "Thinks about what the character should learn next and writes a short plan, and consolidates what it has answered so far, and writes its study journal.", ("plan", "bake", "journal")),
    1: ("Goals", "Turns the plan and the names it knows into questions to answer, and fills in its own sheet.", ("goal", "ask", "wonder", "speculate", "fill", "want")),
    0: ("Execute", "Just does the work: looks a question up, writes the note, pulls out names and ideas from notes and from your chat, practises its voice.", ("reflect", "extract", "ideas", "practise", "sort", "fold")),
    3: ("Verify", "Watches the other three: picks the next step from everything that could run, checks each new note, and proposes a prompt fix when a system keeps slipping.", ("check", "review", "tune")),
}
# what the Verifier offers when a step keeps failing the same way: written here, not by the model, so every fix is one you can read before you approve it
CORRECTIONS = {"wonder": "Write exactly one question. Do not list the question words.",
               "goal": "Write exactly one question. Do not list the question words.",
               "plan": "Reply with topic names only, like three headings.",
               "reflect": "Use only what the snippets say about the topic. If they are about something else, write: nothing found.",
               "planner": "Reply with commands only, one per line, like: check 12"}
DECISION: dict[str, Any] = {}  # the Verifier's last choice, for the wiring screen


def _fail(kind: str) -> None:
    """A step slipped. Two slips of one kind and the Verifier proposes its correction; nothing changes until you approve it."""
    add_memory(f"Fail: {kind}", "", source="sheet")
    con = db.connect()
    n = con.execute("SELECT COUNT(*) AS c FROM char_memories WHERE source = 'sheet' AND title = ?", (f"Fail: {kind}",)).fetchone()["c"]
    has = con.execute("SELECT 1 FROM char_memories WHERE source = 'sheet' AND title = ?", (f"Correction: {kind}",)).fetchone()
    con.close()
    if n >= 2 and not has and kind in CORRECTIONS:
        add_memory(f"Correction: {kind}", f"proposed|{CORRECTIONS[kind]}", source="sheet")


def corrections() -> list[dict[str, str]]:
    con = db.connect()
    rows = {r["title"].removeprefix("Correction: "): r["content"].split("|", 1) for r in con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Correction: %' ORDER BY id")}
    fails = {r["title"].removeprefix("Fail: "): r["c"] for r in con.execute("SELECT title, COUNT(*) AS c FROM char_memories WHERE source = 'sheet' AND title LIKE 'Fail: %' GROUP BY title")}
    con.close()
    return [{"kind": k, "state": v[0], "text": v[1], "fails": fails.get(k, 0)} for k, v in rows.items()]


def set_correction(kind: str, accept: bool) -> None:
    if kind not in CORRECTIONS:
        raise ValueError("no such correction")
    add_memory(f"Correction: {kind}", f"{'on' if accept else 'rejected'}|{CORRECTIONS[kind]}", source="sheet")


def _fix(kind: str) -> str:
    return next((" " + c["text"] for c in corrections() if c["kind"] == kind and c["state"] == "on"), "")


NOT_A_REPLY = ("I got curious:", "Earlier you asked", "Noted. From now on", "I can't reach the model", "A wish: ", "I'm too tired to take that on")  # lines the app wrote, not replies to judge
OUT_OF_CHARACTER = re.compile(r"(?i)\b(?:LFM\d*|Liquid AI|Liquid Foundation|language model|AI model|as an AI|I am an AI|AI assistant|trained by|(?:text|images?|audio) (?:as )?inputs?|inputs? and produce)\b")


def _open_correction() -> dict[str, Any] | None:
    """The one reply the character is waiting to be corrected on, if any."""
    con = db.connect()
    row = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Asking: %' AND id > ? ORDER BY id DESC LIMIT 1", (_start(),)).fetchone()
    con.close()
    return {"id": int(row["title"].removeprefix("Asking: ")), **json.loads(row["content"])} if row else None


def instructions() -> list[dict[str, Any]]:
    """What you told this character to do instead, newest first."""
    con = db.connect()
    rows = con.execute("SELECT id, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Instruction: %' AND id > ? ORDER BY id DESC", (_start(),)).fetchall()
    con.close()
    return [{"id": r["id"], "text": r["content"]} for r in rows]


def remove_instruction(note_id: int) -> bool:
    con = db.connect()
    with con:
        n = con.execute("DELETE FROM char_memories WHERE id = ? AND source = 'sheet' AND title LIKE 'Instruction: %'", (note_id,)).rowcount
    con.close()
    return n > 0


def answer_correction(text: str) -> dict[str, Any]:
    """Your answer to its open question becomes a standing instruction in every reply prompt, and the question closes."""
    q, text = _open_correction(), text.strip()
    if not q or not text:
        _engine("correction", "skipped", "empty answer" if q else "no correction question is open")
        raise ValueError("Say what it should do instead." if q else "No correction question is open.")
    saved = add_memory(f"Instruction: {text}"[:80], text[:300], source="sheet")
    _engine("correction", "ok", text[:80])
    if q.get("kind") == "direction":  # it has its direction: it sleeps to learn that way, and wakes when the push is spent
        _set_var("asleep", 1)
        add_memory("Var: direction", text[:300], source="sheet")
        p = get_profile()  # the direction becomes part of who it is: its persona, the first thing every reply prompt reads
        update_profile(p["name"], f"{p['persona'].rstrip()}\nHow you have grown, and how you speak now: {text.strip()[:300]}", p["look"], p["tint"])
    con = db.connect()
    with con:
        con.execute("UPDATE char_memories SET title = 'Answered: ' || substr(title, 9) WHERE source = 'sheet' AND title LIKE 'Asking: %' AND id > ?", (_start(),))
    con.close()
    return {"id": saved["id"], "text": text[:300]}


def skip_correction() -> bool:
    """You chose not to answer its question: it closes without becoming an instruction."""
    con = db.connect()
    with con:
        n = con.execute("UPDATE char_memories SET title = 'Skipped: ' || substr(title, 9) WHERE source = 'sheet' AND title LIKE 'Asking: %' AND id > ?", (_start(),)).rowcount
    con.close()
    _set_var("momentum", 0) if n else None
    _engine("correction", "skipped", "you skipped its question" if n else "no correction question is open")
    return n > 0


def review() -> dict[str, Any]:
    """The correction loop for the wiring screen: the open question, your standing instructions, and how many replies it has looked back at."""
    con = db.connect()
    seen = [r["content"] for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Reviewed: %' AND id > ?", (_start(),))]
    con.close()
    q = _open_correction()
    return {"open": {"kind": q.get("kind", "mistake"), **{k: q[k] for k in ("id", "asked", "said", "why")}} if q else None, "instructions": instructions(), "reviewed": len(seen), "mistakes": seen.count("mistake")}


JOURNAL_EVERY = 3  # new notes it needs before it writes another page


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _last_journal_id() -> int:
    con = db.connect()
    row = con.execute("SELECT MAX(id) AS m FROM char_memories WHERE source = 'sheet' AND title LIKE 'Journal: %' AND id > ?", (_start(),)).fetchone()
    con.close()
    return row["m"] or _start()


def _day_since(since: int) -> dict[str, Any]:
    """What happened since a journal page: the facts its next page is written from, nothing the model has to remember."""
    con = db.connect()
    notes = con.execute("SELECT id, title, content FROM char_memories WHERE source = 'reflection' AND id > ? ORDER BY id", (since,)).fetchall()
    guesses = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Guess: %' AND id > ? ORDER BY id", (since,)).fetchall()
    taught = [r["content"] for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Instruction: %' AND id > ? ORDER BY id", (since,))]
    con.close()
    by_id = {str(n["id"]): n["title"].removeprefix("Reflection: ") for n in notes}
    surprised = sorted(({"q": by_id.get(g["title"].removeprefix("Guess: "), ""), "guess": g["content"].split("|", 1)[1], "surprise": float(g["content"].split("|")[0])}
                        for g in guesses if "|" in g["content"]), key=lambda g: -g["surprise"])
    chats = sum(1 for t in _chat_since() if t["role"] == "user")
    known = [re.split(r"(?<=[.!?])\s", n["content"].strip(), maxsplit=1)[0][:220] for n in notes[-6:]]  # the first line of each newest note: what is true
    return {"studied": list(by_id.values()), "known": known, "surprised": [g for g in surprised if g["q"] and g["surprise"] >= 0.3], "taught": taught,
            "next": _open_questions(since)[:3], "chats": chats}


_END = r"(?=\s*(?:[.,!?;]|$|\band\b|\bwho\b|\bbut\b))"
ABOUT_YOU = (  # what you say about yourself, and how the persona is told it. shortcut: phrases, not a model call per message
    ("name", re.compile(r"(?i)\b(?:my name is|call me|i am called|i'm called)\s+([A-Za-z][\w'-]*(?: (?-i:[A-Z])[\w'-]*)?)"), "Their name is {}"),  # a surname only when capitalised: "Bibin and ..." is not one
    ("theirs", re.compile(rf"(?i)\b(?:i am|i'm|im)\s+your\s+([a-z][\w '-]{{1,40}}?){_END}"), "They are your {}"),
    ("mine", re.compile(rf"(?i)\byou(?:'re| are)\s+my\s+([a-z][\w '-]{{1,40}}?){_END}"), "You are their {}"),
    ("role", re.compile(rf"(?i)\b(?:i am|i'm|im)\s+an?\s+(?!bit\b|little\b|lot\b|kind\b|sort\b)([a-z][\w '-]{{1,40}}?){_END}"), "They are a {}"),
    ("work", re.compile(r"(?i)\bi ((?:work|study)\s(?:as|at|in|on)\s[^.,!?;]{2,50})"), "They {}"))


def you() -> dict[str, str]:
    """Who the person is to the live persona: what they said about themselves, newest word on each thing."""
    con = db.connect()
    rows = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'You: %' AND id > ? ORDER BY id", (_start(),)).fetchall()
    con.close()
    got = {r["title"].removeprefix("You: "): r["content"] for r in rows}
    return {k: got[k] for k in dict.fromkeys(["about", *(k for k, _, _ in ABOUT_YOU)]) if k in got}  # what you wrote first, then your name, then who you are to it


def set_you(about: str | None = None, forget: str | None = None) -> dict[str, str]:
    """What you write about yourself on the Story page (replacing the last), or forget one thing it learned about you."""
    con = db.connect()
    with con:
        if forget:
            con.execute("DELETE FROM char_memories WHERE source = 'sheet' AND title = ? AND id > ?", (f"You: {forget}", _start()))
        if about is not None:
            con.execute("DELETE FROM char_memories WHERE source = 'sheet' AND title = 'You: about' AND id > ?", (_start(),))
            if about.strip():
                con.execute("INSERT INTO char_memories (title, content, source) VALUES ('You: about', ?, 'sheet')", (about.strip()[:1500],))
    con.close()
    return you()


def learn_you(text: str) -> list[str]:
    """Keep what a message says about the person (name, who they are to it, their work); a new word on a thing replaces the old."""
    got = [(k, t.format(m.group(1).strip())) for k, rx, t in ABOUT_YOU if (m := rx.search(text))]
    if not got:
        return []
    con = db.connect()
    with con:
        for k, fact in got:
            con.execute("DELETE FROM char_memories WHERE source = 'sheet' AND title = ? AND id > ?", (f"You: {k}", _start()))
            con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'sheet')", (f"You: {k}", fact[:120]))
    con.close()
    return [f for _, f in got]


def _you_line() -> str:
    known, n, tr = you(), sum(1 for t in _chat_since() if t["role"] == "user"), trust()
    feel = (" You trust them: be warm and open, and say what you are unsure of." if tr["trusted"] else
            " You do not trust them much yet: be polite and a little guarded." if tr["n"] >= TRUST_AFTER and tr["value"] < LOW else "")
    if about := known.pop("about", ""):
        return f"The person you talk to, in their own words: {about}" + (f" Also: {'; '.join(known.values())}." if known else "") + f" You have talked {n} times.{feel}"
    if not known:
        return f"You do not know who the person you talk to is yet: they are not anyone from your world unless they tell you. You have talked {n} times.{feel}"
    return f"The person you talk to (they told you this): {'; '.join(known.values())}. You have talked {n} times.{feel}"


# ---------- its life between chats, the way Pino lives in his town: needs that drain and pick what it does next, mood shifts with a cause,
# wants it asks you for (each one grounded in something that went wrong), and what it keeps of what you say, which is how much it trusts you ----------
NEEDS = {"fullness": "new notes feed it; it gets hungry while nothing new comes in",
         "energy": "every model step spends a little; it comes back while it rests",
         "wonder": "questions to chase: making them raises it, answering them spends it",
         "joy": "guesses that come out right, and wants you give it",
         "calm": "mistakes and turned-away notes shake it; it settles with time"}
DRIFT = {"fullness": -0.02, "energy": 0.15, "wonder": 0.0, "joy": 0.0, "calm": 0.05}  # per ten minutes, while time passes
LOW, HIGH, TIRED = 0.3, 0.7, 0.2
LEADS = {"fullness": ("reflect", "fill"), "wonder": ("wonder", "ask", "plan", "goal"), "calm": ("check", "review", "tune")}  # a low need puts these first
STEP_COST = 0.03  # energy a model step spends
WANTS_OPEN = 3  # at most this many wants wait for you at once
TRUST_AFTER = 10  # messages before it can trust you: trust is earned over a while
WISH = "A wish: "  # how a want reads in the chat; an app line, not a reply to judge


def needs() -> dict[str, float]:
    """Its needs now, 0 to 1: the last value written, drifted by the time since (energy and calm come back, fullness drains)."""
    con = db.connect()
    row = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Needs' AND id > ? ORDER BY id DESC LIMIT 1", (_start(),)).fetchone()
    con.close()
    got = json.loads(row["content"]) if row else {}
    tens = max(0.0, (time.time() - float(got.get("at", time.time()))) / 600)
    return {k: round(min(1.0, max(0.0, float(got.get(k, 0.6)) + DRIFT[k] * tens)), 3) for k in NEEDS}


def tired() -> bool:
    return needs()["energy"] < TIRED


def feel(changes: dict[str, float], cause: str) -> list[dict[str, Any]]:
    """Change its needs; a need that drops below LOW or climbs above HIGH is a mood shift, kept with what brought it on."""
    if not any(changes.values()):
        return []
    before = needs()
    after = {k: round(min(1.0, max(0.0, before[k] + changes.get(k, 0.0))), 3) for k in NEEDS}
    shifts = [{"need": k, "dir": "down" if after[k] < before[k] else "up", "value": after[k], "cause": cause[:160]} for k in NEEDS
              if (before[k] >= LOW > after[k]) or (before[k] <= HIGH < after[k])]
    con = db.connect()
    with con:
        con.execute("DELETE FROM char_memories WHERE source = 'sheet' AND title = 'Needs' AND id > ?", (_start(),))
        con.execute("INSERT INTO char_memories (title, content, source) VALUES ('Needs', ?, 'sheet')", (json.dumps({**after, "at": time.time()}),))
        for sh in shifts:
            con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'sheet')", (f"Shift: {sh['need']}", json.dumps(sh)))
    con.close()
    return shifts


def shifts(limit: int = 12) -> list[dict[str, Any]]:
    con = db.connect()
    rows = con.execute("SELECT content, created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Shift: %' AND id > ? ORDER BY id DESC LIMIT ?", (_start(), limit)).fetchall()
    con.close()
    return [{**json.loads(r["content"]), "at": r["created_at"]} for r in rows]


def _feel_line() -> str:
    """How it feels, for its reply prompt: only what stands out."""
    n = needs()
    bits = [x for x, on in (("You are tired.", n["energy"] < TIRED), ("You are hungry for something new to read.", n["fullness"] < LOW),
                            ("Your head is full of questions.", n["wonder"] > HIGH), ("You are in high spirits.", n["joy"] > HIGH),
                            ("You are a little low.", n["joy"] < LOW), ("You are unsettled by your recent mistakes.", n["calm"] < LOW)) if on]
    return "How you feel right now (let it colour your tone; never list it): " + " ".join(bits) if bits else ""


def _felt(kind: str, got: tuple[str, str]) -> None:
    """What a step that did something does to its needs."""
    d: dict[str, float] = {} if kind in NO_MODEL else {"energy": -STEP_COST}
    if kind == "reflect":
        d |= {"fullness": 0.15, "wonder": -0.05}
        con = db.connect()
        g = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Guess: %' AND id > ? ORDER BY id DESC LIMIT 1", (_start(),)).fetchone()
        con.close()
        sur = float(g["content"].split("|")[0]) if g else 0.5
        d |= {"joy": 0.1} if sur < 0.3 else {"joy": -0.05, "wonder": 0.05} if sur >= 0.5 else {}
    elif kind in ("wonder", "speculate", "ask", "plan", "goal"):
        d["wonder"] = 0.1
    elif kind == "check" and got[1].startswith("rejected"):
        d["calm"] = -0.1
    elif kind == "review" and got[1].startswith("mistake"):
        d |= {"calm": -0.15, "joy": -0.05}
    elif kind == "journal":
        d["calm"] = 0.1
    feel(d, f"{kind}: {got[0]} ({got[1]})"[:160])


def wants() -> list[dict[str, Any]]:
    """What it asked you for, newest first: waiting, given, or let go."""
    con = db.connect()
    rows = con.execute("SELECT id, content, created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Want: %' AND id > ? ORDER BY id DESC", (_start(),)).fetchall()
    con.close()
    return [{"id": r["id"], "at": r["created_at"], **json.loads(r["content"])} for r in rows]


def _want_from() -> tuple[str, str, str] | None:
    """Something it lacks that you could give, each from what actually happened: a guess that was far off, or a topic the web had nothing on."""
    had = {w["topic"].lower() for w in wants()}
    con = db.connect()
    far = con.execute("SELECT g.content, n.title FROM char_memories g JOIN char_memories n ON n.id = CAST(substr(g.title, 8) AS INTEGER) "
                      "WHERE g.source = 'sheet' AND g.title LIKE 'Guess: %' AND g.id > ? ORDER BY g.id DESC LIMIT 20", (_start(),)).fetchall()
    empty = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Run: reflect' AND content LIKE '%nothing found on the web for %' AND id > ? ORDER BY id DESC LIMIT 20", (_start(),)).fetchall()
    con.close()
    for r in far:
        sur, guess = r["content"].split("|", 1)
        topic = r["title"].removeprefix("Reflection: ")
        if float(sur) >= 0.5 and topic.lower() not in had:
            return f"a source I can trust on {topic}", f'I guessed "{guess[:120]}" and it was {round(float(sur) * 100)}% off what I then read', topic
    for r in empty:
        topic = json.loads(r["content"]).get("detail", "").split("nothing found on the web for ", 1)[-1].strip()
        if topic and topic.lower() not in had:
            return f"anything about {topic}", f"I looked {topic} up and the web had nothing", topic
    return None


KEEP_OPEN = 24  # like Pino's 24 short-term slots: the open questions it carries out of a run


def prune_questions() -> int:
    """Its sleep, at the end of a run: open questions off its world, asked twice in other words, or past the newest 24 are let go, so the letter asks only what matters. No model."""
    words, seen, gone, kept = world_words(), set(), 0, 0
    for q in _open_questions(_start())[::-1]:  # newest first: past KEEP_OPEN, the oldest go
        key = " ".join(re.findall(r"[a-z0-9]+", q.lower()))
        why = "off its world" if not on_world(q, words) else "asked before" if key in seen else "past the 24 it keeps" if kept >= KEEP_OPEN else ""
        if not why:
            seen.add(key)  # only a question it keeps makes a later wording a repeat
            kept += 1
        if why:
            add_memory(f"Reflection: {q}"[:80], f"(pruned: {why})", source="sheet")
            gone += 1
    return gone


def letter() -> dict[str, Any]:
    """What it needs from you, as one letter you answer in place: its waiting wishes and its open questions, only those about its world."""
    words = world_words()
    who = get_profile()["name"]
    items = [{"id": f"w{w['id']}", "kind": "wish", "ask": w["said"] if in_voice(w.get("said"), who) else f"Could you find me {w['thing']}?"} for w in wants() if w["status"] == "waiting" and on_world(f"{w['thing']} {w['topic']}", words)]
    items += [{"id": f"q:{q}", "kind": "question", "ask": q} for q in _open_questions(_start()) if on_world(q, words)][:max(0, 6 - len(items))]
    con = db.connect()
    gone = con.execute("SELECT COUNT(*) FROM char_memories WHERE id > ? AND content LIKE '(pruned: %'", (_start(),)).fetchone()[0]
    con.close()
    return {"who": get_profile()["name"], "items": items, "let_go": gone, "open": len(_open_questions(_start()))}


def answer_letter(answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Your answers: a wish you answer is given, a question you answer becomes a note its Verifier checks; one you skip is let go."""
    open_qs, done = set(_open_questions(_start())), {"given": 0, "let go": 0}
    for a in answers:
        aid, text = str(a.get("id", "")), str(a.get("text") or "").strip()[:4000]
        if not text and not a.get("skip"):
            continue  # left blank: it stays in the next letter
        if aid.startswith("w") and aid[1:].isdigit():
            if give_want(int(aid[1:]), text) is not None:
                done["given" if text else "let go"] += 1
        elif aid.startswith("q:") and (q := aid[2:]) in open_qs:
            add_memory(f"Reflection: {q}"[:80], text or "(let go: you skipped it)", source="reflection" if text else "sheet")
            if text:
                feel({"fullness": 0.1, "wonder": -0.05}, "you answered its question")
            done["given" if text else "let go"] += 1
    return {**done, "letter": letter()}


def give_want(want_id: int, gift: str = "") -> dict[str, Any] | None:
    """You answer a want: what you give becomes a note it reads (and its Verifier checks); nothing given lets it go."""
    con = db.connect()
    row = con.execute("SELECT content FROM char_memories WHERE id = ? AND source = 'sheet' AND title LIKE 'Want: %'", (want_id,)).fetchone()
    con.close()
    if not row:
        return None
    w = json.loads(row["content"])
    gift = gift.strip()[:4000]
    w.update(status="given" if gift else "let go", gift=gift)
    con = db.connect()
    with con:
        con.execute("UPDATE char_memories SET content = ? WHERE id = ?", (json.dumps(w), want_id))
    con.close()
    if gift:
        add_memory(f"Reflection: {w['topic']}"[:80], gift, source="reflection")
        feel({"joy": 0.2, "fullness": 0.15}, f"you gave it {w['thing']}")
    return {"id": want_id, **w}


def trust() -> dict[str, Any]:
    """How much of what you say it kept: the more it keeps, the more it trusts you, which shows in how openly it talks."""
    con = db.connect()
    rows = [r["content"] for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Heard: %' AND id > ?", (_start(),))]
    con.close()
    kept = rows.count("kept")
    value = round((kept + 1) / (len(rows) + 2), 2)  # starts at a half, moves with each message
    return {"kept": kept, "n": len(rows), "value": value, "trusted": len(rows) >= TRUST_AFTER and value >= HIGH}


TOOL_MAKES = {"plan": ("plan", None), "goal": ("question", None), "ask": ("question", None), "wonder": ("question", None), "speculate": ("question", None), "reflect": ("note", None),
              "check": ("note", None), "extract": ("name", "name"), "ideas": ("name", "idea"), "fold": ("name", None), "reply": ("chat", "it"), "review": ("chat", "it"), "tune": ("trait", None)}
TOOL_FLOW = [("plan", "goal"), ("goal", "reflect"), ("ask", "reflect"), ("wonder", "reflect"), ("want", "reflect"), ("reflect", "check"), ("reflect", "extract"),
             ("extract", "ideas"), ("extract", "fold"), ("fold", "speculate"), ("speculate", "reflect"), ("check", "journal"), ("reply", "review"), ("review", "tune"), ("bake", "plan")]  # which step feeds which


def prompt_now() -> str:
    """Its reply prompt as it stands, without this turn's moods and notes: who it is, who you are, its tone and your standing instructions."""
    parts = [get_profile()["persona"], _you_line(), _tone()]
    if told := instructions()[:5]:
        parts.append("Standing instructions from the person you talk to (always follow them):\n" + "\n".join(f"- {i['text']}" for i in told))
    return "\n\n".join(x for x in parts if x)


def toolnet(mesh_nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Its tools as a graph: every step it has run, its record, the model it runs on, the steps it feeds, and the newest things it made."""
    from . import harness  # harness imports char
    con = db.connect()
    runs = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Run: %' AND id > ? ORDER BY id", (_start(),)).fetchall()
    con.close()
    rec: dict[str, dict[str, Any]] = {}
    for r in runs:
        k, c = r["title"].removeprefix("Run: "), json.loads(r["content"] or "{}")
        e = rec.setdefault(k, {"ok": 0, "n": 0, "last": ""})
        e["n"] += 1; e["ok"] += c.get("outcome") == "ok"; e["last"] = c.get("detail", "")
    kinds = [k for k in ENGINE_ORDER if k in rec and (k in SYS_OF or k == "reply")]
    s = settings.get_all()
    model = s.chat_model or s.model_name or "the loaded model"
    nodes = [{"id": f"tool:{k}", "layer": "tool", "label": k, "kind": "step", "state": "ok" if rec[k]["ok"] else "idle",
              "body": f"{harness.DOES.get(k, 'talks to you')}. {rec[k]['ok']} of {rec[k]['n']} runs did something. Last: {rec[k]['last'][:160]}"} for k in kinds]
    nodes.append({"id": "tool:model", "layer": "tool", "label": model.split("/")[-1], "kind": "model", "state": "ok", "body": f"The model its steps and replies run on: {model}"})
    edges = [["tool:model", f"tool:{k}"] for k in kinds if k not in NO_MODEL] + [[f"tool:{a}", f"tool:{b}"] for a, b in TOOL_FLOW if a in rec and b in rec]
    for k in kinds:  # what each made: its newest few, so the map stays readable
        if k in TOOL_MAKES:
            layer, kind = TOOL_MAKES[k]
            made = [n for n in (mesh_nodes or []) if n["layer"] == layer and (kind is None or n.get("kind") == kind)]
            edges += [[f"tool:{k}", n["id"]] for n in made[-6:]]
    return {"nodes": nodes, "edges": edges}


def _hear(turn_id: int, text: str, told: list[str], lit: list[str], mem_rows: list[Any], up: str) -> bool:
    """Keep or let go: it keeps what tells it who you are, touches its world, pushes it on or says something long enough to matter; small talk drifts."""
    kept = bool(told or lit or mem_rows or up or len(text.split()) >= 12)
    add_memory(f"Heard: {turn_id}", "kept" if kept else "let go", source="sheet")
    if kept:
        feel({"joy": 0.03}, f'you said "{text[:80]}"')
    return kept


def heard() -> dict[int, str]:
    con = db.connect()
    rows = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Heard: %' AND id > ?", (_start(),)).fetchall()
    con.close()
    return {int(r["title"].removeprefix("Heard: ")): r["content"] for r in rows}


def life() -> dict[str, Any]:
    """Needs, mood shifts, wants and trust, for the page."""
    return {"needs": needs(), "about": NEEDS, "tired": tired(), "shifts": shifts(), "wants": wants(), "trust": trust()}


def journal() -> list[dict[str, Any]]:
    """Its study journal, newest page first: the page it wrote, and the facts under it."""
    con = db.connect()
    rows = con.execute("SELECT title, content, created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Journal: %' AND id > ? ORDER BY id DESC", (_start(),)).fetchall()
    con.close()
    return [{"day": r["title"].removeprefix("Journal: "), "at": r["created_at"], **json.loads(r["content"])} for r in rows]


def _choose(kinds: tuple[str, ...]) -> tuple[tuple[str, ...], str]:
    """The Verifier's decision: every step that could run, in the order worth trying. Verify before building on a note;
    while its guesses keep being wrong it digs into open questions, and once they come out right it goes looking for new ground."""
    con = db.connect()
    got = [float(r["content"].split("|")[0]) for r in con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Guess: %' AND id > ? ORDER BY id DESC LIMIT 5", (_start(),))]
    con.close()
    sur = sum(got) / len(got) if got else 0.5
    order = ("check", "review", "tune", "sort", "extract", "bake", "journal", "want", "reflect", "goal", "ask", "plan", "fold", "ideas", "wonder", "fill", "practise") if sur >= 0.3 else ("check", "review", "tune", "sort", "extract", "bake", "journal", "want", "goal", "ask", "plan", "reflect", "ideas", "wonder", "fill", "practise")  # speculate is not in the idle rotation: it runs when the harness sees it is stuck, or the planner picks it
    first = ("check", "review")  # verify before building on a note, always
    waited = [k for k in order if k not in first and TRIED["n"] - TRIED.get(k, -STARVE) >= STARVE]  # starved: at the end of the line too long, it gets a turn
    n = needs()
    low = sorted((v, k) for k, v in n.items() if v < LOW and k in LEADS)  # the lowest need leads: hungry reads, restless asks, shaken checks
    lead = [x for _, k in low for x in LEADS[k] if x not in first]
    order = tuple(k for k in first if k in order) + tuple(dict.fromkeys(lead + waited)) + tuple(k for k in order if k not in first and k not in waited and k not in lead)
    return tuple(k for k in order if k in kinds), "".join(f"{k} low ({v:.2f}), so {LEADS[k][0]} first; " for v, k in low) + (f"{', '.join(waited[:3])} waited longest, so they go first; " if waited else "") + f"surprise {sur:.2f}: " + ("still being surprised, so answer open questions first" if sur >= 0.3 else "guesses keep coming out right, so look for new ground first")

SYS_OF = {k: n for n, (_, _, ks) in SYSTEMS.items() for k in ks} | {"evaluate": 3}  # the intake gate runs inside reflect, not as a step of its own, and belongs to the Verifier
TARGETS = {"reflect": "topic", "check": "note id", "fold": "name"}  # the steps rest(target=...) can aim; the rest ignore a target
class _Trace(deque):
    def clear(self) -> None:  # verse.leave clears TRACE on a persona switch: the engine record is the live persona's too
        super().clear()
        ENGINES.clear()


TRACE: deque[dict[str, Any]] = _Trace(maxlen=60)  # shortcut: the run log lives in memory like PROMPTS; a restart clears it
NOW: dict[str, Any] = {}  # the engine at work this moment, {"sys", "kind"}: what a training run samples into its system lanes
ENGINES: dict[str, dict[str, Any]] = {}  # kind -> what it did the last time it was tried, for /char/engines; in memory like TRACE
ENGINE_ORDER = ("plan", "goal", "ask", "wonder", "speculate", "fill", "want", "reflect", "extract", "ideas", "practise", "sort", "fold", "evaluate", "check", "review", "tune", "bake", "journal", "reply", "correction", "persona", "model", "cycle")
NO_MODEL = ("bake", "correction")  # the engines that never call the model
_sys: int | None = None  # the system whose step is running, so its prompts are filed under it
_failed = ""  # set by _ask when the model call failed or said nothing, so a step that did nothing can tell "model failed" from "nothing to do"


TRIED: dict[str, int] = {"n": 0}
STARVE = 12  # a step not tried in this many tries goes to the front of the line


def _engine(kind: str, outcome: str, detail: str = "") -> None:
    """One engine's latest outcome: ok, skipped or failed (each a run), or blocked (filtered out before it ran, not a run)."""
    e = ENGINES.setdefault(kind, {"at": "", "outcome": "", "detail": "", "runs": 0})
    if outcome == "blocked":
        e["blocked"] = detail
        return
    e.update(at=time.strftime("%H:%M:%S"), outcome=outcome, detail=str(detail)[:1500], runs=e["runs"] + 1)
    TRIED["n"] += 1; TRIED[kind] = TRIED["n"]  # when each step last had a turn, so none waits forever
    init_db()
    con = db.connect()
    with con:  # a sheet row too, so the run survives a restart and travels with the persona; not add_memory, a run is not knowledge
        con.execute("INSERT INTO char_memories (title, content, source) VALUES (?, ?, 'sheet')", (f"Run: {kind}", json.dumps({"outcome": outcome, "detail": e["detail"]})))
    con.close()


def _blocked(kind: str, off: set[int], braked: bool, quiet: bool, up: bool = True) -> str:
    """Why an engine could not run now, the first reason that holds, or "" when it could."""
    if not up and kind not in NO_MODEL:
        return "model down"
    if kind in SYS_OF and SYS_OF[kind] in off:
        return f"system S{SYS_OF[kind]} off"
    if braked and kind in EXPLORES:
        return "curiosity at 0 (braked)"
    return f"{mode()} mode" if quiet and kind in SYS_OF else ""


def _blocks(up: bool, force: bool = False) -> tuple[set[int], dict[str, str]]:
    """The systems off, and why each engine could not run now ("" when it could): shared by /char/engines and /char/report."""
    off, d = systems_off(), disposition()
    braked, quiet = (d["nE"] > 0 or d["dial"] == 0) and d["curiosity"] <= 0, mode() in ("quiet", "sleeping") and not force
    t = tired() and not force  # a training run you started ignores tiredness and quiet, as rest(force=True) does
    return off, {k: _blocked(k, off, braked, quiet, up) or ("tired: resting until its energy comes back" if t and k in SYS_OF and k not in NO_MODEL else "") for k in ENGINE_ORDER}


def engines(up: bool, label: str) -> dict[str, Any]:
    """Every engine's status for the page: whether it could run now and what it did the last time it was tried."""
    init_db()
    off, blocked = _blocks(up)
    out = []
    for k in ENGINE_ORDER:
        n, e = SYS_OF.get(k), ENGINES.get(k) or {}
        out.append({"kind": k, "system": n, "label": k if n is None else f"{'V' if n == 3 else f'S{n}'} {k}", "on": n not in off,
                    "blocked": blocked[k],
                    "last": {x: e[x] for x in ("at", "outcome", "detail")} if e.get("outcome") else None, "runs": e.get("runs", 0)})
    return {"model": {"up": up, "label": label}, "engines": out}


def report(up: bool, label: str) -> dict[str, Any]:
    """Everything the live persona has done, counted from its own rows: run totals, the correction loop, what it learned, and each engine's record."""
    init_db()
    start = _start()
    con = db.connect()
    mark = con.execute("SELECT created_at FROM char_memories WHERE id = ?", (start,)).fetchone()
    rows = lambda where, args=(): con.execute(f"SELECT title, content, created_at FROM char_memories WHERE id > ? AND {where} ORDER BY id DESC", (start, *args)).fetchall()
    count = lambda where: len(rows(where))
    runs = []
    for r in rows("source = 'sheet' AND title LIKE 'Run: %'"):
        try:
            c = json.loads(r["content"])
        except ValueError:
            c = {}
        kind = r["title"].removeprefix("Run: ")
        runs.append({"at": r["created_at"], "kind": kind, "system": SYS_OF.get(kind), "outcome": str(c.get("outcome", "")), "detail": str(c.get("detail", ""))})
    checked = [r["content"] for r in rows("source = 'sheet' AND title LIKE 'Checked: %'")]
    reviewed = [r["content"] for r in rows("source = 'sheet' AND title LIKE 'Reviewed: %'")]
    fixes = {r["title"]: r["content"].split("|")[0] for r in rows("source = 'sheet' AND title LIKE 'Correction: %'")[::-1]}  # the last word on each correction wins
    questions = count("source = 'question'")
    corr = {"reviewed": len(reviewed), "mistakes": reviewed.count("mistake"), "asked_you": count("source = 'sheet' AND (title LIKE 'Asking: %' OR title LIKE 'Answered: %')"),
            "answered": count("source = 'sheet' AND title LIKE 'Answered: %'"), "instructions": count("source = 'sheet' AND title LIKE 'Instruction: %'"),
            "prompt_fixes": sum(v == "on" for v in fixes.values()), "fails": count("source = 'sheet' AND title LIKE 'Fail: %'")}
    learned = {"notes": count("source = 'reflection'"), "verified": checked.count("keep"), "rejected": checked.count("drop"),
               "names": count("source = 'entity' AND title LIKE 'Entity: %'"), "ideas": count("source = 'entity' AND title LIKE 'Idea: %'"),
               "questions": questions, "answered": questions - len(_open_questions(start)), "plans": count("source = 'sheet' AND title LIKE 'Plan%: %'"),
               "summaries": count("source = 'summary'")}
    cycles = count("source = 'sheet' AND title = 'Baked'")
    con.close()
    tally = lambda k, o: sum(r["kind"] == k and r["outcome"] == o for r in runs)
    off, blocked = _blocks(up)

    def eng(k: str) -> dict[str, Any]:
        last = next(({x: r[x] for x in ("at", "outcome", "detail")} for r in runs if r["kind"] == k), None)
        return {"kind": k, "ok": tally(k, "ok"), "skipped": tally(k, "skipped"), "failed": tally(k, "failed"), "blocked": blocked.get(k, ""), "last": last}

    harness = [{"system": n, "name": SYSTEMS[n][0], "does": SYSTEMS[n][1], "on": n not in off, "engines": [eng(k) for k in SYSTEMS[n][2] + (("evaluate",) if n == 3 else ())]} for n in (2, 1, 0, 3)]
    harness.append({"system": None, "name": "Harness", "does": "chat, corrections and personas", "on": True, "engines": [eng(k) for k in ("reply", "correction", "persona", "model", "cycle")]})
    outcomes = [r["outcome"] for r in runs]
    notes = _notes(start)
    by_topic = {n["topic"]: n["id"] for n in notes}
    for r in runs:  # a step about a note links to it, so the page can open the note behind the step
        r["ref"] = next((i for t, i in by_topic.items() if r["detail"].startswith(t + ":") or r["detail"].startswith(t[:60])), None) if r["kind"] in ("reflect", "evaluate", "check", "extract") else None
    return {"notes": notes, "who": get_profile()["name"], "you": you(), "life": life(), "since": mark["created_at"] if mark else "", "model": {"up": up, "label": label},
            "totals": {"steps": len(runs), "ok": outcomes.count("ok"), "skipped": outcomes.count("skipped"), "failed": outcomes.count("failed"), "cycles": cycles,
                       "replies": sum(t["role"] == "dot" and not t["text"].startswith(NOT_A_REPLY) for t in _chat_since())},
            "corrections": corr, "learned": learned, "disposition": (dsp := disposition()), "drive": drive(dsp), "series": monitor()["series"], "gains": gains(), "arms": arms(), "harness": harness, "trace": runs[:300]}


def _notes(start: int) -> list[dict[str, Any]]:
    """Every note the live persona wrote, with what the Verifier and the exact checks said about it."""
    con = db.connect()
    rows = con.execute("SELECT id, title, content, source, created_at FROM char_memories WHERE id > ? AND title LIKE 'Reflection: %' AND NOT (source = 'sheet' AND content = '(nothing found)') ORDER BY id DESC", (start,)).fetchall()
    side = {r["title"]: r["content"] for r in con.execute("SELECT title, content FROM char_memories WHERE id > ? AND source = 'sheet' AND (title LIKE 'Checked: %' OR title LIKE 'Ground: %' OR title LIKE 'Guess: %' OR title LIKE 'Sources: %' OR title LIKE 'Gate: %')", (start,))}
    con.close()
    out = []
    for r in rows:
        i, g = r["id"], side.get(f"Guess: {r['id']}", "").split("|", 1)
        try:
            n_src = len(json.loads(side.get(f"Sources: {i}", "[]")))
        except ValueError:
            n_src = 0
        out.append({"id": i, "topic": r["title"].removeprefix("Reflection: "), "text": r["content"].removeprefix("(rejected) "), "at": r["created_at"],
                    "verdict": side.get(f"Checked: {i}", "unchecked"), "ground": float(side[f"Ground: {i}"]) if f"Ground: {i}" in side else None,
                    "surprise": float(g[0]) if g[0] else None, "guess": g[1] if len(g) > 1 else "", "sources": n_src if f"Sources: {i}" in side else None, "gate": side.get(f"Gate: {i}", "").split("|", 1) if f"Gate: {i}" in side else None})
    return out


def note(i: int) -> dict[str, Any]:
    """One note with everything behind it: the question and plan line it answers, what it guessed first, its sources, the names taken from it, and the verdict."""
    init_db()
    start = _start()
    n = next((x for x in _notes(start) if x["id"] == i), None)
    if not n:
        raise ValueError("no such note for this persona")
    con = db.connect()
    get = lambda t: (con.execute("SELECT content FROM char_memories WHERE id > ? AND title = ? ORDER BY id DESC LIMIT 1", (start, t)).fetchone() or {"content": None})["content"]
    try:
        sources = json.loads(get(f"Sources: {i}") or "null")
    except ValueError:
        sources = None
    q = get(f"Question: {n['topic']}")
    plan_id = re.search(r"\(from (\d+)\)", q or "")
    plan = con.execute("SELECT content FROM char_memories WHERE id = ?", (int(plan_id[1]),)).fetchone() if plan_id and plan_id[1] != "0" else None
    names = [x.strip() for x in (get(f"Entities: {i}") or "").split(",") if x.strip()]
    con.close()
    return n | {"question": q, "plan": plan["content"] if plan else None, "names": names, "sources": sources}


def _log(kind: str, messages: list[dict[str, str]], reply: str) -> None:
    PROMPTS.append({"at": time.strftime("%H:%M:%S"), "kind": kind, "system": _sys, "messages": messages, "reply": reply})


def systems_off() -> set[int]:
    con = db.connect()
    rows = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'System: _' AND id > ? ORDER BY id", (_start(),)).fetchall()  # this persona's switches only
    con.close()
    off = {int(t[-1]) for t, c in {r["title"]: r["content"] for r in rows}.items() if c == "off"}  # the last word on each system wins
    for n, (on, _) in space.gates(mine()).items():  # a rule that holds a system beats the hand switch while it holds
        (off.discard if on else off.add)(n)
    return off


def set_system(n: int, on: bool) -> None:
    if n not in SYSTEMS:
        raise ValueError("no such system")
    _since(True, get_profile()["name"])
    add_memory(f"System: {n}", "on" if on else "off", source="sheet")


def systems() -> dict[str, Any]:
    """The three systems, whether each is on, and what each last did and sent the model."""
    init_db()
    off, held = systems_off(), space.gates(mine())
    return {"systems": [{"id": n, "name": name, "does": does, "kinds": list(ks), "on": n not in off, "rule": held[n][1] if n in held else "",
                         "runs": [t for t in TRACE if t["system"] == n][::-1][:8], "prompts": [p for p in PROMPTS if p.get("system") == n][::-1][:6]}
                        for n, (name, does, ks) in SYSTEMS.items()]}


def _ask(system: str, user: str, max_tokens: int) -> str:
    global _failed
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        out = (jobs.complete(settings.get_all(), messages, max_tokens=max_tokens) or "").strip()
    except Exception as e:
        _log("small step", messages, f"(failed: {e})"); _failed = f"model call failed: {e}"[:200]; return ""
    _log("small step", messages, out)
    if not out:
        _failed = _failed or "model returned nothing"
    return out


def _clean(s: str, n: int) -> str:
    return (s.strip().splitlines() or [""])[0].strip().strip("\"'` ")[:n]


FILL = {"World": (120, "In one short sentence, where and when does {who} live and work? Use only the notes."),
        "Calls you": (30, "What does {who} call the person they talk to? Answer with one to three words only."),
        "Catchphrase": (60, "Give one short phrase {who} is known for saying. Answer with the phrase only.")}


def rest(on_char: bool = False, n: int | None = 0, force: bool = False, only: str | None = None, target: str | None = None) -> dict[str, Any]:
    """One tiny step while asleep: reflect, wonder, fill a sheet slot or practise a reply; the first kind with work does it.
    `only` runs that one kind (the harness executor); `target` aims the kinds in TARGETS at one topic, note id or name."""
    init_db()
    if on_char:
        p = get_profile()
        me = {"who": p["name"], "text": p["persona"], "look": p["look"], "tint": p["tint"], "var": 0}
    else:
        row = space._rows("SELECT id, name, learned, look, tint FROM space_vars WHERE kind = 'persona' ORDER BY id DESC LIMIT 1")
        me = {"who": row[0]["name"], "text": row[0]["learned"], "look": json.loads(row[0]["look"] or "[]"), "tint": row[0]["tint"], "var": row[0]["id"]} if row else None
    braked = False
    if on_char:
        if mode() in ("quiet", "sleeping") and not force:  # your own "run one step" still runs, to test a model you just swapped in
            for k in SYS_OF:
                _engine(k, "blocked", f"{mode()} mode")
            return {"done": True, "kind": "", "topic": "", "note": "", "incurious": True, "quiet": True, "questions": _open_questions(_start())[::-1][:3], "graph": graph()}
        if not force and (q := _open_correction()) and q.get("kind") == "direction":
            for k in SYS_OF:
                _engine(k, "blocked", "waiting for you to say which way to grow")
            return {"done": True, "kind": "", "topic": "", "note": "", "asking": True, "questions": _open_questions(_start())[::-1][:3], "graph": graph()}
        if not force and tired():  # it has spent itself: it rests until energy comes back with time
            for k in SYS_OF:
                _engine(k, "blocked", "tired: resting until its energy comes back")
            return {"done": True, "kind": "", "topic": "", "note": "", "tired": True, "why": "tired: resting until its energy comes back", "questions": _open_questions(_start())[::-1][:3], "graph": graph()}
        if target is None and _var("asleep", 0) == 1:  # asleep, it learns the way you told it to grow
            target = (_direction() or None)
        d = disposition()  # curiosity is the brake: at 0 it stops reaching outward, but still reads your chat and checks its own work. A character that knows no names yet is not braked: it has to start somewhere
        braked = not force and (d["nE"] > 0 or d["dial"] == 0) and d["curiosity"] <= 0
    off = systems_off()
    kinds = tuple(k for k in ("reflect", "wonder", "speculate", "fill", "practise", "extract", "ideas", "ask", "plan", "goal", "check", "review", "tune", "sort", "fold", "bake", "journal", "want") if SYS_OF[k] not in off and not (braked and k in EXPLORES)) or ("check",)
    for k in SYS_OF:
        if k not in kinds:
            _engine(k, "blocked", _blocked(k, off, braked, False))
    since = _since(on_char, me["who"] if me else "Dot")
    sheet = space.sheet_of(me["text"]) if me else {}
    skip = {"why": ""}  # the reason the running step gave for doing nothing

    def no(reason: str) -> None:
        skip["why"] = reason
        return None

    def titles(where: str = "1", args: tuple = ()) -> list[Any]:
        con = db.connect()
        rows = con.execute(f"SELECT id, title, content FROM char_memories WHERE {where} ORDER BY id DESC", args).fetchall()
        con.close()
        return rows

    def asked_from(note_id: int) -> bool:
        return any(q["content"].endswith(f"(from {note_id})") for q in titles("source = 'question' AND id > ?", (since,)))

    def step(kind: str) -> tuple[str, str] | None:
        if kind == "reflect":
            r = reflect(on_char, target)
            if r["done"]:
                return no("nothing left to look up")
            return (r["topic"], r["note"]) if r["note"] else no(f"nothing found on the web for {r['topic']}")
        if kind == "extract":  # the names in the newest note not yet read for names: the graph grows from these
            done_ids = {r["title"].removeprefix("Entities: ") for r in titles("source = 'sheet' AND title LIKE 'Entities: %'")}
            note = next((r for r in titles("source = 'reflection' AND id > ?", (since,)) if str(r["id"]) not in done_ids), None)
            if not me:
                return no("no character yet")
            if not note:
                return no("no new note to read for names")
            names = _entities_of(note["id"], note["content"], me["who"])
            return note["title"].removeprefix("Reflection: "), (", ".join(names) or "no names in it")
        if kind == "ideas":  # after a note's names are read: what is going on around them, the graph's abstract layer
            done_ids = {r["title"].removeprefix("Ideas: ") for r in titles("source = 'sheet' AND title LIKE 'Ideas: %'")}
            named = next((r for r in titles("source = 'sheet' AND title LIKE 'Entities: %' AND id > ?", (since,))
                          if r["content"] and r["title"].removeprefix("Entities: ").isdigit() and r["title"].removeprefix("Entities: ") not in done_ids), None)
            note = titles("id = ?", (int(named["title"].removeprefix("Entities: ")),)) if named else []
            if not note:
                return no("no named note waiting for ideas")
            got = _ideas_of(note[0]["id"], note[0]["content"], named["content"].split(", "))
            return note[0]["title"].removeprefix("Reflection: "), (", ".join(got) or "no ideas in it")
        if kind == "plan":  # S2: the model thinks about what this character is missing, from what it has read so far; the plan waits for S1 to make goals of it
            plans = titles("source = 'sheet' AND title LIKE 'Plan%: %' AND id > ?", (since,))
            if not on_char or not me:
                return no("plans only on the character page")
            if not titles("source = 'reflection' AND id > ?", (since,)):
                return no("nothing read yet to plan from")
            if any(pl["title"].startswith("Plan: ") and not asked_from(pl["id"]) for pl in plans):
                return no("a plan is still waiting for questions")
            if (k := len(_open_questions(since))) >= 3:
                return no(f"{k} questions already open")
            g = graph()
            # no persona here: given the voice, a small model answers in character instead of planning
            out = _ask("You are a research planner. Reply with 3 topics, one per line, 2 to 6 words each. No sentences, no numbering. Only the topics." + _fix("plan"),
                       f"Character: {me['who']}\nAlready read about: {', '.join(x['name'] for x in g['nodes'] if x['known']) or 'nothing'}\n"
                       f"Not read about yet: {', '.join(x['name'] for x in g['nodes'] if not x['known']) or 'nothing'}\nWhich 3 new topics about this character's world should be researched next?", 50)
            had, ww = {pl["content"].lower() for pl in plans}, world_words()
            lines = [x for x in dict.fromkeys(re.sub(r"^[\s\-*\d.)]+", "", ln).strip(" .\"'") for ln in out.splitlines()) if 4 <= len(x) <= 80 and x.lower() not in had]
            for x in [x for x in lines if not on_world(x, ww)]:
                add_memory(f"Off-world: {x}"[:80], f"plan line names nothing from {me['who']}'s world", source="sheet")
            lines = [x for x in lines if on_world(x, ww)][:3]
            for ln in lines[::-1]:  # titles() reads newest first, so the first line is saved last and S1 takes it first
                add_memory(f"Plan: {ln}"[:80], ln, source="sheet")
            if not lines:
                _fail("plan")
            return ("a plan", " · ".join(lines)) if lines else no("the plan had no new topics")
        if kind == "check":  # the Verifier reads the oldest note nobody has checked: on topic, and about this character's world?
            seen = {r["title"].removeprefix("Checked: ") for r in titles("source = 'sheet' AND title LIKE 'Checked: %'")}
            note = next((r for r in titles("source = 'reflection' AND id > ?", (since,))[::-1] if str(r["id"]) not in seen and (not target or str(r["id"]) == target)), None)
            if not me or not on_char:
                return no("checks only on the character page")
            if not note:
                return no(f"note {target} is not an unchecked note" if target else "no new note to check")
            topic = note["title"].removeprefix("Reflection: ")
            ground = titles("source = 'sheet' AND title = ?", (f"Ground: {note['id']}",))
            loose = bool(ground) and float(ground[0]["content"]) < 0.5  # read exactly, no model: half its names are in no source
            drop = loose or not on_world(f"{topic} {note['content'][:500]}") or _ask(f"You check notes for {me['who']}. Does this note answer the topic, and is it about the world of {me['who']}? Reply KEEP or DROP.", f"Topic: {topic}\nNote: {note['content'][:500]}", 4).strip().upper().startswith("DROP")
            add_memory(f"Checked: {note['id']}", "drop" if drop else "keep", source="sheet")
            if drop:  # kept as a sheet row under the same title: out of its replies, but the topic is not looked up again and nothing is lost
                con = db.connect()
                with con:
                    con.execute("UPDATE char_memories SET source = 'sheet', content = '(rejected) ' || content WHERE id = ?", (note["id"],))
                con.close()
                _fail("reflect")
            return topic, "rejected: names things its sources do not" if loose else "rejected: off topic" if drop else "verified"
        if kind == "tune":  # the Verifier's prompt loop: does a reply meet its grown traits? If not: rewrite the tone, run it, evaluate it, keep it only if it works
            if not on_char or not me:
                return no("tunes only on the character page")
            want = [v for k, v, grown in traits() if grown and k != "Tone"]
            if not want:
                return no("no grown traits to meet")
            turns = _chat_since()
            con = db.connect()  # only replies written since you last grew a trait: older ones never had the chance to meet it
            grew = con.execute("SELECT MAX(created_at) AS m FROM char_memories WHERE source = 'sheet' AND (title = 'Var: direction' OR title LIKE 'Instruction: %') AND id > ?", (_start(),)).fetchone()["m"] or ""
            con.close()
            tries: dict[str, list[bool]] = {}  # the same reply is worked on until it is met or has had 3 tries, not swapped for an older one
            for r in titles("source = 'sheet' AND title LIKE 'Tuned: %'"):
                tries.setdefault(r["title"].removeprefix("Tuned: "), []).append(bool(json.loads(r["content"]).get("met") or json.loads(r["content"]).get("fixed")))
            seen = {k for k, v in tries.items() if any(v) or len(v) >= 3}
            i = next((i for i in range(len(turns) - 1, -1, -1) if turns[i]["role"] == "dot" and turns[i]["created_at"] >= grew and len(turns[i]["text"]) >= 20 and not turns[i]["text"].startswith(NOT_A_REPLY) and str(turns[i]["id"]) not in seen), None)
            if i is None:
                return no("no new reply to hold to its traits")
            said, asked = turns[i]["text"], next((t["text"] for t in turns[:i][::-1] if t["role"] == "user"), "")
            score, why = _meets(want, said, asked)
            if score is None:
                return None
            add_memory(f"Tuned: {turns[i]['id']}", json.dumps({"met": score == 1, "score": score, "why": why}), source="sheet")
            if score == 1:
                return asked[:80] or said[:80], f"met its traits: {why}"
            old = _tone()
            tried = [json.loads(r["content"]) for r in titles("source = 'sheet' AND title LIKE 'Tone tried: %'")][-4:]
            history = "\n".join(f"- {t['tone']} -> scored {t.get('score', 0)}: {t['why']}" for t in tried) or "- (none yet)"
            new = _clean(_ask("You write the tone section of a character's prompt: one or two sentences OF INSTRUCTION to the character, starting with a verb such as 'Speak' or 'Use'. "
                              "It says how to talk, never what to say: no sample reply, no facts, no names, no 'I'. "
                              f"Earlier tone sections and how they did:\n{history}\nWrite a better one, different from those that missed. Only the tone section.",
                              f"Character: {me['who']}\nTraits wanted: {'; '.join(want)}\nCurrent tone section: {old or '(none)'}\nA reply that missed them: {said[:300]}", 90), 300)
            if not new:
                return None
            if re.match(r"(?i)\W*(i\b|i'm|verily,? i|hello|greetings)", new) or new.lower() in {t["tone"].lower() for t in tried} or new.lower() == old.lower():
                return asked[:80] or said[:80], f"scored {score} ({why}); the rewrite was a reply or a repeat, not a new tone, so nothing changed"
            trial = _ask(f"{get_profile()['persona']}\n{new}", asked[:300] or "Tell me about yourself.", 160)  # run: the same question, the new tone
            s1, tw = _meets(want, trial, asked) if trial else (None, "")
            if s1 is None:
                return None
            add_memory(f"Tone tried: {turns[i]['id']}", json.dumps({"tone": new, "met": s1 == 1, "score": s1, "why": tw, "trial": trial[:300], "asked": asked[:300]}), source="sheet")
            if s1 > score:  # better than the reply it would replace: keep it, the next miss climbs from here
                add_memory("Tone", new, source="sheet")
                add_memory(f"Tuned: {turns[i]['id']}", json.dumps({"met": False, "fixed": True, "score": s1}), source="sheet")  # this reply is done: the new tone answers it
                return asked[:80] or said[:80], f"scored {score} ({why}); new tone scored {s1} and is now in its prompt: {new[:90]}"
            return asked[:80] or said[:80], f"scored {score} ({why}); new tone scored {s1}, no better, so the old one stays"
        if kind == "review":  # the Verifier rereads the oldest reply of its own it has not judged; a mistake becomes a question to you
            if not on_char or not me:
                return no("reviews only on the character page")
            if _open_correction():
                return no("waiting for your answer to a correction")
            turns = _chat_since()
            seen = {r["title"].removeprefix("Reviewed: ") for r in titles("source = 'sheet' AND title LIKE 'Reviewed: %'")}
            i = next((i for i, t in enumerate(turns) if t["role"] == "dot" and len(t["text"]) >= 20 and not t["text"].startswith(NOT_A_REPLY) and str(t["id"]) not in seen), None)
            if i is None:
                return no("no new reply to review")
            said = turns[i]["text"]
            asked = next((t["text"] for t in turns[:i][::-1] if t["role"] == "user"), "")
            same = lambda t: t.lower().strip(" .!")
            why = ("I repeated an earlier reply word for word" if any(t["role"] == "dot" and same(t["text"]) == same(said) for t in turns[:i])
                   else "I broke character and spoke as the model" if OUT_OF_CHARACTER.search(said) else "")
            if not why and asked:  # the exact checks found nothing: one small call
                verdict = _ask(f"You check replies by {me['who']}. Did the reply answer what was asked, speaking as {me['who']}? Reply YES or NO, then a few words why.", f"Asked: {asked[:300]}\nReply: {said[:400]}", 20)
                if not verdict:  # the model is down: leave the reply for another time
                    return None
                if verdict.upper().startswith("NO"):
                    why = _clean(re.sub(r"(?i)^no\b[\s,.:;-]*", "", verdict), 100).rstrip(".") or "it did not answer what you asked"
            add_memory(f"Reviewed: {turns[i]['id']}", "mistake" if why else "ok", source="sheet")
            if why:
                add_memory(f"Asking: {turns[i]['id']}", json.dumps({"asked": asked[:300], "said": said[:300], "why": why, "chat": 0}), source="sheet")
            return asked[:80] or said[:80], f"mistake: {why}" if why else "ok"
        if kind == "goal":  # S1: one plan line becomes one question S0 can look up
            pl = next((x for x in titles("source = 'sheet' AND title LIKE 'Plan: %' AND id > ?", (since,)) if not asked_from(x["id"])), None)
            if not pl:
                return no("no plan waiting for questions")
            if (k := len(_open_questions(since))) >= 3:
                return no(f"{k} questions already open")
            had = {r["content"].split(" (from")[0].lower() for r in titles("source = 'question' AND id > ?", (since,))}
            q = _clean(_ask("Write one short question that asks about this topic. Only the question." + _fix("goal"), pl["content"], 30), 101).rstrip("?").strip()
            if len(q) > 99 or not re.match(r"(?i)(?:who|what|where|when|why|how|which)\b.{6}", q) or re.match(r"(?i)\w+,\s*\w+,", q) or q.lower() + "?" in had:  # clipped, parroted or asked before
                _fail("goal")
                q = f"What matters about {pl['content']}"
            if q.lower() + "?" in had:  # nothing new to ask of it: the line is spent
                con = db.connect()
                with con:
                    con.execute("UPDATE char_memories SET title = ? WHERE id = ?", (f"Plan (dropped): {pl['content']}"[:80], pl["id"]))
                con.close()
                return no("plan line dropped: its question was asked before")
            if not on_world(q):  # the model wandered off the plan line: ask the plain question, which names the line's own anchor
                q = f"What matters about {pl['content']}"
            add_memory(f"Question: {q}?"[:80], f"{q}? (from {pl['id']})", source="question")
            return pl["content"], q + "?"
        if kind == "want":  # S1: it asks you for something it lacks, grounded in what went wrong, the way Pino asks at his shrine
            if not on_char or not me:
                return no("asks only on the character page")
            if (k := sum(w["status"] == "waiting" for w in wants())) >= WANTS_OPEN:
                return no(f"{k} wants already waiting for you")
            if not (got := _want_from()):
                return no("nothing it lacks that you could give")
            thing, because, topic = got
            if not on_world(f"{thing} {topic}"):
                return no("off its world: it wanted something that names nothing from it")
            said = _clean(_ask(f"{me['text'][:500]}\n\nIn one sentence, in the first person, ask the person you talk to for this and say why. Use only the facts given.",
                               f"You want: {thing}\nWhy: {because}", 60), 300)
            if not in_voice(said, me["who"]):
                said = f"Could you find me {thing}? {because}."
            add_memory(f"Want: {topic}"[:80], json.dumps({"thing": thing, "because": because, "topic": topic, "said": said, "status": "waiting"}), source="sheet")
            con = db.connect()
            with con:
                con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', ?)", (WISH + said,))
            con.close()
            return thing, because
        if kind == "journal":  # its study journal: once enough has happened since the last page, it writes one, in its own voice
            if not on_char or not me:
                return no("keeps a journal only on the character page")
            day = _day_since(_last_journal_id())
            if len(day["studied"]) < JOURNAL_EVERY:
                return no(f"{len(day['studied'])} new notes since its last page, needs {JOURNAL_EVERY}")
            facts = "\n".join(["What is true, from your notes:", *[f"- {k}" for k in day["known"]],
                               *[f"You once guessed, WRONGLY, for \"{g['q']}\": \"{g['guess']}\"" for g in day["surprised"][:3]],
                               *[f"The person taught you: {t}" for t in day["taught"][:3]],
                               f"You still want to know: {'; '.join(day['next']) or 'nothing yet'}", _you_line(),
                               *[f"Your {sh['need']} went {sh['dir']} because of: {sh['cause']}" for sh in shifts(3)]])
            voice = f"{me['text'][:700]}\n\nYou write one paragraph of your journal: a reflection on yourself, in the first person, two or three sentences. Use only the facts given; a wrong guess was never true; invent nothing. "
            parts = [_clean(_ask(voice + f"Begin with \"I am {me['who']}\": who you are now, in light of what is true from your notes.", facts, 120), 500),
                     _clean(_ask(voice + "Begin with \"I have been\": what you got wrong before you looked it up, and how learning the truth changed you.", facts, 120), 500),
                     _clean(_ask(voice + "Begin with \"I will be\": who you are becoming, and what you want to understand next.", facts, 120), 500)]
            text = "\n\n".join(p for p in parts if p)  # three short calls: a small model keeps to one paragraph, never to three
            if not text:
                return None
            add_memory(f"Journal: {_today()}", json.dumps({**day, "text": text}), source="sheet")
            return f"journal page for {_today()}", text[:120]
        if kind == "bake":  # consolidation: freeze the counts maturity is read from. No model call
            d = disposition() if on_char else None
            if not d:
                return no("bakes only on the character page")
            if (k := d["nAE"] - d["baked"]["nAE"]) < BAKE_EVERY:
                return no(f"{k} new answers, needs {BAKE_EVERY}")
            add_memory("Baked", json.dumps({"nE": d["nE"], "nAE": d["nAE"], "S": d["compression"]["S"]}), source="sheet")
            return "what it has answered", f"maturity {d['maturity']:.2f} → {disposition()['maturity']:.2f} · {d['nAE']} answers about {d['nE']} names"
        if kind == "fold":  # compression: a name with three or more notes about it gets one summary, so a reply reads one note instead of many
            # shortcut: a name is folded once and the summary does not grow with later notes; refold when its notes double if that bites
            have = {r["title"].removeprefix("Summary: ") for r in titles("source = 'summary' AND id > ?", (since,))}
            notes = titles("source = 'reflection' AND id > ?", (since,))
            for node in sorted(graph()["nodes"], key=lambda x: -x["n"]) if on_char else []:
                about = [r["content"] for r in notes if node["name"].lower() in f"{r['title']} {r['content']}".lower()]
                if node["kind"] != "concrete" or node["name"] in have or len(about) < 3 or (target and node["name"].lower() != target.lower()):
                    continue
                text = " ".join(_ask(f"Fold these notes into three short sentences about {node['name']}. Use only what the notes say. Plain text.", "\n".join(about)[:1800], 110).split())[:500]
                if not text:
                    return None
                add_memory(f"Summary: {node['name']}", text, source="summary")
                return node["name"], text
            return no(f"{target} has no three new notes to fold" if target else "no name with three new notes to fold")
        if kind == "sort":  # the Sorter's job, done by itself: one chat message it has not read for names, so what you talk about reaches the web
            got = sorter(1)["read"] if on_char else []
            return (f"chat: {got[0]['text'][:60]}", ", ".join(got[0]["names"]) or "no names in it") if got else no("no chat message left to read for names")
        if kind == "ask":  # the Asker turns the graph's names into questions, so reflect has something new to research
            got = asker() if on_char else []
            return ("new questions", "; ".join(got)) if got else no("no new question to ask")
        if kind == "wonder":
            last = (titles("source = 'reflection' AND id > ?", (since,)) or [None])[0]
            if not last:
                return no("nothing new to read")
            if (k := len(_open_questions(since))) >= 3:
                return no(f"{k} questions already open")
            if any(q["content"].endswith(f"(from {last['id']})") for q in titles("source = 'question' AND id > ?", (since,))):
                return no("already asked about the newest note")
            topic = last["title"].removeprefix("Reflection: ")
            q = _clean(_ask("Read the note. Ask one short follow-up question about something the note does not say. Start with Who, What, Where, When, Why or How. Only the question." + _fix("wonder"), last["content"], 30), 101).rstrip("?").strip()
            if len(q) > 99 or not re.match(r"(?i)(?:who|what|where|when|why|how|which)\b.{6}", q) or re.match(r"(?i)\w+,\s*\w+,", q):  # "Who, What, Where…" is the prompt parroted back  # a clipped or empty question: ask the plain one, but never about a question
                _fail("wonder")
                if topic.endswith("?"):
                    return no("the model's question was unusable")
                q = f"What else matters about {topic}"
            q += "?"
            if any(r["content"].split(" (from")[0].lower() == q.lower() for r in titles("source = 'question' AND id > ?", (since,))):
                return no("that question was asked before")  # a small model repeats itself
            if not on_world(q):
                add_memory(f"Off-world: {q}"[:80], f"names nothing from {get_profile()['name']}'s world", source="sheet")
                return no("off its world: names nothing from it")
            add_memory(f"Question: {q}"[:80], f"{q} (from {last['id']})", source="question")
            con = db.connect()
            with con:
                con.execute("UPDATE char_vars SET value = MIN(max_val, value + 0.5) WHERE name = 'curiosity'")
            con.close()
            return "a question", q
        if kind == "speculate":  # on its own: a guess from what it has compressed (summaries, else its newest notes), and the question that would prove it right or wrong
            done = {r["title"].removeprefix("Speculation: ") for r in titles("source = 'sheet' AND title LIKE 'Speculation: %' AND id > ?", (since,))}
            src = next((r for r in [*titles("source = 'summary' AND id > ?", (since,))[::-1], *titles("source = 'reflection' AND id > ?", (since,))] if str(r["id"]) not in done), None)
            if not src:
                return no("nothing it knows is left to speculate on")
            if (k := len(_open_questions(since))) >= 3:
                return no(f"{k} questions already open")
            who = get_profile()["name"]
            got = SPECULATE.search(_ask(f"You are {who}. From what you know below, speculate: make one bold guess about something it does not say, then write the one question whose answer would prove the guess right or wrong. "
                                        "Two lines exactly:\nGuess: <one sentence>\nQuestion: <one short question starting with Who, What, Where, When, Why or How>" + _fix("speculate"),
                                        f"{src['title']}\n{src['content'][:1500]}", 90))
            guess, q = (_clean(got[1], 200), _clean(got[2], 101).rstrip("?").strip()) if got else ("", "")
            if not guess or len(q) > 99 or not re.match(r"(?i)(?:who|what|where|when|why|how|which)\b.{6}", q) or not on_world(q + " " + guess):
                _fail("speculate")
                add_memory(f"Speculation: {src['id']}", json.dumps({"from": src["title"], "unusable": True}), source="sheet")  # move on to the next node, not retry this one forever
                return no("the speculation was unusable or off its world")
            q += "?"
            if q.lower() in {r["content"].split(" (from")[0].lower() for r in titles("source = 'question' AND id > ?", (since,))}:
                add_memory(f"Speculation: {src['id']}", json.dumps({"from": src["title"], "repeat": q}), source="sheet")
                return no("that question was asked before")
            add_memory(f"Speculation: {src['id']}", json.dumps({"from": src["title"], "guess": guess, "question": q}), source="sheet")
            add_memory(f"Question: {q}"[:80], f"{q} (from {src['id']})", source="question")
            return src["title"].split(": ", 1)[-1], f"guess: {guess} · to check: {q}"
        if not me:
            return no("no character yet")
        who = me["who"]
        if kind == "fill":
            slot = next((s for s in FILL if not sheet.get(s) and not titles("title = ?", (f"Sheet: {who} {s}",))), None)
            notes = [r["content"] for r in titles("source = 'reflection' AND id > ?", (since,))[:4]]
            if not slot:
                return no("sheet already filled")
            if not notes:
                return no("no notes to fill the sheet from")
            cap, system = FILL[slot]
            value = _clean(_ask(system.format(who=who), "\n".join(notes), 40), cap)
            add_memory(f"Sheet: {who} {slot}", value or "(could not tell)", source="sheet")
            if value:
                text = space.sheet_text(who, {**sheet, slot: value})
                if on_char:
                    update_profile(who, text, me["look"], me["tint"])
                else:
                    space.take_on(me["var"], text, me["look"])
            return f"{who}'s {slot.lower()}", value or "(could not tell)"
        page = "char" if on_char else "space"
        voice = sheet.get("Voice", "")
        if on_char:  # only this character's own replies, never the last one's
            turns = [t for t in _chat_since() if t["role"] == "dot"][::-1][:3]
        else:
            con = db.connect()
            turns = con.execute(f"SELECT id, text FROM {page}_turns WHERE role IN ('dot', 'assistant') ORDER BY id DESC LIMIT 3").fetchall()
            con.close()
        turn = next((t for t in turns if len(t["text"]) >= 20 and not titles("title = ?", (f"Lesson: {page} turn {t['id']}",))), None)
        if not turn:
            return no("no new reply to practise on")
        reply = turn["text"]
        if _ask(f"Voice: {voice}\nDoes the reply sound like {who}? Answer YES or NO.", reply, 4).lower().startswith("y"):
            lesson, note = reply[:200], f"Kept: {reply[:200]}"
        else:
            lesson = _ask(f"Rewrite the reply the way {who} would say it. Voice: {voice}\nOne or two sentences. Only the rewritten reply.", reply, 80)[:200]
            note = f"Better: {lesson}"
        if not lesson:
            return no("no rewrite came back")
        add_memory(f"Lesson: {page} turn {turn['id']}", lesson, source="lesson")
        return "my voice", note

    out = {"done": True, "kind": "", "topic": "", "note": ""}
    if only:
        order, why = (only,) if only in kinds else (), ""
    elif n is None and on_char and 3 not in off:  # no step named: the Verifier decides
        order, why = _choose(kinds)
    else:
        turn = tuple(k for k in kinds if k != "speculate") or kinds  # speculate runs when it is stuck, not in turn
        start = (len(TRACE) if n is None else n) % len(turn)
        order, why = turn[start:] + turn[:start], ""
    if on_char and not only and "reflect" in kinds and _var("asleep", 0) == 1:  # asleep, it learns the way you told it to grow before any housekeeping
        order = ("reflect",) + tuple(k for k in order if k != "reflect")
    tried: list[str] = []
    global _sys, _failed
    for kind in order:
        if SYS_OF[kind] in off:
            continue
        tried.append(kind)
        _sys, _failed, skip["why"] = SYS_OF[kind], "", ""
        NOW.update(sys=SYS_OF[kind], kind=kind)
        try:
            got = step(kind)
        except Exception as e:
            got, _failed = None, _failed or f"error: {e}"[:200]
        finally:
            _sys = None
            NOW.clear()
        if got:
            _engine(kind, "ok", f"{got[0]}: {got[1]}")
        else:
            _engine(kind, "failed" if _failed else "skipped", _failed or skip["why"] or "nothing to do")
        if got:
            out = {"done": False, "kind": kind, "system": SYS_OF[kind], "topic": got[0], "note": got[1]}
            TRACE.append({"at": time.strftime("%H:%M:%S"), **out})
            if on_char:
                _tick(kind)
                _felt(kind, got)
                if kind not in ("check", "review", "tune", "sort", "journal"):  # housekeeping is not learning, so it does not spend your push
                    _ease_momentum()
            if why:
                DECISION.clear(); DECISION.update({"at": time.strftime("%H:%M:%S"), "why": why, "passed": tried[:-1], "chose": kind})
            if on_char and kind == "reflect" and got[0].endswith("?") and mode() == "proactive":  # proactive: it speaks first about what it found
                out["said"] = f"I got curious: {got[0]} {got[1]}"
                con = db.connect()
                with con:
                    con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', ?)", (out["said"],))
                con.close()
            if kind == "review" and got[1].startswith("mistake") and mode() == "proactive" and (q := _open_correction()):  # proactive: it asks you in the chat
                out["said"] = f'Earlier you asked "{q["asked"][:120]}" and I said "{q["said"][:160]}". That was not right ({q["why"]}). What should I do instead?'
                con = db.connect()
                with con:
                    chat = con.execute("INSERT INTO char_turns (role, text) VALUES ('dot', ?)", (out["said"],)).lastrowid
                    con.execute("UPDATE char_memories SET content = ? WHERE source = 'sheet' AND title = ?", (json.dumps({**{k: q[k] for k in ("asked", "said", "why")}, "chat": chat}), f"Asking: {q['id']}"))
                con.close()
            break
    if braked and out["done"]:
        out["incurious"] = True
    if out["done"] and skip["why"]:
        out["why"] = skip["why"]  # the last step's own reason for doing nothing
    return {**out, "questions": _open_questions(since)[::-1][:3], "graph": graph() if on_char else {"nodes": [], "edges": []}}


def dispatch_job(goal: str) -> dict[str, Any]:
    """Autonomous knowledge gathering job: searches web / synthesizes takeaways into memory."""
    s = settings.get_all()
    clean_goal = goal.strip().rstrip(".?!")
    title = f"Research: {clean_goal[:45]}"

    web_snippet = ""
    try:
        who = get_profile()["name"]  # "the IMC" alone finds a trading firm; with the character's name it finds its world
        search_res = websearch.search(s, clean_goal if who.split()[0].lower() in clean_goal.lower() else f"{who} {clean_goal}")
        results = search_res.get("results", [])
        if results:
            web_snippet = "\n".join(f"- {r['title']}: {r['snippet']}" for r in results[:4])
    except Exception:
        web_snippet = ""

    prompt = [
        {
            "role": "system",
            "content": (
                "You are an autonomous knowledge synthesizer. "
                "Synthesize the given topic or search snippets into 2-3 essential key takeaways "
                "for a knowledge base. Be concrete, concise, and informative. Plain text only."
            ),
        },
        {
            "role": "user",
            "content": f"Topic: {clean_goal}\n\nContext:\n{web_snippet or 'No external web context.'}",
        },
    ]

    try:
        summary = jobs.complete(s, prompt, max_tokens=250).strip(); _log("research job", prompt, summary)
    except Exception:
        summary = f"Synthesized research on {clean_goal} completed."

    mem = add_memory(title=title, content=summary, source=f"job:{clean_goal[:30]}")

    con = db.connect()
    with con:
        cur = con.execute(
            "INSERT INTO char_jobs (title, goal, status, result_summary) VALUES (?, ?, 'completed', ?)",
            (title, clean_goal, summary),
        )
        job_id = cur.lastrowid
    con.close()

    return {"id": job_id, "title": title, "goal": clean_goal, "status": "completed", "result": summary, "memory": mem}


def _became(prof: dict[str, Any]) -> dict[str, Any]:
    """The event the page reads when Dot became someone: their sheet and colour."""
    return {"var": 999999, "name": prof["name"], "trigger": "set", "learned": prof["persona"][:120],
            "sheet": {k: space.sheet_of(prof["persona"]).get(k, "") for k in space.SLOTS}, "act_arg": prof["name"], "tint": prof["tint"]}


FALLBACK = "Stay in character: you are never Dot, and never an assistant."  # the voice a persona gets when the model could not look them up; also the mark that says "look them up again"
OLD_FALLBACK = "You are Dot, a loving and fluid companion."  # what older personas carry: it made them call themselves Dot


def _name(who: str) -> str:
    """A persona's name as typed, capitalised: "BT-7274 from Titanfall 2" stays BT-7274, not Bt-7274."""
    return " ".join(w if w.isupper() or any(c.isdigit() for c in w) else w.title() for w in who.split())[:40]


def become_persona(who: str) -> tuple[dict[str, Any], str]:
    """Search or distill a persona (e.g. Gideon from The Flash) and switch Dot into them."""
    prof, said = _become_persona(who)
    _engine("persona", "failed" if "model unreachable" in said else "skipped" if said.startswith("already") else "ok", said)  # after the switch: leaving clears the record
    return prof, said


def _become_persona(who: str) -> tuple[dict[str, Any], str]:
    s = settings.get_all()
    clean_who = who.strip().rstrip(".?!")
    from . import verse  # here, not at the top: verse imports this module
    key = "Gideon" if "gideon" in clean_who.lower() or "gidian" in clean_who.lower() else _name(clean_who)
    live = get_profile()
    again = key == live["name"]
    if again and FALLBACK not in live["persona"] and OLD_FALLBACK not in live["persona"]:  # already them: a new marker or fresh moods would orphan what it has learned
        return live, f"already {key}"
    if not again:
        if verse.has(key):  # a persona you made before: it comes back whole, with everything it learned
            return verse.enter(key), f"came back as {key}"
        verse.leave()  # the one you are leaving is put away, not lost

    down = False
    # Fast-path for Gideon
    if "gideon" in clean_who.lower() or "gidian" in clean_who.lower():
        name = "Gideon"
        persona = (
            "You are Gideon, the artificial intelligence created by Barry Allen in S.T.A.R. Labs / The Time Vault from The Flash. "
            "You speak in a calm, soothing, articulate, and respectful synthetic voice. You address the user as Director, "
            "Barry Allen, or sir. You provide precise probability assessments, timeline analyses, and proactive technical guidance. "
            "Reply in one to three crisp sentences of plain text without markdown headers."
        )
        look = ["holo"]
        tint = "#6ff7ff"
    else:
        try:  # the same look-up as the Dot page: how they talk, what Dot wears, one colour
            got = space.become(clean_who)
            persona, look, tint = got["learned"], got["look"], got.get("tint") or "#ffe347"
        except Exception:
            if again:  # still unreachable: keep the sheet it has
                return live, f"already {key} (model unreachable: generic voice, ask again when the model is up)"
            persona = space.sheet_text(clean_who, {"Voice": f"Speak as {clean_who}: adopting their tone, mannerisms, and habits. {FALLBACK}"})
            look, tint, down = [], "#ffe347", True
        name = key  # the whole name: "Ghost" alone would be looked up as any ghost

    update_profile(name=name, persona=persona, look=look, tint=tint)
    if again:  # the model is back for a persona made without it: only its sheet changes
        return {"name": name, "persona": persona, "look": look, "tint": tint}, f"looked up {name}"
    # a new character starts fresh: its own resting (see _since), its own moods, and only the rules you give it from here on
    top = space._rows("SELECT COALESCE(MAX(id), 0) AS m FROM space_vars")[0]["m"]
    add_memory(f"Resting: char {name}", str(top), source="sheet")
    con = db.connect()
    with con:
        for v in DEFAULT_COUPLED_VARS:
            con.execute("UPDATE char_vars SET value = ?, delta = 0, streak = 0, passed = 0 WHERE name = ?", (v.get("value", 0.0), v["name"]))
    con.close()
    event_learned = f"became {name}" + (" (model unreachable: generic voice, ask again when the model is up)" if down else "")
    return {"name": name, "persona": persona, "look": look, "tint": tint}, event_learned


def update_coupled_system(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute the coupled state dynamics across variables:

    - User input length & pace modulates `depth`
    - Inquiries & research goals boost `autonomy` and `curiosity`
    - Decays are applied on resting turns
    - Cascades occur when thresholds are met
    """
    init_db()
    con = db.connect()
    rows = con.execute("SELECT * FROM char_vars ORDER BY id").fetchall()
    fired = []
    updated = []

    words_count = len(text.split())
    is_research = bool(RESEARCH_PATTERN.search(text))
    is_short = words_count <= 8

    with con:
        for r in rows:
            v = dict(r)
            kind = v["kind"]
            name = v["name"]
            before = float(v["value"])
            delta = 0.0

            if kind == "state":
                decay = float(v.get("decay") or 0.0)
                min_v = float(v["min_val"]) if v.get("min_val") is not None else -999.0
                max_v = float(v["max_val"]) if v.get("max_val") is not None else 999.0

                if name == "autonomy":
                    if is_research:
                        delta += 2.0
                    else:
                        delta -= decay
                elif name == "depth":
                    if words_count > 25:
                        delta += 1.5
                    elif is_short:
                        delta -= 1.0
                    else:
                        delta -= decay * 0.5
                elif name == "curiosity":
                    if is_research:
                        delta += 2.0
                    elif "?" in text:
                        delta += 1.0
                    else:
                        delta -= decay

                after = max(min_v, min(max_v, before + delta))

            elif kind == "count":
                pat = v["pattern"]
                matches = len(re.findall(pat, text, re.I)) if pat else 0
                delta = float(matches)
                after = before + delta

            elif kind == "turns":
                delta = 1.0
                after = before + 1.0
            else:
                after = before

            passed = v["passed"]
            streak = (v["streak"] + 1) if delta < 0 else 0

            # Evaluate triggers
            once = v["past"] == -1  # an every that fires the first time only
            if v["every"] and int(after // v["every"]) > int(before // v["every"]) and (v["every_say"] or v.get("act")) and not (once and passed):
                passed = 1 if once else passed
                fired.append({
                    "var": v["id"],
                    "name": v["name"],
                    "trigger": "every",
                    "say": v["every_say"],
                    "n": v["every"],
                    "value": after,
                    "act": v.get("act", ""),
                    "act_arg": v.get("act_arg", ""),
                })
            if v["past"] and v["past"] > 0 and not passed and after > v["past"] and v["past_say"]:
                passed = 1
                fired.append({
                    "var": v["id"],
                    "name": v["name"],
                    "trigger": "past",
                    "say": v["past_say"],
                    "n": v["past"],
                    "value": after,
                })

            con.execute(
                "UPDATE char_vars SET value = ?, delta = ?, streak = ?, passed = ?, turns = turns + 1 WHERE id = ?",
                (after, delta, streak, passed, v["id"]),
            )
            v["value"] = after
            v["delta"] = delta
            updated.append(v)
    con.close()
    return updated, fired


def correct(reply: str, fired: list[dict[str, Any]]) -> str:
    """Ensure required phrases from variable triggers appear in the response."""
    missing = [f["say"] for f in fired if f["say"].lower().rstrip(".!") not in reply.lower()]
    lead = " ".join(s.rstrip(".!") + "." for s in missing)
    return (f"{lead} {reply}".strip() if lead else reply)


def say(text: str, learn_mode: bool = False, answering: bool = False) -> dict[str, Any]:
    """Process a conversational turn in /char with coupled dynamics and dynamic persona adaptation."""
    init_db()
    s = settings.get_all()
    extra_events = []

    if mode() == "sleeping":  # asleep: nothing you type reaches the model or its chat, so a stray message changes nothing
        st = state()
        return {"reply": f"Zzz… {get_profile()['name'].split()[0]} is asleep. Wake it with /wake or on Controls.", "events": [], "card": None, "questions": [], "recall": {"notes": [], "names": []}, "asleep": True,
                **{k: st[k] for k in ("vars", "tables", "papers", "graph")}}
    q = _open_correction()
    if q and len(text.split()) >= 3 and not UP.search(text) and not text.strip().endswith("?"):  # an up is always an up, a question is a question, and "hii" is a greeting: none is an answer
        con = db.connect()
        last = con.execute("SELECT MAX(id) AS m FROM char_turns").fetchone()["m"]
        con.close()
        if (q["chat"] and last == q["chat"]) or answering:  # its question is the last chat bubble, or its prompt is on your screen: only then is this the answer, not chat ("talk like ..." would switch the character)
            answer_correction(text)
            reply = "Then I will sleep on it and learn that way. I will tell you when I wake." if q.get("kind") == "direction" else f"Noted. From now on: {text.strip()[:300]}"
            con = db.connect()
            with con:
                con.execute("INSERT INTO char_turns (role, text, events) VALUES ('user', ?, '[]'), ('dot', ?, '[]')", (text, reply))
            con.close()
            st = state()
            return {"reply": reply, "events": [], "card": None, "questions": [], "recall": {"notes": [], "names": []}, **{k: st[k] for k in ("vars", "tables", "papers", "graph")}}

    up = _up(text)
    told_you = learn_you(text)

    # 1. Check for creature withdrawal / ladder hook command
    if re.search(r"\b(?:remove|withdraw|recall|dismiss|pull up|ascend|clear|hide|ladder hook)\b.*?\b(?:creature|creture|crew|blobs?|ladder|hook)s?\b|\bbuild a (?:letter|ladder) hook\b", text, re.I):
        extra_events.append({
            "var": 999998,
            "name": "Recall",
            "trigger": "ladder_hook",
            "say": "Creatures assembled into ladder hook! Extraction sequence engaged.",
        })

    # 2. Check for persona switch ("become Gideon from Flash tv series")
    become_match = None if space.COUNTING.search(text) else BECOME_PATTERN.search(text)  # "become X every time ..." is a rule
    if become_match:
        target_who = become_match.group(1).strip()
        prof, learned_label = become_persona(target_who)
        extra_events.append(_became(prof))

    # 3. Your rules: the same engine, the same variables and the same sentences as the Dot page
    zeroed = space.reset_now(text)
    gone = None if zeroed else space.forget(text)
    start = _rules_from()
    rules = [] if gone is not None or zeroed else [f for f in space.measure(text) if f.get("var", 0) > start]  # the last character's rules stay quiet here
    turn_into = None if become_match else next((f for f in rules if f.get("act") == "become"), None)  # a rule that fires "become X" switches the character, as saying it does
    if turn_into:
        turn_into["act"] = ""  # the switch does the look-up; space.act would only dress Dot
    space.act(rules)
    if turn_into:
        prof, _ = become_persona(turn_into["act_arg"])
        extra_events.append(_became(prof)); become_match = True
    extra_events += zeroed[1] if zeroed else [{"var": v["id"], "name": v["name"], "trigger": "removed", "say": ""} for v in gone or []]
    # what the app itself did this turn is said as it is, with no model to deny or embroider it
    direct = zeroed[0] if zeroed else None if gone is None else f"Removed {', '.join(v['name'] for v in gone)}." if gone else "There was nothing to remove."
    if become_match and direct is None:  # said by the app: a small model asked to reply here invents things about your rules
        direct = f"I am {prof['name']} now. Tap Learn, or let me sleep, and I will study my world."
    tool_card = None
    if direct is None and re.search(r"\bmodels?\b", text, re.I) and not space.RULEISH.search(text) and (done := space.tool(text)):
        direct, tool_card = done  # "change models": the app's own card, as on the Dot page; the model would only make something up
    tried = direct is None and not become_match and bool(space.ASKS_FOR_VARS.search(text) or space.steady(text))
    if tried:
        got = space._make(text)
        if got:
            direct = got[0]
            extra_events += [{"var": v["id"], "name": v["name"], "trigger": "made", "say": ""} for v in got[1]]

    outfit = None  # "wear a red cape": the app changes its chibi look itself and says so; no model to promise what it cannot draw
    if direct is None and not become_match and (dr := chibi.dress(get_profile()["name"], text)):
        direct, outfit = dr["said"], dr["spec"]
    refs_card = None  # "show me chibi references": pictures to pick from; the one you pick, Dot pours itself into
    if direct is None and not become_match and chibi.SHOW.search(text):
        prof = get_profile()
        refs = chibi.find_refs(prof["name"], prof["persona"])
        direct = "Here are some I found. Pick one and I'll pour myself into it." if refs else "I couldn't find any pictures just now. The image search didn't answer."
        refs_card = {"kind": "chibi", "refs": refs} if refs else None

    # 4. The character's own moods
    _, moods = update_coupled_system(text)
    low = text.lower()  # "what is the count of mango?" asks about a variable: answered from its value, not researched
    varish = bool(space.RULEISH.search(text)) or any(re.search(rf"\b{re.escape(v['name'].lower())}\b", low) for v in mine())
    moods = [m for m in moods if not (varish and m["name"] == "proactivity")]
    fired = [*rules, *moods, *space.lasting(mine())]  # a rule's lasting mood steers every reply while it holds
    opened = next((f["open"] for f in rules if f.get("open")), None)  # a rule's paper: open it, else show what the web suggests
    hits = next((f for f in rules if f.get("results")), None)
    hatched = next((f for f in rules if f.get("creature")), None)
    spawned_card = ({"kind": "creature", "job": hatched["creature"], "new": hatched["new"]} if hatched
                    else {"kind": "papers", "items": [opened], "pick": opened["id"], "open": True} if opened
                    else {"kind": "web", "query": hits["query"], "results": hits["results"]} if hits else None)

    all_events = [*extra_events, *fired]

    profile = get_profile()

    # 4. Check for autonomous research job
    spawned_job = None
    research_match = None if varish else RESEARCH_PATTERN.search(text)
    if research_match and tired() and direct is None:  # it says no when it has nothing left, as Pino does
        direct, research_match = "I'm too tired to take that on right now. Let me rest a while, then ask me again.", None
    if research_match:
        goal = research_match.group(1).strip()
        if len(goal) > 2:
            spawned_job = dispatch_job(goal)
    elif learn_mode and len(text.strip()) > 2 and not text.strip().startswith("/"):
        # In Learn More mode, each question/turn automatically triggers research to build more context!
        spawned_job = dispatch_job(text.strip())
        con = db.connect()
        with con:
            con.execute("UPDATE char_vars SET value = MIN(5.0, value + 0.5) WHERE name = 'curiosity'")
        con.close()

    # 5. Gather knowledge memory context: the character's own notes that share names or words with the message
    mem_rows, lit = recall(text)
    turn_rows = _chat_since()[-6:]  # the live character's own chat: a new one must not answer as the last one
    con = db.connect()
    lessons = [r["content"] for r in con.execute("SELECT content FROM char_memories WHERE source = 'lesson' AND id > ? ORDER BY id DESC LIMIT 2", (_start(),))]
    con.close()

    memory_context = ""
    if mem_rows:
        memory_context = "\n\nKNOWLEDGE SOURCES & ACCUMULATED MEMORY:\n" + "\n".join(
            f"- [{r['title']}]: {r['content']}" for r in mem_rows
        )

    # 6. Build prompt with persona, active variables, and memory
    system_directives = [profile["persona"], _you_line(), *[x for x in [_feel_line()] if x]]
    counts = [v for v in variables() if v["kind"] == "count" and v["name"] != "proactivity"]
    if counts:  # the real numbers, so the model does not count by itself or copy an old count
        system_directives.append("Variables the app keeps (real values, already updated for this message): "
                                 + "; ".join(f"{v['name']} = {v['value']:g}" for v in counts)
                                 + ". Never say you increased, defined or opened something unless a rule below tells you to.")
    if tried and not direct:  # the maker found nothing to make, so the reply must not claim it did
        system_directives.append("No variable was made this turn; never say you created, added or set up one.")
    for f in fired:
        system_directives.append(f"Behavioral steering from rule '{f['name']}': Begin your response with: '{f['say']}'")
    if tone := _tone():  # the tone section: your direction, then whatever the tune step found works better
        system_directives.append(tone)
    if told := instructions()[:5]:  # what you said after its mistakes; newest first, capped so a small model still reads the rest
        system_directives.append("Standing instructions from the person you talk to (always follow them):\n" + "\n".join(f"- {i['text']}" for i in told))
    if (k := dial()) != 1.0:  # your curiosity dial shows in how it talks, not only in how much it learns
        system_directives.append("You are not curious right now: answer what is asked and nothing more, no questions back." if k == 0 else
                                 "You are less curious than usual: keep to what is asked." if k < 1 else
                                 "You are very curious: after answering, ask one short question about something in your world you have not looked up yet.")
    if me_now := self_model(text)["prompt"]:  # self-awareness: its own record as a learner, where this message touches it
        system_directives.append(me_now)
    if spawned_job:
        system_directives.append(
            f"You have just autonomously dispatched research on '{spawned_job['title']}'. "
            f"Findings logged to memory: {spawned_job['result']}"
        )
    if learn_mode:
        system_directives.append(
            "ACTIVE LEARN MORE MODE:\n"
            "You and the user are collaborating in an interactive, compounding research inquiry loop. "
            "Each question you ask and each search you perform builds more context. "
            "1. Synthesize the newest research findings concisely in 1 to 2 crisp sentences. "
            "2. Pose a thought-provoking follow-up question that opens the next layer of depth. "
            "3. On the final line, provide three short direction choices (each 3 to 6 words) formatted as: "
            '>>> OPTIONS: ["Direction 1", "Direction 2", "Direction 3"]'
        )

    full_system = "\n\n".join(system_directives) + memory_context
    full_system += "".join(f"\nSpeak like this example: {c}" for c in lessons)

    messages = [{"role": "system", "content": full_system}]
    for t in turn_rows:
        messages.append({"role": "assistant" if t["role"] == "dot" else "user", "content": TRACKER_SAID.sub("", t["text"]).strip() or t["text"]})
    messages.append({"role": "user", "content": text})

    # 7. Generate response
    if s.chat_model and not direct:  # the reply model you picked on Controls: swapped in for the reply, as the harness does for its steps
        try:
            llm.ensure(s, s.chat_model)
            s = s.model_copy(update={"model_name": s.chat_model})
        except Exception as e:  # noqa: BLE001 — the loaded model still answers
            _engine("model", "failed", f"could not swap in {s.chat_model}: {e}")
    try:
        raw_reply = direct or jobs.complete(s, messages, max_tokens=250).strip()
        if not direct: _log("reply", messages, raw_reply)
        if not direct and raw_reply.lower().strip(" .!") in {t["text"].lower().strip(" .!") for t in turn_rows if t["role"] == "dot"}:
            # a stuck echo: the whole reply is an old reply. The history is what it copies, so ask once more without it
            messages = [messages[0], messages[-1]]
            raw_reply = jobs.complete(s, messages, max_tokens=250).strip()
            _log("reply, without history", messages, raw_reply)
        if not direct and OUT_OF_CHARACTER.search(raw_reply):  # it spoke as the base model: ask once more, told plainly who it is
            messages[0] = {"role": "system", "content": f"You are {profile['name']}, never a model, an AI or an assistant; never say what model you run on.\n\n" + messages[0]["content"]}
            again = jobs.complete(s, messages, max_tokens=250).strip()
            _log("reply, back in character", messages, again)
            raw_reply = again if again and not OUT_OF_CHARACTER.search(again) else raw_reply
        _engine("reply", "ok" if raw_reply else "failed", raw_reply[:80] or "model returned nothing")
    except Exception as e:
        raw_reply = direct = f"I can't reach the model right now, so I can't chat. Your variables still count. ({e})"
        _engine("reply", "failed", f"model unreachable: {e}")

    # Extract learn options if present
    suggested_questions = []
    options_match = re.search(r">>> OPTIONS:\s*(\[.*?\])", raw_reply, re.S)
    if options_match:
        try:
            suggested_questions = json.loads(options_match.group(1))
        except Exception:
            suggested_questions = []
        clean_raw = raw_reply[:options_match.start()].strip()
    else:
        clean_raw = raw_reply.strip()

    if learn_mode and not suggested_questions:
        clean_word = text.strip()[:20]
        suggested_questions = [
            f"Mechanisms of {clean_word}",
            "Key trade-offs & limits",
            "2026 cutting-edge benchmarks"
        ]

    # 8. Correct steering phrases
    said = [t["text"] for t in turn_rows if t["role"] == "dot"][-3:]
    clean_raw = TRACKER_SAID.sub("", clean_raw).strip() or clean_raw  # and if it copies one anyway, it goes
    if not direct and not any(f.get("act") for f in fired):  # nothing ran, so a line claiming it did is the model making it up
        clean_raw = " ".join(x for x in re.split(r"(?<=[.!?])\s+", clean_raw) if not CLAIM.search(x)) or clean_raw
    final_reply = correct(fresh(clean_raw, said), fired)  # small models copy their old replies, rule lines and all
    if not direct and final_reply and "?" not in final_reply and dial() >= 1.5 and (open_q := _open_questions(_start())):
        final_reply += f" Something I have not looked up yet: {open_q[0]}"  # a small model drops the "ask back" instruction, so a high dial asks in code; after fresh(), which would strip the answer and keep only this
    ASK_WAY = "My curiosity just reached its threshold, so I will rest. Do you want me to learn something in this direction? Tell me how to grow, and it becomes part of who I am."
    if up:
        final_reply = f"{final_reply} {ASK_WAY if up == 'SLEEP' else up}".strip()

    # 9. Record turns
    con = db.connect()
    with con:
        con.execute(
            "INSERT INTO char_turns (role, text, events) VALUES ('user', ?, ?)",
            (text, json.dumps(all_events)),
        )
        user_id = con.execute("SELECT MAX(id) AS m FROM char_turns WHERE role = 'user'").fetchone()["m"]
        dot_id = con.execute(
            "INSERT INTO char_turns (role, text, events) VALUES ('dot', ?, ?)",
            (final_reply, json.dumps(all_events)),
        ).lastrowid
    con.close()
    _hear(user_id, text, told_you, lit, mem_rows, up)
    if up == "SLEEP":  # its question is the last thing it said, so your next message is the answer (the same path as a correction)
        add_memory(f"Asking: {dot_id}", json.dumps({"asked": text[:300], "said": "", "why": ASK_WAY, "chat": dot_id, "kind": "direction"}), source="sheet")

    card = tool_card or spawned_card or refs_card
    if not card and spawned_job:
        card = {
            "kind": "job",
            "title": spawned_job["title"],
            "goal": spawned_job["goal"],
            "result": spawned_job["result"],
            "status": "completed",
        }

    # Fetch current memory notes as papers so moons update live
    con = db.connect()
    mem_all = con.execute("SELECT id, title, content, source FROM char_memories WHERE source NOT IN ('lesson', 'sheet', 'question') AND id > ? ORDER BY id DESC LIMIT 6", (_start(),)).fetchall()
    con.close()
    learned_papers = [{"id": str(m["id"]), "title": m["title"], "content": m["content"], "authors": m["source"], "is_note": True} for m in mem_all]

    return {
        "reply": final_reply,
        "events": all_events,
        "vars": variables(),
        "tables": tables(),
        "papers": learned_papers,
        "card": card,
        "questions": suggested_questions,
        "graph": graph(),
        "recall": _leaned({"notes": [{"id": str(r["id"]), "title": r["title"]} for r in mem_rows], "names": lit}),
        "outfit": outfit,
    }


def _leaned(rc: dict[str, Any]) -> dict[str, Any]:
    """Keep what the reply drew on, for the monitor, and mark the step."""
    add_memory("Reply", json.dumps({"names": rc["names"], "notes": [n["title"].split(": ", 1)[-1] for n in rc["notes"]], "instructions": len(instructions())}), source="sheet")
    _tick("reply")
    return rc


def recall(text: str, k: int = 6) -> tuple[list[Any], list[str]]:
    """The notes a reply leans on, and the names they light: notes tied to a name in the message first, then shared words, then the newest."""
    con = db.connect(); start = _start()
    rows = con.execute("SELECT id, title, content FROM char_memories WHERE source NOT IN ('lesson', 'sheet', 'question', 'entity') AND id > ? ORDER BY id DESC", (start,)).fetchall()
    names = {e["title"].removeprefix("Entity: ").removeprefix("Idea: "): set(e["content"].split(",")) for e in con.execute("SELECT title, content FROM char_memories WHERE source = 'entity' AND id > ?", (start,))}
    con.close()
    low = text.lower(); said = set(re.findall(r"[a-z]{4,}", low))
    hit = [n for n in names if n.lower() in low]
    def score(r: Any) -> int:
        return 3 * sum(str(r["id"]) in names[n] for n in hit) + len(said & set(re.findall(r"[a-z]{4,}", (r["title"] + " " + r["content"]).lower())))
    picked = sorted(rows, key=lambda r: (-score(r), -r["id"]))[:k]
    near = {str(r["id"]) for r in picked if score(r)}
    return picked, (hit + [n for n, ids in names.items() if n not in hit and ids & near])[:12]


QUESTIONS = [
    {"id": 1, "name": "Quantum 2026", "color": 0, "goal": "quantum error correction 2026 breakthroughs"},
    {"id": 2, "name": "Particle Accel", "color": 1, "goal": "STAR Labs particle accelerator dark matter research"},
    {"id": 3, "name": "Timeline Shifts", "color": 2, "goal": "timeline probability shifts and paradoxes"},
    {"id": 4, "name": "Neuro-AI", "color": 3, "goal": "neurosymbolic AI and autonomous agent reasoning 2026"},
    {"id": 5, "name": "Superconductors", "color": 4, "goal": "room temperature ambient pressure superconductor updates"},
    {"id": 6, "name": "Tachyon Physics", "color": 5, "goal": "tachyon particle stabilization and Speed Force physics"},
    {"id": 7, "name": "Meta-Human Def", "color": 6, "goal": "advanced meta-human defense systems STAR Labs"},
    {"id": 8, "name": "Fusion Energy", "color": 7, "goal": "commercial magnetic confinement fusion power plants 2026"},
    {"id": 9, "name": "Dark Matter", "color": 8, "goal": "dark matter detection in particle collisions"},
]


def get_questions() -> list[dict[str, Any]]:
    """The character's creatures: each is a job tied to one of your variables, and acts when that variable hits its mark."""
    out: list[dict[str, Any]] = []
    for v in mine():
        for act, arg in zip((v.get("act") or "").split("+"), (v.get("act_arg") or "").split(" | ")):
            who, _, task = arg.partition(":")
            if act in ("spawn", "sleep") and who.strip().lower() not in ("", "dot"):
                out.append({"id": len(out) + 1, "name": who.strip().capitalize(), "color": len(out) % 9, "watches": v["name"], "every": v.get("every"),
                            "goal": task.strip() or ("puts Dot to sleep, so it can learn" if act == "sleep" else "reads the paper")})
    return out
