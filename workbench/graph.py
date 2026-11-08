"""The graph: papers linked by meaning. Uses the local embedding model only.

Each paper is split into passages and embedded once. Searching embeds the query and scores every
passage. Papers whose average passage vectors are close get a suggested link. A search you keep
becomes a concept node linked to the papers you chose.
"""
import math
import re
import sqlite3
import threading
import uuid
from array import array
from typing import Any

from openai import APIConnectionError, APIError

from . import db, library, llm
from .settings import Settings

CHUNK_CHARS = 900
OVERLAP = 150
BATCH = 32
SUGGEST_MIN = 0.62   # paper-to-paper cosine needed for a suggested link (nomic-embed-text scale)
SUGGEST_TOP = 3      # at most this many suggested links per paper
AUTO_PICK = 0.62     # a search result is ticked for you at or above this score...
PICK_MARGIN = 0.08   # ...and only if it is this close to the best result (unrelated papers sit at 0.55-0.66)
DOC, QUERY = "search_document: ", "search_query: "  # nomic-embed-text task prefixes; harmless for others

_working: dict[str, str] = {}  # base_url -> embed model that answered


class GraphError(Exception):
    pass


# ---------- vectors (plain Python; fine for a personal library of a few thousand passages) ----------
# shortcut: pure-Python dot products. If search gets slow past ~20k passages, ask to add numpy.

def _unit(v: list[float]) -> array:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / n for x in v))


def _dot(a: array, b: array) -> float:
    return sum(x * y for x, y in zip(a, b))


def _blob(v: array) -> bytes:
    return v.tobytes()


def _vec(b: bytes) -> array:
    v = array("f"); v.frombytes(b)
    return v


# ---------- embedding ----------

def embed_model(s: Settings) -> str:
    """The embedding model to use: the setting, else the first listed one with "embed" that works."""
    if s.embed_model:
        return s.embed_model
    if s.base_url in _working:
        return _working[s.base_url]
    models = [m for m in llm.model_status(s)["models"] if "embed" in m.lower()]
    for m in models:
        try:
            llm.client(s, timeout=60).embeddings.create(model=m, input=["test"])
        except APIError:
            continue
        _working[s.base_url] = m
        return m
    raise GraphError("No embedding model found. Load one in Unsloth, for example nomic-embed-text.")


def embed(s: Settings, texts: list[str], model: str) -> list[array]:
    out: list[array] = []
    try:
        for i in range(0, len(texts), BATCH):
            r = llm.client(s).embeddings.create(model=model, input=texts[i:i + BATCH])
            out += [_unit(d.embedding) for d in sorted(r.data, key=lambda d: d.index)]
    except APIConnectionError:
        raise GraphError("Could not reach the model server. Is Unsloth running?")
    except APIError as e:
        raise GraphError(f"The embedding model failed: {e.message}")
    return out


# ---------- indexing ----------

def split(pages: list[str]) -> list[tuple[int, str]]:
    """(page number, passage) pairs. Passages stay inside one page and overlap a little."""
    out: list[tuple[int, str]] = []
    for n, text in enumerate(pages, 1):
        text = re.sub(r"-\n(?=[a-z])", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        start = 0
        while start < len(text):
            end = min(len(text), start + CHUNK_CHARS)
            if end < len(text):  # end on a sentence or word break
                cut = max(text.rfind(". ", start + CHUNK_CHARS // 2, end), text.rfind(" ", start + CHUNK_CHARS // 2, end))
                end = cut + 1 if cut > 0 else end
            piece = text[start:end].strip()
            if len(piece) > 40:
                out.append((n, piece))
            if end >= len(text):
                break
            start = max(end - OVERLAP, start + 1)
    return out


def needs_index(con: sqlite3.Connection, model: str) -> list[str]:
    rows = con.execute("SELECT p.id FROM papers p WHERE NOT EXISTS "
                       "(SELECT 1 FROM chunks c WHERE c.paper_id = p.id AND c.model = ?)", (model,))
    return [r["id"] for r in rows]


def index_paper(s: Settings, paper_id: str, model: str) -> int:
    pages = library.page_texts(paper_id) or []
    parts = split(pages)
    vecs = embed(s, [DOC + t for _, t in parts], model) if parts else []
    con = db.connect()
    with con:
        con.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
        if parts:
            con.executemany("INSERT INTO chunks (paper_id, idx, page, text, vec, model) VALUES (?, ?, ?, ?, ?, ?)",
                            [(paper_id, i, n, t, _blob(v), model) for i, ((n, t), v) in enumerate(zip(parts, vecs))])
        else:  # no text (a scan): mark it read so it is not tried again
            con.execute("INSERT INTO chunks (paper_id, idx, page, text, vec, model) VALUES (?, 0, 0, '', ?, ?)",
                        (paper_id, _blob(array("f")), model))
    con.close()
    return len(parts)


def index_missing(s: Settings) -> dict[str, Any]:
    model = embed_model(s)
    con = db.connect()
    todo = needs_index(con, model)
    con.close()
    for pid in todo:
        index_paper(s, pid, model)
    return {"model": model, "indexed": len(todo)}


# ---------- reading the graph ----------

def _chunks(con: sqlite3.Connection, model: str) -> list[sqlite3.Row]:
    return con.execute("SELECT paper_id, page, text, vec FROM chunks WHERE model = ? AND text != ''", (model,)).fetchall()


def suggested_links(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Each paper's average passage vector; link a paper to its nearest papers above SUGGEST_MIN."""
    sums: dict[str, list[float]] = {}
    for r in rows:
        v = _vec(r["vec"])
        acc = sums.setdefault(r["paper_id"], [0.0] * len(v))
        for i, x in enumerate(v):
            acc[i] += x
    cents = {pid: _unit(acc) for pid, acc in sums.items()}
    ids = sorted(cents)
    best: dict[tuple[str, str], float] = {}
    for a in ids:
        near = sorted(((_dot(cents[a], cents[b]), b) for b in ids if b != a), reverse=True)[:SUGGEST_TOP]
        for sim, b in near:
            if sim >= SUGGEST_MIN:
                best[tuple(sorted((a, b)))] = round(sim, 3)  # type: ignore[index]
    return [{"a": a, "b": b, "score": sc} for (a, b), sc in best.items()]


def read(s: Settings) -> dict[str, Any]:
    con = db.connect()
    papers = [dict(r) for r in con.execute("SELECT id, title, tags FROM papers")]
    concepts = [dict(r) for r in con.execute("SELECT id, label, kind FROM concepts")]
    links = [dict(r) for r in con.execute("SELECT concept_id, paper_id, page, snippet, score FROM concept_links")]
    model = s.embed_model or _working.get(s.base_url, "")
    rows = _chunks(con, model) if model else []
    indexed = {r["paper_id"] for r in rows}
    con.close()
    return {"papers": papers, "concepts": concepts, "links": links,
            "suggested": suggested_links(rows), "indexed": sorted(indexed), "model": model}


def search(s: Settings, q: str, limit: int = 8) -> dict[str, Any]:
    """Best passage per paper for a query, by meaning."""
    model = embed_model(s)
    con = db.connect()
    rows = _chunks(con, model)
    titles = {r["id"]: r["title"] for r in con.execute("SELECT id, title FROM papers")}
    con.close()
    if not rows:
        return {"results": [], "model": model}
    qv = embed(s, [QUERY + q], model)[0]
    best: dict[str, tuple[float, sqlite3.Row]] = {}
    for r in rows:
        sc = _dot(qv, _vec(r["vec"]))
        if sc > best.get(r["paper_id"], (-2.0, r))[0]:
            best[r["paper_id"]] = (sc, r)
    top = sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]
    bar = max(AUTO_PICK, top[0][1][0] - PICK_MARGIN) if top else AUTO_PICK
    return {"model": model, "results": [
        {"paper_id": pid, "title": titles.get(pid, ""), "page": r["page"], "snippet": r["text"][:320],
         "score": round(sc, 3), "pick": sc >= bar} for pid, (sc, r) in top]}


def pages_for(s: Settings, paper_id: str, question: str, most: int = 2) -> list[int]:
    """1-based pages of this paper's best-matching passages, best first. [] without an embedding model."""
    try:
        model = embed_model(s)
        con = db.connect()
        rows = con.execute("SELECT page, vec FROM chunks WHERE paper_id = ? AND model = ? AND text != ''", (paper_id, model)).fetchall()
        con.close()
        if not rows:
            return []
        qv = embed(s, [QUERY + question], model)[0]
    except GraphError:
        return []
    out: list[int] = []
    for r in sorted(rows, key=lambda r: -_dot(qv, _vec(r["vec"]))):
        if r["page"] not in out:
            out.append(r["page"])
    return out[:most]


def add_concept(label: str, links: list[dict[str, Any]], kind: str = "kept") -> str:
    cid = uuid.uuid4().hex[:12]
    con = db.connect()
    with con:
        con.execute("INSERT INTO concepts (id, label, kind) VALUES (?, ?, ?)", (cid, label, kind))
        con.executemany("INSERT INTO concept_links (concept_id, paper_id, page, snippet, score) VALUES (?, ?, ?, ?, ?)",
                        [(cid, l["paper_id"], l["page"], l["snippet"], l["score"]) for l in links])
    con.close()
    return cid


def delete_concept(cid: str) -> bool:
    con = db.connect()
    with con:
        found = con.execute("DELETE FROM concepts WHERE id = ?", (cid,)).rowcount
    con.close()
    return bool(found)


# ---------- AI-suggested ideas ----------

_suggesting = threading.Lock()


def suggest(s: Settings) -> dict[str, Any]:
    """For each paper not done yet: the chat model names its key ideas, then the embedding search
    links each idea to every paper that talks about it. They stay suggestions until you keep them.
    One run at a time: a second call waits, then finds nothing left to do."""
    with _suggesting:
        return _suggest(s)


def _suggest(s: Settings) -> dict[str, Any]:
    con = db.connect()
    todo = [dict(r) for r in con.execute(
        "SELECT id, title FROM papers WHERE id NOT IN (SELECT paper_id FROM suggest_runs)")]
    have = {r["label"].lower() for r in con.execute("SELECT label FROM concepts")}
    con.close()
    made = 0
    for p in todo:
        try:
            ideas = llm.key_ideas(s, p["title"], library.page_texts(p["id"]) or [])
        except RuntimeError as e:
            raise GraphError(str(e))
        for idea in ideas:
            if idea.lower() in have:
                continue
            hits = [r for r in search(s, idea)["results"] if r["pick"] or r["paper_id"] == p["id"]]
            if hits:
                add_concept(idea, hits, kind="suggested")
                have.add(idea.lower()); made += 1
        con = db.connect()
        with con:
            con.execute("INSERT OR IGNORE INTO suggest_runs (paper_id) VALUES (?)", (p["id"],))
        con.close()
    return {"papers": len(todo), "ideas": made}


def keep_concept(cid: str) -> bool:
    con = db.connect()
    with con:
        found = con.execute("UPDATE concepts SET kind = 'kept' WHERE id = ?", (cid,)).rowcount
    con.close()
    return bool(found)
