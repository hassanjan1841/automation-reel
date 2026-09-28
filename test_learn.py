"""Offline tests for the learning loop and what feeds it: history.py storage, the weekly test in generate.py, the
news writer's use of it, trends.performance's fallback, what publish.py records, every step of learn.py, the
weekly workflow's commit step, and a six-week simulation of the whole loop against a fake Instagram and a fake
Claude. No network, no Claude, no Instagram; runs with only requests, pillow and numpy installed (like CI).

Usage: python test_learn.py        runs everything, exit 1 on any failure
       python test_learn.py -v     one line per test
"""

import contextlib
import copy
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dm
import generate
import history
import learn
import publish
import render
import trends

ROOT = Path(__file__).resolve().parent

# A reel that passes generate.validate: a statement hook, 49 spoken words.
VALID = {
    'pillar': 'concept', 'series': 'Explained', 'episode': 1, 'style': 'dark', 'kicker': 'Explained #1',
    'hook': 'Why your *cache* keeps serving stale data',
    'points': [
        {'title': 'Reads hit cache first', 'body': 'The app asks the cache before the database.',
         'visual': [{'type': 'code', 'language': 'ts', 'title': 'read.ts',
                     'code': 'const hit = await cache.get(key)\nif (hit) return hit', 'highlight': [1]}]},
        {'title': 'Writes skip the cache', 'body': 'Updates go straight to the database only.',
         'visual': [{'type': 'code', 'language': 'ts', 'title': 'write.ts',
                     'code': 'await db.update(user)\n// cache still has the old user', 'highlight': [2]}]},
        {'title': 'Delete the key', 'body': 'Clear the cached key on every write.',
         'visual': [{'type': 'terminal', 'commands': ['redis-cli DEL user:42']}]},
    ],
    'cta': 'Do you *invalidate* on write or wait for expiry?',
    'caption': 'Why a cache serves stale data after an update.\nReads use the cache, writes skip it.\nHow do you invalidate yours? 👇',
    'hashtags': ['#webdev', '#redis', '#backend'],
    'voiceover': ['[fired up] Users update a profile, [puzzled] the app shows the old one.',
                  '[explaining] Reads check the cache first, [confident] only a miss hits the database.',
                  '[building tension] A write updates the database, [knowing] nobody tells the cache.',
                  '[punchy] The fix is small. [warm] Delete that key on every write.',
                  '[curious] So tell me, [grinning] do you clear keys or wait?'],
}
QUESTION_HOOK = 'Why does your *cache* serve stale data?'


class Sandbox(unittest.TestCase):
    """Every test gets its own copy of the data files in a temp folder and a clean environment."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(history, 'METRICS', self.tmp / 'metrics'),
            mock.patch.object(history, 'RULES', self.tmp / 'rules.json'),
            mock.patch.object(history, 'EXPERIMENTS', self.tmp / 'experiments.json'),
            mock.patch.object(history, 'IDEAS', self.tmp / 'ideas.json'),
            mock.patch.object(history, 'REPORTS', self.tmp / 'reports'),
            mock.patch.object(history, 'LEARNINGS', self.tmp / 'learnings.md'),
            mock.patch.object(render, 'QUEUE', self.tmp / 'reels.json'),
            mock.patch.object(learn, 'CAROUSELS', self.tmp / 'carousels.json'),
            mock.patch.object(learn, 'REPORT', self.tmp / 'out' / 'report.md'),
            mock.patch.dict(os.environ, {'EXPERIMENT': '', 'SLOT': '', 'THREE_D': '', 'DRY_RUN': '',
                                         'FORCE_POST': '', 'REEL_FORMAT': ''}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()


# ---------- history.py ----------

class HistoryTest(Sandbox):
    def test_snapshots_append_by_month_and_never_rewrite(self):
        history.append_snapshots([{'date': '2026-09-30', 'kind': 'reel', 'id': 1, 'age_days': 3, 'views': 10}])
        first = (self.tmp / 'metrics' / '2026-09.jsonl').read_text()
        history.append_snapshots([{'date': '2026-10-04', 'kind': 'reel', 'id': 1, 'age_days': 7, 'views': 20},
                                  {'date': '2026-09-30', 'kind': 'carousel', 'id': 'm9', 'age_days': 3, 'views': 5}])
        self.assertTrue((self.tmp / 'metrics' / '2026-09.jsonl').read_text().startswith(first))
        self.assertEqual(len((self.tmp / 'metrics' / '2026-09.jsonl').read_text().splitlines()), 2)
        self.assertEqual(sorted(p.name for p in (self.tmp / 'metrics').iterdir()), ['2026-09.jsonl', '2026-10.jsonl'])
        rows = history.snapshots()
        self.assertEqual([r['date'] for r in rows], ['2026-09-30', '2026-09-30', '2026-10-04'])
        posts = history.by_post(rows)
        self.assertEqual([s['views'] for s in posts['reel:1']], [10, 20])
        self.assertEqual(history.value_at(posts['reel:1'], 'views', 7), 20)
        self.assertIsNone(history.value_at(posts['reel:1'], 'views', 8))
        self.assertFalse(history.settled(posts['reel:1']))
        self.assertTrue(history.settled([{'age_days': history.SETTLED_DAYS}]))

    def test_rules_and_learnings(self):
        rules = [{'id': 1, 'text': 'A', 'status': 'trial'}, {'id': 2, 'text': 'B', 'status': 'kept'},
                 {'id': 3, 'text': 'C', 'status': 'retired'}]
        history.save_rules(rules)
        self.assertEqual(json.loads((self.tmp / 'rules.json').read_text()), rules)
        text = (self.tmp / 'learnings.md').read_text()
        self.assertEqual(text, '# What holds our viewers (updated weekly by learn.py)\n\n- B (proven)\n- A\n')
        self.assertEqual(generate.learned.__doc__ is not None, True)

    def test_import_current_learnings(self):
        (self.tmp / 'learnings.md').write_text((ROOT / 'learnings.md').read_text())
        rules = history.import_learnings('2026-10-04')
        bullets = [l for l in (ROOT / 'learnings.md').read_text().splitlines() if l.startswith('- ')]
        self.assertEqual(len(rules), len(bullets))
        self.assertTrue(all(r['status'] == 'trial' and r['since'] == '2026-10-04' for r in rules))
        self.assertEqual(len({r['id'] for r in rules}), len(rules))

    def test_reports(self):
        self.assertEqual(history.week_name(date(2026, 10, 4)), '2026-W40')
        history.save_report(date(2026, 9, 27), 'old')
        history.save_report(date(2026, 10, 4), 'new')
        self.assertEqual(history.last_report(date(2026, 10, 4)), 'old\n')
        self.assertEqual(history.last_report(date(2026, 9, 27)), '')

    def test_defaults_without_files(self):
        self.assertEqual(history.rules(), [])
        self.assertEqual(history.experiments(), {'active': None, 'done': []})
        self.assertEqual(history.ideas(), [])
        (self.tmp / 'rules.json').write_text('not json')
        self.assertEqual(history.rules(), [])


# ---------- the weekly test, writer side ----------

class ExperimentTest(Sandbox):
    def start(self, name):
        history.save_experiments({'active': {'name': name, 'since': '2026-10-04'}, 'done': []})

    def test_no_test_without_active_or_when_off(self):
        self.assertIsNone(generate.experiment_today(date(2026, 10, 5)))
        self.start('hook_style')
        self.assertIsNotNone(generate.experiment_today(date(2026, 10, 5)))
        os.environ['EXPERIMENT'] = 'off'
        self.assertIsNone(generate.experiment_today(date(2026, 10, 5)))
        self.assertEqual(generate.experiment_note(), '')
        os.environ['EXPERIMENT'] = 'length'
        self.assertEqual(generate.experiment_today(date(2026, 10, 5))['name'], 'length')

    def test_unknown_active_test_is_ignored(self):
        self.start('no_such_test')
        self.assertIsNone(generate.experiment_today(date(2026, 10, 5)))

    def test_arm_fixed_per_date_and_slot_and_balanced(self):
        self.start('hook_style')
        day = date(2026, 10, 5)
        self.assertEqual(generate.experiment_today(day), generate.experiment_today(day))
        arms = []
        for s in ('1', '2', '3'):
            os.environ['SLOT'] = s
            arms += [generate.experiment_today(day + timedelta(days=i))['arm'] for i in range(200)]
        share = arms.count('question') / len(arms)
        self.assertTrue(0.4 < share < 0.6, share)
        os.environ['SLOT'] = '1'
        by_slot1 = [generate.experiment_today(day + timedelta(days=i))['arm'] for i in range(30)]
        os.environ['SLOT'] = '2'
        by_slot2 = [generate.experiment_today(day + timedelta(days=i))['arm'] for i in range(30)]
        self.assertNotEqual(by_slot1, by_slot2)

    def test_every_arm_checks(self):
        reel = copy.deepcopy(VALID)
        cases = {('hook_style', 'question'): ({'hook': QUESTION_HOOK}, {}),
                 ('hook_style', 'statement'): ({}, {'hook': QUESTION_HOOK}),
                 ('hook_number', 'number'): ({'hook': 'Fix a stale *cache* in 2 minutes'}, {}),
                 ('hook_number', 'no_number'): ({}, {'hook': 'Fix a stale *cache* in 2 minutes'})}
        for (name, arm), (good, bad) in cases.items():
            self.assertEqual(generate.experiment_errors({**reel, **good, 'test': {'name': name, 'arm': arm}}), [], (name, arm))
            self.assertEqual(len(generate.experiment_errors({**reel, **bad, 'test': {'name': name, 'arm': arm}})), 1, (name, arm))
        self.assertEqual(generate.vo_words(reel), 49)
        self.assertEqual(generate.experiment_errors({**reel, 'test': {'name': 'length', 'arm': 'long'}}), [])
        self.assertEqual(len(generate.experiment_errors({**reel, 'test': {'name': 'length', 'arm': 'short'}})), 1)
        self.assertEqual(generate.experiment_errors({**reel, 'test': {'name': 'gone', 'arm': 'x'}}), [])
        self.assertTrue(generate.NUMBER.search('in two minutes'))
        self.assertFalse(generate.NUMBER.search('someone always forgets this'))

    def test_validate_holds_the_reel_to_its_test(self):
        self.assertEqual(generate.validate(VALID), [])
        errors = generate.validate({**VALID, 'test': {'name': 'hook_style', 'arm': 'question'}})
        self.assertEqual(errors, ['the hook must end with "?" (a question) (this week\'s test)'])
        self.assertEqual(generate.validate({**VALID, 'hook': QUESTION_HOOK, 'test': {'name': 'hook_style', 'arm': 'question'}}), [])

    def test_note_names_the_arm(self):
        self.start('hook_style')
        test = generate.experiment_today()
        self.assertIn(generate.EXPERIMENTS['hook_style'][test['arm']][0], generate.experiment_note())

    def test_generate_attaches_the_test_and_repairs_a_miss(self):
        def ask(todo, hooks, feedback, context):
            return [copy.deepcopy(VALID)]
        fixed = {**copy.deepcopy(VALID), 'hook': QUESTION_HOOK}
        out = SimpleNamespace(returncode=0, stdout=json.dumps({'structured_output': {'reels': [fixed]}}), stderr='')
        with mock.patch.object(generate, 'ask_claude', ask), mock.patch.object(generate.subprocess, 'run', return_value=out) as run:
            new = generate.generate([], 1, dates=[date(2026, 10, 5)], test={'name': 'hook_style', 'arm': 'question'})
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]['test'], {'name': 'hook_style', 'arm': 'question'})
        self.assertEqual(new[0]['hook'], QUESTION_HOOK)
        self.assertEqual(run.call_count, 1)  # one repair round
        self.assertIn('the hook must end with', run.call_args[0][0][2])
        with mock.patch.object(generate, 'ask_claude', ask), mock.patch.object(generate.subprocess, 'run') as run:
            new = generate.generate([], 1, dates=[date(2026, 10, 5)], test={'name': 'hook_style', 'arm': 'statement'})
        self.assertEqual(new[0]['test']['arm'], 'statement')
        run.assert_not_called()
        with mock.patch.object(generate, 'ask_claude', ask):
            self.assertNotIn('test', generate.generate([], 1, dates=[date(2026, 10, 5)])[0])

    def test_today_tells_the_writer(self):
        self.start('hook_style')
        history.save_ideas([{'topic': 'Supabase row level security', 'asked': 3, 'since': '2026-10-04'}])
        seen = {}

        def fake_generate(reels, count, dates=None, context=None, test=None):
            seen.update(context=context, test=test)
            return [{**VALID, 'test': test}]
        with mock.patch.object(generate, 'generate', fake_generate):
            reel = generate.today([])
        self.assertEqual(seen['test'], generate.experiment_today())
        self.assertIn("This week's test", seen['context'])
        self.assertIn('Supabase row level security', seen['context'])
        self.assertIn('never quote them', seen['context'])
        self.assertEqual(reel['test'], seen['test'])

    def test_a_test_never_costs_the_day(self):
        self.start('hook_style')
        calls = []

        def fake_generate(reels, count, dates=None, context=None, test=None):
            calls.append(test)
            return [] if test else [dict(VALID)]
        with mock.patch.object(generate, 'generate', fake_generate):
            reel = generate.today([])
        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(calls[0])
        self.assertIsNone(calls[1])
        self.assertNotIn('test', reel)

    def test_strip_3d_keeps_the_test(self):
        self.assertEqual(generate.strip_3d({**VALID, 'test': {'name': 'x', 'arm': 'y'}})['test'], {'name': 'x', 'arm': 'y'})

    def test_posted_reels_still_valid(self):
        proc = subprocess.run([sys.executable, 'generate.py', '--check'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


# ---------- the news writer and the daily performance lines ----------

class TrendsTest(Sandbox):
    def test_timely_reel_carries_and_enforces_the_test(self):
        option = {'reach_score': 9, 'reason': 'big', 'sources': ['https://example.com/a'], 'reel': copy.deepcopy(VALID)}
        items = [{'title': str(i)} for i in range(12)]
        for arm, expect in (('statement', True), ('question', False)):
            with mock.patch.object(trends, 'collect', return_value=(items, [])), \
                    mock.patch.object(trends, 'pick', return_value={'options': [copy.deepcopy(option)]}), \
                    mock.patch.object(trends, 'fact_check', side_effect=lambda r, s: {'verdict': 'pass', 'problems': [],
                                                                                   'reel': {k: v for k, v in r.items() if k != 'test'}}), \
                    mock.patch.object(generate, 'repair', return_value=None), \
                    mock.patch.object(generate, 'experiment_today', return_value={'name': 'hook_style', 'arm': arm}):
                reel = trends.timely_reel([], perf=[])
            if expect:
                self.assertEqual(reel['test'], {'name': 'hook_style', 'arm': 'statement'})
                self.assertEqual(reel['pillar'], 'timely')
            else:
                self.assertIsNone(reel)

    def test_pick_prompt_has_the_note(self):
        history.save_experiments({'active': {'name': 'length', 'since': '2026-10-04'}, 'done': []})
        with mock.patch.object(trends, 'claude', return_value={'options': []}) as c:
            trends.pick([], [{'source': 's', 'title': 't', 'url': 'u', 'signal': '', 'when': None}], [])
        self.assertIn("This week's test", c.call_args[0][0])

    def fake_get(self, refuse_combined):
        calls = []

        def get(url, params=None, **kw):
            calls.append(params.get('metric'))
            metric = params.get('metric', '')
            if ',' in metric and refuse_combined:
                return SimpleNamespace(json=lambda: {'error': {'message': 'unsupported metric'}})
            if metric == 'total_interactions':
                return SimpleNamespace(json=lambda: {'error': {'message': 'unsupported'}})
            names = metric.split(',')
            return SimpleNamespace(json=lambda: {'data': [{'name': n, 'values': [{'value': 7}]} for n in names
                                                          if n != 'total_interactions']})
        return get, calls

    def test_insights_one_request_when_it_works(self):
        get, calls = self.fake_get(refuse_combined=False)
        with mock.patch.object(trends, 'get', get):
            vals = trends.insights_of('B', {'id': '1', 'media_type': 'VIDEO'}, 'tok')
        self.assertEqual(len(calls), 1)
        self.assertEqual(vals['reels_skip_rate'], 7)

    def test_insights_fall_back_to_one_request_per_metric(self):
        get, calls = self.fake_get(refuse_combined=True)
        with mock.patch.object(trends, 'get', get):
            vals = trends.insights_of('B', {'id': '1', 'media_type': 'VIDEO'}, 'tok')
        self.assertEqual(len(calls), 1 + 7)
        self.assertEqual(set(vals), {'views', 'reach', 'saved', 'shares', 'ig_reels_avg_watch_time', 'reels_skip_rate'})
        get, calls = self.fake_get(refuse_combined=True)
        with mock.patch.object(trends, 'get', get):
            vals = trends.insights_of('B', {'id': '1', 'media_type': 'CAROUSEL_ALBUM'}, 'tok')
        self.assertNotIn('reels_skip_rate', vals)

    def test_performance_lines(self):
        get, _ = self.fake_get(refuse_combined=True)

        def routed(url, params=None, **kw):
            if url.endswith('/me/media'):
                return SimpleNamespace(json=lambda: {'data': [{'id': '1', 'media_type': 'VIDEO', 'caption': 'Hi\nx',
                                                               'timestamp': '2026-10-01T12:00:00+0000'}]})
            return get(url, params)
        with mock.patch.dict(os.environ, {'IG_TOKEN': 'tok'}), mock.patch.object(trends, 'get', routed):
            lines = trends.performance()
        self.assertEqual(len(lines), 1)
        self.assertIn('7% skipped in the first 3s', lines[0])
        self.assertNotIn('no insights', lines[0])


# ---------- what publish.py records ----------

class PublishTest(Sandbox):
    def slides(self):
        spec = lambda t: SimpleNamespace(visual=SimpleNamespace(spec={'type': t}), end=0)
        s = [spec('word'), spec('diagram'), SimpleNamespace(visual=None, end=0), spec('code'), SimpleNamespace(visual=None, end=0)]
        for i, x in enumerate(s):
            x.end = 4.0 * (i + 1) + 0.37
        return s

    def run_main(self, reels, todays=None):
        render.QUEUE.write_text(json.dumps(reels))
        video = self.tmp / 'reel.mp4'
        os.environ.update(FORCE_POST='true', SLOT='2')
        with mock.patch.object(publish, 'make_video', return_value=(video, self.slides())), \
                mock.patch.object(publish, 'upload', return_value='https://x/y.mp4'), \
                mock.patch.object(publish, 'delete_upload'), mock.patch.object(publish, 'wait_for_post_time'), \
                mock.patch.object(publish, 'publish_to_instagram', return_value='17999'), \
                mock.patch.object(publish, 'output'), \
                mock.patch.object(publish, 'todays_reel', return_value=todays):
            publish.main()
        return json.loads(render.QUEUE.read_text())

    def test_records_what_the_learning_loop_needs(self):
        hand = {**copy.deepcopy(VALID), 'id': 5, 'posted_at': None, 'media_id': None}
        saved = self.run_main([hand])[-1]
        self.assertEqual(saved['shown'], ['word', 'diagram', 'text', 'code', 'text'])
        self.assertEqual(saved['slot'], 2)
        self.assertEqual(saved['seconds'], 20.4)
        self.assertEqual(saved['media_id'], '17999')
        self.assertNotIn('test', saved)
        self.assertEqual(generate.validate(saved), [])

    def test_a_written_reel_keeps_its_test(self):
        posted = {**copy.deepcopy(VALID), 'id': 5, 'style': 'light', 'posted_at': '2026-10-01T12:00:00+00:00', 'media_id': '1'}
        written = {**copy.deepcopy(VALID), 'hook': QUESTION_HOOK, 'test': {'name': 'hook_style', 'arm': 'question'}}
        saved = self.run_main([posted], todays=written)[-1]
        self.assertEqual(saved['id'], 6)
        self.assertEqual(saved['test'], {'name': 'hook_style', 'arm': 'question'})
        self.assertEqual(generate.validate(saved), [])
        self.assertEqual(json.loads((self.tmp / 'reel.json').read_text())['test'], saved['test'])

    def test_dry_run_records_nothing(self):
        hand = {**copy.deepcopy(VALID), 'id': 5, 'posted_at': None, 'media_id': None}
        os.environ['DRY_RUN'] = 'true'
        saved = self.run_main([hand])[-1]
        self.assertNotIn('shown', saved)
        self.assertIsNone(saved['posted_at'])


# ---------- learn.py, step by step ----------

def reel(i, posted, **kw):
    points = [{'title': 't', 'body': 'b'} for _ in range(3)]
    return {'id': i, 'hook': f'Hook number {i}', 'pillar': 'concept', 'series': 'Explained', 'points': points,
            'posted_at': posted.isoformat(timespec='seconds'), 'media_id': f'm{i}', **kw}


def row(i, day, skip, watched=None, test='none', **kw):
    return {'kind': 'reel', 'id': i, 'posted_at': day.isoformat() + 'T12:00', 'skip_vs_usual': skip,
            'watched_vs_usual': watched, 'test': test, **kw}


class FakeInstagram:
    """Answers learn.py's Graph API calls from a table of metric functions, and counts the calls."""

    def __init__(self, values, unsupported=('follows',)):
        self.values, self.unsupported, self.calls = values, set(unsupported), []

    def get(self, url, params=None, timeout=None):
        params = params or {}
        if url.startswith('https://cdn.example/'):
            return SimpleNamespace(ok=True, content=b'\xff\xd8jpeg')
        media = url.split('/')[4]
        if url.endswith('/insights'):
            self.calls.append((media, params['metric']))
            if params['metric'] in self.unsupported:
                return SimpleNamespace(ok=False, json=lambda: {'error': {'message': 'unsupported'}})
            value = self.values(media, params['metric'])
            return SimpleNamespace(ok=True, json=lambda: {'data': [{'values': [{'value': value}]}]} if value is not None else {'data': []})
        return SimpleNamespace(ok=True, json=lambda: {'thumbnail_url': f'https://cdn.example/{media}.jpg'})


class MeasureTest(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 10, 4, 10, tzinfo=timezone.utc)
        self.p = [mock.patch.object(learn, 'utcnow', return_value=self.now)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        super().tearDown()

    def test_measure(self):
        reels = [reel(1, self.now - timedelta(hours=30)),                      # too new
                 reel(2, self.now - timedelta(days=3), dm_keyword='MCP'),      # measured, keyword counted
                 reel(3, self.now - timedelta(days=40)),                        # already settled
                 {**reel(4, self.now - timedelta(days=5)), 'media_id': None}]   # never published
        carousels = [{'title': 'C', 'media_id': 'c1', 'posted_at': (self.now - timedelta(days=6)).isoformat(),
                      'dm_keyword': 'KEYS'}]
        stored = history.by_post([{'date': '2026-09-20', 'kind': 'reel', 'id': 3, 'age_days': 30}])
        ig = FakeInstagram(lambda m, n: 42)
        comments = {'m2': [{'text': 'MCP'}, {'text': 'mcp please'}, {'text': 'Can you cover Supabase auth?'}],
                    'c1': [{'text': 'KEYS'}, {'text': 'great'}]}
        with mock.patch.object(learn.requests, 'get', ig.get), \
                mock.patch.object(dm, 'comments', lambda media, token: comments.get(media, [])):
            rows, texts = learn.measure(reels, carousels, 'tok', stored)
        self.assertEqual([(r['kind'], r['id']) for r in rows], [('reel', 2), ('carousel', 'c1')])
        r2 = rows[0]
        self.assertEqual(r2['age_days'], 3.0)
        self.assertEqual(r2['dm_asks'], 2)
        self.assertEqual(r2['views'], 42)
        self.assertIsNone(r2['follows'])
        self.assertEqual(rows[1]['dm_asks'], 1)
        self.assertNotIn('reels_skip_rate', rows[1])
        self.assertEqual(sorted(texts), ['Can you cover Supabase auth?', 'great'])
        self.assertNotIn('m3', {m for m, _ in ig.calls})

    def test_comments_failure_is_not_fatal(self):
        reels = [reel(2, self.now - timedelta(days=3), dm_keyword='MCP')]

        def boom(media, token):
            raise dm.DMError('rate limited')
        with mock.patch.object(learn.requests, 'get', FakeInstagram(lambda m, n: 1).get), mock.patch.object(dm, 'comments', boom):
            rows, texts = learn.measure(reels, [], 'tok', {})
        self.assertEqual(len(rows), 1)
        self.assertNotIn('dm_asks', rows[0])
        self.assertEqual(texts, [])

    def test_errors_never_print_the_token(self):
        reels = [reel(2, self.now - timedelta(days=3), dm_keyword='MCP')]

        def boom(*a, **k):
            raise learn.requests.ConnectionError('Max retries exceeded with url: /v25.0/m2/comments?access_token=SECRET123')
        out = io.StringIO()
        with mock.patch.object(learn.requests, 'get', FakeInstagram(lambda m, n: 1).get), mock.patch.object(dm, 'comments', boom), \
                contextlib.redirect_stdout(out):
            learn.measure(reels, [], 'SECRET123', {})
        best = [row(i, date(2026, 9, 1), -5, media_id=f'm{i}', hook='A') for i in (1, 2)]
        with mock.patch.object(learn.requests, 'get', boom), contextlib.redirect_stdout(out):
            self.assertEqual(learn.review_openings(best, best, 'SECRET123'), '')
        self.assertIn('***', out.getvalue())
        self.assertNotIn('SECRET123', out.getvalue())

    def test_metric_parsing(self):
        with mock.patch.object(learn.requests, 'get', FakeInstagram(lambda m, n: 5).get):
            self.assertEqual(learn.metric('m1', 'views', 't'), 5)
            self.assertIsNone(learn.metric('m1', 'follows', 't'))

        def down(*a, **k):
            raise learn.requests.ConnectionError('down')
        with mock.patch.object(learn.requests, 'get', down):
            self.assertIsNone(learn.metric('m1', 'views', 't'))


class ScoreTest(Sandbox):
    def test_looks(self):
        base = reel(1, datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(learn.looks(base), {'visuals': ['text'], 'hook_word': 'text only', 'three_d': 'flat'})
        self.assertEqual(learn.looks({**base, 'shown': ['word', 'diagram', 'terminal', 'text', 'text']}),
                         {'visuals': ['diagram', 'terminal'], 'hook_word': '3D word', 'three_d': '3D'})
        fell_back = {**base, 'hook_word': 'RLS', 'shown': ['text', 'code', 'text', 'text', 'text']}
        fell_back['points'][0]['visual'] = [{'type': 'diagram'}, {'type': 'code'}]
        self.assertEqual(learn.looks(fell_back)['three_d'], 'flat')
        self.assertEqual(learn.looks({k: v for k, v in fell_back.items() if k != 'shown'})['three_d'], '3D')

    def test_slot_of(self):
        at = lambda h: reel(1, datetime(2026, 10, 1, h, 0, 5, tzinfo=timezone.utc))
        self.assertEqual([learn.slot_of(at(h)) for h in (12, 16, 20)], [1, 2, 3])
        self.assertEqual(learn.slot_of({**at(12), 'slot': 3}), 3)
        self.assertEqual(learn.slot_of({**at(12), 'posted_at': '2026-10-01T17:00:00+05:00'}), 1)

    def test_table_scores_against_the_usual(self):
        t0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        reels = [reel(1, t0, seconds=20.0, test={'name': 'hook_style', 'arm': 'question'}),
                 reel(2, t0, seconds=20.0), reel(3, t0 + timedelta(hours=4), seconds=None), reel(4, t0)]
        snaps = [{'date': '2026-09-05', 'kind': 'reel', 'id': i, 'age_days': 4, 'views': 50, 'reels_skip_rate': s,
                  'ig_reels_avg_watch_time': w} for i, s, w in ((1, 60, 8000), (2, 70, 4000), (3, 80, 5000))]
        snaps.append({'date': '2026-09-12', 'kind': 'reel', 'id': 1, 'age_days': 11, 'views': 90, 'reels_skip_rate': 58,
                      'ig_reels_avg_watch_time': 8000})
        rows, usual = learn.table(reels, [], history.by_post(snaps))
        by = {r['id']: r for r in rows}
        self.assertEqual(set(by), {1, 2, 3})            # 4 has no snapshot yet
        self.assertEqual(usual['skip_rate'], 70)         # median of 58, 70, 80
        self.assertEqual(by[1]['reels_skip_rate'], 58)   # latest snapshot
        self.assertEqual(by[1]['skip_vs_usual'], -12)
        self.assertEqual(by[1]['views_7d'], 90)
        self.assertIsNone(by[2]['views_7d'])
        self.assertEqual(by[1]['watched_share'], 0.4)
        self.assertIsNone(by[3]['watched_share'])        # length unknown
        self.assertEqual(by[1]['test'], 'hook_style: question')
        self.assertEqual(by[2]['test'], 'none')
        self.assertEqual(by[3]['slot'], 'slot 2')
        self.assertEqual(usual['watched_share'], 0.3)
        self.assertEqual(by[2]['watched_vs_usual'], -0.1)
        summary = learn.groups([r for r in rows])
        self.assertEqual(set(summary), set(learn.GROUP_FIELDS))
        self.assertEqual(summary['test']['hook_style: question']['reels'], 1)
        json.dumps(summary)

    def test_verdict_and_clearly(self):
        day = date(2026, 9, 1)
        good = [row(i, day, -3, 0.05) for i in range(5)]
        bad = [row(i, day, 1, 0.0) for i in range(5)]
        self.assertEqual(learn.verdict(good, bad), (4.0, 0.05))
        self.assertIsNone(learn.verdict(good[:4], bad))
        self.assertEqual(learn.clearly((4.0, 0.05)), 1)
        self.assertEqual(learn.clearly((-4.0, None)), -1)
        self.assertEqual(learn.clearly((1.0, 0.01)), 0)
        self.assertEqual(learn.clearly((0.5, 0.08)), 1)      # watched a lot more, skip not worse
        self.assertEqual(learn.clearly((-2.5, 0.08)), -1)    # skip clearly worse wins over watched
        self.assertEqual(learn.clearly((1.0, -0.06)), -1)


class JudgeTest(Sandbox):
    today = date(2026, 11, 1)

    def rule(self, days_ago, status='trial'):
        return {'id': 1, 'text': 'Do X', 'since': (self.today - timedelta(days=days_ago)).isoformat(), 'status': status,
                'source': 'weekly', 'evidence': '', 'verdict': '', 'checked': ''}

    def rows(self, since, before, after):
        return ([row(i, since - timedelta(days=1 + i % 20), before) for i in range(6)]
                + [row(10 + i, since + timedelta(days=i % 14), after) for i in range(6)])

    def test_rule_that_helped_is_kept(self):
        r = self.rule(14)
        changes = learn.evaluate_rules([r], self.rows(date.fromisoformat(r['since']), 2, -2), self.today)
        self.assertEqual(r['status'], 'kept')
        self.assertIn('helped', r['verdict'])
        self.assertEqual(changes, [('kept', r)])

    def test_rule_that_hurt_is_retired(self):
        r = self.rule(14)
        learn.evaluate_rules([r], self.rows(date.fromisoformat(r['since']), -2, 2), self.today)
        self.assertEqual(r['status'], 'retired')
        self.assertIn('hurt', r['verdict'])

    def test_too_early_and_unclear(self):
        r = self.rule(13)
        self.assertEqual(learn.evaluate_rules([r], self.rows(date.fromisoformat(r['since']), 2, -2), self.today), [])
        self.assertEqual(r['status'], 'trial')
        r = self.rule(20)
        learn.evaluate_rules([r], self.rows(date.fromisoformat(r['since']), 0.5, 0), self.today)
        self.assertEqual(r['status'], 'trial')
        r = self.rule(28)
        learn.evaluate_rules([r], self.rows(date.fromisoformat(r['since']), 0.5, 0), self.today)
        self.assertEqual(r['status'], 'retired')
        self.assertIn('no clear effect', r['verdict'])

    def test_never_enough_reels(self):
        r = self.rule(30)
        learn.evaluate_rules([r], [], self.today)
        self.assertEqual(r['status'], 'trial')
        r = self.rule(42)
        learn.evaluate_rules([r], [], self.today)
        self.assertEqual(r['status'], 'retired')

    def test_before_window_is_the_4_weeks_before_the_rule(self):
        r = self.rule(14)
        since = date.fromisoformat(r['since'])
        rows = ([row(i, since - timedelta(days=5), 0) for i in range(5)]             # the real "before"
                + [row(10 + i, since - timedelta(days=40), 9) for i in range(5)]     # too old: must not count
                + [row(20 + i, since, -0.5) for i in range(5)])                      # the day it started counts as after
        learn.evaluate_rules([r], rows, self.today)
        self.assertEqual(r['status'], 'trial', r['verdict'])
        self.assertIn('(5 reels after vs 5 before)', r['verdict'] or 'no verdict')

    def test_kept_rules_stay(self):
        r = self.rule(60, status='kept')
        learn.evaluate_rules([r], self.rows(date.fromisoformat(r['since']), -5, 5), self.today)
        self.assertEqual(r['status'], 'kept')

    def exp_rows(self, q, s, n=5):
        return ([row(i, self.today, q, test='hook_style: question') for i in range(n)]
                + [row(20 + i, self.today, s, test='hook_style: statement') for i in range(n)])

    def test_experiment_lifecycle(self):
        exp, msg = learn.run_experiment({'active': None, 'done': []}, [], [], self.today)
        self.assertEqual(exp['active'], {'name': 'hook_style', 'since': self.today.isoformat()})
        self.assertIn('New test', msg)
        rules = []
        exp, msg = learn.run_experiment(exp, self.exp_rows(-3, 3, n=4), rules, self.today)
        self.assertEqual(exp['active']['name'], 'hook_style')
        self.assertIn('still running', msg)
        exp, msg = learn.run_experiment(exp, self.exp_rows(-3, 3), rules, self.today)
        self.assertEqual(exp['done'][0]['name'], 'hook_style')
        self.assertIn('question won', exp['done'][0]['result'])
        self.assertEqual(rules[0]['status'], 'kept')
        self.assertEqual(rules[0]['text'], generate.EXPERIMENTS['hook_style']['question'][0])
        self.assertEqual(exp['active']['name'], 'length')

    def test_experiment_statement_wins_or_ties_or_times_out(self):
        rules = []
        start = {'active': {'name': 'hook_style', 'since': self.today.isoformat()}, 'done': []}
        exp, _ = learn.run_experiment(copy.deepcopy(start), self.exp_rows(3, -3), rules, self.today)
        self.assertIn('statement won', exp['done'][0]['result'])
        self.assertEqual(rules[0]['text'], generate.EXPERIMENTS['hook_style']['statement'][0])
        rules = []
        exp, _ = learn.run_experiment(copy.deepcopy(start), self.exp_rows(0, 0.5), rules, self.today)
        self.assertIn('no clear difference', exp['done'][0]['result'])
        self.assertEqual(rules, [])
        old = {'active': {'name': 'hook_style', 'since': (self.today - timedelta(days=21)).isoformat()}, 'done': []}
        exp, msg = learn.run_experiment(old, self.exp_rows(-3, 3, n=2), [], self.today)
        self.assertIn('not enough reels', exp['done'][0]['result'])

    def test_all_tests_done_and_off(self):
        done = [{'name': n, 'since': '2026-09-01', 'until': '2026-09-20', 'result': 'x'} for n in generate.EXPERIMENTS]
        exp, msg = learn.run_experiment({'active': None, 'done': done}, [], [], self.today)
        self.assertIsNone(exp['active'])
        self.assertIn('Every test', msg)
        os.environ['EXPERIMENT'] = 'off'
        exp, msg = learn.run_experiment({'active': None, 'done': []}, [], [], self.today)
        self.assertIsNone(exp['active'])
        self.assertIn('switched off', msg)

    def summary(self, better_n=6, worse_n=6, better=-3.0, worse=2.0):
        return {'hook_word': {'3D word': {'reels': better_n, 'skip_vs_usual': better, 'watched_vs_usual': 0.02},
                              'text only': {'reels': worse_n, 'skip_vs_usual': worse, 'watched_vs_usual': 0.0}}}

    def test_new_rules_need_clear_evidence(self):
        ev = [{'field': 'hook_word', 'better': '3D word', 'worse': 'text only'}]
        ok = {'text': 'Spin the key word of the hook in 3D', 'evidence': ev}
        accepted, dropped = learn.check_new_rules([ok], self.summary(), [], self.today)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['status'], 'trial')
        self.assertIn('5.0 points', accepted[0]['evidence'].replace('+', ''))
        for summary, why in ((self.summary(better_n=4), 'no clear'), (self.summary(better=1.5), 'no clear')):
            self.assertIn(why, learn.check_new_rules([ok], summary, [], self.today)[1][0][1])
        bad = [{'text': 'Add upbeat music under the voice', 'evidence': ev},
               {'text': 'Show your face in the first second', 'evidence': ev},
               {'text': 'Say comment below at the end', 'evidence': ev},
               {'text': 'Something', 'evidence': [{'field': 'nope', 'better': 'a', 'worse': 'b'}]},
               {'text': 'Something else', 'evidence': []}]
        accepted, dropped = learn.check_new_rules(bad, self.summary(), [], self.today)
        self.assertEqual(accepted, [])
        self.assertEqual([w.split(' ')[0] for _, w in dropped], ['touches', 'touches', 'touches', 'no', 'no'])
        existing = [{'id': 7, 'text': 'Spin the key word of the hook in 3D.', 'status': 'trial'}]
        self.assertEqual(learn.check_new_rules([ok], self.summary(), existing, self.today)[1][0][1], 'already a rule')

    def test_rules_rest_only_on_what_the_writer_controls(self):
        summary = {'slot': {'slot 1': {'reels': 9, 'skip_vs_usual': -4.0, 'watched_vs_usual': 0.0},
                            'slot 3': {'reels': 9, 'skip_vs_usual': 3.0, 'watched_vs_usual': 0.0}}}
        rule = {'text': 'Post earlier in the day', 'evidence': [{'field': 'slot', 'better': 'slot 1', 'worse': 'slot 3'}]}
        accepted, dropped = learn.check_new_rules([rule], summary, [], self.today)
        self.assertEqual(accepted, [])
        self.assertIn('the writer controls', dropped[0][1])
        self.assertNotIn('slot', learn.RULE_FIELDS)

    def test_rules_are_short(self):
        ev = [{'field': 'hook_word', 'better': '3D word', 'worse': 'text only'}]
        long = {'text': ' '.join(['word'] * (learn.MAX_RULE_WORDS + 1)), 'evidence': ev}
        accepted, dropped = learn.check_new_rules([long], self.summary(), [], self.today)
        self.assertEqual(accepted, [])
        self.assertIn('longer than', dropped[0][1])

    def test_rule_caps(self):
        ev = [{'field': 'hook_word', 'better': '3D word', 'worse': 'text only'}]
        many = [{'text': f'Rule {i}', 'evidence': ev} for i in range(5)]
        accepted, dropped = learn.check_new_rules(many, self.summary(), [], self.today)
        self.assertEqual(len(accepted), learn.MAX_NEW_RULES)
        full = [{'id': i, 'text': f'Old {i}', 'status': 'trial'} for i in range(learn.MAX_ACTIVE_RULES)]
        accepted, _ = learn.check_new_rules(many, self.summary(), full, self.today)
        self.assertEqual(accepted, [])
        self.assertEqual(len({r['id'] for r in learn.check_new_rules(many, self.summary(), [], self.today)[0]}), 3)


class ClaudeTest(Sandbox):
    def test_command_line(self):
        out = SimpleNamespace(returncode=0, stdout=json.dumps({'structured_output': {'a': 1}}), stderr='')
        with mock.patch.object(learn.subprocess, 'run', return_value=out) as run:
            self.assertEqual(learn.claude('p', 's', {'type': 'object'}), {'a': 1})
            cmd = run.call_args[0][0]
            self.assertEqual(cmd[cmd.index('--tools') + 1], '')
            self.assertNotIn('--add-dir', cmd)
            learn.claude('p', 's', {}, tools=('Read',), folder='/tmp/x')
            cmd = run.call_args[0][0]
            self.assertEqual(cmd[cmd.index('--tools') + 1: cmd.index('--tools') + 2], ['Read'])
            self.assertEqual(cmd[cmd.index('--allowedTools') + 1], 'Read')
            self.assertEqual(cmd[cmd.index('--add-dir') + 1], '/tmp/x')
        with mock.patch.object(learn.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='no auth')):
            self.assertRaises(RuntimeError, learn.claude, 'p', 's', {})
        with mock.patch.object(learn.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}', stderr='')):
            self.assertRaises(RuntimeError, learn.claude, 'p', 's', {})

    def test_topic_ideas(self):
        today = date(2026, 10, 4)
        old = [{'topic': 'Old', 'asked': 2, 'since': '2026-09-20'}, {'topic': 'Stale', 'asked': 9, 'since': '2026-08-01'}]
        self.assertEqual(learn.topic_ideas([], [], old, today), old[:1])
        answer = {'ideas': [{'topic': 'RLS', 'asked': 1}, {'topic': 'Auth', 'asked': 4}, {'topic': ' ', 'asked': 3}]}
        with mock.patch.object(learn, 'claude', return_value=answer) as c:
            ideas = learn.topic_ideas(['please cover auth'], [reel(1, datetime(2026, 9, 1, tzinfo=timezone.utc))], old, today)
        self.assertEqual([i['topic'] for i in ideas], ['Auth', 'RLS'])
        self.assertIn('Hook number 1', c.call_args[0][0])
        with mock.patch.object(learn, 'claude', side_effect=RuntimeError('down')):
            self.assertEqual(learn.topic_ideas(['x'], [], old, today), old[:1])

    def test_review_openings(self):
        best = [row(1, date(2026, 9, 1), -5, media_id='m1', hook='A'), row(2, date(2026, 9, 1), -4, media_id='m2', hook='B')]
        worst = [row(3, date(2026, 9, 1), 5, media_id='m3', hook='C'), row(4, date(2026, 9, 1), 4, media_id='m4', hook='D')]
        self.assertEqual(learn.review_openings(best[:1], worst, 't'), '')
        seen = {}

        def fake_claude(prompt, system, schema, tools=(), folder=None, **kw):
            seen.update(prompt=prompt, tools=tools, files=sorted(p.name for p in Path(folder).iterdir()))
            return {'observations': ' Big words win. '}
        with mock.patch.object(learn.requests, 'get', FakeInstagram(lambda m, n: 1).get), mock.patch.object(learn, 'claude', fake_claude):
            self.assertEqual(learn.review_openings(best, worst, 't'), 'Big words win.')
        self.assertEqual(seen['tools'], ('Read',))
        self.assertEqual(seen['files'], ['reel-1.jpg', 'reel-2.jpg', 'reel-3.jpg', 'reel-4.jpg'])
        with mock.patch.object(learn.requests, 'get', FakeInstagram(lambda m, n: 1).get), \
                mock.patch.object(learn, 'claude', side_effect=RuntimeError('x')):
            self.assertEqual(learn.review_openings(best, worst, 't'), '')

    def test_write_up_prompt(self):
        rows = [row(1, date(2026, 9, 1), -1, hook='H', media_id='m')]
        with mock.patch.object(learn, 'claude', return_value={'new_rules': [], 'summary': 's', 'decision': 'd'}) as c:
            learn.write_up(rows, {'slot': {}}, [{'text': 'R', 'status': 'trial', 'since': 'x', 'verdict': ''}], 'T',
                           [{'topic': 'I'}], 'O', 'LAST')
        prompt = c.call_args[0][0]
        for part in ('"skip_vs_usual": -1', 'R', 'The weekly test: T', 'I', 'O', 'LAST', generate.SYSTEM[:200]):
            self.assertIn(part, prompt)
        self.assertNotIn('media_id', prompt)


class OutageTest(Sandbox):
    def test_claude_down_still_saves_the_week(self):
        now = datetime(2026, 10, 11, 10, tzinfo=timezone.utc)
        reels = [reel(i, now - timedelta(days=2 + i % 5), slot=1, seconds=20.0) for i in range(1, 9)]
        render.QUEUE.write_text(json.dumps(reels))
        (self.tmp / 'learnings.md').write_text('# x\n\n- Old rule\n')
        ig = FakeInstagram(lambda m, n: {'reels_skip_rate': 70 + int(m[1:]), 'ig_reels_avg_watch_time': 5000}.get(n, 3))
        with mock.patch.object(learn, 'utcnow', return_value=now), mock.patch.object(learn.requests, 'get', ig.get), \
                mock.patch.object(dm, 'comments', lambda media, token: [{'text': 'cover auth please'}]), \
                mock.patch.object(learn.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='401')), \
                mock.patch.dict(os.environ, {'IG_TOKEN': 't'}):
            learn.main()
        text = (self.tmp / 'out' / 'report.md').read_text()
        self.assertIn('The write-up was unavailable', text)
        self.assertIn('## This week vs last week', text)
        self.assertEqual(len(history.snapshots()), 8)
        self.assertEqual([r['text'] for r in history.rules()], ['Old rule'])
        self.assertEqual(history.experiments()['active']['name'], 'hook_style')
        self.assertEqual(len(list((self.tmp / 'reports').iterdir())), 1)


class ReportTest(Sandbox):
    def test_stray_markup_and_watch_time(self):
        self.assertEqual(learn.clean('All good.</summary>\n</invoke>\n'), 'All good.')
        self.assertEqual(learn.clean('Use <Suspense> for this'), 'Use <Suspense> for this')
        rows = [row(i, date(2026, 9, 26), 0.5 * i, hook='H', reels_skip_rate=80 + i, ig_reels_avg_watch_time=3000 + 100 * i)
                for i in range(1, 5)]
        text = learn.report(date(2026, 9, 28), rows, {'skip_rate': 82, 'watched_share': None}, [], 'T', [], [], [], [], '',
                            {'summary': 'Fine.</summary>\n</invoke>', 'decision': 'None.</decision>'})
        self.assertNotIn('</', text)
        self.assertIn('| Watch time (average) | 3.2s |', text)
        self.assertIn('watched 3.1s', text)
        self.assertNotIn('of it)', text)


class WorkflowTest(unittest.TestCase):
    def test_commit_step_stages_every_existing_file(self):
        """The weekly job's `git add` loop: a missing file must not stop the others from being committed."""
        text = (ROOT / '.github/workflows/weekly.yml').read_text()
        loop = re.search(r'( *for f in learnings\.md.*?\n *done\n)', text, re.S).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            run = lambda *a: subprocess.run(a, cwd=tmp, capture_output=True, text=True, check=True)
            run('git', 'init', '-q')
            for name in ('learnings.md', 'rules.json', 'experiments.json'):
                Path(tmp, name).write_text('x')
            Path(tmp, 'metrics').mkdir()
            Path(tmp, 'metrics', '2026-10.jsonl').write_text('{}\n')
            subprocess.run(['bash', '-e', '-c', loop], cwd=tmp, check=True)
            staged = run('git', 'diff', '--cached', '--name-only').stdout.split()
        self.assertEqual(sorted(staged), ['experiments.json', 'learnings.md', 'metrics/2026-10.jsonl', 'rules.json'])

    def test_a_manual_weekly_run_never_posts_unless_asked(self):
        text = (ROOT / '.github/workflows/weekly.yml').read_text()
        job = text.split('\n  carousel:')[1]
        self.assertIn("if: github.event_name == 'schedule' || inputs.post_carousel", job)
        self.assertRegex(text, r'post_carousel:\n(.*\n){2}\s+default: false')

    def test_learn_job_installs_what_learn_imports(self):
        text = (ROOT / '.github/workflows/weekly.yml').read_text()
        job = text.split('  learn:')[1].split('\n  carousel:')[0]
        self.assertIn('pip install requests pillow numpy', job)


# ---------- the whole loop, six weeks ----------

class SimulationTest(Sandbox):
    """Three reels a day for six weeks, posted under whatever test is running, measured and judged every Sunday by
    learn.main against a fake Instagram in which question hooks really do hold viewers better."""

    EFFECT = {'question': -5.0, 'statement': 5.0}

    def metrics(self, media, name):
        r = self.by_media[media]
        age = (self.now - datetime.fromisoformat(r['posted_at'])).total_seconds() / 86400
        noise = random.Random(f"{r['id']}-{name}").uniform(-1.5, 1.5)
        arm = (r.get('test') or {}).get('arm')
        return {'views': round(100 + 20 * min(age, 30)), 'reach': 90, 'saved': 2, 'shares': 1, 'likes': 5,
                'comments': 1, 'profile_visits': 3,
                'reels_skip_rate': round(70 + self.EFFECT.get(arm, 0) + noise, 1),
                'ig_reels_avg_watch_time': round((6 - self.EFFECT.get(arm, 0) / 5 + noise) * 1000)}.get(name)

    def test_six_weeks(self):
        (self.tmp / 'learnings.md').write_text('# What holds our viewers\n\n- Old rule one\n- Old rule two\n')
        start = datetime(2026, 10, 5, tzinfo=timezone.utc)  # a Monday
        reels, carousels, reports = [], [], []
        ig = FakeInstagram(self.metrics)
        self.by_media = {}
        proposals = iter([[], [{'text': 'Keep hooks under seven words',
                                'evidence': [{'field': 'slot', 'better': 'slot 1', 'worse': 'slot 3'}]}]] + [[]] * 10)

        def fake_claude(prompt, system, schema, **kw):
            if system == learn.SYSTEM:
                return {'new_rules': next(proposals), 'summary': 'All good.', 'decision': 'none this week'}
            if system == learn.IDEAS_SYSTEM:
                return {'ideas': [{'topic': 'Supabase auth', 'asked': 2}]}
            return {'observations': 'Short hooks.'}

        comments = lambda media, token: [{'text': 'Can you do Supabase auth next?'}]
        for day in range(42):
            when = start + timedelta(days=day)
            self.now = when + timedelta(hours=10)
            if when.weekday() == 6:  # Sunday: the weekly job, before that day's posts
                render.QUEUE.write_text(json.dumps(reels))
                learn.CAROUSELS.write_text(json.dumps(carousels))
                before = len(ig.calls)
                with mock.patch.object(learn, 'utcnow', return_value=self.now), \
                        mock.patch.object(learn.requests, 'get', ig.get), mock.patch.object(dm, 'comments', comments), \
                        mock.patch.object(learn, 'claude', fake_claude), mock.patch.dict(os.environ, {'IG_TOKEN': 't'}):
                    learn.main()
                reports.append((when.date(), len(ig.calls) - before))
                carousels.append({'title': f'Carousel {day}', 'media_id': f'c{day}',
                                  'posted_at': (when + timedelta(hours=10, minutes=30)).isoformat()})
                self.by_media[f'c{day}'] = {'id': f'c{day}', 'posted_at': carousels[-1]['posted_at']}
            for s, hour in ((1, 12), (2, 16), (3, 20)):
                os.environ['SLOT'] = str(s)
                test = generate.experiment_today(when.date())
                r = reel(len(reels) + 1, when.replace(hour=hour), slot=s, seconds=20.0,
                         shown=['text', 'code', 'text', 'text', 'text'], **({'test': test} if test else {}))
                reels.append(r)
                self.by_media[r['media_id']] = r

        exp = history.experiments()
        rules = history.rules()
        # The imported rules were judged: no real effect, so retired after 4 weeks.
        imported = [r for r in rules if r['source'] == 'imported']
        self.assertEqual(len(imported), 2)
        self.assertTrue(all(r['status'] == 'retired' for r in imported), imported)
        # The first test found the real effect and handed the writer a proven rule.
        self.assertEqual(exp['done'][0]['name'], 'hook_style')
        self.assertIn('question won', exp['done'][0]['result'])
        proven = [r for r in rules if r['source'] == 'experiment']
        self.assertEqual([r['status'] for r in proven], ['kept'])
        self.assertIn(generate.EXPERIMENTS['hook_style']['question'][0] + ' (proven)', (self.tmp / 'learnings.md').read_text())
        # Each next test started on its own the same Sunday, and the reels written while it ran carry it. The fake
        # Instagram gives length and numbers no effect, so those tests find none; then every test has run.
        self.assertEqual([d['name'] for d in exp['done']], list(generate.EXPERIMENTS))
        self.assertTrue(all('no clear difference' in d['result'] for d in exp['done'][1:]), exp['done'])
        for d in exp['done']:
            during = [r for r in reels if d['since'] <= r['posted_at'][:10] < d['until']]
            self.assertTrue(during and all(r['test']['name'] == d['name'] for r in during), d)
            self.assertEqual(exp['done'][exp['done'].index(d) - 1]['until'] if exp['done'].index(d) else d['since'], d['since'])
        self.assertIsNone(exp['active'])
        self.assertNotIn('test', reels[-1])
        # A proposed rule with no clear evidence behind it never reached the writer.
        self.assertNotIn('Keep hooks under seven words', (self.tmp / 'learnings.md').read_text())
        # One report per Sunday, saved and readable.
        saved = sorted(p.name for p in (self.tmp / 'reports').iterdir())
        self.assertEqual(len(saved), len(reports))  # even the first Sunday: Monday to Friday's reels are 48h+ old
        last = (self.tmp / 'reports' / saved[-1]).read_text()
        for heading in ('## This week vs last week', '## Best and worst openings', '## Carousels', "## This week's test",
                        '## Rules', '## What people asked for', '## Summary', '## One decision for you'):
            self.assertIn(heading, last)
        self.assertIn('Keep hooks under seven words (no clear difference', last + (self.tmp / 'reports' / saved[0]).read_text()
                      + ''.join((self.tmp / 'reports' / s).read_text() for s in saved))
        self.assertEqual((self.tmp / 'out' / 'report.md').read_text(), last)
        # Snapshots went to monthly files, and settled posts stopped costing API calls.
        files = sorted(p.name for p in (self.tmp / 'metrics').iterdir())
        self.assertEqual(files, ['2026-10.jsonl', '2026-11.jsonl'])
        posts = history.by_post()
        first = posts['reel:1']
        self.assertTrue(history.settled(first))
        self.assertEqual(sum(s['age_days'] >= history.SETTLED_DAYS for s in first), 1)
        self.assertEqual(json.loads((self.tmp / 'ideas.json').read_text())[0]['topic'], 'Supabase auth')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a == '-v'])
