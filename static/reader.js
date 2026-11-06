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

async function renderReader(paperId) {
  const [fw, paper, saved] = await Promise.all([api("/framework"),
    api(`/papers/${paperId}?open=true`).catch(() => null), api(`/papers/${paperId}/notes`).catch(() => null)]);
  if (!paper || !saved) {
    view.className = "page page-library";
    view.append(h("div", { class: "library" }, h("h1", {}, "Paper not found"),
      h("p", { class: "quiet" }, "This paper is not in the library. It may have been deleted. ",
        h("a", { href: "#library" }, "Go to the Library"), ".")));
    return;
  }
  const notes = Object.fromEntries(fw.steps.map((st) => [st.id, noteFor(st, saved.steps[st.id])]));
  let current = fw.steps.find((st) => notes[st.id].state !== "done") ?? fw.steps[0];

  const done = h("span", { class: "num" }, `${saved.steps_done} / ${fw.steps.length}`);
  const hideBtn = h("button", { class: "btn ghost", type: "button", "aria-pressed": "false",
    onclick: () => pdf.setHidden(!pdf.hidden()) }, "Hide paper");
  $("#page-extra").append(
    h("a", { href: "#library", class: "paper-title", title: "Back to the Library" }, paper.title),
    h("span", { class: "quiet nowrap" }, done, " steps done"), hideBtn);

  const status = h("span", { class: "save-status", role: "status" });
  const queue = saveQueue(paperId, notes, status, (id, r) => {
    const was = notes[id].state;
    notes[id].state = r.state;
    done.textContent = `${r.steps_done} / ${r.total_steps}`;
    rail.paint(id);
    if (r.state === "done" && was !== "done" && openReader === me) {
      const st = fw.steps.find((x) => x.id === id);
      buddy.say(`Step ${st.n}, ${st.title}, is done. Nice work.`, { mood: "happy" });
    }
  });
  const pdf = pdfViewer(`/papers/${paperId}/pdf`, hideBtn);
  const rail = stepRail(fw, notes, (st) => open(st));
  const timer = stepTimer(() => notes[current.id], () => queue.touch(current.id));
  const body = h("div", { class: "nb-body" });
  const back = h("button", { type: "button", class: "btn ghost", onclick: () => open(fw.steps[idx() - 1]) }, "Back");
  const next = h("button", { type: "button", class: "btn", onclick: () => open(fw.steps[idx() + 1]) }, "Next step");
  const idx = () => fw.steps.indexOf(current);

  function open(st, pop = true) {
    timer.stop();
    queue.flush(); // the notes live in memory; this sends the last keystrokes now instead of in 500 ms
    current = st;
    rail.mark(st.id);
    pdf.autoHide(st.paper_hidden);
    body.replaceChildren(...notebook(st, notes[st.id], timer, () => queue.touch(st.id)));
    body.querySelectorAll("textarea").forEach(grow);
    body.scrollTop = 0;
    [...body.children].forEach((el, i) => el.style.setProperty("--i", i)); // staggered entrance
    back.disabled = idx() === 0;
    next.disabled = idx() === fw.steps.length - 1;
    if (TIMER_AUTOSTART) timer.start();
    stepTip(st, pop);
  }

  view.append(rail.el, pdf.el, splitter(view),
    h("section", { class: "notebook", "aria-label": "Notebook" }, body,
      h("footer", { class: "nb-foot" }, back, status, next)));
  open(current, !greeted.has("reader")); greeted.add("reader");

  // Saves (and retries) can finish after you leave; Dot only speaks while this Reader is open.
  const me = openReader = {
    leave() { timer.stop(); queue.flush(); pdf.destroy(); },
    flushOnExit() { queue.flushKeepalive(); },
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
function stepRail(fw, notes, onPick) {
  const el = h("ol", { class: "rail", "aria-label": "Reading steps" });
  const items = {};
  for (const st of fw.steps) {
    const circle = h("span", { class: "circle" }, String(st.n));
    const btn = h("button", { type: "button", onclick: () => onPick(st) },
      circle, h("span", { class: "label" }, st.title), h("span", { class: "num mins" }, `${st.minutes}m`));
    items[st.id] = { st, btn, circle };
    items[st.id].li = h("li", { class: "step" }, btn);
    el.append(items[st.id].li);
  }
  el.append(h("li", { class: "divider", "aria-hidden": "true" }),
    h("li", {}, h("button", { type: "button", disabled: true, title: "Comes in a later phase" },
      h("span", { class: "circle" }, "R"), h("span", { class: "label" }, "Review"))));
  const paint = (id) => {
    const { st, btn, circle, li } = items[id];
    circle.className = `circle ${notes[id].state}`;
    li.dataset.state = notes[id].state;
    btn.setAttribute("aria-label", `Step ${st.n}, ${st.title}, ${st.minutes} minutes, ${STATE_LABEL[notes[id].state]}`);
  };
  const mark = (id) => Object.values(items).forEach(({ st, btn }) => {
    btn.classList.toggle("active", st.id === id);
    if (st.id === id) { btn.setAttribute("aria-current", "step"); btn.scrollIntoView?.({ block: "nearest", inline: "nearest" }); }
    else btn.removeAttribute("aria-current");
  });
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
  };
  timer.onPaint(paint); paint();
  return h("div", { class: "budget" },
    h("div", { class: "row" }, h("span", {}, "Time budget"), h("span", { class: "timer-ctl" }, time, btn)),
    bar, over);
}

// ---------- notebook ----------
function notebook(st, note, timer, changed) {
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
    timerView(st, note, timer),
    ...st.fields.map((f) => fieldView(st, f, note.fields[f.id], set(f.id))),
    gateView(st, note, changed),
    oldFields(st, note.fields),
  ].filter(Boolean);
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

// Drag (or arrow keys) to trade width between the paper and the notes. Double-click resets.
const NB_KEY = "reader-notes-width";
function splitter(page) {
  const el = h("div", { class: "split", role: "separator", tabindex: 0, "aria-orientation": "vertical",
    "aria-label": "Notes width. Use the left and right arrow keys.", title: "Drag to resize. Double-click to reset." });
  const notesWidth = () => page.lastElementChild.getBoundingClientRect().width;
  const set = (w) => {
    if (w == null) { page.style.removeProperty("--nb-w"); localStorage.removeItem(NB_KEY); return; }
    const max = page.clientWidth - 232 - 320; // keep the rail and a usable paper
    w = Math.round(Math.max(340, Math.min(max, w)));
    page.style.setProperty("--nb-w", `${w}px`);
    el.setAttribute("aria-valuenow", w);
    localStorage.setItem(NB_KEY, w);
  };
  const saved = Number(localStorage.getItem(NB_KEY));
  if (saved) set(saved);
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing");
    const right = page.getBoundingClientRect().right;
    const move = (ev) => set(right - ev.clientX);
    const up = () => { el.removeEventListener("pointermove", move); document.body.classList.remove("resizing"); };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up, { once: true });
    el.addEventListener("pointercancel", up, { once: true });
  });
  el.addEventListener("keydown", (e) => {
    const d = { ArrowLeft: 32, ArrowRight: -32 }[e.key];
    if (d) { e.preventDefault(); set(notesWidth() + d); }
  });
  el.addEventListener("dblclick", () => set(null));
  return el;
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
    wrap = h("div", { class: `nb-field is-${f.type}` }, h("label", { for: id }, f.label), help, control);
  } else {
    wrap = h("fieldset", { class: `nb-field is-${f.type}`, "aria-describedby": helpId }, h("legend", {}, f.label), help, control);
  }
  wrap.classList.toggle("is-filled", filled(value));
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
function pdfViewer(url, hideBtn) {
  const v = { doc: null, page: 1, scale: 1, fit: true, task: null, seq: 0, hidden: false, auto: false };
  const sheet = h("div", { class: "pdf-sheet" });
  const stage = h("div", { class: "pdf-stage" }, sheet);
  const closed = h("div", { class: "pdf-closed", hidden: true },
    h("div", { class: "closed-card" },
      h("p", { class: "closed-title" }, "Paper closed"),
      h("p", { class: "quiet" }, "Explain it out loud first, then check."),
      h("button", { type: "button", class: "btn", onclick: () => setHidden(false) }, "Show the paper anyway")));
  const tool = (label, name, fn) => h("button", { type: "button", class: "btn ghost tool", "aria-label": name, title: name, onclick: fn }, label);
  const prev = tool("←", "Previous page", () => go(v.page - 1));
  const next = tool("→", "Next page", () => go(v.page + 1));
  const pageIn = h("input", { type: "number", class: "num", min: 1, value: 1, "aria-label": "Page number",
    onchange: () => go(Number(pageIn.value)) });
  const total = h("span", { class: "quiet num" }, "of 0");
  const zoomLbl = h("span", { class: "num quiet zoom" });
  const el = h("section", { class: "pdf-pane", "aria-label": "Paper" },
    h("div", { class: "pdf-tools" }, prev, pageIn, total, next, h("span", { class: "spacer" }),
      tool("−", "Zoom out", () => zoom(1 / 1.2)), zoomLbl, tool("+", "Zoom in", () => zoom(1.2)),
      h("button", { type: "button", class: "btn ghost tool", onclick: () => { v.fit = true; draw(); } }, "Fit width")),
    h("div", { class: "pdf-view" }, stage, closed));

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
    sheet.replaceChildren(canvas);
  }
  function go(n) {
    if (!v.doc) return;
    v.page = Math.min(v.doc.numPages, Math.max(1, Math.round(n) || v.page));
    draw();
  }
  function zoom(f) { v.fit = false; v.scale = Math.min(5, Math.max(0.25, v.scale * f)); draw(); }
  function setHidden(on, auto = false) {
    v.hidden = on; v.auto = on && auto;
    el.classList.toggle("is-closed", on);
    closed.hidden = !on;
    hideBtn.textContent = on ? "Show paper" : "Hide paper";
    hideBtn.setAttribute("aria-pressed", String(on));
  }
  const msg = (text) => sheet.replaceChildren(h("p", { class: "pdf-msg" }, text));

  const onKey = (e) => {
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
      v.doc = doc; total.textContent = `of ${doc.numPages}`; pageIn.max = doc.numPages; draw();
    }, () => msg("This PDF could not be opened."));
  }

  return {
    el, setHidden, hidden: () => v.hidden,
    // Self-test closes the paper when it opens; leaving it opens the paper again unless you closed it yourself.
    autoHide(on) { if (on) setHidden(true, true); else if (v.auto) setHidden(false); },
    destroy() { document.removeEventListener("keydown", onKey); ro.disconnect(); v.doc?.destroy(); },
  };
}
