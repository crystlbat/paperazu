"use strict";
// ---------- Dot space: chat with Dot while variables count the chat and steer its next reply ----------
// Everything is dots. Dot is the yellow goo in the middle. Each variable is an arc of beads on its ring, with a readout
// on the left. The tables Dot reads and writes are stacks of dots on the floor. Drops of goo carry data between them.
// The chat itself is a plain transcript on the right, so you can read it. Rules: workbench/space.py.

const SP_COLORS = ["#ffb547", "#ff7ab6", "#7dffa8", "#b49cff", "#6ff7ff", "#ff8f6b"];
const SP_TABLES = [["papers", "Papers"], ["highlights", "Highlights"], ["chat_turns", "Chat turns"], ["variables", "Variables"], ["cards", "Cards"]];
const SP_NS = "http://www.w3.org/2000/svg";
const SP_TRIG = { every: (n) => `every ${n}`, past: (n) => `past ${n}`, drops: (n) => `${n} drops`, catches: (n) => `meets ${n}`, made: () => "new", removed: () => "removed", reset: () => "back to 0", set: () => "persona", ladder_hook: () => "ladder hook",
  rises: (n, e) => e?.target_name ? `${e.target_name} ${e.add > 0 ? "+" : "−"}${Math.abs(e.add)}` : "rises" };
const spSigned = (n) => `${n > 0 ? "+" : n < 0 ? "−" : "±"}${Math.abs(Math.round(n))}`;

async function renderSpace(base = "/space") {
  const root = h("div", { class: base === "/char" ? "sp sp-char" : "sp" });
  root.innerHTML = `<svg class="sp-svg" aria-hidden="true"><defs><filter id="sp-goo" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="7"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -9"/></filter></defs></svg>
    <div class="sp-eyes"><i></i><i></i><div class="sp-look" aria-hidden="true"><span class="sp-glasses"><i></i><i></i></span><span class="sp-monocle"></span><span class="sp-visor"></span><span class="sp-bowtie"></span></div></div>
    <section class="sp-vars" aria-label="Variables"></section>
    <section class="sp-log" id="sp-log" aria-live="polite" aria-label="Chat with Dot"></section>
    <button type="button" class="sp-hist" aria-controls="sp-log" aria-expanded="false">History</button>
    <button type="button" class="sp-notesbtn" aria-controls="sp-notesbox" aria-expanded="false">Notes</button>
    <button type="button" class="sp-steerbtn" aria-label="Open Steer Studio">✦ Steer</button>
    <button type="button" class="sp-learntoggle" aria-pressed="false" title="Toggle autonomous question-driven learning loop"><span class="sp-toggle-pill"></span><span class="sp-toggle-label">Learn More</span></button>
    <section class="sp-notesbox" id="sp-notesbox" aria-label="Your notes" hidden></section>
    <dl class="sp-stats" aria-label="Dot space stats"></dl>
    <div class="sp-stage" aria-hidden="true"></div>
    <a class="sp-home" href="#library" aria-label="Back to the Library">← Library</a>
    <div class="sp-tools"></div><div class="sp-papercards"></div>
    <div class="sp-info" aria-label="What Dot reads and writes"></div>
    <input type="file" class="sp-pick" accept="application/pdf,.pdf" hidden>
    <button type="button" class="sp-knock" hidden aria-label="Knock on Dot. Three knocks wake it"></button>
    <div class="sp-zzz" aria-hidden="true"><i>z</i><i>z</i><i>Z</i></div>
    <form class="sp-ear"><div class="sp-crew" role="list" aria-label="Your creatures"></div><div class="sp-learn-chips" role="group" aria-label="Suggested learning directions"></div><span class="sp-l" aria-hidden="true"><i></i><i></i></span>
      <input name="say" placeholder="Ask Dot anything…" autocomplete="off" aria-label="Talk to Dot" maxlength="4000">
      <button type="button" class="sp-clear" title="Clear the chat and variables">Clear</button>
      <button type="submit" class="sp-go" aria-label="Send">&uarr;</button></form>`;
  view.append(root);
  let histOpen = false; try { histOpen = localStorage.getItem("sp-history") === "1"; } catch { /* storage off: closed */ }
  let firedCount = 0;
  const $s = (q) => root.querySelector(q), svg = $s(".sp-svg"), log = $s(".sp-log"), stage = $s(".sp-stage"), varsEl = $s(".sp-vars"), form = $s(".sp-ear");
  const topRow = h("nav", { class: "sp-top", "aria-label": "Space controls" }); // one row that spaces itself, so the buttons never sit on each other
  topRow.append(...[".sp-learntoggle", ".sp-steerbtn", ".sp-home", ".sp-notesbtn", ".sp-hist"].map($s).filter(Boolean)); root.append(topRow);
  if (base !== "/char") $s(".sp-learntoggle")?.remove(); else $s(".sp-steerbtn")?.remove(); // on /char Steer rides the ring with the other things that change Dot
  // the learning loop runs only in /char
  const el = (tag, a, p = svg) => { const e = document.createElementNS(SP_NS, tag); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); p.append(e); return e; };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const web = base === "/char" && window.spWeb ? spWeb(root, { api, h, still, mind: () => openMind(), wiring: () => openSystems(), step: () => learnOne(true), reload: async () => { try { apply(await api(base)); paint?.(); } catch { /* the next reply refreshes it */ } } }) : null; // /char is drawn by web3d.js; this file keeps the chat, the model calls and the dialogs
  // every /command on /char, in one place: the submit handler runs them and typing "/" shows them (Dot becomes the list)
  const setMode = async (m) => { try { await api("/char/wiring", { method: "POST", body: JSON.stringify({ mode: m }) }); } catch { return; } web?.refresh(); };
  const COMMANDS = [
    { name: "/report", also: ["/report-mode", "/show-report"], does: "Switch to the plain report: cycles, self-corrections, what it learned, and every engine run.", run: () => web.report(true) },
    { name: "/expand-to-net", also: ["/expand", "/contract"], does: "Dot swells out to the base ring and holds the whole net inside it; run it again to gather it back.", run: () => web.expand() },
    { name: "/scene", also: ["/back", "/hide-report"], does: "Back to the 3D scene from the report.", run: () => web.report(false) },
    { name: "/step", does: "Run one learning step now. The Verifier picks which engine runs; watch its row light up.", run: () => learnOne(true) },
    { name: "/mind", does: "Open its memory: every note, question and the prompts it last sent the model.", run: () => openMind() },
    { name: "/wiring", does: "Open the wiring: systems S0, S1, S2, the Verifier, your rules and its corrections.", run: () => openSystems() },
    { name: "/sleep", does: "Put it to sleep: no replies and no learning, so you can swap models and test without chatting by accident.", run: () => setMode("sleeping") },
    { name: "/wake", does: "Wake it up: it answers again and learns while idle (curious).", run: () => setMode("curious") },
    { name: "/quiet", does: "Mode quiet: it only answers you and never learns by itself.", run: () => setMode("quiet") },
    { name: "/curious", does: "Mode curious: it learns by itself while you are idle.", run: () => setMode("curious") },
    { name: "/proactive", does: "Mode proactive: it learns, and tells you what it found.", run: () => setMode("proactive") },
    { name: "/learn", also: ["/learn-more"], does: "Turn learn mode on or off.", run: () => toggleLearnMode() },
    { name: "/steer", also: ["/steer-mode"], does: "Open the steer studio.", run: () => openSteerStudio() },
    { name: "/verse", does: "Go to the verse: every persona around the model.", run: () => { location.hash = "#verse"; } },
  ];
  const command = (t) => { const c = t.toLowerCase().trim().replace(/\s+/g, "-"); return COMMANDS.find((x) => x.name === c || x.also?.includes(c)); };
  let W, H, CX, CY, S, layers, papers = [], spin = 0, all = [], vars = [], tables = {}, arcs = new Map();
  const P = (r, deg) => [CX + r * S * Math.sin(deg * Math.PI / 180), CY - r * S * Math.cos(deg * Math.PI / 180)];
  const colorOf = (v) => SP_COLORS[Math.max(0, vars.findIndex((x) => x.id === v.id)) % SP_COLORS.length];
  // the first arcs sit on the left, beside their readouts, so leaders do not cross Dot
  const SLOTS = [300, 240, 190, 20, 80, 130];
  const slot = (v) => { const a0 = SLOTS[Math.max(0, vars.findIndex((x) => x.id === v.id)) % 6]; return [a0, a0 + 40]; };

  // ---- the stage ----
  function layout() {
    W = root.clientWidth; H = root.clientHeight;
    const wide = W > 980, left = wide ? 300 : 0, right = wide && (histOpen || notesOpen) ? 400 : 0; // closed history gives Dot the room
    // wide: as big as the height allows (rings, Dot's words, then the floor), centred on the page and clear of the readouts
    S = Math.max(.6, Math.min(1.25, (H - 200) / 474, (W - right - 40) / 600));
    CX = Math.max((W - right) / 2, (vars.length ? 270 : 0) + 240 * S); CY = 64 + 212 * S;
    log.style.top = ""; root.style.setProperty("--cx", `${CX}px`); root.style.setProperty("--cy", `${CY}px`); // CSS places things by Dot too
    if (!wide) { // top to bottom: readouts, rings, the line under Dot, floor
      const top = varsEl.offsetTop + varsEl.offsetHeight + 8;
      S = Math.max(.45, Math.min(1, (H - top - 172 - 160) / 440, (W - 24) / 470)); CY = top + 220 * S;
    }
    const kn = $s(".sp-knock"); if (!kn.hidden) { kn.style.left = `${CX}px`; kn.style.top = `${CY}px`; kn.style.width = kn.style.height = `${120 * S}px`; }
    const zz = $s(".sp-zzz"); zz.style.left = `${CX + 50 * S}px`; zz.style.top = `${CY - 70 * S}px`;
    form.style.left = wide ? `${CX}px` : ""; // Dot, its words, the floor and the input bar share one centre line
    form.style.width = wide ? `${Math.min(560, 2 * (W - CX - ($s(".sp-stats")?.offsetWidth || 200) - 36))}px` : ""; // clear of the stats corner
    stage.style.left = `${CX}px`; stage.style.top = `${CY + 226 * S}px`;
    stage.style.setProperty("--room", `${Math.max(25, form.offsetTop - 50 - (CY + 226 * S) - 34)}px`); // the reply stops above the creatures stage.style.maxWidth = `${Math.min(620, W - left - right - 32)}px`;
    const up = root.classList.contains("carded") && stage.querySelector(".sp-card"); if (up) fit(up); // a card that is up keeps its room
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.querySelectorAll(":scope > g").forEach((g) => g.remove());
    const kgL = el("g", { class: "sp-kg" }); // the knowledge graph: drawn first, so it sits behind the ring and Dot
    const g = el("g", { class: "sp-track" });
    const ring = (r, gap, w, color, a0 = 0, a1 = 360) => { for (let a = a0; a <= a1; a += gap / (r * S) * 180 / Math.PI) { const [x, y] = P(r, a); el("circle", { cx: x, cy: y, r: w, fill: color }, g); } };
    ring(212, 16, 2.2, "rgb(111 247 255 / .18)"); // the one track: the tools ride it
    layers = { kg: kgL, rules: el("g", { class: "sp-rules" }), leads: el("g", {}), floor: el("g", { class: "sp-floor" }), goo: el("g", { filter: "url(#sp-goo)", class: "sp-dotg", style: `transform-origin:${CX}px ${CY}px` }) };
    el("circle", { cx: CX, cy: CY, r: 52 * S, fill: "#ffe347", class: "sp-body" }, layers.goo);
    [[20, 4.1, 0], [26, 5.3, -1.7], [24, 3.7, -2.9], [22, 6.1, -.8]].forEach(([r, t, d], i) => // blobs inside the goo keep Dot's edge flowing
      el("circle", { cx: CX, cy: CY, r: r * S, class: `sp-blob sp-blob${i}`, style: `--t:${t}s;--d:${d}s;--o:${34 * S}px` }, layers.goo));
    for (const q of [".sp-eyes"]) { const e = $s(q); e.style.left = `${CX}px`; e.style.top = `${CY}px`; e.style.scale = `calc(${S} * var(--big, 1))`; } // /char: calm, Dot is bigger (see .sp-char)
    // comets: a few dots run round the rings (moving a few dots is cheap; turning whole rings is not)
    root.querySelectorAll(".sp-comet").forEach((c) => c.remove());
    if (!still) for (const [r, t, rev] of [[212, 41, false]]) for (let k = 0; k < 4; k++) {
      const R = r * S, c = h("i", { class: "sp-comet", "aria-hidden": "true" });
      c.style.cssText = `offset-path:path("M${CX - R},${CY} a${R},${R} 0 1,1 ${2 * R},0 a${R},${R} 0 1,1 ${-2 * R},0");` +
        `animation-duration:${t}s;animation-direction:${rev ? "reverse" : "normal"};animation-delay:${-k * t / 160}s;opacity:${1 - k * .24};scale:${1 - k * .15}`;
      root.prepend(c);
    }
    arcs = new Map(); vars.forEach((v) => drawArc(v, false)); drawFloor(); lead(); drawCards(); drawGraph(); orbit();
  }
  // a variable is an arc of beads; how full it is lights them
  function drawArc(v, pop = true) {
    const [a0, a1] = slot(v), c = colorOf(v), g = el("g", { class: pop ? "sp-pop" : "" }, layers.rules), beads = [];
    for (let a = a0; a <= a1; a += 4.5) { const [x, y] = P(128, a); beads.push(el("circle", { cx: x, cy: y, r: 4 * Math.max(S, .7), fill: c, "fill-opacity": .25 }, g)); }
    const id = `sp-tp-${v.id}`, [x0, y0] = P(148, a0 - 20), [x1, y1] = P(148, a1 + 20); // a longer path than the beads, so a name fits on small screens
    const low = (a0 + a1) / 2 % 360 > 95 && (a0 + a1) / 2 % 360 < 265; // on the lower half the name runs the other way, so it reads upright
    el("path", { id, d: low ? `M${x1},${y1} A${148 * S},${148 * S} 0 0 0 ${x0},${y0}` : `M${x0},${y0} A${148 * S},${148 * S} 0 0 1 ${x1},${y1}`, fill: "none" }, g);
    const t = el("text", { class: "sp-arc-name", fill: c, "text-anchor": "middle" }, g); el("textPath", { href: `#${id}`, startOffset: "50%" }, t).textContent = v.name.toUpperCase();
    arcs.set(v.id, beads); light(v);
  }
  const fullness = (v) => v.kind === "watch" ? Math.min(v.value / 10, 1) : v.past ? Math.min(v.value / v.past, 1) : v.every ? (v.value % v.every || (v.value ? v.every : 0)) / v.every : Math.min(v.value / 20, 1);
  function light(v) { const b = arcs.get(v.id) || [], lit = Math.round(b.length * fullness(v)); b.forEach((x, i) => x.setAttribute("fill-opacity", i < lit ? 1 : .25)); }
  function flare(v) { if (still) return; (arcs.get(v.id) || []).forEach((b, i) => b.animate([{ r: b.getAttribute("r") }, { r: 8 }, { r: b.getAttribute("r") }], { duration: 500, delay: i * 25 })); }
  const mid = (v) => { const [a0, a1] = slot(v); return P(128, (a0 + a1) / 2); };

  // ---- readouts: one per variable, a dotted leader from its arc ----
  function drawVars() {
    varsEl.replaceChildren(...(vars.length ? vars.map((v) => {
      const val = v.kind === "persona" ? (v.learned ? "ON" : "…") : v.kind === "count" ? `${Math.round(v.value)}${v.past > 0 ? `/${v.past}` : v.past === -1 ? `/${v.every}` : ""}` : `${Math.round(v.value)}`;
      const doing = (v) => { const args = v.act_arg.split(" | "); // a rule may run several actions: "make+paper" with "action_taken | bias"
        return v.act.split("+").map((a, i) => ({ recolor: `turn Dot ${args[i].split(", ").join(" → ")}`, search: `search the web for “${args[i]}”`,
          become: `learn ${args[i]} from the web`, make: `make ${args[i]}`, paper: `open or suggest a ${args[i]} paper`,
          spawn: `hatch ${args[i].split(":")[0].trim()}`, sleep: args[i] === "dot" ? "go to sleep and reflect" : `let ${args[i]} put Dot to sleep, and reflect` })[a] || a).join(", "); };
      const steers = ["every", "past", "drops", "catches"].filter((t) => v[t] && !(t === "past" && v.past < 0)).map((t) => `${t === "every" && v.past === -1 ? `at ${v.every}` : SP_TRIG[t](v[t])}: ${[v[`${t}_say`], v.act_on === t && v.act ? doing(v) : ""].filter(Boolean).join(", ")}`).filter((x) => !x.endsWith(": ")); // a mark with nothing to do is not shown
      if (v.resets && steers.length) steers[steers.length - 1] += ", then back to 0";
      if (v.kind === "watch") steers.unshift(`when ${v.target} rises${v.rises > 1 ? ` by ${v.rises}` : ""}: ${v.add_n ? `${spSigned(v.add_n)} to ${v.target}` : ""}${v.rises_say ? `${v.add_n ? ", " : ""}say ${v.rises_say}` : ""}`);
      const kind = v.kind === "persona" ? "persona" : v.kind === "state" ? "mood" : v.kind === "words" ? "words a message" : v.kind === "watch" ? `watches ${v.target}${vars.some((x) => x.name.toLowerCase() === v.target.toLowerCase()) ? "" : " (not here)"}` : "count";
      const delta = v.kind === "words" && v.turns > 1 ? ` · ${v.delta > 0 ? "+" : v.delta < 0 ? "−" : "±"}${Math.abs(Math.round(v.delta))}` : "";
      return h("article", { class: "sp-var", "data-id": v.id, style: `--c:${colorOf(v)}` },
        h("header", {}, h("span", {}, `${v.name} · ${kind}${delta}`),
          h("button", { type: "button", "aria-label": `Remove ${v.name}`, onclick: () => drop$(v) }, "×")),
        h("b", { class: "sp-num" }, val),
        v.about ? h("p", { class: "sp-about" }, v.about) : steers.length ? h("p", {}, steers.join(" · ")) : null); // the rule as the engine reads it
    }) : [h("p", { class: "sp-empty" }, "No rules yet. Say one plainly, then check how I read it here. Try: ", h("q", {}, base === "/char" ? "when I say ace of spades 3 times, look up cayde 6" : "count apples in our chat; every 3rd say beep boop, injection works; past 10 say test successful"))]));
    lead();
  }
  function lead() { layers?.leads.replaceChildren(); } // no lines from the list to the arcs: each arc carries its name
  async function drop$(v) { try { apply(await api(`${base}/vars/${v.id}`, { method: "DELETE" })); } catch { /* already gone */ } form.say.focus(); }

  // ---- the Library's blobs ride the outer ring: each one is a shortcut that talks to Dot for you ----
  const ask = (t) => { line = line.then(() => send(t)).catch(() => {}); };
  const fill = (t) => { form.say.value = t; form.say.focus(); form.say.setSelectionRange(t.length, t.length); };
  const TOOLS = [["shelf", "Shelf", "#ff7ab8", () => { libStore.set("lib-mode", "shelf"); location.hash = "#library"; }], ["pick", "Open a paper", "#c6a0ff", () => ask("open a pdf preview")], ["set", "Models", "#c9cdd6", () => ask("show me the list of models")],
    ["persona", "Persona", "#ffa86b", () => fill("set persona as ")], ["add", "Counter", "#ffe347", () => fill("count ")],
    ["next", "Colours", "#7bd88f", () => fill("count hello; every 3 turn dot red, green, blue")], ["talks", "Forget", "#ff9e7a", () => fill("delete all variables")],
    ["find", "Ask", "#8ecbff", () => fill("")], ];
  // /char talks to a character, not the papers: only the tools it understands ride its ring
  let voiceOn = false; try { voiceOn = localStorage.getItem("dot-voice") === "on"; } catch { /* private window: off */ }
  const CHAR_TOOLS = [["persona", "Become", "#ffa86b", () => fill("become ")], ["talks", "Voice", "#7dd3fc", () => { voiceOn = !voiceOn; try { localStorage.setItem("dot-voice", voiceOn ? "on" : "off"); } catch { /* ok */ } toolInfo(); if (voiceOn) talk("I can talk now."); }], ["add", "Counter", "#ffe347", () => fill("create a variable called ")],
    ["find", "Research", "#8ecbff", () => fill("research ")], ["shelf", "Shelf", "#ff7ab8", () => { libStore.set("lib-mode", "shelf"); location.hash = "#library"; }],
    ["bubble", "Learn", "#7dffa8", () => { sleep(); reflect(); }], ["set", "Sleep", "#c9cdd6", () => sleep()], ["theme", "Steer", "#c6a0ff", () => openSteerStudio()]]; // how the character learns more: it rests, looks things up and fills its sheet, in the open
  const tools = (base === "/char" ? CHAR_TOOLS : TOOLS).map(([k, name, c, run]) => libBlob(k, name, c, run));
  $s(".sp-tools").append(...tools);
  function orbit() { // placed round the outer ring; the ring turns slowly unless the pointer is near a blob or motion is reduced
    const n = tools.length, R = 212 * S;
    tools.forEach((b, i) => { const a = spin + i * 2 * Math.PI / n, sn = Math.sin(a);
      b.style.translate = `${CX + R * Math.cos(a)}px ${CY + R * sn}px`; b.style.scale = Math.max(.75, S * 1.1);
      b.classList.toggle("under", sn > .82); }); // passing under Dot's words: it fades out of their way
  }
  let near = false;
  $s(".sp-tools").addEventListener("pointerover", () => { near = true; }); $s(".sp-tools").addEventListener("pointerout", () => { near = false; });
  let tick = performance.now();
  const turn = (t) => { if (!root.isConnected) return; if (!near && !still && !root.classList.contains("leaving")) { spin += (t - tick) * 0.00006; mspin += (t - tick) * 0.000025; orbit(); moonsAt(); } tick = t; requestAnimationFrame(turn); };
  requestAnimationFrame(turn);

  // ---- the papers are moons: covers going round Dot on a wide orbit; the + moon adds a PDF ----
  let moons = [], mspin = 0, kg = { nodes: [], edges: [] }, kgSeen = null;
  // /char: the names its notes mention, as a faint web behind Dot. Read ones glow cyan; ones it is still curious about are amber.
  // Curved guides run between names met in the same note, and a dotted line from Dot reaches the one it will read next.
  let kgAt = new Map();
  async function fire(rc) { // the notes and names a reply drew on light up and send a spark into Dot, like neurons firing
    if (!rc || base !== "/char" || still) return;
    if (web) return web.fire(rc.names);
    const L = layers.kg;
    (rc.notes || []).forEach((n, i) => { const m = root.querySelector(`.sp-notemoon[data-id="${n.id}"]`); if (m) setTimeout(() => { m.classList.add("firing"); setTimeout(() => m.classList.remove("firing"), 2600); }, i * 120); });
    await Promise.all((rc.names || []).map(async (name, i) => {
      const p = kgAt.get(name), g = L.querySelector(`[data-name="${CSS.escape(name)}"]`); if (!p || !g) return;
      await wait(i * 140); g.classList.add("firing");
      const s = el("path", { d: `M${p[0]},${p[1]} Q${(p[0] + CX) / 2 + (p[1] - CY) * .15},${(p[1] + CY) / 2 - (p[0] - CX) * .15} ${CX},${CY}`, class: "sp-kg-fire", pathLength: 1 }, L);
      await s.animate([{ strokeDashoffset: 1 }, { strokeDashoffset: -1 }], { duration: 700, easing: "ease-in" }).finished.catch(() => {});
      s.remove(); setTimeout(() => g.classList.remove("firing"), 1400);
    }));
  }
  function drawGraph() {
    if (base !== "/char" || !layers?.kg) return;
    const L = layers.kg; L.replaceChildren();
    const left = W > 980 ? 330 : 20, rx = Math.max(160, Math.min(W - CX - 60, CX - left, 420 * S)), ry = Math.max(120, Math.min(CY - 40, H - CY - 150, 300 * S));
    const hash = (t) => [...t].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
    const at = new Map(kg.nodes.map((n, i) => { const a = i * 2.39996 - Math.PI / 2, f = .72 + (hash(n.name) % 100) / 360;
      return [n.name, [CX + rx * f * Math.cos(a), CY + ry * f * Math.sin(a)]]; }));
    for (const [a, b] of kg.edges) { const p = at.get(a), q = at.get(b); if (!p || !q) continue;
      const mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2; // the curve bows toward Dot: everything it knows bends round it
      el("path", { d: `M${p[0]},${p[1]} Q${mx + (CX - mx) * .35},${my + (CY - my) * .35} ${q[0]},${q[1]}`, class: "sp-kg-edge" }, L); }
    const next = kg.nodes.filter((n) => !n.known).sort((x, y) => y.n - x.n)[0];
    if (next) { const [x, y] = at.get(next.name); el("line", { x1: CX, y1: CY, x2: x, y2: y, class: "sp-kg-next" }, L); }
    const born = kgSeen ? kg.nodes.filter((n) => !kgSeen.has(n.name)).map((n) => n.name) : [];
    kg.nodes.forEach((n, i) => { const [x, y] = at.get(n.name), r = (3 + Math.min(n.n, 6) * 1.3) * Math.max(.8, S);
      const g = el("g", { "data-name": n.name, class: `sp-kg-node${n.known ? " known" : ""}${n.kind === "abstract" ? " idea" : ""}${born.includes(n.name) ? " born" : ""}`, style: `--d:${-(i * 1.7) % 9}s;transform-origin:${x}px ${y}px` }, L);
      el("circle", { cx: x, cy: y, r: r * 2.6, class: "sp-kg-halo" }, g); el("circle", { cx: x, cy: y, r }, g);
      const t = el("text", { x, y: y + r + 13, "text-anchor": "middle" }, g); t.textContent = n.name; });
    kgSeen = new Set(kg.nodes.map((n) => n.name)); kgAt = at;
    if (born.length && !still) ripple("#ffb347", 240);
  }
  // /char is calm: only a big Dot, until you come near it or tap it; then the tools, moons and rules bloom out round it
  if (base === "/char") {
    let pinned = false, shut;
    const ring = () => [...root.querySelectorAll(".sp-tools .lblob, .sp-moon")];
    const swallow = (back) => { const s = root.getBoundingClientRect(); // the moons and tools come out of Dot, or Dot takes them back in
      ring().forEach((m, i) => { m.getAnimations().forEach((a) => a.constructor === Animation && a.cancel()); if (still) return;
        const b = m.getBoundingClientRect(), to = { translate: `${CX - (b.left - s.left + b.width / 2)}px ${CY - (b.top - s.top + b.height / 2)}px`, scale: .1, opacity: 0 };
        m.animate(back ? [{}, to] : [to, {}], { duration: 480, delay: i * 25, easing: back ? "cubic-bezier(.6,0,.8,.4)" : "cubic-bezier(.3,1.4,.5,1)", fill: back ? "forwards" : "none" }); }); };
    let want = false;
    const open = (on) => { if (on === want) return; want = on; clearTimeout(shut); // a tap mid-close turns it round
      if (on) { root.classList.add("open"); swallow(false); } else { swallow(true); shut = setTimeout(() => { root.classList.remove("open"); ring().forEach((m) => m.getAnimations().forEach((a) => a.constructor === Animation && a.cancel())); }, 520 + ring().length * 25); } };
    const near = (e) => { const b = root.getBoundingClientRect(); return Math.hypot(e.clientX - b.left - CX, e.clientY - b.top - CY); };
    root.addEventListener("pointerdown", (e) => { if (near(e) < 95 * S * (root.classList.contains("open") ? 1 : 1.75) && !e.target.closest("button, a, input, form")) { pinned = !pinned; open(pinned); } }); // only a tap opens it: Dot shrinks and lets them out
    root.addEventListener("focusin", (e) => { if (e.target.closest(".sp-tools, .sp-papercards")) open(true); });
    root.addEventListener("focusout", (e) => { if (!pinned && !root.contains(e.relatedTarget)) open(false); });
  }
  function drawCards() {
    const box = $s(".sp-papercards");
    if (base === "/char") {
      const seen = new Set(moons.map((m) => m.dataset.id)), first = !moons.length;
      moons = papers.slice(0, 8).map((p) => { const t = (p.title || "Note").replace(/^(?:Research|Reflection):\s*/i, "");
        const kind = /^Research:/i.test(p.title || "") || /^job/i.test(p.authors || "") ? "research" : p.authors === "lesson" ? "lesson" : "reflection";
        return h("button", { type: "button", class: `sp-moon sp-notemoon${(p.content || "").length > 200 ? " big" : ""}${!first && !seen.has(p.id) ? " new" : ""}`,
          "data-id": p.id, "data-kind": kind, "aria-label": `Learned: ${t}`, title: t,
          onclick: () => showCard({ kind: "job", title: t, result: p.content || p.note || "", status: kind === "research" ? "Researched" : "Learned" }) },
          h("span", {}, t)); });
    } else {
      moons = [...papers.slice(0, 10).map((p) => h("button", { type: "button", class: "sp-moon", "aria-label": `Open ${p.title}`, onclick: () => travel(p) },
          h("img", { src: `/papers/${p.id}/cover`, alt: "", loading: "lazy", onerror: (e) => e.target.remove() }), h("span", {}, p.title || "Untitled"))),
        h("button", { type: "button", class: "sp-moon sp-addmoon", "aria-label": "Add a PDF", onclick: () => $s(".sp-pick").click() }, h("b", {}, "+"), h("span", {}, "Add a PDF"))];
    }
    box.replaceChildren(...moons); moonsAt();
  }
  function moonsAt() {
    const side = W > 980 && vars.length ? CX - 300 - 40 : Infinity; // clear of the variable list on the left
    const k = base === "/char" ? .58 : 1; // /char: what it learned orbits close, inside the ring of tools
    const rx = k * Math.min((W - (histOpen || notesOpen ? 400 : 0)) / 2 - 40, 330 * S, side), ry = k * Math.min(262 * S, CY - 80, H - 130 - CY), n = moons.length;
    moons.forEach((m, i) => { const a = -mspin + i * 2 * Math.PI / n, sn = Math.sin(a);
      m.style.translate = `${CX + rx * Math.cos(a)}px ${CY + ry * sn}px`; m.style.scale = k < 1 ? "" : Math.max(.75, S);
      m.classList.toggle("under", sn > .45); m.style.zIndex = sn > 0 ? 3 : 1; }); // the far side of the orbit passes behind
  }
  $s(".sp-papercards").addEventListener("pointerover", () => { near = true; }); $s(".sp-papercards").addEventListener("pointerout", () => { near = false; });
  $s(".sp-pick").addEventListener("change", async (e) => { // adding a PDF here, the same way the Library does
    const file = e.target.files[0]; e.target.value = ""; if (!file) return;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") return emerge({ role: "dot", text: `${file.name} is not a PDF. I can only read PDFs.`, events: [] });
    mood("think", 0); emerge({ role: "dot", text: `Reading ${file.name}…`, events: [] });
    try {
      const paper = await api("/papers", { method: "POST", body: file, headers: { "Content-Type": "application/pdf", "X-Filename": encodeURIComponent(file.name) } });
      const st = await api(base); take(st); drawCards(); drawFloor(); stats(); gulp(); mood("happy"); ripple("#ffe347", 300);
      await emerge({ role: "dot", text: `Added ${paper.title || file.name}. It is a new moon.`, events: [] });
      detailsDialog(paper, await api("/settings"), true);
    } catch (err) { mood("sad", 3000); emerge({ role: "dot", text: err.body?.detail ?? "I could not add that PDF.", events: [] }); }
  });


  // ---- the bottom-left infographic: one bar of dots per table Dot reads; drops fly from its row ----
  const SP_DOTC = { chat_turns: "#ffe347", variables: "#ffb547" };
  const stackAt = (k) => { const r = $s(`.sp-info [data-k="${k}"] .sp-bar`), o = root.getBoundingClientRect();
    if (!r || !r.offsetParent) return [CX, H - 104]; const b = r.getBoundingClientRect(); return [b.left - o.left + 12, b.top - o.top + b.height / 2]; };
  function drawFloor() {
    layers.floor.replaceChildren();
    const top = Math.max(1, ...SP_TABLES.map(([k]) => tables[k] || 0));
    const me = base === "/char", who = all.find((v) => v.kind === "persona")?.act_arg || "Dot";
    const rows = me ? [["sheet", "Sheet /4"], ["notes", "Notes"], ["entities", "Names"], ["questions", "Questions"]] : SP_TABLES; // /char: what the character knows of itself
    $s(".sp-info").replaceChildren(h("h3", {}, me ? `What ${who} knows` : "What Dot holds", ...(me ? [h("button", { type: "button", class: "sp-mindbtn", onclick: openMind }, "Open mind"), h("button", { type: "button", class: "sp-mindbtn sp-sysbtn", title: "Signals, systems and memory, and the wires between them", onclick: () => openSystems() }, "⚙ Wiring")] : [])), ...rows.map(([k, label]) => { const n = tables[k] || 0;
      return h("div", { class: "sp-irow", "data-k": k, style: `--c:${SP_DOTC[k] || "#6ff7ff"}` }, h("span", { class: "sp-ilabel" }, label),
        h("span", { class: "sp-bar", "aria-hidden": "true" }, h("i", { style: `width:${Math.max(n ? 4 : 0, 100 * n / (k === "sheet" ? 4 : top))}%` })), h("b", {}, n)); }),
      ...(me && tables.last ? [h("p", { class: "sp-ilast" }, `Last learned: ${tables.last}`)] : []));
  }

  // ---- goo: drops carry data and steering into Dot ----
  async function drop(from, to, color, delay = 0, r = 8) {
    if (still) return; await wait(delay);
    const d = el("circle", { cx: from[0], cy: from[1], r: r * S, fill: color }, layers.goo);
    await d.animate([{ cx: from[0], cy: from[1] }, { cx: to[0], cy: to[1] }], { duration: 650, easing: "cubic-bezier(.5,0,.4,1)", fill: "forwards" }).finished.catch(() => {});
    d.remove();
  }
  const stream = (from, color, n = 5, to = [CX, CY]) => Promise.all(Array.from({ length: n }, (_, i) => drop(from, to, color, i * 90, 8 - i * .6))).then(gulp);
  const gulp = () => !still && $s(".sp-body")?.animate([{ r: 52 * S }, { r: 58 * S }, { r: 52 * S }], { duration: 450, easing: "cubic-bezier(.3,1.6,.4,1)" });
  // a dotted ring that leaves Dot when something happens
  function ripple(color, to = 260) {
    if (still) return;
    const c = el("circle", { cx: CX, cy: CY, r: 56 * S, fill: "none", stroke: color, "stroke-width": 3, "stroke-linecap": "round", "stroke-dasharray": "0 10" }, svg);
    c.animate([{ r: 56 * S, opacity: 1 }, { r: to * S, opacity: 0 }], { duration: 1100, easing: "cubic-bezier(.2,.7,.3,1)" }).finished.then(() => c.remove(), () => c.remove());
  }
  // Dot's face: think, talk, happy, wow, sad; it settles back after a while
  let moodTimer;
  function mood(m, ms = 2600) {
    clearTimeout(moodTimer); root.dataset.mood = m;
    if (ms) moodTimer = setTimeout(() => { if (root.dataset.mood === m) delete root.dataset.mood; }, ms);
  }

  // ---- your creatures drop out of Dot one by one and stand on the input bar; one tap opens it on the Creatures page ----
  let crewHidden = false;
  async function crew(only = null) { // only: the id of a new creature, the one that drops; the rest are already standing
    if (crewHidden) return;
    const box = $s(".sp-crew"); let js = [];
    if (base === "/char") {
      try {
        const qData = await api("/char/questions");
        js = qData.questions || [];
        const sorterEl = h("button", { type: "button", class: "sp-cr sp-sorter", role: "listitem", style: "--bc:#ffb347; --i: 3",
          "aria-label": "Sorter: reads this character's chat and pulls out the names in it. Tap to run.", title: "Sorter reads this character's chat for names",
          onclick: () => runSorter(sorterEl) }, crBody(), h("span", { class: "sp-crname" }, "Sorter · chat"));
        const prunerEl = h("button", { type: "button", class: "sp-cr sp-sorter", role: "listitem", style: "--bc:#ff7a8a; --i: 4",
          "aria-label": "Pruner: weighs each note and drops the ones the character does not need. Tap to run.", title: "Pruner drops notes the character does not need",
          onclick: () => runPruner(prunerEl) }, crBody(), h("span", { class: "sp-crname" }, "Pruner · notes"));
        const askerEl = h("button", { type: "button", class: "sp-cr sp-sorter", role: "listitem", style: "--bc:#6ff7ff; --i: 5",
          "aria-label": "Asker: checks each name belongs to this character's world, then asks who or what it is. Tap to run.", title: "Asker turns names into questions",
          onclick: async () => { if (learning) return; learning = true; askerEl.classList.add("busy"); restEl.hidden = false; restEl.textContent = "Asker is checking names…";
            try { const r = await api("/char/creatures/asker", { method: "POST", body: "{}" }); restEl.textContent = r.asked.length ? `Asker asked: ${r.asked.join(" · ")}` : `Asker: no new questions (${r.open.length} still open)`; apply(await api(base)); }
            catch { restEl.textContent = "Asker could not reach the model."; }
            finally { learning = false; askerEl.classList.remove("busy"); setTimeout(() => { restEl.hidden = true; }, 8000); } } }, crBody(), h("span", { class: "sp-crname" }, "Asker · names"));
        box.replaceChildren(sorterEl, askerEl, prunerEl, ...js.map((q) => h("a", {
          class: "sp-cr",
          role: "listitem",
          "data-job": q.id,
          href: "#creatures", title: `${q.name} watches ${q.watches}${q.every ? ` and acts every ${q.every}` : ""}: ${q.goal}`,
          "aria-label": `${q.name}: watches ${q.watches}${q.every ? `, acts every ${q.every}` : ""}. ${q.goal}`,
          style: `--bc: var(--theme-${q.color ?? 6}); --i: ${q.id % 7}`,
        }, crBody(), h("span", { class: "sp-crname" }, `${q.name} · ${q.watches}`))));
        return;
      } catch {}
    }
    try { js = (await api("/jobs")).jobs; } catch { return; } // no creatures: the bar stays bare
    box.replaceChildren(...js.slice(0, 10).map((j) => h("a", { href: "#creatures", class: "sp-cr", role: "listitem", "data-job": j.id, "aria-label": `${j.name}: open on the Creatures page`, style: `--bc: var(--theme-${j.color ?? 6}); --i: ${j.id % 7}` },
      crBody(), h("span", { class: "sp-crname" }, j.name))));
    if (still) return;
    const o = root.getBoundingClientRect();
    [...box.children].filter((c) => only == null || +c.dataset.job === only).forEach((c, i) => { const b = c.getBoundingClientRect(), dx = o.left + CX - b.left - b.width / 2, dy = o.top + CY - b.top - b.height / 2;
      c.animate([{ transform: `translate(${dx}px, ${dy}px) scale(.2)`, opacity: 0 }, { transform: `translate(${dx * .1}px, -24px) scale(1.1)`, opacity: 1, offset: .75 }, { transform: "none" }],
        { duration: 900, delay: 400 + i * 140, easing: "cubic-bezier(.45,0,.3,1)", fill: "backwards" }).finished.then(() => { if (i === 0 || i % 3 === 0) gulp(); }, () => {}); });
  }

  async function ladderHookAnimation() {
    const box = $s(".sp-crew");
    if (!box) return;
    const crs = [...box.children];
    if (!crs.length) return;
    mood("wow", 3500);
    ripple("#ffe347", 340);
    const s = root.getBoundingClientRect();
    const dotX = CX, dotY = CY + 40;
    const total = crs.length;

    await Promise.all(crs.map((c, i) => {
      const b = c.getBoundingClientRect();
      const startX = b.left - s.left + b.width / 2;
      const startY = b.top - s.top + b.height / 2;
      const targetY = dotY + (total - i) * 26;
      const targetX = dotX + (i % 2 === 0 ? -6 : 6);
      return c.animate([
        { transform: "none" },
        { transform: `translate(${targetX - startX}px, ${targetY - startY}px) scale(1.15) rotate(${(i % 2 === 0 ? -8 : 8)}deg)` }
      ], { duration: 600, delay: i * 45, easing: "cubic-bezier(0.3, 1.4, 0.4, 1)", fill: "forwards" }).finished.catch(() => {});
    }));

    ripple("#6ff7ff", 280);
    $s(".sp-body")?.animate([
      { transform: "none" },
      { transform: "translate(0, 24px) scale(1.1, 0.9)" },
      { transform: "translate(0, -90px) scale(0.9, 1.2)" },
      { transform: "none" }
    ], { duration: 900, easing: "cubic-bezier(0.2, 1.6, 0.4, 1)" });

    await wait(450);

    await Promise.all(crs.map((c) => {
      return c.animate([
        { opacity: 1 },
        { transform: "translate(0, -220px) scale(0.5)", opacity: 0 }
      ], { duration: 500, easing: "cubic-bezier(0.1, 0.9, 0.2, 1)", fill: "forwards" }).finished.catch(() => {});
    }));

    await wait(400);
    crewHidden = true;
    box.replaceChildren();
  }

  // ---- a creature at work: its body on the bar hops, the card fills, and what it leaves shows up ----
  async function watchRun(id, job, { bar, label, out }) {
    const cr = $s(`.sp-cr[data-job="${job.id}"]`); cr?.classList.add("working");
    let r;
    for (;;) {
      try { r = await api(`/runs/${id}`); } catch { label.textContent = "Lost track of it. The Creatures page has it."; break; }
      bar.style.width = `${r.total ? 100 * r.done / r.total : 8}%`;
      label.textContent = r.status === "queued" ? "Waiting its turn…" : r.label || "Working…";
      if (!["queued", "running"].includes(r.status)) break;
      await wait(1200);
    }
    cr?.classList.remove("working");
    if (r?.status === "done") {
      bar.style.width = "100%"; mood("happy"); ripple(getComputedStyle(cr || root).getPropertyValue("--bc") || "#7dffa8", 300);
      label.textContent = job.output === "note" ? `Done. Saved to the note on ${r.paper}.` : "Done.";
      out.replaceChildren(...linked(r.result?.text || ""), job.output === "note"
        ? h("button", { type: "button", class: "sp-open", onclick: () => setNotes(true) }, "Open Notes →") : null);
      fit(out.closest(".sp-card"));
    } else if (r) { mood("sad", 3000); label.textContent = r.error || `It ${r.status}.`; }
  }
  // plain text with its links clickable, one line a row
  const linked = (text) => text.split("\n").filter((l) => l.trim()).map((l) => h("p", {}, ...l.split(/(https?:\/\/\S+)/).map((x, i) => i % 2 ? h("a", { href: x, target: "_blank", rel: "noopener" }, x.replace(/^https?:\/\/(www\.)?/, "").slice(0, 48)) : x)));

  // ---- the notes drawer: every paper with a note, each creature's block under its own name ----
  let notesOpen = false;
  async function setNotes(open) {
    notesOpen = open; const box = $s(".sp-notesbox"), btn = $s(".sp-notesbtn");
    box.hidden = !open; btn.setAttribute("aria-expanded", String(open)); btn.textContent = open ? "Hide notes" : "Notes";
    if (open && histOpen) setHistory(false);
    if (W > 980) layout();
    if (!open) return;
    box.replaceChildren(h("p", { class: "sp-empty" }, "Reading your notes…"));
    let ns = [];
    try { ns = (await api(`${base}/notes`)).notes; } catch { box.replaceChildren(h("p", { class: "sp-empty" }, "I could not read the notes.")); return; }
    box.replaceChildren(h("h2", {}, "Notes"), ...(ns.length ? ns.map((n) => h("article", { class: "sp-nb" },
      h("header", {}, h("b", {}, n.title || "Untitled"), h("button", { type: "button", onclick: () => travel(n) }, "Open →")),
      ...n.note.split(/^--- (.+?) ---\n([\s\S]*?)\n---$/m).reduce((acc, x, i, all) => { // fences: plain, title, text, plain, …
        if (i % 3 === 0) { if (x.trim()) acc.push(h("div", { class: "sp-nbtext" }, ...linked(x))); }
        else if (i % 3 === 1) acc.push(h("section", { class: "sp-nbblock" }, h("span", { class: "sp-nbby" }, `by ${x}`), ...linked(all[i + 1])));
        return acc; }, []))) : [h("p", { class: "sp-empty" }, "No notes yet. A creature that leaves notes will fill this.")]));
  }

  // ---- the transcript ----
  function row(t) {
    if (t.role === "user") return h("p", { class: "sp-you" }, t.text);
    const chips = (t.events || []).map((e) => { const v = vars.find((x) => x.id === e.var);
      const title = e.act ? (e.learned ? `Learned from ${(e.sources || []).join(", ") || "the web"}: ${e.learned}` : e.act_error || "")
        : e.say ? `${e.name} asked Dot to say: ${e.say}${e.corrected ? " (Dot left it out, so it was put in)" : ""}` : `${e.name} is on`;
      if (e.trigger === "set") return h("span", { class: "sp-chip", style: "--c:#6ff7ff", title }, e.learned ? `became ${e.act_arg}` : "lookup failed");
      return h("span", { class: "sp-chip", style: `--c:${v ? colorOf(v) : "#6ff7ff"}`, title },
        `${e.name} · ${SP_TRIG[e.trigger] ? SP_TRIG[e.trigger](e.n ?? v?.[e.trigger] ?? "", e) : e.trigger}${e.corrected ? " · fixed" : ""}${e.reset ? " · back to 0" : ""}${e.act && e.trigger !== "set" ? (e.tint ? ` · turned ${e.tint}` : e.results ? ` · searched “${e.query}”` : e.learned ? ` · became ${e.act_arg}` : e.open ? ` · opened ${e.open.title}${e.made ? `, made ${e.made}` : ""}` : e.made ? ` · made ${e.made}` : e.creature || e.sleep ? "" : e.act_error ? " · failed" : e.act === "recolor" ? " · no colour" : e.act === "search" ? " · search failed" : " · lookup failed") : ""}${e.creature ? ` · hatched ${e.creature.name}` : ""}${e.sleep ? " · asleep" : ""}`); });
    return h("div", { class: "sp-dot" }, chips.length ? h("div", { class: "sp-chips" }, chips) : null, h("p", {}, t.text));
  }
  function say(t) { log.append(row(t)); log.scrollTop = log.scrollHeight; }
  // what you send turns into dots that fly into Dot
  async function absorb(text) {
    if (still) return;
    const ir = form.say.getBoundingClientRect(), s = root.getBoundingClientRect();
    const probe = h("div", { class: "sp-probe", "aria-hidden": "true" }, [...text.slice(0, 120)].map((c) => h("span", { class: c.trim() ? "" : "sp-gap" }, c)));
    probe.style.cssText = `left:${ir.left - s.left}px;top:${ir.top - s.top}px;width:${ir.width}px;height:${ir.height}px`;
    root.append(probe);
    await wait(40); probe.classList.add("dots");
    const spans = [...probe.children].filter((x) => !x.classList.contains("sp-gap"));
    await wait(220);
    await Promise.all(spans.map((sp, i) => { const r = sp.getBoundingClientRect(), dx = CX - (r.left - s.left + r.width / 2), dy = CY - (r.top - s.top + r.height / 2);
      return sp.animate([{ translate: "0 0", scale: 1 }, { translate: `${dx * .5}px ${dy * .5 - 40}px`, scale: 1.3, offset: .5 }, { translate: `${dx}px ${dy}px`, scale: .4, opacity: .6 }],
        { duration: 760, delay: Math.min(i * 14, 900), easing: "cubic-bezier(.45,0,.35,1)", fill: "forwards" }).finished.catch(() => {}); }));
    probe.remove(); gulp();
  }
  // Dot's reply leaves its body as dots; each dot lands where a word goes and turns into the word
  let voiceFrom = "", voiceNow;
  async function talk(text) { // the model server's voice when a speaking model is loaded, else the browser's own
    if (!text) return; voiceNow?.pause?.(); speechSynthesis?.cancel();
    try { const r = await fetch("/char/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      if (!r.ok) throw new Error(await r.text());
      voiceNow = new Audio(URL.createObjectURL(await r.blob())); voiceFrom = "model voice"; await voiceNow.play(); }
    catch { if (!window.speechSynthesis) return; const u = new SpeechSynthesisUtterance(text); u.pitch = 1.5; u.rate = 1.08; speechSynthesis.speak(u); voiceFrom = "browser voice"; }
    toolInfo();
  }
  async function emerge(t) {
    if (base === "/char" && voiceOn && t.role === "dot") talk(t.text);
    const r = row(t); r.classList.add("sp-quiet"); log.append(r); log.scrollTop = log.scrollHeight; // the full reply, for reading back and screen readers
    if (web) return web.say(t);
    const chips = r.querySelector(".sp-chips")?.cloneNode(true), p = h("p", {}), words = t.text.split(/(\s+)/);
    p.append(...words.map((w) => /^\s+$/.test(w) ? w : h("span", { class: "sp-w0" }, w)));
    const drew = t.drew?.length ? [h("div", { class: "sp-drew" }, "Drew on", ...t.drew.slice(0, 4).map((n) => h("span", {}, n.title.replace(/^\w+: /, ""))))] : [];
    if (base === "/char" && !still) { root.classList.add("pouring"); stage.style.top = `${CY + 24 * S}px`; } // Dot becomes the ink: it shrinks to a seed and the words sit where it was
    stage.replaceChildren(...(chips ? [chips] : []), p, ...drew); stage.classList.remove("gone");
    if (base === "/char") for (let f = 17; f > 15 && p.scrollHeight > p.clientHeight + 2; f--) p.style.fontSize = `${f - 1}px`; // five lines hold it: the type gets smaller, not cut
    p.classList.toggle("sp-more", p.scrollHeight > p.clientHeight + 2);
    const spans = [...p.querySelectorAll(".sp-w0")];
    if (still) { spans.forEach((x) => x.classList.add("sp-in")); return; }
    if (base === "/char") { mood("talk", 0); await melt(p); if (root.dataset.mood === "talk") delete root.dataset.mood;
      await wait(Math.min(3000 + spans.length * 260, 20000));
      if (p.isConnected) { if (!root.classList.contains("carded")) await drink(p); root.classList.remove("pouring"); stage.style.top = `${CY + 226 * S}px`; } // a newer reply owns the stage otherwise
      return; }
    mood("talk", 0);
    const s = root.getBoundingClientRect(), talk = setInterval(() => $s(".sp-body")?.animate([{ r: 52 * S }, { r: 56 * S }, { r: 52 * S }], { duration: 150 }), 160);
    await Promise.all(spans.map(async (w, i) => {
      const box = w.getBoundingClientRect(), x = box.left - s.left + box.width / 2, y = box.top - s.top + box.height / 2, delay = Math.min(i * 45, 2400);
      if (box.bottom > stage.getBoundingClientRect().bottom) { await wait(delay); w.classList.add("sp-in"); return; } // past the fold: the transcript has it
      const d = h("i", { class: "sp-fly", "aria-hidden": "true" }); d.style.cssText = `left:${CX}px;top:${CY}px`; root.append(d);
      await d.animate([{ translate: "0 0", scale: 1.6 }, { translate: `${(x - CX) * .4}px ${(y - CY) * .3 + 30}px`, scale: 1.2, offset: .45 }, { translate: `${x - CX}px ${y - CY}px`, scale: .7 }],
        { duration: 620, delay, easing: "cubic-bezier(.3,.1,.3,1)", fill: "forwards" }).finished.catch(() => {});
      d.remove(); w.classList.add("sp-in");
    }));
    clearInterval(talk); if (root.dataset.mood === "talk") delete root.dataset.mood;
  }
  let liquid; // one goo filter: blurred text thresholded back to sharp edges reads as liquid; less blur, more letters
  function goo(p, from, to, ms) {
    if (!liquid) { const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg"); svg.setAttribute("aria-hidden", "true"); svg.style.cssText = "position:absolute;width:0;height:0";
      svg.innerHTML = '<filter id="sp-liquid" x="-20%" y="-80%" width="140%" height="260%"><feMorphology operator="dilate" radius="0"/><feGaussianBlur stdDeviation="0"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 24 -10"/></filter>';
      root.append(svg); liquid = [svg.querySelector("feMorphology"), svg.querySelector("feGaussianBlur")]; }
    p.style.filter = "url(#sp-liquid)";
    return new Promise((done) => { const t0 = performance.now();
      const tick = (t) => { const k = Math.min(1, (t - t0) / ms), e = 1 - (1 - k) ** 3, L = from + (to - from) * e; // L: 1 is one fat merged blob, 0 is crisp letters
        liquid[0].setAttribute("radius", (L * 9).toFixed(2)); liquid[1].setAttribute("stdDeviation", (L * 7).toFixed(2));
        if (k < 1 && p.isConnected) requestAnimationFrame(tick); else done(); };
      requestAnimationFrame(tick); });
  }
  async function melt(p) { // Dot pours down into one blob of its own colour, which settles into the sentence
    p.querySelectorAll(".sp-w0").forEach((w) => w.classList.add("sp-in", "sp-now"));
    p.animate([{ scale: ".15 .4", translate: `0 ${-40 * S}px`, opacity: .9 }, { scale: "1 1", translate: "0 0", opacity: 1 }], { duration: 900, easing: "cubic-bezier(.3,1.25,.5,1)" });
    await goo(p, 1, 0, 1700);
    if (p.isConnected) p.style.filter = ""; // crisp text to read
  }
  async function drink(p) { // backwards: the sentence melts into a blob and drains up into Dot, which fills out again; the transcript keeps it
    const back = p.animate([{}, { scale: ".1 .3", translate: `0 ${-50 * S}px`, opacity: 0 }], { duration: 900, easing: "cubic-bezier(.6,0,.8,.4)", fill: "forwards" });
    await Promise.all([goo(p, 0, 1, 700), back.finished.catch(() => {})]);
    if (p.isConnected) { stage.replaceChildren(); gulp(); mood("happy", 900); }
  }

  // a persona is something Dot wears, not a rule on the ring
  function take(st) { web?.data(st); if (st.graph) kg = st.graph; if (st.papers) papers = st.papers; all = st.vars; vars = st.vars.filter((v) => v.kind !== "persona"); tables = st.tables; }
  const LOOKS = ["glasses", "monocle", "bowtie", "holo", "visor"];
  function paint() { // a recolor rule's colour, over whatever Dot is wearing
    const tint = all.find((v) => v.tint)?.tint || "";
    root.classList.toggle("tinted", !!tint); root.style.setProperty("--dot", tint || "#ffe347");
  }
  async function dress(animate = true) { // puts on the persona's looks one after another, from the fixed list
    paint();
    const want = all.find((v) => v.learned)?.look || [];
    LOOKS.filter((l) => !want.includes(l)).forEach((l) => root.classList.remove(`look-${l}`));
    for (const l of want) { if (root.classList.contains(`look-${l}`)) continue; if (animate && !still) await wait(500); root.classList.add(`look-${l}`); if (animate) gulp(); }
  }

  // answers about the app come back as a card under Dot; each kind has its entrance, anything else gets the plain one
  function showCard(c) {
    const ask = (t) => { line = line.then(() => send(t)).catch(() => {}); };
    stage.querySelectorAll(".sp-card").forEach((el) => el.remove());
    let body;
    if (c.kind === "models") {
      body = [h("header", {}, h("b", {}, "Models"), h("span", {}, c.status)),
        h("div", { class: "sp-models" }, ...c.items.map((m, i) => h("button", {
          type: "button", class: `sp-model${m.current ? " on" : ""}`, disabled: m.current || m.embed, style: `--i:${i}`,
          title: `${m.id}${m.embed ? ": an embedding model, it can't chat" : m.current ? ": in use" : ""}`,
          onclick: () => ask(`switch to model ${m.id}`) }, h("i", {}), h("span", {}, m.id.split("/").pop()), m.embed ? h("small", {}, "embed") : m.current ? h("small", {}, "in use") : null)))];
    } else if (c.kind === "switched") {
      body = [h("header", {}, h("b", {}, "Model switched")),
        h("div", { class: "sp-swap" }, h("span", { class: "sp-from" }, c.from || "none"), h("i", { class: "sp-hop" }), h("span", { class: "sp-to" }, c.to))];
      mood("happy"); ripple("#6ff7ff", 300);
    } else if (c.kind === "papers") {
      body = [h("header", {}, h("b", {}, "Papers"), h("span", {}, `${c.items.length} in the library`)),
        h("div", { class: "sp-papers" }, ...c.items.map((p, i) => h("button", {
          type: "button", class: `sp-paper${p.id === c.pick ? " on" : ""}`, style: `--i:${i}`, title: `${p.title}${p.authors ? `\n${p.authors}` : ""}`,
          onclick: () => travel(p) },
          h("span", { class: "sp-cover" }, h("img", { src: `/papers/${p.id}/cover`, alt: "", loading: "lazy", onerror: (e) => e.target.remove() })),
          h("b", {}, p.title), p.authors ? h("small", {}, p.authors) : null)))];
      const pick = c.items.find((p) => p.id === c.pick);
      if (pick) setTimeout(() => travel(pick), 900); // named one: Dot goes straight there
    } else if (c.kind === "notes" && c.paper) {
      body = [h("header", {}, h("b", {}, "Notes"), h("span", {}, c.paper.title)),
        h("div", { class: "sp-notes" },
          ...c.highlights.map((m, i) => h("blockquote", { style: `--i:${i}` }, h("span", {}, `p. ${m.page}`), h("mark", {}, m.text))),
          c.note ? h("div", { class: "sp-note", style: `--i:${c.highlights.length}` }, c.note) : null,
          !c.highlights.length && !c.note ? h("p", { class: "sp-empty" }, "No highlights or notes on this paper yet.") : null),
        h("button", { type: "button", class: "sp-open", onclick: () => travel(c.paper) }, "Open the paper →")];
    } else if (c.kind === "chibi") { // pictures to pour Dot into: pick one and it fills it
      body = [h("header", {}, h("b", {}, "Pick a look"), h("span", {}, `${c.refs.length} pictures`)),
        h("div", { class: "sp-chibis" }, ...c.refs.map((r, i) => h("button", { type: "button", class: "sp-chibi", style: `--i:${i}`, title: r.title,
          onclick: async (e) => { const card = e.target.closest(".sp-card"); card?.classList.add("pouring");
            const res = await fetch("/char/chibi/pick", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: r.url, thumb: r.thumb }) }).catch(() => null);
            if (res?.ok) { web?.reform(await res.json()); card?.remove(); mood("happy"); ripple("#6ff7ff", 380); }
            else { card?.classList.remove("pouring"); e.target.closest("button")?.remove(); } } }, // that site refused: drop it, pick another
          h("img", { src: r.thumb, alt: r.title || "", loading: "lazy", referrerpolicy: "no-referrer", onerror: (e) => e.target.closest("button").remove() }))))];
    } else if (c.kind === "creature") {
      const j = c.job, reads = (j.steps || []).map((x) => CR_READS[x.scope] || x.scope).join(", then ");
      body = [h("header", {}, h("b", {}, c.new ? "New creature" : "Creature"), h("span", {}, j.name)),
        h("div", { class: "sp-crcard", style: `--bc: var(--theme-${j.color ?? 6}); --i: ${j.id % 7}` }, crBody(),
          h("p", {}, h("b", {}, j.name), h("span", {}, `Reads ${reads}. Leaves ${(CR_OUT_SHORT[j.output] || j.output).toLowerCase()}.`))),
        h("button", { type: "button", class: "sp-open", onclick: () => ask(`run ${j.name}`) }, "Run it on my last paper →")];
      if (c.new) crew(j.id); // it drops out of Dot onto the bar
    } else if (c.kind === "run") {
      const bar = h("i", {}), label = h("span", {}, "Waiting its turn…"), out = h("div", { class: "sp-runout" });
      body = [h("header", {}, h("b", {}, c.job.name), h("span", {}, c.run.paper || "")),
        h("div", { class: "sp-run" }, h("span", { class: "sp-runbar" }, bar), label), out];
      watchRun(c.run.id, c.job, { bar, label, out });
    } else if (c.kind === "crew") { if (c.show) { crewHidden = false; crew(); } else ladderHookAnimation(); return; }
    else if (c.kind === "go") { setTimeout(() => { libStore.set("lib-mode", c.to); location.hash = "#library"; }, 700); return; }
    else if (c.kind === "help") {
      const can = [["Open a paper", () => ask("open a pdf preview")], ["Add a PDF", () => $s(".sp-pick").click()],
        ["Count a word", () => fill("count hello; when hello reaches 3 change color to blue and reset hello to 0")],
        ["Make a creature", () => fill("create a creature that finds similar papers and adds them to my notes")],
        ["Run a creature", () => fill("run ")], ["Show my notes", () => setNotes(true)], ["Open my shelf", () => ask("open my shelf")],
        ["Switch model", () => ask("show me the list of models")], ["Talk like someone", () => fill("set persona as ")], ["Go to sleep", () => fill("shut down")]];
      body = [h("header", {}, h("b", {}, "What I can do")),
        h("div", { class: "sp-help" }, ...can.map(([label, run], i) => h("button", { type: "button", style: `--i:${i}`, onclick: run }, label)))];
    } else if (c.kind === "sleep") { sleep(); return; }
    else if (c.kind === "web") {
      const counted = vars.filter((v) => v.kind === "count" && v.pattern).map((v) => { try { return new RegExp(v.pattern, "gi"); } catch { return null; } }).filter(Boolean);
      const marked = (t) => { // the words the counters count, marked in what came back
        let parts = [t];
        for (const re of counted) parts = parts.flatMap((x) => typeof x !== "string" ? [x] : x.split(new RegExp(`(${re.source})`, "gi")).map((y, i) => i % 2 ? h("mark", {}, y) : y));
        return parts; };
      body = [h("header", {}, h("b", {}, "Web"), h("span", {}, c.query)),
        h("div", { class: "sp-web" }, ...c.results.map((r, i) => h("a", { href: r.url, target: "_blank", rel: "noopener", style: `--i:${i}` },
          h("b", {}, ...marked(r.title)), r.snippet ? h("small", {}, ...marked(r.snippet)) : null))),
        Object.keys(c.fed || {}).length ? h("p", { class: "sp-fed" }, Object.entries(c.fed).map(([k, n]) => `${k} ${spSigned(n)} from these pages`).join(" · ")) : null];
    }
    else if (c.kind === "job") {
      body = [h("header", {}, h("b", {}, "Autonomous Job"), h("span", {}, c.status || "completed")),
        h("div", { class: "sp-jobcard" }, h("b", {}, c.title), h("p", {}, c.result || c.goal))];
    }
    else body = [h("pre", {}, JSON.stringify(c, null, 1))]; // shortcut: raw fields for a card kind the page does not know yet
    const closeBtn = h("button", {
      type: "button",
      class: "sp-card-close",
      "aria-label": "Close notification",
      title: "Close (Esc)",
      onclick: (e) => { e.stopPropagation(); dismissCard(); }
    }, "×");
    const foot = h("footer", { class: "sp-card-foot" },
      h("button", {
        type: "button",
        class: "sp-card-back",
        "aria-label": "Back to Orbit",
        onclick: (e) => { e.stopPropagation(); dismissCard(); }
      }, "← Back to Orbit")
    );
    const card = h("div", { class: `sp-card sp-card-${["models", "switched", "papers", "notes", "web", "creature", "run", "job", "help"].includes(c.kind) ? c.kind : "plain"}` }, closeBtn, ...body, foot);
    stage.append(card); root.classList.add("carded"); // Dot's scene shrinks up out of the way so the card has room
    const p = stage.querySelector(":scope > p"); if (p) p.classList.toggle("sp-more", p.scrollHeight > p.clientHeight + 2);
    fit(card);
  }
  function dismissCard() {
    const card = stage.querySelector(".sp-card");
    if (!card) return;
    card.animate([{ opacity: 1, scale: 1 }, { opacity: 0, scale: 0.94 }], { duration: 160, easing: "ease-out" })
      .finished.catch(() => {}).then(() => {
        stage.querySelectorAll(".sp-card").forEach((el) => el.remove());
        root.classList.remove("carded");
        root.style.removeProperty("--shrink");
        layout();
        form.say?.focus();
      });
  }
  function fit(card) { // a card that grows (a creature's results coming in) asks again for room
    if (!card.isConnected) return;
    card.style.maxHeight = "";
    const formTop = form.getBoundingClientRect().top - root.getBoundingClientRect().top - ($s(".sp-crew").offsetHeight && 44), head = card.offsetTop; // chips + reply above the card
    const k = Math.max(.42, Math.min(1, (formTop - 16 - Math.min(340, card.scrollHeight) - head - 64) / (CY + 226 * S - 64)));
    root.style.setProperty("--shrink", k); root.style.setProperty("--cx", `${CX}px`); root.style.setProperty("--cy", `${CY}px`);
    stage.style.top = `${64 + (CY + 226 * S - 64) * k}px`;
    const room = formTop - 16 - (64 + (CY + 226 * S - 64) * k) - head;
    card.style.maxHeight = `${Math.max(120, room)}px`; // never over the input
  }

  // opening a paper: Dot pulls the whole space into itself, projects the reader, and shrinks into the corner buddy
  async function travel(p) {
    if (root.classList.contains("leaving")) return;
    const go = () => { location.hash = `#read/${p.id}`; };
    if (still) return go();
    root.classList.add("leaving"); mood("wow", 0);
    const box = root.getBoundingClientRect(), dx = box.left + CX, dy = box.top + CY, d = 104 * S;
    const ghost = h("div", { class: `sp-ghost ${[...root.classList].filter((k) => k.startsWith("look-")).join(" ")}`,
      style: `left:${dx - d / 2}px;top:${dy - d / 2}px;width:${d}px;height:${d}px;background:${getComputedStyle($s(".sp-body")).fill}` });
    ghost.append($s(".sp-eyes").cloneNode(true)); ghost.firstChild.removeAttribute("style"); ghost.firstChild.style.scale = S;
    document.body.append(ghost);
    const suck = (el, i) => { const b = el.getBoundingClientRect(); if (!b.width) return;
      el.animate([{}, { transform: `translate(${dx - b.left - b.width / 2}px, ${dy - b.top - b.height / 2}px) scale(0)`, opacity: 0 }],
        { duration: 520, delay: i * 50, easing: "cubic-bezier(.55,0,.8,.2)", fill: "forwards" }); };
    svg.style.transformOrigin = `${CX}px ${CY}px`;
    [svg, ...root.querySelectorAll(".sp-tools .lblob, .sp-moon, .sp-info, .sp-vars, .sp-stage, .sp-stats, .sp-hist, .sp-log, .sp-ear")].forEach(suck);
    ghost.animate([{ scale: 1 }, { scale: 1.25 }, { scale: 1 }], { duration: 520, delay: 300, easing: "ease-in-out" }); // a gulp
    await wait(800);
    const screen = h("div", { class: "sp-screen", style: `--x:${dx}px;--y:${dy}px` }, // the reader, projected out of Dot
      h("header", {}, h("b", {}, p.title), p.authors ? h("small", {}, p.authors) : null),
      h("div", { class: "sp-sheet" }, ...Array.from({ length: 14 }, (_, i) => h("i", { style: `--w:${55 + (i * 37) % 45}%;--i:${i}` }))));
    document.body.insertBefore(screen, ghost);
    await wait(650);
    go(); await wait(120);
    const face = document.querySelector(".buddy:not([hidden]) .buddy-face")?.getBoundingClientRect();
    const to = face?.width ? face : { left: innerWidth - 84, top: innerHeight - 84, width: 64, height: 64 };
    await ghost.animate([{}, { left: `${to.left}px`, top: `${to.top}px`, width: `${to.width}px`, height: `${to.height}px`, borderRadius: "22px" }],
      { duration: 650, easing: "cubic-bezier(.45,.05,.25,1)", fill: "forwards" }).finished;
    screen.animate([{}, { opacity: 0 }], { duration: 350, fill: "forwards" });
    await ghost.animate([{}, { opacity: 0 }], { duration: 250, fill: "forwards" }).finished;
    ghost.remove(); screen.remove();
    try { sessionStorage.setItem("sp-back", "1"); } catch { /* no unfold on the way back */ }
    buddy.say(`Here is ${p.title}.`, { mood: "happy", actions: [{ label: "Back to the space", href: "#space" }] }); // shown only while the buddy is awake
    const pill = h("a", { class: "sp-backpill", href: "#space" }, "← Back to Dot"); // always there, so the way back never depends on the buddy
    document.body.append(pill);
    addEventListener("hashchange", () => pill.remove(), { once: true });
  }

  // back to the Library: everything folds into Dot, which is where the Library starts
  $s(".sp-home").addEventListener("click", async (e) => {
    if (still) return; e.preventDefault(); root.classList.add("leaving");
    const box = root.getBoundingClientRect(), dx = box.left + CX, dy = box.top + CY;
    svg.style.transformOrigin = `${CX}px ${CY}px`;
    const parts = [...root.querySelectorAll(".sp-tools .lblob, .sp-moon, .sp-info, .sp-vars, .sp-stage, .sp-stats, .sp-hist, .sp-ear, .sp-home")];
    parts.forEach((el, i) => { const b = el.getBoundingClientRect(); if (!b.width) return;
      el.animate([{}, { transform: `translate(${dx - b.left - b.width / 2}px, ${dy - b.top - b.height / 2}px) scale(0)`, opacity: 0 }],
        { duration: 450, delay: i * 25, easing: "cubic-bezier(.55,0,.8,.2)", fill: "forwards" }); });
    svg.animate([{}, { opacity: .2, transform: "scale(.6)" }], { duration: 500, fill: "forwards" });
    const here = location.hash; await wait(450 + parts.filter((el) => el.getBoundingClientRect().width).length * 25); if (location.hash === here) location.hash = "#library"; // a nav click during the fold wins
  });

  // ---- sleep: "shut down" powers Dot off; only three knocks on Dot wake it ----
  const knock = $s(".sp-knock");
  function sleep(animate = true) {
    root.classList.add("asleep"); if (animate && !still) root.classList.add("powering-down");
    setTimeout(() => root.classList.remove("powering-down"), 1400);
    form.say.disabled = true; form.say.placeholder = "Asleep. Knock on Dot three times";
    knock.hidden = false; knock.style.left = `${CX}px`; knock.style.top = `${CY}px`; knock.style.width = knock.style.height = `${120 * S}px`;
    buddy.sleep(true); // the same sleep as the reading buddy's: AI off everywhere, until Dot is woken
  }
  // asleep by a rule, Dot reflects: one /rest step at a time, shown in a status line, summed up on waking
  const restEl = h("p", { class: "sp-rest", role: "status", hidden: "" }); root.append(restEl);
  let did = [], lastQs = [], run = 0;
  async function reflect() {
    const mine = ++run; did = []; lastQs = []; const asleep = () => mine === run && root.isConnected && root.classList.contains("asleep"); // a newer loop, or leaving the page, ends this one
    form.say.placeholder = "Asleep and reflecting. Knock on Dot three times"; restEl.hidden = false;
    for (let n = 0; n < 6 && asleep(); n++) {
      restEl.textContent = "Reflecting…";
      let r; try { r = await api("/char/rest", { method: "POST", body: JSON.stringify({ char: base === "/char", n }) }); } catch { break; }
      if (!asleep() || !r || r.done) break;
      did.push({ kind: r.kind, topic: r.topic, note: r.note }); lastQs = r.questions || [];
      const note = (r.note || "").length > 140 ? `${r.note.slice(0, 139)}…` : r.note || "";
      restEl.textContent = r.kind === "wonder" ? `Wondering: ${note}` : `${{ reflect: "Read about", fill: "Learned", practise: "Practised" }[r.kind] || "Thought about"} ${r.topic}. ${note}`;
      if (!still) ripple("#6ff7ff", 160);
    }
    if (asleep()) restEl.textContent = "Done reflecting. Knock three times to wake me.";
  }
  let knocks = [];
  knock.addEventListener("click", async () => {
    const now = Date.now(); knocks = [...knocks.filter((t) => now - t < 1600), now];
    $s(".sp-eyes").animate([{ translate: "-50% -50%" }, { translate: "calc(-50% - 4px) -50%" }, { translate: "calc(-50% + 4px) -50%" }, { translate: "-50% -50%" }], { duration: 220 });
    gulp(); ripple("rgb(255 255 255 / .35)", 90 + knocks.length * 40);
    if (knocks.length < 3) return;
    knocks = []; knock.hidden = true;
    root.classList.remove("asleep"); root.classList.add("waking"); setTimeout(() => root.classList.remove("waking"), 1600);
    buddy.sleep(false);
    form.say.disabled = false; form.say.placeholder = "Ask Dot anything…";
    restEl.hidden = true; restEl.textContent = "";
    const done = did, qs = lastQs; did = []; lastQs = [];
    await wait(700); mood("wow"); ripple("#ffe347", 380);
    await emerge({ role: "dot", text: done.length ? `I'm up! While I slept I worked on ${[...new Set(done.map((d) => d.topic))].join(", ")}.` : "I'm up! Three knocks. What did I miss?", events: [] });
    if (done.length) {
      showCard({ kind: "job", title: "What I did asleep", status: "Reflection", result: done.map((d) => `${d.topic}: ${d.note}`).join("\n\n") });
      if (done.some((d) => d.kind === "fill")) { try { apply(await api(base)); await dress(); } catch { /* the next reply refreshes it */ } }
      if (qs.length) renderLearnChips(qs);
    }
    form.say.focus();
  });

  // the corner shows what the space is doing, in numbers
  function stats() {
    const persona = all.find((v) => v.learned)?.act_arg;
    const rowsOf = [["Turns", tables.chat_turns ?? 0], ["Variables", vars.length], ["Rules fired", firedCount],
      ["Persona", persona || "Dot"], ["Papers", tables.papers ?? 0]];
    $s(".sp-stats").replaceChildren(...rowsOf.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))]));
    $s(".sp-hist").textContent = histOpen ? "Hide history" : `History · ${log.children.length}`;
  }
  function setHistory(open) {
    if (open && notesOpen) setNotes(false);
    histOpen = open; root.classList.toggle("hist-open", open); $s(".sp-hist").setAttribute("aria-expanded", String(open));
    try { localStorage.setItem("sp-history", open ? "1" : "0"); } catch { /* this visit only */ }
    layout(); stats(); if (open) log.scrollTop = log.scrollHeight;
  }

  function apply(st) {
    if (!st || !st.vars) return;
    const fresh = st.vars.filter((v) => !vars.some((o) => o.id === v.id)), gone = vars.some((o) => !st.vars.some((v) => v.id === o.id));
    take(st);
    drawCards(); drawGraph(); toolInfo();
    drawVars(); stats(); // first: on a narrow screen the rings sit below the readouts
    if (gone || W <= 980) layout(); else { vars.forEach((v) => arcs.has(v.id) ? light(v) : drawArc(v)); drawFloor(); lead(); }
    return fresh;
  }

  async function send(text) {
    const answering = !!document.querySelector(".sw-skip")?.offsetParent; // the "your next message teaches it" prompt is on screen: only then is this an answer
    web?.heard(text);
    lastSent = Date.now(); // idle learning waits for a quiet chat
    const input = form.say; root.setAttribute("aria-busy", "true");
    say({ role: "user", text }); log.lastChild.classList.add("sp-quiet");
    stage.classList.add("gone"); root.classList.remove("carded"); stage.style.top = `${CY + 226 * S}px`; // the last reply makes room
    const flying = absorb(text), hint = input.placeholder; input.value = ""; input.placeholder = ""; // the letters are flying out of it
    flying.then(() => { input.placeholder = hint; });
    await flying; root.classList.add("thinking"); mood("think", 0);
    let r;
    try { r = await api(`${base}/say`, { method: "POST", body: JSON.stringify({ text, learn_mode: learnMode, answering }) }); }
    catch (e) { r = { reply: e.body?.detail || "Something went wrong. Try again." }; }
    root.classList.remove("thinking"); if (root.dataset.mood === "think") delete root.dataset.mood;
    const before = new Map(vars.map((v) => [v.id, v.value]));
    const fresh = apply(r) || []; fire(r.recall);
    if (fresh.length) { mood("happy"); ripple("#ffe347", 200); }
    for (const v of fresh) await drop([CX, CY], mid(v), colorOf(v), 0, 14);
    if ((r.events || []).some((e) => e.trigger === "removed")) { mood("wink"); ripple("rgb(255 255 255 / .5)", 180); }
    if ((r.events || []).some((e) => e.trigger === "set" && e.learned)) { ripple("#6ff7ff", 380); mood("wow"); }
    if ((r.events || []).some((e) => e.trigger === "ladder_hook")) { await ladderHookAnimation(); }
    await dress();
    for (const v of vars) if (before.has(v.id) && before.get(v.id) !== v.value) drop(mid(v), stackAt("variables"), colorOf(v));
    for (const e of (r.events || []).filter((x) => !["made", "removed"].includes(x.trigger))) {
      const v = vars.find((x) => x.id === e.var); if (!v) continue; flare(v); mood(e.trigger === "past" ? "happy" : "wow"); ripple(colorOf(v));
      if (e.tint) { await wait(150); paint(); ripple(e.tint, 380); gulp(); mood("wow"); }
      if (e.learned) { ripple("#6ff7ff", 380); await wait(250); ripple("#6ff7ff", 300); mood("wow"); await dress(); }
      const t = vars.find((x) => x.id === e.target);
      if (t) { await drop(mid(v), mid(t), colorOf(v), 0, 11); flare(t); } // a watcher pushes goo into the variable it acts on
      if (e.say) await stream(mid(v), colorOf(v), 4);
    }
    firedCount += (r.events || []).filter((e) => !["made", "removed"].includes(e.trigger)).length;
    const sad = r.error || !r.vars;
    await emerge({ role: "dot", text: r.reply || r.error || "…", events: r.events || [], drew: r.recall?.notes });
    if (sad) mood("sad", 3000);
    const found = (r.events || []).filter((e) => e.results); // the last search a rule ran comes up as a card
    const opened = (r.events || []).find((e) => e.open); // a rule opened a paper: Dot takes you there
    const sheetEv = (r.events || []).find((e) => e.trigger === "set" && e.sheet); // Dot became someone: show who
    if (r.outfit) web?.reform(r.outfit); // it changed its chibi outfit: the new look shows at once
    if (r.card) showCard(r.card);
    else if (sheetEv) showCard({ kind: "job", title: `${sheetEv.name}'s sheet`, status: "Character sheet",
      result: Object.entries(sheetEv.sheet).map(([k, v]) => `${k}: ${v || "learns this while asleep"}`).join("\n") });
    else if (opened) showCard({ kind: "papers", items: [opened.open], pick: opened.open.id });
    else if (found.length) { const e = found.at(-1); showCard({ kind: "web", query: e.query, results: e.results, fed: found.reduce((a, x) => { for (const [k, n] of Object.entries(x.fed || {})) a[k] = (a[k] || 0) + n; return a; }, {}) }); }
    if (r.questions) renderLearnChips(r.questions);
    stats();
    root.removeAttribute("aria-busy"); input.focus();
    if (base === "/char" && ++said % 4 === 0 && !(r.events || []).some((e) => e.sleep)) learnOne(); // awake, it still learns: one small step every few turns
    if ((r.events || []).some((e) => e.sleep)) { await wait(1200); sleep(); reflect(); } // only a rule's sleep reflects; "shut down" and a reload do not
  }

  let said = 0;
  let learning = false, lastSent = 0;
  const DID = { reflect: "Read about", wonder: "Wondered", fill: "Wrote down", practise: "Practised", extract: "Found names in", ideas: "Found ideas in", ask: "Asked", plan: "Planned", goal: "Made a goal from", check: "Checked the note on", review: "Reread its reply to", sort: "Read", fold: "Folded what it knows about" };
  async function learnOne(asked, n) {
    if (learning) return; learning = true; // one model run at a time
    web?.busy(); const quiet = root.classList.contains("asleep"), stop = quiet ? () => {} : seek(); // curiosity made visible: Dot pings out while it looks something up
    let r; try { r = await api("/char/rest", { method: "POST", body: JSON.stringify({ char: true, n, force: !!asked }) }); } catch { learning = false; stop(); web?.stepped(null); return; } finally { learning = false; }
    stop(); web?.stepped(r);
    if (r?.incurious && !quiet && !r.quiet) { restEl.hidden = false; restEl.textContent = "Not curious right now: curiosity is below 1, so it does not learn by itself."; }
    if (r?.quiet) restEl.hidden = true; // quiet mode: no pill, nothing to say
    if (!r || r.done || !root.isConnected) return;
    if (!quiet && !web) await found(r);
    if (r.said && !root.querySelector(".sp-sys")) emerge({ role: "dot", text: r.said, events: [] }); // proactive: it speaks first
    if (!asked && root.querySelector(".sp-sys")) openSystems(true, r.system); // the open Wiring view follows along
    if (!root.classList.contains("asleep")) { restEl.hidden = false; restEl.textContent = `${r.system === 3 ? "V" : `S${r.system}`} · ${DID[r.kind] || "Learned"} ${r.topic}${r.note ? `: ${r.note.slice(0, 110)}` : ""}`; // a word on what it just did, then the reply line is back
      clearTimeout(learnOne.t); learnOne.t = setTimeout(() => { if (!root.classList.contains("asleep")) restEl.hidden = true; }, 6000); }
    try { apply(await api(base)); } catch { return; } // the corner panel shows what it just learned
    if (!still) ripple("#7dffa8", 200);
    $s(".sp-ilast")?.animate([{ color: "#7dffa8" }, { color: "" }], { duration: 2400 });
  }
  function seek() { // while a step runs: sonar rings leave Dot and the thread to the name it is curious about brightens
    if (base !== "/char" || still || !layers?.kg) return () => {};
    root.classList.add("seeking"); restEl.hidden = false; restEl.textContent = "Curious… looking something up";
    const L = layers.kg, next = kg.nodes.filter((n) => !n.known).sort((x, y) => y.n - x.n)[0];
    L.querySelector(`[data-name="${CSS.escape(next?.name || "")}"]`)?.classList.add("sought");
    const rings = [0, 1, 2].map((i) => { const c = el("circle", { cx: CX, cy: CY, r: 60 * S, class: "sp-sonar", style: `transform-origin:${CX}px ${CY}px` }, L);
      c.animate([{ scale: 1, opacity: .5 }, { scale: 5, opacity: 0 }], { duration: 2400, delay: i * 800, iterations: Infinity, easing: "ease-out" }); return c; });
    return () => { root.classList.remove("seeking"); rings.forEach((c) => c.remove()); L.querySelectorAll(".sought").forEach((g) => g.classList.remove("sought")); };
  }
  async function found(r) { // a step came back: new questions float up from their names, or what it read streams into Dot and the name lights up
    if (base !== "/char" || still || !layers?.kg) return;
    const named = (t) => kg.nodes.map((n) => n.name).filter((n) => t.toLowerCase().includes(n.toLowerCase())).sort((a, b) => b.length - a.length).slice(0, 1);
    if (r.kind === "ask") r.note.split("; ").forEach((q, i) => named(q).forEach((n) => { const p = kgAt.get(n); if (!p) return;
      const t = el("text", { x: p[0], y: p[1] - 14, class: "sp-kg-q", "text-anchor": "middle" }, layers.kg); t.textContent = "?";
      t.animate([{ translate: "0 0", opacity: 0 }, { opacity: 1, offset: .2 }, { translate: "0 -46px", opacity: 0 }], { duration: 2200, delay: i * 300, easing: "ease-out" }).finished.then(() => t.remove(), () => t.remove()); }));
    else await fire({ names: named(`${r.topic} ${r.kind === "extract" ? "" : r.note}`) });
    if (r.graph) { kg = r.graph; drawGraph(); }
  }
  // Sorter: one message per call, so you watch the names land one by one; the dial is how many it reads per run
  const SORTER_LIMIT = 12;
  async function runSorter(el) {
    if (learning) return; learning = true; el.classList.add("busy"); restEl.hidden = false;
    try {
      for (let i = 0; i < SORTER_LIMIT && root.isConnected; i++) {
        let r; try { r = await api("/char/creatures/sorter", { method: "POST", body: JSON.stringify({ limit: 1 }) }); } catch { restEl.textContent = "Sorter could not reach the model."; break; }
        const got = r.read[0];
        if (!got) { restEl.textContent = `Sorter has read all ${r.total} messages.`; break; }
        restEl.textContent = `Sorter read ${r.total - r.left} of ${r.total}: “${got.text.slice(0, 60)}” → ${got.names.join(", ") || "no names"}`;
        kg = r.graph; drawGraph(); toolInfo(); stats();
        if (!r.left) { restEl.textContent += ` · done`; break; }
      }
    } finally { learning = false; el.classList.remove("busy"); try { apply(await api(base)); } catch { /* the next reply refreshes it */ } setTimeout(() => { if (!root.classList.contains("asleep")) restEl.hidden = true; }, 8000); }
  }

  async function runPruner(el) { // one note per call, so you watch what the character can live without
    if (learning) return; learning = true; el.classList.add("busy"); restEl.hidden = false;
    const k = (c) => c >= 1000 ? `${(c / 1000).toFixed(1)}k` : c;
    let start;
    try {
      for (let i = 0; i < SORTER_LIMIT && root.isConnected; i++) {
        let r; try { r = await api("/char/creatures/pruner", { method: "POST", body: "{}" }); } catch { restEl.textContent = "Pruner could not reach the model."; break; }
        start ??= r.before || { notes: r.notes, chars: r.chars };
        if (!r.note) { restEl.textContent = `Pruner has weighed every note · ${start.notes} → ${r.notes} notes, ${k(start.chars)} → ${k(r.chars)} chars`; break; }
        restEl.textContent = `Pruner ${r.dropped ? "dropped" : "kept"} “${r.note.title.replace(/^\w+: /, "").slice(0, 40)}” · holds ${r.notes} notes, ${k(r.chars)} chars (was ${start.notes}, ${k(start.chars)})`;
        if (r.dropped) { root.querySelector(`.sp-notemoon[data-id="${r.note.id}"]`)?.animate([{}, { scale: 0, opacity: 0 }], { duration: 500, fill: "forwards" }); kg = r.graph; drawGraph(); }
      }
    } finally { learning = false; el.classList.remove("busy"); try { apply(await api(base)); } catch { /* the next reply refreshes it */ } setTimeout(() => { if (!root.classList.contains("asleep")) restEl.hidden = true; }, 10000); }
  }

  if (base === "/char") { // left alone and awake, it learns by itself now and then: a few small steps per visit, so the model is not kept busy
    let idleSteps = 0;
    const idle = setInterval(() => { if (!root.isConnected) return clearInterval(idle);
      if (idleSteps >= 12 || document.visibilityState !== "visible" || root.classList.contains("asleep") || root.getAttribute("aria-busy") || Date.now() - lastSent < 20000) return;
      idleSteps++; learnOne(); }, 30000);
  }
  function toolInfo() { // each tool moon says what it holds right now
    if (base !== "/char") return;
    const who = all.find((v) => v.kind === "persona")?.act_arg || "Dot", next = kg.nodes.filter((n) => !n.known).sort((x, y) => y.n - x.n)[0];
    const info = { Learn: next ? `next: ${next.name}` : `${tables.notes || 0} learned`, Sleep: "rest and study", Steer: `${vars.filter((v) => v.kind === "count").length} rules`,
      Become: who, Voice: voiceOn ? (voiceFrom || "on") : "off · tap to talk", Research: `${tables.notes || 0} notes`, Counter: "count a word", Shelf: "your papers" };
    for (const b of $s(".sp-tools").children) { const name = b.querySelector(".tag")?.textContent, sub = info[name]; if (!sub) continue;
      (b.querySelector(".sp-sub") || b.appendChild(h("span", { class: "sp-sub" }))).textContent = sub; }
  }

  // Steer: a guided rule. You fill the blanks, it shows how the engine reads the sentence (nothing saved), then sends it like any message
  // Wiring: the whole learning machine on one screen. Signals (your variables) on the left, the three systems in the middle, memory on the right;
  // a wire is a rule that holds a system on or off. S2 plans, S1 makes goals, S0 executes.
  let sysSel = 0;
  async function openSystems(again, ran) {
    let d; try { d = await api("/char/wiring"); } catch { return; }
    root.querySelector(".sp-sys")?.remove();
    if (ran != null) sysSel = ran;
    const TINT = { 2: "#c79bff", 1: "#ffb347", 0: "#6ff7ff", 3: "#7dffa8" }, Y = { 2: 118, 1: 210, 0: 302, 3: 394 }, sig = d.signals, tag = (id) => id === 3 ? "V" : `S${id}`, sy0 = (i) => 86 + i * 64;
    const post = async (body) => { try { await api("/char/wiring", { method: "POST", body: JSON.stringify(body) }); return true; } catch (e) { err.textContent = e.body?.detail || "That did not work."; return false; } };
    const Hh = Math.max(442, sy0(sig.length) + 10), svg = el("svg", { viewBox: `0 0 680 ${Hh}`, class: "sp-wire", role: "group", "aria-label": "Signals wired to systems and memory" });
    const T = (x, y, text, cls, p = svg, a = {}) => { const t = el("text", { x, y, class: cls, ...a }, p); t.textContent = text; return t; };
    T(24, 70, "Signals", "cap"); T(262, 70, "Systems", "cap"); T(506, 70, "Memory", "cap");
    for (const w of d.wires) { const i = sig.findIndex((x) => x.name === w.from); if (i < 0) continue; // wires first, so boxes sit on top
      const y1 = sy0(i) + 20, y2 = w.to < 0 ? 210 : Y[w.to] - 12, x2 = w.to < 0 ? 246 : 262;
      el("path", { d: `M174 ${y1}C${214} ${y1} ${x2 - 40} ${y2} ${x2} ${y2}`, class: `wire${w.holding ? " hold" : ""} ${w.on ? "on" : "off"}` }, svg);
      if (w.to < 0) el("path", { d: "M246 92V328M246 92h8M246 328h8", class: `wire${w.holding ? " hold" : ""} off`, style: "stroke-dasharray:none" }, svg);
      T(28, y1 + 34, `when ${w.when} · ${w.to < 0 ? "all" : `S${w.to}`} ${w.on ? "on" : "off"}`, `lab${w.holding ? " hold " + (w.on ? "on" : "off") : ""}`); }
    sig.forEach((x, i) => { const y = sy0(i), g = el("g", { class: `sig ${x.kind.replace(" ", "-")}` }, svg);
      el("rect", { x: 24, y, width: 150, height: 40, rx: 8 }, g); T(36, y + 17, x.name.slice(0, 13), "nm", g); T(162, y + 17, String(Math.round(x.value * 100) / 100), "val", g, { "text-anchor": "end" });
      el("rect", { x: 36, y: y + 26, width: 126, height: 3, rx: 1.5, class: "track" }, g); el("rect", { x: 36, y: y + 26, width: 126 * Math.max(0, Math.min(1, x.value / (x.max || 1))), height: 3, rx: 1.5, class: "fill" }, g);
      el("circle", { cx: 174, cy: y + 20, r: 4, class: "port" }, g); });
    el("path", { d: "M342 150V176M342 242V268M342 334V360M338 170l4 6 4-6M338 262l4 6 4-6M338 354l4 6 4-6", class: "flow" }, svg);
    for (const sy of d.systems) { const y = Y[sy.id] - 32, run = sy.runs[0];
      const g = el("g", { class: `sys${sy.on ? "" : " off"}${sy.id === sysSel ? " sel" : ""}${d.trace[0]?.system === sy.id ? " hot" : ""}`, style: `--c:${TINT[sy.id]}`, tabindex: 0, role: "button", "aria-pressed": String(sy.id === sysSel), "aria-label": `${tag(sy.id)} ${sy.name}, ${sy.on ? "on" : "off"}. Show details` }, svg);
      el("rect", { x: 262, y, width: 160, height: 64, rx: 10 }, g); T(276, y + 24, tag(sy.id), "id", g); T(302, y + 24, sy.name, "nm", g);
      T(276, y + 46, (sy.id === 3 && d.corrections.some((c) => c.state === "proposed") ? "has a fix to propose" : sy.rule ? `held ${sy.on ? "on" : "off"} by ${sy.rule}` : !sy.on ? "switched off" : run ? `${run.at} ${run.kind}` : "idle").slice(0, 24), "sub", g); el("circle", { cx: 406, cy: y + 20, r: 4, class: "lamp" }, g);
      const pick = () => { sysSel = sy.id; openSystems(true); }; g.addEventListener("click", pick); g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      el("path", { d: sy.id === 3 ? "M422 394C470 394 460 226 506 226" : `M422 ${Y[sy.id]}H506`, class: `wire link${sy.on ? " hold" : ""}`, style: `stroke:${TINT[sy.id]}` }, svg); T(436, Y[sy.id] - 8, { 2: "reads", 1: "asks from", 0: "writes", 3: "checks" }[sy.id], "lab"); }
    for (const m of d.memory) { const y = Y[m.id] - 32, g = el("g", { class: `mem${m.id === 2 && d.memory[0].holds[0] !== "0" ? " lit" : ""}` }, svg);
      el("rect", { x: 506, y, width: 150, height: 64, rx: 10 }, g); T(518, y + 24, `M${m.id}`, "id", g); T(544, y + 24, m.name, "nm", g); T(518, y + 46, m.holds.slice(0, 22), "sub", g); }

    const sy = d.systems.find((x) => x.id === sysSel), err = h("p", { class: "sp-wire-err", role: "alert" });
    const detail = h("section", { class: "sp-sys-card", style: `--c:${TINT[sy.id]}` },
      h("header", {}, h("h3", {}, h("b", {}, tag(sy.id)), ` ${sy.name}`),
        h("button", { type: "button", class: "sp-sys-switch", role: "switch", "aria-checked": String(sy.on), "aria-label": `${sy.name} system`, ...(sy.rule ? { disabled: "" } : {}),
          onclick: async () => { try { await api("/char/systems", { method: "POST", body: JSON.stringify({ id: sy.id, on: !sy.on }) }); } catch { return; } openSystems(true); } }, sy.on ? "On" : "Off")),
      h("p", { class: "sp-sys-does" }, sy.does), ...(sy.rule ? [h("p", { class: "sp-sys-held" }, `Held ${sy.on ? "on" : "off"} by your rule “${sy.rule}”. The switch is yours again when the rule lets go.`)] : []),
      ...(sy.id === 3 ? [ // the Verifier's own work: its last decision, and the fixes waiting on you
        h("p", { class: "sp-sys-held" }, d.decision.chose ? `Last decision ${d.decision.at}: chose ${d.decision.chose}${d.decision.passed.length ? ` after finding no work for ${d.decision.passed.join(", ")}` : ""}. ${d.decision.why}.` : "No decision yet. It decides whenever the character learns by itself."),
        ...d.corrections.map((c) => h("div", { class: `sp-fix ${c.state}` }, h("p", {}, h("small", {}, `${c.kind} slipped ${c.fails} times · ${c.state === "on" ? "fix in use" : c.state}`), ` Add to its prompt: “${c.text}”`),
          ...(c.state === "on" ? [h("button", { type: "button", onclick: async () => { if (await post({ correction: c.kind, accept: false })) openSystems(true); } }, "Remove")]
            : [h("button", { type: "button", onclick: async () => { if (await post({ correction: c.kind, accept: true })) openSystems(true); } }, "Approve"), ...(c.state === "proposed" ? [h("button", { type: "button", onclick: async () => { if (await post({ correction: c.kind, accept: false })) openSystems(true); } }, "Reject")] : [])])))] : []),
      h("div", { class: "sp-sys-runs" }, ...(sy.runs.length ? sy.runs.slice(0, 4).map((r) => h("p", {}, h("small", {}, `${r.at} ${r.kind}`), ` ${r.topic}${r.note ? `: ${r.note.slice(0, 140)}` : ""}`)) : [h("p", { class: "sp-mind-empty" }, "Has not run since the server started.")])),
      ...(sy.prompts.length ? [h("details", { class: "sp-mind-p" }, h("summary", {}, `${sy.prompts.length} prompts it sent`), ...sy.prompts.flatMap((pr) => [...pr.messages.map((x) => h("pre", { "data-role": x.role }, h("i", {}, x.role), x.content)), h("pre", { "data-role": "model" }, h("i", {}, "model"), pr.reply)]))] : []));
    const busy = async (btn, label, n) => { btn.disabled = true; btn.textContent = label; await learnOne(true, n); if (root.querySelector(".sp-sys") === modal) openSystems(true); };
    const g = d.last_guess, next = h("section", { class: "sp-wire-next" },
      h("div", {}, h("small", {}, d.next ? `Next question · ${d.open} open` : "No open question"), h("p", {}, d.next || "S1 will ask one, or S2 will plan, on the next step."),
        ...(g ? [h("small", {}, `last guess “${g.guess.slice(0, 70)}” · surprise ${g.surprise.toFixed(2)}`)] : [])),
      h("button", { type: "button", class: "sp-wire-go", onclick: (e) => busy(e.currentTarget, "Running…", d.next ? 0 : undefined) }, d.next ? "Look it up" : "Run one step"));
    const mine = sig.filter((x) => x.kind === "yours"), sel = (opts, label) => h("select", { "aria-label": label }, ...opts.map(([v, t]) => h("option", { value: v }, t)));
    const fSig = sel(mine.map((x) => [x.name, x.name]), "Signal"), fCmp = sel([["above", "is above"], ["at", "is at or below"]], "Comparison"), fN = h("input", { type: "number", value: "0", "aria-label": "Value" }),
      fSys = sel([[2, "S2 Plan"], [1, "S1 Goals"], [0, "S0 Execute"]], "System"), fTo = sel([["off", "off"], ["on", "on"]], "On or off");
    const form = mine.length ? h("form", { class: "sp-wire-form", onsubmit: async (e) => { e.preventDefault(); err.textContent = "";
        if (fN.value === "") { err.textContent = "Enter a number first."; return; }
        if (await post({ text: `when ${fSig.value} ${fCmp.value === "above" ? "is above" : "="} ${fN.value}, turn S${fSys.value} ${fTo.value}` })) openSystems(true); } },
        h("span", {}, "New wire: when"), fSig, fCmp, fN, h("span", {}, "turn"), fSys, fTo, h("button", { type: "submit" }, "Add wire"))
      : h("p", { class: "sp-mind-empty" }, "To wire your own signal, make one in chat first: “set focus to 2. each done takes 1 off focus”. It shows up on the left.");
    const modes = h("div", { class: "sp-wire-modes", role: "radiogroup", "aria-label": "Mode" }, ...[["quiet", "Quiet", "Never learns by itself"], ["curious", "Curious", "Learns while idle"], ["proactive", "Proactive", "Learns, and tells you what it found"]]
      .map(([m, label, tip]) => h("button", { type: "button", role: "radio", "aria-checked": String(d.mode === m), title: tip, onclick: async () => { if (await post({ mode: m })) openSystems(true); } }, label)));
    const tr = d.trace[0];
    const modal = h("div", { class: "sp-steer-modal sp-mind sp-sys", role: "dialog", "aria-modal": "true", "aria-label": "Wiring" },
      h("div", { class: "sp-steer-dialog sp-mind-dialog sp-sys-dialog" },
        h("header", { class: "sp-mind-head" }, h("h2", {}, `Wiring · ${d.who}`), modes, h("button", { type: "button", class: "sp-steer-close", "aria-label": "Close", onclick: () => modal.remove() }, "✕")),
        h("div", { class: "sp-wire-scroll" }, h("div", { class: "sp-wire-stage" }), next, detail,
          h("section", { class: "sp-wire-self" }, h("small", {}, "Self-model · what it knows about its own learning, told to it when your message touches it"),
            h("p", {}, h("b", {}, "Has read about "), d.self.knows.join(", ") || "nothing yet"),
            ...d.self.wrong.map((w) => h("p", {}, h("b", {}, "Was wrong "), `“${w.q}” · guessed “${w.guess.slice(0, 80)}” · surprise ${w.surprise.toFixed(2)}`)),
            ...d.self.unsure.map((q) => h("p", {}, h("b", {}, "Has not found out "), q)),
            ...(d.self.dropped ? [h("p", {}, h("b", {}, "Verifier rejected "), `${d.self.dropped} of its notes`)] : []),
            ...(d.review?.instructions || []).map((x) => h("p", {}, h("b", {}, "You told it "), x.text, " ", h("button", { type: "button", class: "sp-wire-rm", "aria-label": `Remove instruction: ${x.text}`,
              onclick: async () => { try { await api(`/char/instructions/${x.id}`, { method: "DELETE" }); } catch { return; } web?.refresh(); openSystems(true); } }, "Remove")))), form, err),
        h("p", { class: "sp-wire-trace" }, tr ? `${tr.at}  ${tag(tr.system)} ${tr.kind} · ${tr.topic}${tr.note ? ` · ${tr.note.slice(0, 60)}` : ""}` : "Nothing has run since the server started.")));
    modal.querySelector(".sp-wire-stage").append(svg);
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });
    modal.addEventListener("keydown", (e) => { if (e.key === "Escape") modal.remove(); });
    root.append(modal);
    if (!again) { modal.querySelector(".sp-steer-close").focus(); if (!still) svg.querySelectorAll(".sig, .sys, .mem").forEach((n, i) => n.animate([{ opacity: 0, translate: "0 10px" }, {}], { duration: 420, delay: i * 45, easing: "ease-out", fill: "backwards" })); }
  }
  async function openMind() { // everything the character holds, and the exact prompts it sent the model
    root.querySelector(".sp-mind")?.remove();
    let m; try { m = await api("/char/mind"); } catch { return; }
    const KINDS = [["reflection", "Reflections"], ["question", "Questions"], ["lesson", "Lessons"], ["entity", "Names"], ["sheet", "Sheet"], ["prompts", "Prompts"]];
    const kindOf = (r) => r.source.startsWith("job:") ? "reflection" : r.title.startsWith("Off-world: ") ? "entity" : r.source;
    const body = h("div", { class: "sp-mind-body" });
    const show = (k) => { tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.k === k));
      if (k === "prompts") return body.replaceChildren(...(m.prompts.length ? m.prompts.map((p) => h("details", { class: "sp-mind-p" },
        h("summary", {}, h("b", {}, p.kind), ` ${p.at} · `, (p.messages.at(-1)?.content || "").slice(0, 70)),
        ...p.messages.map((x) => h("pre", { "data-role": x.role }, h("i", {}, x.role), x.content)), h("pre", { "data-role": "model" }, h("i", {}, "model"), p.reply)))
        : [h("p", { class: "sp-mind-empty" }, "No prompts since the server started. Chat, tap Learn or run a creature, then open this again.")]));
      const rows = m.memories.filter((r) => kindOf(r) === k);
      body.replaceChildren(...(k === "question" ? [h("p", { class: "sp-mind-empty" }, `${m.open.length} open, researched next while it learns.`)] : []),
        ...(rows.length ? rows.map((r) => h("article", { class: "sp-mind-row" }, h("h4", {}, r.title.replace(/^\w+: /, ""), h("small", {}, ` #${r.id} · ${r.source} · ${r.created_at}`)),
          h("p", {}, k === "entity" ? (r.source === "sheet" ? `Left out: ${r.content}` : `in ${r.content.split(",").filter(Boolean).length} notes`) : r.content)))
        : [h("p", { class: "sp-mind-empty" }, "Nothing yet.")])); };
    const tabs = h("div", { class: "sp-mind-tabs", role: "group" }, ...KINDS.map(([k, label]) => h("button", { type: "button", "data-k": k, onclick: () => show(k) },
      label, h("small", {}, k === "prompts" ? m.prompts.length : m.memories.filter((r) => kindOf(r) === k).length))));
    const modal = h("div", { class: "sp-steer-modal sp-mind", role: "dialog", "aria-modal": "true", "aria-label": `${m.who}'s mind` },
      h("div", { class: "sp-steer-dialog sp-mind-dialog" },
        h("header", { class: "sp-mind-head" }, h("h2", {}, `${m.who}'s mind`), h("button", { type: "button", class: "sp-steer-close", "aria-label": "Close", onclick: () => modal.remove() }, "✕")),
        h("details", { class: "sp-mind-persona" }, h("summary", {}, "Persona: who it is told it is"), h("p", {}, m.persona)), tabs, body));
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });
    root.append(modal); show("reflection");
  }
  function openSteerStudio() {
    const prev = root.querySelector(".sp-steer-modal");
    if (prev) { prev.remove(); return; }
    const who = all.find((v) => v.kind === "persona")?.act_arg || "Dot";
    const ACTS = [["look", "look up", "cayde 6"], ["talk", "talk like", "Cayde 6"], ["spawn", "hatch a creature that", "watson: lists the clues in the paper"],
      ["sleep", "go to sleep and learn", ""], ["say", "say", "Ace of Spades, best gun"], ["color", "turn Dot", "red"]];
    let word, n, act, arg, out, sentence = "", tick = 0, timer;
    const compose = () => { const [k] = ACTS.find(([k]) => k === act.value), a = arg.value.trim(), w = word.value.trim(), x = Math.max(1, parseInt(n.value, 10) || 1);
      const [name, task] = a.split(":").map((t) => t.trim());
      const doing = { look: `look up ${a}`, talk: `talk like ${a}`, spawn: `spawn a creature called ${name || "helper"}${task ? ` that ${task}` : ""}`,
        sleep: "go to sleep and reflect", say: `say ${a}`, color: `turn Dot ${a}` }[k];
      return w ? `when i say ${w} ${x} times, ${doing}` : ""; };
    const refresh = () => { clearTimeout(timer); arg.hidden = act.value === "sleep"; arg.placeholder = `e.g. ${ACTS.find(([k]) => k === act.value)[2]}`;
      sentence = compose(); out.replaceChildren(sentence ? h("q", {}, sentence) : h("p", { class: "sp-steer-hint" }, "Type the word or phrase it should count. The grey text in the boxes is only an example."));
      if (!sentence) return;
      const mine = ++tick; timer = setTimeout(async () => { try { const r = await api("/space/preview", { method: "POST", body: JSON.stringify({ text: sentence }) });
        if (mine === tick) out.replaceChildren(h("q", {}, sentence), ...(r.rules.length ? r.rules.map((d) => h("p", { class: "sp-steer-read" }, `${who} reads it as: ${d}`))
          : [h("p", { class: "sp-steer-bad" }, "I can't read that as a rule yet. Try a shorter phrase.")])); } catch { /* the preview is a help, not a gate */ } }, 250); };
    const field = (label, el) => h("label", { class: "sp-steer-f" }, h("span", {}, label), el);
    const modal = h("div", { class: "sp-steer-modal", role: "dialog", "aria-modal": "true", "aria-label": "Teach a rule" },
      h("form", { class: "sp-steer-dialog", onsubmit: async (e) => { e.preventDefault(); if (!sentence) return word.focus(); modal.remove(); await send(sentence); } },
        h("header", { class: "sp-steer-head" }, h("div", {}, h("h2", {}, `Teach ${who} a rule`), h("p", {}, "Fill the blanks. You see how it is read before anything is saved.")),
          h("button", { type: "button", class: "sp-steer-close", "aria-label": "Close", onclick: () => modal.remove() }, "✕")),
        h("div", { class: "sp-steer-line" }, h("span", {}, "When I say"),
          field("word or phrase", (word = h("input", { class: "sp-inp", placeholder: "e.g. ace of spades", required: "" }))),
          field("times", (n = h("input", { class: "sp-inp sp-steer-n", type: "number", min: "1", max: "999", value: "3" }))),
          h("span", {}, "times,")),
        h("div", { class: "sp-steer-line" }, field("then", (act = h("select", { class: "sp-inp" }, ...ACTS.map(([k, label]) => h("option", { value: k }, label))))),
          field("what", (arg = h("input", { class: "sp-inp sp-steer-arg" })))),
        (out = h("div", { class: "sp-steer-out", "aria-live": "polite" })),
        h("footer", {}, h("button", { type: "button", class: "sp-steer-ghost", onclick: async () => { const p = window.prompt(`Who should ${who === "Dot" ? "Dot" : "it"} become?`); if (p?.trim()) { modal.remove(); await send(`become ${p.trim()}`); } } }, "Become someone else"),
          h("button", { type: "submit", class: "sp-btn-prime" }, "Teach it"))));
    [word, n, act, arg].forEach((x) => x.addEventListener("input", refresh));
    modal.addEventListener("keydown", (e) => { if (e.key === "Escape") modal.remove(); });
    modal.addEventListener("pointerdown", (e) => { if (e.target === modal) modal.remove(); });
    root.append(modal); refresh(); word.focus();
  }

  let learnMode = false;
  function toggleLearnMode(force = null) {
    learnMode = force !== null ? force : !learnMode;
    const btn = $s(".sp-learntoggle");
    btn?.classList.toggle("on", learnMode);
    btn?.setAttribute("aria-pressed", String(learnMode));
    root.classList.toggle("learn-mode", learnMode);

    if (learnMode) {
      mood("think", 1800);
      ripple("#7dffa8", 320);
      // its own curiosity, not a fixed list: names it has not read about yet, then its open questions
      const curious = [...kg.nodes.filter((n) => !n.known).sort((x, y) => y.n - x.n).map((n) => n.name), ...(lastQs || [])].slice(0, 3);
      renderLearnChips(curious.length ? curious : ["Where do you live?", "Who are your friends?", "What do you fear?"]);
      const stageP = stage.querySelector(":scope > p");
      if (stageP) stageP.textContent = "Ask me anything and I'll research it.";
    } else {
      $s(".sp-learn-chips")?.replaceChildren();
      ripple("rgba(255, 255, 255, 0.4)", 200);
    }
  }

  function renderLearnChips(qs = []) {
    const box = $s(".sp-learn-chips");
    if (!box) return;
    if (!learnMode || !qs.length) {
      box.replaceChildren();
      return;
    }
    box.replaceChildren(...qs.map((q, i) => h("button", {
      type: "button",
      class: "sp-learn-chip",
      style: `--i: ${i}`,
      onclick: (e) => {
        e.preventDefault();
        form.say.value = q;
        line = line.then(() => send(q)).catch(() => {});
      }
    }, h("span", { class: "sp-chip-spark" }, "✦"), h("span", {}, q))));
  }

  $s(".sp-hist").addEventListener("click", () => setHistory(!histOpen));
  $s(".sp-notesbtn").addEventListener("click", () => setNotes(!notesOpen));
  $s(".sp-steerbtn")?.addEventListener("click", () => openSteerStudio());
  $s(".sp-learntoggle")?.addEventListener("click", () => toggleLearnMode());
  let line = Promise.resolve(); // messages sent while Dot is busy wait their turn instead of being dropped
  if (web) { // type "/" and Dot becomes the list of commands; arrows choose, Enter or a click runs one, Escape lets it go
    let pick = 0, shown = [];
    const run = (c) => { form.say.value = ""; web.palette(null); c.run(); };
    const show = () => { const v = form.say.value.trim().toLowerCase();
      shown = v.startsWith("/") && !v.includes(" ") ? COMMANDS.filter((c) => [c.name, ...(c.also || [])].some((n) => n.startsWith(v))) : null;
      pick = Math.min(pick, Math.max(0, (shown?.length || 1) - 1)); web.palette(shown, pick, run); };
    form.say.addEventListener("input", () => { pick = 0; show(); });
    form.say.addEventListener("blur", () => setTimeout(() => web.palette(null), 150));
    form.say.addEventListener("keydown", (e) => {
      if (!shown) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); pick = (pick + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % Math.max(1, shown.length); show(); }
      else if (e.key === "Escape") { form.say.value = ""; web.palette(null); shown = null; }
      else if ((e.key === "Enter" || e.key === "Tab") && shown.length && !command(form.say.value)) { e.preventDefault(); run(shown[pick]); }
    });
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const t = form.say.value.trim();
    if (!t) return;
    form.say.value = "";
    if (web && t.startsWith("/")) { // a slash is always a command, never chat for the model
      const c = command(t);
      web.palette(null);
      if (c) c.run(); else web.say({ text: `${t} is not a command. Type / to see them all.`, events: [] });
      return;
    }
    if (t.toLowerCase() === "/steer" || t.toLowerCase() === "steer" || t.toLowerCase() === "/steer mode") {
      openSteerStudio();
      return;
    }
    if (t.toLowerCase() === "/learn" || t.toLowerCase() === "/learn more" || t.toLowerCase() === "learn more") {
      toggleLearnMode();
      return;
    }
    line = line.then(() => send(t)).catch(() => {});
  });
  window.addEventListener("keydown", function esc(e) {
    if (!root.isConnected) return removeEventListener("keydown", esc);
    if (e.key === "Escape") {
      const modal = root.querySelector(".sp-steer-modal");
      if (modal) modal.remove();
      else dismissCard();
    }
  });
  root.addEventListener("click", (e) => {
    if (root.classList.contains("carded")) {
      const card = stage.querySelector(".sp-card");
      if (card && !card.contains(e.target) && !e.target.closest(".sp-moon") && !e.target.closest(".sp-tool") && !e.target.closest(".sp-crew") && !e.target.closest(".sp-ear") && !e.target.closest(".sp-learntoggle") && !e.target.closest(".sp-steerbtn")) {
        dismissCard();
      }
    }
  });
  $s(".sp-clear").addEventListener("click", async () => {
    if (!confirm("Clear the chat and every variable?")) return;
    log.replaceChildren(); apply(await api(base, { method: "DELETE" })); layout();
  });
  root.addEventListener("pointermove", (e) => { const s = root.getBoundingClientRect(), dx = e.clientX - s.left - CX, dy = e.clientY - s.top - CY, m = Math.hypot(dx, dy) || 1;
    $s(".sp-eyes").style.translate = `calc(-50% + ${dx / m * 6}px) calc(-50% + ${dy / m * 5}px)`;
    const k = (14 + Math.min(m, 400) / 400 * 28) * S, lean = $s(".sp-blob0"); // Dot leans toward the pointer, like a drop
    if (lean && !still) lean.style.translate = `${dx / m * k}px ${dy / m * k}px`; });
  let lastMove = 0;
  root.addEventListener("pointerleave", () => $s(".sp-blob0")?.style.removeProperty("translate"));
  root.addEventListener("pointermove", () => { lastMove = Date.now(); });
  const glance = setInterval(() => { // left alone, Dot looks round at its variables now and then
    if (!root.isConnected) return clearInterval(glance);
    if (Date.now() - lastMove > 1500) $s(".sp-blob0")?.style.removeProperty("translate"); // the lean settles back, so Dot is round again
    if (Date.now() - lastMove < 4000 || root.dataset.mood || still) return;
    const v = vars[Math.floor(Math.random() * (vars.length + 2))], [x, y] = v ? mid(v) : [CX + (Math.random() - .5) * 200, CY + 120];
    const dx = x - CX, dy = y - CY, m = Math.hypot(dx, dy) || 1;
    $s(".sp-eyes").style.translate = `calc(-50% + ${dx / m * 6}px) calc(-50% + ${dy / m * 5}px)`;
  }, 3200);
  const ro = new ResizeObserver(() => { if (root.isConnected) { layout(); } else ro.disconnect(); }); ro.observe(root);

  let st; try { st = await api(base); } catch { st = { turns: [], vars: [], tables: {} }; }
  take(st); dress(false); drawVars();
  let back = false; try { back = sessionStorage.getItem("sp-back") === "1"; sessionStorage.removeItem("sp-back"); } catch { /* a plain visit */ }
  st.turns.forEach((t) => { say(t); log.lastChild.classList.add("sp-quiet"); });
  stats(); layout(); // the floor keeps clear of the stats corner, so that is filled first
  firedCount = st.turns.flatMap((t) => t.events || []).filter((e) => !["made", "removed"].includes(e.trigger)).length;
  root.classList.toggle("hist-open", histOpen); $s(".sp-hist").setAttribute("aria-expanded", String(histOpen)); stats();
  const last = [...st.turns].reverse().find((t) => t.role === "dot");
  if (last && !stage.hidden) { const p = h("p", {}, last.text); stage.replaceChildren(p); }
  if (buddy.asleep?.()) sleep(false); // put to sleep here or in the reader: it is one sleep
  if (back && !still) { // coming back from a paper: the space unfolds out of Dot, the trip run backwards
    const box = root.getBoundingClientRect(), dx = box.left + CX, dy = box.top + CY;
    svg.style.transformOrigin = `${CX}px ${CY}px`;
    [svg, ...root.querySelectorAll(".sp-tools .lblob, .sp-moon, .sp-info, .sp-vars, .sp-stage, .sp-stats, .sp-hist, .sp-ear")].forEach((el, i) => {
      const b = el.getBoundingClientRect(); if (!b.width) return;
      el.animate([{ transform: `translate(${dx - b.left - b.width / 2}px, ${dy - b.top - b.height / 2}px) scale(0)`, opacity: 0 }, {}],
        { duration: 600, delay: 120 + i * 50, easing: "cubic-bezier(.2,.8,.3,1.1)", fill: "backwards" }); });
    mood("happy");
  }
  crew();
  form.say.focus();
}
