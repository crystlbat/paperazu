"use strict";
// The Library around Dot. Bubble mode: Dot in the middle, papers floating around it, coloured by similarity,
// little character blobs orbiting as options, and an Ask field where Dot finds papers, answers across them
// and sends helpers to do jobs. Shelf mode: Dot wears glasses and becomes the search pill over shelves of spines.
// Uses app.js globals (h, api, themeList, streamPrimer, themePicker, rowMenu, ...). Positions are set every frame
// with transforms in one loop; CSS does the rest. Design: docs/superpowers/specs/2026-11-07-library-dot-design.md

const LIB_BLOBS = [["find", "Ask", "#8ecbff"], ["next", "What next?", "#7bd88f"], ["talks", "Talks", "#ff9e7a"],
  ["pick", "Pick up", "#c6a0ff"], ["add", "Add paper", "#ffe347"], ["shelf", "Shelf", "#ff7ab8"], ["persona", "Persona", "#ffa86b"], ["set", "Settings", "#c9cdd6"]];
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
    if (L.job === "ask") return libCloseField();
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
  if (L.f && !L.f.el.hidden) libPenStep(t, dt);
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
  const b = h("button", { type: "button", class: `lblob k-${k}${calm ? " calm named" : " abs"}`, "aria-label": name, style: `--bc:${color}` },
    h("span", { class: "bod" }), h("span", { class: "e" }, h("i"), h("i")), h("span", { class: "pr" }), h("span", { class: "tag" }, name));
  b.dataset.k = k; b.bx = 0; b.by = 0;
  b.addEventListener("click", (e) => { e.stopPropagation(); run(); });
  return b;
}
function libBlobsOut(on) {
  const empty = !L.total;
  L.blobs.forEach((b) => {
    b.hidden = empty && !["add", "set"].includes(b.dataset.k);
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
  L.st.classList.remove("chatting", "shelfing");
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
  if (k === "shelf") return libToShelf();
  if (k === "find") return libOpenField();
  if (k === "persona") return libOpenField(true);
  libBlobsOut(false);
  L.job = k; L.lineGap = 62; L.count.style.opacity = 0;
  L.back.classList.add("on");
  const W = libW(), H = libH();
  L.dot.tx = W / 2; L.dot.ty = k === "add" ? H / 2 - 20 : 150;
  L.back.style.transform = `translate3d(${W / 2 + (k === "add" ? 110 : 78)}px, ${L.dot.ty}px, 0)`;
  ({ next: libNext, talks: libTalks, pick: libPick, add: libAdd })[k]();
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

// ---------- Ask: the blob becomes the field, a typist stamps your letters ----------
function libField() {
  const el = h("div", { class: "lfield abs", hidden: true });
  const goo = h("div", { class: "goo" }, h("div", { class: "body" }), h("div", { class: "bump" }));
  const head = h("div", { class: "head" }, h("span", { class: "ey" }, h("i"), h("i")));
  const line = h("div", { class: "line" });
  const input = h("input", { type: "text", maxlength: 500, "aria-label": "Ask Dot", placeholder: "Ask me anything about your papers" });
  el.append(goo, head, line, input);
  L.st.append(el);
  L.f = { el, goo, bump: goo.lastChild, head, line, input, shown: "", pen: { x: 30, y: 60, vx: 0, vy: 0, tx: 30, ty: 60, snap: true } };
  input.addEventListener("input", () => libStampTo(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && input.value.trim() && !input.disabled) { e.preventDefault(); (L.f.persona ? libSetPersona : libSend)(input.value.trim()); }
  });
  el.addEventListener("pointerdown", (e) => e.stopPropagation());
  el.addEventListener("click", () => { if (input.disabled && !L.f.asking) libNewTurn(); });
  L.histEl.addEventListener("pointerdown", (e) => e.stopPropagation());
  L.st.addEventListener("click", (e) => { if (L.job === "ask" && !e.target.closest(".lfield, .lcard, .lpeek, .lhist, dialog") && !L.f.asking) libCloseField(); });
}
function libPenStep(t, dt) {
  const { pen, head, bump, el } = L.f, k = 0.14, c = 0.34;
  pen.vx += ((pen.tx - pen.x) * k - pen.vx * c) * dt; pen.vy += ((pen.ty - pen.y) * k - pen.vy * c) * dt;
  pen.x += pen.vx * dt; pen.y += pen.vy * dt;
  const think = el.classList.contains("think") && !libRM();
  const squash = 1 + Math.max(-0.12, Math.min(0.12, -pen.vy * 0.03));
  const hy = pen.y - 16 + (think ? Math.sin(t / 140) * 2.5 : 0);
  const tilt = Math.max(-8, Math.min(8, pen.vx * 1.2)) + (think ? Math.sin(t / 200) * 6 : 0);
  head.style.transform = `translate3d(${pen.x - 17}px, ${hy}px, 0) rotate(${tilt}deg) scale(${2 - squash}, ${squash})`;
  bump.style.transform = `translate3d(${pen.x - 25 + 30}px, ${hy - 10 + 30}px, 0) scale(${2 - squash}, ${squash})`;
}
function libPenTo(x, y) { const p = L.f.pen; p.tx = x; p.ty = y; if (p.snap || libRM()) { p.x = x; p.y = y; p.vx = p.vy = 0; p.snap = false; } }
function libAimPen() {
  const { line, el } = L.f, last = line.querySelectorAll("s"), fb = el.getBoundingClientRect();
  if (!last.length) return libPenTo(30, fb.height + 9);
  const r = last[last.length - 1].getBoundingClientRect();
  libPenTo(Math.min(fb.width - 20, r.left - fb.left + r.width / 2 + 3), fb.height + 9);
}
function libFitField() { L.f.el.style.height = `${Math.max(52, L.f.line.offsetHeight)}px`; }
function libStampTo(text) {
  const f = L.f;
  if (!text.startsWith(f.shown)) { f.line.replaceChildren(); f.shown = ""; }
  let w = f.line.lastElementChild;
  for (const ch of text.slice(f.shown.length)) {
    if (ch === " ") { f.line.append(" "); w = null; continue; }
    if (!w || w.nextSibling || w.tagName !== "SPAN") { w = h("span", { class: "w" }); f.line.append(w); }
    const s = h("s", { style: `--r:${(Math.random() * 5 - 2.5).toFixed(1)}deg;--b:${(Math.random() * 2 - 1).toFixed(1)}px` }, ch);
    w.append(s);
    f.head.classList.add("tap"); setTimeout(() => f.head.classList.remove("tap"), 80); f.pen.vy -= 2;
  }
  f.shown = text; f.el.classList.toggle("has-text", !!text);
  libFitField(); libAimPen();
}
// Dot's reply floats up in a wave, word by word, on Dot's yellow.
function libReplyTo(text, buttons = []) {
  const f = L.f;
  f.el.classList.add("dot");
  let i = 0;
  f.line.replaceChildren(...text.split(/(\s+)/).map((w) => (/^\s+$/.test(w) ? w
    : h("span", { class: "w" }, [...w].map((ch) => h("s", { style: `--i:${i++}` }, ch))))),
  ...buttons.map(([label, fn]) => h("button", { type: "button", onclick: (e) => { e.stopPropagation(); fn(); } }, label)));
  f.shown = "\u0000";
  libFitField(); libAimPen(); libLater(450, libAimPen); // again once the field has grown
  return libWait(Math.min(1400, i * 9 + 400));
}
function libDing() {
  const p = L.f.pen, d = h("span", { class: "ding" }, "ding");
  d.style.left = `${p.x + 14}px`; d.style.top = `${p.y - 46}px`; L.f.el.append(d);
  d.animate([{ opacity: 0, transform: "translateY(4px) scale(.7)" }, { opacity: 1, transform: "translateY(-4px) scale(1)", offset: 0.3 },
    { opacity: 0, transform: "translateY(-14px)" }], { duration: 900, easing: "cubic-bezier(.22,1,.36,1)" }).onfinish = () => d.remove();
}
// The typist's eyes go wide, your letters fly into it, it eats them, gulps, and looks around while it thinks.
async function libSwallow() {
  const f = L.f, ss = [...f.line.querySelectorAll("s")], fb = f.el.getBoundingClientRect();
  if (libRM()) { f.line.replaceChildren(); f.shown = ""; return; }
  f.head.classList.add("wide"); await libWait(220);
  f.head.classList.replace("wide", "eat");
  ss.forEach((el, i) => {
    const r = el.getBoundingClientRect();
    const dx = f.pen.x - (r.left - fb.left + r.width / 2), dy = f.pen.y - 6 - (r.top - fb.top + r.height / 2);
    el.animate([{ transform: "none", opacity: 1 }, { transform: `translate(${dx}px, ${dy}px) scale(.15)`, opacity: 0.2 }],
      { duration: 360, delay: (ss.length - 1 - i) * 16, easing: "cubic-bezier(.55,0,.8,.4)", fill: "forwards" });
  });
  await libWait(380 + ss.length * 16);
  f.head.classList.remove("eat"); f.pen.vy += 4; f.line.replaceChildren(); f.shown = "";
}

// Dot stays where it is; the field opens right under it, fetched papers rise into the ring around it.
function libAskLayout() {
  const W = libW(), H = libH();
  L.dot.tx = W / 2; L.dot.ty = H / 2 - 40;
  const fw = Math.min(460, W * 0.84), top = L.dot.ty + 64;
  L.f.el.style.transform = `translate3d(${W / 2}px, ${top}px, 0) translate(-50%, 0)`;
  L.histEl.style.transform = `translate3d(${W / 2 - fw / 2 - 16}px, ${top - 12}px, 0) translate(-100%, 0)`;
  libLayoutFetched();
}
function libOpenField(persona = false) {
  const f = L.f, src = L.blobs.find((b) => b.dataset.k === (persona ? "persona" : "find"));
  f.persona = persona;
  f.input.placeholder = persona ? "Who should I be? Like: a calm tutor who loves puns" : "Ask me anything about your papers";
  L.job = "ask"; L.lineGap = 62;
  libBlobsOut(false); libCardsReset();
  L.st.classList.add("chatting"); L.line.classList.add("off"); L.count.style.opacity = 0;
  f.el.hidden = false; f.el.className = "lfield abs";
  f.el.style.transition = "none";
  f.el.style.transform = `translate3d(${src?.bx ?? L.dot.x}px, ${(src?.by ?? L.dot.y) - 18}px, 0) translate(-50%, 0)`;
  f.input.value = ""; f.input.disabled = false; f.line.replaceChildren(); f.shown = ""; f.pen.snap = true; f.asking = false;
  void f.el.offsetWidth; f.el.style.transition = "";
  f.el.style.transition = "transform .55s cubic-bezier(.22,1,.36,1), width .6s cubic-bezier(.22,1,.36,1), height .4s cubic-bezier(.22,1,.36,1)";
  requestAnimationFrame(() => { f.el.classList.add("open"); libAskLayout(); });
  L.fetched = [];
  L.histEl.classList.toggle("off", !L.hist.length);
  libLater(380, () => f.input.focus()); libLater(620, libAimPen);
  if (persona) {
    L.histEl.classList.add("off");
    const now = L.s.dot_persona?.trim();
    libLater(700, () => {
      if (!now) return;
      f.input.disabled = true;
      libReplyTo(`Right now I am: ${now}. Click to change me.`, [["Back to my usual self", () => libSetPersona("")]]);
    });
  }
}

// Persona: you tell Dot who to be. Saved in Settings; Dot talks that way when you Ask.
async function libSetPersona(text) {
  const f = L.f;
  libDing(); f.input.value = ""; f.input.disabled = true; f.asking = true;
  if (text) await libSwallow();
  try {
    L.s = await api("/settings", { method: "PATCH", body: JSON.stringify({ dot_persona: text.slice(0, 300) }) });
    await libReplyTo(text ? `Got it. From now on I am ${text.replace(/[.!]+$/, "")}. Ask me something and hear it.` : "Back to my usual self.");
    L.dotEl.animate([{ scale: 1 }, { scale: "1.15 .88" }, { scale: ".94 1.06" }, { scale: 1 }], { duration: 500 });
  } catch (e) {
    await libReplyTo(e.body?.detail?.errors?.dot_persona ? "That is too long. Keep it under 300 letters." : "I could not save that. Try again.");
  }
  f.asking = false;
}
function libCloseField(quiet = false) {
  const f = L.f; if (!f || f.el.hidden) return;
  libTuckTurn();
  f.el.classList.remove("open", "dot", "think", "has-text"); f.head.className = "head";
  f.el.style.height = ""; f.line.replaceChildren(); f.shown = "";
  L.histEl.classList.add("off");
  const W = libW(), H = libH();
  f.el.style.transform = `translate3d(${W / 2}px, ${H / 2 - 120}px, 0) translate(-50%, 0)`;
  libLater(420, () => { f.el.hidden = true; });
  L.job = null;
  if (!quiet) libHome();
}
function libNewTurn() {
  const f = L.f;
  libTuckTurn();
  f.el.classList.remove("dot"); f.input.disabled = false; f.input.value = ""; f.line.replaceChildren(); f.shown = "";
  libFitField(); libAimPen(); f.input.focus();
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
  libLayoutFetched();
}
function libLayoutFetched() {
  if (!L.fetched?.length) return;
  const W = libW(), H = libH(), n = L.fetched.length, cx = W / 2, cy = L.dot.ty + 40;
  const rx = Math.max(300, Math.min(W / 2 - 110, 500)), ry = Math.max(200, Math.min(H / 2 - 80, 290));
  // spread over the ring, leaving the middle band (Dot and the field) clear
  L.fetched.forEach((id, i) => {
    const a = n === 1 ? Math.PI / 2 : -Math.PI / 2 + (i + 0.5) * (Math.PI * 2) / n;
    let y = cy + Math.sin(a) * ry; const x = cx + Math.cos(a) * rx;
    if (Math.abs(x - cx) < 330 && Math.abs(y - cy) < 150) y = cy + Math.sign(y - cy || 1) * 175;
    libPlace(id, x, y, i % 2 ? 1.2 : -1.2, { drift: false });
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
  const f = L.f;
  libDing(); f.input.value = ""; f.input.disabled = true; f.asking = true;
  L.turn = { q, a: "" };
  await libSwallow();
  if (!L) return;
  f.el.classList.add("think"); f.head.classList.add("thinking");
  let res;
  try {
    res = await api("/library/ask", { method: "POST", body: JSON.stringify({ question: q, history: L.hist.slice(-4) }) });
  } catch (e) {
    const why = e.status === 404 ? "I need the app restarted before I can answer. Stop it and start it again."
      : typeof e.body?.detail === "string" ? e.body.detail : "Something went wrong on my side. Try again.";
    res = { reply: why, action: { kind: "none", paper_ids: [] }, papers: [] };
  }
  if (!L || L.job !== "ask") return;
  f.el.classList.remove("think"); f.head.classList.remove("thinking");
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
  libRaise(res);
  if (a.kind === "delete") {
    await libReplyTo(reply, [["Yes, delete", () => libRunJob(a, ids, "Deleted.")], ["No", () => libReplyTo("Kept them. Nothing was deleted.").then(() => { f.asking = false; })]]);
    return;
  }
  await libReplyTo(reply);
  if (a.kind === "export") { exportDialog(libP(ids[0]), "markdown"); f.asking = false; return; }
  if (LIB_JOB[a.kind] && ids.length) return libRunJob(a, ids);
  f.asking = false;
}

// Helpers fly to each paper in turn and do the job through the existing endpoints.
async function libRunJob(a, ids, doneText) {
  const f = L.f; f.asking = true;
  if (a.kind === "add_theme") {
    let t = themeList.find((x) => x.name.toLowerCase() === a.theme.toLowerCase());
    try { t ||= await api("/themes", { method: "POST", body: JSON.stringify({ name: a.theme }) }); }
    catch { await libReplyTo(`I could not make the theme "${a.theme}".`); f.asking = false; return; }
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
  f.asking = false;
}

// ---------- shelf mode ----------
function libToShelf() {
  if (!L.total) return libHome();
  libClear(); libPeekClose();
  if (L.f && !L.f.el.hidden) libCloseField(true);
  L.mode = "shelf"; L.job = null; libStore.set("lib-mode", "shelf");
  L.st.classList.remove("chatting"); L.st.classList.add("shelfing"); L.strip.classList.remove("on");
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
    libHome(); await libJob("find"); libLater(500, () => { L.f.input.value = q; libStampTo(q); libLater(300, () => libSend(q)); });
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
