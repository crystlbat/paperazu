# Jarvis pipeline: gather → prune → steering data → steered run that keeps learning

Spec: the user's stated vision. A "Jarvis" gathers facts on dory or Unsloth. A strict checker prunes them. Steering data is built from the clean facts, and a steered run follows that keeps learning. See memory `jarvis-pipeline-vision`.

## Global Constraints

- **Small and plain.** Follow the code style already in `workbench/`: short docstrings that say why, one-line comments only for a why the code can't show, no new abstraction layers, no new dependencies. Reuse the existing helpers (`char.add_memory`, `char._ask`, `char._start`, `db.connect`, `steer.fit`, `steer.rfm`).
- **One model in memory at a time.** Never load two engines at once. `llm.ensure(s, model)` already swaps engines (dory / Unsloth / `llm.STEER`). Every stage change goes through it.
- **Tests never touch a real model or the network.** `tests/conftest.py` already blocks the network. Patch `jobs.complete`, `steer.states`, `steer.generate` and `llm.ensure` as the existing tests do.
- **The real DB is not touched.** Tests use the test DB that the fixtures give.
- **Run the whole suite** with `.venv/bin/python -m pytest -q` from the worktree root. It must stay green (441 passed before this plan).
- **Commits.** One commit per task, and the message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Task 1: Per-claim checker (prune)

**Files:** `workbench/char.py` (inside `reflect`, plus one new helper), `tests/test_char.py`.

After `reflect` gets the model's `note` from the snippets (`lines`), and **before** it saves the note, prune it claim by claim:

1. Split the note into sentences on `(?<=[.!?])\s+`. Ignore sentences under 3 words.
2. A sentence is **supported by exact check** (no model) when at least `CLAIM_OVERLAP = 0.6` of its content words appear in the snippets' text. Content words: lowercase words of 4 or more letters, minus a small stop list (`this, that, with, from, their, they, them, have, been, were, which, what, when, where, also, into, than, then, about, after, before, would, could, should`). A sentence with no content words counts as supported.
3. A sentence the exact check doesn't support goes to **one model call for all such sentences together**, through `char._ask`. Ask it to reply with one line per numbered sentence, `SUPPORTED` or `UNSUPPORTED`, judged only against the snippets. Parse that with the regex `(?im)^\D*?(\d+)\W+(SUPPORTED|UNSUPPORTED)\b`. A sentence the model gives no verdict for, or an empty reply, counts as **unsupported**: the checker is strict.
4. The kept note is the supported sentences joined by a space, in their original order.
   - If at least one sentence is kept, the note saved is the kept text.
   - If none is kept, write the marker `add_memory(f"Reflection: {topic}"[:80], "(nothing supported)", source="sheet")`, call `_engine("reflect", "skipped", f"{topic}: no claim in it held up against its sources")`, and return `{"done": False, "topic": topic, "note": "", "left": len(todo) - 1, "pruned": True}`. This is the same shape as the existing "(nothing found)" path.
5. Record a sheet row `Claims: <saved note id>`, written right after the note is saved: `json.dumps({"kept": [...], "dropped": [...]})`. Lists hold sentences as strings. In the "none kept" case, record `Claims: 0` with the dropped list and an empty kept list, so the dropped claims are still kept as negatives.
6. Add `"Claims: %"` to the sheet-title exclusion lists where `Ground: %` already appears in `char.py`. Those are the bookkeeping filters in the memory list around line 655 and in `harness.stale`'s bookkeeping list, if `Ground` is there. Claims rows must not count as knowledge or as "something new". Check each place `Ground: %` is excluded, and treat `Claims: %` the same way.
7. The existing Ground/Sources/intake code then runs on the pruned note, unchanged.

Put the checking in one helper, `def _claims(note: str, lines: list[str]) -> tuple[list[str], list[str]]`, which returns (kept, dropped). Give it a short docstring that says why it exists: a note is the model's summary, and a summary can add what no snippet says.

**Tests** (in `tests/test_char.py`, using that file's existing fixtures and patterns for `reflect` with a fake `websearch.search` and `jobs.complete`):
- A note of two sentences, where one is copied from the snippet and one invents something with no overlap, gives a model verdict of `UNSUPPORTED` for the invented one. The saved note holds only the copied sentence, and the `Claims:` row lists one kept and one dropped.
- A note where every sentence fails the exact check and the model replies with nothing saves no reflection note, writes the "(nothing supported)" marker, and returns `pruned: True`.
- `_claims` on a sentence fully copied from the snippets keeps it without calling the model. Assert with a `jobs.complete` fake that fails if called.

## Task 2: Steering data from clean facts

**Files:** `workbench/steer.py`, `tests/test_steer.py`.

1. `LEVELS = (0.0, 0.01, 0.02, 0.03)`. A live test showed 0.04 invents facts and 0.06 breaks. Update the comment.
2. `def facts() -> tuple[list[str], list[str]]` returns (kept, dropped) claim sentences from every `Claims: %` sheet row of the live persona (`id > char._start()`). Order is oldest first, and duplicates are removed.
3. `def truth_concept() -> str`: the "true about its world" concept.
   - Positives are kept facts.
   - Negatives are the dropped claims, plus one corrupted copy of each kept fact. The corruption swaps the fact's first word that is in `char.world_words()` for a different world word: the next one in sorted order, wrapping round. A fact with no world word gets no corrupted copy.
   - Each text is wrapped as `f"Note: {sentence}"`.
   - Return `""` when there are fewer than `MIN_FACTS = 12` kept facts, or fewer than 12 negatives.
   - The concept name is `"truth-" + sha1` of the sorted texts and labels, first 10 hex characters. Fit it only when its `.npz` doesn't exist yet, as `world_concept` does. Because the name hashes its data, new facts give a new name, and that is the refit.
4. `world_concept()` changes its contrast. Positives stay the same: the world prefix plus `GENERIC`. Negatives become the same `GENERIC` questions prefixed by the other worlds in `OTHER_WORLDS`, cycled one per question. `OTHER_WORLDS = ("You live in Middle-earth, among hobbits and elves. Answer as someone from there. ", "You live in the Star Wars galaxy, among Jedi and droids. Answer as someone from there. ", "You live at Hogwarts, among wizards and owls. Answer as someone from there. ", "You live in a medieval fantasy tavern town, among knights and bards. Answer as someone from there. ")`. That way the direction means this world, not "being in a story". Put a version tag in the hashed key, for example hash `"v2|" + pre`, so the old world vectors aren't reused.
5. `TRUTH_EPS = 0.02`: the fixed push for the truth concept, added beside the world concept. The world ε tops out at 0.03, so together they stay under 0.06.

**Tests** (in `tests/test_steer.py`, patching `steer.states` to return deterministic arrays so no model loads, and `char.world_words`):
- `facts()` reads kept and dropped from `Claims:` rows and removes duplicates.
- `truth_concept()` returns `""` under `MIN_FACTS`. With enough facts it calls `fit` with the expected positive and negative counts, the corrupted copy has its world word swapped, and the concept name changes when a new fact is added.
- `world_concept()`'s negatives use `OTHER_WORLDS` prefixes. Patch `fit` to capture its arguments.

## Task 3: Staged pipeline run with refit

**Files:** `workbench/settings.py`, `workbench/harness.py`, `workbench/train.py`, `tests/test_train.py`, `tests/test_harness.py`.

1. **In-memory settings override.**
   - `settings.OVERRIDE: dict[str, Any] = {}`, merged last in `get_all()`: `Settings(**{**read_env(), **db.get_settings(), **OVERRIDE})`.
   - The comment says it's for a pipeline stage: it is never written to the DB, so a crash can't leave a stage's engine behind.
2. **Harness steering with the truth concept.** In `harness.pick_steer`, when steering:
   - get `truth = steering.truth_concept()`;
   - in `cycle`, set `steering.ON[truth] = steering.TRUTH_EPS` beside the world concept when `truth` is non-empty and the world ε is above 0. Keep both out of the planner and judge calls, as now;
   - record `truth` in the cycle's `steer` dict and its `Steer` row (key `"truth"`).
   - `pick_steer` returns `(concept, eps, truth)`. Update its callers and the existing tests.
3. **Pipeline mode in `train`.**
   - Add `cfg` keys to `DEFAULTS`: `"gather": ""`, `"gather_steps": 4` and `"steer_steps": 4`. An empty `gather` means the normal run, exactly as before.
   - When `cfg["gather"]` is set, the run repeats rounds of: `gather_steps` steps with `settings.OVERRIDE` set to `{"model_name": gather, "chat_model": gather, "planner_model": gather, "judge_model": gather}`; then **one fit step**; then `steer_steps` steps with the same four keys set to `llm.STEER`.
   - Each step is still one `_one_step()`. The pipeline only sets the override before it and clears it in a `finally`.
   - The fit step does three things, in order:
     1. `llm.ensure(settings.get_all(), llm.STEER)`, with the override for steer;
     2. `w = steer.world_concept()` and `t = steer.truth_concept()`;
     3. returns `("ok", f"fit: world {w or '-'} · truth {t or 'not enough facts yet'}")`.
   - Put the stage logic in one function, `def _pipeline_step(cfg, step) -> tuple[str, str]`. It works out the stage from `step % (gather_steps + 1 + steer_steps)` and prefixes the detail with `gather: `, `fit: ` (the fit detail already starts that way) or `steer: `. `_loop` calls it in place of `_one_step()` when `cfg["gather"]` is set. Each step's log entry also gets `"stage"`: gather, fit or steer.
   - Refit is automatic. Gathering writes new `Claims:` rows; the steered stage's own reflect notes go through the same per-claim checker, so their dropped claims become negatives too; the next round's fit sees new data under a new hash, and fits a new truth concept.
   - `settings.OVERRIDE` is cleared at the end of the run, in `_loop`'s exit path, whatever the outcome.
   - The `gather` value must be a model name. Validate in `start`: if `gather` is non-empty and equals `llm.STEER`, raise `ValueError("gather on a server engine (dory or an Unsloth model), not the steer engine")`.

**Tests:**
- `test_train.py`: with `_one_step` patched to record `settings.get_all().model_name` and to return `("ok", "x")`, and `llm.ensure`, `steer.world_concept` and `steer.truth_concept` patched, a run with `{"gather": "dory", "gather_steps": 2, "steer_steps": 1, "max_steps": 8}` runs this stage sequence: gather, gather, fit, steer, gather, gather, fit, steer. The recorded models are dory for gather steps and `llm.STEER` for steer steps. `settings.OVERRIDE` is empty after the run. `start` refuses `gather = llm.STEER`.
- `test_harness.py`: update the existing steering test for the 3-tuple. Add one where `truth_concept` returns `"truth-x"`, with the world ε above 0. The character's steps then see `steer.ON == {"world-x": eps, "truth-x": 0.02}`, and the planner and judge see `{}`.
