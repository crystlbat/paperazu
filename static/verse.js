"use strict";
const vsLite = (c) => { const m = /^#?([0-9a-f]{6})$/i.exec(c || ""); if (!m) return c; const n = parseInt(m[1], 16); return "#" + [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (255 - v) * .55).toString(16).padStart(2, "0")).join(""); }; // text on the dark canvas needs a light tint (>= 4.5:1)
const vsAgo = (at) => { const m = (Date.now() - Date.parse(`${String(at).replace(" ", "T")}Z`)) / 60000; return !(m >= 0) ? at : m < 1 ? "just now" : m < 60 ? `${Math.round(m)} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
// ---------- /verse: every persona you have made, as a solar system ----------
// The model is the sun: nothing thinks without it. Each persona is a planet on its own orbit, with its variables circling it.
// Only the live one is awake and learns; a beam runs between it and the sun while a step is running. The stored ones sleep,
// whole, until you enter them. Backed by workbench/verse.py.
async function renderVerse() {
  const root = h("div", { class: "vs" }), cv = h("canvas", { class: "vs-cv", "aria-hidden": "true" }), g = cv.getContext("2d");
  const list = h("div", { class: "vs-list", role: "group", "aria-label": "Personas" }), card = h("section", { class: "vs-card", "aria-live": "polite" });
  const who = h("input", { name: "who", placeholder: "e.g. Alfred from Batman", "aria-label": "Who the new persona should be", maxlength: "80" }), err = h("small", { role: "alert" });
  const bar = h("div", { class: "vs-making", role: "status", hidden: "" }, h("i"), h("span"));
  const make = h("form", { class: "vs-new" }, h("span", {}, "New persona"), who, h("button", { type: "submit" }, "Create"), err, bar);
  root.append(cv, h("header", { class: "vs-top" }, h("a", { href: "#library" }, "← Library"), h("h1", {}, "Verse"), h("p", {}, "The model at the centre, your personas around it. One is awake at a time.")), card, h("footer", { class: "vs-foot" }, list, make));
  view.append(root);
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W = 1, H = 1, K = 1, ps = [], sel = "", model = { status: "", label: "Checking the model…", name: "" }, harness = { status: "", label: "Harness waits for the model", on: 0, n: 0 }, tick = 0, spin = 0, over = false, busy = false, beam = 0, hits = [], doing = "", making = "", made = 0, twin = 0, bornName = "", bornAt = 0;
  function fit() { const d = devicePixelRatio || 1; W = root.clientWidth; H = root.clientHeight; cv.width = W * d; cv.height = H * d; g.setTransform(d, 0, 0, d, 0, 0); K = Math.max(.6, Math.min(W / 900, H / 720, 1.4)); }
  const ro = new ResizeObserver(() => root.isConnected ? fit() : ro.disconnect()); ro.observe(root); fit();

  function show() { // the list (so every persona is reachable without the canvas) and the card for the chosen one
    list.replaceChildren(...ps.map((p) => h("button", { type: "button", "aria-pressed": String(p.name === sel), style: `--c:${p.tint}`, onclick: () => { sel = p.name; show(); } }, h("i", {}), p.name, p.live ? h("small", {}, " awake") : "")));
    const p = ps.find((x) => x.name === sel); if (!p) return card.replaceChildren();
    const msg = h("small", { role: "alert" });
    const go = async (path, opts, after) => { msg.textContent = ""; try { apply(await api(path, opts)); after?.(); } catch (e) { msg.textContent = e.body?.detail || "That did not work."; } };
    const del = h("button", { type: "button", class: "vs-del", onclick: () => { // two taps: deleting cannot be undone
      if (del.dataset.sure) return go(`/verse/personas/${encodeURIComponent(p.name)}`, { method: "DELETE" }, () => { sel = ps[0]?.name || ""; show(); });
      del.dataset.sure = "1"; del.textContent = "Delete for good?"; setTimeout(() => { if (del.isConnected) { delete del.dataset.sure; del.textContent = "Delete"; } }, 4000); } }, "Delete");
    card.replaceChildren(h("h2", { style: `--c:${p.tint}` }, h("i", {}), p.name), h("p", { class: "vs-state" }, p.live ? `Awake · ${p.mode} mode` : `Asleep since ${vsAgo(p.at)}`), ...(p.live && (doing || p.doing) ? [h("p", { class: "vs-doing" }, doing || p.doing)] : []),
      h("p", {}, String(p.holds || "").replace(/\b1 notes\b/g, "1 note")), ...(p.next ? [h("p", { class: "vs-next" }, `Next question: ${p.next}`)] : []),
      h("p", { class: "vs-vars" }, ...p.vars.map((v) => h("span", {}, `${v.name} ${Math.round(v.value * 100) / 100}`))),
      h("div", { class: "vs-acts" }, h("button", { type: "button", class: "vs-enter", onclick: () => p.live ? (location.hash = "#char") : go("/verse/enter", { method: "POST", body: JSON.stringify({ name: p.name }) }, () => { location.hash = "#char"; }) }, p.live ? "Enter" : "Wake and enter"),
        ...(p.live ? [h("small", {}, "To delete it, enter another persona first.")] : [del])), msg);
  }
  function apply(d) { const was = Object.fromEntries(ps.map((p) => [p.name, p])); ps = d.personas; ps.forEach((p) => { p.k = was[p.name]?.k || 0; p.chibi ||= was[p.name]?.chibi; p.asked = was[p.name]?.asked; });
    if (!ps.some((p) => p.name === sel)) sel = ps[0]?.name || ""; ps.forEach((p, i) => { p.r = 200 + i * 78; p.a0 = i * 2.3; p.w = .0016 / (1 + i * .45); }); show(); }
  make.addEventListener("submit", async (e) => { e.preventDefault(); err.textContent = ""; const name = who.value.trim();
    if (!name) { err.textContent = "Say who it should be first."; return; }
    const b = make.querySelector("button"); b.disabled = true; b.textContent = "Looking them up…"; busy = true; // the model reads up on them: this takes a while
    const t0 = Date.now(), tk = setInterval(() => { bar.lastChild.textContent = `Making ${name}: searching the web and writing its persona · ${Math.round((Date.now() - t0) / 1000)}s`; }, 500); bar.hidden = false; bar.lastChild.textContent = `Making ${name}…`; making = name; made = tick;
    try { const before = new Set(ps.map((p) => p.name)); apply(await api("/verse/new", { method: "POST", body: JSON.stringify({ who: name }) })); who.value = ""; bornName = ps.find((p) => !before.has(p.name))?.name || ps[0].name; bornAt = tick; sel = bornName; show(); } catch (x) { err.textContent = x.body?.detail || "Could not make that persona."; }
    clearInterval(tk); bar.hidden = true; making = ""; b.disabled = false; b.textContent = "Create"; busy = false; });
  cv.addEventListener("pointermove", () => { over = true; }); cv.addEventListener("pointerleave", () => { over = false; }); // planets hold still under the pointer so they can be clicked
  cv.addEventListener("click", (e) => { const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, hit = hits.find((t) => Math.hypot(t.x - x, t.y - y) < t.r + 16); if (hit) { sel = hit.name; show(); } });

  async function learn() { // the awake one keeps learning while you watch: one small step, like on its own page
    if (busy || !root.isConnected || document.visibilityState !== "visible" || !ps.length) return;
    const live = ps.find((p) => p.live); if (model.status !== "ready" || harness.status !== "ready" || !live || !["curious", "proactive"].includes(live.mode)) return; // viewing never starts model work unless it is up and the persona is allowed to learn
    busy = true; doing = "learning one step by itself…"; show();
    try { const r = await api("/char/rest", { method: "POST", body: JSON.stringify({ char: true }) });
      doing = r.done ? (r.quiet ? "quiet: not learning by itself" : r.incurious ? "not curious right now" : "nothing to learn right now") : `last step: ${r.kind}${r.topic ? ` on “${String(r.topic).slice(0, 40)}”` : ""}`; if (!r.done) beam = 90;
      apply(await api("/verse/personas")); } catch { doing = "could not reach the model"; }
    busy = false;
  }

  function planet(x, y, R, tint, awake, t, form, k = 0) { // k: how far it has morphed into its persona's chibi (chibi.js)
    const c = k * k * (3 - 2 * k), sy = y - R * .3 * c, sr = R * (1 - .38 * c), gr = g.createRadialGradient(x - sr * .35, sy - sr * .4, sr * .1, x, sy, sr); gr.addColorStop(0, "#fff"); gr.addColorStop(.3, tint); gr.addColorStop(1, "#0b1a22"); g.fillStyle = gr; g.globalAlpha = (awake ? 1 : .55) * (1 - c);
    g.beginPath(); g.arc(x, sy, sr * (awake && !still ? 1 + Math.sin(t * .05) * .03 : 1), 0, 6.283); g.fill(); g.globalAlpha = 1;
    const F = form && c > .01 ? drawChibi(g, x, y, R, form, tint, c, t * .02, awake ? 1 : .7) : { x, y, s: 1, ink: "#06222a" }, e = R * F.s; g.fillStyle = g.strokeStyle = F.ink;
    const blink = awake && tick % 210 > 203; for (const o of [-e * .26, e * .26]) { g.beginPath();
      if (!awake) { g.lineWidth = Math.max(1.5, e * .08); g.lineCap = "round"; g.arc(F.x + o, F.y, e * .13, .3, 2.84); g.stroke(); } // asleep: closed eyes
      else { g.ellipse(F.x + o + Math.sin(t * .02) * e * .06, F.y, e * .11, blink ? 1 : e * .27, 0, 0, 6.283); g.fill(); } }
  }
  function frame() {
    if (!root.isConnected) return; requestAnimationFrame(frame); tick++; if (!over) spin++; g.clearRect(0, 0, W, H); hits = [];
    const cx = W / 2, cy = H * (W < 760 ? .3 : .46), fr = Math.min(1, (W / 2 - 50) / (Math.max(...ps.map((p) => p.r), 1) * K)), // fr: shrink the orbits so the outer planets stay on the canvas
       ok = model.status === "ready", sunC = ok ? "#ffd27a" : model.status ? "#ff6b7a" : "#8b93a7", SR = 34 * K;
    for (const p of ps) { g.strokeStyle = "#8b93a7"; g.globalAlpha = p.name === sel ? .32 : .13; g.lineWidth = 1; g.setLineDash([2, 7]); g.beginPath(); g.ellipse(cx, cy, p.r * K * fr, p.r * K * fr * .42, 0, 0, 6.283); g.stroke(); } g.setLineDash([]); g.globalAlpha = 1;
    const at = ps.map((p) => { const a = p.a0 + (still ? 0 : spin * p.w); const f = p.name === bornName && !still ? Math.min(1, (tick - bornAt) / 120) : 1, e = 1 - (1 - f) ** 3; // a newborn flies out from the twin to its orbit
      return { p, x: cx + Math.cos(a) * p.r * K * fr * e, y: cy + Math.sin(a) * p.r * K * fr * .42 * e, back: Math.sin(a) < 0 && f === 1, s: (1 + Math.sin(a) * .16) * (.4 + .6 * e) }; });
    // a twin star: the model and the harness circle each other. The model comes online, then the harness is checked, then the persona wakes
    const hOk = harness.status === "ready", hC = hOk ? "#6ff7ff" : harness.status === "down" ? "#ff6b7a" : "#5b6478", HR = SR * .85, ta = still ? .6 : (twin += making ? .05 : .006), D = SR * 1.6;
    const mx = cx + Math.cos(ta) * D, my = cy + Math.sin(ta) * D * .42, hx = cx - Math.cos(ta) * D, hy = cy - Math.sin(ta) * D * .42; // two suns on one orbit around their shared centre
    const sun = () => { for (let i = 0; i < 3; i++) { const r = SR + ((tick * .5 + i * 26) % 78) * K; g.strokeStyle = sunC; g.globalAlpha = Math.max(0, .28 - (r - SR) / (78 * K) * .28); g.lineWidth = 1.5; g.beginPath(); g.arc(mx, my, r, 0, 6.283); g.stroke(); } g.globalAlpha = 1;
      const gr = g.createRadialGradient(mx - SR * .3, my - SR * .3, 2, mx, my, SR); gr.addColorStop(0, "#fff"); gr.addColorStop(.4, sunC); gr.addColorStop(1, "#5a3a10"); g.fillStyle = gr; g.beginPath(); g.arc(mx, my, SR, 0, 6.283); g.fill();
      if (hOk) { const b = still ? 0 : tick * .045; g.save(); g.translate(hx, hy); g.rotate(b); for (const d of [1, -1]) { const lg = g.createLinearGradient(0, 0, 0, d * 120 * K); lg.addColorStop(0, "rgba(111,247,255,.55)"); lg.addColorStop(1, "rgba(111,247,255,0)"); g.fillStyle = lg; g.beginPath(); g.moveTo(-3 * K, 0); g.lineTo(-14 * K, d * 120 * K); g.lineTo(14 * K, d * 120 * K); g.lineTo(3 * K, 0); g.fill(); } g.restore(); } // the pulsar's sweeping beams: the harness is live
      const pr = HR * (hOk && !still ? 1 + Math.sin(tick * .2) * .08 : 1), hg = g.createRadialGradient(hx - pr * .3, hy - pr * .3, 1, hx, hy, pr); hg.addColorStop(0, "#fff"); hg.addColorStop(.45, hC); hg.addColorStop(1, "#0b2a33"); g.fillStyle = hg; g.globalAlpha = harness.status ? 1 : .5; g.beginPath(); g.arc(hx, hy, pr, 0, 6.283); g.fill(); g.globalAlpha = 1;
      if (making) { const k = Math.min(1, (tick - made) / 900), r = (5 + 14 * k) * K * (still ? 1 : 1 + Math.sin(tick * .15) * .1), px = cx, py = cy - 52 * K; // a new world condensing above the twin
        for (const [sx, sy, c] of [[mx, my, sunC], [hx, hy, hC]]) { g.strokeStyle = c; g.globalAlpha = .45; g.setLineDash([2, 6]); g.lineDashOffset = -tick; g.beginPath(); g.moveTo(sx, sy); g.lineTo(px, py); g.stroke(); } g.setLineDash([]); g.globalAlpha = 1;
        const pg = g.createRadialGradient(px - r * .3, py - r * .3, 1, px, py, r); pg.addColorStop(0, "#fff"); pg.addColorStop(.5, "#b9a6ff"); pg.addColorStop(1, "#1a1530"); g.fillStyle = pg; g.beginPath(); g.arc(px, py, r, 0, 6.283); g.fill();
        g.font = "12px ui-sans-serif, system-ui, sans-serif"; g.textAlign = "center"; g.fillStyle = "#e8ecf4"; g.fillText(making, px, py - r - 10); }
      g.font = "12px ui-monospace, monospace"; g.textAlign = "center"; g.fillStyle = sunC; g.fillText(model.label, cx, cy + SR + 30 * K); g.fillStyle = hC; g.fillText(harness.label, cx, cy + SR + 30 * K + 16);
      if (model.name) { g.fillStyle = "#8b93a7"; g.fillText(model.name, cx, cy + SR + 30 * K + 32); } };
    const one = ({ p, x, y, s }) => { const R = (p.live ? 30 : 22) * K * s; hits.push({ x, y, r: R, name: p.name });
      if (p.live && (busy || beam > 0)) { if (beam > 0) beam--; g.strokeStyle = p.tint; g.globalAlpha = .5; g.lineWidth = 1.5; g.setLineDash([3, 8]); g.lineDashOffset = -tick * 1.5; g.beginPath(); g.moveTo(hx, hy); g.lineTo(x, y); g.stroke(); g.setLineDash([]); g.globalAlpha = 1; // thinking runs between it and the model
        for (let i = 0; i < 3; i++) { const u = ((tick * .012 + i / 3) % 1), back = i % 2; g.fillStyle = "#fff6b0"; g.beginPath(); g.arc(hx + (x - hx) * (back ? 1 - u : u), hy + (y - hy) * (back ? 1 - u : u), 3 * K, 0, 6.283); g.fill(); }
        const r = R + ((tick * .7) % 40) * K; g.strokeStyle = p.tint; g.globalAlpha = 1 - (r - R) / (40 * K); g.beginPath(); g.arc(x, y, r, 0, 6.283); g.stroke(); g.globalAlpha = 1; }
      if (p.name === sel) { g.strokeStyle = "#e8ecf4"; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, R + 7 * K, 0, 6.283); g.stroke(); }
      if ((p.name === sel || p.live) && !p.chibi && !p.asked) { p.asked = 1; api(`/char/chibi?name=${encodeURIComponent(p.name)}`).then((c) => { p.chibi = c; }).catch(() => {}); } // a stored one's look is looked up when you pick it
      p.k = (p.k || 0) + (((p.live || p.name === sel) && p.chibi ? 1 : 0) - (p.k || 0)) * (still ? 1 : .04); // the awake one, and the one you pick, take their chibi form
      planet(x, y, R, p.tint, p.live && model.status === "ready" && hOk, tick, p.chibi, p.k);
      p.vars.slice(0, 6).forEach((v, i, all) => { const a = tick * (p.live && !still ? .014 : .003) + i * 6.283 / all.length, vx = x + Math.cos(a) * (R + 20 * K), vy = y + Math.sin(a) * (R + 20 * K) * .5; // its variables circle it
        g.strokeStyle = g.fillStyle = "#ffb347"; g.globalAlpha = p.live ? 1 : .5; g.lineWidth = 1.5; g.beginPath(); g.arc(vx, vy, 4 * K, 0, 6.283); g.stroke();
        if (p.live || p.name === sel) { g.font = "11px ui-monospace, monospace"; g.textAlign = "left"; g.fillText(`${v.name} ${Math.round(v.value * 10) / 10}`, vx + 8, vy + 4); } g.globalAlpha = 1; });
      g.font = `${p.live ? 600 : 500} ${Math.round(13 * Math.max(1, K))}px ui-sans-serif, system-ui, sans-serif`; g.textAlign = "center"; g.fillStyle = p.live ? "#e8ecf4" : "#8b93a7"; g.fillText(p.name, x, y + R + 30 * K);
      if (p.live) { g.font = "11px ui-monospace, monospace"; g.fillStyle = "#c9d1e0"; g.fillText((model.status !== "ready" ? "waiting for the model" : !hOk ? "waiting for the harness check" : busy ? "thinking…" : doing || p.doing).slice(0, 46), x, y + R + 46 * K); } };
    at.filter((o) => o.back).forEach(one); sun(); at.filter((o) => !o.back).forEach(one);
  }
  try { apply(await api("/verse/personas")); } catch { card.replaceChildren(h("p", {}, "Could not load your personas.")); }
  frame();
  api("/model/status").then((m) => { model = { status: m.status, label: m.label, name: "" };
    if (m.status === "ready") { harness = { status: "", label: "Checking the harness…" }; api("/char/systems").then((r) => { const on = r.systems.filter((x) => x.on).length; harness = { status: "ready", label: `Harness checked · ${on} of ${r.systems.length} systems on` }; }).catch(() => { harness = { status: "down", label: "Harness check failed" }; }); }
    return api("/settings"); }).then((s) => { model.name = (s.model || "").split("/").pop(); }).catch(() => { if (!model.status) model = { status: "down", label: "Model not reachable", name: "" }; });
  setTimeout(learn, 8000); const loop = setInterval(() => root.isConnected ? learn() : clearInterval(loop), 30000);
}
