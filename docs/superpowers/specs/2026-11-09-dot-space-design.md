# Dot space: chat with Dot, steered by variables

## Why
A chat page where Dot is a living character, not a text box. While you talk, small rules count things in the
chat. Their values, and how those values change, steer what Dot says next. You can see all of it happen.

## What it is (v1)
- A new top-bar page, **Dot** (`#space`). *My call:* this is a page for now; opening it over a paper can come later.
- Dot sits in the middle with dotted rings around it. Each **variable** is an arc of beads on the inner ring.
  Each one has a readout: a dotted leader line, a dot-matrix number, and one line saying what it steers.
- The DB layer shows as dot stacks along the floor: papers, highlights, chat turns, variables, and cards.
  A stack grows when a row is written and lights up when it is read.
- **The chat response is a readable transcript under Dot.** The last few turns stay on screen, and older turns
  fade. A reply that a variable steered carries a coloured chip naming that rule.

## Variables (rules: no model, no face)
A variable has a `kind`, which sets how its value is measured on each user turn:
- `count`: adds the matches of a regex `pattern`. Examples: apples, `\?` for questions.
- `words`: the number of words this turn. Its delta from the last turn is kept.

Triggers, any of which may be set:
- `every` n plus `every_say`: each time the value crosses a multiple of n.
- `past` n plus `past_say`: once, when the value first goes past n.
- `drops` k plus `drops_say`: after the value falls k turns in a row.

The kinds and triggers live in one table in `workbench/space.py`, so a new way to steer means adding one entry.

## A turn, in order
1. **Guardrails / measure:** every variable updates from the user text, and the triggers that fired are collected.
2. **Steer:** each fired trigger's `say` becomes an instruction in the system prompt ("Begin your reply with: …").
3. **Model reply:** one call. The prompt holds the library (paper titles plus table counts) as the data source,
   along with the last turns.
4. **Check and correct:** if a required phrase is missing from the reply, it is put in front. This is the
   reinforcement step, so the test always passes, even with a small model.
5. Save both turns and the variable values. Return the reply, the events, the variables, and the table counts.

## Making variables by chat
When the text asks to count, track, or watch something, one JSON model call turns it into variables. A list is
returned, so one message can make several. Plain chat skips that call.

## Test case
"count apples in our chat; every 3rd say beep boop, injection works; past 10 say test successful".
This makes `apples` (count, `\bapples?\b`, every 3, past 10). The 3rd apple brings "beep boop, injection works",
and the 11th brings "test successful".

## Non-goals (v1)
- Model-using creatures inside the space. The existing Creatures page stays.
- Reading paper text into the chat; only titles and counts are used.
- Editing variables by hand: they are made by chat and removed with ×.

## Constraints
- One model call per turn, plus at most one more when variables are being made.
- Do not touch `static/creatures.css` or `drawBench` in `static/creatures.js`.
