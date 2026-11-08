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

KINDS = ("answer", "find", "summarize", "set_date", "add_theme", "mark_done", "export", "delete", "none")
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
    k = max(2, min(8, round(n ** 0.5)))  # a small library still gets a few colours
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
    """One short shelf name per group, one model call each (small models mix up several groups in one call)."""
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    out = []
    for g in groups:
        try:
            text = primer._complete(s, [
                {"role": "system", "content": "You name one shelf in a reading library. Given the paper titles on it, "
                 "reply with one short plain name of 2 to 4 words that says what they share. Not a title from the list. "
                 'Reply as JSON: {"name": "..."}'},
                {"role": "user", "content": "\n".join(titles.get(p, "")[:90] for p in g[:10])}], schema, "shelf_name")
            a, b = text.find("{"), text.rfind("}")
            name = str(json.loads(text[a:b + 1])["name"])
        except (primer.PrimerError, ValueError, KeyError, TypeError):
            return None
        name = name.strip(" \"'.")
        name = name[:1].upper() + name[1:]
        out.append(" ".join(re.sub(r"^\s*G\d+\s*[:.)-]\s*", "", name).replace("\u2014", "-").strip(" \"'.").split()[:5])[:40])
    return out


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

TOP_PAPERS = 6       # level 1: the papers whose best passage is closest to the question
PER_PAPER = 3        # level 2: the best passages inside each of those papers
MAX_PASSAGES = 10
PASSAGE_CHARS = 650
PAPER_FLOOR = graph.AUTO_PICK - 0.12  # papers below this are not about the question at all
NEAR_BEST = 0.1      # inside a paper, keep passages this close to its best one


def passages(s: Settings, question: str, allowed: set[str] | None = None) -> list[dict[str, Any]]:
    """Cross-paper search in two levels: rank papers by their best passage, then take the best few
    passages inside each top paper. Returns [{paper_id, page, text, score}], best first.
    Raises GraphError when there is no embedding model."""
    model = graph.embed_model(s)
    con = db.connect()
    rows = graph._chunks(con, model)
    con.close()
    if allowed is not None:
        rows = [r for r in rows if r["paper_id"] in allowed]
    if not rows:
        return []
    qv = graph.embed(s, [graph.QUERY + question], model)[0]
    per: dict[str, list[tuple[float, Any]]] = {}
    for r in rows:
        per.setdefault(r["paper_id"], []).append((graph._dot(qv, graph._vec(r["vec"])), r))
    for hits in per.values():
        hits.sort(key=lambda x: -x[0])
    tops = sorted(per, key=lambda pid: -per[pid][0][0])[:TOP_PAPERS]
    out = []
    for pid in tops:
        best = per[pid][0][0]
        if best < PAPER_FLOOR:
            continue
        out += [{"paper_id": pid, "page": r["page"], "text": " ".join(r["text"].split())[:PASSAGE_CHARS], "score": round(sc, 3)}
                for sc, r in per[pid][:PER_PAPER] if sc >= best - NEAR_BEST]
    return sorted(out, key=lambda x: -x["score"])[:MAX_PASSAGES]


def _candidates(s: Settings, question: str, papers: list[dict[str, Any]],
                found: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Up to MAX_CANDIDATES papers for the question, with the passage that matched (if any)."""
    by_id = {p["id"]: p for p in papers}
    picked: list[str] = []
    snippet: dict[str, str] = {}
    for r in found:
        if r["paper_id"] in by_id and r["paper_id"] not in picked:
            picked.append(r["paper_id"]); snippet[r["paper_id"]] = r["text"][:200]
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
    "sources": {"type": "array", "items": {"type": "string"}},
    "date": {"type": "string"}, "theme": {"type": "string"}}, "required": ["reply", "kind", "papers"]}

SYSTEM = (
    "You are Dot, a small friendly helper inside a student's paper reading library. Today is {today}. "
    "You get a list of the student's papers (P1, P2, ...) and a request. Reply in one or two short, plain "
    "sentences, simple English, no dashes as punctuation. You may also get passages (S1, S2, ...) from inside "
    "the papers. Choose one kind:\n"
    "answer: they ask what the papers say, want an explanation, or want papers compared. Answer from the passages "
    "only, in 2 to 5 short sentences, and cite every claim like [S2]. Put the passages you used in sources. If the "
    "passages do not answer it, say so plainly and do not guess.\n"
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
    'Reply as JSON: {{"reply": "...", "kind": "...", "papers": [{{"p": "P1", "why": "..."}}], "sources": ["S1"], "date": "", "theme": ""}}'
)


def ask(s: Settings, question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    papers = library.list_papers(framework.load_all())
    con = db.connect()
    themes = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM themes")}
    con.close()
    try:
        found = passages(s, question)
    except graph.GraphError:
        found = []
    cands, snippet = _candidates(s, question, papers, found)
    alias = {f"P{i + 1}": p for i, p in enumerate(cands)}
    listing = "\n".join(_describe(p, a, themes) for a, p in alias.items()) or "(the library is empty)"
    back = {p["id"]: a for a, p in alias.items()}
    srcs = {f"S{i + 1}": x for i, x in enumerate(x for x in found if x["paper_id"] in back)}
    if srcs:
        listing += "\n\nPassages:\n" + "\n".join(f'{k} ({back[x["paper_id"]]}, p. {x["page"]}): {x["text"]}' for k, x in srcs.items())
    system = SYSTEM.format(today=date.today().isoformat())
    if s.dot_persona.strip():
        system += ("\nYour personality, chosen by the student: " + s.dot_persona.strip()[:300] +
                   "\nSpeak in that voice, but keep facts, citations and the JSON format exactly as above.")
    msgs = [{"role": "system", "content": system}]
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
    return clean(out, alias, srcs)


def _cite(reply: str, out: dict[str, Any], srcs: dict[str, dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Keep only citations of real passages, renumbered [1], [2] in the order they are used."""
    order: list[str] = []
    for k in re.findall(r"S\d+", reply.upper()) + [str(x).strip().upper() for x in out.get("sources") or []]:
        if k in srcs and k not in order:
            order.append(k)
    num = {k: i + 1 for i, k in enumerate(order)}

    def sub(m: re.Match[str]) -> str:
        ks = [k for k in re.findall(r"S\d+", m.group(0).upper()) if k in num]
        return "".join(f"[{num[k]}]" for k in ks)
    reply = re.sub(r"\[\s*S\d+(?:\s*[,;]\s*S?\d+)*\s*\]", lambda m: sub(m), reply, flags=re.I)
    reply = re.sub(r"\s+([.,])", r"\1", re.sub(r"\s{2,}", " ", reply)).strip()
    return reply, [{"n": num[k], "paper_id": srcs[k]["paper_id"], "page": srcs[k]["page"], "snippet": srcs[k]["text"][:220]} for k in order]


def clean(out: dict[str, Any], alias: dict[str, dict[str, Any]], srcs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Check the model's JSON: known kind, known papers only, a real date, short reasons, real citations."""
    kind = out.get("kind") if out.get("kind") in KINDS else "none"
    seen: list[dict[str, str]] = []
    for item in out.get("papers") or []:
        if not isinstance(item, dict):
            continue
        p = alias.get(str(item.get("p", "")).strip().upper())
        if p and all(x["id"] != p["id"] for x in seen):
            why = re.sub(r"\b[PS]\d+(?:'s)?\b", "", str(item.get("why", "")))  # the model's own labels mean nothing to you
            seen.append({"id": p["id"], "why": " ".join(why.replace("\u2014", ",").split()[:12]).strip(" ,.:;")})
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
    reply, sources = _cite(reply, out, srcs or {})
    if kind == "answer":
        action = {"kind": "answer", "paper_ids": list(dict.fromkeys([x["paper_id"] for x in sources] + action["paper_ids"]))}
    elif kind not in ("none", "find") and not seen:
        action = {"kind": "none", "paper_ids": []}
    return {"reply": reply, "action": action, "papers": seen, "sources": sources}


def _offline(cands: list[dict[str, Any]], snippet: dict[str, str]) -> dict[str, Any]:
    hits = [p for p in cands if p["id"] in snippet][:6] or cands[:6]
    return {"reply": "I can't reach the model, so here is what matches by title and meaning.",
            "action": {"kind": "find", "paper_ids": [p["id"] for p in hits]},
            "papers": [{"id": p["id"], "why": "matches your words"} for p in hits], "offline": True}
