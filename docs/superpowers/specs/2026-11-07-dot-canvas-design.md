# Paper mode and Dot's canvas

Date: 2026-11-07. Status: draft for approval.

## Why

The reader today has three fixed columns: the steps rail, the paper, and the notebook (Steps and Note tabs). The user finds this "clanky and static". What they want is a paper-aware companion that comes along while they read: the paper is the main thing, Dot does the AI work right on the paper, and everything else does its part and then shrinks back.

The moving sketch in `.superpowers/brainstorm/` (flow-v5.html) is the agreed picture: no text box on screen; you tap Dot, a speech bubble grows out of it for your question; Dot runs down the page; the paragraphs that answer light up, lift off the page and shrink into one-line cards on a canvas beside the paper, each tied by a thread to its lines; the answer is built from those cards.

## Goals

1. **Paper mode is the default.** On opening a paper you see only the paper and Dot. The steps rail and the notebook are not on screen.
2. **Canvas mode opens beside the paper.** The canvas slides in from the right and the paper slides left to make room. Closing it tucks it away and returns to paper mode. One canvas per paper, saved, so it is as you left it next time.
3. **Asking goes through Dot.** No permanent text box. Tap Dot, a speech bubble grows from Dot, type, Enter. The bubble folds back into Dot.
4. **Answers show their sources on the paper.** Dot glides down the page while the model works. When the answer arrives, its source paragraphs light up, a copy of each lifts off the page, flies to the canvas, and shrinks into a short gist card (a one-line summary plus "p. N"). A dotted thread links each card to its paragraph. The answer card appears and is threaded to its source cards.
5. **Follow-ups start from what you tap.** Tap a card (answer, source, or your own note), and Dot's bubble opens on that card. The question and reply become a new card that branches off it with a thread. Tap Dot itself for a fresh question with no link. The card you tapped, and the chain of cards above it, are the context the model gets.
6. **Your notes live on the canvas.** Double-click empty canvas to write a note card. Drag cards to move them. Drag from a card's edge handle onto another card to connect them. Delete with a small x on the card.
7. **The canvas and the paper talk to each other.** Hover a card with a source and its paragraph lights up on the page. Click it and the paper turns to that page and scrolls there. A source on another page shows the thread ending at the canvas edge with "p. N".
8. **Steps and notes still exist, smaller.** They become chips (Steps 0/10, Notes) in the reader's top bar. Clicking one opens that panel as a drawer over the side of the paper; it closes when you click outside or press Escape. Nothing about how step notes are stored changes.

## Non-goals

- The Library screen redesign "centred around the bot". The user wants it, but it is a separate project, designed after this one ships.
- Voice. Still waiting on a go-ahead for any new dependency.
- Moving existing margin notes (marks) or step notes onto the canvas. They stay where they are. (A later project could import them.)
- A whole-paper "map" on the canvas made up front by the model. The user's phrase "after the training and research" is read as: the model already has the paper as context. No training code; Unsloth on a Mac only runs models.

## Anti-goals (would make this a failure even if it works)

- A chat log. Follow-ups must be cards on the canvas, not a scrolling conversation panel.
- A permanent text box anywhere.
- Answers with no visible tie to the paper. If the model names no sources, the answer card says so plainly ("No exact lines found") instead of inventing threads.
- Motion that slows reading down: all of it must be skippable (click to finish) and must respect reduced motion (cards just appear, threads just draw).
- The paper text leaving the machine. Everything goes to the local model only.

## Constraints

- FastAPI, SQLite, PyMuPDF, plain HTML/JS/CSS, PDF.js 3.11.174. No new dependencies without asking.
- Fonts and colours as now: Instrument Serif, Geist, Geist Mono, Doto; graphite plus #ffe347.
- Simple English in all UI text, no em dashes.
- The local model may be text-only or may reject `json_schema`; use the existing fallbacks (`primer._complete` falls back to `json_object`; `llm._answer` retries without the picture).
- Reduced motion respected everywhere.

## How it works (decided)

### Finding sources

A new endpoint answers a question with sources: `POST /papers/{id}/canvas/ask` with `{question, page, from_card?}`.

The server builds a numbered list of paragraphs. A new `marks.paragraphs(paper_id, page)` returns `[(rect, text)]` using the same grouping as `marks.blocks()` (refactor so both share it). Ids like `p3-b7` exist only inside one ask: they are the index in that list, used in the prompt and mapped straight back to page and rect on the server. Ids are never stored; cards store page and rect. The list comes from for a window of pages the page you are on, plus up to 2 pages picked by a new `graph.pages_for(s, paper_id, question)` that ranks only this paper's chunks. If the paper is not indexed or the embedding model is missing (`GraphError`), it falls back to the pages next to the current one, within the budget `llm.paper_text` uses. It asks the model for JSON: `{answer, sources: [{block: "p3-b7", gist}]}`, gist being at most about 12 words. The server checks every block id exists, drops the ones that do not, and returns each source with its page and rect in PDF points, ready for the page to light up.

If `from_card` is given, the prompt includes that card's text and the chain of cards it branches from (up to 6), so follow-ups have context.

Failures (my call): if the JSON does not parse, ask once more as `export.place` does; if it still fails, fall back to a plain `llm.ask` answer, saved as an answer card that says "No exact lines found". Sources with unknown ids are dropped and the rest kept. If the model cannot be reached at all, nothing is saved and Dot says the error in its bubble.

My call: answer length stays at the current "at most 6 short sentences"; at most 4 sources per answer.

### Storage

New tables, both with `ON DELETE CASCADE` on the paper:

- `canvas_cards`: id, paper_id, kind (`answer`, `source`, `note`), question (for answers: your words, shown as the card's first line), text, x, y, w, page (nullable), rect x0..y1 (nullable), parent (nullable card id), created_at.
- `canvas_links`: id, paper_id, from_card, to_card. Only for links you draw yourself.

Threads from `parent` and from `canvas_links` are both drawn, in different styles. A source card's parent is its answer card. A follow-up is one answer card whose parent is the card you tapped. Deleting a card deletes its links; cards whose parent it was keep living with parent set to empty (my call).

Card positions are canvas coordinates in CSS pixels. REST: `GET /papers/{id}/canvas`, `POST/PUT/DELETE /papers/{id}/canvas/cards[/{cid}]`, `POST/DELETE /papers/{id}/canvas/links[/{lid}]`. The ask endpoint saves the cards it makes and returns them.

The Markdown export gains a "Canvas" section: notes and answers in the order they were made, each answer with its question and its sources as "p. N".

### Placing cards

The canvas is a plain HTML layer with an SVG layer for threads, panned by dragging empty space, zoom is out of scope for now. New cards from an ask land in a free column near the top of the visible area: source cards first, then the answer card below them; follow-up cards land just below and to the right of the card they branch from. The builder picks the exact layout rule; cards must not overlap on landing.

### The reader shell

`renderReader` changes from three columns to: top bar (title, chips for Steps and Notes, Canvas toggle, Hide paper, Export), the paper, and the canvas panel (closed by default). The steps rail and the notebook move into drawers opened by the chips. Existing features keep working: guided reading (Map), Lens, Proactive and the reading tracker, Explain, margin notes, circle to search, Self-test hiding the paper. Self-test hides the canvas too, since the answers would give it away (my call).

My call: the canvas opens in three ways: Dot's menu gets a "Canvas" item; asking a question opens it (Dot pulls it open like a curtain, as in the sketch); and a small tab on the right edge of the paper opens it by hand. Whether the canvas is open is remembered per paper.

### Dot's bubble

`buddy.js` gets a small input bubble: `buddy.prompt({ x, y, placeholder }) → Promise<string|null>` that grows from Dot (or from a card when following up), Enter sends, Escape cancels. Tapping Dot (a click without a drag) while on the reader opens it. Today a click on Dot opens the tools menu. My call: on the reader, a tap opens the bubble, and a long press or right-click opens the tools menu; on every other screen a tap still opens the menu as now.

### Motion

While the model works: Dot glides down the visible page with the `ctx-glow` scan from the existing code. When the answer arrives: for each source, light the paragraph (existing `dot-read` style), clone its text-layer spans into a floating box, animate to the card's landing spot while shrinking, swap to the gist card, draw the thread. Click anywhere to skip to the end state.

## Left to the builder

- Exact card sizes, thread curve shape, and the landing-layout rule.
- How the canvas panel width is set (fixed fraction or draggable splitter; the existing `splitter()` may be reused).
- How threads to sources on other pages are drawn. The viewer shows one page at a time, so threads are drawn only to sources on the page shown; others end at the canvas edge with "p. N". Threads are recomputed on page change, zoom and scroll.
- Test shape, as long as the ask endpoint, the block-id checking, and card/link CRUD have server tests in the style of `tests/test_marks.py`.
