"""Render the next unposted reel and publish it to Instagram.

Env:
  IG_TOKEN              Instagram User access token (Instagram API with Instagram Login)
  SUPABASE_URL          https://<ref>.supabase.co
  SUPABASE_SERVICE_KEY  legacy service_role key (JWT), used for Storage uploads
  DRY_RUN=true          render only, post nothing
  TRENDING=off          skip the trend scan and always write an evergreen reel for today's pillar
  POST_AT_UTC           when to post, HH:MM UTC (default 12:00); the job starts early to prepare the reel
  FORCE_POST=true       post even if a reel already went out today (UTC)
  CLAUDE_CODE_OAUTH_TOKEN, YOUTUBE_API_KEY   used by the trend scan, see trends.py
  VOICE_ENGINE, VOICE, VOICE_PITCH, FISH_API_KEY   voiceover settings, see voice.py; VOICE=none for sound effects only
  GRAPH_VERSION         optional, defaults to v25.0
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

import generate
import qa
import render
import trends
import voice

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
    # Storage requires a JWT in Authorization; new sb_secret_ keys are rejected there, so use the service_role key.
    return {'apikey': key, 'Authorization': f'Bearer {key}'}


def allow_type(content_type):
    """Add a MIME type to the bucket's allowed list (it was created for videos only)."""
    base, key = env('SUPABASE_URL').rstrip('/'), env('SUPABASE_SERVICE_KEY')
    bucket = check(requests.get(f'{base}/storage/v1/bucket/{BUCKET}', headers=storage_headers(key), timeout=30),
                   'read bucket settings')
    allowed = bucket.get('allowed_mime_types')
    if not allowed or content_type in allowed:
        return
    check(requests.put(f'{base}/storage/v1/bucket/{BUCKET}', headers=storage_headers(key), timeout=30,
                       json={'public': bucket.get('public', True), 'allowed_mime_types': allowed + [content_type],
                             'file_size_limit': bucket.get('file_size_limit')}), 'update bucket settings')
    print(f'Bucket now also accepts {content_type}')


def upload(path, name, content_type='video/mp4'):
    base, key = env('SUPABASE_URL').rstrip('/'), env('SUPABASE_SERVICE_KEY')

    def send():
        with open(path, 'rb') as f:
            return requests.post(
                f'{base}/storage/v1/object/{BUCKET}/{name}',
                headers={**storage_headers(key), 'Content-Type': content_type, 'x-upsert': 'true'},
                data=f, timeout=300,
            )
    resp = send()
    if not resp.ok and 'invalid_mime_type' in resp.text:
        allow_type(content_type)
        resp = send()
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


def publish_to_instagram(video_url, caption, thumb_ms, cover_url=None):
    token = env('IG_TOKEN')
    me = ig_get('me', token, fields='user_id,username')
    ig_id = me.get('user_id') or me.get('id')
    print(f"Posting as @{me.get('username')} ({ig_id})")

    # cover_url wins over thumb_offset when both are sent; the offset stays as the fallback.
    extra = {'cover_url': cover_url} if cover_url else {}
    container = ig_post(f'{ig_id}/media', token, media_type='REELS', video_url=video_url, caption=caption,
                        share_to_feed='true', thumb_offset=str(thumb_ms), **extra)
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


# ---------- visual review ----------

def check_visuals(reel, clips, path, slides, rounds=3):
    """Have Claude look at the rendered frames. A dishonest claim stops the post; a visual that fails is replaced
    by the point's next choice, or by its text, and the reel is rendered again."""
    shown = reel
    for _ in range(rounds):
        try:
            results = qa.review(path, shown, slides)
        except Exception as e:  # without a review, keep only visuals we draw ourselves; a page could be anything
            print(f'Visual review unavailable ({type(e).__name__}: {redact(str(e))[:200]}); dropping screenshots')
            results = [{'slide': i, 'ok': True, 'visual_ok': False, 'problem': 'not reviewed'}
                       for i, s in enumerate(slides) if s.visual and s.visual.spec.get('type') == 'screenshot']
        dishonest = [r for r in results if r.get('honest') is False]
        if dishonest:
            # Honesty is a hard line: better no post today than a misleading one.
            raise SystemExit('ERROR: the review found a dishonest claim, not posting: '
                             + '; '.join(f"slide {r['slide']}: {r['problem']}" for r in dishonest))
        rejected = {}
        for r in results:
            i = r['slide']
            if 1 <= i <= len(shown['points']) and slides[i].visual and not r['visual_ok']:
                rejected[i - 1] = slides[i].visual.spec
                print(f"Visual on slide {i} rejected: {r['problem']}")
            elif not r['ok']:
                print(f"Warning, slide {i}: {r['problem']}")
        if not rejected:
            print(f'Review passed: honest, {sum(bool(s.visual) for s in slides)} visuals fine')
            break
        # Rendered without the rejected choices; the queue keeps them so they can be fixed by hand.
        points = []
        for i, point in enumerate(shown['points']):
            choices = point.get('visual')
            choices = choices if isinstance(choices, list) else [choices] if choices else []
            if i in rejected:
                choices = [c for c in choices if c != rejected[i]]
            points.append({**{k: v for k, v in point.items() if k != 'visual'}, **({'visual': choices} if choices else {})})
        shown = {**shown, 'points': points}
        path, slides = render.render_reel(shown, voice=clips)
    return path, slides


# ---------- today's reel ----------

def todays_reel(reels):
    """Research today: a verified timely story if one is strong enough, else a fresh tip for today's pillar."""
    perf = []
    try:
        perf = trends.performance()
    except Exception as e:
        print(f'Could not read recent insights ({type(e).__name__})')
    if os.environ.get('TRENDING', 'on').strip().lower() != 'off':
        try:
            reel = trends.timely_reel(reels, perf)
            if reel:
                return reel
        except Exception as e:  # the trend scan is best effort; an evergreen tip is the safety net
            print(f'Trend scan failed ({type(e).__name__}: {redact(str(e))[:300]}), writing an evergreen reel')
    reel = generate.today(reels, perf)
    if not reel:
        raise SystemExit('ERROR: could not write a valid reel today.')
    return reel


def wait_for_post_time():
    """The job starts about an hour early to research and render; post at POST_AT_UTC (default 12:00)."""
    hh, mm = (int(x) for x in (os.environ.get('POST_AT_UTC', '').strip() or '12:00').split(':'))
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if 0 < wait < 2 * 3600:
        print(f'Ready early; waiting {wait / 60:.0f} minutes to post at {hh:02d}:{mm:02d} UTC')
        time.sleep(wait)


# ---------- main ----------

def main():
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    output('posted', 'false')
    reels = json.loads(render.QUEUE.read_text())
    today = datetime.now(timezone.utc).date().isoformat()
    if not dry and any((r.get('posted_at') or '').startswith(today) for r in reels) \
            and os.environ.get('FORCE_POST', '').strip().lower() not in ('1', 'true', 'yes'):
        print(f'Already posted today ({today} UTC); nothing to do. Set FORCE_POST=true to post again.')
        return
    # A reel added by hand goes first; otherwise today's reel is researched and written now, not ahead of time.
    reel = next((r for r in reels if not r.get('posted_at')), None)
    if reel:
        print('Using the reel added by hand')
    else:
        reel = todays_reel(reels)
        posted = [r for r in reels if r.get('posted_at')]
        reel = {'id': max((int(r['id']) for r in reels), default=0) + 1,
                'style': 'dark' if posted and posted[-1]['style'] == 'light' else 'light',
                **reel, 'posted_at': None, 'media_id': None}
        reels.append(reel)

    print(f"Next reel: #{reel['id']} {reel['hook']!r}")
    voice_name = os.environ.get('VOICE', '').strip() or None
    clips = None if voice_name == 'none' else voice.synthesize(voice.script(reel), voice_name)
    path, slides = render.render_reel(reel, voice=clips)
    path, slides = check_visuals(reel, clips, path, slides)
    # Cover is the last fully visible frame of the hook slide.
    thumb_ms = int((slides[0].end - render.EXIT - 0.05) * 1000)
    caption = f"{reel['caption'].strip()}\n\n{' '.join(reel['hashtags'])}"

    # The exact reel beside the video, so a dry run can be reviewed and then posted as is (add it to reels.json).
    path.with_suffix('.json').write_text(json.dumps({k: v for k, v in reel.items() if k not in ('posted_at', 'media_id')},
                                                    indent=2, ensure_ascii=False) + '\n')
    if dry:
        print(f'DRY_RUN: rendered {path}, thumb_offset={thumb_ms}ms. Nothing posted.')
        print(f'Caption preview:\n{caption}')
        return
    wait_for_post_time()

    name = f"reel-{reel['id']}-{int(time.time())}.mp4"
    cover = path.with_name(path.stem + '-cover.jpg')
    cover_name = name.replace('.mp4', '-cover.jpg') if cover.exists() else None
    try:
        url = upload(path, name)
        print(f'Uploaded to {url}')
        cover_url = None
        if cover_name:
            try:
                cover_url = upload(cover, cover_name, 'image/jpeg')
            except PublishError:  # a missing cover never blocks the post; the thumb_offset frame is used instead
                print('Cover upload failed; posting with the video frame as the cover')
                cover_name = None
        media_id = publish_to_instagram(url, caption, thumb_ms, cover_url)
    except PublishError as e:
        raise SystemExit(f'Publish failed: {e}')
    finally:
        delete_upload(name)
        if cover_name:
            delete_upload(cover_name)

    reel['posted_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    reel['media_id'] = media_id
    render.QUEUE.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')
    output('posted', 'true')
    output('reel_id', reel['id'])
    print(f"Published reel #{reel['id']} as media {media_id}")


if __name__ == '__main__':
    main()
