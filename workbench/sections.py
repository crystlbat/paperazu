"""Where a section of a paper is, for guided reading.

Reads the PDF's own structure instead of guessing from paragraph boxes: text rows (a row joins the pieces of one line,
so "1" and "INTRODUCTION" are one heading), the body font size, and the columns. Rows are put in reading order: the page
is cut into bands at full-width rows (titles, captions), and in each band the left column is read before the right.
A section runs from its heading to the next heading at the same or a higher level. The headings come from the PDF's
outline when it has one, else from the fonts (bigger or bold short rows that look like headings).
"""
import re
from collections import Counter
from functools import lru_cache
from typing import Any

import pymupdf

from . import db

BAND_GAP = 14  # points of empty page across both columns that end a band
NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+[A-Za-z]")


def _norm(t: str) -> str:
    t = re.sub(r"^\s*(?:\d{1,2}(?:\.\d{1,2})*\.?|[ivx]+\.|[A-Z]\.)\s+", "", t.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _rows(page: Any, pno: int) -> list[dict[str, Any]]:
    """The text lines of a page joined into rows: pieces at the same height and close together are one row."""
    pieces = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            pieces.append({"box": list(ln["bbox"]), "text": "".join(s["text"] for s in spans).strip(),
                           "size": max(s["size"] for s in spans), "bold": all("Bold" in s["font"] or "TB" in s["font"] or s["flags"] & 16 for s in spans)})
    pieces.sort(key=lambda p: (round((p["box"][1] + p["box"][3]) / 2), p["box"][0]))
    rows: list[dict[str, Any]] = []
    for p in pieces:
        r = rows[-1] if rows else None
        same = r and abs((r["box"][1] + r["box"][3]) / 2 - (p["box"][1] + p["box"][3]) / 2) < 2.5 and 0 <= p["box"][0] - r["box"][2] < 14
        if same:
            r["box"] = [min(r["box"][0], p["box"][0]), min(r["box"][1], p["box"][1]), max(r["box"][2], p["box"][2]), max(r["box"][3], p["box"][3])]
            r["text"] += " " + p["text"]; r["size"] = max(r["size"], p["size"]); r["bold"] = r["bold"] and p["bold"]
        else:
            rows.append({**p, "page": pno})
    return rows


def _heady(t: str) -> bool:
    return bool(NUMBERED.match(t) or re.fullmatch(r"[A-Z][A-Z0-9 ,&:'\u2019?-]{3,}", t))


def _order(rows: list[dict[str, Any]], width: float, body: float) -> list[dict[str, Any]]:
    """Reading order on one page: bands split by full-width rows; in each band the left column, then the right."""
    mid = width / 2
    first = min((r["box"][1] for r in rows if r["bold"] and _heady(r["text"])), default=0)
    for r in rows:
        x0, x1 = r["box"][0], r["box"][2]
        r["col"] = 0 if x1 <= mid + 8 else 1 if x0 >= mid - 8 else -1
        # the masthead (title, authors) above the page's first heading stands between bands like a full-width row;
        # big maths symbols further down are not a masthead
        wordy = len(re.findall(r"[A-Za-z]", r["text"])) >= 0.6 * len(r["text"].replace(" ", ""))
        if r["box"][3] <= first and r["size"] >= body * 1.1 and wordy and not _heady(r["text"]):
            r["col"] = -1
    # a single column page (slides, one-column papers) has no right column worth the name
    if sum(r["col"] == 1 for r in rows) < 3 or sum(r["col"] == 0 for r in rows) < 3:
        for r in rows:
            r["col"] = 0
    # a clear gap running across both columns (under the authors, say) also ends a band
    cover = sorted((r["box"][1], r["box"][3]) for r in rows)
    breaks, reach = set(), None
    for y0, y1 in cover:
        if reach is not None and y0 - reach >= BAND_GAP:
            breaks.add(y0)
        reach = y1 if reach is None else max(reach, y1)
    out: list[dict[str, Any]] = []
    band: list[dict[str, Any]] = []
    for r in sorted(rows, key=lambda r: r["box"][1]):
        if r["box"][1] in breaks:
            out += sorted(band, key=lambda r: (r["col"], r["box"][1]))
            band = []
        if r["col"] == -1:
            out += sorted(band, key=lambda r: (r["col"], r["box"][1]))
            band = []
            out.append(r)
        else:
            band.append(r)
    out += sorted(band, key=lambda r: (r["col"], r["box"][1]))
    return out


@lru_cache(maxsize=8)
def _read(path: str, mtime: float) -> dict[str, Any]:
    with pymupdf.open(path) as doc:
        toc = [(lvl, title, page) for lvl, title, page in doc.get_toc(simple=True)]
        pages = [{"w": pg.rect.width, "h": pg.rect.height, "rows": _rows(pg, i + 1)} for i, pg in enumerate(doc)]
    sizes = Counter()
    for p in pages:
        for r in p["rows"]:
            sizes[round(r["size"], 1)] += len(r["text"])
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    for p in pages:
        p["rows"] = _order(p["rows"], p["w"], body)
    flat = []
    for p in pages:
        for r in p["rows"]:
            # the running head, page numbers and small print (footnotes, licence boxes) are not reading
            small = r["size"] < body * 0.86
            edge = (r["box"][3] < p["h"] * 0.08 or r["box"][1] > p["h"] * 0.93) and (small or len(r["text"]) < 90)
            if not (small or edge or re.fullmatch(r"\d{1,4}", r["text"])):
                flat.append(r)
    return {"body": body, "toc": toc, "rows": flat}


def _headings(data: dict[str, Any]) -> list[dict[str, Any]]:
    """[{i: row index, level, title}] in reading order."""
    rows, out = data["rows"], []
    toc = [t for t in data["toc"] if not re.match(r"^slide \d+", t[1].strip(), re.I) or ":" in t[1]]
    if len(toc) >= 3:
        start = 0
        for lvl, title, page in toc:
            want = _norm(re.sub(r"^\s*slide \d+:\s*", "", title, flags=re.I))[:60]  # slide decks: "Slide 4: Population"
            if not want:
                continue
            for i in range(start, len(rows)):
                r = rows[i]
                if r["page"] < page:
                    continue
                if r["page"] > page + 1:
                    break
                got = _norm(r["text"])
                if got and (got.startswith(want[:40]) or (len(got) >= 8 and want.startswith(got))):
                    out.append({"i": i, "level": lvl, "title": re.sub(r"^\s*slide \d+:\s*", "", title, flags=re.I).strip()}); start = i + 1
                    break
        if len(out) >= 2:
            return out
    body = data["body"]
    for i, r in enumerate(rows):
        t = r["text"]
        if len(t) > 90 or len(t) < 3:
            continue
        big = r["size"] >= body * 1.12
        if (big or r["bold"]) and _heady(t):
            m = NUMBERED.match(t)
            out.append({"i": i, "level": m.group(1).count(".") + 1 if m else 1, "title": t})
    return out


def find(paper_id: str, heading: str, page: int) -> dict[str, Any] | None:
    """The section under `heading` (on or after `page`): {heading: {page, box}, segments: [{page, box}], subs: [titles]}.
    Boxes are PDF points [x0, y0, x1, y1]. None when the paper or the heading cannot be found."""
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        return None
    data = _read(str(path), path.stat().st_mtime)
    rows, heads = data["rows"], _headings(data)
    fig = re.match(r"^\s*(fig(?:ure)?\.?|table)\s*(\d+)", heading, re.I)
    if fig:  # a figure stage: its caption, a few lines in one column
        word = "table" if fig.group(1).lower() == "table" else "fig"
        name = rf"^{word}\w*\.?\s*{fig.group(2)}"
        # the caption ("Figure 4:") first; a sentence that starts "Fig. 4. We plot" only when there is no caption
        at = next((i for pat in (name + r"\s*:", name + r"\b") for i, r in enumerate(rows)
                   if r["page"] >= page and re.match(pat, r["text"], re.I)), None)
        if at is None:
            return None
        h = rows[at]
        box = list(h["box"])
        for r in rows[at + 1:at + 14]:
            if r["page"] != h["page"] or r["col"] != h["col"] or r["box"][1] - box[3] > 6:
                break
            box = [min(box[0], r["box"][0]), box[1], max(box[2], r["box"][2]), max(box[3], r["box"][3])]
        return {"heading": {"page": h["page"], "box": [round(x, 1) for x in h["box"]], "title": h["text"][:80]},
                "segments": [{"page": h["page"], "box": [round(x, 1) for x in box]}], "subs": []}
    want = _norm(heading)
    if not want:
        return None
    hit = next((h for h in heads if rows[h["i"]]["page"] >= page and (_norm(h["title"]).startswith(want) or want.startswith(_norm(h["title"])))), None) \
        or next((h for h in heads if want in _norm(h["title"])), None)
    if hit is None:
        return None
    k = heads.index(hit)
    end = next((h["i"] for h in heads[k + 1:] if h["level"] <= hit["level"]), len(rows))
    subs = [h["title"] for h in heads[k + 1:] if h["i"] < end]
    # rows of one column that follow each other in reading order become one stretch (figure labels and equation pieces
    # inside it too); a new column, a full-width row or a new page starts another
    segs: list[dict[str, Any]] = []
    for r in rows[hit["i"]:end]:
        s = segs[-1] if segs else None
        if s and s["page"] == r["page"] and s["col"] == r["col"]:
            s["box"] = [min(s["box"][0], r["box"][0]), s["box"][1], max(s["box"][2], r["box"][2]), max(s["box"][3], r["box"][3])]
            s["words"] += len(re.findall(r"[A-Za-z]{3,}", r["text"]))
        else:
            segs.append({"page": r["page"], "col": r["col"], "box": list(r["box"]), "words": len(re.findall(r"[A-Za-z]{3,}", r["text"]))})
    # figure labels and tick marks are text too, but not reading: keep stretches with real sentences (and the heading's)
    segs = [g for n, g in enumerate(segs) if n == 0 or g["words"] >= 12]
    h = rows[hit["i"]]
    return {"heading": {"page": h["page"], "box": [round(x, 1) for x in h["box"]], "title": hit["title"]},
            "segments": [{"page": s["page"], "box": [round(x, 1) for x in s["box"]]} for s in segs],
            "subs": subs}
