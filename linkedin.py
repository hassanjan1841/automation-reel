"""LinkedIn: the same work, posted to the creator's LinkedIn profile too (asked 2026-10-20: "can we do this for
LinkedIn entirely, automated like the Instagram"). Each day's reel goes up as a native video, the weekly carousel as
a swipeable PDF document and each showcase as a video, every one with its own LinkedIn text that Claude writes from
the post (longer and plainer than an Instagram caption, the same honesty rules). The post id is recorded on the
entry (`linkedin_id` in reels.json, carousels.json or showcases.json), so nothing is posted twice.

What LinkedIn allows a member's app (Share on LinkedIn, scope w_member_social; learn.microsoft.com/linkedin): posts
with text, video, images and documents. An access token lasts 60 days and only approved partners get refresh
tokens, so the creator makes a new one about every two months; a refused token leaves out/linkedin-alert.md and the
workflow opens a "LinkedIn login expired" issue. Reading and answering comments needs LinkedIn's approval, so
comments there stay with the creator. Without LINKEDIN_TOKEN this does nothing and exits 0.

Usage:
  python linkedin.py reel <id>     post reel <id> (out/reel-<id>.mp4) and record it in reels.json
  python linkedin.py carousel      post the newest carousel (out/carousel/slide-*.jpg) as a PDF document
  python linkedin.py showcase      post the newest showcase (out/showcase-<id>.mp4)
  python linkedin.py --check       check the token and who it posts as
Env: LINKEDIN_TOKEN (secret), LINKEDIN_AUTHOR (urn:li:person:..., optional: else read from /v2/userinfo, which needs
     the openid and profile scopes too), LINKEDIN_VERSION (YYYYMM, default VERSION), DRY_RUN=true writes and prints
     the post and sends nothing.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

import render

API = 'https://api.linkedin.com'
VERSION = '202609'
MAX_TEXT = 3000           # LinkedIn's limit for a post's text
MIN_TEXT, LONG_TEXT = 300, 1500
PART = 4 * 1024 * 1024    # video upload part size LinkedIn's initializeUpload hands out
ALERT = render.OUT_DIR / 'linkedin-alert.md'
CAROUSELS = render.ROOT / 'carousels.json'
SHOWCASES = render.ROOT / 'showcases.json'
# LinkedIn's "little text" format: these characters are syntax and must be escaped, or the post is cut at them.
RESERVED = re.compile(r'([\\|{}@\[\]()<>#*_~])')
HASHTAG = re.compile(r'(?<![\w#])#(\w+)')
COMMENT_BAIT = re.compile(r'\b[Cc]omment\s+["“]?[A-Z]{3,}\b')


class LoginExpired(Exception):
    pass


# ---------- the text ----------

PROMPT = """Write the LinkedIn post for this piece of work by @hassanjan.k (a developer who posts daily web-dev and AI
tips). It goes up on his own LinkedIn profile next to the video or document, for developers and tech leads.

Rules:
- 300 to 1500 characters. A first line that states the point plainly (it is all people see before "see more"), then
  short paragraphs: what most people get wrong or miss, what is true, the exact thing to do. End with one direct
  question for the comments.
- Only what the post itself shows and its sources say. No invented numbers, results, stories or quotes. A product's
  claims are its own docs ("GitHub's docs say ..."). If sources are given, add one line "Source: <url>" (the main one).
- Plain, professional English. No hype words ("game changer", "mind-blowing"), no emojis except at most one, no
  "comment WORD to get", no engagement bait, no asking to like or share. Up to 3 hashtags on the last line.
- Never claim it was written or tested by hand when the post does not show it.

The post:
"""
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['text'],
          'properties': {'text': {'type': 'string'}}}


def text_errors(text, sources=()):
    out = []
    if not MIN_TEXT <= len(text) <= LONG_TEXT:
        out.append(f'the text has {len(text)} characters, needs {MIN_TEXT} to {LONG_TEXT}')
    if '?' not in text.strip().split('\n')[-1] and '?' not in text.strip().split('\n')[-2:][0]:
        out.append('end with one direct question for the comments')
    if len(HASHTAG.findall(text)) > 3:
        out.append('at most 3 hashtags')
    if COMMENT_BAIT.search(text):
        out.append('no "comment WORD" offers')
    if sources and not any(s in text for s in sources):
        out.append('add a "Source: <url>" line with the main source')
    return out


def write_text(piece, sources=(), attempts=3):
    """The LinkedIn text for a piece (reel, carousel or showcase, as JSON), written by Claude and checked."""
    import generate
    feedback = ''
    for _ in range(attempts):
        proc = subprocess.run(
            ['claude', '-p', PROMPT + json.dumps(piece, ensure_ascii=False, indent=1) + feedback, '--model', generate.MODEL,
             '--tools', '', '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(SCHEMA)],
            capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
        text = (json.loads(proc.stdout).get('structured_output') or {}).get('text', '').strip()
        problems = text_errors(text, sources)
        if not problems:
            return text
        feedback = '\n\nA previous draft had these problems, fix them:\n' + '\n'.join(problems)
    raise RuntimeError('no LinkedIn text that passes the checks: ' + '; '.join(problems))


def little(text):
    """The text in LinkedIn's little text format: reserved characters escaped, hashtags as hashtag elements."""
    parts, last = [], 0
    for m in HASHTAG.finditer(text):
        parts.append(RESERVED.sub(r'\\\1', text[last:m.start()]))
        parts.append('{hashtag|\\#|' + m.group(1) + '}')
        last = m.end()
    parts.append(RESERVED.sub(r'\\\1', text[last:]))
    return ''.join(parts)


# ---------- the API ----------

def headers(token, json_body=True):
    h = {'Authorization': f'Bearer {token}', 'LinkedIn-Version': os.environ.get('LINKEDIN_VERSION') or VERSION,
         'X-Restli-Protocol-Version': '2.0.0'}
    if json_body:
        h['Content-Type'] = 'application/json'
    return h


def check(resp, what):
    if resp.status_code == 401:
        ALERT.parent.mkdir(parents=True, exist_ok=True)
        ALERT.write_text('LinkedIn refused the token (HTTP 401) while trying to ' + what + '. Access tokens last 60 days.\n\n'
                         'Make a new one: linkedin.com/developers/apps -> your app -> Auth -> OAuth 2.0 tools -> Create '
                         'token (scopes w_member_social, openid, profile), then GitHub -> Settings -> Secrets and '
                         'variables -> Actions -> LINKEDIN_TOKEN -> Update.\n')
        raise LoginExpired(f'LinkedIn refused the token while trying to {what}')
    if not resp.ok:
        raise RuntimeError(f'LinkedIn {what} failed: HTTP {resp.status_code} {resp.text[:300]}')
    return resp


def author(token):
    urn = os.environ.get('LINKEDIN_AUTHOR', '').strip()
    if urn:
        return urn
    info = check(requests.get(f'{API}/v2/userinfo', headers={'Authorization': f'Bearer {token}'}, timeout=30),
                 'read who the token belongs to').json()
    return f"urn:li:person:{info['sub']}"


def upload_video(token, owner, path):
    size = Path(path).stat().st_size
    init = check(requests.post(f'{API}/rest/videos?action=initializeUpload', headers=headers(token), timeout=60,
                               json={'initializeUploadRequest': {'owner': owner, 'fileSizeBytes': size,
                                                                 'uploadCaptions': False, 'uploadThumbnail': False}}),
                 'start the video upload').json()['value']
    etags = []
    with open(path, 'rb') as f:
        for part in init['uploadInstructions']:
            f.seek(part['firstByte'])
            data = f.read(part['lastByte'] - part['firstByte'] + 1)
            resp = check(requests.put(part['uploadUrl'], data=data, timeout=300,
                                      headers={'Content-Type': 'application/octet-stream'}), 'upload the video')
            etags.append(resp.headers.get('ETag', '').strip('"'))
    check(requests.post(f'{API}/rest/videos?action=finalizeUpload', headers=headers(token), timeout=60,
                        json={'finalizeUploadRequest': {'video': init['video'], 'uploadToken': init.get('uploadToken', ''),
                                                        'uploadedPartIds': etags}}), 'finish the video upload')
    wait_available(token, 'videos', init['video'])
    return init['video']


def upload_document(token, owner, path):
    init = check(requests.post(f'{API}/rest/documents?action=initializeUpload', headers=headers(token), timeout=60,
                               json={'initializeUploadRequest': {'owner': owner}}), 'start the document upload').json()['value']
    with open(path, 'rb') as f:
        check(requests.put(init['uploadUrl'], data=f.read(), timeout=300,
                           headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/octet-stream'}),
              'upload the document')
    wait_available(token, 'documents', init['document'])
    return init['document']


def wait_available(token, kind, urn, tries=40, every=6):
    """LinkedIn processes an upload before a post may use it."""
    for _ in range(tries):
        status = check(requests.get(f'{API}/rest/{kind}/{requests.utils.quote(urn, safe="")}', headers=headers(token, False),
                                    timeout=30), f'check the {kind[:-1]}').json().get('status')
        if status == 'AVAILABLE':
            return
        if status == 'PROCESSING_FAILED':
            raise RuntimeError(f'LinkedIn could not process the {kind[:-1]}')
        time.sleep(every)
    raise RuntimeError(f'the {kind[:-1]} was still processing after {tries * every} seconds')


def create_post(token, owner, text, media_urn, title):
    resp = check(requests.post(f'{API}/rest/posts', headers=headers(token), timeout=60, json={
        'author': owner, 'commentary': little(text), 'visibility': 'PUBLIC',
        'distribution': {'feedDistribution': 'MAIN_FEED', 'targetEntities': [], 'thirdPartyDistributionChannels': []},
        'content': {'media': {'title': title[:200], 'id': media_urn}},
        'lifecycleState': 'PUBLISHED', 'isReshareDisabledByAuthor': False}), 'publish the post')
    return resp.headers.get('x-restli-id') or resp.headers.get('X-RestLi-Id') or ''


# ---------- what gets posted ----------

def pdf(slides, out):
    """The carousel slides as one PDF, which LinkedIn shows as a swipeable document."""
    from PIL import Image
    images = [Image.open(p).convert('RGB') for p in slides]
    images[0].save(out, save_all=True, append_images=images[1:], resolution=150)
    return out


def load(path):
    return json.loads(Path(path).read_text()) if Path(path).exists() else []


def save(path, entries):
    Path(path).write_text(json.dumps(entries, indent=2, ensure_ascii=False) + '\n')


def target(kind, arg=None):
    """(file of records, the entry, the file to post, title, what Claude writes from, sources)."""
    if kind == 'reel':
        entries = json.loads(render.QUEUE.read_text())
        entry = next((r for r in entries if str(r.get('id')) == str(arg)), None)
        if entry is None:
            raise SystemExit(f'no reel {arg} in reels.json')
        piece = {k: entry.get(k) for k in ('hook', 'payoff', 'points', 'voiceover', 'caption', 'sources') if entry.get(k)}
        return render.QUEUE, entries, entry, render.OUT_DIR / f"reel-{entry['id']}.mp4", \
            entry['hook'].replace('*', ''), piece, entry.get('sources') or []
    if kind == 'carousel':
        entries = load(CAROUSELS)
        if not entries:
            raise SystemExit('no carousel in carousels.json')
        entry = entries[-1]
        slides = sorted((render.OUT_DIR / 'carousel').glob('slide-*.jpg'))
        doc = pdf(slides, render.OUT_DIR / 'carousel' / 'carousel.pdf') if slides else render.OUT_DIR / 'carousel' / 'missing.pdf'
        piece = {k: v for k, v in entry.items() if k not in ('media_id', 'posted_at', 'linkedin_id')}
        return CAROUSELS, entries, entry, doc, entry.get('title', 'Cheat sheet'), piece, entry.get('sources') or []
    if kind == 'showcase':
        entries = load(SHOWCASES)
        if not entries:
            raise SystemExit('no showcase in showcases.json')
        entry = entries[-1]
        piece = {'idea': entry.get('title'), 'beats': [b['text'].replace('*', '') for b in entry.get('beats', [])],
                 'caption': entry.get('caption'), 'kind': 'a short abstract motion piece with no voice'}
        return SHOWCASES, entries, entry, render.OUT_DIR / f"showcase-{entry['id']}.mp4", entry.get('title', ''), piece, []
    raise SystemExit(__doc__)


def post(kind, arg=None):
    token = os.environ.get('LINKEDIN_TOKEN', '').strip()
    if not token:
        print('LinkedIn is not set up (no LINKEDIN_TOKEN); skipping')
        return None
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    path, entries, entry, media, title, piece, sources = target(kind, arg)
    if entry.get('linkedin_id'):
        print(f"Already on LinkedIn ({entry['linkedin_id']})")
        return entry['linkedin_id']
    if not Path(media).exists():
        raise SystemExit(f'{media} not found: nothing to post to LinkedIn')
    text = write_text(piece, sources)
    print(f'LinkedIn post ({len(text)} characters):\n{text}\n')
    if dry:
        print('DRY_RUN: not posting to LinkedIn')
        return None
    owner = author(token)
    urn = upload_document(token, owner, media) if kind == 'carousel' else upload_video(token, owner, media)
    post_id = create_post(token, owner, text, urn, title)
    entry['linkedin_id'] = post_id or urn
    save(path, entries)
    print(f'Posted to LinkedIn: {entry["linkedin_id"]}')
    return entry['linkedin_id']


def main():
    args = sys.argv[1:]
    if args == ['--check']:
        token = os.environ.get('LINKEDIN_TOKEN', '').strip()
        if not token:
            raise SystemExit('no LINKEDIN_TOKEN')
        print(f'The token posts as {author(token)}')
        return
    if not args or args[0] not in ('reel', 'carousel', 'showcase') or (args[0] == 'reel' and len(args) != 2):
        raise SystemExit(__doc__)
    try:
        post(args[0], args[1] if len(args) > 1 else None)
    except LoginExpired as e:
        raise SystemExit(f'ERROR: {e}; see {ALERT}')


if __name__ == '__main__':
    main()
