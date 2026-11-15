"use strict";
// ---------- the Chat tab: your talk with the character over a live 2D map of what it knows ----------
// makeChatNet() builds it once and keeps it (the report repaints around it, the graph keeps its layout and keeps moving).
// update(mesh, turns) feeds it /char/mesh and /char turns: new nodes pop in next to what they are wired to, so you watch it grow.
// Subnets: chips pick which layers show, so the one web splits into its maps (names, notes, questions, traits, chat).
const CN_LAYERS = { name: ["Entities", "#7dffa8"], note: ["Notes", "#6ff7ff"], question: ["Questions", "#ffd27a"], plan: ["Plans", "#b49cff"], trait: ["Traits", "#ff7ac6"], chat: ["Chat", "#8b93a7"], tool: ["Tools", "#ffb347"] };
const CN_NETS = [["all", "Everything", Object.keys(CN_LAYERS)], ["world", "World map", ["name", "note"]], ["entities", "Entities", ["name"]],
  ["mind", "What it wonders", ["question", "plan", "name"]], ["traits", "Traits", ["trait", "chat"]], ["notes", "Notes", ["note"]], ["tools", "Tools", ["tool", "plan", "question", "note", "name"]]];

function makeChatNet() {
  const cv = h("canvas", { class: "cn-cv", "aria-label": "Map of what it knows. Hover a node to read it." }), g = cv.getContext("2d");
  const bubbles = h("ol", { class: "cn-log", "aria-label": "Your conversation", "aria-live": "polite" });
  const card = h("aside", { class: "cn-card", hidden: "" }), count = h("small", { class: "cn-count" });
  let net = "all", nodes = new Map(), edges = [], hover = null, W = 1, H = 1, lastTurn = 0, turnsKey = "";
  const chips = h("div", { class: "cn-nets", role: "radiogroup", "aria-label": "Which map" }, ...CN_NETS.map(([k, t]) => h("button", { type: "button", role: "radio", "aria-checked": String(k === net), "data-k": k,
    onclick: () => { net = k; chips.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.k === k))); } }, t)));
  const legend = h("p", { class: "cn-legend" }, ...Object.entries(CN_LAYERS).map(([, [t, c]]) => h("span", { style: `--c:${c}` }, t)));
  const el = h("div", { class: "cn" }, cv, h("div", { class: "cn-top" }, chips, count), legend, card, bubbles);
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fit = () => { const d = devicePixelRatio || 1, r = cv.getBoundingClientRect(); W = Math.max(1, r.width); H = Math.max(1, r.height); cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0); };
  new ResizeObserver(fit).observe(cv);
  const shown = () => new Set(CN_NETS.find(([k]) => k === net)[2]);

  function update(mesh, turns) {
    const seen = new Set();
    for (const n of mesh?.nodes || []) { seen.add(n.id); const o = nodes.get(n.id);
      if (o) { Object.assign(o, { label: n.label, body: n.body, layer: n.layer, state: n.state }); continue; }
      const near = (mesh.edges || []).map(([a, b]) => (a === n.id ? b : b === n.id ? a : null)).map((id) => nodes.get(id)).find(Boolean); // born beside what it is wired to
      nodes.set(n.id, { ...n, x: near ? near.x + (Math.random() - .5) * 30 : (Math.random() - .5) * 300, y: near ? near.y + (Math.random() - .5) * 30 : (Math.random() - .5) * 200, vx: 0, vy: 0, born: nodes.size ? 0 : 1 }); }
    for (const id of [...nodes.keys()]) if (!seen.has(id)) nodes.delete(id);
    edges = (mesh?.edges || []).filter(([a, b]) => nodes.has(a) && nodes.has(b));
    const key = (turns || []).map((t) => t.id).join(",");
    if (key !== turnsKey) { turnsKey = key; const atEnd = bubbles.scrollHeight - bubbles.scrollTop - bubbles.clientHeight < 40;
      bubbles.replaceChildren(...(turns || []).slice(-60).map((t) => h("li", { class: `cn-b ${t.role === "dot" ? "it" : "you"}${t.text.startsWith("A wish: ") ? " wish" : ""}` }, t.text, t.heard ? h("small", { class: `cn-heard ${t.heard === "kept" ? "kept" : ""}` }, t.heard === "kept" ? "kept" : "let go") : "")));
      if (atEnd || (turns || []).at(-1)?.id !== lastTurn) bubbles.scrollTop = bubbles.scrollHeight; lastTurn = (turns || []).at(-1)?.id || 0;
      if (!bubbles.children.length) bubbles.append(h("li", { class: "cn-empty" }, "Nothing said yet. Type below to talk to it.")); }
  }

  function tick() { // a small force layout: nodes push apart, wires pull together, everything drifts to the middle
    const on = shown(), list = [...nodes.values()].filter((n) => on.has(n.layer));
    for (const a of list) { a.born = Math.min(1, a.born + .03);
      for (const b of list) { if (a === b) continue; const dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + 30, f = 900 / d2; a.vx += dx * f / Math.sqrt(d2); a.vy += dy * f / Math.sqrt(d2); }
      a.vx -= a.x * .004; a.vy -= a.y * .006; }
    for (const [ia, ib] of edges) { const a = nodes.get(ia), b = nodes.get(ib); if (!on.has(a.layer) || !on.has(b.layer)) continue;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1, f = (d - 70) * .01; a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f; }
    for (const a of list) { a.vx *= .82; a.vy *= .82; a.x += a.vx; a.y += a.vy; }
    return list;
  }

  function frame() {
    if (!el.isConnected) { requestAnimationFrame(frame); return; } // kept while the report repaints; it waits until it is back on screen
    const list = still ? [...nodes.values()].filter((n) => shown().has(n.layer)) : tick(), on = new Set(list.map((n) => n.id));
    let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity; for (const n of list) { minx = Math.min(minx, n.x); maxx = Math.max(maxx, n.x); miny = Math.min(miny, n.y); maxy = Math.max(maxy, n.y); }
    const left = W * .02, right = W * .6, s = list.length ? Math.min(1.6, (right - left - 80) / Math.max(1, maxx - minx), (H - 140) / Math.max(1, maxy - miny)) : 1; // the map sits left of the bubbles
    const ox = (left + right) / 2 - (minx + maxx) / 2 * s, oy = H / 2 + 20 - (miny + maxy) / 2 * s, P = (n) => [ox + n.x * s, oy + n.y * s];
    g.clearRect(0, 0, W, H); g.lineWidth = 1;
    for (const [ia, ib] of edges) { if (!on.has(ia) || !on.has(ib)) continue; const [x1, y1] = P(nodes.get(ia)), [x2, y2] = P(nodes.get(ib)), hot = hover && (hover.id === ia || hover.id === ib);
      g.strokeStyle = hot ? "rgba(232,236,244,.55)" : "rgba(139,147,167,.16)"; g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); }
    const deg = {}; for (const [a, b] of edges) { deg[a] = (deg[a] || 0) + 1; deg[b] = (deg[b] || 0) + 1; }
    for (const n of list) { const [x, y] = P(n), c = CN_LAYERS[n.layer]?.[1] || "#8b93a7", r = (3 + Math.min(7, Math.sqrt(deg[n.id] || 0) * 1.6)) * (still ? 1 : .3 + .7 * n.born);
      if (n.born < 1 && !still) { g.strokeStyle = c; g.globalAlpha = 1 - n.born; g.beginPath(); g.arc(x, y, r + 14 * n.born, 0, 6.283); g.stroke(); g.globalAlpha = 1; } // a new one rings as it lands
      g.fillStyle = c; g.globalAlpha = n.state === "dropped" || n.state === "idle" ? .35 : 1; g.beginPath();
      if (n.layer === "tool" && n.kind === "model") { g.lineWidth = 3; g.strokeStyle = c; g.arc(x, y, r + 4, 0, 6.283); g.stroke(); g.lineWidth = 1; } // the model: a ring every step hangs from
      else if (n.layer === "tool") { g.rect(x - r, y - r, r * 2, r * 2); g.fill(); } else { g.arc(x, y, r, 0, 6.283); g.fill(); } g.globalAlpha = 1; // tools are squares, what it knows is dots
      if (n === hover || (n.layer === "name" && (deg[n.id] || 0) >= 2) || n.layer === "trait" || n.layer === "tool") { g.font = "12px ui-sans-serif, system-ui, sans-serif"; g.fillStyle = n === hover ? "#fff" : "rgba(201,205,214,.85)"; g.textAlign = "center";
        g.fillText(n.label.length > 32 ? `${n.label.slice(0, 31)}…` : n.label, x, y - r - 6); }
      n.sx = x; n.sy = y; n.sr = r; }
    count.textContent = `${list.length} of ${nodes.size} shown · ${edges.filter(([a, b]) => on.has(a) && on.has(b)).length} wires`;
    requestAnimationFrame(frame);
  }
  cv.addEventListener("pointermove", (e) => { const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, on = shown();
    const hit = [...nodes.values()].filter((n) => on.has(n.layer) && n.sx != null).find((n) => Math.hypot(n.sx - x, n.sy - y) < n.sr + 6) || null;
    if (hit === hover) return; hover = hit; cv.style.cursor = hit ? "pointer" : "";
    if (!hit) { card.hidden = true; return; }
    card.replaceChildren(h("small", { style: `color:${CN_LAYERS[hit.layer]?.[1]}` }, CN_LAYERS[hit.layer]?.[0] || hit.layer), h("b", {}, hit.label), hit.body ? h("p", {}, hit.body.slice(0, 280)) : "");
    card.hidden = false; });
  cv.addEventListener("pointerleave", () => { hover = null; card.hidden = true; });
  requestAnimationFrame(frame);
  return { el, update };
}
