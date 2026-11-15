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

  const COL = { plan: "#ffb347", question: "#ffe347", verified: "#7dffa8", rejected: "#ff6b6b", unchecked: "#8b93a7", name: "#e8ecf4", curious: "#ffb347", idea: "#c79bff", you: "#9fb4ff", mistake: "#ff6b6b", trait: "#ff7ac6" };
  const colour = (n) => n.layer === "note" ? COL[n.state] : n.layer === "name" ? (n.kind === "idea" ? COL.idea : n.state === "known" ? COL.name : COL.curious) : n.layer === "chat" ? (n.state === "mistake" ? COL.mistake : n.kind === "you" ? COL.you : tint) : n.layer === "question" && n.state === "open" ? "#a89a4a" : COL[n.layer];
  const hoverAt = (q) => ptr && Math.hypot(q.x - ptr[0], q.y - ptr[1]) < 30;
  const RS0 = 290; let bandY = {}, RS = RS0; // the globe grows with what it knows, so nodes keep their room
  let planes = {}, W = 1, H = 1, K = 1, cx = 0, cy = 0, nodes = [], edges = [], vars = [], tint = "#6ff7ff", proj = [];
  const EYES = { extract: "read", sort: "read", practise: "read", fill: "read", reflect: "search", wonder: "search", ideas: "search", plan: "think", goal: "think", ask: "think",
    check: "verify", review: "verify", evaluate: "verify", fold: "fold", bake: "fold" };
  const SYSC = { 2: "#c79bff", 1: "#ffb347", 0: "#6ff7ff", 3: "#7dffa8" }, VERB_OF = { read: "reading", search: "searching", think: "thinking", verify: "checking", fold: "folding" };
  // expanded, each job is its own character: a small body in its system's colour, walking the net to the nodes it works on
  const HOME = { reflect: "question", wonder: "question", ideas: "name", plan: "plan", goal: "question", ask: "question", check: "note", review: "chat", evaluate: "note",
    extract: "note", sort: "chat", practise: "chat", fill: "trait", fold: "name", bake: "note" }, sysOf = {};
  let agents = [];
  const pickNode = (k) => { const pool = nodes.filter((n) => n.layer === HOME[k] && !hide.has(n.layer)); return (pool.length ? pool : nodes)[Math.random() * (pool.length || nodes.length) | 0]; };
  function agentOf(k) { return agents.find((a) => a.k === k) || (agents.push({ k, x: cx, y: cy, n: null, work: 0, ph: Math.random() * 99, vx: 0 }), agents.at(-1)); }
  function walk() { // each character heads for its node, works there with its eyes, then wanders to another of its kind; contracting, they all go home into Dot
    if (!agents.length) return;
    for (const a of agents) {
      let tx = cx, ty = cy;
      if (growTo) { if (!a.n || (a.work <= 0 && Math.random() < .004)) a.n = pickNode(a.k); const q = a.n && proj[nodes.indexOf(a.n)]; if (q) { tx = q.x; ty = q.y - 16; } }
      const px0 = a.x; a.x += (tx - a.x) * (still ? 1 : .03); a.y += (ty - a.y) * (still ? 1 : .03); a.vx = a.x - px0; if (a.work > 0) a.work--;
      const c = SYSC[sysOf[a.k]] || tint, r = 14 * K, t = tick * .06 + a.ph, bob = still ? 0 : Math.sin(t) * 2;
      g.globalAlpha = growTo ? .95 : Math.min(.95, Math.hypot(a.x - cx, a.y - cy) / 60); const gr = g.createRadialGradient(a.x - r * .35, a.y + bob - r * .4, r * .1, a.x, a.y + bob, r);
      gr.addColorStop(0, "#fff"); gr.addColorStop(.35, c); gr.addColorStop(1, "#0b1320"); g.fillStyle = gr; g.beginPath(); g.arc(a.x, a.y + bob, r, 0, 6.283); g.fill();
      const mode = a.work > 0 ? EYES[a.k] : "", ph = 260 - a.work; let ex2 = Math.max(-2.5, Math.min(2.5, a.vx * 2)), ey2 = 0, lid = 1;
      if (mode === "read") { ex2 = -2.5 + (ph % 50) / 50 * 5; ey2 = 1; } else if (mode === "search") { ex2 = Math.sin(ph * .12) * 2.5; ey2 = -2; } else if (mode === "think") ey2 = -2.5;
      else if (mode === "verify") lid = .4; else if (mode === "fold") lid = .2;
      g.fillStyle = "#06222a"; for (const o of [-4.8, 4.8]) { g.beginPath(); g.ellipse(a.x + o * K + ex2 * K, a.y + bob + ey2 * K, 2.2 * K, Math.max(.8, 5.4 * K * lid * (tick % 170 > 165 ? .15 : 1)), 0, 0, 6.283); g.fill(); }
      if (a.work > 0 || growTo) { g.font = "600 11px ui-monospace, monospace"; g.textAlign = "center"; g.globalAlpha = a.work > 0 ? 1 : .7; g.fillStyle = c; g.fillText(a.work > 0 ? `${a.k} · ${VERB_OF[mode] || "working"}` : a.k, a.x, a.y + bob - r - 6); }
      g.globalAlpha = 1;
    }
    if (!growTo) agents = agents.filter((a) => Math.hypot(a.x - cx, a.y - cy) > 6);
  }
  let form = null, formOf = "", cb = 0; // its chibi form: the live persona's look from /char/chibi, and how far it has morphed into it
  let eyeTask = null, grow = 0, growTo = 0, detached = false, learning = false, lift = 1, yaw = .5, pitch = -.45, drag = null, moved = 0, tick = 0, ptr = null, ex = 0, ey = 0, happy = 0, blinkAt = 120, talk = 0, morph = 0, slab = null, wet = 1, px = 0, py = 0, busy = false, lit = -1, litT = 0, sparks = [], rings = [], gulp = [];
  const hash = (t) => [...t].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  function fit() { const d = devicePixelRatio || 1; W = root.clientWidth; H = root.clientHeight; cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0); K = Math.max(.4, Math.min(W / (2 * RS + 280), H / (2 * RS + 130), 1.4)); cx = W / 2; cy = H * .47; }
  const ro = new ResizeObserver(() => root.isConnected ? fit() : ro.disconnect()); ro.observe(root); fit();
  function P(x, y, z) { y *= lift; const a = Math.cos(yaw), b = Math.sin(yaw), c = Math.cos(pitch), d = Math.sin(pitch), x1 = x * a + z * b, z1 = -x * b + z * a, y1 = y * c - z1 * d, z2 = y * d + z1 * c, s = 700 / (700 + z2 * K);
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
    const order = LAYERS.map(([k]) => k).filter((k) => by[k]), N = order.reduce((s2, k) => s2 + by[k].length, 0); RS = RS0 * Math.min(1.7, Math.max(1, Math.sqrt(N / 80))); fit(); let k0 = 0; bandY = {};
    for (const layer of order) { const list = by[layer], ys = [];
      list.forEach((x, i) => { const u = 1 - 2 * (k0 + i + .5) / N, rr = RS * Math.sqrt(1 - u * u), a = (k0 + i) * 2.39996, o = old.get(x.id); ys.push(u * RS);
        nodes.push({ ...x, key: x.id, x: rr * Math.cos(a), y: -u * RS, z: rr * Math.sin(a), R: rr, flash: o ? o.flash : old.size ? 70 : 0, born: o || !old.size ? 1 : 0 }); });
      const mid = -(ys[0] + ys.at(-1)) / 2; bandY[layer] = mid; k0 += list.length; }
    const at = new Map(nodes.map((n, i) => [n.id, i]));
    edges = m.edges.map(([a, b]) => [at.get(a), at.get(b)]).filter((e) => e[0] != null && e[1] != null);
    planes = Object.fromEntries(Object.keys(by).filter((k) => bandY[k] != null).map((k) => [k, RS * Math.sqrt(Math.max(0, 1 - (bandY[k] / RS) ** 2))]));
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
    root.dataset.mode = d.mode; const T = d.tracker || {}; learning = !!T.asleep; modeChip.textContent = T.asleep ? "learning" : T.asking ? "asking" : d.mode;
    modeChip.style.setProperty("--p", String(Math.min(1, (T.momentum || 0) / (T.sleep_at || 3)))); modeChip.dataset.halo = T.asleep ? "asleep" : T.asking ? "asking" : "";
    modeChip.title = `Momentum ${T.momentum ?? 0} of ${T.sleep_at ?? 3}: ${T.ups ?? 0} ups said; every ${T.every ?? 10} add 1. ${T.asleep ? "Asleep, learning the way you told it to grow; it wakes when the push is spent." : "At the threshold it asks which way to grow, then sleeps to learn it."}`;
    paintTrack(T); if (ear) ear.placeholder = d.mode === "sleeping" ? `${d.who.split(" ")[0]} is asleep. Type /wake to wake it` : `Talk to ${d.who.split(" ")[0]}…`;
    engines();
    const braked = d.wires[0]?.holding; // one line that says what you can do right now
    const q = d.review?.open; asking = q || null; // the correction loop, as talk: it says what went wrong, and your next message is the answer
    hint.replaceChildren(detached ? "The model is detached: the harness lies flat until it is back." : q?.kind === "direction" ? h("span", {}, "It asks which way to grow. Your next message sets it. ", h("button", { type: "button", class: "sw-skip", onclick: skipAsk }, "Skip"))
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
    const close = h("button", { type: "button", class: "sw-x", "aria-label": "Close details", onclick: () => { note.hidden = true; cv.focus(); } }, "✕");
    const i = nodes.indexOf(n), near = edges.filter((e) => e.includes(i)).map((e) => nodes[e[0] === i ? e[1] : e[0]]);
    const STATE = { verified: "verified by the Verifier", rejected: "rejected by the Verifier", unchecked: "not checked yet", answered: "answered by a note", open: "not answered yet", dropped: "dropped", known: "read about", curious: "not read about yet: it is curious", ok: "reread by the Verifier: fine", mistake: "reread by the Verifier: a mistake" };
    note.replaceChildren(close, h("small", {}, `${LY[n.layer].t}${n.kind && n.layer !== "name" ? ` · ${n.kind}` : ""}${n.state ? ` · ${STATE[n.state] || n.state}` : ""}`),
      h("h3", {}, n.layer === "chat" ? (n.kind === "you" ? "You said" : "It said") : n.label), h("p", {}, n.body || (n.n ? `In ${n.n} note${n.n === 1 ? "" : "s"}.` : "")),
      ...(near.length ? [h("small", {}, "Wired to"), h("ul", { class: "sw-wired" }, ...near.slice(0, 14).map((x) => h("li", {}, h("button", { type: "button", style: `--c:${colour(x)}`, onclick: () => { x.flash = 70; openNote(x); } }, h("small", {}, LY[x.layer].t), " ", x.label.slice(0, 70)))))] : []));
    shut(); note.hidden = false; close.focus();
  }
  function palette(list, active = 0, pick) { // the commands, as Dot: it shrinks away and the list takes its place, with its eyes on top
    if (!list) { if (!cmds.hidden) { cmds.hidden = true; if (bubble.hidden || bubble.classList.contains("out")) slab = null; } return; }
    const tip = h("p", { class: "sw-cmd-tip", "aria-live": "polite" }, list[active]?.does || "No command starts like that.");
    cmds.replaceChildren(h("span", { class: "sw-cmd-eyes", "aria-hidden": "true" }, h("i", {}), h("i", {})),
      ...list.map((c, i) => h("button", { type: "button", role: "option", "aria-selected": String(i === active), title: c.does,
        onmouseenter: () => { tip.textContent = c.does; }, onmouseleave: () => { tip.textContent = list[active]?.does || ""; },
        onmousedown: (e) => { e.preventDefault(); pick?.(c); } }, c.name)), tip);
    cmds.hidden = false; bubble.classList.add("out"); slab = { w: 1, h: 1 };
  }
  // ---- things space.js tells it ----
  function say(t) { // the reply IS Dot: it pours out of its sphere into liquid letters, and its eyes play along the words; then it gathers back
    rings.push(0); happy = 0;
    const n = t.text.length, words = t.text.split(/(\s+)/), p = h("p", { style: `font-size:${n <= 60 ? 32 : n <= 150 ? 25 : n <= 320 ? 20 : 17}px` });
    words.forEach((w, i) => { if (/^\s+$/.test(w)) return p.append(w); const sp = h("span", {}, w); p.append(sp);
      if (!still) sp.animate([{ opacity: 0, translate: "0 18px", scale: "1.3 .5" }, { opacity: 1, translate: "0 0", scale: "1 1" }], { duration: 560, delay: 260 + Math.min(i * 30, 3200), easing: "cubic-bezier(.2,1.5,.4,1)", fill: "backwards" }); });
    ink.replaceChildren(p, drop);
    chipsEl.replaceChildren(...(t.events || []).filter((e) => e.name).map((e) => h("span", { class: "rule" }, e.name)), ...(t.drew || []).slice(0, 4).map((x) => h("span", {}, x.title.replace(/^\w+: /, ""))));
    bubble.hidden = false; bubble.classList.remove("out"); slab = { w: ink.offsetWidth, h: p.offsetHeight }; wet = 1; px = slab.w / 2; py = -20; talk = Math.min(60 + words.length * 3, 300);
    clearTimeout(say.t); say.t = setTimeout(() => { bubble.classList.add("out"); slab = null; }, Math.max(11000, words.length * 400));
    refresh();
    return new Promise((r) => setTimeout(r, still ? 0 : Math.min(words.length * 30 + 900, 3600)));
  }
  function heard(text) { bubble.classList.add("out"); slab = null; clearTimeout(say.t); gulp.push({ text: text.length > 34 ? `${text.slice(0, 33)}…` : text, t: 0 }); } // your words rise from the box and Dot takes them in
  function fire(names) { for (const nm of names || []) { const n = nodes.find((x) => x.label === nm); if (n) { n.flash = 70; sparks.push({ n, t: 0 }); } } } // what a reply drew on lights up and sends a spark in
  function stepped(r) { busy = false; if (!r || r.done) return; lit = r.system; litT = 260; rings.push(0);
    const hit = nodes.filter((n) => n.kind !== "note" && `${r.topic} ${r.note}`.toLowerCase().includes(n.label.toLowerCase())).sort((a, b) => b.label.length - a.label.length).slice(0, 2);
    hit.forEach((n) => { n.flash = 70; sparks.push({ n, t: 0 }); }); if (r.kind === "reflect" || r.kind === "check") happy = 70; refresh(); }

  // ---- drawing ----
  function dot(mood, asleep) {
    morph += ((slab ? 1 : 0) - morph) * (still ? 1 : .08); const m = morph * morph * (3 - 2 * morph); // 1 = all of it has poured into the words
    const quiet = asleep || root.dataset.mode === "quiet", t = tick * (quiet ? .018 : .045), bob = still ? 0 : Math.sin(t * .7) * 5 * K, y = cy + bob + m * 30 * K, R = 82 * K * (1 - m * .93) * (1 + grow * Math.max(0, (planes.chat || 260) / 82 - 1)), sq = 1 + Math.sin(t) * .03;
    rings = rings.map((r) => r + 2.4).filter((r) => r < 80); for (const r of rings) { g.strokeStyle = tint; g.globalAlpha = (1 - r / 80) * (1 - m); g.lineWidth = 2; g.beginPath(); g.arc(cx, cy, 82 * K + r * K, 0, 6.283); g.stroke(); } g.globalAlpha = 1;
    if (m > .97) return;
    cb += ((form && !detached && grow < .3 ? 1 : 0) - cb) * (still ? 1 : .03); const c = cb * cb * (3 - 2 * cb), sy = y - R * .3 * c, sr = R * (1 - .38 * c); // sphere -> chibi: the sphere rises and shrinks into its head
    g.strokeStyle = tint; g.globalAlpha = (.1 + .06 * Math.sin(t)) * (1 - m) * (1 - grow); g.lineWidth = 10 * K; g.beginPath(); g.arc(cx, y, R + 12 * K, 0, 6.283); g.stroke(); g.globalAlpha = 1;
    if ((busy || mood === "think") && grow < .3) { g.strokeStyle = "#ffb347"; g.lineWidth = 2.5; g.lineCap = "round"; for (let i = 0; i < 3; i++) { const a = tick * .07 + i * 2.094; g.beginPath(); g.arc(cx, y, R + 24 * K, a, a + .9); g.stroke(); } } // looking something up, or thinking
    const body = (asleep ? .6 : detached ? .38 : 1) * (1 - grow), gr = g.createRadialGradient(cx - sr * .34, sy - sr * .4, sr * .1, cx, sy, sr); gr.addColorStop(0, "#ffffff"); gr.addColorStop(.3, tint); gr.addColorStop(1, "#0d3a42"); g.fillStyle = gr; g.globalAlpha = body * (1 - c); g.beginPath();
    for (let a = 0; a <= 6.3; a += .12) { const r = sr * (1 + (still ? 0 : .022 * Math.sin(3 * a + t * 1.3) + .016 * Math.sin(5 * a - t * 1.7))), qx = cx + Math.cos(a) * r * sq, qy = sy + Math.sin(a) * r / sq; a ? g.lineTo(qx, qy) : g.moveTo(qx, qy); }
    g.closePath(); g.fill(); g.globalAlpha = 1;
    const F = form && c > .01 ? drawChibi(g, cx, y, R, form, tint, c, t, body) : { x: cx, y, s: 1, ink: "#06222a" }; // where its eyes go: on the chibi's face once it has one
    if (grow > .55) return; // dissolved into the net: its jobs walk it now
    let tx = Math.sin(yaw * 1.3) * 9, ty = mood === "think" || busy ? -9 : pitch * -8; if (ptr && !busy) { tx = Math.max(-13, Math.min(13, (ptr[0] - cx) * .08)); ty = Math.max(-10, Math.min(10, (ptr[1] - F.y) * .08)); }
    const task = eyeTask && tick < eyeTask.until && !still ? EYES[eyeTask.kind] : "", ph = tick - (eyeTask?.until ?? 0) + 260; let lid = 1;
    if (task === "read") { tx = -12 + (ph % 70) / 70 * 24; ty = 2 + (Math.floor(ph / 70) % 3) * 3; } // line by line, left to right
    else if (task === "search") { tx = Math.sin(ph * .09) * 13; ty = -9; } // up and scanning: out on the web
    else if (task === "think") { tx = Math.sin(ph * .025) * 6; ty = -11; } // eyes up, turning it over
    else if (task === "verify") { tx = Math.sin(ph * .04) * 4; lid = .42; } // a squint: checking its own work
    else if (task === "fold") { lid = .18 + .12 * Math.sin(ph * .05); } // heavy-lidded: folding what it knows together
    ex += (tx * K - ex) * .12; ey += (ty * K - ey) * .12; if (tick > blinkAt + 7) blinkAt = tick + 90 + Math.random() * 220;
    const ez = (1 - m) * F.s, open = lid * (asleep ? .08 : quiet ? .45 : root.dataset.mode === "proactive" ? 1.12 : 1) * (tick > blinkAt ? .1 : 1), gap = 21 * K * ez; g.fillStyle = g.strokeStyle = F.ink;
    if (detached || learning) { g.lineWidth = 4.5 * K * ez; g.lineCap = "round"; // detached: flat eyes, nothing behind them; learning: closed, dreaming, under a slow cyan orbit
      if (learning && !detached) { g.save(); g.strokeStyle = "#6ff7ff"; g.globalAlpha = .7; g.lineWidth = 2; g.setLineDash([3, 10]); g.lineDashOffset = still ? 0 : -tick * .4; g.beginPath(); g.arc(cx, y, R + 20 * K, 0, 6.283); g.stroke(); g.restore(); g.strokeStyle = F.ink; }
      for (const o of [-gap, gap]) { g.beginPath(); detached ? (g.moveTo(F.x + o - 9 * K * ez, F.y), g.lineTo(F.x + o + 9 * K * ez, F.y)) : g.arc(F.x + o, F.y - 2 * K * ez, 10 * K * ez, .35, 2.79); g.stroke(); }
      return; }
    if ((happy > 0 || mood === "happy") && !asleep) { happy--; g.lineWidth = 7 * K * ez; g.lineCap = "round"; for (const o of [-gap, gap]) { g.beginPath(); g.arc(F.x + o + ex * ez, F.y + (6 * K + ey) * ez, 11 * K * ez, 3.5, 5.93); g.stroke(); } return; }
    for (const o of [-gap, gap]) { g.fillStyle = F.ink; g.beginPath(); g.ellipse(F.x + o + ex * ez, F.y + ey * ez, 9 * K * ez, Math.max(1, 23 * K * ez * open * (mood === "sad" ? .7 : 1)), 0, 0, 6.283); g.fill();
      if (open > .5 && ez > .3) { g.fillStyle = "#fff"; g.beginPath(); g.arc(F.x + o + ex * ez - 2.5 * K * ez, F.y + ey * ez - 10 * K * ez, 2.6 * K * ez, 0, 6.283); g.fill(); } }
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
    const asleep = root.classList.contains("asleep"), mood = root.dataset.mood || "", quiet = asleep || root.dataset.mode === "quiet";
    if (!drag && !still) yaw += quiet ? .0008 : .0026;
    if (tick % 20 === 0) { const r = root.querySelector(".sp-rest"); if (r && !r.hidden && r.textContent) status.textContent = r.textContent; // the job line space.js writes
      const rv = getComputedStyle(root).getPropertyValue("--dot").trim(); if (rv && rv !== tint) { tint = rv; markTint(); }
      lamps.querySelectorAll("span").forEach((l) => l.classList.toggle("on", busy ? (tick / 20 | 0) % 4 === [2, 1, 0, 3].indexOf(+l.dataset.s) : +l.dataset.s === lit)); }
    grow += (growTo - grow) * (still ? 1 : .05); lift += ((detached ? .04 : 1) - lift) * (still ? 1 : .04); liquid(); g.clearRect(0, 0, W, H);
    proj = nodes.map((n) => P(n.x, n.y, n.z)); const items = [], show = (n) => !hide.has(n.layer);
    for (const [k, R] of Object.entries(planes)) { if (hide.has(k)) continue; g.strokeStyle = "#8b93a7"; g.globalAlpha = .14; g.lineWidth = 1; g.setLineDash([2, 7]); g.beginPath(); // each layer's plane
      for (let a = 0; a <= 6.4; a += .15) { const q = P(R * Math.cos(a), bandY[k], R * Math.sin(a)); a ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); } g.stroke(); g.setLineDash([]);
      const q = P(-R - 18, bandY[k], 0); g.globalAlpha = .7; g.fillStyle = "#8b93a7"; g.font = "11px ui-monospace, monospace"; g.textAlign = "right"; g.fillText(LY[k].t, q.x, q.y + 4); g.globalAlpha = 1; }
    edges.forEach((e, i) => { if (show(nodes[e[0]]) && show(nodes[e[1]])) items.push({ z: (proj[e[0]].z + proj[e[1]].z) / 2, t: "e", a: proj[e[0]], b: proj[e[1]], i }); });
    nodes.forEach((n, i) => { if (!show(n)) return; items.push({ z: proj[i].z, t: "n", n, q: proj[i] }); });
    if (!quiet && edges.length) for (let k = 0; k < Math.min(7, edges.length); k++) { const e = edges[(k * 7 + (tick / 140 | 0)) % edges.length], a = nodes[e[0]], b = nodes[e[1]], u = ((tick + k * 37) % 140) / 140; if (!show(a) || !show(b)) continue;
      items.push({ z: 0, t: "p", q: P(a.x + (b.x - a.x) * u, a.y + (b.y - a.y) * u, a.z + (b.z - a.z) * u) }); items.at(-1).z = items.at(-1).q.z; } // sparks along what it has linked
    sparks = sparks.filter((s) => (s.t += .028) < 1); for (const s of sparks) { const q = P(s.n.x * (1 - s.t), s.n.y * (1 - s.t), s.n.z * (1 - s.t)); items.push({ z: q.z, t: "p", q, big: 1 }); if (s.t > .96) rings.push(0); }
    if (!hide.has("var")) vars.forEach((v, i) => { const a = tick * (quiet ? .004 : .011) + i * 6.283 / vars.length, r = 135, q = P(r * Math.cos(a), r * Math.sin(a) * .35, r * Math.sin(a)); items.push({ z: q.z, t: "v", q, v }); });
    items.push({ z: 0, t: "dot" }); items.sort((a, b) => b.z - a.z);
    for (const it of items) { const near = it.z < 0, al = Math.max(.14, Math.min(1, .62 - it.z / 440)) * (it.t === "dot" ? 1 : 1 - morph * .7); // the web steps back while it speaks
      if (it.t === "dot") { const T = eyeTask && tick < eyeTask.until && eyeTask.n && proj[nodes.indexOf(eyeTask.n)];
        if (T && !hide.has(eyeTask.n.layer) && !agents.length) { const c = SYSC[eyeTask.sys] || tint, f = Math.min(1, (eyeTask.until - tick) / 40); // where the work is: a beam from Dot to the node it is on, with what it is doing
          g.save(); g.strokeStyle = g.fillStyle = c; g.globalAlpha = .75 * f; g.lineWidth = 1.6; g.setLineDash([6, 6]); g.lineDashOffset = still ? 0 : -tick * .8; g.beginPath(); g.moveTo(cx, cy); g.lineTo(T.x, T.y); g.stroke(); g.setLineDash([]);
          const tag = VERB_OF[EYES[eyeTask.kind]] || eyeTask.kind; g.font = "600 11px ui-monospace, monospace"; const w = g.measureText(tag).width + 14; g.globalAlpha = .92 * f; g.fillStyle = "#0b0f17"; g.beginPath(); g.roundRect(T.x - w / 2, T.y - 30, w, 18, 9); g.fill(); g.strokeStyle = c; g.stroke(); g.fillStyle = c; g.textAlign = "center"; g.fillText(tag, T.x, T.y - 17); g.restore(); }
        dot(mood, asleep); continue; }
      if (it.t === "e" || it.t === "s") { g.strokeStyle = tint; g.globalAlpha = al * (it.t === "s" ? .1 : .3); g.lineWidth = near ? 1.1 : .7; g.beginPath(); g.moveTo(it.t === "s" ? cx : it.a.x, it.t === "s" ? cy : it.a.y); g.lineTo((it.b || it.q).x, (it.b || it.q).y); g.stroke(); }
      else if (it.t === "n") { const n = it.n, q = it.q, c = colour(n); if (n.born < 1) n.born = Math.min(1, n.born + .03);
        const r = (n.layer === "trait" ? 10 : n.layer === "note" ? 7 : n.layer === "chat" ? 4.5 : n.layer === "name" ? 3.6 + Math.min(n.n || 1, 6) * .9 : 5.5) * q.s * n.born; g.fillStyle = g.strokeStyle = c;
        if (n.flash > 0) { n.flash--; g.globalAlpha = n.flash / 70; g.lineWidth = 1.6; g.beginPath(); g.arc(q.x, q.y, r + (70 - n.flash) * .5, 0, 6.283); g.stroke(); }
        g.globalAlpha = n.layer === "trait" ? Math.max(al, .85) : al; g.beginPath(); if (n.layer === "trait") { // traits are hexagons: who it is, from its persona prompt; filled and haloed once you have grown them
          for (let i = 0; i < 6; i++) { const a = i * 1.0472 + .5236; g.lineTo(q.x + Math.cos(a) * r, q.y + Math.sin(a) * r); } g.closePath(); g.lineWidth = 2;
          if (n.state === "grown") { g.fill(); g.globalAlpha = al * (.35 + .25 * Math.sin(tick * .05)); g.beginPath(); g.arc(q.x, q.y, r + 6, 0, 6.283); g.stroke(); } else { g.fillStyle = "#1a0d16"; g.fill(); g.stroke(); }
          g.globalAlpha = Math.max(al, .75); g.font = `600 ${Math.round(10 + 2 * q.s)}px ui-monospace, monospace`; g.textAlign = "center"; g.fillStyle = c;
          if (near || n.state === "grown" || hoverAt(q)) g.fillText(n.label.length > 34 ? `${n.label.slice(0, 33)}…` : n.label, q.x, q.y - r - 9); continue; }
        if (n.kind === "summary" || n.layer === "plan") g.rect(q.x - r, q.y - r * .7, r * 2, r * 1.4); else if (n.layer === "question") { g.moveTo(q.x, q.y - r); g.lineTo(q.x + r, q.y); g.lineTo(q.x, q.y + r); g.lineTo(q.x - r, q.y); } else g.arc(q.x, q.y, r, 0, 6.283); g.fill(); // plans are blocks, questions diamonds, the rest dots
        if (n.state === "verified" || n.state === "ok") { g.lineWidth = 1.2; g.globalAlpha = al * .8; g.beginPath(); g.arc(q.x, q.y, r + 3.5, 0, 6.283); g.stroke(); } // the Verifier's ring
        const hover = ptr && Math.hypot(q.x - ptr[0], q.y - ptr[1]) < 30;
        if (near && (hover || n.layer === "plan" || n.layer === "question" || (n.layer === "name" && n.state === "known"))) { g.font = `${n.kind === "idea" ? "italic " : ""}${Math.round(10 + 3 * q.s)}px ui-monospace, monospace`; g.textAlign = "center"; g.fillStyle = c; g.fillText(n.label.length > 30 ? `${n.label.slice(0, 29)}…` : n.label, q.x, q.y + r + 14); } }
      else if (it.t === "p") { g.globalAlpha = al; g.fillStyle = "#fff6b0"; g.beginPath(); g.arc(it.q.x, it.q.y, (it.big ? 4.5 : 2.4) * it.q.s, 0, 6.283); g.fill(); }
      else { const q = it.q; g.globalAlpha = al; g.strokeStyle = g.fillStyle = "#ffb347"; g.lineWidth = 2; g.beginPath(); g.arc(q.x, q.y, 8 * q.s, 0, 6.283); g.stroke(); if (near) { g.font = "12px ui-monospace, monospace"; g.textAlign = "left"; g.fillText(`${it.v.name} ${it.v.value}`, q.x + 13, q.y + 4); } }
      g.globalAlpha = 1; }
    walk();
    gulp = gulp.filter((u) => (u.t += .03) < 1); for (const u of gulp) { const e = u.t * u.t; g.globalAlpha = 1 - e; g.fillStyle = "#e8ecf4"; g.font = `${Math.round(15 * (1 - e * .6))}px ui-sans-serif, system-ui, sans-serif`; g.textAlign = "center"; g.fillText(u.text, cx, H - 90 + (cy - (H - 90)) * e); if (u.t > .93) rings.push(0); } g.globalAlpha = 1;
  }
  const at = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  cv.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY, yaw, pitch]; moved = 0; cv.setPointerCapture(e.pointerId); cv.classList.add("grab"); });
  cv.addEventListener("pointermove", (e) => { ptr = at(e); if (!drag) return; moved += Math.abs(e.movementX) + Math.abs(e.movementY); yaw = drag[2] + (e.clientX - drag[0]) * .008; pitch = Math.max(-1.2, Math.min(1.2, drag[3] + (e.clientY - drag[1]) * .008)); });
  cv.addEventListener("pointerleave", () => { ptr = null; });
  cv.addEventListener("pointerup", (e) => { cv.classList.remove("grab"); if (drag && moved < 6) { const p = at(e); let best = null, bd = 24;
      nodes.forEach((n, i) => { if (hide.has(n.layer) || proj[i].z >= 0) return; const d = Math.hypot(proj[i].x - p[0], proj[i].y - p[1]); if (d < bd) { bd = d; best = n; } });
      if (best) { best.flash = 70; openNote(best); } } drag = null; });
  cv.addEventListener("keydown", (e) => { const k = { ArrowLeft: [-.15, 0], ArrowRight: [.15, 0], ArrowUp: [0, -.12], ArrowDown: [0, .12] }[e.key]; if (e.key === "Escape") note.hidden = true; if (!k) return; e.preventDefault(); yaw += k[0]; pitch = Math.max(-1.2, Math.min(1.2, pitch + k[1])); });
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
  let fPrev = {}; // the values the last poll showed, so each term says which way it moved
  const formulaBox = (D, G = {}) => { const T = D.terms || {}, F = D.frontier || {}, O = D.optim || {}, S = D.score || {};
    const v = (k, x, tip) => { const p = fPrev[k], dir = typeof p?.x === "number" && typeof x === "number" && r2(p.x) !== r2(x) ? (x > p.x ? "↑" : "↓") : p?.dir || ""; fPrev[k] = { x, dir }; // the arrow stays until it moves again
      return h("span", { class: "sw-fv", title: tip, "data-dir": dir === "↑" ? "up" : dir === "↓" ? "down" : "" }, h("b", {}, x == null ? "–" : r2(x)), h("small", {}, `${k}${dir}`)); };
    const row = (k, x, tip, note) => h("li", {}, v(k, x, tip), h("p", {}, note));
    return h("div", { class: "sw-formula" },
      h("p", { class: "sw-fx sw-goal" }, v("J", S.J, "the score to push up, 0 to 1"), " = ", v("know", S.know, "1 − e^(−answers/names), live"), " × (1 − ", v("surprise", S.surprise, "mean surprise of its last 5 guesses"), ")"),
      Object.keys(G).length ? h("p", { class: "sw-dmut" }, "what each step does to J: ", ...Object.entries(G).slice(0, 8).map(([k, g]) => h("span", { class: "sw-gain", "data-dir": g.gain > 0 ? "up" : g.gain < 0 ? "down" : "" }, `${k} ${g.gain > 0 ? "+" : ""}${g.gain.toFixed(3)} ×${g.runs}`))) : "",
      h("p", { class: "sw-fx" }, v("curiosity", D.curiosity, "the brake: at 0 it stops reaching out"), " = ", v("dial", D.dial, "your hand on it"), " × ( ",
        v("tau", D.tau, "share of each name's questions still unanswered"), " × ", v("dnE", D.dnE, "names met since the last consolidation"), " × ", v("damper", T.damper, "e^(−nAE/nE) from the last consolidation: 1 − maturity"),
        " + ", v("D", F.D, "how many layers deep the mesh goes (max 4)"), " × ", v("F", F.F, "share of the mesh still open"), " ) + ", v("momentum", D.momentum, "the push your ups gave")),
      h("p", { class: "sw-dmut" }, `names term ${r2(T.names)} · frontier term ${r2(T.frontier)} · maturity ${r2(D.maturity)}`),
      h("ul", { class: "sw-optim" },
        row("momentum", D.momentum, "eased each step that did something", `× ${O.ease ?? "–"} per step that did something, to 0 under 0.05`),
        row("since bake", O.since_bake, "answers since the last consolidation", `consolidates every ${O.bake_every ?? "–"} answers: then dnE resets and the damper tightens`),
        row("surprise", O.last_surprise, "last speculation's surprise", `speculations under ${O.keep ?? "–"} are kept (${n0(O.held)} of ${n0(O.speculated)}), aiming for ${O.target ?? "–"}`))); };
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
      const rows = (items, empty) => items.length ? h("ol", { class: "st-rows" }, ...items.map(([k, v, c]) => h("li", c ? { style: `--c:${c}` } : {}, h("span", {}, k), h("b", {}, esc(String(v)).slice(0, 240))))) : h("p", { class: "st-empty" }, empty);
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
        newRun, rows([["curiosity", r2(d.disposition?.curiosity)], ["cycles", `${n0(HL.cycles_run)} · ${n0(HL.executed)} of ${n0(HL.proposed)} proposed steps ran`], cyc?.self?.stuck ? ["it notices", cyc.self.said, "#ffe600"] : stuck ? ["mostly stuck on", `${stuck[0]} (${stuck[1]}×)`, "#ffe600"] : null].filter(Boolean)));
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
      pts.push({ t: run.clock ?? 0, step: last?.step, curiosity: D.curiosity, maturity: D.maturity, ...(typeof D.frontier?.term === "number" ? { frontier: D.frontier.term } : {}), ...(D.terms ? { names: D.terms.names, damper: D.terms.damper } : {}), ...(typeof D.frontier?.F === "number" ? { F: D.frontier.F, D: D.frontier.D } : {}), ...(typeof D.momentum === "number" ? { momentum: D.momentum } : {}), ...(typeof D.score?.J === "number" ? { score: D.score.J } : {}), ...(L.needs || {}), ...(typeof L.trust?.value === "number" ? { trust: L.trust.value } : {}), now: true }); }
    const clock = run?.clock ?? last?.t ?? 0, T = Math.max(10, clock, pts.at(-1)?.t || 0), byClock = !!log.length || live; // live: the clock and the lanes from the first second, before the first step lands
    const C = { curiosity: tint, maturity: "#ffb347", frontier: "#c79bff", score: "#ffffff", names: "#ff7ab6", damper: "#9be564", F: "#5ec8ff", D: "#8a8aff", momentum: "#ffe600", ...NEED_C, trust: "#e4e4e7" };
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
      story: () => { const done = trace.filter((t) => t.outcome === "ok").slice(0, 6);
        sty ||= makeStory(); sty.update(d, loop, cTurns);
        return h("div", { class: "sw-story" }, sty.el,
          h("div", { class: "sw-story2" },
            h("section", {}, h("h4", {}, "Just now"), done.length ? h("ol", { class: "sw-feed" }, ...done.map((t) => h("li", {}, h("button", { type: "button", onclick: () => { rSel = { step: tkey(t), note: t.ref }; go("activity"); } },
              h("time", {}, local(t.at)), h("p", {}, h("b", { style: `color:${SC[t.system] || "#d4d4d8"}` }, `${who} ${VERB[t.kind] || t.kind}`), ` ${esc(t.detail.split(":")[0])}`)))))
              : h("p", { class: "sw-dmut" }, "Nothing yet."), why ? h("p", { class: "sw-dmut sw-why" }, `When a step does nothing, it is most often because “${esc(why[0])}”.`) : ""),
            feels(d.life), wishes(d.life),
            youBox(d),
            h("section", {}, h("h4", {}, "Curiosity"), h("p", { class: "sw-big" }, h("strong", {}, r2(D.curiosity)), h("span", {}, `maturity ${r2(D.maturity)}`)),
              formulaBox(D, d.gains), lineChart(d.series || [])))); },
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
  menu.append(h("small", {}, "View"), h("span", {}, h("button", { type: "button", onclick: () => { shut(); report(); } }, "Report")));
  // the page always opens on the mesh, so you see it grow; the report is one click away
  markTint(); refresh(); frame();
  function expand(on = !growTo) { growTo = on ? 1 : 0; if (on) Object.keys(seen).filter((k) => HOME[k]).forEach(agentOf); rings.push(0); status.textContent = on ? "Dot holds the whole net now. /expand-to-net again to gather it back." : "Dot gathers back to its centre."; }
  return { expand, report, palette, data, say, heard, fire, stepped, refresh, reform: (c) => { if (c) form = c; }, busy: () => { busy = true; } };
}
