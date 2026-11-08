"""The canvas: cards (answers, sources, notes) and the links between them, kept per paper."""
from typing import Any, Literal

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db
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
