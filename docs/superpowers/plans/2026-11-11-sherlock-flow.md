# Sherlock flow: rules that hatch creatures, put Dot to sleep, and reflect while asleep

Spec: the user's words (no separate spec file):
"try declaring sherlock from scratch, once declared we declare cases to keep track the way and when counter hits 10
spawn a creature called watson, and its job defined, and eva which will let the UI sleep. this is the best usecase and
a trigger to start researching while its sleeping so its learning about the world and settings like a reflection. build
a mechanism for that such that it works beautifully in harmony with small models."

The target conversation (works the same on the Dot page `#space` → `space.say`, and on `/char` → `char.say`):

1. `become sherlock` (persona; already works)
2. `create a variable called cases` (already works)
3. `when cases hits 10 spawn a creature called watson that lists the clues in the paper, and eva which will let the UI sleep`
4. the user says "cases" until the counter reaches 10 → Watson is hatched (a real creature), the page goes to sleep
   with Eva named as keeper, and while asleep the app researches the persona's world, one topic at a time, saving each
   as a memory. On waking, Dot tells what it learned.

## Global Constraints

- "Harmony with small models": the rule sentence is read by regex, never needing the model. Actions are deterministic
  Python. The model is used only for (a) the normal chat reply and (b) one short call per reflection, which must have a
  no-model fallback.
- Python 3, FastAPI, SQLite. Tests: `.venv/bin/python -m pytest -q` from the repo root (254 pass before this work; all
  must still pass). JS check: `node --check static/space.js`.
- DO NOT COMMIT anything. Do not stash, reset, or switch branches. The working tree has many uncommitted changes from
  other sessions; leave them.
- Other sessions edit `static/space.js`, `static/space.css` and `workbench/char.py` at the same time. Make small,
  surgical edits with the Edit tool; re-read the exact lines right before editing; never rewrite or reformat a file.
- Never touch `static/creatures.css` or the `drawBench` function in `static/creatures.js`.
- Never run against the real database `data/workbench.db` or the real model. Tests use the temp DB fixtures already in
  `tests/test_space.py` / `tests/test_char.py` and mock `jobs.complete` and `websearch.search`.
- Code style of the repo: compact, one-line docstrings/comments that say why, no new abstractions, no new dependencies,
  no new files except where a task says so. Smallest change that fully works.
- Do not dispatch subagents.

## Task 1: Rule actions `spawn` and `sleep` (engine + parsing)

Files: `workbench/space.py`, `workbench/char.py` (one small change in `say`), `tests/test_space.py`, `tests/test_char.py`.

Read first in `workbench/space.py`: `make`, `paper`, `ACTIONS`, `clean_var`, `_acting`, `_does`, `_plain`, `WHEN`,
`NAMED`, `create_creature`, `act`, `_act_one`, `say`. In `workbench/char.py`: the part of `say` that builds
`spawned_card` from `rules`.

### 1a. Two new actions in `ACTIONS`

Action functions have the signature `(arg: str, fired: dict | None = None) -> dict`; the dict's keys are merged into
the fired event; failures raise `RuntimeError`.

- `"spawn"`: `arg` is `"watson: lists the clues in the paper"` or just `"watson"`.
  Name = text before the first `:`, stripped of anything but word chars/hyphens/spaces, capitalised (`"Watson"`), max
  40 chars; empty name → `RuntimeError("That creature has no name.")`.
  Task = text after the `:`; when empty use `"Summarise the key findings of this paper in five short bullet points."`.
  If a row in `jobs` already has that name (case-insensitive) return `{"creature": jobs._job(row), "new": False}`.
  Otherwise create it exactly the way `create_creature` does (`jobs.create_job(jobs.JobIn(name=…, color=<count of jobs
  % 8>, output="doc", steps=[{"scope": "paper", "prompt": task[:4000]}]))`) and return `{"creature": job, "new": True}`.
  Share the make-or-find code with `create_creature` only if that is a small, obvious extraction; do not change what
  `create_creature` returns.
- `"sleep"`: `arg` is the keeper's name (`"eva"`) or `"dot"` when nobody was named. Returns
  `{"sleep": True, "keeper": "Eva"}` (capitalised; `""` when arg is `dot`). When a keeper is named, it is also a real
  creature: make or find it the same way as spawn, with the task
  `"Write a short reflection on what this paper teaches about its world and setting."`, and add `"keeper_job": job`.

### 1b. The rule sentence is read without the model

In `_acting`, in the block that reads the tail after the trigger (where `MAKEVAR` / `PAPERISH` are read), also read:

- a spawn: `spawn|hatch|summon|create|make|add|build` … `creature` … optional `called|named` … NAME, then an optional
  task introduced by `that|to|which|who|whose job is (to)|its job is (to)|and its job is (to)`. The task ends before
  the sleeper clause, a `.`/`;`, or the end. Words like "its job defined" (no real task) mean no task.
- a sleeper: `NAME which|who|that (will|can)? let(s)|put(s)|send(s)|make(s) (the)? ui|dot|app|you|it|screen|page (to)?
  (go to)? sleep` → keeper NAME; or with nobody named, `go(es) to sleep`, `put … to sleep`, `fall(s) asleep` → keeper
  `dot`.

These combine with each other (and with make/paper if present) into one compound action, in the order
spawn, sleep, make, paper: `act = "spawn+sleep"`, `act_arg = "watson: lists the clues in the paper | eva"`. A task must
not contain `|` (strip it). Raise the `act_arg` length cap from 60 to 200 in `clean_var` and in this block of `_acting`
(other blocks keep their own caps). `_does(text)` must return True for these tails too, so the held say is set.

"hits/reaches N" keeps today's meaning (`every N`).

"when the counter hits 10 …", "when counter hits 10 …", "when it hits 10 …" name no variable: the rule then belongs to
the newest `count` variable in `space_vars` (not a new variable called "hits", "counter" or "it"). If there is none,
make nothing.

### 1c. What the user sees

- In `act()` (after a rule's actions ran): if the event's `say` is empty and it has `creature` and/or `sleep`, set
  `say` deterministically so small models do not have to describe it:
  - creature new: `"{Name} is hatched."`; creature not new: `"{Name} is already here."`
  - sleep with keeper: `"{Keeper} is putting me to sleep. I will reflect while I rest."`; without:
    `"I am going to sleep. I will reflect while I rest."`
  - both: the two sentences joined by a space.
- `space.say`: when a fired event has `creature`, the response carries
  `"card": {"kind": "creature", "job": <creature>, "new": <new>}` (the page already draws this card kind).
- `char.say`: same card when a rule event has `creature` (extend the existing `spawned_card` expression; papers/web
  keep priority order: creature first, then opened paper, then web).

### 1d. Tests (add to the existing files, same fixtures and style; mock `jobs.complete` like the neighbours do)

`tests/test_space.py`:
- `space._plain` / `space._make` with the model down (`jobs.complete` raising `llm.ModelError`): the sentence in step 3
  above, after `create a variable called cases`, leaves ONE variable `cases` with `every == 10`,
  `act == "spawn+sleep"`, `act_arg == "watson: lists the clues in the paper | eva"`.
- the user's own loose wording, `"when counter hits 10 spawn a creature called watson , and its job defined and eva
  which will let the UI to sleep"`, after `create a variable called cases`: rule lands on `cases`,
  `act == "spawn+sleep"`, `act_arg == "watson | eva"`; no variable named hits/counter.
- full flow through `space.say`: persona not needed; create cases, add the rule, set the value to 9 in the DB, say
  "cases": the event has `creature` (name `Watson`, `new` True), `sleep` True, `keeper == "Eva"`; the response `card`
  is the creature card; `jobs` has rows named Watson and Eva; the reply starts with
  `"Watson is hatched. Eva is putting me to sleep. I will reflect while I rest."`.
  Firing again at 20 makes no second Watson (`new` False).
- "when cases hits 10 go to sleep": `act == "sleep"`, `act_arg == "dot"`, event `keeper == ""`, no creature made.
- the tool path is unharmed: `space.say("create a creature that finds similar papers")` still answers with the
  creature card from `create_creature`.

`tests/test_char.py`:
- the same flow through `char.say` (create cases, rule, value 9, say "cases") returns the creature card and an event
  with `sleep` True.

Report: full pytest summary line.

## Task 2: Reflection while asleep (`char.reflect`, route, memory in the Dot prompt)

Files: `workbench/char.py`, `workbench/main.py`, `workbench/space.py` (prompt only), `tests/test_char.py`,
`tests/test_space.py`.

Read first in `workbench/char.py`: `init_db`, `get_profile`, `add_memory`, `dispatch_job`, `all_notes`, and how `say`
puts the last memories into the prompt ("KNOWLEDGE SOURCES & ACCUMULATED MEMORY"). In `workbench/main.py`: the `/char`
routes. In `workbench/space.py`: `say` (the `known` string) and `variables`.

### 2a. `char.reflect(on_char: bool = False) -> dict`

One reflection per call (the page calls it repeatedly while asleep), cheap enough for a 2B model.

- Who: `on_char` True → `get_profile()["name"]`; False → the `name` of the newest `space_vars` row with
  `kind = 'persona'`, else `"Dot"`.
- Topics, in this order, de-duplicated case-insensitively, each a plain search string:
  1. `"{who} world and setting"`
  2. for each non-persona variable in `space.variables()`: `"{who} {variable name}"`
  3. for each creature (rows of `jobs`, oldest first): `"{who} {creature name}"`
  4. the titles of the 2 most recently opened papers (`papers` ordered like `space._last_paper` does), as they are.
  When `who` is `"Dot"`, drop the `"Dot "` prefix topics 1–3 would have and skip topic 1 (Dot has no world to look up).
- A topic is done when a `char_memories` row titled `f"Reflection: {topic}"[:80]` exists. Take the first topic not
  done. None left → return `{"done": True, "topic": "", "note": "", "left": 0}`.
- `websearch.search(settings.get_all(), topic)` → up to 4 results as `"- {title}: {snippet}"` lines. An exception or no
  results → return `{"done": False, "topic": topic, "note": "", "left": <topics not done>}` and save nothing.
- One model call: `jobs.complete(settings, [system, user], max_tokens=120)` with system
  `"You are {who}, resting. In two short sentences, note what is worth remembering about the topic from these snippets. Plain text, no lists."`
  and user `f"Topic: {topic}\n\n{snippets}"`. If it raises (any exception) or returns nothing, the note is the first
  two snippet lines joined by a space, cut to 300 characters. Note is cut to 400 characters either way.
- Save with `add_memory(title, note, source="reflection")`; return
  `{"done": False, "topic": topic, "note": note, "left": <topics still not done after this one>}`.

### 2b. Route

`POST /char/reflect` in `workbench/main.py` next to the other `/char` routes, body `{"char": bool}` (optional, default
False) → `char.reflect(on_char=bool(body.get("char")))`.

### 2c. The Dot page remembers too

`char.say` already feeds the last memories into its prompt, so reflections reach `/char` for free (verify with a test,
change nothing if so). In `space.say`, add to the `known` string up to the 3 newest `char_memories` rows with
`source = 'reflection'` as `"\nWhile asleep you learned: {content}"`. The table may not exist (tests of space alone do
not create it): read it through a tiny helper that returns `[]` on `sqlite3.OperationalError`.

### 2d. Tests

`tests/test_char.py` (mock `websearch.search` and `jobs.complete`):
- with profile name set to Sherlock (`char.update_profile`), a `cases` variable (`space.add_var` or `space.say("count
  cases")` with the model mocked) and a creature named Watson: consecutive `char.reflect(on_char=True)` calls reflect
  on `"Sherlock world and setting"`, then `"Sherlock cases"`, then `"Sherlock Watson"`, each saving one memory with
  source `reflection`, then `{"done": True}`; `left` counts down.
- model raising → the note is made from the snippets and is still saved.
- search returning no results → nothing saved, `note == ""`, `done` False.
- after a reflection, the next `char.say(...)` prompt (captured by the mock) contains the note.
- `client.post("/char/reflect", json={"char": True})` returns 200 with a `topic`.

`tests/test_space.py`:
- with a `char_memories` reflection row present (call `char.init_db()` + `char.add_memory(..., source="reflection")`),
  the system prompt `space.say` sends contains `While asleep you learned:`; without the table, `space.say` still works.

Report: full pytest summary line.

## Task 3: Character sheet, the template every character fills (backend)

The user asked: "make the dot morph to whoever the character is, in the dot way; come up with a clear mechanics or
template that they need to fill at character creation", for small models. The mechanic: a character is a SHEET of fixed
slots. Creation fills the cheap slots; the rest are filled one at a time while Dot sleeps (Task 4).

Files: `workbench/space.py`, `workbench/char.py`, `tests/test_space.py`, `tests/test_char.py`.

Read first: `space.become`, `space.take_on`, `space.tint`, `space.recolor` (how a colour word becomes a hex), `COLORS`,
`LOOKS`, `space._act_one`; `char.become_persona`, `char.update_profile`, `char.get_profile`.

### 3a. The sheet is labelled lines inside the persona text (no schema change)

```
You are Sherlock Holmes.
Voice: Speak as … (how they talk)
Calls you: Watson
Catchphrase: Elementary.
World: Victorian London, 221B Baker Street, a consulting detective.
```

In `workbench/space.py`:
- `SLOTS = ("Voice", "Calls you", "Catchphrase", "World")`
- `sheet_of(text: str) -> dict[str, str]`: the slots found as `Label: value` lines (case-insensitive label, one line
  each). Text with no labels at all (an old persona) → `{"Voice": <the whole text on one line>}`.
- `sheet_text(who: str, sheet: dict[str, str]) -> str`: `"You are {who}."` then one `Label: value` line per NON-EMPTY
  slot in `SLOTS` order. Total cut to 900 characters.
Raise the 600 cap on `learned` (in `become`) to 900 where needed so a full sheet fits.

### 3b. Creation fills Voice, look and colour

- `space.become(who)`: keep its existing single model call (voice + what to wear) and its fallbacks exactly; the text
  it got becomes the `Voice` slot and `learned` is `sheet_text(who, {"Voice": voice})`. Then ONE more tiny call picks
  the colour: system `f"Pick the one colour that fits {who} best. Answer with one word from: {', '.join(COLORS)}."`,
  user = who, `max_tokens=8`; accept the first word of the reply that is in `COLORS`; if the call raises
  `llm.ModelError`/any exception or names no listed colour, no tint. With a colour, the returned dict also has
  `"tint": <hex, the same conversion recolor uses>` and `_act_one` paints it for `become` too (it already does for
  `recolor`: reuse `tint(f["var"], …)`).
- `char.become_persona(who)`: leave the Gideon fast-path untouched. In the general path keep its model call; store
  `persona = space.sheet_text(clean_who, {"Voice": <what the call returned or the fallback>})`. Keep look/tint logic.
- The page gets the sheet to show: the `set`/become event already carries `learned`; add `"sheet": sheet_of(learned)`
  with EVERY slot present (empty string when unfilled) to what `space.become` returns, and the same key on the `set`
  event `char.say` emits after `become_persona` (find where that event is built).

### 3c. Tests
- `sheet_of(sheet_text("Sherlock", {...}))` round-trips; unlabelled text → Voice only; empty slots are left out of the
  text.
- `space.become` with mocked search/model: `learned` starts with `You are`, has a `Voice:` line; colour reply
  `"Blue."` → `tint` set; colour reply `"dunno"` → no `tint` key; existing become tests still pass (update their mocks
  only as far as the extra colour call requires).
- `char.say("become sherlock holmes")` (mocked): profile persona contains `Voice:`; the event has `sheet` with all four
  slot keys.

Report: full pytest summary line.

## Task 4: Self-improvement loop while asleep (`char.rest`)

The user asked for "a self improvement loop … cleverly separated tasks which even the dumbest models can do, which when
combined make awesome stuff". One call = one tiny step. Three kinds of step, taken in turn:

- `reflect`: Task 2's `char.reflect` (learn a topic).
- `fill`: fill ONE empty sheet slot from what was learned.
- `practise`: check ONE recent reply against the voice; keep it or rewrite it as an example to speak from.

Files: `workbench/char.py`, `workbench/main.py`, `workbench/space.py` (prompt only), `tests/test_char.py`.

Read first: Task 2's `char.reflect` and its helpers, `char.add_memory`, `space.sheet_of` / `sheet_text` / `SLOTS`
(Task 3), `space.take_on`, `char.update_profile`, how `char.say` and `space.say` build their system prompts, the
`char_turns` and `space_turns` tables.

### 4a. `char.rest(on_char: bool = False, n: int = 0) -> dict`

Order of kinds for call `n`: `("reflect", "fill", "practise")` rotated left by `n % 3`. Try each kind in that order;
the first that has work does ONE step and returns. None has work → `{"done": True, "kind": "", "topic": "", "note": ""}`.
Every step returns `{"done": False, "kind": kind, "topic": <short label for the page>, "note": <one or two sentences>}`.

Where the character lives: `on_char` True → `char_profile` (name, persona); False → the newest `space_vars` persona row
(`name`, `learned`). No persona row on the Dot page → `fill` and `practise` have no work.

- `reflect`: call `reflect(on_char)`; it has work unless it returns `done` or an empty `note` (an empty note = search
  failed: treat as no work this call). Pass its topic/note through.
- `fill`: the first of `("World", "Calls you", "Catchphrase")` that is empty in `sheet_of(persona)` AND was not tried
  before (a `char_memories` row titled `f"Sheet: {who} {slot}"`). Context = the contents of the 4 newest
  `char_memories` rows with source `reflection`; none → no work. One call, `max_tokens=40`, system per slot:
  - World: `f"In one short sentence, where and when does {who} live and work? Use only the notes."`
  - Calls you: `f"What does {who} call the person they talk to? Answer with one to three words only."`
  - Catchphrase: `f"Give one short phrase {who} is known for saying. Answer with the phrase only."`
  user = the notes. Clean the answer: first line, strip quotes/trailing whitespace, max 120 chars (World), 30 (Calls
  you), 60 (Catchphrase). If the call raises or the answer is empty: save the memory row with content `""`… no: save
  NOTHING to the sheet, but still write the marker memory (content `"(could not tell)"`, source `"sheet"`) so the slot
  is not retried every night. On success write the slot into the sheet (`update_profile` keeping name/look/tint, or
  `space.take_on(var_id, new_text, look)` keeping its look) and save the marker memory with the value, source
  `"sheet"`. topic = `f"{who}'s {slot.lower()}"`, note = the value.
- `practise`: the newest assistant/dot turn of that page's chat (`char_turns` for on_char, else `space_turns`; look at
  the table schemas for the role value and text column) that has no `char_memories` row titled
  `f"Lesson: {page} turn {id}"` (`page` = `"char"` or `"space"`), skipping turns shorter than 20 characters and
  considering only the 3 newest turns. Step 1, one call, `max_tokens=4`: system
  `f"Voice: {voice}\nDoes the reply sound like {who}? Answer YES or NO."`, user = the reply. A reply starting with
  `y`/`Y` → keep: lesson content = the reply itself (cut to 200). Otherwise step 2, one call, `max_tokens=80`: system
  `f"Rewrite the reply the way {who} would say it. Voice: {voice}\nOne or two sentences. Only the rewritten reply."`,
  user = the reply; lesson content = the rewrite (cut to 200); if either call raises or the rewrite is empty, no
  lesson is saved and `practise` has no work this call. Save with `add_memory(title, content, source="lesson")`.
  topic = `"my voice"`, note = `f"Kept: {content}"` or `f"Better: {content}"`. `voice` = the sheet's Voice slot.

### 4b. Lessons steer the next replies

In both `char.say` and `space.say` system prompts add the 2 newest `lesson` memories as
`"\nSpeak like this example: {content}"`. Use/extend Task 2's guarded reader in `space.py` (table may not exist).
Check `char.say`'s existing memory section does not ALSO print them in a confusing way; if lessons already land in its
"KNOWLEDGE SOURCES" list, exclude sources `lesson` and `sheet` from that list.

### 4c. Route
`POST /char/rest` body `{"char": bool, "n": int}` → `char.rest(on_char=…, n=…)`. Keep `/char/reflect` as is.

### 4d. Tests (`tests/test_char.py`, model and search mocked; route the mock by words in the system prompt)
- rotation: with one topic to reflect on, an empty World slot and one long dot turn: `rest(True, 0)` → kind
  `reflect`; `rest(True, 1)` → `fill` (World now in `get_profile()["persona"]` as a `World:` line); `rest(True, 2)` →
  `practise`; a NO verdict saves the rewrite as a `lesson`; eventually `{"done": True}`.
- YES verdict keeps the reply as the lesson.
- fill with the model raising: sheet unchanged, marker saved, the slot is not tried again.
- after a lesson exists, the `char.say` system prompt contains `Speak like this example:`.
- the Dot page: with a persona var whose `learned` is a sheet and a reflection memory, `rest(False, 1)` fills World
  into that var's `learned`.
- `client.post("/char/rest", json={"char": True, "n": 0})` → 200.

Report: full pytest summary line.

### 4e. Curiosity drives the loop (adapt the existing Learn More approach)

The user: "the vision is self improvement, adapt the curiosity approaches we did before". The app already has a
`curiosity` mood (`char_vars`, 0..5), a `knowledge` accumulator (bumped by `add_memory`) and Learn More mode in
`char.say` (each answer ends with follow-up directions that become the next question). Read those first. The sleep
loop reuses the idea, split so a tiny model can do it:

- a fourth kind, `wonder`: order for call `n` is `("reflect", "wonder", "fill", "practise")` rotated left by `n % 4`
  (this replaces the 3-kind rotation in 4a; adjust the 4d rotation test to: n=0 reflect, n=1 wonder, n=2 fill,
  n=3 practise).
- `wonder` has work when the newest `reflection` memory has no follow-up yet (no `char_memories` row with source
  `"question"` whose content ends with `f"(from {reflection id})"`) and fewer than 3 questions are still unanswered.
  One call, `max_tokens=30`: system
  `"Read the note. Ask one short follow-up question that would teach you more. Only the question."`, user = the
  note. Clean: first line, max 100 chars, must end with `?` (add it). If the call raises or is empty, the question is
  `f"What else matters about {topic}?"` (topic = the reflection title without `"Reflection: "`). Save
  `add_memory(f"Question: {question}"[:80], f"{question} (from {id})", source="question")`, and raise curiosity:
  `UPDATE char_vars SET value = MIN(max_val, value + 0.5) WHERE name = 'curiosity'` (check the column names).
  topic = `"a question"`, note = the question.
- questions feed `reflect`: in `char.reflect`'s topic list, unanswered questions come FIRST (oldest first), as topics
  with the question text itself as the search string. A question is answered when its reflection exists (the same
  `Reflection: {topic}`[:80] title rule). So each night: learn → wonder → learn the answer → wonder again: compounding.
- Exclude source `question` from the memory lists printed into chat prompts (like `lesson` and `sheet`).
- `rest`'s return gains `"questions": [<unanswered question texts, newest first, max 3>]` on every call (also when
  done), so the page can offer them on waking.

Tests: reflect → wonder saves a question and raises curiosity; the next reflect's topic is that question; model
raising in wonder → the fallback question; never more than 3 unanswered questions.

## Task 5: The page hatches, sleeps, shows its reflecting, wakes, and shows the sheet (`static/space.js`)

Files: `static/space.js`; `static/space.css` only if a few lines are truly needed (append at the end, max ~12 lines).
Both are shared with another session: surgical edits, re-read lines right before each edit.

Read first: `doing(v)`, the chip text built from events (search for `e.made`), `showCard` (kinds `creature`, `job`,
`sleep`), `sleep(animate)`, the knock handler that wakes Dot, `send()` (where `r.card` / `opened` / `found` are shown,
and where a `set` event with `learned` is celebrated), `dress()`, `paint()`, `emerge(...)`, `ripple`, `mood`, and how
`api(...)` does a POST elsewhere in this file. `base` is `"/char"` on the character page.

Backend contract (built in Tasks 1–4):
- a rule's event may carry `creature` (job object with `.name`), `new` (bool), `sleep: true`, `keeper` (string, may be
  `""`). The creature card arrives as `r.card` (`kind: "creature"`); nothing to add for it.
- a variable's rule may have `act` parts `spawn` (arg `"watson: task"` or `"watson"`) and `sleep` (arg keeper or `dot`).
- a `set` event of a persona carries `sheet`: `{"Voice","Calls you","Catchphrase","World"}` → strings, `""` = not
  filled yet; it may also carry `tint`.
- `POST /char/rest` body `{char: base === "/char", n}` → `{done, kind, topic, note}`; kind is `reflect`, `fill` or
  `practise`.

Changes:
1. `doing(v)`: add `spawn: \`hatch ${name}\`` (name = arg before `:`) and
   `sleep: arg === "dot" ? "go to sleep and reflect" : \`let ${arg} put Dot to sleep, and reflect\``.
2. Event chip text: add ` · hatched ${e.creature.name}` and ` · asleep`, in the same chain as `e.made`, composing when
   both are present.
3. Character sheet: when a `set` event has `sheet` and there is no `r.card`, show
   `showCard({ kind: "job", title: \`${e.name}'s sheet\`, result: <one "Label: value" line per slot; an empty slot
   reads "Label: learns this while asleep">, status: "Character sheet" })`. If the event has `tint`, make sure Dot is
   repainted the way a recolor event does (the `e.tint` branch may already cover it). Check `showCard`'s `job` kind
   works on both pages (it may be guarded by `base === "/char"`); if not, make it work on the Dot page with the
   smallest change.
4. In `send()`, after the reply and cards are shown: if an event has `sleep`, wait about 1.2 s, call `sleep()`, then
   start the rest loop. A manual "shut down" (card kind `sleep`) and a reload while asleep must NOT start it: that
   sleep means the AI is off.
5. Rest loop: `n` = 0,1,2… at most 6 calls per sleep, strictly one at a time; before each call and after each response
   check the page is still asleep (`root.classList.contains("asleep")`), stop otherwise; stop on `done` or a failed
   request (catch it; never throw into the page). Keep what was done in a list `[{kind, topic, note}]`.
6. Reflecting must SHOW (the user: "when the dot or character is reflecting it should show"): while the loop runs the
   sleeping page visibly says what Dot is doing, and each finished step is visible:
   - a status line that stays readable while asleep (reuse an existing element/bubble of the page if one is still
     visible in `.asleep`; else add one small element + the few CSS lines): before a response
     `Reflecting…`; after each step, by kind: `Read about ${topic}`, `Learned ${topic}`, `Practised ${topic}`, followed
     by the note (cut to ~140 chars). It has `role="status"` so screen readers hear it.
   - the input placeholder reads `Asleep and reflecting. Knock on Dot three times`.
   - one soft `ripple(...)` per finished step (respect the page's reduced-motion flag `still` the way other code does).
   - when the loop ends while still asleep: status reads `Done reflecting. Knock three times to wake me.`
   - on waking the status element is hidden/cleared.
7. Waking (the three-knock handler): if the list is non-empty, the wake line is
   `I'm up! While I slept I worked on ${distinct topics joined with ", "}.` instead of the usual one, then
   `showCard({ kind: "job", title: "What I did asleep", result: <each "topic: note" as its own paragraph>, status: "Reflection" })`;
   then clear the list. `kind` may also be `wonder` (status text `Wondering: ${note}`); every `/char/rest` response has
   `questions` (array of strings): on waking, if the last response had any and the page has `renderLearnChips`, call
   it with them so the user can pick what to explore next (check it works on the Dot page; if it is /char only, show
   the chips only there). If a `fill` step ran, refresh the page state the way the page normally does after a reply so
   the new sheet is used (find the existing state refresh; do not add a new endpoint).
8. `buddy.sleep(true)` means "AI off everywhere": check in `static/buddy.js` (read only) that it does not block this
   page's own `api()` calls; if something does, say so in the report rather than changing `buddy.js`.

Verify: `node --check static/space.js`. Report what you could not verify without a browser.
