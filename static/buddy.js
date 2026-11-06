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

  const st = { mood: "idle", dx: 0, dy: 0, blink: false, talkFrame: 0, talking: false,
    muted: localStorage.getItem("buddy-muted") === "1", last: null };

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
    const m = MOODS[st.mood];
    const dx = m.dx ?? st.dx, dy = m.dy ?? st.dy;
    const eyes = st.blink && m.eyes !== "closed" ? "closed" : m.eyes;
    const mouth = st.talking ? (st.talkFrame ? "o" : "talk") : m.mouth;
    const on = new Set([...EYES[eyes](dx, dy), ...MOUTHS[mouth]].map(([x, y]) => y * W + x));
    dots.forEach((d, i) => d.classList.toggle("on", on.has(i)));
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
      if (!reduced() && Date.now() - lastMouse > 3000 && st.mood !== "sleep") {
        st.dx = [-1, 0, 0, 1][Math.floor(Math.random() * 4)]; st.dy = 0; draw();
      }
      scheduleGlance();
    }, 4000 + Math.random() * 4000);
  }
  let raf = 0;
  document.addEventListener("mousemove", (e) => {
    lastMouse = Date.now();
    if (raf || reduced()) return;
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
    "Write it in your own words first. Open the primer after.",
    "Wrong notes are fine. You fix them in the check. Copied notes teach you nothing.",
    "Stuck? Write down the exact sentence you do not understand, and move on.",
    "Read the figures before the text. They often tell the whole story.",
    "A short break between steps helps you remember more.",
  ];
  face.addEventListener("click", () => {
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
  function mood(m) { if (bubble.hidden) { st.mood = m; draw(); } }

  document.body.append(root);
  setMuted(st.muted);
  if (st.muted) st.mood = "sleep";
  draw(); scheduleBlink(); scheduleGlance();
  return { say, hide, status, mood };
})();
