"use strict";
// ---------- /char as a 3D web: Dot is a sphere, what it knows is a mesh of neurons round it, its variables orbit close in ----------
// Everything the learning loop does is something you can watch here. Near things are big and labelled, far things small and dim;
// drag (or arrow keys) to turn. space.js owns the chat, the model calls and the modals; this file only draws and reports clicks.
function spWeb(root, { api, h, still, mind, wiring, step, reload }) {
  root.classList.add("sp-web");
  const cv = h("canvas", { class: "sw-cv", tabindex: "0", "aria-label": "The web of what it knows. Drag or use the arrow keys to turn. Click a labelled node for detail." }), g = cv.getContext("2d");
  const lamps = h("span", { class: "sw-lamps", "aria-hidden": "true" }, ...[[2, "S2"], [1, "S1"], [0, "S0"], [3, "V"]].map(([id, t]) => h("span", { "data-s": id }, h("i", {}), t)));
  const who = h("b", {}, "…"), modes = h("span", { class: "sw-modes", role: "radiogroup", "aria-label": "Mode" });
  const status = h("p", { class: "sw-now", "aria-live": "polite" }), tower = h("div", { class: "sw-tower", "aria-label": "Telemetry: its variables over time" }), steps = h("div", { class: "sw-eng", "aria-label": "Engine status" }), facts = h("div", { class: "sw-facts" });
  const hint = h("p", { class: "sw-hint" }), modeChip = h("span", { class: "sw-mode" });
  const TINTS = ["#6ff7ff", "#ffe347", "#ff7ab6", "#7dffa8", "#b49cff", "#ff8f6b"]; // its colour: pick one when you meet it, change it any time
  const tints = h("span", { class: "sw-tints", role: "group", "aria-label": "Its colour" }, ...TINTS.map((c) => h("button", { type: "button", style: `--c:${c}`, "aria-label": `Colour ${c}`, title: "Change its colour",
    "aria-pressed": "false", onclick: async () => { try { await api("/char/tint", { method: "POST", body: JSON.stringify({ tint: c }) }); } catch { return; } tint = c; markTint(); reload(); } })));
  const cur = h("span", { class: "sw-cur" }, h("i", {}), h("span", {})); // the live colour, even when it is not one of the swatches
  const markTint = () => { const t = tint.toLowerCase(); tints.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(TINTS[i] === t))); cur.style.setProperty("--c", tint); cur.lastChild.textContent = `Now ${tint}`; };
  const shut = () => { menu.hidden = true; menuBtn.setAttribute("aria-expanded", "false"); };
  const ink = h("div", { class: "sw-ink" }), drop = h("i", { class: "sw-drop" }), peek = h("div", { class: "sw-peek", "aria-hidden": "true" }, h("i", {}), h("i", {})), chipsEl = h("div", { class: "sw-chips" });
  const fx = h("div", { class: "sw-fx", "aria-hidden": "true" }); // the liquid: letters swell into each other, then a light picks out their edges
  fx.innerHTML = `<svg width="0" height="0"><filter id="sw-liquid" x="-20%" y="-40%" width="140%" height="180%" color-interpolation-filters="sRGB">
    <feMorphology id="sw-fat" in="SourceAlpha" operator="dilate" radius="1"/><feGaussianBlur id="sw-soft" stdDeviation="2"/>
    <feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 20 -8" result="goo"/>
    <feGaussianBlur in="goo" stdDeviation="2.2" result="dome"/>
    <feSpecularLighting in="dome" surfaceScale="5" specularConstant="1.1" specularExponent="22" lighting-color="#ffffff" result="shine"><feDistantLight azimuth="235" elevation="52"/></feSpecularLighting>
    <feDiffuseLighting in="dome" surfaceScale="4" diffuseConstant="1" lighting-color="#b9a6ff" result="hue"><feDistantLight azimuth="45" elevation="38"/></feDiffuseLighting>
    <feFlood id="sw-tint" flood-color="#6ff7ff"/><feComposite in2="goo" operator="in" result="body"/>
    <feComposite in="hue" in2="goo" operator="in" result="hue2"/><feBlend in="body" in2="hue2" mode="soft-light" result="lit"/>
    <feComposite in="shine" in2="goo" operator="in" result="shine2"/>
    <feMerge><feMergeNode in="lit"/><feMergeNode in="shine2"/></feMerge></filter></svg>`;
  const cmds = h("div", { class: "sw-cmds", hidden: "", role: "listbox", "aria-label": "Commands" }); // Dot, poured into the list of commands
  const bubble = h("div", { class: "sw-say", hidden: "" }, ink, peek, chipsEl), note = h("aside", { class: "sw-note", hidden: "", "aria-label": "Details" });
  // the mesh, top to bottom: what S2 planned, the questions S1 made of it, the notes S0 found (the Verifier's verdict is their colour), the names in them, and the chat
  const LAYERS = [["trait", "traits", -235], ["plan", "S2 plans", -170], ["question", "S1 questions", -85], ["note", "S0 notes", 5], ["name", "names", 100], ["chat", "chat", 190], ["var", "variables"]], hide = new Set();
  const LY = Object.fromEntries(LAYERS.map(([k, t, y]) => [k, { t, y }]));
  const stepBtn = h("button", { type: "button", onclick: async () => { stepBtn.disabled = true; await step(); stepBtn.disabled = false; } }, "Run one step");
  // every control lives behind one button, so the scene stays a scene
  const menu = h("div", { class: "sw-menu", hidden: "", role: "dialog", "aria-label": "Controls" },
    h("small", {}, "Mode"), modes, h("small", {}, "Colour"), tints, cur,
    h("small", {}, "Show"), h("span", { role: "group", "aria-label": "Layers" }, ...LAYERS.map(([k, t]) => h("button", { type: "button", class: `sw-lay ${k}`, "aria-pressed": "true",
      onclick: (e) => { const on = hide.has(k); on ? hide.delete(k) : hide.add(k); e.currentTarget.setAttribute("aria-pressed", String(on)); } }, t))),
    h("small", {}, "Look inside"), h("span", {}, stepBtn, h("button", { type: "button", onclick: () => { shut(); mind(); } }, "Mind"), h("button", { type: "button", onclick: () => { shut(); wiring(); } }, "Wiring")));
  const menuBtn = h("button", { type: "button", class: "sw-menubtn", "aria-label": "Controls", "aria-expanded": "false", onclick: () => { menu.hidden = !menu.hidden; menuBtn.setAttribute("aria-expanded", String(!menu.hidden)); } }, "⋯");
  const reportBtn = h("button", { type: "button", class: "sw-reportbtn", onclick: () => report() }, "Report");
  root.append(cmds); root.append(fx, cv, h("div", { class: "sw-top" }, who, modeChip, lamps, reportBtn, menuBtn), menu, bubble, note,
    h("aside", { class: "sw-left" }, tower), h("aside", { class: "sw-right" }, status, steps, facts), hint);
  const nav = root.querySelector(".sp-top"); if (nav) { nav.append(h("a", { href: "#verse", class: "sp-home sw-verse" }, "Verse")); menu.append(h("small", {}, "Go to"), nav); nav.addEventListener("click", (e) => { if (e.target.closest("a, button")) shut(); }); } // Library, Notes and History join the other controls
  root.addEventListener("pointerdown", (e) => { if (!menu.hidden && !e.target.closest(".sw-menu, .sw-menubtn")) shut(); });
  const ear = root.querySelector(".sp-ear input"); // the chat line stays out of the way: start typing anywhere and it takes the words
  addEventListener("keydown", function type(e) { if (!root.isConnected) return removeEventListener("keydown", type);
    if (e.key === "Escape") { shut(); return; }
    if (ear && e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey && !e.target.closest?.("input, textarea, select, button, [contenteditable]") && !root.querySelector(".sp-steer-modal")) ear.focus(); });

  // the story's palette: what it knows is white, yellow is what is live this second, red is what the Verifier turned away; settled things are filled squares, open ones hollow
  const SIG = "#ffe600", BAD = "#ff6b6b", WAVE_C = ["#c79bff", "#ffb347", "#6ff7ff", "#7dffa8"];
  const LCOL = { plan: "#c79bff", question: "#ffb347", note: "#6ff7ff", trait: "#ff7ac6", chat: "#9fb4ff" }; // the systems' colours: S2 violet, S1 amber, S0 cyan, V green
  const colour = (n) => ["rejected", "mistake", "dropped"].includes(n.state) ? BAD : n.layer === "note" && n.state === "verified" ? "#7dffa8"
    : n.layer === "name" ? (n.kind === "idea" ? "#c79bff" : n.state === "known" ? "#f4f6fb" : "#ffd27a") : n.layer === "chat" && n.kind !== "you" ? tint : LCOL[n.layer] || "#fff";
  const rgba = (c, a) => { const v = parseInt(String(c).slice(1), 16); return `rgba(${v >> 16},${(v >> 8) & 255},${v & 255},${Math.max(0, Math.min(1, a))})`; };
  const glow = (x, y, r, c, a) => { if (r < 1 || a <= .01) return; const gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, rgba(c, a)); gr.addColorStop(.4, rgba(c, a * .35)); gr.addColorStop(1, rgba(c, 0)); g.fillStyle = gr; g.fillRect(x - r, y - r, r * 2, r * 2); };
  const R3 = ((s0) => () => ((s0 = (s0 * 16807) % 2147483647) - 1) / 2147483646)(11); // the motes: dust that drifts through its mind, fixed seeds so it keeps its shape
  const MOTES = [...Array(170)].map(() => { const u = R3() * 2 - 1, a = R3() * 6.283, k = Math.cbrt(R3()) * .95, s1 = Math.sqrt(1 - u * u); return { x: Math.cos(a) * s1 * k, y: u * k, z: Math.sin(a) * s1 * k, ph: R3() * 99, c: ["#c79bff", "#ffb347", "#6ff7ff", "#7dffa8", "#ffffff", "#ffffff"][R3() * 6 | 0] }; });
  const hollow = (n) => n.layer === "trait" ? n.state !== "grown" : ["unchecked", "open", "curious"].includes(n.state);
  const hoverAt = (q) => ptr && Math.hypot(q.x - ptr[0], q.y - ptr[1]) < 30;
  const RS0 = 290; let RS = RS0, wires = []; // the mind's shell grows with what it knows, so nodes keep their room
  // inside the shell each layer is its own structure, the way the story opens Dot: where node i of n sits (in shell radii), and the system whose colour its lines take
  const fr = (i) => (i * .618034) % 1, GA = 2.39996;
  const SHAPE = {
    trait: { sys: null, at: (i, n) => { const a = (i + .5) / n * 6.283; return [Math.cos(a) * .3, -.8, Math.sin(a) * .3]; }, tag: [.34, -.86, 0] }, // a crown: who it is
    plan: { sys: 2, at: (i) => { const a = i * GA, u = 1 - 2 * fr(i * 3 + 1), k = .45 + .55 * fr(i), r = Math.sqrt(1 - u * u) * .58 * k; return [Math.cos(a) * r, -.5 + u * .15, Math.sin(a) * r]; }, tag: [.62, -.5, 0] }, // a net in its head
    question: { sys: 1, at: (i, n) => { const a = (i + .5) / n * 6.283; return [Math.cos(a) * (.7 + (fr(i) - .5) * .08), -.12 + Math.sin(i * 1.7) * .035, Math.sin(a) * (.7 + (fr(i) - .5) * .08)]; }, tag: [.8, -.12, 0] }, // a ring round its middle
    note: { sys: 0, at: (i) => { const a = i * GA, r = .48 + .42 * fr(i); return [Math.cos(a) * r, .16 + (fr(i * 7) - .5) * .18, Math.sin(a) * r]; }, tag: [.96, .16, 0] }, // hands reaching out to the web
    name: { sys: 3, at: (i, n) => { const a = i * GA, u = 1 - 2 * (i + .5) / n, r = Math.sqrt(1 - u * u); return [Math.cos(a) * r * 1.1, u * 1.1, Math.sin(a) * r * 1.1]; }, tag: [1.1, .3, 0] }, // the ends of the mesh: out on the shell itself, so every link reaches the surface
    chat: { sys: null, at: (i, n) => { const f = (i + .5) / n, a = f * 6.283 * 2.5; return [Math.cos(a) * (.32 - f * .12), .74 + f * .14, Math.sin(a) * (.32 - f * .12)]; }, tag: [.36, .82, 0] }, // a spiral at its base: what was said
  };
  const xp = { h: 0, s: 0, t: 0, k: 0, w: 0, i: 0 }; const limA = [0, 0, 0, 0, 0], limV = [0, 0, 0, 0, 0], limB = [0, 0, 0, 0, 0], limBV = [0, 0, 0, 0, 0]; let gph = 0, emo = null, hd = { a: 0, av: 0, u: 0, uv: 0, ga: 0, gu: 0, next: 0 }, zoomSaid = false, want = null, gait = 0, zoom = 1, zt = 1, nextEmo = 400, dimD = 0, gat = 0, orbA = 0, fv = [0, 0], spinV = 0, folR = 40, boxT = null, boxIdle = 0, earA = 0, hearts = [], pats = [], patDir = 0, fol = null, folE = 0, fp = null, bp = null, ballE = 0, mouse = null, mouseV = 0; // following you: the command's start, how far the mind has gathered, where it is, where its box is, how much it's a ball round your cursor
  let planes = {}, W = 1, H = 1, K = 1, cx = 0, cy = 0, bcx = 0, bK = 1, lay = 0, sit = null, stageR = null, earNat = null, earOn = false, hold = 0, lastDot = null, nodes = [], edges = [], vars = [], tint = "#6ff7ff", proj = [];
  const EYES = { extract: "read", sort: "read", practise: "read", fill: "read", reflect: "search", wonder: "search", ideas: "search", plan: "think", goal: "think", ask: "think",
    check: "verify", review: "verify", evaluate: "verify", fold: "fold", bake: "fold" };
  const SYSC = { 2: "#c79bff", 1: "#ffb347", 0: "#6ff7ff", 3: "#7dffa8" }, VERB_OF = { read: "reading", search: "searching", think: "thinking", verify: "checking", fold: "folding" };
  // expanded, each job is its own character: a small body in its system's colour, walking the net to the nodes it works on
  const HOME = { reflect: "question", wonder: "question", ideas: "name", plan: "plan", goal: "question", ask: "question", check: "note", review: "chat", evaluate: "note",
    extract: "note", sort: "chat", practise: "chat", fill: "trait", fold: "name", bake: "note" }, sysOf = {};
  let agents = [], pinned = null, workE = 0, workCol = "#fff"; const SHELLPAL = [], WAVE = [[199, 155, 255], [255, 179, 71], [111, 247, 255], [125, 255, 168]];
  const pickNode = (k) => { const pool = nodes.filter((n) => n.layer === HOME[k] && !hide.has(n.layer)); return (pool.length ? pool : nodes)[Math.random() * (pool.length || nodes.length) | 0]; };
  function agentOf(k) { return agents.find((a) => a.k === k) || (agents.push({ k, x: cx, y: cy, n: null, work: 0, ph: Math.random() * 99, vx: 0 }), agents.at(-1)); }
  function walk() { // each character heads for its node, works there with its eyes, then wanders to another of its kind; contracting, they all go home into Dot
    if (!agents.length) return;
    for (const a of agents) {
      let tx = cx, ty = cy;
      if (growTo) { if (!a.n || (a.work <= 0 && Math.random() < .004)) a.n = pickNode(a.k); const q = a.n && proj[nodes.indexOf(a.n)]; if (q) { tx = q.x; ty = q.y - 16; } }
      const px0 = a.x; a.x += (tx - a.x) * (still ? 1 : .03); a.y += (ty - a.y) * (still ? 1 : .03); a.vx = a.x - px0; if (a.work > 0) a.work--;
      const c = SYSC[sysOf[a.k]] || tint, r = 14 * K, t = tick * .06 + a.ph, bob = still ? 0 : Math.sin(t) * 2;
      g.globalAlpha = growTo ? .95 : Math.min(.95, Math.hypot(a.x - cx, a.y - cy) / 60); g.strokeStyle = c; g.lineWidth = 1; g.beginPath(); g.arc(a.x, a.y + bob, r, 0, 6.283); g.stroke();
      const mode = a.work > 0 ? EYES[a.k] : "", ph = 260 - a.work; let ex2 = Math.max(-2.5, Math.min(2.5, a.vx * 2)), ey2 = 0, lid = 1;
      if (mode === "read") { ex2 = -2.5 + (ph % 50) / 50 * 5; ey2 = 1; } else if (mode === "search") { ex2 = Math.sin(ph * .12) * 2.5; ey2 = -2; } else if (mode === "think") ey2 = -2.5;
      else if (mode === "verify") lid = .4; else if (mode === "fold") lid = .2;
      g.fillStyle = "#fff"; for (const o of [-4.8, 4.8]) { g.beginPath(); g.ellipse(a.x + o * K + ex2 * K, a.y + bob + ey2 * K, 2.2 * K, Math.max(.8, 5.4 * K * lid * (tick % 170 > 165 ? .15 : 1)), 0, 0, 6.283); g.fill(); }
      if (a.work > 0 || growTo) { g.font = "600 11px ui-monospace, monospace"; g.textAlign = "center"; g.globalAlpha = a.work > 0 ? 1 : .7; g.fillStyle = c; g.fillText(a.work > 0 ? `${a.k} · ${VERB_OF[mode] || "working"}` : a.k, a.x, a.y + bob - r - 6); }
      g.globalAlpha = 1;
    }
    if (!growTo) agents = agents.filter((a) => Math.hypot(a.x - cx, a.y - cy) > 6);
  }
  let form = null, formOf = "", cb = 0; // its chibi form: the live persona's look from /char/chibi, and how far it has morphed into it
  let eyeTask = null, grow = 0, growTo = 0, detached = false, learning = false, lift = 1, yaw = .5, pitch = -.45, drag = null, moved = 0, tick = 0, ptr = null, ex = 0, ey = 0, happy = 0, blinkAt = 120, talk = 0, morph = 0, slab = null, wet = 1, px = 0, py = 0, busy = false, lit = -1, litT = 0, sparks = [], rings = [], gulp = [];
  const hash = (t) => [...t].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  function fit() { const d = devicePixelRatio || 1; W = root.clientWidth; H = root.clientHeight; cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0); K = Math.max(.4, Math.min(W / (2.2 * RS + 160), (H - 150) / (2.3 * RS), 1.6)); cx = W / 2; cy = 56 + (H - 150) / 2; bcx = cx; bK = K; } // the sphere sits between the top bar and the hint and input, clear of both
  const ro = new ResizeObserver(() => root.isConnected ? fit() : ro.disconnect()); ro.observe(root); fit();
  function P(x, y, z) { y *= lift; const a = Math.cos(yaw), b = Math.sin(yaw), c = Math.cos(pitch), d = Math.sin(pitch), x1 = x * a + z * b, z1 = -x * b + z * a, y1 = y * c - z1 * d, z2 = y * d + z1 * c, s = 700 / (700 + z2 * K) * (1 - .9 * gat * gat) * (1 + .3 * folE * (1 - gat)); // following you, the sky spreads a little wider
    return { x: cx + x1 * s * K, y: cy + y1 * s * K, z: z2, s: s * K }; }

  // ---- what it shows: the graph space.js already holds, and the wiring (signals, mode, the open correction) it fetches itself ----
  function data() { meshLoad(); } // space.js calls this whenever its state changes: the mesh is read whole from /char/mesh
  async function meshLoad() {
    let m; try { m = await api("/char/mesh"); } catch { return; }
    const old = new Map(nodes.map((n) => [n.key, n])), by = {};
    for (const x of m.nodes) (by[x.layer] ||= []).push(x);
    nodes = [];
    // one full globe around Dot: every node evenly on a sphere (a Fibonacci spiral), in layer order from the top, so each layer is a band of latitude
    // as tall as it is full; however lopsided the counts, the shape stays round, with no flat side
    const N = m.nodes.length; RS = RS0 * Math.min(1.7, Math.max(1, Math.sqrt(N / 80))); fit(); wires = [];
    for (const [layer, S] of Object.entries(SHAPE)) { const list = by[layer] || [], pts = [];
      list.forEach((x, i) => { const [ux, uy, uz] = S.at(i, list.length), o = old.get(x.id); pts.push([ux * RS, uy * RS, uz * RS]);
        nodes.push({ ...x, key: x.id, x: ux * RS, y: uy * RS, z: uz * RS, flash: o ? o.flash : old.size ? 70 : 0, born: o || !old.size ? 1 : 0 }); });
      if (!list.length) continue;
      const w = (line, dash) => wires.push({ layer, sys: S.sys, line, dash });
      if (layer === "plan") pts.forEach((p, i) => pts.map((q, j) => [j, Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])]).filter(([j]) => j !== i).sort((u, v) => u[1] - v[1]).slice(0, 2).forEach(([j]) => i < j && w([p, pts[j]]))); // each plan joined to its two nearest
      else if (layer === "question" || layer === "trait") { const [, y] = S.at(0, 1), r = layer === "trait" ? .3 : .7; w([...Array(65)].map((_, j) => [Math.cos(j / 64 * 6.283) * r * RS, y * RS, Math.sin(j / 64 * 6.283) * r * RS])); }
      else if (layer === "note") pts.forEach((p) => w([[p[0] * .2, .1 * RS, p[2] * .2], p], [3, 4])); // a hand from its core to each note
      else if (layer === "chat") w(pts);
      S.n = list.length; }
    const at = new Map(nodes.map((n, i) => [n.id, i]));
    edges = m.edges.map(([a, b]) => [at.get(a), at.get(b)]).filter((e) => e[0] != null && e[1] != null);
    planes = { chat: RS }; // expanded, Dot grows out to the shell
    edges.forEach(([a, b]) => { nodes[a].deg = (nodes[a].deg || 0) + 1; nodes[b].deg = (nodes[b].deg || 0) + 1; }); // hubs draw bigger and are labelled first
    const cnt = (l, st) => (by[l] || []).filter((x) => st.includes(x.state)).length, join = (...xs) => xs.filter(([v]) => v).map(([v, t]) => `${v} ${t}`).join(" · ");
    const SUB = { trait: () => join([cnt("trait", ["grown"]), "grown"], [cnt("trait", ["base"]), "from its persona"]),
      plan: () => join([cnt("plan", ["open"]), "in play"], [cnt("plan", ["dropped"]), "dropped"]), question: () => join([cnt("question", ["answered"]), "answered"], [cnt("question", ["open"]), "open"], [cnt("question", ["dropped"]), "dropped"]),
      note: () => join([cnt("note", ["verified"]), "verified"], [cnt("note", ["unchecked"]), "unchecked"], [cnt("note", ["rejected"]), "turned away"]),
      name: () => join([cnt("name", ["known"]), "read about"], [cnt("name", ["curious"]), "still curious"]), chat: () => `${SHAPE.chat.n} turns` };
    for (const [k, S] of Object.entries(SHAPE)) S.sub = S.n ? SUB[k]() || `${S.n}` : "";
  }
  const spark = (pts, color) => { const el = h("span", { class: "sw-spark" }); if (pts.length < 2) return el; // one line per variable: how it moved, step by step
    const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1, xy = pts.map((v, i) => `${(i / (pts.length - 1) * 96 + 2).toFixed(1)},${(22 - (v - lo) / span * 18).toFixed(1)}`).join(" ");
    el.innerHTML = `<svg viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden="true"><polyline points="${xy}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`; return el; };
  const dialOut = h("output", {}, "×1"), dialIn = h("input", { type: "range", min: 0, max: 3, step: 0.25, value: 1, "aria-label": "Curiosity dial",
    oninput: (e) => { dialOut.textContent = `×${e.target.value}`; }, onchange: async (e) => { try { await api("/char/dial", { method: "POST", body: JSON.stringify({ curiosity: +e.target.value }) }); } catch { /* the next poll shows the real value */ } watch(); } });
  const trackOut = h("small", { class: "sw-track" }), num = (k, label) => h("label", { class: "sw-num" }, label, h("input", { type: "number", min: 0.5, max: 50, step: 0.5, "data-k": k, "aria-label": label,
    onchange: async (e) => { try { paintTrack(await api("/char/tracker", { method: "POST", body: JSON.stringify({ [k]: +e.target.value }) })); } catch { /* the next poll shows the real value */ } refresh(); } }));
  const sleepIn = num("sleep_at", "sleeps at"), maxIn = num("max", "max");
  function paintTrack(T) { trackOut.textContent = `ups ${(T.ups ?? 0) % (T.every || 10)}/${T.every || 10} · momentum +${T.momentum ?? 0}`;
    for (const [el, v] of [[sleepIn, T.sleep_at], [maxIn, T.max]]) { const i = el.querySelector("input"); if (document.activeElement !== i && v != null) i.value = v; } }
  const dialEl = h("label", { class: "sw-dial", onclick: (e) => e.stopPropagation() }, h("small", {}, "your dial: 0 stops it, 3 triples it"), dialIn, dialOut, trackOut, h("span", { class: "sw-nums" }, sleepIn, maxIn)); // your hand on curiosity, opened by clicking its bar
  async function watch() {
    let m; try { m = await api("/char/monitor"); } catch { return; }
    const d = m.disposition, fmt = (v) => String(Math.round(v * 100) / 100);
    tower.replaceChildren(...m.series.map((x) => { const now = x.points.at(-1) ?? (x.name === "curiosity" ? d.curiosity : x.name === "maturity" ? d.maturity : 0), c = x.yours ? "#6ff7ff" : x.name === "maturity" ? "#7dffa8" : "#ffb347";
      return h("div", { class: "sw-tel", style: `--c:${c}`, title: x.name === "curiosity" ? `How much it wants to learn: ${d.dnE} new names × ${fmt(d.tau)} still unanswered, damped by maturity. At 0 it stops reaching out.` : x.name === "maturity" ? `How much it has answered per name (${d.baked.nAE} answers about ${d.baked.nE} names at its last consolidation). The closer to 1, the harder curiosity is braked.` : "A variable of yours, step by step." },
        h("small", {}, x.name), h("b", {}, fmt(now)), spark(x.points, c), ...(x.name === "curiosity" ? [dialEl] : [])); }));
    const cur = tower.querySelector(".sw-tel"); if (cur && m.series[0]?.name === "curiosity") { cur.classList.add("sw-tel-dial"); cur.tabIndex = 0; cur.setAttribute("role", "button"); cur.setAttribute("aria-expanded", String(!dialEl.hidden));
      cur.onclick = () => { dialEl.hidden = !dialEl.hidden; cur.setAttribute("aria-expanded", String(!dialEl.hidden)); }; cur.onkeydown = (e) => { if (e.target === cur && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); cur.click(); } }; }
    if (document.activeElement !== dialIn) { dialIn.value = d.dial ?? 1; dialOut.textContent = `×${d.dial ?? 1}`; }
    const row = (k, v, tip) => h("p", { title: tip || "" }, h("small", {}, k), v);
    facts.replaceChildren(row("last reply", m.last ? `${m.last.names.length} names · ${m.last.notes.length} notes` : "none yet", m.last ? [...m.last.names, ...m.last.notes].join(" · ") : "Ask it something."),
      row("corrections", `${m.loop.cycles} cycle${m.loop.cycles === 1 ? "" : "s"} · ${m.loop.instructions + m.loop.fixes} prompt change${m.loop.instructions + m.loop.fixes === 1 ? "" : "s"}`, `It reread ${m.loop.reviewed} of its replies and found ${m.loop.mistakes} mistakes. You answered ${m.loop.cycles} correction questions; ${m.loop.instructions} standing instructions and ${m.loop.fixes} approved prompt fixes are in use.`),
      row("steps", String(m.steps), "Every learning step and every reply since this character began."));
  }
  const seen = {}; let engOk = true; // kind -> last.at, to flash a row when its engine runs again
  async function engines() {
    let e; try { e = await api("/char/engines"); detached = !e.model.up; } catch { detached = true; engOk = false; steps.replaceChildren(h("p", { class: "sw-engoff" }, "Engine status unavailable")); return; }
    const first = engOk && Object.keys(seen).length === 0, grp = [[2, "S2"], [1, "S1"], [0, "S0"], [3, "Verifier"], [null, "Other"]], out = [];
    engOk = true;
    out.push(h("p", { class: "sw-engmodel", title: e.model.up ? "Model reachable" : "Model not reachable" }, h("i", { class: e.model.up ? "ok" : "failed" }), `Model: ${e.model.label}`));
    for (const [sys, name] of grp) {
      const rows = e.engines.filter((x) => (x.system ?? null) === sys && x.last); if (!rows.length) continue;
      out.push(h("small", { class: "sw-enghead" }, name));
      for (const x of rows) {
        const l = x.last, st = x.blocked ? "idle" : l ? l.outcome : "idle", txt = x.blocked || (l ? `${l.at} ${l.outcome}: ${l.detail}` : "not run yet"),
          row = h("div", { class: "sw-engrow", "data-st": st, title: `${x.label}: ${txt}` }, h("i"), h("b", {}, x.label), h("span", {}, txt), h("small", {}, x.runs ? String(x.runs) : ""));
        if (!first && l && seen[x.kind] !== undefined && seen[x.kind] !== l.at) { row.classList.add("flash"); if (l.outcome === "ok") { const at = nodes.filter((n) => n.label && n.label.length > 3 && l.detail.toLowerCase().includes(n.label.slice(0, 40).toLowerCase())).sort((a, b) => b.label.length - a.label.length)[0];
          eyeTask = { kind: x.kind, until: tick + 260, n: at, sys: x.system }; if (at) { at.flash = 70; sparks.push({ n: at, t: 0 }); } if (growTo) { const a = agentOf(x.kind); a.n = at || pickNode(x.kind); a.work = 260; } } }
        sysOf[x.kind] = x.system; // its eyes act out what just ran
        seen[x.kind] = l ? l.at : ""; out.push(row);
      }
    }
    steps.replaceChildren(...out);
  }
  let polls = 0; const engPoll = setInterval(() => { if (!root.isConnected) return clearInterval(engPoll); engines(); if (++polls % 3 === 0) refresh(); }, 4000); // refresh too, so waking up, the halo and a detached model show without you doing anything
  async function refresh() {
    watch(); meshLoad();
    let d; try { d = await api("/char/wiring"); } catch { return; }
    if (d.who !== formOf) { formOf = d.who; form = null; cb = 0; api("/char/chibi").then((c) => { if (formOf === d.who) form = c; }).catch(() => {}); } // a new persona: Dot starts as a sphere and morphs once its reference is in
    who.textContent = d.who; vars = d.signals.map((s) => ({ name: s.name, value: Math.round(s.value * 100) / 100 }));
    lamps.querySelectorAll("span").forEach((l) => l.classList.toggle("off", !d.systems.find((s) => s.id === +l.dataset.s)?.on));
    modes.replaceChildren(...[["sleeping", "Sleep", "No replies, no learning: safe to swap models"], ["quiet", "Quiet", "Never learns by itself"], ["curious", "Curious", "Learns while idle"], ["proactive", "Proactive", "Learns, and tells you what it found"]].map(([m, t, tip]) =>
      h("button", { type: "button", role: "radio", "aria-checked": String(d.mode === m), title: tip, onclick: async () => { try { await api("/char/wiring", { method: "POST", body: JSON.stringify({ mode: m }) }); } catch { return; } refresh(); } }, t)));
    root.dataset.mode = d.mode; const T = d.tracker || {}; learning = !!T.asleep; modeChip.textContent = T.asleep ? "learning · commands only" : `${T.asking ? "asking" : d.mode} · ${{ sleeping: "chat off", quiet: "chat only", curious: "chat + learns", proactive: "chat + learns + tells", planner: "chat + plans" }[d.mode] || "chat on"}`; // which mode, and whether you can talk to it
    modeChip.style.setProperty("--p", String(Math.min(1, (T.momentum || 0) / (T.sleep_at || 3)))); modeChip.dataset.halo = T.asleep ? "asleep" : T.asking ? "asking" : "";
    modeChip.title = `${MODE_DOES[d.mode] || ""} Momentum ${T.momentum ?? 0} of ${T.sleep_at ?? 3}: ${T.ups ?? 0} ups said; every ${T.every ?? 10} add 1. ${T.asleep ? "Asleep, learning the way you told it to grow; it wakes when the push is spent." : "At the threshold it asks which way to grow, then sleeps to learn it."}`;
    paintTrack(T); if (ear) ear.placeholder = d.mode === "sleeping" ? `${d.who.split(" ")[0]} is asleep · chat off. Type /wake, or / for commands` : learning ? `${d.who.split(" ")[0]} is learning · chat paused. Type / for commands` : `Talk to ${d.who.split(" ")[0]}…`;
    engines();
    const braked = d.wires[0]?.holding; // one line that says what you can do right now
    const q = d.review?.open; asking = q || null; // the correction loop, as talk: it says what went wrong, and your next message is the answer
    hint.replaceChildren(detached ? "The model isn't running: Dot is powered down until it's back. Commands still work." : q?.kind === "direction" ? h("span", {}, "It asks which way to grow. Your next message sets it. ", h("button", { type: "button", class: "sw-skip", onclick: skipAsk }, "Skip"))
      : T.asleep ? "Asleep: it is learning the way you told it to grow, and wakes when the push is spent."
      : q ? h("span", {}, "Your next message teaches it what to do instead. ", h("button", { type: "button", class: "sw-skip", onclick: skipAsk }, "Skip")) : d.mode === "sleeping" ? "Asleep: it will not answer or learn. Type /wake, or wake it on Controls." : d.mode === "quiet" ? "Quiet mode: it only answers. Start typing to talk to it."
      : braked ? "It has nothing new to chase. Tell it about something and its curiosity wakes up."
      : "It is learning by itself. Watch, or just start typing to talk to it.");
    if (q && ear) ear.placeholder = q.kind === "direction" ? "Which way should it grow?" : "Tell it what to do instead…";
    if (q && asked !== q.id) { asked = q.id; if (q.kind === "direction") return; /* its reply already asked */ const why = q.why.charAt(0).toUpperCase() + q.why.slice(1); say({ text: `You asked “${q.asked.slice(0, 90)}” and I said “${q.said.slice(0, 120)}”. ${why}. What should I do instead?` }); }
  }
  let asking = null, asked = null;
  async function skipAsk() { try { await api("/char/correction", { method: "DELETE" }); } catch { /* the next poll shows it again */ } asking = null; refresh(); }

  function openNote(n) { // a click on a node: what it is, the Verifier's word on it, and everything it is wired to
    pinned = n; // its neighbourhood stays lit while the card is open
    const close = h("button", { type: "button", class: "sw-x", "aria-label": "Close details", onclick: () => { note.hidden = true; cv.focus(); } }, "✕");
    const i = nodes.indexOf(n), near = edges.filter((e) => e.includes(i)).map((e) => nodes[e[0] === i ? e[1] : e[0]]);
    const STATE = { verified: "verified by the Verifier", rejected: "rejected by the Verifier", unchecked: "not checked yet", answered: "answered by a note", open: "not answered yet", dropped: "dropped", known: "read about", curious: "not read about yet: it is curious", ok: "reread by the Verifier: fine", mistake: "reread by the Verifier: a mistake" };
    note.replaceChildren(close, h("small", {}, `${LY[n.layer].t}${n.kind && n.layer !== "name" ? ` · ${n.kind}` : ""}${n.state ? ` · ${STATE[n.state] || n.state}` : ""}`),
      h("h3", {}, n.layer === "chat" ? (n.kind === "you" ? "You said" : "It said") : n.label), h("p", {}, n.body || (n.n ? `In ${n.n} note${n.n === 1 ? "" : "s"}.` : "")),
      ...(near.length ? [h("small", {}, "Wired to"), h("ul", { class: "sw-wired" }, ...near.slice(0, 14).map((x) => h("li", {}, h("button", { type: "button", style: `--c:${colour(x)}`, onclick: () => { x.flash = 70; openNote(x); } }, h("small", {}, LY[x.layer].t), " ", x.label.slice(0, 70)))))] : []));
    shut(); note.hidden = false; close.focus();
  }
  // Dot links the chat box to its box: a spark runs from it down the box's edge to the chat box, then dotted stitches join the two, right to left
  function linkUp() { if (!stageR || lay < .3) return; const ear = root.querySelector(".sp-ear"); if (!ear) return; const r = cv.getBoundingClientRect(), q = ear.getBoundingClientRect(), y0 = q.top - r.top, by = stageR[1] + stageR[3], p = cl((lay - .55) / .4);
    if (p <= 0 || y0 <= by) return; g.save(); g.globalCompositeOperation = "lighter";
    for (let k = 0; k < 6; k++) { const sx = stageR[0] + stageR[2] * (1 - (k + .5) / 6), kp = ease(cl(p * 1.8 - k * .14)); for (let y = by + 3; y < by + 3 + (y0 - by - 3) * kp; y += 3) { g.globalAlpha = .7 * lay; g.fillStyle = WAVE_C[k % 4]; g.fillRect(sx - 1, y - 1, 2, 2); } }
    if (p < 1 && lastDot) { const P2 = [[lastDot[0], lastDot[1]], [stageR[0] + stageR[2], by], [q.right - r.left - 10, y0]], s2 = ease(p) * 2, a = P2[s2 < 1 ? 0 : 1], b = P2[s2 < 1 ? 1 : 2], t2 = s2 % 1 || (s2 >= 2 ? 1 : 0);
      for (let j = 0; j < 8; j++) { const tt = cl(t2 - j * .03); g.globalAlpha = (1 - j / 8) * lay; g.fillStyle = SIG; const d = 3.4 - j * .35; g.fillRect(a[0] + (b[0] - a[0]) * tt - d / 2, a[1] + (b[1] - a[1]) * tt - d / 2, d, d); } }
    g.restore(); }
  // while you pick a command, the space beside the list plays a tiny film of what it does: the mind steps back, a small Dot acts it out in dots,
  // and a numbered caption says each beat in words, so it reads on its own
  const BEATS = { "/report": ["The 3D mind…", "…folds flat into a report", "Cycles · fixes · engine runs"], "/scene": ["The flat report…", "…rises back into the 3D mind"],
    "/expand-to-net": ["Dot sits small in the middle", "It swells out to the base ring", "Holding the whole net inside"], "/step": ["The Verifier picks an engine", "One learning step runs", "Its row lights up"],
    "/mind": ["Open its memory", "Every note and question", "And the prompts it sent"], "/wiring": ["Its systems: S0 · S1 · S2 · V", "Wired to your rules", "And its own corrections"],
    "/sleep": ["Its eyes close", "No replies · no learning", "Safe to swap models"], "/wake": ["Its eyes open", "It answers you again", "And learns while you're idle"],
    "/quiet": ["It only answers you", "It never learns by itself"], "/curious": ["While you are idle…", "…it explores by itself"], "/proactive": ["It explores by itself", "And tells you what it found"],
    "/learn": ["Learn mode: off", "Learn mode: on"], "/steer": ["Open the steer studio", "Set which way it grows"], "/verse": ["Step out of this mind…", "…into every persona round the model"] };
  let preview = null;
  function showWhat() { if (!preview || lay < .3 || !BEATS[preview.name]) return;
    const B = BEATS[preview.name], nb = B.length, LEN = 120 * nb, o = P(0, 0, 0), r = Math.max(70, RS * 1.1 * o.s), X = o.x, Y = o.y, f = tick - preview.t0, u = still ? .999 : (f % LEN) / LEN, b = Math.min(nb - 1, u * nb | 0), bu = still ? 1 : (u * nb) % 1, A = Math.min(1, f / 20) * lay, e = ease, L = (p, a, c) => a + (c - a) * p;
    g.save(); g.globalAlpha = .82 * A; g.fillStyle = "#000"; g.beginPath(); g.arc(X, Y, r * 1.18, 0, 6.283); g.fill(); // the mind steps back
    const dt = (x, y, c, al = 1, d = 2.2) => { g.globalAlpha = A * al; g.fillStyle = c; g.fillRect(x - d / 2, y - d / 2, d, d); };
    const ring = (x, y, rr, c, al = 1, n = 64, d = 2) => { for (let i = 0; i < n; i++) { const t2 = i / n * 6.283; dt(x + Math.cos(t2) * rr, y + Math.sin(t2) * rr, c, al, d); } };
    const box = (x, y, w, h2, c, al = 1) => { for (let i = 0; i <= w; i += 4) { dt(x + i, y, c, al); dt(x + i, y + h2, c, al); } for (let i = 0; i <= h2; i += 4) { dt(x, y + i, c, al); dt(x + w, y + i, c, al); } };
    const txt = (s2, x, y, c = "#fff", al = 1, size = 10) => { g.globalAlpha = A * al; g.fillStyle = c; g.font = `${size}px ui-monospace, monospace`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(s2, x, y); g.textBaseline = "alphabetic"; };
    const face = (x, y, s2, open = 1) => { ring(x, y, s2, tint, .9, 40, 2); for (const sx of [-1, 1]) { g.globalAlpha = A; g.fillStyle = "#fff"; g.beginPath(); g.ellipse(x + sx * s2 * .32, y, s2 * .13, Math.max(1, s2 * .26 * open), 0, 0, 6.283); g.fill(); } }; // a small Dot
    const bub = (x, y, w, h2, c, al = 1, tailRight = false) => { box(x - w / 2, y - h2 / 2, w, h2, c, al); for (let i = 0; i < 4; i++) dt(x + (tailRight ? w / 2 - 6 + i * 2 : -w / 2 + 6 - i * 2), y + h2 / 2 + 3 + i * 2, c, al); }; // a speech bubble
    const spark = (x0, y0, x1, y1, p, c) => { for (let j = 0; j < 7; j++) { const pp = cl(p - j * .03); dt(L(pp, x0, x1), L(pp, y0, y1) - Math.sin(pp * Math.PI) * 12, c, 1 - j / 7, 3.2 - j * .3); } };
    const nodesAt = [[-.55, -.35], [.5, -.45], [.62, .2], [-.4, .5], [.15, .62], [-.68, .12]].map(([a, c]) => [X + a * r * .85, Y + c * r * .85]);
    const sq = (x, y, c, al = 1, s2 = 4) => box(x - s2, y - s2, s2 * 2, s2 * 2, c, al);
    const rectPt = (t, x0, y0, w, h2) => { const per = 2 * (w + h2); let d = t * per; if (d < w) return [x0 + d, y0]; d -= w; if (d < h2) return [x0 + w, y0 + d]; d -= h2; if (d < w) return [x0 + w - d, y0 + h2]; d -= w; return [x0, y0 + h2 - d]; };
    g.globalCompositeOperation = "lighter";
    switch (preview.name) {
      case "/report": case "/scene": { const toPage = preview.name === "/report", m0 = toPage ? (b === 0 ? 0 : b === 1 ? e(bu) : 1) : (b === 0 ? 1 : 1 - e(bu)), w = r * 1.1, h2 = r * 1.25, x0 = X - w / 2, y0 = Y - h2 / 2;
        for (let i = 0; i < 90; i++) { const t2 = i / 90, [px2, py2] = rectPt(t2, x0, y0, w, h2), a2 = t2 * 6.283 - Math.PI * .75; dt(L(m0, X + Math.cos(a2) * r * .7, px2), L(m0, Y + Math.sin(a2) * r * .7, py2), m0 > .5 ? "#fff" : WAVE_C[i % 4], .8); }
        if (m0 < .5) nodesAt.slice(0, 5).forEach(([x, y], i) => sq(L(.45, X, x), L(.45, Y, y), WAVE_C[i % 4], 1 - m0 * 2));
        if (m0 > .5) [["CYCLES", SIG], ["FIXES", "#7dffa8"], ["ENGINE RUNS", "#6ff7ff"]].forEach(([t3, c], j) => { const ry = y0 + 22 + j * h2 * .3; txt(t3, X, ry, c, (m0 - .5) * 2, 9); for (let x = 0; x < (w - 30) * e(cl((m0 - .5) * 2 - j * .1)); x += 4) dt(x0 + 15 + x, ry + 12, "#fff", .45); });
        break; }
      case "/expand-to-net": { const R2 = b === 0 ? r * .2 : b === 1 ? L(e(bu), r * .2, r) : r; ring(X, Y, R2, tint, .9, 120, 2.4); face(X, Y, r * .16, 1);
        nodesAt.forEach(([x, y], i) => { const inside = Math.hypot(x - X, y - Y) < R2 - 6; sq(x, y, WAVE_C[i % 4], inside ? 1 : .3, inside && b === 2 ? 5 : 4); }); break; }
      case "/step": { const E2 = [0, 1, 2, 3].map((k) => [X + (k - 1.5) * r * .48, Y - r * .4, k]), pick = (f / LEN | 0) % 3, at2 = b === 0 ? Math.min(3, bu * 7 | 0) % 4 : pick, ry = Y + r * .35;
        E2.forEach(([x, y, k]) => { box(x - 16, y - 11, 32, 22, SYSC[k], k === at2 ? 1 : .4); txt(["S0", "S1", "S2", "V"][k], x, y, SYSC[k], k === at2 ? 1 : .5); });
        const [cx3, cy3] = E2[at2]; box(cx3 - 21, cy3 - 16, 42, 32, SIG, .9); // the Verifier's pick
        if (b >= 1) spark(cx3, cy3 + 14, X, ry, b === 1 ? e(bu) : 1, SIG);
        for (let x = 0; x < r * 1.2; x += 4) dt(X - r * .6 + x, ry, b === 2 ? SIG : "#fff", b === 2 ? .95 : .3); if (b === 2) txt("STEP DONE", X, ry + 16, SIG, e(bu), 9); break; }
      case "/mind": { box(X - r * .7, Y - r * .7, r * 1.4, r * 1.4, "#fff", .35); txt("MEMORY", X, Y - r * .7 - 10, "#fff", .7, 9);
        [["NOTE", "#6ff7ff"], ["NOTE", "#6ff7ff"], ["QUESTION", "#ffb347"], ["QUESTION", "#ffb347"], ["PROMPT", "#c79bff"], ["PROMPT", "#c79bff"]].forEach(([t3, c], j) => { const grp = j >> 1; if (grp > b) return; const p = grp < b ? 1 : e(cl(bu * 2 - (j & 1) * .3)), ry = Y - r * .5 + j * r * .2;
          sq(X - r * .55, ry, c, p, 3); txt(t3, X - r * .3, ry, c, p, 9); for (let x = 0; x < r * .6 * p; x += 4) dt(X - r * .05 + x, ry, "#fff", .4); }); break; }
      case "/wiring": { const S = [[X - r * .5, Y - r * .45, 0], [X + r * .5, Y - r * .45, 1], [X + r * .5, Y + r * .45, 2], [X - r * .5, Y + r * .45, 3]];
        S.forEach(([x, y, k]) => { box(x - 16, y - 11, 32, 22, SYSC[k], .9); txt(["S0", "S1", "S2", "V"][k], x, y, SYSC[k]); });
        const k2 = (u * 8 | 0) % 4, a2 = S[k2], c2 = S[(k2 + 1) % 4]; spark(a2[0], a2[1], c2[0], c2[1], (u * 8) % 1, "#fff");
        if (b >= 1) { box(X - 30, Y - 10, 60, 20, SIG, b === 1 ? e(bu) : 1); txt("YOUR RULES", X, Y, SIG, b === 1 ? e(bu) : 1, 8); S.forEach(([x, y]) => { for (let q = 0; q < 1; q += .08) dt(L(q, X, x), L(q, Y, y), SIG, .35); }); }
        if (b === 2) { spark(S[3][0], S[3][1], S[0][0], S[0][1], e(bu), "#7dffa8"); txt("FIX", (S[3][0] + S[0][0]) / 2 - 18, Y, "#7dffa8", e(bu), 9); } break; }
      case "/sleep": { const open = b === 0 ? 1 - e(bu) : 0; face(X, Y, r * .3, open);
        if (b >= 1) { const bx2 = X + r * .62, by2 = Y - r * .5; bub(bx2, by2, 44, 22, "#fff", .6); txt("hi?", bx2, by2, "#fff", .7); for (let i = -12; i <= 12; i += 2) { dt(bx2 + i, by2 + i * .6, BAD, .9 * (b === 1 ? e(bu) : 1)); dt(bx2 + i, by2 - i * .6, BAD, .9 * (b === 1 ? e(bu) : 1)); } }
        for (let z = 0; z < 3; z++) { const p = (u * 2 + z / 3) % 1, s2 = 5 + z * 2, zx = X + r * .3 + z * 10, zy = Y - r * .3 - p * r * .5; for (let i = 0; i <= s2; i += 2) { dt(zx + i, zy, "#9fb4ff", 1 - p); dt(zx + i, zy + s2, "#9fb4ff", 1 - p); dt(zx + s2 - i, zy + i, "#9fb4ff", 1 - p); } }
        if (b === 2) { box(X - r * .5, Y + r * .5, r, 20, "#fff", .5); txt("MODEL ⇄ MODEL", X, Y + r * .5 + 10, "#fff", e(bu), 9); } break; }
      case "/wake": { const open = b === 0 ? e(bu) : 1; face(X, Y, r * .3, open); if (b === 0) ring(X, Y, r * (.3 + bu * .6), SIG, 1 - bu, 64);
        if (b === 1) { bub(X + r * .62, Y - r * .55, 40, 20, "#fff", .7); txt("hi", X + r * .62, Y - r * .55, "#fff", .8); spark(X + r * .25, Y - r * .2, X + r * .55, Y - r * .45, e(bu), SIG); }
        if (b === 2) nodesAt.forEach(([x, y], i) => { spark(X, Y, x, y, e(cl(bu * 1.5 - i * .1)), WAVE_C[i % 4]); sq(x, y, WAVE_C[i % 4], .4 + .6 * cl(bu * 1.5 - i * .1 - .3)); }); break; }
      case "/quiet": { face(X, Y, r * .3, 1); nodesAt.forEach(([x, y]) => sq(x, y, "#fff", .25));
        if (b === 0) { const p = e(bu); bub(L(p, X + r * 1.1, X + r * .55), Y - r * .5, 40, 20, "#fff", .8); txt("you", L(p, X + r * 1.1, X + r * .55), Y - r * .5, "#fff", .8, 9); if (bu > .5) { bub(X - r * .55, Y - r * .55, 40, 20, tint, .9, true); txt("it", X - r * .55, Y - r * .55, tint, .9, 9); } }
        else { for (let y = -12; y <= 12; y += 3) { dt(X + r * .62 - 5, Y + r * .4 + y, "#fff", .9, 2.6); dt(X + r * .62 + 5, Y + r * .4 + y, "#fff", .9, 2.6); } txt("NO LEARNING", X, Y + r * .78, "#fff", .7, 9); } break; }
      case "/curious": case "/proactive": { const look = b === 0 && preview.name === "/curious"; face(X, Y, r * .25, 1);
        if (look) { txt("you: idle", X + r * .55, Y - r * .7, "#fff", .5, 9); nodesAt.forEach(([x, y], i) => sq(x, y, WAVE_C[i % 4], .3)); }
        else if (preview.name === "/curious" || b === 0) nodesAt.forEach(([x, y], i) => { const p = e(cl(bu * 1.6 - i * .12)); spark(X, Y, x, y, p, WAVE_C[i % 4]); sq(x, y, WAVE_C[i % 4], .3 + .7 * cl(p * 2 - 1)); });
        else { nodesAt.forEach(([x, y], i) => sq(x, y, WAVE_C[i % 4], 1)); const p = e(bu); bub(L(p, X + r * .3, X + r * .75), L(p, Y - r * .2, Y - r * .7), 70, 22, SIG, .9); txt("found: 3", L(p, X + r * .3, X + r * .75), L(p, Y - r * .2, Y - r * .7), SIG, .9, 9); } break; }
      case "/learn": { const on = b === 1, kx = on ? L(e(cl(bu * 3)), X - 20, X + 20) : L(e(cl(bu * 3)), X + 20, X - 20), c = on ? SIG : "#fff"; box(X - 38, Y - 15, 76, 30, c, .8); for (let a3 = 0; a3 < 6.283; a3 += .3) dt(kx + Math.cos(a3) * 9, Y + Math.sin(a3) * 9, c, 1, 2.6); txt(on ? "ON" : "OFF", X, Y + 32, c, .9, 10); break; }
      case "/steer": { box(X - r * .7, Y - r * .6, r * 1.4, r * 1.2, "#fff", .35); txt("STEER", X, Y - r * .6 - 10, "#fff", .7, 9); const t2 = b === 0 ? -Math.PI / 2 : -Math.PI / 2 + Math.sin(bu * 6.283) * 1.1;
        for (let s2 = 0; s2 < r * .5; s2 += 4) dt(X + Math.cos(t2) * s2, Y + Math.sin(t2) * s2 + r * .2, SIG, .9, 2.4); nodesAt.forEach(([x, y], i) => { const lit = b === 1 && Math.cos(Math.atan2(y - Y - r * .2, x - X) - t2) > .7; sq(x, y, WAVE_C[i % 4], lit ? 1 : .25); }); break; }
      case "/verse": { const z = b === 0 ? 1 : 1 - .65 * e(bu); ring(X, Y, r * .5 * z, tint, .9, 60); face(X, Y, r * .16 * z, 1);
        if (b === 1) for (let k = 0; k < 6; k++) { const t2 = k / 6 * 6.283 + u * 2, d2 = r * .75 * e(bu); ring(X + Math.cos(t2) * d2, Y + Math.sin(t2) * d2 * .7, r * .13, WAVE_C[k % 4], e(bu), 24); } break; }
    }
    g.globalCompositeOperation = "source-over";
    txt(`WHAT ${preview.name.toUpperCase()} DOES`, X, Y - r * 1.18 - 14, "#fff", .55, 10); // the caption: which beat this is, in words
    txt(`${b + 1} · ${B[b].toUpperCase()}`, X, Y + r * 1.18 + 16, b === nb - 1 ? SIG : "#fff", Math.min(1, bu * 5, (1 - bu) * 6 + .3), 12);
    for (let k = 0; k < nb; k++) dt(X + (k - (nb - 1) / 2) * 12, Y + r * 1.18 + 34, k === b ? SIG : "#fff", k === b ? 1 : .35, 4);
    g.restore(); }
  function palette(list, active = 0, pick) { // the commands, as Dot: it shrinks away and the list takes its place, with its eyes on top
    if (!list) { preview = null; if (!cmds.hidden) { cmds.hidden = true; if (bubble.hidden || bubble.classList.contains("out")) slab = null; } return; }
    const tip = h("p", { class: "sw-cmd-tip", "aria-live": "polite" }, list[active]?.does || "No command starts like that.");
    cmds.replaceChildren(h("span", { class: "sw-cmd-eyes", "aria-hidden": "true" }, h("i", {}), h("i", {})),
      ...list.map((c, i) => h("button", { type: "button", role: "option", "aria-selected": String(i === active), title: c.does,
        onmouseenter: () => { tip.textContent = c.does; if (preview?.name !== c.name) preview = { name: c.name, t0: tick }; }, onmouseleave: () => { tip.textContent = list[active]?.does || ""; },
        onmousedown: (e) => { e.preventDefault(); pick?.(c); } }, c.name)), tip);
    cmds.hidden = false; bubble.classList.add("out"); slab = { w: 1, h: 1 }; const nm = list[active]?.name; if (nm && preview?.name !== nm) preview = { name: nm, t0: tick };
  }
  // ---- things space.js tells it ----
  function say(t) { // the reply IS Dot: it pours out of its sphere into liquid letters, and its eyes play along the words; then it gathers back
    rings.push(0); happy = 0;
    const n = t.text.length, words = t.text.split(/(\s+)/), p = h("p", { style: `font-size:${n <= 60 ? 32 : n <= 150 ? 25 : n <= 320 ? 20 : 17}px` });
    words.forEach((w, i) => { if (/^\s+$/.test(w)) return p.append(w); const sp = h("span", {}, w); p.append(sp);
    });
    ink.replaceChildren(p, drop);
    chipsEl.replaceChildren(...(t.events || []).filter((e) => e.name).map((e) => h("span", { class: "rule" }, e.name)), ...(t.drew || []).slice(0, 4).map((x) => h("span", {}, x.title.replace(/^\w+: /, ""))));
    bubble.hidden = false; bubble.classList.remove("out"); slab = { w: ink.offsetWidth, h: p.offsetHeight }; wet = 1; px = slab.w / 2; py = -20; talk = Math.min(60 + words.length * 3, 300);
    hold = 0; const q0 = lay > .3 ? root.querySelector(".sp-ear")?.getBoundingClientRect() : null; // a follow-up: the words rise out of the attached chat box
    if (!still) p.querySelectorAll("span").forEach((sp, i) => { const r0 = sp.getBoundingClientRect(), dx = q0 ? q0.left + q0.width * (r0.left - p.getBoundingClientRect().left) / Math.max(1, p.offsetWidth) - r0.left : 0, dy = q0 ? q0.top + q0.height / 2 - r0.top : 18;
      sp.animate([{ opacity: 0, translate: `${dx}px ${dy}px`, scale: q0 ? ".4" : "1.3 .5" }, { opacity: 1, translate: "0 0", scale: "1 1" }], { duration: q0 ? 900 : 560, delay: 200 + Math.min(i * 30, 3200), easing: "cubic-bezier(.2,1.2,.4,1)", fill: "backwards" }); });
    clearTimeout(say.t); say.t = setTimeout(() => { bubble.classList.add("out"); slab = null; }, Math.max(11000, words.length * 400));
    refresh();
    return new Promise((r) => setTimeout(r, still ? 0 : Math.min(words.length * 30 + 900, 3600)));
  }
  function heard(text) { bubble.classList.add("out"); slab = null; clearTimeout(say.t); const staged = lay > .3, q = root.querySelector(".sp-ear")?.getBoundingClientRect(), r = cv.getBoundingClientRect();
    if (staged) hold = tick + 3600; // a follow-up: the stage stays up while it thinks, the box empty, Dot on its corner
    gulp.push({ text: text.length > 34 ? `${text.slice(0, 33)}…` : text, t: 0, from: staged && q ? [q.left - r.left + q.width / 2, q.top - r.top + q.height / 2] : null, to: staged && lastDot ? [...lastDot] : null }); } // your words rise from the box and Dot takes them in
  function fire(names) { for (const nm of names || []) { const n = nodes.find((x) => x.label === nm); if (n) { n.flash = 70; sparks.push({ n, t: 0 }); } } } // what a reply drew on lights up and sends a spark in
  function stepped(r) { busy = false; if (!r || r.done) return; lit = r.system; litT = 260; rings.push(0);
    const hit = nodes.filter((n) => n.kind !== "note" && `${r.topic} ${r.note}`.toLowerCase().includes(n.label.toLowerCase())).sort((a, b) => b.label.length - a.label.length).slice(0, 2);
    hit.forEach((n) => { n.flash = 70; sparks.push({ n, t: 0 }); }); if (r.kind === "reflect" || r.kind === "check") happy = 70; refresh(); }

  // ---- drawing ----
  function dot(mood, asleep) {
    morph += ((slab ? 1 : 0) - morph) * (still ? 1 : .08); const m = morph * morph * (3 - 2 * morph); // 1 = all of it has poured into the words
    const quiet = asleep || root.dataset.mode === "quiet", t = tick * (quiet ? .018 : .045), bob = still ? 0 : Math.sin(t * .7) * 5 * K, y = cy + bob, R = 82 * K * (1 - lay * .35) * (1 + grow * Math.max(0, (planes.chat || 260) / 82 - 1)), sq = 1 + Math.sin(t) * .03;
    rings = rings.map((r) => r + 2.4).filter((r) => r < 80); for (const r of rings) { g.strokeStyle = "#fff"; g.globalAlpha = (1 - r / 80) * (1 - m) * .6; g.lineWidth = 1; g.beginPath(); g.arc(cx, cy, 82 * K + r * K, 0, 6.283); g.stroke(); } g.globalAlpha = 1;
    cb += ((form && grow < .3 ? 1 : 0) - cb) * (still ? 1 : .03); const c = cb * cb * (3 - 2 * cb), sy = y - R * .3 * c, sr = R * (1 - .38 * c); // sphere -> chibi: the sphere rises and shrinks into its head
    g.strokeStyle = "#fff"; g.globalAlpha = (.12 + .06 * Math.sin(t)) * (1 - m) * (1 - grow); g.lineWidth = 1; g.beginPath(); g.arc(cx, y, R + 12 * K, 0, 6.283); g.stroke(); g.globalAlpha = 1; // a breathing hairline where the glow was
    const body = (asleep ? .6 : detached ? (form ? .9 : .38) : 1) * (1 - grow), fade = body * (1 - c);
    g.globalCompositeOperation = "lighter"; glow(cx, y, R * (2.3 + .15 * Math.sin(t * .8)), tint, .32 * body * (1 - m)); glow(cx, y, R * 1.1, "#ffffff", .08 * body * (1 - m)); g.globalCompositeOperation = "source-over"; // its aura, breathing in its colour
    g.strokeStyle = tint; g.lineWidth = 1;
    // the story's Dot: contour rings, the far half dim and the near half bright, inside the same wobbling, breathing outline the blob had
    const tilt = Math.max(.1, Math.abs(Math.sin(pitch))), near = pitch < 0 ? Math.PI : 0, wob = (a) => 1 + (still ? 0 : .022 * Math.sin(3 * a + t * 1.3) + .016 * Math.sin(5 * a - t * 1.7));
    for (let i = 1; i < 18; i++) { const v = -1 + i / 9, rr = sr * Math.sqrt(1 - v * v) * sq * wob(i), yy = sy + v * sr * Math.cos(pitch) / sq;
      for (const [a0, al] of [[near + Math.PI, .14], [near, .62]]) { g.globalAlpha = al * fade; g.beginPath(); g.ellipse(cx, yy, rr, rr * tilt, 0, a0, a0 + Math.PI); g.stroke(); } }
    g.globalAlpha = .4 * fade; g.beginPath();
    for (let a = 0; a <= 6.3; a += .12) { const r = sr * wob(a), qx = cx + Math.cos(a) * r * sq, qy = sy + Math.sin(a) * r / sq; a ? g.lineTo(qx, qy) : g.moveTo(qx, qy); }
    g.closePath(); g.stroke(); g.globalAlpha = 1;
    const F = form && c > .01 ? dotChibi(cx, y, R, c, t, body) : { x: cx, y, s: 1, ink: "#fff" }; // the character, as a cloud of dots in its own colours // where its eyes go: on the chibi's face once it has one
    if (grow > .55) return; // dissolved into the net: its jobs walk it now
    if (asleep && !still) { g.save(); g.globalCompositeOperation = "lighter"; for (let z = 0; z < 3; z++) { const p = (tick * .004 + z / 3) % 1, s2 = (5 + z * 2.5) * K, zx = F.x + 26 * K + z * 12 * K + Math.sin(p * 6) * 4, zy = F.y - 20 * K - p * 70 * K; g.globalAlpha = Math.sin(p * Math.PI) * .9; g.fillStyle = "#9fb4ff"; // asleep: Zs of dots drift up off it
      for (let i = 0; i <= s2; i += 2) { g.fillRect(zx + i, zy, 2, 2); g.fillRect(zx + i, zy + s2, 2, 2); g.fillRect(zx + s2 - i, zy + i, 2, 2); } } g.restore(); }
    let tx = Math.sin(yaw * 1.3) * 9, ty = mood === "think" || busy ? -9 : pitch * -8; if (ptr && !busy) { tx = Math.max(-13, Math.min(13, (ptr[0] - cx) * .08)); ty = Math.max(-10, Math.min(10, (ptr[1] - F.y) * .08)); }
    if (gaze) { tx = Math.max(-13, Math.min(13, (gaze[0] - F.x) * .06)); ty = Math.max(-10, Math.min(10, (gaze[1] - F.y) * .06)); } // on its trip: eyes on what it is weighing
    const task = eyeTask && tick < eyeTask.until && !still ? EYES[eyeTask.kind] : "", ph = tick - (eyeTask?.until ?? 0) + 260; let lid = 1;
    if (task === "read") { tx = -12 + (ph % 70) / 70 * 24; ty = 2 + (Math.floor(ph / 70) % 3) * 3; } // line by line, left to right
    else if (task === "search") { tx = Math.sin(ph * .09) * 13; ty = -9; } // up and scanning: out on the web
    else if (task === "think") { tx = Math.sin(ph * .025) * 6; ty = -11; } // eyes up, turning it over
    else if (task === "verify") { tx = Math.sin(ph * .04) * 4; lid = .42; } // a squint: checking its own work
    else if (task === "fold") { lid = .18 + .12 * Math.sin(ph * .05); } // heavy-lidded: folding what it knows together
    ex += (tx * K - ex) * .12; ey += (ty * K - ey) * .12; const wx = F.pic ? ex * .25 : ex, wy = F.pic ? ey * .25 : ey; if (tick > blinkAt + 7) blinkAt = tick + 90 + Math.random() * 220; // a picture's eyes are painted in place: they only glance
    lastDot = [F.x, F.y]; eyeHit = F.s > .2 ? [F.x, F.y, 21 * K * F.s + 16] : null; if (F.pic) return; // a picture has its own eyes: it shows how it feels with its body
    const ez = F.s, open = lid * (asleep ? .08 : quiet ? .45 : root.dataset.mode === "proactive" ? 1.12 : 1) * (tick > blinkAt ? .1 : 1), gap = 21 * K * ez; g.fillStyle = g.strokeStyle = F.ink;
    const off = detached && !F.pic && !form; if (off || learning || F.calm) { g.lineWidth = 1.6; g.lineCap = "round"; // detached: flat eyes, nothing behind them; learning: closed, dreaming, under a slow cyan orbit
      if (learning && !detached) { g.save(); g.strokeStyle = "#fff"; g.globalAlpha = .6; g.lineWidth = 1; g.setLineDash([3, 10]); g.lineDashOffset = still ? 0 : -tick * .4; g.beginPath(); g.arc(cx, y, R + 20 * K, 0, 6.283); g.stroke(); g.restore(); g.strokeStyle = F.ink; }
      for (const o of [-gap, gap]) { g.beginPath(); off ? (g.moveTo(F.x + o - 9 * K * ez, F.y), g.lineTo(F.x + o + 9 * K * ez, F.y)) : g.arc(F.x + o, F.y - 2 * K * ez, 10 * K * ez, .35, 2.79); g.stroke(); }
      return; }
    if ((happy > 0 || mood === "happy") && !asleep) { happy--; g.lineWidth = 1.6; g.lineCap = "round"; for (const o of [-gap, gap]) { g.beginPath(); g.arc(F.x + o + wx * ez, F.y + (6 * K + wy) * ez, 11 * K * ez, 3.5, 5.93); g.stroke(); } return; }
    if (F.pic && !immerse) { const h = Math.max(1, 15 * K * ez * open * (mood === "sad" ? .7 : 1)), w = 9 * K * ez; // a chibi's eyes: big, filled, with a pupil that looks where it looks and a glint
      for (const o of [-gap, gap]) { const x0 = F.x + o, px = x0 + ex * .35 * ez, py = F.y + ey * .3 * ez; g.fillStyle = "#fff"; g.beginPath(); g.ellipse(x0, F.y, w, h, 0, 0, 6.283); g.fill();
        if (h > 3) { g.save(); g.beginPath(); g.ellipse(x0, F.y, w, h, 0, 0, 6.283); g.clip(); g.fillStyle = "#14161c"; g.beginPath(); g.ellipse(px, py + h * .1, w * .62, Math.min(h * .78, w * 1.1), 0, 0, 6.283); g.fill();
          g.fillStyle = "#fff"; g.beginPath(); g.arc(px - w * .22, py - h * .28, w * .24, 0, 6.283); g.fill(); g.globalAlpha = .7; g.beginPath(); g.arc(px + w * .2, py + h * .25, w * .1, 0, 6.283); g.fill(); g.restore(); } }
      return; }
    g.lineWidth = 1.6; for (const o of [-gap, gap]) { g.beginPath(); g.ellipse(F.x + o + wx * ez, F.y + wy * ez, 9 * K * ez, Math.max(1, 17 * K * ez * open * (mood === "sad" ? .7 : 1)), 0, 0, 6.283); immerse ? g.fill() : g.stroke(); } // outline eyes, as in the story; filled when the dashboard is away
  }
  // the chibi as a 3D cloud of dots: drawn once off screen, its pixels sampled on a grid, each given a depth from how far it sits inside the
  // figure (so it has a front and a back), then turned with the view each frame; it keeps the outfit's colours and lights up in the working system's colour
  let cloud = null, cloudOf = null, cloudT = "", cloudTry = 0;
  // any form gets limbs: below the face, the outer dots of each row are arms (pivoting at the shoulders) and the bottom of the body is legs (pivoting at the hips),
  // each dot weighted softly so a limb bends out of the body rather than tearing off it
  function autoRig(pts, fv) {
    const sm = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
    let top = 1e9, bot = -1e9, uc = 0; pts.forEach((p) => { top = Math.min(top, p[1]); bot = Math.max(bot, p[1]); uc += p[0]; }); uc /= pts.length;
    const hip = bot - (bot - top) * .2, sh = fv + (bot - fv) * .32, row = {}, key = (v) => Math.round(v * 20);
    pts.forEach((p) => { const k = key(p[1]); row[k] = Math.max(row[k] || 0, Math.abs(p[0] - uc)); });
    const shW = row[key(sh)] || .5, hipW = row[key(hip)] || .5;
    // limbs by shape, not just height: each row below the shoulders splits into runs of dots with gaps between. The run at the middle is the body
    // (below the hips, the two runs either side of the middle are the legs); runs further out are arms, so a hand hanging past the hips stays an arm
    const G = .03, cu = Math.round(uc / G), rows = new Map(), lab = new Map();
    pts.forEach((p) => { const r = Math.round(p[1] / G); if (!rows.has(r)) rows.set(r, new Set()); rows.get(r).add(Math.round(p[0] / G)); });
    rows.forEach((cs, r) => { if (r * G < sh - .03) return; const runs = [];
      for (const c of [...cs].sort((a, b) => a - b)) { const l = runs[runs.length - 1]; if (l && c - l[1] <= 2) l[1] = c; else runs.push([c, c]); }
      const inR = runs.findIndex(([a, b]) => a <= cu && cu <= b); let L = -1, Rr = -1; runs.forEach(([a, b], j) => { if (b < cu) L = j; else if (a > cu && Rr < 0) Rr = j; });
      const core = inR >= 0 ? [inR] : [L, Rr].filter((j) => j >= 0), below = r * G > hip;
      runs.forEach(([a, b], j) => { const k = core.includes(j) ? (below ? -1 : 0) : (a + b) / 2 < cu ? 1 : 2; for (let c = a; c <= b; c++) lab.set(r * 1000 + c, k); }); });
    const id = new Int8Array(pts.length), w = new Float32Array(pts.length);
    pts.forEach((p, i) => { const du = p[0] - uc, side = du < 0 ? 0 : 1, k = lab.get(Math.round(p[1] / G) * 1000 + Math.round(p[0] / G));
      if (k === 1 || k === 2) { id[i] = k; w[i] = 1; } // an arm, apart from the body
      else if (k === -1) { if (Math.abs(du) > .06) { id[i] = 3 + side; w[i] = 1; } } // a leg
      else if (k === 0 && Math.abs(du) / (row[key(p[1])] || 1) > .62 && p[1] < hip + .03) { id[i] = 1 + side; w[i] = 1; } }); // an arm held close: the body's outer edge
    return { id, w, hip, bot, piv: [null, [uc - shW * .55, sh], [uc + shW * .55, sh], [uc - hipW * .45, hip], [uc + hipW * .45, hip]] };
  }
  function makeCloud() {
    const pic = !!form.silhouette, S = pic ? 330 : 180, OR = pic ? 82 : 44, ox = S / 2, oy = S * .56, oc = document.createElement("canvas"); oc.width = oc.height = S; const og = oc.getContext("2d", { willReadFrequently: true });
    const face = form.silhouette ? drawFlat(og, ox, oy, OR, form) : drawChibi(og, ox, oy, OR, form, tint, 1, 0, 1); if (!face) return null; // a picture keeps its own colours
    const px = og.getImageData(0, 0, S, S).data, A = (x, y) => x < 0 || y < 0 || x >= S || y >= S ? 0 : px[(y * S + x) * 4 + 3];
    const pts = [], step = 2; let fz = 0, fd = 1e9;
    let G = 1; if (pic) { let sum = 0, n = 0; for (let j = 3; j < px.length; j += 16) if (px[j] > 60) { sum += Math.max(px[j - 3], px[j - 2], px[j - 1]); n++; } G = Math.min(2.2, Math.max(1, 130 / (sum / Math.max(1, n)))); } // a dark picture is lit as a whole, so its darks stay darker than its lights
    for (let y = 0; y < S; y += step) for (let x = 0; x < S; x += step) { if (A(x, y) < 60) continue;
      const i = (y * S + x) * 4; let e = 0; while (e < 24 && A(x + e, y) > 60 && A(x - e, y) > 60 && A(x, y + e) > 60 && A(x, y - e) > 60) e += 2; // how deep inside the figure: its thickness there
      const lu = px[i] * .3 + px[i + 1] * .59 + px[i + 2] * .11, fl = pic ? Math.max(0, 70 - lu * G) : 0, rgb = [0, 1, 2].map((k) => Math.min(255, ((px[i + k] * G + 22 + fl * [.8, .85, 1.1][k]) / (pic ? 5 : 12) | 0) * (pic ? 5 : 12))), c = `rgb(${rgb})`, d = Math.sqrt(e / 24) * .55, sct = pic ? .75 : .9, u = (x - ox + (Math.random() - .5) * step * sct) / OR, v = (y - oy + (Math.random() - .5) * step * sct) / OR; // a little scatter, so it reads as a body of dots, not a printed screen
      const dc = (x2, y2) => { const j = (y2 * S + x2) * 4; return A(x2, y2) < 60 ? 999 : Math.abs(px[i] - px[j]) + Math.abs(px[i + 1] - px[j + 1]) + Math.abs(px[i + 2] - px[j + 2]); };
      let rim = e <= 2 || dc(x + step, y) > 70 || dc(x, y + step) > 70 ? 1 : 0; // the outline and where one part meets another (face plate, arms, legs)
      if (!pic && !rim && (x + y) % 4) continue; // every rim dot, so the shape reads; half the inside, so it stays airy
      const head = pic && y < face.y + face.s * OR * .256 * 2.8; if (head) rim = 1; // the head stays solid and whole: a face you can see through is no face
      if (pic && !rim && (x + y) % 4) continue; // a picture keeps every line and edge, and half its insides: a ghost of it, not a print
      { const q = Math.hypot(x - face.x, y - face.y); if (q < fd) { fd = q; fz = -d; } } // how far its face stands out front, so the eyes turn with it
      pts.push([u, v, -d, c, Math.random() * 6.283, rim, rgb]); if (d > .06 && (!pic || rim || (x + y) % 8 === 0)) pts.push([u, v, d, c, Math.random() * 6.283, 0, rgb]); } // a picture's back is barely seen: its outline and a sprinkle // its front and its back
    if (pic) { let n = 0; for (let y = 1; y < S - 1; y++) for (let x = 1; x < S - 1; x++) { if (A(x, y) < 60 || (A(x - 1, y) >= 60 && A(x + 1, y) >= 60 && A(x, y - 1) >= 60 && A(x, y + 1) >= 60)) continue; // its contour, pixel by pixel: a smooth edge, not a staircase
      const i = (y * S + x) * 4, lu = px[i] * .3 + px[i + 1] * .59 + px[i + 2] * .11, fl = Math.max(0, 70 - lu * G), rgb = [0, 1, 2].map((k) => Math.min(255, px[i + k] * G + 22 + fl * [.8, .85, 1.1][k] | 0)), u = (x - ox) / OR, v = (y - oy) / OR;
      pts.push([u, v, -.07, `rgb(${rgb})`, Math.random() * 6.283, 1, rgb]); if (n++ % 2) continue;
      for (const [z, k] of [[0, .68], [.07, .5]]) { const r2 = rgb.map((a) => a * k | 0); pts.push([u, v, z, `rgb(${r2})`, Math.random() * 6.283, 1, r2]); } } } // and a wall round it, shaded darker, so it has sides when it turns
    // the eyes you marked are their own fine grid of dots, a little bigger than in the picture (chibi eyes), from its own colours with a soft edge;
    // three anchor points ride along in the cloud (its centre, one to its right, one above) so they move, turn and tilt with the face
    const eyeImg = pic && face.eyes ? face.eyes.map((e, j) => { const R2 = Math.ceil(e.r * 1.25), n = R2 * 2;
      const im = og.getImageData(Math.round(e.x) - R2, Math.round(e.y) - R2, n, n), d = im.data;
      for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) { const q = Math.hypot(x - R2 + .5, y - R2 + .5) / R2, o = (y * n + x) * 4; for (let k = 0; k < 3; k++) d[o + k] = Math.max(0, Math.min(255, (d[o + k] * G - 128) * 1.25 + 142)); d[o + 3] *= Math.max(0, Math.min(1, (1 - q) / .3)); }
      [[0, 0], [1, 0], [0, -1]].forEach(([a, b], m) => pts.push([(e.x + a * e.r - ox) / OR, (e.y + b * e.r - oy) / OR, fz - .03, "#000", 0, 2, [0, 0, 0], j * 3 + m]));
      const cols = []; for (let o = 0; o < d.length; o += 4) cols.push(`rgb(${d[o]},${d[o + 1]},${d[o + 2]})`); return { d, n, R2, r: e.r, cols }; }) : null;
    const rig = pts.length > 20 ? autoRig(pts, (face.y - oy) / OR) : null;
    const eyes = face.eyes ? face.eyes.map((e) => [(e.x - ox) / OR, (e.y - oy) / OR, e.r / OR]) : null; // marked eyes, in the body's own units
    return pts.length > 20 ? { pts, pic, rig, eyes, eyeImg, face: [(face.x - ox) / OR, (face.y - oy) / OR, face.s, fz] } : null;
  }
  // the chibi lives the loop, as a little film: it LOOKS round the mesh (a scan line and its eyes pass over a few nodes), DECIDES (the line locks on one),
  // MEDITATES (it shrinks into a mini chibi, eyes closed, breathing, and nearby nodes condense into data dots that fly into it: its sense of the data),
  // TRAVELS as the mini chibi, LANDS on the chosen node with a little bounce (the rest of the mesh steps back), WORKS there, comes home,
  // and POPS back to full size with a silly overshoot and wobble; the nodes it took from grow back after
  let immerse = false, eyeHit = null, boxE = 0, lastBox = null; const setImmerse = (v) => { immerse = v; root.classList.toggle("sw-immerse", v); };
  let trip = null, nextTrip = 300, built = -1e9, gaze = null, tripF = -1;
  const ease = (p) => p <= 0 ? 0 : p >= 1 ? 1 : p < .5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2, TSYS = { plan: 2, question: 1, note: 0, name: 3 }, cl = (p) => Math.max(0, Math.min(1, p));
  const LOOK = 80, DEC = 50, MED = 180, GO = 110, LAND = 45, WORK = 270, BACK = 110, POP = 100, SM = .34;
  // at a node it acts its job out in three beats, its eyes on the node: it sizes it up, does the thing, and leaves its mark on it
  const SCRIPT = { check: [["reading it", "tapping it", "checked"], "check"], ask: [["looking at it", "wondering", "asked"], "ask"], plan: [["tying it in", "pulling it tight", "planned"], "check"], find: [["looking it up", "digging in", "found it"], "bang"] };
  const ROLE = { checking: "check", reading: "check", asking: "ask", thinking: "ask", planning: "plan", folding: "plan", "looking up": "find", searching: "find" };
  const GLYPH = { check: ["....#", "...#.", "#.#..", ".#..."], ask: [".###.", "#...#", "..##.", "..#..", ".....", "..#.."], bang: ["..#..", "..#..", "..#..", ".....", "..#.."] };
  let workTilt = 0;
  const T1 = LOOK, T2 = T1 + DEC, T3 = T2 + MED, T4 = T3 + GO, T5 = T4 + LAND, T6 = T5 + WORK, T7 = T6 + BACK, T8 = T7 + POP;
  function plan(n, x, y, sys, verb) { const vis = (m, i) => m !== n && !hide.has(m.layer) && m.layer !== "chat" && proj[i] && proj[i].z < 0;
    const near = nodes.map((m, i) => vis(m, i) ? [m, Math.hypot(proj[i].x - x, proj[i].y - y)] : null).filter((p) => p && p[1] > 50).sort((p, q) => p[1] - q[1]); // what it takes in while it meditates: the nodes nearest it
    const wp = near.slice(0, 3).map((p) => p[0]), decoys = near.slice(3).sort(() => Math.random() - .5).slice(0, 3).map((p) => p[0]);
    return { n, sys, verb, t0: tick, wp, ate: 0, bits: [], look: [...decoys, ...wp].sort(() => Math.random() - .5) }; }
  const MORPH = 130; // frames a change of form takes
  const bod = { l: 0, lv: 0, s: 0, sv: 0, h: 0, hv: 0 }; let prevC = null, roamT = 0;
  const spring = (o, k, to, pull, damp) => { o[k + "v"] = (o[k + "v"] + (to - o[k]) * pull) * damp; o[k] += o[k + "v"]; }; // overshoots a little, then settles
  function workScene(role, beat, wb, wf, q, tc) {
    const dotAt = (x, y, a, d = 2.4) => { g.globalAlpha = a; g.fillRect(x - d / 2, y - d / 2, d, d); }, bx = 15 * K + 6; g.fillStyle = tc;
    if (beat === 0) { const a = ease(cl(wb * 4)) * (1 - ease(cl((wb - .85) * 7)));
      if (role === "check") { const yy = q.y - bx + ((wb * 2.2) % 1) * bx * 2; for (let i = -6; i <= 6; i++) dotAt(q.x + i * bx / 6, yy, a * (1 - Math.abs(i) / 9)); } // a scan line reads down it, twice
      else if (role === "find") { const an = wb * 9, lx = q.x + Math.cos(an) * bx * .8, ly = q.y + Math.sin(an) * bx * .5; g.strokeStyle = tc; g.lineWidth = 1.4; g.globalAlpha = a; g.beginPath(); g.arc(lx, ly, 7 * K + 3, 0, 6.283); g.moveTo(lx + 5 * K + 2, ly + 5 * K + 2); g.lineTo(lx + 10 * K + 4, ly + 10 * K + 4); g.stroke(); } // a lens goes over it
      else if (role === "ask") for (let i = 0; i < 3; i++) dotAt(q.x - bx * .6 + i * bx * .6, q.y - bx - 6 - Math.abs(Math.sin(wf * .12 + i)) * 5, a, 3); // it looks it over: three dots bob above it
      else { const near = (trip.near ||= nodes.map((m, i) => [m, proj[i]]).filter(([m, p]) => m !== trip.n && p).sort((A, B) => Math.hypot(A[1].x - q.x, A[1].y - q.y) - Math.hypot(B[1].x - q.x, B[1].y - q.y)).slice(0, 3).map(([m]) => m));
        near.forEach((m, j) => { const p = proj[nodes.indexOf(m)]; if (!p) return; const e = ease(cl(wb * 2.2 - j * .35)); for (let s2 = 0; s2 <= 14 * e; s2++) dotAt(q.x + (p.x - q.x) * s2 / 14, q.y + (p.y - q.y) * s2 / 14, a * .8); }); } } // dotted threads out to its neighbours
    if (beat === 1 && role === "plan" && trip.near) trip.near.forEach((m) => { const p = proj[nodes.indexOf(m)]; if (!p) return; const pull = Math.sin(wb * Math.PI * 4) * 3; for (let s2 = 0; s2 <= 14; s2++) dotAt(q.x + (p.x - q.x) * s2 / 14, q.y + (p.y - q.y) * s2 / 14 + Math.sin(s2 / 14 * Math.PI) * pull, .7); }); // pulled tight, twanging
    if (beat === 1 && role === "ask") { const a = ease(cl(wb * 3)); GLYPH.ask.forEach((r, j) => [...r].forEach((ch, i) => ch === "#" && dotAt(q.x + 26 * K + (i - 2) * 3.4, q.y - 44 * K - 10 + j * 3.4 - wb * 8, a * .7, 2.6))); } // a question forms over its head
    if (beat === 2) { const p = cl(wb * 2.5), s = 1 - Math.cos(p * 9) * Math.exp(-p * 5), G = GLYPH[SCRIPT[role][1]], a = 1 - ease(cl((wb - .8) * 5)), u = 3.6 * s; // its mark pops onto the node
      G.forEach((r, j) => [...r].forEach((ch, i) => ch === "#" && dotAt(q.x + 34 * K + 10 + (i - 2) * u, q.y - 30 * K - (G.length - j) * u, a, 2.8 * Math.max(.3, s)))); } // beside it, where its body doesn't hide it
    g.globalAlpha = 1;
  }
  // /follow-me: the mind gathers into Dot and fades back; Dot swallows the chat box, bends its dots out into a long new one, and follows your cursor
  // with it. While you move it unravels into rings round your cursor; when you stop it steps back out beside it, its box hanging under it.
  const SWALLOW = 80, MADE = 160; // frames: the box goes in, the new one is drawn, it's live
  addEventListener("pointermove", (e) => { const r = cv.getBoundingClientRect(), m = [e.clientX - r.left, e.clientY - r.top, performance.now()]; if (mouse) mouseV = mouseV * .7 + Math.hypot(m[0] - mouse[0], m[1] - mouse[1]) * .3;
    if (fol && !fol.out && fp && mouse && tick - fol.t0 > MADE && Math.hypot(m[0] - fp[0], m[1] - fp[1] + folR * .3) < folR * 1.5) { const dx = m[0] - mouse[0], dir = Math.abs(dx) > 2 ? Math.sign(dx) : 0; // patting: strokes back and forth over it
      if (dir && dir !== patDir) { patDir = dir; pats = pats.filter((q) => m[2] - q < 1200); pats.push(m[2]); if (pats.length > 1) hearts.push({ x: fp[0] + (Math.random() - .5) * folR, y: fp[1] - folR * 1.4, t: tick }); bod.sv -= .05;
        if (pats.length >= 5) { pats = []; happy = 80; bod.sv -= .1; if (boxT == null) { boxT = tick; boxIdle = 0; } } } }
    mouse = m; });
  function follow(on) { const ear = root.querySelector(".sp-ear");
    if (on && !fol?.out && fol) return; if (!on && !fol) return;
    if (on) { if (ear) { ear.style.transform = ""; ear.style.width = ""; earOn = false; const q = ear.getBoundingClientRect(), r = cv.getBoundingClientRect(); earNat = [q.left - r.left, q.top - r.top, q.width, q.height]; }
      fol = { t0: tick }; fp = fp || [bcx, cy]; bp = [fp[0], fp[1] + 120]; root.classList.add("sw-following"); trip = null; boxT = null; earA = 0; status.textContent = "Following you. Double-tap or pat it to talk; /end-follow-me sends it home."; }
    else { fol.out = true; fol.t0 = tick; status.textContent = "Going home."; } }
  addEventListener("keydown", (e) => { if (!fol || fol.out || tick - fol.t0 < MADE) return; if (e.key === "Escape") { follow(false); return; }
    if (e.key.length !== 1 || e.metaKey || e.ctrlKey || e.altKey) return; boxIdle = 0; if (boxT == null) { boxT = tick - 60; happy = 40; } const inp = root.querySelector(".sp-ear input"); if (inp && document.activeElement !== inp) inp.focus(); }, true); // first, before the page's own typing handler
  let taps = []; // double or triple tap on it: it's the same as patting it
  addEventListener("pointerdown", (e) => { if (!fol || fol.out || !fp || tick - fol.t0 < MADE || ballE > .3) return; const r = cv.getBoundingClientRect(), m = [e.clientX - r.left, e.clientY - r.top]; // rings round your cursor: you're grabbing the mind, not tapping it
    if (Math.hypot(m[0] - fp[0], m[1] - fp[1] + folR * .3) > folR * 1.5) return; const now = performance.now(); taps = taps.filter((q) => now - q < 500); taps.push(now); bod.sv -= .08;
    hearts.push({ x: fp[0], y: fp[1] - folR * 1.4, t: tick }); if (taps.length >= 2) { taps = []; happy = 80; if (boxT == null) { boxT = tick; boxIdle = 0; } } });
  function follower(mood, asleep) {
    const ear = root.querySelector(".sp-ear"), t = fol ? tick - fol.t0 : 999, on = fol && !fol.out, home = [bcx, cy], live = on && t > MADE;
    folE += ((on ? 1 : 0) - folE) * (still ? 1 : .035);
    gat += ((on && t < MADE + 30 ? 1 : 0) - gat) * (still ? 1 : on && t < MADE + 30 ? .035 : .025); // it gathers the mind in to swallow the box, then lets it back out so you can look round it
    g.globalAlpha = .8 * gat; g.fillStyle = "#000"; g.fillRect(0, 0, W, H); g.globalAlpha = 1;
    const Rm = folR = 82 * bK * (1 - .45 * folE), over = live && mouse && Math.hypot(mouse[0] - fp[0], mouse[1] - fp[1] + Rm * .3) < Rm * 1.5; // your cursor on it: it holds still to be patted
    const moving = live && !over && mouse && performance.now() - mouse[2] < 160 && mouseV > 2;
    ballE += ((moving ? 1 : 0) - ballE) * (still ? 1 : moving ? .14 : .05);
    const rest = mouse ? performance.now() - mouse[2] : 1e9, spin = moving ? .09 : rest < 1800 ? .05 * (1 - rest / 1800) : 0; orbA += still ? 0 : spin;
    const orR = moving ? 45 : rest < 1800 ? 95 * (1 - rest / 2400) : 0, beside = [mouse ? mouse[0] + Rm * 1.6 + 10 : 0, mouse ? mouse[1] - Rm * 1.2 : 0], set = cl((rest - 1200) / 600);
    const tgt = !live || !mouse ? (on ? fp.slice() : home) : over ? fp.slice() : [mouse[0] + Math.cos(orbA) * orR + (beside[0] - mouse[0]) * set, mouse[1] + Math.sin(orbA) * orR * .7 + (beside[1] - mouse[1]) * set]; // it chases you round your cursor, then settles beside it
    if (!on && !fol) tgt.splice(0, 2, ...home);
    if (still || !live) { fp[0] += (tgt[0] - fp[0]) * (still ? 1 : .11); fp[1] += (tgt[1] - fp[1]) * (still ? 1 : .11); fv[0] = fv[1] = 0; }
    else { for (const k of [0, 1]) { fv[k] = (fv[k] + (tgt[k] - fp[k]) * .028) * .88; fp[k] += fv[k]; } } // a spring with momentum: it overshoots and swings back, like something chasing you
    fp[0] = Math.max(Rm, Math.min(W - Rm, fp[0])); fp[1] = Math.max(Rm * 1.6 + 50, Math.min(H - Rm * 1.15 - 96, fp[1]));
    const bw = Math.min(360, W - 40), bt = [Math.max(bw / 2 + 10, Math.min(W - bw / 2 - 10, fp[0])), fp[1] + Rm * 1.15 + 48]; // its box hangs under it, trailing a little
    bp[0] += (bt[0] - bp[0]) * (still ? 1 : .07); bp[1] += (bt[1] - bp[1]) * (still ? 1 : .07);
    const perim = (x0, y0, w, h, u) => { const L = 2 * (w + h); let d = u * L; if (d < w) return [x0 + d, y0]; d -= w; if (d < h) return [x0 + w, y0 + d]; d -= h; if (d < w) return [x0 + w - d, y0 + h]; d -= w; return [x0, y0 + h - d]; };
    g.fillStyle = tint; g.globalCompositeOperation = "lighter";
    if (on && t > SWALLOW - 10 && t < MADE && earNat) { const f = (t - SWALLOW + 10) / (MADE - SWALLOW); // the old box comes apart into dots and they're sucked into its mouth
      for (let j = 0; j < 90; j++) { const p = ease(cl(f * 1.5 - j / 90 * .5)), [sx, sy] = perim(earNat[0], earNat[1], earNat[2], earNat[3], j / 90), w2 = Math.sin(p * Math.PI) * 30;
        g.globalAlpha = (1 - p * p) * .9; const d = 2.4 * (1 - p * .6); g.fillRect(sx + (fp[0] - sx) * p + Math.sin(j + p * 9) * w2 * .3 - d / 2, sy + (fp[1] - sy) * p - w2 - d / 2, d, d); }
      if (t === MADE - 20) { bod.sv -= .12; happy = 30; } } // gulp
    // patted: it bends its dots out of its mouth, along curves, into a long box under it; left alone a while with nothing typed, it takes the box back in
    const typing = ear && (ear.contains(document.activeElement) || ear.querySelector("input")?.value);
    if (boxT != null && tick - boxT > 120 && !typing && ++boxIdle > 480) { boxT = null; boxIdle = 0; } if (typing) boxIdle = 0; if (live && boxT == null && ear?.querySelector("input")?.value) { boxT = tick - 60; happy = 40; } // you started typing: the box comes out to take it
    if (live && boxT != null && tick - boxT < 130) { const f = (tick - boxT) / 90, bx = bt[0] - bw / 2, by = bt[1] - 20;
      for (let j = 0; j < 140; j++) { const p = ease(cl(f * 1.6 - j / 140 * .6)), [ex2, ey2] = perim(bx, by, bw, 40, j / 140), side = j % 2 ? 1 : -1, mx2 = (fp[0] + ex2) / 2 + side * 60 * Math.sin(j * .3), my2 = (fp[1] + ey2) / 2 + 30;
        const qx = (1 - p) * (1 - p) * fp[0] + 2 * (1 - p) * p * mx2 + p * p * ex2, qy = (1 - p) * (1 - p) * fp[1] + 2 * (1 - p) * p * my2 + p * p * ey2;
        g.globalAlpha = p > .02 ? Math.min(1, (130 - (tick - boxT)) / 40) : 0; g.fillRect(qx - 1.2, qy - 1.2, 2.4, 2.4); } }
    if (live && earA > .03) { const bx = bp[0] - bw / 2, by = bp[1] - 20, n = 150; g.fillStyle = tint; // its box, drawn in its own dots: a soft ripple runs round it, and a thread of dots ties it to its feet
      for (let j = 0; j < n; j++) { const [qx, qy] = perim(bx, by, bw, 40, j / n), w2 = Math.sin(j / n * 6.283 * 3 - tick * .06); g.globalAlpha = earA * (.45 + .4 * w2); const d = 2 + .6 * w2; g.fillRect(qx - d / 2, qy - d / 2 + (still ? 0 : w2 * .8), d, d); }
      const fx = fp[0], fy = fp[1] + Rm * 1.05, tx = bp[0], ty = by; for (let j = 0; j <= 10; j++) { const u = j / 10, qx = fx + (tx - fx) * u + Math.sin(u * Math.PI) * 10 * Math.sin(tick * .05), qy = fy + (ty - fy) * u; g.globalAlpha = earA * (.35 + .5 * Math.abs(Math.sin(u * 5 - tick * .1))); g.fillRect(qx - 1.2, qy - 1.2, 2.4, 2.4); } }
    hearts = hearts.filter((h2) => tick - h2.t < 70); g.fillStyle = "#ff8fb1"; // pats come back as little dotted hearts
    for (const h2 of hearts) { const u = (tick - h2.t) / 70; g.globalAlpha = Math.sin(u * Math.PI); [".#.#.", "#####", ".###.", "..#.."].forEach((r, jj) => [...r].forEach((ch, ii) => ch === "#" && g.fillRect(h2.x + (ii - 2) * 3 + Math.sin(u * 6 + h2.x) * 4, h2.y - u * 50 + jj * 3, 2.4, 2.4))); }
    g.globalCompositeOperation = "source-over"; g.globalAlpha = 1;
    if (live) { g.globalAlpha = (boxT == null ? .75 : Math.max(0, 1 - (tick - boxT) / 40)) * Math.min(1, (t - MADE) / 30); g.font = "10px ui-monospace, monospace"; g.letterSpacing = "1.6px"; g.textAlign = "center"; g.fillStyle = SIG;
      g.fillText(boxT == null ? "FOLLOWING YOU · TYPE OR TAP ME TWICE · ESC SENDS ME HOME" : "FOLLOWING YOU", fp[0], fp[1] - Rm * 1.9 - 10); g.letterSpacing = "0px"; g.globalAlpha = 1; }
    // the chat box: swallowed; out again only once you've patted it; home again at the end
    if (ear && earNat) { const ec = [earNat[0] + earNat[2] / 2, earNat[1] + earNat[3] / 2];
      if (on && t < SWALLOW) { ear.style.opacity = ""; }
      else if (on && t < MADE) { const s2 = ease(cl((t - SWALLOW) / 60)); ear.style.transform = `translate(${(fp[0] - ec[0]) * s2}px, ${(fp[1] - ec[1]) * s2}px) scale(${1 - .95 * s2})`; ear.style.opacity = String(1 - s2); ear.style.pointerEvents = "none"; }
      else if (on) { const shown = boxT != null && tick - boxT > 80; ear.style.width = `${bw}px`; ear.style.transform = `translate(${bp[0] - ec[0]}px, ${bp[1] - ec[1]}px)`; earA += ((shown ? 1 : 0) - earA) * .12; ear.style.opacity = String(earA); ear.style.pointerEvents = shown ? "" : "none"; }
      else { ear.style.width = ""; ear.style.transform = ""; ear.style.pointerEvents = ""; ear.style.opacity = String(cl((t - 20) / 40)); } }
    if (!on && folE < .01) { fol = null; folE = 0; gat = 0; ballE = 0; boxT = null; earA = 0; root.classList.remove("sw-following"); if (ear) { ear.style.opacity = ""; ear.style.transform = ""; ear.style.width = ""; ear.style.pointerEvents = ""; } status.textContent = ""; }
    const c0 = cx, y0 = cy, K0 = K; cx = fp[0]; cy = fp[1]; K = bK * (1 - .45 * folE); dot(mood, asleep); cx = c0; cy = y0; K = K0; // Dot itself, smaller, wherever it is
    if (!on) { fp[0] += (home[0] - fp[0]) * .06; fp[1] += (home[1] - fp[1]) * .06; } }
  // its own moves: they work on the cloud of dots itself, so they fit any form it wears
  const BEAT = .034; // the one tempo it lives at: a breath every ~3 s; sway, bob and dance are multiples of it
  const EMO = { hop: [70, "HOP"], spin: [90, "WHEE"], shiver: [60, "BRRR"], poof: [110, "POOF"], bow: [90, "HELLO"], sit: [360, "SIT"], cute: [360, "✦ ♪ ✦"] };
  const emote = (k) => { const ks = Object.keys(EMO); emo = { k: k || ks[Math.random() * ks.length | 0], t0: tick }; };
  function dotChibi(x, y, R, k, t, alpha) {
    const zg = Math.min(1.5, Math.sqrt(Math.max(1, zoom))); R *= zg / Math.max(1, zoom); // zooming in opens up the mind around it; Dot itself grows only a little, to 1.5x at most
    if (zt > 1.7 && !zoomSaid) { zoomSaid = true; want = "bow"; } else if (zt < 1.3) zoomSaid = false; // you came in close: it waves hello
    if ((cloudOf !== form || cloudT !== tint) && tick > cloudTry) { const nc = makeCloud(); cloudTry = tick + 60; if (nc) { if (cloud) { nc.from = cloud; nc.from.from = null; nc.t0 = tick; built = Math.min(built, tick - 400); } else built = tick; cloud = nc; cloudOf = form; cloudT = tint; } } // a new form: the old one's dots flow into it // a poured picture may still be loading: try again in a second
    gaze = null; if (!cloud) return { x, y, s: 1, ink: "#fff" };
    // it lives in the mind, not on a stand: between trips it wanders through it in 3D, nearer and further, turning to face where it goes
    if (!trip && !still && lay < .01) roamT++;
    { const a = roamT * .0019, w = (1 - ease(cl(lay * 3))) * (1 - folE), r = RS * .4, p0 = P(0, 0, 0), p1 = P(Math.sin(a) * r, Math.sin(a * 1.3 + 2) * RS * .12, Math.sin(a * 1.7 + 1) * r * .8);
      x += (p1.x - p0.x) * w; y += (p1.y - p0.y) * w; R *= 1 + (p1.s / p0.s - 1) * w; }
    if (fol) trip = null;
    if (want && !still && lay < .01 && !ballE) { trip = null; emo = null; emote(want); want = null; nextEmo = tick + 600; } // asked for by a command: once the reply has gone
    if (!emo && !trip && !still && lay < .01 && !ballE && tick > nextEmo) { emote(); nextEmo = tick + 260 + Math.random() * 300; } // now and then, when nothing else is going on
    // ONE motion system: every move rides one tempo (b, the breath) and one envelope (env: eases in, holds, eases out), so it starts and ends at rest;
    // a move cut short (a trip, lying down) doesn't snap off: it fades out over a third of a second (fo)
    const b = tick * BEAT;
    if (emo && !emo.out && (trip || lay > .05)) emo.out = tick; const fo = emo?.out ? 1 - cl((tick - emo.out) / 20) : 1;
    let ep = emo ? (tick - emo.t0) / EMO[emo.k][0] : 0; if (emo && (ep >= 1 || fo <= 0)) { emo = null; ep = 0; } const ek = emo?.k, env = emo ? ease(cl(ep / .12)) * (1 - ease(cl((ep - .86) / .14))) * fo : 0;
    if (!still && ek === "hop" && tick - emo.t0 === 1) bod.sv -= .12; if (!still && ek === "hop" && tick - emo.t0 === 52) bod.sv -= .16; // crouch before, squash on landing
    if (!trip && !emo && !fol && !still && !detached && lay < .01 && nodes.length && tick - built > 160) { const T = eyeTask && tick < eyeTask.until ? eyeTask.n : null;
      if (T && !hide.has(T.layer) && proj[nodes.indexOf(T)]) trip = plan(T, x, y, eyeTask.sys, VERB_OF[EYES[eyeTask.kind]] || eyeTask.kind);
      else if (tick > nextTrip && !["quiet", "sleeping"].includes(root.dataset.mode) && !root.classList.contains("asleep")) {
        const pool = nodes.filter((n, i) => TSYS[n.layer] != null && !hide.has(n.layer) && proj[i] && proj[i].z < 0);
        if (pool.length) { const n = pool[Math.random() * pool.length | 0]; trip = plan(n, x, y, TSYS[n.layer], { plan: "planning", question: "asking", note: "checking", name: "looking up" }[n.layer]); }
        nextTrip = tick + 1400 + Math.random() * 900; } }
    if (trip && !nodes.includes(trip.n)) { const by = (m) => nodes.find((o) => o.id === m.id); trip.n = by(trip.n) || trip.n; trip.wp = trip.wp.map(by).filter(Boolean); trip.ate = Math.min(trip.ate, trip.wp.length); trip.bits = []; } // the mesh reloaded mid-trip: find its nodes again
    let f = trip ? tick - trip.t0 : 0; const tq = trip ? proj[nodes.indexOf(trip.n)] : null;
    if (trip && (!tq || f > T8)) { trip = null; f = 0; nextTrip = Math.max(nextTrip, tick + 700); }
    tripF = trip ? f : -1;
    const ax = tq ? tq.x : x, ay = tq ? tq.y - 26 * K : y, tc = trip && SYSC[trip.sys] || workCol;
    const TURN = cloud?.pic ? .12 : .3, ang = Math.max(-TURN, Math.min(TURN, bod.h * .35 + (still ? 0 : Math.sin(tick * .009) * .1) + (ek === "cute" ? Math.sin(b * 2 + 1.57) * .3 * env : 0))) + (ek === "spin" && !cloud?.pic ? ease(Math.min(1, ep + 1 - fo)) * 6.283 : 0), ca = Math.cos(ang), sa = Math.sin(ang), sc = R * (.4 + .6 * k), asm = (tick - built) / 200, N = nodes.length;
    const ph = !trip ? "home" : f < T1 ? "look" : f < T2 ? "decide" : f < T3 ? "med" : f < T4 ? "go" : f < T5 ? "land" : f < T6 ? "work" : f < T7 ? "back" : "pop";
    const fm = (f - T2) / MED, fg = (f - T3) / GO, fl = (f - T4) / LAND, fb = (f - T6) / BACK, fp = (f - T7) / POP;
    const sit = (1 - SM) * R * .45, hx = x, hy = y + sit; // the mini chibi sits a little lower than the big one stood
    const BT = WORK / 3, wf = f - T5, beat = ph === "work" ? Math.min(2, wf / BT | 0) : -1, wb = ph === "work" ? (wf - beat * BT) / BT : 0, role = trip ? ROLE[trip.verb] || "check" : "check";
    const hop = beat === 1 && role !== "ask" ? Math.abs(Math.sin(wb * Math.PI * 2)) * 10 * K : beat === 2 ? Math.sin(cl(wb * 3) * Math.PI) * 6 * K : 0; // two taps on it; a little jump when it's done
    let tiltT = beat === 1 && role === "ask" ? .2 * Math.sin(wb * Math.PI) : 0; // a head tilt while it wonders (a target: the tilt springs toward it)
    if (beat === 0 || beat === 1) gaze = [tq.x, tq.y]; if (beat === 2 && wb > .1) happy = Math.max(happy, 2);
    const nod = ph === "decide" ? Math.sin(cl((f - T1) / DEC) * Math.PI) * 5 * K : 0;
    // where its body is and how big, per frame of the film (sx, sy differ only for the squash and the pop)
    const shrink = ph === "med" ? ease(cl(fm * 3)) : 1, float = ph === "med" ? Math.sin(f * .045) * 3 * K * shrink : 0;
    const along = (p, a0, b0, a1, b1) => [a0 + (a1 - a0) * p, b0 + (b1 - b0) * p - Math.sin(p * Math.PI) * 30 * K]; // a soft arc between two places
    const elastic = (p) => 1 - Math.cos(p * 9) * Math.exp(-p * 5), wob = ph === "pop" ? .2 * Math.sin(fp * 16) * Math.exp(-fp * 4) : ph === "land" ? .14 * Math.sin(fl * Math.PI * 3) * (1 - fl) : 0;
    const body = (p) => ph === "med" ? [x, y + (hy - y) * shrink + float, 1 + (SM - 1) * shrink] : ph === "go" ? [...along(p, hx, hy, ax, ay), SM] : ph === "land" ? [ax, ay - Math.abs(Math.sin(fl * Math.PI * 2)) * Math.exp(-fl * 3) * 8 * K, SM]
      : ph === "work" ? [ax, ay - hop, SM] : ph === "back" ? [...along(p, ax, ay, hx, hy), SM] : ph === "pop" ? [x, hy + (y - hy) * cl(elastic(fp)), SM + (1 - SM) * elastic(fp)] : [x, y + nod, 1];
    const C = body(ph === "go" ? ease(fg) : ph === "back" ? ease(fb) : 0).slice(); if (ek === "hop") C[1] -= Math.max(0, Math.sin(cl((ep - .1) / .65) * Math.PI)) * 34 * K * fo;
    { const md = root.dataset.mood || (busy ? "think" : ""); for (const [q, m] of [["h", "happy"], ["s", "sad"], ["t", "think"], ["k", "talk"], ["w", "wow"], ["i", "wink"]]) xp[q] += ((md === m && !emo && !trip ? 1 : 0) - xp[q]) * (still ? 1 : .06); }
    if (cloud.pic && !still) { C[1] -= (Math.abs(Math.sin(b * 2)) * 5 * xp.h + Math.abs(Math.sin(b * 4)) * 2.5 * xp.k + 7 * xp.w) * K; tiltT += .12 * xp.t + .1 * xp.i; } // happy bounces; talking bobs as it speaks; surprised jumps up a little; thinking and winking tilt the head
    const dance = ek === "cute" ? env : 0; // dancing: the body stays whole and its own dots swarm over it on the beat
    if (ek === "cute" && !still) { C[1] -= Math.abs(Math.sin(b * 4)) * 6 * K * dance; C[0] += Math.sin(b * 2) * 5 * K * dance; happy = Math.max(happy, 2); } // a bob on every beat, a sway every two, on the same tempo as its breath
    // sitting: it settles down, looks about, then gets up (a drawn form folds its legs and swings its feet; a picture just sinks and rests)
    const DOWN = 40, UP = EMO.sit[0] - 40; let sitE = 0, sf = -1;
    if (ek === "sit") { const f = sf = tick - emo.t0;
      sitE = (f < UP ? ease(cl(f / DOWN)) : 1 - ease(cl((f - UP) / 25))) * fo;
      if (!still && f === DOWN) bod.sv -= .08; if (!still && f === UP + 22) bod.sv += .1;
      if (f > DOWN && f < UP) { tiltT += .1 * Math.sin(b * .5) * sitE; gaze = [C[0] + Math.sin(b * .25) * 200, C[1] + 40]; } happy = Math.max(happy, f > DOWN ? 1 : 0);
      if (cloud.pic) C[1] += sitE * 26 * K; }
    if (ek === "spin" && cloud.pic) { tiltT += Math.sin(ep * Math.PI * 6) * .22 * env; C[1] -= Math.abs(Math.sin(ep * Math.PI * 3)) * 10 * K * env; } // a picture can't spin round: it twirls on the spot instead, rocking side to side with little hops
    workTilt = still ? tiltT : workTilt + (tiltT - workTilt) * .1; // one tilt, sprung, whoever asked for it
    // meditating: the nodes nearest it condense and send their data dots into it, one after another
    if (ph === "med") trip.wp.forEach((m, j) => { if (j >= trip.ate && fm >= .3 + j * .18) { trip.ate = j + 1; m.eat = 1; m.flash = 40;
      for (let b = 0; b < 22; b++) trip.bits.push({ n: m, t0: tick + b * 2, c: colour(m), a: Math.random() * 6.283, r: 4 + Math.random() * 10 }); } });
    if (ph === "look" || ph === "decide") { const L = trip.look, q = ph === "look" && L.length ? proj[nodes.indexOf(L[Math.min(L.length - 1, f / (LOOK / L.length) | 0)])] : tq, lock = ph === "decide" ? ease(cl((f - T1) / 30)) : 0;
      if (q) { const per = LOOK / Math.max(1, L.length), fl2 = ph === "look" ? Math.sin(((f % per) / per) * Math.PI) : 1, c = ph === "look" ? "#ffffff" : tc;
        g.save(); g.strokeStyle = c; g.globalAlpha = (ph === "look" ? .28 : .35 + .5 * lock) * fl2; g.lineWidth = ph === "look" ? 1 : 1.4; g.setLineDash(ph === "look" ? [2, 5] : [6, 5]); g.lineDashOffset = -tick * .6;
        g.beginPath(); g.moveTo(x, y); g.lineTo(q.x, q.y); g.stroke(); g.setLineDash([]);
        const b = ph === "look" ? 11 : 26 - 14 * lock, e2 = 5; g.globalAlpha = (ph === "look" ? .6 : .95) * fl2; g.lineWidth = 1.4; g.beginPath(); // corner brackets on what it is looking at
        for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) { g.moveTo(q.x + sx * b, q.y + sy * (b - e2)); g.lineTo(q.x + sx * b, q.y + sy * b); g.lineTo(q.x + sx * (b - e2), q.y + sy * b); } g.stroke(); g.restore(); gaze = [q.x, q.y]; } }
    g.globalCompositeOperation = "lighter";
    if (ph === "med") { const w = Math.min(shrink, cl((1 - fm) * 6)); glow(C[0], C[1], 60 * K, tc, .25 * w); // its calm: breathing rings going out slowly round it
      for (let j = 0; j < 3; j++) { const u = ((f * .006 + j / 3) % 1); g.strokeStyle = tc; g.globalAlpha = w * .45 * (1 - u); g.lineWidth = 1; g.beginPath(); g.ellipse(C[0], C[1] + 6 * K, (14 + 46 * u) * K, (5 + 14 * u) * K, 0, 0, 6.283); g.stroke(); } }
    if (trip && (ph === "land" || ph === "work")) { const w = ph === "land" ? ease(fl) : ease(cl((T6 - f) / 40)); glow(tq.x, tq.y - 10 * K, 70 * K, tc, .22 * w); } // a spotlight on the node it sits on
    trip?.bits.forEach((b) => { const u = (tick - b.t0) / 55; if (u < 0 || u > 1) return; const q = proj[nodes.indexOf(b.n)]; if (!q) return; const e = ease(u), sx = q.x + Math.cos(b.a) * b.r * K, sy = q.y + Math.sin(b.a) * b.r * K; // data dots, flying into it
      g.globalAlpha = .25 + .75 * Math.sin(u * Math.PI); g.fillStyle = b.c; const d = 2.8 - 1.2 * e; g.fillRect(sx + (C[0] - sx) * e - d / 2, sy + (C[1] - sy) * e - Math.sin(e * Math.PI) * 14 * K - d / 2, d, d); });
    if (trip) trip.bits = trip.bits.filter((b) => tick - b.t0 < 56);
    let mx = C[2] * (1 + wob), my = C[2] * (1 - wob);
    // it is a body, not a sticker: it breathes, sways from its feet, leans into where it is going and towards you, stretches as it flies,
    // and when it stops the lean and the stretch spring past and settle, so every move carries through it
    if (!still) { const vx = prevC ? (C[0] - prevC[0]) / sc : 0, vy = prevC ? (C[1] - prevC[1]) / sc : 0, sp = Math.hypot(vx, vy), pt = ptr && !trip ? Math.max(-1, Math.min(1, (ptr[0] - C[0]) / (W * .35))) : 0;
      spring(bod, "l", Math.max(-.32, Math.min(.32, vx * 12)) + pt * (cloud.pic ? 0 : .09), .07, .84); spring(bod, "h", Math.max(-.7, Math.min(.7, vx * 45)), .03, .9); spring(bod, "s", Math.min(.2, sp * 7) - (ph === "med" ? .04 : 0), .09, .8); }
    prevC = [C[0], C[1]];
    const br = still ? 0 : Math.sin(b), sway = still ? 0 : (Math.sin(b * .4) * .045 + Math.sin(b * .9 + 1) * .018) * (cloud.pic ? 1.6 : 1) + (ek === "shiver" ? Math.sin(tick * .5) * .05 * env : 0), rus = still ? 0 : cloud.pic ? .25 : 1;
    // a picture's head lives on its own: it tilts and turns a little toward your cursor, and now and then glances somewhere else, then springs back
    const nk = cloud.rig ? cloud.rig.piv[1][1] - .1 : -.6, nu = cloud.rig ? (cloud.rig.piv[1][0] + cloud.rig.piv[2][0]) / 2 : 0;
    if (!still && cloud.pic) { if (tick > hd.next) { const q = Math.random() < .3; hd.ga = q ? 0 : (Math.random() - .5) * .34; hd.gu = q ? 0 : (Math.random() - .5) * .16; hd.next = tick + 100 + Math.random() * 240; }
      const pt = ptr && !trip ? Math.max(-1, Math.min(1, (ptr[0] - C[0]) / (W * .35))) : 0, ta = hd.ga + .12 * pt + .05 * Math.sin(b * .55) + workTilt * .6, tu = hd.gu + .07 * pt;
      hd.av = (hd.av + (ta - hd.a) * .045) * .8; hd.a += hd.av; hd.uv = (hd.uv + (tu - hd.u) * .045) * .8; hd.u += hd.uv; }
    const bend = (u, v, phs) => { const hh = Math.max(0, Math.min(1, (1.05 - v) / 2.8)), sy = (1 + bod.s) * (1 + (cloud.pic ? .04 : .022) * br * hh), sx = (1 - bod.s * .45) * (1 - .012 * br);
      if (cloud.pic && v < nk + .08) { const w = Math.min(1, (nk + .08 - v) / .18), a = hd.a * w, du = u - nu, dv = v - nk, co = Math.cos(a), si = Math.sin(a); u = nu + du * co * (1 - Math.abs(hd.u) * w * .5) - dv * si + hd.u * w; v = nk + du * si + dv * co; } // the head turns on its neck; the body under it stays put
      return [u * sx + (sway + bod.l + workTilt) * hh * hh + rus * .012 * hh * Math.sin(v * 7 - tick * .07 + phs), 1.05 + (v - 1.05) * sy]; }; // the top moves most; a ripple runs up it like wind through leaves or breath through a chest
    const mo = cloud.from && tick - cloud.t0 < MORPH + 60 ? cloud.from.pts : null, mN = mo ? mo.length / cloud.pts.length : 0, mf = mo ? (tick - cloud.t0) / MORPH : 1; if (cloud.from && !mo) cloud.from = null;
    if (cloud.pic) g.globalCompositeOperation = "source-over"; // a picture keeps its true colours: overlapping dots don't add up to white
    const em2 = emo ? Math.sin(ep * Math.PI) * fo : 0;
    gait += ((still || emo ? 0 : Math.min(1, Math.hypot(bod.l, bod.s) * 4 + (ph === "go" || ph === "back" ? 1 : 0))) - gait) * .08;
    const lim = [0, 0, 0, 0, 0], tk = tick; if (!still && cloud.rig && !cloud.pic) { gph += .06 + .12 * gait; const st = Math.sin(gph); // the step's phase moves on steadily; its speed may change, its place never jumps // arms (1 left, 2 right) and legs (3, 4): positive swings outward
      lim[1] = .1 + .06 * Math.sin(tk * .045) + .25 * gait * st; lim[2] = .1 + .06 * Math.sin(tk * .045 + 2) - .25 * gait * st; lim[3] = (.04 + .22 * gait) * Math.max(0, st); lim[4] = (.04 + .22 * gait) * Math.max(0, -st);
      if (ph === "work") { lim[2] = 1.1 + .35 * Math.sin(tk * .3); } // it reaches out to the node it works on
      if (ph === "pop" || (ph === "land" && fl > .5)) { lim[1] = lim[2] = 1.4; } // ta-da
      if (ek) { const bb = Math.sin(b * 4), base = lim.slice();
        if (ek === "cute") { const w = Math.sin(b * 2); lim[1] = .35 + .55 * Math.max(0, w); lim[2] = .35 + .55 * Math.max(0, -w); lim[3] = .12 * Math.max(0, -bb); lim[4] = .12 * Math.max(0, bb); } // it sways from side to side, each arm lifting as it leans that way, little steps on the beat
        else if (ek === "sit") { lim[1] = lim[2] = .3 + .1 * sitE; const sw = sf > DOWN + 10 && sf < UP ? .2 + .2 * Math.sin(b * 2.6) : 0; lim[3] = (.15 + sw) * sitE; lim[4] = (.15 + (sw ? .4 - sw : 0)) * sitE; } // its feet dangle and swing, one against the other
        else if (ek === "hop") { const air = Math.max(0, Math.sin(cl((ep - .1) / .65) * Math.PI)); lim[1] = lim[2] = .2 + 1.8 * air; lim[3] = lim[4] = .3 * air; }
        else if (ek === "spin") { lim[1] = lim[2] = 1.5 * em2; }
        else if (ek === "bow") { lim[2] = (2.1 + .3 * Math.sin(ep * Math.PI * 6)) * em2; } // HELLO: one hand up, waving
        else if (ek === "shiver") { lim[1] = lim[2] = -.25 * em2 + .06 * Math.sin(tk * .5); lim[3] = lim[4] = -.1 * em2; } // hugging itself
        for (let j = 1; j < 5; j++) lim[j] = base[j] + (lim[j] - base[j]) * env; } } // a move eases out of, and back into, how it was standing
    for (let j = 1; j < 5; j++) { if (still) { limA[j] = limB[j] = lim[j]; continue; } // limbs have weight: the upper part springs toward where it's going, overshoots a touch and settles; the forearm trails it
      limV[j] = (limV[j] + (lim[j] - limA[j]) * .08) * .8; limA[j] += limV[j]; limBV[j] = (limBV[j] + (limA[j] - limB[j]) * .06) * .8; limB[j] += limBV[j]; }
    const rig = cloud.rig, flip = [0, 1, -1, 1, -1];
    const pose = (u, v, z, phs) => { // what a move does to the body; its eyes go through it too, so they stay on its face
      if (xp.s > .01 || xp.w > .01) { const hh = cl((1.05 - v) / 2.8); v += hh * hh * .14 * xp.s; u *= 1 - .05 * xp.s * hh; v = 1.05 + (v - 1.05) * (1 + .07 * xp.w); } // sad: head and shoulders sink; surprised: it draws itself up
      if (ek === "poof") { const b = Math.sin(cl(ep * 1.4) * Math.PI) * fo * 1.3 * (.6 + .4 * Math.sin(phs * 3)); u += Math.cos(phs) * b; v += Math.sin(phs * 1.7) * b * .8; z += Math.sin(phs) * b; } // bursts into a cloud of dots, then pulls back together
      else if (ek === "sit" && cloud.pic) { v = 1.05 + (v - 1.05) * (1 - .12 * sitE); u *= 1 + .05 * sitE; } // a picture settles: it sinks, squats a little lower and wider, nothing bends
      else if (ek === "sit" && rig) { const L = rig.bot - rig.hip, dn = sitE * L * .45; // its top stays whole and upright and just comes down; its legs fold forward toward you, so from the front they look short and splayed
        if (v < rig.hip) v += dn; else { const k = (v - rig.hip) / L; v = rig.hip + dn + (v - rig.hip) * (1 - .5 * sitE); z -= k * .5 * sitE; } }
      else if (ek === "bow") { const hh = cl((1.05 - v) / 2.8); if (cloud.pic) v += hh * hh * em2 * .12; else { v += hh * hh * em2 * .55; z -= hh * em2 * .7; } } // its top bends toward you; a picture nods
      return [u, v, z]; };
    const uc0 = rig ? (rig.piv[1][0] + rig.piv[2][0]) / 2 : 0;
    if (cloud.pic && !still) glow(C[0], C[1] + .2 * sc, sc * 1.5, tint, .1 * alpha * k); // a faint light it stands in
    let lastFs = null;
    // marked eyes close the way eyes do: lids slide over them. No dot moves; the dots a lid covers take the skin's colour, and its edge is a lash line in the eye's own dark
    const EY = cloud.eyes; if (EY && !cloud.eyeCol) cloud.eyeCol = EY.map(([eu, ev, r]) => { let sk = [0, 0, 0], n = 0, dk = null, dl = 999; // the skin just below the eye; the eye's darkest colour
      for (const p of cloud.pts) { if (p[5] === 2) continue; const du = p[0] - eu, dv = p[1] - ev, l = p[6][0] * .3 + p[6][1] * .59 + p[6][2] * .11;
        if (Math.abs(du) < r * .8 && dv > r * 1.15 && dv < r * 1.7) { sk = sk.map((a, k) => a + p[6][k]); n++; }
        if (du * du + dv * dv < r * r && l < dl) { dl = l; dk = p[6]; } }
      return [n ? `rgb(${sk.map((a) => a / n | 0)})` : "rgb(230,200,190)", dk ? `rgb(${dk.map((a) => a * .7 | 0)})` : "rgb(30,20,30)"]; });
    const bk = tick - blinkAt, blink = bk < 0 || bk > 7 ? 0 : bk < 2 ? bk / 2 : bk < 4 ? 1 : 1 - (bk - 4) / 3; // shut fast, hold a beat, open a little slower
    const smile = Math.max(xp.h, ek === "cute" ? env : ek === "sit" ? sitE * env : 0);
    const lids = EY ? EY.map((_, j) => { const cu = Math.max(blink, j === 0 ? xp.i : 0), k = Math.max(cu, smile); return { k, arch: k > .001 ? cl(smile / k) * smile : 0, sad: .45 * xp.s }; }) : null;
    const eyeQ = [], eatC = trip && trip.ate ? trip.wp.map(colour) : null;
    cloud.pts.forEach(([u, v, z, c, phs, rim, rgb, ej], i) => {
      if (EY) for (let j = 0; j < 2; j++) { const [eu, ev, r] = EY[j], du = u - eu, dv = v - ev; if (du * du + dv * dv > r * r * 1.25) continue;
        const L = lids[j], q = Math.min(1, Math.abs(du) / r), meet = ev + .1 * r - .55 * r * (1 - q * q) * (L.arch > 0 ? L.arch / Math.max(L.k, .001) : 0); // where the lids meet: a line, or an arch when it smiles (^ ^)
        const top = ev - r + (meet - (ev - r)) * Math.max(L.k, L.sad), bot = ev + r + (meet - (ev + r)) * L.k, edge = r * .11;
        if (L.k > .03 || L.sad > .03) { if (v < top - edge || v > bot + edge) { c = cloud.eyeCol[j][0]; rim = 1; } else if (v < top + edge || (v > bot - edge && L.k > .03)) { c = cloud.eyeCol[j][1]; rim = 1; } } // lid, then its lash line
        break; }
      const li = rig && !cloud.pic ? rig.id[i] : 0; if (li && (limA[li] || limB[li])) { const [pu, pv] = rig.piv[li], du = u - pu, dv = v - pv, rr = Math.hypot(du, dv), jt = Math.min(1, rr / .18), el = cl((rr - .2) / .22), fore = limB[li] + (li < 3 ? .35 * Math.abs(limA[li]) : 0); // the upper limb follows the shoulder; past the elbow it follows the trailing forearm, and a raised arm bends a little
        const a = ((limA[li] * (1 - el) + fore * el) * jt ) * rig.w[i] * flip[li], co = Math.cos(a), si = Math.sin(a);
        u = pu + du * co - dv * si; v = pv + du * si + dv * co; z -= Math.abs(a) * .15 * (li > 2 ? 1 : 0); } [u, v] = bend(u, v, phs);
      [u, v, z] = pose(u, v, z, phs);
      if (dance > .001) { const fa = b * 4 + u * 5 + v * 3.5, fb = b * 3 - u * 4 + v * 5, am = .045 * dance; u += Math.cos(fa) * am; v += Math.sin(fb) * am; z += Math.sin(fa) * am; } // dancing, its dots swarm: a flow that moves neighbours together, like a school of fish, rippling over its body on the beat while its outline holds
      if (mo) { const o = mo[i * mN | 0], p = ease(cl(mf * 1.5 - (v + 1.3) / 2.6 * .5)), sw = Math.sin(p * Math.PI); // top first, each dot from its place in the old form, swirling out a little on the way
        u = o[0] + (u - o[0]) * p + Math.sin(phs + p * 6) * sw * .18; v = o[1] + (v - o[1]) * p - sw * .1; z = o[2] + (z - o[2]) * p + Math.cos(phs + p * 6) * sw * .18;
        if (p < 1) c = `rgb(${o[6].map((a, k) => a + (rgb[k] - a) * p | 0)})`; rim = p > .5 ? rim : o[5]; }
      if (ballE > .01) { const p = ease(cl(ballE * 1.6 - (v + 1.3) / 2.6 * .6)), r = i % 4, a = (i * .618 % 1) * 6.283 + tick * (.04 + r * .012) * (r % 2 ? -1 : 1), tl = [.3, 1.1, 1.9, 2.6][r], rad = .85 + r * .16; // as you move, it unravels into three rings spinning round your cursor; at rest it comes back out, head first
        u += (Math.cos(a) * rad - u) * p; v += (Math.sin(a) * rad * Math.cos(tl) - v) * p; z += (Math.sin(a) * rad * Math.sin(tl) - z) * p; if (p > .5) { rim = 1; c = WAVE_C[r]; } } // each ring in one system's colour
      const X = u * ca + z * sa, Z = -u * sa + z * ca, jit = still || cloud.pic ? 0 : .008 * Math.sin(t * 1.2 + phs), s = 1 / (1 + Z * .35), del = Math.min(1, Math.max(0, (v + 1.3) / 2.6)) * .85 + phs / 6.283 * .15; // top first, like a ribbon
      const ox = (X + jit) * sc * s, oy = (v + jit * .6) * sc * s, B = ph === "go" ? body(ease(cl(fg * 1.25 - del * .25))) : ph === "back" ? body(ease(cl(fb * 1.25 - del * .25))) : C; // in flight the lower dots trail a little
      let qx = B[0] + ox * mx, qy = B[1] + oy * my;
      if (asm < 1.6 && N && !still) { const a = ease(asm * 1.4 - del * .4), src = proj[(i * 7919) % N]; if (src) { qx = src.x + (qx - src.x) * a; qy = src.y + (qy - src.y) * a; } } // born out of the mesh: each dot flies in from a node
      if (ej !== undefined) { eyeQ[ej] = [qx, qy]; return; } // an eye's anchor: where its cut-out goes
      const lit = (workE > .05 || ph === "work") && Math.sin(v * 5 - tick * .08 + phs * .2) > .6, eaten = eatC && i % 7 < trip.ate ? eatC[i % 7] : null; // a wave of the working colour runs through it; flecks of what it took in ride in it
      g.globalAlpha = alpha * k * (rim ? 1 : Z < 0 ? (cloud.pic ? .82 + .18 * folE : .55 + .3 * folE) : cloud.pic ? .1 : .22) * (still || cloud.pic ? 1 : .85 + .15 * Math.sin(t * 1.5 + phs)); { const fs = lit ? tc : eaten || c; if (fs !== lastFs) { g.fillStyle = fs; lastFs = fs; } }
      const d = (rim ? (cloud.pic ? 1.2 : 2.2) : Z < 0 ? (cloud.pic ? 1.15 : 1.6) : 1.1) * (.72 + .28 * Math.min(1, C[2])) * (1 + .3 * folE) * zg; g.fillRect(qx - d / 2, qy - d / 2, d, d); }); // following you, small: bigger, solider dots keep it crisp
    if (cloud.eyeImg && eyeQ.length === 6 && !mo && ballE < .05) cloud.eyeImg.forEach((E, j) => { const a0 = eyeQ[j * 3], ax = eyeQ[j * 3 + 1], ay = eyeQ[j * 3 + 2], BIG = 1.2, ux = [(ax[0] - a0[0]) / E.r * BIG, (ax[1] - a0[1]) / E.r * BIG], uy = [(a0[0] - ay[0]) / E.r * BIG, (a0[1] - ay[1]) / E.r * BIG];
      const pitch = 1.6 * Math.max(1, zg), st = pitch / Math.max(.2, Math.hypot(ux[0], ux[1])), dsz = 1.1 * Math.max(1, zg), L = lids[j], r = E.r, af = L.arch > 0 ? L.arch / Math.max(L.k, .001) : 0, A = alpha * k * (asm < 1.6 && !still ? cl(asm - .6) : 1); // picture pixels, sampled a screen dot apart
      for (let dy = -E.R2, row = 0; dy <= E.R2; dy += st * .866, row++) for (let dx0 = -E.R2; dx0 <= E.R2; dx0 += st) { const dx = dx0 + (row % 2) * st / 2; // a staggered grid of dots, like a halftone, not squares
        const o = ((Math.round(dy) + E.R2) * E.n + Math.round(dx) + E.R2) * 4; if (o < 0 || o >= E.d.length || E.d[o + 3] < 20) continue;
        let col = E.cols[o >> 2];
        if (L.k > .03 || L.sad > .03) { const q = Math.min(1, Math.abs(dx) / r), meet = .1 * r - .55 * r * (1 - q * q) * af, top = -r * 1.25 + (meet + r * 1.25) * Math.max(L.k, L.sad), bot = r * 1.25 + (meet - r * 1.25) * L.k, ed = r * .09; // lids, in dots: skin over, a lash line at the edge
          if (dy < top - ed || (L.k > .03 && dy > bot + ed)) col = cloud.eyeCol[j][0]; else if (dy < top + ed || (L.k > .03 && dy > bot - ed)) col = cloud.eyeCol[j][1]; }
        g.globalAlpha = A * E.d[o + 3] / 255; g.fillStyle = col; g.fillRect(a0[0] + dx * ux[0] + dy * uy[0] - dsz / 2, a0[1] + dx * ux[1] + dy * uy[1] - dsz / 2, dsz, dsz); }
      if (L.k < .5 && L.sad < .5) { const gx = -.38 * r, gy = -.4 * r, tw = .75 + .25 * Math.sin(tick * .05 + j); g.globalAlpha = A * tw * (1 - L.k * 2); g.fillStyle = "#fff"; const gs = dsz * 1.3; g.fillRect(a0[0] + gx * ux[0] + gy * uy[0] - gs / 2, a0[1] + gx * ux[1] + gy * uy[1] - gs / 2, gs, gs); } }); // a glint of light in each eye
    lastFs = null;
    if (cloud.pic && xp.t > .05) for (let j = 0; j < 3; j++) { g.globalAlpha = xp.t * (.3 + .7 * Math.max(0, Math.sin(tick * .08 - j * .9))); g.fillStyle = "#fff"; const d = 3 * Math.max(1, zg); g.fillRect(C[0] + (.55 + j * .2) * sc - d / 2, C[1] - (1.95 + j * .12) * sc - d / 2, d, d); } // a little "…" while it thinks
    g.globalCompositeOperation = "lighter";
    if (trip && ph === "work") workScene(role, beat, wb, wf, tq, tc);
    if (trip && ph === "work") { const w = ease(Math.min(1, (f - T5) / 40, (T6 - f) / 40)) * .35; // a faint ring of dots turns round the node while it works
      if (role !== "ask" && (wf === (BT * 1.5 | 0) || wf === (BT * 2 | 0) - 1)) { trip.n.flash = 50; sparks.push({ n: trip.n, t: 0 }); } // each tap lands: the node flashes
      for (let j = 0; j < 18; j++) { const a = j / 18 * 6.283 + tick * .02, rr = (17 + 2 * Math.sin(tick * .04)) * K + 10; g.globalAlpha = w * (.35 + .65 * (.5 + .5 * Math.cos(a - tick * .05))); g.fillStyle = tc; g.fillRect(tq.x + Math.cos(a) * rr - 1.2, tq.y + Math.sin(a) * rr * .5 - 1.2, 2.4, 2.4); } }
    g.globalCompositeOperation = "source-over";
    if (emo && !trip) { g.globalAlpha = .85 * env; g.font = "10px ui-monospace, monospace"; g.letterSpacing = "1.6px"; g.textAlign = "center"; g.fillStyle = SIG; g.fillText(EMO[ek][1], C[0], C[1] + R * C[2] * 1.05 + 14); g.letterSpacing = "0px"; g.globalAlpha = 1; }
    if (trip) { const word = { look: "looking", decide: "decided", med: trip.ate ? `meditating · taking in ${trip.ate}` : "meditating", go: "going", land: "landing", work: `${trip.verb || "working"} · ${SCRIPT[role][0][Math.max(0, beat)]}`, back: "coming back", pop: "ta-da" }[ph]; // the film's caption, under where it is
      const fade = ph === "look" ? cl(f / 20) : ph === "pop" ? 1 - cl(fp * 1.6) : 1, atHome = ph === "look" || ph === "decide", lx = atHome ? x : ph === "work" || ph === "land" ? tq.x : C[0], ly = atHome ? y + R * .95 : ph === "work" || ph === "land" ? tq.y + 30 * K + 12 : C[1] + R * C[2] * .95 + 6;
      g.globalAlpha = .9 * fade; g.font = "10px ui-monospace, monospace"; g.letterSpacing = "1.4px"; g.textAlign = "center"; g.fillStyle = ph === "look" ? "#fff" : tc; g.fillText(String(word).toUpperCase(), lx, ly); g.letterSpacing = "0px"; }
    g.globalAlpha = 1;
    let [fu, fv, fsz, fz = 0] = cloud.face; if (mo) { const p = ease(cl(mf)), [a, b, c, d = 0] = cloud.from.face; fu = a + (fu - a) * p; fv = b + (fv - b) * p; fsz = c + (fsz - c) * p; fz = d + (fz - d) * p; } // its eyes slide from the old face to the new
    [fu, fv] = bend(fu, fv, 0); [fu, fv, fz] = pose(fu, fv, fz, 0); // and ride the body as it breathes, leans, sits and dances
    if (ballE > .01) { fu *= 1 - ballE; fv *= 1 - ballE; fz *= 1 - ballE; fsz *= 1 - .7 * ballE; } // small, so they don't hide what you're looking at // in the rings: its eyes sit at the centre, on your cursor
    const em = (mx + my) / 2, fZ = -fu * sa + fz * ca, fs = 1 / (1 + fZ * .35); // its eyes ride with it; closed while it meditates
    return { x: C[0] + (fu * ca + fz * sa) * sc * fs * mx, y: C[1] + fv * sc * fs * my, s: fsz * (.4 + .6 * k) * em * (ek === "spin" ? Math.max(0, ca) : 1), ink: "#fff", pic: cloud.pic, calm: ph === "med" && fm > .08 && fm < .94 };
  }
  function liquid() { // while it speaks: the letters firm up out of a blob, and a droplet with its eyes roams the words, hopping and peeking at your pointer
    wet += ((slab ? 0 : 1) - wet) * .045; fx.querySelector("#sw-fat").setAttribute("radius", (.5 + wet * 7).toFixed(2)); fx.querySelector("#sw-soft").setAttribute("stdDeviation", (1.3 + wet * 9).toFixed(2));
    fx.querySelector("#sw-tint").setAttribute("flood-color", tint); ink.style.filter = wet < .08 ? "none" : ""; // once the letters have set, drop the liquid so they read crisp
    if (!slab) return;
    const a = tick * .011, tx = slab.w * (.5 + .46 * Math.sin(a)), ty = slab.h * (.5 + .62 * Math.sin(a * 2.3 + 1)) + Math.abs(Math.sin(tick * .09)) * -10; // a slow wander with a little hop
    px += (tx - px) * .05; py += (ty - py) * .05; const b = bubble.getBoundingClientRect(), r = root.getBoundingClientRect();
    const lx = ptr ? Math.max(-4, Math.min(4, (ptr[0] - (b.left - r.left + px)) * .03)) : Math.sin(tick * .03) * 3, ly = ptr ? Math.max(-4, Math.min(4, (ptr[1] - (b.top - r.top + py)) * .03)) : Math.cos(tick * .04) * 2;
    drop.style.translate = `${px - 24}px ${py - 24}px`; peek.style.translate = `${px - 24}px ${py - 24}px`; peek.style.setProperty("--lx", `${lx}px`); peek.style.setProperty("--ly", `${ly}px`);
    peek.classList.toggle("blink", tick % 190 > 183);
  }
  function frame() {
    if (!root.isConnected) return; requestAnimationFrame(frame);
    if (root.querySelector(".sp-steer-modal")) return; // a dialog is open over it: rest
    tick++; if (talk > 0) talk--; if (litT > 0 && !--litT) lit = -1;
    const asleep = root.classList.contains("asleep") || root.dataset.mode === "sleeping", mood = root.dataset.mood || "", quiet = asleep || root.dataset.mode === "quiet";
    if (!drag && !still) { yaw += (quiet ? .0006 : .0016) + spinV; spinV *= .95; } // a slow, steady turn; a fling keeps it spinning, easing off
    if (tick % 20 === 0) { const r = root.querySelector(".sp-rest"); if (root.dataset.mode === "sleeping") status.textContent = "Asleep · not answering · not learning"; else if (r && !r.hidden && r.textContent) status.textContent = r.textContent; // the job line space.js writes
      const rv = getComputedStyle(root).getPropertyValue("--dot").trim(); if (rv && rv !== tint) { tint = rv; markTint(); }
      lamps.querySelectorAll("span").forEach((l) => l.classList.toggle("on", busy ? (tick / 20 | 0) % 4 === [2, 1, 0, 3].indexOf(+l.dataset.s) : +l.dataset.s === lit)); }
    const stage = !cmds.hidden ? cmds : (slab && !bubble.hidden && !bubble.classList.contains("out")) || (hold > tick && !bubble.hidden) ? bubble : null, replying = !!stage; lay += ((replying ? 1 : 0) - lay) * (still ? 1 : .04); root.classList.toggle("sw-replying", replying); if (replying && trip) trip = null; // a reply or the command list: both take the stage the same way
    { const e = lay * lay * (3 - 2 * lay); zoom += (zt - zoom) * .12; cx = bcx + (W * .24 - bcx) * e; K = bK * (1 - .5 * e) * zoom; } // the wheel or a pinch zooms into the mesh // while it replies: the mind slides to one side and shrinks, its dots build the reply's box, and Dot sits on the box
    if (replying) { const b = stage.getBoundingClientRect(), r = cv.getBoundingClientRect(); sit = [b.right - r.left - 46, b.top - r.top]; stageR = [b.left - r.left, b.top - r.top, b.width, b.height]; }
    { const ear = root.querySelector(".sp-ear"), e = lay * lay * (3 - 2 * lay); if (ear) { // the chat box goes with the stage: under its box, as wide as it, linked to it
      if (fol || folE > .002) { /* following: follower() places it */ } else if (e < .002) { if (earOn) { ear.style.transform = ""; ear.style.width = ""; earOn = false; } const q = ear.getBoundingClientRect(), r = cv.getBoundingClientRect(); earNat = [q.left - r.left, q.top - r.top, q.width, q.height]; }
      else if (earNat && stageR) { earOn = true; ear.style.width = `${earNat[2] + (stageR[2] - earNat[2]) * e}px`;
        ear.style.transform = `translate(${(stageR[0] + stageR[2] / 2 - earNat[0] - earNat[2] / 2) * e}px, ${(stageR[1] + stageR[3] + 18 - earNat[1]) * e}px)`; } } }
    grow += (growTo - grow) * (still ? 1 : .05); lift += (1 - lift) * (still ? 1 : .04); dimD += ((detached ? 1 : 0) - dimD) * (still ? 1 : .03); liquid(); g.clearRect(0, 0, W, H); // no model: it keeps its shape and just powers down
    proj = nodes.map((n) => P(n.x, n.y, n.z)); const items = [], show = (n) => !hide.has(n.layer);
    // focus + context: the node under the pointer (or the one whose card is open) and what it is wired to stay lit, the rest steps back
    let foc = -1; if (ptr && !drag) { let bd = 18; proj.forEach((q, i) => { if (!show(nodes[i]) || q.z > RS * .6) return; const d = Math.hypot(q.x - ptr[0], q.y - ptr[1]); if (d < bd) { bd = d; foc = i; } }); }
    if (foc < 0 && pinned && !note.hidden) foc = nodes.indexOf(pinned);
    if (foc < 0 && trip && tripF > T4 && tripF < T6) foc = nodes.indexOf(trip.n); // on its node, the rest of the mesh steps back
    const nb = foc < 0 ? null : new Set([foc, ...edges.filter((e) => e.includes(foc)).map((e) => e[0] === foc ? e[1] : e[0])]), dim = (i) => nb && !nb.has(i) ? .16 : 1;
    const SR = RS * 1.1; { // the mind's shell: rings of dots like a dot-matrix globe, the near side bright and bigger, the far side faint, turning with the view
      const fade = (1 - morph * .7) * (nb ? .55 : 1) * (1 - folE) * (1 - .6 * dimD); g.fillStyle = "#fff"; // following you: no shell, no motes, no structure lines
      // one slow wave of the four systems' colours flows across the shell; while it works the colours deepen and the wave quickens a little
      const wsys = lit >= 0 ? lit : eyeTask && tick < eyeTask.until ? eyeTask.sys : null; workE += ((busy || learning || wsys != null ? 1 : 0) - workE) * (still ? 1 : .02);
      workCol = SYSC[wsys] || "#ffffff"; const sat = .55 + .35 * workE, flow = tick * (.0012 + .0012 * workE);
      if (!SHELLPAL[0]) for (let i = 0; i < 64; i++) { const f = i / 64 * 4, A = WAVE[f | 0], B = WAVE[(f + 1 | 0) % 4], m = f % 1, e = m * m * (3 - 2 * m); SHELLPAL[i] = A.map((x, k) => x + (B[k] - x) * e); } // a smooth loop violet → amber → cyan → green
      const tintOf = (i) => { const c = SHELLPAL[i]; return `rgb(${c.map((x) => Math.round(255 + (x - 255) * sat)).join(",")})`; }, PAL = SHELLPAL.map((_, i) => tintOf(i)); // washed toward white at rest
      const amp = still ? 0 : .012 + .014 * workE, bt = tick * .006; // a slow swell and a fine ripple over it: soothing, never a shake
      // a node's card open: the shell's dots pour out of the sphere and lay themselves into the card's box, its border bright; closed, they flow home
      const boxEl = !note.hidden ? note : stage; boxE += ((boxEl ? 1 : 0) - boxE) * (still ? 1 : .035); if (boxEl) lastBox = boxEl.getBoundingClientRect(); const nr = boxE > .002 ? lastBox : null, cr = nr && cv.getBoundingClientRect(); // closed, it measures nothing: the dots flow home from where the card was
      const bx0 = nr ? nr.left - cr.left : 0, by0 = nr ? nr.top - cr.top : 0, cols = nr ? Math.max(1, nr.width / 5 | 0) : 1, rows = nr ? Math.max(1, nr.height / 5 | 0) : 1, cells = cols * rows; let k = 0;
      for (let r = 1; r < 100; r++) { const v = -1 + r / 50, rr = Math.sqrt(1 - v * v) * SR, n = Math.max(24, Math.round(380 * rr / SR)); // dense and faint: a veil of dots rather than a cage
        for (let j = 0; j < n; j++) { const a = j / n * 6.283 + r * .37, b = 1 + amp * (Math.sin(2 * a + v * 3 + bt) + .5 * Math.sin(3 * a - v * 2 - bt * 1.3) + .35 * Math.sin(9 * a + v * 11 + bt * 2.2));
          const q = P(Math.cos(a) * rr * b, v * SR * b, Math.sin(a) * rr * b), z = q.z / SR, d = z < 0 ? .9 + .8 * -z : .8;
          const w = a / 6.283 + v * .35 + flow, ci = ((w % 1 + 1) % 1) * 64 | 0, glow2 = .75 + .25 * Math.sin((a + v * 2) * 2 - tick * .01); g.fillStyle = PAL[ci];
          let al = (z < 0 ? .07 + .24 * -z : .045 - .028 * z) * glow2 * (1 + .4 * workE) * fade, qx = q.x, qy = q.y; k++;
          if (nr) { const c = (k * 7919) % cells, cx2 = c % cols, cy2 = c / cols | 0, edge = cx2 === 0 || cy2 === 0 || cx2 === cols - 1 || cy2 === rows - 1, p = ease(cl(boxE * 1.7 - (k * .618 % 1) * .7)), tx = bx0 + cx2 * 5 + 2.5, ty = by0 + cy2 * 5 + 2.5;
            qx += (tx - qx) * p; qy += (ty - qy) * p - Math.sin(p * Math.PI) * 40; al += ((edge ? 1 : .12) * (k < cells * 1.2 ? 1 : .3) - al) * p; }
          g.globalAlpha = al; g.fillRect(qx - d / 2, qy - d / 2, d, d); } }

      g.globalCompositeOperation = "lighter"; for (const p of MOTES) { const tt = tick * .0025 + p.ph, q = P((p.x + Math.sin(tt) * .03) * SR * .9, (p.y + Math.cos(tt * 1.3) * .03) * SR * .9, (p.z + Math.sin(tt * .7) * .03) * SR * .9), tw = still ? .6 : .4 + .6 * Math.abs(Math.sin(tt * 3));
        g.globalAlpha = (q.z < 0 ? .55 : .22) * tw * fade; g.fillStyle = p.c; const d = q.z < 0 ? 1.6 : 1; g.fillRect(q.x - d / 2, q.y - d / 2, d, d); } g.globalCompositeOperation = "source-over"; // motes drifting through its mind
      const o = P(0, 0, 0); g.strokeStyle = "#fff"; g.lineWidth = 1; g.globalAlpha = .16 * fade * (1 - workE); g.beginPath(); g.ellipse(o.x, o.y, SR * o.s, SR * o.s * Math.max(.04, lift), 0, 0, 6.283); g.stroke(); // a faint outline, so it reads as one sphere
      for (const wr of wires) { if (hide.has(wr.layer)) continue; const pts = wr.line.map((p) => P(...p)), z = pts.reduce((s2, q) => s2 + q.z, 0) / pts.length; // each structure in its system's colour, yellow while that system works
        g.strokeStyle = wr.sys != null && (lit === wr.sys || (eyeTask && tick < eyeTask.until && eyeTask.sys === wr.sys)) ? SIG : wr.sys != null ? SYSC[wr.sys] : "#fff";
        g.globalAlpha = Math.max(.08, Math.min(.5, .3 - z / (RS * 3))) * fade * (nb ? .5 : 1); g.setLineDash(wr.dash || []); g.beginPath(); pts.forEach((q, i) => i ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y)); g.stroke(); }
      g.setLineDash([]); g.globalAlpha = 1; }
    edges.forEach((e, i) => { if (show(nodes[e[0]]) && show(nodes[e[1]])) items.push({ z: (proj[e[0]].z + proj[e[1]].z) / 2, t: "e", a: proj[e[0]], b: proj[e[1]], i }); });
    nodes.forEach((n, i) => { if (!show(n)) return; items.push({ z: proj[i].z, t: "n", n, q: proj[i], i }); });
    if (!quiet && !still && folE < .5) edges.slice(0, 120).forEach((e, k) => { const a = nodes[e[0]], b = nodes[e[1]]; if (!show(a) || !show(b)) return; const u = ((tick * .0035 + k * .618) % 1); // a signal running along every link, in the colour of where it starts
      const q = P(a.x + (b.x - a.x) * u, a.y + (b.y - a.y) * u, a.z + (b.z - a.z) * u); items.push({ z: q.z, t: "p", q, c: colour(a), fade: Math.sin(u * Math.PI) }); });
    sparks = sparks.filter((s) => (s.t += .028) < 1); for (const s of sparks) { const q = P(s.n.x * (1 - s.t), s.n.y * (1 - s.t), s.n.z * (1 - s.t)); items.push({ z: q.z, t: "p", q, big: 1 }); if (s.t > .96) rings.push(0); }
    if (!hide.has("var") && folE < .5) vars.forEach((v, i) => { const a = tick * (quiet ? .004 : .011) + i * 6.283 / vars.length, r = 185, q = P(r * Math.cos(a), r * Math.sin(a) * .35, r * Math.sin(a)); items.push({ z: q.z, t: "v", q, v }); });
    items.push({ z: 0, t: "dot" }); items.sort((a, b) => b.z - a.z); const labs = [];
    for (const it of items) { const near = it.z < 0, al = Math.max(.14, Math.min(1, .62 - it.z / 440)) * (it.t === "dot" ? 1 : (1 - morph * .7) * (1 - .6 * dimD)); // the web steps back while it speaks
      if (it.t === "dot" && (fol || folE > .002)) continue;
      if (it.t === "dot") { const T = eyeTask && tick < eyeTask.until && eyeTask.n && proj[nodes.indexOf(eyeTask.n)];
        if (T && !hide.has(eyeTask.n.layer) && !agents.length && !trip) { const c = SYSC[eyeTask.sys] || tint, f = Math.min(1, (eyeTask.until - tick) / 40); // where the work is: a beam from Dot to the node it is on, with what it is doing
          g.save(); g.strokeStyle = g.fillStyle = c; g.globalAlpha = .75 * f; g.lineWidth = 1.6; g.setLineDash([6, 6]); g.lineDashOffset = still ? 0 : -tick * .8; g.beginPath(); g.moveTo(cx, cy); g.lineTo(T.x, T.y); g.stroke(); g.setLineDash([]);
          const tag = VERB_OF[EYES[eyeTask.kind]] || eyeTask.kind; g.font = "600 11px ui-monospace, monospace"; const w = g.measureText(tag).width + 14; g.globalAlpha = .92 * f; g.fillStyle = "#000"; g.beginPath(); g.rect(T.x - w / 2, T.y - 30, w, 18); g.fill(); g.strokeStyle = c; g.stroke(); g.fillStyle = c; g.textAlign = "center"; g.fillText(tag, T.x, T.y - 17); g.restore(); }
        { const e = lay * lay * (3 - 2 * lay), c0 = cx, y0 = cy; if (sit && e > .001) { cx += (sit[0] - cx) * e; cy += (sit[1] - 24 * bK - Math.sin(cl((lay - .55) / .4) * Math.PI) * 16 * bK - cy) * e; } dot(mood, asleep); cx = c0; cy = y0; } continue; }
      if (it.t === "e" || it.t === "s") { const e = edges[it.i], on = nb && e && e.includes(foc); g.strokeStyle = on ? SIG : e ? colour(nodes[e[0]]) : "#fff"; g.globalAlpha = (on ? .85 : al * (it.t === "s" ? .06 : .26) * (nb ? .3 : 1)) * (1 - .6 * folE); g.lineWidth = on ? 1.2 : near ? 1 : .6; g.beginPath(); g.moveTo(it.t === "s" ? cx : it.a.x, it.t === "s" ? cy : it.a.y); g.lineTo((it.b || it.q).x, (it.b || it.q).y); g.stroke(); }
      else if (it.t === "n" && folE > .5) { const q = it.q, c = colour(it.n), tw = still ? .8 : .55 + .45 * Math.sin(tick * .05 + it.i * 1.7), r = 1.1 + Math.min(it.n.deg || 0, 6) * .3; // following you: the graph is a quiet sky, each node a twinkling star
        g.globalCompositeOperation = "lighter"; glow(q.x, q.y, r * 7, c, .22 * tw * al); g.globalCompositeOperation = "source-over"; g.globalAlpha = tw * al; g.fillStyle = c; g.fillRect(q.x - r, q.y - r, r * 2, r * 2);
        if (r > 2) { g.strokeStyle = c; g.lineWidth = .6; g.globalAlpha = .45 * tw * al; g.beginPath(); g.moveTo(q.x - r * 3.5, q.y); g.lineTo(q.x + r * 3.5, q.y); g.moveTo(q.x, q.y - r * 3.5); g.lineTo(q.x, q.y + r * 3.5); g.stroke(); } g.globalAlpha = 1; } // the bigger ones sparkle
      else if (it.t === "n") { const n = it.n, q = it.q, c = n.flash > 0 || it.i === foc ? SIG : colour(n), lit2 = nb?.has(it.i); if (n.born < 1) n.born = Math.min(1, n.born + .03);
        if (it.z > RS * .3 && !lit2 && n.flash <= 0 && n.layer !== "trait") { g.globalCompositeOperation = "lighter"; glow(q.x, q.y, 6, c, .25 * al * dim(it.i)); g.globalCompositeOperation = "source-over"; g.globalAlpha = al * .7 * dim(it.i); g.fillStyle = c; g.fillRect(q.x - 1, q.y - 1, 2, 2); g.globalAlpha = 1; continue; } // far off: a soft speck, so the near side reads sharp
        const r = (n.layer === "trait" ? 10 : n.layer === "note" ? 7 : n.layer === "chat" ? 4.5 : n.layer === "name" ? 3.6 + Math.min(n.n || 1, 6) * .9 : 5.5) * q.s * n.born * .8 * (1 + Math.min(n.deg || 0, 8) * .07) * (1 - .75 * (n.eat || 0)); if (n.eat > 0 && !trip) n.eat = Math.max(0, n.eat - .008); g.fillStyle = g.strokeStyle = c; g.lineWidth = 1;
        if (n.flash > 0) { n.flash--; g.globalAlpha = n.flash / 70; const o = r + (70 - n.flash) * .5; g.strokeRect(q.x - o, q.y - o, o * 2, o * 2); } // what just lit, in the signal colour
        if (!nb || lit2) { g.globalCompositeOperation = "lighter"; glow(q.x, q.y, r * (4 + (still ? 0 : .6 * Math.sin(tick * .02 + it.i))), c, (lit2 ? .55 : .3) * al); g.globalCompositeOperation = "source-over"; } // it glows, and breathes
        g.fillStyle = g.strokeStyle = c; g.globalAlpha = (n.layer === "trait" ? Math.max(al, .85) : lit2 ? 1 : al) * dim(it.i); // every node a square, as in the story: filled once settled, hollow while still open
        if (hollow(n)) g.strokeRect(q.x - r, q.y - r, r * 2, r * 2); else g.fillRect(q.x - r, q.y - r, r * 2, r * 2);
        if (n.state === "verified" || n.state === "ok" || (n.layer === "trait" && n.state === "grown")) { g.globalAlpha = al * .6; g.strokeRect(q.x - r - 3.5, q.y - r - 3.5, r * 2 + 7, r * 2 + 7); } // the Verifier's frame
        const hover = it.i === foc, top = hover ? 1e4 : n.flash > 0 ? 9e3 : lit2 ? 8500 : nb ? -1e5 : n.layer === "trait" && n.state === "grown" ? 8e3 : 0;
        if (n.layer !== "chat" && top > -1e5 && (top || it.z < RS * .3)) labs.push({ x: q.x, y: q.y + r + 12, n, c, hover, pri: top + (n.deg || 0) * 40 - it.z / RS * 60 + (n.layer === "plan" || n.layer === "trait" ? 50 : 0) }); }
      else if (it.t === "p") { const c = it.c || SIG, f = (it.fade ?? 1) * (nb ? .3 : 1), z = (it.big ? 4 : 1.6) * it.q.s; g.globalCompositeOperation = "lighter"; glow(it.q.x, it.q.y, z * 5, c, .5 * al * f); g.globalCompositeOperation = "source-over";
        g.globalAlpha = al * f; g.fillStyle = it.big ? SIG : "#fff"; g.fillRect(it.q.x - z / 2, it.q.y - z / 2, z, z); }
      else { const q = it.q; g.globalAlpha = al; g.strokeStyle = g.fillStyle = "#fff"; g.lineWidth = 1; const z = 6 * q.s; g.strokeRect(q.x - z, q.y - z, z * 2, z * 2); if (near) { g.font = "11px ui-monospace, monospace"; g.textAlign = "left"; g.fillText(`${it.v.name} ${it.v.value}`, q.x + 13, q.y + 4); } }
      g.globalAlpha = 1; }
    labels(labs, SR);
    if (fol || folE > .002) follower(mood, asleep);
    walk(); showWhat(); linkUp();
    gulp = gulp.filter((u) => (u.t += .03) < 1); for (const u of gulp) { const e = u.t * u.t; g.globalAlpha = 1 - e; g.fillStyle = "#fff"; g.font = `${Math.round(14 * (1 - e * .6))}px ui-monospace, monospace`; g.textAlign = "center"; g.fillText(u.text, u.from ? u.from[0] + (u.to[0] - u.from[0]) * e : cx, u.from ? u.from[1] + (u.to[1] - u.from[1]) * e : H - 90 + (cy - (H - 90)) * e); if (u.t > .93) rings.push(0); } g.globalAlpha = 1;
  }
  function labels(labs, SR) { // node names, best-connected and nearest first, each only where it does not cover another; then each structure's callout, as the story labels Dot's systems
    const fade = (1 - morph * .7) * (1 - folE) * (1 - .6 * dimD), boxes = [], free = (b) => !boxes.some((o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1]), MAX = Math.max(6, Math.min(16, W / 70));
    const back = (x, y, w, h2) => { g.globalAlpha = .72 * fade; g.fillStyle = "#000"; g.fillRect(x, y, w, h2); };
    g.textBaseline = "middle"; g.letterSpacing = "0px";
    // the callouts first, so names give way to them
    const side = { trait: -1, plan: 1, question: -1, note: 1, name: -1, chat: 1 }, o = P(0, 0, 0), edge = SR * o.s, out = [];
    for (const [k, S] of Object.entries(SHAPE)) { if (!S.n || hide.has(k) || lift < .6 || immerse || lay > .2) continue; const d = side[k]; // detached, the mind lies flat and its structures have no sides to label
      let best = null; nodes.forEach((n, i) => { if (n.layer === k && (!best || (proj[i].x - best.x) * d > 0)) best = proj[i]; }); if (best) out.push({ k, S, d, a: best, y: best.y }); }
    { const r0 = root.getBoundingClientRect(), box = (sel) => { const e = root.querySelector(sel)?.getBoundingClientRect(); return e && e.width ? [e.left - r0.left, e.top - r0.top, e.right - r0.left, e.bottom - r0.top] : null; };
      labels.pan = [box(".sw-left"), box(".sw-right")]; } // the side panels the callouts keep clear of
    const clear = (y, d) => { const b = labels.pan[d > 0 ? 1 : 0]; return b && y > b[1] - 24 && y < b[3] + 24 ? (d > 0 ? b[0] - 12 : b[2] + 12) : (d > 0 ? W - 12 : 12); };
    g.font = "10px ui-monospace, monospace"; for (const c of out) c.need = Math.max(g.measureText(`00  ${LY[c.k].t.toUpperCase()}`).width * 1.15, g.measureText(c.S.sub).width) + 34;
    for (const c of out) { const b = labels.pan[c.d > 0 ? 1 : 0], lim = clear(c.y, c.d); // a panel in the way would push it over the sphere: drop it below the panel instead
      if (b && (c.d > 0 ? lim - c.need < o.x + edge * .7 : lim + c.need > o.x - edge * .7)) c.y = Math.max(c.y, b[3] + 30); }
    for (const d of [-1, 1]) { const col = out.filter((c) => c.d === d).sort((a, b) => a.y - b.y); col.forEach((c, i) => { if (i) c.y = Math.max(c.y, col[i - 1].y + 36); }); }
    for (const c of out) { const need = c.need, lim = clear(c.y, c.d);
      const lx = c.d > 0 ? Math.min(o.x + edge + 18, lim - need) : Math.max(o.x - edge - 18, lim + need), tx = lx + c.d * 10, al = .9 * fade;
      g.globalAlpha = .45 * fade; g.strokeStyle = "#fff"; g.lineWidth = 1; g.beginPath(); g.moveTo(c.a.x, c.a.y); g.lineTo(lx - c.d * 10, c.y); g.lineTo(lx, c.y); g.stroke();
      g.font = "10px ui-monospace, monospace"; g.letterSpacing = "1.4px"; const t = `${String(out.indexOf(c) + 1).padStart(2, "0")}  ${LY[c.k].t.toUpperCase()}`, tw = g.measureText(t).width; g.letterSpacing = "0px"; const sw = g.measureText(c.S.sub).width, w = Math.max(tw, sw) + 18;
      const bx = c.d > 0 ? tx - 4 : tx - w + 4; back(bx, c.y - 10, w, 30); boxes.push([bx, c.y - 10, bx + w, c.y + 20]);
      g.globalAlpha = al; g.fillStyle = c.S.sys != null ? SYSC[c.S.sys] : "#fff"; const mx = c.d > 0 ? tx : tx - 7; g.fillRect(mx, c.y - 3, 6, 6);
      g.textAlign = c.d > 0 ? "left" : "right"; g.fillStyle = "#fff"; g.letterSpacing = "1.4px"; g.fillText(t, tx + c.d * 12, c.y); g.letterSpacing = "0px";
      g.globalAlpha = .6 * fade; g.fillText(c.S.sub, tx + c.d * 12, c.y + 13); }
    { const R = 92 * K; boxes.push([cx - R, cy - R * 1.1, cx + R, cy + R * 1.25]); if (lastDot && form) { const r = 80 * K * Math.min(1.5, Math.sqrt(Math.max(1, zoom))); boxes.push([lastDot[0] - r, lastDot[1] - r, lastDot[0] + r, lastDot[1] + r * 1.9]); } } // Dot's own space: no names over it
    labs.sort((a, b) => b.pri - a.pri); let shown = 0;
    for (const L of labs) { if (shown >= MAX && !L.hover) break; const n = L.n, k = L.hover ? 60 : 26, txt = n.label.length > k ? `${n.label.slice(0, k - 1)}…` : n.label;
      g.font = `${n.kind === "idea" ? "italic " : ""}${L.hover ? 12 : 10}px ui-monospace, monospace`; const w = g.measureText(txt).width + 8, b = [L.x - w / 2, L.y - 7, L.x + w / 2, L.y + 7];
      if (!L.hover && !free(b)) continue; boxes.push(b); shown++;
      back(b[0], b[1], w, 14); g.globalAlpha = (L.hover || n.flash > 0 ? 1 : .78) * fade; g.fillStyle = L.c; g.textAlign = "center"; g.fillText(txt, L.x, L.y); }
    g.textBaseline = "alphabetic"; g.globalAlpha = 1; }
  const at = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  cv.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY, yaw, pitch]; moved = 0; cv.setPointerCapture(e.pointerId); cv.classList.add("grab"); });
  cv.addEventListener("pointermove", (e) => { ptr = at(e); cv.style.cursor = eyeHit && Math.hypot(ptr[0] - eyeHit[0], ptr[1] - eyeHit[1]) < eyeHit[2] ? "pointer" : ""; if (!drag) return; moved += Math.abs(e.movementX) + Math.abs(e.movementY); const y1 = drag[2] + (e.clientX - drag[0]) * .011; spinV = spinV * .5 + (y1 - yaw) * .5; yaw = y1; pitch = Math.max(-1.2, Math.min(1.2, drag[3] + (e.clientY - drag[1]) * .011)); });
  cv.addEventListener("pointerleave", () => { ptr = null; });
  cv.addEventListener("wheel", (e) => { e.preventDefault(); zt = Math.max(.5, Math.min(4, zt * Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0015)))); }, { passive: false }); // a trackpad pinch arrives as a wheel with ctrl held
  cv.addEventListener("dblclick", () => { zt = 1; });
  cv.addEventListener("pointerup", (e) => { cv.classList.remove("grab"); if (drag && moved < 6 && lastDot && form && !(eyeHit && Math.hypot(at(e)[0] - eyeHit[0], at(e)[1] - eyeHit[1]) < eyeHit[2]) && Math.hypot(at(e)[0] - lastDot[0], at(e)[1] - lastDot[1] - 30 * K) < 70 * K) { emote(); nextEmo = tick + 600; }
    if (drag && !fol && moved < 6 && eyeHit && Math.hypot(at(e)[0] - eyeHit[0], at(e)[1] - eyeHit[1]) < eyeHit[2]) { setImmerse(!immerse); drag = null; return; } // its eyes: filled hides the dashboard, open brings it back
    if (drag && moved < 6) { const p = at(e); let best = null, bd = 24;
      nodes.forEach((n, i) => { if (hide.has(n.layer) || proj[i].z >= 0) return; const d = Math.hypot(proj[i].x - p[0], proj[i].y - p[1]); if (d < bd) { bd = d; best = n; } });
      if (best) { best.flash = 70; openNote(best); } } drag = null; });
  cv.addEventListener("keydown", (e) => { const k = { ArrowLeft: [-.15, 0], ArrowRight: [.15, 0], ArrowUp: [0, -.12], ArrowDown: [0, .12] }[e.key]; if (e.key === "Escape") note.hidden = true; if (e.key === "i") setImmerse(!immerse); if (!k) return; e.preventDefault(); yaw += k[0]; pitch = Math.max(-1.2, Math.min(1.2, pitch + k[1])); });
  new MutationObserver(() => { status.title = status.textContent; }).observe(status, { childList: true, characterData: true, subtree: true }); // clamped to 2 lines: the full text is the tooltip

  // ---- report mode: a plain readout of the experiment, the harness as sub-engines (/report-mode, /scene, or the menu) ----
  const panel = h("section", { class: "sw-report", "aria-label": "Experiment report", hidden: "" });
  root.append(panel);
  const openSt = new Set(); let reporting = false, rTimer = 0, rLast = 0, rData = null, rSeen = null, rFresh = new Set(), tFilter = "ok", tEngine = ""; // opens on what it did; the skips are one click away
  const esc = (v) => String(v ?? ""), n0 = (v) => (typeof v === "number" ? v : 0), r2 = (v) => (typeof v === "number" ? Math.round(v * 100) / 100 : "–");
  const local = (t) => { if (!t) return ""; const d = new Date(t.replace(" ", "T") + "Z"); return isNaN(d) ? t : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }; // the server writes UTC
  const STAGE = { 2: ["Plan", "decides what to learn next"], 1: ["Goals", "turns the plan into questions"], 0: ["Execute", "looks things up and writes notes"], 3: ["Verifier", "checks notes and rereads replies"] };
  const stageOf = (s) => { // one stage of the loop, in words: is it doing anything, and if not, why
    const e = s.engines || [], ok = e.reduce((a, x) => a + n0(x.ok), 0), runs = e.reduce((a, x) => a + n0(x.ok) + n0(x.skipped) + n0(x.failed), 0), failed = e.reduce((a, x) => a + n0(x.failed), 0);
    const last = e.filter((x) => x.last).sort((a, b) => (b.last.at > a.last.at ? 1 : -1))[0]?.last, blocked = e.length && e.every((x) => x.blocked) ? e[0].blocked : "";
    const state = s.on === false ? ["off", "switched off"] : blocked ? ["blocked", blocked] : failed && last?.outcome === "failed" ? ["failed", last.detail] : ok && last?.outcome === "ok" ? ["working", last.detail] : last ? ["waiting", last.detail] : ["idle", "has not run yet"];
    return { ok, runs, state }; };
  const lineChart = (series) => { // curiosity, maturity and the frontier term on one chart, so you can see them move against each other
    const pick = series.filter((x) => ["curiosity", "maturity", "frontier"].includes(x.name) && (x.points || []).length > 1), all = pick.flatMap((x) => x.points), hi = Math.max(1, ...all), N = Math.max(...pick.map((x) => x.points.length)) - 1 || 1;
    const C = { curiosity: "#ffb347", maturity: "#7dffa8", frontier: "#6ff7ff" }, svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 600 140"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Curiosity, maturity and frontier over the last steps");
    svg.innerHTML = `<line x1="40" x2="600" y1="10" y2="10" class="g"/><line x1="40" x2="600" y1="120" y2="120" class="g"/><text x="34" y="14" text-anchor="end">${r2(hi)}</text><text x="34" y="124" text-anchor="end">0</text><text x="40" y="138">${N + 1} steps ago</text><text x="600" y="138" text-anchor="end">now</text>`
      + pick.map((x) => `<polyline fill="none" stroke="${C[x.name]}" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke" points="${x.points.map((v, k) => `${(40 + k / N * 560).toFixed(1)},${(120 - v / hi * 110).toFixed(1)}`).join(" ")}"/>`).join("");
    return h("figure", { class: "sw-rc" }, svg, h("figcaption", {}, ...pick.map((x) => h("span", { style: `--c:${C[x.name]}` }, x.name)))); };
  let rTab = "steps", rSel = null, rSys = null; const noteCache = new Map();
  const sysTag = (n) => (n == null ? "" : n === 3 ? "V" : `S${n}`), pct = (v) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "–");
  const VERD = { keep: ["kept by the Verifier", "ok"], drop: ["dropped by the Verifier", "bad"], unchecked: ["not checked yet", "wait"] };
  function pick(sel) { rSel = sel; paintReport(); }
  async function noteDetail(id, verdict) { // fetched once per verdict, so a note the Verifier just judged is read again
    const c = noteCache.get(id); if (c && (c.loading || c.verdict === verdict || c.error)) return c;
    noteCache.set(id, { loading: true, verdict }); try { noteCache.set(id, await api(`/char/note/${id}`)); } catch { noteCache.set(id, { error: true, verdict }); } paintReport(); return noteCache.get(id); }
  const ICONS = { yes: '<path d="M3.5 8.5l3 3 6-7"/>', no: '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>', wait: '<circle cx="8" cy="8" r="2.2"/>' };
  const ic = (k) => { const s = document.createElement("span"); s.className = "sw-ic"; s.dataset.k = k; s.innerHTML = `<svg viewBox="0 0 16 16" aria-hidden="true">${ICONS[k]}</svg>`; return s; };
  const SC = { 2: "#c79bff", 1: "#ffb347", 0: "#6ff7ff", 3: "#7dffa8" }; // the system colours the lamps in the header use
  const journey = (n) => { // one note's life, top to bottom: what it guessed, what it read, what it wrote, who let it in
    if (!n || n.loading) return h("p", { class: "sw-dmut" }, "Loading the note…"); if (n.error) return h("p", { class: "sw-dmut" }, "Could not load this note.");
    const src = n.sources, g = n.gate, st = (state, title, ...body) => h("li", { "data-k": state }, ic(state), h("div", {}, h("b", {}, title), ...body));
    return h("article", { class: "sw-jn" }, h("h3", {}, esc(n.topic)), h("p", { class: "sw-dmut" }, `Note ${n.id}, written ${local(n.at)}`),
      h("ol", { class: "sw-jl" },
        st(n.question ? "yes" : "wait", "Asked", h("p", {}, n.plan ? `From the plan line “${esc(n.plan)}”.` : n.question ? "From a name it met, not from a plan line." : "Read straight from a name, never asked as a question.")),
        n.guess ? st("wait", "Guessed before looking", h("blockquote", {}, esc(n.guess)), h("small", {}, `${pct(n.surprise)} of the guess was not in what it found (target 10% or less).`)) : "",
        st(src == null ? "wait" : src.length ? "yes" : "no", src == null ? "Read (sources not kept for this older note)" : `Read ${src.length} source${src.length === 1 ? "" : "s"}`,
          src?.length ? h("ul", { class: "sw-jsrc" }, ...src.map((s) => h("li", {}, s.url ? h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, esc(s.title) || esc(s.url)) : h("span", {}, esc(s.title)), h("small", {}, esc(s.snippet))))) : ""),
        st("yes", "Wrote", h("blockquote", { class: "sw-jtext" }, esc(n.text)), n.ground != null ? h("small", {}, `${pct(n.ground)} of the names it used appear in its sources.`) : ""),
        g ? st(g[0] === "admit" ? "yes" : "no", g[0] === "admit" ? "Let in at the gate" : "Turned away at the gate", h("p", {}, esc(g[1])))
          : st(n.verdict === "keep" ? "yes" : n.verdict === "drop" ? "no" : "wait", n.verdict === "keep" ? "Kept by the Verifier, after it was saved" : n.verdict === "drop" ? "Dropped by the Verifier, after it was saved" : "Not judged yet", h("p", {}, "Written before the intake gate existed.")),
        st((n.names || []).length ? "yes" : "wait", "Joined the mesh", h("p", {}, (n.names || []).length ? n.names.map(esc).join(", ") : "No names taken from it yet.")))); };
  const TABS = [["story", "Story"], ["letter", "Letter"], ["chat", "Chat"], ["journal", "Journal"], ["notes", "Notes"], ["activity", "Activity"], ["engines", "Engines"], ["controls", "Controls"]];
  const MODE_DOES = { sleeping: "Asleep: no replies and no learning, so nothing you type reaches the model. Swap models and test with Run one step.", quiet: "Only answers you. Never learns by itself.", curious: "Learns by itself while you are away.", proactive: "Learns, then tells you what it found.", planner: "Idle time runs harness cycles: planner, controller, executor, Verifier." };
  const ctl = { budget: 4, roles: null, busy: "", last: null, swap: null }; let rCyc = null, jPages = null, cnet = null, cMesh = null, cTurns = null, sMesh = null; // its study journal, pulled while that tab is open
  try { rTab = localStorage.getItem("sw-rtab") || "story"; } catch { rTab = "story"; }
  if (!TABS.some(([k]) => k === rTab)) rTab = "story";
  const go = (k) => { if (rTab !== "story") ctl.lastTab = rTab; rTab = k; try { localStorage.setItem("sw-rtab", k); } catch { /* not remembered */ } if (k === "controls" || k === "engines") loadRoles(); paintReport(); };
  async function loadRoles() { if (ctl.roles) return;
    try { const [s, m] = await Promise.all([api("/settings"), api("/model/status").catch(() => ({ models: [] }))]);
      ctl.roles = { planner_model: s.planner_model || "", chat_model: s.chat_model || "", judge_model: s.judge_model || "" };
      ctl.loaded = s.model_name || ""; ctl.models = (m.models || []).filter((x) => !/embed|asr|audio|tts|chatterbox|whisper|manifests\//i.test(x)); // only models that can talk
    } catch { ctl.roles = { error: true }; } paintReport(); }
  const auraOf = (id) => { let n = 7; for (const c of id || "") n = (n * 31 + c.charCodeAt(0)) >>> 0; return `hsl(${n % 360} 85% 66%)`; }; // one colour per model: parts on the same model glow alike
  const modelOf = (role) => (ctl.roles && !ctl.roles.error && ctl.roles[`${role}_model`]) || ctl.loaded || "";
  const auraChip = (role, what) => { const id = modelOf(role); return id ? h("span", { class: "sw-aura", style: `--aura:${auraOf(id)}`, title: `${what} ${id}` }, h("i"), short(id)) : ""; };
  const short = (id) => (id || "").split("/").pop().replace(/-GGUF$|-MLX.*$|:latest$/i, "");
  async function act(label, fn) { ctl.busy = label; paintReport(); try { ctl.last = { label, ok: true, out: await fn() }; } catch (e) { ctl.last = { label, ok: false, out: String(e?.message || e) }; } ctl.busy = ""; await pullReport(true); }
  // ---------- F1 on the Story page: a broadcast of the training run, timing bar, sectors, telemetry, checkpoints ----------
  const mmss = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.round(s || 0) % 60).padStart(2, "0")}`;
  const letterBox = (d) => { // after a run: what it needs from you, answered in place
    const L = d.letter, items = L?.items || [], run = d.train?.runs?.[0], D = (ctl.drafts ||= {});
    if (!items.length) return ctl.sent ? h("p", { class: "sw-dmut sw-sent" }, ctl.sent) : "";
    const lg = run?.log || [], first = lg[0], last = lg.at(-1);
    const intro = run && run.status !== "running" && last ? `Run ${run.id} finished${run.why ? ` (${run.why})` : ""}. Curiosity went from ${r2(first?.curiosity)} to ${r2(last?.curiosity)} over ${n0(last.step)} steps. To keep learning, I need you for these:` : "To keep learning, I need you for these:";
    const send = () => act("letter", () => api("/char/letter", { method: "POST", body: JSON.stringify({ answers: items.map((x) => ({ id: x.id, text: D[x.id] || "", skip: D[`skip:${x.id}`] })) }) })
      .then((r) => { items.forEach((x) => { delete D[x.id]; delete D[`skip:${x.id}`]; }); ctl.sent = `Sent: ${r.given} answered, ${r["let go"]} let go.`; return ctl.sent; }));
    return h("section", { class: "sw-letter" }, h("header", {}, h("small", {}, `From ${esc(L.who)}`), h("h3", {}, "A letter for you"), h("p", {}, intro)),
      h("ol", {}, ...items.map((x) => h("li", {}, h("p", {}, h("i", {}, x.kind === "wish" ? "Wish" : "Question"), esc(x.ask)),
        h("textarea", { rows: 2, placeholder: "Your answer… (leave blank to answer later)", value: D[x.id] || "", disabled: !!D[`skip:${x.id}`], oninput: (e) => { D[x.id] = e.target.value; } }),
        h("label", { class: "sw-skip" }, h("input", { type: "checkbox", checked: !!D[`skip:${x.id}`], onchange: (e) => { D[`skip:${x.id}`] = e.target.checked; report(true); } }), "Let it go")))),
      h("div", { class: "sw-wbtns" }, h("button", { type: "button", disabled: !!ctl.busy, onclick: send }, "Submit")));
  };
  const DOING = { planner: "Planning what to learn next", plan: "Writing a plan", reflect: "Looking it up, writing a note", extract: "Pulling names out of its notes", ideas: "Finding ideas in its notes", ask: "Asking itself questions", wonder: "Wondering", goal: "Setting goals", fill: "Filling in its sheet", want: "Working out what it needs from you", journal: "Writing in its journal", check: "Checking a note", review: "Rereading a reply", tune: "Tuning a prompt", bake: "Consolidating", fold: "Folding notes together", sort: "Sorting", practise: "Practising its voice" };
  const dragBand = (m, tc, max) => { if (!tc) return m; // idle: press on the line and drag across the range you want; the next run takes it
    const line = m.querySelector(".pn-line"), band = line.querySelector("b"), cap = () => m.nextElementSibling;
    const at = (e) => { const r = line.getBoundingClientRect(); return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); };
    let x0 = null; m.classList.add("pn-drag");
    const show = (a, b) => { const lo = Math.min(a, b), hi = Math.max(a, b); tc.lo = r2(lo * max); tc.hi = r2(hi * max); band.style.left = `${lo * 100}%`; band.style.width = `${(hi - lo) * 100}%`;
      if (cap()) cap().textContent = `curiosity · target ${tc.lo} – ${tc.hi}`; };
    m.onpointerdown = (e) => { x0 = at(e); ctl.dragging = true; m.setPointerCapture(e.pointerId); show(x0, x0); };
    m.onpointermove = (e) => { if (x0 != null) show(x0, at(e)); };
    m.onpointerup = m.onpointercancel = () => { if (x0 == null) return; x0 = null; ctl.dragging = false; paintReport(); };
    return m; };
  const nowCard = (d, who) => { // after Pino's "right now": one sentence of what it is doing this second, then how it feels, what it needs, what is on its mind
    const run = d.train?.runs?.[0], live = !!d.train?.active, N = d.now || {}, L = d.life || {}, D = d.disposition || {}, last = run?.log?.at(-1), t0 = (d.trace || [])[0];
    const doing = N.kind ? DOING[N.kind] || N.kind : live ? "Between steps" : d.mode === "sleeping" ? "Asleep" : L.tired ? "Resting until its energy comes back" : "Waiting for you";
    const why = live && last?.outcome ? `Step ${n0(last.step)}: ${last.outcome}` : t0 ? `Last, it ${VERB[t0.kind] || t0.kind} ${t0.detail}` : "";
    const cfg = live ? run?.config : (ctl.tcfg ||= { minutes: 20, lo: 0, hi: 1, max_steps: 60 }), cmax = Math.max(12, (cfg?.hi || 0) * 2), cur = n0(D.curiosity), tr = L.trust?.value ?? 0;
    const meter = (lo, hi, v, at, band) => h("div", { class: "pn-meter" }, h("div", { class: "pn-line" }, band ? h("b", { style: `left:${band[0] * 100}%;width:${(band[1] - band[0]) * 100}%` }) : "", h("i", { style: `left:${Math.max(0, Math.min(1, at)) * 100}%` })),
      h("div", { class: "pn-ends" }, h("span", {}, lo), h("span", { class: "pn-num" }, v), h("span", {}, hi)));
    const cells = (v) => h("span", { class: "pn-cells" }, ...[...Array(12)].map((_, i) => h("i", i < Math.round(v * 12) ? { "data-on": v < .3 ? "hot" : "on" } : {})));
    const mind = d.letter?.items || [];
    return h("section", { class: "pn", "data-live": String(live || !!N.kind) },
      h("div", { class: "pn-row" }, h("span", { class: "pn-label" }, `${who}, right now`), h("span", { class: "pn-chip" }, h("i"), live ? `run ${run.id} · ${mmss(run.clock ?? last?.t)}` : d.mode || "idle")),
      h("p", { class: "pn-doing" }, doing), why ? h("p", { class: "pn-why" }, esc(why).slice(0, 220)) : "",
      h("div", { class: "pn-grid" },
        h("div", {}, h("span", { class: "pn-label" }, "how it feels"),
          dragBand(meter("settled", "restless", r2(cur), cur / cmax, [cfg.lo / cmax, Math.min(1, cfg.hi / cmax)]), live ? null : cfg, cmax),
          h("small", { class: "pn-cap" }, live ? "curiosity, this run's target marked" : `curiosity · drag along the line to set the next run's target (${r2(cfg.lo)} – ${r2(cfg.hi)})`),
          meter("wary", "open", (tr >= .5 ? "+" : "") + r2(tr * 2 - 1), tr), h("small", { class: "pn-cap" }, "trust in you")),
        h("div", {}, h("span", { class: "pn-label" }, "what it needs"), h("ul", { class: "pn-needs" }, ...Object.entries(L.needs || {}).map(([k, v]) => h("li", { title: L.about?.[k] || "" }, h("span", {}, k), cells(v))))),
        h("div", {}, h("span", { class: "pn-label" }, "on its mind"),
          h("p", { class: "pn-big" }, h("strong", {}, String(mind.length)), h("span", { class: "pn-label" }, mind.length === 1 ? "thing open" : "things open")),
          mind.length ? h("p", { class: "pn-why" }, `Loudest: a ${mind[0].kind}. “${esc(mind[0].ask).slice(0, 140)}”`) : h("p", { class: "pn-why" }, "Nothing open. It asks you here when it needs something."),
          mind.length ? h("button", { type: "button", class: "pn-link", onclick: () => go("letter") }, "answer in the letter →") : "")));
  };
  // ---------- the scroll story: Dot as a wireframe on the right, one slide per system on the left, then the run, live ----------
  const KEYS = [ // one keyframe per slide; scroll eases every number between the two slides on screen
    { yaw: .55, pitch: .22, dist: 7.02, ty: .05, rot: .3, spin: 1, split: 0, organs: 0, eyes: 1, plinth: 1, brain: 0, quest: 0, hands: 0, heart: 0, memory: 0 },
    { yaw: .35, pitch: .2, dist: 7.28, ty: .05, rot: .1, spin: .2, split: 1, organs: 1, eyes: 0, plinth: 1, brain: 0, quest: 0, hands: 0, heart: 0, memory: 0 },
    { yaw: .5, pitch: .5, dist: 4.42, ty: .45, rot: .1, spin: .2, split: .4, organs: 1, eyes: 0, plinth: .4, brain: 1, quest: 0, hands: 0, heart: 0, memory: 0 },
    { yaw: .75, pitch: .4, dist: 4.55, ty: .08, rot: .1, spin: .2, split: .4, organs: 1, eyes: 0, plinth: .4, brain: 0, quest: 1, hands: 0, heart: 0, memory: 0 },
    { yaw: 1.0, pitch: .25, dist: 7.8, ty: -.15, rot: .1, spin: .2, split: .4, organs: 1, eyes: 0, plinth: .4, brain: 0, quest: 0, hands: 1, heart: 0, memory: 0 },
    { yaw: .45, pitch: .12, dist: 3.77, ty: -.45, rot: .1, spin: .2, split: .4, organs: 1, eyes: 0, plinth: .4, brain: 0, quest: 0, hands: 0, heart: 1, memory: 0 },
    { yaw: .6, pitch: .55, dist: 7.28, ty: .45, rot: .1, spin: .3, split: .15, organs: .5, eyes: 0, plinth: .6, brain: .3, quest: 0, hands: 0, heart: 0, memory: 1 },
    { yaw: .6, pitch: .25, dist: 7.02, ty: .05, rot: .3, spin: 2.5, split: 0, organs: .2, eyes: 1, plinth: 1, brain: 0, quest: 0, hands: 0, heart: 0, memory: 0 },
  ];
  let sty = null; // built once and kept between repaints, so the canvas keeps drawing and the inputs keep what you typed
  const makeStory = () => {
    const cv = h("canvas", { class: "st-cv", "aria-hidden": "true" }), scene = makeDotScene(cv), say = h("ol", { class: "st-say", "aria-live": "polite" });
    const rail = h("div", { class: "st-rail", "aria-hidden": "true" }, ...KEYS.map(() => h("i"))), count = h("span", { class: "st-count" }), name = h("span", { class: "st-name" });
    const S = KEYS.map((_, n) => { const t = h("h2", { class: "st-h" }), sub = h("p", { class: "st-sub" }), live = h("div", { class: "st-live" });
      return { el: h("section", { class: "st-slide", "data-n": String(n) }, h("span", { class: "st-no" }, `${String(n + 1).padStart(2, "0")} / ${String(KEYS.length).padStart(2, "0")}`), t, sub, live), t, sub, live }; });
    // the run form lives on its slide and is never rebuilt, so what you type stays while the numbers around it move
    const C = (ctl.tcfg ||= { minutes: 20, lo: 0, hi: 1, max_steps: 60 }), inputs = {};
    const num = (k, label, step) => h("label", { class: "st-in" }, h("span", {}, label), inputs[k] = h("input", { type: "number", step, min: 0, value: C[k], oninput: (e) => { C[k] = +e.target.value; } }));
    const play = h("button", { type: "button", class: "st-play" }), stop = h("button", { type: "button", class: "st-stop", "aria-label": "Stop" }, "■"), runSay = h("p", { class: "st-runsay" });
    const send = (action, extra = {}) => act(`training ${action}`, () => api("/char/train", { method: "POST", body: JSON.stringify({ action, ...extra }) }).then((r) => r.status || action));
    play.onclick = () => { const run = rData?.train?.runs?.[0], live = !!rData?.train?.active;
      if (!live) send("start", { minutes: C.minutes, max_steps: C.max_steps, lo: Math.min(C.lo, C.hi), hi: Math.max(C.lo, C.hi) }); else send(run?.status === "paused" ? "resume" : "pause");
      setTimeout(() => watch.scrollIntoView({ behavior: "smooth", block: "start" }), 400); }; // pressing play takes you to the graph
    stop.onclick = () => send("stop");
    S[7].live.append(h("div", { class: "st-form" }, num("minutes", "minutes", 1), num("max_steps", "steps", 1), num("lo", "curiosity from", .05), num("hi", "to", .05)),
      h("div", { class: "st-deck" }, play, stop, runSay));
    const watchBody = h("div", { class: "st-watchbody" }), watch = h("section", { class: "st-watch" }, h("span", { class: "st-no" }, "live"), h("h2", { class: "st-h" }, "Watch it learn."), watchBody);
    const to = (n) => (n >= S.length ? watch : S[Math.max(0, n)].el).scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    const exit = () => go(ctl.lastTab && ctl.lastTab !== "story" ? ctl.lastTab : "notes");
    const back = h("button", { type: "button", class: "st-move", onclick: () => to(shown - 1) }, "back"), next = h("button", { type: "button", class: "st-move", onclick: () => to(shown + 1) }, "next →");
    const stage = h("div", { class: "st-stage" }, cv, say);
    const el = h("div", { class: "st", tabindex: "-1", onkeydown: (e) => { if (e.key === "Escape") exit(); } }, // the whole screen, like Pino's: Dot behind, the words over it, one slide a screen
      h("div", { class: "st-bar" }, name, rail, h("button", { type: "button", class: "st-move", onclick: exit, title: "Back to the report tabs (Esc)" }, "details ✕")),
      stage, h("div", { class: "st-left" }, ...S.map((x) => x.el)), watch, h("div", { class: "st-foot" }, count, h("span", {}, back, next)));
    const GLYPH = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+=/";
    const decode = (x) => { const text = x.want || ""; x.busy = true; let f = 0; clearInterval(x.timer); // the title types itself in, as Pino's do
      x.timer = setInterval(() => { f++; const shownN = Math.floor(text.length * f / 16); x.t.textContent = [...text].map((c, i) => i < shownN || c === " " ? c : GLYPH[(i * 7 + f * 13) % GLYPH.length]).join("");
        if (f >= 16) { clearInterval(x.timer); x.t.textContent = text; x.busy = false; } }, 28); };
    let D = { now: {} }, k = { ...KEYS[0] }, shown = -1;
    const progress = () => { const mid = innerHeight / 2, c = S.map((x) => { const b = x.el.getBoundingClientRect(); return (b.top + b.bottom) / 2; });
      if (mid <= c[0]) return 0; for (let i = 0; i < c.length - 1; i++) if (mid < c[i + 1]) return i + (mid - c[i]) / (c[i + 1] - c[i]); return c.length - 1; };
    const frame = (now) => {
      if (!el.isConnected) { setTimeout(() => requestAnimationFrame(frame), 400); return; } // off the Story tab: idle, cheaply
      const p = progress(), i = Math.min(KEYS.length - 2, Math.floor(p)), f = Math.min(1, p - i), e = f * f * (3 - 2 * f), A = KEYS[i], B = KEYS[i + 1];
      for (const key in A) k[key] += ((A[key] + (B[key] - A[key]) * e) - k[key]) * .12; // eased towards the scroll, so a fast flick still glides
      const L = D.learned || {};
      scene.draw(now, k, { sys: D.now?.sys, plans: L.plans, questions: L.questions, answered: L.answered, notes: L.notes, verified: L.verified, rejected: L.rejected, open: D.letter?.open });
      const on = Math.round(p); if (on !== shown) { shown = on; [...rail.children].forEach((x, n) => x.toggleAttribute("data-on", n <= on)); count.textContent = `${String(on + 1).padStart(2, "0")} / ${String(KEYS.length).padStart(2, "0")}`; S.forEach((x, n) => x.el.toggleAttribute("data-on", n === on)); if (S[on] && !matchMedia("(prefers-reduced-motion: reduce)").matches) decode(S[on]); back.disabled = on === 0; }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
    const b = (v) => h("b", {}, String(n0(v)));
    const tag = (n, loop) => { const s = loop.find((x) => x.system === n), stt = s ? stageOf(s).state : ["", ""];
      return D.now?.sys === n ? h("p", { class: "st-now", "data-live": "true" }, h("i"), `working now: ${DOING[D.now.kind] || D.now.kind}`) : stt[1] ? h("p", { class: "st-now" }, h("i"), esc(stt[0] && stt[0] !== "working" ? `${stt[0]}: ${stt[1]}` : stt[1]).slice(0, 140)) : ""; };
    return { el, update(d, loop, turns) {
      D = d; const L = d.learned || {}, who = (d.who || "").split(" ")[0], world = (d.who || "").split(/ from /i)[1] || "its world", run = d.train?.runs?.[0], live = !!d.train?.active;
      const plan = (d.trace || []).find((t) => t.kind === "plan" && t.outcome === "ok");
      name.textContent = d.who || "";
      const fill = (n, title, sub, ...live) => { S[n].want = title; if (!S[n].busy && S[n].t.textContent !== title) S[n].t.textContent = title; S[n].sub.replaceChildren(...sub); S[n].live.replaceChildren(...live); };
      // every slide shows what is true right now (real items from the report), not a description of the machine
      const rows = (items, empty) => items.length ? h("ol", { class: "st-rows" }, ...items.map(([k, v, c]) => h("li", c ? { style: `--c:${c}` } : {}, h("span", {}, k), h("b", {}, esc(String(v)).slice(0, 120))))) : h("p", { class: "st-empty" }, empty);
      const T = d.totals || {}, HL = d.harness_loop || {}, cyc = d.cycles?.[0], skips = {};
      for (const t of d.trace || []) if (t.outcome === "skipped" && t.kind !== "cycle") skips[t.detail] = (skips[t.detail] || 0) + 1;
      const stuck = Object.entries(skips).sort((a, b) => b[1] - a[1])[0], notes = d.notes || [], kept = notes.filter((x) => x.verdict === "keep"), dropped = notes.filter((x) => x.verdict === "drop");
      const cells = (n) => { const st = (d.trace || []).filter((t) => t.system === n).slice(0, 48).reverse(), did = st.filter((t) => t.outcome === "ok").length; // its last steps, oldest first: filled did something, hollow found nothing
        return st.length ? h("div", { class: "st-cells", style: `--c:${SC[n]}` }, h("div", {}, ...st.map((t) => h("i", { "data-o": t.outcome, title: `${t.kind} · ${local(t.at)}: ${t.detail}` }))), h("small", {}, `last ${st.length} steps: ${did} did something`)) : ""; };
      const newRun = h("button", { type: "button", class: "st-new", onclick: () => to(7) }, live ? `a run is going · watch it →` : "▶ new run");
      fill(0, `${who}.`, [b(T.steps), " steps since ", local(d.since), ". ", b(T.ok), " did something, ", b(T.skipped), " found nothing to do."],
        h("div", { class: "st-model", "data-up": String(!!d.model?.up) }, h("span", {}, h("i"), d.model?.up ? (d.now?.sys != null ? "thinking on" : "running on") : "model down"), (d.models?.length > 1 ? h("select", { class: "st-pick", "aria-label": "Model it thinks on", disabled: live || !!ctl.busy,
          onchange: (e) => { const v = e.target.value; act(`model ${v}`, () => api("/settings", { method: "PATCH", body: JSON.stringify({ model_name: v }) }).then(() => `now thinking on ${v}`)); } },
          ...d.models.map((m) => h("option", { value: m, selected: m === d.model_name }, m.split("/").pop())))
          : h("strong", { title: "The only model this server lists. Load another in your model server to pick it here." }, esc((d.model_name || "no model set").split("/").pop())))),
        h("div", { class: "st-modes" }, h("div", { role: "radiogroup", "aria-label": "Learning mode" }, ...Object.keys(MODE_DOES).map((m) => h("button", { type: "button", role: "radio", "aria-checked": String(d.mode === m), title: MODE_DOES[m], disabled: !!ctl.busy,
          onclick: () => act(`mode ${m}`, () => api("/char/wiring", { method: "POST", body: JSON.stringify({ mode: m }) }).then(() => `now ${m}`)) }, m))), h("small", {}, MODE_DOES[d.mode] || "")),
        newRun, rows([["curiosity", r2(d.disposition?.curiosity)], ["cycles", `${n0(HL.cycles_run)} · ${n0(HL.executed)} of ${n0(HL.proposed)} proposed steps ran`], stuck ? ["mostly stuck on", `${stuck[0]} (${stuck[1]}×)`, "#ffe600"] : null].filter(Boolean)));
      fill(1, "The dot is just a body.", ["Four systems inside it. What each is doing now:"],
        rows([[2, "S2 plans"], [1, "S1 asks"], [0, "S0 reads"], [3, "V checks"]].map(([n, t]) => { const s = loop.find((x) => x.system === n), stt = s ? stageOf(s).state : ["idle", ""]; return [t, D.now?.sys === n ? `working: ${DOING[D.now.kind] || D.now.kind}` : stt[1] || stt[0], SC[n]]; })));
      fill(2, "A planner.", ["Its last plan, cycle ", b(cyc?.cycle), ": ", b(cyc?.proposed?.length), " proposed, ", b(cyc?.rejected?.length), " rejected."],
        rows([...(cyc?.executed || []).map((x) => [x.outcome, `${x.cmd.split(" ")[0]}: ${x.detail}`]), ...(cyc?.rejected || []).map((x) => ["rejected", `${x.cmd}: ${x.why}`])], plan ? `“${esc(plan.detail).slice(0, 160)}”` : "No plan yet."), cells(2), tag(2, loop));
      fill(3, "Questions.", [b(L.questions), " asked, ", b(L.answered), " answered, ", b(d.letter?.open), " still open:"],
        rows((d.letter?.items || []).filter((x) => x.kind === "question").slice(0, 4).map((x) => ["open", x.ask]), "Nothing open."), cells(1), tag(1, loop));
      fill(4, "Hands.", [b(L.notes), " notes written. The newest:"], rows(notes.slice(0, 4).map((x) => [x.verdict, `${x.topic} — ${x.text}`]), "No notes yet."), cells(0), tag(0, loop));
      fill(5, "A gate.", [b(L.verified), " let in, ", b(L.rejected), " turned away. Last decisions:"],
        rows([...dropped.slice(0, 2).map((x) => ["dropped", `${x.topic} — ${x.text}`, "#ff6b6b"]), ...kept.slice(0, 2).map((x) => ["kept", x.topic, "#7dffa8"])], "Nothing judged yet."), cells(3), tag(3, loop));
      fill(6, "A memory that sleeps.", ["At the end of every run it sleeps: it keeps the newest ", b(24), " open questions about its world and lets the rest go. ", b(d.letter?.let_go), " let go so far, ", b(d.letter?.open), " open now."],
        d.letter?.items?.length ? h("button", { type: "button", class: "pn-link", onclick: () => go("letter") }, `what is left becomes your letter (${d.letter.items.length}) →`) : "");
      S[7].want = "Set it running."; if (!S[7].busy) S[7].t.textContent = S[7].want; S[7].sub.replaceChildren("It learns on its own and stops when the minutes or the steps run out, or when curiosity settles in the target.");
      for (const key of ["minutes", "max_steps", "lo", "hi"]) { const inp = inputs[key]; inp.disabled = live; if (document.activeElement !== inp) inp.value = live ? run.config[key] : C[key]; }
      play.textContent = !live || run.status === "paused" ? "▶" : "❚❚"; play.setAttribute("aria-label", !live ? "Start" : run.status === "paused" ? "Resume" : "Pause"); play.disabled = !live && (!!ctl.busy || !d.model?.up); stop.disabled = !live;
      runSay.textContent = ctl.busy ? "…" : live ? `${run.status === "paused" ? "Paused" : "Running"} · step ${n0(run.log?.at(-1)?.step)} · ${mmss(run.clock)}` : run ? `Run ${run.id} ${run.status === "done" ? "finished" : run.status}${run.why ? `: ${run.why}` : ""}.` : "Ready.";
      watchBody.replaceChildren(nowCard(d, who), f1(d, loop), grown(d, sMesh));
      const lines = (turns || []).filter((x) => x.role === "dot").slice(-2); // what it said last, beside it, newest at the bottom
      say.replaceChildren(...lines.map((x) => h("li", {}, esc(x.text.replace(/^A wish: /, "")).slice(0, 180))));
    } };
  };
  const grown = (d, mesh) => { // what it knows, as the flow it grows along: focal plans → the questions they raise → the notes that answer them → the names those notes meet; this run's part in yellow
    if (!mesh?.nodes?.length) return "";
    const run = d.train?.runs?.[0], live = !!d.train?.active, c = run?.config || {}, lo = c.mem0 ?? Infinity, hi = live ? Infinity : c.mem1 ?? Infinity;
    const COLS = [["plan", "focal points", "S2"], ["question", "questions", "S1"], ["note", "notes", "S0"], ["name", "names", "V kept"]], rid = (n) => +String(n.id).replace(/^m/, "") || 0;
    const nodes = mesh.nodes.filter((n) => COLS.some(([l]) => l === n.layer)), byId = new Map(nodes.map((n) => [n.id, n])), edges = mesh.edges.filter(([a, b]) => byId.has(a) && byId.has(b));
    for (const n of nodes) n.fresh = n.layer !== "name" && rid(n) > lo && rid(n) <= hi;
    for (const n of nodes) if (n.layer === "name") { const nb = edges.filter((e) => e.includes(n.id)).map((e) => byId.get(e[0] === n.id ? e[1] : e[0])); n.fresh = nb.length > 0 && nb.every((x) => x.fresh); } // a name is new if only new notes meet it
    const W = 1000, H = 380, pos = new Map();
    COLS.forEach(([l], ci) => { const col = nodes.filter((n) => n.layer === l).sort((a, b) => rid(a) - rid(b)); col.forEach((n, i) => pos.set(n.id, [70 + ci * 287, 30 + (col.length < 2 ? .5 : i / (col.length - 1)) * (H - 60)])); });
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("role", "img");
    const added = nodes.filter((n) => n.fresh), cut = (t, k) => esc(t).length > k ? `${esc(t).slice(0, k - 1)}…` : esc(t), xml = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    svg.setAttribute("aria-label", `${nodes.length} things it knows, ${added.length} from the last run`);
    svg.innerHTML = edges.map(([a, b]) => { const [x1, y1] = pos.get(a), [x2, y2] = pos.get(b), f = byId.get(a).fresh && byId.get(b).fresh, m = (x1 + x2) / 2;
        return `<path d="M${x1},${y1}C${m},${y1} ${m},${y2} ${x2},${y2}" fill="none" stroke="${f ? "#ffe600" : "#fff"}" stroke-opacity="${f ? .7 : .1}" stroke-width="${f ? 1.4 : 1}"/>`; }).join("")
      + nodes.map((n) => { const [x, y] = pos.get(n.id), s = n.fresh ? 9 : 6, dead = /drop|dropped/.test(n.state || "");
        return `<rect x="${x - s / 2}" y="${y - s / 2}" width="${s}" height="${s}" fill="${n.fresh ? "#ffe600" : dead ? "none" : "#fff"}" stroke="${dead ? "#ff6b6b" : "none"}" opacity="${n.fresh ? 1 : .55}"><title>${xml(`${n.layer}: ${n.label}`)}</title></rect>`
          + (n.fresh ? `<text x="${x + 9}" y="${y + 4}" font-size="11" fill="#ffe600">${xml(cut(n.label, 34))}</text>` : ""); }).join("")
      + COLS.map(([l, name, sys], ci) => `<text x="${70 + ci * 287}" y="${H - 4}" font-size="10" letter-spacing="1.4" fill="rgba(255,255,255,.55)" text-anchor="middle">${sys} · ${name.toUpperCase()}</text>`).join("");
    const counts = COLS.map(([l, name]) => [name, nodes.filter((n) => n.layer === l).length, added.filter((n) => n.layer === l).length]);
    return h("section", { class: "kg" }, h("p", { class: "f1-vno" }, live ? "what it knows · growing now" : run ? `what it knows · after run ${run.id}` : "what it knows"),
      h("h3", {}, c.mem0 == null ? "What it knows." : added.length ? `+${added.length} from ${live ? "this" : "the last"} run.` : live ? "Nothing new yet." : "The last run added nothing."),
      h("ul", { class: "kg-counts" }, ...counts.map(([name, n, a]) => h("li", {}, h("b", {}, String(n)), ` ${name}`, a ? h("i", {}, ` +${a}`) : ""))),
      h("div", { class: "kg-plot" }, svg));
  };
  const verdict = (run) => { // a finished run, in plain words: did it work, what each step did, what failed and why, what to do next
    const steps = (run.log || []).filter((x) => x.step > 0), by = (k) => steps.filter((x) => x.kind === k), ok = by("ok"), sk = by("skipped"), bad = by("failed");
    const reasons = (xs) => Object.entries(xs.reduce((m, x) => (m[x.outcome] = (m[x.outcome] || 0) + 1, m), {})).sort((a, b) => b[1] - a[1]);
    const c0 = run.log?.[0]?.curiosity, c1 = run.log?.at(-1)?.curiosity, cfg = run.config || {}, hit = /reached the target/.test(run.why || "");
    const word = run.status === "failed" ? "Failed" : run.status === "stopped" ? "Stopped" : hit ? "Reached the target" : ok.length ? "Finished" : "Finished, learned nothing";
    const tone = run.status === "failed" ? "bad" : hit || ok.length ? "good" : "flat";
    const next = run.status === "failed" ? (bad.some((x) => /already running/.test(x.outcome)) ? "Its own idle learning was mid-cycle when the run started. Runs now wait their turn, so press play again." : "Look at the failures below, fix what they name, then press play again.")
      : run.status === "stopped" ? "You stopped it. Press play to start again." : hit ? "Curiosity settled where you wanted it." : !ok.length ? "Every step found nothing to do. Answer the open questions in the letter to give it something new." : "Press play to keep it going, or move the target.";
    const row = (k, xs, c) => xs.length ? h("li", { style: `--c:${c}` }, h("span", {}, `${xs.length} ${k}`), h("ol", {}, ...reasons(xs).slice(0, 4).map(([why, n]) => h("li", {}, esc(why), n > 1 ? h("b", {}, ` ×${n}`) : "")))) : "";
    return h("section", { class: "f1-verdict", "data-tone": tone },
      h("p", { class: "f1-vno" }, `run ${run.id} · ${local(run.started)}${run.clock != null ? ` · ${mmss(run.clock)}` : ""}`),
      h("h3", {}, word + "."), h("p", { class: "f1-vwhy" }, esc(run.why || "")),
      h("div", { class: "f1-vcells", "aria-label": `${steps.length} steps` }, ...steps.map((x) => h("i", { "data-o": x.kind, title: `step ${x.step}: ${x.kind} · ${x.outcome}` }))),
      h("ul", { class: "f1-vrows" }, row("did something", ok, "#7dffa8"), row("found nothing to do", sk, "rgb(255 255 255 / .5)"), row("failed", bad, "#ff6b6b"),
        typeof c0 === "number" ? h("li", {}, h("span", {}, "curiosity"), h("p", {}, `${r2(c0)} → ${r2(c1)} · target ${r2(cfg.lo)} – ${r2(cfg.hi)}: ${hit ? "reached" : "not reached"}`)) : ""),
      h("p", { class: "f1-vnext" }, h("b", {}, "Next: "), next));
  };
  const LANE = [[2, "S2 Plan"], [1, "S1 Goals"], [0, "S0 Execute"], [3, "V Verify"]];
  const niceStep = (T) => [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200].find((x) => T / x <= 8) || 7200;
  const tLabel = (t, T) => T < 120 ? `${Math.round(t)}s` : mmss(t);
  const f1 = (d, loop) => { // the run as it happens, on one clock: every variable on top, which system is working in lanes under it, the flow counts last
    const run = d.train?.runs?.[0], live = !!d.train?.active && run && ["running", "paused"].includes(run.status), cfg = run?.config, log = run?.log || [], last = log.at(-1), tint = d.tint || "#6ff7ff";
    const tc = live ? cfg : (ctl.tcfg ||= { minutes: 20, lo: 0, hi: 1, max_steps: 60 }); // idle: the band is the next run's target, and you drag it
    const pts = log.length > 1 || live ? [...log] : (() => { const S = Object.fromEntries((d.series || []).map((x) => [x.name, x.points || []])), n = Math.max(0, ...Object.values(S).map((p) => p.length)); return [...Array(n)].map((_, i) => Object.fromEntries([["t", i], ...Object.entries(S).map(([k, p]) => [k, p[i] ?? 0])])); })();
    if (live && log.length) { const D = d.disposition || {}, L = d.life || {}; // a live "now" point from the report itself, so a line moves inside a long cycle, not only when a step lands
      pts.push({ t: run.clock ?? 0, step: last?.step, curiosity: D.curiosity, maturity: D.maturity, ...(typeof D.frontier?.term === "number" ? { frontier: D.frontier.term } : {}), ...(L.needs || {}), ...(typeof L.trust?.value === "number" ? { trust: L.trust.value } : {}), now: true }); }
    const clock = run?.clock ?? last?.t ?? 0, T = Math.max(10, clock, pts.at(-1)?.t || 0), byClock = !!log.length || live; // live: the clock and the lanes from the first second, before the first step lands
    const C = { curiosity: tint, maturity: "#ffb347", frontier: "#c79bff", ...NEED_C, trust: "#e4e4e7" };
    const has = pts.length ? Object.keys(C).filter((k) => pts.some((p) => typeof p[k] === "number")) : [], moved = (k) => new Set(pts.map((p) => r2(+p[k] || 0))).size > 1;
    const keys = has.filter((k) => moved(k) || k === "curiosity"), still = has.filter((k) => !keys.includes(k)); // a variable that never moved is a fact, not a line
    const X = (t) => Math.min(800, (t / T) * 800), TOP = 14, BASE = 190; // x 0–800 is the clock, names to the right
    const scale = (k) => { const vs = pts.map((p) => +p[k] || 0), band = k === "curiosity" && tc ? [tc.lo, tc.hi] : null, lo0 = Math.min(...vs, band?.[0] ?? Infinity), hi0 = Math.max(...vs, band?.[1] ?? -Infinity);
      const span = Math.max(hi0 - lo0, ["curiosity", "frontier"].includes(k) ? Math.max(1, Math.abs(hi0) * .2) : .25), lo = (hi0 + lo0) / 2 - span / 2; // a small wiggle stays small
      return { vs, band, Y: (v) => BASE - (v - lo) / span * (BASE - TOP), V: (y) => lo + (BASE - y) / (BASE - TOP) * span }; };
    const sc = Object.fromEntries(keys.map((k) => [k, scale(k)]));
    const path = (k) => sc[k].vs.map((v, i) => `${i ? "L" : "M"}${X(pts[i].t || 0).toFixed(1)},${sc[k].Y(v).toFixed(1)}`).join("") + (live ? `L${X(clock).toFixed(1)},${sc[k].Y(sc[k].vs.at(-1)).toFixed(1)}` : ""); // live: each line runs on to now
    const step = niceStep(T), grid = [...Array(Math.floor(T / step) + 1)].map((_, i) => i * step);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 1000 200"); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("aria-hidden", "true");
    const cb = sc.curiosity?.band, yHi = cb && sc.curiosity.Y(cb[1]), yLo = cb && sc.curiosity.Y(cb[0]);
    svg.innerHTML = `<defs><linearGradient id="f1fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${tint}" stop-opacity=".2"/><stop offset="1" stop-color="${tint}" stop-opacity="0"/></linearGradient></defs>`
      + (byClock ? pts.slice(1).filter((p) => !p.now).map((p) => `<line x1="${X(p.t).toFixed(1)}" x2="${X(p.t).toFixed(1)}" y1="0" y2="200" stroke="#fff" opacity=".05" vector-effect="non-scaling-stroke"/>`).join("") : "") // a hairline where each step ended
      + (cb ? `<rect data-band x="0" width="800" y="${yHi.toFixed(1)}" height="${Math.max(1, yLo - yHi).toFixed(1)}" fill="#7dffa8" opacity=".06"/>`
        + [yHi, yLo].map((y) => `<line data-edge x1="0" x2="800" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#7dffa8" opacity=".45" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/>`).join("") : "")
      + (sc.curiosity ? `<path d="${path("curiosity")}L${X(live ? clock : pts.at(-1).t || 0).toFixed(1)},200L0,200Z" fill="url(#f1fill)" data-k="curiosity"/>` : "")
      + keys.filter((k) => k !== "curiosity").map((k) => `<path d="${path(k)}" data-k="${k}" fill="none" stroke="${C[k]}" stroke-width="1.8" opacity=".85" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`).join("")
      + (sc.curiosity ? `<path d="${path("curiosity")}" data-k="curiosity" fill="none" stroke="${tint}" stroke-width="3.5" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>` : "");
    const at = (t, y, cls, extra = "") => h("i", { class: cls, style: `left:${X(t) / 10}%;top:${y / 2}%${extra}` });
    const focus = (k) => svg.querySelectorAll("[data-k]").forEach((p) => { p.style.opacity = !k || p.dataset.k === k ? "" : ".08"; });
    let floor = -Infinity; // each line's name sits at its end, nudged down so no two overlap
    const labels = keys.map((k) => ({ k, y: sc[k].Y(sc[k].vs.at(-1)) })).sort((a, b) => a.y - b.y).map((l) => { l.y = Math.max(l.y, floor + 11); floor = l.y; return l; })
      .map(({ k, y }) => { const v = sc[k].vs, dv = v.at(-1) - v[0];
        return h("button", { type: "button", class: "f1-lab", style: `top:${y / 2}%;--c:${C[k]}`, onmouseenter: () => focus(k), onmouseleave: () => focus(), onfocus: () => focus(k), onblur: () => focus(), "aria-label": `${k}: ${r2(v.at(-1))}, ${dv >= 0 ? "up" : "down"} ${r2(Math.abs(dv))} this run` },
          h("i"), k, h("b", {}, String(r2(v.at(-1)))), r2(Math.abs(dv)) ? h("small", { "data-d": dv > 0 ? "up" : "down" }, `${dv > 0 ? "▲" : "▼"}${r2(Math.abs(dv))}`) : ""); });
    const plot = h("div", { class: "f1-plot" }, svg,
      ...(sc.curiosity ? pts.map((p) => p.snap ? at(p.t || 0, sc.curiosity.Y(+p.curiosity || 0), "f1-bead") : null).filter(Boolean) : []),
      live && sc.curiosity ? at(clock, sc.curiosity.Y(sc.curiosity.vs.at(-1)), "f1-nowdot") : "",
      cb ? h("span", { class: "f1-target", style: `top:${yHi / 2}%` }, `target ${r2(cb[0])} – ${r2(cb[1])}${live ? "" : " · drag up or down on the graph to set it"}`) : "",
      ...(byClock ? pts.slice(1).filter((p) => !p.now).map((p) => h("span", { class: "f1-stepno", style: `left:${X(p.t) / 10}%` }, String(p.step))) : []), ...labels);
    if (!live && sc.curiosity) { // draw the target instead of typing it: press, drag over the curiosity range you want, let go
      const yOf = (e) => { const r = plot.getBoundingClientRect(); return Math.max(0, Math.min(200, (e.clientY - r.top) / r.height * 200)); };
      let y0 = null;
      const show = (a, b) => { const v = [sc.curiosity.V(a), sc.curiosity.V(b)].map((x) => Math.max(0, r2(x))), lo = Math.min(...v), hi = Math.max(...v);
        tc.lo = lo; tc.hi = hi; const top = Math.min(a, b), bot = Math.max(a, b), band = svg.querySelector("[data-band]"), [e1, e2] = svg.querySelectorAll("[data-edge]");
        band.setAttribute("y", top); band.setAttribute("height", Math.max(1, bot - top)); for (const [ln, y] of [[e1, top], [e2, bot]]) { ln.setAttribute("y1", y); ln.setAttribute("y2", y); }
        const lab = plot.querySelector(".f1-target"); lab.style.top = `${top / 2}%`; lab.textContent = `target ${lo} – ${hi}`; };
      plot.classList.add("f1-drag");
      plot.onpointerdown = (e) => { if (e.target.closest("button")) return; y0 = yOf(e); ctl.dragging = true; plot.setPointerCapture(e.pointerId); show(y0, y0 + 1); };
      plot.onpointermove = (e) => { if (y0 != null) show(y0, yOf(e)); };
      plot.onpointerup = plot.onpointercancel = () => { if (y0 == null) return; y0 = null; ctl.dragging = false; paintReport(); };
    }
    const lanes = run?.lanes || [], showLanes = byClock && (live || lanes.length);
    const lanesEl = showLanes ? h("div", { class: "f1-lanes" }, ...LANE.map(([n, name]) => h("div", { class: "f1-lane", style: `--c:${SC[n]}` },
      h("div", { class: "f1-track" }, ...lanes.filter((l) => l[0] === n).map((l) => { const w = X(l[3]) - X(l[2]), on = live && l[3] >= clock - 1.6;
        return h("span", { class: `f1-bar${on ? " on" : ""}`, style: `left:${X(l[2]) / 8}%;width:${Math.max(.5, w / 8)}%`, title: `${l[1]}: ${tLabel(l[2], T)} to ${tLabel(l[3], T)}` }, w > 50 ? l[1] : ""); })),
      h("b", {}, name, live && lanes.at(-1)?.[0] === n && lanes.at(-1)[3] >= clock - 1.6 ? h("small", {}, ` · ${lanes.at(-1)[1]}`) : "")))) : "";
    const axis = h("div", { class: "f1-time" }, ...grid.map((t) => h("span", { style: `left:${X(t) / 8}%` }, byClock ? tLabel(t, T) : `step ${t}`)));
    const gridEl = h("div", { class: "f1-grid" }, ...grid.map((t) => h("i", { style: `left:${X(t) / 8}%` })), live ? h("i", { class: "f1-nowline", style: `left:${X(clock) / 8}%` }) : "") // grid, axis and lanes span the clock's 800 of 1000 units;
    const held = still.length ? h("p", { class: "f1-still" }, "Held steady: ", ...still.map((k) => h("span", { style: `--c:${C[k]}` }, k, h("b", {}, String(r2(+pts.at(-1)?.[k] || 0)))))) : "";
    const head = live ? h("div", { class: "f1-head" }, h("i"), h("span", {}, run.status === "paused" ? "Paused" : "Training"), h("strong", {}, mmss(clock)), h("small", {}, `of ${mmss(cfg?.minutes * 60)}`),
        h("strong", {}, String(n0(last?.step))), h("small", {}, `of ${n0(cfg?.max_steps)} steps`), h("strong", {}, String(n0(run.snaps))), h("small", {}, "checkpoints"),
        !last?.step ? h("small", { class: "f1-first" }, "· a step is one whole cycle (plan, then each command), so the first takes a while: watch the lanes") : "")
      : run ? verdict(run) : h("div", { class: "f1-head" }, h("i"), h("span", {}, "No run yet: press ▶ new run, then watch it here"));
    const L = d.learned || {}, st = (n) => { const s = loop.find((x) => x.system === n); return s ? stageOf(s).state : ["idle", ""]; }, gate = (d.trace || []).find((t) => t.kind === "evaluate");
    const S = [{ n: L.plans, k: "plan lines", c: SC[2], s: st(2), to: () => { rSys = 2; go("activity"); } }, { n: L.questions, k: "questions", c: SC[1], s: st(1), sub: `${n0(L.answered)} answered`, to: () => { rSys = 1; go("activity"); } },
      { n: L.notes, k: "notes written", c: SC[0], s: st(0), to: () => go("notes") }, { n: L.verified, k: "let in", c: SC[3], s: gate ? [gate.outcome === "ok" ? "working" : gate.outcome, gate.detail] : st(3), sub: `${n0(L.rejected)} turned away`, gate: true, to: () => go("notes") },
      { n: L.names, k: "names in the mesh", c: SC[0], s: ["", "people, places and things it can link"], to: () => { tEngine = "extract"; rSys = null; go("activity"); } }];
    return h("figure", { class: "f1 sw-flow", "data-live": String(!!live), style: `--team:${tint}` }, head,
      h("div", { class: "f1-chart" }, gridEl, plot, lanesEl), axis, held,
      live && last?.outcome ? h("p", { class: "f1-now" }, `Step ${n0(last.step)}: ${esc(last.outcome)}`) : "",
      h("h4", { class: "f1-flowh" }, "What it learned, stage by stage"),
      h("ol", {}, ...S.map((x) => h("li", { style: `--c:${x.c}` }, h("button", { type: "button", onclick: x.to, title: "Open the details" },
        h("strong", {}, String(n0(x.n))), h("b", {}, x.k), x.sub ? h("small", { class: x.gate ? "sw-out" : "" }, x.sub) : "",
        x.s[1] ? h("p", { "data-s": x.s[0] }, esc(x.s[0] && x.s[0] !== "working" ? `${x.s[0]}: ${x.s[1]}` : x.s[1])) : "")))));
  };
  const youBox = (d) => { const Y = { ...(d.you || {}) }, about = Y.about || ""; delete Y.about;
    const box = h("textarea", { rows: 3, placeholder: "e.g. I'm Osiris, your Guardian. You were my Ghost before you were destroyed.", "aria-label": "Who you are, in your own words" }); box.value = about;
    const saved = h("small", { class: "sw-dmut", role: "status" });
    const save = h("button", { type: "button", disabled: !!ctl.busy, onclick: async () => { save.disabled = true; try { await api("/char/you", { method: "POST", body: JSON.stringify({ about: box.value }) }); saved.textContent = "Saved. It reads this before every reply."; } catch { saved.textContent = "Could not save."; } save.disabled = false; } }, "Save");
    return h("section", { class: "sw-youbox" }, h("h4", {}, "Who you are"), box, h("div", { class: "sw-wbtns" }, save, saved),
      Object.keys(Y).length ? h("ul", { class: "sw-you" }, ...Object.entries(Y).map(([k, f]) => h("li", {}, f, h("button", { type: "button", class: "sw-x", "aria-label": `Forget: ${f}`, title: "Forget this",
        onclick: () => act("forget", () => api("/char/you", { method: "POST", body: JSON.stringify({ forget: k }) }).then(() => "forgotten")) }, "×")))) : h("p", { class: "sw-dmut" }, "It also learns from chat: “My name is…”, “I'm your…”, “I work as…”."),
      d.life?.trust ? h("p", { class: "sw-dmut" }, `It kept ${n0(d.life.trust.kept)} of the ${n0(d.life.trust.n)} things you said. ` + (d.life.trust.trusted ? "It trusts you, so it talks to you openly." : d.life.trust.n < 10 ? "Trust takes ten messages to earn." : `Trust ${Math.round(d.life.trust.value * 100)}%: at 70% it opens up.`)) : ""); };
  const NEED_C = { fullness: "#7dffa8", energy: "#ffd27a", wonder: "#6ff7ff", joy: "#ff7ac6", calm: "#b49cff" };
  const feels = (L) => !L ? "" : h("section", { class: "sw-feels" }, h("h4", {}, L.tired ? "How it feels · resting" : "How it feels"),
    h("ul", {}, ...Object.entries(L.needs || {}).map(([k, v]) => h("li", { title: L.about?.[k] || "", style: `--c:${NEED_C[k] || "#a1a1aa"}` },
      h("span", {}, k), h("i", { class: v < .3 ? "low" : "" }, h("b", { style: `width:${Math.round(v * 100)}%` })), h("small", {}, Math.round(v * 100))))),
    L.shifts?.length ? h("p", { class: "sw-dmut sw-shift" }, `${L.shifts[0].dir === "down" ? "↓" : "↑"} ${esc(L.shifts[0].need)}, ${local(L.shifts[0].at)}: ${esc(L.shifts[0].cause)}`) : "");
  const wishes = (L) => { const open = (L?.wants || []).filter((w) => w.status === "waiting"), done = (L?.wants || []).filter((w) => w.status !== "waiting").slice(0, 3);
    if (!L || (!open.length && !done.length)) return h("section", {}, h("h4", {}, "It wants"), h("p", { class: "sw-dmut" }, "Nothing yet. When a guess is far off, or the web has nothing on a topic, it asks you for it here."));
    return h("section", { class: "sw-wants" }, h("h4", {}, "It wants"), ...open.map((w) => { const box = h("textarea", { rows: 2, placeholder: "Paste what you found, or a few lines you know", "aria-label": `Give it ${w.thing}` });
      return h("article", {}, h("b", {}, esc(w.thing)), h("p", {}, esc(w.said)), h("small", {}, `what brought it on: ${esc(w.because)}`), box,
        h("div", { class: "sw-wbtns" }, h("button", { type: "button", disabled: !!ctl.busy, onclick: () => box.value.trim() && act("give", () => api(`/char/want/${w.id}`, { method: "POST", body: JSON.stringify({ gift: box.value }) }).then(() => "given: it will read it and check it")) }, "Give it"),
          h("button", { type: "button", class: "ghost", disabled: !!ctl.busy, onclick: () => act("let go", () => api(`/char/want/${w.id}`, { method: "POST", body: "{}" }).then(() => "let go")) }, "Let it go"))); }),
      ...done.map((w) => h("p", { class: "sw-dmut" }, `${w.status === "given" ? "✓ you gave it" : "· let go:"} ${esc(w.thing)}`))); };
  const VERB = { reflect: "wrote a note on", evaluate: "judged at the gate", check: "verified", extract: "took names from", plan: "planned", ask: "asked", goal: "set goals from", wonder: "wondered about", bake: "consolidated", review: "reread a reply", fold: "folded", sort: "sorted", cycle: "ran", model: "swapped models" };
  function paintReport() {
    const d = rData; if (!d) return; const T = d.totals || {}, C = d.corrections || {}, L = d.learned || {}, D = d.disposition || {}, F = D.frontier || {}, HL = d.harness_loop || {};
    const trace = d.trace || [], notes = d.notes || [], cycles = d.cycles || [], skips = trace.filter((t) => t.outcome === "skipped"), why = Object.entries(skips.reduce((a, t) => ((a[t.detail] = (a[t.detail] || 0) + 1), a), {})).sort((a, b) => b[1] - a[1])[0];
    const who = esc(d.who).split(" ")[0];
    const head = !d.model?.up ? `${who} cannot learn: the model is not running.` : !n0(T.steps) ? `${who} has not taken a step yet.` : !n0(T.ok) ? `${who} is stuck: ${T.steps} steps, none did anything.` : `${who} has learned ${n0(L.verified)} thing${n0(L.verified) === 1 ? "" : "s"} it trusts, and turned away ${n0(L.rejected)}.`;
    if (!rSel && notes[0]) rSel = { note: notes[0].id };
    const loop = [2, 1, 0, 3].map((n) => (d.harness || []).find((s) => s.system === n)).filter(Boolean);
    const nRow = rSel?.note ? notes.find((n) => n.id === rSel.note) : null, step = rSel?.step ? trace.find((t) => tkey(t) === rSel.step) : null;
    const nd = nRow ? (noteCache.get(nRow.id)?.verdict === nRow.verdict || noteCache.get(nRow.id)?.loading ? noteCache.get(nRow.id) : (noteDetail(nRow.id, nRow.verdict), { loading: true })) : null;
    const inspect = () => !step && !nd ? h("p", { class: "sw-dmut" }, "Pick a row to see its whole story.") : h("div", {},
      step ? h("div", { class: "sw-dstep" }, h("h3", {}, `${sysTag(step.system)} ${step.kind} ${step.outcome === "ok" ? "did something" : step.outcome}`), h("p", { class: "sw-dmut" }, local(step.at)), h("p", {}, esc(step.detail) || "(no detail)")) : "",
      nd ? journey(nd) : step ? h("p", { class: "sw-dmut" }, "This step is not about one note.") : "");
    const noteRow = (n) => h("li", {}, h("button", { type: "button", "aria-current": String(rSel?.note === n.id && !rSel.step), onclick: () => { rSel = { note: n.id }; paintReport(); } },
      ic(n.gate ? (n.gate[0] === "admit" ? "yes" : "no") : n.verdict === "keep" ? "yes" : n.verdict === "drop" ? "no" : "wait"), h("b", {}, esc(n.topic)), h("time", {}, local(n.at)), h("p", {}, esc(n.text))));
    const split = (list, detail) => h("div", { class: "sw-dsplit" }, h("section", { class: "sw-dlist" }, ...list), h("section", { class: "sw-dsheet", "aria-label": "Detail" }, detail));
    const body = {
      chat: () => { cnet ||= makeChatNet(); if (cMesh) cnet.update(cMesh, cTurns); return cnet.el; }, // kept between repaints: the map keeps its layout and keeps moving
      journal: () => { const pg = jPages; // a page it wrote itself, in its voice, with the facts it was written from underneath
        const write = h("button", { type: "button", class: "sw-jwrite", disabled: !!ctl.busy, onclick: () => act("journal", () => api("/char/rest", { method: "POST", body: JSON.stringify({ char: true, only: "journal" }) }).then((r) => r.done ? (r.why || "nothing new to write about yet") : "wrote a page")) }, ctl.busy === "journal" ? "Writing…" : "Write a page now");
        const said = ctl.last?.label === "journal" ? h("small", { class: "sw-jsaid" }, String(ctl.last.out)) : "";
        if (!pg) return h("p", { class: "sw-dmut" }, "Opening its journal…");
        return h("div", { class: "sw-journal" }, h("div", { class: "sw-jhead" }, h("p", { class: "sw-dmut" }, pg.length ? `${pg.length} page${pg.length === 1 ? "" : "s"}. It writes one by itself after every three new notes.` : "No pages yet. It writes one by itself after every three new notes."), write, said),
          ...pg.map((p) => h("article", { class: "sw-jpage" }, h("header", {}, h("h3", {}, new Date(`${p.day}T12:00`).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })), h("time", {}, local(p.at))),
            h("p", { class: "sw-jbody" }, esc(p.text)),
            h("dl", { class: "sw-jfacts" },
              p.studied?.length ? [h("dt", {}, "Studied"), h("dd", {}, p.studied.map(esc).join(" · "))] : "",
              p.surprised?.length ? [h("dt", {}, "Got wrong"), h("dd", {}, ...p.surprised.map((g) => h("span", {}, `“${esc(g.guess)}” for ${esc(g.q)}, ${pct(g.surprise)} off`)))] : "",
              p.taught?.length ? [h("dt", {}, "You taught it"), h("dd", {}, p.taught.map(esc).join(" · "))] : "",
              p.next?.length ? [h("dt", {}, "Wants to know"), h("dd", {}, p.next.map(esc).join(" · "))] : "",
              h("dt", {}, "Talked with you"), h("dd", {}, `${p.chats} time${p.chats === 1 ? "" : "s"}`))))); },
      letter: () => letterBox(d) || h("p", { class: "sw-dmut" }, "Nothing to answer. After a run, what it needs from you shows up here."),
      story: () => { const done = trace.filter((t) => t.outcome === "ok").slice(0, 6), old = n0(D.curiosity) - n0(F.term);
        sty ||= makeStory(); sty.update(d, loop, cTurns);
        return h("div", { class: "sw-story" }, sty.el,
          h("div", { class: "sw-story2" },
            h("section", {}, h("h4", {}, "Just now"), done.length ? h("ol", { class: "sw-feed" }, ...done.map((t) => h("li", {}, h("button", { type: "button", onclick: () => { rSel = { step: tkey(t), note: t.ref }; go("activity"); } },
              h("time", {}, local(t.at)), h("p", {}, h("b", { style: `color:${SC[t.system] || "#d4d4d8"}` }, `${who} ${VERB[t.kind] || t.kind}`), ` ${esc(t.detail.split(":")[0])}`)))))
              : h("p", { class: "sw-dmut" }, "Nothing yet."), why ? h("p", { class: "sw-dmut sw-why" }, `When a step does nothing, it is most often because “${esc(why[0])}”.`) : ""),
            feels(d.life), wishes(d.life),
            youBox(d),
            h("section", {}, h("h4", {}, "Curiosity"), h("p", { class: "sw-big" }, h("strong", {}, r2(D.curiosity)), h("span", {}, `maturity ${r2(D.maturity)}`)),
              h("p", { class: "sw-dmut" }, `${r2(old)} comes from names it has met but not looked up, ${r2(F.term)} from the mesh still left open (${Math.round(n0(F.F) * 100)}% open, ${n0(F.D)} layers deep).`), lineChart(d.series || [])))); },
      notes: () => split([h("p", { class: "sw-dmut sw-lhead" }, `${notes.length} notes · ${n0(L.verified)} let in · ${n0(L.rejected)} turned away`), h("ol", { class: "sw-dl sw-dnotes" }, ...notes.map(noteRow))], inspect()),
      activity: () => { const steps = trace.filter((t) => (tFilter === "all" || t.outcome === tFilter) && (!tEngine || t.kind === tEngine) && (rSys == null || t.system === rSys)), eng = [...new Set(trace.map((t) => t.kind))].sort();
        const btn = (k, t) => h("button", { type: "button", "aria-pressed": String(tFilter === k), onclick: () => { tFilter = k; paintReport(); } }, t);
        const sel = h("select", { "aria-label": "Engine", onchange: (e) => { tEngine = e.target.value; paintReport(); } }, h("option", { value: "" }, "every engine"), ...eng.map((k) => h("option", { value: k, selected: k === tEngine }, k)));
        return split([h("div", { class: "sw-rtf" }, btn("all", "All"), btn("ok", "Did something"), btn("skipped", "Skipped"), btn("failed", "Failed"), sel, rSys != null ? h("button", { type: "button", "aria-pressed": "true", onclick: () => { rSys = null; paintReport(); } }, `only ${sysTag(rSys)}, clear`) : ""),
          h("ol", { class: "sw-dl sw-dsteps" }, ...steps.slice(0, 300).map((t) => { const k = tkey(t); return h("li", { class: rFresh.has(k) ? "new" : "" }, h("button", { type: "button", "data-o": t.outcome, "aria-current": String(rSel?.step === k), onclick: () => { rSel = { step: k, note: t.ref }; paintReport(); } },
            h("time", {}, local(t.at)), h("b", { style: `color:${SC[t.system] || "#d4d4d8"}` }, `${sysTag(t.system)} ${t.kind}`), h("span", {}, t.outcome === "ok" ? "did" : t.outcome), h("p", {}, esc(t.detail)))); }))], inspect()); },
      engines: () => h("div", { class: "sw-eng2" },
        h("div", { class: "sw-stages" }, ...loop.map((s) => { const st = stageOf(s), [name, role] = STAGE[s.system] || [s.name, s.does];
          return h("section", { style: `--c:${SC[s.system]}` }, h("h4", {}, `${sysTag(s.system)} ${name}`), s.system != null ? auraChip("chat", "Its steps run on") : "", h("p", { class: "sw-dmut" }, `${role}. ${s.on === false ? "Switched off." : ""}`),
            h("ul", {}, ...(s.engines || []).map((e) => { const n = n0(e.ok) + n0(e.skipped) + n0(e.failed);
              return h("li", {}, h("button", { type: "button", title: "Show this engine's steps", onclick: () => { tEngine = e.kind; rSys = null; go("activity"); } },
                h("span", {}, h("b", {}, e.kind), h("small", {}, n ? `${n0(e.ok)} of ${n} did something` : "never ran")),
                n ? h("i", { class: "sw-bar" }, h("b", { style: `flex:${n0(e.ok)}` }), h("b", { class: "sk", style: `flex:${n0(e.skipped)}` }), h("b", { class: "fa", style: `flex:${n0(e.failed)}` })) : "",
                e.blocked ? h("p", {}, `Blocked: ${esc(e.blocked)}`) : e.last && e.last.outcome !== "ok" ? h("p", {}, `Last time: ${esc(e.last.detail)}`) : "")); }))); })),
        h("section", { class: "sw-cyc" }, h("h4", {}, "Harness cycles"), h("p", { class: "sw-auras" }, "plans on ", auraChip("planner", "The planner runs on"), " · judges on ", auraChip("judge", "The Verifier runs on")), cycles.length ? h("p", { class: "sw-dmut" }, `${n0(HL.cycles_run)} cycles: the planner proposed ${n0(HL.proposed)} commands, the controller rejected ${n0(HL.rejected)}, ${n0(HL.executed)} ran and the Verifier kept ${n0(HL.kept)}. ${n0(HL.swaps)} model swaps took ${n0(HL.swap_seconds)} s.`) : "",
          cycles.length ? h("ol", { class: "sw-dl sw-dnotes" }, ...cycles.slice(0, 8).map((c) => h("li", {}, h("button", { type: "button", "aria-current": String(rCyc === c.cycle), onclick: () => { rCyc = rCyc === c.cycle ? null : c.cycle; paintReport(); } },
              ic((c.verdicts || []).some((v) => v.keep) ? "yes" : (c.executed || []).length ? "wait" : "no"), h("b", {}, `Cycle ${c.cycle}`), h("time", {}, `${(c.executed || []).length} ran`),
              h("p", {}, rCyc === c.cycle ? [...(c.rejected || []).map((r) => `rejected ${r.cmd}: ${r.why}`), ...(c.executed || []).map((r) => `${r.cmd}: ${r.outcome} ${r.detail}`), ...(c.verdicts || []).map((v) => `${v.keep ? "kept" : "dropped"} ${v.cmd}: ${v.why}`)].join(" · ") : (c.proposed || []).join(" · "))))))
            : h("p", { class: "sw-dmut" }, "No cycles yet. Run one from Controls, or switch to planner mode."))),
      controls: () => { const R = ctl.roles, sw = ctl.swap;
        return h("div", { class: "sw-ctl" },
          (() => { // a training run: it learns by itself until the time, the steps or the curiosity target says stop
            const T = d.train || {}, run = T.runs?.[0], live = !!T.active && run && ["running", "paused"].includes(run.status), C = (ctl.tcfg ||= { ...(T.defaults || { minutes: 20, lo: 0, hi: 1, max_steps: 60 }) });
            const send = (action, extra = {}) => act(`training ${action}`, () => api("/char/train", { method: "POST", body: JSON.stringify({ action, ...extra }) }).then((r) => r.status || action));
            const num = (k, label, min, max, step) => h("label", {}, label, h("input", { type: "number", min, max, step, value: (live ? run.config : C)[k], disabled: live, oninput: (e) => { C[k] = +e.target.value; } }));
            const snaps = ctl.snaps?.list, ds = ctl.ds, V = live ? run.config : C; // a live run shows its own settings, not the next run's
            const stopped = !live && run ? `Run ${run.id} ${run.status === "done" ? "finished" : run.status}${run.why ? `: ${run.why}` : ""}.` : "";
            return h("section", { class: "sw-train" }, h("h4", {}, "Training run"),
              h("div", { class: "sw-tblock" }, h("h5", {}, h("b", {}, "1"), "Set the run"),
              h("p", { class: "sw-dmut" }, "It learns on its own and stops at whichever comes first: the minutes run out, the steps are used up, or curiosity comes down into the target range."),
              h("div", { class: "sw-tcfg" }, num("minutes", "Minutes", 1, 600, 1), num("max_steps", "Steps", 1, 1000, 1), h("label", { class: "sw-trange" }, "Curiosity target",
                h("span", {}, h("input", { type: "number", min: 0, max: 5, step: 0.05, value: V.lo, disabled: live, "aria-label": "from", oninput: (e) => { C.lo = +e.target.value; } }), "–",
                  h("input", { type: "number", min: 0, max: 5, step: 0.05, value: V.hi, disabled: live, "aria-label": "to", oninput: (e) => { C.hi = +e.target.value; } }))))),
              h("div", { class: "sw-tblock" }, h("h5", {}, h("b", {}, "2"), "Run it"), h("div", { class: "sw-tdeck" },
                h("button", { type: "button", class: "sw-tplay", "aria-label": !live ? "Start" : run.status === "paused" ? "Resume" : "Pause", disabled: !live && (!!ctl.busy || !d.model?.up),
                  onclick: () => !live ? send("start", { minutes: C.minutes, max_steps: C.max_steps, lo: Math.min(C.lo, C.hi), hi: Math.max(C.lo, C.hi) }) : send(run.status === "paused" ? "resume" : "pause") }, !live || run.status === "paused" ? "▶" : "❚❚"),
                h("button", { type: "button", class: "sw-tstop", "aria-label": "Stop", disabled: !live, onclick: () => send("stop") }, "■"),
                h("span", { class: "sw-dmut" }, ctl.busy ? "…" : live ? (run.status === "paused" ? "Paused" : "Learning on its own. Watch it on Story.") : stopped || "Ready"))),
              h("div", { class: "sw-tblock" }, h("h5", {}, h("b", {}, "3"), "Results"), !(T.runs || []).length ? h("p", { class: "sw-dmut" }, "No runs yet. Each run keeps checkpoints and a fine-tuning dataset.") : "",
              (T.runs || []).length ? h("ol", { class: "sw-truns" }, ...T.runs.slice(0, 5).map((r) => h("li", {}, h("b", {}, `Run ${r.id}`), h("span", {}, `${r.status} · ${n0(r.snaps)} checkpoints`),
                h("button", { type: "button", "aria-pressed": String(ctl.snaps?.id === r.id), onclick: () => { if (ctl.snaps?.id === r.id) { ctl.snaps = null; return report(true); } api(`/char/train/${r.id}/snapshots`).then((x) => { ctl.snaps = { id: r.id, list: x.snapshots }; ctl.ds = null; report(true); }); } }, "View"),
                n0(r.examples) ? h("button", { type: "button", "aria-pressed": String(ctl.ds?.id === r.id), onclick: () => { if (ctl.ds?.id === r.id) { ctl.ds = null; return report(true); } fetch(`/char/train/${r.id}/dataset.jsonl`).then((x) => x.text()).then((t) => { ctl.ds = { id: r.id, lines: t.trim().split("\n").filter(Boolean) }; ctl.snaps = null; report(true); }); } }, "Dataset") : ""))) : "",
              ds ? h("div", { class: "sw-tsnaps" }, h("p", { class: "sw-dmut" }, `Run ${ds.id}: ${ds.lines.length} fine-tuning examples (Claude format, one per line) · `, h("a", { href: `/char/train/${ds.id}/dataset.jsonl`, download: `run-${ds.id}.jsonl`, target: "_blank" }, "Save .jsonl")),
                ...ds.lines.map((l, i) => { let j = {}; try { j = JSON.parse(l); } catch {} const u = j.messages?.find((m) => m.role === "user")?.content, a = j.messages?.find((m) => m.role === "assistant")?.content;
                  return h("details", {}, h("summary", {}, `${i + 1}. ${esc(u || "").slice(0, 90)}`), h("p", {}, h("b", {}, "User "), esc(u)), h("p", {}, h("b", {}, "Sagira "), esc(a))); })) : "",
              snaps ? h("div", { class: "sw-tsnaps" }, h("p", { class: "sw-dmut" }, `Run ${ctl.snaps.id}: ${snaps.length} checkpoints`), ...snaps.map((x) => h("details", {}, h("summary", {}, `Step ${x.step} · ${x.why}`),
                h("p", {}, esc(x.prompt)), ...[["Works", x.works], ["Fails", x.fails]].map(([t, g]) => h("div", { class: "sw-tgrp" }, h("b", {}, t), ...Object.entries(g || {}).filter(([, v]) => v.length).map(([k, v]) => h("p", {}, h("i", {}, `${k}: `), v.slice(0, 3).map(esc).join(" · "))))),
                h("p", { class: "sw-dmut" }, `${(x.examples || []).length} examples`)))) : "")); })(),
          h("section", {}, h("h4", {}, "Models"),
            sw?.busy ? h("div", { class: "sw-dswap" }, h("p", {}, `Swapping ${esc(sw.from) || "none"} for ${esc(sw.to)}, ${esc(sw.phase)}`), h("i", { style: `--f:${n0(sw.fraction)}` })) : "",
            !R ? h("p", { class: "sw-dmut" }, "Loading…") : R.error ? h("p", { class: "sw-dmut" }, "Could not read settings.") : h("form", { class: "sw-droles", onsubmit: (e) => { e.preventDefault(); act("save models", () => api("/settings", { method: "PATCH", body: JSON.stringify(R) }).then(() => "models saved")); } },
              ...[["planner_model", "Planner"], ["chat_model", "Replies"], ["judge_model", "Verifier"]].map(([k, t]) => h("label", { class: "sw-aurad", style: `--aura:${auraOf(R[k] || ctl.loaded)}` }, t,
                h("select", { onchange: (e) => { R[k] = e.target.value; } }, h("option", { value: "" }, `Default (${short(ctl.loaded) || "the loaded model"})`),
                  ...[...new Set([...(ctl.models || []), ...(R[k] ? [R[k]] : [])])].map((id) => h("option", { value: id, selected: id === R[k] }, short(id)))))),
              h("button", { type: "submit", disabled: !!ctl.busy }, "Save models"))),
          h("details", { class: "sw-cmore", open: ctl.more || null, ontoggle: (e) => { ctl.more = e.target.open; } }, h("summary", {}, "Learning settings"), h("div", { class: "sw-dseg", role: "radiogroup", "aria-label": "Learning mode" }, ...Object.keys(MODE_DOES).map((m) => h("button", { type: "button", role: "radio", "aria-checked": String(d.mode === m), disabled: !!ctl.busy, onclick: () => act(`mode ${m}`, () => api("/char/wiring", { method: "POST", body: JSON.stringify({ mode: m }) }).then(() => `now ${m}`)) }, m))),
            h("p", { class: "sw-dmut" }, MODE_DOES[d.mode] || ""),
            h("label", { class: "sw-cdial" }, h("span", {}, h("b", {}, "Curiosity dial"), h("output", {}, `×${n0(D.dial ?? 1)}`)),
              h("input", { type: "range", min: 0, max: 3, step: 0.25, value: D.dial ?? 1, disabled: !!ctl.busy, "aria-label": "Curiosity dial", oninput: (e) => { e.target.previousSibling.lastChild.textContent = `×${e.target.value}`; },
                onchange: (e) => act("curiosity dial", () => api("/char/dial", { method: "POST", body: JSON.stringify({ curiosity: +e.target.value }) }).then((r) => `dial ×${r.dial}, curiosity now ${r.disposition.curiosity}`)) }),
              h("small", {}, "0 stops it reaching out and keeps replies to the point. 1 is the formula. Above 1 it learns harder and asks you back.")),
            (() => { const K = d.tracker || {}, num = (k, label) => h("label", {}, label, h("input", { type: "number", min: 0.5, max: 50, step: 0.5, value: K[k] ?? 3, disabled: !!ctl.busy,
                onchange: (e) => act(label, () => api("/char/tracker", { method: "POST", body: JSON.stringify({ [k]: +e.target.value }) }).then((r) => `sleeps at ${r.sleep_at}, max ${r.max}`)) }));
              return h("div", { class: "sw-cpush" }, h("span", {}, h("b", {}, "Your push"), h("output", {}, `+${n0(K.momentum ?? 0)} of ${n0(K.sleep_at ?? 3)}`)),
                h("i", { style: `--f:${Math.min(1, (K.momentum || 0) / (K.sleep_at || 3))}`, "data-asleep": String(!!K.asleep) }),
                h("small", {}, K.asleep ? "Asleep: learning the way you told it to grow. It wakes when the push is spent." : K.asking ? "It is asking you which way to grow. Answer in the chat." : `Say “learn more”, “go explore”, “dig deeper” in the chat: ${(K.ups ?? 0) % (K.every || 10)} of ${K.every || 10} ups toward +1. At the threshold it asks which way to grow, then sleeps to learn it.`),
                h("div", { class: "sw-cnums" }, num("sleep_at", "sleeps at"), num("max", "max"))); })(),
            h("ul", { class: "sw-dsw" }, ...loop.map((s) => h("li", { style: `--c:${SC[s.system]}` }, h("span", {}, h("b", {}, `${sysTag(s.system)} ${STAGE[s.system]?.[0] || s.name}`), h("small", {}, STAGE[s.system]?.[1] || "")),
              h("button", { type: "button", role: "switch", "aria-checked": String(s.on !== false), "aria-label": `${sysTag(s.system)} ${STAGE[s.system]?.[0] || ""}`, disabled: !!ctl.busy, onclick: () => act(`${sysTag(s.system)} ${s.on === false ? "on" : "off"}`, () => api("/char/systems", { method: "POST", body: JSON.stringify({ id: s.system, on: s.on === false }) }).then(() => `${sysTag(s.system)} ${s.on === false ? "on" : "off"}`)) }, h("i", {}))))))); },
    };
    const keep = [...panel.querySelectorAll(".sw-dlist, .sw-dsheet, .sw-dbody")].map((x) => x.scrollTop);
    const stTop = sty?.el.scrollTop || 0; // re-attaching the story would reset it to the first slide
    panel.replaceChildren(h("div", { class: "sw-db" },
      h("header", { class: "sw-dtop" }, h("h2", {}, head), h("p", {}, h("i", { class: "sw-lamp", "data-up": String(!!d.model?.up) }), ` ${esc(d.model?.label)} · since ${local(d.since)} · ${esc(d.mode)} mode · ${n0(T.ok)} of ${n0(T.steps)} steps did something`),
        h("nav", { class: "sw-dtabs", role: "tablist", "aria-label": "Report sections" }, ...TABS.map(([k, t]) => h("button", { type: "button", role: "tab", "aria-selected": String(rTab === k), onclick: () => go(k) }, t, k === "letter" && d.letter?.items?.length ? h("sup", { class: "sw-lcount" }, String(d.letter.items.length)) : "")))),
      h("div", { class: "sw-dbody" }, body[rTab]())));
    panel.querySelectorAll(".sw-dlist, .sw-dsheet, .sw-dbody").forEach((x, i) => { x.scrollTop = keep[i] || 0; });
    if (sty?.el.isConnected && stTop) sty.el.scrollTop = stTop;
  }
  const tkey = (t) => `${t.at}|${t.kind}|${t.outcome}|${t.detail}`;
  async function pullReport(force) {
    if (!reporting || !root.isConnected) { clearInterval(rTimer); rTimer = 0; return; }
    if (force !== true && !rData?.train?.active && Date.now() - rLast < 4800) return; // a live run is pulled every 2 s, the rest every 5
    rLast = Date.now();
    const typing = ctl.dragging || (panel.contains(document.activeElement) && /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName));
    if (rTab === "engines") loadRoles();
    if (rTab === "controls") { loadRoles(); try { ctl.swap = await api("/model/swap"); } catch { ctl.swap = null; } }
    if (rTab === "journal") { try { jPages = (await api("/char/journal")).pages; } catch { jPages = jPages || []; } }
    if (rTab === "story") { try { [cTurns, sMesh] = await Promise.all([api("/char").then((x) => x.turns), api("/char/mesh")]); } catch { /* the next pull tries again */ } } // its last words, beside Dot
    if (rTab === "chat") { try { const [m, c, t] = await Promise.all([api("/char/mesh"), api("/char"), api("/char/tools").catch(() => ({ nodes: [], edges: [] }))]);
      cMesh = { nodes: [...m.nodes, ...t.nodes], edges: [...m.edges, ...t.edges] }; cTurns = c.turns; cnet?.update(cMesh, cTurns); } catch { /* the next pull tries again */ } } // its tools join the map here only: the 3D globe keeps to its own layers
    try { rData = await api("/char/report"); const ks = new Set((rData.trace || []).map(tkey)); rFresh = rSeen ? new Set([...ks].filter((k) => !rSeen.has(k))) : new Set(); rSeen = ks; if (force === true || !typing) paintReport(); }
    catch { if (!rData) panel.replaceChildren(h("p", { class: "sw-rh" }, "Report unavailable (the server may need a restart)")); else panel.prepend(h("p", { class: "sw-rh" }, "Report unavailable (the server may need a restart)")); }
  }
  document.addEventListener("submit", () => { if (reporting && rTab === "chat") for (const ms of [800, 4000, 10000, 20000]) setTimeout(() => pullReport(), ms); }, true);
  function report(on = !reporting) {
    reporting = on; root.classList.toggle("sw-reporting", on); panel.hidden = !on; reportBtn.textContent = on ? "← Mesh" : "Report"; reportBtn.setAttribute("aria-pressed", String(on));
    clearInterval(rTimer); rTimer = 0; rSeen = null; if (on) { pullReport(); rTimer = setInterval(pullReport, 2000); }
  }
  menu.append(h("small", {}, "View"), h("span", {}, h("button", { type: "button", onclick: () => { shut(); report(); } }, "Report"), h("button", { type: "button", title: "Or click its eyes, or press i", onclick: () => { shut(); setImmerse(!immerse); } }, "Immersive")));
  // the page always opens on the mesh, so you see it grow; the report is one click away
  markTint(); refresh(); frame();
  function expand(on = !growTo) { growTo = on ? 1 : 0; if (on) Object.keys(seen).filter((k) => HOME[k]).forEach(agentOf); rings.push(0); status.textContent = on ? "Dot holds the whole net now. /expand-to-net again to gather it back." : "Dot gathers back to its centre."; }
  return { expand, report, palette, data, say, heard, fire, stepped, refresh, reform: (c) => { if (c) form = c; }, follow, emote: (k) => { want = EMO[k] ? k : Object.keys(EMO)[Math.random() * Object.keys(EMO).length | 0]; }, chatOff: () => root.classList.contains("asleep") ? "I'm asleep. Commands still work: type /. Or knock on me three times." : learning ? "I'm learning the way you told me to grow, so chat is paused for now. Commands still work: type /." : root.dataset.mode === "sleeping" ? "I'm asleep, so chat is off. Type /wake to wake me, or / for the other commands." : "",
    dotAt: () => lastDot && lay > .3 ? [...lastDot] : null, busy: () => { busy = true; } };
}
