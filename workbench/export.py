"""Export: a paper's notebook as Markdown, and a reflection outline built only from your own notes.
For the outline the model never writes text: it only sorts numbered notes into sections, and the
app copies your words in as they are, so no new facts can appear."""
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from . import db, framework, library, primer
from .framework import Field, Framework
from .settings import Settings

DEFAULT_REFLECTION = [
    ("Paper information", "Title and presenters."),
    ("Research problem / challenge", "What problem does the paper take on, and why is it hard or important?"),
    ("Proposed solution and results", "What did the authors do, and what did they find?"),
    ("Reflection and critical analysis", "What is strong or weak? What is missing? What would you do next?"),
    ("Feedback for presenters", "Fill this in after the talk."),
]
TEMPLATE_NAME = {"paper": "Research paper", "slides": "Lecture slides"}


def _load(paper_id: str) -> tuple[dict[str, Any], Framework, dict[str, dict[str, Any]]] | None:
    fws = framework.load_all()
    paper = library.get(fws, paper_id)
    if paper is None:
        return None
    con = db.connect()
    rows = con.execute("SELECT step_id, data FROM notes WHERE paper_id = ?", (paper_id,)).fetchall()
    con.close()
    return paper, fws.get(paper["template"], fws["paper"]), {r["step_id"]: json.loads(r["data"]) for r in rows}


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def field_md(f: Field, value: Any) -> str:
    """One field as Markdown, or '' when it is empty."""
    if f.type == "rows" and isinstance(value, list):
        rows = [r for r in value if isinstance(r, list) and any(str(c).strip() for c in r)]
        if not rows:
            return ""
        cols = (["#"] if f.numbered else []) + (f.cols or [])
        lines = ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols)]
        lines += ["| " + " | ".join(([str(i)] if f.numbered else []) + [_cell(c) for c in r]) + " |" for i, r in enumerate(rows, 1)]
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(f"- {_cell(v)}" for v in value if str(v).strip())
    return str(value or "").strip()


def markdown(paper_id: str) -> str | None:
    """The whole notebook for one paper. None if the paper is not there."""
    got = _load(paper_id)
    if got is None:
        return None
    paper, fw, saved = got
    facts = [("Authors", paper["authors"]), ("Venue", paper["venue"]), ("Presenters", paper["presenters"]),
             ("Talk date", paper["presentation_date"] or ""), ("Course", paper["course"]),
             ("Read as", TEMPLATE_NAME.get(paper["template"], "")), ("Tags", ", ".join(paper["tags"]))]
    out = [f"# {paper['title']}", "", *[f"- {k}: {v}" for k, v in facts if v], ""]
    for st in fw.steps:
        data = saved.get(st.id, {})
        fields = data.get("fields", {})
        parts = [(f.label, field_md(f, fields.get(f.id))) for f in st.fields]
        parts = [(label, md) for label, md in parts if md]
        out += [f"## Step {st.n}: {st.title}", ""]
        if not parts:
            out += ["_Not written yet._", ""]
            continue
        for label, md in parts:
            out += [f"**{label}**", "", md, ""]
        gate = data.get("gate", [])
        if st.gate and any(gate):
            out += [f"- [{'x' if i < len(gate) and gate[i] else ' '}] {g}" for i, g in enumerate(st.gate)] + [""]
    if paper["note"].strip():
        out += ["## My note", "", paper["note"].strip(), ""]
    return "\n".join(out).rstrip() + "\n"


# ---------- reflection outline ----------
class Placement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    section: int
    note_ids: list[str] = []


class Outline(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sections: list[Placement]


SORT_SYSTEM = (
    "You help a student plan a written reflection on a paper. You get the student's own notes, each with an id "
    "like n4, and the sections of the reflection. Put each note id in the one section where it fits best. "
    "Leave out notes that fit nowhere. Do not write any text of your own. Return only JSON that matches the schema."
)


def snippets(fw: Framework, saved: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    """(id, where it came from, the note in Markdown) for every field you filled in, steps 1 and up."""
    out = []
    for st in fw.steps:
        if st.n < 1:
            continue
        fields = saved.get(st.id, {}).get("fields", {})
        for f in st.fields:
            md = field_md(f, fields.get(f.id))
            if md:
                out.append((f"n{len(out) + 1}", f"{st.title}: {f.label}", md))
    return out


def _schema(ids: list[str]) -> dict[str, Any]:
    return {"type": "object", "required": ["sections"], "properties": {"sections": {"type": "array", "items": {
        "type": "object", "required": ["section", "note_ids"],
        "properties": {"section": {"type": "integer", "enum": [2, 3, 4]},
                       "note_ids": {"type": "array", "items": {"type": "string", "enum": ids}}}}}}}


def place(s: Settings, notes: list[tuple[str, str, str]], sections: list[tuple[str, str]]) -> dict[int, list[str]]:
    """Ask the model which section each note belongs in (sections 2 to 4). Raises PrimerError."""
    ids = [i for i, _, _ in notes]
    listing = "\n\n".join(f"{i} (from {src}):\n{md[:600]}" for i, src, md in notes)
    secs = "\n".join(f"{n}. {name}: {q}" for n, (name, q) in enumerate(sections, 1) if 2 <= n <= 4)
    messages = [{"role": "system", "content": SORT_SYSTEM},
                {"role": "user", "content": f"Sections:\n{secs}\n\nMy notes:\n{listing}\n\nReturn the JSON."}]
    for attempt in range(2):
        reply = primer._complete(s, messages, _schema(ids), "outline")
        a, b = reply.find("{"), reply.rfind("}")
        try:
            outline = Outline.model_validate_json(reply[a:b + 1] if a >= 0 else reply)
        except ValidationError as e:
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": f"That answer was not valid: {str(e)[:300]}\nReturn only JSON."}]
            continue
        placed: dict[int, list[str]] = {2: [], 3: [], 4: []}
        seen: set[str] = set()
        for p in outline.sections:
            for i in p.note_ids:
                if p.section in placed and i in ids and i not in seen:  # each note once, in a real section
                    placed[p.section].append(i)
                    seen.add(i)
        return placed
    raise primer.PrimerError("The model did not return a valid answer. Try again.")


def reflection(s: Settings, paper_id: str) -> str | None:
    """The reflection outline in Markdown. None if the paper is not there. Raises PrimerError."""
    got = _load(paper_id)
    if got is None:
        return None
    paper, fw, saved = got
    notes = snippets(fw, saved)
    if not notes:
        raise primer.PrimerError("Write some notes first. The outline uses only your own words.")
    placed = place(s, notes, DEFAULT_REFLECTION)
    text = {i: (src, md) for i, src, md in notes}
    out = [f"# Reflection outline: {paper['title']}", "",
           "_Every line below is from your own notes. Your model only chose where each note goes._", ""]
    for n, (name, question) in enumerate(DEFAULT_REFLECTION, 1):
        out += [f"## {n}. {name}", "", f"_{question}_", ""]
        if n == 1:
            out += [f"- Title: {paper['title']}"] + ([f"- Presenters: {paper['presenters']}"] if paper["presenters"] else []) + [""]
        elif n == 5:
            out += ["", ""]
        elif placed[n]:
            for i in placed[n]:
                src, md = text[i]
                out += [f"From {src}:", "", md, ""]
        else:
            out += ["_None of your notes went here yet._", ""]
    left = [i for i, _, _ in notes if not any(i in v for v in placed.values())]
    if left:
        out += ["## Notes not placed", ""] + [f"From {text[i][0]}:\n\n{text[i][1]}\n" for i in left]
    return "\n".join(out).rstrip() + "\n"
