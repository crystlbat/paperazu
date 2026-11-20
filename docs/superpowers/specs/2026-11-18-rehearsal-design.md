# Rehearsal: has it learned its personality?

**Why:** the tune and practise steps grade whatever chat happened. Nothing asks the same questions each time, so nothing shows whether
the voice is learned or only prompted, or whether it is getting better.

**What:** `/rehearse [model]` asks fixed questions (`rehearse.PROBES`) with no chat history, in two takes:
- **prompted**: the chat model with its whole reply prompt (`char.prompt_now()`);
- **trained**: the named model on the current engine, told only "You are {name}."

Each answer is graded trait by trait with `char._meets` on the judge model. The run is a sheet row `Rehearsal`, so it moves with the persona.
Models load one at a time: prompted, then trained, then judge (`llm.ensure`).

**Practice and held-out:** three probes are practice (tune and training may learn from them), three are held out and are the only ones
scored, so the score cannot climb by memorising its own test (Safeguard 4 of Shah & Kathrotia, *Harnesses That Improve Themselves*).

**Feeds the loop:**
- the planner's state gets a line with both scores and the weakest traits;
- tune, when no new chat reply waits, works on the prompted rehearsal answer that missed most;
- training snapshots take prompted answers that met every trait as examples, and misses as fails.

**Approaches:** trait grading on both takes (picked: reuses `_meets`, one call per answer); a blind "which one is the real character"
judge (left out: an extra call per answer, can be added); embedding distance to reference text (left out: no reference corpus).

**Builder's calls:** a trained model must be listed by the current server, or the run refuses, so a llama.cpp server holding one model
cannot quietly answer both takes. A rehearsal refuses while other model work runs (`llm.busy`). Probes are a constant for now.
