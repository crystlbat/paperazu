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
    // a magnifying glass, for the shape "lens"
    lens: [[5, 1], [6, 1], [7, 1], [4, 2], [8, 2], [4, 3], [8, 3], [4, 4], [8, 4], [5, 5], [6, 5], [7, 5], [9, 6], [10, 7], [11, 8]],
  };

  const st = { mood: "idle", dx: 0, dy: 0, blink: false, talkFrame: 0, talking: false, busy: 0, spin: 0,
    muted: localStorage.getItem("buddy-muted") === "1", last: null,
    glyph: null, shapeGlyph: null, lookUntil: 0, off: { x: 0, y: 0 }, away: false, trip: 0,
    shape: "face", ui: 0, hold: 0, follow: false };
  let toolsHow = "click"; // which gesture opens the tools menu: "click" or "context" (right-click or a long press)
  const mouse = { x: -1, y: -1, in: false };

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
    const shown = st.glyph ? GLYPHS[st.glyph] : st.shapeGlyph ? GLYPHS[st.shapeGlyph] : [...EYES[eyes](dx, dy), ...MOUTHS[mouth]];
    const on = new Set(shown.map(([x, y]) => y * W + x));
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
    lastMouse = Date.now(); mouse.x = e.clientX; mouse.y = e.clientY; mouse.in = true;
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
  face.addEventListener("click", (e) => {
    if (dragged) { dragged = false; return; } // the end of a drag is not a click
    if (pressed) { pressed = false; return; } // the end of a long press is not a click
    // with "context" a mouse click shows the tip; a keyboard Enter (detail 0) still opens the menu
    if (tools && (toolsHow === "click" || e.detail === 0)) return toggleTools();
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
  /** Walk so the face is centred on (x, y). Resolves on arrival. Stays put with reduced motion.
      `ms` sets the trip time (a run around a paragraph keeps an even pace). */
  async function goTo(x, y, ms) {
    if (reduced()) return;
    const [cx, cy] = centre();
    const [hx, hy] = homeCentre();
    const dist = Math.hypot(x - cx, y - cy);
    if (dist < 4) return;
    hide();
    st.hold += 1; // following the pointer waits while a trip runs
    ms = ms ?? Math.round(Math.min(1100, Math.max(380, dist * 1.1)));
    st.off = { x: x - hx, y: y - hy };
    st.away = Math.hypot(st.off.x, st.off.y) > 4;
    lookAt(x, y, ms + 200);
    root.style.setProperty("--trip", `${ms}ms`);
    root.style.setProperty("--lean", `${Math.sign(x - cx) * 6}deg`);
    root.classList.add("moving");
    root.style.transform = `translate(${st.off.x}px, ${st.off.y}px)`;
    const cut = await waitSkippable(ms); // a click may cut the trip short
    st.hold -= 1;
    if (cut) root.style.setProperty("--trip", "1ms");
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
  let target = null, drag = null, dragged = false, pressed = false, pressTimer = 0;
  const place = (x, y) => { const [hx, hy] = homeCentre(); st.off = { x: x - hx, y: y - hy }; st.away = true; root.style.transform = `translate(${st.off.x}px, ${st.off.y}px)`; };
  function droppable(t) { target = t; if (!t) pen(false); }
  face.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || root.classList.contains("as-window")) return;
    drag = { x: e.clientX, y: e.clientY, on: false };
    face.setPointerCapture(e.pointerId);
    clearTimeout(pressTimer);
    if (tools && toolsHow === "context") pressTimer = setTimeout(() => { // a long press is a right-click for touch
      if (drag && !drag.on) { pressed = true; drag = null; toggleTools(); }
    }, 500);
  });
  face.addEventListener("contextmenu", (e) => {
    if (!tools || toolsHow !== "context") return;
    e.preventDefault(); clearTimeout(pressTimer); toggleTools();
  });
  face.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.on) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return;
      clearTimeout(pressTimer);
      drag.on = true; st.trip += 1; hide(); root.classList.add("dragging"); st.mood = "surprised"; draw();
    }
    place(e.clientX, e.clientY);
    root.classList.toggle("pen", !!target?.over(e.clientX, e.clientY));
    target?.hover?.(e.clientX, e.clientY);
  });
  face.addEventListener("pointerup", (e) => {
    clearTimeout(pressTimer);
    if (pressed) setTimeout(() => { pressed = false; }, 0);
    if (!drag) return;
    const was = drag.on; drag = null;
    if (!was) return;
    dragged = true; setTimeout(() => { dragged = false; }, 0);
    root.classList.remove("dragging");
    target?.hover?.(null);
    if (target?.over(e.clientX, e.clientY)) { st.mood = "idle"; draw(); target.drop(e.clientX, e.clientY); }
    else { root.classList.remove("pen"); st.mood = "idle"; draw(); goHome(); }
  });
  // As a highlighter Dot rides just above the pointer, eyes on the line below.
  const follow = (e) => { place(e.clientX + 26, e.clientY - 30); st.dx = -1; st.dy = 1; st.lookUntil = Date.now() + 500; draw(); };
  /** reading(on): Dot shrinks into a small yellow marker, to run along lines of the paper */
  function reading(on) { root.classList.toggle("pen", on); root.classList.toggle("reading", on); }
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
  // ---------- tools: clicking Dot fans out a few dotted choices the page offers ----------
  let tools = null;
  const toolsEl = document.createElement("div");
  toolsEl.className = "buddy-tools"; toolsEl.hidden = true; toolsEl.setAttribute("role", "menu");
  root.insertBefore(toolsEl, face);
  /** A 9 x 9 dot picture from rows of "#" and "." */
  function dotPic(rows) {
    const g = document.createElement("span"); g.className = "tool-pic"; g.setAttribute("aria-hidden", "true");
    rows.join("").split("").forEach((c) => { const d = document.createElement("i"); if (c === "#") d.className = "on"; g.append(d); });
    return g;
  }
  /** setTools([{ name, hint, pic: rows, pick() }]) or null to go back to tips */
  function setTools(list) { tools = list; closeTools(); }
  function closeTools() { toolsEl.hidden = true; root.classList.remove("tools-open"); }
  function toggleTools() {
    if (!toolsEl.hidden) return closeTools();
    hide();
    toolsEl.replaceChildren(...tools.map((t, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "buddy-tool"; b.setAttribute("role", "menuitem"); b.style.setProperty("--k", i);
      const name = document.createElement("span"); name.className = "tool-name"; name.textContent = t.name;
      const hint = document.createElement("span"); hint.className = "tool-hint"; hint.textContent = t.hint;
      b.append(dotPic(t.pic), name, hint);
      b.addEventListener("click", (e) => { e.stopPropagation(); closeTools(); t.pick(); });
      return b;
    }));
    toolsEl.hidden = false; root.classList.add("tools-open");
    st.mood = "happy"; draw(); setTimeout(() => { st.mood = "idle"; draw(); }, 600);
    toolsEl.querySelector("button")?.focus();
  }
  document.addEventListener("pointerdown", (e) => { if (!toolsEl.hidden && !root.contains(e.target)) closeTools(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !toolsEl.hidden) { closeTools(); face.focus(); } });

  // ---------- reading mode: follow the pointer, offer options, change shape, become the input ----------
  const FOLLOW = { dx: 16, dy: 14, k: 0.16 }; // the small Dot's corner trails the pointer, as in the mockup
  const pending = new Set(); // waits that a click may cut short
  // resolves true when a click cut the wait short
  const waitSkippable = (ms) => new Promise((res) => {
    const t = setTimeout(() => done(false), ms), cut = () => done(true);
    pending.add(cut);
    function done(skipped) { clearTimeout(t); pending.delete(cut); res(skipped); }
  });
  /** Cut every running shape change and spring short: they jump to their end state. */
  function skip() { [...pending].forEach((f) => f()); }
  const paused = () => !st.follow || reduced() || st.hold > 0 || st.ui > 0 || !mouse.in || drag?.on || face.matches(":hover")
    || !bubble.hidden || !toolsEl.hidden || ["pen", "reading", "penning", "as-window"].some((c) => root.classList.contains(c));
  let fraf = 0, fx = 0, fy = 0, flast = false;
  function followFrame() {
    fraf = requestAnimationFrame(followFrame);
    if (paused() || mouse.x < 0) { if (flast) { root.style.transition = ""; flast = false; } return; }
    if (!flast) { [fx, fy] = centre(); flast = true; root.style.transition = "none"; }
    // the face is centred so its top-left corner trails the pointer by (dx, dy)
    const r = face.getBoundingClientRect();
    const tx = mouse.x + FOLLOW.dx + r.width / 2, ty = mouse.y + FOLLOW.dy + r.height / 2;
    fx += (tx - fx) * FOLLOW.k; fy += (ty - fy) * FOLLOW.k;
    place(Math.min(innerWidth - 8 - r.width / 2, fx), Math.min(innerHeight - 8 - r.height / 2, fy));
  }
  /** follow(on): the small Dot trails the pointer. Off with reduced motion. */
  function followMode(on) {
    st.follow = on; root.classList.toggle("follows", on);
    cancelAnimationFrame(fraf); fraf = 0;
    if (on) { flast = false; fraf = requestAnimationFrame(followFrame); }
    else { root.style.transition = ""; flast = false; goHome(); }
  }
  document.documentElement.addEventListener("mouseleave", () => { mouse.in = false; });
  document.documentElement.addEventListener("mouseenter", () => { mouse.in = true; });

  /** toolsOn("click" | "context"): the gesture that opens the tools menu */
  function toolsOn(how) { toolsHow = how === "context" ? "context" : "click"; closeTools(); }

  const shapeClass = { lens: "sh-lens", squash: "sh-squash", pill: "sh-pill" };
  /** shape("face" | "marker" | "lens" | "squash" | "pill"): resolves when the change has settled (about 380 ms) */
  function shape(name) {
    const was = st.shape;
    st.shape = name;
    if (was === "marker" && name !== "marker") root.classList.remove("pen");
    Object.values(shapeClass).forEach((c) => root.classList.remove(c));
    if (shapeClass[name]) root.classList.add(shapeClass[name]);
    if (name === "marker") root.classList.add("pen");
    st.shapeGlyph = name === "lens" ? "lens" : null; draw();
    return reduced() ? Promise.resolve() : waitSkippable(380);
  }

  /** options({ x, y, items:[{ key, label, icon, disabled }] }) → the key picked, or null. (x, y) is Dot's centre. */
  function options({ x, y, items }) {
    closeTools();
    if (x == null) [x, y] = centre();
    st.ui += 1;
    const wrap = document.createElement("div");
    wrap.className = "buddy-opts"; wrap.setAttribute("role", "menu");
    const n = items.length, R = n > 1 ? Math.max(58, Math.ceil(21 / Math.sin(Math.PI / (2 * (n - 1))))) : 58; // 38px buttons never overlap
    let over = false, resolve;
    const result = new Promise((r) => { resolve = r; });
    const finish = (key) => {
      if (over) return; over = true;
      document.removeEventListener("keydown", onKey, true); document.removeEventListener("pointerdown", onOut, true);
      st.ui = Math.max(0, st.ui - 1);
      wrap.classList.remove("on");
      btns.forEach((b) => { b.style.left = "0px"; b.style.top = "0px"; });
      setTimeout(() => wrap.remove(), reduced() ? 0 : 220);
      resolve(key ?? null);
    };
    const btns = items.map((it, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "menuitem"); b.setAttribute("aria-label", it.label); b.disabled = !!it.disabled;
      b.innerHTML = `${it.icon || ""}<span></span>`; b.lastChild.textContent = it.label;
      const a = ((n === 1 ? -60 : -150 + (i * 180) / (n - 1)) * Math.PI) / 180;
      b.dataset.dx = Math.round(Math.cos(a) * R); b.dataset.dy = Math.round(Math.sin(a) * R);
      b.addEventListener("mousedown", (e) => e.preventDefault()); // keep the chosen words selected
      b.addEventListener("click", (e) => { e.stopPropagation(); finish(it.key); });
      wrap.append(b); return b;
    });
    // keep the arc on screen: shift the whole wrap, not the buttons
    const reach = R + 26;
    const sx = Math.min(0, innerWidth - 8 - (x + reach)) + Math.max(0, 8 - (x - reach)), sy = Math.max(0, 8 - (y - reach));
    wrap.style.cssText = `left:${x + sx}px;top:${y + sy}px`;
    document.body.append(wrap);
    void wrap.offsetWidth;
    wrap.classList.add("on");
    btns.forEach((b) => { b.style.left = `${b.dataset.dx}px`; b.style.top = `${b.dataset.dy}px`; });
    (btns.find((b) => !b.disabled) ?? btns[0])?.focus({ preventScroll: true });
    const onKey = (e) => {
      const live = btns.filter((b) => !b.disabled), i = live.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(null); }
      else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); live[(i + 1) % live.length]?.focus(); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); live[(i - 1 + live.length) % live.length]?.focus(); }
    };
    const onOut = (e) => { if (!wrap.contains(e.target)) finish(null); };
    document.addEventListener("keydown", onKey, true);
    setTimeout(() => document.addEventListener("pointerdown", onOut, true), 0);
    return result;
  }

  const BACK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>';
  /** prompt({ x, y, placeholder, hint(text) }) → the trimmed text, or null (Back, Escape, a click outside). */
  function prompt({ x, y, placeholder = "", hint } = {}) {
    closeTools();
    st.ui += 1;
    const [fx0, fy0] = centre(), PW = Math.min(300, innerWidth - 16), PH = 36;
    const left = Math.max(8, Math.min(x - PH / 2, innerWidth - PW - 8)), top = Math.max(8, Math.min(y - PH / 2, innerHeight - PH - 28));
    const el = document.createElement("form");
    el.className = "buddy-pill"; el.setAttribute("aria-label", placeholder || "Ask Dot");
    el.innerHTML = `<span class="bp-eyes" aria-hidden="true"><i></i><i></i></span>
      <input type="text" autocomplete="off" maxlength="1000"><button type="button" class="bp-back" aria-label="Back" title="Back (Esc)">${BACK}</button>
      <small class="bp-hint" aria-live="polite" hidden></small>`;
    const input = el.querySelector("input"), tip = el.querySelector(".bp-hint");
    input.placeholder = placeholder; input.setAttribute("aria-label", placeholder || "Your words");
    // it grows out of Dot's face
    el.style.cssText = reduced() ? `left:${left}px;top:${top}px;width:${PW}px` : `left:${fx0 - PH / 2}px;top:${fy0 - PH / 2}px;width:${PH}px`;
    document.body.append(el); root.classList.add("as-pill");
    if (!reduced()) { void el.offsetWidth; el.style.cssText = `left:${left}px;top:${top}px;width:${PW}px`; }
    el.classList.add("on");
    setTimeout(() => input.focus({ preventScroll: true }), reduced() ? 0 : 120);
    return new Promise((resolve) => {
      let over = false;
      function finish(text) {
        if (over) return; over = true;
        document.removeEventListener("pointerdown", onOut, true);
        st.ui = Math.max(0, st.ui - 1);
        const [cx, cy] = centre();
        if (!reduced()) el.style.cssText = `left:${cx - PH / 2}px;top:${cy - PH / 2}px;width:${PH}px`;
        el.classList.remove("on");
        setTimeout(() => { el.remove(); root.classList.remove("as-pill"); }, reduced() ? 0 : 300);
        resolve(text);
      }
      const onOut = (e) => { if (!el.contains(e.target)) finish(null); };
      el.addEventListener("submit", (e) => { e.preventDefault(); const t = input.value.trim(); if (t) finish(t); });
      el.querySelector(".bp-back").addEventListener("click", () => finish(null));
      el.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(null); } });
      input.addEventListener("input", () => {
        const s = hint?.(input.value.trim()) ?? null;
        tip.hidden = !s; tip.textContent = s ?? "";
      });
      setTimeout(() => document.addEventListener("pointerdown", onOut, true), 0);
    });
  }

  /** hold(on): keep Dot where it is (no following) for a whole menu session; call hold(false) to let it trail again */
  function hold(on) { st.ui = Math.max(0, st.ui + (on ? 1 : -1)); }
  /** put(x, y): Dot's centre is at (x, y) at once (no trailing with reduced motion: it appears where you clicked) */
  function put(x, y) { root.style.transition = "none"; place(x, y); void root.offsetWidth; root.style.transition = ""; }
  /** nudge(): a small shake, for "nothing more here" */
  function nudge() { root.classList.remove("wobble"); void root.offsetWidth; root.classList.add("wobble"); setTimeout(() => root.classList.remove("wobble"), 480); }

  /** gulp(): Dot opens wide to swallow. burp(): the bounce after it spits. */
  async function gulp() { root.classList.add("gulp"); st.mood = "surprised"; draw(); if (reduced()) return; await waitSkippable(250); }
  async function burp() {
    root.classList.remove("gulp", "full"); void root.offsetWidth; root.classList.add("full");
    st.mood = "happy"; draw();
    setTimeout(() => { root.classList.remove("full"); if (bubble.hidden) { st.mood = "idle"; draw(); } }, 520);
    if (!reduced()) await waitSkippable(300);
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
  return { say, hide, status, mood, busy, lookAt, goTo, goHome, react, trip, roam, droppable, pen, reading, open, format, draggable, tools: setTools,
    follow: followMode, options, shape, prompt, gulp, burp, toolsOn, skip, centre, put, hold, nudge, wait: waitSkippable };
})();
