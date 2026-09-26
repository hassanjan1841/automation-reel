"""Real visuals for point slides: a code editor, a terminal, or a live screenshot of a web page.

A point may carry one of:
  {"type": "code", "language": "tsx", "code": "...", "highlight": [3]}
  {"type": "terminal", "commands": ["npm i drizzle-orm"]}
  {"type": "screenshot", "url": "https://supabase.com/docs/guides/database/postgres/row-level-security",
   "find": "Enable Row Level Security"}   the page is scrolled to that text, outlined and zoomed into

build() returns an object with draw(frame, t, alpha, dy), or None when the visual cannot be made
(a page that will not load, code that does not fit); the slide then falls back to its body text.
"""

import hashlib
import math
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import render

MONO_URL = 'https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf'
MONO = render.FONT_DIR / 'JetBrainsMono.ttf'
SHOTS = render.OUT_DIR / 'shots'
MAX_CODE_LINES, MAX_CODE_COLS = 12, 40
STAGE_MARGIN = 50
EDITOR = {'bg': '#1E2230', 'bar': '#161A25', 'text': '#E6E9F2', 'dim': '#7F8699', 'prompt': '#5AD17E'}
DOTS = ('#FF5F57', '#FEBC2E', '#28C840')

# One Dark-ish colors keyed by Pygments token type name prefix.
SYNTAX = [
    ('Comment', '#7F8699'), ('Keyword', '#C678DD'), ('Name.Function', '#61AFEF'), ('Name.Class', '#E5C07B'),
    ('Name.Builtin', '#56B6C2'), ('Name.Tag', '#E06C75'), ('Name.Attribute', '#D19A66'), ('Name.Decorator', '#61AFEF'),
    ('Literal.String', '#98C379'), ('Literal.Number', '#D19A66'), ('Operator', '#56B6C2'), ('Punctuation', '#ABB2BF'),
]


def mono(size):
    MONO.parent.mkdir(exist_ok=True)
    if not MONO.exists():
        urllib.request.urlretrieve(MONO_URL, MONO)
    return ImageFont.truetype(str(MONO), size)


def hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def color_for(token_type):
    name = str(token_type).replace('Token.', '')
    for prefix, color in SYNTAX:
        if name.startswith(prefix):
            return color
    return EDITOR['text']


def rounded_mask(w, h, r):
    ss = 3
    img = Image.new('L', (w * ss, h * ss), 0)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=r * ss, fill=255)
    return np.asarray(img.resize((w, h), Image.LANCZOS), dtype=np.float32) / 255.0


def window(w, h, title=''):
    """An editor-style window: rounded body, title bar with traffic-light dots."""
    img = Image.new('RGB', (w, h), EDITOR['bg'])
    d = ImageDraw.Draw(img)
    bar = 64
    d.rectangle((0, 0, w, bar), fill=EDITOR['bar'])
    for i, c in enumerate(DOTS):
        d.ellipse((28 + i * 34, bar // 2 - 10, 48 + i * 34, bar // 2 + 10), fill=c)
    if title:
        f = render.font('SemiBold', 26)
        d.text((w / 2, bar / 2), title, font=f, fill=EDITOR['dim'], anchor='mm')
    return img, bar


class Panel:
    """A pre-rendered window revealed row band by row band, with a highlight bar that fades in."""

    def __init__(self, img, rows, box, highlights=(), step=0.12, start=0.25):
        self.x, self.y = box[0], box[1]
        self.img = np.asarray(img, dtype=np.float32)
        self.mask = rounded_mask(img.width, img.height, 28)
        self.rows, self.step, self.start = rows, step, start
        self.highlights = highlights

    def draw(self, frame, t, alpha, dy):
        if alpha <= 0.003:
            return
        mask = self.mask.copy()
        # Hide rows not typed yet (everything below the current row band stays hidden, the chrome stays).
        shown = int((t - self.start) / self.step) + 1
        if shown < len(self.rows):
            cut = self.rows[max(shown, 0)][0]
            mask[cut:, :] = 0
        render.blend(frame, self.img, mask, alpha, self.x, self.y + dy)
        for i in self.highlights:
            if i < len(self.rows) and shown > i:
                y0, y1 = self.rows[i]
                p = render.ease_out(min(1.0, max(0.0, (t - self.start - self.step * len(self.rows) - 0.2) / 0.4)))
                if p > 0:
                    bar = np.ones((y1 - y0, self.img.shape[1] - 8), dtype=np.float32)
                    render.composite(frame, render.El(bar, np.array(hex_rgb('#FFFFFF'), dtype=np.float32), 0, 0, 0),
                                     alpha * 0.08 * p, self.x + 4, self.y + dy + y0)


def code_panel(visual, box):
    from pygments import lex
    from pygments.lexers import TextLexer, get_lexer_by_name
    lines = visual['code'].rstrip('\n').split('\n')
    if len(lines) > MAX_CODE_LINES or max(len(l) for l in lines) > MAX_CODE_COLS:
        raise ValueError(f'code is {len(lines)} lines x {max(len(l) for l in lines)} columns, max '
                         f'{MAX_CODE_LINES} x {MAX_CODE_COLS}')
    box = widen(box)
    w = box[2]
    # Largest readable size that fits the stage both ways.
    for size in range(42, 25, -2):
        line_h = round(size * 1.55)
        if mono(size).getlength('M' * max(len(l) for l in lines)) <= w - 80 and 64 + 72 + line_h * len(lines) <= box[3]:
            break
    else:
        raise ValueError('code does not fit the stage at a readable size')
    f = mono(size)
    img, bar = window(w, 64 + 36 + line_h * len(lines) + 36, visual.get('title', ''))
    d = ImageDraw.Draw(img)
    try:
        lexer = get_lexer_by_name(visual.get('language', 'text'))
    except Exception:
        lexer = TextLexer()
    y0 = bar + 36
    x, row = 40, 0
    rows = [(y0 + i * line_h, y0 + (i + 1) * line_h) for i in range(len(lines))]
    for token_type, text in lex(visual['code'].rstrip('\n'), lexer):
        for k, part in enumerate(text.split('\n')):
            if k:
                row += 1
                x = 40
            if part:
                d.text((x, y0 + row * line_h + (line_h - size) // 2), part, font=f, fill=color_for(token_type))
                x += f.getlength(part)
    highlights = [i - 1 for i in visual.get('highlight', []) if 1 <= i <= len(lines)]
    y = box[1] + (box[3] - img.height) // 2
    return Panel(img, rows, (box[0], y), highlights)


def terminal_panel(visual, box):
    cmds = visual.get('commands', [])[:6]
    if not cmds or max(len(c) for c in cmds) > MAX_CODE_COLS:
        raise ValueError(f'terminal needs 1 to 6 commands of max {MAX_CODE_COLS} characters')
    box = widen(box)
    w, size = box[2], 36
    f = mono(size)
    line_h = round(size * 1.7)
    img, bar = window(w, 64 + 36 + line_h * len(cmds) + 36, 'Terminal')
    d = ImageDraw.Draw(img)
    y0 = bar + 36
    for i, c in enumerate(cmds):
        y = y0 + i * line_h + (line_h - size) // 2
        d.text((40, y), '$', font=f, fill=EDITOR['prompt'])
        d.text((40 + f.getlength('$ '), y), c, font=f, fill=EDITOR['text'])
    rows = [(y0 + i * line_h, y0 + (i + 1) * line_h) for i in range(len(cmds))]
    y = box[1] + (box[3] - img.height) // 2
    return Panel(img, rows, (box[0], y), step=0.45)


def widen(box):
    """Visuals may use more width than text: the stage runs to STAGE_MARGIN from each edge."""
    x, y, w, h = box
    return (STAGE_MARGIN, y, render.W - 2 * STAGE_MARGIN, h)


def capture(url, find):
    """Phone-width screenshot scrolled to the text `find`, with that element outlined in the accent color.
    Returns the image and the outlined box (x0, y0, x1, y1) in image pixels. Cached per URL and text."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f'm4|{url}|{find}'.encode()).hexdigest()[:16]
    path, meta = SHOTS / f'{key}.png', SHOTS / f'{key}.txt'
    if path.exists() and meta.exists():
        return Image.open(path).convert('RGB'), tuple(float(v) for v in meta.read_text().split())
    from playwright.sync_api import sync_playwright
    # Phone width keeps text large; a wider page only when the target itself overflows at phone width
    # (docs code blocks do), since a cut-off line is worse than smaller text.
    for width, dpr, mobile in ((430, 2.5, True), (820, 1.4, False)):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': width, 'height': round(1100 * 430 / width * 2.5 / dpr)},
                                    device_scale_factor=dpr, is_mobile=mobile, has_touch=mobile, color_scheme='light')
            try:
                resp = page.goto(url, wait_until='networkidle', timeout=45000)
                if not resp or resp.status >= 400:
                    raise RuntimeError(f'HTTP {resp.status if resp else "no response"}')
                page.wait_for_timeout(1000)
                target = page.get_by_text(find, exact=False).first
                target.wait_for(state='visible', timeout=8000)
                overflows = target.evaluate(
                    'el => { for (let n = el; n && n !== document.body; n = n.parentElement)'
                    ' if (n.scrollWidth > n.clientWidth + 4 && getComputedStyle(n).overflowX !== "visible") return true;'
                    ' return el.getBoundingClientRect().right > window.innerWidth; }')
                if overflows and mobile:
                    continue
                target.evaluate('el => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 300)')
                page.wait_for_timeout(600)
                box = target.bounding_box()
                if not box or box['width'] < 20 or box['height'] < 10:
                    raise RuntimeError(f'"{find}" is not visible on the page')
                page.screenshot(path=str(path))
                break
            finally:
                browser.close()
    img = Image.open(path).convert('RGB')
    focus = (max(0.0, box['x'] * dpr), max(0.0, box['y'] * dpr),
             min(img.width - 1.0, (box['x'] + box['width']) * dpr), min(img.height - 1.0, (box['y'] + box['height']) * dpr))
    if np.asarray(img.convert('L'), dtype=np.float32).std() < 12:
        path.unlink()
        raise RuntimeError('screenshot is almost blank')
    meta.write_text(' '.join(f'{v:.1f}' for v in focus))
    return img, focus


class Screenshot:
    """A browser frame showing the full page width, scrolling down to the outlined element while everything
    else dims (a spotlight). No zoom: zooming a web page always cuts text off at the edges."""
    SECONDS, DIM = 2.2, 0.3

    def __init__(self, shot, focus, url, box, accent):
        box = widen(box)
        w = box[2]
        bar = 72
        h = min(box[3], round(w * 1.4))
        self.x, self.y, self.w, self.h, self.bar = box[0], box[1] + (box[3] - h) // 2, w, h, bar
        frame = Image.new('RGB', (w, h), '#E9EBF0')
        d = ImageDraw.Draw(frame)
        for i, c in enumerate(DOTS):
            d.ellipse((24 + i * 30, bar // 2 - 9, 42 + i * 30, bar // 2 + 9), fill=c)
        d.rounded_rectangle((140, 16, w - 30, bar - 16), radius=20, fill='#FFFFFF')
        host = url.split('//', 1)[-1].split('/', 1)[0]
        d.text((166, bar / 2), host, font=render.font('Regular', 26), fill='#5B6170', anchor='lm')
        self.chrome = np.asarray(frame, dtype=np.float32)
        self.mask = rounded_mask(w, h, 26)
        scale = w / shot.width
        page = shot.resize((w, round(shot.height * scale)), Image.LANCZOS)
        fx0, fy0, fx1, fy1 = (v * scale for v in focus)
        pad = 14
        rect = (max(fx0 - pad, 3), fy0 - pad, min(fx1 + pad, w - 4), fy1 + pad)
        self.page = np.asarray(page, dtype=np.float32)
        lit = Image.new('L', page.size, 0)
        ImageDraw.Draw(lit).rounded_rectangle(rect, radius=14, fill=255)
        self.lit = np.asarray(lit, dtype=np.float32)[..., None] / 255.0
        ring = Image.new('L', page.size, 0)
        ImageDraw.Draw(ring).rounded_rectangle(rect, radius=14, outline=255, width=6)
        self.ring = np.asarray(ring, dtype=np.float32)[..., None] / 255.0
        self.accent = np.array(accent, dtype=np.float32)
        view_h = h - bar
        # Start near the top of the page and settle with the element a third of the way down the view.
        self.end_top = min(max(0.0, (fy0 + fy1) / 2 - view_h / 3), max(0.0, page.height - view_h))
        self.start_top = max(0.0, self.end_top - view_h * 0.6)

    def draw(self, frame, t, alpha, dy):
        if alpha <= 0.003:
            return
        p = min(1.0, max(0.0, (t - 0.3) / self.SECONDS))
        p = 0.5 - 0.5 * math.cos(math.pi * p)
        view_h = self.h - self.bar
        top = round(self.start_top + (self.end_top - self.start_top) * p)
        page = self.page[top:top + view_h]
        lit, ring = self.lit[top:top + view_h], self.ring[top:top + view_h]
        # The spotlight and outline come in once the scroll arrives.
        s = min(1.0, max(0.0, (t - 0.3 - self.SECONDS * 0.7) / 0.5))
        shade = 1 - self.DIM * s * (1 - lit)
        view = page * shade
        view += (self.accent - view) * ring * s
        img = self.chrome.copy()
        img[self.bar:self.bar + len(view), :] = view
        render.blend(frame, img, self.mask, alpha, self.x, self.y + dy)


def build(visual, theme, box):
    kind = (visual or {}).get('type')
    try:
        if kind == 'code':
            return code_panel(visual, box)
        if kind == 'terminal':
            return terminal_panel(visual, box)
        if kind == 'screenshot':
            if not visual.get('find'):
                raise ValueError('a screenshot needs the text to show ("find")')
            shot, focus = capture(visual['url'], visual['find'])
            return Screenshot(shot, focus, visual['url'], box, render.rgb(theme['accent']))
    except Exception as e:  # a visual is a bonus; the slide falls back to text rather than failing the post
        print(f'  visual skipped ({kind}: {type(e).__name__}: {str(e)[:120]})')
    return None
