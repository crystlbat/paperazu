"""Creatures: jobs Dot runs on your papers, one at a time.

A job is a trigger, a short chain of steps, and an output. The screen talks to the routes in main.py;
this module stores them and runs the queue. See docs/creatures-api.md.
"""
import json
import re
import threading
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import db, library, llm, marks, settings, steer, websearch
from .settings import Settings

# One call carries about 12_000 characters of the paper. A call that reads N papers gives each 1/N.
BUDGET = 12_000
MAX_QUEUED = 20
TRIGGERS = ("manual", "open", "page", "dwell", "highlight", "timer")
OUTPUTS = ("say", "ask", "card", "highlight", "doc", "note")
SCOPES = ("page", "selection", "paper", "each_paper", "sections", "references", "template", "prev", "similar")
# shortcut: a reference list can run past 12_000 characters; 24_000 still fits the context window.
SECTION_BUDGET = 24_000

# Tests set this and call execute() themselves, so a run is not taken by the worker mid-assertion.
pause = threading.Event()
_stopping: set[int] = set()
_started = False
_gate = threading.Lock()

SYSTEM = (
    "You help a student read research papers. Follow the instruction. "
    "Plain English, specific to the source, no preamble."
)
TALK = (
    "You turn what a student wants into one creature: a small job that reads their papers. "
    "Reply with JSON only, no markdown, in this shape: "
    '{"reply": "one or two sentences", "job": null or a job}. '
    "A job has name (short), color (0-7), trigger (manual, open, page, dwell, highlight, or timer), "
    "every (seconds, 20-3600), output (say, ask, card, highlight, doc, or note), papers ([]), "
    "template_id (null, or an id from the list below when a step uses the template scope), on (true), "
    "and steps (1 to 4 of {scope, prompt, model}). "
    "scope is page, selection, paper, each_paper, sections, references, template, or prev. model is always \"\". "
    "If you cannot tell what they want, job is null and reply asks a question.\n"
    "Templates:\n"
)


class Reject(Exception):
    def __init__(self, field: str, message: str) -> None:
        self.field, self.message = field, message


class QueueFull(Exception):
    pass


class StepIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scope: str
    prompt: str = ""
    model: str = ""

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        if v not in SCOPES:
            raise ValueError("Pick what this step reads.")
        return v

    @field_validator("prompt", "model")
    @classmethod
    def _clip(cls, v: str) -> str:
        return v.strip()[:4000] if isinstance(v, str) else ""


class JobIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    color: int = 0
    trigger: str = "manual"
    every: int = 120
    output: str = "doc"
    papers: list[str] = Field(default_factory=list)
    template_id: int | None = None
    steps: list[StepIn] = Field(default_factory=list)
    on: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()[:80]

    @field_validator("color")
    @classmethod
    def _color(cls, v: int) -> int:
        if not 0 <= v <= 7:
            raise ValueError("Pick one of the eight colours.")
        return v

    @field_validator("trigger")
    @classmethod
    def _trigger(cls, v: str) -> str:
        if v not in TRIGGERS:
            raise ValueError("Pick when it wakes.")
        return v

    @field_validator("output")
    @classmethod
    def _output(cls, v: str) -> str:
        if v not in OUTPUTS:
            raise ValueError("Pick what it leaves you.")
        return v

    @field_validator("every")
    @classmethod
    def _every(cls, v: int) -> int:
        if not 20 <= v <= 3600:
            raise ValueError("Use between 20 and 3600 seconds.")
        return v

    @field_validator("papers")
    @classmethod
    def _papers(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for p in v:
            p = (p or "").strip()[:40]
            if p and p not in out:
                out.append(p)
        if len(out) > 24:
            raise ValueError("Pick at most 24 papers.")
        return out

    @model_validator(mode="after")
    def _steps(self) -> "JobIn":
        if not self.name:
            raise ValueError("Give it a name.")
        if not self.steps:
            raise ValueError("Add at least one step.")
        if len(self.steps) > 8:
            raise ValueError("A creature can have at most 8 steps.")
        for i, s in enumerate(self.steps):
            if len(s.prompt) < 3:
                raise ValueError(f"Step {i + 1} needs an instruction.")
            s.model = s.model[:200]
        return self


class SectionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    ask: str = ""

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return v.strip()[:120]

    @field_validator("ask")
    @classmethod
    def _ask(cls, v: str) -> str:
        return v.strip()[:1000]


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    sections: list[SectionIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ok(self) -> "TemplateIn":
        self.name = self.name.strip()[:80]
        if not self.name:
            raise ValueError("Give the template a name.")
        self.sections = [s for s in self.sections if s.title]
        if not self.sections:
            raise ValueError("Add a heading.")
        if len(self.sections) > 24:
            raise ValueError("A shape can have at most 24 headings.")
        return self


class RunIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    paper_id: str = ""
    page: int | None = None
    text: str = ""
    paper: str = ""

    @field_validator("paper_id", "paper")
    @classmethod
    def _clip(cls, v: str) -> str:
        return (v or "").strip()[:300]

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        return (v or "")[:3000]

    @field_validator("page")
    @classmethod
    def _page(cls, v: int | None) -> int | None:
        if v is None or v < 1:
            return None
        return v


# Copied from the stand-in in static/creatures.js. Names are how "add the missing ones" decides.
STARTER_TEMPLATES: list[dict[str, Any]] = [
    {"name": "Research brief", "sections": [
        {"title": "The question", "ask": "What question does this work answer, and why does it matter? Two short paragraphs."},
        {"title": "What they did", "ask": "Describe the method step by step, in plain words, with the key design choices."},
        {"title": "What they found", "ask": "List the main results with their numbers, and what each one means."},
        {"title": "Limits", "ask": "What does this not show? Note weak spots, assumptions, and missing tests."},
        {"title": "Open questions", "ask": "Write five questions a curious student could follow up on."}]},
    {"name": "Comparison", "sections": [
        {"title": "The problem each tackles", "ask": "For each paper, say in one or two sentences what problem it tackles."},
        {"title": "Methods side by side", "ask": "Compare how the papers approach the problem. A short table, then what differs."},
        {"title": "Results side by side", "ask": "Compare their results and the evidence behind them."},
        {"title": "Where they disagree", "ask": "Where do the papers disagree or contradict each other?"},
        {"title": "Gaps", "ask": "What do none of them cover? Suggest a next study."}]},
]
STARTER_JOBS: list[dict[str, Any]] = [
    {"name": "Detailed outline", "color": 0, "trigger": "manual", "every": 120, "output": "doc", "template": "", "steps": [
        {"scope": "paper", "prompt": "List the sections of this paper and, for each, the one question it answers. Short lines.", "model": ""},
        {"scope": "sections", "prompt": "Write a detailed outline of this section: its claim, how they show it, the key numbers, and any terms a student must know. Nested bullet points, plain English.", "model": ""}]},
    {"name": "Simplified version", "color": 2, "trigger": "manual", "every": 120, "output": "doc", "template": "", "steps": [
        {"scope": "sections", "prompt": "Rewrite this section for a first-year student: short sentences, everyday words, one small example. Keep every idea; explain jargon the first time.", "model": ""}]},
    {"name": "Research brief", "color": 3, "trigger": "manual", "every": 120, "output": "doc", "template": "Research brief", "steps": [
        {"scope": "template", "prompt": "Answer this heading from the paper. Be thorough and specific; quote numbers.", "model": ""}]},
    {"name": "Compare papers", "color": 1, "trigger": "manual", "every": 120, "output": "doc", "template": "Comparison", "steps": [
        {"scope": "each_paper", "prompt": "Summarise this paper's problem, method, data and results in ten bullet points.", "model": ""},
        {"scope": "template", "prompt": "Using the summaries, answer this heading across all the papers.", "model": ""}]},
    {"name": "Quiz me", "color": 4, "trigger": "dwell", "every": 180, "output": "ask", "template": "", "steps": [
        {"scope": "page", "prompt": "Ask one short question that checks I understood the main idea of this page. Only the question.", "model": ""}]},
    {"name": "Explain my highlights", "color": 5, "trigger": "highlight", "every": 120, "output": "card", "template": "", "steps": [
        {"scope": "selection", "prompt": "Explain these words in two plain sentences, and say why they matter in this paper.", "model": ""}]},
    {"name": "Reference list", "color": 6, "trigger": "manual", "every": 120, "output": "note", "template": "", "steps": [
        {"scope": "references", "prompt": "List every paper in this reference list, one per line: authors, year, title. Copy only papers printed here. Do not add any, and do not number the lines.", "model": ""}]},
]


def errors(exc: ValidationError) -> list[dict[str, str]]:
    out = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        msg = str(err["msg"]).removeprefix("Value error, ")
        out.append({"field": ".".join(str(x) for x in loc) or "body", "message": msg})
    return out


def _exec(sql: str, args: tuple[Any, ...] = ()) -> tuple[int, int]:
    """Run one write. Returns (lastrowid, rowcount), read before the connection closes."""
    con = db.connect()
    try:
        with con:
            cur = con.execute(sql, args)
            return int(cur.lastrowid or 0), cur.rowcount
    finally:
        con.close()


def _one(sql: str, args: tuple[Any, ...] = ()) -> Any:
    con = db.connect()
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


def _all(sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
    con = db.connect()
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _job(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "color": row["color"], "trigger": row["trigger"],
            "every": row["every"], "output": row["output"], "papers": json.loads(row["papers"]),
            "template_id": row["template_id"], "steps": json.loads(row["steps"]), "on": bool(row["awake"])}


def _template(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "sections": json.loads(row["sections"])}


def _run(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "job_id": row["job_id"], "job": row["job_name"], "paper_id": row["paper_id"],
            "paper": row["paper"], "page": row["page"], "status": row["status"], "done": row["done"],
            "total": row["total"], "label": row["label"], "result": json.loads(row["result"] or "{}"),
            "error": row["error"], "created_at": row["created_at"], "finished_at": row["finished_at"]}


def _cols(data: JobIn) -> tuple[Any, ...]:
    steps = [s.model_dump() for s in data.steps]
    return (data.name, data.color, data.trigger, data.every, data.output, json.dumps(data.papers),
            data.template_id, json.dumps(steps), int(data.on))


def _check_template(template_id: int | None) -> None:
    if template_id is not None and not _one("SELECT 1 FROM job_templates WHERE id = ?", (template_id,)):
        raise Reject("template_id", "That shape is gone.")


def list_jobs() -> dict[str, Any]:
    return {"jobs": [_job(r) for r in _all("SELECT * FROM jobs ORDER BY id")]}


def create_job(data: JobIn) -> dict[str, Any]:
    _check_template(data.template_id)
    new_id, _ = _exec("""INSERT INTO jobs (name, color, trigger, every, output, papers, template_id, steps, awake)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", _cols(data))
    return _job(_one("SELECT * FROM jobs WHERE id = ?", (new_id,)))


def update_job(job_id: int, data: JobIn) -> dict[str, Any]:
    _check_template(data.template_id)
    _, n = _exec("""UPDATE jobs SET name=?, color=?, trigger=?, every=?, output=?, papers=?, template_id=?, steps=?, awake=?
                    WHERE id=?""", (*_cols(data), job_id))
    if n == 0:
        raise KeyError(job_id)
    return _job(_one("SELECT * FROM jobs WHERE id = ?", (job_id,)))


def delete_job(job_id: int) -> bool:
    return _exec("DELETE FROM jobs WHERE id = ?", (job_id,))[1] > 0


def list_templates() -> dict[str, Any]:
    return {"templates": [_template(r) for r in _all("SELECT * FROM job_templates ORDER BY id")]}


def create_template(data: TemplateIn) -> dict[str, Any]:
    new_id, _ = _exec("INSERT INTO job_templates (name, sections) VALUES (?, ?)",
                      (data.name, json.dumps([s.model_dump() for s in data.sections])))
    return _template(_one("SELECT * FROM job_templates WHERE id = ?", (new_id,)))


def update_template(template_id: int, data: TemplateIn) -> dict[str, Any]:
    _, n = _exec("UPDATE job_templates SET name=?, sections=? WHERE id=?",
                 (data.name, json.dumps([s.model_dump() for s in data.sections]), template_id))
    if n == 0:
        raise KeyError(template_id)
    return _template(_one("SELECT * FROM job_templates WHERE id = ?", (template_id,)))


def delete_template(template_id: int) -> bool:
    return _exec("DELETE FROM job_templates WHERE id = ?", (template_id,))[1] > 0


def starters() -> dict[str, Any]:
    """Add the starter jobs and templates whose names are not already there."""
    con = db.connect()
    try:
        with con:
            names = {r["name"] for r in con.execute("SELECT name FROM job_templates")}
            for t in STARTER_TEMPLATES:
                if t["name"] in names:
                    continue
                con.execute("INSERT INTO job_templates (name, sections) VALUES (?, ?)",
                            (t["name"], json.dumps(t["sections"])))
            ids = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM job_templates")}
            have = {r["name"] for r in con.execute("SELECT name FROM jobs")}
            for j in STARTER_JOBS:
                if j["name"] in have:
                    continue
                con.execute("""INSERT INTO jobs (name, color, trigger, every, output, papers, template_id, steps, awake)
                               VALUES (?, ?, ?, ?, ?, '[]', ?, ?, 1)""",
                            (j["name"], j["color"], j["trigger"], j["every"], j["output"],
                             ids.get(j["template"]) if j["template"] else None, json.dumps(j["steps"])))
    finally:
        con.close()
    return list_jobs()


def _title(paper_id: str) -> str:
    row = _one("SELECT title FROM papers WHERE id = ?", (paper_id,))
    return row["title"] if row else ""


def enqueue(job_id: int, body: RunIn) -> tuple[dict[str, Any], bool]:
    """Queue a run. Returns the run and whether it was newly queued (a duplicate returns the one already waiting)."""
    job = _one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job:
        raise Reject("job", "That creature is gone.")
    chosen = json.loads(job["papers"])
    if chosen:
        pids = chosen
    elif body.paper_id:
        pids = [body.paper_id]
    else:
        raise Reject("paper_id", "Pick a paper to run it on.")
    if any(library.page_texts(p) is None for p in pids):
        raise Reject("paper_id", "One of these papers is no longer in the library." if len(pids) > 1
                     else "That paper is not in the library.")
    key = json.dumps(pids)
    dup = _one("""SELECT * FROM job_runs WHERE job_id = ? AND paper_ids = ? AND status IN ('queued', 'running')
                  ORDER BY id LIMIT 1""", (job_id, key))
    if dup:
        return _run(dup), False
    if _one("SELECT COUNT(*) AS n FROM job_runs WHERE status = 'queued'")["n"] >= MAX_QUEUED:
        raise QueueFull()
    template = ""
    if job["template_id"]:
        t = _one("SELECT name, sections FROM job_templates WHERE id = ?", (job["template_id"],))
        if t:
            template = json.dumps({"name": t["name"], "sections": json.loads(t["sections"])})
    focus = body.paper_id if body.paper_id in pids else pids[0]
    paper = body.paper if len(pids) == 1 and body.paper else " · ".join(n for n in (_title(p) for p in pids) if n)
    new_id, _ = _exec("""INSERT INTO job_runs
                         (job_id, job_name, paper_id, paper, paper_ids, page, selection, output, steps, template_json)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (job_id, job["name"], focus, paper, key, body.page, body.text, job["output"], job["steps"], template))
    return _run(_one("SELECT * FROM job_runs WHERE id = ?", (new_id,))), True


def list_runs(limit: int = 30) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    rows = _all("SELECT * FROM job_runs ORDER BY id DESC LIMIT ?", (limit,))
    queued = _one("SELECT COUNT(*) AS n FROM job_runs WHERE status = 'queued'")["n"]
    return {"runs": [_run(r) for r in rows], "parallel": 1, "queued": queued}


def get_run(run_id: int) -> dict[str, Any] | None:
    row = _one("SELECT * FROM job_runs WHERE id = ?", (run_id,))
    return _run(row) if row else None


def stop(run_id: int) -> dict[str, Any] | None:
    """Queued stops at once. Running stops after the model call already in flight."""
    row = _one("SELECT * FROM job_runs WHERE id = ?", (run_id,))
    if not row:
        return None
    if row["status"] == "queued":
        _exec("UPDATE job_runs SET status = 'stopped', finished_at = datetime('now') WHERE id = ? AND status = 'queued'",
              (run_id,))
    elif row["status"] == "running":
        _stopping.add(run_id)
    fresh = _one("SELECT * FROM job_runs WHERE id = ?", (run_id,))
    return _run(fresh) if fresh else None


def fail_interrupted() -> None:
    """Runs left queued or running when the app last stopped never finished."""
    _exec("""UPDATE job_runs SET status = 'failed', error = 'The app restarted before this finished.',
             finished_at = datetime('now') WHERE status IN ('queued', 'running')""")


def _touch(run_id: int, **fields: Any) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    _exec(f"UPDATE job_runs SET {sets} WHERE id = ?", (*fields.values(), run_id))


def _finish(run_id: int, status: str, result: dict[str, Any] | None = None, error: str = "") -> None:
    _exec("""UPDATE job_runs SET status = ?, result = ?, error = ?, label = ?, finished_at = datetime('now')
             WHERE id = ? AND status = 'running'""",
          (status, json.dumps(result or {}), error, "", run_id))


def clip(text: str, n: int = BUDGET) -> str:
    return (text or "").strip()[:n]


def _paper_blob(paper_id: str, limit: int) -> str:
    pages = library.page_texts(paper_id) or []
    body = "\n\n".join(f"--- Page {i} ---\n{p.strip()}" for i, p in enumerate(pages, 1))
    return clip(f"Paper: {_title(paper_id)}\n\n{body}", limit)


def _heading_at(text: str, title: str) -> int | None:
    """Where a heading starts. The PDF often breaks '1 Introduction' across a line, so the number is ignored
    and the words may have any space between them."""
    bare = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", title).strip()
    words = [re.sub(r"[^\w]+$", "", w) for w in (bare.split() or title.split())]
    words = [w for w in words if w]
    if not words:
        return None
    pattern = r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b"
    found = re.search(pattern, text, re.I)
    return found.start() if found else None


def _sections(paper_id: str) -> list[tuple[str, str]]:
    """Level-1 headings found in the page text, each cut from that heading to the next.
    Fewer than two: two pages at a time."""
    pages = library.page_texts(paper_id) or []
    if not pages:
        return []
    joined = "\n\n".join(pages)
    offsets, pos = [], 0
    for page in pages:
        offsets.append(pos)
        pos += len(page) + 2
    found: list[tuple[int, str]] = []
    for level, title, pg in library.headings(paper_id):
        if level != 1 or not 1 <= pg <= len(pages):
            continue
        at = _heading_at(pages[pg - 1], title)
        if at is None:
            continue
        spot = offsets[pg - 1] + at
        if found and spot <= found[-1][0]:
            continue
        found.append((spot, title))
    found.sort()
    if len(found) < 2:
        return [(f"Pages {i + 1}–{min(i + 2, len(pages))}", "\n\n".join(pages[i:i + 2]))
                for i in range(0, len(pages), 2)]
    out = []
    for i, (spot, title) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(joined)
        out.append((title, joined[spot:end].strip()))
    return out


class _Unit:
    def __init__(self, label: str, text: str, ask: str = "", paper_id: str = "", page: int | None = None) -> None:
        self.label, self.text, self.ask, self.paper_id, self.page = label, text, ask, paper_id, page


def _parts(papers: list[str]) -> list[tuple[str, str]]:
    """The papers in pieces of at most BUDGET characters, section by section, references left out. Empty when
    all of them fit in one read, so a short paper is still read whole."""
    if sum(len(p) for pid in papers for p in library.page_texts(pid) or []) <= BUDGET:
        return []
    out = []
    for pid in papers:
        prefix = f"{_title(pid)}: " if len(papers) > 1 else ""
        for label, text in _sections(pid):
            if re.search(r"reference|bibliograph", label, re.I):
                continue
            for i in range(0, len(text), BUDGET):
                out.append((prefix + label + (" (cont.)" if i else ""), text[i:i + BUDGET]))
    return out


NOTES = ("Take notes on this part of a paper for the instruction below: the claims, methods, numbers and results "
         "that matter for it, in plain words. At most 120 words. If nothing here matters, write only: nothing.")


def _read_in_parts(s: Settings, step: dict[str, Any], template: dict[str, Any] | None, label: str, text: str) -> str:
    """Notes on one piece of a paper too long to read at once; the step then works from the notes of every piece."""
    want = step["prompt"] + "".join(f"\n- {x.get('title')}: {x.get('ask') or ''}" for x in (template or {}).get("sections") or [])
    note = complete(s, [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"{NOTES}\n\nInstruction: {want}\n\n<source part=\"{label}\">\n{text}\n</source>"}],
                    max_tokens=300)
    return f"## {label}\n{note.strip()}"


def _units(step: dict[str, Any], papers: list[str], template: dict[str, Any] | None,
           page: int | None, selection: str, prev: str, focus: str, notes: str = "") -> list[_Unit]:
    """`notes` stand in for the paper text of a paper or template step when the papers were read in parts."""
    scope = step["scope"]
    pid = focus if focus in papers else papers[0]
    if scope == "prev":
        return [_Unit("the step before", prev or "")]
    if scope == "page":
        pages = library.page_texts(pid) or []
        n = page if page and 1 <= page <= len(pages) else (1 if pages else None)
        return [_Unit(f"Page {n or 1}", clip(pages[n - 1] if n else ""), paper_id=pid, page=n)]
    if scope == "selection":
        return [_Unit("the highlight", clip(selection), paper_id=pid, page=page)]
    if scope == "similar":
        return [_Unit("Similar papers", _title(pid), paper_id=pid)]
    if scope == "each_paper":
        return [_Unit(_title(p) or f"Paper {i + 1}", _paper_blob(p, BUDGET), paper_id=p) for i, p in enumerate(papers)]
    if scope in ("sections", "references"):
        out = []
        for p in papers:
            chunks = _sections(p)
            if scope == "references":
                chunks = [(label, text) for label, text in chunks if re.search(r"reference|bibliograph", label, re.I)]
            prefix = f"{_title(p)}: " if len(papers) > 1 else ""
            out += [_Unit(prefix + label, clip(text, SECTION_BUDGET), paper_id=p) for label, text in chunks]
        return out or [_Unit("References" if scope == "references" else "the paper", "", paper_id=pid)]
    if scope == "template":
        secs = (template or {}).get("sections") or [{"title": "Notes", "ask": ""}]
        share = max(BUDGET // max(len(papers), 1), 1)
        blob = notes or "\n\n".join(_paper_blob(p, share) for p in papers)
        return [_Unit(s.get("title") or "Notes", blob, ask=s.get("ask") or "", paper_id=pid) for s in secs]
    share = max(BUDGET // max(len(papers), 1), 1)
    blob = notes or "\n\n".join(_paper_blob(p, share) for p in papers)
    return [_Unit("the papers" if len(papers) > 1 else "the paper", blob, paper_id=pid)]


def _ask(step: dict[str, Any], unit: _Unit, prev: str, highlight: bool) -> str:
    parts = [f"Instruction: {step['prompt']}"]
    if unit.ask:
        parts.append(f"Write the section \"{unit.label}\". What belongs there: {unit.ask}")
    if prev and step["scope"] != "prev":
        parts.append("What the step before wrote:\n" + prev[:8000])
    parts.append(f"<source>\n{unit.text}\n</source>")
    if highlight:
        parts.append("After the answer, write a line that is exactly QUOTES: and then up to 5 lines. "
                     "Each line is an exact quote copied from the source, at least four words.")
    return "\n\n".join(parts)


def _join(parts: list[tuple[str, str]]) -> str:
    if len(parts) == 1:
        return parts[0][1]
    return "\n\n".join(f"## {label}\n{text}" for label, text in parts)


def _split_quotes(text: str) -> tuple[str, list[str]]:
    if "QUOTES:" not in text:
        return text.strip(), []
    body, _, rest = text.partition("QUOTES:")
    quotes = []
    for line in rest.splitlines():
        line = re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line.strip()).strip().strip('"')
        if len(line.split()) >= 4:
            quotes.append(line)
    return body.strip(), quotes[:8]


def _mark(paper_id: str, page: int | None, quote: str) -> dict[str, Any] | None:
    pages = [page] if page else list(range(1, 9))
    for pg in pages:
        got = marks._page(paper_id, pg)
        if not got:
            continue
        with got[0]:
            found = marks._find(marks._words(got[1], got[1].rect), quote)
            rects = marks._lines(found)[:60] if found else []
        if not rects:
            continue
        saved = marks.add_highlight(paper_id, marks.HighlightIn(page=pg, kind="dot", text=quote[:2000], rects=rects))
        if saved:
            return {"page": pg, "text": quote[:2000]}
    return None


def complete(s: Settings, messages: list[dict[str, str]], **kw: Any) -> str:
    """One model call. Tests replace this. Raises llm.ModelError (a RuntimeError).
    While the harness steers the character's steps, they run on the steer engine whatever model the call's settings name."""
    if steer.ON:
        s = s.model_copy(update={"model_name": llm.STEER})
    return llm.chat(s, messages, **kw)


def _result(parts: list[tuple[str, str]], highlights: list[dict[str, Any]]) -> dict[str, Any]:
    return {"text": _join(parts) if parts else "", "sections": [[a, b] for a, b in parts] if len(parts) > 1 else [],
            "highlights": highlights}


def execute(run_id: int) -> None:
    """Run one queued job to the end. A running job (just claimed) is run too. Anything else is left alone."""
    con = db.connect()
    try:
        with con:
            cur = con.execute("UPDATE job_runs SET status = 'running' WHERE id = ? AND status = 'queued'", (run_id,))
            if cur.rowcount == 0:
                row = con.execute("SELECT status FROM job_runs WHERE id = ?", (run_id,)).fetchone()
                if not row or row["status"] != "running":
                    return
    finally:
        con.close()
    try:
        _work(run_id)
    except Exception as e:
        _finish(run_id, "failed", error=str(e) or "The model call failed.")
    finally:
        _stopping.discard(run_id)


def _work(run_id: int) -> None:
    row = _one("SELECT * FROM job_runs WHERE id = ?", (run_id,))
    if not row:
        return
    steps = json.loads(row["steps"])
    papers = json.loads(row["paper_ids"])
    template = json.loads(row["template_json"]) if row["template_json"] else None
    parts = _parts(papers) if any(s["scope"] in ("paper", "template") for s in steps) else []
    total = sum(len(_units(s, papers, template, row["page"], row["selection"], "x", row["paper_id"]))
                + (len(parts) if s["scope"] in ("paper", "template") else 0) for s in steps)
    _touch(run_id, total=max(total, 1), done=0)
    done = 0
    prev = ""
    last: list[tuple[str, str]] = []
    quotes: list[tuple[str, int | None, str]] = []
    for si, step in enumerate(steps):
        notes = []
        for label, text in parts if step["scope"] in ("paper", "template") else []:  # too long for one read: notes first
            if run_id in _stopping:
                _finish(run_id, "stopped", _result(last, []))
                return
            _touch(run_id, label=f"reading {label}")
            notes.append(_read_in_parts(_step_settings(step, row["output"]), step, template, label, text))
            done += 1
            _touch(run_id, done=done)
        units = _units(step, papers, template, row["page"], row["selection"], prev, row["paper_id"], "\n\n".join(notes))
        highlight = row["output"] == "highlight" and si == len(steps) - 1
        parts: list[tuple[str, str]] = []
        for unit in units:
            if run_id in _stopping:
                _finish(run_id, "stopped", _result(parts or last, []))
                return
            _touch(run_id, label=unit.label)
            cited = _cited(unit.text) if step.get("scope") == "references" else ""
            if step.get("scope") == "similar":
                answer = similar(unit.text)  # a web search, not a model answer: the list is what it found
            elif cited:
                answer = cited  # a numbered bibliography copies across; the model stops partway and drops the rest
            else:
                answer = complete(_step_settings(step, row["output"]), [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": _ask(step, unit, prev, highlight)}])
            found: list[str] = []
            if highlight:
                answer, found = _split_quotes(answer)
            parts.append((unit.label, answer))
            quotes += [(unit.paper_id or (papers[0] if papers else ""), unit.page, q) for q in found]
            done += 1
            _touch(run_id, done=done)
        prev = _join(parts)
        last = parts
    highlights = []
    if row["output"] == "highlight":
        for pid, pg, quote in quotes:
            if not pid:
                continue
            try:
                if hit := _mark(pid, pg, quote):
                    highlights.append(hit)
            except Exception:
                continue
    result = _result(last, highlights)
    if row["output"] == "note" and result["text"].strip():
        _save_note(row["paper_id"], result["text"], row["job_name"])
    _finish(run_id, "done", result)


def similar(title: str) -> str:
    """Papers like this one, from a web search: one line each, title and link. Raises RuntimeError when the web has none."""
    found = websearch.search(settings.get_all(), f"research papers similar to {title}")["results"][:8]
    lines = [f"- {r.get('title') or r.get('url')} — {r.get('url', '')}".rstrip(" —") for r in found if r.get("url") or r.get("title")]
    if not lines:
        raise RuntimeError(f"The web had no papers like {title}.")
    return "\n".join(lines)


def _step_settings(step: dict[str, Any], output: str) -> Settings:
    s = settings.get_all()
    pinned: dict[str, Any] = {"model_name": step["model"]} if step.get("model") else {}
    if output == "note":
        pinned["max_output_tokens"] = max(s.max_output_tokens, 4096)  # a reference list is longer than a usual answer
    return s.model_copy(update=pinned) if pinned else s


def _cited(text: str) -> str:
    """The numbered references, one per line. Empty when this text is not a bibliography."""
    lines = text.splitlines()
    counts: dict[str, int] = {}
    for line in lines:
        s = line.strip()
        if s:
            counts[s] = counts.get(s, 0) + 1
    furniture = {s for s, n in counts.items() if n >= 2 and not re.match(r"\[\d+\]", s)}
    kept = "\n".join(line for line in lines if line.strip() not in furniture)
    rows: list[str] = []
    for part in re.split(r"(?=\[\d+\])", kept):
        m = re.match(r"\[(\d+)\]\s*(.*)", part, re.S)
        if not m:
            continue
        body = re.sub(r"-\s+", "", m.group(2))
        body = re.sub(r"\s+", " ", body)
        body = re.sub(r"\s+\d{3,4}$", "", body).strip(" -")
        if len(body) >= 12:
            rows.append(f"[{m.group(1)}] {body}")
    return "\n".join(rows) if len(rows) >= 2 else ""


def _save_note(paper_id: str, text: str, title: str) -> None:
    """Add the creature's output to the note under its own heading. A second run replaces its earlier block and leaves the rest."""
    row = _one("SELECT note FROM papers WHERE id = ?", (paper_id,))
    if not row:
        return
    fence = f"--- {title.strip() or 'Creature'} ---"
    block = f"{fence}\n{text.strip()}\n---"
    old = row["note"] or ""
    if fence in old:
        note = re.sub(r"\n*" + re.escape(fence) + r"\n.*?\n---", lambda _: "\n\n" + block, old, count=1, flags=re.S)
    else:
        note = (old.rstrip() + "\n\n" if old.strip() else "") + block
    note = note.strip() + "\n"
    con = db.connect()
    try:
        with con:
            con.execute("UPDATE papers SET note = ? WHERE id = ?", (note[:200_000], paper_id))
            library.reindex(con, paper_id)
    finally:
        con.close()


def _claim() -> int | None:
    """The oldest queued run, if nothing is already running."""
    con = db.connect()
    try:
        with con:
            if con.execute("SELECT 1 FROM job_runs WHERE status = 'running'").fetchone():
                return None
            row = con.execute("SELECT id FROM job_runs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            cur = con.execute("UPDATE job_runs SET status = 'running' WHERE id = ? AND status = 'queued'", (row["id"],))
            return row["id"] if cur.rowcount else None
    finally:
        con.close()


def _loop() -> None:
    while True:
        if pause.is_set():
            time.sleep(0.2)
            continue
        try:
            rid = _claim()
        except Exception:
            time.sleep(0.5)
            continue
        if not rid:
            time.sleep(0.3)
            continue
        execute(rid)


def start() -> None:
    """One worker for the life of the process. Anything left from the last run is marked failed first."""
    global _started
    with _gate:
        if _started:
            return
        fail_interrupted()
        _started = True
        threading.Thread(target=_loop, name="creatures", daemon=True).start()


def talk(messages: list[Any]) -> dict[str, Any]:
    """Ask the model for a creature. Returns a draft; nothing is saved."""
    said = ""
    clean: list[dict[str, str]] = []
    for m in messages[-12:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        content = str(m.get("content") or "").strip()[:2000]
        if not content:
            continue
        clean.append({"role": m["role"], "content": content})
        if m["role"] == "user":
            said = content
    if len(said) < 6:
        return {"reply": "Tell me what you want done while you read, and I will turn it into a creature.", "job": None}
    names = "\n".join(f"{r['id']}: {r['name']}" for r in _all("SELECT id, name FROM job_templates ORDER BY id")) or "none yet"
    # json_object makes the server hold the reply to valid JSON; small models otherwise break it and Dot reads it out raw
    text = complete(settings.get_all(), [{"role": "system", "content": TALK + names}, *clean], response_format={"type": "json_object"})
    return _draft(text)


def _draft(text: str) -> dict[str, Any]:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        found = re.search(r"\{.*\}", text, re.S)
        try:
            data = json.loads(found.group(0)) if found else None
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        return {"reply": text.strip()[:2000] or "I lost my words. Say it again?", "job": None}
    reply = str(data.get("reply") or "Here is a creature for that. Check the steps, then hatch it.")[:2000]
    if not data.get("job"):
        return {"reply": reply, "job": None}
    try:
        job = JobIn.model_validate(data["job"])
    except ValidationError:
        return {"reply": reply, "job": None}
    if job.template_id is not None and not _one("SELECT 1 FROM job_templates WHERE id = ?", (job.template_id,)):
        job.template_id = None
    return {"reply": reply, "job": job.model_dump()}
