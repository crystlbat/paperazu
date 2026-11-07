"""The paper library: add, guess details, list, edit, delete, search, progress."""
import json
from pathlib import Path
import re
import sqlite3
import uuid
from datetime import date
from typing import Any, Literal

import pymupdf
from pydantic import BaseModel, ConfigDict, field_validator

from . import db
from .framework import Framework, Step, Template

MAX_PDF_BYTES = 100 * 1024 * 1024
StepState = Literal["empty", "partial", "done"]
Status = Literal["all", "not_started", "in_progress", "notes_done", "reflection_done"]
Sort = Literal["date", "opened", "title", "progress"]


class PaperPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    authors: str | None = None
    venue: str | None = None
    presenters: str | None = None
    presentation_date: date | None = None
    course: str | None = None
    tags: list[str] | None = None
    reflection_no: int | None = None
    reflection_done: bool | None = None
    template: Template | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("A paper needs a title.")
        return v.strip() if v else v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else [t.strip() for t in v if t.strip()]


# ---------- adding ----------

def _clean_meta(value: str | None) -> str:
    v = (value or "").strip()
    junk = ("microsoft word", "untitled", "arxiv", "latex", "pdf")
    if len(v) < 6 or v.lower().startswith(junk) or v.lower().endswith((".pdf", ".dvi", ".doc", ".docx")):
        return ""
    return v


def _first_page_guess(doc: pymupdf.Document) -> tuple[str, str]:
    """Title = the biggest text on page 1. Authors = the lines just below it."""
    if doc.page_count == 0:
        return "", ""
    lines: list[tuple[float, float, str]] = []  # (size, y, text)
    for block in doc[0].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = " ".join(s["text"] for s in line["spans"]).strip()
            if text:
                lines.append((max(s["size"] for s in line["spans"]), line["bbox"][1], text))
    if not lines:
        return "", ""
    top = max(size for size, _, _ in lines)
    title_lines = [(y, t) for size, y, t in lines if size >= top - 0.5]
    title = " ".join(t for _, t in sorted(title_lines))
    last_y = max(y for y, _ in title_lines)
    after = sorted((y, t) for size, y, t in lines if y > last_y and size < top - 0.5)
    authors = []
    for _, t in after[:3]:
        if re.match(r"(?i)abstract|introduction|\d", t):
            break
        authors.append(t)
    return title, ", ".join(authors)


def guess_details(pdf: bytes) -> dict[str, str]:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        meta = doc.metadata or {}
        title, authors = _clean_meta(meta.get("title")), _clean_meta(meta.get("author"))
        if not title or not authors:
            t, a = _first_page_guess(doc)
            title, authors = title or t, authors or a
    return {"title": re.sub(r"\s+", " ", title)[:300], "authors": re.sub(r"\s+", " ", authors)[:300]}


_SLIDE_TITLE = re.compile(r"^slide\s+\d+\b", re.I)


def guess_template(doc: pymupdf.Document) -> str:
    """Slides if most pages are wide (16:9 or 4:3 decks) or the outline lists "Slide N". Else a paper."""
    pages = [doc[i].rect for i in range(min(doc.page_count, 12))]
    wide = sum(r.width > r.height * 1.15 for r in pages)
    toc = [t for _, t, _ in doc.get_toc(simple=True)]
    slide_toc = toc and sum(bool(_SLIDE_TITLE.match(t)) for t in toc) >= 0.6 * len(toc)
    return "slides" if slide_toc or (pages and wide >= 0.6 * len(pages)) else "paper"


def pick_missing_templates() -> None:
    """Papers added before templates existed get one picked from their PDF, once."""
    con = db.connect()
    with con:
        for (pid,) in con.execute("SELECT id FROM papers WHERE template = ''").fetchall():
            path = db.PAPERS_DIR / f"{pid}.pdf"
            try:
                with pymupdf.open(path) as doc:
                    t = guess_template(doc)
            except Exception:
                t = "paper"
            con.execute("UPDATE papers SET template = ? WHERE id = ?", (t, pid))
    con.close()


def create(pdf: bytes, filename: str) -> str:
    """Raises ValueError with a message for the user if the file is not a usable PDF."""
    if len(pdf) > MAX_PDF_BYTES:
        raise ValueError("This PDF is larger than 100 MB.")
    if not pdf.startswith(b"%PDF"):
        raise ValueError("This file is not a PDF.")
    try:
        details = guess_details(pdf)
    except Exception:
        raise ValueError("This PDF could not be opened. It may be damaged or locked.")
    if not details["title"]:
        details["title"] = re.sub(r"\.pdf$", "", filename, flags=re.I) or "Untitled paper"
    paper_id = uuid.uuid4().hex[:12]
    db.PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    (db.PAPERS_DIR / f"{paper_id}.pdf").write_bytes(pdf)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        template = guess_template(doc)
    con = db.connect()
    with con:
        con.execute("INSERT INTO papers (id, title, authors, template) VALUES (?, ?, ?, ?)",
                    (paper_id, details["title"], details["authors"], template))
        reindex(con, paper_id)
    con.close()
    return paper_id


def page_texts(paper_id: str) -> list[str] | None:
    """The text of every page, read from the stored PDF. None if the paper is not there."""
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        return None
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


# ---------- section tree ----------
# L1 the paper, L2 sections, L3 subsections, L4 sub-subsections and the figures and tables.

_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3}|[A-Z](?:\.\d+){0,3})\.?\s+([A-Z].{1,90})$")
_NAMED = {"abstract", "introduction", "related work", "background", "method", "methods", "methodology",
          "results", "discussion", "conclusion", "conclusions", "limitations", "references",
          "acknowledgments", "acknowledgements", "appendix", "evaluation", "experiments"}
_CAPTION = re.compile(r"^((?:Figure|Fig\.|Table)\s+[A-Z]?\d+)\s*[:.]\s*(.*)", re.S)


def _guess_headings(doc: pymupdf.Document) -> list[tuple[int, str, int]]:
    """For PDFs without a built-in outline: numbered or well-known headings set bold or larger than body text."""
    lines: list[tuple[int, str, float, bool]] = []
    sizes: dict[float, int] = {}
    for n, page in enumerate(doc, 1):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [sp for sp in line["spans"] if sp["text"].strip()]
                if not spans:
                    continue
                text = " ".join(sp["text"].strip() for sp in spans)
                size = round(max(sp["size"] for sp in spans), 1)
                sizes[size] = sizes.get(size, 0) + len(text)
                lines.append((n, text, size, all(sp["flags"] & 16 for sp in spans)))
    body = max(sizes, key=sizes.get) if sizes else 0
    out: list[tuple[int, str, int]] = []
    seen: set[str] = set()
    for n, text, size, bold in lines:
        if len(text) > 95 or not (bold or size > body + 0.5) or text.lower() in seen:
            continue
        m = _NUMBERED.match(text)
        if m:
            out.append((m.group(1).count(".") + 1, text, n))
        elif text.lower().rstrip(".:") in _NAMED:
            out.append((1, text, n))
        else:
            continue
        seen.add(text.lower())
    return out


def _captions(doc: pymupdf.Document) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    seen: set[str] = set()
    for n, page in enumerate(doc, 1):
        for block in page.get_text("blocks"):
            m = _CAPTION.match(block[4].strip())
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                rest = re.sub(r"(\w)- (\w)", r"\1\2", re.sub(r"\s+", " ", m.group(2))).strip()
                out.append((n, f"{m.group(1)}: {rest[:70]}{'…' if len(rest) > 70 else ''}"))
    return out


def _flat_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"-\n(?=[a-z])", "", text)).strip()


def _lead(text: str, limit: int) -> str:
    """Whole sentences up to about `limit` characters."""
    if len(text) <= limit:
        return text
    cut = text.rfind(". ", 0, limit)
    return text[:cut + 1] if cut > limit // 3 else text[:limit].rsplit(" ", 1)[0] + "…"


def _section_texts(pages: list[str], heads: list[tuple[int, str, int]]) -> list[str]:
    """The text under each heading: from the heading to the next one. Headings are found in the
    page text by their words (case and spacing ignored); one that cannot be found starts at its page."""
    doc, starts = "", []
    for t in pages:
        starts.append(len(doc))
        doc += _flat_text(t) + " "
    low = doc.lower()
    pos: list[tuple[int, int]] = []  # (start of heading, end of heading)
    cursor = 0
    for _, title, pg in heads:
        from_ = max(cursor, starts[min(pg, len(starts)) - 1])
        words = re.findall(r"\w+", title.lower())
        found = None
        for ws in (words, words[1:] if len(words) > 1 and re.fullmatch(r"[\da-z]{1,2}", words[0]) else None):
            if not ws:
                continue
            m = re.compile(r"\W*".join(map(re.escape, ws))).search(low, from_, from_ + 20000)
            if m:
                found = (m.start(), m.end()); break
        found = found or (from_, from_)
        pos.append(found)
        cursor = found[1]
    out = []
    for i, (_, end) in enumerate(pos):
        nxt = pos[i + 1][0] if i + 1 < len(pos) else len(doc)
        out.append(doc[end:max(end, nxt)].strip(" .:"))
    return out


def _node(title: str, page: int, level: int, body: str, kind: str = "section") -> dict[str, Any]:
    return {"title": title, "page": page, "level": level, "kind": kind, "children": [],
            "lead": _lead(body, 400), "text": _lead(body, 1200), "words": len(body.split())}


_SLIDE = re.compile(r"^slide\s+(\d+)(?:\s*[:.\-]\s*(.*))?$", re.I)


def _is_deck(heads: list[tuple[int, str, int]]) -> bool:
    return len(heads) >= 4 and sum(bool(_SLIDE.match(t)) for _, t, _ in heads) >= 0.6 * len(heads)


def _deck_tree(root: dict[str, Any], heads: list[tuple[int, str, int]], texts: list[str]) -> None:
    """Slide decks list every slide flat ("Slide 7: Title"). Give them shape: a slide with only a
    short heading starts a section (L2), runs of slides with the same title make a topic (L3), and
    each slide in a run is an L4 leaf."""
    slides = []
    for (_, t, pg), body in zip(heads, texts):
        m = _SLIDE.match(t)
        name = (m.group(2) or "").strip() if m else t
        if name and body.lower().startswith(name.lower()):
            body = body[len(name):]
        body = re.sub(r"^\s*\d{1,3}\b\s*", "", body).strip()  # the slide number printed under the title
        body = re.sub(rf"\s+{pg}$", "", body)  # or in the corner, at the end
        slides.append((name, body, pg))
    if slides and not slides[0][0]:
        root["lead"] = _lead(slides[0][1], 400)  # the title slide
        slides = slides[1:]
    has_dividers = any(not n and 0 < len(b.split()) <= 6 for n, b, _ in slides)
    section = root if not has_dividers else None
    run: dict[str, Any] | None = None
    for name, body, pg in slides:
        if not name and 0 < len(body.split()) <= 6:  # a divider slide: a new section
            section = _node(body, pg, 2, "")
            root["children"].append(section); run = None
            continue
        if section is None:
            section = _node("Opening", pg, 2, "")
            root["children"].append(section)
        lvl = section["level"] + 1
        label = name or f"Slide {pg}"
        if run is not None and run["title"] == label and run["parent"] is section:
            if not run["node"]["children"]:  # second slide of a run: the first becomes a leaf too
                first = run["node"]
                first["children"].append(_node(f"Slide {first['page']}", first["page"], lvl + 1, first.pop("_body")))
            prev = run["last"]
            same = 0  # build-up slides repeat the last one, so a leaf shows only what it adds
            for a, b in zip(prev.split(), body.split()):
                if a != b:
                    break
                same += 1
            leaf = _node(f"Slide {pg}", pg, lvl + 1, body)
            if same >= 8:
                leaf["lead"] = _lead(" ".join(body.split()[same:]), 400) or "Same as the slide before"
            run["node"]["children"].append(leaf)
            run["last"] = body
            run["node"]["words"] += len(body.split())
            continue
        node = _node(label, pg, lvl, body)
        node["_body"] = body
        section["children"].append(node)
        run = {"title": label, "node": node, "parent": section, "last": body}

    def tidy(n: dict[str, Any]) -> None:
        n.pop("_body", None)
        for c in n["children"]:
            tidy(c)
    tidy(root)


def outline(paper_id: str, title: str) -> dict[str, Any] | None:
    """The paper as a tree, with the opening text of every part. Uses the PDF's own outline when it
    has one (slide decks get grouped), else guesses the headings."""
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        return None
    with pymupdf.open(path) as doc:
        toc = [(lvl, t.strip(), max(1, pg)) for lvl, t, pg in doc.get_toc(simple=True) if t.strip()]
        source = "outline" if toc else "guessed"
        heads = toc or _guess_headings(doc)
        caps = _captions(doc)
        pages = doc.page_count
        texts = _section_texts([pg.get_text() for pg in doc], heads) if heads else []
    root: dict[str, Any] = {"title": title, "page": 1, "level": 1, "kind": "paper", "children": []}
    if _is_deck(heads):
        source = "slides"
        _deck_tree(root, heads, texts)
    else:
        stack = [root]
        for (lvl, t, pg), body in zip(heads, texts):
            node = _node(t, pg, min(lvl, 3) + 1, body)
            while stack[-1]["level"] >= node["level"]:
                stack.pop()
            stack[-1]["children"].append(node)
            stack.append(node)
    # figures hang under the last part that starts on or before their page
    # shortcut: by page only, so on a page where two parts start a figure may sit one part late.
    flat: list[dict[str, Any]] = []
    parent: dict[int, dict[str, Any]] = {}

    def order(n: dict[str, Any]) -> None:
        for c in n["children"]:
            parent[id(c)] = n; flat.append(c); order(c)
    order(root)
    for pg, cap in caps:
        owner = next((s for s in reversed(flat) if s["page"] <= pg), root)
        if owner["level"] >= 4:
            owner = parent[id(owner)]
        owner["children"].append(_node(cap, pg, owner["level"] + 1, "", kind="figure"))
    return {"tree": root, "source": source, "pages": pages}


# ---------- progress ----------

def _filled(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_filled(v) for v in value)
    if isinstance(value, dict):
        return any(_filled(v) for v in value.values())
    return bool(value)


def step_state(step: Step, data: dict[str, Any]) -> StepState:
    """done = every field written and every gate ticked. partial = anything written."""
    fields = data.get("fields", {})
    filled = [_filled(fields.get(f.id)) for f in step.fields]
    gate = data.get("gate", [])
    gates_ok = len(gate) >= len(step.gate) and all(gate[: len(step.gate)])
    if all(filled) and gates_ok:
        return "done"
    return "partial" if any(filled) or any(gate) else "empty"


# ---------- reading ----------

def _notes(con: sqlite3.Connection, paper_id: str) -> dict[str, sqlite3.Row]:
    rows = con.execute("SELECT step_id, data, seconds FROM notes WHERE paper_id = ?", (paper_id,))
    return {r["step_id"]: r for r in rows}


Frameworks = Framework | dict[str, Framework]


def _to_dict(con: sqlite3.Connection, row: sqlite3.Row, fws: Frameworks) -> dict[str, Any]:
    """fws is one framework, or one per template (then each paper is measured by its own)."""
    template = row["template"] or "paper"
    fw = fws if isinstance(fws, Framework) else fws.get(template, fws["paper"])
    notes = _notes(con, row["id"])
    progress = [step_state(s, json.loads(notes[s.id]["data"])) if s.id in notes else "empty"
                for s in fw.steps]
    paper = dict(row)
    paper["tags"] = json.loads(paper["tags"])
    paper["reflection_done"] = bool(paper["reflection_done"])
    paper["progress"] = progress
    paper["steps_done"] = progress.count("done")
    paper["seconds"] = sum(n["seconds"] for n in notes.values() if n["step_id"] in {st.id for st in fw.steps})
    paper["template"] = template
    paper["themes"] = [r[0] for r in con.execute(
        "SELECT theme_id FROM paper_themes pt JOIN themes t ON t.id = pt.theme_id WHERE paper_id = ? ORDER BY t.name",
        (row["id"],))]
    return paper


def _status(p: dict[str, Any]) -> str:
    if p["reflection_done"]:
        return "reflection_done"
    if p["steps_done"] == len(p["progress"]):
        return "notes_done"
    if all(s == "empty" for s in p["progress"]):
        return "not_started"
    return "in_progress"


def _fts_query(q: str) -> str:
    return " ".join(f'"{t}"*' for t in re.findall(r"\w+", q))


def list_papers(fw: Frameworks, q: str = "", status: Status = "all", sort: Sort = "date",
                theme: str = "") -> list[dict[str, Any]]:
    con = db.connect()
    match = _fts_query(q)
    if match:
        rows = con.execute("SELECT p.* FROM papers p JOIN papers_fts f ON f.paper_id = p.id "
                           "WHERE papers_fts MATCH ?", (match,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM papers").fetchall()
    papers = [_to_dict(con, r, fw) for r in rows]
    con.close()
    for p in papers:
        p["status"] = _status(p)
    if status != "all":
        papers = [p for p in papers if p["status"] == status]
    if theme:
        papers = [p for p in papers if (not p["themes"] if theme == "none" else theme in p["themes"])]
    if sort == "opened":
        papers.sort(key=lambda p: p["last_opened"] or "", reverse=True)  # never opened goes last
    elif sort == "title":
        papers.sort(key=lambda p: p["title"].lower())
    elif sort == "progress":
        papers.sort(key=lambda p: -p["steps_done"])
    else:
        papers.sort(key=_date_key)
    return papers


def _date_key(p: dict[str, Any]) -> tuple[int, int]:
    """Nearest presentation first: upcoming soonest, then past most recent, then no date."""
    if not p["presentation_date"]:
        return (2, 0)
    days = (date.fromisoformat(p["presentation_date"]) - date.today()).days
    return (0, days) if days >= 0 else (1, -days)


def get(fw: Frameworks, paper_id: str, touch: bool = False) -> dict[str, Any] | None:
    con = db.connect()
    with con:
        if touch:
            con.execute("UPDATE papers SET last_opened = datetime('now') WHERE id = ?", (paper_id,))
        row = con.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        paper = _to_dict(con, row, fw) if row else None
    con.close()
    if paper:
        paper["status"] = _status(paper)
    return paper


# ---------- changing ----------

def update(paper_id: str, patch: PaperPatch) -> bool:
    values = patch.model_dump(exclude_unset=True)
    if not values:
        return True
    if "tags" in values:
        values["tags"] = json.dumps(values["tags"])
    if "presentation_date" in values and values["presentation_date"]:
        values["presentation_date"] = values["presentation_date"].isoformat()
    sets = ", ".join(f"{k} = ?" for k in values)  # keys come from the PaperPatch model only
    con = db.connect()
    with con:
        found = con.execute(f"UPDATE papers SET {sets} WHERE id = ?", (*values.values(), paper_id)).rowcount
        if found:
            reindex(con, paper_id)
    con.close()
    return bool(found)


def delete(paper_id: str) -> bool:
    con = db.connect()
    with con:
        found = con.execute("DELETE FROM papers WHERE id = ?", (paper_id,)).rowcount
        con.execute("DELETE FROM papers_fts WHERE paper_id = ?", (paper_id,))
    con.close()
    (db.PAPERS_DIR / f"{paper_id}.pdf").unlink(missing_ok=True)
    (db.PAPERS_DIR / f"{paper_id}.png").unlink(missing_ok=True)
    return bool(found)


def cover(paper_id: str) -> Path | None:
    """A small picture of page 1 for the Library, made once and kept next to the PDF."""
    pdf = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not pdf.exists():
        return None
    png = db.PAPERS_DIR / f"{paper_id}.png"
    if not png.exists():
        with pymupdf.open(pdf) as doc:
            page = doc[0]
            page.get_pixmap(matrix=pymupdf.Matrix(360 / page.rect.width, 360 / page.rect.width)).save(png)
    return png


def _text_of(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text_of(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_text_of(v) for v in value.values())
    return ""


def reindex(con: sqlite3.Connection, paper_id: str) -> None:
    """Refresh the search row for one paper. Call inside the caller's transaction."""
    p = con.execute("SELECT title, authors, tags, note FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.execute("DELETE FROM papers_fts WHERE paper_id = ?", (paper_id,))
    if p:
        notes = " ".join(_text_of(json.loads(r["data"]).get("fields", {}))
                         for r in _notes(con, paper_id).values()) + " " + p["note"]
        con.execute("INSERT INTO papers_fts (paper_id, title, authors, tags, notes) VALUES (?, ?, ?, ?, ?)",
                    (paper_id, p["title"], p["authors"], " ".join(json.loads(p["tags"])), notes))
