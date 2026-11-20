"""Checker: the local model compares your notes for one step with the paper and gives hints, not answers.
Every check is saved, so you can see how your notes improved."""
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared import db
from pdf_research import framework, library, primer
from pdf_research.framework import Step
from shared.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "checker.txt"
Verdict = Literal["correct", "partial", "wrong", "missing"]
CheckError = primer.PrimerError


class FieldCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    field_id: str
    verdict: Verdict
    hint: str = ""
    pages: list[int] = []


class StepCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step_id: str
    fields: list[FieldCheck] = Field(min_length=1)
    overall: str = ""


def schema_for(step: Step, hint_words: int = 40) -> dict[str, Any]:
    """Field ids limited to the step's own; hint and overall capped in characters, so a chatty model stops in time."""
    ids = [f.id for f in step.fields]
    return {
        "type": "object",
        "properties": {
            "step_id": {"type": "string"},
            "fields": {"type": "array", "items": {
                "type": "object",
                "properties": {"field_id": {"type": "string", "enum": ids},
                               "verdict": {"type": "string", "enum": ["correct", "partial", "wrong", "missing"]},
                               "hint": {"type": "string", "maxLength": hint_words * 7}, "pages": {"type": "array", "items": {"type": "integer"}}},
                "required": ["field_id", "verdict", "hint", "pages"]}},
            "overall": {"type": "string", "maxLength": 240},
        },
        "required": ["step_id", "fields", "overall"],
    }


def system_prompt(step: Step, s: Settings) -> str:
    fields = "\n".join(f"{f.id}: {f.label}" for f in step.fields)
    return (PROMPT.read_text(encoding="utf-8").replace("{{settings.hint_words}}", str(s.hint_words))
            .replace("{{step.title}}", step.title).replace("{{step.fields}}", fields))


def note_text(value: Any) -> str:
    """A field's value as plain lines: table rows become 'a | b | c'."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        rows = [" | ".join(str(c).strip() for c in v) if isinstance(v, list) else str(v).strip() for v in value]
        return "\n".join(r for r in rows if r.strip(" |"))
    return ""


def notes_block(step: Step, fields: dict[str, Any]) -> str:
    return "\n\n".join(f"{f.id} ({f.label}):\n{note_text(fields.get(f.id)) or '(empty)'}" for f in step.fields)


def _tidy(text: str) -> str:
    """End on a full sentence: a reply cut by the length cap goes back to its last full stop."""
    text = text.strip()
    if not text or text[-1] in ".!?)]":
        return text
    end = max(text.rfind(". "), text.rfind("] "), text.rfind("? "))
    return text[:end + 1] if end >= 15 else text + "…"


def parse(text: str, step: Step, fields: dict[str, Any], hint_words: int) -> StepCheck:
    """Validate a reply. Empty notes are always 'missing'; hints are cut to the word limit."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("The reply has no JSON object.")
    out = StepCheck.model_validate_json(text[a:b + 1])
    by_id = {f.field_id: f for f in out.fields if f.field_id in {x.id for x in step.fields}}
    if not by_id:
        raise ValueError(f"No field matches this step. Use these field_id values: {', '.join(f.id for f in step.fields)}.")
    checked = []
    for f in step.fields:
        c = by_id.get(f.id) or FieldCheck(field_id=f.id, verdict="missing")
        if not note_text(fields.get(f.id)):
            c.verdict = "missing"
        if c.verdict == "correct":
            c.hint = ""
        c.hint = _tidy(" ".join(c.hint.split()[:hint_words + 10]))
        checked.append(c)
    out.fields, out.step_id = checked, step.id
    out.overall = _tidy(out.overall) if len(out.overall.split()) >= 4 else ""  # a bare "wrong" says nothing new
    return out


def check(s: Settings, paper_id: str, step_id: str) -> dict[str, Any] | None:
    """Check the saved notes for one step and store the result. None if the paper is not there.
    Raises KeyError for a step the checker does not cover, CheckError for model trouble."""
    con = db.connect()
    try:
        row = con.execute("SELECT title, template FROM papers WHERE id = ?", (paper_id,)).fetchone()
        note = con.execute("SELECT data FROM notes WHERE paper_id = ? AND step_id = ?", (paper_id, step_id)).fetchone()
    finally:
        con.close()
    pages = library.page_texts(paper_id)
    if row is None or pages is None:
        return None
    step = next((x for x in primer.steps_for(framework.load_template(row["template"])) if x.id == step_id), None)
    if step is None:
        raise KeyError(step_id)
    fields = json.loads(note["data"]).get("fields", {}) if note else {}
    if not any(note_text(fields.get(f.id)) for f in step.fields):
        raise CheckError("Write some notes in this step first.")
    system = system_prompt(step, s)
    ask = f'Check my notes for the step "{step.title}" (step_id "{step.id}"). {primer.PAGE_RULE} Return only JSON.\n\nMy notes:\n{notes_block(step, fields)}'
    paper = primer.step_context(step, primer.drop_references(pages), library.headings(paper_id), s, system + ask + row["title"])
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"Paper: {row['title']}\n\n<paper>\n{paper}\n</paper>\n\n{ask}"}]
    result = None
    for attempt in range(2):
        reply = primer._complete(s, messages, schema_for(step, s.hint_words), "check")
        try:
            result = parse(reply, step, fields, s.hint_words)
            break
        except (ValueError, ValidationError) as e:
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": f"That answer was not valid: {str(e)[:400]}\nReturn only JSON that matches the schema."}]
    if result is None:
        raise CheckError("The model did not return a valid answer. Try again.")
    con = db.connect()
    with con:
        cur = con.execute("INSERT INTO checks (paper_id, step_id, notes, result) VALUES (?, ?, ?, ?)",
                          (paper_id, step_id, json.dumps(fields), result.model_dump_json()))
        saved = con.execute("SELECT id, created_at FROM checks WHERE id = ?", (cur.lastrowid,)).fetchone()
    con.close()
    return {"id": saved["id"], "created_at": saved["created_at"], **primer.page_mapper(paper_id)(result.model_dump())}


def history(paper_id: str) -> dict[str, list[dict[str, Any]]] | None:
    """Every check for a paper, newest first, grouped by step. None if the paper is not there."""
    con = db.connect()
    try:
        if con.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is None:
            return None
        rows = con.execute("SELECT id, step_id, result, created_at FROM checks WHERE paper_id = ? ORDER BY id DESC",
                           (paper_id,)).fetchall()
    finally:
        con.close()
    out: dict[str, list[dict[str, Any]]] = {}
    fix = primer.page_mapper(paper_id) if rows else None
    for r in rows:
        out.setdefault(r["step_id"], []).append({"id": r["id"], "created_at": r["created_at"], **fix(json.loads(r["result"]))})
    return out
