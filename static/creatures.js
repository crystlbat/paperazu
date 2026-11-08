"use strict";
// ---------- Creatures: jobs Dot runs on your papers ----------
// Each job is a small creature in a pen. You make one by talking to Dot or by hand: when it wakes (trigger), what it
// reads at each step (scope) on which model, and what it leaves you (output). Templates are document skeletons a job
// fills in heading by heading. Only one creature works at a time; the rest wait in line. API: docs/creatures-api.md.

const CR_TRIGGER = { manual: "Only when I press Run", open: "When I open a paper", page: "When I turn a page",
  dwell: "When I stay on a page", highlight: "When I highlight something", timer: "Every few minutes while I read" };
const CR_OUTPUT = { doc: "A document to read here", say: "Dot tells me", ask: "Dot asks me a question",
  card: "A card on the canvas", highlight: "Dot highlights lines" };
const CR_SCOPE = { page: "The page I'm on", selection: "What I highlighted", paper: "The whole paper (all papers)",
  each_paper: "Each paper in turn", sections: "Each section in turn", template: "Each template heading",
  prev: "Only the step before" };
const CR_SUGGEST = ["Make a detailed outline of the paper", "Rewrite each section simply", "Quiz me when I stay on a page",
  "Compare my papers on their methods"];

const STARTER_TEMPLATES = [
  { name: "Research brief", sections: [
    { title: "The question", ask: "What question does this work answer, and why does it matter? Two short paragraphs." },
    { title: "What they did", ask: "Describe the method step by step, in plain words, with the key design choices." },
    { title: "What they found", ask: "List the main results with their numbers, and what each one means." },
    { title: "Limits", ask: "What does this not show? Note weak spots, assumptions, and missing tests." },
    { title: "Open questions", ask: "Write five questions a curious student could follow up on." }] },
  { name: "Comparison", sections: [
    { title: "The problem each tackles", ask: "For each paper, say in one or two sentences what problem it tackles." },
    { title: "Methods side by side", ask: "Compare how the papers approach the problem. A short table, then what differs." },
    { title: "Results side by side", ask: "Compare their results and the evidence behind them." },
    { title: "Where they disagree", ask: "Where do the papers disagree or contradict each other?" },
    { title: "Gaps", ask: "What do none of them cover? Suggest a next study." }] },
];
const STARTER_JOBS = [
  { name: "Detailed outline", color: 0, trigger: "manual", every: 120, output: "doc", papers: [], template: "", steps: [
    { scope: "paper", prompt: "List the sections of this paper and, for each, the one question it answers. Short lines.", model: "" },
    { scope: "sections", prompt: "Write a detailed outline of this section: its claim, how they show it, the key numbers, and any terms a student must know. Nested bullet points, plain English.", model: "" }] },
  { name: "Simplified version", color: 2, trigger: "manual", every: 120, output: "doc", papers: [], template: "", steps: [
    { scope: "sections", prompt: "Rewrite this section for a first-year student: short sentences, everyday words, one small example. Keep every idea; explain jargon the first time.", model: "" }] },
  { name: "Research brief", color: 3, trigger: "manual", every: 120, output: "doc", papers: [], template: "Research brief", steps: [
    { scope: "template", prompt: "Answer this heading from the paper. Be thorough and specific; quote numbers.", model: "" }] },
  { name: "Compare papers", color: 1, trigger: "manual", every: 120, output: "doc", papers: [], template: "Comparison", steps: [
    { scope: "each_paper", prompt: "Summarise this paper's problem, method, data and results in ten bullet points.", model: "" },
    { scope: "template", prompt: "Using the summaries, answer this heading across all the papers.", model: "" }] },
  { name: "Quiz me", color: 4, trigger: "dwell", every: 180, output: "ask", papers: [], template: "", steps: [
    { scope: "page", prompt: "Ask one short question that checks I understood the main idea of this page. Only the question.", model: "" }] },
  { name: "Explain my highlights", color: 5, trigger: "highlight", every: 120, output: "card", papers: [], template: "", steps: [
    { scope: "selection", prompt: "Explain these words in two plain sentences, and say why they matter in this paper.", model: "" }] },
];

// ---------- STAND-IN: a browser-only backend so the screen works before the real routes exist ----------
// shortcut: fakes progress and writes placeholder text; delete this block once GET /jobs answers (see docs/creatures-api.md).
const crLocal = (() => {
  const KEY = "creatures-local";
  let d;
  try { d = JSON.parse(localStorage.getItem(KEY)); } catch { d = null; }
  d = d || { jobs: [], templates: [], runs: [], next: 1 };
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(d)); } catch {} };
  const now = () => new Date().toISOString().slice(0, 19).replace("T", " ");
  const bad = (field, message) => Object.assign(new Error("422"), { status: 422, body: { detail: { errors: [{ field, message }] } } });
  const check = (j) => {
    if (!j.name?.trim()) throw bad("name", "Give it a name.");
    if (!j.steps?.length) throw bad("steps", "Add at least one step.");
    j.steps.forEach((s, i) => { if ((s.prompt || "").trim().length < 3) throw bad(`steps.${i}.prompt`, `Step ${i + 1} needs an instruction.`); });
  };
  const plan = (job, run) => {  // the labels a real run would walk through
    const tpl = d.templates.find((t) => t.id === job.template_id);
    return job.steps.flatMap((s) => s.scope === "sections" ? ["Introduction", "Method", "Results", "Discussion"]
      : s.scope === "template" ? (tpl?.sections.map((x) => x.title) || ["Template"])
      : s.scope === "each_paper" ? (job.papers.length ? job.papers : [run.paper_id]).map((_, i) => `Paper ${i + 1}`)
      : [CR_SCOPE[s.scope]]);
  };
  function tick() {  // one creature at a time
    let r = d.runs.find((x) => x.status === "running");
    if (!r) { r = d.runs.filter((x) => x.status === "queued").sort((a, b) => a.id - b.id)[0]; if (!r) return; r.status = "running"; }
    const job = d.jobs.find((j) => j.id === r.job_id);
    const steps = job ? plan(job, r) : ["?"];
    r.total = steps.length; r.done = Math.min(r.done + 1, r.total); r.label = steps[Math.min(r.done, r.total - 1)];
    if (r.done >= r.total) {
      const last = job.steps[job.steps.length - 1];
      const secs = ["sections", "template", "each_paper"].includes(last.scope) ? plan({ ...job, steps: [last] }, r) : [];
      r.status = "done"; r.finished_at = now(); r.label = "done";
      r.result = { text: "Stand-in text. Once the backend is built, this is what your model wrote.",
        sections: secs.map((t) => [t, `Stand-in text for "${t}". The real run sends this heading and the paper to the model you picked.`]) };
    }
    save();
  }
  function starters() {
    for (const t of STARTER_TEMPLATES) if (!d.templates.some((x) => x.name === t.name)) d.templates.push({ ...structuredClone(t), id: d.next++ });
    for (const j of STARTER_JOBS) if (!d.jobs.some((x) => x.name === j.name)) {
      const { template, ...rest } = structuredClone(j);
      d.jobs.push({ ...rest, on: true, id: d.next++, template_id: d.templates.find((t) => t.name === template)?.id ?? null });
    }
    save();
  }
  function talk(messages) {  // guesses a job from keywords; the real one asks the model
    const said = messages.filter((m) => m.role === "user").pop()?.content || "";
    const w = said.toLowerCase();
    const job = { name: said.split(/\s+/).slice(0, 3).join(" ").replace(/^./, (c) => c.toUpperCase()) || "New job", color: 6,
      trigger: "manual", every: 120, output: "doc", papers: [], template_id: null, on: true,
      steps: [{ scope: "sections", prompt: said, model: "" }] };
    if (/quiz|question|test me/.test(w)) Object.assign(job, { trigger: "dwell", every: 180, output: "ask", steps: [{ scope: "page", prompt: said, model: "" }] });
    else if (/highlight|mark/.test(w)) Object.assign(job, { trigger: "page", output: "highlight", steps: [{ scope: "page", prompt: said, model: "" }] });
    else if (/compar|across|papers/.test(w)) {
      const t = d.templates.find((x) => x.name === "Comparison");
      Object.assign(job, { template_id: t?.id ?? null, steps: [{ scope: "each_paper", prompt: "Summarise this paper in ten bullet points.", model: "" },
        { scope: "template", prompt: said, model: "" }] });
    } else if (/outline|plan/.test(w)) job.steps.unshift({ scope: "paper", prompt: "List the sections and the question each answers.", model: "" });
    if (said.trim().length < 6) return { reply: "Tell me what you want done while you read, and I will turn it into a creature.", job: null };
    return { reply: "Here is a creature for that. I am the stand-in Dot, so check the steps before you hatch it.", job };
  }
  async function call(path, opts = {}) {
    const m = (opts.method || "GET").toUpperCase();
    const body = opts.body ? JSON.parse(opts.body) : {};
    const [p, q] = path.split("?");
    let x;
    if (p === "/jobs" && m === "GET") return { jobs: d.jobs };
    if (p === "/jobs/starters") { starters(); return { jobs: d.jobs }; }
    if (p === "/jobs" && m === "POST") { check(body); x = { ...body, id: d.next++ }; d.jobs.push(x); save(); return x; }
    if ((x = p.match(/^\/jobs\/(\d+)$/))) {
      const i = d.jobs.findIndex((j) => j.id === +x[1]);
      if (i < 0) throw Object.assign(new Error("404"), { status: 404, body: {} });
      if (m === "DELETE") { d.jobs.splice(i, 1); save(); return { ok: true }; }
      check(body); d.jobs[i] = { ...body, id: +x[1] }; save(); return d.jobs[i];
    }
    if ((x = p.match(/^\/jobs\/(\d+)\/run$/))) {
      const job = d.jobs.find((j) => j.id === +x[1]);
      const pid = body.paper_id || job.papers[0];
      if (!pid) throw bad("paper_id", "Pick a paper to run it on.");
      const dup = d.runs.find((r) => r.job_id === job.id && r.paper_id === pid && ["queued", "running"].includes(r.status));
      if (dup) return dup;
      if (d.runs.filter((r) => r.status === "queued").length >= 20) throw Object.assign(new Error("429"), { status: 429, body: { detail: "Too many jobs waiting." } });
      const r = { id: d.next++, job_id: job.id, job: job.name, paper_id: pid, paper: body.paper || "", status: "queued",
        done: 0, total: 1, label: "", result: {}, error: "", created_at: now(), finished_at: null };
      d.runs.push(r); save(); return r;
    }
    if (p === "/runs") {
      tick();
      const limit = +(new URLSearchParams(q).get("limit") || 30);
      return { runs: [...d.runs].sort((a, b) => b.id - a.id).slice(0, limit), parallel: 1,
        queued: d.runs.filter((r) => r.status === "queued").length };
    }
    if ((x = p.match(/^\/runs\/(\d+)$/))) { tick(); return d.runs.find((y) => y.id === +x[1]) || null; }
    if ((x = p.match(/^\/runs\/(\d+)\/stop$/))) {
      const r = d.runs.find((y) => y.id === +x[1]);
      if (r && ["queued", "running"].includes(r.status)) { r.status = "stopped"; r.finished_at = now(); save(); }
      return r;
    }
    if (p === "/templates" && m === "GET") return { templates: d.templates };
    if (p === "/templates" && m === "POST") {
      if (!body.name?.trim()) throw bad("name", "Give the template a name.");
      x = { ...body, id: d.next++ }; d.templates.push(x); save(); return x;
    }
    if ((x = p.match(/^\/templates\/(\d+)$/))) {
      const i = d.templates.findIndex((t) => t.id === +x[1]);
      if (m === "DELETE") { d.templates.splice(i, 1); d.jobs.forEach((j) => { if (j.template_id === +x[1]) j.template_id = null; }); save(); return { ok: true }; }
      if (!body.name?.trim()) throw bad("name", "Give the template a name.");
      d.templates[i] = { ...body, id: +x[1] }; save(); return d.templates[i];
    }
    if (p === "/dot/talk") return talk(body.messages || []);
    throw Object.assign(new Error("404"), { status: 404, body: {} });
  }
  return { call };
})();
// ---------- end STAND-IN ----------

// ---------- creatures at work while you read ----------
// The Reader calls crWatch when a paper opens. Every awake creature that reads this paper (or "the paper I'm reading")
// and has a reading trigger wakes on what you do: opening the paper, turning a page, staying on one, highlighting, or a
// timer. A woken creature runs on the server queue (one at a time) and its output lands here: Dot says it, asks it,
// leaves a card, marks lines, or tells you a document is ready. Asleep Dot means asleep creatures too.
function crWatch(paperId, pdf, canvas) {
  let jobs = [], stopped = false, page = 0, dwells = [];
  const timers = [], last = new Map(), pending = new Set();
  const held = new Map(); // job id -> the run it finished that you have not looked at yet
  const COOL = { open: 0, page: 45e3, dwell: 0, highlight: 20e3, timer: 0 }; // a page-flicker or a burst of highlights wakes it once
  const wake = async (j, text = "") => {
    if (stopped || buddy.asleep?.() || pending.has(j.id)) return;
    if (document.hidden && ["timer", "dwell"].includes(j.trigger)) return; // nobody is reading a hidden tab; a page turn or highlight means you are here
    if (Date.now() - (last.get(j.id) || 0) < COOL[j.trigger]) return;
    last.set(j.id, Date.now()); pending.add(j.id); paint();
    try {
      let r = await crPost(`/jobs/${j.id}/run`, { paper_id: paperId, page: pdf.page(), text: text.slice(0, 3000) });
      while (!stopped && r && ["queued", "running"].includes(r.status)) {
        await new Promise((ok) => setTimeout(ok, 1500));
        r = await crApi(`/runs/${r.id}`);
      }
      if (!stopped && r?.status === "done") { held.set(j.id, r); await deliver(j, r); }
    } catch { /* a creature that cannot run stays quiet here; the Creatures page shows the failed run */ }
    finally { pending.delete(j.id); paint(); }
  };
  async function deliver(j, r) {
    const res = r.result || {}, text = (res.text || res.sections?.map(([t, x]) => `${t}\n${x}`).join("\n\n") || "").trim();
    const at = () => { const w = innerWidth, hgt = innerHeight; return { x: w - 340, y: hgt - 140 }; };
    if (j.output === "doc") {
      buddy.say(`${j.name} made you something.`, { mood: "happy", actions: [{ label: "Read it", href: "#creatures" }] });
    } else if (j.output === "highlight") {
      await pdf.reloadHighlights?.();
      const n = res.highlights?.length || 0;
      buddy.say(n ? `${j.name} marked ${n} line${n === 1 ? "" : "s"} in blue.` : `${j.name} found nothing to mark here.`, { mood: n ? "happy" : "idle" });
    } else if (!text) {
      return;
    } else if (j.output === "card") {
      const d = await canvas.drop?.({ kind: "answer", question: j.name, text: text.slice(0, 8000), page: r.page || pdf.page() });
      if (d) buddy.say(`${j.name} left a card on your canvas.`, { mood: "happy", actions: canvas.isOpen?.() ? [] : [{ label: "Show me", onClick: () => canvas.open?.() }] });
    } else if (j.output === "ask") {
      const q = text.slice(0, 500);
      buddy.say(`${j.name} asks: ${q}`, { mood: "think", actions: [{ label: "Answer", onClick: async () => {
        const a = (await buddy.prompt({ ...at(), placeholder: "Your answer" }))?.trim();
        if (!a) return;
        const d = await canvas.drop?.({ kind: "note", entries: [{ who: "dot", text: q }, { who: "me", text: a.slice(0, 4000) }], page: r.page || pdf.page() });
        buddy.say(d ? "Saved on your canvas." : "I could not save that. Is the app still running?", { mood: d ? "happy" : "worried" });
      } }] });
    } else {
      buddy.say(`${j.name}: ${text.slice(0, 600)}`, { mood: "happy", actions: text.length > 600 ? [{ label: "Keep it", onClick: () => canvas.drop?.({ kind: "answer", question: j.name, text: text.slice(0, 8000), page: r.page || pdf.page() }) }] : [] });
    }
  }
  // ----- the chip in the reader's bar, and its bubble of creatures -----
  // spiky: it made you something you have not looked at; running: it is working; jumping: awake and watching
  const moodOf = (j) => (pending.has(j.id) ? "run" : held.has(j.id) ? "out" : "watch");
  const LINE = { run: "Working on it", out: "Made you something. Tap to see", watch: null };
  const blob = (j) => h("span", { class: `crm ${moodOf(j)}`, "data-job": j.id, style: `--bc: var(--theme-${j.color ?? 6}); --i: ${j.id % 7}` }, crBody());
  const chip = h("button", { type: "button", class: "dchip cr-rchip", "aria-expanded": "false", "aria-haspopup": "dialog",
    onclick: (e) => { e.stopPropagation(); bubble.hidden ? openBubble() : closeBubble(); } });
  const bubble = h("div", { class: "cr-rbubble", role: "dialog", "aria-label": "Creatures on this paper", hidden: true });
  document.body.append(bubble);
  function paint() {
    const out = jobs.filter((j) => held.has(j.id)).length, run = jobs.filter((j) => pending.has(j.id)).length;
    chip.replaceChildren(h("span", { class: "cr-rflock", "aria-hidden": "true" }, jobs.slice(0, 3).map(blob)),
      jobs.length ? `${jobs.length}` : "Creatures");
    chip.dataset.mood = out ? "out" : run ? "run" : "watch";
    chip.setAttribute("aria-label", `Creatures on this paper: ${jobs.length}${run ? `, ${run} working` : ""}${out ? `, ${out} made something` : ""}`);
    if (!bubble.hidden) fill();
  }
  function fill() {
    bubble.replaceChildren(
      h("p", { class: "cr-rhead" }, jobs.length ? "Creatures watching this paper" : "No creatures are watching this paper."),
      jobs.length ? h("ul", {}, jobs.map((j) => {
        const m = moodOf(j);
        return h("li", {}, h("button", { type: "button", class: `cr-ritem ${m}`, onclick: () => see(j) }, blob(j),
          h("span", {}, h("b", {}, j.name), h("small", {}, LINE[m] || `Wakes when ${CR_WAKE[j.trigger].toLowerCase()}`))));
      })) : null,
      h("a", { href: "#creatures", class: "cr-rmore", onclick: closeBubble }, jobs.length ? "Manage creatures" : "Make one"));
  }
  function see(j) {  // show what it made again, then it calms down
    const r = held.get(j.id);
    if (!r) { hopIn(j); return; }
    held.delete(j.id); paint();
    if (j.output === "doc") { closeBubble(); location.hash = "#creatures"; return; }
    if (j.output === "card") { canvas.open?.(); return; }
    if (j.output === "highlight") { buddy.say(`${j.name} marked them in blue on page ${r.page || pdf.page()}.`, { mood: "happy" }); return; }
    deliver(j, r);
  }
  function hopIn(j) { const b = bubble.querySelector(`.crm[data-job="${j.id}"]`); b?.classList.remove("poke"); void b?.offsetWidth; b?.classList.add("poke"); }
  function openBubble() {
    fill(); bubble.hidden = false; chip.setAttribute("aria-expanded", "true");
    const r = chip.getBoundingClientRect();
    bubble.style.top = `${r.bottom + 10}px`;
    bubble.style.left = `${Math.max(12, Math.min(r.left + r.width / 2 - 150, innerWidth - 312))}px`;
    bubble.style.setProperty("--tip", `${r.left + r.width / 2 - parseFloat(bubble.style.left)}px`);
    document.addEventListener("pointerdown", outside, true); document.addEventListener("keydown", esc, true);
  }
  function closeBubble() {
    bubble.hidden = true; chip.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outside, true); document.removeEventListener("keydown", esc, true);
  }
  const outside = (e) => { if (!bubble.contains(e.target) && !chip.contains(e.target)) closeBubble(); };
  const esc = (e) => { if (e.key === "Escape") { closeBubble(); chip.focus(); } };

  const of = (t) => jobs.filter((j) => j.trigger === t);
  function onPage(n) {
    if (stopped || n === page) return;
    const first = !page;
    page = n;
    dwells.forEach(clearTimeout);
    dwells = of("dwell").map((j) => setTimeout(() => { if (pdf.page() === n) wake(j); }, j.every * 1000));
    if (!first) of("page").forEach((j) => wake(j));
  }
  pdf.hooks.onPage = onPage;
  pdf.hooks.onHighlight = (hl) => of("highlight").forEach((j) => wake(j, hl.text || ""));
  crApi("/jobs").then((r) => {
    if (stopped) return;
    jobs = (r.jobs || []).filter((j) => j.on && j.trigger !== "manual" && (!j.papers?.length || j.papers.includes(paperId)));
    paint();
    of("open").forEach((j) => wake(j));
    of("timer").forEach((j) => timers.push(setInterval(() => wake(j), j.every * 1000)));
    const n = pdf.page(); page = 0; if (n) onPage(n); // the page already shown starts its dwell clock
  }).catch(() => {});
  paint();
  return { chip, stop() { stopped = true; closeBubble(); bubble.remove(); timers.forEach(clearInterval); dwells.forEach(clearTimeout); pdf.hooks.onPage = pdf.hooks.onHighlight = null; } };
}

let crMode = null; // "server" once GET /jobs answers, else "local"
async function crApi(path, opts) {
  if (!crMode) {
    try { await api("/jobs"); crMode = "server"; } catch (e) { crMode = e.status === 404 || e.status === 405 ? "local" : "server"; }
  }
  if (crMode === "local") return crLocal.call(path, opts);
  return api(path, opts);
}
const crPost = (path, body, method = "POST") => crApi(path, { method, body: JSON.stringify(body) });

function crSeen() { try { return new Set(JSON.parse(localStorage.getItem("creatures-seen") || "[]")); } catch { return new Set(); } }
function crMarkSeen(id) { const s = crSeen(); s.add(id); try { localStorage.setItem("creatures-seen", JSON.stringify([...s].slice(-300))); } catch {} }

const crBlank = () => ({ name: "", color: 6, trigger: "manual", every: 120, output: "doc", papers: [], template_id: null, on: true,
  steps: [{ scope: "sections", prompt: "", model: "" }] });

function crSelect(options, value, attrs = {}) {
  const s = h("select", attrs, Object.entries(options).map(([v, t]) => h("option", { value: v }, t)));
  s.value = value;
  return s;
}

// short words for the chips on a step: what it reads
const CR_READS = { page: "this page", selection: "my highlight", paper: "the whole paper", each_paper: "each paper",
  sections: "each section", template: "each heading", prev: "the step before" };
const CR_WAKE = { manual: "When I press Run", open: "I open a paper", page: "I turn a page", dwell: "I stay on a page",
  highlight: "I highlight", timer: "Every few minutes" };
const CR_OUT_ICON = {
  doc: '<svg viewBox="0 0 24 24"><path d="M6 3h9l4 4v14H6z"/><path d="M9 11h7M9 15h7M9 19h4"/></svg>',
  card: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 10h8M8 14h5"/></svg>',
  say: '<svg viewBox="0 0 24 24"><circle cx="8" cy="12" r="1.6" class="fill"/><circle cx="12" cy="12" r="1.6" class="fill"/><circle cx="16" cy="12" r="1.6" class="fill"/></svg>',
  ask: '<svg viewBox="0 0 24 24"><path d="M9 9a3 3 0 1 1 4 2.8c-.8.4-1 1-1 2.2"/><circle cx="12" cy="18" r="1.2" class="fill"/></svg>',
  highlight: '<svg viewBox="0 0 24 24"><path d="M4 17h16" stroke-width="5" opacity=".5"/><path d="M14 4l5 5-8 8H6v-5z"/></svg>',
};
const CR_OUT_SHORT = { doc: "A document", card: "A canvas card", say: "Dot tells me", ask: "Dot asks me", highlight: "Highlights" };
function crIcon(svg) { const s = h("span", { class: "ico", "aria-hidden": "true" }); s.innerHTML = svg; return s; }
// a creature's body: the same little Dot, in its own colour, with feet and a mouth
function crBody(extra = "") {
  return h("span", { class: `cbod ${extra}` }, h("span", { class: "eyes" }, h("i"), h("i")), h("span", { class: "mouth" }),
    h("span", { class: "ft" }, h("i"), h("i")));
}

async function renderCreatures() {
  const st = { jobs: [], templates: [], runs: [], papers: [], models: [], parallel: 1, queued: 0,
    sel: null, edit: null, shape: null, tab: "talk", doc: null, talk: [], draft: null, sending: false };
  const errs = (e) => e?.body?.detail?.errors?.map((x) => x.message).join(" ")
    || (typeof e?.body?.detail === "string" ? e.body.detail : "") || "That did not work. Try again.";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const alive = () => view.classList.contains("page-creatures");

  // ----- layout -----
  const meter = h("p", { class: "cr-meter", role: "status" });
  const mode = h("span", { class: "cr-mode", hidden: true }, "Stand-in");
  const pen = h("div", { class: "cr-pen", role: "list", "aria-label": "Your creatures" });
  const bench = h("div", { class: "cr-bench", hidden: true });
  const habitat = h("div", { class: "cr-habitat" }, pen, bench);
  const tabs = h("div", { class: "cr-tabs", role: "tablist" });
  const panel = h("div", { class: "cr-panel" });
  view.append(h("section", { class: "cr" },
    h("header", { class: "cr-head" },
      h("div", {}, h("h1", {}, "Creatures ", mode),
        h("p", { class: "cr-sub" }, "Each one reads your papers and leaves you something. Pick one to change it, or tell Dot about a new one.")),
      meter),
    h("div", { class: "cr-body" }, habitat, h("aside", { class: "cr-side" }, tabs, panel))));

  // ----- data -----
  async function load() {
    api("/model/status").then((m) => { st.models = m.models || []; }, () => {});  // the brains list; slow, so it does not hold up the pen
    const [j, t, r, p] = await Promise.all([crApi("/jobs"), crApi("/templates"), crApi("/runs?limit=30"),
      api("/papers?sort=opened").catch(() => ({ papers: [] }))]);
    if (!j.jobs.length && !t.templates.length) { await crApi("/jobs/starters", { method: "POST" }); return load(); }
    Object.assign(st, { jobs: j.jobs, templates: t.templates, runs: r.runs, parallel: r.parallel ?? 1, queued: r.queued ?? 0,
      papers: p.papers || [] });
    mode.hidden = crMode !== "local";
    mode.title = "The backend for creatures is not built yet. Runs here are pretend and stay in this browser.";
  }
  async function refreshRuns() {
    const r = await crApi("/runs?limit=30");
    Object.assign(st, { runs: r.runs, parallel: r.parallel ?? 1, queued: r.queued ?? 0 });
  }
  async function poll() {
    if (!alive()) return;
    try {
      await refreshRuns();
      drawPen();
      if (st.tab === "runs" && !st.doc) drawPanel();
      if (st.edit?.id) paintBig();
    } catch {}
    setTimeout(poll, st.runs.some((x) => x.status === "queued" || x.status === "running") ? 1500 : 5000);
  }

  // ----- the pen: creatures wander, look at you, hop when poked -----
  const lastRun = (job) => st.runs.find((r) => r.job_id === job.id);
  const ordinal = (n) => n + (n % 10 === 1 && n % 100 !== 11 ? "st" : n % 10 === 2 && n % 100 !== 12 ? "nd" : n % 10 === 3 && n % 100 !== 13 ? "rd" : "th");
  function stateOf(job) {
    const r = lastRun(job);
    if (r?.status === "running") return ["working", r.total ? `${r.label} · ${r.done} of ${r.total}` : "Starting"];
    if (r?.status === "queued") {
      const line = st.runs.filter((x) => x.status === "queued").sort((a, b) => a.id - b.id);
      return ["waiting", `Waiting, ${ordinal(line.indexOf(r) + 1)} in line`];
    }
    if (!job.on) return ["asleep", "Asleep"];
    if (r?.status === "done" && !crSeen().has(r.id) && job.output === "doc") return ["done", "Made you something"];
    if (r?.status === "failed") return ["failed", "It went wrong"];
    return ["idle", job.trigger === "manual" ? "Ready" : `Wakes when ${CR_WAKE[job.trigger].toLowerCase()}`];
  }
  const els = new Map();
  function creature(job) {
    const b = h("button", { type: "button", class: "crt", role: "listitem", onclick: () => { hop(b); openBench(job.id); } },
      crBody(), h("span", { class: "ring" }), h("span", { class: "prop", "aria-hidden": "true" }),
      h("span", { class: "zz", "aria-hidden": "true" }, h("i", {}, "z"), h("i", {}, "z"), h("i", {}, "z")),
      h("span", { class: "nm" }), h("span", { class: "stt" }));
    return b;
  }
  const egg = h("button", { type: "button", class: "crt crt-egg", onclick: () => { hop(egg); openBench(null); } },
    h("span", { class: "cbod" }, "+"), h("span", { class: "nm" }, "New creature"), h("span", { class: "stt" }, "Build one, or tell Dot"));
  function hop(b) { b.classList.remove("hop"); void b.offsetWidth; b.classList.add("hop"); }
  function place(b, x, y) { b.style.left = `${x}px`; b.style.top = `${y}px`; b.x = x; b.y = y; }
  function layout() {  // a loose grid of homes, each a little off so the pen does not look like a table
    const W = Math.max(pen.clientWidth, 480), cols = Math.max(2, Math.floor((W - 40) / 190)), cw = (W - 40) / cols;
    [...st.jobs.map((j) => els.get(j.id)), egg].forEach((b, i) => {
      if (!b) return;
      const jit = (k) => ((i * 7919 + k * 104729) % 37) - 18;
      b.home = [20 + (i % cols) * cw + cw / 2 + jit(1), 40 + Math.floor(i / cols) * 200 + jit(2)];
      if (b.x == null) { b.style.transition = "none"; requestAnimationFrame(() => requestAnimationFrame(() => { b.style.transition = ""; })); }
      place(b, ...b.home);
    });
    pen.style.minHeight = `${Math.ceil((st.jobs.length + 1) / cols) * 200 + 80}px`;
  }
  function drawPen() {
    const working = st.runs.filter((r) => r.status === "running").length;
    meter.replaceChildren(h("b", {}, `${working} working`), ` · ${st.queued} waiting · `,
      h("span", { title: "Only this many creatures use the model at once, so your Mac keeps its memory." },
        `${st.parallel} at a time to spare your memory`));
    let added = false;
    const keep = new Set();
    st.jobs.forEach((job, i) => {
      let b = els.get(job.id);
      if (!b) { b = creature(job); els.set(job.id, b); pen.append(b); added = true; }
      keep.add(job.id);
      const [state, line] = stateOf(job);
      const r = lastRun(job);
      if (b.dataset.state !== state && state === "done") hop(b);
      b.dataset.state = state;
      b.classList.toggle("sel", st.sel === job.id);
      b.style.setProperty("--bc", `var(--theme-${job.color ?? 6})`);
      b.style.setProperty("--i", i);
      b.style.setProperty("--p", state === "working" && r.total ? r.done / r.total : 0);
      b.setAttribute("aria-label", `${job.name}: ${line}`);
      b.querySelector(".nm").textContent = job.name;
      b.querySelector(".stt").textContent = line;
    });
    for (const [id, b] of els) if (!keep.has(id)) { b.remove(); els.delete(id); added = true; }
    if (!egg.isConnected) { pen.append(egg); added = true; }
    if (added) layout();
  }
  // wander: idle creatures stroll around their home now and then
  const wander = setInterval(() => {
    if (!alive()) { clearInterval(wander); return; }
    if (reduce || pen.hidden) return;
    for (const b of els.values()) {
      if (!["idle", "done"].includes(b.dataset.state) || Math.random() < 0.55 || !b.home) continue;
      const nx = b.home[0] + (Math.random() * 2 - 1) * 60, ny = b.home[1] + (Math.random() * 2 - 1) * 26;
      b.classList.toggle("flip", nx < b.x);
      b.classList.add("walk");
      place(b, nx, ny);
      clearTimeout(b.wt); b.wt = setTimeout(() => b.classList.remove("walk"), 2300);
    }
  }, 2800);
  // eyes follow the pointer
  let look = 0;
  habitat.addEventListener("pointermove", (e) => {
    if (look) return;
    look = requestAnimationFrame(() => {
      look = 0;
      habitat.querySelectorAll(".crt:not(.crt-egg), .cr-big").forEach((b) => {
        const r = b.querySelector(".cbod").getBoundingClientRect();
        const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2), d = Math.hypot(dx, dy) || 1;
        const k = Math.min(1, d / 220) * (b.classList.contains("cr-big") ? 6 : 4);
        b.style.setProperty("--ex", `${(dx / d) * k}px`); b.style.setProperty("--ey", `${(dy / d) * k}px`);
      });
    });
  });
  addEventListener("resize", () => { if (alive() && !pen.hidden) layout(); });

  // ----- the bench: paper(s) -> creature -> what it leaves you -----
  const blank = () => ({ name: "", color: Math.floor(Math.random() * 8), trigger: "manual", every: 120, output: "doc", papers: [],
    template_id: null, on: true, steps: [{ scope: "sections", prompt: "", model: "" }] });
  function openBench(id, job) {
    st.sel = id;
    st.edit = job ? structuredClone(job) : id ? structuredClone(st.jobs.find((j) => j.id === id)) : blank();
    const t = st.templates.find((x) => x.id === st.edit.template_id);
    st.shape = t ? structuredClone(t) : null;
    const r = id && lastRun(st.edit);
    if (r?.status === "done" && st.edit.output === "doc" && !crSeen().has(r.id)) { crMarkSeen(r.id); st.doc = r; st.tab = "runs"; }
    else if (id) { st.tab = "runs"; st.doc = null; }
    pen.hidden = true; bench.hidden = false;
    drawBench(); drawPen(); drawTabs(); drawPanel();
    habitat.scrollTop = 0;
  }
  function closeBench() {
    st.sel = null; st.edit = null; st.shape = null;
    bench.hidden = true; pen.hidden = false;
    drawPen(); layout(); drawPanel();
  }
  let big = null;
  function paintBig() {
    if (!big || !st.edit) return;
    const j = st.edit, saved = j.id && st.jobs.find((x) => x.id === j.id);
    big.style.setProperty("--bc", `var(--theme-${j.color ?? 6})`);
    big.dataset.state = saved ? stateOf(saved)[0] : j.on ? "idle" : "asleep";
    const r = saved && lastRun(saved);
    big.style.setProperty("--p", r?.status === "running" && r.total ? r.done / r.total : 0);
    if (!j.on) big.dataset.state = "asleep";
  }
  const nod = () => { big?.classList.remove("nod"); void big?.offsetWidth; big?.classList.add("nod"); };
  const chip = (label, on, click, attrs = {}) => h("button", { type: "button", class: "cr-chip", "aria-pressed": String(on), onclick: click, ...attrs }, label);

  function drawBench() {
    const j = st.edit;
    const msg = h("p", { class: "cr-err", role: "alert" });
    const runOn = crSelect(Object.fromEntries(st.papers.map((p) => [p.id, p.title])), st.papers[0]?.id || "", { class: "cr-pill wide", "aria-label": "Run on paper" });
    // what it reads
    const inSlot = h("div", { class: "slot slot-in" });
    function drawIn() {
      const fixed = j.papers.length > 0 || inSlot.dataset.fixed === "1";
      runOn.hidden = j.papers.length > 0;
      inSlot.replaceChildren(...[
        h("h3", {}, "Reads"),
        h("div", { class: "cr-choice" },
          chip("The paper I'm reading", !fixed, () => { j.papers = []; inSlot.dataset.fixed = "0"; drawIn(); nod(); }),
          chip("Papers I choose", fixed, () => { inSlot.dataset.fixed = "1"; drawIn(); nod(); })),
        fixed ? h("div", { class: "cr-sheets" }, st.papers.map((p) => {
          const on = j.papers.includes(p.id);
          return h("button", { type: "button", class: "sheet", "aria-pressed": String(on), title: p.title,
            onclick: () => { j.papers = on ? j.papers.filter((x) => x !== p.id) : [...j.papers, p.id]; drawIn(); nod(); } }, h("span", {}, p.title));
        })) : h("div", { class: "cr-sheets one" }, h("span", { class: "sheet ghost" }, h("span", {}, "Whichever paper is open"))),
        h("h3", {}, "Wakes up"),
        h("div", { class: "cr-choice" }, Object.entries(CR_WAKE).map(([k, t]) => chip(t, j.trigger === k, () => { j.trigger = k; drawIn(); nod(); }))),
        ["dwell", "timer"].includes(j.trigger) ? h("label", { class: "cr-inline" },
          j.trigger === "dwell" ? "after" : "every",
          h("input", { type: "number", min: 20, max: 3600, step: 10, value: j.every, "aria-label": "Seconds", oninput: (e) => { j.every = +e.target.value; } }),
          "seconds") : null].filter(Boolean));
    }
    drawIn();

    // the creature: its look, its name, what it does
    big = h("div", { class: "cr-big" }, crBody(), h("span", { class: "ring" }), h("span", { class: "zz", "aria-hidden": "true" }, h("i", {}, "z"), h("i", {}, "z"), h("i", {}, "z")));
    paintBig();
    const name = h("input", { class: "cr-name", value: j.name, maxlength: 80, placeholder: "Name me", "aria-label": "Creature name",
      oninput: () => { j.name = name.value; } });
    const colors = h("div", { class: "cr-colors", role: "radiogroup", "aria-label": "Colour" }, [...Array(8)].map((_, i) =>
      h("button", { type: "button", role: "radio", "aria-checked": String(j.color === i), "aria-label": `Colour ${i + 1}`, style: `--bc: var(--theme-${i})`,
        onclick: () => { j.color = i; colors.querySelectorAll("button").forEach((b, k) => b.setAttribute("aria-checked", String(k === i))); paintBig(); nod(); } })));
    const awake = chip(j.on ? "Awake" : "Asleep", j.on, () => { j.on = !j.on; awake.textContent = j.on ? "Awake" : "Asleep"; awake.setAttribute("aria-pressed", String(j.on)); paintBig(); });
    const steps = h("ol", { class: "cr-thoughts" });
    const brains = { "": "usual brain", ...Object.fromEntries(st.models.map((m) => [m, m.split("/").pop().replace(/-GGUF$/i, "")])) };
    function drawSteps() {
      steps.replaceChildren(...j.steps.map((s, i) => {
        const say = h("textarea", { rows: 2, maxlength: 4000, placeholder: i ? "Then what?" : "What should I do?", "aria-label": `Step ${i + 1}`,
          onfocus: () => big.classList.add("listen"), onblur: () => big.classList.remove("listen"),
          oninput: () => { s.prompt = say.value; say.style.height = "auto"; say.style.height = `${say.scrollHeight}px`; } });
        say.value = s.prompt;
        requestAnimationFrame(() => { say.style.height = `${say.scrollHeight}px`; });
        const reads = crSelect(CR_READS, s.scope, { class: "cr-pill", "aria-label": `Step ${i + 1} reads`, onchange: () => { s.scope = reads.value; } });
        const brain = crSelect(brains, s.model, { class: "cr-pill", "aria-label": `Step ${i + 1} model`, onchange: () => { s.model = brain.value; } });
        if (s.model && !st.models.includes(s.model)) brain.append(h("option", { value: s.model, selected: true }, s.model));
        return h("li", {},
          h("div", { class: "cr-pills" }, h("span", {}, i ? "then reads" : "reads"), reads, h("span", {}, "with"), brain,
            j.steps.length > 1 ? h("button", { type: "button", class: "x", "aria-label": `Forget step ${i + 1}`, onclick: () => { j.steps.splice(i, 1); drawSteps(); } }, "×") : null),
          say);
      }));
    }
    drawSteps();
    const teach = h("button", { type: "button", class: "cr-teach", onclick: () => {
      if (j.steps.length >= 8) return;
      j.steps.push({ scope: "prev", prompt: "", model: "" }); drawSteps(); steps.lastChild.querySelector("textarea").focus(); nod();
    } }, "+ then…");
    const meSlot = h("div", { class: "slot slot-me" }, big, name, h("div", { class: "cr-row center" }, colors, awake), steps, teach);

    // what it leaves you
    const outSlot = h("div", { class: "slot slot-out" });
    function drawOut() {
      const tiles = h("div", { class: "cr-tiles" }, Object.keys(CR_OUT_SHORT).map((k) =>
        h("button", { type: "button", class: "tile", "aria-pressed": String(j.output === k),
          onclick: () => { j.output = k; drawOut(); nod(); } }, crIcon(CR_OUT_ICON[k]), h("span", {}, CR_OUT_SHORT[k]))));
      let shape = null;
      if (j.output === "doc") {
        const pick = (t) => { st.shape = t ? structuredClone(t) : null; j.template_id = t?.id ?? null; drawOut(); };
        shape = h("div", { class: "cr-shape" },
          h("h3", {}, "Shaped like"),
          h("div", { class: "cr-choice" },
            chip("Free-form", !st.shape, () => pick(null)),
            st.templates.map((t) => chip(t.name, st.shape?.id === t.id, () => pick(t))),
            chip("+ New shape", !!st.shape && !st.shape.id, () => { st.shape = { name: j.name ? `${j.name} shape` : "", sections: [{ title: "", ask: "" }] }; j.template_id = null; drawOut(); })),
          st.shape ? paperOf(st.shape) : h("div", { class: "cr-paper free" }, h("i"), h("i"), h("i"), h("i", { class: "short" })));
      }
      outSlot.replaceChildren(...[h("h3", {}, "Leaves you"), tiles, shape].filter(Boolean));
    }
    // the template as the sheet it will fill: one heading and its ask per line
    function paperOf(t) {
      const list = h("ol", {});
      const draw = () => list.replaceChildren(...t.sections.map((s, i) => {
        const title = h("input", { value: s.title, maxlength: 120, placeholder: "Heading", "aria-label": `Heading ${i + 1}`, oninput: () => { s.title = title.value; } });
        const ask = h("textarea", { rows: 1, maxlength: 1000, placeholder: "What goes here?", "aria-label": `What goes under heading ${i + 1}`,
          oninput: () => { s.ask = ask.value; ask.style.height = "auto"; ask.style.height = `${ask.scrollHeight}px`; } });
        ask.value = s.ask;
        requestAnimationFrame(() => { ask.style.height = `${ask.scrollHeight}px`; });
        return h("li", {}, h("div", { class: "cr-row" }, title,
          t.sections.length > 1 ? h("button", { type: "button", class: "x", "aria-label": `Remove heading ${i + 1}`, onclick: () => { t.sections.splice(i, 1); draw(); } }, "×") : null), ask);
      }));
      draw();
      const nm = h("input", { class: "cr-paper-name", value: t.name, maxlength: 80, placeholder: "Name this shape", "aria-label": "Shape name", oninput: () => { t.name = nm.value; } });
      return h("div", { class: "cr-paper" }, nm, list,
        h("button", { type: "button", class: "cr-teach", onclick: () => { t.sections.push({ title: "", ask: "" }); draw(); list.lastChild.querySelector("input").focus(); } }, "+ heading"),
        t.id ? h("button", { type: "button", class: "cr-link danger", onclick: async () => {
          if (!confirm(`Delete the ${t.name} shape? Creatures using it go free-form.`)) return;
          await crApi(`/templates/${t.id}`, { method: "DELETE" });
          st.templates = st.templates.filter((x) => x.id !== t.id); st.jobs.forEach((x) => { if (x.template_id === t.id) x.template_id = null; });
          st.shape = null; j.template_id = null; drawOut();
        } }, "Delete this shape") : null);
    }
    drawOut();

    const arrow = () => h("div", { class: "cr-arrow", "aria-hidden": "true" }, h("i"));
    bench.replaceChildren(
      h("div", { class: "cr-benchtop" }, h("button", { type: "button", class: "cr-back", onclick: closeBench }, "← All creatures")),
      h("div", { class: "cr-flow" }, inSlot, arrow(), meSlot, arrow(), outSlot),
      h("div", { class: "cr-benchbar" }, msg,
        j.id ? h("button", { type: "button", class: "cr-link danger", onclick: () => deleteJob(j) }, "Let it go") : null,
        runOn,
        h("button", { type: "button", class: "btn", onclick: () => runJob(j, j.papers.length ? null : runOn.value, msg) }, "Run now"),
        h("button", { type: "button", class: "btn primary", onclick: () => saveJob(j, msg) }, j.id ? "Save" : "Hatch it")));
  }

  async function saveJob(j, msg, stay = false) {  // stay: keep the bench open (Run saves first)
    try {
      if (j.output === "doc" && st.shape) {  // a new or changed shape is saved with its creature
        const t = st.shape;
        t.sections = t.sections.filter((s) => s.title.trim());
        if (!t.name?.trim()) t.name = `${j.name || "My"} shape`;
        const was = st.templates.find((x) => x.id === t.id);
        if (!was || JSON.stringify(was) !== JSON.stringify(t)) {
          const { id, ...body } = t;
          const saved = id ? await crPost(`/templates/${id}`, body, "PUT") : await crPost("/templates", body);
          st.templates = was ? st.templates.map((x) => (x.id === saved.id ? saved : x)) : [...st.templates, saved];
          st.shape = structuredClone(saved);
        }
        j.template_id = st.shape.id;
      }
      const { id, ...body } = j;
      const saved = id ? await crPost(`/jobs/${id}`, body, "PUT") : await crPost("/jobs", body);
      const i = st.jobs.findIndex((x) => x.id === saved.id);
      if (i < 0) st.jobs.push(saved); else st.jobs[i] = saved;
      if (stay) { j.id = saved.id; st.sel = saved.id; drawPen(); return saved; }
      closeBench();
      const b = els.get(saved.id);
      if (b) { b.classList.add(id ? "hop" : "hatch"); setTimeout(() => b.classList.remove("hatch"), 900); }
      buddy.say(id ? `${saved.name} is ready.` : `${saved.name} hatched.`, { mood: "happy" });
    } catch (e) { msg.textContent = errs(e); }
    return null;
  }
  async function runJob(j, paperId, msg) {
    try {
      if (!(await saveJob(j, msg, true))) return;
      const paper = st.papers.find((p) => p.id === paperId)?.title || "";
      await crPost(`/jobs/${j.id}/run`, { paper_id: paperId || undefined, paper });
      await refreshRuns();
      drawPen(); paintBig(); st.tab = "runs"; st.doc = null; drawTabs(); drawPanel();
      msg.textContent = "";
      nod();
      poll();
    } catch (e) { msg.textContent = errs(e); }
  }
  async function deleteJob(j) {
    if (!confirm(`Let ${j.name} go? Its runs stay in the list.`)) return;
    try {
      await crApi(`/jobs/${j.id}`, { method: "DELETE" });
      st.jobs = st.jobs.filter((x) => x.id !== j.id);
      closeBench();
    } catch (e) { buddy.say(errs(e), { mood: "worried" }); }
  }

  // ----- the side: talk to Dot, and what the creatures made -----
  function drawTabs() {
    tabs.replaceChildren(...[["talk", "Talk to Dot"], ["runs", st.sel ? "Its runs" : "Runs"]].map(([k, label]) =>
      h("button", { type: "button", role: "tab", "aria-selected": String(st.tab === k),
        onclick: () => { st.tab = k; st.doc = null; drawTabs(); drawPanel(); } }, label)));
  }
  function drawPanel() { panel.replaceChildren(st.tab === "talk" ? talkPanel() : runsPanel()); }

  function talkPanel() {
    const av = () => h("i", { class: "cr-av", "aria-hidden": "true" });
    const log = h("div", { class: "cr-log", "aria-live": "polite" },
      h("p", { class: "cr-msg dot" }, av(), "What should a creature do while you read? Say it plainly, like: every time I stay on a page, ask me a question."),
      st.talk.map((m) => h("p", { class: `cr-msg ${m.role === "user" ? "you" : "dot"}` }, m.role === "user" ? null : av(), m.content)),
      st.sending ? h("p", { class: "cr-msg dot thinking" }, av(), "Thinking") : null);
    const input = h("textarea", { class: "cr-input", rows: 2, maxlength: 2000, placeholder: "Tell Dot what to do", "aria-label": "Tell Dot what to do",
      onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); } } });
    const out = h("div", { class: "cr-talk" }, log,
      st.draft ? draftCard(st.draft) : null,
      !st.talk.length ? h("div", { class: "cr-chips" }, CR_SUGGEST.map((s) => h("button", { type: "button", onclick: () => send(s) }, s))) : null,
      h("form", { class: "cr-say", onsubmit: (e) => { e.preventDefault(); send(input.value); } }, input,
        h("button", { class: "btn", type: "submit", disabled: st.sending }, "Send")));
    requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
    return out;
  }
  async function send(text) {
    text = text.trim();
    if (!text || st.sending) return;
    st.talk.push({ role: "user", content: text });
    st.sending = true; drawPanel();
    try {
      const r = await crPost("/dot/talk", { messages: st.talk });
      st.talk.push({ role: "assistant", content: r.reply || r.error || "I lost my words. Say it again?" });
      st.draft = r.job || st.draft;
    } catch (e) { st.talk.push({ role: "assistant", content: errs(e) }); }
    st.sending = false; drawPanel();
  }
  function draftCard(j) {
    return h("div", { class: "cr-draft", style: `--bc: var(--theme-${j.color ?? 6})` },
      h("div", { class: "cr-draft-flow" },
        h("span", {}, j.papers?.length ? `${j.papers.length} papers` : "Your paper"), h("i", { "aria-hidden": "true" }, "→"),
        h("span", { class: "egg", "aria-hidden": "true" }), h("b", {}, j.name), h("i", { "aria-hidden": "true" }, "→"),
        h("span", {}, CR_OUT_SHORT[j.output] || j.output)),
      h("ol", {}, j.steps.map((s) => h("li", {}, h("em", {}, `${CR_READS[s.scope] || s.scope}: `), s.prompt))),
      h("div", { class: "cr-row" },
        h("button", { class: "btn primary", type: "button", onclick: () => { st.draft = null; openBench(null, j); } }, "Put it on the bench")));
  }

  function runsPanel() {
    if (st.doc) return docView(st.doc);
    const runs = st.sel ? st.runs.filter((r) => r.job_id === st.sel) : st.runs;
    if (!runs.length) return h("p", { class: "cr-hint" }, st.sel ? "It has not run yet. Press Run now." : "Nothing has run yet.");
    const label = { queued: "Waiting", running: "Working", done: "Done", failed: "Failed", stopped: "Stopped" };
    return h("ul", { class: "cr-runs" }, runs.map((r) => h("li", { "data-status": r.status },
      h("div", { class: "cr-row" }, h("b", {}, r.job), h("span", { class: "pill" }, label[r.status] || r.status)),
      h("small", {}, [r.paper, r.created_at?.slice(5, 16)].filter(Boolean).join(" · ")),
      r.status === "running" || r.status === "queued" ? h("div", { class: "cr-bar", role: "progressbar", "aria-valuemin": 0,
        "aria-valuemax": r.total || 1, "aria-valuenow": r.done || 0, "aria-label": `${r.job} progress` },
        h("i", { style: `width: ${r.total ? (100 * r.done) / r.total : 0}%` })) : null,
      r.status === "running" && r.label ? h("small", {}, `On ${r.label}`) : null,
      r.status === "failed" ? h("small", { class: "cr-err" }, r.error || "Something went wrong.") : null,
      h("div", { class: "cr-row" },
        ["queued", "running"].includes(r.status) ? h("button", { type: "button", class: "btn", onclick: async () => {
          await crApi(`/runs/${r.id}/stop`, { method: "POST" }); await refreshRuns(); drawPen(); drawPanel(); paintBig();
        } }, "Stop") : null,
        r.status === "done" ? h("button", { type: "button", class: "btn", onclick: () => { crMarkSeen(r.id); st.doc = r; drawPanel(); drawPen(); } }, "Read") : null))));
  }
  function docView(r) {
    const res = r.result || {};
    const md = `# ${r.job}${r.paper ? `: ${r.paper}` : ""}\n\n` + (res.sections?.length
      ? res.sections.map(([t, x]) => `## ${t}\n\n${x}`).join("\n\n") : res.text || "");
    const copy = h("button", { type: "button", class: "btn", onclick: async () => {
      try { await navigator.clipboard.writeText(md); copy.textContent = "Copied"; } catch { copy.textContent = "Could not copy"; }
    } }, "Copy as Markdown");
    return h("article", { class: "cr-doc" },
      h("div", { class: "cr-row" }, h("button", { type: "button", class: "btn", onclick: () => { st.doc = null; drawPanel(); } }, "Back"), copy),
      h("h2", {}, r.job), r.paper ? h("p", { class: "cr-sub" }, r.paper) : null,
      res.sections?.length ? res.sections.map(([t, x]) => h("section", {}, h("h3", {}, t), h("div", { class: "cr-text" }, x)))
        : h("div", { class: "cr-text" }, res.text || "It left nothing."));
  }

  try { await load(); }
  catch { view.append(h("p", { class: "cr-err" }, "Could not load the creatures. Is the app running?")); return; }
  drawPen(); drawTabs(); drawPanel(); layout();
  poll();
  greet("creatures", "These are my creatures. Each reads your papers and leaves you something. Poke one to change it.");
}
