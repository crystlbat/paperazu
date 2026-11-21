# Strategy: changing the model's behaviour, from the knowledge-memory papers

Read on 2026-11-21: AtlasKV (ICLR 2026), KBLaM (ICLR 2025), Memory Layers at Scale (ICML 2025), M+ (MemoryLLM),
RING (2026 preprint), Deep Fusion Memory (2026 preprint), Understanding Parametric Knowledge Injection in RAG (2025),
and the survey Memory in LLMs (2025). The numbers below are the papers' own; none were reproduced here.

## The one finding that sets the strategy

**Weights and hidden states are good at *how* the model behaves. They are bad at holding *what* it knows.**

- Parametric RAG (a LoRA per document) on 2025 news the models had never seen: a 1B model went from 8.5 to 13.5 with
  adapters alone, but to 64.2 with the text in context. On 7B: 15.8 → 20.3 (adapter) vs 69.8 (context). The paper finds the
  injected knowledge acts in the **deep FFN layers as high-level semantic steering, not lexical recall**.
- RING: full fine-tuning to inject facts fell from ~27% to ~12% as documents were added one batch after another (forgetting).
- KBLaM's own README: on a knowledge base unlike its training one, answers "can be reworded … or at times entirely incorrect".

This agrees with what we already wrote down ("steering changes how it writes, not what it knows") and with the ε test
(0.04 invents facts, 0.06 breaks). So the plan splits the work three ways:

| What we want to change | Where it lives | Lever |
|---|---|---|
| Facts about its world, its memories | Context, picked per question | KG2KV-shaped memory (part 1) |
| Tone, faithfulness, staying in-world, not leaking the base model | Hidden states | Steering, sharpened (part 2) |
| Voice that holds without a prompt; saying "I don't know" | Weights | One small LoRA, rebuilt each round (part 3) |

## Before anything: the steering code is not on `main`

`workbench/steer.py` and its tests (RFM, truth and world concepts, the `steer (mlx)` engine, staged pipeline) are only on
`refs/heads/claude/curiosity-maturity-training-bugs-5d4cb8`, 27 commits that never merged. The split into `shared`,
`pdf_research` and `harness_char` happened without them. Parts 2 and 3 build on that code, so it has to come over first,
moved into `harness_char/` (or `shared/` for the MLX engine).

## Part 1: facts as key–value memories (from AtlasKV's KG2KV and KBLaM)

What to borrow is the **data shape**, not the attention surgery.

- Every clean claim the prune step keeps becomes a triple (head, relation, tail). Like KG2KV, mask one end:
  key = "the <relation as a noun> of <other end>", value = the full claim sentence. One triple gives two entries
  (head masked, tail masked), with the relation reworded both ways ("cause" / "result").
- Keys are embedded once with a small sentence encoder (AtlasKV and KBLaM both use all-MiniLM-L6-v2, 384 dims; we already
  embed papers locally). A question is matched against **keys**, not against whole notes, and the top few values go into
  the prompt as the character's own memories (the framing that already cut base-model leaks).
- Why keys and not notes: AtlasKV's whole gain over KBLaM comes from this (ACC@1 on 10⁴ triples, CC-QA: 3.6 → 40.0;
  Pes2o: 0.0 → 16.4). Keys that look like the question match better than keys that look like a document.
- No HiKVP tree. Its point is a billion triples; at 10⁴ its root level is already smaller than its top-k of 128, so pruning
  does nothing. Brute-force dot products over a few thousand keys are instant.
- From KBLaM: when no key scores above a mark, the memory block says so, and the character is told to say it does not know.
  This is the same move as KBLaM training refusals in, without training.

Check: the rehearsal's held-out probes plus a new set of fact questions about the world, scored with a judge asking "does
the answer contain the fact" (the PRAG paper's HasAnswer, 96.7% agreement with people), never string overlap.

## Part 2: steering, sharpened (from AtlasKV's λ, Deep Fusion Memory's gate, the PRAG layer finding)

Today `generate()` adds ε × norm × v at **every** layer with the same ε, while `score()` already weights layers by how well
each one fitted (`corr`). Three changes, each one ε-test away from known:

1. **Weight the push by layer.** Use the stored `corr` per layer as the weight, as `score()` does, and leave the early
   layers alone. Deep Fusion Memory: memory fused only at the last layer scored 21.1, at the last four 22.1, at
   intermediate-to-late layers 27.1–27.5. The PRAG paper puts behaviour change in the deep FFN layers. Expected effect:
   the same pull at a lower total push, so the 0.04 "invents facts" point moves up.
2. **Push only when needed.** AtlasKV's λ mixes the knowledge side in by how strongly it matched; DFM gates memory with a
   sigmoid that starts near 0.12 (bias −2). Our analogue: read the concept score on the prompt first (the monitor already
   exists) and scale ε by how far below the target it sits. A reply already in-world gets no push.
3. **Steer away from the base model.** A third concept, "base-model voice": positives are the logged slips ("I am an AI",
   "made by Liquid AI", from the frustration signal), negatives are in-character replies. Steer with negative ε. The
   slips are already counted, so the data costs nothing.

Keep: the planner and the judge are never steered; Thompson sampling chooses ε per model.

## Part 3: one small LoRA for voice and refusals (roadmap item 8)

`train.py` writes a JSONL set; nothing turns it into weights. `mlx_lm` does LoRA on this Mac for a 2–4B model.

- **What goes in:** behaviour only (voice, staying in-world, refusing what it does not know). No facts, by the finding at
  the top; facts stay in part 1. Refusal pairs come from the truth concept's negatives: a dropped or name-swapped claim as
  the question, "that isn't so / I don't know that" as the answer (KBLaM trained refusals the same way).
- **Diversity over volume:** AtlasKV's data was 7.9% diverse against KBLaM's 0.003%, and that is the reason it held up
  on 100× bigger knowledge bases than it trained on. Vary the question forms ("What is…", "Tell me…", "Provide details
  on…"), as KG2KV does, and do not let one probe phrasing dominate.
- **Small and late:** start from the PRAG settings, which are the only small-model numbers we have: FFN layers only,
  rank 2, lr 3e-4, one epoch. Raise the rank only if the rehearsal shows no change.
- **Never stack:** RING's forgetting curve is the warning. Each round trains a new adapter from the base model on the whole
  clean set so far, not on top of the last adapter. Adapters are files listed as options of the MLX engine (an engine with
  an adapter path), so a bad one is a click away from gone.
- **Gate it like a tone:** the adapter is kept only if, against the model without it, (a) the held-out voice score does
  not fall, (b) a fixed set of plain questions unrelated to the character answers as well as before (the survey's
  "neighbourhood" set; it catches spill-over), and (c) the base-model slip rate does not rise.

Steering then runs on top of the adapted model; concepts are refitted for it, since they are stored per model already.

## How we measure (applies to all three parts)

- One 2B judge has noise of about ±0.17. Use more held-out probes, several runs, and a paired bootstrap between "with"
  and "without" before believing a gain (the survey's advice; DFM and AtlasKV report single runs and we should not).
- Report three things together: the target (voice, facts), the neighbourhood (unrelated questions), and the slip rate.
  A gain on one that costs another is not a gain.

## Not taking

- **Rebuilding attention as KBLaM/AtlasKV do.** It needs trained projection heads (AtlasKV: 3K steps, batch 10, on a
  48 GB GPU with an 8B model) and attention code per architecture. Part 1 gets the matching benefit with text. Revisit
  only if the prompt budget becomes the limit; KBLaM's repo already supports Llama-3.2-1B, the one size that would fit.
- **Memory layers, M+, Deep Fusion Memory, RING's full pipeline.** All need pretraining-scale compute (8×A100 for weeks,
  16×A800, 32×H800). What we take from them is above: where to inject, gating, freezing what is learned.
- **Editing single facts into weights (ROME/MEMIT).** The survey: sequential edits spread off-target; ripple tasks under 50%.

## Order

1. Bring the steering code onto `main`.
2. Part 2.1 (layer weights) with the ε test: smallest change, existing data.
3. Part 1 (key–value memories).
4. Part 2.3 (away from the base model), then 2.2 (gating).
5. Part 3 (LoRA), last, because it needs parts 1 and 2 to know what it must *not* learn.
