---
target: the PDF reader, Dot the companion
total_score: 20
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
target_identity: "file:/Users/bibintony/Desktop/paperazu/static/reader.js"
target_fingerprint: "sha256:2fe650ba845f8a019e630bf0a17b161db1a56a25ac2d1a6859eb3d467593582e"
target_path: /Users/bibintony/Desktop/paperazu/static/reader.js
timestamp: 2026-11-08T03-41-36Z
slug: static-reader-js
---
Method: dual-agent (A: fc147c8d-b624-4c60-8d32-c18141c9ec5a · B: 2e4572e4-0356-4f4c-9bf9-bbea95b24e87)

# Dot on the paper

Target: the reader at `static/reader.js`, with Dot in `static/buddy.js` and the board in `static/canvas.js`. Live page: `http://127.0.0.1:8765/#read/fbbe9ce79bbd`. The funda under test: you drag Dot out of its home corner, and from then on Dot shadows you and works on the page you are reading.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | While Dot is a lens, the board says "Nothing here yet." The outline of the line then disappears. |
| 2 | Match System / Real World | 3 | The grown face and named moons feel like a buddy. "Tag along," "Proactive," "Lens," and "Guide" are lab names, and the result is a card stack. |
| 3 | User Control and Freedom | 2 | Ring Back is labeled "Send me home" and ends shadowing (`reader.js:1257`, `reader.js:1374`). |
| 4 | Consistency and Standards | 2 | Home is an unlabeled fan. A paragraph is a labeled ring. Back means "go home" on the ring and "cancel" on the pill. |
| 5 | Error Prevention | 2 | Arrow keys turn the page outside a field (`reader.js:1622`). Ask sends the page number and drops the outlined passage (`canvas.js:529`). |
| 6 | Recognition Rather Than Recall | 2 | Home names appear only on hover (`style.css:743`). The pull-out sentence is stored away after one show (`reader.js:143`). |
| 7 | Flexibility and Efficiency | 2 | The loop is drag, click, pick 1 of 7, type. No key puts Dot on the paragraph you are reading. |
| 8 | Aesthetic and Minimalist Design | 2 | One question turns the paper into a side column beside an empty dotted board. The home halo stays on. |
| 9 | Error Recovery | 2 | Getting the buddy back means dragging it out again. The card × is the only undo on the board. |
| 10 | Help and Documentation | 1 | The face is named "Reading buddy. Show the last tip." (`buddy.js:64`). The sentence that teaches the drag was not on screen. |
| **Total** | | **20/40** | **Acceptable** |

Cognitive load is high: 4 of 8 checklist items fail (single focus, one thing at a time, minimal choices, working memory). Decision points over the limit of 4: the home fan has 5 moons (`reader.js:124`), a paragraph ring has 7 (`reader.js:1259`), a selected-words ring has 6 (`reader.js:1260`). A click in the margin is 4, which is inside the limit.

## Design Specificity Verdict

**LLM assessment.** The gesture is authored for this product. A yellow face that grows, a ring of colored moons, a home circle you pull out of: a generic PDF chat sidebar would not ship that unchanged. The payoff would. After Ask, the screen is a side column of cards with page chips and the question on top. The paper is the smaller pane. That surface could belong to any PDF chat product. The funda dies in the handoff from "Dot is with me" to "here is a board."

**Deterministic scan.** `impeccable detect` on `static/index.html`, `static/reader.js`, `static/buddy.js`, `static/canvas.js`, and `static/app.js` exited 0 and still printed 2 advisory hits. `static/reader.js`, `static/buddy.js`, and `static/app.js` were clean.

- `repeating-stripes-gradient` at `static/index.html:0`. False positive. That file has no repeating gradient, and line 0 is not a source line. The snippet is the detector's own label.
- `bounce-easing` at `static/canvas.js:470`. The card pop uses `cubic-bezier(.3,.7,.2,1.2)`, so the overshoot is real. It is also the spring the companion is supposed to have. Flattening it to a generic ease-out would make Dot deader. Not a defect to fix.

The in-page detector ran. One console line: primary font Geist, 68% of text. A top banner read **OVERUSED FONT**. Geist is the specified UI face for this product, so that banner is a false positive against the committed type, not a restyle target.

**Visual overlays.** Injection succeeded on a fresh reader tab. The only detector overlay is that font banner. A Pick bar and a yellow box on the title were already there from an earlier live session. They are not detector marks.

## Overall Impression

Dragging Dot out can wake it. I watched the face leave the corner, pick up `awake`, and trail the pointer. Clicking a line grows Dot into a large face with named moons. That is the one moment the paper stays the hero.

The rest of the visit argues with that moment. On open, `buddy.toolsOn("click")` (`reader.js:140`) calls `showHome()` (`buddy.js:579`), so five colored moons are already fanned around a 42px face. The comment on that line says pull Dot out to come along. The call opens a toolbar. The sentence "Pull me out when you want me along" fires once, then `localStorage` swallows it (`reader.js:143`), and opening the fan hides the bubble (`buddy.js:496`).

Back on the paragraph ring calls `setAlong(false)` (`reader.js:1374`). The careful exit ends the relationship. The 168px home halo can stay glowing with nobody in it (`style.css:749`).

Ask is the valley. `canvas.ask` takes the selection and then posts only `{ question, page }` (`canvas.js:526`). The outlined words are dropped. The board slides in, says "Nothing here yet" while Dot is a lens, then lands a stack of cards. `redraw()` draws user-made links and then clears the outgoing thread layer (`canvas.js:345`). The session ended with a 0×0 thread SVG. The line you asked about was gone. At 800×700 the paper was off screen.

Peak-end: you wake a buddy, and you finish in an empty board.

## What's Working

- Once Dot is out, a click on a line outlines it and the actions appear on the page, with their names visible. That is the right idea for a buddy inside the PDF.
- Ask changes Dot's body into a lens. The shape change is legible status.
- Steps and Notes are chips, drawers closed. Before the fan and the board, the slide can be the main thing.

## Priority Issues

**[P1] Home is a fan of tools, so the drag that starts shadowing is easy to miss**

- **Why it matters:** The funda is "pull the buddy out, then it shadows you." The shipped rest state is five icons waiting to be clicked: Tag along, Proactive, Lens, Guide, Canvas. Names live in hover tips at opacity 0 (`style.css:743`). A first visit can click around and never start the loop.
- **Fix:** At home, show only the face inside the circle, and the one sentence, until the first drag. Open the fan on right-click or a long press, which is what the reading-mode spec asked for. Keep the sentence available from the face, whose accessible name should be "Dot. Drag out to come along."
- **Suggested command:** `/impeccable shape`

**[P1] Back ends the shadow, and the empty home halo stays**

- **Why it matters:** Back is the control a careful person hits. On the ring it is "Send me home" (`reader.js:1257`) and it turns follow off (`reader.js:1374`). On the pill, Back cancels the question and Dot stays out. After a drag, the nest can remain `show awake`: a 168px halo with no Dot in it, including over the canvas. `show()` also sends Dot home whenever it talks while away (`buddy.js:154`), so a check-in yanks the buddy off the line.
- **Fix:** Back folds the moons and follow resumes. Hide the nest once Dot is out. Show it again only while dragging back into the corner. Let Dot speak from where it is standing.
- **Suggested command:** `/impeccable clarify`

**[P1] A successful Ask hands the session to an empty board**

- **Why it matters:** The paper stops being the place Dot lives. The outlined passage is not sent (`canvas.js:529`). The outline clears. No thread connects a card to the line, because `redraw()` only strokes links you drew yourself and wipes `gOut` (`canvas.js:349`). The yellow card restated the title. The useful sentence sat in a dark source card. On a narrow window the paper leaves.
- **Fix:** Send the outlined text with the question. Keep the outline until the source card is on screen, and draw the thread to that line. Below a width where both cannot fit, keep the paper full and let the board cover it as a drawer.
- **Suggested command:** `/impeccable layout`

**[P1] The loop is pointer-only, and the paper text is not in the accessibility tree**

- **Why it matters:** The face is a button named "Reading buddy. Show the last tip." (`buddy.js:64`). Enter at home toggles the nest. Paragraph actions start from a pointer click (`reader.js:1286`). The title that was clicked is `role="presentation"` and did not appear in the accessibility tree. A keyboard or screen-reader user cannot point Dot at a line.
- **Fix:** Name the face for the drag. Add a key that outlines the paragraph at the current reading position and opens the ring. Expose the PDF text layer as readable text.
- **Suggested command:** `/impeccable harden`

**[P2] Seven moons, hints on hover, pill parked off the line**

- **Why it matters:** The paragraph ring is Suggest, Ask, Note, Explain, Find, Add more, Back. Hints are `display: none` until hover. The Ask pill is 300px max, lands in the margin, and the placeholder "Ask about this part..." is cut off. "Write a note" sits flush against the zoom control.
- **Fix:** Paragraph actions are Suggest, Ask, Note, Add more, Back. Put Explain and Find on the selected-word ring only. Park the pill on the outline. Give the note button and the zoom their own rows.
- **Suggested command:** `/impeccable distill`

## Persona Red Flags

**Jordan (first visit).** The face has no name on screen. Five colored dots have no labels. Nothing says drag, because that sentence already fired once in this browser. The accessible name says a click shows a tip. The blue moon that would start follow is "Tag along," visible only on hover. Jordan can leave believing Dot is a cluster of buttons in the corner.

**Alex (in a hurry).** Getting a question onto one line is: drag, wait for the ring, choose among seven, type in a clipped pill, then watch the paper shrink into a board whose top card repeats the title. Arrow Left and Right change pages the whole time. The faster path, the Tag along moon, is unlabeled until hover. Follow also pauses while the pointer is on the face (`buddy.js:549`), so grabbing Dot again makes it stick.

**Sam (keyboard and screen reader).** The face button says "Reading buddy. Show the last tip." Home menuitems help only if you already know to tab into a fan. There is no key for "this paragraph." PDF spans use `role="presentation"`. The thread SVG is `aria-hidden` and was empty. The step tip lives in a bubble with `hidden`, while the steps drawer is `visibility: hidden` off the left edge and still exposes "Deck card" to the tree.

## Minor Observations

- The home fan and the paragraph ring are two visual languages for one character.
- Canvas zoom reads as part of "Write a note" because the controls touch.
- There is no PRODUCT.md. `/impeccable init` would lock this funda (drag out of home, then shadow and act on the paper) so later passes stop drifting back toward a toolbar.
- The design review drove the live reader, including an 800×700 window. I checked the cited lines in `reader.js`, `buddy.js`, `canvas.js`, and `style.css` against that account. I did not repeat the drag myself.

## Questions to Consider

- If a student never dragged anything, would they still describe Dot as a buddy who lives in the paper, or as the cluster in the corner?
- The ring is the only moment the paper stays the hero. Why does a successful Ask give the rest of the session to an empty board?
- Back is the control a careful person hits. Why is that the control that ends the relationship?
