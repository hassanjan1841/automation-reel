"""End-to-end run of the daily post with a real render: publish.main on a temp copy of reels.json with a test reel
that has a 3D hook word, a 3D diagram and a screenshot, then checks what was recorded (shown, slot, seconds, test).

Real: rendering (Pillow, ffmpeg, three.js in Chromium), check_visuals, publish.main's bookkeeping, and with
--real-review Claude's frame review. Faked: the upload and Instagram (never posts), and the voice unless --voice
(a silent voice with even word times, so captions and visuals run as with a real one).

Usage: .venv/bin/python tests/e2e_publish.py [--reject] [--real-review] [--voice] [--test name:arm]
  --reject        the (fake) review rejects the first point's visual once, so the re-render path runs
  --real-review   Claude reviews the frames (needs the claude CLI)
  --voice         the real voice (Fish or Kokoro, needs their key or model)
Env for sandboxes without the CDN: E2E_THREE=<folder holding three@0.170.0> serves three.js locally,
E2E_CHROMIUM=<path to chrome> overrides the browser Playwright launches.
"""

import functools
import http.server
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import generate  # noqa: E402
import publish  # noqa: E402
import qa  # noqa: E402
import render  # noqa: E402
import scene3d  # noqa: E402
import voice  # noqa: E402

REEL = {
    'pillar': 'concept', 'series': 'Explained', 'episode': 1, 'style': 'dark', 'kicker': 'Explained #1',
    'payoff': 'Delete the cached key on every write so readers never get the old row',
    'hook': 'Your *cache* serves old data', 'hook_type': 'problem',
    'hook_visual': {'type': 'diff', 'language': 'ts', 'title': 'save.ts',
                    'before': 'await db.update(user)\n// cache keeps the old user', 'after': 'await db.update(user)\nawait cache.del(key)'},
    'alternatives': [
        {'hook': 'Your *cache* hides every profile update', 'hook_type': 'mistake',
         'spoken': '[urgent] You saved the new profile, [exasperated] but your cache still serves the old one.'},
        {'hook': 'One line stops *stale* cache reads', 'hook_type': 'shortcut',
         'spoken': '[fired up] One delete call after each write, [confident] and stale reads are gone.'},
        {'hook': 'Old data after every *update*', 'hook_type': 'before_after',
         'spoken': '[mock outraged] You update the row, [deadpan] the page still shows the old value.'}],
    'points': [
        {'title': 'Reads hit cache', 'body': 'The app asks the cache before the database.',
         'visual': [{'type': 'flow', 'nodes': [{'id': 'app', 'label': 'App', 'kind': 'client'},
                                               {'id': 'cache', 'label': 'Cache', 'kind': 'cache'},
                                               {'id': 'db', 'label': 'Database', 'kind': 'db'}],
                     'hops': [{'from': 'app', 'to': 'cache', 'label': 'read'}, {'from': 'cache', 'to': 'db', 'label': 'miss'},
                              {'from': 'db', 'to': 'cache', 'label': 'row'}, {'from': 'cache', 'to': 'app'}]},
                    {'type': 'diagram', 'nodes': [{'id': 'app', 'label': 'App', 'kind': 'client'},
                                                  {'id': 'cache', 'label': 'Cache', 'kind': 'cache'},
                                                  {'id': 'db', 'label': 'Database', 'kind': 'db'}],
                     'edges': [{'from': 'app', 'to': 'cache'}, {'from': 'cache', 'to': 'db'}],
                     'flow': ['app>cache', 'cache>db', 'db>cache', 'cache>app']},
                    {'type': 'code', 'language': 'ts', 'title': 'read.ts',
                     'code': 'const hit = await cache.get(key)\nif (hit) return hit', 'highlight': [1]}]},
        {'title': 'Writes skip cache', 'body': 'Updates go straight to the database only.',
         'visual': [{'type': 'code', 'language': 'ts', 'title': 'write.ts',
                     'code': 'await db.update(user)\n// cache still has the old user', 'highlight': [2]}]},
        {'title': 'Delete the key', 'body': 'Clear the cached key on every write.',
         'visual': [{'type': 'screenshot', 'url': 'https://redis.io/docs/latest/commands/del/', 'find': 'Removes the specified keys'},
                    {'type': 'terminal', 'commands': ['redis-cli DEL user:42']}]},
    ],
    'cta': 'Do you *invalidate* on write or wait for expiry?',
    'caption': 'Why a cache serves stale data after an update.\nReads use the cache, writes skip it.\nHow do you invalidate yours? 👇',
    'hashtags': ['#webdev', '#redis', '#backend'],
    'voiceover': ['[fired up] Users update a profile, [puzzled] the app shows the old one.',
                  '[explaining] Reads check the cache first, [confident] only a miss hits the database.',
                  '[building tension] A write updates the database, [knowing] nobody tells the cache.',
                  '[punchy] The fix is small. [warm] Delete that key on every write.',
                  '[curious] So tell me, [grinning] do you clear keys or wait?'],
    'posted_at': None, 'media_id': None,
}


def silent_voice(lines, voice_name=None, check=True):
    clips, words = [], []
    for line in lines:
        ws = voice.strip_cues(line).split()
        words.append([(w, 0.1 + i * 0.38, 0.43 + i * 0.38) for i, w in enumerate(ws)])
        clips.append(np.zeros(int(render.SR * (0.3 + len(ws) * 0.38)), dtype=np.float32))
    v = voice.Voiceover(clips, words, continuous=True)
    v.verdict = 'clean'
    return v


def serve_three(folder):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            super().end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=folder))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    scene3d.THREE = f'http://127.0.0.1:{srv.server_address[1]}/three@0.170.0'


def main():
    args = sys.argv[1:]
    if os.environ.get('E2E_THREE'):
        serve_three(os.environ['E2E_THREE'])
    if os.environ.get('E2E_CHROMIUM'):
        from playwright.sync_api._generated import BrowserType
        launch = BrowserType.launch
        BrowserType.launch = lambda self, **k: launch(self, **{'executable_path': os.environ['E2E_CHROMIUM'], **k})
    reel = dict(REEL)
    if '--test' in args:
        name, arm = args[args.index('--test') + 1].split(':')
        reel['test'] = {'name': name, 'arm': arm}
    errors = generate.validate(reel)
    if errors:
        raise SystemExit(f'test reel is invalid: {errors}')

    tmp = Path(tempfile.mkdtemp(prefix='e2e-publish-'))
    queue = tmp / 'reels.json'
    reels = json.loads(render.QUEUE.read_text())
    reels.append({'id': max(r['id'] for r in reels) + 1, **reel})
    queue.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')

    reviews = []
    real_review = qa.review

    def review(path, shown_reel, slides, voiceover=None):
        types = [s.visual.spec.get('type') if s.visual else None for s in slides]
        reviews.append(types)
        print(f'  review {len(reviews)} sees: {types}')
        if '--real-review' in args:
            return real_review(path, shown_reel, slides, voiceover)
        out = [{'slide': i, 'ok': True, 'visual_ok': True, 'honest': True, 'problem': ''} for i in range(len(slides))]
        if '--reject' in args and len(reviews) == 1 and types[1]:
            out[1].update(visual_ok=False, problem='e2e: reject the first point visual')
        return {'slides': out, 'first_frame': {'ok': True, 'problem': ''}, 'payoff': {'ok': True, 'problem': ''}}

    patches = [mock.patch.object(render, 'QUEUE', queue), mock.patch.object(qa, 'review', review),
               mock.patch.object(publish, 'upload', lambda path, name, *a, **k: f'https://example.invalid/{name}'),
               mock.patch.object(publish, 'delete_upload', lambda name: None),
               mock.patch.object(publish, 'wait_for_post_time', lambda: None),
               mock.patch.object(publish, 'publish_to_instagram', lambda *a, **k: 'e2e-media-id'),
               mock.patch.dict(os.environ, {'DRY_RUN': '', 'FORCE_POST': 'true', 'VOICE': os.environ.get('VOICE', 'e2e')})]
    if '--voice' not in args:
        patches.append(mock.patch.object(voice, 'synthesize', silent_voice))
    for p in patches:
        p.start()
    try:
        publish.main()
    finally:
        for p in reversed(patches):
            p.stop()

    posted = json.loads(queue.read_text())[-1]
    last = reviews[-1]
    checks = {
        'posted': posted.get('media_id') == 'e2e-media-id' and bool(posted.get('posted_at')),
        'shown matches the last reviewed render': posted.get('shown') == [t or 'text' for t in last],
        'slot recorded': posted.get('slot') == generate.slot(),
        'seconds recorded': isinstance(posted.get('seconds'), float) and 10 < posted['seconds'] < 40,
        'test kept': posted.get('test') == reel.get('test'),
        'still valid': generate.validate(posted) == [],
        'queue keeps every choice': posted['points'] == reel['points'],
        'hook proof under the hook': reviews[0][0] == reel['hook_visual']['type'],
        'animation on point 1': '--reject' in args or reviews[0][1] == 'flow',
        'review recorded': 'first_frame' in (posted.get('review') or {}),
        'reject path re-rendered': '--reject' not in args or (len(reviews) >= 2 and reviews[0][1] != reviews[1][1]),
    }
    print(json.dumps({k: posted.get(k) for k in ('shown', 'slot', 'seconds', 'test')}))
    for name, ok in checks.items():
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    print(f'video: {render.OUT_DIR}/reel-{posted["id"]}.mp4')
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == '__main__':
    main()
