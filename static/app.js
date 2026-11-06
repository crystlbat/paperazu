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

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...opts.headers } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(r.statusText), { body, status: r.status });
  return body;
}

// ---------- model status chip ----------
const chip = $("#model-chip");
const chipLabel = $("#model-chip .chip-label");
let lastStatus = { status: "unknown", models: [] };

async function refreshChip() {
  chip.dataset.status = "checking";
  chipLabel.textContent = "Checking model";
  try { lastStatus = await api("/model/status"); }
  catch { lastStatus = { status: "error", label: "App error", models: [] }; }
  const before = chip.dataset.prev;
  chip.dataset.status = chip.dataset.prev = lastStatus.status;
  chipLabel.textContent = chip.title = lastStatus.label;
  buddy.status(lastStatus.status);
  if (lastStatus.status !== before) buddyOnStatus(lastStatus.status, before);
  return lastStatus;
}

function buddyOnStatus(now, before) {
  const toSettings = { label: "Open Settings", href: "#settings/connection" };
  if (now === "not_running") {
    buddy.say("I cannot reach the model. Start Unsloth on your Mac, then I can help with primers and checks.",
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
const pages = { library: renderLibrary, read: renderReader, settings: renderSettings };

function route() {
  const [name, arg] = location.hash.replace(/^#/, "").split("/");
  if (!pages[name]) { location.hash = "#library"; return; }
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === name));
  $("#page-extra").replaceChildren();
  view.replaceChildren();
  view.className = `page page-${name}`;
  buddy.hide();
  pages[name](arg);
}
window.addEventListener("hashchange", route);

// ---------- Library ----------
const lib = { q: "", status: "all", sort: "date" };
const STATUSES = [["all", "All"], ["not_started", "Not started"], ["in_progress", "In progress"],
  ["notes_done", "Notes done"], ["reflection_done", "Reflection done"]];
const SORTS = [["date", "Presentation date"], ["opened", "Last opened"], ["title", "Title"], ["progress", "Progress"]];
const PRIMER = { not_made: "Not made", making: "Making", ready: "Ready", failed: "Failed" };

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
  const [s, fw, list] = await Promise.all([api("/settings"), api("/framework"), loadPapers()]);
  const page = h("div", { class: "library" });
  view.append(page);
  const draw = (data) => page.replaceChildren(libHead(data, s),
    data.total ? libBody(data, s, fw) : libEmpty(fw));
  draw(list);
  enablePageDrop(page);
  libraryGreeting(list);
  libRedraw = async () => draw(await loadPapers());
}
let libRedraw = async () => {};

function libraryGreeting(data) {
  if (!data.total) {
    return greet("lib-empty", "Hi, I am Dot. Drop your first PDF anywhere on this page. I will read the title and authors for you.", { mood: "happy" });
  }
  const next = data.papers.filter((p) => p.presentation_date && daysFromToday(p.presentation_date) >= 0)
    .sort((a, b) => a.presentation_date.localeCompare(b.presentation_date))[0];
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

function loadPapers() {
  return api(`/papers?${new URLSearchParams(lib)}`);
}

function libHead(data, s) {
  return h("header", { class: "lib-head" },
    h("h1", {}, "Library"),
    h("span", { class: "stat" }, h("span", { class: "dotnum" }, String(data.total)), data.total === 1 ? "paper" : "papers"),
    h("span", { class: "stat" }, h("span", { class: "dotnum" }, `${data.reflections_done}/${s.reflections_target}`), "reflections done"));
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

function libBody(data, s, fw) {
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
    const d = await loadPapers();
    listEl.replaceChildren(paperTable(d.papers, s, fw));
  }
  listEl.append(paperTable(data.papers, s, fw));

  return h("div", { class: "lib-main" },
    h("div", { class: "toolbar" }, search, sort,
      h("button", { class: "btn", type: "button", onclick: () => picker.click() }, "Add paper"), picker),
    h("div", { class: "toolbar-2" }, filters,
      h("span", { class: "quiet small upload-msg", "aria-live": "polite" }, "You can also drop a PDF anywhere on this page.")),
    listEl);
}

function progressBar(progress) {
  return h("span", { class: "segs", "aria-hidden": "true" },
    progress.map((st, i) => h("i", { class: st, style: `--i:${i}` })));
}

function paperTable(papers, s, fw) {
  if (!papers.length) {
    return h("p", { class: "none quiet" }, lib.q ? `No papers match "${lib.q}".` : "No papers with this status.");
  }
  // "You are here" in the Library: the next presentation coming up.
  const next = papers.filter((p) => p.presentation_date && daysFromToday(p.presentation_date) >= 0)
    .sort((a, b) => a.presentation_date.localeCompare(b.presentation_date))[0];
  return h("table", { class: "papers" },
    h("thead", {}, h("tr", {}, ["Paper", "Presentation", "Reflection", "Progress", "Primer", "Time spent", "Last opened", "Done", ""]
      .map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", {}, papers.map((p) => paperRow(p, s, fw, p === next))));
}

function paperRow(p, s, fw, isNext) {
  const done = h("input", { type: "checkbox", checked: p.reflection_done,
    "aria-label": `Reflection done for ${p.title}`,
    onchange: async () => { await api(`/papers/${p.id}`, { method: "PATCH",
      body: JSON.stringify({ reflection_done: done.checked }) });
      if (done.checked) buddy.say(`Reflection done for "${p.title}". Nice work.`, { mood: "happy" });
      libRedraw(); } });
  return h("tr", {},
    h("td", { class: "c-title" },
      h("a", { href: `#read/${p.id}`, class: "title" }, p.title),
      h("span", { class: "authors" }, p.authors || "Authors unknown"),
      p.tags.length ? h("span", { class: "tags" }, p.tags.map((t) => h("span", { class: "tag" }, t))) : null),
    h("td", { "data-label": "Presentation" }, p.presentation_date
      ? h("span", {}, h("span", { class: isNext ? "hl" : "" }, fmtDate(p.presentation_date)),
          h("span", { class: "sub" }, relDays(p.presentation_date)))
      : h("span", { class: "quiet" }, "No date")),
    h("td", { "data-label": "Reflection", class: "num" }, p.reflection_no ? `${p.reflection_no} / ${s.reflections_target}` : h("span", { class: "quiet" }, "None")),
    h("td", { "data-label": "Progress" }, h("span", { class: "prog" }, progressBar(p.progress),
      h("span", { class: "num" }, `${p.steps_done} / ${p.progress.length}`))),
    h("td", { "data-label": "Primer" }, h("span", { class: `primer ${p.primer_status}` }, PRIMER[p.primer_status])),
    h("td", { "data-label": "Time spent", class: "num" }, fmtSpent(p.seconds)),
    h("td", { "data-label": "Last opened" }, ago(p.last_opened)),
    h("td", { "data-label": "Reflection done", class: "c-done" }, done),
    h("td", { class: "c-actions" },
      h("a", { class: "btn ghost", href: `#read/${p.id}` }, "Open"),
      rowMenu(p, s)));
}

function rowMenu(p, s) {
  const later = (label, phase) => h("button", { type: "button", disabled: true, title: `Comes in phase ${phase}` }, label);
  return h("details", { class: "menu" },
    h("summary", { "aria-label": `More actions for ${p.title}` }, "More"),
    h("div", { class: "menu-list" },
      h("button", { type: "button", onclick: () => detailsDialog(p, s, false) }, "Edit details"),
      later("Make primer again", 5), later("Export Markdown", 7), later("Export reflection outline", 7),
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
    h("p", { class: "quiet" }, "This deletes the PDF, your notes, the primer and the checks. You cannot undo it."),
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

// ---------- Reader ----------
async function renderReader(paperId) {
  const [fw, paper] = await Promise.all([api("/framework"),
    api(`/papers/${paperId}?open=true`).catch(() => null)]);
  if (!paper) {
    view.className = "page page-library";
    view.append(h("div", { class: "library" }, h("h1", {}, "Paper not found"),
      h("p", { class: "quiet" }, "This paper is not in the library. It may have been deleted. ",
        h("a", { href: "#library" }, "Go to the Library"), ".")));
    return;
  }
  let current = fw.steps[0].id;

  $("#page-extra").append(
    h("a", { href: "#library", class: "paper-title", title: "Back to the Library" }, paper.title),
    h("span", { class: "quiet nowrap" }, h("span", { class: "num" }, `${paper.steps_done} / ${fw.steps.length}`), " steps done"),
    h("button", { class: "btn ghost", type: "button", disabled: true }, "Hide paper"));

  const rail = h("ol", { class: "rail", "aria-label": "Reading steps" });
  const notebook = h("section", { class: "notebook" });

  function drawRail() {
    rail.replaceChildren(
      ...fw.steps.map((st, i) => h("li", {},
        h("button", { type: "button", class: st.id === current ? "active" : "",
          "aria-current": st.id === current ? "step" : false,
          onclick: () => { current = st.id; drawRail(); drawNotebook(); stepTip(st, true); } },
          h("span", { class: `circle ${paper.progress[i] ?? ""}` }, String(st.n)),
          h("span", { class: "label" }, st.title),
          h("span", { class: "num mins" }, `${st.minutes}m`)))),
      h("li", { class: "divider", "aria-hidden": "true" }),
      h("li", {}, h("button", { type: "button", disabled: true },
        h("span", { class: "circle" }, "R"), h("span", { class: "label" }, "Review"))));
  }

  function drawNotebook() {
    const st = fw.steps.find((x) => x.id === current);
    notebook.replaceChildren(
      h("div", { class: "step-head" },
        h("span", { class: "num n" }, `Step ${st.n}`),
        h("h2", { class: "step-title" }, h("span", { class: "hl swipe" }, st.title))),
      h("div", { class: "budget" },
        h("div", { class: "row" }, h("span", {}, "Time budget"),
          h("span", { class: "num" }, `00:00 / ${String(st.minutes).padStart(2, "0")}:00`)),
        h("div", { class: "bar" }, h("i", {}))),
      h("ul", { class: "field-preview" }, st.fields.map((f) => h("li", {}, f.label,
        f.help ? h("span", { class: "help" }, f.help) : null))),
      h("p", { class: "quiet small" }, "You can write in these fields from phase 3."));
  }

  drawRail(); drawNotebook();
  stepTip(fw.steps[0], !greeted.has("reader")); greeted.add("reader");
  view.append(rail,
    h("section", { class: "pdf-pane" },
      h("div", { class: "ghost-page" }, h("p", {}, "The PDF shows here from phase 3."))),
    notebook);
}

function stepTip(st, pop) {
  const parts = [`Step ${st.n}, ${st.title}. You have ${st.minutes} ${st.minutes === 1 ? "minute" : "minutes"}.`];
  if (st.paper_hidden) parts.push("Close the paper and explain it out loud, as if to a friend.");
  else if (st.look_in.length) parts.push(`Look in the ${st.look_in.join(", ")}.`);
  if (st.gate.length) parts.push(`Before you move on: ${st.gate[0]}`);
  buddy.say(parts.join(" "), { mood: st.paper_hidden ? "think" : "idle", pop });
}

// ---------- Settings ----------
const SETTINGS_SECTIONS = [
  ["connection", "Model connection"], ["generation", "Generation"], ["primer", "Primer"],
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
  else body.append(
    h("h2", {}, SETTINGS_SECTIONS.find(([id]) => id === section)?.[1] ?? "Settings"),
    h("p", { class: "lede" }, "You can change these settings from phase 8."));
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

function drawConnection(body, s) {
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
    if (await saveSetting("model_name", model.value, modelStatus)) s.model_name = model.value;
  });

  const result = h("div", { class: "test-result", "aria-live": "polite" });
  const test = h("button", { type: "button", class: "btn", onclick: async () => {
    test.disabled = true;
    result.className = "test-result"; result.textContent = "Sending a tiny request";
    buddy.say("Asking the model to say OK", { mood: "think", sticky: true });
    try {
      const r = await api("/settings/test-connection", { method: "POST" });
      result.classList.add(r.ok ? "ok" : "err");
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
    row("Base URL", url, urlStatus),
    row("API key", key, keyStatus, showKey),
    row("Model", model, modelStatus, refresh),
    h("div", { class: "test-row" }, test, result));
  fillModels();
}

// ---------- start ----------
refreshChip();
route();
