"""End-to-end run of the weekly learning loop with the real Claude CLI and a fake Instagram.

Four weeks of reels (three a day, under the running test, with a real effect: question hooks hold viewers better)
and a carousel are "posted", then learn.main runs every Sunday exactly as in the weekly job: real Claude writes the
rules and the report, extracts comment topics and looks at real cover images. Everything is written to a temp
folder; the repo's own files are never touched. Needs the claude CLI logged in; no Instagram, no network otherwise.

Usage: .venv/bin/python tests/e2e_learn.py [weeks]     prints each report, exit 1 if a check fails
"""

import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

import dm  # noqa: E402
import generate  # noqa: E402
import history  # noqa: E402
import learn  # noqa: E402
import render  # noqa: E402

HOOKS = ['Why your cache keeps serving stale data', 'Stop leaking API keys in your repo', 'Your useEffect runs twice on purpose',
         'Ship a Stripe webhook in one afternoon', 'The Postgres index you forgot to add', 'Client wants it done by Friday',
         'Rate limit your API in 2 minutes', 'Supabase RLS in plain English']
COMMENTS = ['Can you do a video on Supabase auth with Next.js?', 'please cover rate limiting with redis', 'MCP',
            'how do I set up row level security for teams?', 'great one', 'Next: Stripe subscriptions please']


def cover(text, dark):
    img = Image.new('RGB', (540, 960), (18, 20, 28) if dark else (245, 240, 230))
    d = ImageDraw.Draw(img)
    d.multiline_text((40, 380), '\n'.join(text[i:i + 18] for i in range(0, len(text), 18)),
                     fill=(250, 250, 250) if dark else (20, 20, 20), spacing=12,
                     font=render.font('Bold', 44) if (render.FONT_DIR / 'Poppins-Bold.ttf').exists() else None)
    out = BytesIO()
    img.save(out, 'JPEG')
    return out.getvalue()


def main():
    weeks = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    tmp = Path(tempfile.mkdtemp(prefix='e2e-learn-'))
    patches = [mock.patch.object(history, n, tmp / f) for n, f in (
        ('METRICS', 'metrics'), ('RULES', 'rules.json'), ('EXPERIMENTS', 'experiments.json'), ('IDEAS', 'ideas.json'),
        ('REPORTS', 'reports'), ('LEARNINGS', 'learnings.md'))]
    patches += [mock.patch.object(render, 'QUEUE', tmp / 'reels.json'), mock.patch.object(learn, 'CAROUSELS', tmp / 'carousels.json'),
                mock.patch.object(learn, 'REPORT', tmp / 'out' / 'report.md')]
    for p in patches:
        p.start()
    (tmp / 'learnings.md').write_text((render.ROOT / 'learnings.md').read_text())
    history.save_experiments({'active': {'name': 'hook_style', 'since': '2026-10-05'}, 'done': []})

    start = datetime(2026, 10, 5, tzinfo=timezone.utc)
    reels, carousels, by_media, now = [], [], {}, [start]

    def metric(media, name):
        r = by_media[media]
        age = (now[0] - datetime.fromisoformat(r['posted_at'])).total_seconds() / 86400
        rnd = random.Random(f'{media}-{name}')
        arm = (r.get('test') or {}).get('arm')
        effect = {'question': -6, 'statement': 4}.get(arm, 0) + (3 if r.get('slot') == 3 else 0)
        return {'views': round(150 + 25 * min(age, 30) + rnd.uniform(-20, 20)), 'reach': 140, 'likes': rnd.randint(2, 9),
                'comments': rnd.randint(0, 4), 'saved': rnd.randint(0, 5), 'shares': rnd.randint(0, 3),
                'reels_skip_rate': round(78 + effect + rnd.uniform(-2, 2), 1),
                'ig_reels_avg_watch_time': round((5.5 - effect / 4 + rnd.uniform(-0.8, 0.8)) * 1000),
                'profile_visits': rnd.randint(0, 6)}.get(name)

    def fake_get(url, params=None, timeout=None):
        from types import SimpleNamespace
        if url.startswith('https://cdn.example/'):
            media = url.rsplit('/', 1)[1].removesuffix('.jpg')
            return SimpleNamespace(ok=True, content=cover(by_media[media]['hook'], by_media[media]['id'] % 2 == 0))
        media = url.split('/')[4]
        if url.endswith('/insights'):
            if params['metric'] == 'follows':
                return SimpleNamespace(ok=False, json=lambda: {'error': {'message': 'unsupported'}})
            value = metric(media, params['metric'])
            return SimpleNamespace(ok=True, json=lambda: {'data': [{'values': [{'value': value}]}]} if value is not None else {'data': []})
        return SimpleNamespace(ok=True, json=lambda: {'thumbnail_url': f'https://cdn.example/{media}.jpg'})

    failures = []
    for day in range(weeks * 7):
        when = start + timedelta(days=day)
        now[0] = when + timedelta(hours=10)
        if when.weekday() == 6:
            render.QUEUE.write_text(json.dumps(reels))
            learn.CAROUSELS.write_text(json.dumps(carousels))
            with mock.patch.object(learn, 'utcnow', return_value=now[0]), mock.patch.object(learn.requests, 'get', fake_get), \
                    mock.patch.object(dm, 'comments', lambda media, token: [{'text': c} for c in COMMENTS]), \
                    mock.patch.dict(os.environ, {'IG_TOKEN': 'fake'}):
                learn.main()
            text = (tmp / 'out' / 'report.md').read_text() if (tmp / 'out' / 'report.md').exists() else ''
            for heading in ('## Summary', '## One decision for you', "## This week's test", '## Rules'):
                if heading not in text:
                    failures.append(f'{when.date()}: report has no {heading}')
            if 'write-up was unavailable' in text:
                failures.append(f'{when.date()}: the real Claude write-up failed')
        for slot, hour in ((1, 12), (2, 16), (3, 20)):
            os.environ['SLOT'] = str(slot)
            test = generate.experiment_today(when.date())
            n = len(reels) + 1
            r = {'id': n, 'hook': HOOKS[n % len(HOOKS)] + ('?' if test and test['arm'] == 'question' else ''),
                 'pillar': 'concept', 'series': 'Explained', 'points': [{'title': 't', 'body': 'b'}] * 3,
                 'posted_at': when.replace(hour=hour).isoformat(), 'media_id': f'm{n}', 'slot': slot, 'seconds': 21.0,
                 'shown': ['text', 'code', 'text', 'terminal', 'text'], **({'test': test} if test else {}),
                 **({'dm_keyword': 'MCP'} if n % 5 == 0 else {})}
            reels.append(r)
            by_media[r['media_id']] = r
        if when.weekday() == 6:
            carousels.append({'title': f'Cheat sheet {day}', 'media_id': f'c{day}', 'posted_at': (when + timedelta(hours=11)).isoformat()})
            by_media[f'c{day}'] = {'id': day, 'hook': 'Cheat sheet', 'posted_at': carousels[-1]['posted_at']}

    rules = history.rules()
    print(f'\nFiles in {tmp}:')
    for p in sorted(tmp.rglob('*')):
        if p.is_file():
            print('  ', p.relative_to(tmp))
    print('\nRules:', json.dumps([{k: r[k] for k in ('text', 'status', 'source', 'verdict')} for r in rules], indent=1))
    print('Test:', json.dumps(history.experiments(), indent=1))
    print('Ideas:', history.ideas())
    for r in rules:
        if r['source'] == 'weekly' and not r['evidence']:
            failures.append(f"rule without evidence reached the writer: {r['text']}")
        if learn.HARD_RULES.search(r['text']) and r['source'] != 'imported':
            failures.append(f"rule touching the hard rules: {r['text']}")
    if not history.ideas():
        failures.append('no topic ideas from the comments')
    for p in reversed(patches):
        p.stop()
    print('\n' + ('\n'.join('FAIL ' + f for f in failures) if failures else 'e2e learn: all checks passed'))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
