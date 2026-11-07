# Reading mode (paper mode and Dot's canvas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the reader a paper-first "reading mode": Dot follows the cursor, offers Suggest highlights / Ask / Note / Add more / Back on any paragraph, lets you highlight exact words yourself, and answers and notes live on a per-paper canvas that grows out of Dot, threaded back to their lines on the page.

**Architecture:** Server side adds three small pieces on the existing FastAPI + SQLite app: paragraph text and saved highlights (`workbench/marks.py`), the canvas store (`workbench/canvas.py`, new), and the source-finding ask plus note replies (`workbench/llm.py`, `workbench/graph.py`). Client side extends Dot in `static/buddy.js` (follow, options, shapes, input pill), reworks the reader shell and paragraph actions in `static/reader.js`, and puts the canvas in a new `static/canvas.js`. Animations follow the live mockup `cursor-v12.html`.

**Tech Stack:** Python 3 / FastAPI / pydantic / SQLite / PyMuPDF / openai SDK (local Unsloth Studio); plain JS, CSS, PDF.js 3.11.174; pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-dot-canvas-design.md`. Mockups: `.superpowers/brainstorm/24622-1794092239/content/cursor-v12.html` (Dot, options, shapes, notes, open/close animations) and `flow-v5.html` (sources lifting off the page). Read both before any front-end task; copy their timings and easing.

## Global Constraints

- No new dependencies (Python or JS) without asking the user first.
- The paper text goes only to the local model (Settings base URL). No cloud calls. The API key is never logged.
- No training code.
- UI text: simple English, sentence case, no em dashes.
- Fonts: Instrument Serif, Geist, Geist Mono, Doto. Colours: graphite plus `#ffe347` (`--marker`); Dot's suggested highlights only: `#8ecbff` (`--dot-ink`).
- `prefers-reduced-motion: reduce` respected everywhere: Dot does not follow (it appears at the click), shapes switch without motion, cards fade, threads appear drawn.
- Every animation can be skipped by clicking: it jumps to its end state.
- Model calls use the existing fallbacks: `primer._complete` (json_schema then json_object) and the image retry in `llm._answer` / `llm.ask_box`.
- Delete test data through the API or `db.connect()`, never the sqlite3 CLI. Never type into the user's real notes when checking in the app; use a test paper and remove what you add.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and are pushed with `git push -q origin HEAD:ui-readability HEAD:main`.
- Run the whole suite with `uv run pytest -q`; it must stay green (63 tests before this plan).

## Review Focus

1. **The model names paragraphs that do not exist, or returns broken JSON.** Unknown ids are dropped, the rest kept; broken JSON is asked once more, then the plain answer is saved with "No exact lines found". Tests in Task 3.
2. **The paper is not indexed, or no embedding model is loaded.** Source finding falls back to the pages next to the current one instead of failing. Test in Task 3.
3. **A page with no text (a scanned page or a full-page figure).** `paragraphs()` returns `[]`; ask still answers with "No exact lines found"; clicking that page offers only Ask, Note and Back. Tests in Tasks 1 and 3.
4. **Deleting a card that has children and drawn links.** Links go, children stay with `parent` set to null, nothing else on the canvas changes. Test in Task 2.
5. **A note line that looks like a question but is not meant for Dot, or the reverse.** The rule in Task 4 decides; the "Ask Dot" hint in the pill (Task 11) shows before Enter. Rule tests in Task 4.

---

### Task 1: Paragraph text and saved highlights

**Files:**
- Modify: `workbench/marks.py` (refactor `blocks()` to share grouping with a new `paragraphs()`; add highlight CRUD)
- Modify: `workbench/db.py` (SCHEMA: `highlights` table)
- Modify: `workbench/main.py` (highlight routes)
- Test: `tests/test_marks.py`

**Interfaces:**
- Produces: `marks.paragraphs(paper_id: str, page: int) -> list[tuple[list[float], str]] | None` — same boxes, same order as `blocks()["blocks"]`, each with its text (`" ".join(page.get_text("text", clip=rect).split())`). None if no such page.
- Produces: table `highlights(id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE, page INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'me', text TEXT NOT NULL DEFAULT '', rects TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))` — `rects` is a JSON list of line rects in PDF points.
- Produces: `marks.HighlightIn(page: int ge 1, kind: Literal["me","dot"] = "me", text: str max 2000, rects: list[list[float]] 1..60 items, each validated like `MarkIn._box`)`; `marks.highlights(paper_id) -> list[dict] | None`, `marks.add_highlight(paper_id, h: HighlightIn) -> dict | None`, `marks.keep_highlight(paper_id, hid) -> dict | None` (sets kind to `me`), `marks.remove_highlight(paper_id, hid: int) -> bool`. Row shape `{"id", "page", "kind", "text", "rects"}`.
- Produces routes: `GET /papers/{id}/highlights` → `{"highlights": [...]}`; `POST /papers/{id}/highlights` → row; `PUT /papers/{id}/highlights/{hid}` (body `{"kind": "me"}`) → row; `DELETE /papers/{id}/highlights/{hid}` → `{"ok": true}`; 404 for unknown paper or id; 422 for bad rects.

- [ ] **Step 1: Write the failing tests**

```python
def test_paragraphs_have_text_in_block_order() -> None:
    pid = _paper()
    paras = marks.paragraphs(pid, 1)
    assert [r for r, _ in paras] == marks.blocks(pid, 1)["blocks"]
    assert "first paragraph" in paras[0][1] and "second paragraph" in paras[1][1]
    assert marks.paragraphs(pid, 2) is None

def test_a_page_with_no_text_has_no_paragraphs() -> None:
    doc = pymupdf.open(); doc.new_page()
    pid = library.create(doc.tobytes(), "blank.pdf")
    assert marks.paragraphs(pid, 1) == []

def test_highlights_round_trip() -> None:
    pid = _paper()
    c = TestClient(main.app)
    h = c.post(f"/papers/{pid}/highlights", json={"page": 1, "text": "first paragraph", "rects": [[90, 92, 160, 102]]}).json()
    assert h["kind"] == "me" and c.get(f"/papers/{pid}/highlights").json()["highlights"] == [h]
    assert c.post(f"/papers/{pid}/highlights", json={"page": 1, "rects": [[400, 90, 70, 110]]}).status_code == 422
    assert c.post(f"/papers/{pid}/highlights", json={"page": 1, "rects": []}).status_code == 422
    d = c.post(f"/papers/{pid}/highlights", json={"page": 1, "kind": "dot", "rects": [[90, 92, 160, 102]]}).json()
    assert c.put(f"/papers/{pid}/highlights/{d['id']}", json={"kind": "me"}).json()["kind"] == "me"
    assert c.delete(f"/papers/{pid}/highlights/{h['id']}").json() == {"ok": True}
    assert c.delete(f"/papers/{pid}/highlights/{h['id']}").status_code == 404
    assert c.get("/papers/nope/highlights").status_code == 404
```

(If `library.create` rejects a PDF with no text, give the page a tiny image or a 1-character string instead; the point is no block of 25+ characters and none 60pt wide.)

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/test_marks.py -q`; expect AttributeError on `paragraphs` and 404/405 on the routes.
- [ ] **Step 3: Implement** — move the body of `blocks()` into a private `_layout(pg) -> list[list[float]]`; `blocks()` and `paragraphs()` both call it. Add the table to `SCHEMA` (it is `CREATE TABLE IF NOT EXISTS`, so existing databases get it on start). Routes follow the `marks` routes' pattern (`_errors`, 404 text "This paper is not in the library.").
- [ ] **Step 4: Run the suite** — `uv run pytest -q`; all pass.
- [ ] **Step 5: Commit** — "Paragraph text for each block, and saved highlights".

---

### Task 1A: Dot suggests highlights

**Files:**
- Modify: `workbench/llm.py` (`HIGHLIGHT_SYSTEM`, `pick_quotes`)
- Modify: `workbench/marks.py` (`suggest`)
- Modify: `workbench/main.py` (`POST /papers/{id}/highlights/suggest`)
- Test: `tests/test_marks.py`

**Interfaces:**
- Consumes: `marks.boxed` (text of the selection), `marks.add_highlight` (Task 1), `primer._complete`.
- Produces: `llm.pick_quotes(s, text: str, title: str) -> list[str]` — JSON schema `{"quotes": [str]}`; `HIGHLIGHT_SYSTEM`: pick only the most important parts a student should remember (a key claim, a definition, a main result), copied word for word from the text, at most 3, each at most 25 words, never a whole paragraph; fewer is better. Raises `primer.PrimerError` with the user-facing message on model failure; broken JSON is asked once more, then `[]`.
- Produces: `marks.suggest(s, paper_id, page, rect, title) -> list[dict] | None` — for each quote, `page.search_for(quote, clip=Rect(rect))`; if not found, retry with the quote's first 8 words; keep found ones, merge the returned quads into line rects, save as `kind="dot"`. Quotes longer than 60% of the selection's text are dropped (no whole-paragraph highlights). None for an unknown paper or page.
- Produces route: `POST /papers/{id}/highlights/suggest` with body `{page, rect}` → `{"ok": True, "highlights": [...]}` or `{"ok": False, "error": message}`.

- [ ] **Step 1: Write the failing tests** (fake model as in `test_box_grows_and_ai_sees_a_picture`)

```python
def test_dot_suggests_only_quotes_that_are_really_there(monkeypatch) -> None:
    # reply: {"quotes": ["enough words to count", "words that are not on the page", "<the whole first paragraph>"]}
    r = c.post(f"/papers/{pid}/highlights/suggest", json={"page": 1, "rect": [60, 80, 560, 320]}).json()
    assert r["ok"] and [h["text"] for h in r["highlights"]] == ["enough words to count"]
    assert r["highlights"][0]["kind"] == "dot" and r["highlights"][0]["rects"]

def test_suggest_with_a_broken_model_reply_adds_nothing(monkeypatch) -> None:
    # replies: "nope", "nope" -> ok True, highlights []
    ...
```

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the suite.**
- [ ] **Step 5: Commit** — "Dot suggests only the important lines to highlight".

---

### Task 2: The canvas store

**Files:**
- Create: `workbench/canvas.py`
- Modify: `workbench/db.py` (SCHEMA: two tables)
- Modify: `workbench/main.py` (routes)
- Test: `tests/test_canvas.py` (new; copy the `tmp_db` fixture and `_paper()` helper from `tests/test_marks.py`)

**Interfaces:**
- Produces tables:
  - `canvas_cards(id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE, kind TEXT NOT NULL, question TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', entries TEXT NOT NULL DEFAULT '[]', x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, page INTEGER, x0 REAL, y0 REAL, x1 REAL, y1 REAL, parent INTEGER REFERENCES canvas_cards(id) ON DELETE SET NULL, hidden INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')))`
  - `canvas_links(id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE, from_card INTEGER NOT NULL REFERENCES canvas_cards(id) ON DELETE CASCADE, to_card INTEGER NOT NULL REFERENCES canvas_cards(id) ON DELETE CASCADE)`
  - `hidden` is the card's x ("put away"): hidden cards come back when the canvas next opens (the client clears it then).
- Produces pydantic models in `canvas.py`: `CardIn(kind: Literal["answer","source","note"], question: str = "" (max 1000), text: str = "" (max 8000), entries: list[Entry] = [] (max 200), x: float, y: float, w: float (120..900), page: int | None (ge 1), rect: list[float] | None (validated like `MarkIn._box`), parent: int | None)`, `Entry(who: Literal["me","dot"], text: str (1..4000))`, `CardEdit` (all of x, y, w, text, entries, hidden optional), `LinkIn(from_card: int, to_card: int)`.
- Produces functions: `canvas.read(paper_id) -> dict | None` returning `{"cards": [card...], "links": [{"id","from_card","to_card"}]}`, card shape `{"id","kind","question","text","entries","x","y","w","page","rect","parent","hidden","created_at"}` (`rect` null when unset, `entries` a list); `add_card(paper_id, c: CardIn) -> dict | None`; `edit_card(paper_id, cid, e: CardEdit) -> dict | None`; `delete_card(paper_id, cid) -> bool`; `add_link(paper_id, l: LinkIn) -> dict | None` (None if either card is not on this paper or from == to); `delete_link(paper_id, lid) -> bool`; `chain(paper_id, cid, most=6) -> list[dict]` (the card, then its parent, grandparent... up to `most`).
- Produces routes: `GET /papers/{id}/canvas`; `POST /papers/{id}/canvas/cards`; `PUT|DELETE /papers/{id}/canvas/cards/{cid}`; `POST /papers/{id}/canvas/links`; `DELETE /papers/{id}/canvas/links/{lid}`. 404 "This paper is not in the library." / "This card is not there."; 422 with `{"errors": ...}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_cards_and_links_round_trip() -> None:
    pid = _paper(); c = TestClient(main.app)
    a = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "answer", "question": "Why?", "text": "Because.", "x": 10, "y": 20, "w": 240}).json()
    s = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "source", "text": "Gist.", "x": 10, "y": 90, "w": 240, "page": 1, "rect": [70, 90, 400, 110], "parent": a["id"]}).json()
    n = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "note", "entries": [{"who": "me", "text": "Mine."}], "x": 300, "y": 20, "w": 240}).json()
    l = c.post(f"/papers/{pid}/canvas/links", json={"from_card": n["id"], "to_card": a["id"]}).json()
    got = c.get(f"/papers/{pid}/canvas").json()
    assert [x["id"] for x in got["cards"]] == [a["id"], s["id"], n["id"]] and got["links"] == [l]
    assert s["rect"] == [70, 90, 400, 110] and s["parent"] == a["id"] and n["entries"][0]["who"] == "me"
    assert c.put(f"/papers/{pid}/canvas/cards/{n['id']}", json={"x": 50, "hidden": True}).json()["x"] == 50

def test_deleting_a_card_keeps_its_children_and_drops_its_links() -> None:
    # a <- s (parent), n -> a (link); delete a
    ...  # build as above
    assert c.delete(f"/papers/{pid}/canvas/cards/{a['id']}").json() == {"ok": True}
    got = c.get(f"/papers/{pid}/canvas").json()
    assert [x["id"] for x in got["cards"]] == [s["id"], n["id"]]
    assert got["cards"][0]["parent"] is None and got["links"] == []

def test_bad_cards_and_links_are_refused() -> None:
    pid = _paper(); c = TestClient(main.app)
    assert c.post(f"/papers/{pid}/canvas/cards", json={"kind": "poem", "x": 0, "y": 0, "w": 240}).status_code == 422
    assert c.post(f"/papers/{pid}/canvas/cards", json={"kind": "note", "x": 0, "y": 0, "w": 50}).status_code == 422
    a = c.post(f"/papers/{pid}/canvas/cards", json={"kind": "note", "x": 0, "y": 0, "w": 240}).json()
    assert c.post(f"/papers/{pid}/canvas/links", json={"from_card": a["id"], "to_card": a["id"]}).status_code == 422
    assert c.post(f"/papers/{pid}/canvas/links", json={"from_card": a["id"], "to_card": 999}).status_code == 404
    assert c.get("/papers/nope/canvas").status_code == 404

def test_chain_walks_up_the_parents() -> None:
    # three answers, each the parent of the next; chain(last) returns last, middle, first
    ...
```

Fill in the `...` with the same calls as the first test; keep the assertions shown.

- [ ] **Step 2: Run them to see them fail** — `uv run pytest tests/test_canvas.py -q`.
- [ ] **Step 3: Implement** `workbench/canvas.py` in the style of `marks.py` (`_exists`, `_row`, connection per call, `with con:` for writes). Self-link → 422 from the route via a validator on `LinkIn` is not possible (it needs both ids); check in the route and raise 422 `{"errors": {"to_card": "A card cannot link to itself."}}`.
- [ ] **Step 4: Run the suite** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — "Canvas store: cards and links for each paper".

---

### Task 3: Ask with sources

**Files:**
- Modify: `workbench/graph.py` (`pages_for`)
- Modify: `workbench/llm.py` (`SOURCES_SYSTEM`, `ask_with_sources`)
- Modify: `workbench/canvas.py` (`ask`, which lays out and saves the cards)
- Modify: `workbench/main.py` (`POST /papers/{id}/canvas/ask`)
- Test: `tests/test_canvas.py`

**Interfaces:**
- Consumes: `marks.paragraphs` (Task 1), `canvas.add_card`, `canvas.chain` (Task 2), `primer._complete`, `primer.PrimerError`, `llm.paper_text`, `llm.ask`.
- Produces: `graph.pages_for(s: Settings, paper_id: str, question: str, most: int = 2) -> list[int]` — 1-based pages of this paper's best-matching chunks, best first, de-duplicated. Returns `[]` when the paper has no chunks for the embedding model or on `GraphError`.
- Produces: `llm.ask_with_sources(s, question: str, title: str, paras: list[tuple[str, int, list[float], str]], context: str = "") -> dict` where each para is `(block_id like "p3-b7", page, rect, text)`. Returns `{"ok": True, "text": answer, "sources": [{"page", "rect", "gist"}]}` (at most 4 sources, unknown ids dropped, gist cut to 120 characters) or `{"ok": False, "error": message}`. Model JSON schema: `{"answer": str, "sources": [{"block": str (enum of the ids), "gist": str}]}`. On a reply that does not parse, ask once more with the error (as `export.place` does); if that also fails, return the plain `llm.ask` answer with `sources: []`.
- Produces: `SOURCES_SYSTEM` — answer in simple English, at most 6 short sentences, name only paragraph ids from the list, a gist of at most 12 words per source, at most 4 sources.
- Produces: `canvas.ask(s, paper_id: str, question: str, page: int, from_card: int | None, at: tuple[float, float]) -> dict | None` — picks pages (current page, plus `graph.pages_for`, else the current page's neighbours within the `llm.paper_text` budget), builds the paragraph list, adds the `chain` as context, calls `ask_with_sources`, saves source cards then the answer card (`kind="answer"`, `question`, `parent=from_card`; each source `parent=answer id`), laid out from `at` = (x, y) in canvas pixels: sources stacked from `at`, 14px apart, answer below them, all `w=260`; card heights estimated as `40 + 18 * ceil(len(text)/34)`. When there are no sources the answer text ends with "\n\nNo exact lines found." Returns `{"ok": True, "answer": card, "sources": [card...]}`, `{"ok": False, "error"}` (nothing saved) or None for an unknown paper.
- Produces route: `POST /papers/{id}/canvas/ask` with body `{question (1..1000), page (ge 1), from_card?: int, at: [x, y]}`.

- [ ] **Step 1: Write the failing tests** (fake model as in `tests/test_marks.py::test_box_grows_and_ai_sees_a_picture`: monkeypatch `llm.pick_model` and `llm.client`; also monkeypatch `graph.pages_for` where noted)

```python
def test_ask_saves_sources_that_point_at_real_paragraphs(monkeypatch) -> None:
    replies = ['{"answer": "Noise on small groups.", "sources": [{"block": "p1-b1", "gist": "Second paragraph says it."}, {"block": "p9-b9", "gist": "Made up."}]}']
    ...  # fake create() returns replies.pop(0); graph.pages_for -> []
    r = c.post(f"/papers/{pid}/canvas/ask", json={"question": "Why?", "page": 1, "at": [20, 20]}).json()
    assert r["ok"] and r["answer"]["question"] == "Why?" and len(r["sources"]) == 1
    assert r["sources"][0]["rect"] == marks.blocks(pid, 1)["blocks"][1] and r["sources"][0]["parent"] == r["answer"]["id"]
    assert len(c.get(f"/papers/{pid}/canvas").json()["cards"]) == 2

def test_broken_json_is_asked_again_then_falls_back(monkeypatch) -> None:
    replies = ["not json", "still not json", "A plain answer."]
    ...
    r = c.post(...).json()
    assert r["ok"] and r["sources"] == [] and r["answer"]["text"].endswith("No exact lines found.")

def test_no_embedding_model_falls_back_to_nearby_pages(monkeypatch) -> None:
    # graph.embed_model raises GraphError; pages_for must return [] and ask must still work
    assert graph.pages_for(settings.get_all(), pid, "q") == []

def test_a_page_with_no_text_still_gets_an_answer(monkeypatch) -> None:
    # blank one-page PDF; fake model returns plain text after two bad JSON replies
    assert r["ok"] and r["sources"] == []

def test_follow_up_gets_the_chain_and_branches(monkeypatch) -> None:
    # ask once, then ask with from_card = first answer id; the second prompt contains the first answer's text
    assert second["answer"]["parent"] == first["answer"]["id"] and first["answer"]["text"] in prompts[-1]

def test_model_unreachable_saves_nothing(monkeypatch) -> None:
    # fake create() raises openai.APIConnectionError(request=None)
    assert r == {"ok": False, "error": "Could not reach the model. Is Unsloth running?"}
    assert c.get(f"/papers/{pid}/canvas").json()["cards"] == []
```

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** `graph.pages_for`, `llm.ask_with_sources`, `canvas.ask`, and the route.
- [ ] **Step 4: Run the suite** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — "Ask with sources: Dot names the paragraphs that answer".

---

### Task 4: Dot answers inside notes

**Files:**
- Modify: `workbench/llm.py` (`NOTE_SYSTEM`, `note_reply`)
- Modify: `workbench/canvas.py` (`for_dot`, `say`)
- Modify: `workbench/main.py` (`POST /papers/{id}/canvas/cards/{cid}/say`)
- Test: `tests/test_canvas.py`

**Interfaces:**
- Consumes: `marks.boxed` (text + PNG of the note's rect), `canvas.edit_card`.
- Produces: `canvas.for_dot(line: str) -> bool` — True when the stripped line ends with "?", starts with "@ai", or its first word (case-insensitive) is one of `explain, summarize, summarise, define, compare, why, how, what`. This exact rule is mirrored in the client (Task 11).
- Produces: `llm.note_reply(s, lines: list[dict], boxed_text: str, image: str | None, title: str, pages: list[str], page: int) -> dict` — like `ask_box` (picture of the area; retry without it on 400/415/422/500/501), the question is the last `me` line with "@ai" stripped, earlier lines of the note given as context. `NOTE_SYSTEM`: help a student inside their note about a part of a paper; trust the picture for formulas; 2 to 5 short sentences; for a formula, say what each symbol stands for.
- Produces: `canvas.say(s, paper_id, cid, text: str) -> dict | None` — appends `{"who": "me", "text"}`; if `for_dot(text)`, calls `note_reply` (note with no rect: no picture, current page 1) and appends `{"who": "dot", ...}` on success. Returns `{"ok": True, "card": card}` or `{"ok": False, "error", "card": card}` (your line is kept even if the model fails). None if the card is not a note on this paper.
- Produces route: `POST /papers/{id}/canvas/cards/{cid}/say` with body `{text (1..1000)}`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("line,dot", [("explain this formula", True), ("Why does it vary?", True), ("@ai what is f*", True),
    ("What a result", True), ("my own thought", False), ("howdy", False), ("  ", False)])
def test_which_lines_go_to_dot(line, dot) -> None:
    assert canvas.for_dot(line) is dot

def test_a_question_in_a_note_is_answered_in_the_note_with_a_picture(monkeypatch) -> None:
    # note card with page 1 and rect over the first paragraph; fake model records calls and answers "It means..."
    r = c.post(f"/papers/{pid}/canvas/cards/{n['id']}/say", json={"text": "explain this"}).json()
    assert [e["who"] for e in r["card"]["entries"]] == ["me", "dot"]
    assert calls[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png")

def test_a_plain_line_is_just_kept(monkeypatch) -> None:
    r = c.post(f".../say", json={"text": "my own thought"}).json()
    assert r["ok"] and [e["who"] for e in r["card"]["entries"]] == ["me"] and calls == []

def test_say_needs_a_note_on_this_paper() -> None:
    # an answer card -> 404; an unknown id -> 404; empty text -> 422
```

(`"What a result"` goes to Dot: the rule is about the first word, and the pill's hint shows it before Enter. Keep this case; it documents the rule.)

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the suite.**
- [ ] **Step 5: Commit** — "Notes on the canvas: Dot answers inside them".

---

### Task 5: Canvas in the Markdown export

**Files:**
- Modify: `workbench/export.py` (`markdown`)
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `canvas.read` (Task 2).
- Produces: after "Margin notes", a section `## Canvas` listing cards with kind `answer` or `note` in `created_at` order (then id): an answer as `- Q: {question}` then its text indented two spaces, then `  Sources: p. 3, p. 4` from its source children (pages, de-duplicated, in card order); a note as `- Note (p. N):` (or `- Note:` without a page) then each entry indented, Dot's entries prefixed `Dot: `. No section when there are no such cards.

- [ ] **Step 1: Failing test** — build an answer with two source children on pages 1 and 1, and a note with a me and a dot entry; assert the exact lines `"## Canvas"`, `"- Q: Why?"`, `"  Sources: p. 1"`, `"- Note (p. 1):"`, `"  Dot: It means this."` appear in `export.markdown(pid)` in that order.
- [ ] **Step 2: Run to see it fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the suite.**
- [ ] **Step 5: Commit** — "Export: the canvas section".

---

### Task 6: Dot learns to follow, offer options, change shape and be the input

**Files:**
- Modify: `static/buddy.js`
- Modify: `static/style.css` (Dot shapes, options arc, pill)
- Test: in the app (no JS test runner in this project): open a test paper at `http://localhost:8765/#read/<id>/1`, call the new functions from the browser console, take screenshots.

**Interfaces:**
- Produces on `buddy`:
  - `follow(on: boolean)` — trail the pointer each frame with lerp factor 0.16 at offset (+16, +14), as in the mockup. Paused while dragging Dot, while `pen`/`reading` is on, while an options arc or pill is open, and when the pointer leaves the window. Reduced motion: no trailing.
  - `options({ x, y, items: [{ key, label, icon /* inline SVG string */, disabled? }] }) -> Promise<string | null>` — icon buttons (38px circles) springing out on an arc of radius 58px at angles spread over -150°..30°; `aria-label` = label; name shown on hover/focus; arrow keys move focus, Enter picks, Escape or a click outside resolves null.
  - `shape(name: "face" | "marker" | "lens" | "squash" | "pill") -> Promise<void>` — resolves when the 380ms transition ends. `marker` reuses the existing `.pen` look (tilted, yellow); `lens` draws a magnifying glass on the dot grid (add a glyph like `GLYPHS`) inside a ring; `squash` is the flattened face; `face` restores mood drawing.
  - `prompt({ x, y, placeholder, hint?: (text) => string | null }) -> Promise<string | null>` — Dot becomes a pill (300×36) at (x, y), kept on screen, with its eyes at the left, an input, and a Back button (the return-arrow icon from the mockup) at the right. Enter resolves the trimmed text (ignored if empty); Back, Escape, or a pointerdown outside resolves null. `hint(text)` returning a string shows it as a small label under the pill while typing (used for "Ask Dot").
  - `gulp(): Promise<void>` and `burp(): Promise<void>` — the open-wide and bounce used when swallowing and spitting cards (mockup `.gulp` / `.full`).
  - `toolsOn(how: "click" | "context")` — which gesture opens the existing tools menu; the reader sets `"context"` (right-click or a 500ms long press), every other screen leaves `"click"`.
- Reduced motion: `follow` off, `shape` instant, `options` appear without springing.

- [ ] **Step 1: Implement** the six functions and their CSS, matching `cursor-v12.html` timings (shapes: `.4s cubic-bezier(.3,1.3,.4,1)`; options: `.35s cubic-bezier(.3,1.4,.4,1)`).
- [ ] **Step 2: Check in the app** — in the console: `buddy.follow(true)` and move the mouse (Dot trails); `await buddy.options({x:400,y:300,items:[{key:"a",label:"A",icon:"<svg/>"}]})` then press Escape (resolves null); `await buddy.prompt({x:300,y:300,placeholder:"Try"})` then click Back (null) and again type "hi" + Enter ("hi"); cycle `buddy.shape("marker"|"lens"|"squash"|"pill"|"face")` with a screenshot of each.
- [ ] **Step 3: Run the suite** (unchanged, must stay green) and **commit** — "Dot can follow, offer options, change shape and become the input".

---

### Task 7: The reading-mode shell

**Files:**
- Modify: `static/reader.js` (`renderReader`, `paneToggles` use)
- Modify: `static/style.css`
- Modify: `static/index.html` (add `<script src="/static/canvas.js"></script>` before `reader.js`; create an empty `static/canvas.js` with a `"use strict";` header comment so the page loads)

**Interfaces:**
- Consumes: `buddy.follow`, `buddy.toolsOn` (Task 6).
- Produces: in `renderReader`, the view holds only `pdf.el` and a canvas host `h("section", { class: "canvas-host" })` (empty until Task 9). The top bar (`#page-extra`) gets two chips, "Steps 3/10" (live count) and "Notes", each opening its existing panel (`rail.el` + notebook body, or `plain.el`) as a drawer over the paper's left/right edge; a drawer closes on Escape or a click outside. `paneToggles` and `splitter(view)` are no longer used by the reader (leave the functions in place if other code uses them; delete them if nothing does).
- Produces: `buddy.follow(true)` on entering the reader and `false` in `leave()`; `buddy.toolsOn("context")` on enter, `"click"` on leave. `dotTools()` gains a "Canvas" item (opens/closes the canvas once Task 9 exists; until then it is left out).
- Produces: Self-test (`pdf.autoHide`) also hides the canvas host.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Check in the app** — open a test paper: only the paper and Dot show; Steps and Notes chips open and close their drawers; step notes still save (type in a step on the test paper, reload, see it, then clear it); Map, Lens, Proactive, circle to search and Explain still work; right-click on Dot opens the tools menu; on the Library a click on Dot still does.
- [ ] **Step 3: Run the suite and commit** — "Reading mode: the paper first, steps and notes in drawers".

---

### Task 8: Paragraph options on the page: Suggest highlights, Add more, Back; your manual highlighter

**Files:**
- Modify: `static/reader.js` (`pdfViewer`)
- Modify: `static/style.css`

**Interfaces:**
- Consumes: `buddy.options`, `buddy.shape`, `buddy.goTo` (existing), highlight routes (Tasks 1 and 1A), `blocks` (already loaded per page), `readAlong`'s line grouping (reuse it to find the lines in a box).
- Produces: while the paper shows, the block under the pointer gets the thin yellow outline (`p.near` in the mockup) on `marksLayer`. A click (pointerdown + pointerup within 6px and 300ms, no text selected, not on a mark pin, not while Lens/pen/Map) on a block opens `buddy.options` with Suggest highlights, Ask, Note, Add more, Back. A click off any block offers Ask, Note, Back. The selection is one box (`.sel-box`) that is the union of the chosen blocks.
- Produces: **Suggest highlights** — `shape("marker")` and run along the selection's lines (as `readAlong`, repeating) while `POST /highlights/suggest` runs; when it returns, the marker goes to each suggested span and draws it in `--dot-ink` blue, line by line; none found → `buddy.say("Nothing here stood out to me.")`; error → `buddy.say(error)`. Then `shape("face")`, follow again.
- Produces: **Manual highlighter** — the existing selection bar (Explain / Find) gets a **Highlight** button: it converts the browser selection's `getClientRects()` (merged per line, clipped to the page) to PDF points and POSTs `{page, kind: "me", text, rects}`; drawn yellow at once.
- Produces: all saved highlights are drawn on each page draw in an `.hl-layer` (one stroke per rect; yellow for `me`, blue for `dot`). Clicking a stroke shows a small chip: **Keep** and **Remove** for blue, **Remove** for yellow (PUT / DELETE).
- Produces: **Add more** — `shape("squash")`, ride the box's bottom edge, grow the box over the next block in `blocks` order (springy `.55s cubic-bezier(.3,1.25,.4,1)`, the dot wave and "+N" badge from the mockup), `shape("face")`, reopen the options. At the last block on the page it does nothing but a small shake of Dot.
- Produces: **Back** — fold the options, drop the selection, follow again.
- Produces: `pdf.selection() -> { page: number, rect: number[] /* PDF points */, text: string } | null` for Tasks 10 and 11; Ask and Note call hooks `onAsk(sel)` / `onNote(sel)` passed into `pdfViewer` (wired in Tasks 10 and 11; until then they do nothing).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Check in the app** on a test paper: hover outlines paragraphs; click opens five icons; Add more twice grows to three paragraphs with "+2"; Suggest highlights (real model) marks only a few short spans in blue, Keep turns one yellow, Remove drops another; selecting a few words and pressing Highlight marks exactly those words yellow; all survive a reload (remove all test highlights after); Back returns to following; dragging still selects text and shows Explain; the reading tracker still works.
- [ ] **Step 3: Run the suite and commit** — "Click a paragraph: Dot suggests highlights, adds more, goes back; you highlight by hand".

---

### Task 9: The canvas

**Files:**
- Create: `static/canvas.js`
- Modify: `static/reader.js` (create the canvas in `renderReader`; "Canvas" item in `dotTools`)
- Modify: `static/style.css`

**Interfaces:**
- Consumes: canvas routes (Task 2), `buddy.gulp/burp/goTo/shape` (Task 6), `pdf.go(n)`, `pdf.page()`, page-pixel helpers in `pdfViewer` (expose `pdf.toScreen(page, rect) -> DOMRect | null` for a rect on the page shown, null otherwise).
- Produces: `canvasPanel(host: HTMLElement, paperId: string, pdf) -> { open(): Promise<void>, close(): Promise<void>, isOpen(): boolean, add(card): HTMLElement, place(): { x, y } /* a free spot near the top of the visible area */, el, redraw(): void, destroy(): void }`.
- Behaviour (copy the mockup):
  - **Ways to open:** Dot's menu item "Canvas", a small tab on the paper's right edge, and any Ask or Note (Tasks 10 and 11).
  - **Open:** the paper slides left (`1s cubic-bezier(.3,.7,.2,1)`); the canvas is revealed by `clip-path: circle()` growing from Dot's centre (`.8s cubic-bezier(.6,0,.2,1)`), two rings ripple out of Dot, a wave of lit grid dots crosses it (`@property --r`), Dot bounces. Cards with `hidden` set are spat back out on arcs (and saved with `hidden: false`). Open state is remembered per paper (`localStorage` key `canvas-open:<paperId>`).
  - **Close:** every visible card is swallowed (below), then the circle shrinks back into Dot and the paper slides back. Cards are saved with `hidden: true`.
  - **Cards:** answer (yellow), source (graphite, "p. N · from K lines"), note (dashed yellow border, entries as lines; Dot's lines with the small face). Drag to move (PUT x, y on drop); a small handle on the right edge, dragged onto another card, makes a link (POST); right-click a card for "Delete" (DELETE, with the swallow animation); its x puts it away (swallow, `hidden: true`). Empty-canvas drag pans (pan offset kept in memory).
  - **Threads:** SVG layer; parent threads dashed yellow, drawn links solid grey; threads from sources to their paragraph only when that page is shown (via `pdf.toScreen`), otherwise ending at the canvas edge with a "p. N" tag. New threads draw themselves (stroke-dashoffset, 650ms). Recompute on page change, zoom, scroll, resize and drag.
  - **Hover:** the card tilts toward the pointer (max 3°) and lifts; a spark runs along its threads; a source card lights its paragraph. **Click** a source card: `pdf.go(page)` and scroll its paragraph into view, then glow it.
  - **Swallow:** card squashes and fades (.25s), crumbles into up to 70 dots in its colours that fly on curved, staggered paths into Dot (`buddy.gulp()` first, `buddy.burp()` after).
- Self-test hiding the paper also closes the canvas.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Check in the app** on a test paper: create two cards and a link through the API in the console; open the canvas from Dot's menu (circle from Dot, ripple, wave); drag a card, reload, it stays; link two cards by the handle; hover tilts and sparks; x swallows; close and reopen spits them back; right-click Delete removes; delete all test cards through the API after.
- [ ] **Step 3: Run the suite and commit** — "The canvas: opens out of Dot, cards, threads, swallow and spit".

---

### Task 10: Ask: the magnifier, sources lifting off the page, follow-ups

**Files:**
- Modify: `static/reader.js`, `static/canvas.js`, `static/style.css`

**Interfaces:**
- Consumes: `pdf.selection()` and the `onAsk` hook (Task 8), `buddy.prompt/shape` (Task 6), `canvasPanel` (Task 9), `POST /canvas/ask` (Task 3), `glow` and the `dot-read` style already in `pdfViewer`.
- Produces: **Ask** — `buddy.prompt` at the selection ("Ask about this part..."); on text: open the canvas if closed; `shape("lens")` and sweep the visible page (back and forth over the blocks) until the reply arrives; then for each source on the page shown: light its paragraph, clone its text-layer spans into a floating box, fly it to its card's spot while shrinking (`.9s`), swap to the gist card, draw the thread; then the answer card fades in with threads to its sources. Sources on other pages appear directly as cards with an edge "p. N" thread. Error: `buddy.say(error, { mood: "worried" })`, nothing added.
- Produces: **Follow-up** — click an answer or source card: `buddy.prompt` on the card ("Follow up on this card..."); POST with `from_card`; the new answer card lands below and right of the clicked card with a downward thread.
- Click anywhere during the animation skips to the end state.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Check in the app** with the real local model on a test paper: ask "why does data order matter?" on a paragraph of page 3 of a two-column paper; sources lift off and land with threads; hover a source lights its paragraph; follow up on the answer; stop Unsloth (or point Settings at a wrong port on the test run only, then restore) and check the error shows and nothing is added. Delete the test cards after.
- [ ] **Step 3: Commit** — "Ask: Dot searches the page and pulls the answer's sources onto the canvas".

---

### Task 11: Note: notes unroll out of Dot, and Dot answers inside them

**Files:**
- Modify: `static/reader.js`, `static/canvas.js`, `static/style.css`

**Interfaces:**
- Consumes: `onNote` hook and `pdf.selection()` (Task 8), `buddy.prompt` with `hint` (Task 6), canvas cards (Task 9), `POST /canvas/cards` and `POST /canvas/cards/{cid}/say` (Tasks 2 and 4).
- Produces: client copy of the rule `forDot(line)` identical to `canvas.for_dot` (Task 4); the pill hint shows "Ask Dot" while `forDot(text)` is true.
- Produces: **Note** — `buddy.prompt` ("Write a note, or ask Dot..."); on text: open the canvas if closed; create the note card (`kind: "note"`, `page`, `rect` = selection) at `place()`, unrolled left to right (`.55s`) with the text typing in behind a blinking yellow caret; thread drawn to the selection; then `POST /say` with the line. If the reply has a Dot entry: Dot hops onto the card, the small face with three hopping dots shows, then the reply types in word by word (55ms a word).
- Produces: clicking a note card opens `buddy.prompt` on it ("Add to this note...") and each line goes through `/say` the same way.
- Produces: double-click on empty canvas makes a note with no page or rect.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Check in the app** with the real model on a test paper with a formula (equation (1) on page 3 of the fairness paper is a good one, but use a copy uploaded as a test paper): select it, Note, "explain this formula": the note unrolls, Dot answers inside it and names the symbols; add "my own thought" (kept, no Dot line); export Markdown shows the Canvas section; delete the test paper after.
- [ ] **Step 3: Run the suite and commit** — "Notes: they unroll out of Dot, and Dot answers inside them".

---

### Task 12: Finish: reduced motion, skipping, and a last look

**Files:**
- Modify: `static/style.css`, `static/buddy.js`, `static/canvas.js`, `static/reader.js` as needed

- [ ] **Step 1:** With the browser set to reduced motion (`mcp__Claude_Browser__resize_window` cannot set it; use DevTools rendering emulation or `matchMedia` override in the console), walk Suggest highlights, manual Highlight, Add more, Ask, Note, open/close canvas: nothing moves except fades; everything still works.
- [ ] **Step 2:** Click during each animation: it jumps to its end state, and the saved data matches.
- [ ] **Step 3:** Keyboard: Tab reaches Dot; Enter on Dot's options; Escape always backs out.
- [ ] **Step 4:** Remove all test data (papers, cards, highlights) through the API; run `uv run pytest -q`; commit and push — "Reading mode: reduced motion, skipping and keyboard".
