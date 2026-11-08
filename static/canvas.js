"use strict";
// The canvas: Dot's per-paper board of answer, source and note cards, with threads between them.
// It opens out of Dot like water: a circle grows from its face and the paper slides left. Cards are
// swallowed when it closes and spat back out when it opens. Plain script; uses h, api and buddy.
// Every animation here can be cut short by a click (it jumps to its end) and is instant with reduced motion.

function canvasPanel(host, paperId, pdf) {
  const desk = host.parentElement;
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
  let zoom = 1;
  let opened = false, busy = false, asking = false, sweeper = null, skipped = false, locked = false, loaded = null, gone = false, holdThreads = false, raf = 0;

  // ----- what is on the page -----
  const board = h("div", { class: "cv-board" });
  const hint = h("p", { class: "cv-hint", hidden: true }, "Nothing here yet.");
  const zoomOut = h("button", { type: "button", class: "cv-z", "aria-label": "Zoom out", onclick: () => zoomBy(1 / 1.15) }, "\u2212");
  const zoomLabel = h("span", { class: "cv-zlabel", "aria-hidden": "true" }, "100%");
  const zoomIn = h("button", { type: "button", class: "cv-z", "aria-label": "Zoom in", onclick: () => zoomBy(1.15) }, "+");
  const writeBtn = h("button", { type: "button", class: "cv-writebtn", onclick: () => newNote() }, "Write a note");
  const allBtn = h("button", { type: "button", class: "cv-writebtn cv-all", hidden: true, onclick: () => fold() }, "\u2190 All blobs");
  const bar = h("div", { class: "cv-bar" }, allBtn, hint, writeBtn, zoomOut, zoomLabel, zoomIn);
  // the field: every question (with its answer and references) and every note lives here as one drifting blob
  const field = h("div", { class: "cv-field", role: "list", "aria-label": "Your questions and notes" });
  // drag the left edge to give the canvas more or less room; the width is remembered
  const grip = h("div", { class: "cv-grip", role: "separator", "aria-orientation": "vertical", "aria-label": "Resize canvas", tabindex: "0" });
  // two views: the Board (blobs and cards) and the Editor (your note for this paper, written in full)
  const editor = h("div", { class: "cv-editor", hidden: true });
  const boardBtn = h("button", { type: "button", "aria-pressed": "true", onclick: () => showView("board") }, "Board");
  const editBtn = h("button", { type: "button", "aria-pressed": "false", onclick: () => showView("editor") }, "Editor");
  const views = h("div", { class: "cv-views", role: "group", "aria-label": "Canvas view" }, boardBtn, editBtn);
  let editing = false, editHooks = null, onViewChange = null;
  host.append(board, field, editor, bar, views, grip);
  const setW = (w) => {
    const max = desk.clientWidth - 360, px = Math.round(Math.max(300, Math.min(max, w)));
    desk.style.setProperty("--cv-w", `${px}px`); desk.style.setProperty("--cv-p", "minmax(0, 1fr)");
    try { localStorage.setItem("cv-w", px); } catch {}
  };
  try { const w = +localStorage.getItem("cv-w"); if (w) { desk.style.setProperty("--cv-w", `${w}px`); desk.style.setProperty("--cv-p", "minmax(0, 1fr)"); } } catch {}
  grip.addEventListener("pointerdown", (e) => {
    e.preventDefault(); e.stopPropagation(); grip.setPointerCapture(e.pointerId);
    desk.classList.add("no-slide"); host.classList.add("sizing");
    const right = desk.getBoundingClientRect().right;
    const move = (ev) => setW(right - ev.clientX);
    const up = () => { desk.classList.remove("no-slide"); host.classList.remove("sizing"); grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); grip.removeEventListener("pointercancel", up); };
    grip.addEventListener("pointermove", move); grip.addEventListener("pointerup", up); grip.addEventListener("pointercancel", up);
  });
  grip.addEventListener("keydown", (e) => {
    const k = { ArrowLeft: 40, ArrowRight: -40 }[e.key];
    if (k) { e.preventDefault(); setW(host.clientWidth + k); }
  });
  grip.addEventListener("dblclick", () => { desk.style.removeProperty("--cv-w"); desk.style.removeProperty("--cv-p"); try { localStorage.removeItem("cv-w"); } catch {} });
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
  const skipAll = () => { if (!live.size && !busy && !asking) return; if (busy || asking) { skipped = true; snap(); } sweeper?.stop(); [...live].forEach((a) => { try { a.finish(); } catch { /* already done */ } }); buddy.skip(); };
  document.addEventListener("pointerdown", skipAll, true);
  const wait = (ms) => (fast() ? Promise.resolve() : buddy.wait(ms));
  const grab = (el, e) => { try { el.setPointerCapture(e.pointerId); } catch { /* the pointer is gone; the listeners are on the element anyway */ } };
  const rnd = (a, b) => a + Math.random() * (b - a);

  // ----- cards -----
  const linesOf = (r) => Math.max(1, Math.round((r[3] - r[1]) / 12));
  const face = () => h("i", { class: "cv-face", "aria-hidden": "true" });
  const openTask = (d) => {
    for (let i = (d.entries || []).length - 1; i >= 0; i--) {
      const e = d.entries[i];
      if (e.who === "dot") return null;
      if (e.who === "me" && /(^|\n)\s*@ai\b/i.test(e.text)) return e.text.trim();
    }
    return null;
  };
  const heading = (d) => {
    if (d.page) return `Page ${d.page}`;
    const raw = d.kind === "answer" ? d.question : ((d.entries && d.entries[0]?.text) || d.text || "");
    const line = String(raw).trim().split("\n")[0].replace(/\s+/g, " ").trim();
    return (line || (d.kind === "answer" ? "Answer" : "Note")).slice(0, 72);
  };
  function fill(c) {
    const d = c.d, head = c.el.querySelector(".cv-head"), body = c.el.querySelector(".cv-body");
    const title = heading(d);
    const titleEl = d.page && d.rect
      ? h("button", { type: "button", class: "cv-title", onclick: (e) => { e.stopPropagation(); pdf.reveal(d.page, d.rect); } }, title)
      : h("h3", { class: "cv-title" }, title);
    const paras = [titleEl];
    if (d.kind === "answer") body.replaceChildren(...(d.text ? buddy.format(d.text) : []));
    else if (d.kind === "source") body.replaceChildren(h("p", {}, d.text || ""));
    else {
      const task = openTask(d), taken = (d.entries || []).some((e) => e.who === "dot");
      const status = task ? (c.fail || "Waiting for Dot.") : taken ? "Dot took this." : "";
      const entries = d.entries?.length ? d.entries : (d.text ? [{ who: "me", text: d.text }] : []);
      let lines = entries.map((e) => ({ who: e.who, text: e.text }));
      if (!d.page && lines.length) {
        const first = lines[0].text.split("\n");
        const rest = first.slice(1).join("\n").trim();
        lines = [...(rest ? [{ who: lines[0].who, text: rest }] : []), ...lines.slice(1)];
        if (!lines.length && entries.length === 1 && entries[0].text.replace(/\s+/g, " ").trim() === title) lines = [];
      }
      body.replaceChildren(
        ...(status ? [h("p", { class: "cv-status" }, status)] : []),
        ...lines.filter((e) => e.text.trim()).map((e) => h("p", { class: `cv-line ${e.who}` }, e.who === "dot" ? face() : null, e.text.trim())));
    }
    head.replaceChildren(...paras);
    c.el.classList.toggle("is-waiting", d.kind === "note" && !!openTask(d));
    c.el.classList.toggle("is-taken", d.kind === "note" && !openTask(d) && (d.entries || []).some((e) => e.who === "dot"));
    c.el.classList.toggle("has-place", !!(d.page && d.rect));
    c.el.setAttribute("aria-label", d.page && d.rect ? `${title}. Show this passage.` : title);
  }
  function ensureEl(c) {
    if (c.el) return c.el;
    const d = c.d;
    const x = h("button", { type: "button", class: "cv-x", "aria-label": "Put away", title: "Put away", onclick: (e) => { e.stopPropagation(); putAway(c); } }, "\u00d7");
    const handle = h("i", { class: "cv-handle", title: "Drag onto another card to link them", "aria-hidden": "true" });
    c.el = h("article", { class: `cv-card cv-${d.kind}`, "data-id": d.id, style: `left:${d.x}px;top:${d.y}px;width:${d.w}px`,
      role: "group", ...(d.kind !== "note" ? { tabindex: "0" } : {}) }, x, h("div", { class: "cv-head" }), h("div", { class: "cv-body" }), handle);
    fill(c);
    wireCard(c, handle);
    grew.observe(c.el);
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
    el.addEventListener("pointerleave", () => {
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
        c.d.x = ox + dx / zoom; c.d.y = oy + dy / zoom;
        el.style.left = `${c.d.x}px`; el.style.top = `${c.d.y}px`;
        later();
      };
      const up = (ev) => {
        el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
        el.classList.remove("drag");
        if (moved) { call(`/cards/${c.d.id}`, "PUT", { x: Math.round(c.d.x), y: Math.round(c.d.y) }).catch(() => {}); }
        else if (ev.type === "pointerup") activate(c, ev.clientX, ev.clientY);
      };
      el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
    });
    el.addEventListener("keydown", (e) => {
      if (e.target === el && e.key === "Enter") activate(c);
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
  // take a card off the board and clear what the swallow animation left on it
  const lift = (c) => { c.el.getAnimations().forEach((a) => a.cancel()); c.el.style.visibility = ""; c.el.remove(); };
  async function putAway(c) {
    closeMenu();
    c.d.hidden = true;
    call(`/cards/${c.d.id}`, "PUT", { hidden: true }).catch(() => {});
    await swallowAll([c]);
    lift(c);
    refreshView(); updateEmpty(); redraw();
  }
  async function del(c) {
    const gone1 = call(`/cards/${c.d.id}`, "DELETE").then(() => true, () => false);
    await swallowAll([c]);
    lift(c);
    cards.delete(c.d.id);
    links = links.filter((l) => l.from_card !== c.d.id && l.to_card !== c.d.id);
    refreshView(); updateEmpty(); redraw();
    if (!(await gone1)) { buddy.say("I could not delete that card. Is the app still running?", { mood: "worried" }); load(true); }
  }

  // Typed to Dot: "clear my notes", "delete all cards", "clear the canvas". The cards are put away, not deleted,
  // so Undo (or All blobs) brings them back.
  async function command(q) {
    if (!/^(?:please\s+)?(?:clear|remove|delete|erase|wipe|tidy|clean)(?:\s+up)?\s+(?:all\s+)?(?:of\s+)?(?:the\s+|my\s+)?(?:notes?|cards?|blobs?|canvas|board)(?:\s+(?:on|from)\s+(?:this|the)\s+(?:paper|page|canvas|board))?[.!]?$/i.test(q.trim())) return false;
    const list = [...cards.values()].filter((c) => !c.d.hidden);
    if (!list.length) { buddy.say("The canvas is already clear.", { mood: "idle" }); return true; }
    closeMenu();
    list.forEach((c) => { c.d.hidden = true; call(`/cards/${c.d.id}`, "PUT", { hidden: true }).catch(() => {}); });
    await swallowAll(list);
    list.forEach(lift);
    refreshView(); updateEmpty(); redraw();
    buddy.say(`I put away ${list.length} card${list.length === 1 ? "" : "s"}.`, { mood: "happy", actions: [{ label: "Undo", onClick: () => {
      list.forEach((c) => { c.d.hidden = false; call(`/cards/${c.d.id}`, "PUT", { hidden: false }).catch(() => {}); board.append(ensureEl(c)); });
      refreshView(); updateEmpty(); redraw(true);
    } }] });
    return true;
  }

  // ----- threads -----
  const threads = new Map(); // key -> { path, mask, maskPath, cards: [ids] }
  let maskN = 0;
  const later = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; redraw(); }); };
  // a card's box in the reader's coordinates (what the SVG layer uses)
  function box(c) {
    const vb = view.getBoundingClientRect(), r = c.el.getBoundingClientRect();
    return { x: r.left - vb.left, y: r.top - vb.top, w: r.width, h: r.height };
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
  // the thread curves out round the right side, so it does not run across the text of the cards between (a stack sits one under the other)
  function around(a, b) {
    const x = Math.max(a.x + a.w, b.x + b.w), ay = a.y + a.h / 2, by = b.y + b.h / 2, k = x + 56;
    return `M${a.x + a.w},${ay} C${k},${ay} ${k},${by} ${b.x + b.w},${by}`;
  }
  const route = (a, b, ids) => (crosses(a, b, ids) ? around(a, b) : between(a, b));
  function crosses(a, b, ids) {
    const ac = [a.x + a.w / 2, a.y + a.h / 2], bc = [b.x + b.w / 2, b.y + b.h / 2];
    const others = [...cards.values()].filter((o) => !ids.includes(o.d.id) && !o.d.hidden && !o.wait && o.el).map(box);
    for (let i = 1; i < 12; i++) {
      const x = ac[0] + (bc[0] - ac[0]) * i / 12, y = ac[1] + (bc[1] - ac[1]) * i / 12;
      if (others.some((o) => x > o.x && x < o.x + o.w && y > o.y && y < o.y + o.h)) return true;
    }
    return false;
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
  function applyBoard() {
    board.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
    const step = 22 * zoom;
    host.style.backgroundSize = `${step}px ${step}px`;
    host.style.backgroundPosition = `${pan.x}px ${pan.y}px`;
    zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
  }
  function redraw() {
    applyBoard();
    threads.forEach((t) => { t.path.remove(); t.mask.remove(); });
    threads.clear();
    gIn.replaceChildren(); gOut.replaceChildren(); gTags.replaceChildren();
    if (!opened || tree == null) { svg.classList.add("off"); paintPins(); return; }
    svg.classList.remove("off");
    for (const c of cards.values()) { // the tree's branches: question to answer to references and follow-ups
      const pa = c.d.parent && cards.get(c.d.parent);
      if (!pa?.el || !c.el || c.el.classList.contains("cv-out") || pa.el.classList.contains("cv-out") || c.wait || pa.wait) continue;
      gIn.append(sv("path", { class: "cv-thread cv-branch", d: between(box(pa), box(c)) }));
    }
    for (const l of links) {
      const a = cards.get(l.from_card), b = cards.get(l.to_card);
      if (!a?.el || !b?.el || a.d.hidden || b.d.hidden || a.wait || b.wait) continue;
      const path = sv("path", { class: "cv-thread cv-link" });
      path.setAttribute("d", between(box(a), box(b)));
      gIn.append(path);
    }
    paintPins();
  }

  // ----- opening and closing -----
  const bareBoard = () => opened && !busy && ![...cards.values()].some((c) => !c.d.hidden) && !board.querySelector(".cv-draft");
  const updateEmpty = () => { hint.hidden = !bareBoard(); };
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
    sweepTasks();
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
      pending.push(play(host, [{ clipPath: circle(lx, ly, 0) }, { clipPath: circle(lx, ly, R) }], { duration: 800, easing: "cubic-bezier(.6,0,.2,1)" }));
      tail.push(ring(ox, oy, 0)); // one soft ring; the blobs do the rest
    }
    updateEmpty();
    await Promise.all(pending);
    host.getAnimations().forEach((a) => a.cancel());
    if (!quick && !fast()) await buddy.burp();
    const back = [...cards.values()].filter((c) => c.d.hidden);
    back.forEach((c) => { c.d.hidden = false; call(`/cards/${c.d.id}`, "PUT", { hidden: false }).catch(() => {}); board.append(ensureEl(c)); });
    tree = null; setMode(); renderField(!quick && !fast());
    await Promise.all(tail);
    busy = false; holdThreads = false; skipped = false;
    svg.classList.remove("off");
    tidy();
    updateEmpty(); redraw(true);
  }
  function showView(name) {
    const on = name === "editor";
    if (on === editing) return;
    editing = on;
    host.classList.toggle("editing", on); editor.hidden = !on;
    boardBtn.setAttribute("aria-pressed", String(!on)); editBtn.setAttribute("aria-pressed", String(on));
    svg.style.visibility = on ? "hidden" : "";
    if (on) editHooks?.show?.(); else { editHooks?.hide?.(); redraw(true); }
    onViewChange?.(name);
  }
  async function edit() { // open the canvas, if it is not, on the Editor
    if (!opened) await open();
    if (opened) showView("editor");
    return opened;
  }
  async function close(o = {}) {
    if (!opened || busy) return;
    showView("board");
    busy = true; holdThreads = true; closeMenu();
    svg.classList.add("off");
    const quick = o.instant || reduced();
    const vis = [...cards.values()].filter((c) => !c.d.hidden);
    vis.forEach((c) => { c.d.hidden = true; call(`/cards/${c.d.id}`, "PUT", { hidden: true }).catch(() => {}); });
    updateEmpty();
    if (!quick) { if (tree == null) await swallowBlobs(); else await swallowAll(vis.filter((c) => !c.el.classList.contains("cv-out"))); }
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
    tree = null; setMode(); field.replaceChildren();
  }
  const toggle = () => (opened ? close() : open());

  // ----- Ask: Dot searches the page with its lens, then the answer's sources lift off the page onto cards -----
  const setPan = (x, y) => { pan.x = x; pan.y = y; board.style.transform = `translate(${x}px,${y}px)`; redraw(); };
  function panTo(nx, ny) {
    const x0 = pan.x, y0 = pan.y;
    if (Math.abs(nx - x0) < 1 && Math.abs(ny - y0) < 1) return Promise.resolve();
    if (fast()) { setPan(nx, ny); return Promise.resolve(); }
    return new Promise((done) => {
      const t0 = performance.now();
      const step = (t) => {
        const k = Math.min(1, (t - t0) / 450), e = 1 - (1 - k) ** 3;
        if (k < 1 && !skipped && !gone) { setPan(x0 + (nx - x0) * e, y0 + (ny - y0) * e); requestAnimationFrame(step); } else { setPan(nx, ny); done(); }
      };
      requestAnimationFrame(step);
    });
  }
  // slide the canvas so a group of cards is on screen (the top first if it is too tall)
  function showGroup(list) {
    const W = host.clientWidth, H = host.clientHeight, m = 16;
    const x0 = Math.min(...list.map((c) => c.d.x)), x1 = Math.max(...list.map((c) => c.d.x + c.d.w));
    const y0 = Math.min(...list.map((c) => c.d.y)), y1 = Math.max(...list.map((c) => c.d.y + (c.el?.offsetHeight || 90)));
    const fit = (lo, hi, p, size) => { let q = p; if (hi + q > size - m) q = size - m - hi; if (lo + q < m) q = m - lo; return q; };
    return panTo(fit(x0, x1, pan.x, W), fit(y0, y1, pan.y, H));
  }
  const reveal = (c) => { c.wait = false; c.el.classList.remove("cv-wait"); };
  const settle = (c) => c.el.getAnimations().forEach((a) => a.cancel());
  async function pop(c) {
    reveal(c); redraw(true);
    await play(c.el, [{ opacity: 0, transform: "scale(.9)" }, { opacity: 1, transform: "scale(1)" }], { duration: 320, easing: "cubic-bezier(.3,.7,.2,1.2)" });
    settle(c);
  }
  // the paragraph lights up, a copy of its words lifts off the page and shrinks into the card's place, and the gist card takes over
  async function fly(c) {
    const d = c.d, lf = fast() ? null : pdf.lift(d.page, d.rect);
    if (!lf) return pop(c);
    const off = pdf.light(d.page, d.rect);
    fx.append(lf.el);
    const cr = c.el.getBoundingClientRect(), r = lf.rect;
    const k = Math.max(0.2, Math.min(1, cr.width / r.width));
    const end = `translate(${cr.left + cr.width / 2 - (r.left + r.width / 2)}px,${cr.top + cr.height / 2 - (r.top + r.height / 2)}px) scale(${k})`;
    await play(lf.el, [{ transform: "none", opacity: 1 }, { transform: end, opacity: 1, offset: 0.88 }, { transform: end, opacity: 0 }], { duration: 900, easing: "cubic-bezier(.3,.7,.2,1)" });
    lf.el.remove(); off();
    reveal(c); redraw(true); // the card is there now, so its thread draws itself
    await play(c.el, [{ transform: "scale(1.05)" }, { transform: "scale(1)" }], { duration: 220 });
    settle(c);
  }
  async function runAsk({ question, page, from = null, at = null, quote = "" }) {
    if (asking || busy || gone) return;
    asking = true; skipped = false;
    let made = null;
    buddy.hold(true); // Dot stays where the work is; it does not trail the pointer meanwhile
    try {
      if (!opened) await open();
      if (!opened) return;
      laying = true; // the new cards land on a clear board (a follow-up keeps its tree in view)
      for (const c of cards.values()) if (c.el && (tree == null || rootOf(c)?.d.id !== tree)) c.el.classList.add("cv-out");
      setMode();
      const p = at ?? place(380);
      sweeper = pdf.sweep();
      trace.think([quote ? "reading your selection" : `reading page ${page}`, from ? "following the earlier cards" : null, "looking for the paragraphs", "asking the model"]);
      let r;
      try { r = await call("/ask", "POST", { question, page, from_card: from, at: [Math.round(p.x), Math.round(p.y)], quote }); }
      catch (e) { r = { ok: false, error: e.body?.detail?.errors?.question ?? "I could not reach the app. Is it still running?" }; }
      trace.done(r.trace || [r.ok ? "answered" : `failed: ${r.error}`], !r.ok);
      sweeper.stop(); await sweeper.done; sweeper = null;
      await buddy.shape("face");
      if (!r.ok) { buddy.say(r.error, { mood: "worried" }); return; }
      made = r.answer.id;
      add(r.answer, { wait: true }); r.sources.forEach((d) => add(d, { wait: true }));
      if (r.trace?.length) cards.get(made).el.append(h("details", { class: "cv-why" }, h("summary", {}, "how Dot got here"),
        h("ol", {}, ...r.trace.map((t) => h("li", {}, t))))); // shortcut: kept in memory only, gone on reload; save it on the card if it proves useful
      const mine = [r.answer, ...r.sources].map((d) => cards.get(d.id));
      // the server only guesses how tall a card is: stack them again by their real heights, with a gap
      let top = r.sources.length ? r.sources[0].y : r.answer.y;
      for (const c of [...mine.slice(1), mine[0]]) {
        if (!c.el) continue;
        if (c.d.y !== top) { c.d.y = top; c.el.style.top = `${top}px`; call(`/cards/${c.d.id}`, "PUT", { y: top }).catch(() => {}); }
        top += c.el.offsetHeight + 14;
      }
      redraw(true);
      await showGroup(mine);
      for (const c of mine.slice(1)) { if (c.d.rect && pdf.toScreen(c.d.page, c.d.rect)) await fly(c); else await pop(c); }
      const a = mine[0];
      reveal(a); redraw(true);
      await play(a.el, [{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }], { duration: 380, easing: "cubic-bezier(.3,.7,.2,1)" });
      settle(a);
    } finally {
      buddy.hold(false); sweeper?.stop(); sweeper = null; asking = false; skipped = false;
      cards.forEach((c) => { if (c.wait) { reveal(c); } }); // if something broke half way, nothing stays hidden
      laying = false;
      const a = made != null && cards.get(made);
      if (a && opened) unfold(rootOf(a)); else refreshView();
      redraw(true); buddy.shape("face");
    }
  }
  // Dot's thinking, as a quiet log in the corner: guesses while it waits, then what the server really did
  const trace = (() => {
    const el = h("ol", { class: "cv-trace", "aria-live": "polite", hidden: true });
    host.append(el);
    let timers = [];
    const clear = () => { timers.forEach(clearTimeout); timers = []; };
    const line = (t, cls = "") => { const li = h("li", { class: cls }, t); el.append(li); return li; };
    return {
      think(steps) {
        clear(); el.replaceChildren(); el.hidden = false; el.classList.remove("over", "bad");
        steps.filter(Boolean).forEach((t, i) => timers.push(setTimeout(() => {
          el.querySelector(".now")?.classList.replace("now", "was");
          line(t, "now");
        }, fast() ? 0 : i * 900)));
      },
      done(lines, bad = false) {
        clear(); el.replaceChildren(); el.classList.toggle("bad", bad);
        lines.forEach((t, i) => timers.push(setTimeout(() => line(t, "got"), fast() ? 0 : i * 140)));
        timers.push(setTimeout(() => el.classList.add("over"), 5200 + lines.length * 140));
        timers.push(setTimeout(() => { el.hidden = true; }, 6000 + lines.length * 140));
      },
    };
  })();
  // "Ask about this part": the words come from the selection (or the page, if none), the answer's cards from the model
  async function ask(sel, at) {
    if (asking || busy || locked || gone) return;
    const q = await buddy.prompt({ x: at.x, y: at.y, placeholder: sel ? "Ask about this part..." : "Ask about this page..." });
    if (q && !(await pdf.command?.(q))) await runAsk({ question: q, page: sel?.page ?? pdf.page(), quote: sel?.text || "" });
  }
  // click an answer or a source card: Dot offers a follow-up question that grows from it
  async function followUp(c, x, y) {
    if (asking || busy || gone) return;
    const r = c.el.getBoundingClientRect();
    const q = await buddy.prompt({ x: x ?? r.left + r.width / 2, y: y ?? r.top + r.height / 2, placeholder: "Follow up on this card..." });
    if (!q) return;
    await runAsk({ question: q, page: c.d.kind === "source" ? c.d.page : pdf.page(), from: c.d.id, at: { x: c.d.x + 60, y: c.d.y + (c.el.offsetHeight || 90) + 60 } });
  }
  function activate(c, x, y) {
    if (c.d.page && c.d.rect) { pdf.reveal(c.d.page, c.d.rect); return; }
    if (c.d.kind === "note") return;
    followUp(c, x, y);
  }
  async function pickup(c) {
    if (!c || c.picking || !openTask(c.d) || buddy.asleep?.()) return; // asleep: the @ai task waits until Dot wakes
    c.picking = true; c.fail = ""; fill(c);
    const r = await call(`/cards/${c.d.id}/pickup`, "POST").catch(() => null);
    c.picking = false;
    if (!r || r.ok === false) { c.fail = r?.error || "Dot could not take that yet. Is the app still running?"; fill(c); return; }
    c.d = r.card; fill(c);
    (r.sources || []).forEach((d) => add(d));
    redraw(true);
  }
  function sweepTasks() { for (const c of cards.values()) if (c.d.kind === "note" && openTask(c.d)) pickup(c); }
  const pins = h("div", { class: "cv-pins" });
  pdf.el.append(pins);
  function paintPins() {
    pins.replaceChildren();
    if (!opened) return;
    const pane = pdf.el.getBoundingClientRect();
    for (const c of cards.values()) {
      if (c.d.hidden || !c.d.page || !c.d.rect) continue;
      const r = pdf.toScreen(c.d.page, c.d.rect);
      if (!r) continue;
      pins.append(h("button", { type: "button", class: "cv-pin", title: "Show this note", "aria-label": `Note on page ${c.d.page}`,
        style: `left:${r.right - pane.left + 6}px;top:${r.top - pane.top}px`,
        onclick: () => { pdf.reveal(c.d.page, c.d.rect); showGroup([c]); } }));
    }
  }

  // dragging empty canvas pans it
  host.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !opened || editing || e.target.closest(".cv-card, .cv-menu, .cv-compose, .cv-editor, button, input, textarea")) return;
    const sx = e.clientX - pan.x, sy = e.clientY - pan.y;
    grab(host, e); host.classList.add("panning");
    const move = (ev) => { pan.x = ev.clientX - sx; pan.y = ev.clientY - sy; redraw(); };
    const up = () => { host.classList.remove("panning"); host.removeEventListener("pointermove", move); host.removeEventListener("pointerup", up); host.removeEventListener("pointercancel", up); };
    host.addEventListener("pointermove", move); host.addEventListener("pointerup", up); host.addEventListener("pointercancel", up);
  });

  // a card that grows or is dropped: an unfolded tree lays itself out again (the field shows no cards)
  function tidy() {
    if (busy || asking || !opened || laying || tree == null) return;
    layoutTree(false);
  }
  let grewRaf = 0;
  const grew = new ResizeObserver(() => {
    if (!grewRaf) grewRaf = requestAnimationFrame(() => { grewRaf = 0; tidy(); });
  });

  // ----- the field of blobs, and the tree a blob unfolds into -----
  let tree = null, laying = false; // the root id of the unfolded tree (null: the field); laying: an ask is laying out its cards
  const order = (a, b) => (String(a.d.created_at ?? "") < String(b.d.created_at ?? "") ? -1 : String(a.d.created_at ?? "") > String(b.d.created_at ?? "") ? 1 : a.d.id - b.d.id);
  function rootOf(c) {
    const seen = new Set();
    while (c?.d.parent != null && cards.get(c.d.parent) && !cards.get(c.d.parent).d.hidden && !seen.has(c.d.id)) { seen.add(c.d.id); c = cards.get(c.d.parent); }
    return c;
  }
  const kids = (c) => [...cards.values()].filter((k) => k.d.parent === c.d.id && k !== c && !k.d.hidden).sort(order);
  const treeOf = (r) => { const out = [r]; for (let i = 0; i < out.length && out.length < 200; i++) out.push(...kids(out[i]).filter((k) => !out.includes(k))); return out; };
  function setMode() {
    host.classList.toggle("fielded", tree == null && !laying);
    allBtn.hidden = tree == null || laying;
    writeBtn.hidden = laying;
  }
  function refreshView(changed = null) {
    if (!opened || laying) return;
    if (tree != null) { const r = cards.get(tree); if (!r || r.d.hidden) fold(); else layoutTree(); return; }
    renderField(false, changed && rootOf(changed));
  }
  const kindOf = (d) => (d.kind === "answer" ? "q" : d.kind === "source" ? "s" : (d.entries || []).some((e) => e.who === "dot") ? "nd" : "n");
  const KIND = { q: "Question", s: "Reference", n: "Note", nd: "Note, Dot replied" };
  function renderField(popIn = false, fresh = null) {
    const roots = [...cards.values()].filter((c) => !c.d.hidden && rootOf(c) === c).sort(order);
    const W = Math.max(280, host.clientWidth), CW = 118, RH = 136, cols = Math.max(2, Math.floor((W - 32) / CW));
    const first = (t) => String(t || "").trim().split("\n")[0].replace(/\s+/g, " ").trim();
    const clip = (t, n) => (t.length > n ? `${t.slice(0, n - 2).trim()}\u2026` : t);
    field.replaceChildren(...roots.map((c, i) => {
      const d = c.d, all = treeOf(c), srcs = all.filter((k) => k.d.kind === "source"), more = all.filter((k) => k !== c && k.d.kind === "answer").length;
      const kind = kindOf(d), raw = first(d.kind === "answer" ? d.question : d.kind === "source" ? d.text : d.entries?.[0]?.text || d.text) || KIND[kind];
      const peek = clip(first(d.kind === "answer" ? d.text : d.kind === "source" ? "" : (d.entries || []).find((e) => e.who === "dot")?.text), 120);
      const col = i % cols, row = Math.floor(i / cols);
      const jx = ((d.id * 37) % 10) - 5, jy = ((d.id * 53) % 10) - 5; // a little scatter, never overlapping
      const count = [d.page ? `p. ${d.page}` : "", srcs.length ? `${srcs.length} ref${srcs.length > 1 ? "s" : ""}` : "", more ? `${more} follow-up${more > 1 ? "s" : ""}` : ""].filter(Boolean).join(" \u00b7 ");
      let off = [];
      const b = h("button", { type: "button", role: "listitem", class: `cv-blob k-${kind}${popIn || c === fresh ? " pop" : ""}${row === 0 ? " low" : ""}${col === cols - 1 ? " end" : ""}`,
        style: `left:${16 + col * CW + (row % 2 ? 12 : 0) + jx}px;top:${16 + row * RH + jy}px;--i:${i}`,
        "aria-label": `${KIND[kind]}: ${raw}.${count ? ` ${count}.` : ""} Open`,
        onclick: () => { off.forEach((f) => f?.()); off = []; b.classList.add("press"); setTimeout(() => unfold(c, b), fast() ? 0 : 160); },
        onpointerenter: () => { // the passages it rests on light up on the paper
          off = [d, ...srcs.map((k) => k.d)].filter((x) => x.page && x.rect).slice(0, 5).map((x) => pdf.light(x.page, x.rect));
          field.classList.add("looking");
        },
        onpointerleave: () => { off.forEach((f) => f?.()); off = []; field.classList.remove("looking"); } },
        h("span", { class: "bod", "aria-hidden": "true" }, h("span", { class: "eyes" }, h("i"), h("i")), h("span", { class: "act" })),
        h("span", { class: "lbl" }, clip(raw, 48)),
        count ? h("span", { class: "cnt" }, count) : null,
        peek ? h("span", { class: "peek", "aria-hidden": "true" }, peek) : null);
      return b;
    }));
    updateEmpty();
  }
  // every blob's eyes follow the pointer across the field; the one under it looks up at you
  field.addEventListener("pointermove", (e) => {
    if (reduced()) return;
    for (const b of field.children) {
      const r = b.firstChild.getBoundingClientRect(), dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2), m = Math.hypot(dx, dy) || 1;
      const k = Math.min(1, m / 160);
      b.style.setProperty("--ex", `${(dx / m) * 4 * k}px`); b.style.setProperty("--ey", `${(dy / m) * 3 * k}px`);
    }
  });
  field.addEventListener("pointerleave", () => { for (const b of field.children) { b.style.removeProperty("--ex"); b.style.removeProperty("--ey"); } });
  // now and then one blob hops, so the field feels lived in without everything drifting
  const hopper = setInterval(() => {
    if (!host.classList.contains("fielded") || reduced() || document.hidden) return;
    const bs = [...field.children].filter((b) => !b.matches(":hover"));
    const b = bs[Math.floor(Math.random() * bs.length)];
    if (b) { b.classList.remove("hop"); void b.offsetWidth; b.classList.add("hop"); }
  }, 2600);
  // a blob opens into its tree: the question and answer first, the references beside it, follow-ups further out
  function unfold(r, from = null) {
    if (!r || busy) return;
    tree = r.d.id; setMode();
    const list = treeOf(r), ids = new Set(list.map((c) => c.d.id));
    for (const c of cards.values()) if (c.el) c.el.classList.toggle("cv-out", !ids.has(c.d.id));
    zoom = 1; pan.x = 0; pan.y = 0;
    layoutTree(!from);
    redraw();
    const fr = from?.getBoundingClientRect();
    if (fr && !fast()) list.forEach((c, i) => {
      const cr = c.el.getBoundingClientRect();
      c.el.animate([{ transform: `translate(${fr.left + fr.width / 2 - cr.left - cr.width / 2}px, ${fr.top + fr.height / 2 - cr.top - cr.height / 2}px) scale(.12)`, opacity: 0 },
        { transform: "none", opacity: 1 }], { duration: 460, delay: i * 55, easing: "cubic-bezier(.3,1.25,.4,1)", fill: "backwards" });
    });
    setTimeout(() => redraw(), fast() ? 0 : 480 + list.length * 55);
  }
  function layoutTree(slide = true) {
    const r = cards.get(tree);
    if (!r) return fold();
    const colY = [], COL = 300, before = new Map();
    const list = treeOf(r);
    if (slide && !fast()) list.forEach((c) => before.set(c, c.el.getBoundingClientRect()));
    const put = (c, depth, y0, seen) => {
      if (seen.has(c)) return; seen.add(c);
      const x = 24 + depth * COL, y = Math.max(y0, colY[depth] ?? 24);
      c.d.x = x; c.d.y = y; c.el.style.left = `${x}px`; c.el.style.top = `${y}px`;
      colY[depth] = y + c.el.offsetHeight + 16;
      for (const k of kids(c)) put(k, depth + 1, y, seen);
    };
    put(r, 0, 24, new Set());
    before.forEach((was, c) => { // cards that were already on show slide to their place
      const now = c.el.getBoundingClientRect();
      if (was.width && (Math.abs(was.left - now.left) > 1 || Math.abs(was.top - now.top) > 1))
        c.el.animate([{ translate: `${was.left - now.left}px ${was.top - now.top}px` }, { translate: "0 0" }], { duration: 380, easing: "cubic-bezier(.3,.8,.2,1)" });
    });
    later();
  }
  function fold() {
    if (tree == null) return;
    tree = null; setMode(); renderField(); redraw();
  }
  async function swallowBlobs() {
    const bl = [...field.children];
    if (!bl.length || fast()) return;
    await buddy.gulp();
    const [dx, dy] = dotAt();
    await Promise.all(bl.map((b, i) => { const r = b.getBoundingClientRect();
      return play(b, [{ transform: "none", opacity: 1 }, { transform: `translate(${dx - r.left - r.width / 2}px, ${dy - r.top - r.height / 2}px) scale(.1)`, opacity: 0.3 }],
        { duration: 520, delay: i * 45, easing: "cubic-bezier(.5,0,.8,.5)" }); }));
    if (!fast()) await buddy.burp();
  }
  // "Write a note" on the canvas: Dot becomes the note pill; the note becomes a new blob
  async function newNote() {
    if (laying || busy) return;
    const r = writeBtn.getBoundingClientRect();
    const text = await buddy.prompt({ x: r.left + r.width / 2 + 60, y: r.top - 34, placeholder: "Write a note" });
    if (text) await note({ text });
  }
  host.addEventListener("keydown", (e) => { if (e.key === "Escape" && tree != null && !laying) { e.stopPropagation(); fold(); } });

  // a free spot near the top of what you can see, in canvas coordinates
  function place(hgt = 130) {
    const w = 260, vx = -pan.x + 24, vy = -pan.y + 24;
    const used = [...cards.values()].filter((c) => !c.d.hidden).map((c) => ({ x: c.d.x, y: c.d.y, w: c.d.w, h: c.el?.offsetHeight || hgt }));
    const cols = Math.max(1, Math.floor((host.clientWidth - 24) / (w + 24)));
    for (let row = 0; row < 60; row++) for (let col = 0; col < cols; col++) {
      const x = vx + col * (w + 36), y = vy + row * (hgt + 28);
      if (!used.some((u) => x < u.x + u.w + 12 && x + w + 12 > u.x && y < u.y + u.h + 12 && y + hgt + 12 > u.y)) return { x: Math.round(x), y: Math.round(y) };
    }
    return { x: Math.round(vx), y: Math.round(vy) };
  }
  function add(d, o = {}) {
    cards.get(d.id)?.el?.remove();
    const c = { d, el: null, wait: !!o.wait }; // wait: laid out but not shown yet (an answer's cards arrive one by one)
    cards.set(d.id, c);
    if (!d.hidden) { const el = ensureEl(c); el.classList.toggle("cv-wait", c.wait); board.append(el); }
    if (!laying && !d.hidden) { c.el.classList.toggle("cv-out", tree == null || rootOf(c)?.d.id !== tree); refreshView(c); }
    updateEmpty(); redraw(true);
    return c.el;
  }
  const refresh = (id) => { const c = cards.get(id); if (c?.el) { fill(c); later(); } };
  // The self-test hides the paper: the canvas goes with it, and cannot be opened until the paper is back.
  function lock(on) {
    locked = on; tab.hidden = on;
    if (on && opened) close({ instant: true });
  }

  let fieldW = 0;
  const ro = new ResizeObserver(() => { // the field re-flows when the canvas is resized
    redraw();
    const w = host.clientWidth;
    if (host.classList.contains("fielded") && Math.abs(w - fieldW) > 40) { fieldW = w; renderField(); }
  });
  ro.observe(host);
  pdf.onView(() => redraw(true));
  loaded = load().then(async () => {
    if (gone) return;
    await bringMarks();
    if (!gone && store.get() && !locked) { loaded = Promise.resolve(); await open({ instant: true }); }
  });

  async function note(info) {
    const text = (info?.text || "").trim();
    if (!text) return null;
    const spot = place(160);
    const d = await call("/cards", "POST", {
      kind: "note", text: "", entries: [{ who: "me", text }],
      x: spot.x, y: spot.y, w: 260,
      ...(info.page ? { page: info.page } : {}),
      ...(info.rect ? { rect: info.rect } : {}),
    }).catch(() => null);
    if (!d) return null;
    add(d);
    const made = cards.get(d.id);
    if (made && openTask(made.d)) pickup(made);
    return d;
  }
  function samePlace(a, b) {
    return Array.isArray(a) && Array.isArray(b) && a.length === 4 && a.every((n, i) => Math.abs(n - b[i]) < 2);
  }
  async function bringMarks() {
    const got = await api(`/papers/${paperId}/marks`).catch(() => null);
    for (const m of got?.marks || []) {
      if (!m.text?.trim()) continue;
      const have = [...cards.values()].some((c) => c.d.page === m.page && samePlace(c.d.rect, m.rect)
        && ((c.d.entries || []).some((e) => e.text === m.text) || c.d.text === m.text));
      if (!have) await note({ page: m.page, rect: m.rect, text: m.text });
    }
  }
  function zoomBy(factor) {
    const rect = host.getBoundingClientRect();
    const mx = rect.width / 2, my = rect.height / 2;
    const wx = (mx - pan.x) / zoom, wy = (my - pan.y) / zoom;
    zoom = Math.min(2.4, Math.max(0.3, zoom * factor));
    pan.x = mx - wx * zoom; pan.y = my - wy * zoom;
    redraw();
  }
  return {
    open, close, toggle, isOpen: () => opened, edit, view: showView, editing: () => editing,
    mountEditor: (el, hooks) => { editor.append(el); editHooks = hooks; }, onViewChange: (f) => { onViewChange = f; }, add, place, ask, command, followUp, note, el: host, redraw, lock, refresh, sweep: sweepTasks, card: (id) => cards.get(id),
    destroy() {
      gone = true; closeMenu();
      document.removeEventListener("pointerdown", skipAll, true);
      [...live].forEach((a) => { try { a.cancel(); } catch { /* done */ } });
      ro.disconnect(); grew.disconnect(); pdf.onView(null); clearInterval(hopper);
      cancelAnimationFrame(raf); cancelAnimationFrame(grewRaf);
      svg.remove(); tab.remove(); fx.remove();
      view.classList.remove("canvas-open");
    },
  };
}
