"""FastAPI app: API routes plus the one-page frontend."""
import json
import re
import os
import time
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import canvas, char, checker, chibi, db, export, guide, harness, jobs, marks, framework, graph, library, llm, notes, primer, sections, settings, shelf, space, themes, train, verse, websearch

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PORT = int(os.environ.get("PORT", "8765"))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init()
    char.init_db()
    library.pick_missing_templates()
    primer.reset_stale()
    jobs.start()
    yield
    llm.stop_dory()  # the dory server this app started does not outlive it


app = FastAPI(title="Paper Reading Workbench", lifespan=lifespan)


@app.middleware("http")
async def no_stale_assets(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    if request.url.path in ("/", "/char", "/space") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
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
    return settings.stored().model_dump()


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


@app.post("/settings/check-context")
def check_context() -> dict[str, Any]:
    """Reads the context window the local server reports. Does not send the paper."""
    return llm.context_window(settings.get_all())


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
    near = marks.around(paper_id, req.page, req.rect) if req.rect else ("", "")
    return llm.explain(settings.get_all(), req.words.strip(), paper["title"], pages, req.page - 1, box[1] if box else None, near)


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


@app.post("/papers/{paper_id}/guide/stages")
def guide_stages(paper_id: str) -> dict[str, Any]:
    """The tour Dot walks: abstract, conclusion, figures, then the sections that matter. Runs on the local model only;
    without it, the paper's own headings are used."""
    out = guide.stages(paper_id, settings.get_all())
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return out


@app.get("/papers/{paper_id}/blocks/{page}")
def get_blocks(paper_id: str, page: int) -> dict[str, Any]:
    out = marks.blocks(paper_id, page)
    if out is None:
        raise HTTPException(404, detail="This page is not in the library.")
    return out


@app.get("/papers/{paper_id}/section")
def get_section(paper_id: str, heading: str = Query(..., max_length=300), page: int = Query(1, ge=1)) -> dict[str, Any]:
    out = sections.find(paper_id, heading, page)
    if out is None:
        raise HTTPException(404, detail="I could not find that section in the paper.")
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


@app.get("/papers/{paper_id}/highlights")
def get_highlights(paper_id: str) -> dict[str, Any]:
    out = marks.highlights(paper_id)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return {"highlights": out}


@app.post("/papers/{paper_id}/highlights")
def add_highlight(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        h = marks.HighlightIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    out = marks.add_highlight(paper_id, h)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return out


@app.post("/papers/{paper_id}/highlights/suggest")
def suggest_highlights(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Dot picks the important lines inside a box and highlights them in blue. Runs on the local model only."""
    try:
        focus = body.get("focus") or ""
        if not isinstance(focus, str) or len(focus) > 300:
            raise HTTPException(422, detail={"errors": [{"field": "focus", "message": "Say what to highlight in at most 300 characters."}]})
        req = marks.MarkIn(**{**{k: v for k, v in body.items() if k != "focus"}, "text": ""})
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    paper = _paper_or_404(paper_id)
    try:
        out = marks.suggest(settings.get_all(), paper_id, req.page, req.rect, paper["title"], focus.strip())
    except primer.PrimerError as e:
        return {"ok": False, "error": str(e)}
    if out is None:
        raise HTTPException(404, detail="This page is not there.")
    return {"ok": True, "highlights": out}


@app.put("/papers/{paper_id}/highlights/{hid}")
def keep_highlight(paper_id: str, hid: int) -> dict[str, Any]:
    out = marks.keep_highlight(paper_id, hid)
    if out is None:
        raise HTTPException(404, detail="This highlight is not there.")
    return out


@app.delete("/papers/{paper_id}/highlights/{hid}")
def remove_highlight(paper_id: str, hid: int) -> dict[str, Any]:
    if not marks.remove_highlight(paper_id, hid):
        raise HTTPException(404, detail="This highlight is not there.")
    return {"ok": True}


@app.get("/papers/{paper_id}/canvas")
def get_canvas(paper_id: str) -> dict[str, Any]:
    out = canvas.read(paper_id)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return out


@app.post("/papers/{paper_id}/canvas/cards")
def add_card(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        c = canvas.CardIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    out = canvas.add_card(paper_id, c)
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return out


@app.put("/papers/{paper_id}/canvas/cards/{cid}")
def edit_card(paper_id: str, cid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        e = canvas.CardEdit(**body)
    except ValidationError as err:
        raise HTTPException(422, detail={"errors": _errors(err)})
    out = canvas.edit_card(paper_id, cid, e)
    if out is None:
        raise HTTPException(404, detail="This card is not there.")
    return out


@app.delete("/papers/{paper_id}/canvas/cards/{cid}")
def remove_card(paper_id: str, cid: int) -> dict[str, Any]:
    if not canvas.delete_card(paper_id, cid):
        raise HTTPException(404, detail="This card is not there.")
    return {"ok": True}


class CanvasAskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    page: int = Field(ge=1)
    from_card: int | None = None
    at: tuple[float, float]
    quote: str = Field("", max_length=3000)  # the part of the page the student selected, if any


@app.post("/papers/{paper_id}/canvas/ask")
def canvas_ask(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        req = CanvasAskIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    out = canvas.ask(settings.get_all(), paper_id, req.question.strip(), req.page, req.from_card, req.at, req.quote.strip())
    if out is None:
        raise HTTPException(404, detail="This paper is not in the library.")
    return out


class CanvasSayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Write something first.")
        return v


@app.post("/papers/{paper_id}/canvas/cards/{cid}/say")
def canvas_say(paper_id: str, cid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """A line in a note. If it is meant for Dot, Dot's answer is added to the same note."""
    try:
        req = CanvasSayIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    out = canvas.say(settings.get_all(), paper_id, cid, req.text)
    if out is None:
        raise HTTPException(404, detail="This card is not there.")
    return out


@app.post("/papers/{paper_id}/canvas/cards/{cid}/pickup")
def canvas_pickup(paper_id: str, cid: int) -> dict[str, Any]:
    """Dot picks up an @ai task left on this card."""
    out = canvas.pickup(settings.get_all(), paper_id, cid)
    if out is None:
        raise HTTPException(404, detail="This card is not there.")
    return out


@app.post("/papers/{paper_id}/canvas/links")
def add_link(paper_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        l = canvas.LinkIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    if l.from_card == l.to_card:
        raise HTTPException(422, detail={"errors": {"to_card": "A card cannot link to itself."}})
    out = canvas.add_link(paper_id, l)
    if out is None:
        raise HTTPException(404, detail="This card is not there.")
    return out


@app.delete("/papers/{paper_id}/canvas/links/{lid}")
def remove_link(paper_id: str, lid: int) -> dict[str, Any]:
    if not canvas.delete_link(paper_id, lid):
        raise HTTPException(404, detail="This link is not there.")
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


# ---------- the Library around Dot ----------

class AskTurn(BaseModel):
    q: str = Field(default="", max_length=500)
    a: str = Field(default="", max_length=1500)


class LibraryAskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)
    history: list[AskTurn] = Field(default_factory=list, max_length=4)


@app.get("/library/map")
def library_map(names: bool = True) -> dict[str, Any]:
    """names=false answers at once with fallback row names; the page asks again for Dot's names."""
    return shelf.library_map(settings.get_all(), name_groups=names)


@app.post("/library/ask")
def library_ask(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        req = LibraryAskIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    return shelf.ask(settings.get_all(), req.question.strip(), [t.model_dump() for t in req.history])


class WebSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=1, max_length=200)

    @field_validator("q")
    @classmethod
    def _words(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Tell me what to look up.")
        return v


@app.post("/library/web")
def library_web(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Search the web through Unsloth. The body is only the query."""
    try:
        req = WebSearchIn(**body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": _errors(e)})
    try:
        return websearch.search(settings.get_all(), req.q)
    except RuntimeError as e:
        raise HTTPException(502, detail=str(e))


@app.get("/model/status")
def model_status() -> dict[str, Any]:
    return llm.model_status(settings.get_all())


def _checked(model: Any, body: dict[str, Any]) -> Any:
    try:
        return model.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, detail={"errors": jobs.errors(e)})


def _reject(e: jobs.Reject) -> HTTPException:
    return HTTPException(422, detail={"errors": [{"field": e.field, "message": e.message}]})


@app.get("/jobs")
def get_jobs() -> dict[str, Any]:
    return jobs.list_jobs()


@app.post("/jobs", status_code=201)
def post_job(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return jobs.create_job(_checked(jobs.JobIn, body))
    except jobs.Reject as e:
        raise _reject(e)


@app.post("/jobs/starters")
def post_starters() -> dict[str, Any]:
    return jobs.starters()


@app.put("/jobs/{job_id}")
def put_job(job_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return jobs.update_job(job_id, _checked(jobs.JobIn, body))
    except jobs.Reject as e:
        raise _reject(e)
    except KeyError:
        raise HTTPException(404, detail="That creature is gone.")


@app.delete("/jobs/{job_id}")
def remove_job(job_id: int) -> dict[str, bool]:
    if not jobs.delete_job(job_id):
        raise HTTPException(404, detail="That creature is gone.")
    return {"ok": True}


@app.post("/jobs/{job_id}/run")
def run_job(job_id: int, response: Response, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        run, created = jobs.enqueue(job_id, _checked(jobs.RunIn, body))
    except jobs.Reject as e:
        raise _reject(e)
    except jobs.QueueFull:
        raise HTTPException(429, detail="Too many jobs waiting.")
    response.status_code = 201 if created else 200
    return run


@app.get("/templates")
def get_templates() -> dict[str, Any]:
    return jobs.list_templates()


@app.post("/templates", status_code=201)
def post_template(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return jobs.create_template(_checked(jobs.TemplateIn, body))


@app.put("/templates/{template_id}")
def put_template(template_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return jobs.update_template(template_id, _checked(jobs.TemplateIn, body))
    except KeyError:
        raise HTTPException(404, detail="That shape is gone.")


@app.delete("/templates/{template_id}")
def remove_template(template_id: int) -> dict[str, bool]:
    if not jobs.delete_template(template_id):
        raise HTTPException(404, detail="That shape is gone.")
    return {"ok": True}


@app.get("/runs")
def get_runs(limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    return jobs.list_runs(limit)


@app.get("/runs/{run_id}")
def get_run(run_id: int) -> dict[str, Any]:
    run = jobs.get_run(run_id)
    if not run:
        raise HTTPException(404, detail="That run is gone.")
    return run


@app.post("/runs/{run_id}/stop")
def stop_run(run_id: int) -> dict[str, Any]:
    run = jobs.stop(run_id)
    if not run:
        raise HTTPException(404, detail="That run is gone.")
    return run


@app.post("/dot/talk")
def dot_talk(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return jobs.talk(body.get("messages") or [])
    except RuntimeError as e:
        raise HTTPException(502, detail=str(e))


@app.get("/space")
def get_space() -> dict[str, Any]:
    return space.state()


@app.get("/space/notes")
def get_space_notes() -> dict[str, Any]:
    return {"notes": space.all_notes()}


@app.post("/space/say")
def space_say(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, detail="Say something to Dot.")
    return space.say(text)


@app.delete("/space/vars/{var_id}")
def space_remove_var(var_id: int) -> dict[str, Any]:
    if not space.remove_var(var_id):
        raise HTTPException(404, detail="That variable is gone.")
    return space.state()


@app.delete("/space")
def space_clear() -> dict[str, Any]:
    space.clear()
    return space.state()


@app.get("/char")
def char_entry(request: Request) -> Any:
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/#char")
    return char.state()


@app.get("/char/notes")
def get_char_notes() -> dict[str, Any]:
    return {"notes": char.all_notes()}


@app.get("/char/questions")
def get_char_questions() -> dict[str, Any]:
    return {"questions": char.get_questions()}


@app.post("/char/say")
def char_say(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, detail="Say something to Jarvis.")
    learn_mode = bool(body.get("learn_mode") or False)
    return char.say(text, learn_mode=learn_mode, answering=bool(body.get("answering")))


@app.post("/space/preview")
def space_preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """How a rule sentence would be read, without saving it."""
    return {"rules": space.preview(str(body.get("text") or "")[:600])}


@app.post("/char/speak")
def char_speak(body: dict[str, Any] = Body(...)) -> Response:
    try:
        return Response(char.speak(str(body.get("text") or "")), media_type="audio/mpeg")
    except Exception as e:  # e.g. "The loaded model cannot answer in speech."
        raise HTTPException(503, detail=f"No speaking model: {getattr(e, 'read', lambda: str(e).encode())()[:200].decode(errors='ignore')}")


@app.get("/char/mind")
def char_mind() -> dict[str, Any]:
    return char.mind()


@app.get("/char/mesh")
def char_mesh() -> dict[str, Any]:
    return char.mesh()


@app.post("/char/creatures/asker")
def char_asker() -> dict[str, Any]:
    return {"asked": char.asker(), "open": char._open_questions(char._start())}


@app.post("/char/creatures/pruner")
def char_pruner() -> dict[str, Any]:
    return char.pruner()


@app.post("/char/creatures/sorter")
def char_sorter(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return char.sorter(int(body.get("limit") or 1))


@app.post("/char/reflect")
def char_reflect(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return char.reflect(on_char=bool(body.get("char")))


@app.post("/char/polish")
def char_polish(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Prune the old notes on one engine (default: the saved model); the next fit refits the truth concept from what is left."""
    model = (body.get("model") or "").strip()
    if model == llm.STEER:
        raise HTTPException(400, "polish on a server engine (dory or an Unsloth model), not the steer engine")
    if model:
        llm.ensure(settings.get_all(), model)
        settings.OVERRIDE["model_name"] = model
    try:
        out = char.polish()
    finally:
        settings.OVERRIDE.pop("model_name", None)
    return out


@app.get("/char/systems")
def char_systems() -> dict[str, Any]:
    return char.systems()


@app.post("/char/systems")
def char_set_system(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        char.set_system(int(body.get("id", -1)), bool(body.get("on")))
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return char.systems()


_model_seen: dict[str, Any] = {}  # the last model status and when, so polling the engines does not list the models each time


def _model() -> tuple[bool, str]:
    if time.time() - _model_seen.get("t", 0) > 10:
        _model_seen.update(llm.model_status(settings.get_all()), t=time.time())
    return _model_seen["status"] == "ready", _model_seen["label"]


@app.get("/char/engines")
def char_engines() -> dict[str, Any]:
    return char.engines(*_model())


@app.post("/char/dial")
def char_dial(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        return {"dial": char.set_dial(float(body.get("curiosity"))), "disposition": char.disposition()}
    except (TypeError, ValueError):
        raise HTTPException(422, detail="curiosity must be a number from 0 to 3")


@app.get("/char/note/{note_id}")
def char_note(note_id: int) -> dict[str, Any]:
    try:
        return char.note(note_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/char/journal")
def char_journal() -> dict[str, Any]:
    """Its study journal, newest page first."""
    return {"pages": char.journal()}


@app.get("/char/train")
def char_train() -> dict[str, Any]:
    """The live persona's training runs, newest first, with their logs."""
    return train.status()


@app.post("/char/train")
def char_train_do(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """start (with minutes, lo, hi, max_steps), pause, resume or stop a training run."""
    action = str(body.get("action") or "start")
    try:
        return train.start(body) if action == "start" else train.control(action)
    except (RuntimeError, KeyError, ValueError) as e:
        raise HTTPException(409, detail=str(e) if not isinstance(e, KeyError) else f"no action {action}")


@app.get("/char/train/{run_id}/snapshots")
def char_train_snaps(run_id: int) -> dict[str, Any]:
    return {"snapshots": train.snapshots(run_id)}


@app.get("/char/train/{run_id}/dataset.jsonl")
def char_train_dataset(run_id: int) -> Response:
    """The run's fine-tuning set: JSONL, one {"system", "messages"} example per line."""
    return Response(train.dataset(run_id), media_type="application/jsonl", headers={"Content-Disposition": f'attachment; filename="{char.get_profile()["name"].replace(" ", "-").lower()}-run-{run_id}.jsonl"'})


@app.post("/char/you")
def char_you(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Tell it who you are in your own words (`about`), or make it forget one thing it learned about you (`forget`: name, theirs, mine, role, work)."""
    return {"you": char.set_you(body.get("about") if "about" in body else None, body.get("forget"))}


@app.get("/char/letter")
def char_letter() -> dict[str, Any]:
    return char.letter()


@app.post("/char/letter")
def char_letter_answer(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """[{id, text, skip}]: your answers to its letter; blank ones wait for the next letter."""
    return char.answer_letter(list(body.get("answers") or []))


@app.get("/char/tools")
def char_tools() -> dict[str, Any]:
    """Its tools as a graph, wired into its mesh: what each step made, which feeds which, and the model they run on."""
    return char.toolnet(char.mesh()["nodes"])


@app.get("/char/life")
def char_life() -> dict[str, Any]:
    """Its needs, mood shifts, wants and trust."""
    return char.life()


@app.post("/char/want/{want_id}")
def char_want(want_id: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Give it what it asked for (the gift becomes a note it reads), or let the want go (no gift)."""
    w = char.give_want(want_id, str(body.get("gift") or ""))
    if w is None:
        raise HTTPException(404, detail="no such want")
    return w


@app.get("/char/report")
def char_report() -> dict[str, Any]:
    return {**char.report(*_model()), "harness_loop": harness.totals(), "cycles": harness.cycles(30), "mode": char.mode(), "tracker": char.tracker(),
            "race": verse.live_race(), "train": train.status(), "letter": char.letter(), "now": dict(char.NOW),
            "model_name": (lambda c: c.chat_model or c.model_name or "")(settings.get_all()), "models": [m for m in _model_seen.get("models", []) if "embed" not in m.lower()]}  # an embedding model cannot think: picking one breaks every reply


@app.post("/char/cycle")
def char_cycle(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        budget = max(1, min(12, int(body.get("budget") or harness.BUDGET)))
    except (TypeError, ValueError):
        raise HTTPException(422, detail="budget must be a whole number")
    try:
        return harness.cycle(budget)
    except RuntimeError as e:
        raise HTTPException(409, detail=str(e))


@app.get("/char/cycles")
def char_cycles(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    return {"cycles": harness.cycles(limit)}


@app.get("/model/swap")
def model_swap() -> dict[str, Any]:
    return dict(llm.SWAP)


@app.post("/char/rest")
def char_rest(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if body.get("char") and train.active() and not body.get("only"):  # a training run is driving it: idle learning stands aside, one step at a time
        return {"done": True, "kind": "", "topic": "", "note": "", "why": "a training run is driving it", "training": True, "questions": char._open_questions(char._start())[::-1][:3], "graph": char.graph()}
    if body.get("char") and char.mode() == "planner" and not body.get("only"):  # planner mode: idle time runs one harness cycle instead of the rule loop; a step you ask for by name still runs
        try:
            c = harness.cycle()
        except RuntimeError as e:
            c = {"busy": str(e), "executed": []}
        did = [x for x in c["executed"] if x["outcome"] == "ok"]
        return {"done": not did, "kind": "cycle", "topic": f"cycle {c.get('cycle', '')}".strip(), "note": " · ".join(x["cmd"] for x in did),
                "cycle": c, "questions": char._open_questions(char._start())[::-1][:3], "graph": char.graph()}
    only = body.get("only")
    if only is not None and only not in char.SYS_OF:
        raise HTTPException(422, detail=f"no step called {only}")
    return char.rest(on_char=bool(body.get("char")), n=None if body.get("n") is None else int(body["n"]), force=bool(body.get("force")), only=only)


@app.get("/verse")
def verse_page() -> RedirectResponse:
    return RedirectResponse("/#verse")


@app.get("/verse/personas")
def verse_list() -> dict[str, Any]:
    return verse.personas()


@app.post("/verse/enter")
def verse_enter(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        p = verse.enter(str(body.get("name") or ""))
    except KeyError:
        raise HTTPException(404, detail="There is no persona by that name.")
    char._engine("persona", "ok", f"entered {p['name']}")
    return verse.personas()


@app.post("/verse/new")
def verse_new(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    who = str(body.get("who") or "").strip()
    if not who:
        raise HTTPException(422, detail="Name who it should become.")
    if who.startswith("/") or not any(c.isalpha() for c in who):  # a slash command typed in the wrong box once made a persona called "/Step"
        raise HTTPException(422, detail="That looks like a command, not someone to become.")
    _, said = char.become_persona(who)  # puts the live one away first, then looks the new one up
    return {**verse.personas(), "said": said}  # says so when the model was down and it got a generic voice


@app.post("/verse/reset")
def verse_reset(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Delete every persona and all they learned, then (when `then` names someone) become them fresh."""
    verse.reset_all()
    said = char.become_persona(str(body["then"]))[1] if body.get("then") else "reset"
    for p in verse.personas()["personas"]:  # becoming someone puts the blank placeholder away: it is not a persona of yours
        if not p["live"] and p["name"] == "Dot":
            verse.delete("Dot")
    return {**verse.personas(), "said": said}


@app.delete("/verse/personas/{name:path}")  # :path so a name with a "/" in it can still be deleted
def verse_delete(name: str) -> dict[str, Any]:
    try:
        verse.delete(name)
    except KeyError:
        raise HTTPException(404, detail="There is no persona by that name.")
    except ValueError as e:
        raise HTTPException(409, detail=str(e))
    return verse.personas()


@app.get("/char/chibi/refs")
def char_chibi_refs() -> dict[str, Any]:
    """Chibi pictures of the live persona from an image search, to pour Dot into."""
    p = char.get_profile()
    return {"refs": chibi.find_refs(p["name"], p["persona"])}


@app.post("/char/chibi/pick")
def char_chibi_pick(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Pour Dot into the picture at `url` (its `thumb` if the site refuses); an empty url goes back to the drawn look."""
    p = char.get_profile()
    try:
        return chibi.pick(p["name"], str(body.get("url") or ""), str(body.get("thumb") or ""), p["look"])
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.get("/char/chibi/image/{name}")
def char_chibi_image(name: str) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{16}\.(png|jpg|webp|gif)", name) or not (chibi.image_dir() / name).is_file():
        raise HTTPException(404)
    return FileResponse(chibi.image_dir() / name)


@app.get("/char/chibi")
def char_chibi(name: str = "") -> dict[str, Any]:
    """The look Dot's chibi form takes for a persona (the live one by default), from a reference looked up on the web once and stored."""
    p = char.get_profile()
    if name and name != p["name"]:
        try:
            p = verse.profile(name)
        except KeyError:
            raise HTTPException(404, detail="There is no persona by that name.")
    return chibi.reference(p["name"], p["look"], p["persona"])


@app.get("/char/monitor")
def char_monitor() -> dict[str, Any]:
    return char.monitor()


@app.post("/char/tint")
def char_tint(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    tint = str(body.get("tint") or "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", tint):
        raise HTTPException(422, detail="Pick a colour.")
    p = char.get_profile()
    char.update_profile(p["name"], p["persona"], p["look"], tint)
    return char.state()


@app.get("/char/wiring")
def char_wiring() -> dict[str, Any]:
    return char.wiring()


@app.post("/char/wiring")
def char_wire(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        if body.get("correction"):
            char.set_correction(str(body["correction"]), bool(body.get("accept")))
            return char.wiring()
        if body.get("mode"):
            char.set_mode(str(body["mode"]))
            return char.wiring()
        return char.wire(str(body.get("text") or ""))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@app.post("/char/correction")
def char_correction(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        char.answer_correction(str(body.get("text") or ""))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return char.wiring()


@app.post("/char/tracker")
def char_tracker(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        return char.set_tracker(body.get("sleep_at"), body.get("max"))
    except (TypeError, ValueError):
        raise HTTPException(422, detail="sleep_at and max must be numbers")


@app.delete("/char/correction")
def char_skip_correction() -> dict[str, Any]:
    char.skip_correction()
    return char.wiring()


@app.delete("/char/instructions/{note_id}")
def char_remove_instruction(note_id: int) -> dict[str, Any]:
    if not char.remove_instruction(note_id):
        raise HTTPException(404, detail="No such instruction.")
    return char.wiring()


@app.delete("/char/vars/{var_id}")
def char_remove_var(var_id: int) -> dict[str, Any]:
    if not char.remove_var(var_id):
        raise HTTPException(404, detail="That variable is gone.")
    return char.state()


@app.delete("/char")
def char_clear() -> dict[str, Any]:
    char.clear()
    return char.state()


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def run() -> None:
    print(f"Paper Reading Workbench: http://127.0.0.1:{PORT}")
    uvicorn.run("workbench.main:app", host="127.0.0.1", port=PORT)
