"""The paper library: add, guess details, list, edit, delete, search, progress."""
import json
import re
import sqlite3
import uuid
from datetime import date
from typing import Any, Literal

import pymupdf
from pydantic import BaseModel, ConfigDict, field_validator

from . import db
from .framework import Framework, Step

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
    con = db.connect()
    with con:
        con.execute("INSERT INTO papers (id, title, authors) VALUES (?, ?, ?)",
                    (paper_id, details["title"], details["authors"]))
        reindex(con, paper_id)
    con.close()
    return paper_id


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


def _to_dict(con: sqlite3.Connection, row: sqlite3.Row, fw: Framework) -> dict[str, Any]:
    notes = _notes(con, row["id"])
    progress = [step_state(s, json.loads(notes[s.id]["data"])) if s.id in notes else "empty"
                for s in fw.steps]
    paper = dict(row)
    paper["tags"] = json.loads(paper["tags"])
    paper["reflection_done"] = bool(paper["reflection_done"])
    paper["progress"] = progress
    paper["steps_done"] = progress.count("done")
    paper["seconds"] = sum(n["seconds"] for n in notes.values())
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


def list_papers(fw: Framework, q: str = "", status: Status = "all", sort: Sort = "date") -> list[dict[str, Any]]:
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


def get(fw: Framework, paper_id: str, touch: bool = False) -> dict[str, Any] | None:
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
    return bool(found)


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
    p = con.execute("SELECT title, authors, tags FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.execute("DELETE FROM papers_fts WHERE paper_id = ?", (paper_id,))
    if p:
        notes = " ".join(_text_of(json.loads(r["data"]).get("fields", {}))
                         for r in _notes(con, paper_id).values())
        con.execute("INSERT INTO papers_fts (paper_id, title, authors, tags, notes) VALUES (?, ?, ?, ?, ?)",
                    (paper_id, p["title"], p["authors"], " ".join(json.loads(p["tags"])), notes))
