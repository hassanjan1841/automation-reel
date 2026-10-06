"""Tests for motion.py: the code-morph token plan, each template reads only fields its spec has, and a real render
of every animation template in headless Chromium (transparent frames, a sane length, a settle frame inside it, sounds
the sound kit knows, nothing left outside the box), plus the frame-0 rule for the two that may sit under a hook and
readable labels on the light theme; the build visual drawn stage by stage, and the closing card's keyword.

Needs playwright with Chromium, pygments and the fonts (render.py --fonts; JetBrains Mono downloads on first use);
CI installs them in the "motion" job. Without playwright the renders are skipped. E2E_CHROMIUM=<path> overrides the
browser, as in tests/e2e_publish.py.

Usage: python test_motion.py        exit 1 on any failure
       python test_motion.py -v     one line per test
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

import re

import motion
import render

SOUNDS = {'key', 'tick', 'pop', 'click', 'swish', 'air', 'thud', 'scribble'}  # render.sound_kit


class MorphPlan(unittest.TestCase):
    def test_unchanged_tokens_glide_and_changes_are_marked(self):
        toks, removed, added = motion.morph_plan('const user = res.json()\nreturn user',
                                                 'const user = await res.json()\nreturn user', 'ts')
        glide = {t['text']: (t['from'], t['to']) for t in toks if t['from'] and t['to']}
        # Tokens are the highlighter's (res . json ( )): each glides right by the 6 columns "await " takes.
        self.assertEqual(glide['res'], ([0, 13], [0, 19]))
        self.assertEqual(glide['json'], ([0, 17], [0, 23]))
        self.assertEqual(glide['return'], ([1, 0], [1, 0]))
        new = [t for t in toks if t['from'] is None]
        self.assertEqual([t['text'] for t in new], ['await'])
        self.assertEqual((removed, added), ([], [0]))

    def test_removed_lines(self):
        toks, removed, added = motion.morph_plan('a()\nb()', 'a()', 'js')
        self.assertEqual(removed, [1])
        self.assertTrue(any(t['text'] == 'b' and t['to'] is None for t in toks))

    def test_tokens_keep_indentation(self):
        lines = motion.tokens('if x:\n    y = 1', 'py')
        self.assertEqual(''.join(t for t, _ in lines[1]), '    y = 1')


class Typography(unittest.TestCase):
    def test_glyph_outlines_are_laid_out_per_glyph(self):
        g = motion.glyph_outlines(['Hi *you*', 'ok'], 800)
        self.assertEqual(len(g['glyphs']), 7)  # spaces have no outline
        self.assertEqual([x['hl'] for x in g['glyphs']], [False, False, True, True, True, False, False])
        self.assertEqual([x['word'] for x in g['glyphs']], [0, 0, 1, 1, 1, 2, 2])
        self.assertEqual([x['line'] for x in g['glyphs']], [0] * 5 + [1] * 2)
        self.assertTrue(all(x['d'].startswith('M') and 'Z' in x['d'] and 1 <= len(x['anchors']) <= 3
                            for x in g['glyphs']))
        self.assertLessEqual(g['gw'], 800.5)
        self.assertEqual(g, motion.glyph_outlines(['Hi *you*', 'ok'], 800))

    def test_highlight_marks_only_the_starred_word(self):
        g = motion.glyph_outlines(['a *b* c'], 600)
        self.assertEqual([x['hl'] for x in g['glyphs']], [False, True, False])

    def test_dot_raster_is_a_grid_of_dots_and_deterministic(self):
        d = motion.dot_raster('IO*1*')
        self.assertEqual(d, motion.dot_raster('IO*1*'))
        self.assertGreaterEqual(d['rows'], 9)
        self.assertTrue(d['dots'] and all(0 <= c < d['cols'] and 0 <= r < d['rows'] for c, r, _ in d['dots']))
        self.assertEqual(len({(c, r) for c, r, _ in d['dots']}), len(d['dots']))
        hl = [c for c, _, on in d['dots'] if on]
        self.assertTrue(hl and min(hl) > d['cols'] // 2)  # only the trailing 1 is highlighted
        self.assertGreater(motion.dot_raster('WIDE')['cols'], motion.dot_raster('I')['cols'])

    def test_prepare_adds_the_computed_data(self):
        self.assertTrue(motion.prepare(motion.EXAMPLES['drawn'], 980)['glyphs'])
        spec = motion.prepare(motion.EXAMPLES['dots'], 980)
        self.assertTrue(spec['dots'] and isinstance(spec['seed'], int))


class Fields(unittest.TestCase):
    def test_templates_read_only_fields_their_spec_has(self):
        # The race once printed "Source: undefined" on every reel: it read S.head_host, prepare() sets source_host.
        starts = [(m.start(), m.group(1)) for m in re.finditer(r'^T\.(\w+) = ', motion.PAGE, re.M)
                  if m.group(1) in motion.TYPES]
        for i, (at, kind) in enumerate(starts):
            body = motion.PAGE[at:starts[i + 1][0] if i + 1 < len(starts) else len(motion.PAGE)]
            spec = motion.prepare(dict(motion.EXAMPLES[kind]), 980)
            self.assertEqual(set(re.findall(r'\bS\.(\w+)', body)) - set(spec), set(), kind)


class Render(unittest.TestCase):
    """Every template rendered for real, once, at a small size."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import BrowserType
        except ImportError:
            raise unittest.SkipTest('playwright is not installed')
        cls.tmp = tempfile.mkdtemp()
        cls.patches = [mock.patch.object(motion, 'FRAMES', Path(cls.tmp))]
        if os.environ.get('E2E_CHROMIUM'):
            launch = BrowserType.launch
            cls.patches.append(mock.patch.object(BrowserType, 'launch', lambda self, **k: launch(
                self, **{'executable_path': os.environ['E2E_CHROMIUM'], **k})))
        for p in cls.patches:
            p.start()
        cls.out = {}
        for kind in motion.TYPES:
            cls.out[kind] = motion.render_motion(motion.EXAMPLES[kind], render.THEMES['dark'], (980, 900))
        cls.light = motion.render_motion(motion.EXAMPLES['race'], render.THEMES['light'], (980, 900))

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_template_renders(self):
        self.assertEqual(set(self.out), set(motion.TYPES))
        for kind, (folder, meta) in self.out.items():
            frames = sorted(folder.glob('*.png'))
            self.assertTrue(2.5 <= meta['duration'] <= motion.MAX_SECONDS, (kind, meta['duration']))
            self.assertEqual(len(frames), round(meta['duration'] * motion.FPS), kind)
            self.assertTrue(0 <= meta['settle'] < meta['duration'], kind)
            self.assertTrue(meta['sounds'] and {k for _, k in meta['sounds']} <= SOUNDS, (kind, meta['sounds']))
            self.assertTrue(all(0 <= t <= meta['duration'] for t, _ in meta['sounds']), kind)

    def test_frames_are_transparent_and_drawn(self):
        for kind, (folder, meta) in self.out.items():
            frames = sorted(folder.glob('*.png'))
            last = np.asarray(Image.open(frames[-1]).convert('RGBA'))
            self.assertEqual(last.shape[:2], (900, 980), kind)
            alpha = last[..., 3]
            drawn = (alpha > 64).mean()  # clearly visible pixels, not the soft edge of a shadow
            self.assertTrue(0.02 < drawn < 0.97, (kind, drawn))
            self.assertTrue(alpha[0, -1] < 8 and alpha[-1, 0] < 8, kind)  # the corners stay see-through

    def test_motion_happens(self):
        for kind, (folder, meta) in self.out.items():
            frames = sorted(folder.glob('*.png'))
            start = round(meta['settle'] * motion.FPS)
            first = np.asarray(Image.open(frames[min(len(frames) - 1, start)]), dtype=np.int16)
            # Something visibly changes after the layout settles (an example may end where it began).
            changed = max((np.abs(np.asarray(Image.open(f), dtype=np.int16) - first).max(axis=2) > 40).mean()
                          for f in frames[start::8])
            self.assertGreater(changed, 0.002, kind)

    def test_text_on_the_background_follows_the_theme(self):
        # Labels drawn straight on a light reel must be dark ink; they were near-white and vanished (2026-10-01).
        folder, _ = self.light
        last = np.asarray(Image.open(sorted(folder.glob('*.png'))[-1]).convert('RGBA'), dtype=np.int16)
        ink = (last[..., 3] > 160) & (last[..., :3].max(axis=2) < 70)
        self.assertGreater(ink.mean(), 0.002)

    def test_hook_proofs_are_whole_at_settle(self):
        # morph and stepper may sit under a hook from frame 0: at their settle frame the code is already there.
        for kind in ('morph', 'stepper'):
            folder, meta = self.out[kind]
            frames = sorted(folder.glob('*.png'))
            at = np.asarray(Image.open(frames[round(meta['settle'] * motion.FPS)]).convert('RGBA'))[..., 3]
            end = np.asarray(Image.open(frames[-1]).convert('RGBA'))[..., 3]
            self.assertGreater((at > 0).mean(), 0.7 * (end > 0).mean(), kind)


class Cards(unittest.TestCase):
    """The build visual (the real page drawn while its CSS is typed in) and the closing card's keyword."""
    BUILD = {'type': 'build', 'title': 'button.css', 'html': '<button class="buy">Buy now</button>',
             'stages': ['.buy {\n  padding: 18px 44px;\n  border: 0;\n}', '.buy {\n  background: #4f46e5;\n  color: #fff;\n}']}

    def test_build_draws_each_stage_for_real(self):
        import importlib.util
        if not importlib.util.find_spec('playwright'):
            self.skipTest('playwright is not installed')
        import visuals
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(visuals, 'BUILDS', Path(tmp)):
            card = visuals.build(self.BUILD, render.THEMES['dark'], (90, 600, 900, 700))
            self.assertIsInstance(card, visuals.Build)
            card.duration = 5.0
            plain, styled, done = card.shots
            # Each stage changes what the browser draws; the finished button is the brand colour.
            self.assertGreater(np.abs(styled - plain).mean(), 0.5)
            self.assertGreater(np.abs(done - styled).mean(), 0.5)
            self.assertTrue((np.abs(done - np.array([0x4f, 0x46, 0xe5])).sum(axis=2) < 30).any())
            first, last = card.layer(card.settle)[0], card.layer(card.final_at() - 0.05)[0]
            page = slice(card.bar, card.preview_h - 3)  # above the accent line between page and code
            self.assertLess(np.abs(first[page] - plain[:-3]).mean(), 1)
            # Frame 0 of a hook: the plain page and its markup, no CSS typed yet.
            html = card.codes[0][0]
            self.assertLess(np.abs(first[card.preview_h:card.preview_h + len(html)] - html[:card.h - card.preview_h]).mean(), 1)
            self.assertLess(np.abs(last[page] - done[:-3]).mean(), 1)
            self.assertEqual([k for _, k in card.sounds].count('pop'), 2)
            # It ends on the finished page above all of its CSS, to screenshot; a short slide skips that view.
            self.assertLess(np.abs(card.layer(4.9)[0] - card.final).mean(), 1)
            card.duration = 3.0
            self.assertIsNone(card.final_at())

    def test_the_closing_card_shows_the_keyword(self):
        import voice
        reel = {'style': 'dark', 'kicker': 'Dev tip', 'hook': 'Your *cache* serves old data',
                'points': [{'title': 'Reads hit cache', 'body': 'Reads go to the cache.'}] * 3,
                'cta': 'Comment *REDIS* for the code', 'dm_keyword': 'REDIS'}
        clips = voice.Voiceover([np.zeros(render.SR, np.float32)] * 5, [[('w', 0.1, 0.3)]] * 5, True)
        slides, _ = render.build_slides(reel, clips)
        without, _ = render.build_slides({k: v for k, v in reel.items() if k != 'dm_keyword'}, clips)
        biggest = lambda s: max(e.mask.shape[0] for e in s.elements)
        self.assertGreater(biggest(slides[-1]), biggest(without[-1]) * 1.5)


if __name__ == '__main__':
    unittest.main(verbosity=2 if '-v' in sys.argv else 1, argv=[sys.argv[0]])
