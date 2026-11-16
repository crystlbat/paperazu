"use strict";
// ---------- Dot's chibi form: the live persona drawn small and big-headed, from the look /char/chibi picked out of a web reference ----------
// drawChibi(g, x, y, R, spec, tint, k, t, alpha) draws the body at morph k (0 = still Dot's sphere of radius R at x,y; 1 = the chibi)
// and returns where its face is, {x, y, s, ink}: the caller draws Dot's own eyes there, s times their sphere size, in ink.
// Shared by web3d.js (/char) and verse.js (the persona planets).
function chibiShade(c, f) { const m = /^#?([0-9a-f]{6})$/i.exec(c || ""); if (!m) return c; const n = parseInt(m[1], 16);
  return "#" + [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f).toString(16).padStart(2, "0")).join(""); }
// ---------- poured: Dot squeezed into a picture you picked ----------
// The picture's figure is cut from its background (its own transparency, or a flood from the edges), Dot's liquid fills it from the
// bottom up while the picture stays faint over it, and the eyes ride the rising surface until it passes the face, then spring into place.
const chibiCuts = new Map(); // picture url -> {img, mask, w, h, eye: {x, y, gap}} once loaded; null while loading
function chibiCut(src, outline) { // outline: the figure as traced with /trace, [[x, y], ...] in fractions of the picture
  const key = outline?.length > 2 ? src + "#" + outline.join(";") : src;
  if (chibiCuts.has(key)) return chibiCuts.get(key);
  chibiCuts.set(key, null); const img = new Image();
  img.onload = () => { const S = 256 / Math.max(img.width, img.height), w = Math.max(1, Math.round(img.width * S)), h = Math.max(1, Math.round(img.height * S));
    const c = document.createElement("canvas"); c.width = w; c.height = h; const x = c.getContext("2d", { willReadFrequently: true }); x.drawImage(img, 0, 0, w, h);
    const px = x.getImageData(0, 0, w, h), d = px.data, fg = new Uint8Array(w * h).fill(1), at = (i) => [d[i * 4], d[i * 4 + 1], d[i * 4 + 2], d[i * 4 + 3]];
    const clear = [0, w - 1, (h - 1) * w, h * w - 1].some((i) => at(i)[3] < 40);
    if (key !== src) { const m = document.createElement("canvas"); m.width = w; m.height = h; const mx = m.getContext("2d", { willReadFrequently: true }); mx.beginPath(); outline.forEach(([a, b]) => mx.lineTo(a * w, b * h)); mx.fill();
      const md = mx.getImageData(0, 0, w, h).data, q = []; for (let i = 0; i < w * h; i++) fg[i] = md[i * 4 + 3] > 127 && (!clear || d[i * 4 + 3] > 40) ? 1 : 0; // inside your outline is the figure
      for (let i = 0; i < w * h; i++) if (fg[i]) { const X = i % w; for (const j of [X > 0 ? i - 1 : -1, X < w - 1 ? i + 1 : -1, i - w, i + w]) if (j >= 0 && j < w * h && !fg[j]) { q.push(i, j); break; } } // then the background still inside it, where it runs smoothly in from the outline, goes too
      while (q.length) { const from = q.pop(), i = q.pop(); if (!fg[i] || Math.abs(d[i * 4] - d[from * 4]) + Math.abs(d[i * 4 + 1] - d[from * 4 + 1]) + Math.abs(d[i * 4 + 2] - d[from * 4 + 2]) > 24) continue; fg[i] = 0; const X = i % w;
        if (X > 0) q.push(i - 1, i); if (X < w - 1) q.push(i + 1, i); if (i >= w) q.push(i - w, i); if (i < w * (h - 1)) q.push(i + w, i); } }
    else if (clear) for (let i = 0; i < w * h; i++) fg[i] = d[i * 4 + 3] > 40 ? 1 : 0; // it has its own transparency: use it
    else { const diff = (i, j) => Math.abs(d[i * 4] - d[j * 4]) + Math.abs(d[i * 4 + 1] - d[j * 4 + 1]) + Math.abs(d[i * 4 + 2] - d[j * 4 + 2]), q = []; // grow the background in from the edges, step by step, so a gradient goes too
      for (let i = 0; i < w; i++) q.push(i, i, (h - 1) * w + i, (h - 1) * w + i); for (let j = 0; j < h; j++) q.push(j * w, j * w, j * w + w - 1, j * w + w - 1);
      while (q.length) { const from = q.pop(), i = q.pop(); if (!fg[i] || diff(i, from) > 24) continue; fg[i] = 0; const X = i % w;
        if (X > 0) q.push(i - 1, i); if (X < w - 1) q.push(i + 1, i); if (i >= w) q.push(i - w, i); if (i < w * (h - 1)) q.push(i + w, i); } }
    let top = h, bot = 0; const rows = []; for (let j = 0; j < h; j++) { let a = w, b = -1; for (let i = 0; i < w; i++) if (fg[j * w + i]) { a = Math.min(a, i); b = i; } rows.push([a, b]); if (b >= 0) { top = Math.min(top, j); bot = j; } }
    if (bot <= top) { chibiCuts.set(key, { img, mask: null, w, h }); return; }
    const H = bot - top; let neck = Math.round(top + H * .55), nw = w; // a chibi's head is its widest part up top; the neck is the narrowest row below it
    for (let j = Math.round(top + H * .3); j < top + H * .7; j++) { const r = rows[j]; if (r[1] >= 0 && r[1] - r[0] < nw) { nw = r[1] - r[0]; neck = j; } }
    const ey = Math.round(top + (neck - top) * .58), er = rows[ey][1] >= 0 ? rows[ey] : [0, w]; // eyes a little below the middle of the head
    for (let i = 0; i < w * h; i++) d[i * 4 + 3] = fg[i] ? d[i * 4 + 3] : 0; x.putImageData(px, 0, 0); // c is now the figure alone, background gone
    const eye = chibiEyes(d, fg, w, h, top, bot) || { x: (er[0] + er[1]) / 2, y: ey, gap: Math.max(6, (er[1] - er[0]) * .2) }; // its own painted eyes if it has them, else a guess from its head
    chibiCuts.set(key, { img: c, mask: c, w, h, top, bot, eye }); };
  img.onerror = () => chibiCuts.set(key, { img: null, mask: null });
  img.src = src; return null;
}
// the picture's own eyes: two dark blobs inside the figure, level with each other, alike in size, a little apart; null when there aren't two
function chibiEyes(d, fg, w, h, top, bot, glow = false) {
  const H = bot - top, dark = (i) => { if (!fg[i]) return false; const l = d[i * 4] * .3 + d[i * 4 + 1] * .59 + d[i * 4 + 2] * .11; return glow ? l > 200 : l < 70; }, seen = new Uint8Array(w * h), blobs = [];
  for (let j = top; j < top + H * .5; j++) for (let i = 0; i < w; i++) { const k0 = j * w + i; if (seen[k0] || !dark(k0)) continue;
    let n = 0, sx = 0, sy = 0, edge = false; const q = [k0]; seen[k0] = 1;
    while (q.length) { const k = q.pop(), X = k % w, Y = (k / w) | 0; n++; sx += X; sy += Y;
      for (const m of [X > 0 ? k - 1 : -1, X < w - 1 ? k + 1 : -1, k - w, k + w]) { if (m < 0 || m >= w * h) continue; if (!fg[m]) edge = true; else if (!seen[m] && dark(m)) { seen[m] = 1; q.push(m); } } }
    if (!edge && n >= H * H * .0015 && n < H * H * .03) blobs.push({ x: sx / n, y: sy / n, n }); } // an outline touches the background; an eye sits inside
  let best = null;
  for (const a of blobs) for (const b of blobs) { const dx = b.x - a.x; if (dx < w * .05 || dx > w * .5 || Math.abs(a.y - b.y) > H * .05 || Math.max(a.n, b.n) > 3 * Math.min(a.n, b.n)) continue;
    const sc = a.n + b.n - Math.abs(a.y - b.y); if (!best || sc > best.sc) best = { sc, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, gap: dx / 2 }; }
  return best ? { x: best.x, y: best.y, gap: best.gap } : glow ? null : chibiEyes(d, fg, w, h, top, bot, true); // no dark eyes: try glowing ones (a visor, a mask's lenses)
}
// the picture in its own colours at Dot's size, for the dot cloud to sample; its face where its eyes are. null while it loads
function drawFlat(g, x, y, R, spec) {
  const cut = chibiCut(spec.silhouette, spec.cuts?.[spec.silhouette]); if (!cut?.mask) return null;
  const sc = (R * 2.7) / (cut.bot - cut.top), ox = x - cut.eye.x * sc, oy = y + R - cut.bot * sc;
  g.drawImage(cut.img, ox, oy, cut.w * sc, cut.h * sc);
  const mk = spec.eyes?.[spec.silhouette], eyes = mk?.length === 2 ? mk.map((e) => ({ x: ox + e.x * cut.w * sc, y: oy + e.y * cut.h * sc, r: e.r * cut.w * sc })) : null; // the eyes you marked with /align-eyes
  const eye = eyes ? { x: (eyes[0].x + eyes[1].x) / 2, y: (eyes[0].y + eyes[1].y) / 2, gap: Math.abs(eyes[1].x - eyes[0].x) / 2 / sc } : { x: ox + cut.eye.x * sc, y: oy + cut.eye.y * sc, gap: cut.eye.gap };
  return { x: eye.x, y: eye.y, s: (eye.gap * sc) / (R * .256), ink: "#fff", eyes };
}
function drawPoured(g, x, y, R, spec, tint, k, t, alpha) {
  const cut = chibiCut(spec.silhouette, spec.cuts?.[spec.silhouette]), face = { x, y, s: 1, ink: "#06222a" };
  if (!cut?.mask || k < .01) return face;
  const sc = (R * 2.7) / (cut.bot - cut.top), w = cut.w * sc, h = cut.h * sc, ox = x - (cut.eye.x * sc), oy = y + R - cut.bot * sc; // its feet where the sphere's bottom was, centred on its face
  const level = oy + (cut.bot - (cut.bot - cut.top) * Math.min(1, k * 1.08)) * sc; // the liquid's surface, rising as it pours in
  g.save(); g.globalAlpha = alpha * .28 * Math.min(1, k * 3); g.drawImage(cut.img, ox, oy, w, h); // the picture, faint
  g.beginPath(); g.moveTo(ox, oy + h); for (let i = 0; i <= 24; i++) g.lineTo(ox + w * i / 24, level + Math.sin(i * .9 + t * 3) * R * .04 * (1 - k)); g.lineTo(ox + w, oy + h); g.closePath(); g.clip();
  const L = chibiCuts.get(spec.silhouette + "#" + tint) || (() => { const c = document.createElement("canvas"); c.width = cut.w; c.height = cut.h; const q = c.getContext("2d");
    const gr = q.createRadialGradient(cut.w * .4, cut.top + (cut.bot - cut.top) * .25, 2, cut.w / 2, (cut.top + cut.bot) / 2, cut.h * .7); gr.addColorStop(0, "#ffffff"); gr.addColorStop(.25, tint); gr.addColorStop(1, "#0d3a42");
    q.fillStyle = gr; q.fillRect(0, 0, cut.w, cut.h); q.globalCompositeOperation = "destination-in"; q.drawImage(cut.mask, 0, 0); chibiCuts.set(spec.silhouette + "#" + tint, c); return c; })();
  g.globalAlpha = alpha * .82; g.drawImage(L, ox, oy, w, h); // Dot's liquid, in the figure's shape
  g.globalAlpha = alpha * .3; g.globalCompositeOperation = "overlay"; g.drawImage(cut.img, ox, oy, w, h); g.restore(); // the picture's lines show through it
  const ex = ox + cut.eye.x * sc, ey = oy + cut.eye.y * sc, s = (cut.eye.gap * sc) / (R * .256), now = performance.now();
  if (level > ey) { spec._eyesAt = 0; return { x: ex + Math.sin(t * 2.2) * cut.eye.gap * sc * .8, y: Math.max(level, ey), s: s * .8, ink: face.ink }; } // riding the surface, looking about
  spec._eyesAt ||= now; const dt = (now - spec._eyesAt) / 1000, wob = Math.exp(-dt * 4) * Math.cos(dt * 16); // the surface passed the face: they spring into place
  return { x: ex + wob * cut.eye.gap * sc * .5, y: ey - wob * R * .06, s: s * (1 + wob * .25), ink: face.ink };
}
function drawChibi(g, x, y, R, spec, tint, k, t, alpha = 1, line = false) { // line: hairline outlines over black, as the story draws (the /char mesh)
  if (spec.silhouette) return drawPoured(g, x, y, R, spec, tint, k, t, alpha);
  const f = new Set(spec.features || []), mech = spec.kind === "mech", holo = f.has("holo") && !mech, beast = spec.kind === "creature";
  const suit = f.has("suit") && !mech, c1 = suit ? "#1d212b" : spec.colours?.[0] || (mech ? "#9aa3ad" : tint), // a butler wears black, whatever else his article mentions
    c2 = f.has("grey_hair") && !mech ? "#c3c7cf" : spec.colours?.[1] && !suit ? spec.colours[1] : (mech ? "#5d6670" : holo ? chibiShade(c1, -.45) : beast ? chibiShade(c1, -.3) : "#3b2a20");
  const pop = k < 1 ? 1 + 2.7 * (k - 1) ** 3 + 1.7 * (k - 1) ** 2 : 1; // ease-out-back: the limbs spring out of the sphere
  const hr = R * (1 - .38 * k), hx = x, hy = y - R * .3 * k, b = R * pop * k, top = hy + hr * .72, skin = holo ? chibiShade(c1, .35) : "#f3cfb3";
  const face = { x: hx, y: hy + hr * .1 * k, s: (hr / R) * (mech && f.has("optic") ? .72 : .9 + .1 * (1 - k)), ink: k > .5 && mech ? tint : "#06222a" };
  if (k < .01) return face;
  g.save(); g.globalAlpha = alpha * Math.min(1, k * 1.6) * (holo ? .8 + .08 * Math.sin(t * 2.1) : 1); g.lineJoin = g.lineCap = "round";
  const fill = (c, path) => { g.fillStyle = line ? "#000" : c; g.beginPath(); path(); g.fill(); if (line) { g.strokeStyle = "#fff"; g.lineWidth = 1; g.stroke(); } };
  if (f.has("cape")) fill(c2, () => { g.moveTo(hx - b * .32, top + b * .05); g.lineTo(hx + b * .32, top + b * .05); g.lineTo(hx + b * .55, top + b * .78); g.quadraticCurveTo(hx, top + b * .9, hx - b * .55, top + b * .78); });
  if (f.has("wings")) for (const s of [-1, 1]) fill(chibiShade(c1, .4), () => g.ellipse(hx + s * b * .5, top + b * .2, b * .32, b * .16, s * -.5, 0, 6.283));
  if (f.has("tail") || beast) { g.strokeStyle = c1; g.lineWidth = b * .1; g.beginPath(); g.moveTo(hx + b * .25, top + b * .5); g.quadraticCurveTo(hx + b * .75, top + b * .55, hx + b * .6, top + b * .1 + Math.sin(t * 3) * b * .05); g.stroke(); }
  // legs and feet, then the body
  for (const s of [-1, 1]) fill(mech ? c2 : chibiShade(c1, -.25), () => g.roundRect(hx + s * b * .2 - b * .1, top + b * .5, b * .2, b * .26, b * .06));
  for (const s of [-1, 1]) fill(mech ? "#3d444c" : chibiShade(c2, -.2), () => g.ellipse(hx + s * b * .2, top + b * .78, b * .15, b * .08, 0, 0, 6.283));
  if (mech) { fill(c1, () => { g.moveTo(hx - b * .58, top); g.lineTo(hx + b * .58, top); g.lineTo(hx + b * .36, top + b * .58); g.lineTo(hx - b * .36, top + b * .58); }); // a titan's hull: broad at the shoulders
    fill(c2, () => g.rect(hx - b * .36, top + b * .3, b * .72, b * .07)); fill(tint, () => g.arc(hx, top + b * .18, b * .07, 0, 6.283));
    for (const s of [-1, 1]) { fill(c2, () => g.roundRect(hx + s * b * .6 - b * .14, top - b * .06, b * .28, b * .24, b * .05)); fill(c1, () => g.roundRect(hx + s * b * .62 - b * .09, top + b * .14, b * .18, b * .4, b * .06)); } }
  else { fill(c1, () => g.roundRect(hx - b * .3, top, b * .6, b * .56, [b * .22, b * .22, b * .12, b * .12]));
    for (const s of [-1, 1]) fill(beast ? c1 : skin, () => g.ellipse(hx + s * b * .37, top + b * .25 + Math.sin(t * 1.5 + s) * b * .02, b * .09, b * .2, s * -.35, 0, 6.283));
    if (suit) fill("#f4f4f5", () => { g.moveTo(hx - b * .13, top + b * .02); g.lineTo(hx + b * .13, top + b * .02); g.lineTo(hx, top + b * .34); }); // the white shirt front between the lapels
    if (f.has("bowtie")) fill(suit ? "#0b0d12" : c2, () => { g.moveTo(hx, top + b * .06); g.lineTo(hx - b * .12, top - b * .01); g.lineTo(hx - b * .12, top + b * .13); g.lineTo(hx + b * .12, top - b * .01); g.lineTo(hx + b * .12, top + b * .13); g.closePath(); }); }
  if (f.has("circuits") || holo) { g.strokeStyle = chibiShade(tint, .5); g.lineWidth = Math.max(1, b * .018); g.beginPath(); g.moveTo(hx - b * .18, top + b * .1); g.lineTo(hx - b * .05, top + b * .22); g.lineTo(hx - b * .05, top + b * .45); g.moveTo(hx + b * .16, top + b * .08); g.lineTo(hx + b * .08, top + b * .3); g.stroke(); }
  // the head: Dot's sphere settles into it
  if (f.has("horns")) for (const s of [-1, 1]) fill(c2, () => { g.moveTo(hx + s * hr * .35, hy - hr * .75); g.lineTo(hx + s * hr * .7, hy - hr * 1.25); g.lineTo(hx + s * hr * .62, hy - hr * .6); });
  if (f.has("ears") || beast) for (const s of [-1, 1]) fill(c1, () => { g.moveTo(hx + s * hr * .25, hy - hr * .8); g.lineTo(hx + s * hr * .78, hy - hr * 1.18); g.lineTo(hx + s * hr * .9, hy - hr * .35); });
  if (f.has("hair_long") && !mech) fill(c2, () => g.roundRect(hx - hr * 1.02, hy - hr * .4, hr * 2.04, hr * 1.55, hr * .5));
  if (mech) { fill(c1, () => g.roundRect(hx - hr * .95, hy - hr * .8, hr * 1.9, hr * 1.55, hr * .32));
    fill("#12161c", () => g.roundRect(hx - hr * .72, hy - hr * .42, hr * 1.44, hr * 1.02, hr * .22)); // the face plate Dot looks out of
    if (f.has("optic")) { g.strokeStyle = tint; g.lineWidth = hr * .08; g.globalAlpha *= .9; g.beginPath(); g.arc(face.x, face.y, hr * .4, 0, 6.283); g.stroke(); g.globalAlpha /= .9; } }
  else { const gr = g.createRadialGradient(hx - hr * .3, hy - hr * .35, hr * .1, hx, hy, hr); gr.addColorStop(0, "#fff"); gr.addColorStop(.35, beast ? c1 : skin); gr.addColorStop(1, chibiShade(beast ? c1 : skin, -.35));
    fill(gr, () => g.arc(hx, hy, hr, 0, 6.283)); }
  if (f.has("helmet")) fill(c2, () => { g.arc(hx, hy, hr * 1.04, Math.PI * 1.05, Math.PI * 1.95); g.closePath(); });
  else if (f.has("grey_hair") && !mech) for (const s2 of [-1, 1]) fill(c2, () => g.ellipse(hx + s2 * hr * .9, hy - hr * .15, hr * .2, hr * .38, s2 * .3, 0, 6.283)); // receding: grey at the temples
  else if (!mech && (!beast || f.has("hair_short") || f.has("hair_long"))) fill(c2, () => { // a fringe over the top of the head, swept to one side
    g.arc(hx, hy, hr * 1.03, Math.PI * .95, Math.PI * 2.05); g.quadraticCurveTo(hx + hr * .5, hy - hr * .5, hx - hr * .1, hy - hr * .35); g.quadraticCurveTo(hx - hr * .6, hy - hr * .2, hx - hr * 1.03, hy - hr * .05); });
  if (f.has("antenna") || mech) { g.strokeStyle = c2; g.lineWidth = hr * .06; g.beginPath(); g.moveTo(hx + hr * .5, hy - hr * .78); g.lineTo(hx + hr * .62, hy - hr * 1.15); g.stroke(); fill(tint, () => g.arc(hx + hr * .62, hy - hr * 1.15, hr * .07, 0, 6.283)); }
  if (f.has("moustache") && !mech) fill(c2, () => { const my = face.y + hr * .38; g.ellipse(hx - hr * .17, my, hr * .2, hr * .07, .25, 0, 6.283); g.ellipse(hx + hr * .17, my, hr * .2, hr * .07, -.25, 0, 6.283); });
  if (f.has("visor")) { g.globalAlpha *= .45; fill(tint, () => g.roundRect(hx - hr * .8, face.y - hr * .3, hr * 1.6, hr * .5, hr * .25)); g.globalAlpha /= .45; }
  if (holo) { g.globalAlpha = alpha * k * .16; g.fillStyle = "#fff"; for (let sy = hy - hr * 1.1 + (t * 6) % 6; sy < top + b * .86; sy += 6) g.fillRect(hx - b * .7, sy, b * 1.4, 1.2); // scanlines: it is a projection
    g.globalAlpha = alpha * k * .5; g.strokeStyle = tint; g.lineWidth = 1.5; g.beginPath(); g.arc(hx, hy, hr + 3, 0, 6.283); g.stroke(); }
  g.restore();
  return face;
}
