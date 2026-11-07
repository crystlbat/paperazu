"use strict";
// Dot, the reading buddy: a dot-matrix face that blinks, glances, follows the cursor and talks.
// It only shows messages the app gives it. No model calls, no network.
const buddy = (() => {
  const W = 13, H = 9;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- face drawing ----------
  const block = (x, y, w, h) => Array.from({ length: w * h }, (_, i) => [x + (i % w), y + Math.floor(i / w)]);
  const EYES = {
    open: (dx, dy) => [...block(3 + dx, 2 + dy, 2, 2), ...block(8 + dx, 2 + dy, 2, 2)],
    closed: (dx, dy) => [...block(3 + dx, 3 + dy, 2, 1), ...block(8 + dx, 3 + dy, 2, 1)],
    happy: (dx) => [[2 + dx, 3], [3 + dx, 2], [4 + dx, 3], [8 + dx, 3], [9 + dx, 2], [10 + dx, 3]],
    wide: (dx, dy) => [...block(3 + dx, 1 + dy, 2, 3), ...block(8 + dx, 1 + dy, 2, 3)],
  };
  const MOUTHS = {
    smile: [[4, 6], [8, 6], [5, 7], [6, 7], [7, 7]],
    grin: [[3, 6], [9, 6], [4, 7], [5, 7], [6, 7], [7, 7], [8, 7]],
    flat: [[5, 7], [6, 7], [7, 7]],
    wobble: [[4, 7], [5, 6], [6, 7], [7, 6], [8, 7]],
    o: block(5, 6, 3, 2),
    talk: [[4, 7], [5, 7], [6, 7], [7, 7], [8, 7]],
  };
  const MOODS = {
    idle: { eyes: "open", mouth: "smile" },
    happy: { eyes: "happy", mouth: "grin" },
    think: { eyes: "open", mouth: "flat", dx: 1, dy: -1 },
    worried: { eyes: "open", mouth: "wobble" },
    sleep: { eyes: "closed", mouth: "flat" },
    surprised: { eyes: "wide", mouth: "o" },
  };

  // the rim of the grid, clockwise, for the "working" light that runs around it
  const RIM = [...Array(W).keys()].map((x) => x)
    .concat([...Array(H - 2).keys()].map((y) => (y + 1) * W + W - 1))
    .concat([...Array(W).keys()].map((x) => (H - 1) * W + W - 1 - x))
    .concat([...Array(H - 2).keys()].map((y) => (H - 2 - y) * W));

  // a tick and a cross, for when Dot judges a match
  const GLYPHS = {
    yes: [[3, 4], [4, 5], [5, 6], [6, 5], [7, 4], [8, 3], [9, 2], [3, 5], [4, 6], [5, 7], [6, 6], [7, 5], [8, 4], [9, 3]],
    no: [[4, 2], [5, 3], [6, 4], [7, 5], [8, 6], [8, 2], [7, 3], [5, 5], [4, 6], [3, 1], [9, 1], [3, 7], [9, 7]],
  };

  const st = { mood: "idle", dx: 0, dy: 0, blink: false, talkFrame: 0, talking: false, busy: 0, spin: 0,
    muted: localStorage.getItem("buddy-muted") === "1", last: null,
    glyph: null, lookUntil: 0, off: { x: 0, y: 0 }, away: false, trip: 0 };

  const root = document.createElement("aside");
  root.className = "buddy";
  root.innerHTML = `
    <div class="buddy-bubble" role="status" aria-live="polite" hidden>
      <div class="buddy-top"><span class="buddy-name">Dot</span>
        <button type="button" class="buddy-mute"></button>
        <button type="button" class="buddy-x" aria-label="Hide message">×</button></div>
      <p class="buddy-text"></p>
      <div class="buddy-actions"></div>
    </div>
    <button type="button" class="buddy-face" aria-label="Reading buddy. Show the last tip.">
      <span class="buddy-led"></span><span class="buddy-grid"></span>
    </button>`;
  const grid = root.querySelector(".buddy-grid");
  const dots = Array.from({ length: W * H }, () => grid.appendChild(document.createElement("i")));
  const bubble = root.querySelector(".buddy-bubble");
  const textEl = root.querySelector(".buddy-text");
  const actionsEl = root.querySelector(".buddy-actions");
  const face = root.querySelector(".buddy-face");
  const muteBtn = root.querySelector(".buddy-mute");

  function draw() {
    const m = MOODS[st.busy && !st.talking ? "think" : st.mood];
    const dx = st.busy ? [-1, 0, 1, 0][Math.floor(st.spin / 6) % 4] : m.dx ?? st.dx, dy = m.dy ?? st.dy;
    const eyes = st.blink && m.eyes !== "closed" ? "closed" : m.eyes;
    const mouth = st.talking ? (st.talkFrame ? "o" : "talk") : m.mouth;
    const on = new Set((st.glyph ? GLYPHS[st.glyph] : [...EYES[eyes](dx, dy), ...MOUTHS[mouth]]).map(([x, y]) => y * W + x));
    const tail = new Map(st.busy ? [0, 1, 2, 3, 4].map((k) => [RIM[(st.spin - k + RIM.length) % RIM.length], k]) : []);
    dots.forEach((d, i) => {
      d.classList.toggle("on", on.has(i) || tail.get(i) === 0);
      d.classList.toggle("trail", tail.has(i) && tail.get(i) > 0);
    });
  }

  // ---------- working: a light runs round the rim while the model is busy ----------
  let spinTimer = 0, busySince = 0;
  function busy(delta) {
    st.busy = Math.max(0, st.busy + delta);
    root.classList.toggle("busy", st.busy > 0);
    face.setAttribute("aria-label", st.busy ? "Reading buddy. The model is working." : "Reading buddy. Show the last tip.");
    if (st.busy && !spinTimer) {
      busySince = Date.now();
      if (!reduced()) spinTimer = setInterval(() => { st.spin = (st.spin + 1) % (RIM.length * 4); draw(); }, 55);
    } else if (!st.busy) {
      clearInterval(spinTimer); spinTimer = 0;
      if (!reduced() && Date.now() - busySince > 600) { root.classList.add("done"); setTimeout(() => root.classList.remove("done"), 700); }
    }
    draw();
  }

  // ---------- life: blinking, glancing, following the cursor ----------
  let lastMouse = 0;
  function scheduleBlink() {
    setTimeout(() => {
      if (!reduced()) { st.blink = true; draw(); setTimeout(() => { st.blink = false; draw(); }, 140); }
      scheduleBlink();
    }, 2500 + Math.random() * 3500);
  }
  function scheduleGlance() {
    setTimeout(() => {
      if (!reduced() && Date.now() - lastMouse > 3000 && Date.now() > st.lookUntil && st.mood !== "sleep") {
        st.dx = [-1, 0, 0, 1][Math.floor(Math.random() * 4)]; st.dy = 0; draw();
      }
      scheduleGlance();
    }, 4000 + Math.random() * 4000);
  }
  function scheduleHop() {
    setTimeout(() => {
      if (!reduced() && !st.busy && st.mood !== "sleep" && document.visibilityState === "visible") {
        root.classList.remove("hop"); void root.offsetWidth; root.classList.add("hop");
        st.dx = -1; draw(); setTimeout(() => { st.dx = 1; draw(); }, 320); setTimeout(() => { st.dx = 0; draw(); }, 640);
      }
      scheduleHop();
    }, 14000 + Math.random() * 12000);
  }
  let raf = 0;
  document.addEventListener("mousemove", (e) => {
    lastMouse = Date.now();
    if (raf || reduced() || Date.now() < st.lookUntil) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const r = face.getBoundingClientRect();
      const dx = Math.max(-1, Math.min(1, Math.round((e.clientX - (r.left + r.width / 2)) / 260)));
      const dy = e.clientY < r.top - 200 ? -1 : 0;
      if (dx !== st.dx || dy !== st.dy) { st.dx = dx; st.dy = dy; draw(); }
    });
  });

  // ---------- talking ----------
  let typing = 0, mouthTimer = 0, hideTimer = 0;
  function show(msg) {
    if (st.away) home(); // talk from the corner, where the bubble has room
    clearInterval(typing); clearInterval(mouthTimer); clearTimeout(hideTimer);
    st.mood = msg.mood; st.talking = false; draw();
    actionsEl.replaceChildren(...(msg.actions || []).map((a) => {
      const b = document.createElement(a.href ? "a" : "button");
      b.className = "btn ghost small-btn"; b.textContent = a.label;
      if (a.href) b.href = a.href; else b.type = "button";
      b.addEventListener("click", () => { a.onClick?.(); hide(); });
      return b;
    }));
    bubble.hidden = false;
    root.classList.add("talking");
    if (reduced()) { textEl.textContent = msg.text; return autoHide(msg); }
    textEl.textContent = "";
    const start = performance.now();
    st.talking = true;
    mouthTimer = setInterval(() => { st.talkFrame ^= 1; draw(); }, 110);
    typing = setInterval(() => {
      // by elapsed time, so a throttled tab catches up instead of crawling
      const i = Math.ceil((performance.now() - start) / 11);
      textEl.textContent = msg.text.slice(0, i);
      if (i >= msg.text.length) {
        clearInterval(typing); clearInterval(mouthTimer);
        st.talking = false; draw(); autoHide(msg);
      }
    }, 22);
  }
  function autoHide(msg) {
    if (msg.actions?.length || msg.sticky) return;
    hideTimer = setTimeout(() => { if (!root.matches(":hover")) hide(); }, Math.max(6000, msg.text.length * 70));
  }
  function hide() {
    bubble.hidden = true; root.classList.remove("talking");
    clearInterval(typing); clearInterval(mouthTimer); st.talking = false;
    if (st.mood !== "sleep") st.mood = st.muted ? "sleep" : "idle";
    draw();
  }

  function setMuted(m) {
    st.muted = m; localStorage.setItem("buddy-muted", m ? "1" : "0");
    muteBtn.textContent = m ? "Wake up" : "Quiet";
    muteBtn.setAttribute("aria-label", m ? "Let Dot pop up with tips again" : "Stop Dot from popping up");
  }
  muteBtn.addEventListener("click", () => { setMuted(!st.muted); if (st.muted) { st.mood = "sleep"; hide(); } });
  root.querySelector(".buddy-x").addEventListener("click", hide);
  root.addEventListener("mouseleave", () => {
    if (!bubble.hidden && !actionsEl.children.length) hideTimer = setTimeout(hide, 2500);
  });
  root.addEventListener("mouseenter", () => clearTimeout(hideTimer));

  const TIPS = [
    "Write it in your own words first. Open the AI summary after.",
    "Wrong notes are fine. You fix them in the check. Copied notes teach you nothing.",
    "Stuck? Write down the exact sentence you do not understand, and move on.",
    "Read the figures before the text. They often tell the whole story.",
    "A short break between steps helps you remember more.",
  ];
  face.addEventListener("click", () => {
    if (dragged) { dragged = false; return; } // the end of a drag is not a click
    if (!bubble.hidden) return hide();
    if (st.muted) setMuted(false);
    if (!reduced()) { st.mood = "surprised"; draw(); }
    const msg = st.last ?? { text: TIPS[Math.floor(Math.random() * TIPS.length)], mood: "idle" };
    setTimeout(() => show(msg), reduced() ? 0 : 260);
  });

  // ---------- public ----------
  /** say(text, {mood, actions:[{label, href|onClick}], pop=true, sticky}) */
  function say(text, opts = {}) {
    const msg = { text, mood: opts.mood || "idle", actions: opts.actions, sticky: opts.sticky };
    st.last = msg;
    if (opts.pop === false || st.muted) {
      if (opts.mood && !st.muted && bubble.hidden) { st.mood = opts.mood === "happy" ? "idle" : opts.mood; draw(); }
      return;
    }
    show(msg);
  }
  function status(s) { root.dataset.status = s; }

  // ---------- moving about: travel to a point, look at a point, judge, wander ----------
  const centre = () => { const r = face.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  // where the face sits in its corner: its centre now, less however far the glide has carried it so far
  const homeCentre = () => { const [cx, cy] = centre(), m = new DOMMatrixReadOnly(getComputedStyle(root).transform); return [cx - m.m41, cy - m.m42]; };
  /** Turn the eyes toward a point on screen and hold the look for `ms`. */
  function lookAt(x, y, ms = 1800) {
    const [cx, cy] = centre();
    st.dx = Math.max(-1, Math.min(1, Math.round((x - cx) / 120)));
    st.dy = y < cy - 60 ? -1 : y > cy + 60 ? 1 : 0;
    st.lookUntil = Date.now() + ms; draw();
  }
  /** Walk so the face is centred on (x, y). Resolves on arrival. Stays put with reduced motion. */
  async function goTo(x, y) {
    if (reduced()) return;
    const [cx, cy] = centre();
    const [hx, hy] = homeCentre();
    const dist = Math.hypot(x - cx, y - cy);
    if (dist < 4) return;
    hide();
    const ms = Math.round(Math.min(1100, Math.max(380, dist * 1.1)));
    st.off = { x: x - hx, y: y - hy };
    st.away = Math.hypot(st.off.x, st.off.y) > 4;
    lookAt(x, y, ms + 200);
    root.style.setProperty("--trip", `${ms}ms`);
    root.style.setProperty("--lean", `${Math.sign(x - cx) * 6}deg`);
    root.classList.add("moving");
    root.style.transform = `translate(${st.off.x}px, ${st.off.y}px)`;
    await wait(ms);
    root.classList.remove("moving");
  }
  function home() {
    st.off = { x: 0, y: 0 }; st.away = false;
    root.style.setProperty("--trip", "700ms");
    root.style.transform = "";
  }
  async function goHome() {
    if (!st.away) return;
    await goTo(...homeCentre());
    home();
  }
  /** Show a tick ("yes") or a cross ("no") with a nod or a shake. */
  async function react(kind) {
    st.glyph = kind; draw();
    root.classList.remove("yes", "no"); void root.offsetWidth; root.classList.add(kind);
    await wait(reduced() ? 500 : 750);
    st.glyph = null; root.classList.remove(kind); draw();
  }
  /** A trip is a run of moves that owns Dot; starting a new one cancels the old. */
  function trip() { st.trip += 1; const id = st.trip; return () => id === st.trip; }

  // wander inside the area the page gives (a function returning a DOMRect), then come back
  let roamArea = null;
  function roam(area) { roamArea = area; if (!area) { st.trip += 1; goHome(); } }
  (function scheduleRoam() {
    setTimeout(async () => {
      const r = roamArea?.();
      if (r && !reduced() && !st.busy && !st.away && bubble.hidden && document.visibilityState === "visible") {
        const live = trip();
        await goTo(r.left + 60 + Math.random() * (r.width - 120), r.top + 60 + Math.random() * (r.height - 120));
        for (const d of [-1, 1, 0]) { if (!live()) return; st.dx = d; st.lookUntil = Date.now() + 700; draw(); await wait(600); }
        if (live()) { root.classList.remove("hop"); void root.offsetWidth; root.classList.add("hop"); await wait(2600); }
        if (live()) goHome();
      }
      scheduleRoam();
    }, 9000 + Math.random() * 8000);
  })();
  function mood(m) { if (bubble.hidden) { st.mood = m; draw(); } }

  // ---------- drag Dot onto the page: it turns into a highlighter ----------
  // The page says where Dot may land with droppable({ over(x, y), drop(x, y) }).
  let target = null, drag = null, dragged = false;
  const place = (x, y) => { const [hx, hy] = homeCentre(); st.off = { x: x - hx, y: y - hy }; st.away = true; root.style.transform = `translate(${st.off.x}px, ${st.off.y}px)`; };
  function droppable(t) { target = t; if (!t) pen(false); }
  face.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || root.classList.contains("as-window")) return;
    drag = { x: e.clientX, y: e.clientY, on: false };
    face.setPointerCapture(e.pointerId);
  });
  face.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.on) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return;
      drag.on = true; st.trip += 1; hide(); root.classList.add("dragging"); st.mood = "surprised"; draw();
    }
    place(e.clientX, e.clientY);
    root.classList.toggle("pen", !!target?.over(e.clientX, e.clientY));
  });
  face.addEventListener("pointerup", (e) => {
    if (!drag) return;
    const was = drag.on; drag = null;
    if (!was) return;
    dragged = true; setTimeout(() => { dragged = false; }, 0);
    root.classList.remove("dragging");
    if (target?.over(e.clientX, e.clientY)) { st.mood = "idle"; draw(); target.drop(e.clientX, e.clientY); }
    else { root.classList.remove("pen"); st.mood = "idle"; draw(); goHome(); }
  });
  // As a highlighter Dot rides just above the pointer, eyes on the line below.
  const follow = (e) => { place(e.clientX + 26, e.clientY - 30); st.dx = -1; st.dy = 1; st.lookUntil = Date.now() + 500; draw(); };
  function pen(on) {
    root.classList.toggle("pen", on); root.classList.toggle("penning", on);
    document[on ? "addEventListener" : "removeEventListener"]("pointermove", follow);
  }

  // ---------- the Dot window: Dot bursts into dots that become a window ----------
  /** open({ x, y, quote, first, ask(question), area?: DOMRect to open inside, save?(text) }) → close() */
  function open({ x, y, quote, first, ask, area, save }) {
    pen(false);
    const [fx, fy] = centre();
    const w = Math.min(500, innerWidth - 24), maxH = Math.min(620, innerHeight * 0.78);
    // inside the area it was asked from (the paper), so it does not cover the notes
    const box = area && area.width >= w + 24 ? area : { left: 0, right: innerWidth };
    const left = Math.max(box.left + 12, Math.min(x + 24, box.right - w - 12));
    const top = Math.max(12, Math.min(y - 60, innerHeight - maxH - 12));
    const el = document.createElement("section");
    el.className = "dot-win"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Dot explains");
    el.style.cssText = `left:${left}px;top:${top}px;width:${w}px;max-height:${maxH}px`;
    el.innerHTML = `<header class="dw-head"><span class="buddy-name">Dot</span><button type="button" class="buddy-x" aria-label="Close">×</button></header>
      <blockquote class="dw-quote"></blockquote><div class="dw-log" aria-live="polite"></div>
      <form class="dw-ask"><input type="text" placeholder="Ask a follow-up" aria-label="Ask a follow-up" autocomplete="off"><button type="submit" class="btn small-btn">Ask</button></form>`;
    el.querySelector(".dw-quote").textContent = quote;
    const log = el.querySelector(".dw-log"), form = el.querySelector(".dw-ask"), input = form.querySelector("input");
    document.body.append(el);
    root.classList.add("as-window"); hide();
    const r = el.getBoundingClientRect(), ox = fx - r.left, oy = fy - r.top, R = Math.hypot(r.width, r.height);
    if (!reduced()) {
      for (let i = 0; i < 64; i++) { // the dots multiply and fly out to make the window
        const d = document.createElement("i"); d.className = "dw-spark";
        d.style.cssText = `left:${fx}px;top:${fy}px`;
        document.body.append(d);
        const tx = r.left + Math.random() * r.width - fx, ty = r.top + Math.random() * r.height - fy;
        d.animate([{ transform: "translate(0,0) scale(1)", opacity: 1 }, { transform: `translate(${tx}px,${ty}px) scale(.6)`, opacity: 0.9, offset: 0.7 }, { transform: `translate(${tx}px,${ty}px) scale(0)`, opacity: 0 }],
          { duration: 620, delay: i * 4, easing: "cubic-bezier(.2,.7,.2,1)" }).finished.then(() => d.remove());
      }
      el.animate([{ clipPath: `circle(10px at ${ox}px ${oy}px)`, opacity: 0.4 }, { clipPath: `circle(${R}px at ${ox}px ${oy}px)`, opacity: 1 }],
        { duration: 560, delay: 180, easing: "cubic-bezier(.3,.7,.2,1)", fill: "backwards" });
    }
    draggable(el, el.querySelector(".dw-head"));
    const add = (cls, text) => { const p = document.createElement("div"); p.className = cls; p.append(...format(text)); log.append(p); p.scrollIntoView({ block: "nearest" }); return p; };
    let lastQ = "";
    async function answer(promise) {
      const pending = add("dw-wait", "Reading the paper");
      form.querySelector("button").disabled = true;
      const res = await promise.catch(() => ({ ok: false, error: "Could not ask the model. Is the app still running?" }));
      pending.remove(); form.querySelector("button").disabled = false;
      const a = add(res.ok ? "dw-a" : "dw-a err", res.ok ? res.text : res.error);
      if (res.ok && save) {
        const q = lastQ, b = document.createElement("button");
        b.type = "button"; b.className = "dw-save"; b.textContent = "Add to my note";
        b.addEventListener("click", async () => { b.disabled = true; b.textContent = (await save({ quote, question: q, answer: res.text })) === false ? "Could not add it" : "Added to your note"; });
        a.append(b);
      }
      input.focus();
    }
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = input.value.trim();
      if (!q || form.querySelector("button").disabled) return;
      input.value = ""; lastQ = q; add("dw-q", q); answer(ask(q));
    });
    let closed = false;
    async function close() {
      if (closed) return; closed = true;
      document.removeEventListener("keydown", onKey);
      if (!reduced()) {
        const b = el.getBoundingClientRect();
        const shrink = el.animate([{ clipPath: `circle(${R}px at ${fx - b.left}px ${fy - b.top}px)` }, { clipPath: `circle(10px at ${fx - b.left}px ${fy - b.top}px)`, opacity: 0.3 }],
          { duration: 380, easing: "cubic-bezier(.6,0,.8,.4)", fill: "forwards" });
        await Promise.race([shrink.finished, wait(420)]); // a busy or hidden tab can stall animations
      }
      el.remove(); root.classList.remove("as-window");
      st.mood = "happy"; draw(); setTimeout(() => { st.mood = "idle"; draw(); goHome(); }, 500);
    }
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    el.querySelector(".buddy-x").addEventListener("click", close);
    answer(first);
    return close;
  }
  // Drag a floating card by its handle (buttons inside the handle still click). Kept on screen.
  function draggable(el, handle) {
    handle.style.cursor = "grab"; handle.style.touchAction = "none";
    let start = null;
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button, input, a")) return;
      const dx = parseFloat(el.style.getPropertyValue("--dx")) || 0, dy = parseFloat(el.style.getPropertyValue("--dy")) || 0;
      start = { x: e.clientX - dx, y: e.clientY - dy, r: el.getBoundingClientRect(), dx, dy };
      handle.setPointerCapture(e.pointerId); handle.style.cursor = "grabbing"; e.preventDefault();
    });
    handle.addEventListener("pointermove", (e) => {
      if (!start) return;
      const { r } = start;
      // how far the card may go and still keep its handle on screen
      const nx = Math.max(start.dx - r.left + 8, Math.min(start.dx + innerWidth - r.right - 8, e.clientX - start.x));
      const ny = Math.max(start.dy - r.top + 8, Math.min(start.dy + innerHeight - r.top - 48, e.clientY - start.y));
      el.style.setProperty("--dx", `${nx}px`); el.style.setProperty("--dy", `${ny}px`);
    });
    const end = () => { start = null; handle.style.cursor = "grab"; };
    handle.addEventListener("pointerup", end); handle.addEventListener("pointercancel", end);
  }

  // Model text as paragraphs and lists; small models add Markdown marks even when asked not to.
  function format(text) {
    const out = [];
    let list = null;
    for (const raw of text.split(/\n+/)) {
      const line = raw.replace(/\*\*(.+?)\*\*/g, "$1").replace(/(^|\s)\*(\S.*?)\*/g, "$1$2").replace(/^#+\s*/, "").trim();
      if (!line) continue;
      const item = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)/);
      if (item) { if (!list) out.push(list = document.createElement("ul")); const li = document.createElement("li"); li.textContent = item[1]; list.append(li); continue; }
      list = null;
      const p = document.createElement("p"); p.textContent = line; out.push(p);
    }
    return out;
  }

  document.body.append(root);
  setMuted(st.muted);
  if (st.muted) st.mood = "sleep";
  draw(); scheduleBlink(); scheduleGlance(); scheduleHop();
  return { say, hide, status, mood, busy, lookAt, goTo, goHome, react, trip, roam, droppable, pen, open, format, draggable };
})();
