"""Showcase reels: once or twice a week, a fully animated piece with no voice, made only of moving light and a few
words (the creator asked for "some good complete interesting animation video, maybe once or twice a week",
2026-10-20; the bar is @louis_rlee's all-code motion piece, director.md). Claude writes one true idea a developer
recognises (how an agent loops, how a request travels, what a branch is) as 4 to 6 short beats, each with an
abstract motif; the page draws one continuous glowing line that morphs from motif to motif, the words arriving on
each beat, sound effects only (never music), and glides back to the first motif so a replay loops.

Abstract shapes only (director.md, CLAUDE.md): no faces, people, characters, mascots or animals, no numbers that
are not true, no logos. A Claude review of the frames must pass before anything is posted.

Usage:
  python showcase.py                  write, render, review and post today's showcase (showcase.yml)
  python showcase.py --render <json>  render a showcase spec (a file) to out/showcase-<id>.mp4, nothing else
Env: DRY_RUN=true renders and reviews, posts nothing; FORCE_POST=true posts even if one already went out today.
     IG_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY, GRAPH_VERSION as in publish.py; CLAUDE_MODEL for the review.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import render

LOG = render.ROOT / 'showcases.json'
MOTIFS = ('spark', 'ring', 'bloom', 'orbit', 'arcs', 'flow', 'loop', 'blob', 'wave', 'card')
BEAT = 2.8                # seconds per beat
BACK = 0.9                # the closing glide back to the first motif
MIN_BEATS, MAX_BEATS = 4, 6
NUMBERS = re.compile(r'\d')

SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['title', 'beats', 'caption', 'hashtags'],
    'properties': {
        'title': {'type': 'string'},
        'beats': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['text', 'motif'],
            'properties': {'text': {'type': 'string'}, 'motif': {'type': 'string', 'enum': list(MOTIFS)},
                           'labels': {'type': 'array', 'items': {'type': 'string'}},
                           'light': {'type': 'boolean'}}}},
        'caption': {'type': 'string'},
        'hashtags': {'type': 'array', 'items': {'type': 'string'}},
    },
}

PROMPT = """Write this week's showcase reel for @hassanjan.k, a faceless account of daily web-dev and AI tips.
A showcase is a short, fully animated piece with no voice: one glowing line morphs from shape to shape while a few
words arrive, like a motion designer's reel. It carries one true idea a developer recognises and enjoys seeing
drawn: how an AI agent loops (plan, act, check, repeat), how a request travels, what a git branch is, why caching
works, how a build becomes a deploy. Calm, beautiful, true. Not a tutorial, not a list of tools, no promotion.

Return 4 to 6 beats, in order. Each beat:
- text: 2 to 6 words, the line on screen; put the one key word in *asterisks* (it is set in an italic serif and
  the accent colour). Short and plain: "Start with a *plan*", "Let the agent *act*", "Check the *result*". No
  numbers, no names of products or people.
- motif: the shape the line becomes on this beat, one of: spark (a single point of light), ring (a circle),
  bloom (a flower of petals), orbit (dots circling), arcs (rhythm arcs), flow (a path through up to 3 labelled
  nodes), loop (an infinity sign: something that repeats), blob (a soft living orb), wave (a moving line),
  card (a glass card with one label). Pick the shape that means what the words say, and let neighbouring beats
  flow into each other.
- labels: only for flow (1 to 3 node labels, 2 to 10 characters each) and card (1 label of 2 to 14 characters).
- light: true on at most one beat (a light chapter that wakes the viewer up); never the first.
Start on a spark or a ring, so the first frame already shows light and the first words.
title: the idea in a few words (for the record). caption: 2 or 3 short lines saying the idea plainly, ending with
a question for the comments and 👇. hashtags: 3 to 5.

Never: faces, people, characters, mascots, animals, logos, music, made-up numbers or claims. Do not repeat these
earlier showcases:
"""


# ---------- writing and checking ----------

def errors(spec):
    """What is wrong with a showcase spec, as messages for the writer; [] when it can be drawn."""
    out = []
    beats = spec.get('beats')
    if not isinstance(beats, list) or not MIN_BEATS <= len(beats) <= MAX_BEATS:
        return [f'beats: needs {MIN_BEATS} to {MAX_BEATS}']
    light = 0
    for i, b in enumerate(beats):
        text = str(b.get('text', ''))
        words = text.replace('*', '').split()
        if not 2 <= len(words) <= 6:
            out.append(f'beat {i + 1}: text needs 2 to 6 words')
        if text.count('*') != 2:
            out.append(f'beat {i + 1}: put exactly one key word in *asterisks*')
        if NUMBERS.search(text):
            out.append(f'beat {i + 1}: no numbers in a showcase')
        if b.get('motif') not in MOTIFS:
            out.append(f'beat {i + 1}: motif must be one of {", ".join(MOTIFS)}')
        labels = b.get('labels') or []
        if b.get('motif') == 'flow' and not (1 <= len(labels) <= 3 and all(2 <= len(str(x)) <= 10 for x in labels)):
            out.append(f'beat {i + 1}: flow needs 1 to 3 labels of 2 to 10 characters')
        if b.get('motif') == 'card' and not (len(labels) == 1 and 2 <= len(str(labels[0])) <= 14):
            out.append(f'beat {i + 1}: card needs one label of 2 to 14 characters')
        if b.get('light'):
            light += 1
            if i == 0:
                out.append('beat 1 stays dark; a light beat comes later')
    if light > 1:
        out.append('at most one light beat')
    if beats and beats[0].get('motif') not in ('spark', 'ring'):
        out.append('beat 1 must be a spark or a ring, so the first frame already shows light')
    lines = [l for l in str(spec.get('caption', '')).split('\n') if l.strip()]
    if not 2 <= len(lines) <= 3 or not lines[-1].rstrip().endswith('👇') or '?' not in lines[-1]:
        out.append('caption: 2 or 3 lines, the last a question ending with 👇')
    if not 3 <= len(spec.get('hashtags') or []) <= 5:
        out.append('hashtags: 3 to 5')
    return out


def write(log, attempts=3):
    import generate
    done = '\n'.join(f"- {e.get('title')}" for e in log) or '- none yet'
    feedback = ''
    for _ in range(attempts):
        proc = subprocess.run(
            ['claude', '-p', PROMPT + done + feedback, '--model', generate.MODEL, '--system-prompt',
             'You write calm, true, beautiful motion pieces. Follow the director\'s rules:\n\n' + generate.playbook(),
             '--tools', '', '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(SCHEMA)],
            capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
        spec = json.loads(proc.stdout).get('structured_output') or {}
        problems = errors(spec)
        if not problems:
            return spec
        print('Showcase draft rejected: ' + '; '.join(problems))
        feedback = '\n\nA previous draft had these problems, avoid them:\n' + '\n'.join(problems)
    raise RuntimeError('no valid showcase after retries')


# ---------- the page ----------

def timeline(spec):
    beats = spec['beats']
    total = len(beats) * BEAT + BACK
    return [{**b, 'start': i * BEAT, 'words': words(b['text'], i * BEAT)} for i, b in enumerate(beats)], total


def words(text, start):
    out, at = [], start + (0.0 if start == 0 else 0.45)
    for w in text.split():
        key = w.startswith('*') or w.endswith('*') or w.strip('*.,!?') != w.strip('.,!?')
        out.append([w.replace('*', ''), key, -1.0 if start == 0 else round(at, 3)])
        at += 0.14
    return out


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
html,body{margin:0;width:540px;height:960px;overflow:hidden;background:#050608;font-family:Poppins}
canvas{position:absolute;left:0;top:0;width:540px;height:960px}
#txt{position:absolute;left:30px;right:30px;top:650px;text-align:center;font:600 30px/1.2 Poppins;letter-spacing:-.01em}
#txt span{display:inline-block;margin:0 .12em;color:var(--ink)}
#txt span.k{font:italic 400 38px/1 'Instrument Serif';color:var(--accent)}
#handle{position:absolute;left:0;right:0;top:770px;text-align:center;font:500 13px Poppins;color:var(--mute);opacity:0;letter-spacing:.04em}
.lab{position:absolute;font:600 13px Poppins;color:var(--ink);transform:translate(-50%,0);white-space:nowrap;letter-spacing:.02em}
body{--ink:#F2F3F7;--mute:#6C7284}
body.lit{--ink:#16181F;--mute:#8B8F99}
</style></head><body><canvas id="c" width="1080" height="1920"></canvas><div id="labs"></div><div id="txt"></div><div id="handle"></div>
<script>
const P = window.PARAMS, B = P.beats, T = P.total, BEAT = P.beat, N = 240, SOUNDS = [];
document.documentElement.style.setProperty('--accent', P.accent);
document.getElementById('handle').textContent = P.handle;
const cv = document.getElementById('c'), cx = cv.getContext('2d'); cx.scale(2, 2);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x)), prog = (t, a, d) => clamp((t - a) / d);
const expo = p => p >= 1 ? 1 : 1 - Math.pow(2, -10 * p), inout = p => p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
const snd = (t, k) => { if (t >= 0 && t < T) SOUNDS.push([+t.toFixed(3), k]); };
const CX = 270, CY = 420, TAU = Math.PI * 2;
// Every motif is N points (index-aligned, starting at the top and going clockwise, so morphs never twist) plus
// accent dots and labels, as a pure function of the beat's local time u.
function polar(f) { const pts = []; for (let i = 0; i < N; i++) { const a = -Math.PI / 2 + TAU * i / N, r = f(a); pts.push([CX + r * Math.cos(a), CY + r * Math.sin(a)]); } return pts; }
function along(path) { // resample a polyline to N points by length
  const seg = [], L = [0]; for (let i = 1; i < path.length; i++) { const d = Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]); L.push(L[i - 1] + d); }
  const tot = L[L.length - 1], pts = []; let j = 1;
  for (let i = 0; i < N; i++) { const s = tot * i / (N - 1); while (j < L.length - 1 && L[j] < s) j++; const f = (s - L[j - 1]) / ((L[j] - L[j - 1]) || 1);
    pts.push([path[j - 1][0] + (path[j][0] - path[j - 1][0]) * f, path[j - 1][1] + (path[j][1] - path[j - 1][1]) * f]); } return pts; }
const M = {
  spark: u => ({pts: polar(() => 2 + 1.5 * Math.sin(u * 6)), dots: [[CX, CY, 7 + 2 * Math.sin(u * 5)]], rip: true}),
  ring: u => { const pts = polar(() => 130); const dots = [0, 1, 2, 3].map(k => { const a = u * .9 + k * TAU / 4 - Math.PI / 2; return [CX + 130 * Math.cos(a), CY + 130 * Math.sin(a), 5]; }); return {pts, dots}; },
  bloom: u => ({pts: polar(a => 120 * (1 + .3 * Math.sin(5 * a + u * .8))), dots: [0, 1, 2, 3, 4].map(k => { const a = (Math.PI / 2 - u * .8) / 5 + k * TAU / 5; return [CX + 156 * Math.cos(a), CY + 156 * Math.sin(a), 5]; })}),
  orbit: u => { const pts = polar(a => 150 / Math.sqrt(1 + 1.8 * Math.pow(Math.sin(a - u * .5), 2))); const dots = [0, 1, 2].map(k => { const a = u * (1.2 + k * .5) + k * 2; const r = 150 / Math.sqrt(1 + 1.8 * Math.pow(Math.sin(a - u * .5), 2)); return [CX + r * Math.cos(a), CY + r * Math.sin(a), 6]; }); return {pts, dots, rings: [70]}; },
  arcs: u => { const path = []; for (let i = 0; i <= 120; i++) { const a = Math.PI + Math.PI * i / 120; path.push([CX + 170 * Math.cos(a), CY + 60 + 170 * Math.sin(a)]); }
    const dots = [0, 1, 2, 3].map(k => { const a = Math.PI + Math.PI * ((u * .35 + k * .23) % 1); const r = 170 - k * 30; return [CX + r * Math.cos(a), CY + 60 + r * Math.sin(a), 5]; });
    return {pts: along(path), dots, arcs: [140, 110, 80]}; },
  flow: (u, b) => { const n = Math.max(1, (b.labels || []).length), xs = [...Array(n)].map((_, k) => n === 1 ? CX : 110 + 320 * k / (n - 1)), ys = xs.map((_, k) => CY - 90 + 180 * (k % 2));
    const path = []; for (let k = 0; k < n - 1 || (n === 1 && k < 1); k++) { const a = [xs[k], ys[k]], c = n === 1 ? [CX, CY + 120] : [xs[k + 1], ys[k + 1]];
      for (let i = 0; i <= 40; i++) { const s = i / 40, e = s * s * (3 - 2 * s); path.push([a[0] + (c[0] - a[0]) * s, a[1] + (c[1] - a[1]) * e]); } }
    const pts = along(path), head = pts[Math.floor(((u * .45) % 1) * (N - 1))];
    return {pts, dots: xs.map((x, k) => [x, ys[k], 9]).concat([[head[0], head[1], 5]]), labels: (b.labels || []).map((l, k) => [l, xs[k], ys[k] + 22])}; },
  loop: u => { const path = []; for (let i = 0; i <= 200; i++) { const a = -Math.PI / 2 + TAU * i / 200, d = 1 + Math.pow(Math.sin(a), 2); path.push([CX + 180 * Math.cos(a) / d, CY + 180 * Math.sin(a) * Math.cos(a) / d]); }
    const pts = along(path), head = pts[Math.floor(((u * .4) % 1) * (N - 1))]; return {pts, dots: [[head[0], head[1], 7]]}; },
  blob: u => ({pts: polar(a => 110 * (1 + .12 * Math.sin(3 * a + u * 1.3) + .08 * Math.sin(5 * a - u * 1.7))), dots: [], fill: true}),
  wave: u => { const path = []; for (let i = 0; i <= 120; i++) { const x = 40 + 460 * i / 120; path.push([x, CY + 60 * Math.sin(i / 120 * TAU * 1.5 + u * 2) * Math.sin(Math.PI * i / 120)]); }
    const pts = along(path); return {pts, dots: [.25, .5, .75].map(f => { const p = pts[Math.floor(f * (N - 1))]; return [p[0], p[1], 5]; })}; },
  card: (u, b) => { const w = 300, h = 170, r = 26, x0 = CX - w / 2, y0 = CY - h / 2, path = [];
    const arc = (cx0, cy0, a0) => { for (let i = 0; i <= 12; i++) { const a = a0 + Math.PI / 2 * i / 12; path.push([cx0 + r * Math.cos(a), cy0 + r * Math.sin(a)]); } };
    path.push([CX, y0]); arc(x0 + w - r, y0 + r, -Math.PI / 2); arc(x0 + w - r, y0 + h - r, 0); arc(x0 + r, y0 + h - r, Math.PI / 2); arc(x0 + r, y0 + r, Math.PI); path.push([CX, y0]);
    return {pts: along(path), dots: [], glass: [x0, y0, w, h, r], labels: [[(b.labels || [''])[0], CX, CY - 12]], big: true}; },
};
const shapes = B.map(b => (u => M[b.motif](u, b)));
B.forEach((b, i) => { if (i) { snd(b.start - .05, 'swish'); } b.words.forEach(([w, k, at]) => { if (k && at >= 0) snd(at, 'pop'); }); if (b.light) snd(b.start, 'air'); });
snd(T - P.back, 'swish');
const lerp = (a, b, f) => a.map((p, i) => [p[0] + (b[i][0] - p[0]) * f, p[1] + (b[i][1] - p[1]) * f]);
function frame(t) {
  // which beat, and the morph from the previous one
  let k = 0; B.forEach((b, i) => { if (t >= b.start) k = i; });
  const back = prog(t, T - P.back, P.back * .85);
  const u = t - B[k].start, cur = shapes[k](u);
  let pts = cur.pts, m = 1;
  if (k > 0) { m = inout(prog(t, B[k].start, .7)); if (m < 1) pts = lerp(shapes[k - 1](u + BEAT).pts, cur.pts, m); }
  if (back > 0) pts = lerp(pts, shapes[0](0).pts, inout(back));
  // light chapter
  let lit = 0; B.forEach((b, i) => { if (b.light) lit = Math.max(lit, prog(t, b.start, .45) * (1 - prog(t, b.start + BEAT - .1, .45))); });
  document.body.classList.toggle('lit', lit > .5);
  const bg = [5 + (243 - 5) * lit, 6 + (239 - 6) * lit, 8 + (231 - 8) * lit];
  cx.globalCompositeOperation = 'source-over'; cx.fillStyle = `rgb(${bg.map(Math.round)})`; cx.fillRect(0, 0, 540, 960);
  // a soft glow under the shape, drifting
  const g = cx.createRadialGradient(CX + 30 * Math.sin(t * .3), CY + 20 * Math.cos(t * .23), 0, CX, CY, 330);
  g.addColorStop(0, `rgba(${P.accentRgb},${.16 * (1 - lit) + .10 * lit})`); g.addColorStop(1, `rgba(${P.accentRgb},0)`); cx.fillStyle = g; cx.fillRect(0, 0, 540, 960);
  const line = lit > .5 ? '20,22,31' : P.accentRgb;
  const sm = m < 1 || back > 0 ? 0 : 1;  // decorations only once a shape has settled
  const ink = lit > .5 ? 'rgba(20,22,31,' : `rgba(${P.accentRgb},`;
  if (cur.fill && sm) { const f = cx.createRadialGradient(CX - 30, CY - 40, 10, CX, CY, 140); f.addColorStop(0, `rgba(${P.accent2Rgb},.95)`); f.addColorStop(1, `rgba(${P.accentRgb},.85)`);
    cx.beginPath(); pts.forEach(([x, y], i) => i ? cx.lineTo(x, y) : cx.moveTo(x, y)); cx.closePath(); cx.shadowColor = `rgba(${P.accentRgb},.7)`; cx.shadowBlur = 40; cx.fillStyle = f; cx.fill(); cx.shadowBlur = 0; }
  if (cur.glass && sm) { const [x0, y0, w, h] = cur.glass; const gl = cx.createLinearGradient(x0, y0, x0 + w, y0 + h); gl.addColorStop(0, `rgba(${P.accentRgb},.55)`); gl.addColorStop(1, `rgba(${P.accent2Rgb},.35)`);
    cx.beginPath(); pts.forEach(([x, y], i) => i ? cx.lineTo(x, y) : cx.moveTo(x, y)); cx.closePath(); cx.fillStyle = gl; cx.shadowColor = `rgba(${P.accentRgb},.6)`; cx.shadowBlur = 50; cx.fill(); cx.shadowBlur = 0; }
  (cur.rings || []).forEach(r => { if (!sm) return; cx.beginPath(); cx.arc(CX, CY, r, 0, TAU); cx.strokeStyle = ink + '.25)'; cx.lineWidth = 1; cx.stroke(); });
  (cur.arcs || []).forEach(r => { if (!sm) return; cx.beginPath(); cx.arc(CX, CY + 60, r, Math.PI, TAU); cx.strokeStyle = ink + '.35)'; cx.lineWidth = 1.5; cx.stroke(); });
  if (cur.rip) for (let j = 0; j < 3; j++) { const p = ((t * .6 + j / 3) % 1); cx.beginPath(); cx.ellipse(CX, CY + 40, 30 + 150 * p, 8 + 28 * p, 0, 0, TAU); cx.strokeStyle = ink + `${(.45 * (1 - p)).toFixed(3)})`; cx.lineWidth = 1.2; cx.stroke(); }
  // the line itself: a wide glow, then a bright core
  cx.beginPath(); pts.forEach(([x, y], i) => i ? cx.lineTo(x, y) : cx.moveTo(x, y));
  cx.lineJoin = 'round'; cx.lineCap = 'round';
  cx.shadowColor = `rgba(${line},.9)`; cx.shadowBlur = lit > .5 ? 6 : 22; cx.strokeStyle = `rgba(${line},.95)`; cx.lineWidth = 3; cx.stroke();
  cx.shadowBlur = 0; cx.strokeStyle = lit > .5 ? 'rgba(20,22,31,1)' : 'rgba(255,240,230,.9)'; cx.lineWidth = 1.2; cx.stroke();
  // dots
  if (sm || cur.rip) (cur.dots || []).forEach(([x, y, r]) => { cx.beginPath(); cx.arc(x, y, r, 0, TAU); cx.shadowColor = `rgba(${P.accentRgb},1)`; cx.shadowBlur = 18;
    cx.fillStyle = lit > .5 ? `rgb(${P.accentRgb})` : '#FFF1E6'; cx.fill(); cx.shadowBlur = 0; });
  // labels
  const labs = document.getElementById('labs'); labs.innerHTML = '';
  if (sm) (cur.labels || []).forEach(([l, x, y]) => { const d = document.createElement('div'); d.className = 'lab'; d.textContent = l; d.style.left = x + 'px'; d.style.top = y + 'px';
    if (cur.big) d.style.font = "600 22px Poppins"; d.style.opacity = prog(t, B[k].start + .6, .3); labs.appendChild(d); });
  // words
  const txt = document.getElementById('txt'), b = B[k], end = k + 1 < B.length ? B[k + 1].start : T - P.back;
  txt.innerHTML = ''; const q = prog(t, end - .3, .3);
  if (back === 0) b.words.forEach(([w, key, at]) => { const sp = document.createElement('span'); sp.textContent = w; if (key) sp.className = 'k';
    const p = at < 0 ? 1 : prog(t, at, .35); sp.style.opacity = p * (1 - q); sp.style.transform = `translateY(${((1 - expo(p)) * 12 - q * 10).toFixed(1)}px)`;
    sp.style.filter = p < 1 || q > 0 ? `blur(${((1 - p) * 8 + q * 6).toFixed(1)}px)` : 'none'; txt.appendChild(sp); });
  else B[0].words.forEach(([w, key]) => { const sp = document.createElement('span'); sp.textContent = w; if (key) sp.className = 'k'; sp.style.opacity = inout(back); txt.appendChild(sp); });
  document.getElementById('handle').style.opacity = k === B.length - 1 ? prog(t, B[k].start + 1, .5) * (1 - back) : 0;
}
window.renderAt = frame;
document.fonts.ready.then(() => { frame(0); window.SOUNDS = SOUNDS.sort((x, y) => x[0] - y[0]); window.READY = true; }).catch(e => { window.ERROR = String(e); });
window.onerror = m => { window.ERROR = String(m); };
</script></body></html>"""


def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return ','.join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def page(spec):
    import motion
    beats, total = timeline(spec)
    accent = render.THEMES['dark']['accent']
    params = {'beats': beats, 'total': total, 'back': BACK, 'beat': BEAT, 'handle': render.HANDLE, 'accent': accent,
              'accentRgb': _rgb(accent), 'accent2Rgb': _rgb('#FFB36B')}
    return PAGE.replace('<head>', '<head><style>' + motion.font_css() + '</style><script>window.PARAMS = '
                        + json.dumps(params).replace('</', '<\\/') + ';</script>', 1), total


def render_showcase(spec, out_path):
    """The showcase as an MP4 (frames from the page, its sound effects) and a cover JPEG beside it."""
    import stage
    html, total = page(spec)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp) / 'frames.mp4'
        sounds = stage.film(html, total, frames, label='showcase')
        wav = Path(tmp) / 'sfx.wav'
        sound_track(sounds, total, wav)
        stage.mux(frames, wav, out_path)
    cover = out_path.with_name(out_path.stem + '-cover.jpg')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{BEAT * 1.6:.2f}', '-i', str(out_path), '-frames:v', '1',
                    '-q:v', '2', str(cover)], check=True)
    return out_path, total


def sound_track(sounds, total, wav):
    """The effects alone (there is no voice): shaped noise from render.sound_kit, never music."""
    import wave
    kit = render.sound_kit(np.random.default_rng(11))
    track = np.zeros(int(render.SR * (total + 0.5)))
    for at, kind in sounds:
        s = kit[kind]() * render.SOUND_GAIN[kind] * 2.5
        i = int(at * render.SR)
        track[i:i + len(s)] += s[:max(0, len(track) - i)]
    peak = np.max(np.abs(track)) or 1.0
    track = (track / peak * 0.6)[:int(render.SR * total)]
    with wave.open(str(wav), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(render.SR)
        w.writeframes((track * 32767).astype(np.int16).tobytes())


# ---------- review and posting ----------

REVIEW_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['ok', 'problem'],
                 'properties': {'ok': {'type': 'boolean'}, 'problem': {'type': 'string'}}}
REVIEW = """You review frames of a short abstract motion reel before it is posted on Instagram. Open each frame with
the Read tool. ok is false if any frame shows a face, a person, a character, a mascot, an animal or a logo; if the
words are cut off, overlap the shapes badly or cannot be read; if a frame is broken (blank, garbled, glitched); or
if the words claim something untrue. Abstract glowing lines, dots, orbs and cards are expected. problem: one short
sentence, or an empty string."""


def review(path, spec, total):
    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for k in range(len(spec['beats'])):
            f = Path(tmp) / f'beat-{k}.png'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{k * BEAT + BEAT * 0.75:.2f}', '-i', str(path),
                            '-frames:v', '1', '-vf', 'scale=540:-1', str(f)], check=True)
            frames.append(f)
        prompt = ('Frames, one per beat, with the words meant to be on each:\n'
                  + '\n'.join(f"{f}: {b['text'].replace('*', '')}" for f, b in zip(frames, spec['beats'])))
        proc = subprocess.run(
            ['claude', '-p', prompt, '--model', os.environ.get('CLAUDE_MODEL') or 'claude-sonnet-5', '--system-prompt',
             REVIEW, '--tools', 'Read', '--allowedTools', 'Read', '--add-dir', tmp, '--setting-sources', '',
             '--no-session-persistence', '--output-format', 'json', '--json-schema', json.dumps(REVIEW_SCHEMA)],
            capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f'review failed: claude exited {proc.returncode}')
    return json.loads(proc.stdout).get('structured_output') or {'ok': False, 'problem': 'no verdict'}


def load():
    return json.loads(LOG.read_text()) if LOG.exists() else []


def posted_today(log, day=None):
    day = (day or datetime.now(timezone.utc).date()).isoformat()
    return any(e.get('media_id') and str(e.get('posted_at', '')).startswith(day) for e in log)


def main():
    import publish
    if len(sys.argv) == 3 and sys.argv[1] == '--render':
        spec = json.loads(Path(sys.argv[2]).read_text())
        problems = errors(spec)
        if problems:
            raise SystemExit('; '.join(problems))
        out, total = render_showcase(spec, render.OUT_DIR / f"showcase-{spec.get('id', 'test')}.mp4")
        print(f'Rendered {out} ({total:.1f}s)')
        return
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    publish.output('posted', 'false')
    log = load()
    if posted_today(log) and os.environ.get('FORCE_POST') != 'true':
        print('A showcase already went out today; FORCE_POST=true posts another')
        return
    spec = write(log)
    spec['id'] = max([e.get('id', 0) for e in log] + [0]) + 1
    print(f"Showcase #{spec['id']}: {spec['title']}\n" + '\n'.join(f"  {b['motif']:6} {b['text']}" for b in spec['beats']))
    out, total = render_showcase(spec, render.OUT_DIR / f"showcase-{spec['id']}.mp4")
    (render.OUT_DIR / f"showcase-{spec['id']}.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    verdict = review(out, spec, total)
    if not verdict.get('ok'):
        raise SystemExit(f"Showcase review failed: {verdict.get('problem')}; nothing posted")
    print('Review passed')
    caption = spec['caption'].strip() + '\n\n' + ' '.join(spec['hashtags'])
    if dry:
        print(f'DRY_RUN: not posting. Caption:\n{caption}')
        return
    stamp = int(datetime.now(timezone.utc).timestamp())
    name, cover_name = f'showcase-{spec["id"]}-{stamp}.mp4', f'showcase-{spec["id"]}-{stamp}-cover.jpg'
    url = publish.upload(out, name)
    cover_url = publish.upload(out.with_name(out.stem + '-cover.jpg'), cover_name, 'image/jpeg')
    try:
        media_id = publish.publish_to_instagram(url, caption, int(BEAT * 1.6 * 1000), cover_url)
    finally:
        publish.delete_upload(name)
        publish.delete_upload(cover_name)
    log.append({**spec, 'media_id': media_id, 'posted_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'seconds': round(total, 1)})
    LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False) + '\n')
    print(f'Posted showcase #{spec["id"]} as {media_id}')
    publish.output('posted', 'true')


if __name__ == '__main__':
    main()
