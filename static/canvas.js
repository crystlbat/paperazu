"use strict";
// The canvas: Dot's per-paper board of answer, source and note cards, with threads between them.
// It opens out of Dot like water: a circle grows from its face and the paper slides left. Cards are
// swallowed when it closes and spat back out when it opens. Plain script; uses h, api and buddy.
// Every animation here can be cut short by a click (it jumps to its end) and is instant with reduced motion.

function canvasPanel(host, paperId, pdf) {
  const view = host.parentElement;
  const KEY = `canvas-open:${paperId}`;
  const NS = "http://www.w3.org/2000/svg";
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get: () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } },
    set: (on) => { try { on ? localStorage.setItem(KEY, "1") : localStorage.removeItem(KEY); } catch { /* private mode */ } },
  };
  const call = (sub, method = "GET", body) =>
    api(`/papers/${paperId}/canvas${sub}`, { method, ...(body && { body: JSON.stringify(body) }) });
  const sv = (tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };

  const cards = new Map(); // id -> { d: the card as the server has it, el }
  let links = [];          // [{ id, from_card, to_card }]
  const pan = { x: 0, y: 0 };
  let opened = false, busy = false, skipped = false, locked = false, loaded = null, gone = false, holdThreads = false, raf = 0;

  // ----- what is on the page -----
  const board = h("div", { class: "cv-board" });
  const empty = h("p", { class: "cv-empty", hidden: true }, "Nothing here yet. Ask Dot a question about the paper, or write a note.");
  const wave = h("div", { class: "cv-wave", "aria-hidden": "true" });
  host.append(wave, empty, board);
  host.inert = true;
  const fx = h("div", { class: "cv-fx", "aria-hidden": "true" }); // rings, crumbs and flying cards; above the page, below Dot
  document.body.append(fx);
  // threads cross from the canvas to the paper, so they live over the whole reader, not inside the canvas
  const clipRect = sv("rect");
  const defs = sv("defs", {}); defs.append(sv("clipPath", { id: `cvclip-${paperId}` }));
  defs.firstChild.append(clipRect);
  const gIn = sv("g", { "clip-path": `url(#cvclip-${paperId})` }), gOut = sv("g"), gTags = sv("g");
  const svg = sv("svg", { class: "cv-svg off", "aria-hidden": "true" });
  svg.append(defs, gIn, gOut, gTags);
  view.append(svg);
  const tab = h("button", { type: "button", class: "cv-tab", "aria-expanded": "false", title: "Canvas", onclick: () => toggle() }, h("span", {}, "Canvas"));
  pdf.el.append(tab);

  // ----- animations: all can be skipped -----
  const live = new Set();
  const track = (a) => { live.add(a); return a.finished.catch(() => {}).finally(() => live.delete(a)); };
  const fast = () => reduced() || skipped; // reduced motion, or a click cut this open or close short: everything goes to its end
  const play = (el, keys, o) => track(el.animate(keys, { fill: "both", ...o, duration: fast() ? 1 : o.duration, delay: fast() ? 0 : o.delay ?? 0 }));
  const snap = () => { view.classList.add("no-slide"); void view.offsetWidth; view.classList.remove("no-slide"); }; // the paper and canvas jump to where they are going
  const skipAll = () => { if (!live.size && !busy) return; if (busy) { skipped = true; snap(); } [...live].forEach((a) => { try { a.finish(); } catch { /* already done */ } }); buddy.skip(); };
  document.addEventListener("pointerdown", skipAll, true);
  const wait = (ms) => (fast() ? Promise.resolve() : buddy.wait(ms));
  const grab = (el, e) => { try { el.setPointerCapture(e.pointerId); } catch { /* the pointer is gone; the listeners are on the element anyway */ } };
  const rnd = (a, b) => a + Math.random() * (b - a);

  // ----- cards -----
  const linesOf = (r) => Math.max(1, Math.round((r[3] - r[1]) / 12));
  const face = () => h("i", { class: "cv-face", "aria-hidden": "true" });
  function fill(c) {
    const d = c.d, body = c.el.querySelector(".cv-body");
    if (d.kind === "answer") body.replaceChildren(h("p", { class: "cv-q" }, d.question), ...buddy.format(d.text));
    else if (d.kind === "source") body.replaceChildren(h("p", { class: "cv-where" }, `p. ${d.page}${d.rect ? ` \u00b7 from ${linesOf(d.rect)} lines` : ""}`), h("p", {}, d.text));
    else if (d.entries.length) body.replaceChildren(...d.entries.map((e) => h("p", { class: `cv-line ${e.who}` }, e.who === "dot" ? face() : null, e.text)));
    else body.replaceChildren(h("p", { class: "cv-line me" }, d.text));
    c.el.setAttribute("aria-label", d.kind === "answer" ? `Answer: ${d.question}` : d.kind === "source" ? `Source, page ${d.page}. Press Enter to show it in the paper.` : "Note");
  }
  function ensureEl(c) {
    if (c.el) return c.el;
    const d = c.d;
    const x = h("button", { type: "button", class: "cv-x", "aria-label": "Put away", title: "Put away", onclick: (e) => { e.stopPropagation(); putAway(c); } }, "\u00d7");
    const handle = h("i", { class: "cv-handle", title: "Drag onto another card to link them", "aria-hidden": "true" });
    c.el = h("article", { class: `cv-card cv-${d.kind}`, "data-id": d.id, style: `left:${d.x}px;top:${d.y}px;width:${d.w}px`,
      role: "group", ...(d.kind === "source" ? { tabindex: "0" } : {}) }, x, h("div", { class: "cv-body" }), handle);
    fill(c);
    wireCard(c, handle);
    return c.el;
  }
  function wireCard(c, handle) {
    const el = c.el;
    let off = null, sparks = [];
    el.addEventListener("pointerenter", () => {
      if (el.classList.contains("drag")) return;
      if (c.d.kind === "source" && c.d.rect) off = pdf.light(c.d.page, c.d.rect);
      if (!reduced()) for (const t of threads.values()) if (t.cards.includes(c.d.id)) sparks.push(spark(t));
    });
    el.addEventListener("pointermove", (e) => {
      if (el.classList.contains("drag") || reduced()) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--ry", `${((e.clientX - r.left) / r.width - 0.5) * 6}deg`); // at most 3 degrees
      el.style.setProperty("--rx", `${-((e.clientY - r.top) / r.height - 0.5) * 6}deg`);
    });
    el.addEventListener("pointerleave", () => {
      el.style.removeProperty("--rx"); el.style.removeProperty("--ry");
      off?.(); off = null;
      sparks.forEach((s) => s.remove()); sparks = [];
    });
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button, input, textarea, select, a, [contenteditable], .cv-handle")) return;
      const sx = e.clientX, sy = e.clientY, ox = c.d.x, oy = c.d.y;
      let moved = false;
      grab(el, e);
      const move = (ev) => {
        const dx = ev.clientX - sx, dy = ev.clientY - sy;
        if (!moved && Math.hypot(dx, dy) < 4) return;
        if (!moved) { moved = true; el.classList.add("drag"); }
        c.d.x = ox + dx; c.d.y = oy + dy;
        el.style.left = `${c.d.x}px`; el.style.top = `${c.d.y}px`;
        later();
      };
      const up = () => {
        el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
        el.classList.remove("drag");
        if (moved) call(`/cards/${c.d.id}`, "PUT", { x: Math.round(c.d.x), y: Math.round(c.d.y) }).catch(() => {});
        else if (c.d.kind === "source" && c.d.rect) pdf.reveal(c.d.page, c.d.rect);
      };
      el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
    });
    el.addEventListener("keydown", (e) => {
      if (e.target === el && e.key === "Enter" && c.d.kind === "source" && c.d.rect) pdf.reveal(c.d.page, c.d.rect);
    });
    el.addEventListener("contextmenu", (e) => { e.preventDefault(); menu(e.clientX, e.clientY, c); });
    // the handle on the right edge: drag it onto another card to link the two
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      grab(handle, e);
      const tmp = sv("path", { class: "cv-thread cv-link" }); gIn.append(tmp);
      const vb = view.getBoundingClientRect();
      const under = (ev) => { const id = Number(document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".cv-card")?.dataset.id); const t = cards.get(id); return t && t !== c ? t : null; };
      let target = null;
      const move = (ev) => {
        const a = box(c), q = { x: ev.clientX - vb.left, y: ev.clientY - vb.top, w: 0, h: 0 };
        tmp.setAttribute("d", between(a, q));
        const t = under(ev);
        if (t !== target) { target?.el.classList.remove("cv-target"); target = t; target?.el.classList.add("cv-target"); }
      };
      const up = (ev) => {
        handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); handle.removeEventListener("pointercancel", up);
        tmp.remove(); target?.el.classList.remove("cv-target");
        const t = ev.type === "pointerup" ? under(ev) : null;
        if (t && !links.some((l) => (l.from_card === c.d.id && l.to_card === t.d.id) || (l.from_card === t.d.id && l.to_card === c.d.id))) {
          call("/links", "POST", { from_card: c.d.id, to_card: t.d.id })
            .then((l) => { links.push(l); redraw(true); })
            .catch(() => buddy.say("I could not link those cards. Is the app still running?", { mood: "worried" }));
        }
      };
      handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", up); handle.addEventListener("pointercancel", up);
    });
  }

  // ----- right-click menu -----
  let menuEl = null;
  const closeMenu = () => { menuEl?.remove(); menuEl = null; document.removeEventListener("pointerdown", menuOut, true); document.removeEventListener("keydown", menuKey, true); };
  const menuOut = (e) => { if (!menuEl?.contains(e.target)) closeMenu(); };
  const menuKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); closeMenu(); } };
  function menu(x, y, c) {
    closeMenu();
    menuEl = h("div", { class: "cv-menu", role: "menu", style: `left:${Math.min(x, innerWidth - 150)}px;top:${Math.min(y, innerHeight - 56)}px` },
      h("button", { type: "button", role: "menuitem", onclick: () => { closeMenu(); del(c); } }, "Delete"));
    document.body.append(menuEl);
    menuEl.firstChild.focus({ preventScroll: true });
    setTimeout(() => { document.addEventListener("pointerdown", menuOut, true); document.addEventListener("keydown", menuKey, true); }, 0);
  }

  // ----- swallow and spit -----
  const dotAt = () => buddy.centre();
  const dotPick = (kind) => (kind === "answer" ? ["#ffe347", "#f2cf1d", "#2a2c30"] : kind === "source" ? ["#1c1d20", "#565a62", "#f4f4ef"] : ["#ffe347", "#b9bcc2", "#2a2c30"]);
  // the card squashes and crumbles into dots that curve into Dot
  async function crumble(c, dx, dy, delay) {
    if (fast()) return;
    await wait(delay);
    const r = c.el.getBoundingClientRect();
    const colours = dotPick(c.d.kind), n = Math.min(70, Math.max(18, Math.round((r.width * r.height) / 1100)));
    const all = [play(c.el, [{ transform: "none", opacity: 1 }, { transform: "scale(1.04, .92)", opacity: 1, offset: 0.4 }, { transform: "scale(.92, .35)", opacity: 0 }],
      { duration: 250, easing: "ease-in" })];
    const bits = [];
    for (let i = 0; i < n; i++) {
      const sx = r.left + rnd(0, r.width), sy = r.top + rnd(0, r.height), bend = rnd(-70, 70);
      const mx = (sx + dx) / 2 - (dy - sy) * 0.25 + bend, my = (sy + dy) / 2 + (dx - sx) * 0.25 - Math.abs(bend);
      const b = h("i", { class: "cv-crumb", style: `left:${sx}px;top:${sy}px;background:${colours[i % colours.length]}` });
      fx.append(b); bits.push(b);
      all.push(play(b, [{ transform: "translate(0,0) scale(1)", opacity: 1 },
        { transform: `translate(${mx - sx}px,${my - sy}px) scale(1.15)`, opacity: 1, offset: 0.5 },
        { transform: `translate(${dx - sx}px,${dy - sy}px) scale(.2)`, opacity: 0.9 }],
      { duration: rnd(450, 800), delay: 120 + rnd(0, 320), easing: "cubic-bezier(.5,0,.8,.5)" }));
    }
    await Promise.all(all);
    bits.forEach((b) => b.remove());
  }
  async function swallowAll(list) {
    if (!list.length || fast()) return;
    await buddy.gulp();
    const [dx, dy] = dotAt();
    await Promise.all(list.map((c, i) => crumble(c, dx, dy, i * 90)));
    if (!fast()) await buddy.burp();
  }
  // a copy of the card flies out of Dot on an arc to where the card sits
  async function spit(c, delay) {
    const el = ensureEl(c);
    board.append(el);
    if (fast()) return;
    el.style.visibility = "hidden";
    await wait(delay);
    if (fast()) { el.style.visibility = ""; return; }
    const r = el.getBoundingClientRect(), [dx, dy] = dotAt();
    const ghost = el.cloneNode(true);
    ghost.classList.add("cv-ghost"); ghost.removeAttribute("tabindex"); ghost.inert = true;
    ghost.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;margin:0`;
    fx.append(ghost);
    buddy.burp();
    const fx0 = dx - (r.left + r.width / 2), fy0 = dy - (r.top + r.height / 2);
    await play(ghost, [{ transform: `translate(${fx0}px,${fy0}px) scale(.08)`, opacity: 0 },
      { transform: `translate(${fx0 * 0.45}px,${fy0 * 0.45 - 110}px) scale(.6) rotate(-6deg)`, opacity: 1, offset: 0.5 },
      { transform: "translate(0,0) scale(1) rotate(0)", opacity: 1 }], { duration: 650, easing: "cubic-bezier(.3,.7,.2,1.05)" });
    ghost.remove();
    el.style.visibility = "";
  }
  // take a card off the board and clear what the swallow animation left on it
  const lift = (c) => { c.el.getAnimations().forEach((a) => a.cancel()); c.el.style.visibility = ""; c.el.remove(); };
  async function putAway(c) {
    closeMenu();
    c.d.hidden = true;
    call(`/cards/${c.d.id}`, "PUT", { hidden: true }).catch(() => {});
    await swallowAll([c]);
    lift(c);
    updateEmpty(); redraw();
  }
  async function del(c) {
    const gone1 = call(`/cards/${c.d.id}`, "DELETE").then(() => true, () => false);
    await swallowAll([c]);
    lift(c);
    cards.delete(c.d.id);
    links = links.filter((l) => l.from_card !== c.d.id && l.to_card !== c.d.id);
    updateEmpty(); redraw();
    if (!(await gone1)) { buddy.say("I could not delete that card. Is the app still running?", { mood: "worried" }); load(true); }
  }

  // ----- threads -----
  const threads = new Map(); // key -> { path, mask, maskPath, cards: [ids] }
  let maskN = 0;
  const later = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; redraw(); }); };
  // a card's box in the reader's coordinates (what the SVG layer uses)
  function box(c) {
    const vb = view.getBoundingClientRect(), hb = host.getBoundingClientRect();
    return { x: hb.left - vb.left + pan.x + c.d.x, y: hb.top - vb.top + pan.y + c.d.y, w: c.d.w, h: c.el?.offsetHeight || 90 };
  }
  // a smooth curve from the side of `a` that faces `b`
  function between(a, b) {
    const ac = [a.x + a.w / 2, a.y + a.h / 2], bc = [b.x + b.w / 2, b.y + b.h / 2];
    let p, q, side;
    if (b.x >= a.x + a.w - 20) { p = [a.x + a.w, ac[1]]; q = [b.x, bc[1]]; side = "h"; }
    else if (b.x + b.w <= a.x + 20) { p = [a.x, ac[1]]; q = [b.x + b.w, bc[1]]; side = "h"; }
    else if (b.y >= a.y) { p = [ac[0], a.y + a.h]; q = [bc[0], b.y]; side = "v"; }
    else { p = [ac[0], a.y]; q = [bc[0], b.y + b.h]; side = "v"; }
    const i = side === "h" ? 0 : 1, dir = Math.sign(q[i] - p[i]) || 1, k = Math.max(36, Math.abs(q[i] - p[i]) / 2) * dir;
    const c1 = side === "h" ? [p[0] + k, p[1]] : [p[0], p[1] + k], c2 = side === "h" ? [q[0] - k, q[1]] : [q[0], q[1] - k];
    return `M${p} C${c1} ${c2} ${q}`;
  }
  function mkThread(key, cls) {
    const id = `cvm${paperId}-${maskN++}`;
    const path = sv("path", { class: `cv-thread ${cls}` });
    const maskPath = sv("path", { stroke: "#fff", "stroke-width": "10", fill: "none" });
    const mask = sv("mask", { id, maskUnits: "userSpaceOnUse", x: "-9999", y: "-9999", width: "30000", height: "30000" });
    mask.append(maskPath); defs.append(mask);
    return { key, id, path, mask, maskPath, cards: [] };
  }
  // a new thread draws itself in 650 ms: the mask grows along it
  function drawIn(t) {
    if (fast()) return;
    const len = t.path.getTotalLength();
    if (!len) return;
    t.maskPath.style.strokeDasharray = len;
    t.path.setAttribute("mask", `url(#${t.id})`);
    play(t.maskPath, [{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { duration: 650, easing: "cubic-bezier(.3,.7,.2,1)" })
      .then(() => { t.path.removeAttribute("mask"); t.maskPath.getAnimations().forEach((a) => a.cancel()); });
  }
  // a bright dash runs along a thread when you hover a card on it
  function spark(t) {
    const s = sv("path", { class: "cv-spark", d: t.path.getAttribute("d"), pathLength: "100" });
    s.style.strokeDasharray = "7 100";
    t.path.parentNode.append(s);
    play(s, [{ strokeDashoffset: 7 }, { strokeDashoffset: -100 }], { duration: 750, easing: "ease-in-out" }).then(() => s.remove());
    return s;
  }
  function redraw(animate = false) {
    if (holdThreads || !opened || gone) return;
    const vb = view.getBoundingClientRect(), hb = host.getBoundingClientRect();
    const ox = hb.left - vb.left, oy = hb.top - vb.top;
    for (const [k, v] of Object.entries({ x: ox, y: oy, width: hb.width, height: hb.height })) clipRect.setAttribute(k, v);
    const specs = [], tags = [];
    for (const c of cards.values()) {
      if (c.d.hidden) continue;
      const p = c.d.parent != null ? cards.get(c.d.parent) : null;
      if (p && !p.d.hidden) specs.push({ key: `p${c.d.id}`, cls: "cv-parent", grp: gIn, d: between(box(p), box(c)), cards: [p.d.id, c.d.id] });
      if (c.d.kind === "source" && c.d.page && c.d.rect) {
        const b = box(c), y0 = b.y + 16, r = pdf.toScreen(c.d.page, c.d.rect);
        if (r) { // that page is on screen: the thread reaches the paragraph
          const qx = r.right - vb.left + 4, qy = r.top + r.height / 2 - vb.top, k = Math.max(40, (b.x - qx) / 2);
          specs.push({ key: `s${c.d.id}`, cls: "cv-paper", grp: gOut, d: `M${b.x},${y0} C${b.x - k},${y0} ${qx + k},${qy} ${qx},${qy}`, cards: [c.d.id] });
        } else if (b.x > ox) { // another page: it ends at the canvas edge with the page number
          specs.push({ key: `s${c.d.id}`, cls: "cv-paper cv-edge", grp: gOut, d: `M${b.x},${y0} L${ox},${y0}`, cards: [c.d.id] });
          tags.push({ x: ox + 6, y: y0 - 6, text: `p. ${c.d.page}` });
        }
      }
    }
    for (const l of links) {
      const a = cards.get(l.from_card), b = cards.get(l.to_card);
      if (a && b && !a.d.hidden && !b.d.hidden) specs.push({ key: `l${l.id}`, cls: "cv-link", grp: gIn, d: between(box(a), box(b)), cards: [a.d.id, b.d.id] });
    }
    const seen = new Set();
    for (const s of specs) {
      seen.add(s.key);
      let t = threads.get(s.key);
      const fresh = !t || t.cls !== s.cls;
      if (fresh) {
        t?.path.remove(); t?.mask.remove();
        t = mkThread(s.key, s.cls); t.cls = s.cls; threads.set(s.key, t);
        s.grp.append(t.path);
      }
      t.cards = s.cards;
      t.path.setAttribute("d", s.d); t.maskPath.setAttribute("d", s.d);
      if (fresh && animate) drawIn(t);
    }
    for (const [k, t] of threads) if (!seen.has(k)) { t.path.remove(); t.mask.remove(); threads.delete(k); }
    gTags.replaceChildren(...tags.map((t) => { const e = sv("text", { class: "cv-tag", x: t.x, y: t.y }); e.textContent = t.text; return e; }));
  }

  // ----- opening and closing -----
  const updateEmpty = () => { empty.hidden = !opened || busy || [...cards.values()].some((c) => !c.d.hidden); };
  const setTab = (on) => { tab.setAttribute("aria-expanded", String(on)); tab.classList.toggle("on", on); };
  const circle = (x, y, r) => `circle(${r}px at ${x}px ${y}px)`;
  const reach = (hb, x, y) => Math.ceil(Math.max(Math.hypot(x, y), Math.hypot(hb.width - x, y), Math.hypot(x, hb.height - y), Math.hypot(hb.width - x, hb.height - y))) + 4;
  function ring(x, y, delay) {
    const r = h("i", { class: "cv-ring", style: `left:${x}px;top:${y}px` });
    fx.append(r);
    return play(r, [{ transform: "scale(.4)", opacity: 0.75 }, { transform: "scale(15)", opacity: 0 }], { duration: 900, delay, easing: "cubic-bezier(.2,.6,.3,1)" }).then(() => r.remove());
  }
  async function load(again = false) {
    const r = await call("").catch(() => null);
    if (!r) return;
    if (again) { cards.forEach((c) => c.el?.remove()); cards.clear(); }
    links = r.links;
    for (const d of r.cards) { const c = { d, el: null }; cards.set(d.id, c); if (!d.hidden) board.append(ensureEl(c)); }
    updateEmpty(); redraw();
  }
  async function open(o = {}) {
    if (opened || busy || locked || gone) return;
    busy = true; holdThreads = true;
    await (loaded ??= load());
    if (gone) return;
    opened = true; store.set(true); setTab(true);
    host.inert = false; host.classList.add("on");
    const quick = o.instant || reduced();
    const pending = [], tail = [];
    if (quick) view.classList.add("canvas-open");
    else {
      const [ox, oy] = dotAt();
      view.classList.add("no-slide", "canvas-open"); // measure where the canvas will end up, then slide there
      const hb = host.getBoundingClientRect();
      view.classList.remove("canvas-open"); void view.offsetWidth; view.classList.remove("no-slide"); view.classList.add("canvas-open");
      const lx = ox - hb.left, ly = oy - hb.top, R = reach(hb, lx, ly);
      wave.style.setProperty("--ox", `${lx}px`); wave.style.setProperty("--oy", `${ly}px`);
      pending.push(play(host, [{ clipPath: circle(lx, ly, 0) }, { clipPath: circle(lx, ly, R) }], { duration: 800, easing: "cubic-bezier(.6,0,.2,1)" }));
      tail.push(play(wave, [{ "--r": "-90px", opacity: 1 }, { "--r": `${R + 90}px`, opacity: 1 }], { duration: 1100, delay: 120, easing: "ease-out" }),
        ring(ox, oy, 0), ring(ox, oy, 160)); // the wave and rings keep going while the cards come out
    }
    updateEmpty();
    await Promise.all(pending);
    host.getAnimations().forEach((a) => a.cancel());
    if (!quick && !fast()) await buddy.burp();
    const back = [...cards.values()].filter((c) => c.d.hidden);
    back.forEach((c) => { c.d.hidden = false; call(`/cards/${c.d.id}`, "PUT", { hidden: false }).catch(() => {}); });
    await Promise.all(back.map((c, i) => spit(c, i * 110)));
    await Promise.all(tail);
    wave.getAnimations().forEach((a) => a.cancel());
    busy = false; holdThreads = false; skipped = false;
    svg.classList.remove("off");
    updateEmpty(); redraw(true);
  }
  async function close(o = {}) {
    if (!opened || busy) return;
    busy = true; holdThreads = true; closeMenu();
    svg.classList.add("off");
    const quick = o.instant || reduced();
    const vis = [...cards.values()].filter((c) => !c.d.hidden);
    vis.forEach((c) => { c.d.hidden = true; call(`/cards/${c.d.id}`, "PUT", { hidden: true }).catch(() => {}); });
    updateEmpty();
    if (!quick) await swallowAll(vis);
    vis.forEach(lift);
    if (quick) view.classList.remove("canvas-open");
    else {
      const [ox, oy] = dotAt(), hb = host.getBoundingClientRect(), lx = ox - hb.left, ly = oy - hb.top;
      view.classList.remove("canvas-open"); // the paper slides back while the circle shrinks into Dot
      if (fast()) snap();
      await play(host, [{ clipPath: circle(lx, ly, reach(hb, lx, ly)) }, { clipPath: circle(lx, ly, 0) }], { duration: 800, easing: "cubic-bezier(.6,0,.2,1)" });
      if (!fast()) await buddy.burp();
    }
    host.getAnimations().forEach((a) => a.cancel());
    host.classList.remove("on"); host.inert = true;
    opened = false; store.set(false); setTab(false);
    busy = false; holdThreads = false; skipped = false;
    threads.forEach((t) => { t.path.remove(); t.mask.remove(); }); threads.clear();
    gTags.replaceChildren();
  }
  const toggle = () => (opened ? close() : open());

  // dragging empty canvas pans it
  host.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !opened || e.target.closest(".cv-card, .cv-menu, button, input, textarea")) return;
    const sx = e.clientX - pan.x, sy = e.clientY - pan.y;
    grab(host, e); host.classList.add("panning");
    const move = (ev) => { pan.x = ev.clientX - sx; pan.y = ev.clientY - sy; board.style.transform = `translate(${pan.x}px,${pan.y}px)`; later(); };
    const up = () => { host.classList.remove("panning"); host.removeEventListener("pointermove", move); host.removeEventListener("pointerup", up); host.removeEventListener("pointercancel", up); };
    host.addEventListener("pointermove", move); host.addEventListener("pointerup", up); host.addEventListener("pointercancel", up);
  });

  // a free spot near the top of what you can see, in canvas coordinates
  function place() {
    const w = 260, hgt = 130, vx = -pan.x + 24, vy = -pan.y + 24;
    const used = [...cards.values()].filter((c) => !c.d.hidden).map((c) => ({ x: c.d.x, y: c.d.y, w: c.d.w, h: c.el?.offsetHeight || hgt }));
    const cols = Math.max(1, Math.floor((host.clientWidth - 24) / (w + 24)));
    for (let row = 0; row < 60; row++) for (let col = 0; col < cols; col++) {
      const x = vx + col * (w + 24), y = vy + row * 40;
      if (!used.some((u) => x < u.x + u.w + 12 && x + w + 12 > u.x && y < u.y + u.h + 12 && y + hgt + 12 > u.y)) return { x: Math.round(x), y: Math.round(y) };
    }
    return { x: Math.round(vx), y: Math.round(vy) };
  }
  function add(d) {
    cards.get(d.id)?.el?.remove();
    const c = { d, el: null };
    cards.set(d.id, c);
    if (!d.hidden) board.append(ensureEl(c));
    updateEmpty(); redraw(true);
    return c.el;
  }
  const refresh = (id) => { const c = cards.get(id); if (c?.el) { fill(c); later(); } };
  // The self-test hides the paper: the canvas goes with it, and cannot be opened until the paper is back.
  function lock(on) {
    locked = on; tab.hidden = on;
    if (on && opened) close({ instant: true });
  }

  const ro = new ResizeObserver(() => redraw());
  ro.observe(host);
  pdf.onView(() => redraw(true));
  loaded = load().then(() => { if (!gone && store.get() && !locked) { loaded = Promise.resolve(); open({ instant: true }); } });

  return {
    open, close, toggle, isOpen: () => opened, add, place, el: host, redraw, lock, refresh, card: (id) => cards.get(id),
    destroy() {
      gone = true; closeMenu();
      document.removeEventListener("pointerdown", skipAll, true);
      [...live].forEach((a) => { try { a.cancel(); } catch { /* done */ } });
      ro.disconnect(); pdf.onView(null);
      cancelAnimationFrame(raf);
      svg.remove(); tab.remove(); fx.remove();
      view.classList.remove("canvas-open");
    },
  };
}
