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
      <span class="buddy-eyes" aria-hidden="true"><i></i><i></i></span>
      <svg class="buddy-lensg" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-5-5"/></svg>
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
    const eyesOnly = root.classList.contains("follows");
    const shown = st.glyph ? GLYPHS[st.glyph] : st.shapeGlyph ? GLYPHS[st.shapeGlyph]
      : eyesOnly ? EYES[eyes](dx, dy) : [...EYES[eyes](dx, dy), ...MOUTHS[mouth]];
    root.classList.toggle("talking", st.talking && eyesOnly);
    // the wandering circle: its two eyes follow the same mood, blink and glance
    root.classList.toggle("blinking", st.blink); root.dataset.eyes = eyes;
    face.style.setProperty("--ex", `${dx * 7}px`); face.style.setProperty("--ey", `${dy * 6}px`);
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
    if (tools && toolsHow === "click" && atHome()) { // a click at home opens the circle, not the icon pile
      if (nestHeld) { nestHeld = false; return; }
      if (nest.classList.contains("show")) hideNest(); else showNest();
      return;
    }
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
    hide(); closeTools(); // the icon row is for home, not a trip
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
    showHome();
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
  let target = null, drag = null, dragged = false, pressed = false, pressTimer = 0, nestHeld = false;
  const nest = document.createElement("div");
  nest.className = "buddy-nest"; nest.setAttribute("aria-hidden", "true");
  document.body.append(nest);
  const placeNest = () => { const [hx, hy] = homeCentre(); nest.style.left = `${hx}px`; nest.style.top = `${hy}px`; };
  const showNest = () => { placeNest(); nest.classList.add("show"); };
  const hideNest = () => nest.classList.remove("show", "awake", "ready");
  const overNest = (x, y) => { const r = nest.getBoundingClientRect(); return !!r.width && Math.hypot(x - r.left - r.width / 2, y - r.top - r.height / 2) < r.width / 2; };
  const chill = () => { root.classList.remove("awake"); nest.classList.remove("awake", "ready"); st.mood = "idle"; draw(); };
  function wake() {
    if (root.classList.contains("awake")) return;
    root.classList.remove("pen", "penning", "reading");
    root.classList.add("awake"); nest.classList.add("awake"); nest.classList.remove("ready");
    st.mood = "surprised"; draw();
    along?.pull?.(); // tag-along starts as Dot leaves the circle
  }
  document.addEventListener("pointerdown", (e) => { if (nest.classList.contains("show") && !st.follow && !root.contains(e.target)) hideNest(); });
  root.addEventListener("wheel", (e) => { // the page keeps scrolling when the pointer is over Dot
    const stage = document.querySelector(".pdf-stage");
    if (!stage || e.target.closest(".buddy-bubble")) return;
    stage.scrollTop += e.deltaY; stage.scrollLeft += e.deltaX;
  }, { passive: true });
  const place = (x, y) => { const [hx, hy] = homeCentre(); st.off = { x: x - hx, y: y - hy }; st.away = true; root.style.transform = `translate(${st.off.x}px, ${st.off.y}px)`; };
  function droppable(t) { target = t; if (!t) pen(false); }
  face.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || root.classList.contains("as-window")) return;
    const pull = atHome() || (nest.classList.contains("show") && overNest(e.clientX, e.clientY));
    drag = { x: e.clientX, y: e.clientY, on: false, pull };
    if (atHome() && !nest.classList.contains("show")) { showNest(); nestHeld = true; }
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
    if (drag.pull) { // leaving the home circle wakes tag-along. It is not the highlighter.
      root.classList.remove("pen", "penning", "reading");
      if (nest.classList.contains("show")) {
        const inside = overNest(e.clientX, e.clientY);
        nest.classList.toggle("ready", inside);
        if (!inside) wake();
      }
      return;
    }
    const live = !along || st.follow;
    root.classList.toggle("pen", live && !!target?.over(e.clientX, e.clientY));
    if (live) target?.hover?.(e.clientX, e.clientY);
  });
  face.addEventListener("pointerup", (e) => {
    clearTimeout(pressTimer);
    if (pressed) setTimeout(() => { pressed = false; }, 0);
    if (!drag) return;
    const was = drag.on, wasPull = drag.pull; drag = null;
    if (!was) return;
    dragged = true; nestHeld = false; setTimeout(() => { dragged = false; }, 0);
    root.classList.remove("dragging");
    target?.hover?.(null);
    const back = nest.classList.contains("show") && overNest(e.clientX, e.clientY);
    if (along && (wasPull || back)) { // this drag woke Dot, or it landed back in the corner
      root.classList.remove("pen", "penning", "reading");
      if (back) {
        const wasAwake = root.classList.contains("awake");
        chill(); goHome();
        if (wasAwake) { along.home(); hideNest(); }
      } else if (!root.classList.contains("awake")) wake();
      return;
    }
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
  /** setTools([{ group, name, hint, pick() }]) or null to go back to tips */
  function setTools(list) { tools = list; closeTools(); if (atHome()) showHome(); }
  let homeStay = false;
  function closeTools() { homeStay = false; toolsEl.hidden = true; root.classList.remove("tools-open"); }
  const atHome = () => !st.follow && !st.away && !root.classList.contains("moving");
  function toggleTools() {
    if (!atHome()) return closeTools(); // wandering: the paragraph buddies do the work, not this row
    if (!toolsEl.hidden) return closeTools();
    hide();
    const list = tools.slice();
    const span = Math.PI * 0.5, radius = 128; // left to straight up, just off the face, circles do not touch
    const step = span / Math.max(1, list.length - 1);
    let a = Math.PI;
    const buttons = list.map((t, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = `buddy-tool tool-${t.key || "item"}${t.on ? " on" : ""}`;
      b.setAttribute("role", "menuitem"); b.setAttribute("aria-label", t.hint ? `${t.name}. ${t.hint}` : t.name);
      b.style.setProperty("--k", i); b.style.setProperty("--bc", t.color || "#ffe347");
      b.style.setProperty("--ox", `${Math.cos(a) * radius}px`);
      b.style.setProperty("--oy", `${Math.sin(a) * radius}px`);
      a += step;
      b.innerHTML = t.icon || "";
      const tip = document.createElement("span"); tip.className = "tip";
      const title = document.createElement("b"); title.textContent = t.name;
      const line = document.createElement("small"); line.textContent = t.hint || "";
      tip.append(title, line); b.append(tip);
      b.addEventListener("click", (e) => { e.stopPropagation(); closeTools(); t.pick(); });
      return b;
    });
    toolsEl.replaceChildren(...buttons);
    toolsEl.hidden = false; root.classList.add("tools-open");
    draw();
    if (!homeStay) toolsEl.querySelector("button")?.focus();
  }
  const paperSelection = () => {
    const s = getSelection();
    if (!s || s.isCollapsed || !s.anchorNode) return false;
    const layer = document.querySelector(".page-read .textLayer");
    return !!(layer && layer.contains(s.anchorNode));
  };
  function showHome() {
    if (!tools || !atHome() || paperSelection()) return closeTools();
    homeStay = true;
    if (!toolsEl.hidden) return;
    toggleTools();
  }
  document.addEventListener("selectionchange", () => { if (tools && atHome()) showHome(); });
  document.addEventListener("pointerdown", (e) => { if (!homeStay && !toolsEl.hidden && !root.contains(e.target)) closeTools(); });
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
  /** follow(on): tag-along. Dot trails the pointer until you send it home. Off with reduced motion. Dot rests at home otherwise. */
  function followMode(on) {
    st.follow = on; root.classList.toggle("along", on);
    if (on) closeTools();
    cancelAnimationFrame(fraf); fraf = 0;
    if (on) { flast = false; fraf = requestAnimationFrame(followFrame); }
    else { root.style.transition = ""; flast = false; goHome(); }
  }
  /** look(on): the reader's Dot: the same yellow circle with two eyes as the Library's Dot. Where it rests is still the corner. */
  function look(on) { root.classList.toggle("follows", on); }
  /** tagAlong({ pull(x, y), home() } | null): what dragging Dot off its home, and dropping it on its home, mean on this screen */
  let along = null;
  const tagAlong = (hooks) => { along = hooks; };
  document.documentElement.addEventListener("mouseleave", () => { mouse.in = false; });
  document.documentElement.addEventListener("mouseenter", () => { mouse.in = true; });

  /** toolsOn("click" | "context"): the gesture that opens the tools menu */
  function toolsOn(how) { toolsHow = how === "context" ? "context" : "click"; if (tools && atHome()) showHome(); else closeTools(); }

  const shapeClass = { lens: "sh-lens", squash: "sh-squash", pill: "sh-pill", blob: "sh-blob" };
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

  function nudgeMoonNames(orbs, angles) {
    const words = [...document.querySelectorAll(".page-read .textLayer span")]
      .filter((sp) => sp.textContent.trim()).map((sp) => sp.getBoundingClientRect()).filter((r) => r.width > 1);
    const passages = [...document.querySelectorAll(".sel-box:not([hidden])")].map((el) => el.getBoundingClientRect());
    const over = (r, list) => list.some((s) => r.left < s.right && r.right > s.left && r.top < s.bottom && r.bottom > s.top);
    orbs.forEach((b, i) => {
      const ux = Math.cos(angles[i]), uy = Math.sin(angles[i]);
      let dist = 46;
      const tag = b.querySelector(".tag");
      const stage = document.querySelector(".pdf-stage")?.getBoundingClientRect();
      for (let k = 0; k < 14; k++) {
        b.style.setProperty("--lx", `${Math.round(ux * dist)}px`);
        b.style.setProperty("--ly", `${Math.round(uy * dist)}px`);
        const box = tag.getBoundingClientRect();
        const r = { left: box.left - 4, right: box.right + 4, top: box.top - 3, bottom: box.bottom + 3 };
        const moon = orbs.some((o) => {
          if (o === b) return false;
          const m = (o.querySelector(".bod") || o).getBoundingClientRect();
          return r.left < m.right && r.right > m.left && r.top < m.bottom && r.bottom > m.top;
        });
        const offStage = stage && (box.left < stage.left + 4 || box.right > stage.right - 4 || box.top < stage.top + 4 || box.bottom > stage.bottom - 4);
        if (offStage || (!over(r, words) && !over(r, passages) && !moon)) break;
        dist += 28;
      }
    });
  }

  // Moons: one even ring around Dot. The old column of places is not used.
  // Face is 92px while the ring is open, so the centre stays 46px clear of the paper edge.
  function moonSpot(hintX, hintY, n) {
    const FACE = 46, MOON = 32;
    const stage = document.querySelector(".pdf-stage")?.getBoundingClientRect();
    const bar = Math.max(
      document.querySelector(".topbar")?.getBoundingClientRect().bottom || 0,
      document.querySelector(".pdf-tools")?.getBoundingClientRect().bottom || 0,
    );
    const tab = document.querySelector(".cv-tab")?.getBoundingClientRect();
    const L = (stage?.left ?? 8) + 8;
    const Rgt = Math.min(stage?.right ?? innerWidth, tab && tab.width > 8 ? tab.left - 6 : innerWidth) - 8;
    const T = Math.max(stage?.top ?? 0, bar) + 8;
    const B = (stage?.bottom ?? innerHeight) - 8;
    const passages = [];
    const sel = getSelection();
    if (sel && !sel.isCollapsed && sel.rangeCount) { for (const r of sel.getRangeAt(0).getClientRects()) passages.push(r); }
    document.querySelectorAll(".sel-box:not([hidden])").forEach((el) => passages.push(el.getBoundingClientRect()));
    const words = [...document.querySelectorAll(".page-read .textLayer span")]
      .filter((sp) => sp.textContent.trim())
      .map((sp) => sp.getBoundingClientRect())
      .filter((r) => r.width > 1 && r.height > 1);
    const hit = (box, rects) => rects.some((r) => box.l < r.right - 1 && box.r > r.left + 1 && box.t < r.bottom - 1 && box.b > r.top + 1);
    const disk = (cx, cy, rad) => ({ l: cx - rad, t: cy - rad, r: cx + rad, b: cy + rad });
    const blocked = (cx, cy, R, wordsToo) => {
      const name = 46; // room for the short name just outside the moon
      if (cx - R - MOON - name < L || cx + R + MOON + name > Rgt || cy - R - MOON - 18 < T || cy + R + MOON + 18 > B) return true;
      if (hit(disk(cx, cy, FACE - 2), passages)) return true;
      if (wordsToo && hit(disk(cx, cy, FACE - 6), words)) return true;
      for (let i = 0; i < n; i++) {
        const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
        const mx = cx + Math.cos(a) * R, my = cy + Math.sin(a) * R;
        if (hit(disk(mx, my, MOON), passages)) return true;
        if (wordsToo && hit(disk(mx, my, MOON - 2), words)) return true;
      }
      return false;
    };
    const clear = (cx, cy, R) => !blocked(cx, cy, R, true);
    const pack = (cx, cy, R) => ({
      x: cx, y: cy, r: R,
      moons: Array.from({ length: n }, (_, i) => {
        const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
        return [cx + Math.cos(a) * R, cy + Math.sin(a) * R];
      }),
      angles: Array.from({ length: n }, (_, i) => -Math.PI / 2 + (i * 2 * Math.PI) / n),
    });
    const radii = [124, 116, 108, 100, 92];
    const seeds = [[hintX, hintY]];
    if (passages.length) {
      const top = Math.min(...passages.map((r) => r.top));
      const bot = Math.max(...passages.map((r) => r.bottom));
      const mid = passages.reduce((s, r) => s + (r.left + r.right) / 2, 0) / passages.length;
      const side = passages.reduce((s, r) => s + r.left, 0) / passages.length;
      for (const R of radii) {
        seeds.push([mid, top - R - MOON - 16], [mid, bot + R + MOON + 16]);
        seeds.push([side - R - MOON - 16, (top + bot) / 2], [passages.reduce((s, r) => Math.max(s, r.right), 0) + R + MOON + 16, (top + bot) / 2]);
      }
    }
    const scan = (wordsToo) => {
      const near = [...seeds].sort((a, b) => Math.hypot(a[0] - hintX, a[1] - hintY) - Math.hypot(b[0] - hintX, b[1] - hintY));
      for (const [sx, sy] of near) {
        for (const R of radii) if (!blocked(sx, sy, R, wordsToo)) return pack(sx, sy, R);
      }
      for (let ring = 1; ring <= 12; ring++) {
        for (let k = 0; k < 16; k++) {
          const a = (k / 16) * Math.PI * 2;
          const cx = hintX + Math.cos(a) * ring * 32, cy = hintY + Math.sin(a) * ring * 32;
          for (const R of radii) if (!blocked(cx, cy, R, wordsToo)) return pack(cx, cy, R);
        }
      }
      return null;
    };
    const found = scan(true) || scan(false);
    if (found) return found;
    const top = passages.length ? Math.min(...passages.map((r) => r.top)) : hintY;
    const cx = Math.max(L + FACE + 40, Math.min(Rgt - FACE - 40, hintX));
    const cy = Math.max(T + FACE + 40, Math.min(top - 120, B - FACE - 40));
    const room = Math.min(cx - L, Rgt - cx, cy - T, B - cy) - MOON - 46;
    return pack(cx, cy, Math.max(72, Math.min(84, room)));
  }

  /** options({ x, y, items:[{ key, label, icon, color, disabled }], caption }) -> the key picked, or null.
      Dot grows to the large face and the tools sit as equal moons around it. They ease out of the face.
      Escape, Back or a click outside folds them in. `caption` is a short line under Dot. */
  function options({ x, y, items, angle = -Math.PI / 2, places = null, labelsRight = true, caption = "" }) {
    closeTools();
    if (x == null) [x, y] = centre();
    void angle; void places; void labelsRight;
    const spot = moonSpot(x, y, items.length);
    const faceEl = root.querySelector(".buddy-face");
    root.classList.add("attached");
    root.style.transition = "none";
    faceEl.style.transition = "none"; // grow to 92px before centring, or the ring slips off the eyes
    void faceEl.offsetWidth;
    place(spot.x, spot.y);
    void faceEl.offsetWidth;
    root.style.transition = "";
    faceEl.style.transition = "";
    x = spot.x; y = spot.y;
    st.ui += 1;
    const wrap = document.createElement("div");
    wrap.className = "buddy-opts ring";
    wrap.dataset.radius = String(Math.round(spot.r));
    wrap.setAttribute("role", "menu"); wrap.setAttribute("aria-label", "Dot's tools");
    const cap = document.createElement("p");
    cap.className = "ob-cap"; cap.textContent = caption; cap.hidden = !caption; cap.setAttribute("aria-live", "polite");
    cap.style.cssText = `left:${x}px;top:${y + 70}px`;
    wrap.style.cssText = "left:0;top:0";
    const n = items.length;
    const at = (i) => spot.moons[i];
    let over = false, resolve;
    const result = new Promise((r) => { resolve = r; });
    wrap.addEventListener("wheel", (e) => {
      const stage = document.querySelector(".pdf-stage");
      if (!stage) return;
      stage.scrollTop += e.deltaY; stage.scrollLeft += e.deltaX;
    }, { passive: true });
    const orbs = items.map((it, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "menuitem"); b.setAttribute("aria-label", it.label); b.disabled = !!it.disabled;
      b.className = `obuddy ob-${it.key}`; b.style.setProperty("--bc", it.color || "#ffe347"); b.style.setProperty("--i", i);
      b.innerHTML = `<span class="bod"><span class="who" aria-hidden="true"><i></i><i></i></span><span class="scene" aria-hidden="true"><span class="prop"></span><span class="mx"></span></span></span><span class="tag"><b></b><small></small></span>`;
      b.querySelector(".tag b").textContent = it.label;
      b.querySelector(".tag small").textContent = it.hint || "";
      const [sx, sy] = at(i);
      b.style.transform = reduced() ? `translate3d(${sx}px, ${sy}px, 0)` : `translate3d(${x}px, ${y}px, 0) scale(.2)`;
      b.addEventListener("mousedown", (e) => e.preventDefault()); // keep the chosen words selected
      b.addEventListener("click", (e) => { e.stopPropagation(); finish(it.key); });
      wrap.append(b); return b;
    });
    wrap.append(cap);
    document.body.append(wrap);
    void wrap.offsetWidth;
    const pose = (i, px, py) => `translate3d(${px}px, ${py}px, 0)`;
    orbs.forEach((b, i) => {
      const [px, py] = at(i);
      const ux = Math.cos(spot.angles[i]), uy = Math.sin(spot.angles[i]);
      b.style.setProperty("--lx", `${Math.round(ux * 48)}px`);
      b.style.setProperty("--ly", `${Math.round(uy * 48)}px`);
      b.style.transition = "none";
      b.style.transform = pose(i, px, py);
    });
    void wrap.offsetWidth;
    nudgeMoonNames(orbs, spot.angles);
    if (!reduced()) {
      orbs.forEach((b, i) => { b.style.transform = `translate3d(${x}px, ${y}px, 0) scale(.2)`; });
      void wrap.offsetWidth;
    }
    orbs.forEach((b, i) => {
      const [px, py] = at(i);
      b.style.transition = reduced() ? "none" : "transform .55s cubic-bezier(.22,1,.36,1), opacity .25s";
      b.style.transitionDelay = reduced() ? "0s" : `${i * 45}ms`;
      b.style.transform = pose(i, px, py);
      b.classList.add("on");
    });
    (orbs.find((b) => !b.disabled) ?? orbs[0])?.focus({ preventScroll: true });
    const finish = (key) => {
      if (over) return; over = true;
      document.removeEventListener("keydown", onKey, true); document.removeEventListener("pointerdown", onOut, true);
      st.ui = Math.max(0, st.ui - 1);
      const [cx, cy] = centre();
      orbs.forEach((b, i) => {
        const picked = items[i].key === key;
        b.disabled = true; b.classList.remove("on"); b.style.transitionDelay = reduced() ? "0s" : picked ? "0s" : `${(n - i) * 20}ms`;
        if (reduced()) b.style.transition = "none";
        b.style.transform = `translate3d(${cx}px, ${cy}px, 0) scale(.2)`; // each one is taken back into Dot
      });
      cap.hidden = true;
      if (key && !reduced()) gulp().then(() => burp()); // Dot opens wide for the one it takes, then settles
      setTimeout(() => { wrap.remove(); if (!document.querySelector(".buddy-opts")) root.classList.remove("attached"); }, reduced() ? 0 : 520);
      resolve(key ?? null);
    };
    const onKey = (e) => {
      const live = orbs.filter((b) => !b.disabled), i = live.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(null); }
      else if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); live[(i + 1) % live.length]?.focus(); }
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); live[(i - 1 + live.length) % live.length]?.focus(); }
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
    el.addEventListener("wheel", (e) => {
      const stage = document.querySelector(".pdf-stage");
      if (!stage) return;
      stage.scrollTop += e.deltaY; stage.scrollLeft += e.deltaX;
    }, { passive: true });
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
    follow: followMode, look, tagAlong, options, shape, prompt, gulp, burp, toolsOn, skip, centre, put, hold, nudge, wait: waitSkippable };
})();
