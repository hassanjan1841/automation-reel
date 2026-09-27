"""The weekly cheat-sheet carousel: Claude writes 6 to 8 swipeable slides on one practical topic, they are drawn
in the reels' editorial style (code slides use the same editor window), reviewed like reels, and posted to
Instagram as a carousel with alt text on every image. Posted carousels are recorded in carousels.json.

Env: IG_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY, CLAUDE_CODE_OAUTH_TOKEN; DRY_RUN=true renders only.
Usage: python carousel.py
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw

import generate
import render
import visuals

W, H = 1080, 1350
LOG = render.ROOT / 'carousels.json'
OUT = render.OUT_DIR / 'carousel'

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['title', 'subtitle', 'slides', 'question', 'caption', 'hashtags', 'style'],
    'properties': {
        'title': {'type': 'string'}, 'subtitle': {'type': 'string'}, 'question': {'type': 'string'},
        'caption': {'type': 'string'}, 'hashtags': {'type': 'array', 'items': {'type': 'string'}},
        'style': {'type': 'string', 'enum': ['light', 'dark']},
        'slides': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['heading', 'alt'],
            'properties': {'heading': {'type': 'string'}, 'points': {'type': 'array', 'items': {'type': 'string'}},
                           'code': {'type': 'string'}, 'language': {'type': 'string'}, 'alt': {'type': 'string'}}}},
    },
}

SYSTEM = """You write a weekly Instagram cheat-sheet carousel for @hassanjan.k, a freelance full-stack developer.
It is the post people save: one practical topic, one idea per slide, useful on its own.
- title: 3 to 8 words, the topic in plain searchable words; subtitle: one short line on what the reader gets.
- slides: 6 to 8. Each has a heading (max 7 words) and either 2 to 4 short "points" (max 12 words each) or a
  "code" snippet (max 8 lines of 40 characters, current non-deprecated APIs) with its "language". Mix both.
- alt: one plain sentence describing the slide for screen readers and search.
- question: a short question for the last slide that invites a real answer.
- caption: first line is the topic in searchable words, then 1 or 2 short lines, ending with a question and 👇.
- hashtags: 3 to 5 focused tags. style: light or dark.
Honesty: evergreen and accurate; no invented numbers, results or stories; nothing presented as someone else's
work. No emojis on slides."""


def write(reels, carousels):
    done = [c['title'] for c in carousels] + [r['hook'].replace('*', '') for r in reels][-40:]
    context = generate.learned()
    prompt = ('Write this week\'s carousel. Topics already covered, do not repeat them:\n'
              + '\n'.join(f'- {t}' for t in done)
              + (f'\n\nWhat this account\'s viewers respond to:\n{context}' if context else ''))
    for _ in range(2):
        proc = subprocess.run(['claude', '-p', prompt, '--model', generate.MODEL, '--system-prompt', SYSTEM,
                               '--tools', '', '--setting-sources', '', '--no-session-persistence',
                               '--output-format', 'json', '--json-schema', json.dumps(SCHEMA)],
                              capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        out = json.loads(proc.stdout).get('structured_output') if proc.returncode == 0 else None
        errors = check(out) if out else ['no output']
        if not errors:
            return out
        prompt += '\n\nThe previous attempt had these problems, fix them:\n' + '\n'.join(errors)
    raise SystemExit('ERROR: could not write a valid carousel: ' + '; '.join(errors))


def check(c):
    errors = []
    if not 6 <= len(c['slides']) <= 8:
        errors.append('needs 6 to 8 slides')
    for i, s in enumerate(c['slides'], 1):
        if len(s['heading'].split()) > 7:
            errors.append(f'slide {i} heading is over 7 words')
        if s.get('code'):
            lines = s['code'].rstrip('\n').split('\n')
            if len(lines) > 8 or max(len(l) for l in lines) > 40:
                errors.append(f'slide {i} code is over 8 lines of 40 characters')
        elif not 2 <= len(s.get('points') or []) <= 4 or any(len(p.split()) > 12 for p in s['points']):
            errors.append(f'slide {i} needs 2 to 4 points of max 12 words, or code')
    if not 3 <= len(c['hashtags']) <= 5:
        errors.append('needs 3 to 5 hashtags')
    return errors


# ---------- drawing ----------

def canvas(theme):
    bg = render.make_background(theme)
    # The reel background is 1080x1920; the carousel uses its middle.
    top = (render.H - H) // 2
    return Image.fromarray(np.clip(bg[top:top + H], 0, 255).astype(np.uint8))


def header(d, theme, n, total):
    m = render.MARGIN
    d.rounded_rectangle((m, 92, m + 36, 98), radius=3, fill=theme['accent'])
    d.text((m + 52, 95), 'CHEAT SHEET', font=render.font('SemiBold', 30), fill=theme['accent'], anchor='lm')
    d.text((W - m, 95), f'{n}/{total}', font=render.font('Regular', 30), fill=theme['muted'], anchor='rm')


def footer(d, theme, swipe=True):
    m = render.MARGIN
    d.text((m, H - 80), render.HANDLE, font=render.font('Regular', 30), fill=theme['muted'], anchor='lm')
    if swipe:
        d.text((W - m, H - 80), 'Swipe  >', font=render.font('SemiBold', 30), fill=theme['accent'], anchor='rm')


def wrap_text(text, fnt, width):
    lines, cur = [], ''
    for word in text.split():
        trial = (cur + ' ' + word).strip()
        if fnt.getlength(trial) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur]


def title_slide(c, theme, total):
    img = canvas(theme)
    d = ImageDraw.Draw(img)
    header(d, theme, 1, total)
    fnt, size, lines, line_h = render.fit(render.parse_highlights(c['title']), 'Bold', 118, 60, W - 2 * render.MARGIN,
                                          560, leading=1.08)
    y = 360
    for li, line in enumerate(lines):
        for word, hl, x, _ in line:
            d.text((render.MARGIN + x, y + li * line_h), word, font=fnt, fill=theme['ink'], anchor='lt')
    y += len(lines) * line_h + 50
    for line in wrap_text(c['subtitle'], render.font('Regular', 44), W - 2 * render.MARGIN):
        d.text((render.MARGIN, y), line, font=render.font('Regular', 44), fill=theme['muted'], anchor='lt')
        y += 62
    footer(d, theme)
    return img


def content_slide(s, theme, n, total):
    img = canvas(theme)
    d = ImageDraw.Draw(img)
    header(d, theme, n, total)
    m = render.MARGIN
    d.text((m, 190), f'{n - 1:02d}', font=render.font('Bold', 40), fill=theme['accent'], anchor='lt')
    y = 250
    for line in wrap_text(s['heading'], render.font('Bold', 74), W - 2 * m):
        d.text((m, y), line, font=render.font('Bold', 74), fill=theme['ink'], anchor='lt')
        y += 86
    y += 40
    if s.get('code'):
        panel, _ = visuals.code_image(s['code'], s.get('language'), '', W - 2 * 60, H - y - 170)
        shadow = Image.new('RGBA', (panel.width + 80, panel.height + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((40, 52, panel.width + 40, panel.height + 52), radius=28,
                                                 fill=(0, 0, 0, 70))
        from PIL import ImageFilter
        img.paste(shadow.filter(ImageFilter.GaussianBlur(16)), (60 - 40, y - 40), shadow.filter(ImageFilter.GaussianBlur(16)))
        mask = Image.fromarray((visuals.rounded_mask(panel.width, panel.height, 28) * 255).astype(np.uint8))
        img.paste(panel, (60, y), mask)
    else:
        f = render.font('Regular', 46)
        for p in s['points']:
            d.ellipse((m, y + 22, m + 14, y + 36), fill=theme['accent'])
            for li, line in enumerate(wrap_text(p, f, W - 2 * m - 44)):
                d.text((m + 40, y + li * 62), line, font=f, fill=theme['ink'], anchor='lt')
            y += 62 * len(wrap_text(p, f, W - 2 * m - 44)) + 34
    footer(d, theme)
    return img


def end_slide(c, theme, total):
    img = canvas(theme)
    d = ImageDraw.Draw(img)
    header(d, theme, total, total)
    y = 420
    for line in wrap_text(c['question'], render.font('Bold', 84), W - 2 * render.MARGIN):
        d.text((render.MARGIN, y), line, font=render.font('Bold', 84), fill=theme['ink'], anchor='lt')
        y += 98
    d.text((render.MARGIN, y + 40), 'Save this for later', font=render.font('SemiBold', 48), fill=theme['accent'],
           anchor='lt')
    d.text((render.MARGIN, y + 110), f'Follow {render.HANDLE} for daily dev + AI tips', font=render.font('Regular', 36),
           fill=theme['muted'], anchor='lt')
    footer(d, theme, swipe=False)
    return img


def draw(c):
    render.ensure_fonts()
    theme = render.THEMES[c['style']]
    total = len(c['slides']) + 2
    images = [title_slide(c, theme, total)] + [content_slide(s, theme, i + 2, total) for i, s in enumerate(c['slides'])] \
        + [end_slide(c, theme, total)]
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, im in enumerate(images, 1):
        path = OUT / f'slide-{i:02d}.jpg'
        im.convert('RGB').save(path, 'JPEG', quality=92)
        paths.append(path)
    alts = [f"{c['title']}: {c['subtitle']}"] + [s['alt'] for s in c['slides']] + [c['question']]
    return paths, alts


# ---------- review and publishing ----------

def review(paths, tries=2):
    """Claude looks at every slide: readable, nothing cut off, honest. A layout complaint gets a second look
    (the reviewer sometimes misreads a word); a dishonest verdict stops at once."""
    for attempt in range(tries):
        out = review_once(paths)
        if not out.get('honest', False):
            raise SystemExit('ERROR: carousel review found a dishonest claim: ' + '; '.join(out.get('problems', [])))
        if out.get('ok'):
            return
        print('Review problems: ' + '; '.join(out.get('problems', [])))
    raise SystemExit('ERROR: carousel review failed twice: ' + '; '.join(out.get('problems', ['no review'])))


def review_once(paths):
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['ok', 'honest', 'problems'],
              'properties': {'ok': {'type': 'boolean'}, 'honest': {'type': 'boolean'},
                             'problems': {'type': 'array', 'items': {'type': 'string'}}}}
    prompt = ('Open each slide image with the Read tool. Is every slide readable on a phone, with no text cut off or '
              'overlapping, and honest (no invented results, numbers or stories)?\n' + '\n'.join(map(str, paths)))
    proc = subprocess.run(['claude', '-p', prompt, '--model', os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5'),
                           '--tools', 'Read', '--allowedTools', 'Read', '--add-dir', str(OUT), '--setting-sources', '',
                           '--no-session-persistence', '--output-format', 'json', '--json-schema', json.dumps(schema)],
                          capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    try:
        return json.loads(proc.stdout).get('structured_output') or {}
    except ValueError:
        return {}


def post(paths, alts, caption):
    import publish
    token = publish.env('IG_TOKEN')
    me = publish.ig_get('me', token, fields='user_id,username')
    ig_id = me.get('user_id') or me.get('id')
    stamp = int(time.time())
    names, children = [], []
    try:
        for i, (path, alt) in enumerate(zip(paths, alts), 1):
            name = f'carousel-{stamp}-{i:02d}.jpg'
            url = publish.upload(path, name, 'image/jpeg')
            names.append(name)
            children.append(publish.ig_post(f'{ig_id}/media', token, image_url=url, is_carousel_item='true',
                                            alt_text=alt[:1000])['id'])
        parent = publish.ig_post(f'{ig_id}/media', token, media_type='CAROUSEL', children=','.join(children),
                                 caption=caption)['id']
        for _ in range(30):
            if publish.ig_get(parent, token, fields='status_code').get('status_code') == 'FINISHED':
                break
            time.sleep(5)
        return publish.ig_post(f'{ig_id}/media_publish', token, creation_id=parent)['id']
    finally:
        for name in names:
            publish.delete_upload(name)


def main():
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    reels = json.loads(render.QUEUE.read_text())
    carousels = json.loads(LOG.read_text()) if LOG.exists() else []
    c = write(reels, carousels)
    paths, alts = draw(c)
    print(f"Carousel: {c['title']} ({len(paths)} slides)")
    review(paths)
    caption = f"{c['caption'].strip()}\n\n{' '.join(c['hashtags'])}"
    if dry:
        print(f'DRY_RUN: rendered {len(paths)} slides to {OUT}. Nothing posted.\n{caption}')
        return
    media_id = post(paths, alts, caption)
    carousels.append({**c, 'posted_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'media_id': media_id})
    LOG.write_text(json.dumps(carousels, indent=2, ensure_ascii=False) + '\n')
    print(f'Published carousel as media {media_id}')


if __name__ == '__main__':
    main()
