"""The verse: every persona you have made, each kept whole.

/char holds one live persona in its tables. Leaving it puts everything that is its own away in one row here: its profile, its notes,
its chat, its rules and where its variables stood. Entering it again brings the same rows back under the same ids, so nothing it
learned is lost and nothing leaks between personas. Only the live one learns.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from . import char, chibi, db

SCHEMA = "CREATE TABLE IF NOT EXISTS verse (name TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT DEFAULT (datetime('now')))"


def _con() -> Any:
    char.init_db()
    con = db.connect()
    con.execute(SCHEMA)
    return con


def _marker(con: Any) -> Any:
    return con.execute("SELECT id, content, created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Resting: char %' ORDER BY id DESC LIMIT 1").fetchone()


def has(name: str) -> bool:
    con = _con()
    row = con.execute("SELECT 1 FROM verse WHERE name = ?", (name,)).fetchone()
    con.close()
    return bool(row)


def leave() -> str:
    """Put the live persona away whole. Its rows leave the live tables; ids are never reused, so they come back as they were."""
    p = char.get_profile()
    con = _con()
    if not _marker(con):  # the first persona never marked where it starts: mark it now, so only what comes after is its own
        con.close()
        char._since(True, p["name"])
        con = _con()
    m = _marker(con)
    rules_from = int(m["content"]) if (m["content"] or "").isdigit() else 0
    rows = lambda sql, args: [dict(r) for r in con.execute(sql, args)]
    data = {"profile": p, "vars": rows("SELECT * FROM char_vars", ()),
            "memories": rows("SELECT * FROM char_memories WHERE id >= ?", (m["id"],)),
            "turns": rows("SELECT * FROM char_turns WHERE created_at >= ?", (m["created_at"],)),
            "rules": rows("SELECT * FROM space_vars WHERE id > ? AND kind != 'persona'", (rules_from,))}
    with con:  # one transaction: stored and removed together, or not at all
        con.execute("INSERT INTO verse (name, data, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(name) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at", (p["name"], json.dumps(data)))
        con.execute("DELETE FROM char_memories WHERE id >= ?", (m["id"],))
        con.execute("DELETE FROM char_turns WHERE created_at >= ?", (m["created_at"],))
        con.execute("DELETE FROM space_vars WHERE id > ? AND kind != 'persona'", (rules_from,))
    con.close()
    for log in (char.TRACE, char.PROMPTS, char.DECISION):  # in-memory logs are the live persona's: the next one starts with none
        log.clear()
    return p["name"]


def enter(name: str) -> dict[str, Any]:
    """Make a stored persona the live one: the current one is put away first, then this one's rows come back."""
    if name == char.get_profile()["name"]:
        return char.get_profile()
    con = _con()
    row = con.execute("SELECT data FROM verse WHERE name = ?", (name,)).fetchone()
    con.close()
    if not row:
        raise KeyError(name)
    leave()
    d = json.loads(row["data"])
    con = _con()
    with con:
        for table, key in (("char_memories", "memories"), ("char_turns", "turns"), ("space_vars", "rules")):
            for r in d[key]:
                con.execute(f"INSERT INTO {table} ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})", tuple(r.values()))
        for v in d["vars"]:
            keep = {k: x for k, x in v.items() if k not in ("id", "name")}
            con.execute(f"UPDATE char_vars SET {', '.join(f'{k} = ?' for k in keep)} WHERE name = ?", (*keep.values(), v["name"]))
        con.execute("DELETE FROM verse WHERE name = ?", (name,))
    con.close()
    p = d["profile"]
    char.update_profile(p["name"], p["persona"], p["look"], p["tint"])
    return p


def profile(name: str) -> dict[str, Any]:
    """A stored persona's profile, as it was when it was put away."""
    con = _con()
    row = con.execute("SELECT data FROM verse WHERE name = ?", (name,)).fetchone()
    con.close()
    if not row:
        raise KeyError(name)
    return json.loads(row["data"])["profile"]


def delete(name: str) -> None:
    """Forget a stored persona for good. The live one cannot be deleted from under you: enter another first."""
    if name == char.get_profile()["name"]:
        raise ValueError("That persona is the live one. Enter another first, then delete it.")
    con = _con()
    with con:
        n = con.execute("DELETE FROM verse WHERE name = ?", (name,)).rowcount
    con.close()
    if not n:
        raise KeyError(name)
    chibi.forget(name)  # its look goes with it


def reset_all() -> None:
    """Start over: every persona goes, stored and live, with its notes, chat, rules, looks and training runs. Your Dot page is not touched."""
    leave()  # the live one's rules leave space_vars with it, so deleting the verse takes them too
    con = _con()
    with con:
        for t in ("verse", "char_memories", "char_turns", "char_vars", "char_chibi", "train_runs"):
            if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone():
                con.execute(f"DELETE FROM {t}")
        con.execute("UPDATE char_profile SET name = 'Dot', persona = ?, look = '[]', tint = '#6ff7ff' WHERE id = 1", (char.FALLBACK,))
    con.close()
    char.init_db()  # the moods come back at their starting values
    for log in (char.TRACE, char.PROMPTS, char.DECISION):
        log.clear()


def race(mems: list[dict[str, Any]]) -> dict[str, Any]:
    """How far a persona has come, from its own rows: what it learned and let in is distance, steps that did something per hour is pace,
    journal pages are laps, and corrections it took are pit stops."""
    t = lambda p: [m for m in mems if m["source"] == "sheet" and m["title"].startswith(p)]
    runs = [json.loads(m["content"] or "{}").get("outcome") for m in t("Run: ")]
    notes = sum(m["source"] == "reflection" for m in mems)
    verified = sum(m["content"] == "keep" for m in t("Checked: "))
    names = sum(m["source"] == "entity" and m["title"].startswith("Entity: ") for m in mems)
    laps, pits = len(t("Journal: ")), len(t("Answered: "))
    when = sorted(m["created_at"] for m in mems if m.get("created_at"))
    hours = max(0.25, (datetime.fromisoformat(when[-1]) - datetime.fromisoformat(when[0])).total_seconds() / 3600) if len(when) > 1 else 0.25
    ok = runs.count("ok")
    return {"distance": round(verified * 3 + notes + names * 0.5 + laps * 5, 1), "verified": verified, "notes": notes, "names": names,
            "laps": laps, "pits": pits, "steps": len(runs), "ok": ok, "pace": round(ok / hours, 1)}


def live_race() -> dict[str, Any]:
    con = _con()
    m = _marker(con)
    rows = [dict(r) for r in con.execute("SELECT title, content, source, created_at FROM char_memories WHERE id >= ?", (m["id"] if m else 0,))]
    con.close()
    return race(rows)


def personas() -> dict[str, Any]:
    """Every persona for the /verse screen: the live one with what it is doing right now, the stored ones as they were left."""
    w = char.wiring()
    live = char.get_profile()
    tr = w["trace"][0] if w["trace"] else None
    con = _con()
    m = _marker(con)
    live_rows = [dict(r) for r in con.execute("SELECT title, content, source, created_at FROM char_memories WHERE id >= ?", (m["id"] if m else 0,))]
    con.close()
    out = [{"name": live["name"], "tint": char.readable(live["tint"]), "live": True, "race": race(live_rows), "tired": char.tired(), "mode": w["mode"], "vars": [{"name": s["name"], "value": s["value"]} for s in w["signals"]],
            "chibi": chibi.cached(live["name"]), "doing": f"{tr['kind']} · {tr['topic']}" if tr else "idle", "at": tr["at"] if tr else "", "holds": w["memory"][1]["holds"], "next": w["next"]}]
    con = _con()
    for row in con.execute("SELECT name, data, updated_at FROM verse ORDER BY updated_at DESC"):
        d = json.loads(row["data"])
        notes = sum(m["source"] == "reflection" for m in d["memories"])
        names = sum(m["source"] == "entity" for m in d["memories"])
        out.append({"name": row["name"], "tint": char.readable(d["profile"]["tint"]), "live": False, "mode": "asleep", "race": race(d["memories"]),
                    "vars": [{"name": v["name"], "value": v["value"]} for v in d["vars"]] + [{"name": r["name"], "value": r["value"]} for r in d["rules"]],
                    "chibi": chibi.cached(row["name"]), "doing": "asleep", "at": row["updated_at"], "holds": f"{notes} notes · {names} names", "next": ""})
    con.close()
    return {"personas": out}
