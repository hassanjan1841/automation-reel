"""The weekly cheat-sheet carousel: Claude writes 6 to 8 swipeable slides on one practical topic, they are drawn
in the reels' editorial style (code slides use the same editor window), reviewed like reels, and posted to
Instagram as a carousel with alt text on every image. Posted carousels are recorded in carousels.json.

Env: IG_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY, CLAUDE_CODE_OAUTH_TOKEN; DRY_RUN=true renders only;
CLAUDE_MODEL (optional, the slide review), GRAPH_VERSION (optional, defaults to v25.0).
Usage: python carousel.py
"""

import json
import os
import re
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
CALL_TO_ACTION = re.compile(r'\b(save (this|it)|share (this|it)|bookmark|follow (me|us|for|@)|send (it|this)|tag a)\b', re.I)
OUT = render.OUT_DIR / 'carousel'

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['title', 'subtitle', 'slides', 'takeaway', 'question', 'caption', 'hashtags', 'style', 'dm_keyword',
                 'dm_guide'],
    'properties': {
        'title': {'type': 'string'}, 'subtitle': {'type': 'string'}, 'question': {'type': 'string'},
        'takeaway': {'type': 'string'}, 'dm_keyword': {'type': 'string'}, 'dm_guide': {'type': 'string'},
        'caption': {'type': 'string'}, 'hashtags': {'type': 'array', 'items': {'type': 'string'}},
        'style': {'type': 'string', 'enum': ['light', 'dark']},
        'slides': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['heading', 'alt'],
            'properties': {'heading': {'type': 'string'}, 'points': {'type': 'array', 'items': {'type': 'string'}},
                           'code': {'type': 'string'}, 'language': {'type': 'string'}, 'alt': {'type': 'string'}}}},
    },
}

SYSTEM = """You write a weekly Instagram cheat-sheet carousel for @hassanjan.k, a freelance full-stack developer.
It is the post people save: one practical topic, one idea per slide, useful on its own. The strongest topics
build one concrete thing in steps ("Add Stripe checkout in one afternoon", "Give Claude access to your database")
or are a checklist for a real task; the title promises that result.
- title: 3 to 8 words, the topic in plain searchable words; subtitle: one short line on what the reader gets.
- slides: 6 to 8. Each has a heading (max 5 words) and either 2 to 3 short "points" (max 7 words each) or a
  "code" snippet (max 8 lines of 40 characters, current non-deprecated APIs) with its "language". Mix both.
- alt: one plain sentence describing the slide for screen readers and search.
- takeaway: the whole carousel in one short line (max 8 words), shown big on the last slide under "The
  takeaway", e.g. "One webhook. Ten minutes. Payments that never get lost."
- dm_keyword and dm_guide: people who comment the keyword get dm_guide as a private message. dm_keyword: one short
  word in capitals (3 to 10 letters) tied to the topic, e.g. "STRIPE". dm_guide: the complete guide as a plain
  message (all steps, exact commands or code, official links), 150 to 900 characters, nothing invented. The
  caption's last line offers it: "Comment STRIPE and I'll send you the full guide 👇".
- question: a short question for the last slide that invites a real answer. That last slide is added for you
  and already asks people to save and follow, so every slide in "slides" is a real tip: none about saving,
  sharing, bookmarking or following.
- caption: first line is the topic in searchable words, then 1 or 2 short lines, ending with a question and 👇.
- hashtags: 3 to 5 focused tags. style: light or dark.
Never cover gambling, betting, interest-based loans, adult content or anything deceptive.
Code uses only real, official packages from the tool's maker (e.g. "@modelcontextprotocol/server-postgres"), never
a random third-party package, least of all for anything that handles credentials.
Honesty: evergreen and accurate; no invented numbers, results or stories; nothing presented as someone else's
work. No emojis on slides."""


def write(reels, carousels):
    done = [c['title'] for c in carousels] + [r['hook'].replace('*', '') for r in reels][-40:]
    context = generate.learned()
    prompt = ('Write this week\'s carousel. Topics already covered, do not repeat them:\n'
              + '\n'.join(f'- {t}' for t in done)
              + (f'\n\nWhat this account\'s viewers respond to:\n{context}' if context else '')
              + (f'\n\n{generate.asked()}' if generate.asked() else ''))
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
        if len(s['heading'].split()) > 5:
            errors.append(f'slide {i} heading is over 5 words')
        if s.get('code') and generate.package_errors(s['code']):
            errors.append(f"slide {i} names packages that do not exist: {', '.join(generate.package_errors(s['code']))}")
        if s.get('code'):
            lines = s['code'].rstrip('\n').split('\n')
            if len(lines) > 8 or max(len(l) for l in lines) > 40:
                errors.append(f'slide {i} code is over 8 lines of 40 characters')
        elif not 2 <= len(s.get('points') or []) <= 3 or any(len(p.split()) > 7 for p in s['points']):
            errors.append(f'slide {i} needs 2 to 3 points of max 7 words, or code')
    for i, s in enumerate(c['slides'], 1):
        # The closing slide already asks to save; a second "save this" slide wastes a swipe (2026-09-27).
        if CALL_TO_ACTION.search(' '.join([s['heading']] + (s.get('points') or []))):
            errors.append(f'slide {i} asks to save, share or follow; the last slide does that, make it a tip')
    if not 1 <= len(c.get('takeaway', '').split()) <= 8:
        errors.append('takeaway needs 1 to 8 words')
    errors += generate.dm_errors(c, f"Comment {c.get('dm_keyword', '')}")
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
    sub = wrap_text(c['subtitle'], render.font('Regular', 44), W - 2 * render.MARGIN)
    y = centred(len(lines) * line_h + 50 + 62 * len(sub))
    for li, line in enumerate(lines):
        for word, hl, x, _ in line:
            d.text((render.MARGIN + x, y + li * line_h), word, font=fnt, fill=theme['ink'], anchor='lt')
    y += len(lines) * line_h + 50
    for line in sub:
        d.text((render.MARGIN, y), line, font=render.font('Regular', 44), fill=theme['muted'], anchor='lt')
        y += 62
    footer(d, theme)
    return img


TOP, BOTTOM = 190, H - 150


def centred(height):
    """Top of a block of this height centred between the header and the footer, so no slide is half empty."""
    return TOP + max(0, (BOTTOM - TOP - height) // 2)


def content_slide(s, theme, n, total, top=None):
    """One tip. With top=None only measures: returns the block height, so every slide can start at the same
    height (centred for the tallest one) and headings do not jump around between swipes."""
    img = canvas(theme)
    d = ImageDraw.Draw(img)
    header(d, theme, n, total)
    m = render.MARGIN
    heading = wrap_text(s['heading'], render.font('Bold', 84), W - 2 * m)
    f = render.font('Regular', 54)
    if s.get('code'):
        panel, _ = visuals.code_image(s['code'], s.get('language'), '', W - 2 * 60, BOTTOM - TOP - 60 - 96 * len(heading) - 40)
        body_h = panel.height
    else:
        points = [wrap_text(p, f, W - 2 * m - 48) for p in s['points']]
        body_h = sum(72 * len(p) + 56 for p in points) - 56
    if top is None:
        return 60 + 96 * len(heading) + 40 + body_h
    y = top
    d.text((m, y), f'{n - 1:02d}', font=render.font('Bold', 44), fill=theme['accent'], anchor='lt')
    y += 60
    for line in heading:
        d.text((m, y), line, font=render.font('Bold', 84), fill=theme['ink'], anchor='lt')
        y += 96
    y += 40
    if s.get('code'):
        shadow = Image.new('RGBA', (panel.width + 80, panel.height + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((40, 52, panel.width + 40, panel.height + 52), radius=28,
                                                 fill=(0, 0, 0, 70))
        from PIL import ImageFilter
        img.paste(shadow.filter(ImageFilter.GaussianBlur(16)), (60 - 40, y - 40), shadow.filter(ImageFilter.GaussianBlur(16)))
        mask = Image.fromarray((visuals.rounded_mask(panel.width, panel.height, 28) * 255).astype(np.uint8))
        img.paste(panel, (60, y), mask)
    else:
        for lines in points:
            d.ellipse((m, y + 26, m + 16, y + 42), fill=theme['accent'])
            for li, line in enumerate(lines):
                d.text((m + 44, y + li * 72), line, font=f, fill=theme['ink'], anchor='lt')
            y += 72 * len(lines) + 56
    footer(d, theme)
    return img


def end_slide(c, theme, total):
    """The takeaway in one big line, then the question and the one call to save and follow."""
    img = canvas(theme)
    d = ImageDraw.Draw(img)
    header(d, theme, total, total)
    m, width = render.MARGIN, W - 2 * render.MARGIN
    take = wrap_text(c.get('takeaway', ''), render.font('Bold', 84), width) if c.get('takeaway') else []
    question = wrap_text(c['question'], render.font('SemiBold', 50) if take else render.font('Bold', 84), width)
    q_line = 64 if take else 98
    y = centred((70 + 98 * len(take) + 50 if take else 0) + q_line * len(question) + 160)
    if take:
        d.text((m, y), 'THE TAKEAWAY', font=render.font('SemiBold', 34), fill=theme['accent'], anchor='lt')
        y += 70
        for line in take:
            d.text((m, y), line, font=render.font('Bold', 84), fill=theme['ink'], anchor='lt')
            y += 98
        y += 50
    for line in question:
        d.text((m, y), line, font=render.font('SemiBold', 50) if take else render.font('Bold', 84),
               fill=theme['muted'] if take else theme['ink'], anchor='lt')
        y += q_line
    offer = f"Comment {c['dm_keyword']} for the full guide" if c.get('dm_keyword') else 'Save this for later'
    d.text((m, y + 40), offer, font=render.font('SemiBold', 48), fill=theme['accent'], anchor='lt')
    d.text((m, y + 110), f'Follow {render.HANDLE} for daily dev + AI tips', font=render.font('Regular', 36),
           fill=theme['muted'], anchor='lt')
    footer(d, theme, swipe=False)
    return img


def draw(c):
    render.ensure_fonts()
    theme = render.THEMES[c['style']]
    total = len(c['slides']) + 2
    top = centred(max(content_slide(s, theme, i + 2, total) for i, s in enumerate(c['slides'])))
    images = [title_slide(c, theme, total)] + [content_slide(s, theme, i + 2, total, top) for i, s in enumerate(c['slides'])] \
        + [end_slide(c, theme, total)]
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('slide-*.jpg'):
        old.unlink()  # a longer earlier run would leave extra slides behind
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
    proc = subprocess.run(['claude', '-p', prompt, '--model', (os.environ.get('CLAUDE_MODEL') or 'claude-sonnet-5'),
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
