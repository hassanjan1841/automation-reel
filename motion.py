"""Premium 2D explainer animations for point slides, rendered as transparent frames in headless Chromium.

Each animation is SVG drawn by our own small engine (eases, a spring, a timeline, glow, a light sweep), seeked to
t = frame / FPS and screenshotted, the way scene3d.py renders three.js; nothing is downloaded and every frame is
the same on every run. The page also reports its natural length, the moment its layout is complete (`settle`, so
it can sit under a hook from frame 0) and the moments of its sounds, so effects land on the frame things arrive.
Rules from the research (playbook.md): one change at a time with a hold after it, the active part glows and the
rest dims, moves of 0.25 to 0.6 s, a soft spring that settles without bouncing, one light sweep at most, the same
thing always in the same colour. Abstract shapes only: boxes, dots, arrows, code. No faces, people or animals.

Types (fields in generate.VISUAL_SCHEMA, limits in generate.visual_errors):
  stepper    code run line by line; a panel shows the variables changing      language, code, trace
  flow       a request travelling between parts, a label at each hop          nodes, hops
  morph      before code turns into after code; unchanged tokens glide         language, title, before, after
  git        commits on branch lanes, then a merge or a rebase replay          commits, op, head, base
  eventloop  cards moving between call stack, Web APIs, queues and console     cards
  structure  array, stack, queue or map changing step by step                  structure, items, ops
  sequence   messages between parts over time; a failed one turns red          actors, calls
  states     a state machine walked event by event                              states, moves
  race       bars growing to real numbers from a cited page                     title, unit, bars, source
  xray       a zoom into one part to show what is inside                        nodes, focus, inside
  memory     variables pointing at objects; references move, orphans dim       refs, objects, reassign
  outputmap  a real command's output lines lift out into a diagram              command, output
  kinetic    the takeaway in big type, word by word, the key word underlined     lines, tag
  statement  short lines rising in over a drifting gradient and glass panels   lines
  quotes     real posts typed onto dark cards, then stacked into a pile         quotes

Usage: python motion.py <type> [light|dark]   renders the built-in example to out/motion-<type>.mp4
"""

import base64
import difflib
import hashlib
import json
import re
import subprocess
import sys

import render

TYPES = ('stepper', 'flow', 'morph', 'git', 'eventloop', 'structure', 'sequence', 'states', 'race', 'xray',
         'memory', 'outputmap', 'kinetic', 'statement', 'quotes')
FRAMES = render.OUT_DIR / 'motion'
FPS = render.FPS
MAX_SECONDS = 12.0

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent;overflow:hidden}svg{display:block;width:100vw;height:100vh}
text{font-family:Poppins;dominant-baseline:alphabetic;white-space:pre}.mono{font-family:'JetBrains Mono'}
</style></head><body><svg id="stage" xmlns="http://www.w3.org/2000/svg"></svg><script>
const P = window.PARAMS, S = P.spec, W = P.w, H = P.h;
const C = {panel: '#1E2230', bar: '#161A25', text: '#E6E9F2', dim: '#8A91A5', line: 'rgba(230,233,242,0.18)',
  green: '#3FB950', red: '#E5534B', amber: '#E3A33B', accent: P.accent};
// Text and lines drawn straight on the reel's background follow its theme (dark panels keep C.text and C.dim).
const rgba = (hex, a) => `rgba(${[1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)).join(',')},${a})`;
Object.assign(C, {ink: P.ink, mute: P.muted, guide: rgba(P.ink, 0.22), track: rgba(P.ink, 0.08)});
const NS = 'http://www.w3.org/2000/svg', svg = document.getElementById('stage');
svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
function mk(tag, a = {}, parent = svg) { const e = document.createElementNS(NS, tag);
  for (const k in a) e.setAttribute(k, a[k]); parent.appendChild(e); return e; }
svg.innerHTML = `<defs>
<filter id="glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="9"/></filter>
<filter id="shadow" x="-20%" y="-20%" width="140%" height="170%"><feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#000" flood-opacity="0.32"/></filter>
<filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3"/></filter>
<linearGradient id="sweep" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="0.5" stop-color="#fff" stop-opacity="0.22"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>`;
const ROOT = mk('g'), L0 = mk('g', {}, ROOT), L1 = mk('g', {}, ROOT), L2 = mk('g', {}, ROOT), L3 = mk('g', {}, ROOT);  // edges, nodes, labels, dots

// ---------- engine: eases, a spring, a timeline that is seeked frame by frame ----------
const clamp = x => Math.max(0, Math.min(1, x));
const lerp = (a, b, p) => a + (b - a) * p;
const E = {
  out: p => 1 - Math.pow(1 - p, 3),
  inout: p => p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2,
  lin: p => p,
  // A damped spring (damping ratio 0.82): it lands with about 1% overshoot and settles, never bounces.
  spring: p => { if (p >= 1) return 1; const z = 0.82, w = 2 * Math.PI * 1.35, t = p * 1.6, wd = w * Math.sqrt(1 - z * z);
    return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + z * w / wd * Math.sin(wd * t)); },
};
const TW = [], SND = []; let SETTLE = 0, END = 0, FIT = null;  // FIT: what to fit into the box when ROOT holds clipped overflow
function at(start, dur, fn, ease = E.out) { TW.push({start, dur, fn, ease}); END = Math.max(END, start + dur); }
function set(t, fn) { at(t, 0, p => p && fn()); }
function snd(t, kind) { SND.push([Math.round(t * 1000) / 1000, kind]); }
window.renderAt = t => { for (const w of TW) { if (t < w.start) continue;
  const p = w.dur <= 0 ? 1 : clamp((t - w.start) / w.dur); w.fn(w.ease(p), p); } };
const sortTW = () => TW.sort((a, b) => a.start - b.start);

// ---------- building blocks ----------
function fade(e, t, d = 0.35, a = 0, b = 1) { at(t, d, p => e.setAttribute('opacity', lerp(a, b, p))); }
function pop(g, t, cx, cy, d = 0.5) { at(t, d, (p, raw) => {
  const s = lerp(0.88, 1, p); g.setAttribute('transform', `translate(${cx} ${cy}) scale(${s}) translate(${-cx} ${-cy})`);
  g.setAttribute('opacity', Math.min(1, raw * 2.2)); }, E.spring); }
function moveTo(g, t, d, x0, y0, x1, y1, ease = E.spring) { at(t, d, p =>
  g.setAttribute('transform', `translate(${lerp(x0, x1, p)} ${lerp(y0, y1, p)})`), ease); }
function txt(parent, x, y, s, size, a = {}) { const e = mk('text', {x, y, 'font-size': size, fill: C.text,
  'font-weight': 600, ...a}, parent); e.textContent = s; return e; }
function fit(e, maxw) { let s = +e.getAttribute('font-size');
  while (e.getComputedTextLength() > maxw && s > 14) { s -= 2; e.setAttribute('font-size', s); } return e; }
function panel(parent, x, y, w, h, a = {}) { return mk('rect', {x, y, width: w, height: h, rx: 22, fill: C.panel,
  stroke: C.line, 'stroke-width': 2, filter: 'url(#shadow)', ...a}, parent); }
// A labelled box: shadowed panel, an accent halo that glows when it is the active part.
function node(x, y, w, h, label, size = 34) {
  const g = mk('g', {opacity: 0}, L1);
  const halo = mk('rect', {x: x - 4, y: y - 4, width: w + 8, height: h + 8, rx: 26, fill: 'none', stroke: C.accent,
    'stroke-width': 6, opacity: 0, filter: 'url(#glow)'}, g);
  const ring = mk('rect', {x, y, width: w, height: h, rx: 22, fill: 'none', stroke: C.accent, 'stroke-width': 3, opacity: 0}, g);
  const r = panel(g, x, y, w, h);
  g.insertBefore(r, halo);
  const t = fit(txt(g, x + w / 2, y + h / 2 + size * 0.36, label, size, {'text-anchor': 'middle'}), w - 28);
  return {g, r, t, halo, ring, x, y, w, h, cx: x + w / 2, cy: y + h / 2};
}
function glow(n, t, on = 1, d = 0.3) { const a = on ? 0 : 1, b = on ? 1 : 0;
  at(t, d, p => { n.halo.setAttribute('opacity', lerp(a, b, p) * 0.75); n.ring.setAttribute('opacity', lerp(a, b, p)); }); }
function dim(e, t, to = 0.4, d = 0.3, from = 1) { fade(e, t, d, from, to); }
// Where the segment between two boxes' centres leaves each box.
function exits(a, b) { const dx = b.cx - a.cx, dy = b.cy - a.cy;
  const clip = (n, sx, sy) => { const k = Math.min(Math.abs((n.w / 2 + 10) / (sx || 1e-9)), Math.abs((n.h / 2 + 10) / (sy || 1e-9)));
    return [n.cx + sx * k, n.cy + sy * k]; };
  return [...clip(a, dx, dy), ...clip(b, -dx, -dy)]; }
function line(d, a = {}) { const p = mk('path', {d, fill: 'none', stroke: C.guide, 'stroke-width': 4, 'stroke-linecap': 'round', ...a}, L0);
  const len = p.getTotalLength(); p.setAttribute('stroke-dasharray', len); p.setAttribute('stroke-dashoffset', len);
  return {p, len}; }
function draw(l, t, d = 0.45) { at(t, d, p => l.p.setAttribute('stroke-dashoffset', l.len * (1 - p)), E.inout); }
function arrowHead(x1, y1, x2, y2, color, parent = L0) { const a = Math.atan2(y2 - y1, x2 - x1), s = 16;
  return mk('path', {d: `M${x2} ${y2} L${x2 - s * Math.cos(a - 0.45)} ${y2 - s * Math.sin(a - 0.45)} L${x2 - s * Math.cos(a + 0.45)} ${y2 - s * Math.sin(a + 0.45)} Z`,
    fill: color, opacity: 0}, parent); }
// A glowing dot with a short trail, travelling along a path.
function pulse(path, t, d = 0.7, color = C.accent, reverse = false) {
  const len = path.getTotalLength();
  const dots = [0, 1, 2, 3].map(i => mk('circle', {r: 13 - i * 2.6, fill: color, opacity: 0}, L3));
  const halo = mk('circle', {r: 26, fill: color, opacity: 0, filter: 'url(#glow)'}, L3);
  at(t, d, (p, raw) => { dots.forEach((c, i) => { const q = clamp(p - i * 0.05), pt = path.getPointAtLength((reverse ? 1 - q : q) * len);
      c.setAttribute('cx', pt.x); c.setAttribute('cy', pt.y); c.setAttribute('opacity', raw >= 1 ? 0 : (1 - i * 0.24)); });
    const pt = path.getPointAtLength((reverse ? 1 - p : p) * len);
    halo.setAttribute('cx', pt.x); halo.setAttribute('cy', pt.y); halo.setAttribute('opacity', raw >= 1 ? 0 : 0.55); }, E.inout);
}
function pill(parent, cx, cy, s, size = 28, color = C.accent, textColor = '#fff') {
  const g = mk('g', {opacity: 0}, parent);
  const t = txt(g, cx, cy + size * 0.36, s, size, {'text-anchor': 'middle', fill: textColor});
  const w = t.getComputedTextLength() + 34, h = size * 1.6;
  const r = mk('rect', {x: cx - w / 2, y: cy - h / 2, width: w, height: h, rx: h / 2, fill: color}, g); g.insertBefore(r, t);
  return {g, w, h, cx, cy};
}
// One light sweep across a box, once per animation at most.
function sweep(x, y, w, h, t) { const clip = mk('clipPath', {id: 'sw' + t}, svg.querySelector('defs'));
  mk('rect', {x, y, width: w, height: h, rx: 22}, clip);
  const r = mk('rect', {x: x - w, y, width: w * 0.6, height: h, fill: 'url(#sweep)', 'clip-path': `url(#sw${t})`, opacity: 0}, L3);
  at(t, 0.9, (p, raw) => { r.setAttribute('x', lerp(x - w * 0.6, x + w, p)); r.setAttribute('opacity', raw >= 1 ? 0 : 1); }, E.inout); }
// A code window from tokens [[text, colour]] per line; returns where each line sits.
function codeWindow(x, y, w, lines, title = '', maxSize = 40) {
  const cols = Math.max(8, ...lines.map(l => l.reduce((n, t) => n + t[0].length, 0)));
  const size = Math.min(maxSize, Math.floor((w - 90) / (cols * 0.6))), lh = Math.round(size * 1.6), bar = 56;
  const h = bar + 30 + lh * lines.length + 26, g = mk('g', {opacity: 0}, L1);
  panel(g, x, y, w, h); mk('rect', {x, y, width: w, height: bar, rx: 22, fill: C.bar}, g);
  mk('rect', {x, y: y + bar - 22, width: w, height: 22, fill: C.bar}, g);
  ['#FF5F57', '#FEBC2E', '#28C840'].forEach((c, i) => mk('circle', {cx: x + 34 + i * 30, cy: y + bar / 2, r: 9, fill: c}, g));
  if (title) txt(g, x + w / 2, y + bar / 2 + 9, title, 24, {'text-anchor': 'middle', fill: C.dim, 'font-weight': 500});
  const hl = mk('rect', {x: x + 6, y: y + bar + 30, width: w - 12, height: lh, fill: C.accent, opacity: 0}, g);
  const hlEdge = mk('rect', {x: x + 6, y: y + bar + 30, width: 6, height: lh, fill: C.accent, opacity: 0}, g);
  const rows = lines.map((toks, i) => { const ty = y + bar + 30 + i * lh + lh / 2 + size * 0.36;
    const t = mk('text', {x: x + 40, y: ty, 'font-size': size, class: 'mono', 'font-weight': 500, 'xml:space': 'preserve'}, g);
    toks.forEach(([s, c]) => { const sp = mk('tspan', {fill: c}, t); sp.textContent = s; }); return t; });
  return {g, x, y, w, h, size, lh, rows, hl, hlEdge, top: y + bar + 30,
    lineY: i => y + bar + 30 + i * lh, cw: size * 0.6};
}

// ---------- templates ----------
const T = {};

T.stepper = () => {
  const lines = S.tokens, trace = S.trace;
  const names = [...new Set(trace.flatMap(s => (s.vars || []).map(v => v.name)))];
  const rowH = 74, outN = trace.filter(s => s.out).length;
  const ph = 70 + Math.max(1, names.length) * rowH + (outN ? 70 + outN * 46 : 0);
  // The code shrinks (down to 24 px) until the code and the variables panel both fit the box.
  const cols = Math.max(8, ...lines.map(l => l.reduce((n, t) => n + t[0].length, 0)));
  let maxSize = 40;
  while (maxSize > 24) { const size = Math.min(maxSize, Math.floor((W - 90) / (cols * 0.6)));
    if (56 + 30 + Math.round(size * 1.6) * lines.length + 26 + 36 + ph <= H - 8) break; maxSize -= 2; }
  const cw = codeWindow(0, 0, W, lines, S.title || '', maxSize);
  pop(cw.g, 0, W / 2, cw.h / 2, 0.5); SETTLE = 0.5;
  const top = cw.h + 36;
  const pg = mk('g', {opacity: 0}, L1); panel(pg, 0, top, W, Math.min(ph, H - top));
  txt(pg, 34, top + 48, 'Variables', 26, {fill: C.dim, 'font-weight': 500});
  pop(pg, 0.25, W / 2, top + ph / 2, 0.5);
  const cells = {};
  names.forEach((n, i) => { const y = top + 70 + i * rowH;
    const g = mk('g', {opacity: 0}, L2); txt(g, 34, y + 44, n, 34, {class: 'mono', fill: C.accent});
    cells[n] = {g, y, cur: null, x: 34 + Math.max(160, n.length * 22 + 40)}; });
  let outY = top + 70 + names.length * rowH + 30;
  if (outN) txt(pg, 34, outY + 18, 'Console', 26, {fill: C.dim, 'font-weight': 500});
  outY += 46;
  const step = 1.3; let t = 0.9;
  trace.forEach((s, k) => {
    const ly = cw.lineY(s.line - 1);
    if (k === 0) { set(t, () => { cw.hl.setAttribute('y', ly); cw.hlEdge.setAttribute('y', ly); });
      fade(cw.hl, t, 0.3, 0, 0.16); fade(cw.hlEdge, t, 0.3, 0, 1); }
    else { const py = cw.lineY(trace[k - 1].line - 1);
      at(t, 0.35, p => { const y = lerp(py, ly, p); cw.hl.setAttribute('y', y); cw.hlEdge.setAttribute('y', y); }, E.inout); }
    snd(t, 'tick');
    (s.vars || []).forEach((v, j) => { const c = cells[v.name], tv = t + 0.3 + j * 0.06;
      if (c.cur === null) pop(c.g, tv, 120, c.y + 30, 0.4);
      const e = txt(L2, c.x, c.y + 44, v.value, 34, {class: 'mono', opacity: 0}); fit(e, W - c.x - 40);
      const old = c.cur;
      if (old) { at(tv, 0.35, (p, raw) => { old.setAttribute('opacity', 1 - raw); old.setAttribute('transform', `translate(0 ${-26 * p})`); }); }
      at(tv, 0.4, (p, raw) => { e.setAttribute('opacity', Math.min(1, raw * 1.6)); e.setAttribute('transform', `translate(0 ${26 * (1 - p)})`); });
      if (old) { const flash = mk('rect', {x: c.x - 14, y: c.y + 6, width: W - c.x - 30, height: 56, rx: 12, fill: C.green, opacity: 0}, L1);
        at(tv, 0.9, (p, raw) => flash.setAttribute('opacity', 0.28 * Math.sin(Math.PI * raw))); }
      c.cur = e; });
    if (s.out) { const e = txt(L2, 34, outY + 10, s.out, 32, {class: 'mono', fill: C.green, opacity: 0}); fit(e, W - 70);
      fade(e, t + 0.35, 0.3); snd(t + 0.35, 'pop'); outY += 46; }
    t += step;
  });
  END = Math.max(END, t + 0.6);
};

T.flow = () => {
  const ns = S.nodes, n = ns.length, cols = n <= 3 ? n : Math.ceil(n / 2), rows = Math.ceil(n / cols);
  const bw = Math.min(300, (W - (cols - 1) * 70) / cols), bh = 150, gx = (W - cols * bw) / Math.max(1, cols - 1 || 1);
  const rowGap = rows > 1 ? Math.min(330, (H - 120 - rows * bh) / (rows - 1) + bh) : 0;
  const by = {};
  ns.forEach((d, i) => { const r = Math.floor(i / cols), c = r % 2 ? cols - 1 - (i % cols) : i % cols;
    const x = cols === 1 ? (W - bw) / 2 : c * (bw + gx), y = 70 + r * rowGap;
    by[d.id] = node(x, y, bw, bh, d.label, 40); });
  ns.forEach((d, i) => { pop(by[d.id].g, 0.1 + i * 0.12, by[d.id].cx, by[d.id].cy); snd(0.1 + i * 0.12, 'pop'); });
  const paths = {}; let t = 0.15 + n * 0.12;
  S.hops.forEach(h => { const key = [h.from, h.to].sort().join('|'); if (paths[key]) return;
    const [x1, y1, x2, y2] = exits(by[h.from], by[h.to]); paths[key] = {l: line(`M${x1} ${y1} L${x2} ${y2}`), from: h.from};
    draw(paths[key].l, t, 0.4); t += 0.12; });
  SETTLE = t + 0.3; t += 0.5;
  const labels = [];
  S.hops.forEach((h, k) => { const key = [h.from, h.to].sort().join('|'), pth = paths[key];
    const rev = pth.from !== h.from; pulse(pth.l.p, t, 0.7, C.accent, rev); snd(t, 'swish');
    const dst = by[h.to]; glow(dst, t + 0.6, 1, 0.25); if (k) glow(by[S.hops[k - 1].to], t + 0.6, 0, 0.25);
    if (h.label) { const mid = pth.l.p.getPointAtLength(pth.l.len / 2);
      const pl = pill(L2, mid.x, mid.y - 52, h.label, 32, k === S.hops.length - 1 ? C.accent : '#2B3142');
      pop(pl.g, t + 0.55, mid.x, mid.y - 52, 0.4); snd(t + 0.6, 'tick');
      labels.forEach(o => dim(o.g, t + 0.55, 0.45, 0.3)); labels.push(pl); }
    t += 1.15; });
  END = Math.max(END, t + 0.5);
};

T.morph = () => {
  const toks = S.toks, size = S.size, lh = Math.round(size * 1.6), bar = 56, cw = size * 0.6;
  const h = bar + 30 + lh * S.rows + 26, g = mk('g', {opacity: 1}, L1);
  panel(g, 0, 0, W, h); mk('rect', {x: 0, y: 0, width: W, height: bar, rx: 22, fill: C.bar}, g);
  mk('rect', {x: 0, y: bar - 22, width: W, height: 22, fill: C.bar}, g);
  ['#FF5F57', '#FEBC2E', '#28C840'].forEach((c, i) => mk('circle', {cx: 34 + i * 30, cy: bar / 2, r: 9, fill: c}, g));
  if (S.title) txt(g, W / 2, bar / 2 + 9, S.title, 24, {'text-anchor': 'middle', fill: C.dim, 'font-weight': 500});
  const X = c => 40 + c * cw, Y = l => bar + 30 + l * lh + lh / 2 + size * 0.36;
  const bands = S.added_lines.map(l => mk('rect', {x: 6, y: bar + 30 + l * lh, width: W - 12, height: lh, fill: C.green, opacity: 0}, g));
  const rbands = S.removed_lines.map(l => mk('rect', {x: 6, y: bar + 30 + l * lh, width: W - 12, height: lh, fill: C.red, opacity: 0}, g));
  SETTLE = 0; const t0 = 1.0;
  rbands.forEach(b => at(t0, 0.9, (p, raw) => b.setAttribute('opacity', 0.16 * Math.sin(Math.PI * raw))));
  toks.forEach(k => { const e = mk('text', {'font-size': size, class: 'mono', 'font-weight': 500, fill: k.color,
      'xml:space': 'preserve'}, L2); e.textContent = k.text;
    if (k.from) { e.setAttribute('x', X(k.from[1])); e.setAttribute('y', Y(k.from[0])); }
    if (k.from && k.to) { at(t0 + 0.35, 0.6, p => { e.setAttribute('x', lerp(X(k.from[1]), X(k.to[1]), p));
        e.setAttribute('y', lerp(Y(k.from[0]), Y(k.to[0]), p)); }, E.inout); }
    else if (k.from) { at(t0, 0.4, (p, raw) => { e.setAttribute('fill', C.red); e.setAttribute('opacity', 1 - raw);
        e.setAttribute('text-decoration', 'line-through'); }); }
    else { e.setAttribute('x', X(k.to[1])); e.setAttribute('y', Y(k.to[0])); e.setAttribute('opacity', 0);
      at(t0 + 0.8, 0.45, (p, raw) => { e.setAttribute('opacity', raw); e.setAttribute('fill', raw < 1 ? C.green : k.color);
        e.setAttribute('transform', `translate(0 ${10 * (1 - p)})`); }); } });
  bands.forEach(b => at(t0 + 0.8, 0.5, p => b.setAttribute('opacity', 0.14 * p)));
  snd(t0, 'tick'); snd(t0 + 0.35, 'swish'); snd(t0 + 0.85, 'pop');
  sweep(0, 0, W, h, t0 + 1.6);
  END = Math.max(END, t0 + 3.2);
};

T.git = () => {
  const cs = S.commits, lanes = [...new Set(cs.map(c => c.branch))];
  if (S.op !== 'none' && !lanes.includes(S.base)) lanes.unshift(S.base);
  const extra = S.op === 'none' ? 0 : (S.op === 'merge' ? 1 : cs.filter(c => c.branch === S.head).length);
  const slots = cs.length + extra, laneGap = Math.min(220, (H - 160) / Math.max(1, lanes.length - 1 || 1));
  const x0 = 170, dx = Math.min(150, (W - x0 - 60) / Math.max(1, slots - 1)), ly = b => 90 + lanes.indexOf(b) * laneGap;
  lanes.forEach((b, i) => { const l = line(`M${x0 - 30} ${ly(b)} L${W - 20} ${ly(b)}`, {stroke: C.track, 'stroke-width': 3});
    draw(l, 0.05 + i * 0.1, 0.5); const lab = txt(L2, 0, ly(b) + 10, b, 28, {fill: C.mute, opacity: 0}); fit(lab, x0 - 50); fade(lab, 0.1 + i * 0.1); });
  const pos = {}, last = {}, laneCol = b => [C.accent, '#58A6FF', C.amber, C.green][lanes.indexOf(b) % 4];
  const dot = (x, y, color, label, t, ghost = false, parent = L1) => { const g = mk('g', {opacity: 0}, parent);
    mk('circle', {cx: x, cy: y, r: 22, fill: C.panel, stroke: color, 'stroke-width': 6, ...(ghost ? {'stroke-dasharray': '6 6'} : {})}, g);
    if (label) fit(txt(g, x, y - 38, label, 24, {'text-anchor': 'middle', class: 'mono', fill: ghost ? C.mute : C.ink, 'font-weight': 500}), dx * 1.6);
    pop(g, t, x, y, 0.45); return g; };
  const link = (a, b, t, color) => { const l = line(a[1] === b[1] ? `M${a[0] + 24} ${a[1]} L${b[0] - 24} ${b[1]}`
      : `M${a[0]} ${a[1] + (b[1] > a[1] ? 24 : -24)} C${a[0]} ${b[1]} ${a[0]} ${b[1]} ${b[0] - 24} ${b[1]}`, {stroke: color, 'stroke-width': 5}); draw(l, t, 0.35); return l; };
  let t = 0.5;
  cs.forEach((c, i) => { const x = x0 + i * dx, y = ly(c.branch); pos[c.id] = [x, y];
    const prev = last[c.branch] || (lanes.indexOf(c.branch) > 0 ? last[lanes[0]] : null);
    if (prev) link(prev, [x, y], t - 0.1, laneCol(c.branch));
    pos[c.id].push(dot(x, y, laneCol(c.branch), c.id, t)); snd(t, 'pop'); last[c.branch] = [x, y]; t += 0.32; });
  SETTLE = t; t += 0.6;
  if (S.op === 'merge') { const x = x0 + cs.length * dx, y = ly(S.base);
    link(last[S.base] || last[lanes[0]], [x, y], t, laneCol(S.base)); link(last[S.head], [x, y], t, laneCol(S.head));
    snd(t, 'swish'); const g = dot(x, y, C.accent, 'merge', t + 0.35); snd(t + 0.4, 'pop');
    const halo = mk('circle', {cx: x, cy: y, r: 34, fill: C.accent, opacity: 0, filter: 'url(#glow)'}, L0);
    at(t + 0.4, 1.0, (p, raw) => halo.setAttribute('opacity', 0.6 * Math.sin(Math.PI * raw))); t += 1.6; }
  if (S.op === 'rebase') { let tip = last[S.base] || last[lanes[0]], k = 0;
    cs.filter(c => c.branch === S.head).forEach(c => { const [ox, oy] = pos[c.id];
      const x = x0 + (cs.length + k) * dx, y = ly(S.base);
      const wrap = mk('g', {transform: `translate(${ox} ${oy})`}, L1);
      dot(0, 0, laneCol(S.head), c.id + "'", t, false, wrap);
      at(t, 0.65, p => wrap.setAttribute('transform', `translate(${lerp(ox, x, p)} ${lerp(oy, y, p)})`), E.inout); link(tip, [x, y], t + 0.55, laneCol(S.head)); snd(t, 'swish'); snd(t + 0.6, 'pop');
      dim(pos[c.id][2], t + 0.1, 0.3, 0.4);  // the original stays, faded: rebase copies commits, it does not move them
      tip = [x, y]; k++; t += 0.85; });
    t += 0.6; }
  END = Math.max(END, t + 0.6);
};

T.eventloop = () => {
  const names = {stack: 'Call stack', apis: 'Web APIs', micro: 'Microtasks', macro: 'Task queue'};
  const pw = (W - 30) / 2, logH = 170, ph = Math.min(330, (H - logH - 60) / 2);
  const lanes = {}; let i = 0;
  for (const k of ['stack', 'apis', 'micro', 'macro']) { const x = (i % 2) * (pw + 30), y = Math.floor(i / 2) * (ph + 30);
    const g = mk('g', {opacity: 0}, L1); panel(g, x, y, pw, ph); txt(g, x + 26, y + 46, names[k], 28, {fill: C.dim, 'font-weight': 500});
    const n = {g, x, y, w: pw, h: ph, count: 0, halo: mk('rect', {x: x - 4, y: y - 4, width: pw + 8, height: ph + 8, rx: 26, fill: 'none', stroke: C.accent, 'stroke-width': 6, opacity: 0, filter: 'url(#glow)'}, L0),
      ring: mk('rect', {x, y, width: pw, height: ph, rx: 22, fill: 'none', stroke: C.accent, 'stroke-width': 3, opacity: 0}, L2)};
    lanes[k] = n; pop(g, 0.05 + i * 0.08, x + pw / 2, y + ph / 2); i++; }
  const ly0 = 2 * (ph + 30), lg = mk('g', {opacity: 0}, L1); panel(lg, 0, ly0, W, logH);
  txt(lg, 26, ly0 + 46, 'Console', 28, {fill: C.dim, 'font-weight': 500}); pop(lg, 0.4, W / 2, ly0 + logH / 2);
  SETTLE = 0.7; let t = 1.0, logs = 0; const cards = {}, slot = (k, n) => [lanes[k].x + 24, lanes[k].y + 70 + n * 64];
  let active = null;
  S.cards.forEach(c => { const lane = c.lane;
    if (active && active !== lane && lanes[active]) glow(lanes[active], t, 0, 0.25);
    if (lane === 'log') { const e = txt(L2, 26, ly0 + 100 + logs * 46, c.label, 32, {class: 'mono', fill: C.green, opacity: 0}); fit(e, W - 60);
      if (cards[c.label]) { const k = cards[c.label]; fade(k.g, t, 0.3, 1, 0); lanes[k.lane].count--; delete cards[c.label]; }
      fade(e, t + 0.15, 0.35); snd(t + 0.15, 'pop'); logs++; t += 0.85; active = null; return; }
    if (lane === 'done') { const k = cards[c.label]; if (k) { fade(k.g, t, 0.35, 1, 0); lanes[k.lane].count--; delete cards[c.label]; } snd(t, 'tick'); t += 0.6; return; }
    const [x, y] = slot(lane, lanes[lane].count); lanes[lane].count++;
    let k = cards[c.label];
    if (!k) { const g = mk('g', {opacity: 0}, L2); const r = mk('rect', {x: 0, y: 0, width: pw - 48, height: 52, rx: 14, fill: '#2B3142', stroke: C.accent, 'stroke-width': 2}, g);
      fit(txt(g, 18, 36, c.label, 28, {class: 'mono', 'font-weight': 500}), pw - 84); void r;
      g.setAttribute('transform', `translate(${x} ${y})`); fade(g, t, 0.3); k = cards[c.label] = {g, x, y, lane}; snd(t, 'pop'); }
    else { lanes[k.lane].count--; moveTo(k.g, t, 0.6, k.x, k.y, x, y); snd(t, 'swish'); k.x = x; k.y = y; k.lane = lane; }
    glow(lanes[lane], t + 0.1, 1, 0.25); active = lane; t += 0.85; });
  END = Math.max(END, t + 0.6);
};

T.structure = () => {
  const kind = S.structure, ops = S.ops, vertical = kind === 'stack';
  const items = S.items.map(String), maxN = Math.max(items.length, items.length + ops.filter(o => ['push', 'insert'].includes(o.op)).length, 1);
  const cell = vertical ? Math.min(110, (H - 120) / maxN) : Math.min(170, (W - 20) / maxN), gap = 14;
  const rowW = maxN * cell + (maxN - 1) * gap;
  const cells = [], place = i => vertical ? [W / 2 - 170, H - 40 - (i + 1) * (cell + gap)] : [(W - rowW) / 2 + i * (cell + gap), H / 2 - cell / 2];
  if (kind === 'map') { return T.map(); }
  const make = (v, i, t) => { const [x, y] = place(i), w = vertical ? 340 : cell, h = cell;
    const g = mk('g', {opacity: 0}, L1); panel(g, 0, 0, w, h, {rx: 18});
    fit(txt(g, w / 2, h / 2 + 13, v, 36, {'text-anchor': 'middle', class: 'mono'}), w - 20);
    g.setAttribute('transform', `translate(${x} ${y - 40})`); at(t, 0.5, (p, raw) => { g.setAttribute('opacity', Math.min(1, raw * 2));
      g.setAttribute('transform', `translate(${x} ${lerp(y - 40, y, p)})`); }, E.spring);
    const idx = vertical ? null : txt(L2, x + w / 2, y + h + 40, String(i), 24, {'text-anchor': 'middle', fill: C.mute, opacity: 0});
    if (idx) fade(idx, t + 0.1, 0.3); return {g, x, y, w, h, idx}; };
  items.forEach((v, i) => cells.push(make(v, i, 0.1 + i * 0.08)));
  const label = txt(L2, vertical ? W / 2 + 190 : (W - rowW) / 2, vertical ? H - 60 : H / 2 - cell / 2 - 40, {stack: 'top ↑', queue: 'front', array: ''}[kind] || '', 26, {fill: C.mute, opacity: 0});
  fade(label, 0.4); SETTLE = 0.3 + items.length * 0.08; let t = SETTLE + 0.6;
  const relayout = (from, t) => cells.forEach((c, i) => { if (i < from) return; const [x, y] = place(i);
    moveTo(c.g, t, 0.45, c.x, c.y, x, y); if (c.idx) { const e = c.idx, ox = c.x; at(t, 0.45, p => e.setAttribute('x', lerp(ox + c.w / 2, x + c.w / 2, p)), E.spring);
      set(t + 0.2, () => { e.textContent = String(i); }); } c.x = x; c.y = y; });
  ops.forEach(o => { const op = o.op;
    if (op === 'push' || op === 'insert') { const i = op === 'insert' ? Math.min(+o.at || 0, cells.length) : cells.length;
      const c = make(String(o.value), i, t + 0.15); cells.splice(i, 0, c); relayout(i + 1, t); glowCell(c, t + 0.5); snd(t + 0.2, 'pop'); }
    else if (op === 'pop' || op === 'remove') { const i = op === 'remove' ? Math.min(+o.at || 0, cells.length - 1) : (kind === 'queue' ? 0 : cells.length - 1);
      const c = cells.splice(i, 1)[0]; if (c) { at(t, 0.45, (p, raw) => { c.g.setAttribute('opacity', 1 - raw);
          c.g.setAttribute('transform', `translate(${c.x} ${c.y - 60 * p})`); }); if (c.idx) fade(c.idx, t, 0.3, 1, 0); snd(t, 'swish'); relayout(i, t + 0.3); } }
    t += 1.15; });
  function glowCell(c, t) { const h = mk('rect', {x: c.x - 6, y: c.y - 6, width: c.w + 12, height: c.h + 12, rx: 22, fill: 'none', stroke: C.accent, 'stroke-width': 5, opacity: 0, filter: 'url(#glow)'}, L0);
    at(t, 1.0, (p, raw) => h.setAttribute('opacity', 0.8 * Math.sin(Math.PI * raw))); }
  END = Math.max(END, t + 0.5);
};

T.map = () => {
  const B = 4, rowH = Math.min(150, (H - 40) / B), g0 = mk('g', {}, L1), slots = Array(B).fill(0);
  for (let b = 0; b < B; b++) { const g = mk('g', {opacity: 0}, g0); panel(g, 0, b * rowH, W, rowH - 18, {rx: 18});
    txt(g, 24, b * rowH + (rowH - 18) / 2 + 10, `bucket ${b}`, 26, {fill: C.dim, 'font-weight': 500, class: 'mono'}); pop(g, 0.05 + b * 0.08, W / 2, b * rowH + rowH / 2); }
  const hash = s => [...s].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7) % B;
  const put = (k, v, t) => { const b = hash(k), x = 200 + slots[b] * 250, y = b * rowH + (rowH - 18) / 2;
    const pl = pill(L2, x + 110, y, `${k}: ${v}`, 26, '#2B3142'); at(t, 0.55, (p, raw) => { pl.g.setAttribute('opacity', Math.min(1, raw * 2));
      pl.g.setAttribute('transform', `translate(0 ${-40 * (1 - p)})`); }, E.spring); slots[b]++; snd(t, 'pop'); return pl; };
  S.items.forEach((it, i) => { const [k, v] = String(it).split(':').map(s => s.trim()); put(k, v ?? '', 0.4 + i * 0.12); });
  SETTLE = 0.5 + S.items.length * 0.12; let t = SETTLE + 0.5;
  S.ops.forEach(o => { put(String(o.at), String(o.value), t); t += 1.1; });
  END = Math.max(END, t + 0.5);
};

T.sequence = () => {
  const as = S.actors, n = as.length, colW = W / n, top = 20, hh = 90;
  const xs = as.map((a, i) => colW * i + colW / 2);
  as.forEach((a, i) => { const nd = node(xs[i] - Math.min(130, colW / 2 - 10), top, Math.min(260, colW - 20), hh, a, 30); pop(nd.g, 0.05 + i * 0.1, xs[i], top + hh / 2);
    const l = line(`M${xs[i]} ${top + hh + 8} L${xs[i]} ${H - 10}`, {'stroke-dasharray': '10 12', 'stroke-width': 3}); l.p.setAttribute('stroke-dasharray', '10 12');
    l.p.setAttribute('stroke-dashoffset', 0); l.p.setAttribute('opacity', 0); fade(l.p, 0.2 + i * 0.1, 0.4); });
  SETTLE = 0.3 + n * 0.1; let t = SETTLE + 0.4;
  const gap = Math.min(170, (H - top - hh - 80) / Math.max(1, S.calls.length));
  S.calls.forEach((c, k) => { const a = as.indexOf(c.from), b = as.indexOf(c.to), y = top + hh + 60 + k * gap;
    const x1 = xs[a] + (b > a ? 8 : -8), x2 = xs[b] + (b > a ? -8 : 8), color = c.fail ? C.red : C.accent;
    const l = line(`M${x1} ${y} L${x2} ${y}`, {stroke: color, 'stroke-width': 5}); draw(l, t, 0.45);
    const head = arrowHead(x1, y, x2, y, color); fade(head, t + 0.4, 0.1);
    const lab = txt(L2, (x1 + x2) / 2, y - 18, c.label, 32, {'text-anchor': 'middle', opacity: 0, fill: c.fail ? C.red : C.ink}); fit(lab, Math.abs(x2 - x1) - 10);
    fade(lab, t + 0.2, 0.35); snd(t, c.fail ? 'thud' : 'swish');
    if (c.fail) { const xg = txt(L2, x2 + (b > a ? -40 : 40), y + 12, '×', 44, {'text-anchor': 'middle', fill: C.red, opacity: 0}); fade(xg, t + 0.45, 0.2);
      at(t + 0.45, 0.35, (p, raw) => xg.setAttribute('transform', `translate(${8 * Math.sin(raw * Math.PI * 6) * (1 - raw)} 0)`), E.lin); }
    t += 0.9; });
  END = Math.max(END, t + 0.6);
};

T.states = () => {
  const st = S.states, n = st.length, by = {};
  const R = Math.min(W, H) * 0.34, cx = W / 2, cy = H / 2, bw = Math.min(280, W / Math.min(n, 3) - 40), bh = 110;
  st.forEach((s, i) => { let x, y; if (n <= 3) { x = (W / n) * i + (W / n - bw) / 2; y = cy - bh / 2; }
    else { const a = -Math.PI / 2 + i * 2 * Math.PI / n; x = cx + R * Math.cos(a) * 1.15 - bw / 2; y = cy + R * Math.sin(a) - bh / 2; }
    by[s] = node(x, y, bw, bh, s, 36); pop(by[s].g, 0.05 + i * 0.1, x + bw / 2, y + bh / 2); });
  SETTLE = 0.2 + n * 0.1; glow(by[st[0]], SETTLE, 1, 0.3); let cur = st[0], t = SETTLE + 0.7, k = 0;
  S.moves.forEach(m => { const a = by[cur], b = by[m.to]; if (!b || b === a) return;
    const [x1, y1, x2, y2] = exits(a, b), mx = (x1 + x2) / 2, my = (y1 + y2) / 2, nx = -(y2 - y1), ny = x2 - x1, nl = Math.hypot(nx, ny) || 1;
    const bend = 70 * (k % 2 ? -1 : 1), qx = mx + nx / nl * bend, qy = my + ny / nl * bend;
    const l = line(`M${x1} ${y1} Q${qx} ${qy} ${x2} ${y2}`, {stroke: C.accent, 'stroke-width': 4}); draw(l, t, 0.45);
    const hd = arrowHead(qx, qy, x2, y2, C.accent); fade(hd, t + 0.4, 0.1);
    const pl = pill(L2, qx, qy, m.event, 30, '#2B3142'); pop(pl.g, t + 0.2, qx, qy, 0.4);
    pulse(l.p, t + 0.45, 0.5); snd(t, 'swish'); glow(a, t + 0.85, 0, 0.25); glow(b, t + 0.9, 1, 0.3); snd(t + 0.9, 'pop');
    dim(l.p, t + 1.2, 0.45, 0.3); dim(pl.g, t + 1.2, 0.5, 0.3); cur = m.to; k++; t += 1.35; });
  END = Math.max(END, t + 0.5);
};

T.race = () => {
  const bars = S.bars, max = Math.max(...bars.map(b => b.value)), n = bars.length;
  const labW = 230, rowH = Math.min(140, (H - 150) / n), bh = rowH * 0.56, x0 = labW + 20, maxW = W - x0 - 150;
  if (S.title) { const tt = txt(L2, 0, 40, S.title, 34, {fill: C.ink, opacity: 0}); fit(tt, W); fade(tt, 0); }
  bars.forEach((b, i) => { const y = 80 + i * rowH, w = Math.max(6, maxW * b.value / max);
    const lab = txt(L2, labW, y + bh / 2 + 11, b.label, 30, {'text-anchor': 'end', fill: C.ink, opacity: 0}); fit(lab, labW - 10); fade(lab, 0.1 + i * 0.08);
    mk('rect', {x: x0, y, width: maxW, height: bh, rx: bh / 2, fill: C.track}, L0);
    const r = mk('rect', {x: x0, y, width: 0, height: bh, rx: bh / 2, fill: i === 0 ? C.accent : '#58A6FF'}, L1);
    const dec = (String(b.value).split('.')[1] || '').length, t = 0.5 + i * 0.15;
    // The final value is set up front (hidden) so the layout fit makes room for it at the end of the longest bar.
    const v = txt(L2, x0 + w + 14, y + bh / 2 + 11, b.value.toFixed(dec) + (S.unit ? ' ' + S.unit : ''), 30,
                  {class: 'mono', fill: C.ink, opacity: 0});
    at(t, 1.1, (p, raw) => { r.setAttribute('width', Math.max(bh, w * p)); v.setAttribute('x', x0 + Math.max(bh, w * p) + 14);
      v.textContent = (b.value * p).toFixed(dec) + (S.unit ? ' ' + S.unit : ''); v.setAttribute('opacity', Math.min(1, raw * 3)); });
    snd(t, 'tick'); });
  const src = txt(L2, 0, 80 + n * rowH + 30, 'Source: ' + S.source_host, 22, {fill: C.mute, 'font-weight': 500, opacity: 0}); fade(src, 0.6);
  SETTLE = 0.4; sweep(x0, 80, maxW, n * rowH - (rowH - bh), 2.2); END = Math.max(END, 3.6);
};

T.xray = () => {
  const ns = S.nodes, n = ns.length, bw = Math.min(260, (W - (n - 1) * 60) / n), bh = 130, gx = n > 1 ? (W - n * bw) / (n - 1) : 0, y = H / 2 - bh / 2;
  const by = {}, scene = mk('g', {}, ROOT); [L0, L1, L2, L3].forEach(l => scene.appendChild(l));
  ns.forEach((d, i) => { by[d.id] = node(i * (bw + gx), y, bw, bh, d.label, 30); pop(by[d.id].g, 0.05 + i * 0.1, by[d.id].cx, by[d.id].cy); });
  for (let i = 1; i < n; i++) { const [x1, y1, x2, y2] = exits(by[ns[i - 1].id], by[ns[i].id]); draw(line(`M${x1} ${y1} L${x2} ${y2}`), 0.3 + i * 0.1); }
  SETTLE = 0.4 + n * 0.1; const f = by[S.focus], t = SETTLE + 0.6; glow(f, t - 0.3, 1, 0.3); snd(t - 0.3, 'pop');
  const k = Math.min(W / (bw + 80), (H - 40) / (bh + 120)) * 0.92, tx = W / 2 - f.cx * k, ty = H / 2 - f.cy * k;
  at(t, 0.8, p => scene.setAttribute('transform', `translate(${lerp(0, tx, p)} ${lerp(0, ty, p)}) scale(${lerp(1, k, p)})`), E.inout);
  snd(t, 'swish');
  ns.forEach(d => { if (d.id !== S.focus) dim(by[d.id].g, t, 0.15, 0.6); });
  at(t + 0.5, 0.35, (p, raw) => f.t.setAttribute('opacity', 1 - raw));
  const inner = S.inside, m = inner.length, pw = (bw - 24), ph = Math.min(30, (bh - 20) / m - 6);
  inner.forEach((s, i) => { const g = mk('g', {opacity: 0}, L2); const yy = f.y + 12 + i * ((bh - 20) / m);
    mk('rect', {x: f.x + 12, y: yy, width: pw, height: ph, rx: 8, fill: '#2B3142', stroke: C.accent, 'stroke-width': 0.8}, g);
    fit(txt(g, f.cx, yy + ph * 0.72, s, ph * 0.62, {'text-anchor': 'middle', 'font-weight': 500}), pw - 10);
    fade(g, t + 0.8 + i * 0.12, 0.3); snd(t + 0.8 + i * 0.12, 'tick'); });
  END = Math.max(END, t + 1.2 + m * 0.12 + 1.2);
};

T.memory = () => {
  const vars = S.refs.map(r => r.name), objs = S.objects, colW = W * 0.36, rowH = Math.min(120, (H - 90) / Math.max(vars.length, objs.length));
  txt(L2, 0, 34, 'Stack', 28, {fill: C.mute, 'font-weight': 500}); txt(L2, W - colW, 34, 'Heap', 28, {fill: C.mute, 'font-weight': 500});
  const V = {}, O = {}; vars.forEach((v, i) => { V[v] = node(0, 60 + i * rowH, colW, rowH - 24, v, 32); V[v].t.setAttribute('class', 'mono'); pop(V[v].g, 0.05 + i * 0.08, colW / 2, 60 + i * rowH); });
  objs.forEach((o, i) => { O[o.id] = node(W - colW, 60 + i * rowH, colW, rowH - 24, o.label, 28); pop(O[o.id].g, 0.2 + i * 0.08, W - colW / 2, 60 + i * rowH); });
  const curve = (a, b) => { const x1 = a.x + a.w + 8, y1 = a.cy, x2 = b.x - 14, y2 = b.cy; return `M${x1} ${y1} C${x1 + 160} ${y1} ${x2 - 160} ${y2} ${x2} ${y2}`; };
  const arrows = {}, refs = {}; let t = 0.6;
  S.refs.forEach(r => { refs[r.name] = r.to; if (!O[r.to]) return; const l = line(curve(V[r.name], O[r.to]), {stroke: C.accent, 'stroke-width': 4}); draw(l, t, 0.45);
    const tip = mk('circle', {r: 7, fill: C.accent, opacity: 0, cx: O[r.to].x - 10, cy: O[r.to].cy}, L3); fade(tip, t + 0.4, 0.1); arrows[r.name] = {l, tip}; t += 0.15; });
  SETTLE = t + 0.3; t += 0.8;
  S.reassign.forEach(r => { const a = arrows[r.name], V0 = V[r.name]; glow(V0, t, 1, 0.25);
    if (a) { const oldD = a.l.p.getAttribute('d'); void oldD; at(t, 0.35, (p, raw) => { a.l.p.setAttribute('stroke-dashoffset', a.l.len * p); a.tip.setAttribute('opacity', 1 - raw); }, E.inout); }
    if (O[r.to]) { const l = line(curve(V0, O[r.to]), {stroke: C.accent, 'stroke-width': 4}); draw(l, t + 0.35, 0.45);
      const tip = mk('circle', {r: 7, fill: C.accent, opacity: 0, cx: O[r.to].x - 10, cy: O[r.to].cy}, L3); fade(tip, t + 0.75, 0.1); arrows[r.name] = {l, tip}; }
    else { const nl = txt(L2, V0.x + V0.w + 30, V0.cy + 11, 'null', 30, {class: 'mono', fill: C.mute, opacity: 0}); fade(nl, t + 0.4, 0.3); delete arrows[r.name]; }
    snd(t, 'swish'); refs[r.name] = r.to; glow(V0, t + 0.9, 0, 0.25);
    objs.forEach(o => { if (!Object.values(refs).includes(o.id) && !O[o.id].gone) { O[o.id].gone = 1; dim(O[o.id].g, t + 0.8, 0.3, 0.4);
        O[o.id].r.setAttribute('stroke-dasharray', '10 8'); const u = txt(L2, O[o.id].cx, O[o.id].y + O[o.id].h + 26, 'unreachable', 22, {'text-anchor': 'middle', fill: C.mute, opacity: 0}); fade(u, t + 0.9, 0.3); snd(t + 0.9, 'tick'); } });
    t += 1.3; });
  END = Math.max(END, t + 0.6);
};

T.outputmap = () => {
  const out = S.output, size = 32, lh = 50, th = 56 + 30 + lh * (1 + out.length) + 20, g = mk('g', {opacity: 0}, L1);
  panel(g, 0, 0, W, th); mk('rect', {x: 0, y: 0, width: W, height: 56, rx: 22, fill: C.bar}, g); mk('rect', {x: 0, y: 34, width: W, height: 22, fill: C.bar}, g);
  ['#FF5F57', '#FEBC2E', '#28C840'].forEach((c, i) => mk('circle', {cx: 34 + i * 30, cy: 28, r: 9, fill: c}, g));
  pop(g, 0, W / 2, th / 2, 0.45); SETTLE = 0.45;
  const cmd = txt(g, 40, 56 + 30 + lh / 2 + 11, '', size, {class: 'mono', fill: C.text, 'font-weight': 500, 'xml:space': 'preserve'});
  const full = '$ ' + S.command, per = 0.035, t0 = 0.6;
  at(t0, full.length * per, p => { cmd.textContent = full.slice(0, Math.round(p * full.length)); }, E.lin);
  for (let i = 2; i < full.length; i += 6) snd(t0 + i * per, 'key');
  let t = t0 + full.length * per + 0.3; const rows = [];
  out.forEach((o, i) => { const e = txt(g, 40, 56 + 30 + lh * (i + 1) + lh / 2 + 11, o, size - 2, {class: 'mono', fill: C.dim, 'font-weight': 500, opacity: 0, 'xml:space': 'preserve'}); fit(e, W - 80);
    fade(e, t + i * 0.12, 0.25); rows.push(e); });
  t += out.length * 0.12 + 0.9;
  const cols = Math.min(3, out.length), bw = (W - (cols - 1) * 24) / cols, bh = 100, gy = th + 70;
  out.forEach((o, i) => { const x = (i % cols) * (bw + 24), y = gy + Math.floor(i / cols) * (bh + 24);
    const n = node(x, y, bw, bh, o.split(/\s+/).filter(Boolean).slice(0, 2).join(' '), 28); n.t.setAttribute('class', 'mono');
    const sy = 56 + 30 + lh * (i + 1);
    at(t + i * 0.1, 0.6, (p, raw) => { n.g.setAttribute('opacity', Math.min(1, raw * 2)); n.g.setAttribute('transform', `translate(0 ${lerp(sy - y, 0, p)})`); }, E.spring);
    at(t + i * 0.1, 0.3, (p) => rows[i].setAttribute('fill', p > 0.5 ? C.accent : C.dim)); snd(t + i * 0.1, 'pop'); });
  END = Math.max(END, t + out.length * 0.1 + 1.4);
};

T.kinetic = () => {
  // The takeaway in big type: words rise in one by one out of a soft blur, the key word in the accent with a marker
  // stroke drawn under it, then an optional tag. Calm and on one colour, like a motion designer's title card.
  const parsed = S.lines.map(l => { const out = []; let hl = false;
    l.split(/(\*)/).forEach(part => { if (part === '*') { hl = !hl; return; }
      part.split(/\s+/).filter(Boolean).forEach(w => out.push([w, hl])); }); return out; });
  let size = Math.min(132, Math.floor(H / (parsed.length * 1.2 + (S.tag ? 1.1 : 0))));
  const measure = (w, sz) => { const e = txt(L2, 0, 0, w, sz, {'font-weight': 700}); const n = e.getComputedTextLength();
    e.remove(); return n; };
  const width = (ws, sz) => ws.reduce((n, [w]) => n + measure(w, sz), 0) + sz * 0.28 * (ws.length - 1);
  while (size > 40 && Math.max(...parsed.map(ws => width(ws, size))) > W - 20) size -= 4;
  const lh = size * 1.18, marks = []; let t = 0.15;
  parsed.forEach((ws, li) => { let x = (W - width(ws, size)) / 2; const y = li * lh + size;
    ws.forEach(([w, hl]) => { const e = txt(L2, x, y, w, size, {'font-weight': 700, fill: hl ? C.accent : C.ink, opacity: 0, filter: 'url(#soft)'});
      const wd = e.getComputedTextLength(), t0 = t;
      at(t0, 0.55, (p, raw) => { e.setAttribute('opacity', Math.min(1, raw * 2.5));
        e.setAttribute('transform', `translate(0 ${(1 - p) * size * 0.32})`);
        if (raw > 0.5) e.removeAttribute('filter'); }, E.spring);
      snd(t0, hl ? 'pop' : 'tick');
      if (hl) marks.push(line(`M${x} ${y + size * 0.16} Q${x + wd / 2} ${y + size * 0.22} ${x + wd} ${y + size * 0.14}`,
        {stroke: C.accent, 'stroke-width': Math.max(6, size * 0.07), opacity: 0.85}));
      x += wd + size * 0.28; t += 0.13; });
    t += 0.12; });
  // Every word is in place; the marker under the key word draws last, as the emphasis, then the tag.
  SETTLE = t + 0.15;
  marks.forEach(u => draw(u, t + 0.2, 0.45)); if (marks.length) snd(t + 0.2, 'scribble');
  if (S.tag) { const tg = pill(L2, W / 2, parsed.length * lh + size * 0.55, S.tag, Math.round(size * 0.26));
    pop(tg.g, t + 0.6, W / 2, tg.cy, 0.45); snd(t + 0.6, 'pop'); }
  END = Math.max(END, t + 2.2);
};

T.statement = () => {
  // Short stacked statements on a soft card of drifting blurred blobs, with frosted glass panels floating over it.
  // Each line rises out of a blur, held a beat before the next; the key word in the accent gets a marker stroke.
  const cw = W - 72, ch = H - 72, defs = svg.querySelector('defs'), ink = '#141821', w = 2 * Math.PI * 0.08;
  const G = mk('g', {}, L1);
  const blur = (id, sd) => { const f = mk('filter', {id, x: '-30%', y: '-30%', width: '160%', height: '160%'}, defs);
    return mk('feGaussianBlur', {stdDeviation: sd}, f); };
  blur('stblob', 46); blur('stfrost', 110);
  mk('clipPath', {id: 'stclip'}, defs).appendChild(mk('rect', {x: 0, y: 0, width: cw, height: ch, rx: 56}, svg));
  FIT = mk('rect', {x: 0, y: 0, width: cw, height: ch, rx: 56, fill: '#F5F2FB', filter: 'url(#shadow)'}, G);
  const hues = [[C.accent, 0.5, 0.25, 0.3], ['#B9C4FF', 0.8, 0.8, 0.28], ['#BFEBD8', 0.85, 0.2, 0.26], ['#FFD9C2', 0.2, 0.85, 0.3]];
  const sets = [];
  const blobs = (parent, filter) => { const g = mk('g', {filter: `url(#${filter})`}, parent);
    sets.push(hues.map(([c, bx, by, r]) => ({e: mk('circle', {r: r * cw, fill: c, opacity: c === C.accent ? 0.42 : 0.8}, g), bx, by}))); };
  const base = mk('svg', {width: cw, height: ch, overflow: 'hidden', 'clip-path': 'url(#stclip)'}, G); blobs(base, 'stblob');
  const panels = [[0.5, 0.1, 0.4, 0.3, 0], [0.42, 0.62, 0.46, 0.26, 2.1]].map(([px, py, pw, ph, ph0], k) => {
    const clip = mk('clipPath', {id: 'stp' + k}, defs), cr = mk('rect', {width: pw * cw, height: ph * ch, rx: 36}, clip);
    blobs(mk('svg', {width: cw, height: ch, overflow: 'hidden', 'clip-path': `url(#stp${k})`}, G), 'stfrost');
    const r = mk('rect', {width: pw * cw, height: ph * ch, rx: 36, fill: 'rgba(255,255,255,0.4)', stroke: 'rgba(255,255,255,0.8)', 'stroke-width': 2}, G);
    return {r, cr, x: px * cw, y: py * ch, ph0}; });
  const drift = t => { hues.forEach((_, j) => sets.forEach(s => { const b = s[j], a = 0.09 * cw;
      b.e.setAttribute('cx', b.bx * cw + a * Math.cos(w * t + j * 1.7)); b.e.setAttribute('cy', b.by * ch + a * Math.sin(w * t + j * 2.3)); }));
    panels.forEach(p => { const x = p.x + 0.03 * cw * Math.sin(w * t + p.ph0), y = p.y + 0.03 * ch * Math.cos(w * t + p.ph0);
      for (const e of [p.r, p.cr]) { e.setAttribute('x', x); e.setAttribute('y', y); } }); };
  drift(0);
  const parsed = S.lines.map(l => l.split('*').map((s, i) => [s, i % 2 === 1]).filter(([s]) => s));
  const left = cw * 0.08, avail = cw - left - cw * 0.05;
  let size = Math.min(84, Math.floor(ch / (parsed.length * 1.25 + 1)));
  const els = parsed.map(segs => { const e = mk('text', {x: left, y: 0, 'font-size': size, 'font-weight': 700, fill: ink, opacity: 0}, G);
    segs.forEach(([s, hl]) => { const sp = mk('tspan', hl ? {fill: C.accent} : {}, e); sp.textContent = s; }); return e; });
  while (size > 36 && Math.max(...els.map(e => e.getComputedTextLength())) > avail) { size -= 2; els.forEach(e => e.setAttribute('font-size', size)); }
  const lh = size * 1.3, y0 = (ch - lh * els.length) / 2 + size * 0.95, marks = [];
  els.forEach((e, i) => { const y = y0 + i * lh; e.setAttribute('y', y);
    const g = blur('stline' + i, 8); e.setAttribute('filter', `url(#stline${i})`);
    const t0 = 0.25 + i * 1.2;
    at(t0, 0.3, (p, raw) => { e.setAttribute('opacity', Math.min(1, raw * 2.5)); e.setAttribute('transform', `translate(0 ${(1 - p) * 40})`);
      g.setAttribute('stdDeviation', 8 * (1 - p)); if (raw >= 1) e.removeAttribute('filter'); });
    snd(t0, 'swish');
    [...e.querySelectorAll('tspan[fill]')].forEach(sp => { const n = sp.textContent.length;
      const x1 = sp.getStartPositionOfChar(0).x, x2 = sp.getEndPositionOfChar(n - 1).x;
      const m = mk('path', {d: `M${x1} ${y + size * 0.16} Q${(x1 + x2) / 2} ${y + size * 0.22} ${x2} ${y + size * 0.14}`, fill: 'none', stroke: C.accent,
        'stroke-width': Math.max(6, size * 0.07), 'stroke-linecap': 'round', opacity: 0.85}, G);
      const len = m.getTotalLength(); m.setAttribute('stroke-dasharray', len); m.setAttribute('stroke-dashoffset', len);
      G.insertBefore(m, e); marks.push({m, len}); }); });
  SETTLE = 0.25 + (els.length - 1) * 1.2 + 0.4;
  marks.forEach(({m, len}) => at(SETTLE, 0.45, p => m.setAttribute('stroke-dashoffset', len * (1 - p)), E.inout));
  if (marks.length) snd(SETTLE, 'scribble');
  const total = SETTLE + 1.5; at(0, total, (p, raw) => drift(raw * total), E.lin);
  END = Math.max(END, total);
};

T.quotes = () => {
  // Real posts typed onto dark cards one after another (about 18 characters a second, faster only when the text would
  // not fit the time), each card blur-sliding out as the next slides in; at the end the cards stack into a tilted pile.
  const Q = S.quotes, n = Q.length, cw = W - 150, pad = 44, bodyW = cw - 2 * pad, defs = svg.querySelector('defs');
  const total = Q.reduce((k, q) => k + q.text.length, 0), cps = Math.max(18, total / 6.5), IN = p => p * p * p;
  const wrap = (text, sz) => { const probe = txt(L2, 0, 0, '', sz, {'font-weight': 500}); const out = [];
    text.split('\n').forEach(par => { let cur = '';
      par.split(/\s+/).filter(Boolean).forEach(word => { const trial = cur ? cur + ' ' + word : word; probe.textContent = trial;
        if (cur && probe.getComputedTextLength() > bodyW) { out.push(cur); cur = word; } else cur = trial; });
      out.push(cur); });
    probe.remove(); return out; };
  let size = 40, wrapped = Q.map(q => wrap(q.text, size));
  while (size > 28 && Math.max(...wrapped.map(l => l.length)) > 8) { size -= 2; wrapped = Q.map(q => wrap(q.text, size)); }
  const lh = Math.round(size * 1.4), head = 150, ch = head + 30 + lh * Math.max(...wrapped.map(l => l.length)) + 40;
  const cx = cw / 2, cy = ch / 2;
  const tf = (x, y, rot, s) => `translate(${x} ${y}) translate(${cx} ${cy}) rotate(${rot}) scale(${s}) translate(${-cx} ${-cy})`;
  const rest = {x: 0, y: 0, rot: 0, s: 1, blur: 0, op: 1}, gone = {x: -cw * 0.9, y: 0, rot: 0, s: 1, blur: 12, op: 0};
  const cards = Q.map((q, j) => {
    const f = mk('filter', {id: 'qb' + j, x: '-30%', y: '-30%', width: '160%', height: '160%'}, defs), sd = mk('feGaussianBlur', {stdDeviation: 0}, f);
    const g = mk('g', {opacity: 0, transform: tf(0, 0, 0, 1)}, L1);
    mk('rect', {x: 0, y: 0, width: cw, height: ch, rx: 34, fill: '#161C28', stroke: '#2A3242', 'stroke-width': 2, filter: 'url(#shadow)'}, g);
    const name = q.author.replace(/^@/, '');
    mk('circle', {cx: pad + 36, cy: 50 + 36, r: 36, fill: '#232A38', stroke: C.accent, 'stroke-width': 2}, g);
    txt(g, pad + 36, 50 + 36 + 11, name.split(/\s+/).slice(0, 2).map(x => x[0]).join('').toUpperCase(), 30, {'text-anchor': 'middle', fill: C.accent, 'font-weight': 700});
    fit(txt(g, pad + 96, 50 + 30, name, 34), cw - pad * 2 - 96);
    txt(g, pad + 96, 50 + 68, q.platform, 26, {fill: C.dim, 'font-weight': 500});
    const rows = wrapped[j].map((l, i) => ({t: txt(g, pad, head + 30 + i * lh + size * 0.8, '', size, {'font-weight': 500, fill: '#E6E9F2'}), full: l}));
    const caret = mk('rect', {x: pad, y: head + 30 + size * 0.05, width: 4, height: size * 1.05, rx: 2, fill: C.accent, opacity: 0}, g);
    return {g, sd, rows, caret, q, len: rows.reduce((k, r) => k + r.full.length, 0)};
  });
  // Animate any of x, y, rot, scale, blur and opacity of a card between two states.
  const move = (j, t, d, a, b, ease = E.out) => at(t, d, p => { const c = cards[j], v = k => lerp(a[k], b[k], p);
    c.g.setAttribute('transform', tf(v('x'), v('y'), v('rot'), v('s'))); c.g.setAttribute('opacity', v('op'));
    c.sd.setAttribute('stdDeviation', v('blur')); if (v('blur') > 0.05) c.g.setAttribute('filter', `url(#qb${j})`); else c.g.removeAttribute('filter'); }, ease);
  let t = 0.1;
  cards.forEach((c, j) => {
    move(j, t, 0.45, j ? {...gone, x: cw * 0.7} : {...rest, y: 40, blur: 10, op: 0}, rest); snd(t, 'swish');
    if (j === 0) SETTLE = t + 0.45;
    const ts = t + 0.5, dur = c.len / cps, hold = 0.55;
    at(ts, dur, p => { let left = Math.round(p * c.len), at_ = 0;
      c.rows.forEach((r, i) => { const k = Math.min(left, r.full.length); r.t.textContent = r.full.slice(0, k); left -= k; if (k > 0) at_ = i; });
      const r = c.rows[at_]; c.caret.setAttribute('x', pad + r.t.getComputedTextLength() + 4);
      c.caret.setAttribute('y', head + 30 + at_ * lh + size * 0.05); }, E.lin);
    at(ts, dur + hold, (p, raw) => { const tm = raw * (dur + hold);
      c.caret.setAttribute('opacity', raw < 1 && (tm < dur || Math.floor(tm * 4) % 2 === 0) ? 1 : 0); }, E.lin);
    for (let k = 3; k <= c.len; k += 3) snd(ts + k / cps, 'key');
    t = ts + dur + hold;
    if (j < n - 1) { move(j, t, 0.4, rest, gone, IN); t += 0.1; }
  });
  if (n > 1) {
    const pile = j => ({x: (j - (n - 1)) * 16, y: (j - (n - 1)) * 14, rot: 2 + (j - (n - 1)) * 4, s: 0.88, blur: 0, op: 1});
    const t1 = t + 0.1;
    cards.forEach((c, j) => { move(j, t1 + (n - 1 - j) * 0.08, 0.6, j === n - 1 ? rest : {...gone, op: 0}, pile(j)); });
    snd(t1, 'swish'); snd(t1 + 0.45, 'thud'); END = Math.max(END, t1 + 0.6 + (n - 1) * 0.08 + 0.6);
  } else END = Math.max(END, t + 0.4);
};

Promise.all([document.fonts.load('500 34px Poppins'), document.fonts.load('600 34px Poppins'), document.fonts.load('700 34px Poppins'), document.fonts.load('500 34px "JetBrains Mono"')]).then(() => {
  T[S.type](); sortTW();
  // Fit inside a margin that leaves room for the soft shadows (a shadow cut at the box edge shows as a line in the
  // reel), scaling down only when needed, and centre the layout both ways.
  const M = 36, bb = (FIT || ROOT).getBBox(), k = Math.min(1, (W - 2 * M) / bb.width, (H - 2 * M) / bb.height);
  ROOT.setAttribute('transform', `translate(${(W - bb.width * k) / 2 - bb.x * k} ${(H - bb.height * k) / 2 - bb.y * k}) scale(${k})`); window.META = {duration: Math.min(P.max, END + 0.4), settle: SETTLE, sounds: SND};
  window.renderAt(0); window.READY = true;
}).catch(e => { window.ERROR = String(e); });
</script></body></html>"""


def tokens(code, language):
    """Highlighted code as [[text, colour], ...] per line (the editor colours of visuals.code_image)."""
    import visuals
    from pygments import lex
    from pygments.lexers import TextLexer, get_lexer_by_name
    try:
        lexer = get_lexer_by_name(language or 'text')
    except Exception:
        lexer = TextLexer()
    lines, cur = [], []
    for token_type, text in lex(code.rstrip('\n'), lexer):
        for k, part in enumerate(text.split('\n')):
            if k:
                lines.append(cur)
                cur = []
            if part:
                cur.append([part, visuals.color_for(token_type)])
    lines.append(cur)
    return lines[:len(code.rstrip('\n').split('\n'))]


def words(code, language):
    """Each line's tokens split at spaces: [(line, column, text, colour)], spaces dropped."""
    out = []
    for i, line in enumerate(tokens(code, language)):
        col = 0
        for text, color in line:
            for part in re.split(r'(\s+)', text):
                if part and not part.isspace():
                    out.append((i, col, part, color))
                col += len(part)
    return out


def morph_plan(before, after, language):
    """Tokens of a before/after morph: each with where it starts (from) and ends (to). Tokens in both glide; a
    token only in before fades out red; one only in after fades in green. Lines that changed get a band."""
    a, b = words(before, language), words(after, language)
    toks, matched_b = [], set()
    sm = difflib.SequenceMatcher(None, [t[2] for t in a], [t[2] for t in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                toks.append({'text': a[i][2], 'color': b[j][3], 'from': [a[i][0], a[i][1]], 'to': [b[j][0], b[j][1]]})
                matched_b.add(j)
        else:
            toks += [{'text': a[i][2], 'color': a[i][3], 'from': [a[i][0], a[i][1]], 'to': None} for i in range(i1, i2)]
    toks += [{'text': t[2], 'color': t[3], 'from': None, 'to': [t[0], t[1]]} for j, t in enumerate(b) if j not in matched_b]
    removed = sorted({t['from'][0] for t in toks if t['to'] is None})
    added = sorted({t['to'][0] for t in toks if t['from'] is None})
    return toks, removed, added


def prepare(spec, w):
    """The spec with what the page needs computed here: highlighted tokens, a font size, a source's host."""
    spec = dict(spec)
    if spec['type'] == 'stepper':
        spec['tokens'] = tokens(spec['code'], spec.get('language'))
    elif spec['type'] == 'morph':
        toks, removed, added = morph_plan(spec['before'], spec['after'], spec.get('language'))
        cols = max(len(l) for l in (spec['before'] + '\n' + spec['after']).split('\n'))
        spec.update(toks=toks, removed_lines=removed, added_lines=added,
                    rows=max(len(spec['before'].rstrip('\n').split('\n')), len(spec['after'].rstrip('\n').split('\n'))),
                    size=min(40, int((w - 90) / (max(cols, 8) * 0.6))))
    elif spec['type'] == 'race':
        from urllib.parse import urlparse
        spec['source_host'] = urlparse(spec.get('source', '')).netloc.removeprefix('www.')
    elif spec['type'] == 'structure' and spec.get('structure') == 'map':
        spec['items'] = [str(i) for i in spec.get('items', [])]
    for key in ('ops', 'trace', 'hops', 'calls', 'moves', 'reassign', 'refs', 'objects', 'cards', 'output', 'inside',
                'lines', 'quotes'):
        spec.setdefault(key, [])
    return spec


def font_css():
    import visuals
    visuals.mono(20)  # makes sure JetBrains Mono is downloaded
    faces = [('Poppins', wt, render.FONT_DIR / f'Poppins-{name}.ttf') for wt, name in (('700', 'Bold'), ('600', 'SemiBold'),
                                                                                      ('500', 'Regular'))]
    faces.append(('JetBrains Mono', '500', visuals.MONO))
    return ''.join(f"@font-face{{font-family:'{fam}';font-weight:{wt};src:url(data:font/ttf;base64,"
                   f"{base64.b64encode(path.read_bytes()).decode()})}}" for fam, wt, path in faces)


def render_motion(spec, theme, size):
    """Transparent RGBA frames of an animation at its natural length, and its META {duration, settle, sounds}.
    Cached per spec, theme, size and page."""
    w, h = size
    key = hashlib.sha1(json.dumps({'spec': spec, 'accent': theme['accent'], 'ink': theme['ink'], 'size': size,
                                   'page': hashlib.sha1(PAGE.encode()).hexdigest()}, sort_keys=True).encode()).hexdigest()[:16]
    folder = FRAMES / key
    meta_path = folder / 'meta.json'
    if meta_path.exists() and any(folder.glob('*.png')):
        return folder, json.loads(meta_path.read_text())
    params = {'spec': prepare(spec, w), 'w': w, 'h': h, 'accent': theme['accent'], 'ink': theme['ink'],
              'muted': theme['muted'], 'max': MAX_SECONDS}
    html = PAGE.replace('<head>', '<head><style>' + font_css() + '</style><script>window.PARAMS = '
                        + json.dumps(params).replace('</', '<\\/') + ';</script>', 1)
    from playwright.sync_api import sync_playwright
    dpr = 2
    folder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': w // dpr, 'height': h // dpr}, device_scale_factor=dpr)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.set_content(html, wait_until='domcontentloaded')
        try:
            page.wait_for_function('window.READY === true || window.ERROR', timeout=30000)
        except Exception:
            raise RuntimeError(f'motion page did not load: {errors or "no error reported"}') from None
        if errors or page.evaluate('window.ERROR || null'):
            raise RuntimeError(f"motion page failed: {(errors or [page.evaluate('window.ERROR')])[0][:300]}")
        meta = page.evaluate('window.META')
        for f in range(max(1, round(meta['duration'] * FPS))):
            page.evaluate(f'window.renderAt({f / FPS})')
            page.screenshot(path=str(folder / f'{f:04d}.png'), omit_background=True)
        browser.close()
    meta_path.write_text(json.dumps(meta))
    return folder, meta


EXAMPLES = {
    'stepper': {'type': 'stepper', 'language': 'js', 'title': 'closure.js',
                'code': 'function counter() {\n  let n = 0\n  return () => ++n\n}\nconst next = counter()\nnext()\nnext()',
                'trace': [{'line': 5, 'vars': [{'name': 'n', 'value': '0'}]},
                          {'line': 6, 'vars': [{'name': 'n', 'value': '1'}], 'out': '1'},
                          {'line': 7, 'vars': [{'name': 'n', 'value': '2'}], 'out': '2'}]},
    'flow': {'type': 'flow', 'nodes': [{'id': 'app', 'label': 'Browser', 'kind': 'client'},
                                       {'id': 'api', 'label': 'API', 'kind': 'server'},
                                       {'id': 'cache', 'label': 'Redis', 'kind': 'cache'},
                                       {'id': 'db', 'label': 'Postgres', 'kind': 'db'}],
             'hops': [{'from': 'app', 'to': 'api', 'label': 'GET /user'}, {'from': 'api', 'to': 'cache', 'label': 'miss'},
                      {'from': 'api', 'to': 'db', 'label': 'query'}, {'from': 'api', 'to': 'cache', 'label': 'save'}]},
    'morph': {'type': 'morph', 'language': 'ts', 'title': 'user.ts',
              'before': 'const res = await fetch(url)\nconst user = res.json()\nreturn user.name',
              'after': 'const res = await fetch(url)\nconst user = await res.json()\nreturn user.name'},
    'git': {'type': 'git', 'commits': [{'id': 'a1f', 'branch': 'main'}, {'id': 'b2c', 'branch': 'main'},
                                       {'id': 'c3d', 'branch': 'feature'}, {'id': 'd4e', 'branch': 'main'},
                                       {'id': 'e5f', 'branch': 'feature'}],
            'op': 'rebase', 'head': 'feature', 'base': 'main'},
    'eventloop': {'type': 'eventloop', 'cards': [{'label': 'log(1)', 'lane': 'stack'}, {'label': '1', 'lane': 'log'},
                                                 {'label': 'log(1)', 'lane': 'done'},
                                                 {'label': 'setTimeout', 'lane': 'apis'},
                                                 {'label': 'then cb', 'lane': 'micro'},
                                                 {'label': 'setTimeout', 'lane': 'macro'},
                                                 {'label': 'then cb', 'lane': 'stack'}, {'label': '2', 'lane': 'log'},
                                                 {'label': 'then cb', 'lane': 'done'},
                                                 {'label': 'setTimeout', 'lane': 'stack'}, {'label': '3', 'lane': 'log'}]},
    'structure': {'type': 'structure', 'structure': 'array', 'items': ['3', '7', '9'],
                  'ops': [{'op': 'insert', 'at': 1, 'value': '5'}, {'op': 'remove', 'at': 0}]},
    'sequence': {'type': 'sequence', 'actors': ['App', 'Stripe', 'Webhook'],
                 'calls': [{'from': 'App', 'to': 'Stripe', 'label': 'checkout'},
                           {'from': 'Stripe', 'to': 'Webhook', 'label': 'event', 'fail': True},
                           {'from': 'Stripe', 'to': 'Webhook', 'label': 'retry'},
                           {'from': 'Webhook', 'to': 'Stripe', 'label': '200 OK'}]},
    'states': {'type': 'states', 'states': ['idle', 'loading', 'success', 'error'],
               'moves': [{'event': 'submit', 'to': 'loading'}, {'event': 'fail', 'to': 'error'},
                         {'event': 'retry', 'to': 'loading'}, {'event': 'ok', 'to': 'success'}]},
    'race': {'type': 'race', 'title': 'Cold start', 'unit': 'ms', 'source': 'https://example.com/benchmark',
             'bars': [{'label': 'Tool A', 'value': 120}, {'label': 'Tool B', 'value': 480}]},
    'xray': {'type': 'xray', 'nodes': [{'id': 'app', 'label': 'App', 'kind': 'client'},
                                       {'id': 'pg', 'label': 'Postgres', 'kind': 'db'}],
             'focus': 'pg', 'inside': ['parser', 'planner', 'executor', 'buffer cache']},
    'memory': {'type': 'memory', 'refs': [{'name': 'a', 'to': 'o1'}, {'name': 'b', 'to': 'o1'}],
               'objects': [{'id': 'o1', 'label': "{ name: 'Ana' }"}, {'id': 'o2', 'label': "{ name: 'Bo' }"}],
               'reassign': [{'name': 'b', 'to': 'o2'}, {'name': 'a', 'to': 'null'}]},
    'outputmap': {'type': 'outputmap', 'command': 'git branch',
                  'output': ['* main', '  feature/login', '  fix/cache']},
    'kinetic': {'type': 'kinetic', 'lines': ['Delete the key', 'on every *write*'], 'tag': 'Key step'},
    'statement': {'type': 'statement', 'lines': ['Cache the *read*,', 'never the write.', 'Delete the key.']},
    'quotes': {'type': 'quotes', 'quotes': [
        {'author': 'Andrej Karpathy', 'platform': 'X', 'url': 'https://x.com/karpathy/status/1617979122625712128',
         'text': 'The hottest new programming language is English'},
        {'author': 'Andrej Karpathy', 'platform': 'X', 'url': 'https://x.com/karpathy/status/1886192184808149383',
         'text': 'There\'s a new kind of coding I call "vibe coding", where you fully give in to the vibes, '
                 'embrace exponentials, and forget that the code even exists.'}]},
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TYPES:
        raise SystemExit(__doc__)
    kind, style = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else 'dark')
    theme = render.THEMES[style]
    folder, meta = render_motion(EXAMPLES[kind], theme, (980, 900))
    render.OUT_DIR.mkdir(exist_ok=True)
    out = render.OUT_DIR / f'motion-{kind}.mp4'
    bg = theme['bg'].lstrip('#')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=0x{bg}:s=980x900:r={FPS}',
                    '-framerate', str(FPS), '-i', str(folder / '%04d.png'), '-filter_complex', 'overlay=shortest=1',
                    '-pix_fmt', 'yuv420p', str(out)], check=True)
    print(f"{out} ({meta['duration']:.1f}s, settles at {meta['settle']:.1f}s, {len(meta['sounds'])} sounds)")


if __name__ == '__main__':
    main()
