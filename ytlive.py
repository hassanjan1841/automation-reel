"""Live YouTube numbers: every 10 minutes (scheduler.yml) read the public counts of recent Shorts and keep one GitHub
issue, "Live YouTube numbers", updated in place: views now, views in the last hour, views per hour since posting.

YouTube's Analytics API runs 48 to 72 hours behind and Studio's realtime card has no API, so this uses the Data API
counts (videos.list statistics, 1 quota unit per call for up to 50 videos). Shorts posted in the last 48 hours are
read on every run, those 2 to 7 days old once an hour, older ones not at all. The samples live in the issue body
(a hidden JSON block), so nothing is committed. Standard library only.

Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (the upload login), GH_TOKEN (gh CLI, issues: write).
Usage: python ytlive.py          update the issue (does nothing without the YT_ secrets)
       python ytlive.py --dry    print the table instead
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TITLE = 'Live YouTube numbers'
FAST_HOURS, SLOW_DAYS = 48, 7          # every run while this young, then hourly until this old
KEEP = 60                              # samples kept per Short in the issue body
STATE = re.compile(r'<!-- ytlive (.*?) -->', re.S)


def now():
    return datetime.now(timezone.utc)


def recent(entries, at):
    """[(youtube_id, title, posted_at)] for entries posted within SLOW_DAYS, newest first."""
    out = []
    for e in entries:
        if e.get('youtube_id') and e.get('posted_at'):
            posted = datetime.fromisoformat(e['posted_at'])
            if at - posted <= timedelta(days=SLOW_DAYS):
                out.append((e['youtube_id'], (e.get('hook') or e.get('title') or '').replace('*', ''), posted))
    return sorted(out, key=lambda x: x[2], reverse=True)


def due(posted, samples, at):
    """Read every run while young; afterwards once an hour."""
    if at - posted <= timedelta(hours=FAST_HOURS) or not samples:
        return True
    return at - datetime.fromisoformat(samples[-1][0]) >= timedelta(minutes=55)


def views_last_hour(samples, at):
    """Views gained since the newest sample at least an hour old (None until one exists)."""
    old = [s for s in samples if at - datetime.fromisoformat(s[0]) >= timedelta(hours=1)]
    return samples[-1][1] - old[-1][1] if old and samples else None


def table(videos, state, at):
    rows = ['| Short | Age | Views | Last hour | Per hour | Likes | Comments |', '|---|---|---|---|---|---|---|']
    for vid, title, posted in videos:
        s = state.get(vid) or []
        if not s:
            continue
        hours = max((at - posted).total_seconds() / 3600, 0.1)
        last = views_last_hour(s, at)
        age = f'{hours:.0f} h' if hours < 48 else f'{hours / 24:.1f} d'
        rows.append(f'| [{title[:48]}](https://youtube.com/shorts/{vid}) | {age} | {s[-1][1]} | '
                    f"{'-' if last is None else f'+{last}'} | {s[-1][1] / hours:.1f} | {s[-1][2]} | {s[-1][3]} |")
    stamp = at.strftime('%Y-%m-%d %H:%M UTC')
    return (f'# {TITLE}\n\nUpdated {stamp} by ytlive.py (every 10 minutes for 48 hours after posting, then hourly '
            'until day 7). Counts are YouTube\'s public numbers, read live; watch time, sources and audience are in the '
            'daily report (2 to 3 days behind).\n\n' + '\n'.join(rows) + '\n')


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None,
                                 headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def stats(ids):
    token = http('https://oauth2.googleapis.com/token', {
        'client_id': os.environ['YT_CLIENT_ID'].strip(), 'client_secret': os.environ['YT_CLIENT_SECRET'].strip(),
        'refresh_token': os.environ['YT_REFRESH_TOKEN'].strip(), 'grant_type': 'refresh_token'})['access_token']
    q = urllib.parse.urlencode({'part': 'statistics', 'id': ','.join(ids[:50])})
    data = http(f'https://www.googleapis.com/youtube/v3/videos?{q}', headers={'Authorization': f'Bearer {token}'})
    return {v['id']: [int(v['statistics'].get(k, 0)) for k in ('viewCount', 'likeCount', 'commentCount')]
            for v in data.get('items', [])}


def gh(*args, body=None):
    return subprocess.run(['gh', *args], input=body, capture_output=True, text=True, check=True).stdout


def main():
    dry = '--dry' in sys.argv
    if not os.environ.get('YT_REFRESH_TOKEN'):
        print('ytlive: no YT_ secrets, nothing to do')
        return
    at = now()
    entries = []
    for name in ('reels.json', 'showcases.json'):
        if (ROOT / name).exists():
            entries += json.loads((ROOT / name).read_text())
    videos = recent(entries, at)
    number, state = None, {}
    if not dry:
        found = json.loads(gh('issue', 'list', '--state', 'open', '--search', f'"{TITLE}" in:title', '--json',
                              'number,title,body', '--limit', '5') or '[]')
        issue = next((i for i in found if i['title'] == TITLE), None)
        if issue:
            number = issue['number']
            m = STATE.search(issue.get('body') or '')
            state = json.loads(m.group(1)) if m else {}
    todo = [v for v in videos if due(v[2], state.get(v[0], []), at)]
    if not todo:
        print('ytlive: nothing due')
        return
    fresh = stats([v[0] for v in todo])
    keep = {v[0] for v in videos}
    state = {k: s for k, s in state.items() if k in keep}
    for vid, counts in fresh.items():
        state[vid] = (state.get(vid, []) + [[at.isoformat(timespec='minutes'), *counts]])[-KEEP:]
    text = table(videos, state, at) + f'\n<!-- ytlive {json.dumps(state, separators=(",", ":"))} -->\n'
    if dry:
        print(text)
    elif number:
        gh('issue', 'edit', str(number), '--body-file', '-', body=text)
    else:
        gh('issue', 'create', '--title', TITLE, '--body-file', '-', body=text)
    print(f'ytlive: {len(fresh)} Shorts read')


if __name__ == '__main__':
    main()
