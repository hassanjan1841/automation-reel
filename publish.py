"""Render the next unposted reel and publish it to Instagram.

Env:
  IG_TOKEN              Instagram User access token (Instagram API with Instagram Login)
  SUPABASE_URL          https://<ref>.supabase.co
  SUPABASE_SERVICE_KEY  service role / secret key, used for Storage uploads
  DRY_RUN=true          render only, post nothing
  GRAPH_VERSION         optional, defaults to v25.0
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

import render

GRAPH = f"https://graph.instagram.com/{os.environ.get('GRAPH_VERSION', 'v25.0')}"
BUCKET = 'reels'
POLL_EVERY, POLL_LIMIT = 10, 600


class PublishError(Exception):
    pass


def secrets():
    return [v for v in (os.environ.get('IG_TOKEN'), os.environ.get('SUPABASE_SERVICE_KEY')) if v]


def redact(text):
    for s in secrets():
        text = text.replace(s, '***')
    return text


def check(resp, what):
    if resp.ok:
        return resp.json() if resp.content else {}
    try:
        body = json.dumps(resp.json(), indent=2)
    except ValueError:
        body = resp.text[:2000]
    print(f'ERROR during {what}: HTTP {resp.status_code}\n{redact(body)}', file=sys.stderr)
    raise PublishError(what)


def output(key, value):
    path = os.environ.get('GITHUB_OUTPUT')
    if path:
        with open(path, 'a') as f:
            f.write(f'{key}={value}\n')


def env(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise SystemExit(f'Missing env var {name}')
    return value


# ---------- Supabase Storage ----------

def storage_headers(key):
    headers = {'apikey': key}
    # New-format sb_secret_ keys are not JWTs; legacy service_role JWTs also go in Authorization.
    if not key.startswith('sb_'):
        headers['Authorization'] = f'Bearer {key}'
    return headers


def upload(path, name):
    base, key = env('SUPABASE_URL').rstrip('/'), env('SUPABASE_SERVICE_KEY')
    with open(path, 'rb') as f:
        resp = requests.post(
            f'{base}/storage/v1/object/{BUCKET}/{name}',
            headers={**storage_headers(key), 'Content-Type': 'video/mp4', 'x-upsert': 'true'},
            data=f, timeout=300,
        )
    check(resp, 'Supabase upload')
    url = f'{base}/storage/v1/object/public/{BUCKET}/{name}'
    head = requests.head(url, timeout=30)
    if not head.ok:
        print(f'ERROR: public URL returned HTTP {head.status_code}. Is the "{BUCKET}" bucket public?', file=sys.stderr)
        raise PublishError('public URL check')
    return url


def delete_upload(name):
    base, key = env('SUPABASE_URL').rstrip('/'), env('SUPABASE_SERVICE_KEY')
    resp = requests.delete(f'{base}/storage/v1/object/{BUCKET}/{name}', headers=storage_headers(key), timeout=60)
    if not resp.ok:
        print(f'Warning: could not delete {name} from storage (HTTP {resp.status_code})', file=sys.stderr)


# ---------- Instagram ----------

def ig_get(path, token, **params):
    return check(requests.get(f'{GRAPH}/{path}', params={**params, 'access_token': token}, timeout=60), f'GET {path}')


def ig_post(path, token, **data):
    return check(requests.post(f'{GRAPH}/{path}', data={**data, 'access_token': token}, timeout=120), f'POST {path}')


def publish_to_instagram(video_url, caption, thumb_ms):
    token = env('IG_TOKEN')
    me = ig_get('me', token, fields='user_id,username')
    ig_id = me.get('user_id') or me.get('id')
    print(f"Posting as @{me.get('username')} ({ig_id})")

    container = ig_post(f'{ig_id}/media', token, media_type='REELS', video_url=video_url, caption=caption,
                        share_to_feed='true', thumb_offset=str(thumb_ms))
    cid = container['id']
    print(f'Container {cid} created, waiting for Instagram to process the video')

    deadline = time.time() + POLL_LIMIT
    while True:
        info = ig_get(cid, token, fields='status_code,status')
        code = info.get('status_code')
        print(f'  status: {code}')
        if code == 'FINISHED':
            break
        if code in ('ERROR', 'EXPIRED'):
            print(f"ERROR: container {code}: {redact(info.get('status', ''))}", file=sys.stderr)
            raise PublishError(f'container {code}')
        if time.time() > deadline:
            raise PublishError('container not FINISHED after 10 minutes')
        time.sleep(POLL_EVERY)

    return ig_post(f'{ig_id}/media_publish', token, creation_id=cid)['id']


# ---------- main ----------

def main():
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    output('posted', 'false')
    reels = json.loads(render.QUEUE.read_text())
    reel = next((r for r in reels if not r.get('posted_at')), None)
    if reel is None:
        raise SystemExit('ERROR: no unposted reels left in reels.json. Run generate.py or add reels by hand.')

    print(f"Next reel: #{reel['id']} {reel['hook']!r}")
    path, slides = render.render_reel(reel)
    thumb_ms = int((slides[0].end - render.EXIT - 0.05) * 1000)
    caption = f"{reel['caption'].strip()}\n\n{' '.join(reel['hashtags'])}"

    if dry:
        print(f'DRY_RUN: rendered {path}, thumb_offset={thumb_ms}ms. Nothing posted.')
        print(f'Caption preview:\n{caption}')
        return

    name = f"reel-{reel['id']}-{int(time.time())}.mp4"
    try:
        url = upload(path, name)
        print(f'Uploaded to {url}')
        media_id = publish_to_instagram(url, caption, thumb_ms)
    except PublishError as e:
        raise SystemExit(f'Publish failed: {e}')
    finally:
        delete_upload(name)

    reel['posted_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    reel['media_id'] = media_id
    render.QUEUE.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')
    output('posted', 'true')
    output('reel_id', reel['id'])
    print(f"Published reel #{reel['id']} as media {media_id}")


if __name__ == '__main__':
    main()
