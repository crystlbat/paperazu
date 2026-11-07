# Paper mode and Dot's canvas

Date: 2026-11-07. Status: approved in chat ("all of that please"), 2026-11-07.

## Why

The reader today has three fixed columns: the steps rail, the paper, and the notebook (Steps and Note tabs). The user finds this "clanky and static". What they want is a paper-aware companion that comes along while they read: the paper is the main thing, Dot does the AI work right on the paper, and everything else does its part and then shrinks back.

Two live sketches in `.superpowers/brainstorm/24622-1794092239/content/` are the agreed picture. `flow-v5.html`: no text box on screen; Dot pulls the canvas open; Dot runs down the page; the paragraphs that answer light up, lift off the page and shrink into one-line cards on a canvas beside the paper, each tied by a thread to its lines; the answer is built from those cards. `cursor-v12.html`: Dot follows your cursor; clicking a paragraph pops out five icons around Dot; Dot changes shape for each job (marker, magnifying glass, input pill) and changes back to its face after.

## Goals

1. **Paper mode is the default.** On opening a paper you see only the paper and Dot. The steps rail and the notebook are not on screen.
2. **Canvas mode opens beside the paper.** The canvas slides in from the right and the paper slides left to make room. Closing it tucks it away and returns to paper mode. One canvas per paper, saved, so it is as you left it next time.
3. **Dot follows you.** In paper mode Dot trails the cursor with a little lag and outlines the paragraph under it. Clicking a paragraph (a click, not a drag; dragging still selects text as now) stops Dot and pops out five icon buttons (Suggest highlights, Ask, Note, Add more, Back) in an arc around it, each with its name on hover:
   - **Suggest highlights** (marker icon). Dot does not highlight everything. It turns into a tilted marker and runs along the selection while the model picks only the important parts (key claims, definitions, results; usually 1 to 3 short spans, never whole paragraphs). Those spans get a stroke in Dot's own colour, a soft blue (`--dot-ink: #8ecbff`), so they never look like yours. Click a blue span for a small chip: **Keep** (it becomes your yellow highlight) or **Remove**.
   - **Ask** (magnifier icon). Dot stretches into an input pill right there. On Enter it turns into a magnifying glass and sweeps the page while the model works; then the sources fly to the canvas as in goal 4.
   - **Note** (pencil icon). Dot stretches into the input pill; the text becomes a note card on the canvas tied to the selection (goal 6).
   - **Add more** (down-arrow icon). Dot squashes and rides down the selection box, which springs down over the next paragraph while a wave of yellow dots pours through it, and a badge counts what was added ("+1", "+2"). The icons pop back out.
   - **Back** (return-arrow icon). Icons fold away; Dot follows again.
   **Your own highlighter is manual.** Select words with the mouse, exactly as now; the bar that shows Explain and Find gets **Highlight**, which marks exactly the selected words in yellow. Click a yellow span for **Remove**.
   After every job Dot changes back into its face and follows the cursor. Escape always cancels back to following. No permanent text box anywhere. Clicking where there is no paragraph (margin, empty canvas) offers only Ask, Note and Back, about the paper as a whole.
4. **Answers show their sources on the paper.** Dot glides down the page while the model works. When the answer arrives, its source paragraphs light up, a copy of each lifts off the page, flies to the canvas, and shrinks into a short gist card (a one-line summary plus "p. N"). A dotted thread links each card to its paragraph. The answer card appears and is threaded to its source cards.
5. **Follow-ups start from what you click.** Click an answer or source card, and Dot stretches into the input on that card. The question and reply become a new answer card that branches off it with a thread. The card you clicked, and the chain of cards above it, are the context the model gets.
6. **Your notes live on the canvas, and Dot works inside them.** A note is a small running page tied to the lines it was made from. You keep adding to it: click the note and Dot stretches into the input on it. Plain text is added as your line. A question, or a request such as "explain this formula", is answered by Dot right inside the note, under your line, in Dot's style. Dot gets the note's selected area as text and as a picture (so formulas read right, as Explain does now), plus the earlier lines of the note. Example: select equation (1), Note, type "explain this formula", and the explanation appears in the note. Notes can also be made with no selection by double-clicking empty canvas. Drag cards to move them. Drag from a card's edge handle onto another card to connect them. Put a card away with the small x on it (Dot swallows it); delete for good from its right-click menu.
7. **The canvas and the paper talk to each other.** Hover a card with a source and its paragraph lights up on the page. Click it and the paper turns to that page and scrolls there. A source on another page shows the thread ending at the canvas edge with "p. N".
8. **Steps and notes still exist, smaller.** They become chips (Steps 0/10, Notes) in the reader's top bar. Clicking one opens that panel as a drawer over the side of the paper; it closes when you click outside or press Escape. Nothing about how step notes are stored changes.

## Non-goals

- The Library screen redesign "centred around the bot". The user wants it, but it is a separate project, designed after this one ships.
- Voice. Still waiting on a go-ahead for any new dependency.
- Moving existing margin notes (marks) or step notes onto the canvas. They stay where they are and keep working (drag Dot onto the page to trace one). New notes go to the canvas. (A later project could import the old ones.)
- A whole-paper "map" on the canvas made up front by the model. The user's phrase "after the training and research" is read as: the model already has the paper as context. No training code; Unsloth on a Mac only runs models.

## Anti-goals (would make this a failure even if it works)

- A chat log. Follow-ups must be cards on the canvas, not a scrolling conversation panel.
- A permanent text box anywhere.
- Answers with no visible tie to the paper. If the model names no sources, the answer card says so plainly ("No exact lines found") instead of inventing threads.
- Motion that slows reading down: all of it must be skippable (click to finish) and must respect reduced motion (cards just appear, threads just draw).
- The paper text leaving the machine. Everything goes to the local model only.

## Constraints

- FastAPI, SQLite, PyMuPDF, plain HTML/JS/CSS, PDF.js 3.11.174. No new dependencies without asking.
- Fonts and colours as now: Instrument Serif, Geist, Geist Mono, Doto; graphite plus #ffe347. One addition the user asked for: Dot's suggested highlights use a second colour, soft blue #8ecbff (my pick of the shade).
- Simple English in all UI text, no em dashes.
- The local model may be text-only or may reject `json_schema`; use the existing fallbacks (`primer._complete` falls back to `json_object`; `llm._answer` retries without the picture).
- Reduced motion respected everywhere.

## How it works (decided)

### Finding sources

A new endpoint answers a question with sources: `POST /papers/{id}/canvas/ask` with `{question, page, from_card?}`.

The server builds a numbered list of paragraphs. A new `marks.paragraphs(paper_id, page)` returns `[(rect, text)]` using the same grouping as `marks.blocks()` (refactor so both share it). Ids like `p3-b7` exist only inside one ask: they are the index in that list, used in the prompt and mapped straight back to page and rect on the server. Ids are never stored; cards store page and rect. The pages used are the page you are on, plus up to 2 pages picked by a new `graph.pages_for(s, paper_id, question)` that ranks only this paper's chunks. If the paper is not indexed or the embedding model is missing (`GraphError`), it falls back to the pages next to the current one, within the budget `llm.paper_text` uses. It asks the model for JSON: `{answer, sources: [{block: "p3-b7", gist}]}`, gist being at most about 12 words. The server checks every block id exists, drops the ones that do not, and returns each source with its page and rect in PDF points, ready for the page to light up.

If `from_card` is given, the prompt includes that card's text and the chain of cards it branches from (up to 6), so follow-ups have context.

Failures (my call): if the JSON does not parse, ask once more as `export.place` does; if it still fails, fall back to a plain `llm.ask` answer, saved as an answer card that says "No exact lines found". Sources with unknown ids are dropped and the rest kept. If the model cannot be reached at all, nothing is saved and Dot says the error in its bubble.

My call: answer length stays at the current "at most 6 short sentences"; at most 4 sources per answer.

### Storage

New tables, both with `ON DELETE CASCADE` on the paper:

- `canvas_cards`: id, paper_id, kind (`answer`, `source`, `note`), question (for answers: your words, shown as the card's first line), text (answers and sources), entries (notes: JSON list of `{who: "me"|"dot", text}`), x, y, w, page (nullable), rect x0..y1 (nullable; for a note, the union of its selected paragraphs), parent (nullable card id), created_at.
- `highlights`: id, paper_id, page, kind (`me` or `dot`), text (the exact words), rects (JSON list of line rects in PDF points, one per line the words cover). `me` is drawn yellow, `dot` blue. Manual highlights send the rects of the browser selection converted to PDF points. Dot's suggestions: the model returns exact quotes from the selected paragraphs (JSON `{"quotes": [str]}`, at most 3, each at most about 25 words); the server keeps only quotes found word for word with PyMuPDF `page.search_for(quote, clip=selection)` and stores their line rects.
- `canvas_links`: id, paper_id, from_card, to_card. Only for links you draw yourself.

Threads from `parent` and from `canvas_links` are both drawn, in different styles. A source card's parent is its answer card. A follow-up is one answer card whose parent is the card you tapped. Deleting a card deletes its links; cards whose parent it was keep living with parent set to empty (my call).

Card positions are canvas coordinates in CSS pixels. REST: `GET /papers/{id}/canvas`, `POST/PUT/DELETE /papers/{id}/canvas/cards[/{cid}]`, `POST/DELETE /papers/{id}/canvas/links[/{lid}]`, `POST /papers/{id}/canvas/cards/{cid}/say` (add a line to a note; if it is a question, Dot's reply is added too and returned), `GET/POST/DELETE /papers/{id}/highlights[/{hid}]`, `PUT /papers/{id}/highlights/{hid}` (`{kind: "me"}` to keep a suggestion), `POST /papers/{id}/highlights/suggest` (`{page, rect}` → the new `dot` highlights). The ask endpoint saves the cards it makes and returns them.

The Markdown export gains a "Canvas" section: notes and answers in the order they were made, each answer with its question and its sources as "p. N", each note with its lines, Dot's lines marked "Dot:".

### Placing cards

The canvas is a plain HTML layer with an SVG layer for threads, panned by dragging empty space, zoom is out of scope for now. New cards from an ask land in a free column near the top of the visible area: source cards first, then the answer card below them; follow-up cards land just below and to the right of the card they branch from. The builder picks the exact layout rule; cards must not overlap on landing.

### The reader shell

`renderReader` changes from three columns to: top bar (title, chips for Steps and Notes, Canvas toggle, Hide paper, Export), the paper, and the canvas panel (closed by default). The steps rail and the notebook move into drawers opened by the chips. Existing features keep working: guided reading (Map), Lens, Proactive and the reading tracker, Explain, margin notes, circle to search, Self-test hiding the paper. Self-test hides the canvas too, since the answers would give it away (my call).

My call: the canvas opens in three ways: Dot's menu gets a "Canvas" item; asking a question opens it (Dot pulls it open like a curtain, as in the sketch); and a small tab on the right edge of the paper opens it by hand. Whether the canvas is open is remembered per paper.

### Dot on the reader: follow, options, shapes

`buddy.js` gets:
- `follow(on)`: trail the cursor (lerp each frame, offset just below-right of the pointer). Off during drags, text selection, Lens, the pen, open inputs, and when the pointer leaves the reader. Reduced motion: Dot does not follow; it appears at the click instead.
- `options({ x, y, items }) → Promise<key|null>`: the arc of icon buttons around Dot (icons are inline SVG; names shown on hover and as `aria-label`). Keyboard: arrow keys move between icons, Enter picks, Escape closes.
- `shape(name)`: `face` (default), `marker`, `lens`, `squash`, `pill`. CSS classes on the Dot root, with springy transitions, as in `cursor-v12.html`.
- `prompt({ x, y, placeholder }) → Promise<string|null>`: Dot becomes the input pill at that spot. Enter sends. There is always a visible way back: a Back button (return-arrow icon) at the end of the pill, a click anywhere outside it, or Escape; all three cancel and Dot changes back to its face and follows again.

The tools menu (Lens, Map, Proactive, Clear trail, Canvas) opens on right-click or long press on Dot on the reader (my call); on every other screen a click still opens it as now.

Questions vs plain lines in a note (my call): a line is sent to Dot when it ends with "?", starts with a verb such as explain, summarize, compare, define, why, how, what (case-insensitive), or starts with "@ai" as margin notes do now. Everything else is kept as your own line. A small "Ask Dot" hint shows in the pill while typing a line that will be sent, so it is never a surprise.

The note's Dot replies use a new `llm.note_reply(s, lines, boxed_text, image, title, pages, page)`, built like `ask_box` (picture of the area, retry without it on a text-only model).

### Motion

While the model works: Dot glides down the visible page with the `ctx-glow` scan from the existing code. When the answer arrives: for each source, light the paragraph (existing `dot-read` style), clone its text-layer spans into a floating box, animate to the card's landing spot while shrinking, swap to the gist card, draw the thread. Click anywhere to skip to the end state.

Opening and notes (cursor-v12.html). The canvas opens as a circle growing out of Dot (a clip-path reveal centred on Dot), with two yellow rings rippling out and a wave of lit grid dots running across the canvas; Dot bounces. Closing the canvas shrinks the circle back into Dot. New notes unroll out of Dot from left to right and type themselves in with a blinking yellow caret. Threads draw themselves from the paper to the card. When Dot answers inside a note, its small face appears under your line with three hopping dots, then the reply types in word by word. Hovering a card tilts it slightly toward the pointer and lifts it, and a spark runs along its threads from the paper to the card. Spat-out cards fly on an arc and wobble as they land.

Closing things feeds Dot (cursor-v12.html). Closing a card (its x) or closing the canvas crumbles each card into dots in its own colours; the card squashes flat and fades, and the dots fly on curved, staggered paths into Dot, which swells open while they arrive, then bounces as it swallows. Closing the canvas keeps the cards: when it opens again Dot bounces and spits them back out to where they were. My call: a card's x only puts the card away (it comes back with the canvas); deleting for good is a separate "Delete" in the card's right-click menu, with the same animation. Reduced motion: cards just fade.

## Left to the builder

- Exact card sizes, thread curve shape, and the landing-layout rule.
- How the canvas panel width is set (fixed fraction or draggable splitter; the existing `splitter()` may be reused).
- How threads to sources on other pages are drawn. The viewer shows one page at a time, so threads are drawn only to sources on the page shown; others end at the canvas edge with "p. N". Threads are recomputed on page change, zoom and scroll.
- Test shape, as long as the ask endpoint, the block-id checking, and card/link CRUD have server tests in the style of `tests/test_marks.py`.
