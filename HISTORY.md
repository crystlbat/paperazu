# History: the journey and what we observed

Paperazu is an ongoing build. When I learn something, from a paper, a tool or a failure, it goes in here as a prototype with a test.
This file is the lab notebook: what was built, in what order, and what each stage taught. Newest entries go at the bottom.

## Stage 1: a desk for reading papers (Nov 6–8, 2026)

**Built:** a local-first reader (FastAPI, SQLite, PDF.js) that runs on small models on a 16 GB Mac. Notes per reading step, an AI
summary made before you read, "check my notes" that gives hints instead of answers, Markdown export, and a graph of papers linked by
meaning using local embeddings. Dot, a reading companion, guides you through a paper (abstract, conclusion, figures, then the rest),
explains circled words and formulas, suggests highlights, and opens a canvas of cards and threads.
Creatures came next: small jobs Dot runs on your papers while you read.

**Observed:**
- Small models are reliable when each call has one job. Formula explanation became four calls: read the formula from a picture, name each
  piece, work it with tiny numbers, then explain. One big prompt did worse.
- Maths extracted from a PDF as text comes out jumbled. Sending a picture of the region works better.
- Guessing sections from paragraph boxes failed often. Reading the PDF's own structure (font sizes, columns, reading order) fixed it.
- A model that writes your reflection for you invents facts. In the export outline the model only sorts your numbered notes into sections,
  and the app copies your words in as they are.

## Stage 2: a character that learns (Nov 14–16)

**Built:** Dot space and personas: a self-learning character harness. Each persona has needs, wants and trust, a journal, a chat map,
and a Verse where personas live apart. Training runs learn on their own and export a fine-tuning set. The Story view shows a run live:
every variable on one clock, with each system's last steps.

**Observed:**
- Variables you can watch are the best debugging tool for an agent. Once curiosity, tiredness and trust were charted, drift was visible.
- A dataset has to leave out drift, or the next round learns the drift too.

## Stage 3: one codebase, three parts (Nov 18)

**Built:** the split into `shared`, `pdf_research` and `harness_char`; the paper as a mind map that grows, where each node cites its page;
engines to pick how models run (only one model in memory at a time); `/browse`, where the character uses a real browser and learns how.

## Stage 4: the harness checks itself (Nov 19)

**Read:** D. Shah and N. Kathrotia, *Harnesses That Improve Themselves* (SSRN 7707158). Its outer loop is diagnose, propose, validate,
deploy. Its safeguards include a held-out test split and a non-regression gate. Its failure modes include prompt bloat and silently dropped
constraints. The mapping to this project is in `docs/superpowers/plans/2026-11-19-self-improving-harness-roadmap.md`.

**Built:**
- **Rehearsal**: fixed probes are asked of the prompted model and of a trained model given only its name. Each answer is graded trait by
  trait by a judge model. Three probes are practice and three are held out; only the held-out ones are scored and they are never taught.
- **Non-regression gate**: a new tone is kept only if the held-out score does not fall.
- **Prompt hygiene**: instructions past the newest five are folded into one line instead of dropped. Directions merge into one capped
  grown line, and the prompt has a budget.
- **Steering signals**: frustration (corrective words, repeated questions, base-model slips) and voice (each reply graded). Past their
  marks the model is told, the Verifier logs a failure, and frustrating turns are kept out of training.

**Observed, live with a 2B model:**
- The first version let tune learn from the very questions it was scored on. The score could only climb. Splitting practice from
  held-out is what makes the number mean anything.
- Yoda's held-out score went from 0.5 to 0.67. With a 2B judge the noise is about ±0.17, so one run proves little. A bigger judge,
  or several runs, is needed before trusting small gains.
- The judge answered "1. trait. NO" where the parser expected "1 NO", so every grade was silently empty. Parsers of model output
  need tests built from real output.
- A fresh J.A.R.V.I.S. got the voice "Speak as J.A.R.V.I.S.", which says nothing. A hollow-voice check and a plain-text retry fixed it.
- The base model keeps leaking through: "I am an AI, I have no memory", "made by Liquid AI". Framing recalled notes as the character's
  own memories helped, and the leaks now count as slips. Chat history full of base-model replies still pulls it back.
- When the user says "look it up", the right response is research, not an apology. That correction now queues a question.

**Next:** prove each learned rule earns its place by ablation, group failures before fixing them, and train the voice into the weights so
the "trained" take has something to measure (roadmap items 3, 4 and 8).
