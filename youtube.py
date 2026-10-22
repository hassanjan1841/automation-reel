"""YouTube Shorts: the same reels and showcases, uploaded to the creator's YouTube channel too (asked 2026-10-22,
"Yup add YouTube Shorts"). A vertical video under three minutes is a Short on its own, so the reel file goes up as
it is. Title and description come from the reel itself (its hook, caption, sources and hashtags), not from a new
Claude write, so they say only what the reel says. The video id is recorded on the entry (`youtube_id` in reels.json
or showcases.json), so nothing is uploaded twice.

What YouTube allows (developers.google.com/youtube/v3/docs/videos/insert, read 2026-10-22): videos.insert with the
youtube.upload scope, 100 uploads a day; uploads from unverified API projects are not restricted to private. Title at
most 100 characters and description at most 5000 bytes, neither with < or >. status.containsSyntheticMedia is for
realistic altered or synthetic scenes (a real person saying what they did not); our reels are code and abstract
motion, so it stays false, and the description says plainly that the voice is an AI voice.

Login: an OAuth client (YT_CLIENT_ID, YT_CLIENT_SECRET) and a refresh token for the channel (YT_REFRESH_TOKEN),
all repository secrets. A refused refresh token leaves out/youtube-alert.md and the workflow opens a "YouTube login
expired" issue. Without the three secrets this does nothing and exits 0.

Usage:
  python youtube.py reel <id>     upload reel <id> (out/reel-<id>.mp4) and record it in reels.json
  python youtube.py showcase      upload the newest showcase (out/showcase-<id>.mp4)
  python youtube.py --check       check the login and which channel it uploads to
Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (secrets), YT_PRIVACY (public, unlisted or private; default
     public), DRY_RUN=true prints the title and description and uploads nothing.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests

import render

TOKEN_URL = 'https://oauth2.googleapis.com/token'
UPLOAD_URL = 'https://www.googleapis.com/upload/youtube/v3/videos'
CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'
MAX_TITLE, MAX_DESCRIPTION = 100, 5000
# The scopes the refresh token needs: upload, and read (for --check, which channel it uploads to).
SCOPES = 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly'
CATEGORY = '28'             # Science & Technology
ALERT = render.OUT_DIR / 'youtube-alert.md'
SHOWCASES = render.ROOT / 'showcases.json'
AI_VOICE = 'Narrated with an AI voice.'
HASHTAG = re.compile(r'#(\w+)')


class LoginExpired(Exception):
    pass


# ---------- the words: taken from the reel, never written fresh ----------

def clean(text):
    """Text YouTube accepts: no < or >, no markdown highlights."""
    return re.sub(r'[<>]', '', str(text or '').replace('*', '')).strip()


def title_for(entry, kind):
    words = clean(entry.get('hook') if kind == 'reel' else entry.get('title'))
    if len(words) > MAX_TITLE:
        words = words[:MAX_TITLE - 1].rsplit(' ', 1)[0] + '…'
    return words


def description_for(entry, kind):
    lines = [clean(entry.get('caption'))]
    sources = entry.get('sources') or []
    if sources:
        lines.append('Sources:\n' + '\n'.join(clean(s) for s in sources))
    if kind == 'reel':
        lines.append(AI_VOICE)
    tags = ' '.join('#' + t for t in tags_for(entry)) + ' #Shorts'
    lines.append(tags.strip())
    text = '\n\n'.join(x for x in lines if x)
    while len(text.encode()) > MAX_DESCRIPTION:
        text = text[:-50]
    return text


def tags_for(entry):
    tags = entry.get('hashtags') or HASHTAG.findall(str(entry.get('caption') or ''))
    return [str(t).lstrip('#') for t in tags][:10]


# ---------- the API ----------

def access_token():
    resp = requests.post(TOKEN_URL, timeout=60, data={
        'client_id': os.environ['YT_CLIENT_ID'].strip(), 'client_secret': os.environ['YT_CLIENT_SECRET'].strip(),
        'refresh_token': os.environ['YT_REFRESH_TOKEN'].strip(), 'grant_type': 'refresh_token'})
    if resp.status_code in (400, 401) and 'invalid_grant' in resp.text:
        ALERT.parent.mkdir(exist_ok=True)
        ALERT.write_text('YouTube refused the refresh token (revoked, expired or the app is still in Testing, where '
                         'refresh tokens last 7 days). Make a new one and update the YT_REFRESH_TOKEN secret; see '
                         'README.md, "YouTube Shorts".\n')
        raise LoginExpired('YouTube login expired')
    resp.raise_for_status()
    return resp.json()['access_token']


def upload(token, path, title, description, tags, privacy):
    meta = {'snippet': {'title': title, 'description': description, 'tags': tags, 'categoryId': CATEGORY},
            'status': {'privacyStatus': privacy, 'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': False}}
    size = Path(path).stat().st_size
    start = requests.post(UPLOAD_URL, params={'uploadType': 'resumable', 'part': 'snippet,status'}, timeout=60,
                          json=meta, headers={'Authorization': f'Bearer {token}', 'X-Upload-Content-Type': 'video/mp4',
                                              'X-Upload-Content-Length': str(size)})
    start.raise_for_status()
    with open(path, 'rb') as f:
        done = requests.put(start.headers['Location'], data=f, timeout=600,
                            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'video/mp4',
                                     'Content-Length': str(size)})
    done.raise_for_status()
    return done.json()['id']


# ---------- what to post ----------

def load(path):
    return json.loads(Path(path).read_text()) if Path(path).exists() else []


def save(path, entries):
    Path(path).write_text(json.dumps(entries, indent=2, ensure_ascii=False) + '\n')


def target(kind, arg=None):
    """(file of records, all entries, the entry, the video file)."""
    if kind == 'reel':
        entries = json.loads(render.QUEUE.read_text())
        entry = next((r for r in entries if str(r.get('id')) == str(arg)), None)
        if entry is None:
            raise SystemExit(f'no reel {arg} in reels.json')
        return render.QUEUE, entries, entry, render.OUT_DIR / f"reel-{entry['id']}.mp4"
    if kind == 'showcase':
        entries = load(SHOWCASES)
        if not entries:
            raise SystemExit('no showcase in showcases.json')
        return SHOWCASES, entries, entries[-1], render.OUT_DIR / f"showcase-{entries[-1]['id']}.mp4"
    raise SystemExit(__doc__)


def configured():
    return all(os.environ.get(k, '').strip() for k in ('YT_CLIENT_ID', 'YT_CLIENT_SECRET', 'YT_REFRESH_TOKEN'))


def post(kind, arg=None):
    if not configured():
        print('YouTube is not set up (no YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN); skipping')
        return None
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    path, entries, entry, video = target(kind, arg)
    if entry.get('youtube_id'):
        print(f"Already on YouTube ({entry['youtube_id']})")
        return entry['youtube_id']
    if not Path(video).exists():
        raise SystemExit(f'{video} not found: nothing to upload to YouTube')
    title, description = title_for(entry, kind), description_for(entry, kind)
    privacy = os.environ.get('YT_PRIVACY', '').strip() or 'public'
    print(f'YouTube Short ({privacy}): {title}\n{description}\n')
    if dry:
        print('DRY_RUN: not uploading to YouTube')
        return None
    video_id = upload(access_token(), video, title, description, tags_for(entry), privacy)
    entry['youtube_id'] = video_id
    save(path, entries)
    print(f'Uploaded to YouTube: https://youtube.com/shorts/{video_id}')
    return video_id


def main():
    args = sys.argv[1:]
    if args == ['--check']:
        if not configured():
            raise SystemExit('YouTube is not set up')
        resp = requests.get(CHANNELS_URL, params={'part': 'snippet', 'mine': 'true'}, timeout=60,
                            headers={'Authorization': f'Bearer {access_token()}'})
        resp.raise_for_status()
        print('Uploads to:', ', '.join(c['snippet']['title'] for c in resp.json().get('items', [])) or 'no channel')
        return
    if not args or args[0] not in ('reel', 'showcase') or (args[0] == 'reel' and len(args) != 2):
        raise SystemExit(__doc__)
    try:
        post(args[0], args[1] if len(args) > 1 else None)
    except LoginExpired as e:
        raise SystemExit(f'ERROR: {e}; see {ALERT}')


if __name__ == '__main__':
    main()
