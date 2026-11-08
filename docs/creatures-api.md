# Creatures: the backend the screen expects

The Creatures page (`#creatures`, `static/creatures.js`) is built. Until these routes exist it runs on a stand-in kept in
the browser (`localStorage["creatures-local"]`) and labels itself "Stand-in". Once `GET /jobs` answers 200 the page uses
the real routes and the stand-in is never touched. Delete the stand-in block in `creatures.js` (marked `STAND-IN`) once
the backend is done.

A **creature** is a job: a trigger, a short chain of steps, and an output. A **template** is the skeleton of a document a
job fills in, one heading at a time (deep-research style). Jobs run on one paper, or across several.

## Shapes

```jsonc
// Job
{ "id": 1, "name": "Detailed outline", "color": 3,            // color: 0-7, the --theme-N slot
  "trigger": "manual",     // manual | open | page | dwell | highlight | timer
  "every": 120,            // seconds; used by dwell (time on one page) and timer (how often). 20-3600
  "output": "doc",         // say | ask | card | highlight | doc
  "papers": [],            // [] = the paper being read (or picked at Run). Else paper ids: runs across them
  "template_id": null,     // the template a "template" step fills in
  "steps": [ { "scope": "paper", "prompt": "…", "model": "" } ],   // 1-8 steps; model "" = model in Settings
  "on": true }

// scope, per step
//   page       the page being read          selection  the words just highlighted
//   paper      all chosen papers together   each_paper one call per chosen paper
//   sections   one call per section          template   one call per template heading (uses that heading's ask)
//   prev       only what the step before wrote
// Every step after the first also gets the previous step's output as context.

// Template
{ "id": 1, "name": "Research brief",
  "sections": [ { "title": "The question", "ask": "What question does this answer, and why does it matter?" } ] }

// Run
{ "id": 9, "job_id": 1, "job": "Detailed outline", "paper_id": "2af63b6635b7", "paper": "Title…",
  "status": "queued",      // queued | running | done | failed | stopped
  "done": 2, "total": 7, "label": "3 Method",   // progress: calls finished / planned, and what it is on now
  "result": { "text": "…", "sections": [["3 Method", "…"]], "highlights": [] },   // {} until done
  "error": "", "created_at": "2026-11-08 10:00:00", "finished_at": null }
```

## Routes

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/jobs` | | `{jobs: [Job]}` |
| POST | `/jobs` | Job without id | Job (201) |
| PUT | `/jobs/{id}` | Job without id | Job |
| DELETE | `/jobs/{id}` | | `{ok: true}` |
| POST | `/jobs/starters` | | `{jobs}`: adds the starter jobs and templates that are missing (by name) |
| GET | `/templates` | | `{templates: [Template]}` |
| POST / PUT / DELETE | `/templates`, `/templates/{id}` | Template without id | as for jobs |
| POST | `/jobs/{id}/run` | `{paper_id?, page?, text?}` | Run (status `queued`) |
| GET | `/runs?limit=30` | | `{runs: [Run], parallel: 1, queued: 2}` newest first |
| GET | `/runs/{id}` | | Run |
| POST | `/runs/{id}/stop` | | Run (queued → stopped at once; running → stops after the call in flight) |
| POST | `/dot/talk` | `{messages: [{role: "user"\|"assistant", content}]}` | `{reply, job: Job-without-id \| null}` (a draft, not saved) |

Validation errors: 422 with `{detail: {errors: [{field, message}]}}`, like the other routes. A run that cannot start (no
paper, job gone) is 422 with one error. Add `/jobs/\d+/run` and `/dot/talk` to `AI_CALL` in `static/app.js` so they are
off while Dot sleeps.

## Keeping the Mac alive

- **One creature works at a time.** One worker thread takes queued runs oldest first; `parallel` in `/runs` reports it.
- **At most 20 queued.** Past that, `POST /jobs/{id}/run` is 429 with `{detail: "Too many jobs waiting."}`.
- **No duplicates.** Running a job that is already queued or running for the same paper returns that run.
- **Bounded prompts.** About 12,000 characters of paper per call; across N papers each gets 1/N of it.
- On app start, runs left `running` or `queued` become `failed` ("The app restarted before this finished.").
- Each step can name its own model (from `/model/status` `models`); pin it with `s.model_copy(update={"model_name": m})`.
  Send `extra_body=llm.NO_THINK` like every other call.

## Starters (`POST /jobs/starters`)

The stand-in in `creatures.js` (`STARTER_JOBS`, `STARTER_TEMPLATES`) has the exact names, prompts and sections; copy them.
Detailed outline, Simplified version, Research brief (template), Compare papers (each_paper then template), Quiz me on
the page (dwell, ask), Explain what I highlight (highlight, card).

## Paper text

`library.page_texts(id)` gives each page's text. `library.headings(id)` gives `(level, title, page)`; the `sections`
table is empty, so cut sections from the level-1 headings found in the joined page text, and fall back to 2 pages at a
time when fewer than 2 headings match.
