"use strict";

// ---------- helpers ----------
const $ = (sel, el = document) => el.querySelector(sel);

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  el.append(...kids.flat().filter((k) => k != null));
  return el;
}

// calls that wait on the local model: Dot shows it is working while they run
const MODEL_CALL = /\/(explain|ask|test-connection)$|^\/graph\/(index|search|suggest)$/;

async function api(path, opts = {}) {
  const working = MODEL_CALL.test(path);
  if (working) buddy.busy(1);
  try {
    const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...opts.headers } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(r.statusText), { body, status: r.status });
    return body;
  } finally {
    if (working) buddy.busy(-1);
  }
}

// ---------- model status chip ----------
const chip = $("#model-chip");
const chipLabel = $("#model-chip .chip-label");
let lastStatus = { status: "unknown", models: [] };

async function refreshChip() {
  chip.dataset.status = "checking";
  chipLabel.textContent = "Checking model";
  paintConn();
  try { lastStatus = await api("/model/status"); }
  catch { lastStatus = { status: "error", label: "App error", models: [] }; }
  const before = chip.dataset.prev;
  chip.dataset.status = chip.dataset.prev = lastStatus.status;
  chipLabel.textContent = chip.title = lastStatus.label;
  buddy.status(lastStatus.status);
  paintConn();
  if (lastStatus.status !== before) buddyOnStatus(lastStatus.status, before);
  return lastStatus;
}

function buddyOnStatus(now, before) {
  const toSettings = { label: "Open Settings", href: "#settings/connection" };
  if (now === "not_running") {
    buddy.say("I cannot reach the model. Start Unsloth on your Mac, then I can help with AI summaries and checks.",
      { mood: "worried", actions: [toSettings] });
  } else if (now === "wrong_key") {
    buddy.say("The model is running, but the API key is wrong. Paste the key that Unsloth shows.",
      { mood: "worried", actions: [toSettings] });
  } else if (now === "ready" && before && before !== "ready" && before !== "checking") {
    buddy.say("The model is back. We are good to go.", { mood: "happy" });
  }
}

// Pop up a page's greeting only the first time you visit it in this session.
const greeted = new Set();
function greet(key, text, opts = {}) {
  buddy.say(text, { ...opts, pop: !greeted.has(key) && opts.pop !== false });
  greeted.add(key);
}
chip.addEventListener("click", refreshChip);
setInterval(refreshChip, 30000);

// ---------- router ----------
const view = $("#view");
const pages = { library: renderLibrary, read: renderReader, graph: renderGraph, settings: renderSettings };

function route() {
  const [name, arg, extra] = location.hash.replace(/^#/, "").split("/");
  if (!pages[name]) { location.hash = "#library"; return; }
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === name));
  $("#page-extra").replaceChildren();
  view.replaceChildren();
  view.className = `page page-${name}`;
  buddy.hide();
  pages[name](arg, extra);
}
window.addEventListener("hashchange", route);

// ---------- Library ----------
const lib = { q: "", status: "all", sort: "date", theme: "" };
let themeList = []; // [{id, name, color, papers}], loaded with the Library
const STATUSES = [["all", "All"], ["not_started", "Not started"], ["in_progress", "In progress"],
  ["notes_done", "Notes done"], ["reflection_done", "Reflection done"]];
const SORTS = [["date", "Presentation date"], ["opened", "Last opened"], ["title", "Title"], ["progress", "Progress"]];
const PRIMER = { not_made: "Not made", making: "Making", ready: "Ready", failed: "Failed" };

// Start (or follow) the AI summary for a paper. The server streams progress as Server-Sent Events;
// onEvent gets {state, done, total, step, error} each time. Resolves with the last event.
async function streamPrimer(id, onEvent) {
  buddy.busy(1);
  let last = { state: "failed", error: "Could not reach the app. Is it still running?" };
  try {
    const r = await fetch(`/papers/${id}/primer`, { method: "POST" });
    if (!r.ok) throw new Error(String(r.status));
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) if (part.startsWith("data: ")) { last = JSON.parse(part.slice(6)); onEvent?.(last); }
    }
  } catch { onEvent?.(last); } finally { buddy.busy(-1); }
  return last;
}
const primerLabel = (e) => (e.state === "making" ? (e.total ? `AI summary: step ${Math.min(e.done + 1, e.total)} of ${e.total}` : "AI summary: starting")
  : `AI summary ${PRIMER[e.state]?.toLowerCase() ?? ""}`);
const AI_SUMMARY_TIP = "A short summary of the paper, written by the AI model on your Mac. It is split into the reading steps and stays closed until you write your own notes.";

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const daysFromToday = (iso) => Math.round((new Date(`${iso}T00:00`) - new Date(new Date().toDateString())) / 864e5);
function fmtDate(iso) {
  return new Date(`${iso}T00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}
function relDays(iso) {
  const d = daysFromToday(iso);
  if (d === 0) return "today";
  if (d === 1) return "tomorrow";
  if (d === -1) return "yesterday";
  return d > 0 ? `in ${d} days` : `${-d} days ago`;
}
function ago(ts) {
  if (!ts) return "Never";
  const min = Math.round((Date.now() - new Date(`${ts.replace(" ", "T")}Z`)) / 6e4);
  if (min < 1) return "Just now";
  if (min < 60) return `${min} min ago`;
  if (min < 60 * 24) return `${Math.round(min / 60)} h ago`;
  return `${Math.round(min / 1440)} days ago`;
}
function fmtSpent(sec) {
  const m = Math.round(sec / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

async function renderLibrary() {
  const [s, fw, list, th] = await Promise.all([api("/settings"), api("/frameworks"), loadPapers(), api("/themes")]);
  themeList = th.themes;
  const page = h("div", { class: "library" });
  view.append(page);
  // The agenda shows every dated paper, even when a filter or search narrows the list.
  const draw = async (data) => {
    const all = lib.q || lib.status !== "all" || lib.theme ? (await api("/papers")).papers : data.papers;
    page.replaceChildren(libHead(data, s, all), data.total ? libBody(data, s, fw, nextTalk(all)?.id) : libEmpty(fw.paper));
  };
  await draw(list);
  enablePageDrop(page);
  libraryGreeting(list);
  libRedraw = async () => { themeList = (await api("/themes")).themes; await draw(await loadPapers()); };
  // a summary still being made (you came back mid-way): follow it so its chip counts up
  for (const p of list.papers.filter((x) => x.primer_status === "making")) {
    streamPrimer(p.id, (e) => { const el = document.querySelector(`[data-primer="${p.id}"]`); if (el) el.textContent = primerLabel(e); })
      .then(() => { if (location.hash.startsWith("#library") || !location.hash) libRedraw(); });
  }
}
let libRedraw = async () => {};

function libraryGreeting(data) {
  if (!data.total) {
    return greet("lib-empty", "Hi, I am Dot. Drop your first PDF anywhere on this page. I will read the title and authors for you.", { mood: "happy" });
  }
  const next = nextTalk(data.papers);
  if (next) {
    const left = next.progress.length - next.steps_done;
    greet("lib", `Your next talk is "${next.title}", ${relDays(next.presentation_date)}. ` +
      (left ? `${left} steps to go.` : "Your notes are done. Time for the reflection."),
      { mood: daysFromToday(next.presentation_date) <= 2 && left ? "surprised" : "idle",
        actions: [{ label: "Open it", href: `#read/${next.id}` }] });
  } else {
    greet("lib", "No talks with a date coming up. Add a presentation date with More, then Edit details.");
  }
}

const nextTalk = (papers) => papers.filter((p) => p.presentation_date && daysFromToday(p.presentation_date) >= 0)
  .sort((a, b) => a.presentation_date.localeCompare(b.presentation_date))[0];

function loadPapers() {
  return api(`/papers?${new URLSearchParams(lib)}`);
}

function libHead(data, s, all) {
  return h("header", { class: "lib-head" },
    h("h1", {}, "Library"),
    h("span", { class: "stat" }, h("span", { class: "dotnum" }, String(data.total)), data.total === 1 ? "paper" : "papers"),
    h("span", { class: "stat" }, h("span", { class: "dotnum" }, `${data.reflections_done}/${s.reflections_target}`), "reflections done"),
    data.total ? agenda(all) : null);
}

// The next 14 days as a dot-matrix strip: a lit column is a talk, the next talk wears the marker.
let agendaPlayed = false;
function agenda(papers) {
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const byDay = Object.groupBy(papers.filter((p) => p.presentation_date), (p) => p.presentation_date);
  const next = nextTalk(papers);
  const days = Array.from({ length: 14 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return d; });
  const inRange = days.reduce((n, d) => n + (byDay[iso(d)]?.length ?? 0), 0);
  const summary = !next ? "No talks with a date coming up."
    : `${inRange ? plural(inRange, "talk") : "No talks"} in this window. Next talk ${fmtDate(next.presentation_date)}, ${relDays(next.presentation_date)}.`;
  const intro = !agendaPlayed; agendaPlayed = true;
  return h("div", { class: `agenda${intro ? " intro" : ""}` },
    h("ol", { class: "agenda-days", "aria-hidden": "true" }, days.map((d, i) => {
      const talks = byDay[iso(d)] ?? [];
      const isNext = next && next.presentation_date === iso(d);
      return h("li", { class: [i === 0 && "today", talks.length && "talk", isNext && "next"].filter(Boolean).join(" "),
        style: `--i:${i}`, title: [fmtDate(iso(d)), ...talks.map((p) => p.title)].join("\n") },
        h("span", { class: "wd" }, d.toLocaleDateString("en-GB", { weekday: "narrow" })),
        h("span", { class: "col" }, h("i"), h("i"), h("i"), h("i")),
        h("span", { class: "dn" }, h("span", { class: isNext ? "hl" : "" }, String(d.getDate()))));
    })),
    h("p", { class: "agenda-cap" }, h("span", { class: "agenda-label" }, "Next 14 days"), h("span", { class: "quiet" }, summary)));
}

function filePicker() {
  const input = h("input", { type: "file", accept: "application/pdf,.pdf", hidden: true,
    onchange: () => input.files[0] && addPaper(input.files[0]) });
  return input;
}

function libEmpty(fw) {
  const total = fw.steps.reduce((t, st) => t + st.minutes, 0);
  const picker = filePicker();
  return h("div", { class: "lib-empty" },
    h("div", { class: "sheet-drop", "data-drop": "" },
      h("h2", {}, "Add the first paper you need to read."),
      h("p", { class: "quiet" }, "Drop a PDF on this page, or choose one from your Mac."),
      dropGlyph(),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: () => picker.click() }, "Choose PDF"),
        h("span", { class: "quiet small upload-msg", "aria-live": "polite" }), picker)),
    h("section", { class: "path" },
      h("h2", {}, "How you will read it"),
      h("p", {}, `Every paper goes through the same ${fw.steps.length} steps, about `,
        h("span", { class: "num" }, `${total}`), " minutes in all. Write your own notes first. The model checks them after."),
      h("ol", {}, fw.steps.map((st) => h("li", {},
        h("span", { class: "num n" }, String(st.n)),
        h("span", {}, h("span", { class: "title" }, st.title),
          st.look_in.length ? h("span", { class: "look" }, `  in ${st.look_in.join(", ")}`) : null),
        h("span", { class: "num quiet" }, `${st.minutes} min`))))));
}

// A dot-matrix arrow into a tray. It drops one row while you hover or drag a file over the page.
const DROP = [".....#.....", ".....#.....", ".....#.....", "..#..#..#..", "...#.#.#...", "....###....", ".....#.....",
  "...........", "#.........#", "###########"];
function dropGlyph() {
  return h("span", { class: "dm", "aria-hidden": "true" }, DROP.flatMap((line, y) =>
    [...line].map((c) => h("i", { class: c === "#" ? (y < 7 ? "a" : "t") : "" }))));
}

function libBody(data, s, fw, nextId) {
  const picker = filePicker();
  let timer;
  const search = h("input", { type: "search", placeholder: "Search titles, authors, tags and notes",
    value: lib.q, "aria-label": "Search papers",
    oninput: () => { clearTimeout(timer); timer = setTimeout(() => { lib.q = search.value; refreshList(); }, 250); } });
  const filters = h("div", { class: "segmented", role: "group", "aria-label": "Show papers" },
    STATUSES.map(([id, label]) => h("button", { type: "button", "aria-pressed": String(lib.status === id),
      onclick: (e) => { lib.status = id;
        filters.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
        refreshList(); } }, label)));
  const sort = h("select", { "aria-label": "Sort by", onchange: () => { lib.sort = sort.value; refreshList(); } },
    SORTS.map(([id, label]) => h("option", { value: id, selected: lib.sort === id }, `Sort: ${label}`)));
  const listEl = h("div", { class: "paper-list" });

  async function refreshList() {
    const [d, all] = await Promise.all([loadPapers(), api("/papers")]);
    listEl.replaceChildren(paperTable(d.papers, s, fw, nextTalk(all.papers)?.id));
  }
  listEl.append(paperTable(data.papers, s, fw, nextId));

  return h("div", { class: "lib-main" },
    h("div", { class: "toolbar" }, search, sort,
      h("button", { class: "btn", type: "button", onclick: () => picker.click() }, "Add paper"), picker),
    h("div", { class: "toolbar-2" }, filters,
      h("span", { class: "quiet small upload-msg", "aria-live": "polite" }, "You can also drop a PDF anywhere on this page.")),
    themeBar(), listEl);
}

// Themes: your own topic groups. Click one to show only its papers; papers with none are "Unsorted".
const themeDot = (t) => h("i", { class: "tdot", style: `--tc:var(--theme-${t.color})` });
function themeBar() {
  const pick = (id) => { lib.theme = lib.theme === id ? "" : id; libRedraw(); };
  const name = h("input", { type: "text", placeholder: "New theme", maxlength: 40, "aria-label": "Name of the new theme" });
  const err = h("span", { class: "status err", "aria-live": "polite" });
  const add = h("form", { class: "tadd", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    try { await api("/themes", { method: "POST", body: JSON.stringify({ name: name.value }) }); libRedraw(); }
    catch (x) { err.textContent = x.body?.detail?.errors?.name ?? "Could not add the theme."; }
  } }, name, h("button", { type: "submit", class: "btn ghost" }, "Add"), err);
  return h("div", { class: "themebar", role: "group", "aria-label": "Themes" },
    h("span", { class: "tlabel" }, "Themes"),
    h("button", { type: "button", class: "tchip", "aria-pressed": String(!lib.theme), onclick: () => pick("") }, "All"),
    themeList.map((t) => h("span", { class: "tchip-wrap" },
      h("button", { type: "button", class: "tchip", "aria-pressed": String(lib.theme === t.id), onclick: () => pick(t.id) },
        themeDot(t), t.name, h("span", { class: "tn" }, String(t.papers))),
      h("button", { type: "button", class: "tdel", "aria-label": `Delete the theme ${t.name}`, title: "Delete theme",
        onclick: async () => {
          if (!confirm(`Delete the theme "${t.name}"? Papers stay in the library, only the theme goes.`)) return;
          await api(`/themes/${t.id}`, { method: "DELETE" }).catch(() => {});
          if (lib.theme === t.id) lib.theme = "";
          libRedraw();
        } }, "×"))),
    themeList.length ? h("button", { type: "button", class: "tchip", "aria-pressed": String(lib.theme === "none"), onclick: () => pick("none") }, "Unsorted") : null,
    add);
}

// The theme picker on a card: tick themes, or make a new one and put the paper in it at once.
function themePicker(p) {
  const menu = h("details", { class: "menu tpick" });
  const save = async (ids) => { await api(`/papers/${p.id}/themes`, { method: "PUT", body: JSON.stringify({ ids }) }); libRedraw(); };
  const name = h("input", { type: "text", placeholder: "New theme", maxlength: 40, "aria-label": "New theme for this paper" });
  menu.append(h("summary", { class: "pchip add", "aria-label": `Themes for ${p.title}` }, p.themes.length ? "Edit themes" : "+ Theme"),
    h("div", { class: "menu-list" },
      themeList.map((t) => h("label", { class: "tcheck" },
        h("input", { type: "checkbox", checked: p.themes.includes(t.id),
          onchange: (e) => save(e.target.checked ? [...p.themes, t.id] : p.themes.filter((x) => x !== t.id)) }),
        themeDot(t), t.name)),
      themeList.length ? h("hr") : null,
      h("form", { class: "tadd", onsubmit: async (e) => {
        e.preventDefault();
        try {
          const t = await api("/themes", { method: "POST", body: JSON.stringify({ name: name.value }) });
          await save([...p.themes, t.id]);
        } catch (x) { name.setCustomValidity(x.body?.detail?.errors?.name ?? "Could not add."); name.reportValidity(); name.setCustomValidity(""); }
      } }, name, h("button", { type: "submit", class: "btn ghost" }, "Add"))));
  return menu;
}

function progressBar(progress) {
  return h("span", { class: "segs", "aria-hidden": "true" },
    progress.map((st, i) => h("i", { class: st, style: `--i:${i}` })));
}

let cardsPlayed = false;
function paperTable(papers, s, fw, nextId) {
  if (!papers.length) {
    return h("p", { class: "none quiet" }, lib.q ? `No papers match "${lib.q}".` : "No papers with this status.");
  }
  // "You are here" in the Library: the next presentation overall (nextId comes from the unfiltered list).
  const intro = !cardsPlayed; cardsPlayed = true; // the entrance plays once, not on every change
  return h("ol", { class: `pcards${intro ? " intro" : ""}` }, papers.map((p, i) => paperRow(p, s, fw, p.id === nextId, i)));
}

// One paper: cover, what it is, how far you are, and the one thing to do next. Only facts that exist are shown.
function paperRow(p, s, fws, isNext, i = 0) {
  const fw = fws[p.template] ?? fws.paper;
  const done = h("input", { type: "checkbox", checked: p.reflection_done, class: "switch",
    "aria-label": `Reflection done for ${p.title}`,
    onchange: async () => { await api(`/papers/${p.id}`, { method: "PATCH",
      body: JSON.stringify({ reflection_done: done.checked }) });
      if (done.checked) buddy.say(`Reflection done for "${p.title}". Nice work.`, { mood: "happy" });
      libRedraw(); } });
  const total = p.progress.length;
  const at = p.progress.findIndex((x) => x !== "done");
  const step = at < 0 ? null : fw.steps[at];
  const where = p.steps_done === total ? `All ${total} steps done`
    : p.progress.every((x) => x === "empty") ? `Not started, ${fw.steps.reduce((t, x) => t + x.minutes, 0)} min in all`
    : `Step ${step.n} of ${total - 1}: ${step.title}`;
  const go = p.steps_done === total ? "Review" : p.progress.every((x) => x === "empty") ? "Start reading" : "Continue";
  const chip = (text, cls = "") => h("span", { class: `pchip ${cls}` }, text);
  const chips = [
    p.presentation_date
      ? chip(`Talk ${fmtDate(p.presentation_date)}, ${relDays(p.presentation_date)}`, isNext ? "next" : "")
      : h("button", { type: "button", class: "pchip add", onclick: () => detailsDialog(p, s, false) }, "+ Set talk date"),
    p.reflection_no ? chip(`Reflection ${p.reflection_no} of ${s.reflections_target}`) : null,
    p.primer_status !== "not_made" ? h("span", { class: `pchip ${p.primer_status}`, "data-primer": p.id }, primerLabel({ state: p.primer_status })) : null,
    p.seconds >= 60 ? chip(`${fmtSpent(p.seconds)} read`) : null,
    chip(p.last_opened ? `Opened ${ago(p.last_opened).toLowerCase()}` : "Not opened yet", "soft"),
    ...p.themes.map((id) => themeList.find((t) => t.id === id)).filter(Boolean)
      .map((t) => h("span", { class: "pchip theme", style: `--tc:var(--theme-${t.color})` }, themeDot(t), t.name)),
    themePicker(p),
    ...p.tags.map((t) => chip(t, "tag")),
  ].filter(Boolean);
  return h("li", { class: `pcard${isNext ? " is-next" : ""}${p.reflection_done ? " is-done" : ""}`, style: `--i:${i}` },
    h("a", { class: "pcover", href: `#read/${p.id}`, tabindex: -1, "aria-hidden": "true" },
      h("img", { src: `/papers/${p.id}/cover`, alt: "", loading: "lazy", decoding: "async",
        onerror: (e) => e.target.replaceWith(h("span", { class: "pcover-none" }, "PDF")) })),
    h("div", { class: "pmain" },
      h("a", { href: `#read/${p.id}`, class: "ptitle" }, p.title),
      h("span", { class: "pauthors" }, h("span", { class: "ptype" }, p.template === "slides" ? "Slides" : "Paper"),
        p.authors || "Authors unknown"),
      h("div", { class: "chips" }, chips)),
    h("div", { class: "ptrack" },
      h("span", { class: "pwhere" }, where),
      h("span", { class: "steps", role: "img", "aria-label": `${p.steps_done} of ${total} steps done` },
        p.progress.map((x, k) => h("i", { class: `${x}${k === at ? " here" : ""}`, style: `--k:${k}`,
          title: `Step ${fw.steps[k].n}, ${fw.steps[k].title}: ${x === "done" ? "done" : x === "partial" ? "started" : "not started"}` }))),
      h("span", { class: "pcount" }, `${p.steps_done} / ${total}`)),
    h("div", { class: "pact" },
      h("a", { class: `btn${go === "Review" ? " ghost" : ""}`, href: `#read/${p.id}` }, go),
      h("label", { class: "pdone" }, done, "Reflection done"),
      rowMenu(p, s)));
}

async function makePrimerFromLibrary(p) {
  document.querySelectorAll("details.menu[open]").forEach((d) => { d.open = false; });
  p.primer_status = "making"; libRedraw();
  const end = await streamPrimer(p.id, (e) => {
    const el = document.querySelector(`[data-primer="${p.id}"]`);
    if (el) { el.textContent = primerLabel(e); el.className = `pchip ${e.state}`; }
  });
  if (end.state === "ready") buddy.say(`The AI summary for "${p.title}" is ready. It stays closed in each step until you write your own notes.`, { mood: "happy" });
  else buddy.say(end.error || "The AI summary failed. Try again.", { mood: "worried" });
  libRedraw();
}

function rowMenu(p, s) {
  const later = (label, phase) => h("button", { type: "button", disabled: true, title: `Comes in phase ${phase}` }, label);
  return h("details", { class: "menu" },
    h("summary", { "aria-label": `More actions for ${p.title}` }, "More"),
    h("div", { class: "menu-list" },
      h("button", { type: "button", onclick: () => detailsDialog(p, s, false) }, "Edit details"),
      h("button", { type: "button", onclick: async () => {
        await api(`/papers/${p.id}`, { method: "PATCH", body: JSON.stringify({ template: p.template === "slides" ? "paper" : "slides" }) });
        libRedraw();
      } }, p.template === "slides" ? "Read as a research paper" : "Read as lecture slides"),
      h("button", { type: "button", disabled: p.primer_status === "making", onclick: () => makePrimerFromLibrary(p) },
        p.primer_status === "ready" ? "Make AI summary again" : "Make AI summary"),
      later("Export Markdown", 7), later("Export reflection outline", 7),
      h("hr", {}),
      h("button", { type: "button", class: "danger", onclick: () => deleteDialog(p) }, "Delete")));
}
document.addEventListener("click", (e) => {
  document.querySelectorAll("details.menu[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
});

// ---------- adding a paper ----------
function enablePageDrop(page) {
  let depth = 0;
  page.addEventListener("dragenter", (e) => {
    e.preventDefault();
    if (depth++ === 0) { page.classList.add("dragging"); buddy.mood("surprised"); }
  });
  page.addEventListener("dragleave", () => {
    if (--depth === 0) { page.classList.remove("dragging"); buddy.mood("idle"); }
  });
  page.addEventListener("dragover", (e) => e.preventDefault());
  page.addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; page.classList.remove("dragging");
    const file = e.dataTransfer.files[0];
    if (file) addPaper(file);
  });
}

async function addPaper(file) {
  const msg = $(".upload-msg");
  const say = (text, cls = "") => { if (msg) { msg.textContent = text; msg.className = `small upload-msg ${cls}`; } };
  if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
    buddy.say(`"${file.name}" is not a PDF. I can only read PDF files.`, { mood: "worried" });
    return say("Choose a PDF file.", "err");
  }
  say(`Adding ${file.name}`, "quiet");
  buddy.say("Reading the first page", { mood: "think", sticky: true });
  try {
    const paper = await api("/papers", { method: "POST", body: file,
      headers: { "Content-Type": "application/pdf", "X-Filename": encodeURIComponent(file.name) } });
    say("", "quiet");
    buddy.say("Got it. Check that I read the title and authors right.", { mood: "happy" });
    await libRedraw();
    detailsDialog(paper, await api("/settings"), true);
  } catch (e) {
    say(e.body?.detail ?? "The PDF could not be added.", "err");
    buddy.say(e.body?.detail ?? "I could not add that PDF.", { mood: "worried" });
  }
}

function detailsDialog(p, s, isNew) {
  const fields = [
    ["title", "Title", "text"], ["authors", "Authors", "text"], ["venue", "Venue and year", "text"],
    ["presenters", "Presenter(s) in class", "text"], ["presentation_date", "Presentation date", "date"],
    ["course", "Course", "text"], ["tags", "Tags", "text", "Separate tags with commas."],
  ];
  const inputs = {};
  const errors = {};
  const row = (key, label, el, help) => {
    errors[key] = h("span", { class: "status err" });
    el.id = `d-${key}`; el.name = key;
    return h("div", { class: "dfield" }, h("label", { for: el.id }, label), el,
      help ? h("span", { class: "quiet small" }, help) : null, errors[key]);
  };
  const body = fields.map(([key, label, type, help]) => {
    const value = key === "tags" ? p.tags.join(", ") : (p[key] ?? "");
    inputs[key] = h("input", { type, value });
    return row(key, label, inputs[key], help);
  });
  inputs.reflection_no = h("select", {}, h("option", { value: "" }, "None"),
    Array.from({ length: s.reflections_target }, (_, i) =>
      h("option", { value: String(i + 1), selected: p.reflection_no === i + 1 }, `Reflection ${i + 1}`)));
  body.push(row("reflection_no", "Reflection number", inputs.reflection_no));
  inputs.template = h("select", {}, [["paper", "Research paper, 10 steps"], ["slides", "Lecture slides, 8 steps"]]
    .map(([v, l]) => h("option", { value: v, selected: (p.template ?? "paper") === v }, l)));
  body.push(row("template", "Reading template", inputs.template, "Picked from the PDF. Your notes for each template are kept."));

  const dlg = h("dialog", { class: "dialog" });
  const form = h("form", { method: "dialog", onsubmit: async (e) => {
    e.preventDefault();
    Object.values(errors).forEach((el) => { el.textContent = ""; });
    const patch = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value.trim()]));
    patch.tags = patch.tags ? patch.tags.split(",") : [];
    patch.presentation_date ||= null;
    patch.reflection_no = patch.reflection_no ? Number(patch.reflection_no) : null;
    try {
      await api(`/papers/${p.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      dlg.close(); libRedraw();
    } catch (err) {
      const errs = err.body?.detail?.errors ?? { title: "Could not save." };
      for (const [k, m] of Object.entries(errs)) (errors[k] ?? errors.title).textContent = m;
    }
  } },
    h("h2", {}, isNew ? "Check the details" : "Edit details"),
    h("p", { class: "quiet" }, isNew ? "These were read from the PDF. Fix anything that is wrong." : p.title),
    h("div", { class: "dgrid" }, body),
    h("div", { class: "dactions" },
      h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, isNew ? "Skip for now" : "Cancel"),
      h("button", { type: "submit", class: "btn" }, "Save details")));
  dlg.append(form);
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

function deleteDialog(p) {
  const dlg = h("dialog", { class: "dialog narrow" },
    h("h2", {}, "Delete this paper?"),
    h("p", {}, h("strong", {}, p.title)),
    h("p", { class: "quiet" }, "This deletes the PDF, your notes, the AI summary and the checks. You cannot undo it."),
    h("div", { class: "dactions" },
      h("button", { type: "button", class: "btn ghost", autofocus: true, onclick: () => dlg.close() }, "Keep it"),
      h("button", { type: "button", class: "btn danger", onclick: async () => {
        await api(`/papers/${p.id}`, { method: "DELETE" }).catch(() => {});
        dlg.close(); libRedraw();
        buddy.say("Deleted. The PDF and its notes are gone.", { mood: "idle" });
      } }, "Delete paper")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

// The Reader lives in reader.js.

// ---------- Settings ----------
const SETTINGS_SECTIONS = [
  ["connection", "Model connection"], ["generation", "Generation"], ["primer", "AI summary"],
  ["checker", "Checker"], ["copy", "Copy detector"], ["framework", "Framework"],
  ["course", "Course and reflections"], ["timer", "Timer"], ["appearance", "Appearance"], ["data", "Data"],
];

async function renderSettings(section = "connection") {
  const menu = h("nav", { class: "submenu", "aria-label": "Settings sections" },
    SETTINGS_SECTIONS.map(([id, label]) => h("a", { href: `#settings/${id}`,
      class: id === section ? "active" : "", "aria-current": id === section ? "page" : false },
      h("span", {}, label))));
  const body = h("section", { class: "settings-body" });
  view.append(menu, body);
  const s = await api("/settings");
  if (section === "connection") {
    drawConnection(body, s);
    greet("settings", "Paste the URL and key that Unsloth shows, then press Test connection.", { pop: false });
  }
  else if (section === "primer") drawPrimerSettings(body, s);
  else body.append(
    h("h2", {}, SETTINGS_SECTIONS.find(([id]) => id === section)?.[1] ?? "Settings"),
    h("p", { class: "lede" }, "You can change these settings from phase 8."));
  if (section === "primer") buddy.say(AI_SUMMARY_TIP, { mood: "idle", pop: false });
}

function drawPrimerSettings(body, s) {
  const st = () => h("span", { class: "status" });
  const [a, b, c] = [st(), st(), st()];
  const panel = h("select", { onchange: () => saveSetting("primer_panel", panel.value, a) },
    [["after_writing", "Closed until I write something in the step"], ["click", "Closed, open with a click"], ["open", "Always open"]]
      .map(([v, t]) => h("option", { value: v, selected: s.primer_panel === v }, t)));
  const sentences = h("select", { onchange: () => saveSetting("primer_sentences", Number(sentences.value), b) },
    [1, 2, 3].map((n) => h("option", { value: n, selected: s.primer_sentences === n }, `${n} ${n === 1 ? "sentence" : "sentences"}`)));
  const auto = h("input", { type: "checkbox", class: "switch", checked: s.primer_auto, onchange: () => saveSetting("primer_auto", auto.checked, c) });
  body.append(h("h2", {}, "AI summary"),
    h("p", { class: "lede" }, AI_SUMMARY_TIP),
    row("AI summary panel", panel, a),
    row("Length of each part", sentences, b),
    row("Make it right after I add a paper", auto, c));
}

// Save one setting at once; show "Saved" or the error next to the control.
async function saveSetting(key, value, statusEl) {
  statusEl.className = "status";
  try {
    await api("/settings", { method: "PATCH", body: JSON.stringify({ [key]: value }) });
    statusEl.textContent = "Saved";
    statusEl.classList.add("ok");
    setTimeout(() => { if (statusEl.textContent === "Saved") statusEl.textContent = ""; }, 2000);
    return true;
  } catch (e) {
    statusEl.textContent = e.body?.detail?.errors?.[key] ?? "Could not save.";
    statusEl.classList.add("err");
    return false;
  }
}

function row(label, control, status, extra) {
  const id = `f-${Math.random().toString(36).slice(2, 8)}`;
  control.id = id;
  return h("div", { class: "field" },
    h("label", { class: "label", for: id }, label),
    h("div", { class: "control" }, control, extra), status);
}

// The connection display: a small graphite device, like Dot. It answers "can the app talk to the model, and how fast?"
const conn = { seconds: null, failed: false, model: "" };
const CONN_HINT = { not_running: "Start Unsloth on your Mac.", wrong_key: "Paste the key that Unsloth shows.",
  error: "The server sent an error.", checking: "Asking the server", unknown: "Asking the server" };
function paintConn(animate = false) {
  const panel = $("#conn-panel");
  if (!panel) return;
  const status = chip.dataset.status || "unknown";
  const ready = status === "ready";
  const sec = ready ? conn.seconds : null;
  const bars = sec == null ? 0 : sec < 1 ? 5 : sec < 2 ? 4 : sec < 4 ? 3 : sec < 8 ? 2 : 1;
  panel.dataset.status = status;
  panel.classList.toggle("lit", animate);
  panel.replaceChildren(
    h("span", { class: "conn-led", "aria-hidden": "true" }),
    h("div", { class: "conn-text" },
      h("p", { class: "conn-label" }, status === "checking" ? "Checking model" : lastStatus.label || "Checking model"),
      h("p", { class: "conn-sub" }, ready ? (conn.model || lastStatus.models[0] || "First model the server lists") : CONN_HINT[status] ?? "")),
    h("div", { class: "conn-meter" },
      h("span", { class: "conn-bars", "aria-hidden": "true" }, [1, 2, 3, 4, 5].map((n) =>
        h("span", { class: n <= bars ? "on" : "", style: `--i:${n}` }, Array.from({ length: n }, () => h("i"))))),
      h("span", { class: "conn-num" }, h("span", { class: "dotnum" }, sec == null ? "--" : `${sec.toFixed(1)}s`),
        h("span", { class: "conn-sub" }, sec != null ? "Answer time" : conn.failed ? "Test failed" : ready ? "Not tested yet" : "No answer"))));
}

function drawConnection(body, s) {
  conn.model = s.model_name;
  const urlStatus = h("span", { class: "status" });
  const keyStatus = h("span", { class: "status" });
  const modelStatus = h("span", { class: "status" });

  const url = h("input", { type: "url", value: s.base_url, spellcheck: "false" });
  const key = h("input", { type: "password", value: s.api_key, autocomplete: "off", spellcheck: "false" });
  const showKey = h("button", { type: "button", class: "btn ghost", onclick: () => {
    key.type = key.type === "password" ? "text" : "password";
    showKey.textContent = key.type === "password" ? "Show" : "Hide";
  } }, "Show");
  const model = h("select", {});
  const refresh = h("button", { type: "button", class: "btn ghost", onclick: () => fillModels() }, "Refresh");

  async function fillModels() {
    const st = await refreshChip();
    const names = [...new Set([...st.models, s.model_name].filter(Boolean))];
    model.replaceChildren(h("option", { value: "" }, "First model the server lists"),
      ...names.map((n) => h("option", { value: n, selected: n === s.model_name }, n)));
  }

  const onConn = (input, k, status) => input.addEventListener("change", async () => {
    if (await saveSetting(k, input.value, status)) { s[k] = input.value; fillModels(); }
  });
  onConn(url, "base_url", urlStatus);
  onConn(key, "api_key", keyStatus);
  model.addEventListener("change", async () => {
    if (await saveSetting("model_name", model.value, modelStatus)) { s.model_name = conn.model = model.value; paintConn(); }
  });

  const result = h("div", { class: "test-result", "aria-live": "polite" });
  const test = h("button", { type: "button", class: "btn", onclick: async () => {
    test.disabled = true;
    result.className = "test-result"; result.textContent = "Sending a tiny request";
    buddy.say("Asking the model to say OK", { mood: "think", sticky: true });
    try {
      const r = await api("/settings/test-connection", { method: "POST" });
      result.classList.add(r.ok ? "ok" : "err");
      Object.assign(conn, { seconds: r.ok ? r.seconds : null, failed: !r.ok });
      paintConn(r.ok);
      result.replaceChildren(...(r.ok
        ? [`Connected to ${r.model}. It answered in `, h("span", { class: "num" }, `${r.seconds} s`), "."]
        : [r.error]));
      buddy.say(r.ok ? `Connected to ${r.model}. It answered in ${r.seconds} seconds.` : r.error,
        { mood: r.ok ? "happy" : "worried" });
    } catch { result.classList.add("err"); result.textContent = "The app could not run the test."; }
    test.disabled = false;
  } }, "Test connection");

  body.append(
    h("h2", {}, "Model connection"),
    h("p", { class: "lede" }, "Unsloth shows the URL and API key when it starts. Paste them here. The key stays in the database on this Mac."),
    h("div", { id: "conn-panel", class: "conn-panel", role: "group", "aria-label": "Connection status" }),
    row("Base URL", url, urlStatus),
    row("API key", key, keyStatus, showKey),
    row("Model", model, modelStatus, refresh),
    h("div", { class: "test-row" }, test, result));
  paintConn();
  fillModels();
}

// ---------- start ----------
refreshChip();
route();
