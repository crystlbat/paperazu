"use strict";
// ---------- Graph: your papers linked by meaning ----------
// Plain script loaded before app.js; uses its helpers (h, api, view, greet) at call time.
// Papers are round nodes, ideas you kept are pills. Dashed lines are links the local
// embedding model suggests; solid lines are links you made. Search by meaning, then keep it.

const SVGNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v != null && v !== false) el.setAttribute(k, v);
  }
  el.append(...kids.flat().filter((k) => k != null));
  return el;
}
const POS_KEY = "graph-positions";
const shortTitle = (t, n = 4) => { const w = t.split(/\s+/); return w.length > n ? `${w.slice(0, n).join(" ")}…` : t; };
const pct = (x) => `${Math.round(x * 100)}%`;

let openGraph = null;
window.addEventListener("hashchange", () => { openGraph?.leave(); openGraph = null; });

async function renderGraph() {
  const svg = sv("svg", { class: "g-svg", role: "group", "aria-label": "Graph of your papers and ideas" });
  const world = sv("g");
  const edgeLayer = sv("g", { class: "g-edges" });
  const nodeLayer = sv("g", { class: "g-nodes" });
  world.append(edgeLayer, nodeLayer);
  svg.append(sv("defs", {}, sv("clipPath", { id: "g-round", clipPathUnits: "objectBoundingBox" }, sv("circle", { cx: 0.5, cy: 0.5, r: 0.5 }))), world);

  const note = h("p", { class: "g-note", role: "status" });
  const input = h("input", { type: "search", class: "g-input", placeholder: "Search an idea, for example: re-identifying blurred faces",
    "aria-label": "Search an idea across your papers", maxlength: 300 });
  const findBtn = h("button", { type: "submit", class: "btn" }, "Find");
  const form = h("form", { class: "g-search", onsubmit: (e) => { e.preventDefault(); find(input.value.trim()); } }, input, findBtn);
  // Dot watches the search box while you type in it
  const watchInput = () => { const r = input.getBoundingClientRect(); buddy.lookAt(r.left + Math.min(r.width, 14 + input.value.length * 8), r.top + r.height / 2, 2500); };
  input.addEventListener("focus", watchInput);
  input.addEventListener("input", watchInput);
  const legend = h("div", { class: "g-legend", "aria-hidden": "true" },
    h("span", {}, h("i", { class: "lg-theme" }), "Theme"),
    h("span", {}, h("i", { class: "lg-paper" }), "Paper"),
    h("span", {}, h("i", { class: "lg-idea" }), "Idea you kept"),
    h("span", {}, h("i", { class: "lg-solid" }), "You linked"),
    h("span", {}, h("i", { class: "lg-sim" }), "Similar papers"),
    h("span", {}, h("i", { class: "lg-dash" }), "AI suggests"),
    h("span", { class: "lg-crossing" }, h("i", { class: "lg-cross" }), "Crosses themes"));
  const zoomBtns = h("div", { class: "g-zoom" },
    h("button", { type: "button", class: "btn ghost", "aria-label": "Zoom in", onclick: () => zoomBy(1.25) }, "+"),
    h("button", { type: "button", class: "btn ghost", "aria-label": "Zoom out", onclick: () => zoomBy(0.8) }, "−"),
    h("button", { type: "button", class: "btn ghost", onclick: () => fit() }, "Fit"));
  // AI ideas stay hidden until you pick a paper (then only its own appear) or turn them all on here
  const aiToggle = h("button", { type: "button", class: "btn ghost g-ai", "aria-pressed": "false",
    onclick: () => { st.showAI = !st.showAI; localStorage.setItem("graph-show-ai", st.showAI ? "1" : "0"); build(); heat(0.4); } });
  // themes: each one is a hub its papers gather round. Off = links that cross from one theme to another are hidden.
  const linkToggle = h("button", { type: "button", class: "btn ghost g-ai", "aria-pressed": "true", hidden: true,
    onclick: () => { st.interlink = !st.interlink; localStorage.setItem("graph-interlink", st.interlink ? "1" : "0"); build(); heat(0.5); paintSide(); } });
  zoomBtns.prepend(linkToggle, aiToggle);
  const dock = h("div", { class: "g-dock" }, legend, zoomBtns);
  const stage = h("section", { class: "g-stage", "aria-label": "Graph" }, svg, form, note, dock);
  const side = h("aside", { class: "g-side", "aria-label": "Details" });
  view.append(stage, side);

  // ---------- state ----------
  const st = { nodes: new Map(), edges: [], ghost: null, sel: null, hover: null, data: null, papers: [],
    t: { x: 0, y: 0, k: 1 }, alpha: 0, raf: 0, alive: true,
    showAI: localStorage.getItem("graph-show-ai") === "1", focusPaper: null,
    themes: [], interlink: localStorage.getItem("graph-interlink") !== "0" };
  const saved = JSON.parse(localStorage.getItem(POS_KEY) || "{}");
  const savePos = () => localStorage.setItem(POS_KEY, JSON.stringify(Object.fromEntries(
    [...st.nodes.values()].filter((n) => n.kind !== "ghost").map((n) => [n.id, [Math.round(n.x), Math.round(n.y)]]))));

  // ---------- load ----------
  async function load(select) {
    const [g, lib, th] = await Promise.all([api("/graph"), api("/papers"), api("/themes")]);
    st.data = g; st.papers = lib.papers; st.themes = th.themes;
    if (select) st.sel = select;
    build();
    paintSide(); heat(0.6);
    return g;
  }

  async function boot() {
    try { await load(); } catch { note.textContent = "Could not load the graph."; return; }
    if (!st.papers.length) {
      note.textContent = "";
      side.replaceChildren(h("h2", {}, "Graph"), h("p", { class: "lede" }, "Add papers in the Library first. Each paper becomes a dot here."),
        h("a", { class: "btn", href: "#library" }, "Go to the Library"));
      return;
    }
    const missing = st.papers.filter((p) => !st.data.indexed.includes(p.id)).length;
    if (missing || !st.data.model) {
      note.textContent = missing ? `Reading ${plural(missing, "paper")} with your embedding model` : "Finding your embedding model";
      note.classList.add("busy");
      try {
        const r = await api("/graph/index", { method: "POST" });
        if (!st.alive) return;
        await load();
        note.textContent = r.indexed ? `Read ${plural(r.indexed, "paper")} with ${r.model}.` : "";
      } catch (e) {
        note.textContent = e.body?.detail || "Could not read the papers. Is Unsloth running?";
        note.classList.add("err");
      }
      note.classList.remove("busy");
    }
    await suggestIdeas();
    greet("graph", "Search an idea. I will find where your papers talk about it, and you choose what to link.", { pop: true });
  }

  // The model names each new paper's key ideas once; they arrive as dashed suggestions.
  async function suggestIdeas() {
    if (!st.alive || !st.data.indexed.length) return;
    const slow = setTimeout(() => { note.textContent = "Your model is picking the key ideas in your papers"; note.classList.add("busy"); }, 600);
    try {
      const r = await api("/graph/suggest", { method: "POST" });
      clearTimeout(slow);
      if (!st.alive) return;
      note.classList.remove("busy");
      if (r.ideas) {
        await load();
        note.textContent = `Your model suggests ${plural(r.ideas, "idea")}. Click a dashed one to keep or dismiss it.`;
      } else if (r.papers) note.textContent = "Your model found no new ideas.";
      else note.textContent = "";
    } catch (e) {
      clearTimeout(slow);
      note.classList.remove("busy");
      note.textContent = `No AI suggestions: ${e.body?.detail || "the model did not answer."}`;
      note.classList.add("err");
    }
  }

  // ---------- model -> nodes and edges ----------
  function node(id, kind, label, extra = {}) {
    const old = st.nodes.get(id);
    const [x, y] = old ? [old.x, old.y] : saved[id] ?? [(Math.random() - 0.5) * 300, (Math.random() - 0.5) * 300];
    return { id, kind, label, x, y, vx: 0, vy: 0, fx: null, ...extra };
  }
  // two papers are in the same place if they share a theme; papers with no theme count as one group
  const groups = (pid) => { const t = paperById(pid)?.themes ?? []; return t.length ? t : ["none"]; };
  const shares = (a, b) => { const gb = groups(b); return groups(a).some((t) => gb.includes(t)); };
  const themeOf = (id) => st.themes.find((t) => t.id === id);

  function build() {
    const { papers } = st, g = st.data;
    const next = new Map();
    for (const p of papers) {
      const t = themeOf(p.themes[0]);
      next.set(p.id, node(p.id, "paper", p.title, { done: p.steps_done, total: p.progress.length, r: 30, color: t?.color }));
    }
    const used = st.themes.filter((t) => papers.some((p) => p.themes.includes(t.id)));
    for (const t of used) {
      const n = node(`t:${t.id}`, "theme", t.name, { color: t.color, r: 46, theme: t.id });
      if (!st.nodes.has(n.id) && !saved[n.id]) { // start in the middle of its papers
        const ps = papers.filter((p) => p.themes.includes(t.id)).map((p) => next.get(p.id));
        n.x = ps.reduce((a, q) => a + q.x, 0) / ps.length; n.y = ps.reduce((a, q) => a + q.y, 0) / ps.length;
      }
      next.set(n.id, n);
    }
    linkToggle.hidden = !used.length;
    if (used.length && !st.themed) st.alpha = 1; // themes just appeared: let everything find its cluster
    st.themed = used.length > 0;
    stage.classList.toggle("themed", st.themed && st.interlink);
    linkToggle.textContent = st.interlink ? "Links across themes: on" : "Links across themes: off";
    linkToggle.setAttribute("aria-pressed", String(st.interlink));
    const shown = (c) => c.kind !== "suggested" || st.showAI || st.sel === c.id
      || g.links.some((l) => l.concept_id === c.id && l.paper_id === st.focusPaper);
    for (const c of g.concepts.filter(shown)) {
      const n = node(c.id, c.kind === "suggested" ? "sugg" : "idea", c.label);
      if (n.kind === "sugg" && !st.nodes.has(c.id)) { // bloom out of its paper
        const home = next.get(st.focusPaper) ?? next.get(g.links.find((l) => l.concept_id === c.id)?.paper_id);
        if (home) { n.x = home.x + (Math.random() - 0.5) * 60; n.y = home.y + (Math.random() - 0.5) * 60; }
      }
      next.set(c.id, n);
    }
    const hidden = g.concepts.filter((c) => c.kind === "suggested").length;
    aiToggle.textContent = st.showAI ? "Hide AI ideas" : `Show AI ideas (${hidden})`;
    aiToggle.setAttribute("aria-pressed", String(st.showAI));
    if (st.ghost) next.set("ghost", node("ghost", "ghost", st.ghost.q));
    st.nodes = next;
    // an idea lives in the themes of the paper it matches best; with links across themes off, it only reaches papers there
    const home = {};
    for (const l of g.links) if (!home[l.concept_id] || l.score > home[l.concept_id].score) home[l.concept_id] = l;
    const cross = (a, b) => used.length > 0 && !shares(a, b);
    const ideaLinks = g.links.filter((l) => next.has(l.concept_id) && next.has(l.paper_id))
      .filter((l) => st.interlink || !cross(home[l.concept_id].paper_id, l.paper_id));
    // each paper keeps only its two closest papers, so the strongest links read instead of a web
    const top = new Set();
    for (const p of papers) g.suggested.filter((e) => e.a === p.id || e.b === p.id).sort((x, y) => y.score - x.score).slice(0, 2).forEach((e) => top.add(e));
    const paperLinks = g.suggested.filter((e) => top.has(e) && next.has(e.a) && next.has(e.b)).filter((e) => st.interlink || !cross(e.a, e.b));
    st.edges = [
      ...used.flatMap((t) => papers.filter((p) => p.themes.includes(t.id)).map((p) => ({ a: `t:${t.id}`, b: p.id, kind: "theme", score: 1, color: t.color }))),
      ...paperLinks.map((e) => ({ a: e.a, b: e.b, kind: `sim${cross(e.a, e.b) ? " cross" : ""}`, score: e.score })),
      ...ideaLinks.map((l) => ({ a: l.concept_id, b: l.paper_id, kind: `${next.get(l.concept_id).kind === "sugg" ? "suggest" : "link"}${cross(home[l.concept_id].paper_id, l.paper_id) ? " cross" : ""}`, score: l.score })),
      ...(st.ghost ? st.ghost.results.filter((r) => r.on && next.has(r.paper_id)).map((r) => ({ a: "ghost", b: r.paper_id, kind: "ghost", score: r.score })) : []),
    ];
    draw();
  }

  // ---------- drawing ----------
  function draw() {
    edgeLayer.replaceChildren(...st.edges.map((e) => {
      e.el = sv("path", { class: `g-edge ${e.kind}`, fill: "none", "stroke-width": 1.35,
        style: e.kind === "theme" ? `--tc:var(--theme-${e.color})` : null });
      return e.el;
    }));
    nodeLayer.replaceChildren(...[...st.nodes.values()].map((n) => {
      const label = n.kind === "paper" ? (n.label.length > 24 ? `${n.label.slice(0, 22).replace(/[\s_\-/]+\S*$/, "")}…` : n.label) : n.label;
      const g = sv("g", { class: `g-node ${n.kind}`, tabindex: 0, role: "button",
        style: n.color != null ? `--tc:var(--theme-${n.color})` : null,
        "aria-label": n.kind === "theme" ? `Theme: ${n.label}` : n.kind === "paper" ? `Paper: ${n.label}. ${n.done} of ${n.total} steps done.` : n.kind === "idea" ? `Idea: ${n.label}`
          : n.kind === "sugg" ? `AI suggested idea: ${n.label}` : `Search preview: ${n.label}` });
      if (n.kind === "theme") {
        // a soft territory with the theme's name; its papers are tied to it
        g.append(sv("circle", { class: "terr", r: 74 }), sv("circle", { class: "halo", r: 18 }), sv("circle", { class: "body", r: 10 }),
          sv("text", { class: "tlabel", "text-anchor": "middle", y: -22 }, label.length > 28 ? `${label.slice(0, 27)}…` : label));
      } else if (n.kind === "paper") {
        // page 1 of the paper, in a circle, with a ring that fills as you finish steps
        const r = n.r, c = 2 * Math.PI * (r + 5);
        g.append(sv("circle", { class: "halo", r: r + 11 }), sv("circle", { class: "body", r }),
          sv("image", { class: "cover", href: `/papers/${n.id}/cover`, x: -r, y: -r, width: 2 * r, height: 2 * r,
            preserveAspectRatio: "xMidYMin slice", "clip-path": "url(#g-round)" }),
          sv("circle", { class: "rim", r }),
          sv("circle", { class: `track${n.color != null ? " themed" : ""}`, r: r + 5 }),
          sv("circle", { class: "prog", r: r + 5, "stroke-dasharray": `${(c * n.done) / Math.max(1, n.total)} ${c}`, transform: "rotate(-90)" }),
          sv("text", { class: "label", "text-anchor": "middle", y: r + 26 }, label),
          sv("text", { class: "sub", "text-anchor": "middle", y: r + 42 }, n.done ? `${n.done} of ${n.total} steps` : "Not started"));
      } else if (n.kind === "sugg") {
        // a small dashed dot; its name shows on hover, when selected, or when you zoom in
        n.r = 16;
        g.append(sv("circle", { class: "halo", r: 15 }), sv("circle", { class: "body", r: 7 }),
          sv("text", { class: "label", "text-anchor": "middle", y: 24 }, label.length > 34 ? `${label.slice(0, 33)}…` : label));
      } else {
        const shown = label.length > 22 ? `${label.slice(0, 21)}…` : label;
        const w = Math.min(168, 36 + shown.length * 8);
        n.r = w / 2;
        g.append(sv("rect", { class: "halo", x: -w / 2 - 6, y: -24, width: w + 12, height: 48, rx: 24 }),
          sv("rect", { class: "body", x: -w / 2, y: -18, width: w, height: 36, rx: 18 }),
          sv("text", { class: "label", "text-anchor": "middle", dy: "0.35em" }, shown));
      }
      g.addEventListener("pointerdown", (e) => grab(e, n));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(n.id); } });
      g.addEventListener("pointerenter", () => { st.hover = n.id; paintFocus(); });
      g.addEventListener("pointerleave", () => { st.hover = null; paintFocus(); });
      g.addEventListener("dblclick", () => { if (n.kind === "paper") location.hash = `#read/${n.id}`; });
      n.el = g;
      return g;
    }));
    paintFocus(); place();
  }
  // How much room a node needs so its title is not sitting on another title.
  function footprint(n) {
    if (n.kind === "paper") {
      const lw = Math.min(200, Math.max(72, n.label.length * 8));
      return { hw: Math.max(n.r + 10, lw / 2 + 8), hhTop: n.r + 10, hhBot: n.r + 56 };
    }
    if (n.kind === "theme") {
      const lw = Math.min(260, Math.max(48, n.label.length * 10));
      return { hw: lw / 2 + 10, hhTop: 48, hhBot: 18 };
    }
    if (n.kind === "sugg") return { hw: 18, hhTop: 12, hhBot: 14 };
    const w = Math.min(220, 26 + n.label.length * 7.4);
    return { hw: w / 2 + 10, hhTop: 22, hhBot: 22 };
  }
  function separate(p, q, a) {
    const A = footprint(p), B = footprint(q), gap = 28;
    const dx = q.x - p.x, dy = q.y - p.y;
    const ox = A.hw + B.hw + gap - Math.abs(dx);
    const oy = (dy >= 0 ? A.hhBot + B.hhTop : A.hhTop + B.hhBot) + gap - Math.abs(dy);
    if (ox <= 0 || oy <= 0) return;
    const push = Math.min(ox, oy) * 0.45 * a;
    if (ox < oy) {
      const s = Math.sign(dx) || 1;
      p.vx -= s * push; q.vx += s * push;
    } else {
      const s = Math.sign(dy) || 1;
      p.vy -= s * push; q.vy += s * push;
    }
  }
  // Boxes a line must not cross: the round node, and the title plate under or over it.
  function obstacles() {
    const out = [];
    for (const n of st.nodes.values()) {
      if (!n.el) continue;
      const add = (el, pad) => {
        if (!el) return;
        const b = el.getBBox();
        if (b.width < 2 || b.height < 2) return;
        out.push({ id: n.id, kind: "title", x: n.x + b.x - pad, y: n.y + b.y - pad, w: b.width + pad * 2, h: b.height + pad * 2 });
      };
      if (n.kind === "paper") {
        add(n.el.querySelector(".label"), 4);
        add(n.el.querySelector(".sub"), 3);
        const rad = n.r + 5;
        out.push({ id: n.id, kind: "body", x: n.x - rad, y: n.y - rad, w: rad * 2, h: rad * 2 });
      } else if (n.kind === "theme") {
        add(n.el.querySelector(".tlabel"), 4);
        out.push({ id: n.id, kind: "body", x: n.x - 14, y: n.y - 14, w: 28, h: 28 });
      } else if (n.kind === "sugg") {
        const show = svg.classList.contains("zoomed") || n.el.classList.contains("near") || n.el.matches(":hover");
        if (show) add(n.el.querySelector(".label"), 3);
        out.push({ id: n.id, kind: "body", x: n.x - 10, y: n.y - 10, w: 20, h: 20 });
      } else out.push({ id: n.id, kind: "body", x: n.x - n.r - 4, y: n.y - 18, w: n.r * 2 + 8, h: 36 });
    }
    return out;
  }
  function segsCross(ax, ay, bx, by, cx, cy, dx, dy) {
    const side = (px, py, qx, qy, rx, ry) => (qy - py) * (rx - qx) - (qx - px) * (ry - qy);
    const d1 = side(cx, cy, dx, dy, ax, ay), d2 = side(cx, cy, dx, dy, bx, by);
    const d3 = side(ax, ay, bx, by, cx, cy), d4 = side(ax, ay, bx, by, dx, dy);
    return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
  }
  function hitsBox(x1, y1, x2, y2, b) {
    const xR = b.x + b.w, yB = b.y + b.h;
    const inn = (x, y) => x >= b.x && x <= xR && y >= b.y && y <= yB;
    if (inn(x1, y1) || inn(x2, y2)) return true;
    return segsCross(x1, y1, x2, y2, b.x, b.y, xR, b.y) || segsCross(x1, y1, x2, y2, xR, b.y, xR, yB)
      || segsCross(x1, y1, x2, y2, xR, yB, b.x, yB) || segsCross(x1, y1, x2, y2, b.x, yB, b.x, b.y);
  }
  // The part of the segment that sits inside the box, as 0 to 1 along the line. Null when it misses.
  function insideBox(x1, y1, x2, y2, box) {
    const dx = x2 - x1, dy = y2 - y1;
    const p = [-dx, dx, -dy, dy];
    const q = [x1 - box.x, box.x + box.w - x1, y1 - box.y, box.y + box.h - y1];
    let t0 = 0, t1 = 1;
    for (let i = 0; i < 4; i++) {
      if (p[i] === 0) { if (q[i] < 0) return null; continue; }
      const t = q[i] / p[i];
      if (p[i] < 0) { if (t > t1) return null; if (t > t0) t0 = t; }
      else { if (t < t0) return null; if (t < t1) t1 = t; }
    }
    return t0 < t1 ? [t0, t1] : null;
  }
  // Leave the node on the rim of its circle or past its title. A straight stub, never a sweep.
  function anchor(n, tx, ty, boxes) {
    const dx = tx - n.x, dy = ty - n.y, len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    let dist = (n.kind === "paper" ? n.r : n.kind === "theme" ? 14 : n.kind === "sugg" ? 10 : n.r) + 8;
    const mine = boxes.filter((b) => b.id === n.id);
    for (let k = 0; k < 6; k++) {
      const x = n.x + ux * dist, y = n.y + uy * dist;
      const hit = mine.find((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
      if (!hit) break;
      let far = dist;
      if (ux > 0.02) far = Math.max(far, (hit.x + hit.w - n.x) / ux);
      else if (ux < -0.02) far = Math.max(far, (hit.x - n.x) / ux);
      if (uy > 0.02) far = Math.max(far, (hit.y + hit.h - n.y) / uy);
      else if (uy < -0.02) far = Math.max(far, (hit.y - n.y) / uy);
      dist = far + 8;
    }
    return [n.x + ux * dist, n.y + uy * dist];
  }
  function route(a, b, boxes) {
    const [x1, y1] = anchor(a, b.x, b.y, boxes);
    const [x2, y2] = anchor(b, a.x, a.y, boxes);
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
    let spans = [[0, 1]];
    for (const box of boxes) {
      if ((box.id === a.id || box.id === b.id) && box.kind !== "title") continue;
      const hit = insideBox(x1, y1, x2, y2, box);
      if (!hit) continue;
      const [h0, h1] = hit;
      const next = [];
      for (const [s, e] of spans) {
        const lo = Math.max(s, h0), hi = Math.min(e, h1);
        if (hi <= lo + 0.012) { next.push([s, e]); continue; }
        if (lo > s + 0.02) next.push([s, lo]);
        if (e > hi + 0.02) next.push([hi, e]);
      }
      spans = next;
    }
    return spans.filter(([s, e]) => (e - s) * len > 16).map(([s, e]) => {
      const sx = x1 + dx * s, sy = y1 + dy * s, ex = x1 + dx * e, ey = y1 + dy * e;
      return `M ${sx.toFixed(1)} ${sy.toFixed(1)} L ${ex.toFixed(1)} ${ey.toFixed(1)}`;
    }).join(" ");
  }
  function place() {
    const boxes = obstacles();
    for (const e of st.edges) {
      const a = st.nodes.get(e.a), b = st.nodes.get(e.b);
      if (a && b) e.el.setAttribute("d", route(a, b, boxes));
    }
    for (const n of st.nodes.values()) n.el.setAttribute("transform", `translate(${n.x.toFixed(1)} ${n.y.toFixed(1)})`);
    world.setAttribute("transform", `translate(${st.t.x} ${st.t.y}) scale(${st.t.k})`);
    svg.classList.toggle("zoomed", st.t.k >= 1.6);
    crowd();
  }
  // An AI idea's name only shows when it has room: a name that would sit on a paper's title or on another name stays
  // hidden until you hover it. The hovered or selected one always wins its spot.
  function crowd() {
    const taken = [], box = (x, y, w, h) => ({ x: x - w / 2, y, w, h });
    const hits = (b) => taken.some((t) => b.x < t.x + t.w && t.x < b.x + b.w && b.y < t.y + t.h && t.y < b.y + b.h);
    for (const n of st.nodes.values()) {
      if (n.kind === "paper") taken.push(box(n.x, n.y + n.r + 12, Math.min(200, n.label.length * 8), 36), box(n.x, n.y - n.r, 2 * n.r, 2 * n.r));
      else if (n.kind === "theme") taken.push(box(n.x, n.y - 38, Math.min(260, n.label.length * 10), 22));
      else if (n.kind !== "sugg") taken.push(box(n.x, n.y - 18, 2 * n.r, 36));
    }
    const first = (n) => (n.id === st.hover || n.id === st.sel ? 0 : 1);
    const sugg = [...st.nodes.values()].filter((n) => n.kind === "sugg").sort((a, b) => first(a) - first(b));
    for (const n of sugg) {
      const b = box(n.x, n.y + 12, Math.min(34, n.label.length) * 7.2, 18);
      const hide = first(n) === 1 && hits(b);
      n.el.classList.toggle("crowd", hide);
      if (!hide) taken.push(b);
    }
  }
  // Hovering or selecting a node lights it and its neighbours; the rest steps back.
  function paintFocus() {
    if (st.sel && !st.nodes.has(st.sel)) st.sel = null; // the node went away (a removed idea, a closed search)
    if (st.hover && !st.nodes.has(st.hover)) st.hover = null;
    const f = st.hover ?? st.sel;
    const near = new Set(f ? [f] : []);
    if (f) for (const e of st.edges) { if (e.a === f) near.add(e.b); if (e.b === f) near.add(e.a); }
    svg.classList.toggle("focusing", !!f);
    for (const n of st.nodes.values()) { n.el.classList.toggle("near", near.has(n.id)); n.el.classList.toggle("sel", n.id === st.sel); }
    for (const e of st.edges) e.el.classList.toggle("near", !!f && (e.a === f || e.b === f));
    crowd();
  }

  // ---------- forces ----------
  function tick() {
    const ns = [...st.nodes.values()], a = st.alpha;
    for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) {
      const p = ns[i], q = ns[j];
      let dx = q.x - p.x, dy = q.y - p.y, d2 = dx * dx + dy * dy || 1;
      separate(p, q, a); // titles get their own patch of desk
      const min = (p.r ?? 20) + (q.r ?? 20) + (p.kind === "paper" && q.kind === "paper" ? 200 : 30); // room for the titles
      const big = (k) => k === "paper" || k === "theme";
      const both = big(p.kind) && big(q.kind);
      // papers keep well apart; with themes, papers of one theme sit closer and theme territories push hard
      const push = p.kind === "theme" && q.kind === "theme" ? 90000
        : !both ? 2600 : !st.themed || p.kind !== "paper" || q.kind !== "paper" ? 45000 : shares(p.id, q.id) ? 6000 : 26000;
      const f = (push / d2 + (d2 < min * min ? 0.4 : 0)) * a;
      const d = Math.sqrt(d2); dx /= d; dy /= d;
      p.vx -= dx * f; p.vy -= dy * f; q.vx += dx * f; q.vy += dy * f;
    }
    for (const e of st.edges) {
      const p = st.nodes.get(e.a), q = st.nodes.get(e.b);
      const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 1;
      const pp = st.nodes.get(e.a).kind === "paper" && st.nodes.get(e.b).kind === "paper";
      const len = e.kind === "theme" ? 150 : e.kind.includes("cross") ? 220 : pp ? 200 : e.kind.startsWith("suggest") ? 140 : e.kind === "ghost" ? 160 : 140;
      const f = ((d - len) / d) * (e.kind === "theme" ? 0.09 : e.kind.includes("cross") ? 0.02 : 0.05) * a;
      p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
    }
    for (const n of ns) {
      n.vx -= n.x * 0.004 * a; n.vy -= n.y * 0.004 * a; // gentle pull to the middle
      if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = n.vy = 0; continue; }
      n.vx *= 0.82; n.vy *= 0.82; n.x += n.vx; n.y += n.vy;
    }
    st.alpha *= 0.985;
  }
  function heat(a) {
    st.alpha = Math.max(st.alpha, a);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      while (st.alpha > 0.02) tick();
      place(); savePos(); if (!st.fitted) { st.fitted = true; fit(); } return;
    }
    if (!st.raf) st.raf = requestAnimationFrame(loop);
  }
  function loop() {
    st.raf = 0;
    if (!st.alive) return;
    tick(); place();
    if (st.alpha > 0.02) st.raf = requestAnimationFrame(loop);
    else { savePos(); if (!st.fitted) { st.fitted = true; fit(); } }
  }

  // ---------- pointer: drag nodes, pan, zoom ----------
  const toWorld = (cx, cy) => { const r = svg.getBoundingClientRect(); return [(cx - r.left - st.t.x) / st.t.k, (cy - r.top - st.t.y) / st.t.k]; };
  function grab(e, n) {
    e.stopPropagation(); e.preventDefault();
    const start = [e.clientX, e.clientY];
    let moved = false;
    const move = (ev) => {
      if (!moved && Math.hypot(ev.clientX - start[0], ev.clientY - start[1]) < 4) return;
      moved = true;
      [n.fx, n.fy] = toWorld(ev.clientX, ev.clientY);
      heat(0.3);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      n.fx = n.fy = null;
      if (!moved) select(n.id); else savePos();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  }
  svg.addEventListener("pointerdown", (e) => {
    const start = [e.clientX - st.t.x, e.clientY - st.t.y], s0 = [e.clientX, e.clientY];
    svg.classList.add("panning");
    const move = (ev) => { st.t.x = ev.clientX - start[0]; st.t.y = ev.clientY - start[1]; place(); };
    const up = (ev) => {
      svg.classList.remove("panning");
      window.removeEventListener("pointermove", move);
      if (Math.hypot(ev.clientX - s0[0], ev.clientY - s0[1]) < 4 && st.sel) { st.sel = null; st.focusPaper = null; build(); heat(0.2); paintSide(); }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  });
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  function zoomBy(f, cx, cy) {
    const r = svg.getBoundingClientRect();
    cx ??= r.width / 2; cy ??= r.height / 2;
    const k = Math.min(3, Math.max(0.3, st.t.k * f));
    st.t.x = cx - ((cx - st.t.x) * k) / st.t.k; st.t.y = cy - ((cy - st.t.y) * k) / st.t.k; st.t.k = k;
    place();
  }
  function fit() {
    const ns = [...st.nodes.values()], r = svg.getBoundingClientRect();
    if (!ns.length || !r.width) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of ns) {
      const f = footprint(n);
      minX = Math.min(minX, n.x - f.hw); maxX = Math.max(maxX, n.x + f.hw);
      minY = Math.min(minY, n.y - f.hhTop); maxY = Math.max(maxY, n.y + f.hhBot);
    }
    // Match the margins in graph.css: search and Dot's corner on top, the dock along the bottom.
    const top = 120, bottom = 100, side = 36;
    const w = Math.max(40, maxX - minX), hgt = Math.max(40, maxY - minY);
    const roomW = Math.max(80, r.width - side * 2), roomH = Math.max(80, r.height - top - bottom);
    st.t.k = Math.min(1.15, Math.max(0.7, Math.min(roomW / w, roomH / hgt)));
    st.t.x = side + roomW / 2 - ((minX + maxX) / 2) * st.t.k;
    st.t.y = top + roomH / 2 - ((minY + maxY) / 2) * st.t.k;
    place();
  }
  const ro = new ResizeObserver(() => fit());
  ro.observe(svg);

  // ---------- side panel ----------
  function select(id) {
    st.sel = id;
    if (st.nodes.get(id)?.kind === "paper" || paperById(id)) st.focusPaper = id;
    else if (st.nodes.get(id)?.kind !== "sugg") st.focusPaper = null; // a suggestion keeps its paper's ideas in view
    build(); heat(0.25); paintSide();
  }
  const paperById = (id) => st.papers.find((p) => p.id === id);
  const ideaLinks = (cid) => st.data.links.filter((l) => l.concept_id === cid);

  function paintSide() {
    if (st.ghost) return paintSearch();
    const n = st.sel && st.nodes.get(st.sel);
    if (n?.kind === "paper") return paintPaper(n);
    if (n?.kind === "theme") return paintTheme(n);
    if (n?.kind === "idea") return paintIdea(n);
    if (n?.kind === "sugg") return paintSuggestion(n);
    const g = st.data;
    side.replaceChildren(
      h("h2", {}, "Graph"),
      h("p", { class: "lede" }, "Your papers, linked by what they mean. Search an idea and the model on your Mac finds the passages that talk about it. Keep the ones you agree with."),
      h("dl", { class: "g-stats" },
        h("div", {}, h("dt", {}, "Papers"), h("dd", { class: "num" }, String(st.papers.length))),
        h("div", {}, h("dt", {}, "Ideas you kept"), h("dd", { class: "num" }, String(g.concepts.filter((c) => c.kind !== "suggested").length))),
        h("div", {}, h("dt", {}, "AI suggestions"), h("dd", { class: "num" }, String(g.concepts.filter((c) => c.kind === "suggested").length + g.suggested.length)))),
      section("Your papers", st.papers.map((p) => h("button", { type: "button", class: "g-row g-paper", onclick: () => select(p.id) },
        h("img", { src: `/papers/${p.id}/cover`, alt: "", loading: "lazy" }),
        h("span", { class: "g-pick-body" }, h("span", { class: "g-row-title" }, p.title),
          h("span", { class: "g-row-sub" }, p.steps_done ? `${p.steps_done} of ${p.progress.length} steps done` : "Not started")))), ""),
      h("p", { class: "help" }, "Drag papers to arrange them. Click one for details. Double-click a paper to open it."),
      g.model ? h("p", { class: "help" }, `Embedding model: ${g.model}`) : null);
  }

  function paintTheme(n) {
    const members = st.papers.filter((p) => p.themes.includes(n.theme));
    const ids = new Set(members.map((p) => p.id));
    const out = st.edges.filter((e) => e.kind.includes("cross") && (ids.has(e.a) || ids.has(e.b))).length;
    side.replaceChildren(
      h("p", { class: "g-kind" }, "Theme"),
      h("h3", { class: "g-title" }, h("i", { class: "tdot", style: `--tc:var(--theme-${n.color})` }), " ", n.label),
      h("p", { class: "help" }, st.interlink
        ? `${plural(members.length, "paper")}. ${out ? `${plural(out, "link")} reach other themes.` : "No links to other themes yet."}`
        : `${plural(members.length, "paper")}. Links across themes are off, so this theme is shown on its own.`),
      h("div", { class: "g-actions" },
        h("button", { type: "button", class: "btn ghost", onclick: () => { lib.theme = n.theme; location.hash = "#library"; } }, "Show in the Library")),
      section("Papers in this theme", members.map((p) => h("button", { type: "button", class: "g-row", onclick: () => select(p.id) },
        h("span", { class: "g-row-title" }, p.title), h("span", { class: "g-row-sub" }, `${p.steps_done} of ${p.progress.length} steps done`))), ""));
  }

  function paintPaper(n) {
    const p = paperById(n.id);
    const ideas = st.data.links.filter((l) => l.paper_id === n.id);
    const similar = st.data.suggested.filter((e) => e.a === n.id || e.b === n.id)
      .map((e) => ({ id: e.a === n.id ? e.b : e.a, score: e.score })).sort((a, b) => b.score - a.score);
    side.replaceChildren(
      h("p", { class: "g-kind" }, "Paper"),
      h("h3", { class: "g-title" }, p.title),
      p.authors ? h("p", { class: "help" }, p.authors) : null,
      h("p", { class: "g-prog" }, h("span", { class: "num" }, `${p.steps_done} of ${p.progress.length}`), " steps done"),
      h("div", { class: "g-actions" },
        h("a", { class: "btn", href: `#read/${p.id}` }, "Open in the Reader"),
        h("button", { type: "button", class: "btn ghost", onclick: () => openTree(p) }, "Section tree")),
      section("Ideas linked here", ideas.map((l) => h("button", { type: "button", class: "g-row", onclick: () => select(l.concept_id) },
        h("span", { class: "g-row-title" }, st.nodes.get(l.concept_id)?.label ?? "",
          st.nodes.get(l.concept_id)?.kind === "sugg" ? h("span", { class: "g-tag" }, "AI suggests") : null),
        h("span", { class: "g-row-sub" }, `Page ${l.page}. ${l.snippet}`))), "No ideas linked yet. Search one above."),
      section("Close in meaning (AI)", similar.map((s) => h("button", { type: "button", class: "g-row", onclick: () => select(s.id) },
        h("span", { class: "g-row-title" }, paperById(s.id)?.title ?? ""),
        h("span", { class: "g-row-sub" }, `${pct(s.score)} alike`))), st.papers.length < 2 ? "Add more papers to see which ones are alike." : "No close papers yet."));
  }

  function paintIdea(n) {
    const links = ideaLinks(n.id);
    let armed = false;
    const del = h("button", { type: "button", class: "btn ghost danger-text", onclick: async () => {
      if (!armed) { armed = true; del.textContent = "Click again to remove"; return; }
      await api(`/graph/concepts/${n.id}`, { method: "DELETE" }).catch(() => {});
      st.sel = null; await load();
    } }, "Remove this idea");
    side.replaceChildren(
      h("p", { class: "g-kind" }, "Idea you kept"),
      h("h3", { class: "g-title serif" }, n.label),
      section(`In ${plural(links.length, "paper")}`, links.map((l) => h("a", { class: "g-row", href: `#read/${l.paper_id}` },
        h("span", { class: "g-row-title" }, paperById(l.paper_id)?.title ?? ""),
        h("span", { class: "g-row-sub" }, `Page ${l.page}. ${l.snippet}`),
        meter(l.score)))),
      del);
  }

  function paintSuggestion(n) {
    const links = ideaLinks(n.id);
    const act = (path, method) => async () => {
      await api(path, { method }).catch(() => {});
      st.sel = method === "POST" ? n.id : null;
      await load();
    };
    side.replaceChildren(
      h("p", { class: "g-kind" }, "AI suggests this idea"),
      h("h3", { class: "g-title serif" }, n.label),
      h("p", { class: "help" }, "Your model picked this as a key idea, then found where your papers talk about it. Keep it if it is right."),
      section(`In ${plural(links.length, "paper")}`, links.map((l) => h("a", { class: "g-row", href: `#read/${l.paper_id}` },
        h("span", { class: "g-row-title" }, paperById(l.paper_id)?.title ?? ""),
        h("span", { class: "g-row-sub" }, `Page ${l.page}. ${l.snippet}`),
        meter(l.score)))),
      h("div", { class: "g-actions" },
        h("button", { type: "button", class: "btn", onclick: act(`/graph/concepts/${n.id}/keep`, "POST") }, "Keep this idea"),
        h("button", { type: "button", class: "btn ghost", onclick: act(`/graph/concepts/${n.id}`, "DELETE") }, "Dismiss")));
  }

  function section(title, rows, empty) {
    return h("section", { class: "g-sec" }, h("h4", {}, title),
      rows.length ? h("div", { class: "g-rows" }, rows) : h("p", { class: "help" }, empty ?? ""));
  }
  // five dots: how closely a passage matches
  function meter(score) {
    const on = Math.max(1, Math.min(5, Math.round((score - 0.35) / 0.08)));
    return h("span", { class: "g-meter", title: `${pct(score)} match`, "aria-label": `${pct(score)} match` },
      [1, 2, 3, 4, 5].map((i) => h("i", { class: i <= on ? "on" : "" })));
  }

  // ---------- search by meaning ----------
  async function find(q) {
    if (!q) return;
    findBtn.disabled = true;
    const live = buddy.trip();
    const fr = form.getBoundingClientRect();
    buddy.goTo(fr.right + 56, fr.top + fr.height / 2).then(() => live() && watchInput()); // Dot comes to read your question
    side.replaceChildren(h("p", { class: "g-kind" }, "Searching"), h("h3", { class: "g-title serif" }, q),
      h("p", { class: "help g-wait" }, "Comparing your search with every passage in your papers."));
    try {
      const r = await api("/graph/search", { method: "POST", body: JSON.stringify({ q }) });
      st.ghost = { q, results: r.results.map((x) => ({ ...x, on: x.pick })) };
      st.sel = "ghost";
      build(); heat(0.7); paintSide();
      visit(st.ghost.results, live);
    } catch (e) {
      if (live()) buddy.goHome();
      side.replaceChildren(h("p", { class: "status err" }, e.body?.detail?.errors?.q || e.body?.detail || "Search failed."));
    } finally { findBtn.disabled = false; }
  }

  // Dot walks to each paper the search found, nods at good matches and shakes at weak ones, then goes home.
  async function visit(results, live) {
    const seen = new Set();
    const stops = [...results].sort((a, b) => b.score - a.score).filter((r) => !seen.has(r.paper_id) && seen.add(r.paper_id)).slice(0, 6);
    await new Promise((r) => setTimeout(r, 500)); // let the search dot settle in
    for (const r of stops) {
      const n = st.nodes.get(r.paper_id);
      if (!live() || !st.alive || !n) break;
      const box = svg.getBoundingClientRect();
      const x = box.left + st.t.x + n.x * st.t.k, y = box.top + st.t.y + n.y * st.t.k;
      if (x < box.left || x > box.right || y < box.top || y > box.bottom) continue; // off screen
      await buddy.goTo(x + (n.r ?? 30) * st.t.k + 48, y - 18);
      if (!live()) break;
      buddy.lookAt(x, y, 1200);
      await buddy.react(r.on ? "yes" : "no");
    }
    if (live()) {
      await buddy.goHome();
      const good = results.filter((r) => r.on).length;
      buddy.say(good ? `I ticked ${good} good ${good === 1 ? "match" : "matches"}. Untick any you disagree with, then link.` : "Nothing matched well. Try other words.",
        { mood: good ? "happy" : "worried" });
    }
  }

  function paintSearch() {
    const gh = st.ghost;
    const chosen = gh.results.filter((r) => r.on);
    const keep = h("button", { type: "button", class: "btn", disabled: !chosen.length, onclick: async () => {
      keep.disabled = true;
      const r = await api("/graph/concepts", { method: "POST", body: JSON.stringify({ label: gh.q.slice(0, 120),
        links: chosen.map(({ paper_id, page, snippet, score }) => ({ paper_id, page, snippet, score })) }) }).catch(() => null);
      if (!r) { keep.disabled = false; return; }
      st.ghost = null;
      await load(r.id);
      buddy.say(`Linked "${gh.q}" to ${plural(chosen.length, "paper")}.`, { mood: "happy" });
    } }, chosen.length ? `Link to ${plural(chosen.length, "paper")}` : "Pick a paper to link");
    side.replaceChildren(
      h("p", { class: "g-kind" }, "Search by meaning"),
      h("h3", { class: "g-title serif" }, gh.q),
      gh.results.length
        ? h("p", { class: "help" }, "Strong matches are ticked for you. Untick any that miss the point, then link.")
        : h("p", { class: "help" }, "No passages yet. Add papers, or try other words."),
      h("div", { class: "g-rows" }, gh.results.map((r) => h("label", { class: `g-row g-pick${r.on ? " on" : ""}` },
        h("input", { type: "checkbox", checked: r.on, onchange: (e) => { r.on = e.target.checked; build(); heat(0.3); paintSide(); } }),
        h("span", { class: "g-pick-body" },
          h("span", { class: "g-row-title" }, r.title),
          h("span", { class: "g-row-sub" }, `Page ${r.page}. ${r.snippet}`)),
        meter(r.score)))),
      h("div", { class: "g-actions" }, keep,
        h("button", { type: "button", class: "btn ghost", onclick: () => { st.ghost = null; st.sel = null; build(); heat(0.3); paintSide(); } }, "Cancel")));
  }

  // ---------- section tree: L1 paper, L2 sections, L3 subsections, L4 deeper parts and figures ----------
  let tree = null;
  async function openTree(p) {
    tree?.remove();
    const data = await api(`/papers/${p.id}/outline`).catch(() => null);
    if (!data || !st.alive) return;
    const CW = 240, CH = 132, RING = 270, PAD = 24; // card size, gap between rings, room round the edge
    const kind = data.source === "slides" ? ["Deck", "Sections", "Topics", "Slides"] : ["Paper", "Sections", "Subsections", "Parts and figures"];
    const back = h("button", { type: "button", class: "btn ghost", onclick: () => closeTree() }, "Back to the graph");
    const holder = h("div", { class: "t-scroll" });
    const panel = h("aside", { class: "t-panel", "aria-live": "polite" });
    tree = h("section", { class: "g-tree", "aria-label": `Section tree of ${p.title}` },
      h("div", { class: "t-head" }, back,
        h("span", { class: "t-name" }, p.title),
        h("span", { class: "t-levels", "aria-hidden": "true" },
          kind.map((t, i) => h("span", { class: `t-lv l${i + 1}` }, h("i"), `L${i + 1} ${t}`)))),
      data.source === "guessed" ? h("p", { class: "help t-note" }, "This PDF has no built-in outline, so the sections are guessed from its headings.") : null,
      h("div", { class: "t-body" }, holder, panel));
    stage.classList.add("tree-open"); side.hidden = true;
    stage.append(tree);
    back.focus();
    let seq = 0, count = 0;
    (function tag(n) { n.key = seq++; count++; n.children.forEach(tag); })(data.tree);
    // The tree blooms from the middle: only the sections show at first, and opening a card unfolds its parts.
    const closed = new Set();
    (function fold(n) { if (n.level >= 2 && n.children.length) closed.add(n.key); n.children.forEach(fold); })(data.tree);
    let sel = data.tree.key;
    const byKey = new Map();
    (function index(n) { byKey.set(n.key, n); n.children.forEach(index); })(data.tree);
    const blurb = (n) => n.lead || (n.children.length ? `Inside: ${n.children.map((c) => c.title).join(", ")}` : "");
    const shown = new Set(); // cards already on screen; only new ones bloom
    let from = new Map(); // where each new card grows from
    let prev = new Map(); // where cards already on screen were, so they glide to their new place

    // Radial layout. Each card takes the angle it needs: its own width on its ring, or all its open
    // parts side by side, whichever is wider. Parts sit centred on their parent; the first ring grows
    // until every section fits round the middle, and spare room is shared out between the sections.
    function layout() {
      const kids = (n) => (closed.has(n.key) ? [] : n.children);
      let depth = 1;
      (function d(n) { depth = Math.max(depth, n.level); kids(n).forEach(d); })(data.tree);
      let r1 = 250;
      const radius = (lv) => (lv === 1 ? 0 : r1 + (lv - 2) * RING);
      const wide = (n) => Math.max((CW + 16) / radius(n.level), kids(n).reduce((a, k) => a + wide(k), 0));
      const sum = () => data.tree.children.reduce((a, k) => a + wide(k), 0);
      while (sum() > 2 * Math.PI) r1 += 20;
      const size = 2 * (radius(depth) + PAD + CW / 2);
      const c = size / 2;
      const out = [];
      function place(n, parent, ang) {
        const r = radius(n.level);
        const me = { n, parent, ang, x: c + r * Math.cos(ang), y: c + r * Math.sin(ang) };
        out.push(me);
        let a = ang - kids(n).reduce((t, k) => t + wide(k), 0) / 2;
        for (const k of kids(n)) { place(k, me, a + wide(k) / 2); a += wide(k); }
      }
      const root = { n: data.tree, parent: null, ang: -Math.PI / 2, x: c, y: c };
      out.push(root);
      const secs = kids(data.tree), gap = (2 * Math.PI - sum()) / Math.max(secs.length, 1);
      let a = -Math.PI / 2 - (wide(secs[0] ?? data.tree) + gap) / 2; // the first section sits at the top; reading runs clockwise
      for (const k of secs) { place(k, root, a + (wide(k) + gap) / 2); a += wide(k) + gap; }
      return { items: out, size, c };
    }

    function card(it) {
      const n = it.n;
      const root = n.level === 1;
      const title = root ? (data.source === "slides" ? "The whole deck" : "The whole paper") : n.title;
      const hidden = closed.has(n.key) ? n.children.length : 0;
      const meta = root ? `${data.pages} pages` : `Page ${n.page}${hidden ? `, ${hidden} parts to open` : ""}`;
      const isNew = !shown.has(n.key);
      const f = isNew ? from.get(n.key) : null;
      const style = [`left:${it.x - (root ? 90 : CW / 2)}px`, `top:${it.y - (root ? 90 : CH / 2)}px`];
      if (!root) style.push(`width:${CW}px`, `height:${CH}px`);
      if (f) style.push(`--fx:${f.x - it.x}px`, `--fy:${f.y - it.y}px`, `--d:${Math.min(born++, 16) * 28}ms`);
      return h("button", { type: "button", class: `t-card l${n.level} ${n.kind}${n.key === sel ? " on" : ""}${isNew ? " born" : ""}${hidden ? " shut" : ""}`,
        style: style.join(";"), "data-key": n.key, "aria-pressed": String(n.key === sel),
        "aria-expanded": n.children.length && !root ? String(!hidden) : null, onclick: () => choose(n.key, false, true) },
        h("span", { class: "t-title" }, title),
        !root && blurb(n) ? h("span", { class: "t-lead" }, blurb(n)) : null,
        h("span", { class: "t-meta" }, meta),
        hidden ? h("span", { class: "t-badge", "aria-hidden": "true" }, `+${hidden}`) : null);
    }

    let centred = false, born = 0;
    function paint() {
      const { items, size, c } = layout();
      if (!centred) items.forEach((it) => from.set(it.n.key, { x: c, y: c })); // the first view opens out of the middle
      born = 0;
      const svg = sv("svg", { class: "t-svg", width: size, height: size });
      for (const it of items) if (it.parent) {
        const a = it.parent, pa = a.parent ? a.ang : it.ang, k = RING * 0.45; // petal curve: leave and arrive heading outward
        svg.append(sv("path", { class: `t-link l${it.n.level}${shown.has(it.n.key) ? "" : " born"}`, pathLength: 1,
          d: `M${a.x} ${a.y} C${a.x + k * Math.cos(pa)} ${a.y + k * Math.sin(pa)} ${it.x - k * Math.cos(it.ang)} ${it.y - k * Math.sin(it.ang)} ${it.x} ${it.y}` }));
      }
      const layer = h("div", { class: "t-layer", style: `width:${size}px;height:${size}px` }, svg);
      const oldSize = holder.firstChild?.offsetWidth ?? size, d = (size - oldSize) / 2; // the canvas grows on every side
      const glide = [];
      items.forEach((it) => {
        const el = layer.appendChild(card(it)), was = prev.get(it.n.key);
        if (was && shown.has(it.n.key)) { glide.push([el, el.style.left, el.style.top]); el.style.left = `${parseFloat(was[0]) + d}px`; el.style.top = `${parseFloat(was[1]) + d}px`; }
      });
      const sx = holder.scrollLeft, sy = holder.scrollTop;
      holder.replaceChildren(layer);
      if (!centred) { centred = true; holder.scrollTo(c - holder.clientWidth / 2, c - holder.clientHeight / 2); }
      else holder.scrollTo(sx + d, sy + d); // the middle stays put as the tree grows
      items.forEach((it) => shown.add(it.n.key));
      from = new Map(); prev = new Map();
      if (glide.length) { void layer.offsetWidth; glide.forEach(([el, l, t]) => { el.style.left = l; el.style.top = t; }); }
      return items;
    }

    function paintPanel() {
      const n = byKey.get(sel);
      const title = n.level === 1 ? p.title : n.title;
      panel.replaceChildren(...[
        h("p", { class: "t-lvl" }, `L${n.level} ${kind[n.level - 1].replace(/s$/, "").toLowerCase()}, page ${n.page}${n.words ? `, ${n.words} words` : ""}`),
        h("h3", { class: "t-ptitle" }, title),
        n.text || n.lead ? h("p", { class: "t-text" }, n.text || n.lead)
          : h("p", { class: "help" }, n.kind === "figure" ? "A figure or table. Open the page to see it." : "This part has no text of its own. Its parts are listed below."),
        h("button", { type: "button", class: "btn", onclick: () => { location.hash = `#read/${p.id}/${n.page}`; } }, `Open at page ${n.page}`),
        n.children.length ? h("div", { class: "t-kids" }, h("p", { class: "t-lvl" }, `${n.children.length} parts inside`),
          h("ol", {}, n.children.map((c) => h("li", {}, h("button", { type: "button", class: "t-kid", onclick: () => choose(c.key, true) },
            h("span", {}, c.title), h("span", { class: "t-meta" }, `p${c.page}`)))))) : null].filter(Boolean));
    }

    // Picking a card opens it; picking the open, picked card again folds it.
    function choose(key, reveal, fromCard) {
      const n = byKey.get(key);
      if (reveal) for (let p2 = parentOf(key); p2; p2 = parentOf(p2.key)) closed.delete(p2.key);
      if (fromCard && n.children.length && n.level > 1) {
        if (closed.has(key)) closed.delete(key);
        else if (sel === key) fold(n);
      }
      sel = key;
      bloomFrom();
      tree.classList.add("settled"); paint(); paintPanel();
      holder.querySelector(".t-card.on")?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
    }
    function fold(n) { closed.add(n.key); (function drop(m) { shown.delete(m.key); m.children.forEach(drop); })(n); shown.add(n.key); }
    // New cards grow out of their parent's current place.
    function bloomFrom() {
      const pos = new Map([...holder.querySelectorAll(".t-card")].map((el) =>
        [Number(el.dataset.key), { x: el.offsetLeft + el.offsetWidth / 2, y: el.offsetTop + el.offsetHeight / 2 }]));
      from = new Map();
      prev = new Map([...holder.querySelectorAll(".t-card")].map((el) => [Number(el.dataset.key), [el.style.left, el.style.top]]));
      (function walk(n, at) { if (!shown.has(n.key) && at) from.set(n.key, at); n.children.forEach((k) => walk(k, pos.get(n.key) ?? at)); })(data.tree, null);
    }
    function parentOf(key) {
      for (const n of byKey.values()) if (n.children.some((c) => c.key === key)) return n;
      return null;
    }
    paint(); paintPanel();
  }
  function closeTree() { tree?.remove(); tree = null; stage.classList.remove("tree-open"); side.hidden = false; }

  buddy.look(true); // the yellow face with two eyes, no mouth, parked in the canvas corner
  buddy.roam(null);
  openGraph = { leave() { st.alive = false; cancelAnimationFrame(st.raf); ro.disconnect(); savePos(); buddy.look(false); buddy.roam(null); } };
  await boot();
  requestAnimationFrame(() => fit());
}
