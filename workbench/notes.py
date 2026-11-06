"""Reader's notebook: one saved row per paper and step."""
import json
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

from . import db, library
from .framework import Framework

MAX_BODY_BYTES = 200 * 1024
Value = str | list[str] | list[list[str]]


class NoteError(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(errors)
        self.errors = errors


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Value]
    gate: list[StrictBool]
    seconds: StrictInt = Field(ge=0, le=86400)


def _parse(body: bytes) -> NoteIn:
    if len(body) > MAX_BODY_BYTES:
        raise NoteError({"": "These notes are too large to save (200 KB at most)."})
    try:
        return NoteIn.model_validate_json(body)
    except ValidationError as e:
        raise NoteError({".".join(str(p) for p in err["loc"][:2]): err["msg"] for err in e.errors()})


def _summary(fw: Framework, rows: list[sqlite3.Row]) -> dict[str, Any]:
    steps = {s.id: s for s in fw.steps}
    out: dict[str, Any] = {}
    for r in rows:
        data = json.loads(r["data"])
        state = library.step_state(steps[r["step_id"]], data) if r["step_id"] in steps else "partial"
        out[r["step_id"]] = {"fields": data.get("fields", {}), "gate": data.get("gate", []),
                             "seconds": r["seconds"], "state": state, "updated_at": r["updated_at"]}
    return out


def _done(fw: Framework, steps: dict[str, Any]) -> int:
    ids = {s.id for s in fw.steps}
    return sum(1 for k, v in steps.items() if k in ids and v["state"] == "done")


def _exists(con: sqlite3.Connection, paper_id: str) -> bool:
    return con.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is not None


def load(fw: Framework, paper_id: str) -> dict[str, Any] | None:
    """All saved steps for a paper, or None if the paper does not exist."""
    con = db.connect()
    try:
        if not _exists(con, paper_id):
            return None
        rows = con.execute("SELECT * FROM notes WHERE paper_id = ?", (paper_id,)).fetchall()
    finally:
        con.close()
    steps = _summary(fw, rows)
    return {"steps": steps, "steps_done": _done(fw, steps), "total_steps": len(fw.steps)}


def save(fw: Framework, paper_id: str, step_id: str, body: bytes) -> dict[str, Any] | None:
    """Upsert one step; request fields merge over stored ones. None if the paper does not exist.
    Raises NoteError(errors) for bad input."""
    con = db.connect()
    try:
        if not _exists(con, paper_id):
            return None
        if step_id not in {s.id for s in fw.steps}:
            raise NoteError({"step_id": "This step is not in the framework."})
        note = _parse(body)
        with con:
            old = con.execute("SELECT data FROM notes WHERE paper_id = ? AND step_id = ?",
                              (paper_id, step_id)).fetchone()
            fields = {**(json.loads(old["data"]).get("fields", {}) if old else {}), **note.fields}
            con.execute(
                "INSERT INTO notes (paper_id, step_id, data, seconds, updated_at) "
                "VALUES (?, ?, ?, ?, datetime('now')) ON CONFLICT (paper_id, step_id) DO UPDATE SET "
                "data = excluded.data, seconds = excluded.seconds, updated_at = excluded.updated_at",
                (paper_id, step_id, json.dumps({"fields": fields, "gate": note.gate}), note.seconds))
            library.reindex(con, paper_id)
        rows = con.execute("SELECT * FROM notes WHERE paper_id = ?", (paper_id,)).fetchall()
    finally:
        con.close()
    steps = _summary(fw, rows)
    return {"state": steps[step_id]["state"], "steps_done": _done(fw, steps),
            "total_steps": len(fw.steps), "updated_at": steps[step_id]["updated_at"]}
