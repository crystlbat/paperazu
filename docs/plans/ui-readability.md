# Plan: UI readability and font consistency

Spec: no spec file. The binding source is the user's build prompt (summarised in Global Constraints) plus the user's feedback of 2026-11-06:
"these fonts are too thin, for all views ensure readability is comfy and font consistency across entire platform ... what is primer? if its AI filler say so ... readability on dark mode especially the library when selected is so bad".

Project: local FastAPI app. Frontend is plain HTML/CSS/JS with no build step: `static/index.html`, `static/style.css`, `static/app.js`, `static/buddy.js`. Run: `uv run app.py` (port 8765). There is no frontend test runner; verification is by reading the code and loading the page.

## Global Constraints

- Fonts (from the build prompt): Instrument Serif for step titles, Geist for body text, Geist Mono for numbers and the timer. Fonts load from Google Fonts in `static/index.html`. Doto (dot-matrix) is used only for the reading buddy and the Library header counters.
- Colors: graphite and off-white, one yellow highlighter accent `#ffe347`. Yellow means "you are here" (current nav page, current step, current settings section, step title, next presentation date). Nothing else is yellow.
- Light and dark mode via `prefers-color-scheme`.
- UI text: simple English, sentence case, no em dashes.
- No new dependencies. No build step. No frameworks.
- Do not change backend Python files, API routes, JSON field names or database names. `primer`, `primer_status` stay as they are in code and API.
- Reduced motion must stay respected.

## Task 1: Typography and readability system

Files: `static/index.html`, `static/style.css`, `static/app.js` (only class names or markup needed for the type roles), `static/buddy.js` (only if needed for the bubble text).

Goal: text everywhere reads comfortably in light and dark mode, and the platform uses a small, consistent set of type roles.

Requirements:
1. Load Geist as a variable weight range that covers 400 to 700 (Google Fonts `Geist:wght@400..700`) and Geist Mono 400 to 600.
2. Remove `-webkit-font-smoothing: antialiased` (it makes text thinner on macOS, worst in dark mode).
3. Define the type roles once as CSS custom properties or classes at the top of `style.css`, and use them everywhere instead of ad hoc sizes:
   - Display (page titles "Library", settings section titles, dialog titles, step titles): Instrument Serif. Instrument Serif is used only at 28px or larger.
   - Body: Geist 16px, weight 450, line-height 1.55.
   - UI label and secondary text (table headers, field labels, authors, help text, captions): Geist 14px, weight 450 or 500. No visible text smaller than 13px anywhere, including the buddy bubble and data-label captions.
   - Paper titles in the Library list: Geist 17px, weight 600, line-height 1.3 (not Instrument Serif: a single-weight serif is too thin at this size).
   - Numbers in tables and meta (progress count, time spent, reflection number, dates): Geist with `font-variant-numeric: tabular-nums`, same size and weight as the surrounding text. Geist Mono is used only for the step timer and its budget line in the Reader. This fixes mixed fonts in one row (for example "0 min" in mono next to "Just now" in sans).
   - Interactive text (nav links, buttons, segmented filter buttons, menu items, settings sub-menu): Geist 15px, weight 500.
4. No `font-weight` below 400 anywhere. No text set in `--pencil` on `--paper` in dark mode with a contrast ratio under 7:1, and no text on any background in either mode under 4.5:1. Check the actual hex values in `:root` and the dark block; adjust `--pencil` or the backgrounds if needed, and put the computed ratio for each text/background pair you rely on in a comment next to the dark-mode tokens.
5. Selected states must be clearly readable in dark mode and light mode: active top nav link, active segmented filter button, active settings sub-menu item, active Reader rail step, `aria-pressed="true"` buttons and row hover in the Library table. Active labels use weight 600. Where a selected state puts text on the yellow marker, the text color is `#1f2023` or darker (contrast on `#ffe347` must be at least 7:1) and the marker must fully cover the text height (no thin strip under thin text). Where a selected state uses a background tint, the text on it must meet the 7:1 rule in dark mode.
6. Checkboxes in the Library table must be clearly visible in dark mode (border or accent with at least 3:1 against the row background).
7. Keep the visual concept: dotted paper background, yellow "you are here" marker, graphite device for the buddy. Do not add new colors except to fix contrast.

Done when: every visible text element maps to one of the roles above, the dark-mode Library page (header, filters, table with hover, menu, dialog) meets the contrast rules, and the CSS has no leftover font sizes or families outside the roles.

## Task 2: Rename "Primer" to "AI summary" in the UI

Files: `static/app.js` only.

Goal: the user understood "Primer" as unclear. It is an AI-written summary, made by the local model, that is split into the reading steps and hidden until the student writes their own notes.

Requirements:
1. Every user-visible "Primer"/"primer" string becomes "AI summary" (sentence case). This includes: the Library table column header and card label, the row menu item "Make primer again" which becomes "Make AI summary again", and the Settings sub-menu label "Primer" which becomes "AI summary". The status values stay: "Not made", "Making", "Ready", "Failed".
2. Add a short explanation where the user first meets the term: give the Library column header a `title` tooltip and an accessible description: "A short summary of the paper, written by the AI model on your Mac. It is split into the reading steps and stays closed until you write your own notes."
3. Add one tip to the reading buddy's random tips in `static/buddy.js` is NOT allowed (Task 2 touches `app.js` only); instead, add a buddy line in `app.js`: when the user opens the Settings section "AI summary" (`#settings/primer`), call `buddy.say` with the explanation above, mood "idle", `pop: false`.
4. Do not change internal identifiers (`PRIMER` constant name may stay, `primer_status`, `#settings/primer` route id, CSS class `primer`).

Done when: `grep -ni primer static/app.js` shows no user-visible string containing "primer" (identifiers, routes and class names are fine), and the explanation is reachable by tooltip and by the buddy.

## Task 3: Notes API (build-prompt phase 3, backend)

Files: new `workbench/notes.py`; `workbench/main.py` (routes only); `workbench/library.py` (only if a helper must be shared); new `tests/test_notes.py`; `pyproject.toml` (pytest as a dev dependency group only).

Runs in parallel with Tasks 1 and 2: it must not touch anything under `static/`.

Data shape stored in the existing `notes` table (`paper_id`, `step_id`, `data` JSON, `seconds`, `updated_at`):
`data = {"fields": {<field_id>: <value>}, "gate": [<bool>, ...]}`. Field values: `text`/`long`/`date`/`choice` are strings; `rows` is a list of lists of strings; `checks` is a list of strings. `library.step_state(step, data)` already defines empty/partial/done from this shape and must keep working unchanged.

Requirements:
1. `GET /papers/{paper_id}/notes` returns `{"steps": {<step_id>: {"fields": {...}, "gate": [...], "seconds": int, "state": "empty"|"partial"|"done", "updated_at": str}}, "steps_done": int, "total_steps": int}`. Steps with no saved row are omitted from `steps`. 404 with detail "This paper is not in the library." if the paper does not exist.
2. `PUT /papers/{paper_id}/notes/{step_id}` with body `{"fields": {...}, "gate": [...], "seconds": int}` saves one step (upsert), sets `updated_at`, refreshes the paper's search row (`library.reindex`), and returns `{"state": ..., "steps_done": int, "total_steps": int, "updated_at": str}`. 404 for an unknown paper. 422 with `{"errors": {...}}` (same shape as the existing settings/paper PATCH errors) for: unknown `step_id` (not in the current framework), `seconds` not an integer from 0 to 86400, `gate` not a list of booleans, `fields` not an object, a field value that is not a string, list of strings, or list of lists of strings, or a request body larger than 200 KB.
3. Field ids that are not in the current framework step are accepted and stored (the build prompt says notes for removed fields are kept and shown as "Old fields"). The API never deletes stored fields that the request omits: the request's `fields` object replaces stored fields key by key (merge), so an older client cannot wipe other fields.
4. Validation with a Pydantic model in `notes.py`, consistent with `library.PaperPatch` style. Type hints everywhere, short functions.
5. Tests in `tests/test_notes.py` with pytest, using a temporary database (point `db.DB_PATH`/`db.DATA_DIR` at `tmp_path` via monkeypatch and call `db.init()`), testing the `notes.py` functions directly (no HTTP client: `httpx` is not an allowed dependency). Cover: save then load round trip, merge keeps omitted fields, unknown field id kept, unknown step rejected, bad seconds rejected, state transitions empty -> partial -> done for one step using the real `framework.yaml`, steps_done count, and search finds a word from saved notes via `library.list_papers(fw, q=...)`. Add pytest with `uv add --dev pytest`. Run with `uv run pytest -q`.

## Task 4: Reader frontend (build-prompt phase 3)

Runs after Tasks 1, 2 and 3 are merged. Files: `static/app.js`, `static/style.css`, `static/index.html` (PDF.js script tag only).

Requirements (from the build prompt, Reader page):
1. Middle pane: PDF rendered with PDF.js 3.11.174 from cdnjs (`pdf.min.js` and its worker), loaded from `GET /papers/{id}/pdf`. Canvas rendering only, no text layer (the student must not copy text). Controls: page number input, previous, next, zoom in, zoom out, fit width. Render only the current page. Keyboard: left/right arrow keys change page when focus is not in a text field.
2. "Hide paper" button in the top bar blurs the PDF and shows "Paper closed" with a "Show the paper anyway" button. Step 8 (`paper_hidden: true` in framework.yaml) does this automatically when the step opens.
3. Right pane notebook for the current step, rendered from `framework.yaml` field types: `text` (input), `long` (auto-growing textarea), `date` (date input), `rows` (table with the step's `cols`, `start_rows` empty rows, an "Add row" button, numbered rows when `numbered: true`), `choice` (radio group), `checks` (checkbox group). Show `help` text under the label.
4. Autosave every change with a 500 ms debounce to `PUT /papers/{id}/notes/{step_id}` (Task 3). A save status in the footer: "Saving", "Saved", or "Could not save. Retrying." with retry. Never lose typed text when switching steps (flush the pending save first).
5. Notes for field ids that are no longer in the step are shown read-only in an "Old fields" box at the end of the step.
6. "Before you move on" checklist from `gate`, saved with the notes.
7. Timer: counts the time spent on the current step, starting when the step opens only if a setting says so (default off: show a Start button; the setting arrives in a later phase, so read a constant default off). Pause/resume. Shown in Geist Mono as `mm:ss / mm:00` with the thin budget bar. When over budget, show a gentle warning ("Over the time budget. Finish the thought, then move on.") and colour the bar amber. Seconds are saved with the notes.
8. Left rail circles: empty, partial (dashed ring), done (filled) from the API `state`, updated after each save. Top bar progress "n / 10 steps done" updates after each save.
9. Footer: Back, save status, Next step. "Review" in the rail stays disabled (later phase).
10. The reading buddy (`buddy.say`) keeps its step tip on step change. When a step becomes "done", the buddy says a short happy line.
11. Uses the type roles from Task 1. Works in light and dark mode and in a narrow window (stack panes; the PDF pane above the notebook).

## Task 5: Visual enrichment (Library, Settings, global, buddy)

Runs in parallel with Task 2 in its own worktree, and before Task 4 so the Reader inherits the visual language. Files: `static/style.css`, `static/index.html`, `static/buddy.js`, and in `static/app.js` only the Library and Settings render code (`renderLibrary`, `libHead`, `libEmpty`, `libBody`, `paperTable`, `paperRow`, `progressBar`, `renderSettings`, `drawConnection`, dialogs). Do not touch `renderReader`, `drawNotebook`, `stepTip`, backend files, or any visible string that contains "Primer" or "AI summary" (Task 2 owns those).

User request (2026-11-06): "enrich the UI visually". Earlier: "add more visual elements and effects", "Nothing style reading buddy / AI guide that is lively", "hope the UI design will be top notch and not some generic stuff".

Requirements:
1. Keep the established concept: dotted notebook paper, graphite and off-white, the single yellow `#ffe347` marker that means "you are here", the dot-matrix (Doto) language shared with the reading buddy "Dot". Extend this language; do not introduce a second visual idea.
2. Add visual richness that carries information, chosen with restraint (pick the strongest 3 to 5, not all). Candidates: a dot-matrix "next 14 days" strip in the Library header that marks presentation dates (today and the next talk marked); a generated dot-matrix monogram or "cover" per paper derived from its title (deterministic, no images); a richer empty state (for example an animated dot-matrix illustration on the drop page); a dot-matrix connection meter or status display in Settings "Model connection"; buddy reactions to more events or new expressions; one orchestrated page-load moment. Decorative-only effects that carry no information are out.
3. Readability rules from Task 1 stay binding: type roles defined at the top of `style.css`, no text under 13px, no weight under 400, dark-mode secondary text 7:1 or better on its background, every text pair 4.5:1 or better, selected states readable in both modes. New colors only if they keep these ratios; record any new pair's ratio in the token comment.
4. Motion: only one load sequence plus motion that answers a user action; everything respects `prefers-reduced-motion`. No continuous animation except the buddy's existing idle life.
5. Works in light and dark mode, desktop and a 375px wide window. No horizontal scroll.
6. No new dependencies, no images or external assets beyond the already-loaded Google Fonts. No build step.
7. Verify visually: screenshot the Library (with at least one paper and with zero papers if you can do so without deleting user data; do not delete or modify existing papers) and Settings in light and dark, desktop and mobile, and fix what looks wrong before committing.
