"use strict";
// ---------- Reader: PDF viewer, notebook, autosave, step timer ----------
// Plain script loaded before app.js. It uses app.js helpers (h, api, $, view, greeted) at call time.

const PDFJS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/";
if (window.pdfjsLib) pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS_CDN}pdf.worker.min.js`;
// shortcut: the Timer setting arrives in phase 8; read it from /settings then.
const TIMER_AUTOSTART = false;
const SAVE_DELAY = 500;
const TIMER_SAVE_EVERY = 15; // seconds between saves while the timer runs
const STATE_LABEL = { empty: "not started", partial: "started", done: "done" };

// The open Reader. Registered before app.js's router, so it runs before the next page draws.
let openReader = null;
window.addEventListener("hashchange", () => { openReader?.leave(); openReader = null; });
window.addEventListener("pagehide", () => openReader?.flushOnExit());
// Mobile browsers may close a hidden tab without pagehide, so send the notes when the tab hides.
document.addEventListener("visibilitychange", () => { if (document.hidden) openReader?.flushOnExit(); });

async function renderReader(paperId, startPage) {
  const [paper, saved] = await Promise.all([api(`/papers/${paperId}?open=true`).catch(() => null),
    api(`/papers/${paperId}/notes`).catch(() => null)]);
  const [fw, aiData, cfg, checks] = await Promise.all([api(`/framework?template=${paper?.template ?? "paper"}`),
    api(`/papers/${paperId}/primer`).catch(() => null), api("/settings").catch(() => ({})),
    api(`/papers/${paperId}/checks`).catch(() => ({ steps: {} }))]);
  if (!paper || !saved) {
    view.className = "page page-library";
    view.append(h("div", { class: "library" }, h("h1", {}, "Paper not found"),
      h("p", { class: "quiet" }, "This paper is not in the library. It may have been deleted. ",
        h("a", { href: "#library" }, "Go to the Library"), ".")));
    return;
  }
  const notes = Object.fromEntries(fw.steps.map((st) => [st.id, noteFor(st, saved.steps[st.id])]));
  let current = fw.steps.find((st) => notes[st.id].state !== "done") ?? fw.steps[0];

  const done = h("span", { class: "num" }, `${saved.steps_done}/${fw.steps.length}`);
  const stepsChip = h("button", { type: "button", class: "dchip", "aria-expanded": "false", onclick: () => drawers.toggle("steps") }, "Steps ", done);
  const notesChip = h("button", { type: "button", class: "dchip", "aria-expanded": "false", onclick: () => drawers.toggle("notes") }, "Notes");
  const hideBtn = h("button", { class: "btn ghost", type: "button", "aria-pressed": "false",
    onclick: () => pdf.setHidden(!pdf.hidden()) }, "Hide paper");
  $("#page-extra").append(
    h("a", { href: "#library", class: "paper-title", title: "Back to the Library" }, paper.title),
    hideBtn,
    h("details", { class: "menu" },
      h("summary", {}, "Export"),
      h("div", { class: "menu-list" },
        h("button", { type: "button", onclick: () => exportDialog(paper, "markdown", () => queue.flush()) }, "Export Markdown"),
        h("button", { type: "button", onclick: () => exportDialog(paper, "reflection", () => queue.flush()) }, "Export reflection outline"))),
    h("div", { class: "dchip-group" }, stepsChip, notesChip));

  const status = h("span", { class: "save-status", role: "status" });
  const queue = saveQueue(paperId, notes, status, (id, r) => {
    const was = notes[id].state;
    notes[id].state = r.state;
    done.textContent = `${r.steps_done}/${r.total_steps}`;
    rail.paint(id);
    if (r.state === "done" && was !== "done" && openReader === me) {
      const st = fw.steps.find((x) => x.id === id);
      buddy.say(`Step ${st.n}, ${st.title}, is done. Nice work.`, { mood: "happy" });
    }
  });
  const pdf = pdfViewer(`/papers/${paperId}/pdf`, hideBtn, paperId, Number(startPage) || 1,
    ({ quote, question, answer }) => plain.append([`Marked: "${quote}"`, question && `Q: ${question}`, `AI: ${answer}`].filter(Boolean).join("\n")));
  const rail = stepRail(fw, notes, (st) => open(st));
  const timer = stepTimer(() => notes[current.id], () => queue.touch(current.id));
  const body = h("div", { class: "nb-body" });
  const back = h("button", { type: "button", class: "btn ghost", onclick: () => open(fw.steps[idx() - 1]) }, "Back");
  const next = h("button", { type: "button", class: "btn", onclick: () => open(fw.steps[idx() + 1]) }, "Next step");
  const idx = () => fw.steps.indexOf(current);

  // AI summary: what the model wrote for each step before you read, and the job that makes it
  const ai = { data: aiData ?? { steps: {}, progress: { state: "not_made" } }, mode: cfg.primer_panel ?? "after_writing",
    go: (n) => pdf.go(n), live: null,
    checks: checks.steps, hints: cfg.checker_hints !== false,
    async check(st) { // send the last keystrokes first; the server checks what is saved
      await queue.flush();
      return api(`/papers/${paperId}/check/${st.id}`, { method: "POST" })
        .catch((e) => ({ ok: false, error: e.body?.detail?.errors?.step_id || "Could not reach the app. Is it still running?" }));
    },
    async make() {
      ai.live = ai.live ?? streamPrimer(paperId, (e) => { ai.data.progress = e; ai.paint?.(); }).then(async () => {
        ai.data = (await api(`/papers/${paperId}/primer`).catch(() => null)) ?? ai.data;
        ai.live = null;
        if (openReader === me) open(current, false);
      });
      ai.paint?.();
    } };

  function open(st, pop = true) {
    timer.stop();
    queue.flush(); // the notes live in memory; this sends the last keystrokes now instead of in 500 ms
    current = st;
    rail.mark(st.id);
    pdf.autoHide(st.paper_hidden);
    canvasHost.hidden = !!st.paper_hidden; canvas.lock(!!st.paper_hidden); // Self-test: the canvas goes with the paper
    body.replaceChildren(...notebook(st, notes[st.id], timer, () => queue.touch(st.id), ai));
    body.querySelectorAll("textarea").forEach(grow);
    body.scrollTop = 0;
    [...body.children].forEach((el, i) => el.style.setProperty("--i", i)); // staggered entrance
    back.disabled = idx() === 0;
    next.disabled = idx() === fw.steps.length - 1;
    if (TIMER_AUTOSTART) timer.start();
    stepTip(st, pop);
  }

  // Steps (the template) live in a drawer on the left; one plain note per paper in a drawer on the right,
  // where "@ai question" asks the local model. Only the paper shows until you ask for one.
  const foot = h("footer", { class: "nb-foot" }, back, status, next);
  const plain = plainNote(paperId, () => pdf.page());
  plain.el.hidden = false;
  const drawers = readerDrawers({
    steps: { side: "left", label: "Steps", chip: stepsChip, onClose: () => queue.flush(),
      content: h("div", { class: "drawer-steps" }, rail.el, h("section", { class: "notebook", "aria-label": "Step notes" }, body, foot)) },
    notes: { side: "right", label: "Notes", chip: notesChip, onOpen: () => plain.show(), onClose: () => plain.flush(),
      content: h("section", { class: "notebook", "aria-label": "Notes" }, plain.el) },
  });
  const canvasHost = h("section", { class: "canvas-host", "aria-label": "Canvas" });
  view.append(pdf.el, canvasHost, drawers.steps.el, drawers.notes.el);
  const canvas = canvasPanel(canvasHost, paperId, pdf);
  const guide = guidedReading(paperId, pdf, (id) => { const st = fw.steps.find((x) => x.id === id); if (st && st !== current) open(st, false); },
    () => drawers.open("notes"));
  const dotTools = () => buddy.tools([
    { name: "Lens", hint: "Highlight words, I explain", pick: () => pdf.lens(),
      pic: ["..###....", ".#...#...", "#.....#..", "#.....#..", "#.....#..", ".#...#...", "..###.#..", ".......#.", "........#"] },
    { name: "Map", hint: "I guide you through the paper", pick: () => guide.start(),
      pic: ["......##.", ".....#..#", ".....#..#", "......##.", ".......#.", "...#.....", "..#......", ".#.......", "#........"] },
    { name: pdf.watching() ? "Proactive: on" : "Proactive", hint: pdf.watching() ? "Turn off check-ins" : "I check in if you get stuck",
      pick: () => { pdf.watch(!pdf.watching()); dotTools(); },
      pic: [".........", "..#####..", ".#.....#.", "#..###..#", "#..###..#", "#..###..#", ".#.....#.", "..#####..", "........."] },
    { name: "Canvas", hint: "Open or put away your cards", pick: () => (canvasHost.hidden ? buddy.say("The paper is closed for this step, so the canvas is too.") : canvas.toggle()),
      pic: ["####.....", "#..#.....", "####.....", "...#.....", "...##....", "....#####", ".....#..#", ".....#..#", ".....####"] },
    ...(pdf.watching() ? [{ name: "Clear trail", hint: "Forget which parts you read", pick: () => pdf.clearTrail(),
      pic: [".........", "#.......#", ".#.....#.", "..#...#..", "...#.#...", "..#...#..", ".#.....#.", "#.......#", "........."] }] : []),
  ]);
  dotTools();
  open(current, !greeted.has("reader")); greeted.add("reader");
  if (ai.data.progress.state === "making") ai.make(); // it was started elsewhere; follow it here
  buddy.follow(true); buddy.toolsOn("context"); // reading mode: Dot trails the pointer; right-click it for its tools

  // Saves (and retries) can finish after you leave; Dot only speaks while this Reader is open.
  const me = openReader = {
    leave() { guide.stop(); timer.stop(); queue.flush(); plain.flush(); drawers.destroy(); canvas.destroy(); buddy.follow(false); buddy.toolsOn("click"); pdf.destroy(); },
    flushOnExit() { queue.flushKeepalive(); plain.flush(true); },
  };
}

// Steps and Notes are drawers over the paper's edges. One is open at a time; Escape or a click outside closes it.
function readerDrawers(defs) {
  const out = {};
  for (const [key, d] of Object.entries(defs)) {
    const el = h("aside", { class: `drawer drawer-${d.side}`, "aria-label": d.label }, d.content);
    el.inert = true;
    out[key] = { el, d, isOpen: () => el.classList.contains("open") };
  }
  const set = (key, on) => {
    const x = out[key];
    if (x.isOpen() === on) return;
    x.el.classList.toggle("open", on); x.el.inert = !on;
    x.d.chip.setAttribute("aria-expanded", String(on));
    if (on) x.d.onOpen?.(); else x.d.onClose?.();
  };
  const open = (key) => { Object.keys(out).forEach((k) => k !== key && set(k, false)); set(key, true); };
  const closeAll = () => Object.keys(out).forEach((k) => set(k, false));
  const onKey = (e) => {
    if (e.key !== "Escape" || document.querySelector(".dot-win, .buddy-opts, .buddy-pill")) return;
    if (Object.values(out).some((x) => x.isOpen())) { closeAll(); e.stopPropagation(); }
  };
  const onDown = (e) => {
    if (e.target.closest?.(".drawer, .dchip, .buddy, .buddy-opts, .buddy-pill, .dot-win")) return;
    closeAll();
  };
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("pointerdown", onDown, true);
  return { ...out, open, closeAll, toggle: (key) => (out[key].isOpen() ? set(key, false) : open(key)),
    destroy() { document.removeEventListener("keydown", onKey, true); document.removeEventListener("pointerdown", onDown, true); } };
}

// Guided reading: with only the paper showing, Dot offers to take you to each part to read for each step,
// hovers beside its heading and tells you what to look for. The places come from the paper's own headings.
function guidedReading(paperId, pdf, onStep, openNotes) {
  let stops = null, i = 0, live = 0, offered = false, on = false;
  const label = h("p", { class: "gd-count num" });
  const what = h("p", { class: "gd-step" });
  const where = h("p", { class: "gd-where" });
  const look = h("ul", { class: "gd-look" });
  const back = h("button", { type: "button", class: "btn ghost small-btn", onclick: () => show(i - 1) }, "Back");
  const next = h("button", { type: "button", class: "btn small-btn", onclick: () => show(i + 1) });
  const card = h("section", { class: "guide-card", hidden: true, "aria-label": "Guided reading", "aria-live": "polite" },
    h("div", { class: "gd-top" }, h("span", { class: "buddy-name" }, "Dot guides"), label,
      h("button", { type: "button", class: "buddy-x", "aria-label": "Stop guided reading", onclick: () => stop() }, "×")),
    what, where, look, h("div", { class: "gd-actions" }, back, next));
  pdf.el.append(card);
  buddy.draggable(card, card.querySelector(".gd-top"));
  const onKey = (e) => { if (e.key === "Escape" && on && !document.querySelector(".dot-win")) stop(); };

  function offer() {
    if (offered || on) return;
    offered = true;
    buddy.say("Just the paper now. Want me to guide you? I will take you to each part to read and tell you what to look for.",
      { mood: "happy", actions: [{ label: "Guide me", onClick: start }, { label: "Not now" }] });
  }
  async function start() {
    stops = stops ?? (await api(`/papers/${paperId}/guide`).catch(() => ({ stops: [] }))).stops;
    if (!stops.length) return buddy.say("I could not find the parts of this paper to guide you through.", { mood: "worried" });
    on = true; card.hidden = false;
    document.addEventListener("keydown", onKey);
    show(0);
  }
  async function show(k) {
    if (k >= stops.length) return finish();
    i = Math.max(0, k);
    const s = stops[i], my = ++live;
    label.textContent = `${i + 1} of ${stops.length}`;
    what.textContent = `Step ${s.n}, ${s.title}. About ${s.minutes} ${s.minutes === 1 ? "minute" : "minutes"}.`;
    look.replaceChildren(...s.look_for.map((q) => h("li", {}, q)));
    back.disabled = i === 0;
    next.textContent = i === stops.length - 1 ? "Finish" : "Next";
    onStep(s.step_id);
    const r = await pdf.point(s.heading, s.page);
    if (my !== live || !on) return;
    where.textContent = r.found ? `Read "${s.heading}" on page ${s.page}.` : `Read page ${s.page}. Look for the ${s.look_in.slice(0, 2).join(" or ")}.`;
    const stage = pdf.el.querySelector(".pdf-stage").getBoundingClientRect();
    const left = r.left - 64 > stage.left + 30; // hover in the margin left of the heading (clear of its number), or else to its right
    await buddy.goTo(left ? r.left - 64 : Math.min(r.left + r.w + 50, stage.right - 40), r.top + r.h / 2);
    if (my === live && on) buddy.lookAt(r.left + r.w / 2, r.top + r.h / 2, 4000);
  }
  function finish() {
    stop();
    buddy.say("That is every part. Now write it down in your own words, step by step.",
      { mood: "happy", actions: [{ label: "Open my notes", onClick: openNotes }] });
  }
  function stop() {
    if (!on) return;
    on = false; live += 1; card.hidden = true; pdf.unmark();
    document.removeEventListener("keydown", onKey);
    buddy.goHome();
  }
  return { offer, stop, start: () => (on ? show(i) : start()) };
}

// One free page of notes per paper. A line that starts with @ai, ended with Enter, asks the local model
// about this paper; the answer is written into the note under the question.
function plainNote(paperId, page) {
  const url = `/papers/${paperId}/note`;
  const ta = h("textarea", { class: "plain-text", "aria-label": "Note",
    placeholder: "Write your notes here." });
  const status = h("span", { class: "save-status", role: "status" });
  const el = h("div", { class: "plain", hidden: true },
    ta, h("div", { class: "plain-foot" },
      h("p", { class: "plain-hint" }, "Start a line with ", h("b", {}, "@ai"), " and press Enter to ask about this paper."), status));
  let loaded = false, dirty = false, t = 0;
  const say = (text, cls = "") => { status.textContent = text; status.className = `save-status ${cls}`; };

  async function flush(keepalive = false) {
    clearTimeout(t);
    if (!dirty) return;
    dirty = false;
    const req = { method: "PUT", body: JSON.stringify({ text: ta.value }) };
    if (keepalive) { fetch(url, { ...req, keepalive: true, headers: { "Content-Type": "application/json" } }); return; }
    try { await api(url, req); say("Saved"); } catch { dirty = true; say("Not saved. Retrying when you type.", "err"); }
  }
  const changed = () => { dirty = true; say("Saving"); clearTimeout(t); t = setTimeout(flush, SAVE_DELAY); grow(ta); };

  async function askAi(question) {
    const mark = `AI is reading the paper (${Date.now()})`;
    const at = ta.selectionStart;
    ta.setRangeText(`\n${mark}\n`, at, at, "end");
    changed();
    const r = await api(`/papers/${paperId}/ask`, { method: "POST", body: JSON.stringify({ question, page: page() }) })
      .catch(() => ({ ok: false, error: "Could not ask the model. Is the app still running?" }));
    const answer = r.ok ? `AI: ${r.text}` : `AI could not answer: ${r.error}`;
    const i = ta.value.indexOf(mark);
    if (i >= 0) ta.setRangeText(answer, i, i + mark.length, "preserve");
    else ta.value += `\n${answer}\n`;
    changed();
  }

  ta.addEventListener("input", changed);
  ta.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    const start = ta.value.lastIndexOf("\n", ta.selectionStart - 1) + 1;
    const m = ta.value.slice(start, ta.selectionStart).match(/^\s*@ai\b[:,]?\s*(.+)$/i);
    if (!m) return;
    e.preventDefault();
    askAi(m[1].trim());
  });

  return {
    el, flush,
    /** Add text at the end of the note (loading it first), and save. */
    async append(text) {
      if (!loaded) { loaded = true; const r = await api(url).catch(() => null); if (r && !dirty) ta.value = r.text; }
      ta.value = `${ta.value.replace(/\s*$/, "")}${ta.value.trim() ? "\n\n" : ""}${text}\n`;
      changed(); await flush();
      return !dirty;
    },
    async show() {
      if (!loaded) {
        loaded = true;
        const r = await api(url).catch(() => null);
        if (r && !dirty) ta.value = r.text;
      }
      grow(ta); ta.focus();
    },
  };
}

function noteFor(st, s) {
  return { fields: { ...s?.fields }, gate: st.gate.map((_, i) => s?.gate?.[i] === true),
    seconds: s?.seconds ?? 0, state: s?.state ?? "empty" };
}

function stepTip(st, pop) {
  const parts = [`Step ${st.n}, ${st.title}. You have ${st.minutes} ${st.minutes === 1 ? "minute" : "minutes"}.`];
  if (st.paper_hidden) parts.push("Close the paper and explain it out loud, as if to a friend.");
  else if (st.look_in.length) parts.push(`Look in the ${st.look_in.join(", ")}.`);
  if (st.gate.length) parts.push(`Before you move on: ${st.gate[0]}`);
  buddy.say(parts.join(" "), { mood: st.paper_hidden ? "think" : "idle", pop });
}

// ---------- rail ----------
// Line icons, 24 grid, drawn by hand. Stroke and caps come from CSS (.ico svg).
const ICONS = {
  card: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 10h8M8 14h5"/>',
  first: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.5"/>',
  problem: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1.1.9-1.1 1.6v.3M12 16.7v.1"/>',
  gap: '<path d="M3 12h4.5M16.5 12H21M7.5 7.5v9M16.5 7.5v9M12 12h.01"/>',
  method: '<path d="M9 3.5h6M10 3.5V9l-5 9.3a1.5 1.5 0 0 0 1.3 2.2h11.4a1.5 1.5 0 0 0 1.3-2.2L14 9V3.5M7.4 14.5h9.2"/>',
  results: '<path d="M4 20h16M7.5 16.5v-4M12 16.5v-9M16.5 16.5v-6"/>',
  limits: '<path d="M12 4.5 20.5 19.5h-17z"/><path d="M12 10.5v4M12 17v.01"/>',
  impact: '<circle cx="12" cy="12" r="2.5"/><path d="M12 3.5V6M12 18v2.5M3.5 12H6M18 12h2.5M6 6l1.8 1.8M16.2 16.2 18 18M6 18l1.8-1.8M16.2 7.8 18 6"/>',
  selftest: '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 16h-8l-4.5 3.5V16H5a1.5 1.5 0 0 1-1.5-1.5v-8A1.5 1.5 0 0 1 5 5z"/><path d="M8 9.5h8M8 12.5h5"/>',
  questions: '<path d="M9.5 17.5h5M10.5 20.5h3M12 3.5a6 6 0 0 0-3.4 10.9c.4.3.6.7.6 1.2v.4h5.6v-.4c0-.5.2-.9.6-1.2A6 6 0 0 0 12 3.5z"/>',
  review: '<path d="M4.5 12a7.5 7.5 0 0 1 13-5.1M19.5 12a7.5 7.5 0 0 1-13 5.1"/><path d="M17.5 3.5v3.4h-3.4M6.5 20.5v-3.4h3.4"/>',
  check: '<path pathLength="1" d="M6.5 12.5l3.6 3.6L17.5 8.5"/>',
  prev: '<path d="M14.5 6 8.5 12l6 6"/>',
  next: '<path d="M9.5 6l6 6-6 6"/>',
  minus: '<path d="M6 12h12"/>',
  plus: '<path d="M12 6v12M6 12h12"/>',
  fit: '<path d="M3.5 12h17M7 8.5 3.5 12 7 15.5M17 8.5l3.5 3.5-3.5 3.5"/>',
};
function icon(name, cls = "ico") {
  const s = h("span", { class: cls, "aria-hidden": "true" });
  s.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none">${ICONS[name] ?? '<circle cx="12" cy="12" r="3"/>'}</svg>`;
  return s;
}

function stepRail(fw, notes, onPick) {
  const total = fw.steps.length;
  const planned = fw.steps.reduce((a, st) => a + st.minutes, 0);
  const ringArc = h("span", { class: "rail-ring", "aria-hidden": "true" });
  ringArc.innerHTML = '<svg viewBox="0 0 36 36" width="36" height="36"><circle cx="18" cy="18" r="15" pathLength="100"/><circle class="arc" cx="18" cy="18" r="15" pathLength="100"/></svg>';
  const count = h("span", { class: "num" });
  const head = h("div", { class: "rail-head" }, ringArc,
    h("span", { class: "rail-sum" }, h("span", { class: "rail-count" }, count),
      h("span", { class: "rail-plan num" }, `${planned} min planned`)));
  const glide = h("li", { class: "rail-glide", "aria-hidden": "true" });
  const list = h("ol", { class: "rail-steps", "aria-label": "Reading steps" }, glide);
  const el = h("div", { class: "rail" }, head, list);
  const items = {};
  fw.steps.forEach((st, i) => {
    const circle = h("span", { class: "circle" }, icon(st.id), icon("check", "ico chk"));
    const btn = h("button", { type: "button", onclick: () => onPick(st) }, circle,
      h("span", { class: "txt" }, h("span", { class: "label" }, st.title),
        h("span", { class: "sub num" }, `Step ${st.n}`, h("span", { class: "mins" }, ` · ${st.minutes} min`))));
    items[st.id] = { st, btn, circle, li: h("li", { class: "step", style: `--i:${i}` }, btn) };
    list.append(items[st.id].li);
  });
  list.append(h("li", { class: "divider", "aria-hidden": "true" }),
    h("li", { class: "later", style: `--i:${total}` }, h("button", { type: "button", disabled: true, title: "Comes in a later phase" },
      h("span", { class: "circle" }, icon("review")),
      h("span", { class: "txt" }, h("span", { class: "label" }, "Review"), h("span", { class: "sub" }, "Comes later")))));
  const paint = (id) => {
    const { st, btn, circle, li } = items[id];
    circle.className = `circle ${notes[id].state}`;
    li.dataset.state = notes[id].state;
    btn.setAttribute("aria-label", `Step ${st.n}, ${st.title}, ${st.minutes} minutes, ${STATE_LABEL[notes[id].state]}`);
    const n = fw.steps.filter((x) => notes[x.id].state === "done").length;
    count.textContent = `${n} of ${total} done`;
    ringArc.style.setProperty("--off", 100 - (n / total) * 100);
  };
  let activeBtn = null;
  // the sheet behind the active step glides to it
  const place = () => {
    if (!activeBtn) return;
    const li = activeBtn.parentElement; // offsets ignore the entrance slide, so the sheet lands where the step ends up
    glide.style.cssText = `--x:${li.offsetLeft + activeBtn.offsetLeft}px;--y:${li.offsetTop + activeBtn.offsetTop}px;width:${activeBtn.offsetWidth}px;height:${activeBtn.offsetHeight}px`;
  };
  new ResizeObserver(place).observe(list);
  const mark = (id) => {
    Object.values(items).forEach(({ st, btn }) => {
      btn.classList.toggle("active", st.id === id);
      if (st.id === id) { activeBtn = btn; btn.setAttribute("aria-current", "step"); btn.scrollIntoView?.({ block: "nearest", inline: "nearest" }); }
      else btn.removeAttribute("aria-current");
    });
    place();
    requestAnimationFrame(() => el.classList.add("ready")); // no glide on the first placement
  };
  Object.keys(items).forEach(paint);
  return { el, paint, mark };
}

// ---------- save queue ----------
// One request at a time. Edits made while a save runs are sent right after it.
function saveQueue(paperId, notes, statusEl, onSaved) {
  const dirty = new Set();
  let wait = null, retry = null, busy = false;
  const url = (id) => `/papers/${paperId}/notes/${id}`;
  const body = (id) => JSON.stringify({ fields: notes[id].fields, gate: notes[id].gate, seconds: notes[id].seconds });
  const show = (text, cls = "") => { statusEl.textContent = text; statusEl.className = `save-status ${cls}`; };

  function touch(id) {
    dirty.add(id); show("Saving");
    clearTimeout(wait); wait = setTimeout(flush, SAVE_DELAY);
  }
  async function flush() {
    clearTimeout(wait); clearTimeout(retry);
    if (busy || !dirty.size) return;
    busy = true;
    try {
      while (dirty.size) {
        // The step stays dirty until its PUT succeeds, so a keepalive send on exit still includes it.
        const id = dirty.values().next().value;
        const sent = body(id);
        try {
          const r = await api(url(id), { method: "PUT", body: sent });
          if (body(id) === sent) dirty.delete(id); // edited meanwhile: the loop sends it again
          onSaved(id, r);
        } catch (e) {
          if (e.status >= 400 && e.status < 500) {
            // retrying the same notes would fail again; the next edit tries again
            const msg = Object.values(e.body?.detail?.errors ?? {})[0];
            return show(`Could not save.${msg ? ` ${msg}` : ""}`, "err");
          }
          show("Could not save. Retrying.", "err");
          retry = setTimeout(flush, 3000);
          return;
        }
      }
      show("Saved", "ok");
    } finally { busy = false; }
  }
  // Exit send: keepalive survives the page closing. The steps stay dirty and a normal save follows
  // (the same notes twice is harmless), so a failed keepalive or a tab that comes back still saves.
  function flushKeepalive() {
    if (!dirty.size) return;
    clearTimeout(wait);
    for (const id of dirty) {
      fetch(url(id), { method: "PUT", keepalive: true, headers: { "Content-Type": "application/json" }, body: body(id) }).catch(() => {});
    }
    wait = setTimeout(flush, 1000);
  }
  return { touch, flush, flushKeepalive };
}

// ---------- step timer ----------
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

function stepTimer(note, onSave) {
  let tick = null, paint = () => {};
  const start = () => {
    if (tick) return;
    tick = setInterval(() => {
      const n = note();
      n.seconds = Math.min(86400, n.seconds + 1);
      if (n.seconds % TIMER_SAVE_EVERY === 0) onSave();
      paint();
    }, 1000);
    paint();
  };
  const stop = () => {
    if (!tick) return;
    clearInterval(tick); tick = null;
    onSave(); paint();
  };
  return { start, stop, running: () => tick != null, onPaint: (fn) => { paint = fn; } };
}

function timerView(st, note, timer) {
  const budget = st.minutes * 60;
  const time = h("span", { class: "timer" });
  const fill = h("i", {});
  const bar = h("div", { class: "bar", "aria-hidden": "true" }, fill);
  const over = h("p", { class: "over-msg", hidden: true }, "Over the time budget. Finish the thought, then move on.");
  const btn = h("button", { type: "button", class: "btn ghost small-btn",
    onclick: () => (timer.running() ? timer.stop() : timer.start()) });
  const paint = () => {
    const s = note.seconds;
    time.textContent = `${mmss(s)} / ${String(st.minutes).padStart(2, "0")}:00`;
    fill.style.width = `${Math.min(100, (s / budget) * 100)}%`;
    bar.classList.toggle("over", s > budget);
    over.hidden = s <= budget;
    btn.textContent = timer.running() ? "Pause" : s ? "Resume" : "Start";
    time.classList.toggle("running", timer.running());
  };
  timer.onPaint(paint); paint();
  return h("div", { class: "budget" },
    h("div", { class: "row" }, h("span", {}, "Time budget"), h("span", { class: "timer-ctl" }, time, btn)),
    bar, over);
}

// ---------- notebook ----------
function notebook(st, note, timer, changed, ai) {
  const meter = writtenMeter(st, note);
  const set = (fid) => (value) => { note.fields[fid] = value; changed(); meter.paint(); };
  const where = st.paper_hidden
    ? h("span", { class: "look" }, "The paper stays closed for this step.")
    : st.look_in.length ? h("span", { class: "look" }, "Look in", st.look_in.map((x) => h("span", { class: "look-tag" }, x)))
    : h("span");
  return [
    h("div", { class: "step-head" },
      h("span", { class: "num n" }, `Step ${st.n}`),
      h("h2", { class: "step-title" }, h("span", { class: "hl swipe" }, st.title))),
    h("div", { class: "step-meta" }, where, meter.el),
    ai ? whereToLook(st, ai) : null,
    timerView(st, note, timer),
    ai ? aiSummary(st, note, ai) : null,
    ...st.fields.map((f) => fieldView(st, f, note.fields[f.id], set(f.id))),
    ai ? checkBar(st, ai) : null,
    gateView(st, note, changed),
    oldFields(st, note.fields),
  ].filter(Boolean);
}

// ---------- Checker: verdicts next to each field, hints under it ----------
const VERDICT = { correct: "Correct", partial: "Partial", wrong: "Wrong", missing: "Missing" };
const tally = (c) => Object.entries(c.fields.reduce((t, f) => ({ ...t, [f.verdict]: (t[f.verdict] ?? 0) + 1 }), {}))
  .map(([v, n]) => `${n} ${v}`).join(", ");

function checkBar(st, ai) {
  if (!AI_STEP(st)) return null;
  const box = h("section", { class: "chk-bar", "aria-label": "Check my notes" });
  const paint = () => {
    const list = ai.checks[st.id] ?? [], last = list[0];
    const btn = h("button", { type: "button", class: "btn", onclick: async () => {
      btn.disabled = true; btn.textContent = "Checking your notes";
      const r = await ai.check(st);
      if (r.ok) { (ai.checks[st.id] ??= []).unshift(r); paint(); buddy.react?.(r.fields.every((f) => f.verdict === "correct") ? "yes" : "no"); }
      else { paint(); box.append(h("p", { class: "status err" }, r.error)); }
    } }, last ? "Check again" : "Check my notes");
    box.replaceChildren(
      h("div", { class: "chk-row" }, btn,
        h("span", { class: "help" }, last ? `Checked ${ago(last.created_at).toLowerCase()}: ${tally(last)}.` : "Your model compares your notes with the paper and gives hints, not answers.")),
      last?.overall ? h("p", { class: "chk-overall" }, pageLinks(last.overall, ai.go)) : null,
      list.length > 1 ? h("details", { class: "chk-history" }, h("summary", {}, `Earlier checks (${list.length - 1})`),
        h("ol", {}, list.slice(1).map((c) => h("li", {}, h("span", {}, ago(c.created_at)), h("span", { class: "help" }, tally(c)))))) : null);
    queueMicrotask(() => verdicts(box.parentElement, last, ai));
  };
  paint();
  return box;
}

// put the latest verdict beside each field's label, and its hint under the field
function verdicts(root, check, ai) {
  if (!root) return;
  root.querySelectorAll(".chk-chip, .chk-hint").forEach((el) => el.remove());
  for (const f of check?.fields ?? []) {
    const wrap = root.querySelector(`[data-field="${CSS.escape(f.field_id)}"]`);
    if (!wrap) continue;
    wrap.querySelector(":scope > label, :scope > legend")?.append(h("span", { class: `chk-chip ${f.verdict}` }, VERDICT[f.verdict]));
    if (ai.hints && f.hint) wrap.append(h("p", { class: `chk-hint ${f.verdict}` }, pageLinks(f.hint, ai.go)));
  }
}

// ---------- AI summary in the notebook ----------
const AI_STEP = (st) => st.n >= 1 && st.n <= 7 && !st.paper_hidden && st.look_in.length > 0; // the steps the server summarises
// "[p. 4]", "p. 4" and "page 4" become buttons that turn the PDF to that page
function pageLinks(text, go) {
  const out = [];
  let at = 0;
  for (const m of text.matchAll(/\[p\.?\s*(\d+)\]|\bp\.\s*(\d+)\b|\bpages?\s+(\d+)\b/gi)) {
    const n = Number(m[1] ?? m[2] ?? m[3]);
    out.push(text.slice(at, m.index), h("button", { type: "button", class: "pg-link", title: `Show page ${n}`, onclick: () => go(n) }, `p. ${n}`));
    at = m.index + m[0].length;
  }
  out.push(text.slice(at));
  return out;
}

function whereToLook(st, ai) {
  const w = ai.data.steps[st.id]?.where_to_look;
  return w ? h("p", { class: "ai-where" }, h("span", { class: "ai-where-label" }, "Where to look"), " ", pageLinks(w, ai.go)) : null;
}

function aiSummary(st, note, ai) {
  if (!AI_STEP(st)) return null;
  const box = h("section", { class: "ai-sum", "aria-label": "AI summary" });
  const data = ai.data.steps[st.id];
  const paint = () => {
    const pr = ai.data.progress;
    if (data) return;
    const making = pr.state === "making";
    box.replaceChildren(
      h("p", { class: "ai-sum-title" }, "AI summary"),
      h("p", { class: "ai-sum-sub" }, making ? (pr.total ? `Your model is writing it: step ${Math.min(pr.done + 1, pr.total)} of ${pr.total}${pr.step ? `, ${pr.step}` : ""}.` : "Your model is starting.")
        : pr.state === "failed" && pr.error ? pr.error : "Your model can write a short summary of each step, with page links. It stays closed until you write your own notes."),
      making ? h("div", { class: "ai-bar" }, h("i", { style: `width:${pr.total ? (100 * pr.done) / pr.total : 4}%` }))
        : h("button", { type: "button", class: "btn ghost", onclick: () => ai.make() }, pr.state === "failed" ? "Try again" : "Make AI summary"));
  };
  if (!data) { ai.paint = paint; paint(); return box; }
  ai.paint = null;
  const locked = () => ai.mode === "after_writing" && !Object.values(note.fields).some(filled);
  const sub = h("span", { class: "ai-sum-sub" }, "Read your own first, then open");
  const det = h("details", { open: ai.mode === "open" },
    h("summary", { onclick: (e) => {
      if (!det.open && locked() && !det.dataset.anyway) {
        e.preventDefault();
        sub.replaceChildren("Try writing your own first. ",
          h("button", { type: "button", class: "linklike", onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); det.dataset.anyway = "1"; det.open = true; sub.textContent = "Read your own first, then open"; sub.classList.remove("warn"); } }, "Open anyway"));
        sub.classList.add("warn");
      }
    } }, h("span", { class: "ai-sum-title" }, "AI summary"), sub),
    h("div", { class: "ai-sum-body" }, st.fields.map((f) => {
      const x = data.fields.find((y) => y.field_id === f.id);
      if (!x) return null;
      const cited = /\[p\.?\s*\d+\]|\bp\.\s*\d+|\bpages?\s+\d+/i.test(x.summary);
      return h("div", { class: "ai-f" }, h("p", { class: "ai-f-label" }, f.label),
        h("p", { class: "ai-f-text" }, [pageLinks(x.summary, ai.go), !cited && x.pages?.length ? [" ", x.pages.length > 3 // a long list reads as a range
          ? [pageLinks(`[p. ${Math.min(...x.pages)}]`, ai.go), " to ", pageLinks(`[p. ${Math.max(...x.pages)}]`, ai.go)]
          : x.pages.map((n) => pageLinks(`[p. ${n}]`, ai.go))] : []].flat(4)));
    }).filter(Boolean)),
    h("p", { class: "help" }, "Written by the model on your Mac from this paper. Check it against the pages."));
  box.append(det);
  return box;
}

const filled = (v) => (typeof v === "string" ? !!v.trim() : Array.isArray(v) ? v.some(filled) : !!v);

// "2 of 5 written", with one dot per field.
function writtenMeter(st, note) {
  const dots = st.fields.map(() => h("i"));
  const label = h("span", { class: "num" });
  const el = h("span", { class: "written" }, h("span", { class: "written-dots", "aria-hidden": "true" }, dots), label);
  const paint = () => {
    const n = st.fields.filter((f) => filled(note.fields[f.id])).length;
    dots.forEach((d, i) => d.classList.toggle("on", i < n));
    label.textContent = `${n} of ${st.fields.length} written`;
    el.classList.toggle("all", n === st.fields.length);
  };
  paint();
  return { el, paint };
}

function grow(t) {
  t.style.height = "auto";
  t.style.height = `${t.scrollHeight + t.offsetHeight - t.clientHeight}px`;
}

const FIELDS = {
  text: (f, v, set, id) => h("input", { type: "text", id, value: v ?? "", oninput: (e) => set(e.target.value) }),
  date: (f, v, set, id) => h("input", { type: "date", id, value: v ?? "", oninput: (e) => set(e.target.value) }),
  long: (f, v, set, id) => h("textarea", { id, rows: 2, oninput: (e) => { grow(e.target); set(e.target.value); } }, v ?? ""),
  choice: (f, v, set, id) => h("div", { class: "opts" }, f.options.map((o) =>
    h("label", { class: "opt" }, h("input", { type: "radio", name: id, value: o, checked: v === o,
      onchange: () => set(o) }), h("span", {}, o)))),
  checks: (f, v, set) => {
    const chosen = new Set(Array.isArray(v) ? v : []);
    return h("div", { class: "opts" }, f.options.map((o) =>
      h("label", { class: "opt" }, h("input", { type: "checkbox", checked: chosen.has(o),
        onchange: (e) => { chosen[e.target.checked ? "add" : "delete"](o); set([...chosen]); } }), h("span", {}, o))));
  },
  rows: rowsField,
};

function fieldView(st, f, value, set) {
  const id = `f-${st.id}-${f.id}`;
  const helpId = f.help ? `${id}-help` : null;
  const help = f.help ? h("p", { class: "help", id: helpId }, f.help) : null;
  let wrap = null;
  const control = FIELDS[f.type](f, value, (v) => { set(v); wrap.classList.toggle("is-filled", filled(v)); }, id);
  if (["text", "date", "long"].includes(f.type)) {
    if (helpId) control.setAttribute("aria-describedby", helpId);
    wrap = h("div", { class: `nb-field is-${f.type}${f.type !== "long" ? " is-inline" : ""}` }, h("label", { for: id }, f.label), help, control);
  } else {
    wrap = h("fieldset", { class: `nb-field is-${f.type}`, "aria-describedby": helpId }, h("legend", {}, f.label), help, control);
  }
  wrap.classList.toggle("is-filled", filled(value));
  wrap.dataset.field = f.id;
  return wrap;
}

function rowsField(f, v, set) {
  const blank = () => f.cols.map(() => "");
  const data = Array.isArray(v) && v.length
    ? v.map((r) => f.cols.map((_, c) => (Array.isArray(r) ? r[c] ?? "" : "")))
    : Array.from({ length: f.start_rows }, blank);
  const tbody = h("tbody");
  const addRow = (r, i) => tbody.append(h("tr", {},
    f.numbered ? h("td", { class: "rn num" }, String(i + 1)) : null,
    r.map((cell, c) => h("td", {}, h("textarea", { rows: 1, "aria-label": `${f.cols[c]}, row ${i + 1}`,
      oninput: (e) => { grow(e.target); r[c] = e.target.value; set(data); } }, cell)))));
  data.forEach(addRow);
  return h("div", { class: "rows-wrap" },
    h("table", { class: "rows" },
      h("thead", {}, h("tr", {}, f.numbered ? h("th", { scope: "col", class: "rn" }, h("span", { "aria-label": "Row number" }, "#")) : null,
        f.cols.map((c) => h("th", { scope: "col" }, c)))),
      tbody),
    h("button", { type: "button", class: "btn ghost small-btn", onclick: () => {
      data.push(blank()); addRow(data.at(-1), data.length - 1); set(data);
      tbody.lastElementChild.querySelector("textarea").focus();
    } }, "Add row"));
}

function gateView(st, note, changed) {
  if (!st.gate.length) return null;
  return h("fieldset", { class: "gate" }, h("legend", {}, "Before you move on"),
    st.gate.map((g, i) => h("label", { class: "opt" },
      h("input", { type: "checkbox", checked: note.gate[i], onchange: (e) => { note.gate[i] = e.target.checked; changed(); } }),
      h("span", {}, g))));
}

// Notes saved under field ids that framework.yaml no longer has for this step. Kept, shown, not editable.
function oldFields(st, fields) {
  const ids = new Set(st.fields.map((f) => f.id));
  const text = (v) => (typeof v === "string" ? v : v.map((x) => (Array.isArray(x) ? x.join(" | ") : x)).join("\n"));
  const old = Object.entries(fields).filter(([k, v]) => !ids.has(k) && text(v).replace(/[\s|]/g, ""));
  if (!old.length) return null;
  return h("section", { class: "old-fields", "aria-label": "Old fields" },
    h("p", { class: "old-title" }, "Old fields"),
    h("p", { class: "help" }, "These notes are from fields that are no longer in this step. They are kept, but you cannot edit them."),
    h("dl", {}, old.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, text(v))])));
}

// ---------- PDF viewer ----------
// Canvas only, no text layer, so the text cannot be selected or copied. Renders the current page only.
function pdfViewer(url, hideBtn, paperId, startPage = 1, saveToNote = null) {
  const v = { doc: null, page: startPage, scale: 1, fit: true, task: null, seq: 0, hidden: false, auto: false, vp: null };
  const sheet = h("div", { class: "pdf-sheet" });
  let shown = 0; // the page on screen, so a page change can slide in
  const hits = h("div", { class: "pdf-hits", "aria-hidden": "true" });
  const ink = h("canvas", { class: "pdf-ink", "aria-hidden": "true" });
  const pageBox = h("div", { class: "pdf-page" });
  let textLayer = h("div", { class: "textLayer" });
  const penHint = h("p", { class: "pen-hint", hidden: true }, "Drag over the words for Dot to explain.",
    h("button", { type: "button", class: "pen-stop", onclick: () => { endPen(); buddy.goHome(); } }, "Stop"));
  const guideMark = h("i", { class: "guide-mark", hidden: true, "aria-hidden": "true" });
  const marksLayer = h("div", { class: "marks-layer" });
  const hlLayer = h("div", { class: "hl-layer", "aria-hidden": "true" }); // saved highlights, under the text
  const selLayer = h("div", { class: "sel-layer", "aria-hidden": "true" }); // the paragraph outline and the chosen box
  const trackLayer = h("div", { class: "track-layer" }); // Proactive: where you are reading, and what you have read
  const stage = h("div", { class: "pdf-stage" }, sheet);
  const closed = h("div", { class: "pdf-closed", hidden: true },
    h("div", { class: "closed-card" },
      h("p", { class: "closed-title" }, "Paper closed"),
      h("p", { class: "quiet" }, "Explain it out loud first, then check."),
      h("button", { type: "button", class: "btn", onclick: () => setHidden(false) }, "Show the paper anyway")));
  const tool = (label, name, fn) => h("button", { type: "button", class: "btn ghost tool", "aria-label": name, title: name, onclick: fn }, label);
  const prev = tool(icon("prev"), "Previous page", () => go(v.page - 1));
  const next = tool(icon("next"), "Next page", () => go(v.page + 1));
  const pageIn = h("input", { type: "number", class: "num", min: 1, value: 1, "aria-label": "Page number",
    onchange: () => go(Number(pageIn.value)) });
  const total = h("span", { class: "quiet num" }, "of 0");
  const zoomLbl = h("span", { class: "num quiet zoom" });
  const el = h("section", { class: "pdf-pane", "aria-label": "Paper" });
  const search = circleSearch({ v, go, ink, hits, pane: el, paperId });
  el.append(
    h("div", { class: "pdf-tools" }, prev, pageIn, total, next, search.button, h("span", { class: "spacer" }),
      tool(icon("minus"), "Zoom out", () => zoom(1 / 1.2)), zoomLbl, tool(icon("plus"), "Zoom in", () => zoom(1.2)),
      h("button", { type: "button", class: "btn ghost tool", onclick: () => { v.fit = true; draw(); } }, icon("fit"), "Fit width")),
    h("div", { class: "pdf-view" }, stage, closed, search.panel, penHint));

  async function draw() {
    if (!v.doc) return;
    const seq = ++v.seq;
    const page = await v.doc.getPage(v.page);
    if (seq !== v.seq) return;
    if (v.fit) v.scale = Math.max(0.25, (stage.clientWidth - 48) / page.getViewport({ scale: 1 }).width);
    const vp = page.getViewport({ scale: v.scale });
    const dpr = window.devicePixelRatio || 1;
    // A fresh canvas per render, so a cancelled render never fights a new one for the same canvas.
    const canvas = h("canvas", { role: "img", "aria-label": `Page ${v.page} of ${v.doc.numPages}` });
    canvas.width = Math.floor(vp.width * dpr); canvas.height = Math.floor(vp.height * dpr);
    canvas.style.width = `${Math.floor(vp.width)}px`; canvas.style.height = `${Math.floor(vp.height)}px`;
    v.task?.cancel();
    v.task = page.render({ canvasContext: canvas.getContext("2d"), viewport: vp, transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0] });
    pageIn.value = v.page;
    prev.disabled = v.page <= 1; next.disabled = v.page >= v.doc.numPages;
    zoomLbl.textContent = `${Math.round(v.scale * 100)}%`;
    try { await v.task.promise; } catch { return; } // cancelled by a newer draw
    v.vp = vp;
    ink.width = canvas.width; ink.height = canvas.height;
    ink.style.width = canvas.style.width; ink.style.height = canvas.style.height;
    if (shown && shown !== v.page) canvas.classList.add(v.page > shown ? "turn-next" : "turn-prev"); // zoom and resize redraws stay still
    shown = v.page;
    const layer = h("div", { class: "textLayer", style: `--scale-factor:${vp.scale}` });
    pdfjsLib.renderTextLayer({ textContentSource: await page.getTextContent(), container: layer, viewport: vp });
    if (seq !== v.seq) return;
    textLayer = layer;
    pageBox.replaceChildren(canvas, hlLayer, hits, guideMark, textLayer, marksLayer, selLayer, trackLayer, ink);
    drawTrack();
    guideMark.hidden = true;
    drawMarks(); loadBlocks(v.page); drawHl();
    if (sel && sel.page !== v.page && !job) clearSel(); else drawSel();
    sheet.replaceChildren(pageBox);
    search.paint();
    viewCb?.();
  }
  let viewCb = null; // the canvas redraws its threads when the page, zoom or scroll changes
  stage.addEventListener("scroll", () => viewCb?.(), { passive: true });
  // Select text with the mouse (formulas too): Dot, which trails the pointer, offers what it can do with the words.
  const picked = () => getSelection().toString().normalize("NFKC").replace(/\s+/g, " ").trim().slice(0, 600);
  function clearPick() { getSelection().removeAllRanges(); }
  pageBox.addEventListener("mouseup", (e) => { if (e.button === 0 && !e.target.closest?.(NOT_PAGE)) setTimeout(() => wordsMenu(e.clientX, e.clientY), 0); });

  // Guided reading: go to a heading, mark it, scroll it near the top, and say where it is on screen.
  async function point(heading, page) {
    await go(page);
    const norm = (t) => t.toLowerCase().replace(/\s+/g, " ").replace(/^[\d.]+\s+/, "").trim();
    const want = norm(heading || "");
    const items = (await (await v.doc.getPage(v.page)).getTextContent()).items.filter((i) => i.str?.trim());
    const boxes = want ? items.filter((i) => { const t = norm(i.str); return t.length >= 3 && (want.startsWith(t) || t.startsWith(want)); })
      .map((i) => itemBox(i, v.vp)) : [];
    const b = boxes.sort((a, c) => c.h - a.h)[0]; // the biggest match is the heading, not a word in the text
    if (b) {
      guideMark.style.cssText = `left:${b.x - 8}px;top:${b.y - 5}px;width:${b.w + 16}px;height:${b.h + 8}px`;
      guideMark.hidden = false; guideMark.classList.remove("on"); void guideMark.offsetWidth; guideMark.classList.add("on");
    }
    const y = b ? b.y : 0;
    const top = () => pageBox.getBoundingClientRect().top;
    stage.scrollTop += top() + y - stage.getBoundingClientRect().top - stage.clientHeight * (b ? 0.3 : 0);
    const pr = pageBox.getBoundingClientRect(), sr = stage.getBoundingClientRect();
    return b ? { left: pr.left + b.x, top: pr.top + b.y, w: b.w, h: b.h, found: true }
      : { left: Math.max(pr.left, sr.left) + 40, top: sr.top + 40, w: 0, h: 0, found: false };
  }
  function unmark() { guideMark.hidden = true; }

  // Dot explains in its own window, and takes follow-up questions there.
  // a page-pixel area, padded a little, as PDF points for the server to crop
  function toPoints(x0, y0, x1, y1) {
    const k = v.vp?.scale ?? 1, pad = 8;
    return [Math.max(0, x0 - pad), Math.max(0, y0 - pad), x1 + pad, y1 + pad].map((q) => Math.round((q / k) * 10) / 10);
  }
  // The part of the page Dot is sending to the model lights up: a field of yellow dots sweeps across it.
  function glow(rect, label) {
    const [x0, y0, x1, y1] = px(rect);
    const g = h("div", { class: "ctx-glow", style: `left:${x0 - 6}px;top:${y0 - 6}px;width:${x1 - x0 + 12}px;height:${y1 - y0 + 12}px` },
      h("i", { class: "ctx-dots" }), ...(label ? [h("span", {}, label)] : []));
    marksLayer.append(g);
    return () => { g.classList.add("out"); setTimeout(() => g.remove(), 420); };
  }
  // Dot reads a box like a finger under the lines: it runs along each line and the words it passes light up.
  // Returns { stop(), done }; `passes` rounds over the box (Infinity: until stopped), at most `most` lines a round.
  function readAlong(rect, passes = Infinity, most = 40) {
    let on = true;
    const [x0, y0, x1, y1] = px(rect), box = pageBox.getBoundingClientRect();
    const lines = [];
    [...textLayer.querySelectorAll("span")].map((sp) => [sp, sp.getBoundingClientRect()])
      .filter(([sp, r]) => sp.textContent.trim() && r.width > 0 && r.left + r.width / 2 - box.left >= x0 && r.left + r.width / 2 - box.left <= x1
        && r.top + r.height / 2 - box.top >= y0 && r.top + r.height / 2 - box.top <= y1)
      .sort((a, b) => a[1].top - b[1].top || a[1].left - b[1].left)
      .forEach(([sp, r]) => { const l = lines.at(-1); if (l && Math.abs(l.top - r.top) < r.height * 0.6) l.spans.push(sp); else lines.push({ top: r.top, spans: [sp] }); });
    const lit = (sp) => {
      sp.classList.remove("dot-read"); void sp.offsetWidth; sp.classList.add("dot-read");
      sp.addEventListener("animationend", () => sp.classList.remove("dot-read"), { once: true });
    };
    const done = (async () => {
      if (!lines.length) return;
      buddy.reading(true);
      for (let n = 0; on && n < passes; n++) {
        for (const { spans } of lines.slice(0, most)) {
          if (!on) break;
          const rs = spans.map((sp) => sp.getBoundingClientRect()), a = rs[0].left, z = Math.max(...rs.map((r) => r.right));
          const y = Math.max(...rs.map((r) => r.bottom)) + 10, ms = Math.round(Math.min(1400, Math.max(450, (z - a) * 3.2)));
          await buddy.goTo(a, y, 220);
          spans.forEach((sp, i) => setTimeout(() => on && lit(sp), (ms * (rs[i].left - a)) / Math.max(1, z - a)));
          await buddy.goTo(z, y, ms);
        }
      }
      buddy.reading(false);
    })();
    return { stop() { on = false; buddy.reading(false); }, done };
  }
  async function dotExplain(words, x, y, rect) {
    if (!words) return;
    await buddy.goTo(x, y);
    let said = "";
    const post = (path, body) => api(`/papers/${paperId}/${path}`, { method: "POST", body: JSON.stringify(body) });
    buddy.open({ x, y, quote: words, area: el.getBoundingClientRect(), save: saveToNote,
      first: post("explain", { words, page: v.page, ...(rect && { rect }) }).finally(rect ? glow(rect, "Dot is reading this") : () => {}).then((r) => { said = r.text || ""; return r; }),
      ask: (q) => post("ask", { page: v.page,
        question: `${q}\n\n(This is about the part I marked: "${words.slice(0, 300)}". You explained: "${said.slice(0, 400)}")`.slice(0, 1000) })
        .then((r) => { if (r.ok) said = r.text; return r; }) });
  }
  // Drag Dot onto the page and it becomes a highlighter; drag over words and it explains them.
  function endPen() { search.stopPen(); buddy.pen(false); penHint.hidden = true; }
  buddy.droppable({
    over: (x, y) => {
      const c = pageBox.querySelector("canvas")?.getBoundingClientRect();
      return !v.hidden && !!c && x >= c.left && x <= c.right && y >= c.top && y <= c.bottom;
    },
    hover: (x, y) => preview(x == null ? null : edgeBlock(x, y)),
    drop: (x, y) => { const b = edgeBlock(x, y); preview(null); return !b ? lens() : openMark ? grow2(openMark, b) : trace(b); },
  });

  // ---------- margin notes: drag Dot to a paragraph's edge; it runs round it and you write beside it ----------
  const blockCache = new Map();
  let blocks = [], marks = [], openMark = null; // openMark: the note whose card is open; a drop then grows its box
  const union = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
  const inside = (a, b) => a[0] >= b[0] - 1 && a[1] >= b[1] - 1 && a[2] <= b[2] + 1 && a[3] <= b[3] + 1;
  api(`/papers/${paperId}/marks`).then((r) => { marks = r.marks; drawMarks(); }).catch(() => {});
  async function loadBlocks(n) {
    if (!blockCache.has(n)) blockCache.set(n, api(`/papers/${paperId}/blocks/${n}`).catch(() => ({ blocks: [] })));
    const r = await blockCache.get(n);
    if (n === v.page) blocks = r.blocks;
  }
  const px = (r) => r.map((q) => q * (v.vp?.scale ?? 1)); // PDF points to page pixels
  // The paragraph whose edge is near the point: within 40px outside it, but not deep inside its text.
  function edgeBlock(x, y) {
    if (!v.vp || v.hidden) return null;
    const box = pageBox.getBoundingClientRect(), lx = x - box.left, ly = y - box.top;
    let best = null, bestD = Infinity;
    for (const b of blocks) {
      const [x0, y0, x1, y1] = px(b);
      const out = Math.max(x0 - lx, lx - x1, y0 - ly, ly - y1); // > 0 outside, < 0 inside
      if (out > 40 || out < -12) continue;
      const d = Math.abs(out);
      if (d < bestD) { bestD = d; best = b; }
    }
    return best;
  }
  const traceBox = h("div", { class: "trace-preview", hidden: true }, h("span", {}, "Drop to trace"));
  function preview(b) {
    if (!b) { traceBox.hidden = true; return; }
    const grow = openMark?.page === v.page;
    traceBox.firstChild.textContent = grow ? "Drop to add to this note" : "Drop to trace";
    const [x0, y0, x1, y1] = px(grow ? union(openMark.rect, b) : b);
    traceBox.style.cssText = `left:${x0 - 8}px;top:${y0 - 8}px;width:${x1 - x0 + 16}px;height:${y1 - y0 + 16}px`;
    if (traceBox.parentNode !== marksLayer) marksLayer.append(traceBox);
    traceBox.hidden = false;
  }
  // a dotted outline: a mask draws it in, so the dots appear as Dot runs past
  function outline(m, ms = 0) {
    const [x0, y0, x1, y1] = px(m.rect), w = x1 - x0 + 16, ht = y1 - y0 + 16;
    const el = h("div", { class: "mk-outline", style: `left:${x0 - 8}px;top:${y0 - 8}px;width:${w}px;height:${ht}px` });
    const id = `mk${m.id}-${Math.random().toString(36).slice(2, 7)}`;
    el.innerHTML = `<svg width="${w}" height="${ht}" viewBox="0 0 ${w} ${ht}"><defs><mask id="${id}"><rect x="2" y="2" width="${w - 4}" height="${ht - 4}" rx="10" pathLength="100" fill="none" stroke="#fff" stroke-width="10" stroke-dasharray="100" stroke-dashoffset="${ms ? 100 : 0}"${ms ? ` style="animation: mk-draw ${ms}ms linear forwards"` : ""}/></mask></defs>
      <rect class="mk-dots" x="2" y="2" width="${w - 4}" height="${ht - 4}" rx="10" fill="none" pathLength="${Math.round((w + ht) * 2 / 9)}" stroke-dasharray="0 1" stroke-linecap="round" mask="url(#${id})"/></svg>`;
    return el;
  }
  function drawMarks() {
    marksLayer.replaceChildren(...marks.filter((m) => m.page === v.page).flatMap((m) => [outline(m), pin(m)]));
  }
  function pin(m) {
    const [x0, y0, x1] = px(m.rect), right = x1 + 32 < pageBox.clientWidth;
    return h("button", { type: "button", class: "mk-pin", style: `left:${right ? x1 + 6 : x0 - 30}px;top:${y0 - 10}px`,
      title: m.text.slice(0, 120), "aria-label": `Margin note: ${m.text.slice(0, 60)}`, onclick: () => card(m) },
      h("i"), h("i"));
  }
  async function trace(b) {
    clearPick(); buddy.pen(false);
    const r = await api(`/papers/${paperId}/marks`, { method: "POST", body: JSON.stringify({ page: v.page, rect: b, text: "" }) }).catch(() => null);
    if (!r) { buddy.goHome(); return buddy.say("I could not save that note. Is the app still running?", { mood: "worried" }); }
    marks.push(r);
    const [x0, y0, x1, y1] = px(b), box = pageBox.getBoundingClientRect();
    const c = [[x0 - 8, y0 - 8], [x1 + 8, y0 - 8], [x1 + 8, y1 + 8], [x0 - 8, y1 + 8], [x0 - 8, y0 - 8]].map(([x, y]) => [box.left + x, box.top + y]);
    const edges = [x1 - x0 + 16, y1 - y0 + 16, x1 - x0 + 16, y1 - y0 + 16];
    const total = Math.min(2600, Math.max(1300, edges.reduce((a, e) => a + e, 0) * 1.6));
    await buddy.goTo(...c[0]);
    marksLayer.append(outline(r, total));
    for (let i = 0; i < 4; i++) await buddy.goTo(...c[i + 1], Math.round((total * edges[i]) / edges.reduce((a, e) => a + e, 0)));
    buddy.goHome();
    drawMarks(); card(r);
  }
  // Grow a note's box over another box (with every box between, so a merged area reads in order).
  async function grow2(m, b) {
    if (m.page !== v.page) return trace(b);
    clearPick(); buddy.pen(false); buddy.goHome();
    let r = union(m.rect, b);
    for (const x of blocks) if (x[0] < r[2] && x[2] > r[0] && x[1] < r[3] && x[3] > r[1]) r = union(r, x); // boxes it now cuts
    m.rect = r.map((q) => Math.round(q * 10) / 10);
    await api(`/papers/${paperId}/marks/${m.id}`, { method: "PUT", body: JSON.stringify({ text: m.text, rect: m.rect }) }).catch(() => {});
    marksLayer.querySelector(".mk-card")?.dispatchEvent(new Event("regrow"));
  }
  // the box after this note's box in reading order (column by column, top to bottom)
  function nextBlock(m) {
    if (m.page !== v.page) return null;
    const last = blocks.findLastIndex((b) => inside(b, m.rect)); // blocks come sorted column by column
    return last >= 0 ? blocks.slice(last + 1).find((b) => !inside(b, m.rect))
      : blocks.find((b) => b[1] >= m.rect[3] - 2 && Math.abs(b[0] - m.rect[0]) < 60);
  }
  // the note beside the paragraph; empty notes go away when closed, written ones fold into a pin
  function card(m) {
    marksLayer.querySelector(".mk-card")?.dispatchEvent(new Event("fold"));
    const [x0, y0, x1, y1] = px(m.rect), W = pageBox.clientWidth;
    const w = Math.min(280, W - 24);
    const side = W - x1 - 20 >= 200 ? x1 + 14 : x0 - 20 >= 200 ? Math.max(8, x0 - 14 - w) : null;
    const pos = side != null ? `left:${side}px;top:${y0 - 4}px;width:${Math.min(w, side > x1 ? W - side - 10 : w)}px`
      : `left:${Math.max(8, Math.min(x0, W - w - 8))}px;top:${y1 + 14}px;width:${w}px`;
    const ta = h("textarea", { class: "mk-text", rows: 3, placeholder: "Write here. Start a line with @ai and press Enter to ask about this box.", "aria-label": `Margin note, page ${m.page}` });
    ta.value = m.text;
    let t = 0;
    const save = () => { clearTimeout(t); if (m.text === ta.value) return; m.text = ta.value; return api(`/papers/${paperId}/marks/${m.id}`, { method: "PUT", body: JSON.stringify({ text: m.text }) }).catch(() => {}); };
    ta.addEventListener("input", () => { clearTimeout(t); t = setTimeout(save, SAVE_DELAY); grow(ta); });
    ta.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
      const start = ta.value.lastIndexOf("\n", ta.selectionStart - 1) + 1;
      const q = ta.value.slice(start, ta.selectionStart).match(/^\s*@ai\b[:,]?\s*(.+)$/i);
      if (!q) return;
      e.preventDefault();
      const wait = `AI is looking at this box (${Date.now()})`;
      ta.setRangeText(`\n${wait}\n`, ta.selectionStart, ta.selectionStart, "end");
      grow(ta); await save();
      const off = glow(m.rect, "Dot is reading this"), finger = readAlong(m.rect);
      const r = await api(`/papers/${paperId}/marks/${m.id}/ask`, { method: "POST", body: JSON.stringify({ question: q[1].trim().slice(0, 600) }) })
        .catch(() => ({ ok: false, error: "Could not ask the model. Is the app still running?" }));
      off(); finger.stop(); buddy.goHome();
      const answer = r.ok ? `AI: ${r.text}` : `AI could not answer: ${r.error}`;
      const i = ta.value.indexOf(wait);
      if (i >= 0) ta.setRangeText(answer, i, i + wait.length, "preserve"); else ta.value += `\n${answer}\n`;
      grow(ta); await save();
    });
    const more = h("button", { type: "button", class: "mk-del mk-more", title: "Take in the next paragraph or formula too",
      onclick: () => { const b = nextBlock(m); if (b) grow2(m, b); else more.disabled = true; } }, "+ Next box");
    const el = h("div", { class: "mk-card", style: pos, role: "dialog", "aria-label": "Margin note" },
      h("div", { class: "mk-head" }, h("span", { class: "buddy-name" }, `p. ${m.page}`),
        more, h("button", { type: "button", class: "mk-del", onclick: () => remove(m) }, "Delete"),
        h("button", { type: "button", class: "buddy-x", "aria-label": "Fold the note", onclick: () => fold() }, "×")),
      ta);
    async function fold() {
      document.removeEventListener("pointerdown", outside, true);
      if (openMark === m) openMark = null;
      await save();
      el.remove();
      if (!m.text.trim()) remove(m);
    }
    // Dot stays usable while a note is open: dragging it to another box grows this note
    const outside = (e) => { if (!el.contains(e.target) && !e.target.closest?.(".mk-pin, .buddy")) fold(); };
    el.addEventListener("fold", fold);
    el.addEventListener("regrow", async () => { // the box changed: redraw it, move the card, keep the words
      document.removeEventListener("pointerdown", outside, true);
      clearTimeout(t); m.text = ta.value; el.remove(); openMark = null;
      drawMarks(); card(m);
    });
    openMark = m;
    el.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); fold(); } });
    setTimeout(() => document.addEventListener("pointerdown", outside, true), 0);
    marksLayer.append(el);
    grow(ta); ta.focus();
  }
  async function remove(m) {
    marks = marks.filter((x) => x !== m);
    if (openMark === m) openMark = null;
    marksLayer.querySelector(".mk-card")?.remove();
    drawMarks();
    await api(`/papers/${paperId}/marks/${m.id}`, { method: "DELETE" }).catch(() => {});
  }
  function lens() {
    clearPick(); buddy.pen(true); penHint.hidden = false;
    search.startPen((words, x, y, area) => {
      endPen();
      if (words) return dotExplain(words, x, y, area && toPoints(...area));
      buddy.goHome(); buddy.say("No words there. Pictures and scanned pages have no text to read.", { mood: "worried" });
    });
  }
  // Lens from Dot's menu: Dot flies to the paper first, then follows the pointer as a highlighter
  async function lensFromMenu() {
    if (v.hidden) return buddy.say("Show the paper first, then pick Lens.", { mood: "worried" });
    const r = stage.getBoundingClientRect();
    await buddy.goTo(r.left + r.width / 2, r.top + r.height / 2);
    lens();
  }

  // ---------- Proactive: Dot notices when you stay on one part a long time, and offers help ----------
  const TICK = 5000, STUCK_MS = Number(localStorage.getItem("dot-stuck-ms")) || 120_000, AWAY_MS = 180_000; // the override is for testing
  let watchOn = localStorage.getItem("dot-proactive") === "1", seen = { key: "", ms: 0 }, lastHere = Date.now(), pointer = null, asking = false;
  const asked = new Set(), watchStop = new AbortController(), opt = { passive: true, signal: watchStop.signal };
  ["pointermove", "keydown", "wheel"].forEach((t) => document.addEventListener(t, () => { lastHere = Date.now(); }, opt));
  document.addEventListener("input", () => { seen.ms = 0; }, opt); // writing notes is progress
  pageBox.addEventListener("pointermove", (e) => { pointer = [e.clientX, e.clientY]; }, opt);
  pageBox.addEventListener("pointerleave", () => { pointer = null; }, opt);
  // the box you are reading: under the pointer if it is on the page, else the one nearest the middle of the view
  function readingBlock() {
    const box = pageBox.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const [x, y] = pointer ?? [s.left + s.width / 2, s.top + s.height / 2];
    let best = null, bd = Infinity;
    for (const b of blocks) {
      const [x0, y0, x1, y1] = px(b);
      if (box.top + y1 < s.top || box.top + y0 > s.bottom) continue; // not on screen
      const d = Math.max(0, box.top + y0 - y, y - box.top - y1) + (x >= box.left + x0 && x <= box.left + x1 ? 0 : 150);
      if (d < bd) { bd = d; best = b; }
    }
    return best;
  }
  function textIn(b) {
    const [x0, y0, x1, y1] = px(b), box = pageBox.getBoundingClientRect();
    return [...textLayer.querySelectorAll("span")].filter((sp) => {
      const r = sp.getBoundingClientRect(), cx = r.left + r.width / 2 - box.left, cy = r.top + r.height / 2 - box.top;
      return cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1;
    }).map((sp) => sp.textContent).join(" ").normalize("NFKC").replace(/\s+/g, " ").trim();
  }
  // A small Dot rides in the margin beside the part you are reading; parts you stayed on keep a rail.
  const READ_MS = 10_000, trailKey = `dot-trail:${paperId}`, lastKey = `dot-last:${paperId}`;
  const trail = new Set(JSON.parse(localStorage.getItem(trailKey) || "[]"));
  const here = h("div", { class: "track-here", hidden: true }, h("i", {}, h("b"), h("b")));
  let hereKey = "";
  function drawTrack() {
    trackLayer.replaceChildren(here);
    trackLayer.hidden = !watchOn;
    if (!watchOn || !v.vp) return;
    for (const k of trail) {
      const [pg, r] = k.split(":");
      if (pg === String(v.page)) trackLayer.append(rail("track-read", r.split(",").map(Number)));
    }
    hereKey = ""; track();
  }
  function rail(cls, b) {
    const [x0, y0, , y1] = px(b);
    return h("div", { class: cls, style: `left:${Math.max(2, x0 - 14)}px;top:${y0}px;height:${y1 - y0}px` });
  }
  function track() {
    if (!watchOn || v.hidden || !v.vp) return;
    const b = readingBlock();
    if (!b) { here.hidden = true; return; }
    const key = `${v.page}:${b.join()}`;
    if (key === hereKey) return;
    hereKey = key;
    const [x0, y0, , y1] = px(b);
    here.style.cssText = `left:${Math.max(2, x0 - 14)}px;top:${y0}px;height:${y1 - y0}px`;
    here.hidden = false;
  }
  let trackRaf = 0;
  const trackSoon = () => { if (!trackRaf) trackRaf = requestAnimationFrame(() => { trackRaf = 0; track(); }); };
  stage.addEventListener("scroll", trackSoon, opt);
  pageBox.addEventListener("pointermove", trackSoon, opt);
  function readIt(key) {
    localStorage.setItem(lastKey, key); // the last part you read, to pick up from next time
    if (trail.has(key)) return;
    trail.add(key); localStorage.setItem(trailKey, JSON.stringify([...trail]));
    const [pg, r] = key.split(":");
    if (pg === String(v.page)) trackLayer.append(rail("track-read fresh", r.split(",").map(Number)));
  }
  function tick() {
    if (!watchOn || asking || v.hidden || document.hidden || !v.vp) return;
    track();
    if (document.querySelector(".dot-win, .mk-card") || search.penning()) { seen.ms = 0; return; } // busy with Dot already
    const b = readingBlock();
    if (!b) return;
    const key = `${v.page}:${b.join()}`;
    if (key !== seen.key) { seen = { key, ms: 0 }; return; }
    if (Date.now() - lastHere < AWAY_MS) seen.ms += TICK; // time away from the screen does not count
    if (seen.ms >= READ_MS) readIt(key);
    if (seen.ms >= STUCK_MS * (asked.has(key) ? 3 : 1)) offer(b, key);
  }
  const watchTimer = setInterval(tick, TICK);
  async function offer(b, key) {
    asking = true; asked.add(key); seen.ms = 0;
    const [, y0, x1] = px(b), box = pageBox.getBoundingClientRect(), x = box.left + x1, y = box.top + y0;
    const off = glow(b, "Stuck here?");
    await readAlong(b, 1, 3).done; // Dot reads the first lines with you, then asks
    const text = textIn(b), done = () => { asking = false; off(); clearTimeout(gone); };
    const gone = setTimeout(() => { done(); buddy.hide(); }, 45_000); // no answer: let it go quietly
    buddy.say("You have been on this part for a few minutes. Want a hand?", { mood: "surprised", actions: [
      { label: "Explain it", onClick: () => { done(); dotExplain(text.slice(0, 600) || "this part", x, y, b); } },
      { label: "Quiz me", onClick: () => { done(); quiz(text, x, y); } },
      { label: "I'm fine", onClick: done },
    ] });
  }
  // Dot asks one question about the part; your reply in its window gets checked
  function quiz(text, x, y) {
    const part = text.slice(0, 500) || `page ${v.page}`;
    const post = (question) => api(`/papers/${paperId}/ask`, { method: "POST", body: JSON.stringify({ page: v.page, question: question.slice(0, 1000) }) });
    let q = "";
    buddy.open({ x, y, quote: part, area: el.getBoundingClientRect(), save: saveToNote,
      first: post(`Ask me one short question that checks whether I understood this part. Only the question, not the answer. The part: "${part}"`)
        .then((r) => { q = r.text || ""; return r; }),
      ask: (a) => post(`You asked me "${q.slice(0, 250)}" about this part: "${part.slice(0, 300)}". My answer: "${a}". Is it right? Say what is right and what is missing, in 2 to 4 sentences.`) });
  }
  function clearTrail() {
    trail.clear(); localStorage.removeItem(trailKey); localStorage.removeItem(lastKey); drawTrack();
    buddy.say("I cleared the reading trail for this paper.", { mood: "idle" });
  }
  // Opening the paper again: Dot offers to take you back to the last part you read.
  function offerResume() {
    const last = localStorage.getItem(lastKey);
    if (!watchOn || !last) return;
    const [pg, r] = last.split(":"), b = r.split(",").map(Number);
    setTimeout(() => buddy.say(`Last time you got to page ${pg}. Pick up there?`, { mood: "happy", actions: [
      { label: "Take me there", onClick: async () => {
        await go(Number(pg));
        const box = pageBox.getBoundingClientRect(), s = stage.getBoundingClientRect();
        stage.scrollTop += box.top + px(b)[1] - s.top - 80;
        const off = glow(b, "You were here");
        setTimeout(off, 3000);
      } },
      { label: "Not now", onClick: () => {} },
    ] }), 2500);
  }
  function watch(on) {
    watchOn = on; localStorage.setItem("dot-proactive", on ? "1" : "0"); seen = { key: "", ms: 0 };
    drawTrack();
    buddy.say(on ? "Proactive is on. I will check in if you stay on one part for a couple of minutes." : "Proactive is off. I will wait until you call me.", { mood: on ? "happy" : "idle" });
  }


  // ---------- reading mode: click a paragraph for Dot's options; highlight by hand ----------
  // The reader sets hooks.onAsk(selection, at) and hooks.onNote(selection, at); until then Ask and Note only close the menu.
  const hooks = { onAsk: null, onNote: null };
  let hls = [], sel = null, job = false, animating = false, skipAnim = false, chip = null;
  const near = h("div", { class: "p-near", hidden: true });
  const selBox = h("div", { class: "sel-box", hidden: true }, h("b"));
  selLayer.append(near, selBox);
  api(`/papers/${paperId}/highlights`).then((r) => { hls = r.highlights; drawHl(); }).catch(() => {});
  const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fast = () => skipAnim || reducedMotion(); // a click, or reduced motion, jumps animations to their end
  const rnd = (r) => r.map((q) => Math.round(q * 10) / 10);
  // an animation runs inside anim(): a click anywhere skips it to its end state
  async function anim(fn) {
    animating = true; skipAnim = false;
    try { await fn(); } finally { animating = false; skipAnim = false; }
  }
  document.addEventListener("pointerdown", () => { if (animating) { skipAnim = true; buddy.skip(); } }, { capture: true, signal: watchStop.signal });

  const ICON = {
    suggest: '<svg viewBox="0 0 24 24"><path d="m9 11-6 6v3h9l3-3"/><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/></svg>',
    ask: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>',
    note: '<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
    more: '<svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>',
    back: '<svg viewBox="0 0 24 24"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>',
    explain: '<svg viewBox="0 0 24 24"><path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z"/></svg>',
    mark: '<svg viewBox="0 0 24 24"><path d="m4 20 3-1 10-10-2-2L5 17Z"/><path d="m14 6 2-2 4 4-2 2"/><path d="M4 21h8"/></svg>',
    find: '<svg viewBox="0 0 24 24"><path d="M3 6h12"/><path d="M3 11h6"/><path d="M3 16h6"/><circle cx="16" cy="15" r="4"/><path d="m21 20-2.2-2.2"/></svg>',
  };
  const ITEMS = [["suggest", "Suggest highlights"], ["ask", "Ask"], ["note", "Note"], ["more", "Add more"], ["back", "Back"]]
    .map(([key, label]) => ({ key, label, icon: ICON[key] }));
  // chosen words: Explain, Highlight and Find in paper are Dot's options too (there is no separate popup)
  const WORDS = [["explain", "Explain"], ["mark", "Highlight"], ["find", "Find in paper"], ["ask", "Ask"], ["note", "Note"], ["back", "Back"]]
    .map(([key, label]) => ({ key, label, icon: ICON[key] }));

  function setBox(el, r) {
    const [x0, y0, x1, y1] = px(r);
    el.style.cssText = `left:${x0 - 8}px;top:${y0 - 6}px;width:${x1 - x0 + 16}px;height:${y1 - y0 + 12}px`;
  }
  const blockAt = (cx, cy, slack = 4) => {
    const box = pageBox.getBoundingClientRect(), lx = cx - box.left, ly = cy - box.top;
    return blocks.filter((b) => { const [x0, y0, x1, y1] = px(b); return lx >= x0 - slack && lx <= x1 + slack && ly >= y0 - slack && ly <= y1 + slack; })
      .sort((a, b) => (a[2] - a[0]) * (a[3] - a[1]) - (b[2] - b[0]) * (b[3] - b[1]))[0] ?? null; // the smallest box that holds the point
  };
  // the paragraph is free to click: not while Lens, the pen, the Map, a note or another job has Dot
  const clickable = () => !v.hidden && !!v.vp && !job && !search.penning() && !search.isOpen() && !openMark
    && !document.querySelector(".guide-card:not([hidden]), .dot-win, .mk-card, .hl-chip, .buddy.pen, .buddy.penning, .buddy.dragging, .buddy-opts, .buddy-pill");
  const NOT_PAGE = ".mk-pin, .mk-card, .hl-chip, .buddy-opts, .guide-card, .pen-hint, .track-here";

  pageBox.addEventListener("pointermove", (e) => {
    if (!clickable() || e.target.closest?.(NOT_PAGE)) { near.hidden = true; return; }
    const b = blockAt(e.clientX, e.clientY, 2);
    if (!b) { near.hidden = true; return; }
    setBox(near, b); near.hidden = false;
  }, opt);
  pageBox.addEventListener("pointerleave", () => { near.hidden = true; }, opt);

  let down = null;
  pageBox.addEventListener("pointerdown", (e) => { down = e.button === 0 ? { x: e.clientX, y: e.clientY, t: performance.now(), tgt: e.target } : null; });
  pageBox.addEventListener("pointerup", (e) => {
    const d = down; down = null;
    if (!d || e.button !== 0 || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6 || performance.now() - d.t > 300) return;
    if (d.tgt.closest?.(NOT_PAGE)) return;
    const x = e.clientX, y = e.clientY;
    setTimeout(() => { // a click leaves no selection; a double-click selects a word and is not ours
      if (!getSelection().isCollapsed || !clickable()) return;
      const hl = hlAt(x, y);
      if (hl) showChip(hl, x, y); else paragraphMenu(x, y, blockAt(x, y));
    }, 0);
  });

  // ----- the chosen box -----
  function drawSel() {
    if (!sel || sel.page !== v.page || !v.vp) { selBox.hidden = true; return; }
    setBox(selBox, sel.blocks.reduce(union));
    selBox.hidden = false;
    selBox.querySelector("b").textContent = sel.blocks.length > 1 ? `+${sel.blocks.length - 1}` : "";
    selBox.classList.toggle("more", sel.blocks.length > 1);
  }
  function clearSel() { sel = null; selBox.hidden = true; selBox.classList.remove("more", "grow"); }
  const selection = () => {
    if (!sel) return null;
    const rect = rnd(sel.blocks.reduce(union));
    return { page: sel.page, rect, text: textIn(rect).slice(0, 3000) };
  };

  // Dot comes to the click: reduced motion puts it there at once; otherwise a short walk if it is not already beside the pointer
  async function toClick(x, y) {
    if (reducedMotion()) { buddy.put(x + 36, y + 34); return; }
    const [cx, cy] = buddy.centre();
    if (Math.hypot(cx - x - 36, cy - y - 34) > 60) await buddy.goTo(x + 36, y + 34, 260);
  }

  // ----- Dot's options on a paragraph (or on the page, off any paragraph) -----
  async function paragraphMenu(x, y, b) {
    job = true; near.hidden = true;
    sel = b ? { page: v.page, blocks: [b] } : null;
    drawSel();
    buddy.hold(true); // Dot stays with this paragraph until you are done
    try {
      await toClick(x, y);
      for (;;) {
        const [cx, cy] = buddy.centre();
        const pick = await buddy.options({ x: cx, y: cy, items: sel ? ITEMS : ITEMS.filter((i) => ["ask", "note", "back"].includes(i.key)) });
        if (pick === "more") { await addMore(); continue; }
        if (pick === "suggest") await suggestHere();
        else if (pick === "ask" || pick === "note") await hooks[pick === "ask" ? "onAsk" : "onNote"]?.(selection(), { x: cx, y: cy });
        break;
      }
    } finally { job = false; clearSel(); buddy.hold(false); await buddy.shape("face"); }
  }

  // ----- Dot's options on chosen words: it is already beside the pointer, so the options come out of it there -----
  async function wordsMenu(x, y) {
    const sl = getSelection();
    if (!textLayer || sl.isCollapsed || !sl.rangeCount || !textLayer.contains(sl.anchorNode) || !picked() || !clickable()) return;
    const words = picked(), rects = selectionRects();
    if (!rects.length) return;
    const rr = sl.getRangeAt(0).getBoundingClientRect(), box = pageBox.getBoundingClientRect();
    const area = toPoints(rr.left - box.left, rr.top - box.top, rr.right - box.left, rr.bottom - box.top);
    const tight = rnd(rects.reduce(union));
    job = true; near.hidden = true;
    await toClick(x, y);
    const [cx, cy] = buddy.centre();
    let pick;
    try { pick = await buddy.options({ x: cx, y: cy, items: WORDS }); } finally { job = false; }
    if (pick === "mark") highlightSelection();
    else if (pick === "explain") { clearPick(); await dotExplain(words, cx, cy, area); }
    else if (pick === "find") { clearPick(); search.find(words); }
    else if (pick === "ask" || pick === "note") { const at = { x: cx, y: cy }, chosen = { page: v.page, rect: tight, text: words.slice(0, 3000) }; clearPick(); await hooks[pick === "ask" ? "onAsk" : "onNote"]?.(chosen, at); }
    else if (pick === "back") clearPick();
  }

  // ----- Add more: Dot squashes, rides the box's bottom edge, and the box grows over the next paragraph -----
  async function addMore() {
    const last = Math.max(...sel.blocks.map((q) => blocks.indexOf(q)));
    const nx = blocks[last + 1];
    if (!nx || sel.page !== v.page) { buddy.nudge(); return; } // nothing more on this page
    await anim(async () => {
      await buddy.shape("squash");
      const box = () => pageBox.getBoundingClientRect();
      // Dot rides the middle of the box's bottom edge; the page scrolls to keep that edge in view
      const edge = (r) => { const [x0, , x1, y1] = px(r); return [box().left + (x0 + x1) / 2, box().top + y1 + 4]; };
      const see = async (r) => {
        const over = edge(r)[1] - (stage.getBoundingClientRect().bottom - 110);
        if (over <= 0) return;
        stage.scrollBy({ top: over, behavior: fast() ? "auto" : "smooth" });
        for (let last = -1, i = 0; !fast() && i < 30 && stage.scrollTop !== last; i++) { last = stage.scrollTop; await buddy.wait(50); } // until the scroll settles
      };
      await see(sel.blocks.reduce(union));
      await buddy.goTo(...edge(sel.blocks.reduce(union)), fast() ? 1 : 250);
      sel.blocks.push(nx);
      selBox.classList.remove("grow"); void selBox.offsetWidth;
      drawSel(); selBox.classList.add("grow");
      await see(sel.blocks.reduce(union));
      await buddy.goTo(...edge(sel.blocks.reduce(union)), fast() ? 1 : 550);
      await buddy.shape("face");
      if (!fast()) await buddy.wait(150);
      selBox.classList.remove("grow");
    });
  }

  // ----- saved highlights: yellow are yours, blue are Dot's suggestions -----
  const strokeEl = (hl, r, from0 = false) => {
    const [x0, y0, x1, y1] = px(r);
    return h("i", { class: `hlk hlk-${hl.kind}`, style: `left:${x0 - 1}px;top:${y0 - 1}px;width:${from0 ? 0 : x1 - x0 + 2}px;height:${y1 - y0 + 2}px` });
  };
  function drawHl() {
    hlLayer.replaceChildren(...hls.filter((x) => x.page === v.page && x.rects).flatMap((x) => x.rects.map((r) => strokeEl(x, r))));
  }
  function hlAt(cx, cy) {
    const box = pageBox.getBoundingClientRect(), k = v.vp?.scale ?? 1, lx = (cx - box.left) / k, ly = (cy - box.top) / k;
    return hls.findLast((x) => x.page === v.page && x.rects.some((r) => lx >= r[0] && lx <= r[2] && ly >= r[1] && ly <= r[3])) ?? null;
  }
  function closeChip() { chip?.remove(); chip = null; document.removeEventListener("pointerdown", chipOut, true); document.removeEventListener("keydown", chipKey, true); }
  const chipOut = (e) => { if (!chip?.contains(e.target)) closeChip(); };
  const chipKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); closeChip(); } };
  function showChip(hl, x, y) {
    closeChip();
    const box = pageBox.getBoundingClientRect();
    const btn = (label, fn) => h("button", { type: "button", class: "btn small-btn", onclick: () => { closeChip(); fn(); } }, label);
    chip = h("div", { class: "hl-chip", role: "toolbar", "aria-label": hl.kind === "dot" ? "Dot's highlight" : "Your highlight",
      style: `left:${Math.min(x - box.left, box.width - 170)}px;top:${y - box.top + 12}px` },
      ...(hl.kind === "dot" ? [btn("Keep", async () => { const r = await api(`/papers/${paperId}/highlights/${hl.id}`, { method: "PUT" }).catch(() => null); if (r) { hl.kind = "me"; drawHl(); } })] : []),
      btn("Remove", async () => { hls = hls.filter((q) => q !== hl); drawHl(); await api(`/papers/${paperId}/highlights/${hl.id}`, { method: "DELETE" }).catch(() => {}); }));
    pageBox.append(chip);
    chip.querySelector("button").focus({ preventScroll: true });
    setTimeout(() => { document.addEventListener("pointerdown", chipOut, true); document.addEventListener("keydown", chipKey, true); }, 0);
  }

  // ----- Suggest highlights: Dot runs along the lines while the model picks, then inks each pick in blue -----
  async function suggestHere() {
    const s = selection();
    if (!s) return;
    await buddy.shape("marker");
    const finger = readAlong(s.rect);
    const r = await api(`/papers/${paperId}/highlights/suggest`, { method: "POST", body: JSON.stringify({ page: s.page, rect: s.rect }) })
      .catch(() => ({ ok: false, error: "Could not ask the model. Is the app still running?" }));
    finger.stop();
    await buddy.shape("marker");
    if (!r.ok) { buddy.say(r.error, { mood: "worried" }); return; }
    if (!r.highlights.length) { buddy.say("Nothing here stood out to me."); return; }
    await anim(async () => {
      for (const hl of r.highlights) {
        hls.push(hl);
        for (const rect of hl.rects) { if (s.page !== v.page) break; await inkLine(hl, rect); }
      }
    });
    drawHl();
  }
  async function inkLine(hl, rect) {
    const [x0, , x1] = px(rect), box = pageBox.getBoundingClientRect(), full = x1 - x0 + 2;
    const el = strokeEl(hl, rect, true);
    hlLayer.append(el);
    if (fast()) { el.style.width = `${full}px`; return; }
    const top = box.top + px(rect)[1] - 14;
    await buddy.goTo(box.left + x0, top, 160);
    const ms = Math.max(250, full * 2.2);
    el.style.transition = `width ${ms}ms linear`; void el.offsetWidth; el.style.width = `${full}px`;
    await buddy.goTo(box.left + x1, top, ms);
    el.style.transition = "none"; el.style.width = `${full}px`;
  }

  // ----- your own highlighter: select words, press Highlight -----
  // the selection's line rectangles in PDF points: pieces on one line are joined, pieces in another column are not
  function selectionRects() {
    const sl = getSelection();
    if (!sl.rangeCount || !v.vp) return [];
    const box = pageBox.getBoundingClientRect(), k = v.vp.scale, W = v.vp.width / k, H = v.vp.height / k;
    const raw = [...sl.getRangeAt(0).getClientRects()].filter((r) => r.width > 2 && r.height > 2)
      .map((r) => [(r.left - box.left) / k, (r.top - box.top) / k, (r.right - box.left) / k, (r.bottom - box.top) / k]);
    if (!raw.length) return [];
    const med = raw.map((r) => r[3] - r[1]).sort((a, b) => a - b)[raw.length >> 1];
    const lines = [];
    for (const r of raw.filter((q) => q[3] - q[1] < med * 2.5).sort((a, b) => a[1] - b[1] || a[0] - b[0])) {
      const l = lines.at(-1), hh = Math.min(r[3] - r[1], l ? l[3] - l[1] : 1e9);
      if (l && Math.min(l[3], r[3]) - Math.max(l[1], r[1]) > 0.5 * hh && r[0] - l[2] < hh * 1.5) {
        l[0] = Math.min(l[0], r[0]); l[1] = Math.min(l[1], r[1]); l[2] = Math.max(l[2], r[2]); l[3] = Math.max(l[3], r[3]);
      } else lines.push([...r]);
    }
    return lines.map((r) => rnd([Math.max(0, r[0]), Math.max(0, r[1]), Math.min(W, r[2]), Math.min(H, r[3])])).filter((r) => r[0] < r[2] && r[1] < r[3]).slice(0, 60);
  }
  async function highlightSelection() {
    const text = picked(), rects = selectionRects();
    clearPick();
    if (!rects.length) return;
    const hl = { id: null, page: v.page, kind: "me", text, rects };
    hls.push(hl); drawHl(); // yellow at once
    const r = await api(`/papers/${paperId}/highlights`, { method: "POST", body: JSON.stringify({ page: hl.page, kind: "me", text, rects }) }).catch(() => null);
    if (r) hl.id = r.id;
    else { hls = hls.filter((q) => q !== hl); drawHl(); buddy.say("I could not save that highlight. Is the app still running?", { mood: "worried" }); }
  }

  function go(n) {
    if (!v.doc) return;
    v.page = Math.min(v.doc.numPages, Math.max(1, Math.round(n) || v.page));
    return draw();
  }
  function zoom(f) { v.fit = false; v.scale = Math.min(5, Math.max(0.25, v.scale * f)); draw(); }
  function setHidden(on, auto = false) {
    v.hidden = on; v.auto = on && auto;
    el.classList.toggle("is-closed", on);
    closed.hidden = !on;
    hideBtn.textContent = on ? "Show paper" : "Hide paper";
    hideBtn.setAttribute("aria-pressed", String(on));
    if (on) search.close(); // no peeking at the words while the paper is closed
    search.button.disabled = on;
  }
  const msg = (text) => sheet.replaceChildren(h("p", { class: "pdf-msg" }, text));

  const onKey = (e) => {
    if (e.key === "Escape" && search.penning()) { endPen(); return buddy.goHome(); }
    if (e.key === "Escape" && search.isOpen()) return search.close();
    if (e.altKey || e.ctrlKey || e.metaKey || e.target.closest?.("input, textarea, select, [contenteditable], dialog, [role=separator]")) return;
    if (e.key === "ArrowLeft") go(v.page - 1);
    else if (e.key === "ArrowRight") go(v.page + 1);
  };
  document.addEventListener("keydown", onKey);
  let resizing = null;
  const ro = new ResizeObserver(() => { if (v.fit) { clearTimeout(resizing); resizing = setTimeout(draw, 80); } });
  ro.observe(stage);

  if (!window.pdfjsLib) msg("The PDF viewer could not load. Check your internet connection, then reload the page.");
  else {
    msg("Opening the PDF");
    pdfjsLib.getDocument({ url, isEvalSupported: false }).promise.then((doc) => {
      v.doc = doc; v.page = Math.min(Math.max(1, v.page), doc.numPages); // a link may ask for any page
      total.textContent = `of ${doc.numPages}`; pageIn.max = doc.numPages; draw().then(offerResume);
    }, () => msg("This PDF could not be opened."));
  }

  return {
    el, hooks, selection, setHidden,
    onView: (f) => { viewCb = f; },
    // a paragraph's box on screen, or null when that page is not shown or the box is scrolled out of sight
    toScreen(n, r) {
      if (n !== v.page || !v.vp || v.hidden) return null;
      const b = pageBox.getBoundingClientRect(), s = stage.getBoundingClientRect(), [x0, y0, x1, y1] = px(r);
      const out = new DOMRect(b.left + x0, b.top + y0, x1 - x0, y1 - y0);
      return out.bottom < s.top || out.top > s.bottom ? null : out;
    },
    light: (n, r) => (n === v.page && v.vp && !v.hidden ? glow(r) : () => {}), // returns the function that puts the glow out
    async reveal(n, r) {
      await go(n);
      const b = pageBox.getBoundingClientRect(), s = stage.getBoundingClientRect();
      stage.scrollTop += b.top + px(r)[1] - s.top - stage.clientHeight * 0.3;
      const off = glow(r); setTimeout(off, 1800);
    }, hidden: () => v.hidden, page: () => v.page, go, point, unmark, lens: lensFromMenu, watch, watching: () => watchOn, clearTrail,
    // Self-test closes the paper when it opens; leaving it opens the paper again unless you closed it yourself.
    autoHide(on) { if (on) setHidden(true, true); else if (v.auto) setHidden(false); },
    destroy() { clearInterval(watchTimer); watchStop.abort(); buddy.tools(null); if (search.penning()) { endPen(); buddy.goHome(); } buddy.droppable(null); document.removeEventListener("keydown", onKey); ro.disconnect(); v.doc?.destroy(); },
  };
}

// ---------- circle to search ----------
// Circle (or tap) words on the page. The words come from the PDF's own text, read in the browser.
// Finds them in this paper and in your other papers. Nothing leaves this computer.
const flat = (s) => s.replace(/-\s+(?=[a-z])/g, "").replace(/\s+/g, " ").trim(); // also joins words split at line ends

function itemBox(it, vp) {
  const t = pdfjsLib.Util.transform(vp.transform, it.transform);
  const hgt = Math.hypot(t[2], t[3]);
  return { x: t[4], y: t[5] - hgt, w: it.width * vp.scale, h: hgt * 1.15 };
}

// shortcut: letters are placed by even spacing across each text run, so a circle edge can be off by a letter
// in wide fonts; the cut is widened to whole words, which hides it. Upgrade to per-glyph boxes if it misses.
function wordsIn(items, vp, r, max = 12) {
  const parts = [];
  for (const it of items) {
    const b = itemBox(it, vp);
    const mid = b.y + b.h / 2;
    // a line counts when its middle is inside the circle; a tap counts when it lands on the line
    const inLine = r.line != null ? r.line >= b.y && r.line <= b.y + b.h : mid >= r.y0 && mid <= r.y1;
    if (!inLine || b.x + b.w < r.x0 || b.x > r.x1) continue;
    const s = it.str, n = s.length;
    let a = 0, z = n;
    while (a < n && b.x + (b.w * (a + 0.5)) / n < r.x0) a++;
    while (z > a && b.x + (b.w * (z - 0.5)) / n > r.x1) z--;
    while (a < z && /\s/.test(s[a])) a++; // an edge on a space does not reach into the next word
    while (z > a && /\s/.test(s[z - 1])) z--;
    if (a === z && !r.tap) continue;
    while (a > 0 && /\w/.test(s[a - 1])) a--;
    while (z < n && /\w/.test(s[z])) z++;
    parts.push(s.slice(a, z));
  }
  const text = flat(parts.join(" ")).normalize("NFKC");
  // plain words: trim stray punctuation and keep it short for search; a formula keeps its symbols
  return /[=∑∏∫←→≤≥∈∼~^_]/.test(text) ? text.slice(0, 600) : text.replace(/^\W+|\W+$/g, "").split(" ").slice(0, max).join(" ").slice(0, 600);
}

function circleSearch({ v, go, ink, hits, pane, paperId }) {
  const texts = new Map();
  const pageItems = (n) => {
    if (!texts.has(n)) texts.set(n, v.doc.getPage(n).then((p) => p.getTextContent())
      .then((tc) => tc.items.filter((i) => i.str?.trim())));
    return texts.get(n);
  };
  let on = false, query = "", run = 0, jump = false, pts = null, penCb = null;

  const input = h("input", { type: "search", class: "cs-input", placeholder: "Words to find", "aria-label": "Words to find",
    onkeydown: (e) => { if (e.key === "Enter") find(input.value); } });
  const results = h("div", { class: "cs-results", role: "status", "aria-live": "polite" });
  const panel = h("div", { class: "cs-panel", hidden: true, role: "dialog", "aria-label": "Circle to search" },
    h("div", { class: "cs-head" }, h("span", { class: "cs-title" }, "Circle to search"),
      h("button", { type: "button", class: "cs-x", "aria-label": "Close search", onclick: () => close() }, "×")),
    input,
    h("p", { class: "help" }, "Circle or tap words on the page. Or type, then press Enter."),
    results);
  const button = h("button", { type: "button", class: "btn ghost tool cs-btn", "aria-pressed": "false",
    onclick: () => (on ? close() : open()) }, h("span", { class: "cs-ring", "aria-hidden": "true" }), "Circle to search");

  function open() {
    on = true; panel.hidden = false; pane.classList.add("is-circling");
    button.setAttribute("aria-pressed", "true"); input.focus();
  }
  function close() {
    if (!on) return;
    on = false; panel.hidden = true; pane.classList.remove("is-circling");
    button.setAttribute("aria-pressed", "false");
    query = ""; input.value = ""; results.replaceChildren(); clearInk(); paint();
  }

  // ----- drawing the circle -----
  const pt = (e) => { const r = ink.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  function clearInk() { ink.getContext("2d").clearRect(0, 0, ink.width, ink.height); ink.classList.remove("fade"); }
  function stroke() {
    const c = ink.getContext("2d"), k = ink.width / (ink.clientWidth || 1);
    c.clearRect(0, 0, ink.width, ink.height);
    c.lineCap = c.lineJoin = "round";
    c.beginPath(); pts.forEach(([x, y], i) => (i ? c.lineTo(x * k, y * k) : c.moveTo(x * k, y * k)));
    if (penCb) { c.lineWidth = 18 * k; c.strokeStyle = "rgba(255,227,71,.55)"; c.globalCompositeOperation = "multiply"; c.stroke(); c.globalCompositeOperation = "source-over"; return; } // a highlighter
    c.lineWidth = 8 * k; c.strokeStyle = "rgba(31,32,35,.25)"; c.stroke(); // soft edge so yellow shows on white
    c.lineWidth = 5 * k; c.strokeStyle = "#ffe347"; c.stroke();
  }
  ink.addEventListener("pointerdown", (e) => {
    if ((!on && !penCb) || !v.vp) return;
    e.preventDefault(); ink.setPointerCapture(e.pointerId); clearInk();
    pts = [pt(e)]; stroke();
  });
  ink.addEventListener("pointermove", (e) => { if (pts) { pts.push(pt(e)); stroke(); } });
  ink.addEventListener("pointerup", () => {
    if (!pts) return;
    const p = pts; pts = null;
    ink.classList.add("fade"); setTimeout(() => { if (!pts) clearInk(); }, penCb ? 900 : 450);
    if (penCb) { const cb = penCb; stopPen(); highlight(p, cb); } else pick(p);
  });
  ink.addEventListener("pointercancel", () => { pts = null; clearInk(); });

  function region(p) {
    const xs = p.map((q) => q[0]), ys = p.map((q) => q[1]);
    const r = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
    if (r.x1 - r.x0 < 6 && r.y1 - r.y0 < 6) return { ...r, x1: r.x0, line: r.y0, tap: true }; // a tap picks one word
    if (r.y1 - r.y0 < 14) return { ...r, line: (r.y0 + r.y1) / 2 }; // a flat swipe picks the line it runs along
    return r;
  }
  // Dot as a highlighter: the words under the stroke, and where the stroke ended on screen
  async function highlight(p, cb) {
    const box = ink.getBoundingClientRect(), [ex, ey] = p.at(-1);
    const r = region(p);
    cb(wordsIn(await pageItems(v.page), v.vp, r, 120), box.left + ex, box.top + ey, [r.x0, r.y0 - 10, Math.max(r.x1, r.x0 + 60), r.y1 + 10]);
  }
  function startPen(cb) { penCb = cb; pane.classList.add("is-penning"); }
  function stopPen() { penCb = null; pane.classList.remove("is-penning"); }

  async function pick(p) {
    const words = wordsIn(await pageItems(v.page), v.vp, region(p));
    if (!words) {
      results.replaceChildren(h("p", { class: "help" }, "No words there. Pictures and scanned pages have no text to find."));
      return;
    }
    input.value = words;
    find(words);
  }

  // ----- finding -----
  async function find(q) {
    query = flat(q);
    const my = ++run;
    paint();
    if (query.length < 2) { results.replaceChildren(); return; }
    results.replaceChildren(h("p", { class: "help" }, "Searching"));
    const lower = query.toLowerCase();
    const pages = [];
    for (let n = 1; n <= v.doc.numPages; n++) {
      const text = flat((await pageItems(n)).map((i) => i.str).join(" "));
      const low = text.toLowerCase();
      const first = low.indexOf(lower);
      let count = 0;
      for (let at = first; at !== -1; at = low.indexOf(lower, at + lower.length)) count++;
      if (count) pages.push({ n, count, before: text.slice(Math.max(0, first - 40), first),
        hit: text.slice(first, first + query.length), after: text.slice(first + query.length, first + query.length + 40) });
    }
    const lib = (await api(`/papers?q=${encodeURIComponent(query)}`).catch(() => ({ papers: [] })))
      .papers.filter((p) => p.id !== paperId);
    if (my !== run) return; // a newer search started meanwhile
    const total = pages.reduce((s, p) => s + p.count, 0);
    // the page the words are on: the one you are looking at if it has them, else the first match
    const onPage = pages.find((p) => p.n === v.page)?.n ?? pages[0]?.n ?? v.page;
    const answer = h("div", { class: "cs-answer" });
    const ask = h("button", { type: "button", class: "btn small-btn cs-ask",
      onclick: () => explainIt(query, onPage, answer, ask) }, "Explain this");
    const plural = (n, w) => `${n} ${w}${n === 1 ? "" : w.endsWith("h") ? "es" : "s"}`;
    results.replaceChildren(...[
      h("div", { class: "cs-explain" }, ask, answer),
      h("p", { class: "cs-sum" }, total ? `${plural(total, "match")} on ${plural(pages.length, "page")}` : "Not in this paper."),
      pages.length ? h("ol", { class: "cs-pages" }, pages.map((p) => h("li", {},
        h("button", { type: "button", class: "cs-hit", "data-page": p.n, onclick: () => { jump = true; go(p.n); } },
          h("span", { class: "cs-pg num" }, `Page ${p.n}`, p.count > 1 ? h("span", { class: "quiet" }, ` ${p.count} times`) : null),
          h("span", { class: "cs-snip" }, p.before && `…${p.before}`, h("mark", {}, p.hit), p.after && `${p.after}…`))))) : null,
      lib.length ? h("div", { class: "cs-lib" }, h("p", { class: "cs-sum" }, "Also in your papers"),
        lib.slice(0, 5).map((p) => h("a", { href: `#read/${p.id}`, class: "cs-paper" }, p.title))) : null,
    ].filter(Boolean));
    paint();
  }

  // Asks the local model what the words mean. The server sends it the whole paper (or what fits).
  async function explainIt(words, page, box, btn) {
    btn.disabled = true;
    box.replaceChildren(h("p", { class: "help cs-wait" }, "Reading the whole paper. This can take a minute."));
    buddy.mood("think");
    try {
      const r = await api(`/papers/${paperId}/explain`, { method: "POST", body: JSON.stringify({ words, page }) });
      box.replaceChildren(...(r.ok ? [
        h("p", { class: "cs-ai-label" }, "AI explanation"),
        h("div", { class: "cs-ai-text" }, buddy.format(r.text)),
        h("p", { class: "help" }, r.whole
          ? `Your model read the whole paper (${r.total} pages) in ${r.seconds} seconds.`
          : `The paper is too long for your model's context, so it read pages ${r.pages[0]} to ${r.pages[1]} of ${r.total}.`),
      ] : [h("p", { class: "status err" }, r.error)]));
    } catch {
      box.replaceChildren(h("p", { class: "status err" }, "Could not ask the model. Is the app still running?"));
    } finally {
      btn.disabled = false; buddy.mood("idle");
    }
  }

  // Marks every match on the page you are looking at.
  async function paint() {
    hits.replaceChildren();
    results.querySelectorAll(".cs-hit").forEach((b) => b.toggleAttribute("aria-current", Number(b.dataset.page) === v.page));
    if (!query || !v.vp || !v.doc) return;
    const n = v.page, vp = v.vp, lower = query.toLowerCase();
    const items = await pageItems(n);
    if (n !== v.page || vp !== v.vp) return; // the page changed while the text loaded
    const mark = (b, x, w) => hits.append(h("i", { style: `left:${x}px;top:${b.y}px;width:${w}px;height:${b.h}px` }));
    for (const it of items) {
      const s = it.str.toLowerCase(), b = itemBox(it, vp);
      let at = s.indexOf(lower);
      if (at === -1) {
        // a phrase broken across lines: mark the pieces
        if (it.str.trim().length >= 4 && lower.includes(flat(s))) mark(b, b.x, b.w);
        continue;
      }
      for (; at !== -1; at = s.indexOf(lower, at + lower.length)) mark(b, b.x + (b.w * at) / s.length, (b.w * lower.length) / s.length);
    }
    if (jump && hits.firstChild) { hits.firstChild.scrollIntoView({ block: "center", behavior: "smooth" }); }
    jump = false;
  }

  return {
    button, panel, paint, close, isOpen: () => on,
    find(words) { open(); input.value = words; return find(words); },
    startPen, stopPen, penning: () => !!penCb,
    async explain(words) {
      open(); input.value = words; await find(words);
      results.querySelectorAll(".cs-sum").forEach((p) => { if (p.textContent === "Not in this paper.") p.remove(); }); // a formula rarely matches word for word
      results.querySelector(".cs-ask")?.click();
    },
  };
}
