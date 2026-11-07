"""FastAPI app: API routes plus the one-page frontend."""
import json
import os
import time
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import checker, db, export, guide, marks, framework, graph, library, llm, notes, primer, settings, themes

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PORT = int(os.environ.get("PORT", "8765"))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init()
    library.pick_missing_templates()
    primer.reset_stale()
    yield


app = FastAPI(title="Paper Reading Workbench", lifespan=lifespan)


@app.middleware("http")
async def no_stale_assets(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"  # revalidate, so UI edits show at once
    return response


@app.get("/framework")
def get_framework(template: framework.Template = "paper") -> dict[str, Any]:
    return framework.load_template(template).model_dump()


@app.get("/frameworks")
def get_frameworks() -> dict[str, Any]:
    return {name: fw.model_dump() for name, fw in framework.load_all().items()}


def _fw_of(paper_id: str) -> framework.Framework:
    """The step list this paper is read with."""
    con = db.connect()
    row = con.execute("SELECT template FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.close()
    return framework.load_template(row["template"] if row else "paper")


@app.get("/settings")
def get_settings() -> dict[str, Any]:
    return settings.get_all().model_dump()


@app.patch("/settings")
def patch_settings(patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return settings.update(patch).model_dump()
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})


def _errors(e: ValidationError) -> dict[str, str]:
    return {str(err["loc"][0]) if err["loc"] else "": err["msg"].removeprefix("Value error, ")
            for err in e.errors()}


@app.post("/settings/test-connection")
def test_connection() -> dict[str, Any]:
    return llm.test_connection(settings.get_all())


@app.post("/papers", status_code=201)
async def add_paper(request: Request) -> dict[str, Any]:
    """Body is the raw PDF (Content-Type: application/pdf); X-Filename carries the name."""
    if int(request.headers.get("content-length") or 0) > library.MAX_PDF_BYTES:
        raise HTTPException(413, detail="This PDF is larger than 100 MB.")
    try:
        paper_id = library.create(await request.body(), unquote(request.headers.get("x-filename", "")))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    if settings.get_all().primer_auto:
        primer.start(paper_id)
    return _paper_or_404(paper_id)


@app.get("/papers")
def list_papers(q: str = "", status: library.Status = "all", sort: library.Sort = "date",
                theme: str = "") -> dict[str, Any]:
    papers = library.list_papers(framework.load_all(), q, status, sort, theme)
    con = db.connect()
    total, done = con.execute("SELECT count(*), coalesce(sum(reflection_done), 0) FROM papers").fetchone()
    con.close()
    return {"papers": papers, "total": total, "reflections_done": done}


def _paper_or_404(paper_id: str, touch: bool = False) -> dict[str, Any]:
    paper = library.get(framework.load_all(), paper_id, touch)
    if not paper:
        raise HTTPException(404, detail="This paper is not in the library.")
    return paper


@app.get("/papers/{paper_id}")
def get_paper(paper_id: str, open: bool = False) -> dict[str, Any]:
    return _paper_or_404(paper_id, touch=open)


@app.patch("/papers/{paper_id}")
def patch_paper(paper_id: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        parsed = library.PaperPatch(**patch)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    target = settings.get_all().reflections_target
    if parsed.reflection_no is not None and not 1 <= parsed.reflection_no <= target:
        raise HTTPException(422, detail={"errors": {"reflection_no": f"Pick a number from 1 to {target}."}})
    if not library.update(paper_id, parsed):
        raise HTTPException(404, detail="This paper is not in the library.")
    return _paper_or_404(paper_id)


# ---------- themes ----------

class ThemeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=200)


class PaperThemesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(max_length=50)


@app.get("/themes")
def list_themes() -> dict[str, Any]:
    return {"themes": themes.list_all()}


@app.post("/themes")
def create_theme(body: ThemeIn) -> dict[str, Any]:
    try:
        return themes.create(body.name)
    except ValueError as e:
        raise HTTPException(422, detail={"errors": {"name": str(e)}})


@app.delete("/themes/{theme_id}", status_code=204)
def delete_theme(theme_id: str) -> None:
    if not themes.delete(theme_id):
        raise HTTPException(404, detail="This theme does not exist.")


@app.put("/papers/{paper_id}/themes")
def put_paper_themes(paper_id: str, body: PaperThemesIn) -> dict[str, Any]:
    if not themes.set_for_paper(paper_id, body.ids):
        raise HTTPException(404, detail="This paper or one of the themes does not exist.")
    return _paper_or_404(paper_id)


@app.get("/papers/{paper_id}/outline")
def get_outline(paper_id: str) -> dict[str, Any]:
    paper = _paper_or_404(paper_id)
    tree = library.outline(paper_id, paper["title"])
    if tree is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return tree


@app.get("/papers/{paper_id}/notes")
def get_notes(paper_id: str) -> dict[str, Any]:
    result = notes.load(_fw_of(paper_id), paper_id)
    if result is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return result


@app.put("/papers/{paper_id}/notes/{step_id}")
async def put_notes(paper_id: str, step_id: str, request: Request) -> dict[str, Any]:
    try:
        result = notes.save(_fw_of(paper_id), paper_id, step_id, await request.body())
    except notes.NoteError as e:
        raise HTTPException(422, detail={"errors": e.errors})
    if result is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return result


class ExplainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    words: str = Field(min_length=1, max_length=600)
    page: int = Field(1, ge=1)  # the page the words were marked on, 1-based
    rect: list[float] | None = Field(None, min_length=4, max_length=4)  # the marked area in PDF points, sent as a picture

    _box = field_validator("rect")(marks.MarkIn._box.__func__)


@app.post("/papers/{paper_id}/explain")
def explain(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Explains marked words with the whole paper as context. Runs on the local model only."""
    try:
        req = ExplainIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    paper = _paper_or_404(paper_id)
    pages = library.page_texts(paper_id)
    if pages is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    box = marks.boxed(paper_id, req.page, req.rect) if req.rect else None
    return llm.explain(settings.get_all(), req.words.strip(), paper["title"], pages, req.page - 1, box[1] if box else None)


@app.get("/papers/{paper_id}/primer")
def get_primer(paper_id: str) -> dict[str, Any]:
    out = primer.load(paper_id)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return out


@app.post("/papers/{paper_id}/primer")
def make_primer(paper_id: str) -> StreamingResponse:
    """Starts the AI summary (unless it is running) and streams its progress as Server-Sent Events.
    The work goes on in the background if you leave the page."""
    _paper_or_404(paper_id)
    primer.start(paper_id)

    def events() -> Any:
        while True:
            p = primer.progress(paper_id)
            yield f"data: {json.dumps(p)}\n\n"
            if p["state"] != "making":
                return
            time.sleep(0.5)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/papers/{paper_id}/check/{step_id}")
def check_notes(paper_id: str, step_id: str) -> dict[str, Any]:
    """Checks the saved notes for one step against the paper. Runs on the local model only."""
    try:
        out = checker.check(settings.get_all(), paper_id, step_id)
    except KeyError:
        raise HTTPException(422, detail={"errors": {"step_id": "The checker does not cover this step."}})
    except checker.CheckError as e:
        return {"ok": False, "error": str(e)}
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"ok": True, **out}


@app.get("/papers/{paper_id}/export/markdown")
def export_markdown(paper_id: str) -> dict[str, Any]:
    out = export.markdown(paper_id)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"ok": True, "markdown": out}


@app.get("/papers/{paper_id}/export/reflection")
def export_reflection(paper_id: str) -> dict[str, Any]:
    """The model only sorts your notes into sections; every line is your own text."""
    try:
        out = export.reflection(settings.get_all(), paper_id)
    except primer.PrimerError as e:
        return {"ok": False, "error": str(e)}
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"ok": True, "markdown": out}


@app.get("/papers/{paper_id}/guide")
def get_guide(paper_id: str) -> dict[str, Any]:
    out = guide.stops(paper_id)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"stops": out}


@app.get("/papers/{paper_id}/blocks/{page}")
def get_blocks(paper_id: str, page: int) -> dict[str, Any]:
    out = marks.blocks(paper_id, page)
    if out is None:
        raise HTTPException(404, detail="This page is not in the library.")
    return out


@app.get("/papers/{paper_id}/marks")
def get_marks(paper_id: str) -> dict[str, Any]:
    out = marks.all_for(paper_id)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"marks": out}


@app.post("/papers/{paper_id}/marks")
def add_mark(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        m = marks.MarkIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    out = marks.create(paper_id, m)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return out


@app.put("/papers/{paper_id}/marks/{mark_id}")
def edit_mark(paper_id: str, mark_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        t = marks.MarkText(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    if not marks.update(paper_id, mark_id, t.text, t.rect):
        raise HTTPException(404, detail="This note is not there.")
    return {"ok": True}


@app.post("/papers/{paper_id}/marks/{mark_id}/ask")
def ask_mark(paper_id: str, mark_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """An @ai question in a margin note: the local model gets the boxed text and a picture of the box."""
    try:
        req = marks.BoxAsk(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    paper = _paper_or_404(paper_id)
    m = marks.get(paper_id, mark_id)
    pages = library.page_texts(paper_id)
    box = m and marks.boxed(paper_id, m["page"], m["rect"])
    if not box or pages is None:
        raise HTTPException(404, detail="This note is not there.")
    return llm.ask_box(settings.get_all(), req.question.strip(), box[0], box[1], paper["title"], pages, m["page"] - 1)


@app.delete("/papers/{paper_id}/marks/{mark_id}")
def remove_mark(paper_id: str, mark_id: int) -> dict[str, Any]:
    if not marks.delete(paper_id, mark_id):
        raise HTTPException(404, detail="This note is not there.")
    return {"ok": True}


@app.get("/papers/{paper_id}/checks")
def get_checks(paper_id: str) -> dict[str, Any]:
    out = checker.history(paper_id)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"steps": out}


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    page: int = Field(1, ge=1)


@app.post("/papers/{paper_id}/ask")
def ask(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Answers a question from the plain note (@ai). Runs on the local model only."""
    try:
        req = AskIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    paper = _paper_or_404(paper_id)
    pages = library.page_texts(paper_id)
    if pages is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return llm.ask(settings.get_all(), req.question.strip(), paper["title"], pages, req.page - 1)


class NoteTextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=200_000)


@app.get("/papers/{paper_id}/note")
def get_note(paper_id: str) -> dict[str, Any]:
    con = db.connect()
    row = con.execute("SELECT note FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.close()
    if row is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"text": row["note"]}


@app.put("/papers/{paper_id}/note")
def put_note(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        req = NoteTextIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    con = db.connect()
    try:
        with con:
            if con.execute("UPDATE papers SET note = ? WHERE id = ?", (req.text, paper_id)).rowcount == 0:
                raise HTTPException(404, detail="This paper is not in the library.")
            library.reindex(con, paper_id)
    finally:
        con.close()
    return {"ok": True}


@app.delete("/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: str) -> None:
    if not library.delete(paper_id):
        raise HTTPException(404, detail="This paper is not in the library.")


@app.get("/papers/{paper_id}/cover")
def get_cover(paper_id: str) -> FileResponse:
    path = library.cover(paper_id)
    if path is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.get("/papers/{paper_id}/pdf")
def get_pdf(paper_id: str) -> FileResponse:
    path = db.PAPERS_DIR / f"{paper_id}.pdf"
    if not paper_id.isalnum() or not path.exists():
        raise HTTPException(404, detail="This paper is not in the library.")
    return FileResponse(path, media_type="application/pdf")


# ---------- graph ----------

class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=1, max_length=300)


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    page: int = Field(ge=0)
    snippet: str = Field(max_length=2000)
    score: float


class ConceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    links: list[LinkIn] = Field(min_length=1, max_length=50)


def _graph_call(fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except graph.GraphError as e:
        raise HTTPException(503, detail=str(e))


@app.get("/graph")
def get_graph() -> dict[str, Any]:
    return graph.read(settings.get_all())


@app.post("/graph/index")
def index_graph() -> dict[str, Any]:
    """Embeds papers that have not been read by the embedding model yet."""
    return _graph_call(graph.index_missing, settings.get_all())


@app.post("/graph/search")
def search_graph(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        req = SearchIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    return _graph_call(graph.search, settings.get_all(), req.q.strip())


@app.post("/graph/concepts", status_code=201)
def add_concept(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        req = ConceptIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    try:
        cid = graph.add_concept(req.label.strip(), [l.model_dump() for l in req.links])
    except sqlite3.IntegrityError:
        raise HTTPException(422, detail={"errors": {"links": "One of these papers is no longer in the library."}})
    return {"id": cid}


@app.post("/graph/suggest")
def suggest_ideas() -> dict[str, Any]:
    """Asks the local model for key ideas in papers it has not looked at yet."""
    return _graph_call(graph.suggest, settings.get_all())


@app.post("/graph/concepts/{concept_id}/keep")
def keep_concept(concept_id: str) -> dict[str, Any]:
    if not graph.keep_concept(concept_id):
        raise HTTPException(404, detail="This idea is not in the graph.")
    return {"id": concept_id}


@app.delete("/graph/concepts/{concept_id}", status_code=204)
def delete_concept(concept_id: str) -> None:
    if not graph.delete_concept(concept_id):
        raise HTTPException(404, detail="This concept is not in the graph.")


@app.get("/model/status")
def model_status() -> dict[str, Any]:
    return llm.model_status(settings.get_all())


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def run() -> None:
    print(f"Paper Reading Workbench: http://127.0.0.1:{PORT}")
    uvicorn.run("workbench.main:app", host="127.0.0.1", port=PORT)
