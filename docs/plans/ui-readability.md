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
