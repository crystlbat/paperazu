"""The Library around Dot: papers grouped by meaning (colours and shelf rows), and Ask, where Dot
finds papers and proposes jobs. The server never acts on a job; the page runs it through the
existing endpoints. Uses the local models only.
"""
import hashlib
import json
import re
from datetime import date
from typing import Any

from . import db, framework, graph, library, primer
from .settings import Settings

KINDS = ("find", "summarize", "set_date", "add_theme", "mark_done", "export", "delete", "none")
MAX_CANDIDATES = 12
MAX_STATE = 40  # questions about state ("not opened") reach every match, up to this
STATE_WORDS = re.compile(r"not opened|never opened|unopened|no summary|without (a )?summary|not started|"
                         r"this week|next week|coming up|soon|upcoming|done|finished", re.I)


# ---------- grouping by meaning ----------

def _centroids(con: Any, model: str) -> dict[str, tuple[Any, int]]:
    """Each paper's mean passage vector (unit length) and how many passages it has."""
    sums: dict[str, list[float]] = {}
    count: dict[str, int] = {}
    for r in graph._chunks(con, model):
        v = graph._vec(r["vec"])
        acc = sums.setdefault(r["paper_id"], [0.0] * len(v))
        for i, x in enumerate(v):
            acc[i] += x
        count[r["paper_id"]] = count.get(r["paper_id"], 0) + 1
    return {pid: (graph._unit(acc), count[pid]) for pid, acc in sums.items()}


def kmeans(vecs: dict[str, Any], weight: dict[str, int]) -> list[list[str]]:
    """Deterministic k-means on unit vectors (cosine). Seeds: the paper with the most passages,
    then farthest-point. Fewer than 4 papers make one group."""
    ids = sorted(vecs)
    n = len(ids)
    if n < 4:
        return [ids] if ids else []
    k = max(2, min(8, round((n / 2) ** 0.5)))
    seeds = [max(ids, key=lambda p: (weight.get(p, 0), p))]
    while len(seeds) < k:
        seeds.append(min((p for p in ids if p not in seeds),
                         key=lambda p: (max(graph._dot(vecs[p], vecs[s]) for s in seeds), p)))
    cents = [vecs[s] for s in seeds]
    assign: dict[str, int] = {}
    for _ in range(20):
        new = {p: max(range(k), key=lambda c: graph._dot(vecs[p], cents[c])) for p in ids}
        if new == assign:
            break
        assign = new
        for c in range(k):
            members = [vecs[p] for p in ids if assign[p] == c]
            if members:
                cents[c] = graph._unit([sum(col) for col in zip(*members)])
    groups = [[p for p in ids if assign[p] == c] for c in range(k)]
    return sorted((g for g in groups if g), key=lambda g: (-len(g), g[0]))


def _key(ids: list[str]) -> str:
    return hashlib.sha1(",".join(sorted(ids)).encode()).hexdigest()


def _fallback_name(con: Any, ids: list[str], n: int) -> str:
    tags: dict[str, int] = {}
    for r in con.execute(f"SELECT tags FROM papers WHERE id IN ({','.join('?' * len(ids))})", ids):
        for t in json.loads(r["tags"] or "[]"):
            tags[t] = tags.get(t, 0) + 1
    best = max(tags.items(), key=lambda kv: (kv[1], kv[0]), default=None)
    return best[0] if best and best[1] > 1 else f"Group {n}"


def _ask_names(s: Settings, groups: list[list[str]], titles: dict[str, str]) -> list[str] | None:
    lines = "\n".join(f"G{i + 1}: " + " | ".join(titles.get(p, "")[:90] for p in g[:8]) for i, g in enumerate(groups))
    schema = {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}},
              "required": ["names"]}
    try:
        text = primer._complete(s, [
            {"role": "system", "content": "You name shelves in a reading library. For each group of paper titles, "
             "give one short plain name of 2 to 4 words that says what the papers share. No quotes, no numbering. "
             'Reply as JSON: {"names": ["...", ...]} in the same order as the groups.'},
            {"role": "user", "content": lines}], schema, "shelf_names")
        a, b = text.find("{"), text.rfind("}")
        names = json.loads(text[a:b + 1])["names"]
    except (primer.PrimerError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(names, list) or len(names) != len(groups):
        return None
    return [" ".join(str(x).replace("—", "-").split()[:5])[:40] or "" for x in names]


def library_map(s: Settings, name_groups: bool = True) -> dict[str, Any]:
    """{groups: [{id, name, hue, paper_ids}], unread: [paper_ids], reason?}. hue is a palette slot 0-7."""
    con = db.connect()
    titles = {r["id"]: r["title"] for r in con.execute("SELECT id, title FROM papers")}
    try:
        model = graph.embed_model(s)
    except graph.GraphError as e:
        con.close()
        return {"groups": [], "unread": sorted(titles), "reason": str(e)}
    cents = _centroids(con, model)
    groups = kmeans({p: v for p, (v, _) in cents.items() if p in titles}, {p: n for p, (_, n) in cents.items()})
    keys = [_key(g) for g in groups]
    cached = {r["key"]: r["name"] for r in con.execute(
        f"SELECT key, name FROM shelf_names WHERE key IN ({','.join('?' * len(keys))})", keys)} if keys else {}
    missing = [i for i, k in enumerate(keys) if k not in cached]
    if missing and name_groups:
        names = _ask_names(s, [groups[i] for i in missing], titles)
        if names:
            with con:
                for i, name in zip(missing, names):
                    if name:
                        con.execute("INSERT OR REPLACE INTO shelf_names (key, name) VALUES (?, ?)", (keys[i], name))
                        cached[keys[i]] = name
    out = [{"id": keys[i][:10], "name": cached.get(keys[i]) or _fallback_name(con, g, i + 1), "hue": i % 8,
            "paper_ids": g} for i, g in enumerate(groups)]
    con.close()
    grouped = {p for g in groups for p in g}
    return {"groups": out, "unread": sorted(p for p in titles if p not in grouped)}


# ---------- Ask ----------

def _candidates(s: Settings, question: str, papers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Up to MAX_CANDIDATES papers for the question, with the passage that matched (if any)."""
    by_id = {p["id"]: p for p in papers}
    picked: list[str] = []
    snippet: dict[str, str] = {}
    try:
        for r in graph.search(s, question, MAX_CANDIDATES)["results"]:
            if r["paper_id"] in by_id and r["score"] >= graph.AUTO_PICK - 0.1:
                picked.append(r["paper_id"]); snippet[r["paper_id"]] = r["snippet"][:200]
    except graph.GraphError:
        pass
    for p in library.list_papers(framework.load_all(), q=question):
        if p["id"] not in picked:
            picked.append(p["id"])
    words = [w for w in re.findall(r"[a-z]{4,}", question.lower())]
    for p in papers:  # title words, for short questions FTS misses ("fairness papers")
        if p["id"] not in picked and any(w in p["title"].lower() for w in words):
            picked.append(p["id"])
    state = bool(STATE_WORDS.search(question))
    if state or len(picked) < 3:
        rest = sorted((p for p in papers if p["id"] not in picked), key=library._date_key)
        picked += [p["id"] for p in rest]
    return [by_id[i] for i in picked[:MAX_STATE if state else MAX_CANDIDATES]], snippet


def _describe(p: dict[str, Any], alias: str, themes: dict[str, str]) -> str:
    bits = [f'{alias}: "{p["title"][:120]}"', f"status {p['status'].replace('_', ' ')}",
            f"steps {p['steps_done']}/{len(p['progress'])}",
            f"talk {p['presentation_date']}" if p["presentation_date"] else "no talk date",
            "opened" if p["last_opened"] else "never opened",
            f"AI summary {p.get('primer_status', 'not_made').replace('_', ' ')}"]
    names = [themes[t] for t in p["themes"] if t in themes]
    if names:
        bits.append("themes " + ", ".join(names))
    return "; ".join(bits)


ASK_SCHEMA = {"type": "object", "properties": {
    "reply": {"type": "string"},
    "kind": {"type": "string", "enum": list(KINDS)},
    "papers": {"type": "array", "items": {"type": "object", "properties": {
        "p": {"type": "string"}, "why": {"type": "string"}}, "required": ["p", "why"]}},
    "date": {"type": "string"}, "theme": {"type": "string"}}, "required": ["reply", "kind", "papers"]}

SYSTEM = (
    "You are Dot, a small friendly helper inside a student's paper reading library. Today is {today}. "
    "You get a list of the student's papers (P1, P2, ...) and a request. Reply in one or two short, plain "
    "sentences, simple English, no dashes as punctuation. Choose one kind:\n"
    "find: they want to see papers (\"show me\", \"which papers\", \"find\").\n"
    "summarize: make the AI summary for the papers.\n"
    "set_date: set the talk (presentation) date; put it in date as YYYY-MM-DD.\n"
    "add_theme: put the papers in a theme; put the theme name in theme.\n"
    "mark_done: mark the reflection done.\n"
    "export: export notes of one paper.\n"
    "delete: delete papers. Only when clearly asked.\n"
    "none: just answer.\n"
    "List the papers the request is about in papers, each with why: at most 10 words on why it fits. "
    "Use only papers from the list. If nothing fits, use kind none and say so. For a job, the reply says "
    "what you will do, naming the papers by short title. "
    'Reply as JSON: {{"reply": "...", "kind": "...", "papers": [{{"p": "P1", "why": "..."}}], "date": "", "theme": ""}}'
)


def ask(s: Settings, question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    papers = library.list_papers(framework.load_all())
    con = db.connect()
    themes = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM themes")}
    con.close()
    cands, snippet = _candidates(s, question, papers)
    alias = {f"P{i + 1}": p for i, p in enumerate(cands)}
    listing = "\n".join(_describe(p, a, themes) for a, p in alias.items()) or "(the library is empty)"
    msgs = [{"role": "system", "content": SYSTEM.format(today=date.today().isoformat())}]
    for h in history[-4:]:
        msgs += [{"role": "user", "content": h.get("q", "")[:500]}, {"role": "assistant", "content": h.get("a", "")[:800]}]
    msgs.append({"role": "user", "content": f"Papers:\n{listing}\n\nRequest: {question}"})
    try:
        text = primer._complete(s, msgs, ASK_SCHEMA, "library_ask")
        a, b = text.find("{"), text.rfind("}")
        out = json.loads(text[a:b + 1])
    except primer.PrimerError:
        return _offline(cands, snippet)
    except (ValueError, TypeError):
        return {"reply": "I got muddled there. Try asking again in other words.", "action": {"kind": "none", "paper_ids": []}, "papers": []}
    return clean(out, alias)


def clean(out: dict[str, Any], alias: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Check the model's JSON: known kind, known papers only, a real date, short reasons."""
    kind = out.get("kind") if out.get("kind") in KINDS else "none"
    seen: list[dict[str, str]] = []
    for item in out.get("papers") or []:
        if not isinstance(item, dict):
            continue
        p = alias.get(str(item.get("p", "")).strip().upper())
        if p and all(x["id"] != p["id"] for x in seen):
            seen.append({"id": p["id"], "why": " ".join(str(item.get("why", "")).split()[:12])})
    action: dict[str, Any] = {"kind": kind, "paper_ids": [x["id"] for x in seen]}
    reply = " ".join(str(out.get("reply") or "").replace("—", ",").split()) or "Done."
    if kind == "set_date":
        try:
            action["date"] = date.fromisoformat(str(out.get("date", "")).strip()).isoformat()
        except ValueError:
            action = {"kind": "none", "paper_ids": action["paper_ids"]}
            reply = "Which date? Try something like 12 November."
    if kind == "add_theme":
        name = " ".join(str(out.get("theme") or "").split())[:40]
        if not name:
            action = {"kind": "none", "paper_ids": action["paper_ids"]}
            reply = "Which theme should I put them in?"
        else:
            action["theme"] = name
    if kind != "none" and kind != "find" and not seen:
        action = {"kind": "none", "paper_ids": []}
    return {"reply": reply, "action": action, "papers": seen}


def _offline(cands: list[dict[str, Any]], snippet: dict[str, str]) -> dict[str, Any]:
    hits = [p for p in cands if p["id"] in snippet][:6] or cands[:6]
    return {"reply": "I can't reach the model, so here is what matches by title and meaning.",
            "action": {"kind": "find", "paper_ids": [p["id"] for p in hits]},
            "papers": [{"id": p["id"], "why": "matches your words"} for p in hits], "offline": True}
