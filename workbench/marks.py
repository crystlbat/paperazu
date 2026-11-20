"""Margin notes. Dot traces a paragraph and you write beside it. Paragraph boxes come from PyMuPDF's
text blocks; a note keeps the box (PDF points, top-left origin) and the page it is on."""
from typing import Any, Literal

import base64
import re
import json

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


class HighlightIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    kind: Literal["me", "dot"] = "me"
    text: str = Field("", max_length=2000)
    rects: list[list[float]] = Field(min_length=1, max_length=60)

    @field_validator("rects")
    @classmethod
    def _boxes(cls, rs: list[list[float]]) -> list[list[float]]:
        for r in rs:
            if len(r) != 4:
                raise ValueError("Each rectangle needs four numbers.")
            MarkIn._box.__func__(cls, r)
        return rs


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


def _layout(pg: Any) -> list[list[float]]:
    text = [(list(b[:4]), len(" ".join(str(b[4]).split()))) for b in pg.get_text("blocks") if b[6] == 0]
    long = [r for r, n in text if n >= 25]
    small = _join([r for r, n in text if 0 < n < 25])  # equations come out as many small blocks
    keep = long + [r for r in small if r[2] - r[0] >= 60 and not any(_near(r, x, 0) and r[1] >= x[1] and r[3] <= x[3] for x in long)]
    return sorted(([round(v, 1) for v in r] for r in keep), key=lambda r: (r[0] > pg.rect.width / 2, r[1]))


def _page(paper_id: str, page: int) -> Any:
    """Open the PDF and return (doc, page), or None. The caller closes the doc."""
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        return None
    doc = pymupdf.open(path)
    if not 1 <= page <= doc.page_count:
        doc.close()
        return None
    return doc, doc[page - 1]


def blocks(paper_id: str, page: int) -> dict[str, Any] | None:
    """The page size and its paragraphs (text blocks with real text). None if there is no such page."""
    got = _page(paper_id, page)
    if not got:
        return None
    with got[0]:
        return {"w": got[1].rect.width, "h": got[1].rect.height, "blocks": _layout(got[1])}


def _inside(a: list[float], b: list[float]) -> bool:
    """Most of box a lies within box b."""
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return w > 0 and h > 0 and w * h >= .6 * (a[2] - a[0]) * (a[3] - a[1])


def _side_by_side(boxes: list[list[float]]) -> list[list[float]]:
    """Merge pictures that sit side by side (mostly the same height band, under 40pt apart): one figure's panels."""
    out: list[list[float]] = []
    for b in sorted(boxes, key=lambda r: r[0]):
        hit = next((o for o in out if min(o[3], b[3]) - max(o[1], b[1]) >= .5 * min(o[3] - o[1], b[3] - b[1]) and b[0] - o[2] < 40), None)
        if hit:
            hit[:] = [min(hit[0], b[0]), min(hit[1], b[1]), max(hit[2], b[2]), max(hit[3], b[3])]
        else:
            out.append(b[:])
    return out


def reflow(paper_id: str, page: int) -> dict[str, Any] | None:
    """A page as reading-order items for the text view: {"kind": "h"|"p", "text"} for headings and paragraphs, and
    {"kind": "img", "src", "text"} for what does not survive as text (equations, tables, figures), cut from the page.
    None if there is no such page."""
    got = _page(paper_id, page)
    if not got:
        return None
    with got[0]:
        pg = got[1]
        spans = [s for b in pg.get_text("dict")["blocks"] if b["type"] == 0 for ln in b["lines"] for s in ln["spans"] if s["text"].strip()]
        body = sorted(s["size"] for s in spans)[len(spans) // 2] if spans else 10
        h = pg.rect.height
        text = [(list(b[:4]), " ".join(str(b[4]).split())) for b in pg.get_text("blocks")
                if b[6] == 0 and str(b[4]).strip() and h * .09 < (b[1] + b[3]) / 2 < h * .95]  # running heads and page numbers go

        def head(r: list[float], t: str) -> bool:
            inn = [s for s in spans if _inside(list(s["bbox"]), r)]
            big, bold = max((s["size"] for s in inn), default=body), all(s["flags"] & 16 for s in inn) and bool(inn)
            return len(t) < 90 and not t.endswith(".") and (big > body * 1.12 or bold)

        heads = [head(r, t) for r, t in text]
        # short blocks are equation and table pieces, a line ending in "(n)" is a displayed equation, and a block that
        # is mostly numbers is a table: they join
        # each other and any figure they touch, and are shown as pictures
        eq = [(len(t) < 25 and (len(t) <= 3 or re.search(r"[=+−∑Õ∫λ<>≤≥^_|\d]", t)) or len(t) < 140 and re.search(r"\(\d{1,3}\)$", t)
               or len(re.findall(r"(?<!\w)[\d.,%±]+(?!\w)", t)) > .3 * len(t.split()) > 3) and not hd for (r, t), hd in zip(text, heads)]
        figs = [list(i["bbox"]) for i in pg.get_image_info()] + [list(r) for r in pg.cluster_drawings()]
        figs = [r for r in figs if r[2] - r[0] >= 40 and r[3] - r[1] >= 30]
        long = [r for (r, t), e in zip(text, eq) if not e and len(t) >= 25]
        pics = _join(figs + [r for (r, t), e in zip(text, eq) if e and not any(_inside(r, x) for x in long)])
        pics = [r for r in pics if r[2] - r[0] >= 30 and r[3] - r[1] >= 8]
        pics = _side_by_side(pics)
        items: list[tuple[list[float], dict[str, Any]]] = []
        for (r, t), hd in zip(text, heads):
            if any(_inside(r, x) for x in pics):
                continue
            t = " ".join(re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", pg.get_text("text", clip=pymupdf.Rect(*r))).split()) or t
            items.append((r, {"kind": "h" if hd else "p", "text": t}))
        for r in pics:
            clip = pymupdf.Rect(*r) & pg.rect
            png = pg.get_pixmap(clip=clip, dpi=150).tobytes("png")
            items.append((r, {"kind": "img", "src": "data:image/png;base64," + base64.b64encode(png).decode(),
                              "text": " ".join(pg.get_text("text", clip=clip).split()), "w": round(clip.width)}))
        half = pg.rect.width / 2
        items.sort(key=lambda it: (it[0][0] >= half - 10, it[0][1]))  # left column, then right; a full-width row stays in the left run
        return {"page": page, "items": [it[1] for it in items]}


def paragraphs(paper_id: str, page: int) -> list[tuple[list[float], str]] | None:
    """The same boxes as blocks(), each with its text. None if there is no such page."""
    got = _page(paper_id, page)
    if not got:
        return None
    with got[0]:
        return [(r, " ".join(got[1].get_text("text", clip=pymupdf.Rect(*r)).split())) for r in _layout(got[1])]


def around(paper_id: str, page: int, rect: list[float], most: int = 600) -> tuple[str, str]:
    """The paragraph just above a box and the one just below it, in the same column: where a formula is set up and explained."""
    paras = [(r, t) for r, t in paragraphs(paper_id, page) or [] if t and r[0] < rect[2] and r[2] > rect[0]]
    above = [p for p in paras if p[0][3] <= rect[1] + 3]
    below = [p for p in paras if p[0][1] >= rect[3] - 3]
    up = max(above, key=lambda p: p[0][3], default=(None, ""))[1]
    down = min(below, key=lambda p: p[0][1], default=(None, ""))[1]
    return up[-most:], down[:most]


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


def _hrow(r: Any) -> dict[str, Any]:
    return {"id": r["id"], "page": r["page"], "kind": r["kind"], "text": r["text"], "rects": json.loads(r["rects"])}


def highlights(paper_id: str) -> list[dict[str, Any]] | None:
    con = db.connect()
    try:
        if not _exists(con, paper_id):
            return None
        return [_hrow(r) for r in con.execute("SELECT * FROM highlights WHERE paper_id = ? ORDER BY page, id", (paper_id,))]
    finally:
        con.close()


def add_highlight(paper_id: str, h: HighlightIn) -> dict[str, Any] | None:
    con = db.connect()
    try:
        if not _exists(con, paper_id):
            return None
        with con:
            cur = con.execute("INSERT INTO highlights (paper_id, page, kind, text, rects) VALUES (?, ?, ?, ?, ?)",
                              (paper_id, h.page, h.kind, h.text, json.dumps(h.rects)))
        return _hrow(con.execute("SELECT * FROM highlights WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


def keep_highlight(paper_id: str, hid: int) -> dict[str, Any] | None:
    """Dot's blue highlight becomes yours (yellow)."""
    con = db.connect()
    try:
        with con:
            con.execute("UPDATE highlights SET kind = 'me' WHERE id = ? AND paper_id = ?", (hid, paper_id))
        r = con.execute("SELECT * FROM highlights WHERE id = ? AND paper_id = ?", (hid, paper_id)).fetchone()
        return _hrow(r) if r else None
    finally:
        con.close()


def remove_highlight(paper_id: str, hid: int) -> bool:
    con = db.connect()
    try:
        with con:
            return bool(con.execute("DELETE FROM highlights WHERE id = ? AND paper_id = ?", (hid, paper_id)).rowcount)
    finally:
        con.close()


def _lines(rects: list[Any]) -> list[list[float]]:
    """Merge the pieces of one line (same height band) into a single rectangle per line."""
    out: list[list[float]] = []
    for r in sorted(rects, key=lambda r: (r.y0, r.x0)):
        last = out[-1] if out else None
        if last and min(last[3], r.y1) - max(last[1], r.y0) > 0.5 * (r.y1 - r.y0):
            last[:] = [min(last[0], r.x0), min(last[1], r.y0), max(last[2], r.x1), max(last[3], r.y1)]
        else:
            out.append([r.x0, r.y0, r.x1, r.y1])
    return [[round(v, 1) for v in r] for r in out]


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def _words(pg: Any, clip: Any) -> list[tuple[str, list[Any]]]:
    """The words in a box in reading order as (normalised word, [rects]). A word split by a hyphen at a line's end is
    one word with two rects, so a quote copied without the break still matches."""
    raw = [w for w in pg.get_text("words", clip=clip, sort=True) if _norm(w[4])]
    out: list[tuple[str, list[Any]]] = []
    i = 0
    while i < len(raw):
        w = raw[i]
        r = pymupdf.Rect(w[:4])
        if w[4].endswith("-") and i + 1 < len(raw) and raw[i + 1][1] > w[3] - 1:  # hyphen, and the next word is on the next line
            n = raw[i + 1]
            out.append((_norm(w[4]) + _norm(n[4]), [r, pymupdf.Rect(n[:4])])); i += 2
        else:
            out.append((_norm(w[4]), [r])); i += 1
    return out


def _find(words: list[tuple[str, list[Any]]], quote: str) -> list[Any]:
    """The rects of a quote's words: the exact run of words if it is there, else from where its first four words
    start to where its last four end (the model sometimes drops or changes a word in the middle)."""
    q = [n for w in quote.split() if (n := _norm(w))]
    if len(q) < 3:
        return []
    toks = [w for w, _ in words]
    def at(seq: list[str], start: int = 0) -> int:
        for i in range(start, len(toks) - len(seq) + 1):
            if toks[i:i + len(seq)] == seq:
                return i
        return -1
    i = at(q)
    if i >= 0:
        j = i + len(q)
    else:
        k = min(4, len(q))
        i = at(q[:k])
        e = at(q[-k:], max(i, 0)) if i >= 0 else -1
        if i < 0 or e < 0 or e + k - i > 2 * len(q):
            return []
        j = e + k
    return [r for _, rs in words[i:j] for r in rs]


def _whole(text: str, quote: str, short: int = 8, most: int = 45) -> str:
    """A quote of fewer than `short` words grown to the sentence of `text` it sits in, so a highlight marks a whole
    claim and not a scrap of one ("fairness variance observed"). Longer quotes stay, and so does a scrap whose sentence
    is over `most` words or most of the box."""
    q = [n for w in quote.split() if (n := _norm(w))]
    if len(q) >= short:
        return quote
    flat = " ".join(re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text).split())  # join words split at a line's end
    for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", flat):
        toks = [n for w in sent.split() if (n := _norm(w))]
        if any(toks[i:i + len(q)] == q for i in range(len(toks) - len(q) + 1)):
            return sent if len(toks) <= most and len(sent) <= 0.6 * len(flat) else quote  # never most of the box
    return quote


def suggest(s: Any, paper_id: str, page: int, rect: list[float], title: str, focus: str = "") -> list[dict[str, Any]] | None:
    """Dot highlights the important quotes inside a box, about `focus` if you said what to look for. Quotes the model
    made up, or that are most of the box, are dropped."""
    from . import llm
    got = boxed(paper_id, page, rect)
    if not got:
        return None
    text = got[0]
    quotes = list(dict.fromkeys(_whole(text, q) for q in llm.pick_quotes(s, text, title, focus)))  # two scraps of one sentence mark it once
    pg = _page(paper_id, page)
    if not pg:
        return None
    out: list[dict[str, Any]] = []
    with pg[0]:
        clip = pymupdf.Rect(*rect) & pg[1].rect
        words = _words(pg[1], clip)
        for q in quotes:
            if len(q) > 0.6 * len(text):
                continue
            found = _find(words, q)
            if found:
                out.append({"text": q, "rects": _lines(found)})
    return [h for x in out if (h := add_highlight(paper_id, HighlightIn(page=page, kind="dot", text=x["text"], rects=x["rects"])))]
