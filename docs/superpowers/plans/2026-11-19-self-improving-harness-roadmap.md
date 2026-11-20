# Roadmap: what "Harnesses That Improve Themselves" means for the /char harness

Source: D. Shah and N. Kathrotia, *Harnesses That Improve Themselves: A Unifying Framework for Self-Improving Agent Harnesses* (SSRN 7707158).
The paper splits a harness into four editable parts (context and state, control, actions, verification) driven by an outer loop:
**diagnose → propose → validate → deploy**. This plan maps that onto our harness, says what we already have, and ranks what to build.

## Where we already stand

| Paper | Ours today | Where |
|---|---|---|
| Stage 1: diagnose from traces | Verifier feedback, `Fail: <kind>` rows, review of its own replies | `harness.verify`, `char._fail` |
| Require repeated failures before a fix | a correction is drafted only after 2 slips since the last fix | `char._fail` |
| Stage 3: validate, no regression | a correction runs a trial of `TRIAL_RUNS` runs and is rolled back if it, or any other step, slips more (`REGRESS`) | `char._judge` |
| Read-only evaluator | the grader `_meets` and the checks are code the loop cannot edit; fixes are fixed text in `CORRECTIONS` | `char.py` |
| Held-out test split (Safeguard 4) | rehearsal: 3 practice probes feed tune and training, 3 held-out probes are only scored | `rehearse.py` |
| Non-regression gate on prompt edits | tune keeps a new tone only if the held-out score holds | `rehearse.gate` |
| Pruning | the Pruner archives notes that do not help it stay itself (`Pruned:` rows) | `char.pruner` |

So the loop is real. The gaps are in what it lets pile up, what it forgets silently, and how sure it is that a change helped.

## Ranked work

### 1. Stop silently dropping your instructions (Mode 1: dropped user constraints) — done, except the rehearsal check after folding
Built as `char.standing()`: the newest 5 word for word, older ones folded once per set (cached `Folded instructions` row), all verbatim if the fold fails.
**Now:** the reply prompt reads only `instructions()[:5]`. A sixth instruction quietly pushes the oldest one out, and nothing tells you.
**Do:** when there are more than five, fold the oldest ones into one line with a single model call, and keep the originals as sheet rows. Show
"N instructions, folded into M" on /wiring. A rehearsal after folding checks that the folded prompt holds the traits.
**Done when:** a test with seven instructions shows all seven reflected in the prompt, and the rehearsal score does not fall after folding.
**Size:** small.

### 2. Cap how much the persona can grow (Mode 1: prompt bloat) — done, except enforcing the budget and the rehearsal check
Built as `char.grow()`: one grown line (≤300 chars) that new directions merge into, and `prompt_size()` against `PROMPT_BUDGET` on the monitor.
**Now:** each direction you answer adds "How you have grown, and how you speak now: …" to the persona in `answer_correction`. It never shrinks.
**Do:** keep one grown line, and merge a new direction into it instead of adding another. Set a character budget for persona + tone + instructions and
show it in the report. Anything over budget must be merged before it is adopted.
**Done when:** ten directions give one grown line within the budget, and the held-out rehearsal score holds.
**Size:** small.

### 3. Prove each learned rule earns its place (Table III: ablation checks)
**Now:** we know that tones, instructions and grown traits were adopted, not whether each still helps.
**Do:** a `/ablate` that runs the held-out rehearsal once with each learned rule switched off. A rule whose removal does not lower the score is
offered to you for removal (never removed silently: they are your words).
**Done when:** the report lists each rule with "score without it", and a rule that helps nothing is flagged.
**Size:** medium. Costs one held-out rehearsal per rule, so run it on demand or while asleep.

### 4. Group failures before fixing them (Stage 1: failure clustering)
**Now:** tune works on one reply at a time, and corrections count slips per step kind.
**Do:** after a rehearsal, count which trait was missed across all probes and across the last N tuned replies. Tune targets the most-missed
trait, with all the replies that missed it, instead of the newest reply.
**Done when:** tune's prompt names the trait and quotes two or three misses, and its note says which group of misses it worked on.
**Size:** small, building on `rehearse.last()` and the `Tuned:` rows.

### 5. An archive of tones and prompts to branch from (Stage 4: archive)
**Now:** `Tone tried:` rows keep every tone with its score, but tune always climbs from the current tone.
**Do:** record the held-out score next to each adopted tone. When tune stalls (three tries in a row with no gain), restart from the best archived
tone instead of the current one. Show the archive on /wiring with "go back to this one".
**Done when:** a stall restarts from the archive's best, and you can roll back a tone by hand.
**Size:** small.

### 6. Test across models; keep model-specific fixes separate (§V: two-tier evolution)
**Now:** a tone or correction is judged on whatever model was loaded. Engines and role models exist (`shared/engines.py`).
**Do:** let the rehearsal run over a list of models, one at a time, using `llm.ensure` so only one is loaded. A change goes into the shared prompt only if it holds
on every model. One that helps a single model is stored as that model's adapter, a per-model tone keyed by model name and read when that model is loaded.
**Done when:** the report shows the held-out score per model, and a per-model tone is used only with its model.
**Size:** medium. Model swaps are slow on 16 GB, so this runs on demand.

### 7. Track where every memory came from (Mode 5: poisoned memory)
**Now:** notes carry a `source`, and `Sources:` and `Ground:` rows exist for reflections. Browse lessons and recipes come from web pages.
**Do:** every learned rule, recipe and instruction records where it came from (you, a web page with its URL, a step). Anything from a web page
is treated as untrusted: it never becomes a standing instruction without your yes, and one click removes everything from a bad source.
**Done when:** each rule on /wiring shows its origin, and a test shows a web-sourced line cannot reach the reply prompt by itself.
**Size:** medium.

### 8. Train the voice into the weights (open problem 1)
**Now:** `train.py` writes a JSONL dataset; nothing turns it into weights. The rehearsal's trained take is ready to measure the result.
**Do:** the MLX steer/fine-tune step from the Jarvis plan: train on the dataset, serve the result as an engine, and run `/rehearse <model>`
after each round. The loop is closed when "learned into the model" rises from round to round.
**Done when:** two rounds in a row show the trained held-out score going up, with the prompted score as the ceiling.
**Size:** large; its own design.

## Built alongside: steering signals instead of code edits
The harness changes how it talks through variables, not its own code. Two built-in signals per persona (`char.signals()`):
- **frustration** rises with your words ("no", "wrong", "ugh", …, at most two per message), the same question asked again, or a base-model slip;
  it eases 0.5 on a calm message. At 3 or more the model is told, the Verifier gets `Fail: frustration`, and the reply you were frustrated by is never taught.
- **voice** is each reply graded on its traits (one small call; `GRADE_REPLIES`), as a running average starting at 1.0. Under 0.6 the model is told what it missed.
Both show on the monitor and in the planner's state.

## Not taking from the paper
- **Letting the harness rewrite its own code** (recursive self-improvers, DGM). We edit prompts and data, not code, and that is the safer side of the line the paper draws.
- **Routers across harness branches** (MoSIB). One persona and one live harness; personas already live apart in the verse.
- **Trace-replay simulators.** Our steps are cheap enough to run live.

## Guardrails that stay fixed while we build all this
- The grader (`_meets`), the held-out probes and the checks stay code the loop cannot change.
- Held-out answers are never taught (asserted in `tests/harness_char/test_rehearse.py`).
- Only one model is in memory at a time (`llm.ensure`).
- Your instructions are never removed without your yes.
