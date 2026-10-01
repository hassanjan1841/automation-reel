"""Real visuals for point slides: a code editor, a before/after diff, a terminal, a post card, a chat, or a live
screenshot of a web page.

A point may carry one of:
  {"type": "code", "language": "tsx", "code": "...", "highlight": [3]}
  {"type": "diff", "language": "ts", "before": "...", "after": "..."}       old lines go red, new ones come in green
  {"type": "terminal", "commands": ["npm i drizzle-orm"]}                  typed out with key clicks
  {"type": "tweet", "text": "Junior dev: ... Senior dev: ..."}              a post card in the creator's own name
  {"type": "chat", "messages": [{"from": "client", "text": "..."}, {"from": "me", "text": "..."}]}
  {"type": "quote", "author": "...", "handle": "@...", "platform": "X", "url": "https://...", "text": "..."}
                                                                          a real public post, credited, verbatim
  {"type": "walkthrough", ...} or {"type": "ide", ...}   a real screen recording, see demos.py
  {"type": "diagram" | "device" | "bars" | "logos", ...}   a 3D scene, see scene3d.py
  {"type": "screenshot", "url": "https://supabase.com/docs/guides/database/postgres/row-level-security",
   "find": "Enable Row Level Security"}   scrolled to that text, a cursor glides over and clicks it, spotlit

build() returns a Card with draw(frame, t, alpha, dy), `duration` (set by render once slide lengths are known)
and `sounds` [(t, kind)], or None when the visual cannot be made (a page that will not load, code that does not
fit); the slide then falls back to its body text.
"""

import hashlib
import math
import subprocess
import re
import textwrap
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
SHADOW = np.zeros(3, dtype=np.float32)
BG = np.array([int(EDITOR['bg'][i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)
RED, GREEN = '#E5534B', '#3FB950'
AUTHOR, AUTHOR_HANDLE = 'Hassan Jan', render.HANDLE

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


def widen(box):
    """Visuals may use more width than text: the stage runs to STAGE_MARGIN from each edge."""
    x, y, w, h = box
    return (STAGE_MARGIN, y, render.W - 2 * STAGE_MARGIN, h)


# ---------- 3D tilt ----------

def perspective_coeffs(src, dst):
    """PIL PERSPECTIVE coefficients mapping output points dst to input points src."""
    rows = []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    b = np.array([c for p in src for c in p], dtype=np.float64)
    return np.linalg.solve(np.array(rows, dtype=np.float64), b)


def tilted(rgb, mask, rx, ry, focal=1700.0):
    """The card rotated rx/ry degrees around its centre and projected, on a canvas of the same size."""
    h, w = mask.shape
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    ax, ay = math.radians(rx), math.radians(ry)
    dst = []
    for x, y in corners:
        # rotate around Y, then X; z grows away from the viewer
        x1, z1 = x * math.cos(ay), -x * math.sin(ay)
        y2, z2 = y * math.cos(ax) - z1 * math.sin(ax), y * math.sin(ax) + z1 * math.cos(ax)
        k = focal / (focal + z2)
        dst.append((x1 * k + w / 2, y2 * k + h / 2))
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    c = perspective_coeffs(src, dst)
    rgba = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), mask[..., None] * 255]).astype(np.uint8), 'RGBA')
    out = np.asarray(rgba.transform((w, h), Image.PERSPECTIVE, tuple(c), resample=Image.BILINEAR), dtype=np.float32)
    return out[..., :3], out[..., 3] / 255.0


def sketch_ellipse(rect, seed, loops=1.15, wobble=6.0, n=160):
    """Points of a hand-drawn loop around rect (x0, y0, x1, y1): slightly irregular, overshooting its start."""
    rng = np.random.default_rng(seed)
    x0, y0, x1, y1 = rect
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 + 26, (y1 - y0) / 2 + 18
    phase = rng.uniform(0, 2 * math.pi)
    k1, k2 = rng.uniform(-1, 1, 2)
    pts = []
    for i in range(n):
        a = -2.4 + 2 * math.pi * loops * i / (n - 1)
        r = 1 + 0.04 * math.sin(3 * a + phase) + 0.025 * math.sin(5 * a + 1.3 * phase)
        pts.append((cx + rx * r * math.cos(a) + k1 * wobble * i / n, cy + ry * r * math.sin(a) + k2 * wobble * i / n))
    return pts


def sketch_underline(x0, x1, y, seed, n=60):
    """A hand-drawn underline: a slight arc with a little wobble."""
    rng = np.random.default_rng(seed)
    tilt, bow = rng.uniform(-4, 4), rng.uniform(3, 8)
    return [(x0 + (x1 - x0) * i / (n - 1), y + tilt * (i / (n - 1) - 0.5) - bow * math.sin(math.pi * i / (n - 1))
             + 1.2 * math.sin(i * 0.9)) for i in range(n)]


def stroke(rgb, pts, p, color, width=6):
    """Draw the first fraction p of a path onto rgb (float array) in color, as if drawn with a marker."""
    if p <= 0:
        return
    k = max(2, int(len(pts) * min(1.0, p)))
    h, w = rgb.shape[:2]
    ss = 2
    img = Image.new('L', (w * ss, h * ss), 0)
    ImageDraw.Draw(img).line([(x * ss, y * ss) for x, y in pts[:k]], fill=255, width=width * ss, joint='curve')
    m = np.asarray(img.resize((w, h), Image.BILINEAR), dtype=np.float32)[..., None] / 255.0
    rgb += (np.asarray(color, dtype=np.float32) - rgb) * m


class Card:
    """A floating card: two-layer shadow, a 3D tilt entrance that settles flat, and per-frame content from
    layer(t) -> (rgb, mask). Subclasses fill self.sounds with (t, kind) for the sound track."""
    TILT, TILT_X, TILT_Y = 0.7, 9.0, -13.0

    def __init__(self, x, y, w, h, radius=28):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.mask = rounded_mask(w, h, radius)
        self.shadows = render.shadow_layers(self.mask, (4, 8, 0.35), (18, 44, 0.22))
        self.duration = 4.0
        self.sounds = []

    def layer(self, t):
        raise NotImplementedError

    @property
    def settle(self):
        """Seconds until the card has landed and shows its content; a card that must be complete on its slide's
        first frame (the hook's proof) is drawn from this point in its own timeline."""
        return self.TILT

    def draw(self, frame, t, alpha, dy):
        if alpha <= 0.003:
            return
        rgb, mask = self.layer(t)
        p = min(1.0, max(0.0, t / self.TILT))
        if p < 1:
            e = 1 - render.ease_out(p)
            rgb, mask = tilted(rgb, mask, self.TILT_X * e, self.TILT_Y * e)
        for m, ox, oy, a in self.shadows:
            render.composite(frame, render.El(m, SHADOW, 0, 0, 0), alpha * a * (0.4 + 0.6 * p), self.x + ox,
                             self.y + dy + oy)
        s = (t - self.SHEEN_AT) / self.SHEEN
        if 0 < s < 1:
            rgb = rgb + self.sheen(s)
        render.blend(frame, rgb, mask, alpha, self.x, self.y + dy)

    SHEEN_AT, SHEEN = 0.55, 0.9

    def sheen(self, s):
        """A soft diagonal band of light that sweeps across the card once after it lands."""
        if not hasattr(self, '_diag'):
            yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
            self._diag = (xx + yy * 0.6) / (self.w + self.h * 0.6)
        centre = -0.2 + 1.4 * render.ease_out(s)
        band = np.exp(-((self._diag - centre) / 0.06) ** 2) * 38 * math.sin(math.pi * s)
        return band[..., None]


# ---------- code ----------

def code_image(code, language, title, w, max_h, marks=None, with_char_w=False):
    """A syntax-highlighted editor window. marks: {line index: (color, strike)} tints whole lines.
    Returns (image, row bands) or raises when the code cannot be read at a comfortable size."""
    from pygments import lex
    from pygments.lexers import TextLexer, get_lexer_by_name
    lines = code.rstrip('\n').split('\n')
    if len(lines) > MAX_CODE_LINES or max(len(l) for l in lines) > MAX_CODE_COLS:
        raise ValueError(f'code is {len(lines)} lines x {max(len(l) for l in lines)} columns, max '
                         f'{MAX_CODE_LINES} x {MAX_CODE_COLS}')
    for size in range(54, 25, -2):  # short snippets get big type: code is what people read
        line_h = round(size * 1.55)
        if mono(size).getlength('M' * max(len(l) for l in lines)) <= w - 110 and 64 + 72 + line_h * len(lines) <= max_h:
            break
    else:
        raise ValueError('code does not fit the stage at a readable size')
    f = mono(size)
    img, bar = window(w, 64 + 36 + line_h * len(lines) + 36, title)
    d = ImageDraw.Draw(img, 'RGBA')
    y0 = bar + 36
    rows = [(y0 + i * line_h, y0 + (i + 1) * line_h) for i in range(len(lines))]
    for i, (color, strike) in (marks or {}).items():
        r, g, b = hex_rgb(color)
        d.rectangle((0, rows[i][0], w, rows[i][1]), fill=(r, g, b, 46))
        d.rectangle((0, rows[i][0], 8, rows[i][1]), fill=(r, g, b, 255))
    try:
        lexer = get_lexer_by_name(language or 'text')
    except Exception:
        lexer = TextLexer()
    x, row = 56, 0
    for token_type, text in lex(code.rstrip('\n'), lexer):
        for k, part in enumerate(text.split('\n')):
            if k:
                row += 1
                x = 56
            if part:
                d.text((x, y0 + row * line_h + (line_h - size) // 2), part, font=f, fill=color_for(token_type))
                x += f.getlength(part)
    for i, (color, strike) in (marks or {}).items():
        if strike:
            y = (rows[i][0] + rows[i][1]) // 2
            d.line((56, y, 56 + f.getlength(lines[i]), y), fill=hex_rgb(color) + (230,), width=4)
    return (img, rows, f.getlength('M')) if with_char_w else (img, rows)


class Code(Card):
    """Lines appear one by one; the lines that carry the point get a soft highlight bar after."""
    STEP, START = 0.12, 0.3

    def __init__(self, visual, box, accent):
        box = widen(box)
        img, self.rows, self.char_w = code_image(visual['code'], visual.get('language'), visual.get('title', ''),
                                                 box[2], box[3], with_char_w=True)
        super().__init__(box[0], box[1] + (box[3] - img.height) // 2, img.width, img.height)
        self.img = np.asarray(img, dtype=np.float32)
        self.highlights = [i - 1 for i in visual.get('highlight', []) if 1 <= i <= len(self.rows)]
        self.sounds = [(self.START + self.STEP * i, 'tick') for i in range(len(self.rows))]
        self.accent = accent
        if self.highlights:
            i = self.highlights[0]
            line = visual['code'].rstrip('\n').split('\n')[i]
            indent = len(line) - len(line.lstrip())
            x0 = 56 + self.char_w * indent
            x1 = min(self.w - 40, 56 + self.char_w * len(line.rstrip()))
            self.circle = sketch_ellipse((x0, self.rows[i][0] + 4, x1, self.rows[i][1] - 4), seed=i + 7)
            done = self.START + self.STEP * len(self.rows) + 0.45
            self.sounds.append((done, 'scribble'))

    @property
    def settle(self):
        # Every line in place; the highlight and the hand-drawn circle still arrive after, as motion on frame 0.
        return max(self.TILT, self.START + self.STEP * len(self.rows))

    def layer(self, t):
        # The card is always full size (its shadow belongs to all of it); lines not typed yet are blank.
        mask = self.mask
        shown = int((t - self.START) / self.STEP) + 1
        rgb = self.img
        if shown < len(self.rows):
            rgb = rgb.copy()
            rgb[self.rows[max(shown, 0)][0]:self.rows[-1][1]] = BG
        done = self.START + self.STEP * len(self.rows) + 0.2
        p = render.ease_out(min(1.0, max(0.0, (t - done) / 0.4)))
        if p > 0 and self.highlights:
            rgb = rgb.copy()
            for i in self.highlights:
                y0, y1 = self.rows[i]
                rgb[y0:y1, 4:-4] += (255 - rgb[y0:y1, 4:-4]) * 0.08 * p
            # The first highlighted line gets circled by hand.
            stroke(rgb, self.circle, (t - done - 0.25) / 0.55, self.accent, 5)
        return rgb, mask


class Diff(Card):
    """Before, then the removed lines turn red and strike through, then the new code arrives with its added
    lines in green."""

    def __init__(self, visual, box, theme):
        import difflib
        box = widen(box)
        before, after = visual['before'].rstrip('\n').split('\n'), visual['after'].rstrip('\n').split('\n')
        removed, added = set(), set()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, before, after).get_opcodes():
            if op in ('replace', 'delete'):
                removed.update(range(i1, i2))
            if op in ('replace', 'insert'):
                added.update(range(j1, j2))
        title, lang = visual.get('title', ''), visual.get('language')
        plain, _ = code_image(visual['before'], lang, title, box[2], box[3])
        marked, _ = code_image(visual['before'], lang, title, box[2], box[3], {i: (RED, True) for i in removed})
        new, _ = code_image(visual['after'], lang, title, box[2], box[3], {i: (GREEN, False) for i in added})
        h = max(plain.height, new.height)

        def pad(im):
            # Shorter states are extended with editor background, so the window keeps one size.
            out = Image.new('RGB', (im.width, h), EDITOR['bg'])
            out.paste(im, (0, 0))
            return np.asarray(out, dtype=np.float32)
        self.states = [pad(plain), pad(marked), pad(new)]
        super().__init__(box[0], box[1] + (box[3] - h) // 2, plain.width, h)
        self.heights = [plain.height, marked.height, new.height]
        self.sounds = [(0.9, 'tick'), (1.9, 'swish')]

    def layer(self, t):
        # plain until 0.9s, red marks until ~45% of the slide, then the new code
        switch = max(1.8, self.duration * 0.45)
        if t < 0.9:
            k, mix, nxt = 0, 0.0, 1
        elif t < switch:
            k, mix, nxt = 0, min(1.0, (t - 0.9) / 0.25), 1
        else:
            k, mix, nxt = 1, min(1.0, (t - switch) / 0.3), 2
        rgb = self.states[k] * (1 - mix) + self.states[nxt] * mix
        return rgb, self.mask


class Terminal(Card):
    """Commands typed at a human pace (about 14 characters a second, uneven, longer pauses on spaces), each
    key with a click, and a blinking block cursor."""

    def __init__(self, visual, box, seed=3):
        cmds = visual.get('commands', [])[:6]
        if not cmds or max(len(c) for c in cmds) > MAX_CODE_COLS:
            raise ValueError(f'terminal needs 1 to 6 commands of max {MAX_CODE_COLS} characters')
        box = widen(box)
        size = 36
        self.f = mono(size)
        self.line_h = round(size * 1.7)
        img, bar = window(box[2], 64 + 36 + self.line_h * len(cmds) + 36, 'Terminal')
        super().__init__(box[0], box[1] + (box[3] - img.height) // 2, img.width, img.height)
        self.base = np.asarray(img, dtype=np.float32)
        self.y0, self.size, self.cmds = bar + 36, size, cmds
        self.prompt_w = self.f.getlength('$ ')
        full = img.copy()
        d = ImageDraw.Draw(full)
        for i, c in enumerate(cmds):
            y = self.y0 + i * self.line_h + (self.line_h - size) // 2
            d.text((40, y), '$', font=self.f, fill=EDITOR['prompt'])
            d.text((40 + self.prompt_w, y), c, font=self.f, fill=EDITOR['text'])
        self.full = np.asarray(full, dtype=np.float32)
        rng = np.random.default_rng(seed)
        # (line, chars typed) at each key time
        self.keys, t = [], 0.45
        for i, c in enumerate(cmds):
            for k in range(1, len(c) + 1):
                t += rng.uniform(0.045, 0.1) + (0.08 if c[k - 1] == ' ' else 0)
                self.keys.append((t, i, k))
                self.sounds.append((t, 'key'))
            t += 0.35
        self.char_w = self.f.getlength('M')

    def layer(self, t):
        rgb = self.base.copy()
        line, chars = -1, 0
        for kt, i, k in self.keys:
            if kt > t:
                break
            line, chars = i, k
        x_text = 40 + self.prompt_w
        for i in range(len(self.cmds)):
            y0 = self.y0 + i * self.line_h
            if i < line or (i == line and chars == len(self.cmds[i]) and i < len(self.cmds) - 1):
                rgb[y0:y0 + self.line_h] = self.full[y0:y0 + self.line_h]
            elif i == line or (i == 0 and line < 0) or i == line + 1:
                # prompt always shows on the current line; typed part up to the last key
                upto = round(x_text + (self.char_w * chars if i == line else 0))
                rgb[y0:y0 + self.line_h, :upto] = self.full[y0:y0 + self.line_h, :upto]
                if int(t * 2.2) % 2 == 0 or (i == line and chars < len(self.cmds[i])):
                    cx = upto + 2
                    cy = y0 + (self.line_h - self.size) // 2
                    rgb[cy:cy + self.size + 6, cx:cx + round(self.char_w * 0.9)] = np.array(hex_rgb(EDITOR['text']), np.float32)
                break
        return rgb, self.mask


# ---------- post card and chat ----------

def avatar(d, x, y, r, accent, initials='HJ'):
    # Initials, never a photo: no faces in the reels.
    d.ellipse((x, y, x + 2 * r, y + 2 * r), fill=accent)
    d.text((x + r, y + r), initials[:2], font=render.font('Bold', round(r * 0.8)), fill='#FFFFFF', anchor='mm')


class Post(Card):
    """A social post card in the creator's own name: avatar, name, handle and the text, lines landing one
    after another. No like or view counts: numbers on it would be invented."""

    def __init__(self, visual, box, theme, author=AUTHOR, handle=AUTHOR_HANDLE, platform='', url=''):
        box = widen(box)
        text = visual['text'].strip()
        dark = theme is render.THEMES['dark']
        bg, ink, dim = ('#16181C', '#E7E9EA', '#71767B') if dark else ('#FFFFFF', '#0F1419', '#536471')
        w, pad = box[2], 48
        size = 46
        while True:
            f = render.font('Regular', size)
            lines = []
            for para in text.split('\n'):
                words, cur = para.split(), ''
                for word in words:
                    trial = (cur + ' ' + word).strip()
                    if f.getlength(trial) > w - 2 * pad and cur:
                        lines.append(cur)
                        cur = word
                    else:
                        cur = trial
                lines.append(cur)
            line_h = round(size * 1.4)
            h = pad + 96 + 30 + line_h * len(lines) + pad
            if h <= box[3] or size <= 32:
                break
            size -= 2
        if h > box[3]:
            raise ValueError('post text is too long for the stage')
        img = Image.new('RGB', (w, h), bg)
        d = ImageDraw.Draw(img)
        initials = ''.join(p[0] for p in author.replace('@', '').split()[:2]).upper() or '?'
        colour = render.THEMES['dark' if dark else 'light']['accent'] if author == AUTHOR else '#5B6474'
        avatar(d, pad, pad, 48, colour, initials)
        d.text((pad + 116, pad + 22), author[:28], font=render.font('Bold', 36), fill=ink, anchor='lm')
        d.text((pad + 116, pad + 70), handle[:34], font=render.font('Regular', 30), fill=dim, anchor='lm')
        if platform:
            d.text((w - pad, pad + 22), platform, font=render.font('SemiBold', 28), fill=dim, anchor='rm')
        if url:
            host = url.split('//', 1)[-1].split('/', 1)[0].replace('www.', '')
            d.text((w - pad, h - 22), host, font=render.font('Regular', 24), fill=dim, anchor='rs')
        y0 = pad + 96 + 30
        self.rows = []
        for i, line in enumerate(lines):
            d.text((pad, y0 + i * line_h), line, font=f, fill=ink)
            self.rows.append((y0 + i * line_h, y0 + (i + 1) * line_h))
        super().__init__(box[0], box[1] + (box[3] - h) // 2, w, h, radius=32)
        self.img = np.asarray(img, dtype=np.float32)
        self.bg = np.array(hex_rgb(bg), dtype=np.float32)
        self.step = min(0.35, 1.8 / max(1, len(lines)))
        self.sounds = [(0.35 + self.step * i, 'tick') for i in range(len(lines))]

    def layer(self, t):
        shown = int((t - 0.35) / self.step) + 1
        if shown >= len(self.rows):
            return self.img, self.mask
        rgb = self.img.copy()
        rgb[self.rows[max(shown, 0)][0]:self.rows[-1][1]] = self.bg
        return rgb, self.mask


class Quote(Post):
    """A real public post by someone else, redrawn as a credited quote card: their name, handle and platform,
    the text word for word, and where it came from. Initials instead of profile photos."""

    def __init__(self, visual, box, theme):
        super().__init__({'text': '“' + visual['text'].strip() + '”'}, box, theme,
                         author=visual.get('author', ''), handle=visual.get('handle', ''),
                         platform=visual.get('platform', ''), url=visual.get('url', ''))


class Chat(Card):
    """A 'Client / Me' chat: incoming messages arrive after a typing indicator, replies pop in on the right."""
    TYPING = 0.8

    def __init__(self, visual, box, theme):
        box = widen(box)
        msgs = visual.get('messages', [])[:6]
        if len(msgs) < 2:
            raise ValueError('a chat needs at least 2 messages')
        dark = theme is render.THEMES['dark']
        self.bg = '#0B0D12' if dark else '#FFFFFF'
        self.them_bg, self.them_ink = ('#26282E', '#F2F3F5') if dark else ('#E9E9EB', '#101114')
        self.me_bg, self.me_ink = render.THEMES['dark' if dark else 'light']['accent'], '#FFFFFF'
        w = box[2]
        # Largest text size at which the whole conversation fits the stage.
        for size in range(40, 25, -2):
            head, line_h, pad_y, gap = round(size * 2.3), round(size * 1.3), round(size * 0.5), round(size * 0.45)
            f = render.font('Regular', size)
            max_text = w * 0.68
            self.bubbles, y = [], head + gap
            for m in msgs:
                me = m.get('from') == 'me'
                words, lines, cur = m['text'].split(), [], ''
                for word in words:
                    trial = (cur + ' ' + word).strip()
                    if f.getlength(trial) > max_text and cur:
                        lines.append(cur)
                        cur = word
                    else:
                        cur = trial
                lines.append(cur)
                bw = round(max(f.getlength(l) for l in lines) + 2 * pad_y + 20)
                bh = round(len(lines) * line_h + 2 * pad_y)
                self.bubbles.append((me, lines, bw, bh, y))
                y += bh + gap
            h = y + round(size * 1.8)
            if h <= box[3]:
                break
        else:
            raise ValueError('the chat is too long for the stage')
        self.size, self.line_h, self.pad_y, self.head = size, line_h, pad_y, head
        super().__init__(box[0], box[1] + (box[3] - h) // 2, w, h, radius=32)
        base = Image.new('RGB', (w, h), self.bg)
        d = ImageDraw.Draw(base)
        d.rectangle((0, 0, w, head), fill='#15171C' if dark else '#F6F6F8')
        r = round(head * 0.3)
        d.ellipse((32, head // 2 - r, 32 + 2 * r, head // 2 + r), fill='#8A8F98')
        d.text((32 + r, head // 2), 'C', font=render.font('Bold', round(r * 0.9)), fill='#FFFFFF', anchor='mm')
        d.text((52 + 2 * r, head // 2), visual.get('title', 'Client'), font=render.font('SemiBold', round(size * 0.9)),
               fill='#F2F3F5' if dark else '#101114', anchor='lm')
        # An illustrative scene, not a real conversation: say so on the card itself.
        d.rounded_rectangle((w - 150, head // 2 - 22, w - 28, head // 2 + 22), radius=22,
                            fill=self.me_bg)
        d.text((w - 89, head // 2), 'POV', font=render.font('Bold', 26), fill='#FFFFFF', anchor='mm')
        self.base = np.asarray(base, dtype=np.float32)
        self.f = f
        self.w, self.h = w, h
        self.imgs = [self.bubble(*b) for b in self.bubbles]
        self.schedule()

    def bubble(self, me, lines, bw, bh, y):
        img = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=min(30, bh // 2), fill=self.me_bg if me else self.them_bg)
        for i, line in enumerate(lines):
            d.text((self.pad_y + 10, self.pad_y + i * self.line_h), line, font=self.f,
                   fill=self.me_ink if me else self.them_ink)
        a = np.asarray(img, dtype=np.float32)
        return a[..., :3], a[..., 3] / 255.0

    def schedule(self):
        """When each message lands, spread over the slide; incoming ones show a typing indicator first."""
        n = len(self.bubbles)
        gap = min(1.7, max(0.9, (self.duration - 0.8) / n))
        self.times, t = [], 0.35
        for me, *_ in self.bubbles:
            t += 0 if me else self.TYPING * min(1.0, gap / 1.7)
            self.times.append(t)
            t += gap - (0 if me else self.TYPING * min(1.0, gap / 1.7))
        self.sounds = [(t, 'pop') for t in self.times]

    @property
    def duration(self):
        return self._duration

    @duration.setter
    def duration(self, value):
        self._duration = value
        if hasattr(self, 'bubbles'):
            self.schedule()

    def layer(self, t):
        rgb = self.base.copy()
        mask = self.mask
        for (me, lines, bw, bh, y), (brgb, bmask), at in zip(self.bubbles, self.imgs, self.times):
            x = self.w - 36 - bw if me else 36
            if t >= at:
                p = min(1.0, (t - at) / 0.25)
                s = 0.85 + 0.15 * render.back_out(p, 2.5)
                if s != 1:
                    im = Image.fromarray(np.dstack([brgb, bmask[..., None] * 255]).astype(np.uint8), 'RGBA')
                    im = im.resize((max(1, round(bw * s)), max(1, round(bh * s))), Image.BILINEAR)
                    a = np.asarray(im, dtype=np.float32)
                    sx = x + (bw - im.width) * (1 if me else 0)
                    sy = y + (bh - im.height)
                    cut = rgb[sy:sy + im.height, sx:sx + im.width]
                    m = a[..., 3:4] / 255.0 * min(1.0, p * 2)
                    cut += (a[..., :3] - cut) * m
                else:
                    cut = rgb[y:y + bh, x:x + bw]
                    cut += (brgb - cut) * bmask[..., None]
            elif not me and t >= at - self.TYPING * 0.9:
                # typing indicator: three dots bouncing in turn
                cut = rgb[y:y + 84, x:x + 150]
                dot = Image.new('RGBA', (150, 84), (0, 0, 0, 0))
                d = ImageDraw.Draw(dot)
                d.rounded_rectangle((0, 0, 149, 83), radius=30, fill=self.them_bg)
                for k in range(3):
                    lift = 8 * max(0.0, math.sin(t * 9 - k * 0.9))
                    d.ellipse((34 + k * 32, 34 - lift, 50 + k * 32, 50 - lift), fill='#9AA0A6')
                a = np.asarray(dot, dtype=np.float32)
                cut += (a[..., :3] - cut) * (a[..., 3:4] / 255.0)
                break
            else:
                break
        return rgb, mask


# ---------- recorded demos ----------

class Clip(Card):
    """A real screen recording (website walkthrough or live coding) playing inside the card. It may be sped up a
    little to fit the slide (at most MAX_SPEED, faster reads as hurried); if it is still too long, it jumps to its
    end, where the result is, like an editor's cut. Frames are streamed from ffmpeg in order, so memory stays
    small."""
    MAX_SPEED, LEAD = 1.5, 0.35

    def __init__(self, path, box, chrome=None):
        self.path = path
        w, h = box[2], box[3]
        super().__init__(box[0], box[1], w, h, radius=26)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                                str(path)], capture_output=True, text=True, check=True)
        self.length = float(probe.stdout.strip())
        self.proc, self.index, self.last = None, -1, None
        self.sounds = [(0.4, 'swish')]

    def open(self):
        avail = max(1.0, self.duration - self.LEAD - 0.3)
        speed = min(self.MAX_SPEED, max(1.0, self.length / avail))
        start = max(0.0, self.length - avail * speed)
        vf = f'setpts=(PTS-STARTPTS)/{speed:.4f},fps=30,scale={self.w}:{self.h}:force_original_aspect_ratio=increase,' \
             f'crop={self.w}:{self.h}'
        self.proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{start:.3f}', '-i', str(self.path), '-vf', vf,
                                      '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)

    def frame(self, t):
        if self.proc is None:
            self.open()
        want = max(0, int((t - self.LEAD) * 30))
        size = self.w * self.h * 3
        while self.index < want:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:
                break  # the clip ended: hold its last frame
            self.last = np.frombuffer(buf, dtype=np.uint8).reshape(self.h, self.w, 3).astype(np.float32)
            self.index += 1
        return self.last

    def layer(self, t):
        rgb = self.frame(t)
        if rgb is None:
            rgb = np.full((self.h, self.w, 3), 30.0, dtype=np.float32)
        return rgb, self.mask


def recorded(visual, box):
    import demos
    box = widen(box)
    size = (box[2], box[3] - box[3] % 2)
    return Clip(demos.record(visual, size), (box[0], box[1], size[0], size[1]))


# ---------- 3D scenes ----------

class Scene:
    """A three.js scene from scene3d.py floating straight on the reel background (no card; objects cast their own
    shadows). It is rendered once, then its frames are stretched or squeezed to fill the slide, so the diagram's
    packets finish their trip whatever the voice line's length. Rendering happens here, not at draw time, so a scene
    that fails falls back to text like any other visual."""
    LEAD, SECONDS = 0.25, 6.0

    def __init__(self, spec, theme, box):
        import scene3d
        x, y, w, h = box
        if spec.get('type') != 'device':
            # Wide scenes read bigger in a shorter box; centre it in the space it was given.
            h2 = min(h, round(w * 0.72))
            y, h = y + (h - h2) // 3, h2
        if spec.get('type') == 'logos' and set(spec.get('items', [])) & scene3d.ANIMAL_LOGOS:
            raise ValueError('an animal or mascot logo is not allowed')
        self.x, self.y, self.w, self.h = x, y, w, h
        self.frames = sorted(scene3d.render_scene(spec, theme, (self.w, self.h), self.SECONDS, transparent=True)
                             .glob('*.png'))
        if not self.frames:
            raise ValueError('3D scene rendered no frames')
        self.duration = 4.0
        self.sounds = [(0.35, 'swish')]
        self.index, self.cached = -1, None

    def draw(self, frame, t, alpha, dy):
        if alpha <= 0.003:
            return
        p = max(0.0, t - self.LEAD) / max(1.0, self.duration - self.LEAD - 0.3)
        i = min(len(self.frames) - 1, int(p * len(self.frames)))
        if i != self.index:
            a = np.asarray(Image.open(self.frames[i]).convert('RGBA'), dtype=np.float32)
            self.index, self.cached = i, (a[..., :3], a[..., 3] / 255.0)
        rgb, mask = self.cached
        render.blend(frame, rgb, mask, alpha, self.x, self.y + dy)


SCENES_3D = ('diagram', 'device', 'bars', 'logos', 'word')


# ---------- screenshot ----------

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
    if focus[2] - focus[0] < 20 or focus[3] - focus[1] < 10:
        path.unlink()
        raise RuntimeError(f'"{find}" is outside the captured page')
    meta.write_text(' '.join(f'{v:.1f}' for v in focus))
    return img, focus


def cursor_mask(size=46):
    """An arrow pointer: white fill with a dark outline, as (rgb, mask)."""
    ss = 4
    pts = [(0, 0), (0, 34), (9, 26), (15, 40), (21, 37), (15, 24), (27, 24)]
    img = Image.new('RGBA', (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    scaled = [(x * ss + 4 * ss, y * ss + 2 * ss) for x, y in pts]
    d.polygon(scaled, fill=(255, 255, 255, 255), outline=(20, 20, 24, 255), width=2 * ss)
    img = img.resize((size, size), Image.LANCZOS)
    a = np.asarray(img, dtype=np.float32)
    return a[..., :3], a[..., 3] / 255.0


class Screenshot(Card):
    """A browser frame showing the full page width, scrolling down to the outlined element while everything
    else dims (a spotlight); a cursor glides over and clicks it with a ripple. No zoom: zooming a web page
    always cuts text off at the edges."""
    SECONDS, DIM = 2.2, 0.3

    def __init__(self, shot, focus, url, box, accent):
        box = widen(box)
        w = box[2]
        bar = 72
        h = min(box[3], round(w * 1.4))
        super().__init__(box[0], box[1] + (box[3] - h) // 2, w, h, radius=26)
        self.bar = bar
        frame = Image.new('RGB', (w, h), '#E9EBF0')
        d = ImageDraw.Draw(frame)
        for i, c in enumerate(DOTS):
            d.ellipse((24 + i * 30, bar // 2 - 9, 42 + i * 30, bar // 2 + 9), fill=c)
        d.rounded_rectangle((140, 16, w - 30, bar - 16), radius=20, fill='#FFFFFF')
        host = url.split('//', 1)[-1].split('/', 1)[0]
        d.text((166, bar / 2), host, font=render.font('Regular', 26), fill='#5B6170', anchor='lm')
        self.chrome = np.asarray(frame, dtype=np.float32)
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
        self.target = (min((fx0 + fx1) / 2, w - 80), (fy0 + fy1) / 2 - self.end_top + bar)
        self.cursor = cursor_mask()
        self.arrive = 0.3 + self.SECONDS * 0.7 + 0.2
        self.sounds = [(0.35, 'swish'), (self.arrive + 0.45, 'click'), (self.arrive + 0.8, 'scribble')]
        top = self.end_top - bar
        self.loop = sketch_ellipse((max(fx0, 20), fy0 - top, min(fx1, w - 20), fy1 - top), seed=3)

    def layer(self, t):
        p = min(1.0, max(0.0, (t - 0.3) / self.SECONDS))
        p = 0.5 - 0.5 * math.cos(math.pi * p)
        view_h = self.h - self.bar
        top = round(self.start_top + (self.end_top - self.start_top) * p)
        page = self.page[top:top + view_h]
        lit, ring = self.lit[top:top + view_h], self.ring[top:top + view_h]
        s = min(1.0, max(0.0, (t - 0.3 - self.SECONDS * 0.7) / 0.5))
        shade = 1 - self.DIM * s * (1 - lit)
        view = page * shade
        view += (self.accent - view) * ring * s
        rgb = self.chrome.copy()
        rgb[self.bar:self.bar + len(view), :] = view
        stroke(rgb, self.loop, (t - self.arrive - 0.75) / 0.6, self.accent, 6)
        self.draw_cursor(rgb, t)
        return rgb, self.mask

    def draw_cursor(self, rgb, t):
        """The pointer glides in from the lower right, clicks the target, and a ripple spreads from it."""
        glide = min(1.0, max(0.0, (t - self.arrive + 0.1) / 0.55))
        if glide <= 0:
            return
        e = 0.5 - 0.5 * math.cos(math.pi * glide)
        sx, sy = self.w * 0.86, self.h * 0.92
        tx, ty = self.target
        x = sx + (tx - sx) * e + 18 * math.sin(math.pi * e) * (1 - e)
        y = sy + (ty - sy) * e
        click = t - (self.arrive + 0.45)
        if click >= 0:
            q = min(1.0, click / 0.6)
            r = 18 + 48 * render.ease_out(q)
            yy, xx = np.ogrid[:self.h, :self.w]
            ringm = np.clip(1 - np.abs(np.sqrt((xx - tx) ** 2 + (yy - ty) ** 2) - r) / 4, 0, 1)[..., None]
            rgb += (self.accent - rgb) * ringm * (1 - q) * 0.9
        press = 0.88 if 0 <= click < 0.12 else 1.0
        crgb, cmask = self.cursor
        if press != 1.0:
            im = Image.fromarray(np.dstack([crgb, cmask[..., None] * 255]).astype(np.uint8), 'RGBA')
            im = im.resize((round(im.width * press), round(im.height * press)), Image.BILINEAR)
            a = np.asarray(im, dtype=np.float32)
            crgb, cmask = a[..., :3], a[..., 3] / 255.0
        cx, cy = int(x) - 4, int(y) - 2
        h, w = cmask.shape
        x0, y0 = max(cx, 0), max(cy, 0)
        x1, y1 = min(cx + w, self.w), min(cy + h, self.h)
        if x0 < x1 and y0 < y1:
            m = cmask[y0 - cy:y1 - cy, x0 - cx:x1 - cx][..., None]
            region = rgb[y0:y1, x0:x1]
            region += (crgb[y0 - cy:y1 - cy, x0 - cx:x1 - cx] - region) * m


def build(visual, theme, box):
    kind = (visual or {}).get('type')
    try:
        if kind == 'code':
            return Code(visual, box, render.rgb(theme['accent']))
        if kind == 'diff':
            return Diff(visual, box, theme)
        if kind == 'terminal':
            return Terminal(visual, box)
        if kind == 'tweet':
            return Post(visual, box, theme)
        if kind == 'chat':
            return Chat(visual, box, theme)
        if kind == 'quote':
            return Quote(visual, box, theme)
        if kind in ('walkthrough', 'ide'):
            return recorded(visual, box)
        if kind in SCENES_3D:
            return Scene(visual, theme, widen(box))
        if kind == 'screenshot':
            if not visual.get('find'):
                raise ValueError('a screenshot needs the text to show ("find")')
            shot, focus = capture(visual['url'], visual['find'])
            return Screenshot(shot, focus, visual['url'], box, render.rgb(theme['accent']))
    except Exception as e:  # a visual is a bonus; the slide falls back to text rather than failing the post
        print(f'  visual skipped ({kind}: {type(e).__name__}: {str(e)[:120]})')
    return None
