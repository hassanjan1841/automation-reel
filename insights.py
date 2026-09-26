"""Print Instagram insights for the account and every recent reel, straight from the Instagram API.

Env: IG_TOKEN
Usage: python insights.py [limit]
"""

import os
import sys

import requests

GRAPH = f"https://graph.instagram.com/{os.environ.get('GRAPH_VERSION', 'v25.0')}"
REEL_METRICS = ['views', 'reach', 'reels_skip_rate', 'ig_reels_avg_watch_time', 'likes', 'comments', 'saved',
                'shares', 'total_interactions']


def get(path, token, **params):
    resp = requests.get(f'{GRAPH}/{path}', params={**params, 'access_token': token}, timeout=60)
    body = resp.json() if resp.content else {}
    if not resp.ok:
        raise RuntimeError(str(body.get('error', body).get('message', body))[:300].replace(token, '***'))
    return body


def metric(media_id, name, token):
    # One call per metric: a single unsupported metric fails the whole request otherwise.
    try:
        data = get(f'{media_id}/insights', token, metric=name).get('data', [])
        return data[0]['values'][0]['value'] if data else None
    except RuntimeError as e:
        return f'error: {e}'


def main():
    token = os.environ['IG_TOKEN'].strip()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    me = get('me', token, fields='user_id,username,followers_count,follows_count,media_count')
    print(f"@{me.get('username')}: {me.get('followers_count')} followers, {me.get('follows_count')} following, "
          f"{me.get('media_count')} posts\n")

    media = get('me/media', token, fields='id,caption,media_product_type,timestamp,permalink', limit=min(limit, 100))['data']
    print('date        type    views reach skip%  watch  likes cmts saves shares  permalink  caption')
    for m in media:
        s = {name: metric(m['id'], name, token) for name in REEL_METRICS}
        s = {k: (v if isinstance(v, (int, float)) else '-') for k, v in s.items()}
        watch = f"{s['ig_reels_avg_watch_time'] / 1000:.1f}s" if s['ig_reels_avg_watch_time'] != '-' else '-'
        caption = ((m.get('caption') or '').splitlines() or [''])[0][:70]
        print(f"{m['timestamp'][:10]}  {(m.get('media_product_type') or '')[:6]:6} {s['views']:>6} {s['reach']:>5} "
              f"{s['reels_skip_rate']:>5} {watch:>6} {s['likes']:>6} {s['comments']:>4} {s['saved']:>5} "
              f"{s['shares']:>6}  {m.get('permalink', '')}  {caption}")


if __name__ == '__main__':
    main()
