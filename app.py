"""Start the app: uv run app.py. Wires the three parts together: shared, pdf_research (the paper reader) and harness_char (the live character)."""
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import harness_char.routes
import pdf_research.routes
import shared.routes
from harness_char import char
from pdf_research import jobs, library, primer
from shared import db

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8765"))
PARTS = ("shared", "pdf_research", "harness_char")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init()
    char.init_db()
    library.pick_missing_templates()
    primer.reset_stale()
    jobs.start()
    yield


app = FastAPI(title="Paper Reading Workbench", lifespan=lifespan)


@app.middleware("http")
async def no_stale_assets(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    if request.url.path in ("/", "/char", "/space") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(shared.routes.router)
app.include_router(pdf_research.routes.router)
app.include_router(harness_char.routes.router)
for part in PARTS:
    app.mount(f"/static/{part}", StaticFiles(directory=ROOT / part / "static"), name=f"static-{part}")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "shared" / "static" / "index.html")


def run() -> None:
    print(f"Paper Reading Workbench: http://127.0.0.1:{PORT}")
    uvicorn.run("app:app", host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    run()
