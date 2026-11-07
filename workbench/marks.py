"""Margin notes. Dot traces a paragraph and you write beside it. Paragraph boxes come from PyMuPDF's
text blocks; a note keeps the box (PDF points, top-left origin) and the page it is on."""
from typing import Any

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db


class MarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    rect: list[float] = Field(min_length=4, max_length=4)
    text: str = Field("", max_length=4000)

    @field_validator("rect")
    @classmethod
    def _box(cls, r: list[float]) -> list[float]:
        if not (r[0] < r[2] and r[1] < r[3] and min(r) >= 0):
            raise ValueError("The box must have its top-left corner before its bottom-right corner.")
        return r


class MarkText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=4000)


def blocks(paper_id: str, page: int) -> dict[str, Any] | None:
    """The page size and its paragraphs (text blocks with real text). None if there is no such page."""
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        return None
    with pymupdf.open(path) as doc:
        if not 1 <= page <= doc.page_count:
            return None
        pg = doc[page - 1]
        out = [[round(b[0], 1), round(b[1], 1), round(b[2], 1), round(b[3], 1)]
               for b in pg.get_text("blocks") if b[6] == 0 and len(" ".join(str(b[4]).split())) >= 25]
        return {"w": pg.rect.width, "h": pg.rect.height, "blocks": out}


def _row(r: Any) -> dict[str, Any]:
    return {"id": r["id"], "page": r["page"], "rect": [r["x0"], r["y0"], r["x1"], r["y1"]], "text": r["text"], "created_at": r["created_at"]}


def _exists(con: Any, paper_id: str) -> bool:
    return con.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is not None


def all_for(paper_id: str) -> list[dict[str, Any]] | None:
    con = db.connect()
    try:
        if not _exists(con, paper_id):
            return None
        return [_row(r) for r in con.execute("SELECT * FROM marks WHERE paper_id = ? ORDER BY page, y0", (paper_id,))]
    finally:
        con.close()


def create(paper_id: str, m: MarkIn) -> dict[str, Any] | None:
    con = db.connect()
    try:
        if not _exists(con, paper_id):
            return None
        with con:
            cur = con.execute("INSERT INTO marks (paper_id, page, x0, y0, x1, y1, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (paper_id, m.page, *m.rect, m.text))
        return _row(con.execute("SELECT * FROM marks WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


def update(paper_id: str, mark_id: int, text: str) -> bool:
    con = db.connect()
    with con:
        n = con.execute("UPDATE marks SET text = ? WHERE id = ? AND paper_id = ?", (text, mark_id, paper_id)).rowcount
    con.close()
    return bool(n)


def delete(paper_id: str, mark_id: int) -> bool:
    con = db.connect()
    with con:
        n = con.execute("DELETE FROM marks WHERE id = ? AND paper_id = ?", (mark_id, paper_id)).rowcount
    con.close()
    return bool(n)
