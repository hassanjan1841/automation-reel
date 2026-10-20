"""Tests for motion.py: the code-morph token plan, each template reads only fields its spec has, and a real render
of every animation template in headless Chromium (transparent frames, a sane length, a settle frame inside it, sounds
the sound kit knows, nothing left outside the box), plus the frame-0 rule for the two that may sit under a hook and
readable labels on the light theme; the build visual drawn stage by stage, and the closing card's keyword; and the
look (`Look`): the living background, code drawn without ligatures, titles rising out of their line, captions with
no box; and a real stage reel (`Stage`).

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


class PaletteRules(unittest.TestCase):
    def test_pick_must_be_a_real_item_that_scrolls_into_view(self):
        import generate
        ok = dict(motion.EXAMPLES['palette'])
        self.assertEqual(generate.motion_errors(1, ok), [])
        for bad in ({**ok, 'pick': 'not-a-component'}, {**ok, 'pick': ok['items'][0]}, {**ok, 'items': ok['items'][:3]},
                    {**ok, 'chips': ['x'] * 7}):
            self.assertEqual(len(generate.motion_errors(1, bad)), 1, bad)


class Review(unittest.TestCase):
    def test_every_animation_is_described_to_the_reviewer(self):
        # New types once fell through to "a screenshot of", so the frame review judged them against the wrong thing.
        import qa
        for kind in motion.TYPES:
            self.assertFalse(qa.describe(motion.EXAMPLES[kind]).startswith('a screenshot of'), kind)


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


class Prepare(unittest.TestCase):
    def test_inspect_gets_highlighted_tokens_and_empty_lists_default(self):
        spec = motion.prepare(dict(motion.EXAMPLES['inspect']), 980)
        self.assertEqual(len(spec['tokens']), len(spec['code'].split('\n')))
        self.assertEqual(motion.prepare({'type': 'variants'}, 980)['marks'], [])
class WallRules(unittest.TestCase):
    def test_wall_validation(self):
        import generate
        ok = dict(motion.EXAMPLES['wall'])
        self.assertEqual(generate.motion_errors(1, ok), [])
        for bad in ({**ok, 'tiles': ['a', 'b']}, {**ok, 'tiles': ['x' * 15] * 3}, {**ok, 'stats': ok['stats'][:1]},
                    {**ok, 'stats': [{'value': -1, 'label': 'x'}] * 2}, {**ok, 'stats': [{'value': 5, 'label': 'x', 'suffix': 'abcd'}] * 2},
                    {**ok, 'stats': [{'value': '5', 'label': 'x'}] * 2}):
            self.assertEqual(len(generate.motion_errors(1, bad)), 1, bad)
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

    def test_layout_fills_and_centres_the_box(self):
        # A hidden sweep bar parked outside the box once made the fit shrink command and palette to half width, pushed
        # to the right; the visible layout must be centred and use most of one side of the box.
        for kind, (folder, meta) in self.out.items():
            frames = sorted(folder.glob('*.png'))
            alpha = np.asarray(Image.open(frames[-1]).convert('RGBA'))[..., 3] > 64
            ys, xs = np.nonzero(alpha)
            w, h = (xs.max() - xs.min()) / alpha.shape[1], (ys.max() - ys.min()) / alpha.shape[0]
            self.assertLess(abs((xs.max() + xs.min()) / 2 / alpha.shape[1] - 0.5), 0.08, kind)
            self.assertGreater(max(w, h), 0.45, (kind, round(w, 2), round(h, 2)))

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

    def test_predict_stamps_the_chip_that_matches_the_output(self):
        # The example's output "A C B" is the right-hand chip: green lands only there, after the countdown, and the
        # left chip is struck through in red. Nothing green on the chips at settle: the answer is never given away.
        folder, meta = self.out['predict']
        frames = sorted(folder.glob('*.png'))

        def marks(f):
            a = np.asarray(Image.open(f).convert('RGBA')).astype(int)
            r, g, b, seen = a[..., 0], a[..., 1], a[..., 2], a[..., 3] > 200
            xs_g = np.nonzero(seen & (g - np.maximum(r, b) > 60))[1] / a.shape[1]
            xs_r = np.nonzero(seen & (r - np.maximum(g, b) > 80))[1] / a.shape[1]
            return (xs_g > 0.55).sum(), ((xs_g > 0.2) & (xs_g < 0.45)).sum(), (xs_r < 0.5).sum()
        start, end = marks(frames[round(meta['settle'] * motion.FPS)]), marks(frames[-1])
        self.assertEqual(start[0], 0)
        self.assertGreater(end[0], 1000)
        self.assertLess(end[1], 50)
        self.assertGreater(end[2], start[2] + 1000)

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


class Look(unittest.TestCase):
    """The premium look: a living background, code drawn as typed, titles rising out of their line, captions with
    no box."""

    def test_background_moves_slowly_and_hands_out_fresh_arrays(self):
        bg = render.Background(render.THEMES['dark'])
        a, b = bg.at(0.0), bg.at(1 / render.FPS)
        self.assertTrue(np.array_equal(a, b))        # refreshed every few frames, reused in between
        a[:] = 0
        self.assertGreater(bg.at(0.0).mean(), 5)     # drawing on a frame never touches the cache
        later = bg.at(6.0)
        self.assertGreater(np.abs(later - bg.at(0.0)).max(), 3)   # it moves
        self.assertLess(np.abs(bg.at(3 / render.FPS) - bg.at(0.0)).max(), 6)   # but slowly
        self.assertTrue(np.array_equal(render.make_background(render.THEMES['dark']), bg.at(0.0)))

    def test_code_is_drawn_as_typed(self):
        import visuals
        from PIL import ImageDraw
        f = visuals.mono(40)
        for pair in ('=>', '<=', '!=', '->'):
            whole, parts = Image.new('L', (200, 80)), Image.new('L', (200, 80))
            ImageDraw.Draw(whole).text((10, 10), pair, font=f, fill=255)
            d = ImageDraw.Draw(parts)
            d.text((10, 10), pair[0], font=f, fill=255)
            d.text((10 + f.getlength(pair[0]), 10), pair[1], font=f, fill=255)
            self.assertTrue(np.array_equal(np.asarray(whole), np.asarray(parts)), pair)
        self.assertIn('font-variant-ligatures:none', motion.PAGE)

    def test_title_word_rises_out_of_its_line(self):
        mask = np.ones((40, 60), dtype=np.float32)
        el = render.El(mask, np.full(3, 255.0, dtype=np.float32), 100, 200, 0.0, dur=0.4, rise=44, clip=240)
        early = np.zeros((render.H, render.W, 3), dtype=np.float32)
        render.draw_element(early, el, 0.05)
        self.assertGreater(early.max(), 0)
        self.assertEqual(early[240:].max(), 0)        # nothing below the line's bottom edge
        done = np.zeros_like(early)
        render.draw_element(done, el, 1.0)
        self.assertGreater(done[200:240, 100:160].min(), 250)   # fully in place once it lands

    def test_cards_glow_and_the_marked_line_takes_focus(self):
        import visuals
        spec = {'type': 'code', 'language': 'python', 'code': 'a = 1\nb = 2\nc = 3\nd = 4', 'highlight': [1]}
        card = visuals.build(spec, render.THEMES['dark'], (90, 600, 900, 700))
        self.assertIsNotNone(card.glow)
        frame = np.zeros((render.H, render.W, 3), dtype=np.float32)
        card.draw(frame, 3.0, 1.0, 0)
        self.assertGreater(frame[card.y + card.h + 20, card.x + card.w // 2].max(), 2)   # light below the card
        (b0, b1), (a0, a1) = card.rows[0], card.rows[3]   # the marked line, and one clear of its circle
        before, after = card.layer(card.settle)[0], card.layer(3.0)[0]
        ink = lambda img, y0, y1: np.abs(img[y0:y1, 40:-40] - visuals.BG).mean()
        self.assertLess(ink(after, a0, a1), ink(before, a0, a1) * 0.6)    # other lines step back
        self.assertGreaterEqual(ink(after, b0, b1), ink(before, b0, b1))  # the marked line does not

    def test_captions_have_no_box(self):
        class Voice(list):
            continuous = True
        voice = Voice([np.zeros(render.SR * 3)])
        voice.words = [[('Hello', 0.0, 0.4), ('world', 0.5, 0.9)]]
        slide = render.Slide('hook', 0.0, 3.0)
        caps = render.Captions(voice, [slide], render.THEMES['dark'])
        frame = np.full((render.H, render.W, 3), 40.0, dtype=np.float32)
        caps.draw(frame, render.VOICE_LEAD + 0.7)
        changed = np.abs(frame - 40).max(axis=2) > 1
        rows = np.where(changed.any(axis=1))[0]
        self.assertTrue(len(rows))
        band = changed[rows.min():rows.max() + 1]
        cols = np.where(band.any(axis=0))[0]
        # Halos fade out: the corners of the caption's band stay background, where a box would have filled them.
        self.assertFalse(band[:4, :8].any() or band[-4:, -8:].any())
        self.assertLess(band.mean(), 0.85)
        accent = np.abs(frame - render.rgb(render.THEMES['dark']['accent'])).max(axis=2) < 8
        self.assertTrue(accent.any())                 # the spoken word sits on the accent pill
        self.assertGreater(cols.max() - cols.min(), 150)


class Stage(unittest.TestCase):
    """A real stage reel (stage.py) rendered in Chromium with a silent stand-in voice: the whole length, a sound
    track, the hook complete on frame 0, and the scenes moving."""

    def test_renders_a_stage_reel(self):
        import subprocess
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'tests'))
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from e2e_publish import silent_voice
        from test_learn import STAGED
        reel = {**STAGED, 'id': 99901}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'stage.mp4'
            path, slides = render.render_reel(reel, out_path=out, voice=silent_voice(reel['voiceover']))
            self.assertEqual([s.visual.spec['type'] for s in slides],
                             ['stage-code', 'stage-file', 'stage-steps', 'stage-docs', 'stage-words'])
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                                    '-of', 'json', str(path)], capture_output=True, text=True, check=True).stdout
            import json
            info = json.loads(probe)
            self.assertAlmostEqual(float(info['format']['duration']), slides[-1].end, delta=0.25)
            self.assertEqual(sorted(x['codec_type'] for x in info['streams']), ['audio', 'video'])
            frames = []
            for t in (0.0, slides[2].start + 1.5, slides[-1].end - 0.4):
                png = Path(tmp) / f'{t:.2f}.png'
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(path), '-frames:v', '1',
                                str(png)], check=True)
                frames.append(np.asarray(Image.open(png).convert('L'), dtype=np.float32))
            zero, chapter, last = frames
            self.assertGreater((zero[244:330] > 200).sum(), 2000)      # the hook's words, white, on frame 0
            self.assertGreater((zero[560:1440] > 120).sum(), 5000)     # its proof (the code card) already in place
            self.assertGreater(chapter.mean(), zero.mean() + 60)        # the light chapter
            self.assertLess(np.abs(last - zero).mean(), 25)             # it glides back to the opening for the loop


if __name__ == '__main__':
    unittest.main(verbosity=2 if '-v' in sys.argv else 1, argv=[sys.argv[0]])
