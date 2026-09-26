"""Render a reel from reels.json into a 1080x1920 MP4.

Usage:
  python render.py <id>        render out/reel-<id>.mp4
  python render.py --fonts     download fonts only
"""

import json
import math
import os
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
TEXT_W = W - 2 * MARGIN

WORD_STEP = 0.11
WORD_ANIM = 0.38
EXIT = 0.3
VOICE_LEAD = 0.25
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


@dataclass
class Slide:
    kind: str
    start: float = 0.0
    end: float = 0.0
    elements: list = field(default_factory=list)
    clicks: list = field(default_factory=list)


def ease_out(p):
    return 1 - (1 - p) ** 3


def ease_in(p):
    return p ** 3


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


def add_words(slide, lines, fnt, size, line_h, top, t_start, theme, color_key='ink'):
    """Word-by-word reveal, highlighted words in accent with a soft underline behind them."""
    ink, accent = rgb(theme[color_key]), rgb(theme['accent'])
    t = t_start
    underlines, words = [], []
    for li, line in enumerate(lines):
        baseline = top + li * line_h + round(size * 0.92)
        run = None
        for word, hl, x, w in line:
            mask, pad, ascent = text_mask(word, fnt)
            words.append(El(mask, accent if hl else ink, round(MARGIN + x - pad), baseline - ascent, t))
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
            t += WORD_STEP
        if run:
            underlines.append((run, baseline))
    for (x0, x1, t0), baseline in underlines:
        uh = max(8, round(size * 0.2))
        mask = rounded_rect_mask(round(x1 - x0) + 12, uh, uh // 2)
        slide.elements.append(El(mask, accent, round(MARGIN + x0 - 6), baseline - round(uh * 0.35), t0 + 0.15,
                                 dur=0.45, rise=0, alpha=0.28, grow=True))
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

    # Hook
    s = Slide('hook')
    fnt, size, lines, line_h = fit(parse_highlights(reel['hook']), 'Bold', 124, 60, TEXT_W, 820, leading=1.1)
    block_h = len(lines) * line_h
    top = CONTENT_TOP + (CONTENT_BOTTOM - CONTENT_TOP - block_h) // 2 - 60
    end = add_words(s, lines, fnt, size, line_h, top, 0.3, theme)
    s.need = end + WORD_ANIM + 1.2 + 0.18 * words_in(reel['hook'])
    slides.append(s)

    # Points
    for i, point in enumerate(reel['points'], 1):
        s = Slide('point')
        num = f'{i:02d}'
        big, big_pad, big_asc = text_mask(num, font('Bold', 520))
        s.elements.append(El(big, rgb(theme['ink']), W - 50 - big.shape[1] + big_pad, SAFE_BOTTOM - 10 - big_asc,
                             0.05, dur=0.7, rise=40, alpha=0.06))

        t_fnt, t_size, t_lines, t_lh = fit(parse_highlights(point['title']), 'Bold', 88, 48, TEXT_W, 400, leading=1.12)
        b_fnt, b_size, b_lines, b_lh = fit(parse_highlights(point['body']), 'Regular', 48, 30, TEXT_W, 330, leading=1.38)
        circle_d, gap1, gap2 = 104, 44, 40
        group_h = circle_d + gap1 + len(t_lines) * t_lh + gap2 + len(b_lines) * b_lh
        # Centre above the big number; long text may still reach into it, which stays readable at 6% opacity.
        top = CONTENT_TOP + max(0, (POINT_BOTTOM - CONTENT_TOP - group_h) // 2)

        s.elements.append(El(circle_number_mask(num, circle_d), rgb(theme['accent']), MARGIN, top, 0.12, dur=0.45))
        title_top = top + circle_d + gap1
        end = add_words(s, t_lines, t_fnt, t_size, t_lh, title_top, 0.3, theme)
        body_t = end + 0.2
        body_top = title_top + len(t_lines) * t_lh + gap2
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
    top = CONTENT_TOP + (CONTENT_BOTTOM - CONTENT_TOP - group_h) // 2 - 40
    end = add_words(s, q_lines, q_fnt, q_size, q_lh, top, 0.3, theme)
    y = top + len(q_lines) * q_lh + 56
    y += add_block(s, 'Comment below', 'SemiBold', cb_size, 'accent', y, end + 0.15, theme, max_h=120) + 22
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
    if voice:
        # Speech sets the pace: each slide stays up until its line is finished.
        durs = [max(d, VOICE_LEAD + len(clip) / SR + 0.45 + EXIT) for d, clip in zip(durs, voice)]

    t = 0.0
    for s, d in zip(slides, durs):
        s.start, s.end = t, t + d
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
    if t < el.t0 or t >= el.slide[1]:
        return
    p = ease_out(min(1.0, (t - el.t0) / el.dur))
    a = el.alpha * (p if not el.grow else 1.0)
    dy = (1 - p) * el.rise
    q = min(1.0, max(0.0, (t - (el.slide[1] - EXIT)) / EXIT))
    if q > 0:
        e = ease_in(q)
        a *= 1 - e
        dy -= e * 70
    if a <= 0.003:
        return
    mask = el.mask
    if el.grow:
        cols = max(1, round(mask.shape[1] * p))
        mask = mask[:, :cols]
    composite(frame, el, a, el.x, round(el.y + dy), mask)


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
    statics = [
        El(accent_bar, rgb(theme['accent']), MARGIN, baseline - 16, 0, dur=0.3, rise=0),
        El(k_mask, rgb(theme['accent']), MARGIN + 50 - k_pad, baseline - k_asc, 0, dur=0.3, rise=0),
        El(h_mask, rgb(theme['muted']), W - MARGIN - h_mask.shape[1] + h_pad, baseline - h_asc, 0, dur=0.3, rise=0),
    ]
    return bars, bar_mask, statics


def render_frames(reel, slides, theme, pipe):
    bg = make_background(theme)
    bars, bar_mask, statics = build_chrome(reel, theme, len(slides))
    ink = rgb(theme['ink'])
    total = slides[-1].end
    n = round(total * FPS)
    track = El(bar_mask, ink, 0, 0, 0)
    for f in range(n):
        t = f / FPS
        frame = bg.copy()
        for i, (x, y, w, h) in enumerate(bars):
            s = slides[i]
            composite(frame, track, 0.16, x, y)
            p = min(1.0, max(0.0, (t - s.start) / (s.end - s.start)))
            cols = round(w * p)
            if cols:
                composite(frame, track, 0.85, x, y, bar_mask[:, :cols])
        for el in statics:
            draw_element(frame, el, t)
        for s in slides:
            if s.start <= t < s.end:
                for el in s.elements:
                    draw_element(frame, el, t)
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


def build_audio(slides, path, voice=None):
    total = slides[-1].end
    track = np.zeros(int(SR * (total + 0.5)))
    rng = np.random.default_rng(42)

    def place(sound, at, gain):
        i = int(at * SR)
        j = min(len(track), i + len(sound))
        if i < j:
            track[i:j] += sound[:j - i] * gain

    click_gain, whoosh_gain = (0.03, 0.08) if voice else (0.09, 0.16)
    for s in slides:
        for c in s.clicks:
            place(click_sound(rng), c, click_gain)
    for s in slides[1:]:
        place(whoosh_sound(rng), s.start - 0.3, whoosh_gain)
    if voice:
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
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
            '-profile:v', 'high', '-level', '4.1', '-maxrate', '8M', '-bufsize', '16M',
            '-g', str(FPS * 2),
            '-c:a', 'aac', '-b:a', '128k', '-ar', str(SR),
            '-shortest', '-movflags', '+faststart', str(out_path),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            render_frames(reel, slides, theme, proc.stdin)
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit('ffmpeg failed')
    print(f'Rendered {out_path} ({slides[-1].end:.1f}s, {out_path.stat().st_size / 1e6:.1f} MB)')
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
