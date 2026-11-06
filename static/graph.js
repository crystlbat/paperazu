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
  svg.append(world);

  const note = h("p", { class: "g-note", role: "status" });
  const input = h("input", { type: "search", class: "g-input", placeholder: "Search an idea, for example: re-identifying blurred faces",
    "aria-label": "Search an idea across your papers", maxlength: 300 });
  const findBtn = h("button", { type: "submit", class: "btn" }, "Find");
  const form = h("form", { class: "g-search", onsubmit: (e) => { e.preventDefault(); find(input.value.trim()); } }, input, findBtn);
  const legend = h("div", { class: "g-legend", "aria-hidden": "true" },
    h("span", {}, h("i", { class: "lg-paper" }), "Paper"),
    h("span", {}, h("i", { class: "lg-idea" }), "Idea you kept"),
    h("span", {}, h("i", { class: "lg-solid" }), "You linked"),
    h("span", {}, h("i", { class: "lg-dash" }), "AI suggests"));
  const zoomBtns = h("div", { class: "g-zoom" },
    h("button", { type: "button", class: "btn ghost", "aria-label": "Zoom in", onclick: () => zoomBy(1.25) }, "+"),
    h("button", { type: "button", class: "btn ghost", "aria-label": "Zoom out", onclick: () => zoomBy(0.8) }, "−"),
    h("button", { type: "button", class: "btn ghost", onclick: () => fit() }, "Fit"));
  const stage = h("section", { class: "g-stage", "aria-label": "Graph" }, svg, form, note, legend, zoomBtns);
  const side = h("aside", { class: "g-side", "aria-label": "Details" });
  view.append(stage, side);

  // ---------- state ----------
  const st = { nodes: new Map(), edges: [], ghost: null, sel: null, hover: null, data: null, papers: [],
    t: { x: 0, y: 0, k: 1 }, alpha: 0, raf: 0, alive: true };
  const saved = JSON.parse(localStorage.getItem(POS_KEY) || "{}");
  const savePos = () => localStorage.setItem(POS_KEY, JSON.stringify(Object.fromEntries(
    [...st.nodes.values()].filter((n) => n.kind !== "ghost").map((n) => [n.id, [Math.round(n.x), Math.round(n.y)]]))));

  // ---------- load ----------
  async function load(select) {
    const [g, lib] = await Promise.all([api("/graph"), api("/papers")]);
    st.data = g; st.papers = lib.papers;
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
  function build() {
    const { papers } = st, g = st.data;
    const next = new Map();
    for (const p of papers) next.set(p.id, node(p.id, "paper", p.title, { done: p.steps_done, total: p.progress.length, r: 16 + Math.min(10, p.steps_done) }));
    for (const c of g.concepts) next.set(c.id, node(c.id, c.kind === "suggested" ? "sugg" : "idea", c.label));
    if (st.ghost) next.set("ghost", node("ghost", "ghost", st.ghost.q));
    st.nodes = next;
    st.edges = [
      ...g.suggested.filter((e) => next.has(e.a) && next.has(e.b)).map((e) => ({ a: e.a, b: e.b, kind: "suggest", score: e.score })),
      ...g.links.filter((l) => next.has(l.concept_id) && next.has(l.paper_id)).map((l) => ({ a: l.concept_id, b: l.paper_id, kind: next.get(l.concept_id).kind === "sugg" ? "suggest" : "link", score: l.score })),
      ...(st.ghost ? st.ghost.results.filter((r) => r.on && next.has(r.paper_id)).map((r) => ({ a: "ghost", b: r.paper_id, kind: "ghost", score: r.score })) : []),
    ];
    draw();
  }

  // ---------- drawing ----------
  function draw() {
    edgeLayer.replaceChildren(...st.edges.map((e) => {
      e.el = sv("line", { class: `g-edge ${e.kind}`, "stroke-width": e.kind === "suggest" ? 1 + (e.score - 0.5) * 6 : 1.75 });
      return e.el;
    }));
    nodeLayer.replaceChildren(...[...st.nodes.values()].map((n) => {
      const label = n.kind === "paper" ? shortTitle(n.label) : n.label;
      const g = sv("g", { class: `g-node ${n.kind}`, tabindex: 0, role: "button",
        "aria-label": n.kind === "paper" ? `Paper: ${n.label}. ${n.done} of ${n.total} steps done.` : n.kind === "idea" ? `Idea: ${n.label}`
          : n.kind === "sugg" ? `AI suggested idea: ${n.label}` : `Search preview: ${n.label}` });
      if (n.kind === "paper") {
        const r = n.r, c = 2 * Math.PI * (r + 4);
        g.append(sv("circle", { class: "halo", r: r + 9 }), sv("circle", { class: "body", r }),
          sv("circle", { class: "track", r: r + 4 }),
          sv("circle", { class: "prog", r: r + 4, "stroke-dasharray": `${(c * n.done) / Math.max(1, n.total)} ${c}`, transform: "rotate(-90)" }),
          sv("text", { class: "glyph", "text-anchor": "middle", dy: "0.35em" }, String(n.done)),
          sv("text", { class: "label", "text-anchor": "middle", y: r + 22 }, label));
      } else if (n.kind === "sugg") {
        // a small dashed dot; its name shows on hover, when selected, or when you zoom in
        n.r = 16;
        g.append(sv("circle", { class: "halo", r: 15 }), sv("circle", { class: "body", r: 7 }),
          sv("text", { class: "label", "text-anchor": "middle", y: 24 }, label.length > 34 ? `${label.slice(0, 33)}…` : label));
      } else {
        const w = Math.min(220, 26 + label.length * 7.4);
        n.r = w / 2;
        g.append(sv("rect", { class: "halo", x: -w / 2 - 7, y: -22, width: w + 14, height: 44, rx: 22 }),
          sv("rect", { class: "body", x: -w / 2, y: -15, width: w, height: 30, rx: 15 }),
          sv("text", { class: "label", "text-anchor": "middle", dy: "0.35em" }, label.length > 30 ? `${label.slice(0, 29)}…` : label));
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
  function place() {
    for (const e of st.edges) {
      const a = st.nodes.get(e.a), b = st.nodes.get(e.b);
      e.el.setAttribute("x1", a.x); e.el.setAttribute("y1", a.y); e.el.setAttribute("x2", b.x); e.el.setAttribute("y2", b.y);
    }
    for (const n of st.nodes.values()) n.el.setAttribute("transform", `translate(${n.x.toFixed(1)} ${n.y.toFixed(1)})`);
    world.setAttribute("transform", `translate(${st.t.x} ${st.t.y}) scale(${st.t.k})`);
    svg.classList.toggle("zoomed", st.t.k >= 1.6);
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
  }

  // ---------- forces ----------
  function tick() {
    const ns = [...st.nodes.values()], a = st.alpha;
    for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) {
      const p = ns[i], q = ns[j];
      let dx = q.x - p.x, dy = q.y - p.y, d2 = dx * dx + dy * dy || 1;
      const min = (p.r ?? 20) + (q.r ?? 20) + 30;
      const both = p.kind === "paper" && q.kind === "paper";
      const f = ((both ? 14000 : 2600) / d2 + (d2 < min * min ? 0.4 : 0)) * a; // papers keep well apart
      const d = Math.sqrt(d2); dx /= d; dy /= d;
      p.vx -= dx * f; p.vy -= dy * f; q.vx += dx * f; q.vy += dy * f;
    }
    for (const e of st.edges) {
      const p = st.nodes.get(e.a), q = st.nodes.get(e.b);
      const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 1;
      const pp = st.nodes.get(e.a).kind === "paper" && st.nodes.get(e.b).kind === "paper";
      const len = pp ? 320 - e.score * 120 : e.kind === "suggest" ? 170 : 150;
      const f = ((d - len) / d) * 0.05 * a;
      p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
    }
    for (const n of ns) {
      n.vx -= n.x * 0.006 * a; n.vy -= n.y * 0.006 * a; // gentle pull to the middle
      if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = n.vy = 0; continue; }
      n.vx *= 0.82; n.vy *= 0.82; n.x += n.vx; n.y += n.vy;
    }
    st.alpha *= 0.985;
  }
  function heat(a) {
    st.alpha = Math.max(st.alpha, a);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      while (st.alpha > 0.02) tick();
      place(); savePos(); return;
    }
    if (!st.raf) st.raf = requestAnimationFrame(loop);
  }
  function loop() {
    st.raf = 0;
    if (!st.alive) return;
    tick(); place();
    if (st.alpha > 0.02) st.raf = requestAnimationFrame(loop);
    else savePos();
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
      if (Math.hypot(ev.clientX - s0[0], ev.clientY - s0[1]) < 4 && st.sel) { st.sel = null; paintFocus(); paintSide(); }
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
    const xs = ns.map((n) => n.x), ys = ns.map((n) => n.y), pad = 110;
    const w = Math.max(...xs) - Math.min(...xs) + pad * 2, hgt = Math.max(...ys) - Math.min(...ys) + pad * 2;
    const top = 76; // keep clear of the search bar
    st.t.k = Math.min(1.3, r.width / w, (r.height - top) / hgt);
    st.t.x = r.width / 2 - ((Math.min(...xs) + Math.max(...xs)) / 2) * st.t.k;
    st.t.y = top + (r.height - top) / 2 - ((Math.min(...ys) + Math.max(...ys)) / 2) * st.t.k;
    place();
  }
  const ro = new ResizeObserver(() => fit());
  ro.observe(svg);

  // ---------- side panel ----------
  function select(id) { st.sel = id; paintFocus(); paintSide(); }
  const paperById = (id) => st.papers.find((p) => p.id === id);
  const ideaLinks = (cid) => st.data.links.filter((l) => l.concept_id === cid);

  function paintSide() {
    if (st.ghost) return paintSearch();
    const n = st.sel && st.nodes.get(st.sel);
    if (n?.kind === "paper") return paintPaper(n);
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
      h("p", { class: "help" }, "Drag dots to arrange them. Click one for details. Double-click a paper to open it."),
      g.model ? h("p", { class: "help" }, `Embedding model: ${g.model}`) : null);
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
        h("span", { class: "g-row-sub" }, `Page ${l.page}. ${l.snippet.slice(0, 110)}…`))), "No ideas linked yet. Search one above."),
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
        h("span", { class: "g-row-sub" }, `Page ${l.page}. ${l.snippet.slice(0, 160)}…`),
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
        h("span", { class: "g-row-sub" }, `Page ${l.page}. ${l.snippet.slice(0, 160)}…`),
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
    side.replaceChildren(h("p", { class: "g-kind" }, "Searching"), h("h3", { class: "g-title serif" }, q),
      h("p", { class: "help g-wait" }, "Comparing your search with every passage in your papers."));
    try {
      const r = await api("/graph/search", { method: "POST", body: JSON.stringify({ q }) });
      st.ghost = { q, results: r.results.map((x) => ({ ...x, on: x.pick })) };
      st.sel = "ghost";
      build(); heat(0.7); paintSide();
    } catch (e) {
      side.replaceChildren(h("p", { class: "status err" }, e.body?.detail?.errors?.q || e.body?.detail || "Search failed."));
    } finally { findBtn.disabled = false; }
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
          h("span", { class: "g-row-sub" }, `Page ${r.page}. ${r.snippet.slice(0, 180)}…`)),
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
    const COL = 300, ROW = 34, PAD = 28;
    const back = h("button", { type: "button", class: "btn ghost", onclick: () => closeTree() }, "Back to the graph");
    const holder = h("div", { class: "t-scroll" });
    tree = h("section", { class: "g-tree", "aria-label": `Section tree of ${p.title}` },
      h("div", { class: "t-head" }, back,
        h("span", { class: "t-name" }, p.title),
        h("span", { class: "t-levels", "aria-hidden": "true" },
          ["Paper", "Sections", "Subsections", "Parts and figures"].map((t, i) => h("span", { class: `t-lv l${i + 1}` }, h("i"), `L${i + 1} ${t}`)))),
      data.source === "guessed" ? h("p", { class: "help t-note" }, "This PDF has no built-in outline, so the sections are guessed from its headings.") : null,
      holder);
    stage.classList.add("tree-open");
    stage.append(tree);
    back.focus();
    const closed = new Set(); // nodes you folded
    let seq = 0;
    (function tag(n) { n.key = seq++; n.children.forEach(tag); })(data.tree);

    function layout() {
      let row = 0;
      const out = [];
      (function place(n, parent) {
        const kids = closed.has(n.key) ? [] : n.children;
        const me = { n, parent, x: PAD + (n.level - 1) * COL, y: 0 };
        out.push(me);
        if (!kids.length) me.y = PAD + row++ * ROW;
        else { const ys = kids.map((c) => place(c, me).y); me.y = (ys[0] + ys[ys.length - 1]) / 2; }
        return me;
      })(data.tree, null);
      return { items: out, h: PAD * 2 + row * ROW };
    }

    function paint() {
      const { items, h: height } = layout();
      const maxLevel = Math.max(...items.map((i) => i.n.level));
      const svg = sv("svg", { class: "t-svg", width: PAD * 2 + (maxLevel - 1) * COL + COL, height });
      for (const it of items) if (it.parent) {
        const a = it.parent, mx = (a.x + it.x) / 2;
        svg.append(sv("path", { class: `t-link l${it.n.level}`, d: `M${a.x} ${a.y} C${mx} ${a.y} ${mx} ${it.y} ${it.x} ${it.y}` }));
      }
      for (const it of items) {
        const n = it.n, max = n.level === 1 ? 26 : 32;
        const label = n.level === 1 ? `${data.pages} pages` // the title is in the header above
          : n.title.length > max ? `${n.title.slice(0, max - 1)}…` : n.title;
        const g = sv("g", { class: `t-node l${n.level} ${n.kind}`, transform: `translate(${it.x} ${it.y})`,
          style: `--d:${n.level * 70}ms`, tabindex: 0, role: "link",
          "aria-label": `${n.title}, page ${n.page}. Opens the paper at this page.`,
          onclick: () => { location.hash = `#read/${p.id}/${n.page}`; },
          onkeydown: (e) => { if (e.key === "Enter") location.hash = `#read/${p.id}/${n.page}`; } },
          sv("title", {}, `${n.title} (page ${n.page})`),
          n.kind === "figure" ? sv("rect", { class: "dot", x: -4.5, y: -4.5, width: 9, height: 9, rx: 2 }) : sv("circle", { class: "dot", r: [0, 8, 6, 5, 4][n.level] }),
          sv("text", { class: "t-label", x: n.level === 1 ? -20 : 14, y: n.level === 1 ? 28 : 0, dy: "0.35em" }, label, n.level === 1 ? null : sv("tspan", { class: "t-page", dx: 8 }, `p${n.page}`)));
        svg.append(g);
        if (n.children.length && n.level > 1) {
          const shut = closed.has(n.key);
          svg.append(sv("g", { class: "t-fold", transform: `translate(${it.x - 22} ${it.y})`, tabindex: 0, role: "button",
            "aria-label": `${shut ? "Show" : "Hide"} the ${n.children.length} parts under ${n.title}`, "aria-expanded": String(!shut),
            onclick: () => toggle(n.key), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(n.key); } } },
            sv("circle", { r: 7 }), sv("text", { "text-anchor": "middle", dy: "0.35em" }, shut ? "+" : "−")));
        }
      }
      holder.replaceChildren(svg);
    }
    function toggle(key) { closed.has(key) ? closed.delete(key) : closed.add(key); tree.classList.add("settled"); paint(); }
    paint();
  }
  function closeTree() { tree?.remove(); tree = null; stage.classList.remove("tree-open"); }

  openGraph = { leave() { st.alive = false; cancelAnimationFrame(st.raf); ro.disconnect(); savePos(); } };
  await boot();
  requestAnimationFrame(() => fit());
}
