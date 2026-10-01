"""Tests for motion.py: the code-morph token plan, each template reads only fields its spec has, and a real render
of every animation template in headless Chromium (transparent frames, a sane length, a settle frame inside it, sounds
the sound kit knows, nothing left outside the box), plus the frame-0 rule for the two that may sit under a hook and
readable labels on the light theme.

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


if __name__ == '__main__':
    unittest.main(verbosity=2 if '-v' in sys.argv else 1, argv=[sys.argv[0]])
