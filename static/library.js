"use strict";
// The Library around Dot. Bubble mode: Dot in the middle, papers floating around it, coloured by similarity,
// little character blobs orbiting as options, and an Ask field where Dot finds papers, answers across them
// and sends helpers to do jobs. Shelf mode: Dot wears glasses and becomes the search pill over shelves of spines.
// Uses app.js globals (h, api, themeList, streamPrimer, themePicker, rowMenu, ...). Positions are set every frame
// with transforms in one loop; CSS does the rest. Design: docs/superpowers/specs/2026-11-07-library-dot-design.md

const LIB_BLOBS = [["find", "Ask", "#8ecbff"], ["web", "Web", "#3ddec8"], ["next", "What next?", "#7bd88f"], ["talks", "Talks", "#ff9e7a"],
  ["pick", "Pick up", "#c6a0ff"], ["add", "Add paper", "#ffe347"], ["shelf", "Shelf", "#ff7ab8"], ["persona", "Persona", "#ffa86b"], ["super", "Super intelligence", "#6ff7ff"],
  ["set", "Settings", "#c9cdd6"]];
const LIB_HINT = { web: "I search the web and bring pages back." };
const SHELF_BLOBS = [["group", "#7bd88f"], ["sort", "#8ecbff"], ["show", "#ff9e7a"], ["theme", "#c6a0ff"],
  ["add", "#ffe347"], ["set", "#c9cdd6"], ["bubble", "#ff7ab8"]];
const HUES = ["#6fb6ff", "#6fd08a", "#ff9673", "#b993ff", "#ff74b0", "#4fd1c5", "#f2b84b", "#d8c3a0"];
const GREY = "#6b6d75";
const RING_MAX = 12;
const libRM = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const libStore = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private window */ } } };
let L = null; // the live Library, or null when another page is open

// ---------- entering and leaving ----------
function libraryStage({ s, fw, list }) {
  libraryLeave();
  document.querySelectorAll(".lst").forEach((x) => x.remove()); // a second route() while the first was loading
  const st = h("div", { class: "lst" });
  L = { st, s, fw, papers: list.papers, total: list.total, done: list.reflections_done, hue: {}, groups: [], unread: [], mapReason: "",
    mode: "bubble", job: null, cards: new Map(), blobs: [], timers: [], busy: 0, spin: 0, near: false, orbit: true, peekId: null,
    dot: { x: 0, y: 0, tx: 0, ty: 0 }, lineGap: 150, hist: [], turn: null, groupBy: libStore.get("lib-group") || "sim",
    sortI: 0, showI: 0, q: "", qIds: null, raf: 0, last: 0, keys: null };
  document.body.classList.add("lib-on");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.position = "absolute";
  svg.innerHTML = '<filter id="lgoo"><feGaussianBlur in="SourceGraphic" stdDeviation="7"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -10"/></filter>';
  L.dotEl = h("button", { class: "ldot abs", type: "button", "aria-label": "Dot. Drag me onto a paper to peek at it." },
    h("span", { class: "specs" }), h("span", { class: "eyes" }, h("i"), h("i")),
    h("input", { type: "text", "aria-label": "Search the shelves, or ask Dot", placeholder: "Search titles, authors, tags, notes. Enter asks me" }));
  L.line = h("div", { class: "lline abs", "aria-live": "polite" });
  L.count = h("div", { class: "lcount abs" });
  L.back = h("button", { class: "lback abs", type: "button", "aria-label": "Back", onclick: () => libHome() },
    libSvg('<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>'));
  L.peek = h("div", { class: "lpeek abs", role: "dialog", "aria-label": "Paper" });
  L.strip = h("div", { class: "lstrip abs" });
  L.shelf = h("div", { class: "lshelf", hidden: true });
  L.sblobs = h("div", { class: "lsblobs abs", hidden: true });
  L.hist = []; L.histEl = h("div", { class: "lhist abs off" });
  L.picker = filePicker();
  st.append(svg, L.shelf, L.strip, L.line, L.count, L.dotEl, L.back, L.peek, L.histEl, L.sblobs, L.picker);
  libField();
  for (const p of L.papers) libCard(p);
  L.blobs = LIB_BLOBS.map(([k, name, c]) => libBlob(k, name, c, () => libJob(k)));
  L.blobs.forEach((b) => st.append(b));
  SHELF_BLOBS.forEach(([k, c]) => L.sblobs.append(libBlob(k, "", c, () => libShelfOpt(k), true)));
  libWrapBuddy();
  libDotDrag();
  st.addEventListener("pointermove", (e) => {
    const r = st.getBoundingClientRect(); L.px = e.clientX - r.left; L.py = e.clientY - r.top;
    L.near = Math.hypot(L.px - L.dot.x, L.py - L.dot.y) < 160; st.classList.toggle("near", L.near && L.mode === "bubble" && !L.job);
  });
  st.addEventListener("pointerdown", (e) => {
    if (L.peekId && !L.peek.contains(e.target) && !e.target.closest(".lcard, .lspine, .ldot, dialog")) libPeekClose();
  });
  L.keys = (e) => {
    if (e.key !== "Escape" || document.querySelector("dialog[open]")) return;
    if (L.peekId) return libPeekClose();
    if (L.job === "ask") return libEscape();
    if (L.job) return libHome();
    if (L.mode === "shelf" && L.dotEl.querySelector("input").value) { L.dotEl.querySelector("input").value = ""; libFilter(""); }
  };
  document.addEventListener("keydown", L.keys);
  L.resize = () => libRelayout();
  addEventListener("resize", L.resize);
  enablePageDrop(st);
  L.raf = requestAnimationFrame(libLoop);
  const start = () => { if (!L || L.st !== st) return; if (!st.clientWidth) return setTimeout(start, 30);
    L.dot.x = L.dot.tx = st.clientWidth / 2; L.dot.y = L.dot.ty = st.clientHeight / 2;
    const theme = lib.theme; lib.theme = "";
    if (theme && L.total) { L.groupBy = "mine"; libToShelf();
      libLater(500, () => [...L.shelf.querySelectorAll(".srow")].find((r) => r.querySelector(".slabel span")?.textContent === themeList.find((t) => t.id === theme)?.name)?.scrollIntoView({ block: "center" })); }
    else if (libStore.get("lib-mode") === "shelf" && L.total) libToShelf(); else libHome();
    libLoadMap(); };
  requestAnimationFrame(start);
  return st;
}

function libraryLeave() {
  if (!L) return;
  cancelAnimationFrame(L.raf); L.timers.forEach(clearTimeout);
  document.removeEventListener("keydown", L.keys); removeEventListener("resize", L.resize);
  if (L.orig) Object.assign(buddy, L.orig);
  document.body.classList.remove("lib-on");
  L = null;
}

// Everything else in the app talks through buddy.say; on the Library that becomes Dot's own line.
function libWrapBuddy() {
  L.orig = { say: buddy.say, busy: buddy.busy, mood: buddy.mood };
  buddy.say = (text, o = {}) => {
    if (!L) return;
    libSay(text, (o.actions || []).map((a) => [a.label, () => (a.href ? (location.hash = a.href) : a.onClick?.())]));
    if (o.mood === "worried") L.dotEl.animate([{ rotate: "0deg" }, { rotate: "-8deg" }, { rotate: "8deg" }, { rotate: "0deg" }], { duration: 420 });
  };
  buddy.busy = (n) => { if (!L) return; L.busy = Math.max(0, L.busy + n); L.dotEl.classList.toggle("think", L.busy > 0); };
  buddy.mood = (m) => { if (L) L.dotEl.classList.toggle("wide", m === "surprised"); };
}

async function libraryRefresh() {
  if (!L) return;
  const [list, th] = await Promise.all([api("/papers"), api("/themes")]);
  if (!L) return;
  themeList = th.themes;
  const was = L.total;
  L.papers = list.papers; L.total = list.total; L.done = list.reflections_done;
  const ids = new Set(L.papers.map((p) => p.id));
  for (const [id, c] of L.cards) if (!ids.has(id)) { c.el.remove(); L.cards.delete(id); }
  for (const p of L.papers) libCard(p);
  libCount();
  if (L.mode === "shelf") libRenderShelf();
  else if (!L.job || (was === 0) !== (L.total === 0)) { if (!L.job) libHome(true); }
  if (L.peekId) { const p = libP(L.peekId); p ? libPeek(p, null, true) : libPeekClose(); }
  if (L.total !== was) libLoadMap();
}

async function libLoadMap() {
  try {
    let m = await api("/library/map?names=false");
    for (let pass = 0; pass < 2; pass++) {
    if (!L) return;
    L.groups = m.groups; L.unread = m.unread; L.mapReason = m.reason || "";
    L.hue = {};
    m.groups.forEach((g) => g.paper_ids.forEach((id) => { L.hue[id] = HUES[g.hue % HUES.length]; }));
    for (const [id, c] of L.cards) c.el.style.setProperty("--tc", L.hue[id] || GREY);
    if (L.mode === "shelf") libRenderShelf();
    if (pass === 0) m = await api("/library/map");
    }
  } catch { /* the colours just stay grey */ }
}

// ---------- small helpers ----------
const libP = (id) => L.papers.find((p) => p.id === id);
const libW = () => L.st.clientWidth, libH = () => L.st.clientHeight;
const libLater = (ms, f) => { const t = setTimeout(f, libRM() ? Math.min(ms, 60) : ms); L.timers.push(t); return t; };
const libWait = (ms) => new Promise((r) => libLater(ms, r));
function libClear() { L.timers.forEach(clearTimeout); L.timers = []; }
function libSvg(paths) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.innerHTML = paths; return s;
}
const libShortDate = (iso) => new Date(`${iso}T00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
const libDays = (p) => (p.presentation_date ? daysFromToday(p.presentation_date) : null);

// Dot's words: plain text above Dot, no box. Actions become underlined words.
function libSay(text, actions = []) {
  let i = 0;
  L.line.replaceChildren(...text.split(/(\s+)/).map((w) => (/^\s+$/.test(w) ? w : h("span", { class: "w", style: `--i:${i++}` }, w))),
    ...actions.map(([label, fn]) => h("button", { type: "button", onclick: (e) => { e.stopPropagation(); fn(); } }, label)));
  L.line.classList.remove("off");
}

function libCount() {
  const more = L.mode === "bubble" && !L.job && L.total > RING_MAX ? h("span", {}, `${L.total - RING_MAX} more on the shelf`) : null;
  L.count.replaceChildren(h("span", {}, h("b", {}, String(L.total)), L.total === 1 ? "paper" : "papers"),
    h("span", {}, h("b", {}, `${L.done}/${L.s.reflections_target}`), "reflections"), ...(more ? [more] : []));
}

function libGreeting() {
  if (!L.total) return libSay("Hi, I am Dot. Drop your first PDF anywhere, or on me.", [["Choose PDF", () => L.picker.click()]]);
  const next = nextTalk(L.papers);
  if (!next) return libSay("Hi, I am Dot. No talks with a date coming up. What shall we do?");
  const left = next.progress.length - next.steps_done;
  libSay(`Your talk on "${next.title}" is ${relDays(next.presentation_date)}. ` +
    (left ? `${left} steps to go. What shall we do?` : "Your notes are done. Time for the reflection."),
  [["Open it", () => { location.hash = `#read/${next.id}`; }]]);
}

// ---------- the loop: Dot, cards, blobs, the typist ----------
function libLoop(t) {
  if (!L) return;
  const dt = Math.min(2.5, (t - L.last) / 16.7 || 1); L.last = t;
  const rm = libRM(), d = L.dot, k = rm ? 1 : 1 - Math.pow(1 - 0.16, dt);
  if (!L.dragging) { d.x += (d.tx - d.x) * k; d.y += (d.ty - d.y) * k; }
  L.dotEl.style.transform = `translate3d(${d.x}px, ${d.y}px, 0)`;
  if (!L.dragging && L.px != null && !L.dotEl.classList.contains("pill")) { // eyes follow the pointer
    const a = Math.atan2(L.py - d.y, L.px - d.x), m = Math.min(5, Math.hypot(L.px - d.x, L.py - d.y) / 40);
    L.dotEl.firstChild.nextSibling.style.translate = `${Math.cos(a) * m}px ${Math.sin(a) * m}px`;
  }
  L.line.style.transform = `translate3d(${d.x}px, ${d.y - L.lineGap}px, 0) translate(-50%, -100%)`;
  if (L.mode === "bubble") L.count.style.transform = `translate3d(${d.x}px, ${d.y + 150}px, 0) translate(-50%, 0)`;
  const ck = rm ? 1 : 1 - Math.pow(1 - 0.12, dt);
  for (const c of L.cards.values()) {
    c.x += (c.tx - c.x) * ck; c.y += (c.ty - c.y) * ck; c.r += (c.tr - c.r) * ck;
    const drift = c.drift && !rm ? 1 : 0;
    const dx = drift * Math.sin(t / 1900 + c.ph) * 5, dy = drift * Math.cos(t / 2300 + c.ph * 1.3) * 6;
    c.el.style.transform = `translate3d(${c.x + dx}px, ${c.y + dy}px, 0) translate(-50%, -50%) rotate(${c.r}deg)`;
  }
  if (L.orbit && !L.near && !rm && !L.blobs.some((b) => b === document.activeElement)) L.spin += dt * 0.0021;
  const n = L.blobs.filter((b) => !b.hidden).length;
  let i = 0;
  for (const b of L.blobs) {
    if (b.hidden) continue;
    if (b.gulping) { b.bx += (d.x - b.bx) * 0.25; b.by += (d.y - b.by) * 0.25; }
    else { const a = L.spin + (i * Math.PI * 2) / n - Math.PI / 2; b.bx = d.x + Math.cos(a) * 118; b.by = d.y + Math.sin(a) * 118 * 0.92; }
    b.style.transform = `translate3d(${b.bx}px, ${b.by}px, 0)${b.gulping ? " scale(.3)" : ""}`;
    i++;
  }
  L.raf = requestAnimationFrame(libLoop);
}

// ---------- paper cards ----------
function libCard(p) {
  let c = L.cards.get(p.id);
  if (!c) {
    const el = h("div", { class: "lcard abs gone", role: "button", tabindex: "-1" });
    el.addEventListener("click", (e) => { e.stopPropagation(); libPeek(libP(p.id), el); });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); libPeek(libP(p.id), el); } });
    c = { el, x: 0, y: 0, tx: 0, ty: 0, r: 0, tr: 0, ph: Math.random() * 6, drift: true };
    c.x = c.tx = (L.st.clientWidth || 800) / 2; c.y = c.ty = (L.st.clientHeight || 600) / 2;
    L.cards.set(p.id, c); L.st.append(el);
  }
  const days = libDays(p);
  c.el.setAttribute("aria-label", `${p.title}. Open the details.`);
  c.el.style.setProperty("--tc", L.hue[p.id] || GREY);
  const keep = c.el.querySelector(".why")?.textContent || "";
  c.el.replaceChildren(h("h3", {}, p.title || "Untitled"),
    h("div", { class: "row" }, h("span", { class: "steps" }, p.progress.map((x) => h("i", { class: x }))),
      days != null && days >= 0 ? h("span", { class: "talk" }, days === 0 ? "Today" : days === 1 ? "Tomorrow" : libShortDate(p.presentation_date)) : null),
    h("div", { class: "why" }, keep), h("span", { class: "mark", "aria-hidden": "true" }));
  return c;
}
function libPlace(id, x, y, r = 0, opts = {}) {
  const c = L.cards.get(id); if (!c) return;
  c.tx = x; c.ty = y; c.tr = r; c.drift = opts.drift ?? true;
  c.el.classList.remove("gone", "dim"); c.el.tabIndex = 0;
  if (opts.snap) { c.x = x; c.y = y; c.r = r; }
}
function libHideCard(id) { const c = L.cards.get(id); if (c) { c.el.classList.add("gone"); c.el.tabIndex = -1; c.tx = L.dot.x; c.ty = L.dot.y; } }
function libCardsReset() {
  for (const c of L.cards.values()) c.el.classList.remove("fetched", "lift", "lit", "dim", "ok", "bad", "hot");
  for (const c of L.cards.values()) { const w = c.el.querySelector(".why"); if (w) w.textContent = ""; }
}

function libRing() {
  const P = L.papers, out = [], seen = new Set();
  const add = (list) => list.forEach((p) => { if (!seen.has(p.id) && out.length < RING_MAX) { seen.add(p.id); out.push(p); } });
  add(P.filter((p) => { const d = libDays(p); return d != null && d >= 0 && d <= 14 && p.steps_done < p.progress.length; })
    .sort((a, b) => a.presentation_date.localeCompare(b.presentation_date)));
  add(P.filter((p) => p.primer_status === "failed"));
  add([...P].sort((a, b) => (b.last_opened || "").localeCompare(a.last_opened || "")));
  return out;
}

// ---------- the small blobs ----------
function libBlob(k, name, color, run, calm = false) {
  const hint = LIB_HINT[k] || "";
  const attrs = { type: "button", class: `lblob k-${k}${calm ? " calm named" : " abs"}`, "aria-label": hint ? `${name}. ${hint}` : name, style: `--bc:${color}` };
  if (hint) attrs.title = hint;
  const b = h("button", attrs,
    h("span", { class: "bod" }), h("span", { class: "e" }, h("i"), h("i")), h("span", { class: "pr" }), h("span", { class: "tag" }, name));
  b.dataset.k = k; b.bx = 0; b.by = 0;
  b.addEventListener("click", (e) => { e.stopPropagation(); run(); });
  return b;
}
function libBlobsOut(on) {
  const empty = !L.total;
  L.blobs.forEach((b) => {
    b.hidden = empty && !["add", "set", "web"].includes(b.dataset.k);
    b.classList.toggle("out", !on); b.tabIndex = on ? 0 : -1; b.gulping = false;
    b.classList.toggle("bounce", empty && b.dataset.k === "add");
  });
  L.orbit = on;
}

// ---------- layout per state ----------
function libHome(soft = false) {
  if (!L) return;
  libClear(); libPeekClose();
  if (L.f && !L.f.el.hidden) libCloseField(true);
  L.mode = "bubble"; L.job = null; libStore.set("lib-mode", "bubble");
  if (L.web) { L.web.hidden = true; L.webGen++; L.webHits.replaceChildren(); L.webIn.disabled = false; L.webIn.value = ""; }
  L.st.classList.remove("chatting", "shelfing", "webbing", "hits");
  L.shelf.hidden = true; L.sblobs.hidden = true; L.strip.classList.remove("on");
  L.dotEl.className = "ldot abs"; L.dotEl.tabIndex = 0; L.dotEl.querySelector("input").tabIndex = -1;
  L.back.classList.remove("on"); L.lineGap = 150; L.count.style.opacity = 1;
  if (!soft) libCardsReset();
  libRelayout();
  libBlobsOut(true);
  libGreeting(); libCount();
}

function libRelayout() {
  if (!L || !L.st.clientWidth) return;
  const W = libW(), H = libH();
  if (L.mode === "shelf") { L.dot.tx = W / 2; L.dot.ty = 46; L.sblobs.style.transform = `translate3d(${W / 2}px, 84px, 0)`;
    L.count.style.transform = `translate3d(24px, 22px, 0)`; return; }
  if (L.job === "ask") return libAskLayout();
  if (L.job === "web") return libWebPlace();
  if (L.job) return;
  L.dot.tx = W / 2; L.dot.ty = H / 2 + 10;
  libPlaceRing(1, new Set());
}
// The floating ring of papers around the middle. While chatting it stays, a little wider, behind what Dot fetched.
function libPlaceRing(scale, skip) {
  const W = libW(), H = libH(), ring = libRing().filter((p) => !skip.has(p.id)), ids = new Set(ring.map((p) => p.id));
  const rx = Math.max(250, Math.min(W / 2 - 105, 470)) * scale, ry = Math.max(205, Math.min(H / 2 - 62, 300)) * scale;
  ring.forEach((p, i) => {
    const a = -Math.PI / 2 + Math.PI / ring.length + (i * Math.PI * 2) / ring.length;
    const j = 1 + (((i * 37) % 7) - 3) * 0.025;
    libPlace(p.id, W / 2 + Math.cos(a) * rx * j, H / 2 + 10 + Math.sin(a) * ry * j, (((i * 53) % 7) - 3) * 0.9);
  });
  for (const id of L.cards.keys()) if (!ids.has(id) && !skip.has(id)) libHideCard(id);
}

// ---------- jobs: a blob is swallowed, then it plays ----------
async function libJob(k) {
  if (k === "set") { location.hash = "#settings"; return; }
  const b = L.blobs.find((x) => x.dataset.k === k);
  libPeekClose(); libClear();
  if (b && !libRM()) {
    b.gulping = true; b.classList.add("out");
    await libWait(260);
    L.dotEl.classList.remove("gulp"); void L.dotEl.offsetWidth; L.dotEl.classList.add("gulp");
    await libWait(200);
  }
  if (!L) return;
  if (k === "super") { // the Dot space: it unfolds out of Dot on arrival
    try { sessionStorage.setItem("sp-back", "1"); } catch { /* it opens without the unfold */ }
    location.hash = "#space"; return;
  }
  if (k === "shelf") return libToShelf();
  if (k === "find") return libOpenField();
  if (k === "persona") return libOpenField(true);
  libBlobsOut(false);
  L.job = k; L.lineGap = 62; L.count.style.opacity = 0;
  L.back.classList.add("on");
  const W = libW(), H = libH();
  L.dot.tx = W / 2; L.dot.ty = k === "add" ? H / 2 - 20 : 150;
  L.back.style.transform = `translate3d(${W / 2 + (k === "add" ? 110 : 78)}px, ${L.dot.ty}px, 0)`;
  ({ next: libNext, talks: libTalks, pick: libPick, add: libAdd, web: libWeb })[k]();
}

function libFocusOn(p, msg) {
  const W = libW(), H = libH();
  for (const id of L.cards.keys()) if (id !== p.id) L.cards.get(id).el.classList.add("dim");
  const c = L.cards.get(p.id);
  libPlace(p.id, Math.max(110, W / 2 - 150), Math.min(H - 90, H / 2 + 40), -1.5, { drift: false });
  c.el.classList.add("lift");
  libSay(msg);
  libLater(650, () => libPeek(p, c.el));
}

async function libNext() {
  libSay("Looking at your talks and what is left...");
  L.dotEl.classList.add("think");
  await libWait(900);
  if (!L || L.job !== "next") return;
  L.dotEl.classList.remove("think");
  const open = L.papers.filter((p) => p.steps_done < p.progress.length);
  const soon = open.filter((p) => { const d = libDays(p); return d != null && d >= 0; }).sort((a, b) => a.presentation_date.localeCompare(b.presentation_date));
  const going = open.filter((p) => p.progress.some((x) => x !== "empty")).sort((a, b) => (b.last_opened || "").localeCompare(a.last_opened || ""));
  const p = soon[0] || going[0] || open[0];
  if (!p) return libSay("Every paper has all its steps done. Time for reflections.");
  const left = p.progress.length - p.steps_done;
  libFocusOn(p, soon[0] === p ? `Next: "${p.title}". The talk is ${relDays(p.presentation_date)} and ${plural(left, "step")} are left.`
    : `Next: "${p.title}". You started it, ${plural(left, "step")} to go.`);
}

function libPick() {
  const p = [...L.papers].filter((x) => x.last_opened).sort((a, b) => b.last_opened.localeCompare(a.last_opened))[0];
  if (!p) return libSay("You have not opened a paper yet. Pick one and I will remember it.");
  libFocusOn(p, `You were reading "${p.title}", ${ago(p.last_opened).toLowerCase()}.`);
}

function libTalks() {
  const W = libW(), iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const days = Array.from({ length: 14 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return d; });
  const byDay = Object.groupBy(L.papers.filter((p) => p.presentation_date), (p) => p.presentation_date);
  L.strip.replaceChildren(...days.map((d, i) => {
    const n = byDay[iso(d)]?.length ?? 0;
    return h("div", { class: [i === 0 && "today", n && "talk"].filter(Boolean).join(" "), title: (byDay[iso(d)] || []).map((p) => p.title).join("\n") },
      d.toLocaleDateString("en-GB", { weekday: "narrow" }), h("b", {}, String(d.getDate())),
      h("span", { class: "col" }, h("i"), h("i"), h("i"), h("i")));
  }));
  const colW = Math.min(56, (W - 40) / 14);
  L.strip.querySelectorAll("div").forEach((x) => { x.style.width = `${colW - 6}px`; });
  L.strip.style.transform = `translate3d(${W / 2}px, 208px, 0)`;
  L.strip.classList.add("on");
  const dated = days.flatMap((d, i) => (byDay[iso(d)] || []).map((p) => [p, i]));
  const shown = new Set(dated.map(([p]) => p.id));
  dated.forEach(([p, i], j) => libLater(250 + j * 70, () => {
    const x = W / 2 + (i - 6.5) * colW;
    libPlace(p.id, Math.min(W - 95, Math.max(95, x)), 380 + (j % 3) * 100, j % 2 ? 1.5 : -1.5, { drift: false });
  }));
  for (const id of L.cards.keys()) if (!shown.has(id)) libHideCard(id);
  const next = nextTalk(L.papers);
  libSay(!dated.length ? "No talks in the next two weeks." + (next ? ` The next one is ${relDays(next.presentation_date)}.` : "")
    : `${plural(dated.length, "talk")} in the next two weeks. ${next ? `The first is ${relDays(next.presentation_date)}.` : ""}`);
}

function libAdd() {
  L.dotEl.classList.add("tray");
  for (const id of L.cards.keys()) L.cards.get(id).el.classList.add("dim");
  libSay("Drop a PDF on me, or anywhere on the page.", [["Choose PDF", () => L.picker.click()]]);
}

// Web: the blob opens a query, Unsloth searches, and the pages land under Dot.
function libWebPlace() {
  const W = libW();
  L.dot.tx = W / 2; L.dot.ty = 150;
  L.back.style.transform = `translate3d(${W / 2 + 78}px, ${L.dot.ty}px, 0)`;
  if (L.web) L.web.style.transform = `translate3d(${W / 2}px, ${L.dot.ty + 78}px, 0) translate(-50%, 0)`;
}
function libWebPanel() {
  const input = h("input", { type: "search", maxlength: "200", "aria-label": "Words to look up", placeholder: "Words to look up",
    onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); libWebGo(input.value); } } });
  const hits = h("div", { class: "hits" });
  const el = h("div", { class: "lweb abs", hidden: true }, h("form", { onsubmit: (e) => { e.preventDefault(); libWebGo(input.value); } }, input), hits);
  el.addEventListener("pointerdown", (e) => e.stopPropagation());
  L.st.append(el);
  L.web = el; L.webIn = input; L.webHits = hits; L.webGen = 0;
}
function libWebHit(r, i = 0) {
  let u = null;
  try { u = new URL(r.url); } catch { u = null; }
  if (!u || !/^https?:$/.test(u.protocol)) return null;
  const host = u.host.replace(/^www\./, "");
  const path = decodeURIComponent(u.pathname).split("/").filter(Boolean).slice(0, 2).join(" \u203a ");
  // a letter tile tinted from the site's name: no icon fetched, so only your query ever leaves the Mac
  const hue = [...host].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
  return h("a", { class: "hit", href: r.url, target: "_blank", rel: "noopener noreferrer", style: `--i:${i};--hue:${hue}` },
    h("span", { class: "fav", "aria-hidden": "true" }, host[0]?.toUpperCase() || "?"),
    h("span", { class: "hbody" },
      h("span", { class: "host" }, host, path ? h("span", { class: "path" }, ` \u203a ${path}`) : null),
      h("strong", {}, r.title || host),
      r.snippet ? h("span", { class: "snip" }, r.snippet) : null),
    h("span", { class: "go", "aria-hidden": "true" }, "\u2197"));
}
function libWeb() {
  if (!L.web) libWebPanel();
  L.st.classList.add("chatting", "webbing");
  for (const id of L.cards.keys()) L.cards.get(id).el.classList.add("dim");
  L.web.hidden = false; L.webHits.replaceChildren(); L.webIn.value = ""; L.webIn.disabled = false;
  libWebPlace();
  libSay("What should I look up?");
  libLater(280, () => { if (L && L.job === "web") L.webIn.focus(); });
}
async function libWebGo(raw) {
  const q = raw.trim();
  if (!q || !L || L.job !== "web" || L.webIn.disabled) return;
  const gen = ++L.webGen;
  L.webIn.disabled = true; L.webHits.replaceChildren();
  L.dotEl.classList.add("think");
  libSay("Looking that up.");
  let res;
  try {
    res = await api("/library/web", { method: "POST", body: JSON.stringify({ q }) });
  } catch (e) {
    if (!L || L.job !== "web" || L.webGen !== gen) return;
    L.dotEl.classList.remove("think"); L.webIn.disabled = false;
    const why = typeof e.body?.detail === "string" ? e.body.detail : "Something went wrong on my side. Try again.";
    libSay(why); L.webIn.focus();
    return;
  }
  if (!L || L.job !== "web" || L.webGen !== gen) return;
  L.dotEl.classList.remove("think"); L.webIn.disabled = false;
  const rows = (res.results || []).map((r, i) => libWebHit(r, i)).filter(Boolean);
  L.webHits.replaceChildren(...rows);
  const lead = rows.length ? `I found ${plural(rows.length, "page")}.` : "Nothing came back for that.";
  libSay(res.note && rows.length ? `${lead} ${res.note}` : lead);
  L.webIn.focus();
}

// Drag Dot onto a paper to peek at it. A plain click on Dot says hello again.
function libDotDrag() {
  const d = L.dotEl;
  d.addEventListener("pointerdown", (e) => {
    if (L.mode !== "bubble" || L.job || e.button) return;
    const sx = e.clientX, sy = e.clientY, r0 = L.st.getBoundingClientRect();
    let moved = false, hot = null;
    d.setPointerCapture(e.pointerId);
    const move = (ev) => {
      if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 6) return;
      if (!moved) { moved = true; L.dragging = true; d.classList.add("drag"); libBlobsOut(false); }
      L.dot.x = ev.clientX - r0.left; L.dot.y = ev.clientY - r0.top;
      let found = null;
      for (const [id, c] of L.cards) {
        if (c.el.classList.contains("gone")) continue;
        const r = c.el.getBoundingClientRect();
        if (ev.clientX > r.left - 10 && ev.clientX < r.right + 10 && ev.clientY > r.top - 10 && ev.clientY < r.bottom + 10) found = id;
      }
      if (found !== hot) { hot && L.cards.get(hot)?.el.classList.remove("hot"); hot = found; hot && L.cards.get(hot).el.classList.add("hot"); }
      d.classList.toggle("peeking", !!hot);
    };
    const up = () => {
      d.removeEventListener("pointermove", move); d.removeEventListener("pointerup", up); d.removeEventListener("pointercancel", up);
      L.dragging = false; d.classList.remove("drag", "peeking");
      if (!moved) { libGreeting(); d.animate([{ scale: 1 }, { scale: "1.12 .9" }, { scale: ".95 1.06" }, { scale: 1 }], { duration: 420 }); return; }
      libBlobsOut(true);
      if (hot) { L.cards.get(hot).el.classList.remove("hot"); libPeek(libP(hot), L.cards.get(hot).el); }
    };
    d.addEventListener("pointermove", move); d.addEventListener("pointerup", up); d.addEventListener("pointercancel", up);
  });
  // Dot is a drop target too: a PDF dropped on it is added
  d.addEventListener("drop", (e) => { e.preventDefault(); });
}

// ---------- peek: everything a table row had ----------
function libPeek(p, anchor, keepPlace = false) {
  if (!p) return;
  L.peekId = p.id;
  const fw = L.fw[p.template] ?? L.fw.paper, total = p.progress.length;
  const at = p.progress.findIndex((x) => x !== "done"), step = at < 0 ? null : fw.steps[at];
  const where = p.steps_done === total ? `All ${total} steps done`
    : p.progress.every((x) => x === "empty") ? `Not started, ${fw.steps.reduce((t, x) => t + x.minutes, 0)} min in all`
    : `Step ${step.n} of ${total}: ${step.title}`;
  const go = p.steps_done === total ? "Review" : p.progress.every((x) => x === "empty") ? "Start reading" : "Continue";
  const done = h("input", { type: "checkbox", checked: p.reflection_done, class: "switch", "aria-label": `Reflection done for ${p.title}`,
    onchange: async () => { await api(`/papers/${p.id}`, { method: "PATCH", body: JSON.stringify({ reflection_done: done.checked }) });
      if (done.checked) buddy.say(`Reflection done for "${p.title}". Nice work.`, { mood: "happy" });
      libRedraw(); } });
  const chip = (text, cls = "") => h("span", { class: `pchip ${cls}` }, text);
  const chips = [
    p.presentation_date ? chip(`Talk ${fmtDate(p.presentation_date)}, ${relDays(p.presentation_date)}`)
      : h("button", { type: "button", class: "pchip add", onclick: () => detailsDialog(p, L.s, false) }, "+ Set talk date"),
    p.reflection_no ? chip(`Reflection ${p.reflection_no} of ${L.s.reflections_target}`) : null,
    p.primer_status !== "not_made" ? h("span", { class: `pchip ${p.primer_status}`, "data-primer": p.id }, primerLabel({ state: p.primer_status })) : null,
    p.seconds >= 60 ? chip(`${fmtSpent(p.seconds)} read`) : null,
    chip(p.last_opened ? `Opened ${ago(p.last_opened).toLowerCase()}` : "Not opened yet", "soft"),
    ...p.themes.map((id) => themeList.find((t) => t.id === id)).filter(Boolean)
      .map((t) => h("span", { class: "pchip theme", style: `--tc:var(--theme-${t.color})` }, h("i", { class: "tdot", style: `--tc:var(--theme-${t.color})` }), t.name)),
    themePicker(p),
    ...p.tags.map((t) => chip(t, "tag")),
  ].filter(Boolean);
  L.peek.style.setProperty("--tc", L.hue[p.id] || "var(--marker)");
  L.peek.replaceChildren(
    h("a", { class: "cov", href: `#read/${p.id}`, tabindex: -1, "aria-hidden": "true" },
      h("img", { src: `/papers/${p.id}/cover`, alt: "", onerror: (e) => e.target.replaceWith("PDF") })),
    h("div", { class: "main" },
      h("h4", {}, h("a", { href: `#read/${p.id}` }, p.title || "Untitled")),
      h("div", { class: "by" }, h("span", { class: "ptype" }, p.template === "slides" ? "Slides" : "Paper"), p.authors || "Authors unknown"),
      h("div", { class: "chips" }, chips),
      h("div", { class: "where" }, where),
      h("div", { class: "steps", role: "img", "aria-label": `${p.steps_done} of ${total} steps done` }, p.progress.map((x) => h("i", { class: x }))),
      h("div", { class: "acts" },
        h("a", { class: `btn${go === "Review" ? " ghost" : ""}`, href: `#read/${p.id}` }, go),
        h("label", { class: "pdone" }, done, "Reflection done"),
        rowMenu(p, L.s))),
    h("button", { class: "x", type: "button", "aria-label": "Close", onclick: () => libPeekClose() }, "×"));
  if (!keepPlace || !L.peek.classList.contains("on")) {
    const sr = L.st.getBoundingClientRect(), W = libW(), H = libH(), pw = Math.min(400, W - 24);
    let x = W / 2 - pw / 2, y = H / 2 - 100;
    if (anchor) {
      const r = anchor.getBoundingClientRect(), ax = r.left - sr.left, ay = r.top - sr.top;
      x = ax + r.width + 16 + pw < W ? ax + r.width + 16 : ax - pw - 16 > 0 ? ax - pw - 16 : W / 2 - pw / 2;
      y = ay - 10;
    }
    L.peek.style.transform = `translate3d(${Math.max(12, Math.min(W - pw - 12, x))}px, ${Math.max(12, Math.min(H - 250, y))}px, 0)`;
  }
  L.peek.classList.add("on");
  L.st.querySelectorAll(".lspine.peek").forEach((s) => s.classList.remove("peek"));
  if (anchor?.classList.contains("lspine")) anchor.classList.add("peek");
}
function libPeekClose() {
  if (!L || !L.peekId) return;
  L.peekId = null; L.peek.classList.remove("on");
  L.st.querySelectorAll(".lspine.peek").forEach((s) => s.classList.remove("peek"));
}

// ---------- Ask and Persona: the blob becomes the field; the bubble itself reacts as you type ----------
function libField() {
  const el = h("div", { class: "lfield abs", hidden: true });
  const goo = h("div", { class: "goo" }, h("div", { class: "body" }));
  const line = h("div", { class: "line" });
  const mirror = h("div", { class: "pmirror", "aria-hidden": "true" });
  const caret = h("span", { class: "lcaret", "aria-hidden": "true" });
  const input = h("input", { type: "text", maxlength: 500, "aria-label": "Ask Dot", placeholder: "Ask me anything about your papers" });
  const cap = h("p", { class: "pcap" });
  const area = h("textarea", { class: "parea", rows: 2, maxlength: 300, "aria-label": "Who Dot is now", placeholder: "A calm tutor who loves puns" });
  const clear = h("button", { type: "button", class: "pclear" }, "Back to my usual self");
  el.append(goo, line, caret, input, cap, area, mirror, clear);
  L.st.append(el);
  L.f = { el, goo, body: goo.firstChild, line, mirror, caret, input, cap, area, clear, shown: "", persona: false, gen: 0, ctl: null, retry: "" };
  input.addEventListener("input", () => {
    if (L.f.persona) return;
    if (el.classList.contains("dot")) { const v = input.value; libNewTurn(false); input.value = v; } // first key clears the reply
    libTypeTo(input.value);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && input.value.trim() && !input.disabled && !L.f.persona) { e.preventDefault(); libSend(input.value.trim()); }
  });
  // the Ask caret is drawn by hand (the input is invisible), so keep it where the real caret is
  for (const ev of ["keyup", "click", "select", "focus", "blur"]) input.addEventListener(ev, () => { if (!L.f.persona) libCaret(); });
  area.addEventListener("input", () => {
    if (!L.f.persona) return;
    L.f.cap.textContent = area.value.trim() ? "Right now I am" : "No persona yet";
    libTypeTo(area.value);
  });
  area.addEventListener("scroll", () => { mirror.scrollTop = area.scrollTop; });
  area.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !area.disabled) { e.preventDefault(); if (area.value.trim()) libSetPersona(area.value.trim()); }
  });
  clear.addEventListener("click", (e) => { e.stopPropagation(); if (!L.f.asking) libSetPersona(""); });
  el.addEventListener("pointerdown", (e) => e.stopPropagation());
  el.addEventListener("click", () => { if (!L.f.asking && el.classList.contains("dot") && !L.f.persona) libNewTurn(); });
  L.histEl.addEventListener("pointerdown", (e) => e.stopPropagation());
  L.st.addEventListener("click", (e) => { if (L.job === "ask" && !e.target.closest(".lfield, .lcard, .lpeek, .lhist, dialog") && (!L.f.asking || L.f.ctl)) libCloseField(); });
}
// Where is the caret (character offset `at`) inside the word spans of `box`? Returns viewport coordinates.
function libCaretAt(box, at) {
  const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
  let n = walk.nextNode(), left = at, last = null;
  while (n) {
    last = n;
    if (left <= n.nodeValue.length) break;
    left -= n.nodeValue.length; n = walk.nextNode();
  }
  if (last) {
    const r = document.createRange(), off = Math.min(left, last.nodeValue.length);
    r.setStart(last, off); r.collapse(true);
    const b = r.getClientRects()[0] || r.getBoundingClientRect();
    if (b && (b.height || b.width)) return { x: b.left, y: b.top + b.height / 2 };
  }
  const br = box.getBoundingClientRect(), cs = getComputedStyle(box);
  return { x: br.left + parseFloat(cs.paddingLeft), y: br.top + parseFloat(cs.paddingTop) + 11 };
}
// Ask draws its own caret over the word spans, because the input itself is invisible.
function libCaret() {
  const f = L.f; if (!f || f.el.hidden || f.persona) return;
  const ctl = f.input, fb = f.el.getBoundingClientRect();
  const on = document.activeElement === ctl && !ctl.disabled && !f.el.classList.contains("dot") && !f.el.classList.contains("think");
  if (!on) { f.caret.style.cssText = ""; return; }
  const c = libCaretAt(f.line, ctl.selectionStart ?? ctl.value.length);
  f.caret.style.cssText = `opacity:1;transform:translate(${c.x - fb.left}px,${c.y - fb.top - 10}px)`;
}
function libFitField() {
  const f = L.f;
  if (f.el.classList.contains("persona") && !f.el.classList.contains("dot")) {
    // The field grows from a small blob. Measuring mid-grow wraps every letter and the box becomes a sheet.
    if (f.el.getBoundingClientRect().width < 200) return;
    f.area.style.height = "0px";
    const raw = f.area.scrollHeight;
    const textH = Math.min(132, Math.max(48, raw));
    f.area.style.height = `${textH}px`;
    f.area.style.overflow = raw > 132 ? "auto" : "hidden";
    const clearH = f.clear.hidden ? 0 : f.clear.offsetHeight + 8;
    f.el.style.height = `${f.cap.offsetHeight + textH + clearH + 22}px`;
    // the mirror sits exactly over the textarea so words can settle in while the real text stays editable
    Object.assign(f.mirror.style, { top: `${f.area.offsetTop}px`, width: `${f.area.offsetWidth}px`, height: `${textH}px` });
    f.mirror.scrollTop = f.area.scrollTop;
    return;
  }
  f.el.style.height = `${Math.max(52, f.line.offsetHeight)}px`;
  if (L.fetched?.length) libLayoutFetched(); // a longer reply pushes the results down
}
// Typing shows whole words, drawn as plain text while you type them. When a word is finished (a space follows it)
// it fades up once as one piece and the bubble gives a small squash. Nothing animates per letter.
// Ask draws the words itself (the input is invisible); Persona draws them over the real textarea.
// `quiet` is for a value that was already there: no fade, no squash.
function libTypeTo(text, quiet = false) {
  const f = L.f, box = f.persona ? f.mirror : f.line, toks = text.split(/(\s+)/).filter(Boolean), go = !quiet && !libRM();
  let finished = 0;
  toks.forEach((tok, i) => {
    const old = box.childNodes[i], space = /^\s/.test(tok);
    let node = old;
    if (old && (old.nodeType === 3) === space && (space || old.classList.contains("w"))) {
      if (old.textContent !== tok) old.textContent = tok;
    } else {
      node = space ? document.createTextNode(tok) : h("span", { class: "w" }, tok);
      if (old) old.replaceWith(node); else box.append(node);
    }
    // a word is finished once something follows it
    if (!space && i < toks.length - 1 && !node.classList.contains("done")) {
      node.classList.add("done");
      if (go) { node.style.setProperty("--d", `${Math.min(finished, 6) * 35}ms`); node.classList.add("in"); }
      finished++;
    }
  });
  while (box.childNodes.length > toks.length) box.lastChild.remove();
  f.shown = text; f.el.classList.toggle("has-text", !!text);
  libFitField(); libCaret();
  if (finished && go) libSquash();
}
// The bubble itself squashes a little and springs back. Only the blob behind the text moves, never the letters.
function libSquash() {
  const f = L.f, w = f.el.offsetWidth || 1, hh = f.el.offsetHeight || 1;
  f.body.animate([{ scale: "1 1" }, { scale: `${1 + 7 / w} ${1 - 5 / hh}`, offset: 0.4 }, { scale: "1 1" }],
    { duration: 240, easing: "cubic-bezier(.22,1,.36,1)" });
  L.dotEl.animate([{ scale: "1 1" }, { scale: "1.035 .965", offset: 0.4 }, { scale: "1 1" }], { duration: 240, easing: "cubic-bezier(.22,1,.36,1)" }); // Dot answers with the bubble
}
// Dot's reply floats up in a wave, word by word, on Dot's yellow.
function libReplyTo(text, buttons = []) {
  const f = L.f;
  f.el.classList.add("dot");
  const acts = buttons.map(([label, fn]) => h("button", { type: "button", onclick: (e) => { e.stopPropagation(); fn(); } }, label));
  if (f.persona) {
    // one sentence, settling in together, rather than a character typing each letter
    f.line.replaceChildren(h("span", { class: "whole" }, text), ...acts);
    f.shown = "\u0000";
    libFitField();
    return libWait(libRM() ? 0 : 460);
  }
  let i = 0;
  f.line.replaceChildren(...text.split(/(\s+)/).map((w) => (/^\s+$/.test(w) ? w
    : h("span", { class: libRM() ? "w" : "w in", style: `--d:${Math.min(i++ * 28, 700)}ms` }, w))), ...acts);
  f.shown = "\u0000";
  libFitField();
  return libWait(libRM() ? 0 : Math.min(1000, i * 28 + 300));
}
function libDing() {
  const f = L.f, d = h("span", { class: "ding" }, "ding");
  d.style.left = `${f.el.offsetWidth - 56}px`; d.style.top = "-26px"; f.el.append(d);
  d.animate([{ opacity: 0, transform: "translateY(4px) scale(.7)" }, { opacity: 1, transform: "translateY(-4px) scale(1)", offset: 0.3 },
    { opacity: 0, transform: "translateY(-14px)" }], { duration: 900, easing: "cubic-bezier(.22,1,.36,1)" }).onfinish = () => d.remove();
}
// Sending: the question slides away as one piece and the bubble squashes, then Dot's yellow bubble thinks.
async function libSwallow() {
  const f = L.f;
  f.caret.style.cssText = "";
  if (libRM()) { f.line.replaceChildren(); f.shown = ""; return; }
  libSquash();
  const gone = f.line.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(-6px)" }],
    { duration: 220, easing: "cubic-bezier(.55,0,.8,.4)", fill: "forwards" });
  await libWait(240);
  gone.cancel(); f.line.replaceChildren(); f.shown = "";
}

// Dot stays where it is; the field opens right under it, fetched papers rise into the ring around it.
function libAskLayout() {
  const W = libW(), H = libH();
  L.dot.tx = W / 2; L.dot.ty = L.fetched?.length ? Math.max(70, H * 0.16) : H / 2 - 40; // results need the room below
  const fw = Math.min(460, W * 0.84), top = L.dot.ty + 64;
  L.f.el.style.transform = `translate3d(${W / 2}px, ${top}px, 0) translate(-50%, 0)`;
  L.histEl.style.transform = `translate3d(${W / 2 - fw / 2 - 16}px, ${top - 12}px, 0) translate(-100%, 0)`;
  libLayoutFetched();
}
function libShowPersona(now) {
  const f = L.f;
  f.area.value = now;
  f.area.disabled = false;
  f.cap.textContent = now ? "Right now I am" : "No persona yet";
  f.clear.hidden = !now;
  libTypeTo(now, true);
}
function libOpenField(persona = false) {
  const f = L.f, src = L.blobs.find((b) => b.dataset.k === (persona ? "persona" : "find"));
  f.persona = persona; f.gen++; f.ctl?.abort(); f.ctl = null; f.retry = "";
  f.input.placeholder = "Ask me anything about your papers";
  L.job = "ask"; L.lineGap = 62;
  libBlobsOut(false); libCardsReset();
  L.st.classList.add("chatting"); L.line.classList.add("off"); L.count.style.opacity = 0;
  f.el.hidden = false; f.el.className = persona ? "lfield abs persona" : "lfield abs";
  f.el.style.transition = "none";
  f.el.style.transform = `translate3d(${src?.bx ?? L.dot.x}px, ${(src?.by ?? L.dot.y) - 18}px, 0) translate(-50%, 0)`;
  f.input.value = ""; f.input.disabled = false; f.line.replaceChildren(); f.mirror.replaceChildren(); f.caret.style.cssText = ""; f.shown = ""; f.asking = false;
  const shown = persona ? (L.s.dot_persona?.trim() || "") : "";
  if (persona) { f.area.value = shown; f.area.disabled = false; f.cap.textContent = shown ? "Right now I am" : "No persona yet"; f.clear.hidden = !shown; libTypeTo(shown, true); }
  void f.el.offsetWidth; f.el.style.transition = "";
  f.el.style.transition = "transform .55s cubic-bezier(.22,1,.36,1), width .6s cubic-bezier(.22,1,.36,1), height .4s cubic-bezier(.22,1,.36,1)";
  requestAnimationFrame(() => { f.el.classList.add("open"); libAskLayout(); if (persona) libLater(640, () => { if (L && L.f.persona) libFitField(); }); });
  L.fetched = [];
  L.histEl.classList.toggle("off", persona || !L.hist.length);
  if (persona && !libRM()) { L.dotEl.classList.add("blink"); libLater(160, () => L.dotEl?.classList.remove("blink")); }
  libLater(380, () => (persona ? f.area : f.input).focus());
  if (persona) api("/settings").then((fresh) => {
    if (!L || !f.persona || f.asking || f.area.value !== shown) return;
    L.s = fresh; libShowPersona(fresh.dot_persona?.trim() || "");
  }).catch(() => {});
}

// Persona: you tell Dot who to be. Saved in Settings; Dot talks that way when you Ask.
async function libSetPersona(text) {
  const f = L.f;
  f.asking = true; f.area.disabled = true; f.el.classList.add("think");
  try {
    L.s = await api("/settings", { method: "PATCH", body: JSON.stringify({ dot_persona: text.slice(0, 300) }) });
    f.el.classList.remove("think", "dot");
    libShowPersona((L.s.dot_persona || "").trim());
    if (!libRM()) L.dotEl.animate([{ scale: 1 }, { scale: "1.06 .96" }, { scale: 1 }], { duration: 420 });
  } catch (e) {
    f.el.classList.remove("think"); f.area.disabled = false;
    f.cap.textContent = e.body?.detail?.errors?.dot_persona ? "That is too long. Keep it under 300 letters." : "I could not save that. Try again.";
  }
  f.asking = false;
}
function libCloseField(quiet = false) {
  const f = L.f; if (!f || f.el.hidden) return;
  f.gen++; f.ctl?.abort(); f.ctl = null; f.retry = ""; f.asking = false;
  libTuckTurn();
  f.el.classList.remove("open", "dot", "think", "has-text", "persona"); f.persona = false;
  f.el.style.height = ""; f.line.replaceChildren(); f.mirror.replaceChildren(); f.caret.style.cssText = ""; f.shown = "";
  L.histEl.classList.add("off");
  const W = libW(), H = libH();
  f.el.style.transform = `translate3d(${W / 2}px, ${H / 2 - 120}px, 0) translate(-50%, 0)`;
  libLater(420, () => { f.el.hidden = true; });
  L.job = null;
  if (!quiet) libHome();
}
// After a reply the typing line comes back: the reply stays until the first key, so it can be read.
function libReady() {
  const f = L && L.f; if (!f || f.el.hidden || L.job !== "ask") return;
  f.asking = false; f.ctl = null; f.input.disabled = false; f.input.value = "";
  if (!f.persona) { f.input.focus(); libCaret(); }
}
// Clear the reply and show an empty typing line, or the words of a question that failed.
function libNewTurn(restore = true) {
  const f = L.f;
  libTuckTurn();
  f.el.classList.remove("dot", "think"); f.line.replaceChildren(); f.shown = "";
  if (f.persona) { f.input.disabled = false; libShowPersona(L.s.dot_persona?.trim() || ""); f.area.focus(); return; }
  const back = restore ? f.retry || "" : ""; f.retry = "";
  f.asking = false; f.input.disabled = false; f.input.value = back;
  libTypeTo(back, true); f.input.focus(); libCaret();
}
// Escape: cancel a pending question, leave a reply for a fresh line, or close the field.
function libEscape() {
  const f = L.f;
  if (f.persona || f.el.hidden) return libCloseField();
  if (f.ctl) { const q = L.turn?.q || ""; f.gen++; f.ctl.abort(); f.ctl = null; L.turn = null; f.retry = q; return libNewTurn(); }
  if (f.asking) return libCloseField();
  if (f.el.classList.contains("dot")) return libNewTurn();
  libCloseField();
}
function libTuckTurn() {
  const t = L.turn; if (!t || !t.a) return;
  L.turn = null;
  const c = h("button", { type: "button", class: "chip" }, h("span", { class: "q" }, t.q), h("span", { class: "a" }, t.a.length > 90 ? `${t.a.slice(0, 88)}…` : t.a));
  c.addEventListener("click", (e) => { e.stopPropagation(); L.f.input.disabled = true; L.turn = null; libReplyTo(t.a); if (t.res) libRaise(t.res); });
  L.histEl.append(c);
  while (L.histEl.children.length > 5) L.histEl.firstChild.remove();
  [...L.histEl.children].forEach((x, i, a) => { x.className = `chip${i < a.length - 2 ? " older" : i < a.length - 1 ? " old" : ""}`; });
  L.histEl.classList.remove("off");
}

// Papers Dot fetched rise below the field, each with why it fits (or the page it answers from).
function libRaise(res) {
  libCardsReset();
  const items = [];
  const why = new Map();
  for (const x of res.papers || []) { why.set(x.id, x.why); items.push(x.id); }
  const refs = new Map();
  for (const s of res.sources || []) {
    if (!items.includes(s.paper_id)) items.push(s.paper_id);
    refs.set(s.paper_id, [...(refs.get(s.paper_id) || []), s]);
  }
  for (const [id, list] of refs) {
    const head = list.map((s) => `[${s.n}] p. ${s.page}`).join("  ");
    why.set(id, `${head}\n${why.get(id) || `"${list[0].snippet.slice(0, 120).trim()}..."`}`);
  }
  L.fetched = items.filter((id) => L.cards.has(id)).slice(0, 8);
  libPlaceRing(L.fetched.length ? 1.16 : 1, new Set(L.fetched));
  L.fetched.forEach((id) => { const c = L.cards.get(id); c.el.classList.add("fetched"); c.el.querySelector(".why").textContent = why.get(id) || ""; });
  libAskLayout();
}
function libLayoutFetched() {
  L.st.classList.toggle("hits", !!L.fetched?.length);
  if (!L.fetched?.length) return;
  // a tidy grid under the field, best first; the rest of the shelf steps aside (see .lst.hits)
  const W = libW(), n = L.fetched.length, fh = parseFloat(L.f.el.style.height) || L.f.el.offsetHeight || 52; // the height it is growing to
  const cw = Math.max(...L.fetched.map((id) => L.cards.get(id).el.offsetWidth || 150)) + 18;
  const ch = Math.max(...L.fetched.map((id) => L.cards.get(id).el.offsetHeight || 130)) + 16;
  const cols = Math.max(1, Math.min(n, Math.floor((W - 32) / cw), 4)), top = L.dot.ty + 64 + fh + 34;
  L.fetched.forEach((id, i) => {
    const row = Math.floor(i / cols), inRow = Math.min(cols, n - row * cols), col = i % cols;
    const el = L.cards.get(id).el;
    libPlace(id, W / 2 + (col - (inRow - 1) / 2) * cw, top + row * ch + (el.offsetHeight || 120) / 2, 0, { drift: false });
  });
}

const LIB_JOB = {
  summarize: { verb: "Making the AI summary", run: async (p, c) => {
    const end = await streamPrimer(p.id, (e) => { c.el.querySelector(".why").textContent = primerLabel(e); });
    return end.state === "ready"; } },
  set_date: { verb: "Setting the talk date", run: (p, c, a) => api(`/papers/${p.id}`, { method: "PATCH", body: JSON.stringify({ presentation_date: a.date }) }) },
  add_theme: { verb: "Adding to the theme", run: (p, c, a) => api(`/papers/${p.id}/themes`, { method: "PUT", body: JSON.stringify({ ids: [...new Set([...p.themes, a.themeId])] }) }) },
  mark_done: { verb: "Marking the reflection done", run: (p) => api(`/papers/${p.id}`, { method: "PATCH", body: JSON.stringify({ reflection_done: true }) }) },
  delete: { verb: "Deleting", run: (p) => api(`/papers/${p.id}`, { method: "DELETE" }) },
};

async function libSend(q) {
  const f = L.f, gen = f.gen;
  libDing(); f.input.value = ""; f.input.disabled = true; f.asking = true; f.retry = "";
  L.turn = { q, a: "" };
  await libSwallow();
  if (!L || f.gen !== gen) return;
  // never an empty pill while we wait: Dot's yellow bubble says so
  f.el.classList.add("think"); libReplyTo("One moment.");
  const ctl = f.ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 200000);
  let res;
  try {
    res = await api("/library/ask", { method: "POST", signal: ctl.signal, body: JSON.stringify({ question: q, history: L.hist.slice(-4) }) });
  } catch (e) {
    clearTimeout(timer);
    if (!L || f.gen !== gen) return; // closed or cancelled while waiting: ignore
    f.ctl = null; f.el.classList.remove("think"); L.turn = null;
    const why = e.name === "AbortError" ? "That took too long. Try again."
      : e.status === 404 ? "I need the app restarted before I can answer. Stop it and start it again."
      : typeof e.body?.detail === "string" ? e.body.detail : "Something went wrong on my side. Try again.";
    // say so, then bring the typing line back with their words in it
    f.retry = q; f.asking = false;
    await libReplyTo(why);
    await libWait(libRM() ? 0 : 1600);
    if (L && f.gen === gen && f.retry === q && f.el.classList.contains("dot")) libNewTurn();
    return;
  }
  clearTimeout(timer);
  if (!L || f.gen !== gen || L.job !== "ask") return;
  f.ctl = null;
  f.el.classList.remove("think");
  const a = res.action || { kind: "none", paper_ids: [] };
  let ids = (a.paper_ids || []).filter((id) => libP(id));
  let reply = res.reply || "Done.";
  if (a.kind === "summarize") {
    const skip = ids.filter((id) => ["ready", "making"].includes(libP(id).primer_status));
    ids = ids.filter((id) => !skip.includes(id));
    if (skip.length) reply += ` I skipped ${plural(skip.length, "paper")} that already ${skip.length === 1 ? "has" : "have"} one.`;
    if (ids.length > 1) reply += " Keep this page open while I work.";
    if (!ids.length) a.kind = "none";
  }
  if (a.kind === "export" && ids.length !== 1) { reply += ids.length ? " Click the one you want and use More, then Export." : ""; a.kind = "find"; }
  L.turn.a = reply.replace(/\s+/g, " "); L.turn.res = res;
  L.hist.push({ q, a: L.turn.a }); L.hist = L.hist.slice(-4);
  if ((res.papers || []).length || (res.sources || []).length) libRaise(res); else { libCardsReset(); L.fetched = []; libAskLayout(); libPlaceRing(1, new Set()); }
  if (a.kind === "delete") {
    await libReplyTo(reply, [["Yes, delete", () => libRunJob(a, ids, "Deleted.")], ["No", () => libReplyTo("Kept them. Nothing was deleted.").then(() => libReady())]]);
    return;
  }
  if (res.web) { // not in the papers: one tap takes the question to the web search
    const q2 = res.web;
    await libReplyTo(reply, [["Search the web", async () => { libCloseField(true); await libJob("web"); if (L?.job === "web") { L.webIn.value = q2; libWebGo(q2); } }], ["No", () => libReady()]]);
    return;
  }
  if (a.kind !== "export" && !(LIB_JOB[a.kind] && ids.length)) { libReplyTo(reply); libReady(); return; } // the typing line is usable while the reply settles in
  await libReplyTo(reply);
  if (f.gen !== gen) return;
  if (a.kind === "export") { exportDialog(libP(ids[0]), "markdown"); libReady(); return; }
  if (LIB_JOB[a.kind] && ids.length) return libRunJob(a, ids);
  libReady();
}

// Helpers fly to each paper in turn and do the job through the existing endpoints.
async function libRunJob(a, ids, doneText) {
  const f = L.f; f.asking = true;
  if (a.kind === "add_theme") {
    let t = themeList.find((x) => x.name.toLowerCase() === a.theme.toLowerCase());
    try { t ||= await api("/themes", { method: "POST", body: JSON.stringify({ name: a.theme }) }); }
    catch { await libReplyTo(`I could not make the theme "${a.theme}".`); libReady(); return; }
    a.themeId = t.id;
  }
  const job = LIB_JOB[a.kind];
  const helper = h("div", { class: "lhelper abs" });
  L.st.append(helper);
  let at = { x: L.dot.x, y: L.dot.y }, ok = 0, bad = [];
  const fly = (x, y) => { const anim = helper.animate([{ transform: `translate3d(${at.x}px, ${at.y}px, 0)` }, { transform: `translate3d(${x}px, ${y - 40}px, 0)` }],
    { duration: libRM() ? 1 : 520, easing: "cubic-bezier(.3,1.2,.4,1)", fill: "forwards" }); at = { x, y: y - 40 }; return anim.finished; };
  for (const id of ids) {
    if (!L || !L.st.contains(helper)) return;
    const p = libP(id), c = L.cards.get(id);
    if (!p || !c) continue;
    await fly(c.tx, c.ty);
    c.el.classList.add("lit"); helper.classList.add("work");
    let good = false;
    try { good = (await job.run(p, c, a)) !== false; } catch { good = false; }
    helper.classList.remove("work"); c.el.classList.remove("lit");
    c.el.classList.add(good ? "ok" : "bad");
    c.el.querySelector(".mark").textContent = good ? "✓" : "×";
    if (good) ok++; else bad.push(p.title);
  }
  await fly(L.dot.x, L.dot.y + 40);
  helper.remove();
  if (!L) return;
  await libraryRefresh();
  if (!L || L.job !== "ask") return;
  if (a.kind === "delete") for (const id of ids) libHideCard(id);
  const msg = doneText && !bad.length ? doneText
    : bad.length ? `Done with ${ok}. These did not work: ${bad.map((t) => `"${t}"`).join(", ")}.` : `All done, ${plural(ok, "paper")}.`;
  await libReplyTo(msg);
  if (L.turn) L.turn.a += ` ${msg}`;
  libReady();
}

// ---------- shelf mode ----------
function libToShelf() {
  if (!L.total) return libHome();
  libClear(); libPeekClose();
  if (L.f && !L.f.el.hidden) libCloseField(true);
  L.mode = "shelf"; L.job = null; libStore.set("lib-mode", "shelf");
  L.st.classList.remove("chatting", "hits"); L.st.classList.add("shelfing"); L.strip.classList.remove("on");
  libBlobsOut(false); L.blobs.forEach((b) => { b.classList.add("out"); });
  for (const id of L.cards.keys()) libHideCard(id);
  L.back.classList.remove("on"); L.line.classList.add("off"); L.count.style.opacity = 1;
  L.dotEl.className = "ldot abs pill"; L.dotEl.tabIndex = -1;
  const inp = L.dotEl.querySelector("input");
  inp.tabIndex = 0; inp.value = L.q; L.shelfInput = "search";
  inp.placeholder = "Search titles, authors, tags, notes. Enter asks me";
  inp.oninput = () => { if (L.shelfInput === "search") libFilter(inp.value); };
  inp.onkeydown = async (e) => {
    if (e.key !== "Enter" || !inp.value.trim()) return;
    if (L.shelfInput === "theme") {
      try { await api("/themes", { method: "POST", body: JSON.stringify({ name: inp.value.trim() }) });
        themeList = (await api("/themes")).themes; L.groupBy = "mine"; libStore.set("lib-group", "mine"); }
      catch (x) { libShelfSay(x.body?.detail?.errors?.name ?? "Could not add the theme."); return; }
      L.shelfInput = "search"; inp.value = ""; inp.placeholder = "Search titles, authors, tags, notes. Enter asks me";
      libShelfSay("New theme made. Add papers to it from a paper's + Theme."); libRenderShelf(); return;
    }
    const q = inp.value.trim(); inp.value = ""; L.q = ""; L.qIds = null;
    libHome(); await libJob("find"); libLater(500, () => { L.f.input.value = q; libTypeTo(q); libLater(300, () => libSend(q)); });
  };
  L.sblobs.hidden = false; libShelfTags();
  L.shelf.hidden = false;
  libRelayout(); libCount();
  libRenderShelf();
  libLater(500, () => inp.focus());
}
function libShelfSay(text) {
  libSay(text); L.lineGap = -150;
  libLater(3200, () => { if (L?.mode === "shelf") L.line.classList.add("off"); });
}
function libShelfTags() {
  const SHORT = { date: "Talk date", opened: "Last opened", title: "Title", progress: "Progress" };
  const tag = { group: L.groupBy === "sim" ? "Similar" : "My themes", sort: SHORT[SORTS[L.sortI][0]], show: STATUSES[L.showI][1],
    theme: "+ Theme", add: "+ Paper", set: "Settings", bubble: "Bubble" };
  const what = { group: "Group shelves by", sort: "Sort by", show: "Show", theme: "Make a new theme", add: "Add a paper", set: "Settings", bubble: "Back to bubble mode" };
  L.sblobs.querySelectorAll(".lblob").forEach((b) => { b.querySelector(".tag").textContent = tag[b.dataset.k];
    b.setAttribute("aria-label", `${what[b.dataset.k]}: ${tag[b.dataset.k]}`); b.title = what[b.dataset.k]; });
}
async function libShelfOpt(k) {
  if (k === "bubble") return libHome();
  if (k === "set") { location.hash = "#settings"; return; }
  if (k === "add") return L.picker.click();
  if (k === "theme") { const inp = L.dotEl.querySelector("input"); L.shelfInput = "theme"; inp.value = ""; inp.placeholder = "Name the new theme, then Enter"; inp.focus(); return; }
  if (k === "group") { L.groupBy = L.groupBy === "sim" ? "mine" : "sim"; libStore.set("lib-group", L.groupBy); }
  if (k === "sort") L.sortI = (L.sortI + 1) % SORTS.length;
  if (k === "show") L.showI = (L.showI + 1) % STATUSES.length;
  libShelfTags(); libRenderShelf();
  if (k === "group") libShelfSay(L.groupBy === "sim" ? (L.mapReason ? `I can't sort by meaning yet: ${L.mapReason}` : "Shelves by similarity. I named them.") : "Shelves by your themes.");
}
let libFilterTimer;
function libFilter(q) {
  L.q = q;
  clearTimeout(libFilterTimer);
  if (q.trim().length < 2) { L.qIds = null; libMarkSpines(); return; }
  libFilterTimer = setTimeout(async () => {
    const r = await api(`/papers?${new URLSearchParams({ q })}`).catch(() => null);
    if (!L || L.q !== q || !r) return;
    L.qIds = new Set(r.papers.map((p) => p.id)); libMarkSpines();
  }, 220);
}
function libMarkSpines() {
  const st = STATUSES[L.showI][0], hits = [];
  L.shelf.querySelectorAll(".lspine").forEach((s) => {
    const p = libP(s.dataset.id); if (!p) return;
    const okStatus = st === "all" || p.status === st, okQ = !L.qIds || L.qIds.has(p.id);
    s.classList.toggle("miss", !(okStatus && okQ));
    s.classList.toggle("found", !!L.qIds && okQ && okStatus);
    if (L.qIds && okQ && okStatus) hits.push(s);
  });
  if (hits[0]) hits[0].scrollIntoView({ block: "nearest", behavior: libRM() ? "auto" : "smooth" });
}
function libSortKey(p) {
  const k = SORTS[L.sortI][0];
  if (k === "opened") return [p.last_opened ? 0 : 1, -(Date.parse((p.last_opened || "").replace(" ", "T")) || 0)];
  if (k === "title") return [p.title.toLowerCase()];
  if (k === "progress") return [-p.steps_done];
  const d = libDays(p);
  return d == null ? [2, 0] : d >= 0 ? [0, d] : [1, -d];
}
const libCmp = (a, b) => { const x = libSortKey(a), y = libSortKey(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; return 0; };
function libRenderShelf() {
  if (L.mode !== "shelf") return;
  let rows;
  if (L.groupBy === "sim" && L.groups.length) {
    rows = L.groups.map((g) => ({ name: g.name, tc: HUES[g.hue % HUES.length], ids: g.paper_ids }));
    if (L.unread.length) rows.push({ name: "Dot has not read these yet", tc: GREY, ids: L.unread });
  } else {
    rows = themeList.map((t) => ({ name: t.name, tc: `var(--theme-${t.color})`, ids: L.papers.filter((p) => p.themes.includes(t.id)).map((p) => p.id), theme: t }));
    rows.push({ name: "Unsorted", tc: GREY, ids: L.papers.filter((p) => !p.themes.length).map((p) => p.id) });
    rows = rows.filter((r) => r.ids.length || r.theme);
  }
  L.shelf.replaceChildren(...rows.map((r, ri) => {
    const papers = r.ids.map(libP).filter(Boolean).sort(libCmp);
    return h("section", { class: "srow", style: `--tc:${r.tc}` },
      h("div", { class: "slabel" }, h("i"), h("span", { title: r.name }, r.name), h("small", {}, String(papers.length)),
        r.theme ? h("button", { type: "button", class: "del", "aria-label": `Delete the theme ${r.name}`, title: "Delete theme", onclick: async () => {
          if (!confirm(`Delete the theme "${r.name}"? Papers stay in the library, only the theme goes.`)) return;
          await api(`/themes/${r.theme.id}`, { method: "DELETE" }).catch(() => {});
          libraryRefresh(); } }, "×") : null),
      h("div", { class: "plank", style: `--r:${ri}` }, papers.length ? papers.map((p, k) => {
        const frac = p.steps_done / p.progress.length;
        const s = h("button", { type: "button", class: "lspine", "data-id": p.id, "aria-label": p.title,
          style: `--tc:${L.hue[p.id] || (L.groupBy === "mine" ? r.tc : GREY)};--hgt:${138 + ((p.title.length * 7) % 34)}px;--r:${ri};--k:${k}` },
        h("span", {}, p.title), h("i", { class: `sd${frac >= 1 ? " full" : frac > 0 ? " half" : ""}` }));
        s.addEventListener("click", (e) => { e.stopPropagation(); libPeek(libP(p.id), s); });
        return s;
      }) : h("span", { class: "none" }, "Empty for now")));
  }));
  if (!rows.length) L.shelf.append(h("p", { class: "none" }, "No papers yet."));
  libMarkSpines();
}
