"""FastAPI app: API routes plus the one-page frontend."""
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import db, framework, graph, library, llm, notes, settings

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PORT = int(os.environ.get("PORT", "8765"))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init()
    yield


app = FastAPI(title="Paper Reading Workbench", lifespan=lifespan)


@app.middleware("http")
async def no_stale_assets(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"  # revalidate, so UI edits show at once
    return response


@app.get("/framework")
def get_framework() -> dict[str, Any]:
    return framework.load().model_dump()


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
    return _paper_or_404(paper_id)


@app.get("/papers")
def list_papers(q: str = "", status: library.Status = "all", sort: library.Sort = "date") -> dict[str, Any]:
    papers = library.list_papers(framework.load(), q, status, sort)
    con = db.connect()
    total, done = con.execute("SELECT count(*), coalesce(sum(reflection_done), 0) FROM papers").fetchone()
    con.close()
    return {"papers": papers, "total": total, "reflections_done": done}


def _paper_or_404(paper_id: str, touch: bool = False) -> dict[str, Any]:
    paper = library.get(framework.load(), paper_id, touch)
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


@app.get("/papers/{paper_id}/outline")
def get_outline(paper_id: str) -> dict[str, Any]:
    paper = _paper_or_404(paper_id)
    tree = library.outline(paper_id, paper["title"])
    if tree is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return tree


@app.get("/papers/{paper_id}/notes")
def get_notes(paper_id: str) -> dict[str, Any]:
    result = notes.load(framework.load(), paper_id)
    if result is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return result


@app.put("/papers/{paper_id}/notes/{step_id}")
async def put_notes(paper_id: str, step_id: str, request: Request) -> dict[str, Any]:
    try:
        result = notes.save(framework.load(), paper_id, step_id, await request.body())
    except notes.NoteError as e:
        raise HTTPException(422, detail={"errors": e.errors})
    if result is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return result


class ExplainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    words: str = Field(min_length=1, max_length=300)
    page: int = Field(1, ge=1)  # the page the words were marked on, 1-based


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
    return llm.explain(settings.get_all(), req.words.strip(), paper["title"], pages, req.page - 1)


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
