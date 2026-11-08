"""The canvas: cards (answers, sources, notes) and the links between them, kept per paper."""
from typing import Any, Literal

import json
import math
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db, formula, graph, library, llm, marks
from .marks import MarkIn


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    who: Literal["me", "dot"]
    text: str = Field(min_length=1, max_length=4000)


class CardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["answer", "source", "note"]
    question: str = Field("", max_length=1000)
    text: str = Field("", max_length=8000)
    entries: list[Entry] = Field(default_factory=list, max_length=200)
    x: float
    y: float
    w: float = Field(ge=120, le=900)
    page: int | None = Field(None, ge=1)
    rect: list[float] | None = Field(None, min_length=4, max_length=4)
    parent: int | None = None

    _box = field_validator("rect")(MarkIn._box.__func__)


class CardEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float | None = None
    y: float | None = None
    w: float | None = Field(None, ge=120, le=900)
    text: str | None = Field(None, max_length=8000)
    entries: list[Entry] | None = Field(None, max_length=200)
    hidden: bool | None = None


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_card: int
    to_card: int


def _card(r: Any) -> dict[str, Any]:
    rect = None if r["x0"] is None else [r["x0"], r["y0"], r["x1"], r["y1"]]
    return {"id": r["id"], "kind": r["kind"], "question": r["question"], "text": r["text"], "entries": json.loads(r["entries"]),
            "x": r["x"], "y": r["y"], "w": r["w"], "page": r["page"], "rect": rect, "parent": r["parent"],
            "hidden": bool(r["hidden"]), "created_at": r["created_at"]}


def _exists(con: Any, paper_id: str) -> bool:
    return con.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is not None


def _get(con: Any, paper_id: str, cid: int | None) -> dict[str, Any] | None:
    r = con.execute("SELECT * FROM canvas_cards WHERE id = ? AND paper_id = ?", (cid, paper_id)).fetchone()
    return _card(r) if r else None


def read(paper_id: str) -> dict[str, Any] | None:
    con = db.connect()
    try:
        if not _exists(con, paper_id):
            return None
        return {"cards": [_card(r) for r in con.execute("SELECT * FROM canvas_cards WHERE paper_id = ? ORDER BY id", (paper_id,))],
                "links": [{"id": r["id"], "from_card": r["from_card"], "to_card": r["to_card"]}
                          for r in con.execute("SELECT * FROM canvas_links WHERE paper_id = ? ORDER BY id", (paper_id,))]}
    finally:
        con.close()


def add_card(paper_id: str, c: CardIn) -> dict[str, Any] | None:
    """None if the paper is missing, or the parent is not a card on this paper."""
    con = db.connect()
    try:
        if not _exists(con, paper_id) or (c.parent is not None and not _get(con, paper_id, c.parent)):
            return None
        with con:
            cur = con.execute(
                "INSERT INTO canvas_cards (paper_id, kind, question, text, entries, x, y, w, page, x0, y0, x1, y1, parent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (paper_id, c.kind, c.question, c.text, json.dumps([e.model_dump() for e in c.entries]), c.x, c.y, c.w, c.page,
                 *(c.rect or [None] * 4), c.parent))
        return _get(con, paper_id, cur.lastrowid)
    finally:
        con.close()


def edit_card(paper_id: str, cid: int, e: CardEdit) -> dict[str, Any] | None:
    con = db.connect()
    try:
        with con:
            for k in e.model_fields_set:
                v = getattr(e, k)
                if v is None:
                    continue
                v = json.dumps([x.model_dump() for x in v]) if k == "entries" else int(v) if k == "hidden" else v
                con.execute(f"UPDATE canvas_cards SET {k} = ? WHERE id = ? AND paper_id = ?", (v, cid, paper_id))  # k is a model field name
        return _get(con, paper_id, cid)
    finally:
        con.close()


def delete_card(paper_id: str, cid: int) -> bool:
    con = db.connect()
    try:
        with con:
            return bool(con.execute("DELETE FROM canvas_cards WHERE id = ? AND paper_id = ?", (cid, paper_id)).rowcount)
    finally:
        con.close()


def add_link(paper_id: str, l: LinkIn) -> dict[str, Any] | None:
    con = db.connect()
    try:
        if l.from_card == l.to_card or not _get(con, paper_id, l.from_card) or not _get(con, paper_id, l.to_card):
            return None
        with con:
            cur = con.execute("INSERT INTO canvas_links (paper_id, from_card, to_card) VALUES (?, ?, ?)", (paper_id, l.from_card, l.to_card))
        return {"id": cur.lastrowid, "from_card": l.from_card, "to_card": l.to_card}
    finally:
        con.close()


def delete_link(paper_id: str, lid: int) -> bool:
    con = db.connect()
    try:
        with con:
            return bool(con.execute("DELETE FROM canvas_links WHERE id = ? AND paper_id = ?", (lid, paper_id)).rowcount)
    finally:
        con.close()


def chain(paper_id: str, cid: int, most: int = 6) -> list[dict[str, Any]]:
    """The card, then its parent, grandparent... up to `most` cards."""
    con = db.connect()
    try:
        out: list[dict[str, Any]] = []
        c = _get(con, paper_id, cid)
        while c and len(out) < most and c["id"] not in [o["id"] for o in out]:
            out.append(c)
            c = _get(con, paper_id, c["parent"]) if c["parent"] else None
        return out
    finally:
        con.close()


def _h(text: str) -> int:
    return 40 + 18 * math.ceil(len(text) / 34)


def _also(question: str, texts: list[str]) -> list[int]:
    """1-based pages a question points at by name: "section 7.2" is where that heading starts, a summary needs the abstract."""
    out = []
    if m := re.search(r"\b(?:section|sec\.?|§)\s*(\d+(?:\.\d+)*)", question, re.I):
        head = re.compile(rf"(?m)^\s*{re.escape(m[1])}\.?\s+[A-Z]")
        out += [i + 1 for i, t in enumerate(texts) if head.search(t)][:1]
    if re.search(r"summar|overview|abstract|main (idea|point|contribution)|what is this paper", question, re.I):
        out.append(1)
    return out


def _cited(s: Any, paper_id: str, question: str, page: int, title: str, texts: list[str], ctx: str = "",
           extra: list[int] = ()) -> dict[str, Any]:
    """The local model answers and names the paragraphs it used. `page` is 1-based; `extra` are pages the cards point at."""
    near = graph.pages_for(s, paper_id, question)
    graph_hit = bool(near)
    if not near:  # no embeddings: the pages around this one that fit the model's budget
        keep = llm.paper_text(s, texts, page - 1, question + ctx)[1]
        near = [p for p in (page - 1, page, page + 1) if p - 1 in keep]
    # best first, so the budget cuts the least useful pages
    chosen = [p for p in dict.fromkeys([page, *extra, *_also(question, texts), *near]) if 1 <= p <= len(texts)][:4]
    paras = [(f"p{pg}-b{i}", pg, r, t) for pg in chosen for i, (r, t) in enumerate(marks.paragraphs(paper_id, pg) or []) if t]
    why = [f"read pages {', '.join(map(str, chosen))}" + (" (by meaning)" if graph_hit else " (around this page)")]
    if paras:
        got = llm.ask_with_sources(s, question, title, paras, ctx)
        return {**got, "trace": why + got.get("trace", [])}
    got = llm.ask(s, ctx + question, title, texts, page - 1)
    return {**got, "sources": [], "trace": why + ["no paragraphs on those pages, plain answer"]}


def _same(a: str, b: str) -> bool:
    """Two answers that share most of their content words say the same thing."""
    x, y = llm._stems(a), llm._stems(b)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) > 0.75


def _earlier(cards: list[dict[str, Any]]) -> str:
    """The cards a follow-up branches from, oldest first, as lines for the prompt."""
    out = []
    for c in cards:
        if c["kind"] == "answer":
            out.append(f"Earlier question: {c['question']}\nEarlier answer: {c['text'][:1500]}\n")
        elif c["kind"] == "source":
            out.append(f"Earlier source (page {c['page']}): {c['text'][:300]}\n")
        elif c["entries"]:
            out.append("Note:\n" + "".join(f"{'Student' if e['who'] == 'me' else 'Dot'}: {e['text'][:500]}\n" for e in c["entries"][-6:]))
    return "".join(x + "\n" for x in out)


def _task(entries: list[dict[str, Any]]) -> str | None:
    """The open @ai line on a card, or None once Dot has answered it."""
    for e in reversed(entries):
        if e["who"] == "dot":
            return None
        if e["who"] != "me":
            continue
        for line in e["text"].splitlines():
            s = line.strip()
            if s.lower().startswith("@ai"):
                return s[3:].strip(" :,-") or "Summarise this paper."
        return None
    return None


def ask(s: Any, paper_id: str, question: str, page: int, from_card: int | None, at: tuple[float, float],
        quote: str = "") -> dict[str, Any] | None:
    """Answer with Dot, saving the answer card and a card for each paragraph it points at."""
    texts = library.page_texts(paper_id)
    con = db.connect()
    row = con.execute("SELECT title FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.close()
    if texts is None or row is None:
        return None
    prior = chain(paper_id, from_card) if from_card is not None else []
    if from_card is not None and not prior:
        return {"ok": False, "error": "That card is not there."}
    ctx = _earlier(prior[::-1]) + (f"The part I selected on page {page} (\"this\" means this part):\n{quote}\n\n" if quote else "")
    pages = [c["page"] for c in prior if c["page"]]
    got = _cited(s, paper_id, question, page, row["title"], texts, ctx, pages)
    last = next((c["text"] for c in prior if c["kind"] == "answer"), "")
    echoed = got["ok"] and last and _same(got["text"], last)
    if echoed:  # small models often hand back the earlier answer; ask once more, plainly
        rework = (f"Text to rework:\n{last}\n\nRewrite it, do not copy it: a numbered list, one part per line, in everyday "
                  f"words with no symbols or subscripts, then one everyday example. The student asked: {question}\n\n")
        again = _cited(s, paper_id, question, page, row["title"], texts, rework, pages)
        if again["ok"]:
            got = again
    trace = ([f"your selection, {len(quote)} characters"] if quote else ["no selection, the whole page"]) \
        + ([f"follow-up on {len(prior)} earlier card{'s' * (len(prior) > 1)}"] if prior else []) \
        + (["first reply repeated the earlier answer, asked again"] if echoed else []) + got.get("trace", [])
    if not got["ok"]:
        return {"ok": False, "error": got["error"], "trace": trace}
    text = got["text"] + ("" if got["sources"] else "\n\nNo exact lines found.")
    x, y = at
    pos, top = [], y
    for src in got["sources"]:
        pos.append(top)
        top += _h(src["gist"]) + 14
    ans = add_card(paper_id, CardIn(kind="answer", question=question, text=text, x=x, y=top, w=260, parent=from_card))
    if ans is None:
        return {"ok": False, "error": "That card is not there."}
    cards = [add_card(paper_id, CardIn(kind="source", text=src["gist"], x=x, y=py, w=260, page=src["page"], rect=src["rect"], parent=ans["id"]))
             for src, py in zip(got["sources"], pos)]
    return {"ok": True, "answer": ans, "sources": cards, "trace": trace + [f"{len(cards)} source card{'s' * (len(cards) != 1)} placed"]}


def _formula_reply(s: Any, paper_id: str, card: dict[str, Any], question: str) -> dict[str, Any]:
    q = re.sub(r"(?im)^\s*@ai\b[\s:,-]*", "", question).strip()
    return formula.breakdown(s, paper_id, card["page"] or 1, card["rect"], q)


_DOT_WORDS = {"explain", "summarize", "summarise", "define", "compare", "why", "how", "what"}


def for_dot(line: str) -> bool:
    """Is this note line meant for Dot? The client mirrors this rule exactly."""
    line = line.strip()
    return bool(line) and (line.endswith("?") or line.startswith("@ai") or line.split()[0].lower() in _DOT_WORDS)


def say(s: Any, paper_id: str, cid: int, text: str) -> dict[str, Any] | None:
    """Add a line to a note; if it is meant for Dot, Dot's answer goes in the same note.
    None if the card is not a note on this paper. Your line is kept even if the model fails."""
    texts = library.page_texts(paper_id)
    con = db.connect()
    try:
        card = _get(con, paper_id, cid)
        row = con.execute("SELECT title FROM papers WHERE id = ?", (paper_id,)).fetchone()
    finally:
        con.close()
    if card is None or card["kind"] != "note" or row is None or texts is None:
        return None
    text = text.strip()
    if len(card["entries"]) >= 200:
        return {"ok": False, "error": "This note is full.", "card": card}
    entries = [*card["entries"], {"who": "me", "text": text}]
    card = edit_card(paper_id, cid, CardEdit(entries=entries)) or card
    if not for_dot(text):
        return {"ok": True, "card": card}
    page = card["page"] or 1
    box = marks.boxed(paper_id, page, card["rect"]) if card["rect"] else None
    got = _formula_reply(s, paper_id, card, text) if box and llm._formula(box[0]) else \
        llm.note_reply(s, entries, box[0] if box else "", box[1] if box else None, row["title"], texts, page - 1)
    if not got["ok"]:
        return {"ok": False, "error": got["error"], "card": card}
    if len(entries) >= 200:
        return {"ok": False, "error": "This note is full.", "card": card}
    card = edit_card(paper_id, cid, CardEdit(entries=[*entries, {"who": "dot", "text": got["text"][:4000]}])) or card
    return {"ok": True, "card": card}


def pickup(s: Any, paper_id: str, cid: int) -> dict[str, Any] | None:
    """An @ai line left on a card is a task. Dot searches the paper and notes the sections it used.
    None if this is not a note on this paper. The card is unchanged when the model cannot answer."""
    texts = library.page_texts(paper_id)
    con = db.connect()
    try:
        card = _get(con, paper_id, cid)
        row = con.execute("SELECT title FROM papers WHERE id = ?", (paper_id,)).fetchone()
    finally:
        con.close()
    if card is None or card["kind"] != "note" or row is None or texts is None:
        return None
    question = _task(card["entries"])
    if not question:
        return {"ok": False, "error": "Nothing for Dot to pick up.", "card": card, "sources": []}
    page = card["page"] or 1
    box = marks.boxed(paper_id, page, card["rect"]) if card["rect"] else None
    if box and llm._formula(box[0]):  # a formula gets taken apart step by step, not searched for
        got = {**_formula_reply(s, paper_id, card, question), "sources": []}
    else:
        ctx = (f'The note is about this part of page {page}:\n"""\n{box[0][:2000]}\n"""\n' if box else "") + _earlier([card])
        got = _cited(s, paper_id, question, page, row["title"], texts, ctx)
    if not got["ok"]:
        return {"ok": False, "error": got["error"], "card": card, "sources": []}
    card = edit_card(paper_id, cid, CardEdit(entries=[*card["entries"], {"who": "dot", "text": got["text"][:4000]}])) or card
    x, y = card["x"], card["y"] + 150
    sources = []
    for src in got["sources"]:
        made = add_card(paper_id, CardIn(kind="source", text=src["gist"], x=x, y=y, w=card["w"], page=src["page"], rect=src["rect"], parent=card["id"]))
        if made:
            sources.append(made)
            y += _h(src["gist"]) + 14
    return {"ok": True, "card": card, "sources": sources}
