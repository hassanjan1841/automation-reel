"""Offline tests for study.py: the measurements on synthetic videos made with ffmpeg (known cuts, a blank first
second, a tone), the links and search picks, the breakdown's placeholder check and retry, the saved report and
index, and main's handling of a link that fails. No network, no Claude, no YouTube; needs ffmpeg on PATH and only
requests, pillow and numpy (like CI).

Usage: python test_study.py        runs everything, exit 1 on any failure
       python test_study.py -v     one line per test
"""

import io
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

import study

GOOD = {'first_second': 'A terminal with a red error fills the screen.', 'pacing': 'A new picture every 1.5 s.',
        'hook': {'spoken': 'Your build fails for one reason', 'on_screen': 'BUILD FAILED', 'type': 'problem'},
        'structure': [{'at': '0-2s', 'what': 'the error'}, {'at': '2-8s', 'what': 'the fix'}],
        'why_it_works': ['The problem is visible before a word is said.'],
        'adoptable': [{'pattern': 'Open on the error itself', 'for_us': 'Show the terminal first.',
                       'test': 'Half the reels open on the visual.'}],
        'not_adoptable': [{'pattern': 'Face to camera', 'rule': 'no faces'}]}


def make_video(path, blank_first=True, audio=True):
    """1 s black (or a test pattern), 2 s white, 3 s gray: cuts at 1 s and 3 s, 6 s long, 180x320."""
    first = 'color=c=black:s=180x320:d=1:r=25' if blank_first else 'testsrc=s=180x320:d=1:r=25'
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', first, '-f', 'lavfi', '-i', 'color=c=white:s=180x320:d=2:r=25',
           '-f', 'lavfi', '-i', 'color=c=gray:s=180x320:d=3:r=25']
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=6']
    cmd += ['-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]', '-map', '[v]']
    if audio:
        cmd += ['-map', '3:a', '-c:a', 'aac']
    subprocess.run(cmd + ['-c:v', 'libx264', str(path)], check=True)
    return path


@unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is not on PATH')
class Measure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.video = make_video(Path(cls.tmp.name) / 'v.mp4')
        cls.plain = make_video(Path(cls.tmp.name) / 'p.mp4', blank_first=False, audio=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_probe(self):
        p = study.probe(self.video)
        self.assertAlmostEqual(p['seconds'], 6, delta=0.1)
        self.assertEqual((p['width'], p['height']), (180, 320))
        self.assertTrue(p['has_audio'])
        self.assertFalse(study.probe(self.plain)['has_audio'])

    def test_cuts_and_blank_start(self):
        m = study.motion(study.frames_gray(self.video))
        self.assertEqual(len(m['cuts']), 2, m)
        self.assertAlmostEqual(m['cuts'][0], 1.0, delta=0.15)
        self.assertAlmostEqual(m['cuts'][1], 3.0, delta=0.15)
        self.assertEqual(m['first_cut'], m['cuts'][0])
        self.assertEqual(len(m['beats']), 2, m)
        self.assertTrue(m['blank_start'])
        self.assertAlmostEqual(m['cuts_per_10s'], 3.3, delta=0.1)

    def test_not_blank(self):
        self.assertFalse(study.motion(study.frames_gray(self.plain))['blank_start'])

    def test_flash_is_one_cut(self):
        # black, one white frame, then gray: two big changes 0.1 s apart are one cut (a flash transition)
        frames = np.array([np.full((160, 90), v, np.float32) for v in [0] * 10 + [255] + [128] * 10])
        self.assertEqual(study.motion(frames)['cuts'], [1.0])

    def test_still_video_has_no_cuts(self):
        frames = np.full((30, 160, 90), 120, np.float32)
        m = study.motion(frames)
        self.assertEqual((m['cuts'], m['beats'], m['moving_share'], m['first_change']), ([], [], 0, None))

    def test_loudness(self):
        loud = study.loudness(study.audio(self.video))
        self.assertGreaterEqual(len(loud), 11)
        self.assertTrue(all(-30 < v < 0 for v in loud[1:-1]), loud)
        self.assertTrue(all(v < -100 for v in study.loudness(np.zeros(study.render.SR * 2, np.float32))))

    def test_measure_and_frames(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(study, 'transcribe', return_value=[(' Hi', 0.4, 0.6), (' there', 0.7, 1.0)]):
            m, words, frames = study.measure(self.video, tmp)
            self.assertEqual(m['speech_start'], 0.4)
            self.assertEqual(len(words), 2)
            times = [t for t, _ in frames]
            self.assertEqual(times[:3], [0.0, 0.5, 1.0])  # the first second is always shown
            self.assertTrue(any(abs(t - 4.0) < 0.2 for t in times), times)  # a second after every cut
            self.assertAlmostEqual(times[-1], 5.0, delta=0.1)  # and the ending
            self.assertTrue(all(p.exists() for _, p in frames))

    def test_fetch_local_file(self):
        path, meta = study.fetch(str(self.video), self.tmp.name)
        self.assertEqual(path, self.video)
        self.assertEqual(meta['title'], 'v')


class Pieces(unittest.TestCase):
    def test_sources_in(self):
        body = ('Look at https://youtube.com/shorts/abc123. And https://youtube.com/shorts/abc123 again,\n'
                '![img](https://github.com/user-attachments/assets/x.png) '
                'https://github.com/user-attachments/assets/1234-5678')
        self.assertEqual(study.sources_in(body), ['https://youtube.com/shorts/abc123',
                                                  'https://github.com/user-attachments/assets/1234-5678'])
        self.assertEqual(study.sources_in(None), [])

    def test_iso_seconds(self):
        self.assertEqual(study.iso_seconds('PT45S'), 45)
        self.assertEqual(study.iso_seconds('PT1M5S'), 65)
        self.assertEqual(study.iso_seconds('PT1H'), 3600)
        self.assertEqual(study.iso_seconds('P0D'), 0)

    def test_speech(self):
        words = [(' a', 0.5, 0.7), (' b', 0.8, 1.0), (' c', 2.5, 2.9), (' d', 3.5, 3.9)]
        s = study.speech(words, 5)
        self.assertEqual(s, {'speech_start': 0.5, 'words_per_second': 1.2, 'words_first_3s': 3, 'longest_pause': 1.5})
        self.assertEqual(study.speech([], 5)['speech_start'], None)

    def test_search_picks_outliers(self):
        def get(url, params=None, timeout=None):
            if url.endswith('/search'):
                data = {'items': [{'id': {'videoId': v}} for v in 'abcd']}
            elif url.endswith('/videos'):
                data = {'items': [
                    {'id': 'a', 'snippet': {'title': 'A', 'channelId': 'big', 'channelTitle': 'Big'},
                     'statistics': {'viewCount': '500000'}, 'contentDetails': {'duration': 'PT30S'}},
                    {'id': 'b', 'snippet': {'title': 'B', 'channelId': 'small', 'channelTitle': 'Small'},
                     'statistics': {'viewCount': '90000'}, 'contentDetails': {'duration': 'PT45S'}},
                    {'id': 'c', 'snippet': {'title': 'C', 'channelId': 'small', 'channelTitle': 'Small'},
                     'statistics': {'viewCount': '5000'}, 'contentDetails': {'duration': 'PT20S'}},  # too few views
                    {'id': 'd', 'snippet': {'title': 'D', 'channelId': 'small', 'channelTitle': 'Small'},
                     'statistics': {'viewCount': '900000'}, 'contentDetails': {'duration': 'PT4M'}}]}  # too long
            else:
                data = {'items': [{'id': 'big', 'statistics': {'subscriberCount': '1000000'}},
                                  {'id': 'small', 'statistics': {'subscriberCount': '2000'}}]}
            return SimpleNamespace(json=lambda: data)
        with mock.patch.object(study.requests, 'get', get):
            picks = study.search('q', top=5, key='k')
        self.assertEqual([p['title'] for p in picks], ['B', 'A'])  # 45x its channel beats 0.5x
        self.assertEqual(picks[0]['outlier'], 45.0)
        self.assertEqual(picks[0]['url'], 'https://www.youtube.com/shorts/b')

    def test_search_error(self):
        with mock.patch.object(study.requests, 'get', lambda *a, **k: SimpleNamespace(json=lambda: {'error': {'message': 'quota'}})):
            with self.assertRaisesRegex(RuntimeError, 'quota'):
                study.search('q', key='k')


def short(vid, views, days_ago=3, seconds=30, channel='chan'):
    from datetime import datetime, timedelta, timezone
    posted = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'id': vid, 'snippet': {'title': vid.upper(), 'channelId': channel, 'channelTitle': 'Chan', 'publishedAt': posted},
            'statistics': {'viewCount': str(views)}, 'contentDetails': {'duration': f'PT{seconds}S'}}


class Auto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(study, 'STUDIES', root), mock.patch.object(study, 'INDEX', root / 'index.jsonl'),
                        mock.patch.object(study, 'CHANNELS', root / 'channels.json')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_channel_outliers(self):
        videos = [short('a', 20000), short('b', 15000), short('c', 200000), short('old', 900000, days_ago=40),
                  short('long', 900000, seconds=600), short('d', 18000)]

        def get(url, params=None, timeout=None):
            data = {'channels': {'items': [{'contentDetails': {'relatedPlaylists': {'uploads': 'UU1'}}}]},
                    'playlistItems': {'items': [{'contentDetails': {'videoId': v['id']}} for v in videos]},
                    'videos': {'items': videos}}[url.rsplit('/', 1)[1]]
            return SimpleNamespace(json=lambda: data)
        with mock.patch.object(study.requests, 'get', get):
            picks = study.channel_outliers('chan', 'k')
        # usual (median of all its Shorts, old ones too) is 20,000: only c beats it twice among the recent ones
        self.assertEqual([p['url'] for p in picks], ['https://www.youtube.com/shorts/c'])
        self.assertEqual(picks[0]['outlier'], 10.0)

    def test_week_topics_rotate(self):
        a, b = study.week_topics(date(2026, 10, 4)), study.week_topics(date(2026, 10, 11))
        self.assertEqual(len(a), study.AUTO_TOPICS)
        self.assertTrue(set(a).isdisjoint(b))
        self.assertTrue(set(a) <= set(study.TOPICS))

    def pick(self, vid, outlier, channel, why='search "x"'):
        return {'url': f'https://www.youtube.com/shorts/{vid}', 'title': vid, 'channel': channel.title(),
                'channel_id': channel, 'views': 50000, 'followers': 1000, 'outlier': outlier, 'why': why}

    def test_auto_picks(self):
        study.INDEX.write_text(json.dumps({'source': 'https://www.youtube.com/shorts/seen'}) + '\n')
        study.CHANNELS.write_text(json.dumps({'watched': {'title': 'W', 'added': '2026-09-01', 'outlier': 9}}))
        found = [self.pick('seen', 99, 'x'), self.pick('big', 50, 'new'), self.pick('big2', 40, 'new'),
                 self.pick('small', 2, 'small')]
        with mock.patch.object(study, 'search', side_effect=[found, [], []]) as search, \
                mock.patch.object(study, 'channel_outliers', return_value=[self.pick('w1', 8, 'watched', 'channel')]) as co, \
                mock.patch.object(study, 'relevant', side_effect=lambda picks: picks):
            picks = study.auto_picks('k', date(2026, 10, 4), top=3)
        self.assertEqual(search.call_count, study.AUTO_TOPICS)
        co.assert_called_once_with('watched', 'k')
        self.assertEqual([p['title'] for p in picks], ['big', 'w1', 'small'])  # never seen, one per channel
        watch = json.loads(study.CHANNELS.read_text())
        self.assertEqual(set(watch), {'watched', 'x', 'new'})  # big outliers join; the 2x one does not

    def test_watchlist_is_capped(self):
        study.CHANNELS.write_text(json.dumps({f'c{i}': {'title': 't', 'added': f'2026-09-{i + 1:02d}', 'outlier': 5}
                                              for i in range(study.MAX_CHANNELS)}))
        with mock.patch.object(study, 'search', side_effect=[[self.pick('n', 30, 'newest')], [], []]), \
                mock.patch.object(study, 'channel_outliers', return_value=[]), \
                mock.patch.object(study, 'relevant', side_effect=lambda picks: picks):
            study.auto_picks('k', date(2026, 10, 4))
        watch = json.loads(study.CHANNELS.read_text())
        self.assertEqual(len(watch), study.MAX_CHANNELS)
        self.assertIn('newest', watch)
        self.assertNotIn('c0', watch)  # the oldest made room

    def test_off_topic_is_dropped(self):
        study.CHANNELS.write_text(json.dumps({'gaming': {'title': 'G', 'added': '2026-09-01', 'outlier': 30}}))
        found = [self.pick('dev', 20, 'dev'), self.pick('game', 90, 'games')]
        with mock.patch.object(study, 'search', side_effect=[found, [], []]), \
                mock.patch.object(study, 'channel_outliers', return_value=[self.pick('g1', 50, 'gaming', 'channel')]), \
                mock.patch.object(study, 'claude', return_value={'relevant': [1]}) as claude:
            picks = study.auto_picks('k', date(2026, 10, 4))
        self.assertIn('[2] game (channel: Games)', claude.call_args[0][0])
        self.assertEqual([p['title'] for p in picks], ['dev'])
        self.assertEqual(set(json.loads(study.CHANNELS.read_text())), {'dev'})  # the gaming channel left, games never joined

    def test_relevance_unavailable_keeps_all(self):
        found = [self.pick('a', 9, 'a'), self.pick('b', 8, 'b')]
        with mock.patch.object(study, 'claude', side_effect=RuntimeError('down')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(study.relevant(found), found)
        self.assertEqual(study.relevant([]), [])

    def test_digest_counts_itself(self):
        self.assertEqual(study.digest('.'), '')  # fewer than 3 studies: nothing to sum up
        study.INDEX.write_text(''.join(json.dumps({'source': f's{i}', 'title': f'T{i}', 'adoptable': ['p']}) + '\n'
                                       for i in range(4)))
        answer = {'summary': 'They open on the thing itself.', 'recurring': [
            {'pattern': 'Visual first', 'studies': [1, 2, 3, 3], 'for_us': 'Open on code.', 'test': 'Half open on code.'},
            {'pattern': 'Only once', 'studies': [2], 'for_us': '-', 'test': '-'},
            {'pattern': 'Made up', 'studies': [2, 99], 'for_us': '-', 'test': '-'}]}
        with mock.patch.object(study, 'claude', return_value=answer), mock.patch.object(study, 'ours', return_value=''):
            text = study.digest('.')
        self.assertIn('**Visual first** (in 3 of 4 studies)', text)
        self.assertNotIn('Only once', text)
        self.assertNotIn('Made up', text)  # a study number that does not exist is not counted

    def test_main_auto(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sys, 'argv', ['study.py', '--auto']), \
                mock.patch.dict(os.environ, {'YOUTUBE_API_KEY': 'k'}), mock.patch.object(study.render, 'OUT_DIR', Path(tmp)), \
                mock.patch.object(study, 'OUT', Path(tmp) / 'study.md'), \
                mock.patch.object(study.shutil, 'which', return_value='/usr/bin/ffmpeg'), \
                contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(study, 'auto_picks', return_value=[]):
                study.main()  # nothing new: no failure
            self.assertFalse((Path(tmp) / 'study.md').exists())
            with mock.patch.object(study, 'auto_picks', return_value=[self.pick('a', 9, 'c')]), \
                    mock.patch.object(study, 'study', return_value='# Study: a'), \
                    mock.patch.object(study, 'digest', side_effect=RuntimeError('claude down')):
                study.main()  # a failed digest keeps the studies
            self.assertIn('# Study: a', (Path(tmp) / 'study.md').read_text())
            with mock.patch.object(study, 'auto_picks', return_value=[self.pick('a', 9, 'c')]), \
                    mock.patch.object(study, 'study', return_value='# Study: a'), \
                    mock.patch.object(study, 'digest', return_value='# What keeps working for others\n'):
                study.main()
            self.assertTrue((Path(tmp) / 'study.md').read_text().startswith('# What keeps working'))
            self.assertEqual(len(list(study.STUDIES.glob('*-digest.md'))), 1)


class Breakdown(unittest.TestCase):
    METRICS = {'loudness': [-20.0], 'seconds': 6}

    def run_breakdown(self, *answers):
        calls = []

        def fake(prompt, folder):
            calls.append(prompt)
            return answers[len(calls) - 1]
        with mock.patch.object(study, 'claude', fake), mock.patch.object(study, 'ours', return_value='Our reels.'):
            return study.breakdown({'source': 's'}, self.METRICS, [(' Hi', 0.1, 0.3)], [(0.0, Path('f.jpg'))], '.'), calls

    def test_empty_fields(self):
        self.assertEqual(study.empty_fields(GOOD), [])
        bad = {**GOOD, 'first_second': 'placeholder', 'hook': {'spoken': 'placeholder', 'on_screen': '', 'type': 'TBD'},
               'structure': []}
        self.assertEqual(study.empty_fields(bad), ['first_second', 'hook.spoken', 'hook.on_screen', 'hook.type', 'structure'])
        self.assertEqual(study.empty_fields({**GOOD, 'hook': {**GOOD['hook'], 'spoken': 'no speech'}}), [])

    def test_good_answer_asked_once(self):
        a, calls = self.run_breakdown(GOOD)
        self.assertEqual((a, len(calls)), (GOOD, 1))
        self.assertIn('[0.1] Hi', calls[0])
        self.assertIn('0.0s: f.jpg', calls[0])
        self.assertIn('Our reels.', calls[0])

    def test_placeholder_asked_again(self):
        bad = {**GOOD, 'first_second': 'placeholder'}
        a, calls = self.run_breakdown(bad, GOOD)
        self.assertEqual((a, len(calls)), (GOOD, 2))
        self.assertIn('first_second', calls[1])

    def test_placeholder_twice_fails(self):
        bad = {**GOOD, 'pacing': 'placeholder'}
        with self.assertRaisesRegex(RuntimeError, 'pacing'):
            self.run_breakdown(bad, bad)

    def test_system_prompt_keeps_the_hard_rules(self):
        for words in ('faces', 'music', 'Reddit', 'never copy', 'placeholder'):
            self.assertIn(words, study.SYSTEM)


class Saving(unittest.TestCase):
    M = {'seconds': 6.0, 'width': 180, 'height': 320, 'cuts': [1.0, 3.0], 'first_cut': 1.0, 'cuts_per_10s': 3.3,
         'beats': [1.0, 3.0], 'beats_per_10s': 3.3, 'moving_share': 0.03, 'blank_start': True, 'first_change': 1.0,
         'speech_start': None, 'words_per_second': None, 'words_first_3s': 0, 'longest_pause': None}

    def test_report_and_save(self):
        meta = {'source': 'https://youtube.com/shorts/b', 'title': 'Fix It Fast!', 'channel': 'Small', 'views': 90000,
                'followers': 2000}
        text = study.report(meta, self.M, GOOD)
        for part in ('# Study: Fix It Fast!', '90,000 views', 'opens on a blank frame', '## First second',
                     'Said: Your build fails', '## What we could test', '**Open on the error itself**', 'Face to camera (no faces)'):
            self.assertIn(part, text)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(study, 'STUDIES', Path(tmp)), \
                mock.patch.object(study, 'INDEX', Path(tmp) / 'index.jsonl'):
            path = study.save(meta, self.M, GOOD, text, date(2026, 9, 29))
            study.save(meta, self.M, GOOD, text, date(2026, 9, 30))
            self.assertEqual(path.name, '2026-09-29-fix-it-fast.md')
            self.assertEqual(path.read_text(), text)
            rows = [json.loads(line) for line in (Path(tmp) / 'index.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), 2)  # appended, never rewritten
            self.assertEqual(rows[0]['adoptable'], ['Open on the error itself'])
            self.assertEqual(rows[0]['file'], '2026-09-29-fix-it-fast.md')

    def test_slug(self):
        self.assertEqual(study.slug('Claude Code: 3 tips!!'), 'claude-code-3-tips')
        self.assertEqual(study.slug(None), 'video')
        self.assertEqual(study.slug('???'), 'video')


class Main(unittest.TestCase):
    def run_main(self, argv, env, outcome):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sys, 'argv', ['study.py', *argv]), \
                mock.patch.dict(os.environ, env), mock.patch.object(study.render, 'OUT_DIR', Path(tmp)), \
                mock.patch.object(study, 'OUT', Path(tmp) / 'study.md'), mock.patch.object(study, 'study', outcome), \
                mock.patch.object(study.shutil, 'which', return_value='/usr/bin/ffmpeg'), \
                contextlib.redirect_stdout(io.StringIO()):
            code = 0
            try:
                study.main()
            except SystemExit as e:
                code = e.code
            out = (Path(tmp) / 'study.md').read_text() if (Path(tmp) / 'study.md').exists() else None
        return code, out

    def test_one_bad_link_does_not_stop_the_rest(self):
        def outcome(source, token, extra):
            if 'bad' in source:
                raise RuntimeError('could not download')
            return f'# Study: {source}'
        code, out = self.run_main(['--issue'], {'ISSUE_BODY': 'https://x.com/bad https://x.com/good'}, outcome)
        self.assertEqual(code, 0)
        self.assertIn('# Study: https://x.com/good', out)
        self.assertIn('**Could not study:**\n- https://x.com/bad', out)

    def test_all_failed_exits_1(self):
        code, out = self.run_main(['https://x.com/bad'], {}, mock.Mock(side_effect=RuntimeError('nope')))
        self.assertEqual(code, 1)
        self.assertIn('nope', out)

    def test_search_needs_a_key(self):
        code, _ = self.run_main(['--search', 'q'], {'YOUTUBE_API_KEY': ''}, mock.Mock())
        self.assertIn('YOUTUBE_API_KEY', str(code))

    def test_search_passes_what_it_knows(self):
        seen = []
        pick = {'url': 'u', 'title': 'T', 'channel': 'C', 'views': 20000, 'followers': 100, 'outlier': 20.0}
        with mock.patch.object(study, 'search', return_value=[pick]) as search:
            code, _ = self.run_main(['--search', 'claude code', '--top', '2'], {'YOUTUBE_API_KEY': 'k'},
                                    lambda s, t, extra: seen.append((s, extra)) or 'ok')
        self.assertEqual(code, 0)
        search.assert_called_once_with('claude code', 2, 'k')
        self.assertEqual(seen, [('u', {'title': 'T', 'channel': 'C', 'views': 20000, 'followers': 100})])


if __name__ == '__main__':
    unittest.main(verbosity=2 if '-v' in sys.argv else 1, argv=[sys.argv[0]])
