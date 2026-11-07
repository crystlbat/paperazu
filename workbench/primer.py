"""AI summary (the primer): a short model-written summary for each reading step, made before you read.
One model call per step, run in a background thread; results are cached in SQLite until you ask again."""
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import context, db, framework, library, llm
from .framework import Step
from .settings import Settings, get_all

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "primer.txt"
log = logging.getLogger("workbench.primer")


class PrimerError(Exception):
    """A message the user can act on."""


class FieldSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    field_id: str
    summary: str = Field(min_length=1)
    pages: list[int] = []


class StepPrimer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step_id: str
    fields: list[FieldSummary] = Field(min_length=1)
    where_to_look: str = ""


SCHEMA = {
    "type": "object",
    "properties": {
        "step_id": {"type": "string"},
        "fields": {"type": "array", "items": {
            "type": "object",
            "properties": {"field_id": {"type": "string"}, "summary": {"type": "string"},
                           "pages": {"type": "array", "items": {"type": "integer"}}},
            "required": ["field_id", "summary", "pages"]}},
        "where_to_look": {"type": "string"},
    },
    "required": ["step_id", "fields", "where_to_look"],
}


def steps_for(fw: framework.Framework) -> list[Step]:
    """Steps 1 to 7 that read the paper. The paper card, the self-test and open questions get none."""
    return [s for s in fw.steps if 1 <= s.n <= 7 and not s.paper_hidden and s.look_in]


def system_prompt(step: Step, s: Settings) -> str:
    fields = "\n".join(f"{f.id}: {f.label}" for f in step.fields)
    return (PROMPT.read_text(encoding="utf-8").replace("{{settings.primer_sentences}}", str(s.primer_sentences))
            .replace("{{step.title}}", step.title).replace("{{step.fields}}", fields))


# ---------- what each step reads ----------
_REFS = re.compile(r"^\s*(?:\d+\.?\s*)?(references|bibliography)\s*$", re.I | re.M)


def drop_references(pages: list[str]) -> list[str]:
    """Cut the reference list (from a References heading in the back half) out of what the model reads."""
    for i in range(len(pages) - 1, len(pages) // 2 - 1, -1):
        m = _REFS.search(pages[i])
        if m:
            return pages[:i] + ([pages[i][:m.start()]] if pages[i][:m.start()].strip() else [])
    return pages


def _fallback(step: Step, n: int) -> list[int]:
    """Pages to read when no heading matches the step: the spec's rough places in a paper."""
    if step.id in ("first", "problem"):
        return list(range(min(2, n)))
    if step.id in ("limits", "impact"):
        return list(range(max(0, n - 3), n))
    if step.id in ("method", "results"):
        return list(range(n // 4, max(n // 4 + 1, 3 * n // 4)))
    return list(range(n))


def step_pages(step: Step, n: int, heads: list[tuple[int, str, int]]) -> list[int]:
    """0-based pages under the headings that match the step's look_in names."""
    want = [w.lower() for w in step.look_in]
    chosen: set[int] = set()
    for i, (_, title, page) in enumerate(heads):
        if any(w in title.lower() for w in want):
            end = next((p for _, _, p in heads[i + 1:] if p > page), page + 1)
            chosen.update(range(page - 1, min(end - 1, n)) if end > page else [page - 1])
    return sorted(p for p in chosen if 0 <= p < n) or _fallback(step, n)


def labelled(pages: list[str], keep: list[int]) -> str:
    return "\n\n".join(f"[p. {i + 1}]\n{pages[i].strip()}" for i in keep)


def step_context(step: Step, pages: list[str], heads: list[tuple[int, str, int]], s: Settings, overhead: str) -> str:
    """The whole paper when it fits in 60% of the budget (so every step can cite any page);
    otherwise the step's own pages, trimmed to the budget around where they start."""
    budget = s.max_context_tokens - s.max_output_tokens - context.tokens(overhead) - 200
    every = list(range(len(pages)))
    if context.tokens(labelled(pages, every)) <= 0.6 * budget:
        return labelled(pages, every)
    # shortcut: no map-reduce over section summaries; a long step sends the pages nearest its sections.
    mine = step_pages(step, len(pages), heads)
    keep = context.fit_pages([pages[i] if i in mine else "" for i in every], budget, mine[0])
    keep = [i for i in keep if i in mine] or mine[:1]
    room = int(budget * context.CHARS_PER_TOKEN)
    return labelled(pages, keep)[:max(room, 0)]


# ---------- one step ----------
_json_schema_ok = True  # llama-server takes json_schema; if it refuses once, use json_object from then on


def schema_for(step: Step) -> dict[str, Any]:
    """The schema with this step's field ids as the only allowed values, so the model cannot invent fields."""
    out = json.loads(json.dumps(SCHEMA))
    out["properties"]["fields"]["items"]["properties"]["field_id"]["enum"] = [f.id for f in step.fields]
    return out


def _complete(s: Settings, messages: list[dict[str, str]], schema: dict[str, Any] = SCHEMA) -> str:
    global _json_schema_ok
    fmt: dict[str, Any] = ({"type": "json_schema", "json_schema": {"name": "primer", "schema": schema}}
                           if _json_schema_ok else {"type": "json_object"})
    try:
        r = llm.client(s).chat.completions.create(model=llm.pick_model(s) or "default", messages=messages,
                                                  max_tokens=s.max_output_tokens, temperature=s.temperature,
                                                  response_format=fmt)  # type: ignore[arg-type]
    except AuthenticationError:
        raise PrimerError("Wrong API key. Check it in Settings.")
    except APIConnectionError:
        raise PrimerError("Could not reach the model. Is Unsloth running?")
    except APIStatusError as e:
        if _json_schema_ok and e.status_code in (400, 422, 500, 501):
            _json_schema_ok = False
            return _complete(s, messages, schema)
        raise PrimerError(e.message)
    except APIError as e:
        raise PrimerError(e.message)
    text = llm._strip_thinking(r.choices[0].message.content or "")
    if text is None:
        raise PrimerError("The model ran out of room before it answered. Raise Max output tokens in Settings.")
    return text


def parse(text: str, step: Step) -> StepPrimer:
    """Validate a reply; keep only the step's own fields. Raises ValueError or ValidationError."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("The reply has no JSON object.")
    out = StepPrimer.model_validate_json(text[a:b + 1])
    ids = {f.id for f in step.fields}
    if len(step.fields) == 1 and out.fields and not any(f.field_id in ids for f in out.fields):
        # a one-field step (often a table): small models split it into one entry per row; join them
        out.fields = [FieldSummary(field_id=step.fields[0].id, summary=" ".join(f.summary.strip() for f in out.fields),
                                   pages=sorted({p for f in out.fields for p in f.pages}))]
    out.fields = [f for f in out.fields if f.field_id in ids and f.summary.strip()]
    if not out.fields:
        raise ValueError(f"No field matches this step. Use these field_id values: {', '.join(sorted(ids))}.")
    out.step_id = step.id
    return out


def make_step(s: Settings, step: Step, title: str, pages: list[str], heads: list[tuple[int, str, int]]) -> StepPrimer:
    system = system_prompt(step, s)
    ask = f'Write the primer for the step "{step.title}" (step_id "{step.id}"). Return only JSON.'
    paper = step_context(step, pages, heads, s, system + ask + title)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\n{ask}"}]
    for attempt in range(2):
        reply = _complete(s, messages, schema_for(step))
        try:
            return parse(reply, step)
        except (ValueError, ValidationError) as e:
            if attempt:
                break
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": f"That answer was not valid: {str(e)[:400]}\nReturn only JSON that matches the schema."}]
    raise PrimerError("The model did not return a valid answer. Try again.")


# ---------- the job ----------
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _set_status(paper_id: str, status: str) -> None:
    con = db.connect()
    with con:
        con.execute("UPDATE papers SET primer_status = ? WHERE id = ?", (status, paper_id))
    con.close()


def start(paper_id: str) -> None:
    """Start making the summary unless it is already being made."""
    with _lock:
        if _jobs.get(paper_id, {}).get("state") == "making":
            return
        _jobs[paper_id] = {"state": "making", "done": 0, "total": 0, "step": "", "error": ""}
    _set_status(paper_id, "making")
    threading.Thread(target=_run, args=(paper_id,), daemon=True).start()


def _run(paper_id: str) -> None:
    job = _jobs[paper_id]
    try:
        con = db.connect()
        row = con.execute("SELECT title, template FROM papers WHERE id = ?", (paper_id,)).fetchone()
        con.close()
        pages = library.page_texts(paper_id)
        if row is None or pages is None:
            raise PrimerError("This paper is not in the library.")
        s = get_all()
        steps = steps_for(framework.load_template(row["template"]))
        pages, heads = drop_references(pages), library.headings(paper_id)
        job["total"] = len(steps)
        made: list[tuple[str, str]] = []
        for i, step in enumerate(steps):
            job.update(done=i, step=step.title)
            made.append((step.id, make_step(s, step, row["title"], pages, heads).model_dump_json()))
        con = db.connect()
        with con:  # swap the old summary for the new one only when every step worked
            con.execute("DELETE FROM primers WHERE paper_id = ?", (paper_id,))
            con.executemany("INSERT INTO primers (paper_id, step_id, data) VALUES (?, ?, ?)",
                            [(paper_id, sid, data) for sid, data in made])
            con.execute("UPDATE papers SET primer_status = 'ready' WHERE id = ?", (paper_id,))
        con.close()
        job.update(state="ready", done=len(steps), step="")
    except PrimerError as e:
        job.update(state="failed", error=str(e))
        _set_status(paper_id, "failed")
    except Exception:
        log.exception("AI summary failed for paper %s", paper_id)  # the API key is never in these messages
        job.update(state="failed", error="Something went wrong while making the summary. Try again.")
        _set_status(paper_id, "failed")


def progress(paper_id: str) -> dict[str, Any]:
    if paper_id in _jobs:
        return dict(_jobs[paper_id])
    con = db.connect()
    row = con.execute("SELECT primer_status FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.close()
    return {"state": row["primer_status"] if row else "not_made", "done": 0, "total": 0, "step": "", "error": ""}


def load(paper_id: str) -> dict[str, Any] | None:
    """The saved summary, step by step, plus the job's progress. None if the paper does not exist."""
    con = db.connect()
    try:
        if con.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is None:
            return None
        rows = con.execute("SELECT step_id, data FROM primers WHERE paper_id = ?", (paper_id,)).fetchall()
    finally:
        con.close()
    return {"progress": progress(paper_id), "steps": {r["step_id"]: json.loads(r["data"]) for r in rows}}


def reset_stale() -> None:
    """A summary still marked 'making' when the app starts was cut off by a restart."""
    con = db.connect()
    with con:
        con.execute("UPDATE papers SET primer_status = 'failed' WHERE primer_status = 'making'")
    con.close()
