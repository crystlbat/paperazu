# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Bibin, a student, reading research papers at this desk. Creatures work in the background while a paper is open.

## Product Purpose

Paper Reading Workbench is the desk for that reading: library, graph, reader, and creatures. A creature is a companion that reads papers and leaves something behind. Success is teaching a creature once, then meeting its work while reading, without turning the desk into an admin console.

## Positioning

Configuring a creature is a meeting, not a job form. The settings are how you teach it: what it reads, when it wakes, the steps it takes, and what it leaves you. A neighboring automation tool could copy those fields. It could not truthfully say you meet a companion that then works while you read.

## Operating Context

Reading happens in the Reader, over PDFs in the Library. Dot is the buddy on the desk. You can draft a creature by talking to Dot, or build one by hand. Either way it is finished on the creature's own page, then it waits in the pen and wakes from the paper you are reading. Models run locally on this Mac.

## Capabilities and Constraints

A creature keeps these facts, and the configuration page must still edit all of them: name, one of eight colours, awake or asleep, which papers it reads (the open paper, or papers you choose), when it wakes (only on Run, when a paper opens, when a page turns, after staying on a page, when something is highlighted, or on a timer), a chain of one to eight steps (what each step reads, the instruction, and which local model), and what it leaves (Dot speaks, Dot asks a question, a card on the canvas, highlighted lines, or a document). A document can be free-form or a named shape with headings and an ask under each heading.

Only one creature uses the model at a time. The rest wait. When Dot is asleep, creatures are asleep too. You can still make one by talking to Dot or by hand. Runs stay on this Mac. Until the real job routes exist, the page uses the browser stand-in and must keep saying so.

Confirmed outputs: a document to read here, Dot tells me, Dot asks me a question, a card on the canvas, Dot highlights lines. Confirmed starters already in the product: Detailed outline, Simplified version, Research brief, Compare papers, Quiz me, Explain my highlights.

Undecided, and out of this record: the visual world of the configuration page.

## Brand Commitments

The product name in the interface is Paper Workbench. The buddy is Dot. The jobs are creatures. Voice is plain and second person, as the page already speaks: "Name me", "Hatch it", "Let it go", "What should I do?". The configuration page should feel like meeting the creature. That commitment is about the product, not a palette or typeface.

## Evidence on Hand

Working UI: `static/creatures.js`, `static/creatures.css`, reached at `#creatures`. The configuration view is the bench inside that page (Reads, the creature, Leaves you). Contract for the unfinished backend: `docs/creatures-api.md`. Starter copy lives in `static/creatures.js`.

No testimonials, customers, pricing, or benchmarks. Do not invent any.

## Product Principles

1. Meet the creature, then teach it. Every setting stays reachable, and none of them is the page's subject.
2. The paper stays the main act. Setup is a visit to the creature, then back to reading.
3. One mind at a time. The shared model is a real limit and stays visible.
4. Plain speech. Dot and the creatures say what they do in everyday words.
5. Nothing runs that was not taught. Papers, wake rules, and steps stay visible before hatch or save.
