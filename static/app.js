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
const MODEL_CALL = /\/(explain|ask|test-connection)$|\/check\/\w+$|\/export\/reflection$|^\/graph\/(index|search|suggest)$/;

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
  libraryLeave();
  $("#page-extra").replaceChildren();
  view.replaceChildren();
  view.className = `page page-${name}`;
  buddy.hide();
  pages[name](arg, extra);
}
window.addEventListener("hashchange", route);

// ---------- Library ----------
const lib = { theme: "" }; // the Graph page sets theme to open the Library on that theme's shelf
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
  const [s, fw, list, th] = await Promise.all([api("/settings"), api("/frameworks"), api("/papers"), api("/themes")]);
  themeList = th.themes;
  if (!view.classList.contains("page-library")) return; // you left while it loaded
  view.append(libraryStage({ s, fw, list }));
  libRedraw = libraryRefresh;
  // a summary still being made (you came back mid-way): follow it so its chip counts up
  for (const p of list.papers.filter((x) => x.primer_status === "making")) {
    streamPrimer(p.id, (e) => { const el = document.querySelector(`[data-primer="${p.id}"]`); if (el) el.textContent = primerLabel(e); })
      .then(() => { if (location.hash.startsWith("#library") || !location.hash) libRedraw(); });
  }
}
let libRedraw = async () => {};

const nextTalk = (papers) => papers.filter((p) => p.presentation_date && daysFromToday(p.presentation_date) >= 0)
  .sort((a, b) => a.presentation_date.localeCompare(b.presentation_date))[0];

function filePicker() {
  const input = h("input", { type: "file", accept: "application/pdf,.pdf", hidden: true,
    onchange: () => input.files[0] && addPaper(input.files[0]) });
  return input;
}

const themeDot = (t) => h("i", { class: "tdot", style: `--tc:var(--theme-${t.color})` });

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
      h("button", { type: "button", onclick: () => exportDialog(p, "markdown") }, "Export Markdown"),
      h("button", { type: "button", onclick: () => exportDialog(p, "reflection") }, "Export reflection outline"),
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

// ---------- export ----------
// Shows the Markdown, then copy or download it. `before` lets the Reader save pending notes first.
async function exportDialog(p, kind, before) {
  document.querySelectorAll("details.menu[open]").forEach((d) => { d.open = false; });
  const outline = kind === "reflection";
  const status = h("p", { class: "quiet", role: "status" }, outline ? "Your model is sorting your notes into the sections..." : "Getting your notes...");
  const text = h("textarea", { class: "export-text", readonly: true, "aria-label": "Exported Markdown", hidden: true });
  const name = `${(p.title || "paper").replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-").slice(0, 60) || "paper"}${outline ? "-reflection" : ""}.md`;
  const copy = h("button", { type: "button", class: "btn ghost", disabled: true, onclick: async () => {
    await navigator.clipboard.writeText(text.value).then(() => { copy.textContent = "Copied"; }, () => { text.select(); copy.textContent = "Press Cmd+C to copy"; });
  } }, "Copy");
  const save = h("button", { type: "button", class: "btn", disabled: true, onclick: () => {
    const a = h("a", { href: URL.createObjectURL(new Blob([text.value], { type: "text/markdown" })), download: name });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } }, "Download .md");
  const dlg = h("dialog", { class: "dialog export" },
    h("h2", {}, outline ? "Reflection outline" : "Export notes"),
    h("p", {}, h("strong", {}, p.title)),
    outline ? h("p", { class: "quiet" }, "Every line is from your own notes. The model only chose which section each note goes in. It adds no new facts.") : null,
    status, text,
    h("div", { class: "dactions" },
      h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Close"), copy, save));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  try {
    if (before) await before();
    const r = await api(`/papers/${p.id}/export/${kind}`);
    if (!r.ok) { status.textContent = r.error; return; }
    text.value = r.markdown; text.hidden = false; status.hidden = true;
    copy.disabled = save.disabled = false;
  } catch (e) {
    status.textContent = e.status === 404 ? "This paper is not in the library." : "Could not export. Try again.";
  }
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
  else if (section === "checker") drawCheckerSettings(body, s);
  else body.append(
    h("h2", {}, SETTINGS_SECTIONS.find(([id]) => id === section)?.[1] ?? "Settings"),
    h("p", { class: "lede" }, "You can change these settings from phase 8."));
  if (section === "primer") buddy.say(AI_SUMMARY_TIP, { mood: "idle", pop: false });
}

function drawCheckerSettings(body, s) {
  const [a, b] = [h("span", { class: "status" }), h("span", { class: "status" })];
  const words = h("input", { type: "number", min: 20, max: 60, step: 5, value: s.hint_words,
    onchange: () => saveSetting("hint_words", Number(words.value), a) });
  const hints = h("select", { onchange: () => saveSetting("checker_hints", hints.value === "1", b) },
    h("option", { value: "1", selected: s.checker_hints }, "The verdict and a hint"), h("option", { value: "0", selected: !s.checker_hints }, "The verdict only"));
  body.append(h("h2", {}, "Checker"),
    h("p", { class: "lede" }, "Check my notes sends your notes for one step, and the paper, to the model on your Mac. It says correct, partial, wrong or missing for each field, and points to a page instead of giving the answer."),
    row("Hint length, in words (20 to 60)", words, a),
    row("Show", hints, b));
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
