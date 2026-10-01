"""Comment-to-DM: when someone comments a post's keyword ("Comment MCP for the setup"), send them the guide that
post promised as a private reply, then answer the comment publicly ("Sent you a DM"). That public answer is also
the record: a comment we already answered is never sent twice, so no state is stored anywhere.

Posts are the reels (reels.json) and carousels (carousels.json) that have a dm_keyword and dm_guide, posted in
the last PRIVATE_REPLY_DAYS days (Instagram only allows a private reply to a comment for 7 days).

Env: IG_TOKEN (needs instagram_business_manage_comments and instagram_business_manage_messages); DRY_RUN=true
prints what it would send and sends nothing; GRAPH_VERSION (optional, defaults to v25.0).
Usage: python dm.py            answer new keyword comments
       python dm.py --check    only check the token can read comments and read conversations (messaging access)
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

import render

GRAPH = f"https://graph.instagram.com/{os.environ.get('GRAPH_VERSION') or 'v25.0'}"
PRIVATE_REPLY_DAYS = 7
PUBLIC_REPLY = 'Sent you a DM 📩'
GUIDE_LIMIT = 1000  # Instagram's text message limit; one private reply per comment, so the guide fits in one


class DMError(Exception):
    pass


def call(method, path, token, **params):
    resp = requests.request(method, f'{GRAPH}/{path}', timeout=60,
                            **({'params': {**params, 'access_token': token}} if method == 'GET'
                               else {'json': params, 'headers': {'Authorization': f'Bearer {token}'}}))
    if not resp.ok:
        try:
            message = resp.json().get('error', {}).get('message', '')
        except ValueError:
            message = resp.text[:300]
        raise DMError(f'{method} {path}: HTTP {resp.status_code} {message}'.replace(token, '***'))
    return resp.json() if resp.content else {}


def posts():
    """Recent posts with a keyword: [(media_id, keyword, guide, label)]."""
    since = datetime.now(timezone.utc) - timedelta(days=PRIVATE_REPLY_DAYS)
    found = []
    for path in (render.QUEUE, render.ROOT / 'carousels.json'):
        entries = json.loads(path.read_text()) if path.exists() else []
        for e in entries if isinstance(entries, list) else [entries]:
            if e.get('media_id') and e.get('dm_keyword') and e.get('dm_guide') and e.get('posted_at') \
                    and datetime.fromisoformat(e['posted_at']) > since:
                found.append((e['media_id'], e['dm_keyword'], e['dm_guide'], e.get('hook') or e.get('title', '')))
    return found


def asks(text, keyword):
    """Whether a comment asks for the guide: the keyword as its own word, any case ("mcp please", "MCP!")."""
    return re.search(rf'(?<![A-Za-z0-9]){re.escape(keyword)}s?(?![A-Za-z0-9])', text or '', re.I) is not None


def comments(media_id, token):
    """Every top-level comment with who wrote it and who has answered it, following pages."""
    out, after = [], None
    while True:
        page = call('GET', f'{media_id}/comments', token, fields='id,text,from{id,username},replies{from{id}}',
                    limit=50, **({'after': after} if after else {}))
        out += page.get('data', [])
        after = page.get('paging', {}).get('cursors', {}).get('after')
        if not page.get('paging', {}).get('next'):
            return out


def answer(media_id, keyword, guide, me, token, dry):
    """Send the guide to every new keyword comment on one post. Returns how many were sent."""
    sent = 0
    for c in comments(media_id, token):
        author = (c.get('from') or {}).get('id')
        answered = any((r.get('from') or {}).get('id') == me for r in (c.get('replies') or {}).get('data', []))
        if author == me or answered or not asks(c.get('text'), keyword):
            continue
        who = (c.get('from') or {}).get('username', '?')
        if dry:
            print(f'  DRY_RUN: would DM @{who} the {keyword} guide')
            continue
        call('POST', f'{me}/messages', token, recipient={'comment_id': c['id']}, message={'text': guide})
        call('POST', f"{c['id']}/replies", token, message=PUBLIC_REPLY)
        print(f'  sent the {keyword} guide to @{who}')
        sent += 1
    return sent


def main():
    token = os.environ.get('IG_TOKEN', '').strip()
    if not token:
        raise SystemExit('Missing env var IG_TOKEN')
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    me = call('GET', 'me', token, fields='user_id,username')
    my_id = me.get('user_id') or me.get('id')
    if '--check' in sys.argv:
        media = call('GET', 'me/media', token, fields='id', limit=1).get('data', [])
        if media:
            comments(media[0]['id'], token)
            print('comments: readable')
        call('GET', 'me/conversations', token, platform='instagram')
        print('messages: allowed')
        return
    todo = posts()
    print(f'{len(todo)} recent posts with a DM keyword')
    failed = False
    for media_id, keyword, guide, label in todo:
        try:
            n = answer(media_id, keyword, guide[:GUIDE_LIMIT], my_id, token, dry)
            if n:
                print(f'{label!r}: {n} sent')
        except DMError as e:  # one post failing (deleted, rate limit) must not stop the others
            print(f'{label!r}: {e}', file=sys.stderr)
            failed = True
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
