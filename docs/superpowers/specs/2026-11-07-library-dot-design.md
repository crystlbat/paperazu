# The Library, centred on Dot

Date: 2026-11-07. Status: mockup approved in chat ("perfect start the build"), 2026-11-07.

## Why

The Library today is a table: header, agenda strip, search, filters, then one dense row per paper. The user's words: "clunky, looked dead, too text heavy, spaces less utilised, boring table format". They want it "bot oriented": Dot is the centre, and the Library works through Dot, the way the new reading mode does (see `2026-11-07-dot-canvas-design.md`).

The agreed picture is the live mockup `docs/superpowers/specs/mockups/library-dot-v27.html`. It is a copy of the last brainstorm screen and holds every motion described below. Open it in a browser to see it. It is an HTML fragment, so some page chrome is missing; the stage `#st` is what matters. Where this text and the mockup differ, this text wins.

## Goals

1. **Two modes: Bubble (friendly, the default) and Shelf (serious).** You switch with the Shelf blob, and back with the bubble blob on the shelf. The last mode you used is remembered.
2. **Bubble mode: Dot in the middle, your papers floating around it.**
   - Up to 12 paper cards float in a loose, slowly drifting ring around Dot. The cards are slightly tilted, with title, step dots and talk date, as in the mockup.
   - **Colour shows similarity.** Papers that are about the same thing share a hue. There are no lines between papers and no extra dots.
   - **Peek.** Drag Dot onto a paper, or click a paper, and a peek card opens. It holds everything a table row has today (goal 7).
   - Under Dot, a small count: "40 papers 3/6 reflections".
   - Above Dot, Dot's greeting as plain text with no box, for example about the next talk.
3. **The small blobs are Dot's options.** Seven small coloured blobs orbit Dot slowly. The orbit pauses while the pointer is within 150px of Dot. Each blob keeps a face (two eyes that blink) and takes the shape of its job. Its name shows faintly under it when you are near Dot or hover it:

   | Blob | Colour | Shape and motion | What it does |
   |---|---|---|---|
   | Ask | blue #8ecbff | round, mouth chatters | stretches into the Ask field (goal 4) |
   | What next? | green #7bd88f | looks right, hops on little feet | Dot looks over your talks and steps left, then lifts the one paper that needs you next to the middle and peeks it |
   | Talks | coral #ff9e7a | a calendar with rings, face on the page | a 14-day strip appears and dated papers drop under their day; the rest dim below |
   | Pick up | violet #c6a0ff | a book with a swinging ribbon | the last opened paper comes to the middle with Continue |
   | Add paper | yellow #ffe347 | a page with a folded corner and a "+", dropping in | Dot opens as a tray: drop a PDF on it or Choose PDF. Dropping a PDF anywhere on the page still works too |
   | Shelf | pink #ff7ab8 | wears the keeper's glasses | switches to Shelf mode |
   | Settings | grey #c9cdd6 | a turning gear, the face stays still | opens the Settings page |

   Clicking a blob makes Dot swallow it (the gulp), and then the job plays. A Back control returns to the ring.
4. **Ask: the blob becomes the field, and Dot can do things.**
   - The Ask blob stretches into a wide input field below Dot. There is no separate chat box and no speech bubble. The background fades.
   - A small typist blob is merged into the field's lower edge (the gooey join) and sits under the last letter. Each key you type stamps the letter on with a slight random tilt, like a typewriter. The typist strikes and bounces on a spring.
   - **On Enter:** a ding, the typist's eyes go wide, your letters fly one by one into it, it eats them with squeezed happy eyes, gulps, then looks side to side while the model thinks.
   - **Dot's reply looks different from your text.** The field turns Dot's yellow and the reply floats up softly, word by word in a wave. It is not stamped.
   - **History.** When you start the next question, the finished turn tucks away as a small dark glass pill above the left end of the field. The pill holds the question, with a tiny half-blue, half-yellow mark meaning "you asked, Dot answered". On hover or focus it opens and shows the start of Dot's answer in yellow. A click brings the full answer back into the field. Older pills fade; at most 5 are kept. History lasts for the visit and is not saved.
   - **Fetch.** When the question asks for papers ("show me my papers on fairness"), the matching papers rise to the middle as clickable cards, each with a one-line "why" under it. A click peeks it.
   - **Helpers.** When the question asks for work ("make summaries for the papers I have not opened"), Dot says what it will do, then sends small helper blobs flying to each paper. A paper being worked on lights up with a turning ring. When a job finishes, its paper gets a tick. See "What helpers can do" below.
   - Click outside the field or press Escape, and the field shrinks back into the Ask blob and the orbit starts again.
5. **Shelf mode: Dot becomes the search pill, the whole library sits on shelves.**
   - Dot puts on glasses and stretches into a search pill at the top. Typing filters the spines live by title, author, tag and notes, as search does now. Enter asks Dot, the same as goal 4.
   - Every paper is a spine on a wooden plank, coloured by its similarity hue.
   - Rows are either **by similarity**, with rows named by Dot, or **by my themes**, with your own themes plus Unsorted.
   - Calm blobs sit beside the pill with their names always visible: Group (by similar or my themes), Sort (presentation date, last opened, title, progress), Show (All, Not started, In progress, Notes done, Reflection done), + Theme, + Paper, Settings, Bubble.
   - Clicking a spine peeks it.
6. **The Graph page stays** as it is, and so does its nav entry.
7. **Nothing the Library can do today is lost.** Here is where each thing lives now:
   - **Search, status filter, sort:** the Shelf pill and the Show and Sort blobs. In Bubble mode, Ask finds papers.
   - **Themes:** create with + Theme. Filter by grouping the shelf by my themes. Delete from the shelf row's label, which shows a small x on hover and asks first. Add a paper to a theme from the peek card.
   - **Add paper:** the Add paper blob, Choose PDF, and drop anywhere.
   - **14-day talk agenda:** the Talks blob.
   - **Paper and reflection counts:** under Dot, and under the shelf pill.
   - **Dot's greeting about the next talk:** the plain text above Dot.
   - **Empty state:** see "My calls".
   - **Per paper, all in the peek card:**
     - cover, title, authors, Paper or Slides
     - talk date or "+ Set talk date", and reflection number
     - AI summary state (make, remake, streamed progress) and its gist
     - time read and last opened
     - theme chips with "+ theme", and tags
     - step dots
     - Start / Continue / Review
     - the Reflection done switch
     - a More menu: Edit details, Make AI summary, Export Markdown, Export reflection outline, Delete

## Non-goals

- Changing the reader or reading mode. Another session is building it in `static/reader.js`, `static/canvas.js`, `workbench/canvas.py`, `workbench/marks.py` and `static/buddy.js` (its Task 6).
- Changing the Graph page.
- Saving the Ask history across visits.
- Voice, or any new dependency.

## Anti-goals (would make this a failure even if it works)

- A speech bubble, a chat log panel, or any box around Dot's words.
- Small icon buttons or text menus standing in for the blobs. The blobs must read as little characters, with faces.
- A blob whose job you cannot tell from its shape (and its name when you come near).
- Janky motion. Springs and transforms only (no animating `left`/`top` every frame), 60 fps on a normal laptop with 40 papers.
- Dot doing something you did not ask for. Above all, deleting without asking.
- Paper text leaving the machine. Only the local model is used.

## Constraints

- FastAPI, SQLite, PyMuPDF, plain HTML/JS/CSS. No new dependencies. No JS test runner exists; JS is checked in the app.
- Fonts and colours as now: Instrument Serif, Geist, Geist Mono, Doto; graphite plus #ffe347. The blob colours in the table above are added, and so is a similarity palette.
- Simple English in all UI text, no em dashes.
- The local model may reject `json_schema`. Use `primer._complete`, which falls back to `json_object`. The model may be slow or offline: everything except Ask's free-form answers and Dot's row names must work without it.
- Never use the sqlite3 CLI on `./data`.
- Reduced motion is respected everywhere. With it on:
  - The orbit stops, with blobs fixed on their ring.
  - Cards do not drift.
  - Letters appear without flying and the reply appears whole.
  - Helpers jump straight to their papers.
  - Blob shapes stay, without their loops.
- Do not edit `static/buddy.js`; its reading-mode changes are in flight in another session. The Library brings its own centre Dot (see "My calls").

## How it works (decided)

### Similarity: colours and shelf rows

A new `workbench/shelf.py` with `GET /library/map` returns `{groups: [{id, name, hue, paper_ids}], unread: [paper_ids]}`.

- **Grouping.**
  - Each indexed paper gets one vector: the normalised mean of its chunk vectors (`graph._chunks`, `graph._vec`, `graph._unit`).
  - The papers are grouped by k-means with cosine distance. k is `clamp(round(sqrt(n / 2)), 2, 8)`. The seeds are picked farthest-point from the paper with the most chunks, so the result is the same each time.
  - Fewer than 4 indexed papers means one group.
- **Hues.** Groups are sorted by size and given hues from a fixed palette of 8: blue, green, coral, violet, pink, teal, amber, sand, all tuned to sit on graphite. Unindexed papers are grey and sit on a last shelf, "Dot has not read these yet".
- **Row names.**
  - One model call gets a name of 2 to 4 words for each group, from the titles in it.
  - The names are cached in a new table `shelf_names(key TEXT PRIMARY KEY, name TEXT)`. The key is the sha1 of the group's sorted paper ids, so a name is reused until the group changes.
  - If the model fails, the name is the group's most common tag, else "Group N".
- **When embeddings are missing** (`GraphError`), every paper is grey and "By similarity" falls back to my themes, with Dot saying why.

### Ask: `POST /library/ask`

Body: `{question, history: [{q, a}] (at most 4)}`. Reply:

`{reply, action: {kind, paper_ids, date?, theme?}, papers: [{id, why}]}`

Steps:

1. **Candidates.** Up to 12 papers are picked:
   - `graph.search(s, question, 12)` when indexed;
   - plus FTS hits from `library.list_papers(q=…)`;
   - plus, for questions about state ("not opened", "no summary", "this week"), the papers matching that state from `list_papers`.
2. **Prompt.** The model gets each candidate as a short alias `P1…P12` with its title, status, talk date, summary state and themes. It also gets the history and the question, and is asked for JSON:

   `{reply, kind, papers: [{p: "P3", why}], date?, theme?}`

   `kind` is one of `find`, `summarize`, `set_date`, `add_theme`, `mark_done`, `export`, `delete`, `none`.
3. **Checks.** The server maps aliases back to ids and drops unknown ones. It rejects a `date` that does not parse, and caps `why` at about 12 words.
4. **Fallback.** If the model is offline, `kind` is `find`. The papers are the FTS and embedding hits, and the reply says "I can't reach the model, so here is what matches by title and meaning."

The server never acts. The page shows the reply, raises the papers, and runs the helpers.

### What helpers can do

All of these run in the page, through endpoints that exist today, one paper after another:

- `summarize`: `POST /papers/{id}/primer`. The helper stays on the paper while the stream counts up.
- `set_date`: `PATCH /papers/{id}` with `presentation_date`.
- `add_theme`: create the theme if it is new (`POST /themes`), then `PUT /papers/{id}/themes` with its existing themes plus this one.
- `mark_done`: `PATCH /papers/{id}` with `reflection_done: true`.
- `export`: one paper only; it opens `/papers/{id}/export/markdown`. For several papers, Dot asks you to pick one.
- `delete`: never runs straight away. The field shows "Delete *title*? This cannot be undone." with Yes and No as plain words in the field. Only Yes calls `DELETE /papers/{id}`, one paper at a time.

Before any job that changes something, the reply names what will change ("Setting the talk date of *X* to 12 Nov"). A job that fails leaves its paper with a small cross and Dot says which one.

### The page

- **Files.**
  - `renderLibrary` in `static/app.js` hands over to a new `static/library.js`, which holds the stage, the blobs, Ask, the shelf and the peek card. Styles go in a new `static/library.css`.
  - The peek card reuses the existing helpers in `app.js`: `themePicker`, `rowMenu`, `streamPrimer`, `enablePageDrop`, the add-paper flow, `fmtSpent` and relative dates. Move them or export them, but do not copy them.
  - The old table code is removed once the peek card covers it.
- **The ring.**
  - The 12 papers are chosen in this order: papers with a talk in the next 14 days and steps left; then papers whose summary failed; then papers by last opened. The rest are reached by Ask, Talks or Shelf.
  - When there are more than 12, Dot's count line adds "28 more on the shelf".
- **Motion.** Use the mockup's techniques:
  - orbit and drift with `translate3d` in one `requestAnimationFrame` loop;
  - the typist on a spring (k 0.14, damping 0.34);
  - the gooey join with the SVG filter (blur 7, alpha matrix 22 −10);
  - WAAPI for the letters flying in, the ding and the helper flights;
  - CSS for the blob shape loops.
- **Keyboard.**
  - Tab reaches Dot, the blobs in ring order, then the papers.
  - Enter on a paper peeks it, and Escape closes the peek, the field or the job.
  - The orbit pauses while a blob has focus.
  - Each blob has `aria-label` set to its name.

## My calls (not discussed with the user)

- **The centre Dot.** On the Library, Dot is the big smooth yellow blob with two oval eyes from the mockup, drawn by `library.js`. The floating buddy from `buddy.js` is hidden while the Library is open and comes back on other pages. This keeps the reading-mode work untouched.
- **The ring cap of 12** and its order, as above.
- **The helper jobs list** and "export one paper at a time".
- **Delete a theme** from the shelf row's label, with a confirm.
- **Settings opens the Settings page** instead of the small sheet shown in the mockup.
- **The empty state.**
  - Dot's line is "Hi, I am Dot. Drop your first PDF anywhere, or on me."
  - Only the Add paper and Settings blobs are out, and Add paper bounces.
  - Shelf mode is not offered until there is a paper.
- **The similarity method:** mean chunk vector, deterministic k-means, and k from library size.
- **Ask history** lasts only for the visit.
- **Dot's other messages on the Library.** While the Library is open, `library.js` wraps `buddy.say` and `buddy.busy`, without editing `buddy.js`, and restores them on leaving. Every message becomes Dot's plain line above the centre Dot: the model warnings, the add-paper messages, summary ready or failed, Deleted, Reflection done. Any actions in a message become underlined words in that line. Busy shows as Dot's thinking eyes. A message that arrives while the Ask field is open still shows above Dot; the field is below Dot, so they do not clash.
- **State questions reach every match.** When the question is about state ("not opened", "no summary", "this week"), the candidates are every paper in that state, up to 40, not 12.
- **Summaries never overwrite.** `summarize` skips papers whose summary is ready or being made, and Dot says how many it skipped.
- **Jobs run one after another in the page.** If you leave the Library, the summary being made goes on in the background as now, and the rest of the queue stops. Dot says "Keep this page open while I work" when a queue has more than one summary.
- **Enter in the Shelf pill** switches to Bubble mode, opens the Ask field there, and sends the question.
- **Branch.** This work stays on `ui-readability` next to the reading-mode work. It never edits `buddy.js` or `style.css`: the Library's styles are all in `library.css`, and only the Library part of `app.js` changes.

## Left to the builder

- Exact durations and easing, within the mockup's feel.
- The similarity palette values.
- Where the peek card sits on small screens. The Library must still work at 1024px wide.
- Prompt wording.
