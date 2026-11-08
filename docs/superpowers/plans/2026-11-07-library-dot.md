# Library around Dot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Library table with Dot in the middle: Bubble mode (papers floating and coloured by similarity, character blobs as options, an Ask field where Dot finds papers and runs jobs) and Shelf mode (spines on planks, grouped by similarity or by your themes).

**Architecture:** Two read endpoints in a new `workbench/shelf.py`: the similarity map and Ask, which proposes but never acts. The page lives in a new `static/library.js` and `static/library.css`. `renderLibrary` in `app.js` hands over to it and reuses the existing helpers for dialogs, themes, summaries and adding papers. Jobs run in the page through endpoints that exist today.

**Tech Stack:** FastAPI, SQLite, plain JS/CSS. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-07-library-dot-design.md`. The mockup is `docs/superpowers/specs/mockups/library-dot-v27.html`.

## Global Constraints

- No new dependencies. Never use the sqlite3 CLI on `./data`.
- Do not edit `static/buddy.js`, `static/style.css`, `static/reader.js`, `static/canvas.js`, `workbench/canvas.py` or `workbench/marks.py`.
- Fonts: Instrument Serif, Geist, Geist Mono, Doto. Colours: graphite plus #ffe347, plus the blob colours in the spec.
- UI text in simple English, with no em dashes.
- Reduced motion respected everywhere.
- The model goes through `primer._complete`, which falls back to JSON mode.

## Review Focus

- **Model offline or slow.** Ask still finds papers by title and meaning and says so. The map still renders, with fallback row names. Test: `test_ask_offline_falls_back_to_find`.
- **The model names papers that are not in the list, or an unparseable date.** These are dropped, and a date job turns into a question. Tests: `test_clean_drops_unknown_and_bad_date`, `test_clean_job_without_papers_is_none`.
- **An empty library, or 1 to 3 papers.** The map makes one group or none, with no crash. Test: `test_kmeans_small`.
- **No embedding model.** Every paper is unread grey and a reason is given. Test: `test_map_without_embeddings`.
- **Delete is asked for.** The page always confirms in the field first. Checked in the app.

---

### Task 1: Similarity map and Ask endpoints

**Files:**
- Create: `workbench/shelf.py`
- Modify: `workbench/db.py`: add `shelf_names(key TEXT PRIMARY KEY, name TEXT NOT NULL)` to `SCHEMA`
- Modify: `workbench/main.py`: add `GET /library/map` and `POST /library/ask`
- Test: `tests/test_shelf.py`

**Interfaces (produces):**
- `shelf.kmeans(vecs: dict[str, array], weight: dict[str, int]) -> list[list[str]]`
- `shelf.library_map(s, name_groups=True) -> {groups: [{id, name, hue, paper_ids}], unread: [ids], reason?}`
- `shelf.ask(s, question, history) -> {reply, action: {kind, paper_ids, date?, theme?}, papers: [{id, why}], offline?}`
- `shelf.clean(out, alias) -> same shape as ask`
- `POST /library/ask` takes the body `{question: str (1-500 chars), history: [{q, a}] (at most 4)}`.

- [ ] **Step 1: Write the tests.**
  - `test_kmeans_small`: 0 papers give `[]`, and 3 papers give one group.
  - `test_kmeans_splits_topics`: with the fake embed from `test_graph.py`, the street/privacy papers and the protein papers land in different groups, and the result is the same on every run.
  - `test_map_groups_and_names`: monkeypatch `_ask_names`. Names are cached in `shelf_names`: a second call does not ask again.
  - `test_map_without_embeddings`: make `embed_model` raise `GraphError`. Every paper is in `unread` and `reason` is set.
  - `test_clean_drops_unknown_and_bad_date`
  - `test_clean_job_without_papers_is_none`
  - `test_ask_offline_falls_back_to_find`: make `_complete` raise `PrimerError`. The kind is `find` and `offline` is true.
- [ ] **Step 2:** Run `uv run pytest tests/test_shelf.py -q` and expect failures.
- [ ] **Step 3:** Implement, following the spec's "Similarity" and "Ask" sections and the builder-check calls. For state questions, the candidates go up to 40.
- [ ] **Step 4:** Run `uv run pytest -q`. Expect all tests to pass.
- [ ] **Step 5:** Commit "Library: similarity map and Ask endpoints".

### Task 2: The Library page around Dot

**Files:**
- Create: `static/library.js`, `static/library.css`
- Modify: `static/index.html`: add the stylesheet and the script (before `app.js`)
- Modify: `static/app.js`:
  - `renderLibrary` calls `libraryStage({settings, frameworks, papers, themes})`.
  - `libRedraw` redraws the stage.
  - Remove `libHead`, `libBody`, `themeBar`, `paperTable`, `paperRow`, `agenda`, `libEmpty` and `dropGlyph` once nothing uses them.

**Interfaces:**
- Consumes from `app.js`: `h`, `api`, `streamPrimer`, `primerLabel`, `themePicker`, `rowMenu`, `detailsDialog`, `enablePageDrop`, `addPaper`, `filePicker`, `nextTalk`, `fmtDate`, `relDays`, `ago`, `fmtSpent`, `themeList`, `lib`, `STATUSES`, `SORTS`. These are all globals, because the scripts are classic scripts.
- Produces: `libraryStage(ctx) -> HTMLElement` and `libraryLeave()`. `libraryLeave` is called from `route()`, and it restores `buddy.say` and `buddy.busy` and stops the animation loops.

- [ ] **Step 1: Stage and Dot.**
  - A graphite stage (`.lib-stage`) fills the view.
  - The centre Dot is a yellow blob with oval eyes that blink and follow the pointer.
  - Dot's line sits above Dot, and the count sits under it.
  - The buddy is hidden while the Library is open, and `buddy.say` and `buddy.busy` are wrapped.
- [ ] **Step 2: Ring.**
  - Up to 12 papers, picked in the spec's order, drift in one `requestAnimationFrame` loop using `translate3d`.
  - Their hue comes from `/library/map`, which is fetched after first paint. Cards fade to their colour when it arrives.
  - Click a paper, or drag Dot onto it, to open the peek card. The peek card holds the cover, details, chips, `themePicker`, steps, Go, the Reflection done switch and `rowMenu`.
- [ ] **Step 3: Blobs.** The seven character blobs from the mockup's v27 CSS, in an orbit that pauses near Dot or on focus. The gulp animation runs, then the job:
  - What next, Talks and Pick up, as in the spec.
  - Add paper opens a tray with Choose PDF.
  - Settings goes to `#settings`.
  - Shelf switches to Shelf mode.
- [ ] **Step 4: Ask field.**
  - The blob stretches into the field, with the typist on a spring and the goo filter, and letters stamp on.
  - On Enter: ding, swallow, then the thinking look, then `POST /library/ask`.
  - The reply floats up in yellow.
  - For `find`, papers rise with their why. For a job, helpers fly to the papers and run it through the existing endpoints. `delete` asks Yes or No first.
  - History pills sit above the field.
  - Escape or a click outside closes the field.
- [ ] **Step 5: Shelf mode.**
  - The pill filters live.
  - Planks grow in, and spines carry their hue.
  - Group: by similar or my themes. Sort and Show use `SORTS` and the five `STATUSES`. The other blobs are + Theme, + Paper, Settings and Bubble.
  - A theme row's label has an x that deletes the theme after a confirm.
  - Enter in the pill switches to Bubble and asks there.
- [ ] **Step 6: Empty state and reduced motion,** as in the spec.
- [ ] **Step 7: Check in the app.**
  - Start the preview `workbench`, open `#library` and screenshot both modes.
  - Ask "show me my papers on <a word from a title>" and check the cards rise.
  - Open a peek card and change the talk date.
  - Make sure there are no console errors.
- [ ] **Step 8:** Run `uv run pytest -q`. Commit "Library: Dot in the middle, bubble and shelf modes", and push to `ui-readability` and `main`.
