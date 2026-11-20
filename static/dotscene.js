// Dot as a wireframe, for the Story's scroll: a sphere cut into contour rings, opened down the middle to show the four
// systems inside (S2 a net of plan nodes, S1 a ring of questions, S0 hands reaching out to the web, V the heart that
// lets notes in), with memory slots orbiting its head. Lines on a 2D canvas, no library: every shape is a list of
// 3D points, the camera eases between one keyframe per slide, and the live numbers set how many of each there are.
function makeDotScene(cv) {
  const g = cv.getContext("2d"), TAU = Math.PI * 2, SIG = "#ffe600";
  const SYSC = { 2: "#c79bff", 1: "#ffb347", 0: "#6ff7ff", 3: "#7dffa8" };
  const rnd = (s) => () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646; // fixed seeds: the brain keeps its shape between frames
  const R1 = rnd(7), BRAIN = [...Array(46)].map(() => { const a = R1() * TAU, u = R1() * 2 - 1, k = Math.cbrt(R1()) * .95, s = Math.sqrt(1 - u * u);
    return [Math.cos(a) * s * .46 * k, .42 + u * .2 * k, Math.sin(a) * s * .34 * k]; });
  const LINKS = BRAIN.flatMap((p, i) => BRAIN.map((q, j) => [j, Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])]).filter(([j]) => j !== i)
    .sort((a, b) => a[1] - b[1]).slice(0, 2).map(([j]) => [i, j]));
  const R2 = rnd(31), REACH = [...Array(24)].map(() => [R2() * TAU, (R2() - .5) * .9]);
  const RINGS = 24, SEG = 64;

  return { draw(now, k, live) {
    const dpr = Math.min(2, devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight;
    if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const t = now / 1000;
    // the camera, once a frame: it orbits a point on Dot's axis
    const cp = Math.cos(k.pitch), eye = [Math.sin(k.yaw) * cp * k.dist, k.ty + Math.sin(k.pitch) * k.dist, Math.cos(k.yaw) * cp * k.dist], at = [0, k.ty, 0];
    const nrm = (v) => { const l = Math.hypot(...v) || 1; return v.map((x) => x / l); }, cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const fw = nrm(at.map((x, i) => x - eye[i])), rt = nrm(cross(fw, [0, 1, 0])), up = cross(rt, fw), focal = H / (2 * Math.tan(.28));
    const P = (p) => { const v = [p[0] - eye[0], p[1] - eye[1], p[2] - eye[2]], z = v[0] * fw[0] + v[1] * fw[1] + v[2] * fw[2];
      if (z < .1) return null; const s = focal / z; return [W / 2 + (v[0] * rt[0] + v[1] * rt[1] + v[2] * rt[2]) * s, H * .44 - (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) * s, z]; };
    const turn = k.rot + t * .22 * k.spin, ct = Math.cos(turn), st = Math.sin(turn);
    const body = (x, y, z, cut = true) => { const sx = cut ? Math.sign(x || 1) * k.split * .9 : 0, X = x + sx; return [X * ct + z * st, y, -X * st + z * ct]; }; // open down the middle, then turned
    const face = (p, n) => { const v = nrm(eye.map((e, i) => e - p[i])); return n[0] * v[0] + n[1] * v[1] + n[2] * v[2]; };
    // the body: every short stretch of every ring sorted into four bands by how much it faces the camera, then stroked once a band
    const bands = [[], [], [], []], ALPHA = [.06, .14, .34, .7];
    for (let r = 1; r < RINGS; r++) {
      const y = -1 + 2 * r / RINGS, rr = Math.sqrt(1 - y * y); let prev = null;
      for (let j = 0; j <= SEG; j++) {
        const a = j / SEG * TAU, x = Math.cos(a) * rr, z = Math.sin(a) * rr, w = body(x, y, z), s = P(w);
        if (prev && s && (k.split < .01 || Math.sign(x || 1) === Math.sign(prev.x || 1))) { // a ring that crosses the cut breaks there
          const f = face(w, nrm([x * ct + z * st, y, -x * st + z * ct])); bands[f > .35 ? 3 : f > 0 ? 2 : f > -.45 ? 1 : 0].push(prev.s, s); }
        prev = { s, x };
      }
    }
    g.lineWidth = 1;
    bands.forEach((b, i) => { if (!b.length) return; g.strokeStyle = `rgba(255,255,255,${ALPHA[i]})`; g.beginPath();
      for (let n = 0; n < b.length; n += 2) { g.moveTo(b[n][0], b[n][1]); g.lineTo(b[n + 1][0], b[n + 1][1]); } g.stroke(); });
    const line = (pts, style, w = 1, dash = null) => { const s = pts.map(P); if (s.some((x) => !x)) return; g.strokeStyle = style; g.lineWidth = w; g.setLineDash(dash || []);
      g.beginPath(); s.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.stroke(); g.setLineDash([]); };
    // the cut face of each half, hatched, once it is open
    if (k.split > .03) for (const side of [-1, 1]) {
      const a = Math.min(1, k.split * 2) * .3;
      line([...Array(49)].map((_, j) => body(side * 1e-6, Math.cos(j / 48 * TAU), Math.sin(j / 48 * TAU))), `rgba(255,255,255,${a + .15})`);
      for (let r = 2; r < RINGS; r += 2) { const y = -1 + 2 * r / RINGS, rr = Math.sqrt(1 - y * y); line([body(side * 1e-6, y, -rr), body(side * 1e-6, y, rr)], `rgba(255,255,255,${a * .5})`); }
    }
    // its eyes, on the front, gone when it is opened
    if (k.eyes > .02) for (const sx of [-.3, .3]) {
      const fh = [Math.sin(k.yaw), 0, Math.cos(k.yaw)], rh = [Math.cos(k.yaw), 0, -Math.sin(k.yaw)]; // its eyes find you: they sit on the side facing the camera, whatever the body's turn
      const c = nrm(fh.map((f, i) => f * .93 + rh[i] * sx + (i === 1 ? .2 : 0))), tu = nrm(cross([0, 1, 0], c)), tv = cross(c, tu);
      line([...Array(33)].map((_, j) => { const a = j / 32 * TAU; return c.map((x, i) => x * 1.01 + tu[i] * Math.cos(a) * .1 + tv[i] * Math.sin(a) * .17); }), `rgba(255,255,255,${.9 * k.eyes})`, 1.6);
    }
    // the plinth: two circles and a ring of ticks that turns
    if (k.plinth > .02) { const y = -1.22, a = .5 * k.plinth;
      for (const r of [1.25, 1.42]) line([...Array(73)].map((_, j) => [Math.cos(j / 72 * TAU) * r, y, Math.sin(j / 72 * TAU) * r]), `rgba(255,255,255,${a})`);
      g.strokeStyle = `rgba(255,255,255,${a * .8})`; g.lineWidth = 1; g.beginPath();
      for (let j = 0; j < 96; j++) { const an = j / 96 * TAU + t * .05 * k.spin, l = j % 8 ? .07 : .16, p = P([Math.cos(an) * 1.45, y, Math.sin(an) * 1.45]), q = P([Math.cos(an) * (1.45 + l), y, Math.sin(an) * (1.45 + l)]);
        if (p && q) { g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); } } g.stroke(); }
    const work = (n) => live.sys === n ? .55 + .45 * Math.sin(t * 6) : 0; // the system at work this second pulses in the signal colour
    const tint = (n, a) => { const w = work(n); return w ? `rgba(255,230,0,${Math.max(a, w)})` : hexA(SYSC[n], a); };
    const labels = [];
    const label = (p3, text, sub, a, dx = 1) => { const p = P(p3); if (p && a > .05) labels.push([p, text, sub, a, dx]); };
    const show = (x) => Math.min(1, k.organs * .3 + x);
    // S2: a net of plan nodes in its head, joined to their nearest neighbours
    const b2 = show(k.brain) + work(2) * k.organs;
    if (b2 > .02) {
      const pts = BRAIN.map(([x, y, z]) => body(x, y, z, false));
      g.strokeStyle = tint(2, .5 * b2); g.lineWidth = 1; g.beginPath();
      LINKS.forEach(([i, j]) => { const p = P(pts[i]), q = P(pts[j]); if (p && q) { g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); } }); g.stroke();
      const lit = Math.min(BRAIN.length, live.plans || 0);
      pts.forEach((p3, i) => { const p = P(p3); if (!p) return; g.fillStyle = i < lit ? tint(2, b2) : `rgba(255,255,255,${.35 * b2})`; g.fillRect(p[0] - 1.5, p[1] - 1.5, 3, 3); });
      label(body(.5, .55, 0, false), "S2 planner", `${live.plans || 0} plan lines`, k.brain);
    }
    // S1: a ring of questions round its middle; the ones it answered are white, the open ones its colour
    const b1 = show(k.quest) + work(1) * k.organs;
    if (b1 > .02) { const n = Math.min(48, live.questions || 0), done = Math.min(n, live.answered || 0);
      for (let i = 0; i < n; i++) { const a = i * 2.39996 + t * .15, r = .3 + .32 * ((i * .618) % 1), p = P(body(Math.cos(a) * r, .05 + Math.sin(i * 1.7) * .05, Math.sin(a) * r, false));
        if (!p) continue; const tw = .6 + .4 * Math.sin(t * 3 + i); g.fillStyle = i < done ? `rgba(255,255,255,${.75 * b1 * tw})` : tint(1, b1 * tw); g.beginPath(); g.arc(p[0], p[1], i < done ? 1.6 : 2.4, 0, TAU); g.fill(); }
      line([...Array(65)].map((_, j) => body(Math.cos(j / 64 * TAU) * .66, .05, Math.sin(j / 64 * TAU) * .66, false)), tint(1, .35 * b1));
      label(body(.7, .1, 0, false), "S1 questions", `${live.questions || 0} asked · ${live.answered || 0} answered`, k.quest);
    }
    // S0: hands that reach out through it to the web, one for each note it wrote
    const b0 = show(k.hands) + work(0) * k.organs;
    if (b0 > .02) { const n = Math.min(REACH.length, live.notes || 0);
      for (let i = 0; i < REACH.length; i++) { const [a, y] = REACH[i], on = i < n, far = on ? 1.75 + .1 * Math.sin(t + i) : 1.15;
        const from = body(Math.cos(a) * .25, -.3, Math.sin(a) * .25, false), to = body(Math.cos(a) * far, -.3 + y, Math.sin(a) * far, false);
        line([from, to], on ? tint(0, .55 * b0) : `rgba(255,255,255,${.1 * b0})`, 1, on ? [3, 4] : null);
        const p = P(to); if (p && on) { g.strokeStyle = tint(0, .9 * b0); g.strokeRect(p[0] - 2.5, p[1] - 2.5, 5, 5); } }
      label(body(.3, -.3, 0, false), "S0 hands", `${live.notes || 0} notes from the web`, k.hands, -1);
    }
    // V: the heart, lofted from the classic curve in seven slices; it beats while it is the slide being told
    const bv = show(k.heart) + work(3) * k.organs;
    if (bv > .02) { const beat = 1 + .07 * k.heart * Math.max(0, Math.sin(t * 7)) ** 8, s = .2 * beat;
      for (let z = -3; z <= 3; z++) { const sc = Math.sqrt(1 - (z / 3.6) ** 2);
        line([...Array(41)].map((_, j) => { const a = j / 40 * TAU, hx = 16 * Math.sin(a) ** 3, hy = 13 * Math.cos(a) - 5 * Math.cos(2 * a) - 2 * Math.cos(3 * a) - Math.cos(4 * a);
          return body(hx / 17 * s * sc, -.5 + hy / 17 * s * sc, z * .035, false); }), tint(3, (z ? .35 : .95) * bv), z ? 1 : 1.6); }
      const out = Math.min(12, live.rejected || 0); // what it turned away falls out under it
      for (let i = 0; i < out; i++) { const f = (t * .25 + i / out) % 1, p = P(body(Math.sin(i * 2.1) * .25, -.75 - f * .9, Math.cos(i * 2.1) * .25, false));
        if (p) { g.fillStyle = `rgba(252,165,165,${(1 - f) * .7 * bv})`; g.fillRect(p[0] - 1.5, p[1] - 1.5, 3, 3); } }
      label(body(.3, -.5, 0, false), "V the gate", `${live.verified || 0} let in · ${live.rejected || 0} turned away`, k.heart);
    }
    // memory: two orbits of slots round its head, the open questions it keeps and the notes it trusts, 24 each
    if (k.memory > .02) [[1.2, .62, live.open || 0, 1], [1.5, .82, live.verified || 0, -1]].forEach(([r, y, n, dir], o) => {
      for (let i = 0; i < 24; i++) { const a = i / 24 * TAU + t * .12 * dir, p = P([Math.cos(a) * r, y, Math.sin(a) * r]); if (!p) continue;
        const sz = 5 * focal / p[2] / 120; g.globalAlpha = k.memory;
        if (i < Math.min(24, n)) { g.fillStyle = o ? "#fff" : SIG; g.fillRect(p[0] - sz / 2, p[1] - sz / 2, sz, sz); } else { g.strokeStyle = "rgba(255,255,255,.35)"; g.strokeRect(p[0] - sz / 2, p[1] - sz / 2, sz, sz); }
        g.globalAlpha = 1; }
      label([r * .7, y + .05, r * .7], o ? "kept for good" : "open questions", `${Math.min(24, n)} of 24`, k.memory, o ? 1 : -1);
    });
    // labels beside what they name, with a line to it
    g.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace"; g.textBaseline = "middle";
    for (let [p, text, sub, a, dx] of labels) {
      const wide = Math.max(g.measureText(text.toUpperCase()).width, g.measureText(sub).width) + 100;
      if (dx > 0 && p[0] + wide > W - 8) dx = -1; else if (dx < 0 && p[0] - wide < 8) dx = 1; // a label never leaves the frame
      const lx = p[0] + dx * 70, ly = p[1] - 34; g.globalAlpha = a;
      g.strokeStyle = "rgba(255,255,255,.5)"; g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(lx, ly); g.lineTo(lx + dx * 14, ly); g.stroke();
      g.fillStyle = "#fff"; g.textAlign = dx > 0 ? "left" : "right"; g.fillText(text.toUpperCase(), lx + dx * 20, ly - 7);
      g.fillStyle = "rgba(255,255,255,.62)"; g.fillText(sub, lx + dx * 20, ly + 8); g.globalAlpha = 1;
    }
  } };
  function hexA(hex, a) { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${Math.max(0, Math.min(1, a))})`; }
}
