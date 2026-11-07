"""Margin notes. Dot traces a paragraph and you write beside it. Paragraph boxes come from PyMuPDF's
text blocks; a note keeps the box (PDF points, top-left origin) and the page it is on."""
from typing import Any

import base64

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
    rect: list[float] | None = Field(None, min_length=4, max_length=4)  # set when the box grows over more paragraphs

    _box = field_validator("rect")(MarkIn._box.__func__)


class BoxAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=600)


def _near(a: list[float], b: list[float], gap: float = 6) -> bool:
    return a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]


def _join(boxes: list[list[float]]) -> list[list[float]]:
    """Merge boxes that touch (within a few points) until none do: the scattered pieces of a formula become one."""
    out: list[list[float]] = []
    for b in boxes:
        b = b[:]
        while (hit := next((o for o in out if _near(o, b)), None)) is not None:
            out.remove(hit)
            b = [min(b[0], hit[0]), min(b[1], hit[1]), max(b[2], hit[2]), max(b[3], hit[3])]
        out.append(b)
    return out


def blocks(paper_id: str, page: int) -> dict[str, Any] | None:
    """The page size and its paragraphs (text blocks with real text). None if there is no such page."""
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        return None
    with pymupdf.open(path) as doc:
        if not 1 <= page <= doc.page_count:
            return None
        pg = doc[page - 1]
        text = [(list(b[:4]), len(" ".join(str(b[4]).split()))) for b in pg.get_text("blocks") if b[6] == 0]
        long = [r for r, n in text if n >= 25]
        small = _join([r for r, n in text if 0 < n < 25])  # equations come out as many small blocks
        keep = long + [r for r in small if r[2] - r[0] >= 60 and not any(_near(r, x, 0) and r[1] >= x[1] and r[3] <= x[3] for x in long)]
        out = sorted(([round(v, 1) for v in r] for r in keep), key=lambda r: (r[0] > pg.rect.width / 2, r[1]))
        return {"w": pg.rect.width, "h": pg.rect.height, "blocks": out}


def boxed(paper_id: str, page: int, rect: list[float]) -> tuple[str, str] | None:
    """The text inside a box, and a PNG of it as a data: URL. None if there is no such page."""
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        return None
    with pymupdf.open(path) as doc:
        if not 1 <= page <= doc.page_count:
            return None
        clip = pymupdf.Rect(*rect) & doc[page - 1].rect
        text = " ".join(doc[page - 1].get_text("text", clip=clip).split())
        png = doc[page - 1].get_pixmap(clip=clip, dpi=150 if clip.height < 400 else 110).tobytes("png")
    return text, "data:image/png;base64," + base64.b64encode(png).decode()


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


def get(paper_id: str, mark_id: int) -> dict[str, Any] | None:
    con = db.connect()
    r = con.execute("SELECT * FROM marks WHERE id = ? AND paper_id = ?", (mark_id, paper_id)).fetchone()
    con.close()
    return _row(r) if r else None


def update(paper_id: str, mark_id: int, text: str, rect: list[float] | None = None) -> bool:
    con = db.connect()
    with con:
        n = con.execute("UPDATE marks SET text = ? WHERE id = ? AND paper_id = ?", (text, mark_id, paper_id)).rowcount
        if n and rect:
            con.execute("UPDATE marks SET x0 = ?, y0 = ?, x1 = ?, y1 = ? WHERE id = ?", (*rect, mark_id))
    con.close()
    return bool(n)


def delete(paper_id: str, mark_id: int) -> bool:
    con = db.connect()
    with con:
        n = con.execute("DELETE FROM marks WHERE id = ? AND paper_id = ?", (mark_id, paper_id)).rowcount
    con.close()
    return bool(n)
