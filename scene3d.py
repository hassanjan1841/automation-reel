"""3D moments for reels, drawn with three.js in headless Chromium and rendered frame by frame (the clock is ours,
so motion is smooth and exactly as long as asked). Objects, text, devices and diagrams only: no people or animals.

A point (or the hook) may carry one of:
  {"type": "diagram", "nodes": [{"id": "app", "label": "Browser", "kind": "client"}, ...],
   "edges": [{"from": "app", "to": "api"}, ...], "flow": ["app>api", "api>cache", "cache>api", "api>app"]}
      kinds: client, server, db, cache, queue, cloud, phone, lock
  {"type": "word", "text": "RLS"}                     the hook word in extruded 3D, transparent background
  {"type": "device", "device": "laptop" | "phone", "show": <a code, diff or screenshot visual>}
      laptop for code; phone only for a screenshot (code is unreadable on a phone-width screen)
  {"type": "bars", "title": "...", "unit": "ms", "bars": [{"label": "Node", "value": 42}], "source": "https://..."}
  {"type": "logos", "items": ["nextdotjs", "supabase", "stripe"]}   Simple Icons slugs (CC0 logos)

Usage: python scene3d.py '<json>' [width height seconds]   renders out/scenes/<hash>.mp4 and prints the path
"""

import base64
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import render

SCENES = render.OUT_DIR / 'scenes'
# Logos that are animals or mascots (the creator's rule: no faces or animals in visuals).
ANIMAL_LOGOS = {'postgresql', 'docker', 'mysql', 'mariadb', 'linux', 'github', 'gitlab', 'firefox', 'firefoxbrowser',
                'mastodon', 'python', 'duckdb', 'apachehadoop', 'ollama', 'huggingface', 'swift', 'hasura', 'reddit',
                'discord', 'twitter', 'openbsd', 'freebsd', 'nestjs', 'deno', 'jenkins', 'rabbitmq', 'mozilla',
                'tor', 'thunderbird', 'squarespace', 'sentry', 'bluesky'}
THREE = 'https://cdn.jsdelivr.net/npm/three@0.170.0'
FPS = 30

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:transparent;overflow:hidden}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"THREE/build/three.module.js","three/addons/":"THREE/examples/jsm/"}}</script>
</head><body><script type="module">
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { FontLoader } from 'three/addons/loaders/FontLoader.js';
import { TextGeometry } from 'three/addons/geometries/TextGeometry.js';
import { SVGLoader } from 'three/addons/loaders/SVGLoader.js';

const W = innerWidth, H = innerHeight;
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(W, H);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, W / H, 0.1, 200);
const ease = p => 1 - Math.pow(1 - Math.min(Math.max(p, 0), 1), 3);
const back = p => { p = Math.min(Math.max(p, 0), 1) - 1; return 1 + p * p * (2.7 * p + 1.7); };

function lights(dark) {
  scene.add(new THREE.HemisphereLight(0xffffff, dark ? 0x202840 : 0xc8bfae, dark ? 1.1 : 1.6));
  const key = new THREE.DirectionalLight(0xffffff, dark ? 2.2 : 2.6);
  key.position.set(4, 8, 6); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048); key.shadow.radius = 6;
  Object.assign(key.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12 });
  scene.add(key);
  const rim = new THREE.DirectionalLight(new THREE.Color(P.accent), P.spec.type === 'logos' ? 0.25 : 1.2);
  rim.position.set(-6, 3, -4); scene.add(rim);
}
function floor(y) {
  const g = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.ShadowMaterial({ opacity: P.dark ? 0.35 : 0.18 }));
  g.rotation.x = -Math.PI / 2; g.position.y = y; g.receiveShadow = true; scene.add(g);
}
function label(text, size, color, weight) {
  const c = document.createElement('canvas'), s = 4, x = c.getContext('2d');
  x.font = `${weight || 700} ${size * s}px Poppins, Inter, Arial, sans-serif`;
  const w = Math.ceil(x.measureText(text).width) + 20 * s;
  c.width = w; c.height = size * s * 1.6;
  x.font = `${weight || 700} ${size * s}px Poppins, Inter, Arial, sans-serif`;
  x.fillStyle = color; x.textAlign = 'center'; x.textBaseline = 'middle';
  x.fillText(text, w / 2, c.height / 2);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w / (size * s) * 0.42, c.height / (size * s) * 0.42),
    new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false }));
  return m;
}
const mat = (color, rough) => new THREE.MeshStandardMaterial({ color, roughness: rough ?? 0.45, metalness: 0.08 });

// ---------- 1. diagram ----------
const ICON = { client: 'box', phone: 'phone', server: 'box', db: 'cyl', cache: 'box', queue: 'queue', cloud: 'cloud',
               lock: 'box' };
const TINT = { client: 0x5b8def, phone: 0x5b8def, server: 0x7c5cff, db: 0x2bb673, cache: 0xff9f1c, queue: 0xe85d75,
               cloud: 0x3fb5d6, lock: 0x9aa3b2 };
function node(n) {
  const g = new THREE.Group(), kind = ICON[n.kind] || 'box', col = TINT[n.kind] || 0x7c5cff;
  let body;
  if (kind === 'cyl') {
    body = new THREE.Group();
    for (let i = 0; i < 3; i++) {
      const d = new THREE.Mesh(new THREE.CylinderGeometry(0.72, 0.72, 0.36, 48), mat(col));
      d.position.y = i * 0.42; d.castShadow = true; body.add(d);
    }
    body.position.y = -0.4;
  } else if (kind === 'phone') {
    body = new THREE.Mesh(new RoundedBoxGeometry(0.9, 1.6, 0.14, 6, 0.1), mat(0x1c1f27, 0.3));
    body.castShadow = true;
    const s = new THREE.Mesh(new THREE.PlaneGeometry(0.78, 1.42), mat(col, 0.2)); s.position.z = 0.075; body.add(s);
  } else if (kind === 'queue') {
    body = new THREE.Group();
    for (let i = 0; i < 4; i++) {
      const b = new THREE.Mesh(new RoundedBoxGeometry(0.34, 0.9, 0.9, 4, 0.06), mat(col));
      b.position.x = (i - 1.5) * 0.4; b.castShadow = true; body.add(b);
    }
  } else if (kind === 'cloud') {
    body = new THREE.Group();
    [[0, 0.1, 0.6], [-0.55, -0.1, 0.45], [0.55, -0.1, 0.45], [0.25, 0.3, 0.42]].forEach(([x, y, r]) => {
      const s = new THREE.Mesh(new THREE.SphereGeometry(r, 32, 24), mat(col, 0.6)); s.position.set(x, y, 0);
      s.castShadow = true; body.add(s);
    });
  } else {
    body = new THREE.Mesh(new RoundedBoxGeometry(1.5, 1.05, 1.05, 6, 0.14), mat(col));
    body.castShadow = true;
    if (n.kind === 'lock') {
      const sh = new THREE.Mesh(new THREE.TorusGeometry(0.28, 0.07, 16, 32, Math.PI), mat(0x9aa3b2, 0.3));
      sh.position.y = 0.52; body.add(sh);
    }
  }
  g.add(body);
  const l = label(n.label, 40, P.ink, 700); l.position.set(0, 1.25, 0); g.add(l);
  return g;
}
function diagram() {
  const nodes = P.spec.nodes, n = nodes.length, gap = n > 3 ? 2.6 : 3.1;
  const pos = {};
  nodes.forEach((nd, i) => {
    const g = node(nd);
    const x = (i - (n - 1) / 2) * gap, z = (i % 2 ? -0.6 : 0.4) * (n > 3 ? 1 : 0);
    g.position.set(x, 0, z); g.userData = { i, x, z }; scene.add(g); pos[nd.id] = g;
  });
  const lines = [];
  (P.spec.edges || []).forEach(e => {
    const a = pos[e.from], b = pos[e.to]; if (!a || !b) return;
    const pts = [a.position.clone(), b.position.clone()].map(v => v.setY(0.05));
    const tube = new THREE.Mesh(new THREE.TubeGeometry(new THREE.LineCurve3(pts[0], pts[1]), 8, 0.035, 8),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(P.muted), transparent: true, opacity: 0.55 }));
    scene.add(tube); lines.push(tube);
  });
  const packet = new THREE.Mesh(new THREE.SphereGeometry(0.26, 32, 24),
    new THREE.MeshStandardMaterial({ color: P.accent, emissive: P.accent, emissiveIntensity: 2.2 }));
  const glow = new THREE.PointLight(new THREE.Color(P.accent), 14, 5); packet.add(glow);
  scene.add(packet);
  // A short fading trail makes the direction of travel readable at phone size.
  const trail = [1, 2, 3, 4].map(i => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.26 * (1 - i * 0.18), 20, 16),
    new THREE.MeshBasicMaterial({ color: P.accent, transparent: true, opacity: 0.5 - i * 0.1, blending: THREE.AdditiveBlending, depthWrite: false })); scene.add(m); return m; });
  floor(-0.62);
    const span = (n - 1) * gap + 2.6, hfov = Math.atan(Math.tan(THREE.MathUtils.degToRad(17.5)) * W / H);
  camera.position.set(0, 3.0, Math.max(7.5, span / 2 / Math.tan(hfov) + 1.2)); camera.lookAt(0, 0.2, 0);
  const flow = (P.spec.flow || []).map(s => s.split('>')).filter(([a, b]) => pos[a] && pos[b]);
  const intro = 0.6 + 0.18 * n, hop = Math.max(0.55, (P.seconds - intro - 0.4) / Math.max(1, flow.length));
  return t => {
    nodes.forEach(nd => { const g = pos[nd.id], p = back((t - 0.1 - 0.18 * g.userData.i) / 0.5);
      g.scale.setScalar(Math.max(0.001, p)); g.position.y = (1 - Math.min(1, p)) * -0.6 + 0.05 * Math.sin(t * 1.6 + g.userData.i); });
    lines.forEach(l => { l.material.opacity = 0.55 * ease((t - intro + 0.3) / 0.4); });
    const k = Math.floor((t - intro) / hop), f = ((t - intro) / hop) - k;
    const at = (k, f) => { const [a, b] = flow[k], pa = pos[a].position, pb = pos[b].position, e = ease(f);
      return [pa.x + (pb.x - pa.x) * e, 0.45 + Math.sin(Math.PI * e) * 0.9, pa.z + (pb.z - pa.z) * e]; };
    const on = t >= intro && k < flow.length;
    packet.visible = on; trail.forEach(m => { m.visible = on; });
    if (on) {
      packet.position.set(...at(k, f));
      trail.forEach((m, i) => m.position.set(...at(k, Math.max(0, f - (i + 1) * 0.06))));
    }
    const o = t * 0.06;
    camera.position.x = Math.sin(o) * 0.8; camera.lookAt(0, 0.2, 0);
  };
}

// ---------- 2. word ----------
async function word() {
  const font = await new FontLoader().loadAsync('THREE/examples/fonts/helvetiker_bold.typeface.json');
  const geo = new TextGeometry(P.spec.text, { font, size: 1, depth: 0.32, curveSegments: 10, bevelEnabled: true,
    bevelThickness: 0.05, bevelSize: 0.035, bevelSegments: 5 });
  geo.computeBoundingBox(); geo.center();
  const width = geo.boundingBox.max.x - geo.boundingBox.min.x;
  const mesh = new THREE.Mesh(geo, [new THREE.MeshStandardMaterial({ color: P.accent, roughness: 0.3, metalness: 0.2 }),
                                    new THREE.MeshStandardMaterial({ color: new THREE.Color(P.accent).multiplyScalar(0.55),
                                                                     roughness: 0.5 })]);
  mesh.castShadow = true; scene.add(mesh);
  floor(-0.9);
  const dist = Math.max(5.2, width * 1.9 / (W / H));
  camera.position.set(0, 0.9, dist); camera.lookAt(0, 0, 0);
  return t => {
    const p = back(t / 0.9);
    mesh.rotation.y = (1 - Math.min(1, ease(t / 1.1))) * -1.9 + 0.12 * Math.sin(t * 1.3);
    mesh.rotation.x = (1 - Math.min(1, ease(t / 1.1))) * 0.6;
    mesh.scale.setScalar(Math.max(0.001, 0.35 + 0.65 * p));
    mesh.position.y = 0.06 * Math.sin(t * 2);
  };
}

// ---------- 3. device ----------
async function device() {
  const tex = await new THREE.TextureLoader().loadAsync(P.image);
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  const phone = P.spec.device === 'phone', g = new THREE.Group();
  const aspect = tex.image.width / tex.image.height;
  if (phone) {
    const h = 3.4, w = 1.7;
    const body = new THREE.Mesh(new RoundedBoxGeometry(w + 0.18, h + 0.3, 0.16, 8, 0.14), mat(0x15171d, 0.35));
    body.castShadow = true; g.add(body);
    const glass = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: 0x0d1117 }));
    glass.position.z = 0.082; g.add(glass);
    // Fit the picture to the screen width so it is never squashed.
    const ih = Math.min(h, w / aspect), iw = ih * aspect;
    const s = new THREE.Mesh(new THREE.PlaneGeometry(iw, ih), new THREE.MeshBasicMaterial({ map: tex }));
    s.position.set(0, ih < h * 0.6 ? 0.25 : (h - ih) / 2, 0.085); g.add(s);
  } else {
    const w = 4.2, h = w / 1.6;
    const lid = new THREE.Group();
    const bezel = new THREE.Mesh(new RoundedBoxGeometry(w + 0.24, h + 0.24, 0.1, 6, 0.08), mat(0x23262e, 0.35));
    bezel.castShadow = true; lid.add(bezel);
    const glass = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: 0x0d1117 }));
    glass.position.z = 0.052; lid.add(glass);
    const iw = Math.min(w, h * aspect), ih = iw / aspect;
    const s = new THREE.Mesh(new THREE.PlaneGeometry(iw, ih), new THREE.MeshBasicMaterial({ map: tex }));
    s.position.set(0, (h - ih) / 2, 0.055); lid.add(s);
    lid.position.set(0, h / 2 + 0.1, -0.05);
    const base = new THREE.Mesh(new RoundedBoxGeometry(w + 0.4, 0.1, 2.3, 6, 0.05), mat(0x8e939e, 0.4));
    base.position.set(0, 0, 1.1); base.castShadow = true;
    g.add(lid, base); g.userData.lid = lid;
    g.position.y = -h / 2 + 0.3;
  }
  scene.add(g); floor(phone ? -1.9 : g.position.y - 0.08);
  camera.position.set(0, phone ? 0.6 : 0.9, phone ? 6.6 : 7.8); camera.lookAt(0, phone ? 0.1 : 0.25, 0);
  return t => {
    const p = ease(t / 1.2);
    g.rotation.y = (1 - p) * 0.9 + 0.22 * Math.sin(t * 0.45);
    g.rotation.x = (1 - p) * 0.35;
    if (g.userData.lid) g.userData.lid.rotation.x = (1 - ease(t / 1.4)) * 1.3;
    g.scale.setScalar(0.7 + 0.3 * back(t / 0.9));
  };
}

// ---------- 4. bars ----------
function bars() {
  const items = P.spec.bars, n = items.length, max = Math.max(...items.map(b => b.value)) || 1, gap = 1.35;
  const cols = items.map((b, i) => {
    const g = new THREE.Group();
    const m = new THREE.Mesh(new RoundedBoxGeometry(0.9, 1, 0.9, 4, 0.08), mat(i === items.findIndex(x => x.value === max)
      ? new THREE.Color(P.accent) : new THREE.Color(P.dark ? 0x5c6680 : 0x9aa3b2)));
    m.castShadow = true; m.position.y = 0.5; g.add(m);
    const l = label(b.label, 34, P.ink, 700); l.position.set(0, -0.35, 0.5); g.add(l);
    g.position.x = (i - (n - 1) / 2) * gap; scene.add(g);
    return { g, m, h: 0.3 + 3.2 * b.value / max, b, v: null };
  });
  if (P.spec.title) { const tl = label(P.spec.title, 44, P.ink, 700); tl.position.set(0, 4.5, 0); scene.add(tl); }
  floor(0);
  camera.position.set(0, 2.6, Math.max(11, n * 2.6)); camera.lookAt(0, 2.1, 0);
  return t => cols.forEach((c, i) => {
    const p = ease((t - 0.2 - i * 0.18) / 1.0), h = Math.max(0.001, c.h * p);
    c.m.scale.y = h; c.m.position.y = h / 2;
    const val = Math.round(c.b.value * p * 10) / 10, text = `${Number.isInteger(c.b.value) ? Math.round(val) : val}${P.spec.unit || ''}`;
    if (c.v) c.g.remove(c.v);
    c.v = label(text, 36, P.ink, 600); c.v.position.set(0, h + 0.4, 0.5); c.g.add(c.v);
  });
}

// ---------- 5. logos ----------
async function logos() {
  const items = P.spec.items.slice(0, 5), group = new THREE.Group(), meshes = [];
  for (const [i, slug] of items.entries()) {
    const res = await fetch(`https://cdn.jsdelivr.net/npm/simple-icons@13/icons/${slug}.svg`);
    const data = new SVGLoader().parse(await res.text());
    const shapes = data.paths.flatMap(p => SVGLoader.createShapes(p));
    const geo = new THREE.ExtrudeGeometry(shapes, { depth: 2.4, bevelEnabled: true, bevelThickness: 0.5, bevelSize: 0.3,
                                                     bevelSegments: 3, curveSegments: 14 });
    geo.center(); geo.scale(0.06, -0.06, 0.06);
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: P.dark ? 0xf2f3f5 : 0x1b1e26, roughness: 0.4,
                                                                   metalness: 0.05 }));
    m.castShadow = true;
    m.position.x = (i - (items.length - 1) / 2) * 2.1; group.add(m); meshes.push(m);
  }
  scene.add(group); floor(-1.1);
  const span = (items.length - 1) * 2.1 + 2.4, hfov = Math.atan(Math.tan(THREE.MathUtils.degToRad(17.5)) * W / H);
  camera.position.set(0, 0.7, Math.max(5.5, span / 2 / Math.tan(hfov) + 0.8)); camera.lookAt(0, 0, 0);
  return t => meshes.forEach((m, i) => {
    const p = back((t - 0.15 - i * 0.2) / 0.7);
    m.scale.setScalar(Math.max(0.001, p));
    m.rotation.y = (1 - Math.min(1, ease((t - 0.15 - i * 0.2) / 1))) * Math.PI + 0.25 * Math.sin(t * 0.9 + i);
    m.position.y = 0.08 * Math.sin(t * 1.7 + i);
  });
}

const P = window.PARAMS;
lights(P.dark);
await Promise.all(['700', '600'].map(w => document.fonts.load(`${w} 40px Poppins`)));
const build = { diagram, word, device, bars, logos }[P.spec.type];
const step = await build();
window.renderAt = t => { step(t); renderer.render(scene, camera); };
window.READY = true;
</script></body></html>"""


def device_image(spec, theme):
    """The picture on the device screen: a code, diff or screenshot visual drawn by visuals.py, as a data URL."""
    import visuals
    show = spec.get('show') or {}
    if show.get('type') == 'screenshot':
        img, _ = visuals.capture(show['url'], show['find'])
    else:
        code = show.get('code') or show.get('after') or '// ...'
        # As narrow as the longest line at full size, so short code fills the device screen instead of a corner.
        longest = max(len(l) for l in code.rstrip('\n').split('\n'))
        w = int(min(1200, max(560, visuals.mono(42).getlength('M' * longest) + 130)))
        img, _ = visuals.code_image(code, show.get('language'), show.get('title', ''), w, 1400)
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=90)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def render_scene(spec, theme, size, seconds=6.0, transparent=False):
    """Render a scene to an mp4 (or, with transparent, a list of RGBA PNG frames for compositing). Cached."""
    key = hashlib.sha1(json.dumps({**spec, 'theme': theme['bg'], 'size': size, 's': seconds, 'a': transparent, 'page': hashlib.sha1(PAGE.encode()).hexdigest()},
                                  sort_keys=True).encode()).hexdigest()[:16]
    SCENES.mkdir(parents=True, exist_ok=True)
    out = SCENES / (f'{key}.mp4' if not transparent else f'{key}')
    if (out.exists() and not transparent) or (transparent and out.exists() and any(out.iterdir())):
        return out
    params = {'spec': spec, 'seconds': seconds, 'dark': theme is render.THEMES['dark'], 'accent': theme['accent'],
              'ink': theme['ink'], 'muted': theme['muted']}
    if spec['type'] == 'device':
        params['image'] = device_image(spec, theme)
    from playwright.sync_api import sync_playwright
    dpr = 2
    w, h = size[0] // dpr, size[1] // dpr
    fonts = ''.join(f"@font-face{{font-family:Poppins;font-weight:{wt};src:url(data:font/ttf;base64,"
                    f"{base64.b64encode((render.FONT_DIR / f'Poppins-{name}.ttf').read_bytes()).decode()})}}"
                    for wt, name in (('700', 'Bold'), ('600', 'SemiBold')))
    html = PAGE.replace('THREE/', THREE + '/').replace('<head>', '<head><style>' + fonts + '</style><script>window.PARAMS = '
                                                        + json.dumps(params).replace('</', '<\\/') + ';</script>', 1)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch(args=[f'--force-device-scale-factor={dpr}', '--use-angle=swiftshader',
                                          '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        page = browser.new_page(viewport={'width': w, 'height': h}, device_scale_factor=dpr)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.set_content(html, wait_until='domcontentloaded')
        try:
            page.wait_for_function('window.READY === true', timeout=60000)
        except Exception:
            raise RuntimeError(f'3D scene did not load: {errors or "no error reported"}') from None
        frames = round(seconds * FPS)
        folder = Path(tmp) if not transparent else out
        folder.mkdir(exist_ok=True)
        for f in range(frames):
            page.evaluate(f'window.renderAt({f / FPS})')
            page.screenshot(path=str(folder / f'{f:04d}.png'), omit_background=True)
        browser.close()
        if not transparent:
            bg = theme['bg'].lstrip('#')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=0x{bg}:s={size[0]}x{size[1]}:r={FPS}',
                            '-framerate', str(FPS), '-i', str(Path(tmp) / '%04d.png'),
                            '-filter_complex', '[0][1]overlay=shortest=1', '-c:v', 'libx264', '-crf', '17',
                            '-pix_fmt', 'yuv420p', str(out)], check=True)
    return out


def main():
    if len(sys.argv) not in (2, 5):
        raise SystemExit(__doc__)
    spec = json.loads(sys.argv[1])
    size = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) == 5 else (980, 620)
    seconds = float(sys.argv[4]) if len(sys.argv) == 5 else 6.0
    render.ensure_fonts()
    print(render_scene(spec, render.THEMES['dark'], size, seconds))


if __name__ == '__main__':
    main()
