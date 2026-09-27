"""Render a reel from reels.json into a 1080x1920 MP4.

Usage:
  python render.py <id>        render out/reel-<id>.mp4
  python render.py --fonts     download fonts only
"""

import json
import math
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / 'fonts'
OUT_DIR = ROOT / 'out'
QUEUE = ROOT / 'reels.json'

W, H, FPS = 1080, 1920, 30
SR = 44100
HANDLE = '@hassanjan.k'

# Instagram safe zone: UI covers the top strip, the bottom caption area and the right-hand buttons.
SAFE_TOP, SAFE_BOTTOM, MARGIN = 140, 1450, 90
CONTENT_TOP, CONTENT_BOTTOM = 300, 1430
POINT_BOTTOM = 1060
HOOK_WORD_H = 420
CAPTION_TOP, CAPTION_BOTTOM = 1330, 1470
TEXT_W = W - 2 * MARGIN

WORD_STEP = 0.11
WORD_ANIM = 0.38
EXIT = 0.3
VOICE_LEAD = 0.25
VOICE_TAIL = 1.2
LOOP = 0.4
MIN_SLIDE, MAX_SLIDE = 3.0, 6.0
MIN_TOTAL, MAX_TOTAL = 15.0, 25.0

THEMES = {
    'light': {'bg': '#F3EEE4', 'ink': '#141821', 'muted': '#5B6170', 'accent': '#E8472E'},
    'dark': {'bg': '#0C1120', 'ink': '#FFFFFF', 'muted': '#A6ADBD', 'accent': '#FF6A3D'},
}

FONT_URL = 'https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-{}.ttf'
WEIGHTS = ('Bold', 'SemiBold', 'Regular')


def ensure_fonts():
    FONT_DIR.mkdir(exist_ok=True)
    for weight in WEIGHTS:
        path = FONT_DIR / f'Poppins-{weight}.ttf'
        if path.exists() and path.stat().st_size > 10_000:
            continue
        print(f'Downloading Poppins-{weight}')
        urllib.request.urlretrieve(FONT_URL.format(weight), path)


_font_cache = {}


def font(weight, size):
    key = (weight, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONT_DIR / f'Poppins-{weight}.ttf'), size)
    return _font_cache[key]


def rgb(hex_color):
    h = hex_color.lstrip('#')
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


# ---------- text layout ----------

def parse_highlights(text):
    """'Stop *fighting* types' -> [('Stop', False), ('fighting', True), ('types', False)]"""
    words, chars, hl_word, hl = [], [], False, False
    for ch in text + ' ':
        if ch == '*':
            hl = not hl
        elif ch.isspace():
            if chars:
                words.append((''.join(chars), hl_word))
            chars, hl_word = [], False
        else:
            chars.append(ch)
            # Punctuation glued to a highlight ("*this*,") stays part of that word.
            hl_word = hl_word or (hl and ch.isalnum())
    return words


def text_mask(text, fnt, pad=6):
    ascent, descent = fnt.getmetrics()
    width = math.ceil(fnt.getlength(text)) + pad * 2
    img = Image.new('L', (width, ascent + descent + pad), 0)
    ImageDraw.Draw(img).text((pad, ascent), text, font=fnt, fill=255, anchor='ls')
    return np.asarray(img, dtype=np.float32) / 255.0, pad, ascent


def wrap(words, fnt, max_w):
    space = fnt.getlength(' ')
    lines, line, x = [], [], 0.0
    for word, hl in words:
        w = fnt.getlength(word)
        if line and x + space + w > max_w:
            lines.append(line)
            line, x = [], 0.0
        if line:
            x += space
        line.append((word, hl, x, w))
        x += w
    if line:
        lines.append(line)
    return lines


def fit(words, weight, max_size, min_size, max_w, max_h, leading=1.12, max_lines=None):
    """Largest font size where the text fits the box. Shrinks until it does."""
    size = max_size
    while True:
        fnt = font(weight, size)
        lines = wrap(words, fnt, max_w)
        line_h = round(size * leading)
        fits = len(lines) * line_h <= max_h and all(l[-1][2] + l[-1][3] <= max_w for l in lines)
        if max_lines:
            fits = fits and len(lines) <= max_lines
        if fits or size <= min_size:
            return fnt, size, lines, line_h
        size -= 2


# ---------- scene elements ----------

@dataclass
class El:
    mask: np.ndarray
    color: np.ndarray
    x: int
    y: int
    t0: float
    dur: float = WORD_ANIM
    rise: float = 26.0
    alpha: float = 1.0
    grow: bool = False
    slide: tuple = (0.0, 1e9)
    frames: list = None       # masks that replace `mask` over COUNT seconds (a number counting up)


COUNT = 1.1
NUMBER = re.compile(r'^([$]?)(\d{1,3}(?:,\d{3})+|\d+)(%|[KkMmBb]|\+)?([.,!?:;]?)$')


def count_frames(word, fnt, steps=22):
    """Masks for a number counting up from zero to its value, formatted like the original word."""
    m = NUMBER.match(word)
    if not m:
        return None
    prefix, digits, suffix, punct = m.group(1), m.group(2), m.group(3) or '', m.group(4)
    value = int(digits.replace(',', ''))
    if value < 10:
        return None
    comma = ',' in digits
    frames = []
    for k in range(steps + 1):
        v = round(value * ease_out(k / steps))
        text = f'{prefix}{v:,}{suffix}{punct}' if comma else f'{prefix}{v}{suffix}{punct}'
        frames.append(text_mask(text, fnt)[0])
    return frames


@dataclass
class Slide:
    kind: str
    start: float = 0.0
    end: float = 0.0
    elements: list = field(default_factory=list)
    clicks: list = field(default_factory=list)
    visual: object = None


def ease_out(p):
    return 1 - (1 - p) ** 3


def ease_in(p):
    return p ** 3


def back_out(p, overshoot=1.7):
    """Ease out that runs a little past the end and settles back (a pop instead of a stop)."""
    p -= 1
    return 1 + p * p * ((overshoot + 1) * p + overshoot)


def shadow_layers(mask, key=(2, 5, 0.32), ambient=(10, 26, 0.2)):
    """Two stacked shadows for a floating element: a tight key shadow and a soft ambient one.
    Each is (mask, x offset, y offset, alpha) relative to the element's top-left corner."""
    from PIL import ImageFilter
    out = []
    for dy, blur, alpha in (key, ambient):
        pad = blur * 2
        h, w = mask.shape
        img = Image.new('L', (w + 2 * pad, h + 2 * pad), 0)
        img.paste(Image.fromarray((mask * 255).astype(np.uint8)), (pad, pad))
        img = img.filter(ImageFilter.GaussianBlur(blur / 2))
        out.append((np.asarray(img, dtype=np.float32) / 255.0, -pad, dy - pad, alpha))
    return out


def marker_mask(w, thick, seed=0):
    """A slightly wobbly, bowed marker stroke w pixels long, as a mask."""
    rng = np.random.default_rng(seed)
    ss, h = 3, thick * 3
    tilt, bow = rng.uniform(-0.25, 0.25) * thick, rng.uniform(0.3, 0.6) * thick
    pts = [(ss * (thick / 2 + (w - thick) * i / 59),
            ss * (h / 2 + tilt * (i / 59 - 0.5) + bow * math.sin(math.pi * i / 59) - bow / 2 + 0.6 * math.sin(i * 0.8)))
           for i in range(60)]
    img = Image.new('L', (w * ss, h * ss), 0)
    ImageDraw.Draw(img).line(pts, fill=255, width=thick * ss, joint='curve')
    return np.asarray(img.resize((w, h), Image.LANCZOS), dtype=np.float32) / 255.0


def rounded_rect_mask(w, h, r, ss=4):
    img = Image.new('L', (w * ss, h * ss), 0)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=r * ss, fill=255)
    return np.asarray(img.resize((w, h), Image.LANCZOS), dtype=np.float32) / 255.0


def circle_number_mask(num, d=104, stroke=4, ss=4):
    img = Image.new('L', (d * ss, d * ss), 0)
    draw = ImageDraw.Draw(img)
    draw.ellipse((stroke * ss // 2, stroke * ss // 2, d * ss - stroke * ss // 2, d * ss - stroke * ss // 2),
                 outline=255, width=stroke * ss)
    draw.text((d * ss / 2, d * ss / 2 + 2 * ss), num, font=font('SemiBold', 36 * ss), fill=255, anchor='mm')
    return np.asarray(img.resize((d, d), Image.LANCZOS), dtype=np.float32) / 255.0


def add_words(slide, lines, fnt, size, line_h, top, t_start, theme, color_key='ink', step=WORD_STEP, anim=WORD_ANIM):
    """Word-by-word reveal, highlighted words in accent with a soft underline behind them."""
    ink, accent = rgb(theme[color_key]), rgb(theme['accent'])
    t = t_start
    underlines, words = [], []
    for li, line in enumerate(lines):
        baseline = top + li * line_h + round(size * 0.92)
        run = None
        for word, hl, x, w in line:
            mask, pad, ascent = text_mask(word, fnt)
            words.append(El(mask, accent if hl else ink, round(MARGIN + x - pad), baseline - ascent, t, dur=anim,
                            frames=count_frames(word, fnt)))
            slide.clicks.append(t)
            if hl:
                ul_end = x + fnt.getlength(word.rstrip(',.;:!?'))
                if run is None:
                    run = [x, ul_end, t]
                else:
                    run[1] = ul_end
            elif run:
                underlines.append((run, baseline))
                run = None
            t += step
        if run:
            underlines.append((run, baseline))
    for (x0, x1, t0), baseline in underlines:
        # A marker stroke drawn by hand under the highlighted words, revealed left to right.
        uh = max(10, round(size * 0.16))
        mask = marker_mask(round(x1 - x0) + 16, uh, seed=len(slide.elements))
        slide.elements.append(El(mask, accent, round(MARGIN + x0 - 8), baseline + round(uh * 0.1), t0 + 0.2,
                                 dur=0.5, rise=0, alpha=0.9, grow=True))
    slide.elements.extend(words)
    return t


def add_block(slide, text, weight, size, color, top, t0, theme, max_h=400, rise=30.0, dur=0.5):
    """A paragraph that fades in as one block."""
    fnt, size, lines, line_h = fit(parse_highlights(text), weight, size, 26, TEXT_W, max_h, leading=1.35)
    for li, line in enumerate(lines):
        txt = ' '.join(word for word, *_ in line)
        mask, pad, ascent = text_mask(txt, fnt)
        baseline = top + li * line_h + round(size * 0.95)
        slide.elements.append(El(mask, rgb(theme[color]), MARGIN - pad, baseline - ascent, t0, dur=dur, rise=rise))
    return len(lines) * line_h


def words_in(text):
    return len(text.replace('*', '').split())


def build_slides(reel, voice=None):
    theme = THEMES[reel['style']]
    slides = []
    # With spoken captions the bottom band belongs to them, text reveals fast and nothing waits on a blank frame.
    captions = bool(getattr(voice, 'words', None))
    bottom = CAPTION_TOP - 40 if captions else CONTENT_BOTTOM
    start, step, anim = (0.0, 0.03, 0.22) if captions else (0.3, WORD_STEP, WORD_ANIM)

    # Hook: with a voice it is already on its way in at frame 0, so the very first frame is never empty.
    s = Slide('hook')
    text_top = CONTENT_TOP
    if captions and reel.get('hook_word'):
        import visuals
        # The key word spins in above the hook in 3D; the hook text takes the space below it.
        s.visual = visuals.build({'type': 'word', 'text': reel['hook_word']}, theme,
                                 (MARGIN, CONTENT_TOP - 60, TEXT_W, HOOK_WORD_H))
        if s.visual:
            s.visual.spec = {'type': 'word', 'text': reel['hook_word']}
            text_top = CONTENT_TOP - 60 + HOOK_WORD_H
    fnt, size, lines, line_h = fit(parse_highlights(reel['hook']), 'Bold', 128, 60, TEXT_W, bottom - text_top, leading=1.08)
    block_h = len(lines) * line_h
    top = text_top + (bottom - text_top - block_h) // 2 - (0 if captions else 60)
    end = add_words(s, lines, fnt, size, line_h, top, -0.12 if captions else start, theme, step=step * 0.8, anim=anim)
    s.need = end + WORD_ANIM + 1.2 + 0.18 * words_in(reel['hook'])
    slides.append(s)

    # Points
    for i, point in enumerate(reel['points'], 1):
        s = Slide('point')
        num = f'{i:02d}'
        visual = point.get('visual') if captions else None
        if not captions:
            big, big_pad, big_asc = text_mask(num, font('Bold', 520))
            s.elements.append(El(big, rgb(theme['ink']), W - 50 - big.shape[1] + big_pad, SAFE_BOTTOM - 10 - big_asc,
                                 0.05, dur=0.7, rise=40, alpha=0.06))

        t_fnt, t_size, t_lines, t_lh = fit(parse_highlights(point['title']), 'Bold', 88 if not visual else 72, 44,
                                           TEXT_W, 400 if not visual else 200, leading=1.12)
        b_fnt, b_size, b_lines, b_lh = fit(parse_highlights(point['body']), 'Regular', 48, 30, TEXT_W, 330, leading=1.38)
        circle_d, gap1, gap2 = (104, 44, 40) if not visual else (84, 28, 36)
        title_h = circle_d + gap1 + len(t_lines) * t_lh
        group_h = title_h + (gap2 + len(b_lines) * b_lh if not visual else 0)
        if visual:
            top = CONTENT_TOP
        else:
            # Centre above the big number; long text may still reach into it, which stays readable at 6% opacity.
            top = CONTENT_TOP + max(0, ((POINT_BOTTOM if not captions else bottom) - CONTENT_TOP - group_h) // 2)

        s.elements.append(El(circle_number_mask(num, circle_d), rgb(theme['accent']), MARGIN, top, start + 0.02, dur=0.3))
        title_top = top + circle_d + gap1
        end = add_words(s, t_lines, t_fnt, t_size, t_lh, title_top, start + 0.05, theme, step=step, anim=anim)
        body_t = end + 0.2
        body_top = title_top + len(t_lines) * t_lh + gap2
        if visual:
            import visuals
            # A point may list several visuals, best first; the first one that can be made is used.
            for choice in (visual if isinstance(visual, list) else [visual]):
                s.visual = visuals.build(choice, theme, (MARGIN, body_top, TEXT_W, bottom - body_top))
                if s.visual:
                    s.visual.spec = choice
                    break
        if not s.visual:
            add_block(s, point['body'], 'Regular', b_size, 'muted', body_top, body_t, theme, max_h=330)
        s.need = body_t + 0.5 + 0.2 * words_in(point['body']) + 0.6
        slides.append(s)

    # CTA
    s = Slide('cta')
    q_fnt, q_size, q_lines, q_lh = fit(parse_highlights(reel['cta']), 'Bold', 92, 52, TEXT_W, 520, leading=1.1)
    cb_size, fl_size = 52, 38
    follow = f'Follow {HANDLE} for daily dev + AI tips'
    fl_lines = len(wrap(parse_highlights(follow), font('Regular', fl_size), TEXT_W))
    group_h = len(q_lines) * q_lh + 56 + round(cb_size * 1.3) + 22 + fl_lines * round(fl_size * 1.35)
    top = CONTENT_TOP + (bottom - CONTENT_TOP - group_h) // 2 - (0 if captions else 40)
    end = add_words(s, q_lines, q_fnt, q_size, q_lh, top, start, theme, step=step, anim=anim)
    y = top + len(q_lines) * q_lh + 56
    prompt = "I'll send it to your DMs" if reel.get('dm_keyword') else 'Comment below'
    y += add_block(s, prompt, 'SemiBold', cb_size, 'accent', y, end + 0.15, theme, max_h=120) + 22
    add_block(s, follow, 'Regular', fl_size, 'muted', y, end + 0.5, theme, max_h=160)
    s.need = end + 0.5 + 2.2
    slides.append(s)

    # Durations: scale with word count, clamp per slide, then keep the total in range.
    durs = [min(MAX_SLIDE, max(MIN_SLIDE, s.need + EXIT)) for s in slides]
    total = sum(durs)
    if total > MAX_TOTAL:
        extra = sum(d - MIN_SLIDE for d in durs)
        k = (total - MAX_TOTAL) / extra
        durs = [d - (d - MIN_SLIDE) * k for d in durs]
    elif total < MIN_TOTAL:
        room = sum(MAX_SLIDE - d for d in durs)
        k = (MIN_TOTAL - total) / room
        durs = [d + (MAX_SLIDE - d) * k for d in durs]
    if getattr(voice, 'continuous', False):
        # One continuous recording: each slide lasts exactly as long as its part of the speech, so the voice never stops.
        durs = [len(clip) / SR for clip in voice]
        durs[0] += VOICE_LEAD
        durs[-1] += VOICE_TAIL
    elif voice:
        # Speech sets the pace: each slide stays up until its line is finished.
        durs = [max(d, VOICE_LEAD + len(clip) / SR + 0.45 + EXIT) for d, clip in zip(durs, voice)]

    t = 0.0
    for s, d in zip(slides, durs):
        s.start, s.end = t, t + d
        if s.visual:
            s.visual.duration = d
        for el in s.elements:
            el.t0 += t
            el.slide = (s.start, s.end)
        s.clicks = [c + t for c in s.clicks]
        t += d
    return slides, theme


# ---------- frame rendering ----------

def make_background(theme, seed=7):
    bg = rgb(theme['bg'])
    accent = rgb(theme['accent'])
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dark = theme is THEMES['dark']
    glow_color = accent if not dark else accent * 0.55 + rgb('#3B5BDB') * 0.45
    g1 = np.exp(-(((xx - W * 0.82) ** 2 + (yy - H * 0.2) ** 2) / (2 * 520.0 ** 2)))
    g2 = np.exp(-(((xx - W * 0.1) ** 2 + (yy - H * 0.9) ** 2) / (2 * 600.0 ** 2)))
    strength = (0.10 if not dark else 0.20) * g1 + (0.05 if not dark else 0.10) * g2
    frame = bg[None, None, :] * (1 - strength[..., None]) + glow_color[None, None, :] * strength[..., None]
    # Static triangular dither so the gradient does not band after 8-bit quantisation.
    rng = np.random.default_rng(seed)
    frame += (rng.random((H, W, 1), dtype=np.float32) - rng.random((H, W, 1), dtype=np.float32))
    return frame


def composite(frame, el, a, x, y, mask=None):
    mask = el.mask if mask is None else mask
    h, w = mask.shape
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x][..., None] * a
    region = frame[y0:y1, x0:x1]
    region += (el.color - region) * m


def draw_element(frame, el, t):
    if t < max(el.t0, el.slide[0]) or t >= el.slide[1]:
        return
    lin = min(1.0, (t - el.t0) / el.dur)
    p = ease_out(lin)
    a = el.alpha * (p if not el.grow else 1.0)
    dy = (1 - back_out(lin)) * el.rise
    q = min(1.0, max(0.0, (t - (el.slide[1] - EXIT)) / EXIT))
    if q > 0:
        e = ease_in(q)
        a *= 1 - e
        dy -= e * 70
    if a <= 0.003:
        return
    mask = el.mask
    if el.frames:
        k = min(len(el.frames) - 1, int(max(0.0, t - el.t0) / COUNT * (len(el.frames) - 1)))
        mask = el.frames[k]
    if el.grow:
        cols = max(1, round(mask.shape[1] * p))
        mask = mask[:, :cols]
    composite(frame, el, a, el.x, round(el.y + dy), mask)


def border_mask(mask, width=2):
    """The rim of a rounded shape, for a thin light edge."""
    from PIL import ImageFilter
    img = Image.fromarray((mask * 255).astype(np.uint8))
    inner = img.filter(ImageFilter.MinFilter(width * 2 + 1))
    return np.clip(mask - np.asarray(inner, dtype=np.float32) / 255.0, 0, 1)


def glow_mask(mask, blur):
    """A soft bloom around a shape: (mask, x offset, y offset)."""
    from PIL import ImageFilter
    pad = blur * 2
    h, w = mask.shape
    img = Image.new('L', (w + 2 * pad, h + 2 * pad), 0)
    img.paste(Image.fromarray((mask * 255).astype(np.uint8)), (pad, pad))
    img = img.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(img, dtype=np.float32) / 255.0, -pad, -pad


def frost(frame, mask, x, y, a, blur=14):
    """Frosted glass: blur what is behind a shape before it is tinted."""
    from PIL import ImageFilter
    h, w = mask.shape
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1 or a <= 0:
        return
    region = frame[y0:y1, x0:x1]
    img = Image.fromarray(np.clip(region, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur))
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x][..., None] * a
    region += (np.asarray(img, dtype=np.float32) - region) * m


def blend(frame, img, mask, a, x, y):
    """Composite an RGB image with its own alpha mask."""
    h, w = mask.shape
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x][..., None] * a
    region = frame[y0:y1, x0:x1]
    region += (img[y0 - y:y1 - y, x0 - x:x1 - x] - region) * m


class Captions:
    """Spoken words shown 2 or 3 at a time on a dark pill near the bottom, the word being said on an accent
    highlight."""
    SIZE, MAX_WORDS, GAP, PAD_X, PAD_Y = 66, 3, 0.35, 34, 18
    TEXT, BOX, BOX_ALPHA = rgb('#FFFFFF'), rgb('#101421'), 0.62

    def __init__(self, voice, slides, theme):
        self.accent = rgb(theme['accent'])
        self.cache = {}
        words, at = [], VOICE_LEAD
        for i, (s, ws) in enumerate(zip(slides, voice.words)):
            off = at if voice.continuous else s.start + VOICE_LEAD
            words += [(w, a + off, b + off) for w, a, b in ws]
            at += len(voice[i]) / SR
        chunks, cur = [], []
        for w in words:
            if cur and (len(cur) == self.MAX_WORDS or cur[-1][0][-1] in '.,?!;:' or w[1] - cur[-1][2] > self.GAP):
                chunks.append(cur)
                cur = []
            cur.append(w)
        if cur:
            chunks.append(cur)
        self.chunks = []
        bounds = [sl.end for sl in slides]
        for k, chunk in enumerate(chunks):
            start = chunk[0][1]
            end = chunks[k + 1][0][1] if k + 1 < len(chunks) else chunk[-1][2] + 0.5
            # Never carry a line's caption across the beat into the next slide.
            end = min(end, chunk[-1][2] + 0.6, next((b for b in bounds if b > start + 0.05), end))
            self.chunks.append((start, end, *self.layout(chunk)))

    def layout(self, chunk):
        shown = [w.rstrip('.,;:') for w, *_ in chunk]
        size = self.SIZE
        while True:
            fnt = font('Bold', size)
            space = fnt.getlength(' ')
            width = sum(fnt.getlength(w) for w in shown) + space * (len(shown) - 1)
            if width <= TEXT_W - 2 * self.PAD_X or size <= 40:
                break
            size -= 4
        ascent, descent = fnt.getmetrics()
        box_h = ascent + descent + 2 * self.PAD_Y
        # The box grows as words are spoken; one box per number of words shown, left edge fixed.
        x0 = (W - width) / 2
        boxes = []
        for k in range(1, len(shown) + 1):
            part = sum(fnt.getlength(w) for w in shown[:k]) + space * (k - 1)
            m = rounded_rect_mask(round(part + 2 * self.PAD_X), box_h, 22)
            boxes.append((m, round(x0 - self.PAD_X), CAPTION_BOTTOM - box_h, shadow_layers(m), border_mask(m)))
        box = boxes
        x, baseline = x0, CAPTION_BOTTOM - self.PAD_Y - descent
        placed = []
        for (w, a, b), text in zip(chunk, shown):
            mask, pad, asc = text_mask(text, fnt)
            tw = round(fnt.getlength(text))
            hl_mask = rounded_rect_mask(tw + 20, ascent + descent + 4, 12)
            hl = (hl_mask, round(x) - 10, baseline - ascent - 2, glow_mask(hl_mask, 16))
            placed.append((mask, round(x - pad), baseline - asc, a, b, hl))
            x += fnt.getlength(text) + space
        return box, placed

    POP = 0.16

    def scaled(self, key, mask, scale):
        """A mask resized for the pop, cached per (chunk, word, layer) key and scale step."""
        key = (*key, round(scale, 2))
        if key not in self.cache:
            h, w = mask.shape
            img = Image.fromarray((mask * 255).astype(np.uint8)).resize(
                (max(1, round(w * key[-1])), max(1, round(h * key[-1]))), Image.BILINEAR)
            self.cache[key] = np.asarray(img, dtype=np.float32) / 255.0
        return self.cache[key]

    def pop(self, frame, key, mask, color, x, y, t0, t, alpha):
        """Draw a mask scaled 80% -> ~105% -> 100% over POP seconds from t0, centred on its place."""
        p = min(1.0, max(0.0, (t - t0) / self.POP))
        scale = 0.8 + 0.2 * back_out(p, 3.5)
        m = mask if p >= 1 else self.scaled(key, mask, scale)
        h, w = mask.shape
        composite(frame, El(m, color, 0, 0, 0), alpha * min(1.0, 0.4 + p),
                  round(x + (w - m.shape[1]) / 2), round(y + (h - m.shape[0]) / 2))

    def draw(self, frame, t):
        for c, (start, end, boxes, placed) in enumerate(self.chunks):
            if start <= t < end:
                p = ease_out(min(1.0, (t - start) / 0.12))
                dy = round((1 - back_out(min(1.0, (t - start) / 0.2))) * 14)
                box_mask, bx, by, shadows, border = boxes[max(0, sum(1 for w in placed if w[3] <= t) - 1)]
                for m, ox, oy, a in shadows:
                    composite(frame, El(m, rgb('#000000'), 0, 0, 0), a * p, bx + ox, by + dy + oy)
                frost(frame, box_mask, bx, by + dy, p)
                composite(frame, El(box_mask, self.BOX, 0, 0, 0), self.BOX_ALPHA * p, bx, by + dy)
                composite(frame, El(border, self.TEXT, 0, 0, 0), 0.22 * p, bx, by + dy)
                for i, (mask, x, y, a, b, (hl_mask, hx, hy, glow)) in enumerate(placed):
                    if t < a:
                        break  # words appear as they are spoken
                    nxt = placed[i + 1][3] if i + 1 < len(placed) else end
                    if t < nxt:
                        g, gx, gy = glow
                        pulse = 0.35 + 0.15 * math.sin((t - a) * 9)
                        composite(frame, El(g, self.accent, 0, 0, 0), pulse * p, hx + gx, hy + dy + gy)
                        self.pop(frame, (c, i, 'hl'), hl_mask, self.accent, hx, hy + dy, a, t, p)
                    self.pop(frame, (c, i, 'word'), mask, self.TEXT, x, y + dy, a, t, p)
                return


def speech_beats(slides, voice):
    """When each spoken sentence starts, in reel time: the camera punches on these instead of on a timer, so the
    picture moves with what is being said. Empty without word timings."""
    if not getattr(voice, 'words', None):
        return []
    beats, at, prev = [], VOICE_LEAD, None
    for i, (s, ws) in enumerate(zip(slides, voice.words)):
        off = at if voice.continuous else s.start + VOICE_LEAD
        for w, a, b in ws:
            if prev is None or prev[0][-1:] in '.!?' or a + off - prev[2] > 0.35:
                beats.append(a + off)
            prev = (w, a + off, b + off)
        at += len(voice[i]) / SR
    return beats


class Camera:
    """Moves the slide content like a filmed shot so nothing is ever frozen: a slow breathing zoom and drift,
    a zoom punch at every slide change and on every spoken sentence (or every PUNCH_EVERY seconds without a
    voice; varied strength, so the rhythm never feels mechanical), a focus push into each point's visual (show,
    focus, release: something changes every one to two seconds), a short shake on the hook and the call to
    action, and a zoom-out reveal at frame 0.
    Chrome (progress bars, kicker) and captions are drawn after the camera, so they stay put like real UI."""
    BASE = 1.018              # slight overscan so drift and shake never show an edge
    PUNCH_EVERY = 2.6
    PUNCH_UP, PUNCH_DOWN = 0.07, 0.24

    FOCUS = 0.1               # extra zoom while pushed into a visual

    def __init__(self, slides, seed=11, beats=()):
        rng = np.random.default_rng(seed)
        self.punches = []
        for i, s in enumerate(slides):
            if i:
                self.punches.append((s.start, 0.06 + rng.uniform(0, 0.025)))
            mine = [b for b in beats if s.start + 0.8 < b < s.end - 0.8]
            if not beats:
                t = s.start + self.PUNCH_EVERY
                while t < s.end - 0.8:
                    mine.append(t)
                    t += self.PUNCH_EVERY * rng.uniform(0.8, 1.0)
            last = s.start
            for t in mine:
                if t - last >= 1.2:  # sentence starts closer than this would make it jitter
                    self.punches.append((t, 0.025 + rng.uniform(0, 0.02)))
                    last = t
        # Push into each point's visual partway through, hold, and ease back before the slide ends.
        self.focuses = []
        for s in slides:
            v = s.visual
            if s.kind == 'point' and v is not None and s.end - s.start >= 3.0:
                d = s.end - s.start
                # Never so far that a wide visual (a full-width code card) runs off the frame.
                zoom = min(self.FOCUS, (W - 24) / v.w - self.BASE - 0.012)
                if zoom > 0.01:
                    self.focuses.append((s.start + 0.4 * d, s.end - 0.8, v.x + v.w / 2, v.y + v.h / 2, zoom))
        # Shake when the hook has landed and when the call to action appears.
        self.shakes = [(0.45, 7.0), (slides[-1].start + 0.1, 6.0)]
        self.jitter = rng.uniform(-1, 1, (4096, 2))

    def punch(self, t):
        amount = 0.0
        for at, strength in self.punches:
            d = t - at
            if 0 <= d < self.PUNCH_UP:
                amount += strength * back_out(d / self.PUNCH_UP, 1.2)
            elif self.PUNCH_UP <= d < self.PUNCH_UP + self.PUNCH_DOWN:
                amount += strength * (1 - ease_out((d - self.PUNCH_UP) / self.PUNCH_DOWN))
        return amount

    def focus(self, t):
        """(zoom, focus x, focus y) of a push into a visual at time t."""
        for start, end, fx, fy, zoom in self.focuses:
            if start <= t < end + 0.5:
                k = ease_out(min(1.0, (t - start) / 0.6)) * (1 - ease_in(min(1.0, max(0.0, (t - end) / 0.5))))
                return zoom * k, fx, fy
        return 0.0, W / 2, H / 2

    def params(self, t):
        breathe = 0.009 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 3.1))
        reveal = 0.1 * (1 - ease_out(min(1.0, t / 0.6)))
        push, fx, fy = self.focus(t)
        scale = self.BASE + breathe + reveal + self.punch(t) + push
        # Zoom about the visual, drifting it a little toward the centre, instead of about the frame centre.
        k = 1.0 if push else 0.0
        dx = 2.2 * math.sin(2 * math.pi * t / 5.3) + (fx - W / 2) * (1 - scale) * k + (W / 2 - fx) * 0.25 * k
        dy = 1.8 * math.sin(2 * math.pi * t / 6.7 + 1.0) + (fy - H / 2) * (1 - scale) * k + (H / 2 - fy) * 0.25 * k
        for at, amp in self.shakes:
            d = t - at
            if 0 <= d < 0.16:
                k = int(t * FPS * 3) % len(self.jitter)
                fade = 1 - d / 0.16
                dx += amp * fade * self.jitter[k, 0]
                dy += amp * fade * self.jitter[k, 1]
        return scale, dx, dy

    def fast(self, t):
        """True while the camera moves fast enough to deserve motion blur."""
        a, b = self.params(t - 1 / (2 * FPS)), self.params(t + 1 / (2 * FPS))
        return abs(a[0] - b[0]) > 0.004 or abs(a[1] - b[1]) + abs(a[2] - b[2]) > 3

    @staticmethod
    def apply(img, scale, dx, dy):
        cx, cy = W / 2, H / 2
        return img.transform((W, H), Image.AFFINE,
                             (1 / scale, 0, cx - (cx + dx) / scale, 0, 1 / scale, cy - (cy + dy) / scale),
                             resample=Image.BILINEAR)

    def shoot(self, frame, t):
        """The content frame as the camera sees it, with motion blur (3 sub-frames) during fast moves."""
        img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8))
        if not self.fast(t):
            return np.asarray(self.apply(img, *self.params(t)), dtype=np.float32)
        samples = [np.asarray(self.apply(img, *self.params(t + k / (3 * FPS))), dtype=np.float32) for k in (-1, 0, 1)]
        return sum(samples) / 3


def finishing(theme, seed=5, frames=12):
    """A soft vignette and a cycle of film-grain frames, precomputed once."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
    strength = 0.16 if theme is THEMES['light'] else 0.24
    vignette = (1 - strength * np.clip((r - 0.45) / 0.55, 0, 1) ** 1.6)[..., None]
    rng = np.random.default_rng(seed)
    # Grain at half resolution: it reads as film texture, and the encoder does not spend the bitrate on it.
    grain = [np.repeat(np.repeat(rng.normal(0, 2.0, (H // 2, W // 2, 1)), 2, 0), 2, 1).astype(np.float32)
             for _ in range(frames)]
    return vignette, grain


def build_chrome(reel, theme, n_slides):
    """Progress bar geometry plus the static kicker and handle."""
    gap, bar_h, bar_y = 10, 6, 150
    seg_w = (TEXT_W - gap * (n_slides - 1)) // n_slides
    bars = [(MARGIN + i * (seg_w + gap), bar_y, seg_w, bar_h) for i in range(n_slides)]
    bar_mask = rounded_rect_mask(seg_w, bar_h, bar_h // 2)

    kicker_y = 196
    k_fnt = font('SemiBold', 34)
    accent_bar = rounded_rect_mask(34, 6, 3)
    k_mask, k_pad, k_asc = text_mask(reel['kicker'].upper(), k_fnt)
    h_fnt = font('Regular', 32)
    h_mask, h_pad, h_asc = text_mask(HANDLE, h_fnt)
    baseline = kicker_y + 34
    # Already on screen at frame 0: the first frame is what the feed shows before anyone taps.
    statics = [
        El(accent_bar, rgb(theme['accent']), MARGIN, baseline - 16, -1, dur=0.3, rise=0, slide=(-1, 1e9)),
        El(k_mask, rgb(theme['accent']), MARGIN + 50 - k_pad, baseline - k_asc, -1, dur=0.3, rise=0, slide=(-1, 1e9)),
        El(h_mask, rgb(theme['muted']), W - MARGIN - h_mask.shape[1] + h_pad, baseline - h_asc, -1, dur=0.3, rise=0,
           slide=(-1, 1e9)),
    ]
    return bars, bar_mask, statics


def render_frames(reel, slides, theme, pipe, captions=None, voice=None):
    bg = make_background(theme)
    bars, bar_mask, statics = build_chrome(reel, theme, len(slides))
    ink = rgb(theme['ink'])
    total = slides[-1].end
    n = round(total * FPS)
    track = El(bar_mask, ink, 0, 0, 0)
    camera = Camera(slides, beats=speech_beats(slides, voice))
    vignette, grain = finishing(theme)
    for f in range(n):
        t = f / FPS
        frame = bg.copy()
        for s in slides:
            if s.start <= t < s.end:
                if s.visual:
                    lin = min(1.0, max(0.0, (t - s.start - 0.05) / 0.35))
                    p = ease_out(lin)
                    q = ease_in(min(1.0, max(0.0, (t - (s.end - EXIT)) / EXIT)))
                    s.visual.draw(frame, t - s.start, p * (1 - q), round((1 - back_out(lin)) * 40 - q * 70))
                for el in s.elements:
                    draw_element(frame, el, t)
        frame = camera.shoot(frame, t) * vignette
        for i, (x, y, w, h) in enumerate(bars):
            s = slides[i]
            composite(frame, track, 0.16, x, y)
            p = min(1.0, max(0.0, (t - s.start) / (s.end - s.start)))
            cols = round(w * p)
            if cols:
                composite(frame, track, 0.85, x, y, bar_mask[:, :cols])
        for el in statics:
            draw_element(frame, el, t)
        if captions:
            captions.draw(frame, t)
        # Loop ending: the last moment eases into the opening frame, so a replay continues seamlessly.
        if f == 0:
            first = frame.copy()
        elif t > total - LOOP:
            w = ease_in(min(1.0, (t - (total - LOOP)) / LOOP))
            frame = frame * (1 - w) + first * w
        frame += grain[f % len(grain)]
        pipe.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())


# ---------- audio ----------

def click_sound(rng):
    n = int(SR * 0.035)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    # Differenced noise is brighter, like a key switch; the short sine adds body.
    tick = np.diff(noise, prepend=0) * np.exp(-t * 260)
    body = np.sin(2 * np.pi * rng.uniform(1700, 2300) * t) * np.exp(-t * 180) * 0.35
    thump = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 90) * 0.5
    s = tick * 0.5 + body + thump
    return s / np.sqrt(np.mean(s ** 2))


def whoosh_sound(rng, length=0.55):
    n = int(SR * length)
    noise = rng.standard_normal(n)
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 2
    # One-pole lowpass whose cutoff sweeps up then down gives the air movement.
    cutoff = 300 + 3200 * np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5
    alpha = 1 - np.exp(-2 * np.pi * cutoff / SR)
    out = np.empty(n)
    y = 0.0
    for i in range(n):
        y += alpha[i] * (noise[i] - y)
        out[i] = y
    s = out * env
    return s / np.sqrt(np.mean(s ** 2))


def noise_hit(rng, length, bright, decay):
    """A short burst of shaped noise: no pitch, so it reads as a sound effect and never as music."""
    n = int(SR * length)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    for _ in range(bright):
        noise = np.diff(noise, prepend=0)
    s = noise * np.exp(-t * decay)
    return s / (np.sqrt(np.mean(s ** 2)) or 1.0)


def sound_kit(rng):
    """Every sound effect by name, all noise based. Levels are set where they are placed."""
    return {
        'key': lambda: noise_hit(rng, 0.018, 2, 420),
        'tick': lambda: noise_hit(rng, 0.025, 1, 260),
        'pop': lambda: noise_hit(rng, 0.05, 0, 90) * 0.7 + noise_hit(rng, 0.05, 2, 200) * 0.3,
        'click': lambda: np.concatenate([noise_hit(rng, 0.012, 2, 500), np.zeros(int(SR * 0.03)),
                                         noise_hit(rng, 0.012, 1, 500)]),
        'swish': lambda: whoosh_sound(rng, 0.32),
        'air': lambda: whoosh_sound(rng, 0.2),
        'thud': lambda: lowpass(noise_hit(rng, 0.14, 0, 30), 0.02),
        'scribble': lambda: scribble_sound(rng),
    }


SOUND_GAIN = {'key': 0.035, 'tick': 0.03, 'pop': 0.06, 'click': 0.07, 'swish': 0.05, 'air': 0.022, 'thud': 0.11,
              'scribble': 0.03}


def lowpass(x, alpha):
    """One-pole low-pass filter; small alpha keeps only the low rumble."""
    out, y = np.empty_like(x), 0.0
    for i, v in enumerate(x):
        y += alpha * (v - y)
        out[i] = y
    return out / (np.sqrt(np.mean(out ** 2)) or 1.0)


def scribble_sound(rng, length=0.5):
    """A marker on paper: bright noise in quick uneven strokes."""
    n = int(SR * length)
    t = np.arange(n) / SR
    noise = np.diff(rng.standard_normal(n), prepend=0)
    strokes = np.clip(np.sin(2 * np.pi * (7 + 3 * np.sin(t * 5)) * t), 0, 1) ** 0.6
    env = np.sin(np.pi * t / length) ** 0.5
    s = noise * strokes * env
    return s / (np.sqrt(np.mean(s ** 2)) or 1.0)


def build_audio(slides, path, voice=None):
    total = slides[-1].end
    track = np.zeros(int(SR * (total + 0.5)))
    rng = np.random.default_rng(42)

    def place(sound, at, gain):
        # The hook starts slightly before frame 0; drop the part of a sound that falls before the start.
        i = int(at * SR)
        if i < 0:
            sound, i = sound[-i:], 0
        j = min(len(track), i + len(sound))
        if i < j:
            track[i:j] += sound[:j - i] * gain

    # With a voice the fast text reveal would turn clicks into a rattle; keep only the transitions.
    click_gain, whoosh_gain = (0.0, 0.08) if voice else (0.09, 0.16)
    for s in slides:
        for c in s.clicks:
            place(click_sound(rng), c, click_gain)
    for s in slides[1:]:
        place(whoosh_sound(rng), s.start - 0.3, whoosh_gain)
    kit = sound_kit(rng)
    # The camera's own moves: a breath of air on mid-slide punches (slide changes already whoosh), a thud on shakes.
    camera = Camera(slides, beats=speech_beats(slides, voice))
    starts = {round(s.start, 3) for s in slides}
    for at, _ in camera.punches:
        if round(at, 3) not in starts:
            place(kit['air'](), at - 0.05, SOUND_GAIN['air'])
    for at, _ in camera.shakes:
        place(kit['thud'](), at, SOUND_GAIN['thud'])
    for s in slides:
        for at, kind in getattr(s.visual, 'sounds', []):
            if s.start + at < s.end - EXIT:
                place(kit[kind](), s.start + at, SOUND_GAIN[kind])
    if getattr(voice, 'continuous', False):
        peak = max(np.max(np.abs(clip)) for clip in voice) or 1.0
        at = VOICE_LEAD
        for clip in voice:
            place(clip / peak, at, 0.9)
            at += len(clip) / SR
    elif voice:
        for s, clip in zip(slides, voice):
            place(clip / (np.max(np.abs(clip)) or 1.0), s.start + VOICE_LEAD, 0.9)

    peak = np.max(np.abs(track)) or 1.0
    track = track / peak * 0.7  # -3 dBFS peak
    track = track[:int(SR * total)]
    pcm = (track * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------- entry points ----------

def make_cover(reel, path):
    """The grid cover: kicker, the hook large with its highlight and a marker stroke, and the handle, all inside
    the centre 1080x1080 square so the profile grid's crop never cuts them."""
    theme = THEMES[reel['style']]
    img = Image.fromarray(np.clip(make_background(theme), 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    top, side = (H - W) // 2 + 60, W - 2 * MARGIN
    kick = font('SemiBold', 40)
    d.rounded_rectangle((MARGIN, top + 18, MARGIN + 40, top + 26), radius=4, fill=theme['accent'])
    d.text((MARGIN + 58, top + 22), reel['kicker'].upper(), font=kick, fill=theme['accent'], anchor='lm')
    fnt, size, lines, line_h = fit(parse_highlights(reel['hook']), 'Bold', 118, 60, side, 700, leading=1.08)
    y = top + 90 + (700 - len(lines) * line_h) // 2
    for li, line in enumerate(lines):
        baseline = y + li * line_h + round(size * 0.92)
        for word, hl, x, wdt in line:
            if hl:
                stroke_w = round(fnt.getlength(word.rstrip(',.;:!?')))
                m = marker_mask(stroke_w + 16, max(10, round(size * 0.16)), seed=li)
                layer = Image.fromarray((m * 230).astype(np.uint8))
                img.paste(theme['accent'], (MARGIN + round(x) - 8, baseline + 2), layer)
            d.text((MARGIN + x, baseline), word, font=fnt, fill=theme['accent'] if hl else theme['ink'], anchor='ls')
    d.text((MARGIN, top + W - 150), HANDLE, font=font('Regular', 38), fill=theme['muted'], anchor='lm')
    img.save(path, 'JPEG', quality=92)
    return path


def load_reel(reel_id):
    reels = json.loads(QUEUE.read_text())
    for r in reels:
        if str(r['id']) == str(reel_id):
            return r
    raise SystemExit(f'No reel with id {reel_id} in reels.json')


def render_reel(reel, out_path=None, voice=None):
    ensure_fonts()
    OUT_DIR.mkdir(exist_ok=True)
    out_path = Path(out_path or OUT_DIR / f"reel-{reel['id']}.mp4")
    slides, theme = build_slides(reel, voice)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'sfx.wav'
        build_audio(slides, wav, voice)
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
            '-i', str(wav),
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '21', '-pix_fmt', 'yuv420p',
            '-profile:v', 'high', '-level', '4.1', '-maxrate', '5M', '-bufsize', '10M',
            '-g', str(FPS * 2),
            '-c:a', 'aac', '-b:a', '128k', '-ar', str(SR),
            '-shortest', '-movflags', '+faststart', str(out_path),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            captions = Captions(voice, slides, theme) if getattr(voice, 'words', None) else None
            render_frames(reel, slides, theme, proc.stdin, captions, voice)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit('ffmpeg failed')
    make_cover(reel, out_path.with_name(out_path.stem + '-cover.jpg'))
    print(f'Rendered {out_path} ({slides[-1].end:.1f}s, {out_path.stat().st_size / 1e6:.1f} MB) and its cover')
    return out_path, slides


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == '--fonts':
        ensure_fonts()
        return
    render_reel(load_reel(sys.argv[1]))


if __name__ == '__main__':
    main()
