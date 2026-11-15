"use strict";
// ---------- Dot's chibi form: the live persona drawn small and big-headed, from the look /char/chibi picked out of a web reference ----------
// drawChibi(g, x, y, R, spec, tint, k, t, alpha) draws the body at morph k (0 = still Dot's sphere of radius R at x,y; 1 = the chibi)
// and returns where its face is, {x, y, s, ink}: the caller draws Dot's own eyes there, s times their sphere size, in ink.
// Shared by web3d.js (/char) and verse.js (the persona planets).
function chibiShade(c, f) { const m = /^#?([0-9a-f]{6})$/i.exec(c || ""); if (!m) return c; const n = parseInt(m[1], 16);
  return "#" + [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f).toString(16).padStart(2, "0")).join(""); }
function drawChibi(g, x, y, R, spec, tint, k, t, alpha = 1) {
  const f = new Set(spec.features || []), mech = spec.kind === "mech", holo = f.has("holo") && !mech, beast = spec.kind === "creature";
  const suit = f.has("suit") && !mech, c1 = suit ? "#1d212b" : spec.colours?.[0] || (mech ? "#9aa3ad" : tint), // a butler wears black, whatever else his article mentions
    c2 = f.has("grey_hair") && !mech ? "#c3c7cf" : spec.colours?.[1] && !suit ? spec.colours[1] : (mech ? "#5d6670" : holo ? chibiShade(c1, -.45) : beast ? chibiShade(c1, -.3) : "#3b2a20");
  const pop = k < 1 ? 1 + 2.7 * (k - 1) ** 3 + 1.7 * (k - 1) ** 2 : 1; // ease-out-back: the limbs spring out of the sphere
  const hr = R * (1 - .38 * k), hx = x, hy = y - R * .3 * k, b = R * pop * k, top = hy + hr * .72, skin = holo ? chibiShade(c1, .35) : "#f3cfb3";
  const face = { x: hx, y: hy + hr * .1 * k, s: (hr / R) * (mech && f.has("optic") ? .72 : .9 + .1 * (1 - k)), ink: k > .5 && mech ? tint : "#06222a" };
  if (k < .01) return face;
  g.save(); g.globalAlpha = alpha * Math.min(1, k * 1.6) * (holo ? .8 + .08 * Math.sin(t * 2.1) : 1); g.lineJoin = g.lineCap = "round";
  const fill = (c, path) => { g.fillStyle = c; g.beginPath(); path(); g.fill(); };
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
