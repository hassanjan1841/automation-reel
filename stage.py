"""Stage reels: the whole reel drawn as one animated page in headless Chromium, in the style of the explainers the
creator picked as the bar (director.md): the spoken sentence builds up word by word at the top (the word being said
bright, earlier words grey, stressed words in the serif italic, the key word in a "selected text" box), one real
object per slide in the middle (a file, code typing itself, a docs quote highlighted on its word, ordered steps
lighting up, a counter, bars, a terminal, a repo card, big words), every move landing on a spoken word, new cards
arriving sharp while old ones blur and sink back, and at most one light chapter.

A reel becomes a stage reel when it has `scenes`: one scene per slide (hook, each point, call to action), each one
kind from KINDS (validated by scene_errors). render.render_reel hands such a reel here after build_slides has timed
the slides to the voice. The page is a pure function of time (window.renderAt(t)), so every frame is exact.

Usage: python stage.py <id>     render out/reel-<id>.mp4 from reels.json with a silent stand-in voice (layout check)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import render

KINDS = ('file', 'code', 'edit', 'docs', 'steps', 'checklist', 'counter', 'bars', 'terminal', 'repo', 'words')
HOOK_KINDS = ('file', 'code', 'docs', 'terminal', 'repo', 'counter')  # complete on frame 0, like a hook_visual
CSS_W, CSS_H = render.W // 2, render.H // 2
MAX_CODE_LINES, MAX_CODE_COLS = 10, 38
MOTIFS = ('wave', 'brackets', 'rings')   # abstract shapes a words scene may pulse behind its words
EDIT_COLS = 34          # an edit scene's lines, before and after the edit
TYPE_STEP = 0.06        # seconds per typed character in an edit scene
LINE_WORDS = 9            # a caption group closes at a sentence end or after this many words
RETURN = 1.0              # the last seconds glide back to the opening scene, so a replay continues seamlessly
CHAPTER = 0.6             # seconds a chapter card ("02 TOOLBOX") holds the stage before its scene arrives
LAND = 1.9                # a scene's main move lands at least this long before its slide ends, so the result holds
                          # still for a screenshot and the frame review sees it complete (director.md, section 1)
JPEG_QUALITY = 92
# Frames are drawn by several browsers at once (RENDER_WORKERS; default one per CPU core, at most 4). The page is a
# pure function of time, so frame f comes out the same from any of them. Chromium paints in tiles, and under that
# load a screenshot taken straight after drawing could keep one tile of the previous frame (seen 2026-10-23), so
# each frame waits two display frames before its screenshot.
SETTLE = 'window.renderAt(%r); new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))'
AHEAD = 48                # frames a browser may draw ahead of the encoder, to bound memory


# ---------- validation ----------

def _norm(word):
    return re.sub(r"[^\w']", '', word.lower())


def _text(scene):
    """Everything a scene shows as text, for checks that a phrase is on it."""
    kind = scene.get('kind')
    if kind == 'file':
        return '\n'.join(map(str, scene.get('lines') or []))
    if kind == 'code':
        return str(scene.get('code', ''))
    if kind == 'edit':
        return '\n'.join(edited(scene)[0] + edited(scene)[1])
    if kind == 'docs':
        return str(scene.get('text', ''))
    if kind == 'terminal':
        return '\n'.join([str(scene.get('command', ''))] + [str(x) for x in scene.get('output') or []])
    if kind == 'steps':
        return '\n'.join(str(i.get('label', '')) for i in scene.get('items') or [] if isinstance(i, dict))
    if kind == 'words':
        return '\n'.join(str(x).replace('*', '') for x in scene.get('lines') or [])
    if kind == 'checklist':
        return '\n'.join(str(i.get('label', '')) for i in scene.get('items') or [] if isinstance(i, dict))
    if kind == 'repo':
        return f"{scene.get('name', '')}\n{scene.get('description', '')}"
    return ''


def edited(scene):
    """An edit scene's lines before and after its edit, worked out here rather than written by the writer, so the
    result on screen is what the keys really do: one press of the key per match of `find` (each adds a cursor), then
    `typed` is typed once and lands at every cursor."""
    lines = [str(x) for x in scene.get('lines') or []]
    find, typed = str(scene.get('find') or ''), str(scene.get('typed') or '')
    return lines, [x.replace(find, typed) if find else x for x in lines]


def matches(scene):
    """(line, column) of each match of `find`, in the order the key selects them."""
    find = str(scene.get('find') or '')
    out = []
    for r, line in enumerate(str(x) for x in scene.get('lines') or []):
        c = line.find(find) if find else -1
        while c >= 0:
            out.append((r, c))
            c = line.find(find, c + len(find))
    return out


def _short(v, n):
    return isinstance(v, str) and 0 < len(v.strip()) <= n


def scene_errors(reel):
    """What is wrong with a reel's scenes, as messages for the writer; [] when they can be drawn honestly."""
    scenes = reel.get('scenes')
    if scenes is None:
        return []
    want = 2 + len(reel.get('points') or [])
    if not isinstance(scenes, list) or len(scenes) != want:
        return [f'scenes: needs exactly {want}, one per slide (hook, each point, cta)']
    sources = set(reel.get('sources') or [])
    import voice
    spoken = [voice.strip_cues(line) for line in (reel.get('voiceover') or [])]
    errors, light, accent = [], 0, 0
    points = len(reel.get('points') or [])
    for i, s in enumerate(scenes):
        where = f'scenes[{i}]'
        if not isinstance(s, dict) or s.get('kind') not in KINDS:
            errors.append(f'{where}: kind must be one of {", ".join(KINDS)}')
            continue
        kind = s['kind']
        if i == 0 and kind not in HOOK_KINDS:
            errors.append(f'{where}: the hook scene must show its proof from frame 0: one of {", ".join(HOOK_KINDS)}')
        if kind == 'file':
            lines = s.get('lines')
            if not _short(s.get('title'), 40) or not isinstance(lines, list) or not 1 <= len(lines) <= 7 \
                    or not all(_short(x, 40) for x in lines):
                errors.append(f'{where}: file needs a title and 1 to 7 lines of at most 40 characters')
        elif kind == 'code':
            code = str(s.get('code') or '').rstrip('\n')
            rows = code.split('\n')
            if not code or len(rows) > MAX_CODE_LINES or max(len(r) for r in rows) > MAX_CODE_COLS:
                errors.append(f'{where}: code needs 1 to {MAX_CODE_LINES} lines of at most {MAX_CODE_COLS} columns')
            if not _short(s.get('title'), 40):
                errors.append(f'{where}: code needs a title (the file name)')
            if any(not isinstance(n, int) or not 1 <= n <= len(rows) for n in s.get('highlight') or []):
                errors.append(f'{where}: highlight lists line numbers of the code')
        elif kind == 'edit':
            lines, after = edited(s)
            if not _short(s.get('title'), 40) or not isinstance(s.get('lines'), list) or not 2 <= len(lines) <= 7 \
                    or not all(isinstance(x, str) and len(x) <= EDIT_COLS for x in s['lines']):
                errors.append(f'{where}: edit needs a title and 2 to 7 lines of at most {EDIT_COLS} characters')
            elif not _short(s.get('find'), 20) or not 2 <= len(matches(s)) <= 8:
                errors.append(f'{where}: edit needs find (at most 20 characters) appearing 2 to 8 times in its lines')
            elif not isinstance(s.get('typed'), str) or len(s['typed']) > 20 or s['typed'] == s['find'] \
                    or any(len(x) > EDIT_COLS for x in after):
                errors.append(f'{where}: edit needs typed (at most 20 characters, not the same as find) and its lines '
                              f'must stay within {EDIT_COLS} characters after the edit')
            if s.get('key') is not None and not _short(s.get('key'), 14):
                errors.append(f'{where}: edit key is the shortcut, at most 14 characters, like Ctrl+D')
        elif kind == 'docs':
            text, mark = str(s.get('text') or ''), str(s.get('mark') or '')
            if s.get('url') not in sources:
                errors.append(f'{where}: docs url must be one of the reel\'s sources (the page the quote is from)')
            if not _short(s.get('title'), 50) or not 20 <= len(text) <= 240:
                errors.append(f'{where}: docs needs the page title and its exact text (20 to 240 characters)')
            if not mark or mark not in text or len(mark) > 60:
                errors.append(f'{where}: docs mark must be a phrase of the text (at most 60 characters)')
        elif kind == 'steps':
            items = s.get('items')
            if not isinstance(items, list) or not 2 <= len(items) <= 4 \
                    or not all(isinstance(x, dict) and _short(x.get('label'), 14) for x in items):
                errors.append(f'{where}: steps needs 2 to 4 items with a label of at most 14 characters')
            stop = s.get('stop')
            if stop is not None and not (isinstance(stop, dict) and _short(stop.get('request'), 24)
                                         and _short(stop.get('result'), 12) and isinstance(stop.get('at'), int)
                                         and isinstance(items, list) and 0 <= stop['at'] < len(items)):
                errors.append(f'{where}: steps stop needs request (24 chars), result (12 chars) and at (an item index)')
        elif kind == 'checklist':
            items = s.get('items')
            if not _short(s.get('title'), 40) or not isinstance(items, list) or not 2 <= len(items) <= 5 or not all(
                    isinstance(x, dict) and _short(x.get('label'), 28) and isinstance(x.get('ok'), bool) for x in items):
                errors.append(f'{where}: checklist needs a title and 2 to 5 items, each a label (28 chars) and ok '
                              '(true when that check really passes in what the reel shows)')
        elif kind == 'counter':
            if not isinstance(s.get('value'), (int, float)) or s['value'] < 0 or not _short(s.get('label'), 40):
                errors.append(f'{where}: counter needs a real value (a number) and a label')
            if s.get('source') not in sources:
                errors.append(f'{where}: counter source must be one of the reel\'s sources')
        elif kind == 'bars':
            items = s.get('items')
            if not isinstance(items, list) or not 2 <= len(items) <= 5 or not all(
                    isinstance(x, dict) and _short(x.get('label'), 16) and isinstance(x.get('value'), (int, float))
                    and x['value'] >= 0 for x in items):
                errors.append(f'{where}: bars needs 2 to 5 items with a label (16 chars) and a value')
            if not _short(s.get('title'), 40):
                errors.append(f'{where}: bars needs a title')
            if not s.get('illustration') and s.get('source') not in sources:
                errors.append(f'{where}: bars needs a source from the reel\'s sources, or illustration: true')
        elif kind == 'terminal':
            out = s.get('output')
            if not _short(s.get('command'), 40) or not isinstance(out, list) or not 1 <= len(out) <= 6 \
                    or not all(isinstance(x, str) and len(x) <= 40 for x in out):
                errors.append(f'{where}: terminal needs a command (40 chars) and 1 to 6 real output lines (40 chars)')
        elif kind == 'repo':
            if not re.fullmatch(r'[\w.-]+/[\w.-]+', str(s.get('name') or '')) or not _short(s.get('description'), 90):
                errors.append(f'{where}: repo needs name as owner/repo and a description (90 chars)')
            if not isinstance(s.get('stars'), int) or s['stars'] < 0:
                errors.append(f'{where}: repo stars must be its real star count (a whole number)')
            if s.get('url') not in sources:
                errors.append(f'{where}: repo url must be one of the reel\'s sources')
        elif kind == 'words':
            lines = s.get('lines')
            if not isinstance(lines, list) or not 1 <= len(lines) <= 3 \
                    or not all(_short(str(x).replace('*', ''), 18) for x in lines):
                errors.append(f'{where}: words needs 1 to 3 lines of at most 18 characters')
            if s.get('label') is not None and not _short(s.get('label'), 24):
                errors.append(f'{where}: a words label is one small line over the words, at most 24 characters')
            if s.get('motif') is not None and s.get('motif') not in MOTIFS:
                errors.append(f'{where}: a words motif is one of {", ".join(MOTIFS)}')
        at = s.get('at')
        if at is not None and (not _short(at, 30) or i >= len(spoken)
                               or _norm(at.split()[0]) not in [_norm(w) for w in spoken[i].split()]):
            errors.append(f'{where}: at must be a word of that slide\'s voiceover line')
        if s.get('light'):
            light += 1
            if i == 0:
                errors.append(f'{where}: the hook stays dark; a light chapter comes later')
        if s.get('accent'):
            accent += 1
            if i == 0 or s.get('light'):
                errors.append(f'{where}: an accent flip comes after the hook, and not on a light scene')
        chapter = s.get('chapter')
        if chapter is not None and (not 1 <= i <= points or not _short(chapter, 14)):
            errors.append(f'{where}: chapter is a point\'s short name (14 chars), only on the point scenes')
        carry = s.get('carry')
        if carry is not None and (i == 0 or not _short(carry, 24) or not isinstance(scenes[i - 1], dict)
                                  or carry not in _text(scenes[i - 1]) or carry not in _text(s)):
            errors.append(f'{where}: carry must be text shown on both the previous scene and this one')
    if light > 2:
        errors.append('scenes: at most 2 light scenes (one light chapter)')
    if accent > 1:
        errors.append('scenes: at most 1 accent flip')
    chaptered = [bool(isinstance(x, dict) and x.get('chapter')) for x in scenes[1:1 + points]]
    if any(chaptered) and not all(chaptered):
        errors.append('scenes: give every point scene a chapter, or none')
    return errors


class Shown:
    """What a slide of a stage reel showed, for the frame review and the record (publish.shown): the scene spec."""

    def __init__(self, spec):
        self.spec = dict(spec, type='stage-' + spec['kind'])
        self.sounds, self.lead, self.marked = [], 0.0, None


def _line(spec, n):
    rows = str(spec.get('code', '')).split('\n')
    return rows[n - 1].strip() if 1 <= n <= len(rows) else ''


def describe(spec):
    """What a stage scene is meant to show, in words for the frame reviewer (qa.describe)."""
    kind = spec.get('kind')
    lines = {
        'file': f"an editor window '{spec.get('title')}' listing: " + ' / '.join(spec.get('lines') or [])
                + (' (the lines get struck through' + (f", tagged {spec.get('tag')}" if spec.get('tag') else '') + ')'
                   if spec.get('strike') else ''),
        'code': f"code in '{spec.get('title')}' (typing itself, or already complete on the hook)" + (
            '; once it lands, line(s) ' + ', '.join(f"{n} ({_line(spec, n)!r})" for n in spec['highlight'])
            + ' get a soft red bar on the left and the other lines dim' if spec.get('highlight') else ''),
        'edit': (lambda n, after: f"an editor '{spec.get('title')}' where {spec.get('key') or 'Ctrl+D'} is pressed {n} "
                 f"times (a counter shows each press), adding a cursor on each of the {n} matches of "
                 f"'{spec.get('find')}'; then '{spec.get('typed')}' is typed once and appears at every cursor, ending "
                 "as: " + ' / '.join(after))(len(matches(spec)), edited(spec)[1]),
        'docs': f"a card of the page {spec.get('url')} ('{spec.get('title')}') quoting: \"{spec.get('text')}\", with "
                f"\"{spec.get('mark')}\" highlighted (check the quote is what that page says)",
        'steps': 'ordered steps lighting up one by one: ' + ' → '.join(i.get('label', '') for i in spec.get('items') or [])
                 + (f" ; a request '{(spec.get('stop') or {}).get('request')}' drops in and is stopped with "
                    f"'{(spec.get('stop') or {}).get('result')}'" if spec.get('stop') else ''),
        'counter': f"a counter ticking up to {spec.get('prefix', '')}{spec.get('value')}{spec.get('suffix', '')} "
                   f"({spec.get('label')}), source {spec.get('source')} (check the number)",
        'bars': f"bars '{spec.get('title')}': " + ', '.join(f"{i.get('label')} {i.get('value')}"
                                                          for i in spec.get('items') or [])
                + (' tagged as an illustration' if spec.get('illustration') else f", source {spec.get('source')} "
                                                                                     '(check the numbers)'),
        'terminal': f"a terminal running {spec.get('command')} and printing: " + ' / '.join(spec.get('output') or [])
                    + ' (check this is what the command really prints)',
        'repo': f"a GitHub repo card {spec.get('name')} with {spec.get('stars')} stars (check the count at "
                f"{spec.get('url')})",
        'words': (f"a small label '{spec['label']}' over " if spec.get('label') else '') + 'big words: '
                 + ' / '.join(str(x).replace('*', '') for x in spec.get('lines') or [])
                 + ' (each word lands as an outline, then its letters fill in one by one)'
                 + (f", with an abstract {spec['motif']} shape pulsing behind them" if spec.get('motif') else ''),
        'checklist': f"a checklist '{spec.get('title')}': " + ', '.join(
            ('✓ ' if i.get('ok') else '✗ ') + str(i.get('label', '')) for i in spec.get('items') or [])
            + ', then stamped ' + ('PASSED' if all(i.get('ok') for i in spec.get('items') or []) else 'FAILED')
            + ' (check each tick or cross matches what the reel really shows)',
    }
    out = lines.get(kind, 'a scene')
    if spec.get('chapter'):
        out = f"a chapter card '{spec['chapter']}' opens it, then " + out
    if spec.get('accent'):
        out += ' (on a full accent-colour background)'
    if spec.get('carry'):
        out += f"; the text '{spec['carry']}' flies in from the previous card"
    return out


# ---------- timing ----------

def _match(words, phrase, after=-1e9):
    """The start time of the first spoken word equal to the phrase's first word, at or after `after`."""
    key = _norm(str(phrase).split()[0]) if str(phrase).split() else ''
    for w, a, _ in words:
        if a >= after and _norm(w) == key:
            return a
    return None


def _beat(words, start, end, frac=0.55):
    if words:
        return words[min(len(words) - 1, int(len(words) * frac))][1]
    return start + (end - start) * frac


def font_size(rows):
    """The mono font size (CSS px) that fills the card without wrapping: short code reads big, like the classic
    code cards (visuals.code_image)."""
    cols = max([len(r) for r in rows] + [1])
    by_width = 492 / (cols * 0.6 + 2)        # JetBrains Mono is 0.6 em wide; the card's side padding is 1 em each
    by_height = 330 / (max(len(rows), 1) * 1.62)
    return int(max(17, min(36, by_width, by_height)))


def tokens(code, language):
    """Each line of the code as [[text, colour], ...], coloured like the editor cards."""
    import visuals
    from pygments import lex
    from pygments.lexers import TextLexer, get_lexer_by_name
    try:
        lexer = get_lexer_by_name(language or 'text')
    except Exception:
        lexer = TextLexer()
    lines = [[]]
    for token_type, text in lex(code.rstrip('\n'), lexer):
        for k, part in enumerate(text.split('\n')):
            if k:
                lines.append([])
            if part:
                lines[-1].append([part, visuals.color_for(token_type)])
    return lines


def plan(reel, slides, words):
    """Everything the page needs, with each move's time worked out from the voice: scenes with start, end, their
    beat (`at`) and per-kind times, and the caption groups."""
    total = slides[-1].end
    scenes = []
    for i, (spec, s) in enumerate(zip(reel['scenes'], slides)):
        ws = words[i] if i < len(words) else []
        end = slides[i + 1].start if i + 1 < len(slides) else total - RETURN
        sc = dict(spec, start=0.0 if i == 0 else s.start, end=end, ready=i == 0)
        # A chapter card takes the first moment; the scene arrives just after it.
        sc['enter'] = sc['start'] + (CHAPTER if spec.get('chapter') else 0.0)
        if spec.get('chapter'):
            sc['number'] = f'{i:02d}'
        at = _match(ws, spec['at']) if spec.get('at') else None
        latest = max(sc['enter'] + 0.4, end - LAND)
        sc['latest'] = latest
        sc['beat'] = min(at if at is not None else _beat(ws, sc['start'], end), latest)
        kind = spec['kind']
        sc['font'] = font_size(_text(spec).split('\n') if kind != 'terminal'
                               else ['$ ' + spec['command']] + list(spec['output']))
        if kind == 'code':
            sc['lines'] = tokens(spec['code'], spec.get('language'))
            n = sum(len(line) for line in sc['lines'])
            step = min(0.06, 0.45 * (end - sc['start']) / max(n, 1))
            sc['type_at'], sc['step'] = (-1.0, 0.0) if sc['ready'] else (sc['enter'] + 0.3, step)
        elif kind == 'edit':
            hits, typed = matches(spec), str(spec['typed'])
            sc['hits'] = [list(h) for h in hits]
            sc['after'] = edited(spec)[1]
            first = sc['enter'] + 0.5
            sc['type_at'] = max(first + 0.3, min(max(sc['beat'], first + 0.3 * len(hits) + 0.3),
                                                 latest + 0.3 - TYPE_STEP * len(typed)))
            gap = max(0.1, min(0.38, (sc['type_at'] - 0.35 - first) / max(len(hits) - 1, 1)))
            sc['presses'] = [round(min(first + j * gap, sc['type_at'] - 0.3), 3) for j in range(len(hits))]
            sc['step'] = TYPE_STEP
            sc['font'] = font_size(edited(spec)[0] + edited(spec)[1])
        elif kind == 'docs':
            m = _match(ws, spec['mark'])
            sc['mark_at'] = min(m if m is not None else sc['beat'], latest)
            k = spec['text'].index(spec['mark'])
            sc['parts'] = [spec['text'][:k], spec['mark'], spec['text'][k + len(spec['mark']):]]
        elif kind in ('steps', 'checklist'):
            times, after = [], sc['enter']
            n = len(spec['items'])
            for j, item in enumerate(spec['items']):
                m = _match(ws, item['label'], after)
                even = sc['enter'] + 0.6 + (end - sc['enter'] - 1.4) * (j + 1) / (n + 1)
                times.append(min(m if m is not None else even, latest))
                after = times[-1]
            sc['times'] = times
        elif kind == 'words':
            times, after = [], sc['start']
            for line in spec['lines']:
                row = []
                for w in str(line).split():
                    m = _match(ws, w.replace('*', ''), after)
                    t = m if m is not None else (row[-1][2] + 0.12 if row else after + 0.15)
                    t = min(t, latest + 0.4)  # all the words are in well before the cut
                    row.append([w.replace('*', ''), w.startswith('*'), t])
                    after = t
                times.append(row)
            sc['rows'] = times
            # Anton capitals are about 0.47 em wide: the longest line fills the card without running off it.
            longest = max(len(str(x).replace('*', '')) for x in spec['lines'])
            sc['font'] = int(max(40, min(96, 470 / (longest * 0.47))))
        scenes.append(sc)
    return {'scenes': scenes, 'captions': caption_groups(reel, slides, words), 'total': total,
            'kicker': reel.get('kicker', ''), 'handle': render.HANDLE, 'accent': render.THEMES['dark']['accent']}


def caption_groups(reel, slides, words):
    """The hook as one complete line on frame 0, then the spoken words in groups of a sentence (or LINE_WORDS)."""
    groups = []
    hook = [(w.replace('*', ''), w.startswith('*') or w.endswith('*')) for w in reel['hook'].split()]
    first_end = slides[1].start if len(slides) > 1 else slides[0].end
    groups.append({'start': 0.0, 'end': first_end, 'words': [[w, 'key' if k else '', -1] for w, k in hook]})
    keys = set()
    for p in reel.get('points') or []:
        keys |= {_norm(w) for w in re.findall(r'\*([^*]+)\*', p.get('title', '')) for w in w.split()}
    lines = reel.get('voiceover') or []
    for i, ws in enumerate(words):
        if i == 0:
            continue
        stress = set()
        if i < len(lines):
            stress = {_norm(m) for m in re.findall(r'\[emphasis\]\s*(\S+)', lines[i])}
        end = slides[i + 1].start if i + 1 < len(slides) else slides[-1].end - RETURN
        sentence = []
        for k, (w, a, _) in enumerate(ws):
            cls = 'key' if _norm(w) in keys else 'em' if _norm(w) in stress else ''
            sentence.append([w, cls, a])
            if w[-1:] in '.?!' or k == len(ws) - 1:
                # A long sentence splits into even parts, never leaving one word alone on the screen.
                parts = -(-len(sentence) // LINE_WORDS)
                size = -(-len(sentence) // parts)
                for j in range(0, len(sentence), size):
                    groups.append({'start': sentence[j][2], 'words': sentence[j:j + size]})
                sentence = []
        for g in groups:
            g.setdefault('slide_end', end)
    for k, g in enumerate(groups):
        if 'end' not in g:
            nxt = groups[k + 1]['start'] if k + 1 < len(groups) else g['slide_end']
            g['end'] = min(nxt, g['slide_end'])
    return groups


# ---------- the page ----------

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
html,body{margin:0;width:540px;height:960px;overflow:hidden;background:#07080C;font-family:Poppins}
#bg{position:absolute;inset:0}
#light{position:absolute;inset:0;background:#F3EFE7;opacity:0}
.grid{position:absolute;inset:0;background-size:30px 30px;-webkit-mask-image:radial-gradient(ellipse 75% 50% at 50% 50%,#000 25%,transparent 80%)}
#gridD{background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px)}
#gridL{opacity:0;background-image:linear-gradient(rgba(0,0,0,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,.06) 1px,transparent 1px)}
#chrome{position:absolute;left:30px;right:30px;top:80px;display:flex;justify-content:space-between;font:600 11px Poppins;letter-spacing:.12em}
#kicker{color:var(--accent)} #handle{color:var(--past);letter-spacing:.02em;font-weight:500}
#cap{position:absolute;left:28px;right:28px;top:122px;height:120px;text-align:center}
.grp{position:absolute;left:0;right:0;top:0;font:600 31px/1.22 Poppins;letter-spacing:-.01em}
.w{display:inline-block;margin:0 .13em;position:relative;color:var(--now)}
.w.past{color:var(--past)}
.w.em{font:italic 400 37px/1 'Instrument Serif';letter-spacing:0}
.w.key::before{content:'';position:absolute;inset:-1px -5px -3px;background:rgba(76,141,255,.22);border:1.5px solid #4C8DFF;border-radius:3px;transform:scaleX(var(--k,0));transform-origin:0 50%;z-index:-1}
.w.key::after,.w.key i{content:'';position:absolute;width:6px;height:6px;border-radius:50%;background:#4C8DFF;opacity:var(--k,0)}
.w.key::after{right:-8px;bottom:-6px} .w.key i{left:-8px;top:-5px}
body{--now:#fff;--past:#5D6475}
body.lit{--now:#14161D;--past:#A3A6AE}
body.acc{--now:#fff;--past:rgba(255,255,255,.62)}
#cam{position:absolute;inset:0;perspective:1200px;perspective-origin:50% 50%}
#world{position:absolute;inset:0;transform-style:preserve-3d}
.scene{position:absolute;left:24px;right:24px;top:270px;height:450px;display:flex;align-items:center;justify-content:center;transform-style:preserve-3d}
.win{position:relative;width:100%;border-radius:16px;background:#12141B;box-shadow:0 30px 70px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.07) inset;overflow:hidden;color:#E8EAF0}
.bar{height:32px;display:flex;align-items:center;gap:6px;padding:0 12px;background:rgba(255,255,255,.035);border-bottom:1px solid rgba(255,255,255,.05);position:relative}
.bar i{width:9px;height:9px;border-radius:50%;background:#2E3240;display:block}
.bar span{position:absolute;left:0;right:0;text-align:center;font:600 11px Poppins;color:#8C93A6}
.code{font:500 19px/31px 'JetBrains Mono';padding:16px 20px;white-space:pre;font-variant-ligatures:none;font-feature-settings:'calt' 0,'liga' 0}
.code .ln{position:relative}
.code .hl{position:absolute;left:-12px;right:-12px;top:0;bottom:0;border-radius:6px;background:rgba(255,106,61,.14);box-shadow:inset 3px 0 0 var(--accent);transform:scaleX(0);transform-origin:0 50%}
.strike{position:absolute;left:-4px;top:50%;height:2px;background:var(--accent);width:0;box-shadow:0 0 8px var(--accent)}
.tag{position:absolute;right:14px;top:44px;font:600 11px Poppins;letter-spacing:.08em;padding:5px 9px;border-radius:999px;background:rgba(255,106,61,.16);color:var(--accent);border:1px solid rgba(255,106,61,.4);opacity:0}
.doc{background:#FBFAF7;color:#1B1D24}
.doc .bar{background:#EFEDE7;border-bottom:1px solid #E2DFD7} .doc .bar span{color:#7A7D86}
.doc .url{font:500 12px 'JetBrains Mono';color:#6E7280;padding:12px 20px 0}
.doc h3{margin:6px 20px 4px;font:700 23px Poppins}
.doc p{margin:8px 20px 20px;font:500 17px/28px Poppins;color:#3A3D46}
.doc b{font-weight:700;background:linear-gradient(rgba(255,106,61,.30),rgba(255,106,61,.30)) no-repeat 0 100%;background-size:calc(var(--h,0)*100%) 100%}
.steps{position:relative;width:300px;height:100%}
.step{position:absolute;left:0;width:300px;height:78px;border-radius:20px;background:#fff;box-shadow:0 18px 40px rgba(20,22,29,.14),0 0 0 1px rgba(20,22,29,.06) inset;display:flex;align-items:center;padding:0 24px;gap:16px;font:700 26px Poppins;color:#14161D}
.step em{font:500 12px 'JetBrains Mono';color:#8A8E98;font-style:normal;margin-left:auto}
.step .dot{width:12px;height:12px;border-radius:50%;background:#D7D9DE}
.req{position:absolute;left:30px;width:240px;text-align:center;font:500 17px 'JetBrains Mono';background:#14161D;color:#fff;padding:9px 0;border-radius:10px;box-shadow:0 14px 30px rgba(20,22,29,.25);opacity:0}
.res{position:absolute;left:282px;font:700 13px Poppins;letter-spacing:.06em;color:#E5484D;opacity:0;white-space:nowrap}
.big{text-align:center}
.big .num{font:700 92px/1 Poppins;letter-spacing:-.03em;color:var(--now)}
.big .lab{font:600 18px Poppins;color:var(--past);margin-bottom:10px}
.big .src,.chart .src{font:500 11px 'JetBrains Mono';color:var(--past);margin-top:16px}
.chart{width:100%;padding:22px;border-radius:18px;background:#12141B;box-shadow:0 30px 70px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.07) inset;color:#E8EAF0}
.chart h4{margin:0 0 14px;font:600 16px Poppins;color:#C9CEDA;display:flex;justify-content:space-between}
.chart h4 small{font:500 10px 'JetBrains Mono';color:#8C93A6;border:1px solid #3A3F50;border-radius:999px;padding:2px 8px}
.row{position:relative;height:42px;margin:8px 0}
.row .fill{position:absolute;left:0;top:0;bottom:0;border-radius:8px;background:#2A2F3D}
.row.top .fill{background:var(--accent)}
.row span{position:absolute;left:12px;top:9px;font:600 16px Poppins;color:#fff}
.row b{position:absolute;right:10px;top:9px;font:500 15px 'JetBrains Mono';color:#C9CEDA}
.term .code{font-size:18px}
.term .cmd{color:#E8EAF0} .term .prompt{color:#5AD17E} .term .out{color:#AEB4C2}
.repo{background:#0D1117;border:1px solid #30363D;border-radius:16px;padding:22px;width:100%;color:#E6EDF3;box-shadow:0 30px 70px rgba(0,0,0,.5)}
.repo .nm{font:600 22px Poppins;color:#58A6FF} .repo .ds{font:500 16px/25px Poppins;color:#9DA7B3;margin:10px 0 16px}
.repo .st{font:600 18px Poppins;color:#E6EDF3;display:flex;gap:8px;align-items:center}
.repo .st i{color:#E3B341;font-style:normal}
.kin{text-align:center;width:100%}
.kin .r{font:400 var(--fs,78px)/1.0 Anton,Poppins;letter-spacing:.005em;text-transform:uppercase;color:var(--now)}
.kin .r span{display:inline-block;margin:0 .08em}
.kin .r span.k{color:var(--accent)}
.kin{position:relative}
.kin .r span b{font-weight:400;-webkit-text-stroke:1.6px var(--now);color:transparent}
.kin .r span.k b{-webkit-text-stroke-color:var(--accent)}
.kin .lab{font:600 21px Poppins;color:var(--past);letter-spacing:.01em;margin-bottom:6px;opacity:0}
.motif{position:absolute;left:50%;top:50%;width:460px;height:300px;margin:-150px 0 0 -230px;z-index:-1;pointer-events:none}
.motif i{position:absolute;display:block}
body.acc .motif i{color:#14161D!important;border-color:#14161D!important;background-color:transparent}
body.acc .motif.wave i{background-color:#14161D!important}
#leak{position:absolute;inset:0;pointer-events:none;mix-blend-mode:screen;opacity:0;z-index:4}
body.acc .kin .r span.k b{-webkit-text-stroke-color:#14161D}
body.acc .kin .r span.k,body.acc #kicker,body.acc #chapchip{color:#14161D}
#acc{position:absolute;inset:0;background:var(--accent);opacity:0}
.frame i{position:absolute;width:16px;height:16px;border-color:var(--past);border-style:solid;opacity:.7}
.frame .a{left:18px;top:70px;border-width:1.5px 0 0 1.5px}.frame .b{right:18px;top:70px;border-width:1.5px 1.5px 0 0}
.frame .c{left:18px;top:744px;border-width:0 0 1.5px 1.5px}.frame .d{right:18px;top:744px;border-width:0 1.5px 1.5px 0}
#tc{position:absolute;right:30px;top:100px;font:500 10px 'JetBrains Mono';color:var(--past);letter-spacing:.06em}
#chapchip{position:absolute;left:30px;top:100px;font:600 10px 'JetBrains Mono';color:var(--accent);letter-spacing:.14em;opacity:0}
#chap{position:absolute;left:0;right:0;top:400px;text-align:center;opacity:0;pointer-events:none}
#chap b{display:block;font:600 22px/1 Poppins;color:var(--now);letter-spacing:.02em;margin-bottom:6px}
#chap span{display:block;font:400 110px/1 Anton,Poppins;color:var(--accent);text-transform:uppercase;letter-spacing:.01em}
#orb{position:absolute;left:0;top:0;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:#FFE3D6;box-shadow:0 0 10px 3px var(--accent),0 0 28px 8px var(--accent)}
.check{width:100%;border-radius:18px;background:#FBFAF7;color:#16181F;padding:22px 24px;box-shadow:0 30px 70px rgba(0,0,0,.45);position:relative}
.check h4{margin:0 0 14px;font:400 30px/1 Anton,Poppins;text-transform:uppercase;letter-spacing:.01em;display:flex;justify-content:space-between;align-items:baseline}
.check h4 small{font:600 10px 'JetBrains Mono';letter-spacing:.14em;color:var(--accent)}
.item{display:flex;align-items:center;gap:14px;font:600 19px/1.3 Poppins;margin:12px 0}
.box{width:24px;height:24px;border-radius:6px;border:2px solid #C9CCD3;display:flex;align-items:center;justify-content:center;font:700 16px Poppins;color:#fff;flex:none}
.stamp{position:absolute;right:18px;bottom:16px;font:400 34px/1 Anton,Poppins;letter-spacing:.04em;padding:6px 14px;border:3px solid currentColor;border-radius:8px;transform:rotate(-8deg);opacity:0}
.ed .m{position:relative;white-space:pre}
.ed .sel{position:absolute;left:-2px;right:-2px;top:-2px;bottom:-2px;border-radius:4px;background:rgba(76,141,255,.35);box-shadow:0 0 0 1.5px #4C8DFF inset;opacity:0}
.ed .cur{position:absolute;top:-3px;bottom:-3px;width:2.5px;margin-left:-1px;background:#7FB0FF;box-shadow:0 0 10px #4C8DFF;opacity:0}
.ed .nw{color:#5AD17E}
.edwrap{width:100%;display:flex;flex-direction:column;align-items:center;gap:34px}
.keycap{display:flex;align-items:center;gap:14px;opacity:0}
.keycap b{font:700 30px 'JetBrains Mono';color:#14161D;background:#F3F4F7;padding:10px 18px;border-radius:12px;box-shadow:0 6px 0 #9DA2AE,0 18px 40px rgba(0,0,0,.45)}
.keycap span{font:400 46px/1 Anton,Poppins;color:var(--accent);min-width:90px}
.edtag{position:absolute;right:14px;top:44px;font:600 12px Poppins;letter-spacing:.08em;padding:5px 10px;border-radius:999px;background:rgba(90,209,126,.16);color:#5AD17E;border:1px solid rgba(90,209,126,.45);opacity:0}
#chip{position:absolute;left:0;top:0;z-index:5;font:500 17px 'JetBrains Mono';color:#E8EAF0;background:#1B1F2B;border:1px solid rgba(255,255,255,.14);padding:4px 10px;border-radius:8px;opacity:0;box-shadow:0 10px 30px rgba(0,0,0,.4);white-space:pre}
</style></head><body>
<canvas id="bg" width="540" height="960"></canvas><div id="light"></div><div id="acc"></div><div class="grid" id="gridD"></div><div class="grid" id="gridL"></div>
<div class="frame"><i class="a"></i><i class="b"></i><i class="c"></i><i class="d"></i></div><div id="tc"></div><div id="chapchip"></div>
<div id="chrome"><span id="kicker"></span><span id="handle"></span></div>
<div id="cam"><div id="world"></div></div><div id="chap"><b></b><span></span></div><div id="orb"></div><div id="chip"></div><div id="leak"></div><div id="cap"></div>
<script>
const P = window.PARAMS, S = P.scenes, T = P.total, SOUNDS = [];
document.documentElement.style.setProperty('--accent', P.accent);
document.getElementById('kicker').textContent = (P.kicker || '').toUpperCase();
document.getElementById('handle').textContent = P.handle;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const prog = (t, a, d) => clamp((t - a) / d);
const expo = p => p >= 1 ? 1 : 1 - Math.pow(2, -10 * p);
const out3 = p => 1 - Math.pow(1 - p, 3);
const inout = p => p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
const back = p => { const c = 2.2; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); };
const snd = (t, k) => { if (t >= 0) SOUNDS.push([+t.toFixed(3), k]); };
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const esc = s => String(s).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
// The carried phrase gets its own span on both scenes so it can fly from one to the other.
function withCarry(text, carry, cls) {
  const t = esc(text); if (!carry) return t; const c = esc(carry), k = t.indexOf(c);
  return k < 0 ? t : t.slice(0, k) + `<span class="${cls}">${c}</span>` + t.slice(k + c.length);
}
function win(title, light) {
  const w = el('div', 'win' + (light ? ' doc' : '')), b = el('div', 'bar');
  b.innerHTML = '<i></i><i></i><i></i>'; b.appendChild(el('span', '', title)); w.appendChild(b); return w;
}
const world = document.getElementById('world');
const sizeCode = (c, s) => { c.style.fontSize = s.font + 'px'; c.style.lineHeight = Math.round(s.font * 1.62) + 'px';
  c.style.padding = `${Math.round(s.font * .9)}px ${Math.round(s.font)}px`; };
const K = {};  // per kind: build(scene, box, next carry) -> draw(t)
K.file = (s, box, nc) => {
  const w = win(s.title), c = el('div', 'code'); w.appendChild(c); box.appendChild(w); sizeCode(c, s);
  const rows = s.lines.map(line => { const d = el('div', 'ln'); d.innerHTML = withCarry(line, nc, 'carry-src');
    const st = el('b', 'strike'); d.appendChild(st); c.appendChild(d); return st; });
  const tag = s.tag ? el('div', 'tag', s.tag) : null; if (tag) w.appendChild(tag);
  if (s.strike) { snd(s.beat, 'swish'); if (tag) snd(s.beat + .3, 'pop'); }
  return t => {
    rows.forEach((st, i) => { const p = s.strike ? inout(prog(t, s.beat + i * .09, .25)) : 0;
      st.style.display = p > 0 ? 'block' : 'none'; st.style.width = `calc(${(p * 100).toFixed(1)}% + ${(8 * p).toFixed(1)}px)`; });
    c.style.opacity = s.strike ? 1 - .55 * prog(t, s.beat + .3, .3) : 1;
    if (tag) { const p = prog(t, s.beat + .3, .35); tag.style.opacity = p; tag.style.transform = `scale(${.6 + .4 * back(p)})`; }
  };
};
K.code = (s, box, nc) => {
  const w = win(s.title), c = el('div', 'code'); w.appendChild(c); box.appendChild(w); sizeCode(c, s);
  const toks = [], hls = [];
  s.lines.forEach((line, i) => { const d = el('div', 'ln'), hl = el('div', 'hl'); d.appendChild(hl); hls.push([i + 1, hl, d]);
    line.forEach(([txt, col]) => { const sp = el('span'); sp.style.color = col; sp.innerHTML = withCarry(txt, s.carry, 'carry-dst');
      d.appendChild(sp); toks.push(sp); });
    if (!line.length) d.appendChild(el('span', '', ' ')); c.appendChild(d); });
  toks.forEach((sp, i) => { if (i % 2 === 0) snd(s.type_at + i * s.step, 'key'); });
  const marked = new Set(s.highlight || []);
  if (marked.size) snd(s.beat, 'tick');
  return t => {
    toks.forEach((sp, i) => { const p = s.type_at < 0 ? 1 : prog(t, s.type_at + i * s.step, .18); sp.style.opacity = p; sp.style.transform = `translateY(${(1 - p) * 5}px)`; sp.style.display = 'inline-block'; });
    const f = expo(prog(t, s.beat, .45));
    hls.forEach(([n, hl, d]) => { if (marked.has(n)) { hl.style.transform = `scaleX(${f})`; d.style.opacity = 1; } else { hl.style.display = 'none'; d.style.opacity = marked.size ? 1 - .5 * f : 1; } });
  };
};
K.edit = (s, box) => {
  // The edit happens on screen: each press of the key adds a cursor on the next match (the counter shows which),
  // then the typed text lands at every cursor at once. The end state is s.after, worked out by stage.edited.
  const wrap = el('div', 'edwrap'), w = win(s.title), c = el('div', 'code ed'); w.appendChild(c); wrap.appendChild(w);
  box.appendChild(wrap); sizeCode(c, s);
  const L = s.find.length, ms = [];
  const rows = {}; s.hits.forEach(([r, col], j) => { (rows[r] = rows[r] || []).push([col, j]); });
  s.lines.forEach((line, r) => { const d = el('div', 'ln'); let at = 0;
    (rows[r] || []).forEach(([col, j]) => { d.appendChild(el('span', '', line.slice(at, col)));
      const m = el('span', 'm'), sel = el('i', 'sel'), old = el('span', '', s.find), nw = el('span', 'nw'), cur = el('i', 'cur');
      m.append(sel, old, nw, cur); d.appendChild(m); ms[j] = {sel, old, nw, cur, m}; at = col + L; });
    d.appendChild(el('span', '', line.slice(at) || (at ? '' : ' '))); c.appendChild(d); });
  const cap = el('div', 'keycap'); cap.innerHTML = `<b>${esc(s.key || 'Ctrl+D')}</b><span></span>`; wrap.appendChild(cap);
  const cnt = cap.querySelector('span'), n = s.hits.length, done = s.type_at + s.typed.length * s.step;
  const tag = el('div', 'edtag', `${n} CURSORS, 1 EDIT`); w.appendChild(tag);
  s.presses.forEach(p => snd(p, 'click'));
  for (let k = 0; k < s.typed.length; k += 2) snd(s.type_at + k * s.step, 'key'); snd(done + .05, 'pop');
  return t => {
    const pressed = s.presses.filter(p => t >= p).length, typing = t >= s.type_at;
    const k = Math.floor(clamp((t - s.type_at) / s.step, 0, s.typed.length));
    ms.forEach((m, j) => { const on = t >= s.presses[j], p = expo(prog(t, s.presses[j], .25));
      m.sel.style.opacity = on && !typing ? p : 0; m.sel.style.transform = `scale(${.6 + .4 * p})`;
      m.old.style.display = typing ? 'none' : 'inline'; m.nw.textContent = typing ? s.typed.slice(0, k) : '';
      m.nw.style.display = typing ? 'inline' : 'none';
      const blink = typing && t < done ? 1 : (Math.sin(t * 9) > -.2 ? 1 : .15);
      m.cur.style.opacity = on && t < done + .8 ? blink : 0;
      m.cur.style.left = typing ? `${m.nw.offsetWidth}px` : `${m.old.offsetWidth}px`; });
    const show = s.ready && t <= 0 ? 0 : expo(prog(t, s.presses[0] - .2, .3)) * (1 - prog(t, done + .5, .4));
    const last = s.presses[Math.max(0, pressed - 1)], bump = pressed ? Math.sin(Math.PI * prog(t, last, .18)) : 0;
    cap.style.opacity = show; cap.style.transform = `translateY(${(-6 * bump).toFixed(1)}px) scale(${(1 + .08 * bump).toFixed(3)})`;
    cap.querySelector('b').style.boxShadow = bump > .3 ? '0 2px 0 #9DA2AE,0 10px 30px rgba(0,0,0,.45)' : '';
    cnt.textContent = typing ? '' : `${pressed}/${n}`;
    const g = prog(t, done + .1, .3); tag.style.opacity = g; tag.style.transform = `scale(${.6 + .4 * back(g)})`;
  };
};
K.docs = (s, box, nc) => {
  const w = win(s.title, true); box.appendChild(w);
  w.insertAdjacentHTML('beforeend', `<div class="url">${esc(s.url.replace(/^https?:\/\//, ''))}</div><h3>${esc(s.title)}</h3>` +
    `<p>${withCarry(s.parts[0], nc, 'carry-src')}<b>${esc(s.parts[1])}</b>${withCarry(s.parts[2], nc, 'carry-src')}</p>`);
  const b = w.querySelector('b'); snd(s.mark_at, 'scribble');
  return t => { b.style.setProperty('--h', expo(prog(t, s.mark_at, .45))); };
};
K.steps = (s, box, nc) => {
  const wrap = el('div', 'steps'); box.appendChild(wrap);
  const gap = s.items.length > 3 ? 92 : 108, top = (450 - gap * (s.items.length - 1) - 78) / 2 + (s.stop ? 30 : 0);
  const cols = ['#E5484D', '#F5A524', '#2E9E5B', '#4C8DFF'];
  const rows = s.items.map((it, i) => { const r = el('div', 'step'); r.style.top = (top + i * gap) + 'px';
    r.innerHTML = `<span class="dot"></span>${esc(it.label)}<em>${esc(it.note || (i + 1) + '')}</em>`; wrap.appendChild(r); return r; });
  s.times.forEach(x => snd(x, 'tick'));
  let req, res, hitAt;
  if (s.stop) { req = el('div', 'req', s.stop.request); res = el('div', 'res', s.stop.result); wrap.appendChild(req); wrap.appendChild(res);
    hitAt = Math.min(Math.max(s.times[s.times.length - 1] + .4, s.end - 1.6), s.latest + .3); snd(hitAt, 'thud'); }
  return t => {
    rows.forEach((r, i) => { const p = expo(prog(t, s.enter + .15 + i * .12, .55)); r.style.opacity = p;
      r.style.transform = `translateY(${(1 - p) * 60}px) scale(${.92 + .08 * p})`;
      const on = prog(t, s.times[i], .2), dot = r.querySelector('.dot'), col = cols[i % cols.length];
      dot.style.background = on > 0 ? col : '#D7D9DE'; dot.style.boxShadow = on > 0 ? `0 0 0 ${6 * on}px ${col}22` : 'none';
      const bump = Math.sin(Math.PI * prog(t, s.times[i], .24)); r.style.transform += ` scale(${1 + .05 * bump})`; });
    if (req) { const y0 = top + s.stop.at * gap - 52, f = prog(t, hitAt - .55, .55);
      req.style.opacity = f > 0 ? 1 : 0; req.style.top = (y0 - 160 + 160 * f * f) + 'px';
      const hit = prog(t, hitAt, .15); req.style.background = hit > 0 ? '#E5484D' : '#14161D';
      res.style.top = (y0 + 10) + 'px'; res.style.opacity = hit; res.textContent = s.stop.result;
      if (hit > 0) rows[s.stop.at].style.transform += ` translateX(${Math.sin(prog(t, hitAt, .3) * Math.PI * 6) * 4 * (1 - prog(t, hitAt, .3))}px)`; }
  };
};
const fmt = (v, d) => v.toLocaleString('en-US', {maximumFractionDigits: d, minimumFractionDigits: d});
K.counter = (s, box) => {
  const b = el('div', 'big'); b.innerHTML = `<div class="lab">${esc(s.label)}</div><div class="num"></div><div class="src">source: ${esc(s.source.replace(/^https?:\/\//, ''))}</div>`;
  box.appendChild(b); const num = b.querySelector('.num'), dec = Number.isInteger(s.value) ? 0 : 1;
  for (let k = 0; k < 8; k++) snd(s.beat + k * .17, 'tick');
  return t => { const p = s.ready && t <= 0 ? 1 : out3(prog(t, s.beat, 1.5)); num.textContent = (s.prefix || '') + fmt(s.value * p, dec) + (s.suffix || ''); };
};
K.bars = (s, box) => {
  const c = el('div', 'chart'); c.innerHTML = `<h4>${esc(s.title)}${s.illustration ? '<small>illustration</small>' : ''}</h4>`;
  const max = Math.max(...s.items.map(x => x.value)) || 1, best = s.items.reduce((a, x) => x.value > a.value ? x : a, s.items[0]);
  const rows = s.items.map(x => { const r = el('div', 'row' + (x === best ? ' top' : '')); r.innerHTML = `<div class="fill"></div><span>${esc(x.label)}</span><b></b>`; c.appendChild(r); return [r, x]; });
  if (!s.illustration) c.insertAdjacentHTML('beforeend', `<div class="src">source: ${esc(s.source.replace(/^https?:\/\//, ''))}</div>`);
  box.appendChild(c); snd(s.beat, 'pop');
  return t => rows.forEach(([r, x], i) => { const p = out3(prog(t, s.beat + i * .08, 1.0));
    r.querySelector('.fill').style.width = `${Math.max(2, 100 * x.value / max * p)}%`;
    r.querySelector('b').textContent = fmt(x.value * p, Number.isInteger(x.value) ? 0 : 1) + (s.unit ? ' ' + s.unit : ''); });
};
K.terminal = (s, box, nc) => {
  const w = win('Terminal'); w.classList.add('term'); const c = el('div', 'code'); w.appendChild(c); box.appendChild(w); sizeCode(c, s);
  const cmd = el('div'); cmd.innerHTML = '<span class="prompt">$ </span><span class="cmd"></span>'; c.appendChild(cmd);
  const outs = s.output.map(o => { const d = el('div', 'out'); d.innerHTML = withCarry(o, nc, 'carry-src') || ' '; c.appendChild(d); return d; });
  const t0 = s.ready ? -10 : s.enter + .3, per = .035, done = t0 + s.command.length * per,
    show = Math.min(Math.max(done + .3, s.beat), s.latest);  // the real output is on screen well before the cut
  for (let k = 0; k < s.command.length; k += 3) snd(t0 + k * per, 'key'); snd(show, 'pop');
  return t => { const n = Math.floor(clamp((t - t0) / per, 0, s.command.length)); cmd.querySelector('.cmd').textContent = s.command.slice(0, n);
    outs.forEach((d, i) => { const p = s.ready && t <= 0 ? 1 : prog(t, show + i * .12, .2); d.style.opacity = p; }); };
};
K.repo = (s, box) => {
  const r = el('div', 'repo'); r.innerHTML = `<div class="nm">${esc(s.name)}</div><div class="ds">${esc(s.description)}</div><div class="st"><i>★</i><span></span><small style="color:#9DA7B3;font-weight:500">stars</small></div>`;
  box.appendChild(r); const n = r.querySelector('.st span'); for (let k = 0; k < 6; k++) snd(s.beat + k * .2, 'tick');
  return t => { const p = s.ready && t <= 0 ? 1 : out3(prog(t, s.beat, 1.4)); n.textContent = fmt(Math.round(s.stars * p), 0); };
};
K.words = (s, box) => {
  // Each word lands as an outline and its letters fill in one by one; an optional small label sits over the words
  // and an optional abstract motif pulses behind them.
  const k = el('div', 'kin'); box.appendChild(k); k.style.setProperty('--fs', s.font + 'px');
  const first = s.rows[0][0][2], lab = s.label ? el('div', 'lab', s.label) : null; if (lab) k.appendChild(lab);
  const spans = []; s.rows.forEach(row => { const r = el('div', 'r'); row.forEach(([w, key, at]) => { const sp = el('span', key ? 'k' : '');
    const ls = [...w].map(ch => { const b = el('b', '', ch); sp.appendChild(b); return b; }); r.appendChild(sp); spans.push([sp, at, ls]); snd(at, 'pop'); }); k.appendChild(r); });
  const mot = s.motif ? el('div', 'motif ' + s.motif) : null, parts = [];
  if (mot) { k.appendChild(mot);
    if (s.motif === 'wave') for (let j = 0; j < 36; j++) { const b = el('i'); b.style.cssText = `left:${j * 12.8}px;width:6px;border-radius:3px;background:var(--accent)`; mot.appendChild(b); parts.push(b); }
    if (s.motif === 'brackets') ['{', '}'].forEach((c, j) => { const b = el('i', '', c); b.style.cssText = `top:-40px;${j ? 'right' : 'left'}:-10px;font:300 300px/1 'JetBrains Mono';color:var(--accent)`; mot.appendChild(b); parts.push(b); });
    if (s.motif === 'rings') for (let j = 0; j < 3; j++) { const b = el('i'); b.style.cssText = 'left:50%;top:50%;border-radius:50%;border:2px solid var(--accent)'; mot.appendChild(b); parts.push(b); } }
  return t => {
    spans.forEach(([sp, at, ls]) => { const p = prog(t, at, .3); sp.style.opacity = p;
      sp.style.transform = `scale(${1.35 - .35 * expo(p)})`; sp.style.filter = `blur(${((1 - p) * 8).toFixed(1)}px)`;
      ls.forEach((b, j) => { b.style.color = t >= at + .22 + j * .045 ? 'inherit' : 'transparent'; }); });
    if (lab) { const p = prog(t, first - .15, .3); lab.style.opacity = p; lab.style.transform = `translateY(${(1 - out3(p)) * 8}px)`; }
    if (mot) { const on = expo(prog(t, first - .1, .6));
      mot.style.opacity = .35 * on;
      if (s.motif === 'wave') parts.forEach((b, j) => { const h = 20 + 120 * on * Math.abs(Math.sin(t * 3.1 + j * .55) * Math.sin(t * 1.7 + j * .23)); b.style.height = h.toFixed(1) + 'px'; b.style.top = (150 - h / 2).toFixed(1) + 'px'; });
      if (s.motif === 'brackets') parts.forEach((b, j) => { b.style.transform = `translateX(${((j ? 1 : -1) * (40 * (1 - on) + 6 * Math.sin(t * 2))).toFixed(1)}px)`; });
      if (s.motif === 'rings') parts.forEach((b, j) => { const r = 60 + ((t * 70 + j * 90) % 270); b.style.width = b.style.height = (2 * r) + 'px'; b.style.margin = `${-r}px 0 0 ${-r}px`; b.style.opacity = 1 - (r - 60) / 270; });
    }
  };
};
K.checklist = (s, box) => {
  const c = el('div', 'check'), passed = s.items.every(x => x.ok);
  c.innerHTML = `<h4>${esc(s.title)}<small>DONE MEANS</small></h4>`;
  const rows = s.items.map(x => { const r = el('div', 'item'); r.innerHTML = `<span class="box"></span><span>${esc(x.label)}</span>`; c.appendChild(r); return [r, x]; });
  const stamp = el('div', 'stamp', passed ? 'PASSED' : 'FAILED'); stamp.style.color = passed ? '#1F9D55' : '#E5484D'; c.appendChild(stamp); box.appendChild(c);
  const stampAt = Math.min(s.times[s.times.length - 1] + .45, s.latest + .5);
  s.times.forEach(x => snd(x, 'tick')); snd(stampAt, 'thud');
  return t => {
    rows.forEach(([r, x], i) => { const p = s.ready && t <= 0 ? 0 : prog(t, s.times[i], .18), b = r.querySelector('.box');
      b.style.background = p > 0 ? (x.ok ? '#1F9D55' : '#E5484D') : 'transparent'; b.style.borderColor = p > 0 ? 'transparent' : '#C9CCD3';
      b.textContent = p > 0 ? (x.ok ? '✓' : '✕') : ''; b.style.transform = `scale(${p > 0 ? 1 + .3 * Math.sin(Math.PI * p) : 1})`;
      r.style.opacity = .55 + .45 * (p > 0 ? 1 : 0); });
    const q = prog(t, stampAt, .25); stamp.style.opacity = q; stamp.style.transform = `rotate(-8deg) scale(${1.6 - .6 * expo(q)})`;
  };
};
// ---------- scenes: build, then each frame place them in depth ----------
const scenes = S.map((s, i) => { const box = el('div', 'scene'); world.appendChild(box);
  const draw = K[s.kind](s, box, S[i + 1] && S[i + 1].carry); if (i) snd(s.start, 'air'); return {s, box, draw}; });
const nextStart = i => i + 1 < S.length ? S[i + 1].start : T - 1.0;
function place(t) {
  scenes.forEach(({s, box, draw}, i) => {
    const e = s.ready ? 1 : expo(prog(t, s.enter, .8)), n = nextStart(i), k = inout(prog(t, n - .15, .7)), g = prog(t, n + .55, .5);
    let op = e * (1 - .7 * k) * (1 - g), z = -60 * (1 - e) - 260 * k, y = (1 - e) * 220 - 120 * k, rx = -18 * (1 - e), blur = 5 * k;
    let local = t;
    if (i === 0) { const r = expo(prog(t, T - 1.0, .8)); if (r > 0) { op = r; z = -260 * (1 - r); y = -120 * (1 - r); blur = 5 * (1 - r); rx = 0; local = 0; } }
    box.style.display = op > .003 ? 'flex' : 'none';
    box.style.opacity = op; box.style.filter = blur > .05 ? `blur(${blur.toFixed(2)}px)` : 'none';
    box.style.transform = `translate3d(0,${y.toFixed(1)}px,${z.toFixed(1)}px) rotateX(${rx.toFixed(2)}deg)`;
    draw(local);
  });
  // the camera breathes and punches gently on each scene's beat
  let punch = 0; S.forEach(s => { const a = prog(t, s.beat - .1, .4), b = prog(t, s.beat + .5, .8); punch += .05 * expo(a) * (1 - inout(b)); });
  world.style.transform = `scale(${(1 + punch).toFixed(4)}) rotateX(${(4 + Math.sin(t * .4) * 1.2).toFixed(2)}deg) rotateY(${(-4 + Math.sin(t * .27) * 2).toFixed(2)}deg)`;
}
// ---------- the carried phrase flies from the previous scene into this one ----------
const chip = document.getElementById('chip');
function carry(t) {
  chip.style.opacity = 0;
  scenes.forEach(({s, box}, i) => { if (!s.carry || !i) return;
    const dst = box.querySelector('.carry-dst'), src = scenes[i - 1].box.querySelector('.carry-src'); if (!dst || !src) return;
    const a = s.start + .55, b = a + .7, p = prog(t, a, b - a); dst.style.visibility = t < b ? 'hidden' : 'visible';
    if (t < a || t >= b + .03) return;
    const r1 = src.getBoundingClientRect(), r2 = dst.getBoundingClientRect(), e = inout(p), v = Math.sin(Math.PI * p);
    chip.textContent = s.carry; chip.style.opacity = 1;
    chip.style.transform = `translate(${(r1.left + (r2.left - r1.left) * e - 10).toFixed(1)}px,${(r1.top + (r2.top - r1.top) * e - 4 - 140 * v).toFixed(1)}px) scale(${1 + .15 * v})`;
    chip.style.filter = `blur(${(v * 2.2).toFixed(2)}px)`; });
}
scenes.forEach(({s}, i) => { if (s.carry && i) { snd(s.start + .55, 'swish'); snd(s.start + 1.25, 'pop'); } });
// ---------- light chapter and accent flip ----------
function tone(flag) { const v = S.map(s => s[flag] ? 1 : 0);
  return t => { let m = v[0]; S.forEach((s, i) => { if (i) m += (v[i] - v[i - 1]) * prog(t, s.start, flag === 'accent' ? .25 : .5); });
    return m - m * prog(t, T - 1.0, .5); }; }
const litAt = tone('light'), accAt = tone('accent');
S.forEach((s, i) => { if (i && s.accent) snd(s.start, 'thud'); });
function light(t) {
  const m = litAt(t), a = accAt(t);
  document.getElementById('light').style.opacity = m; document.getElementById('acc').style.opacity = a;
  document.getElementById('gridL').style.opacity = m; document.getElementById('gridD').style.opacity = 1 - m;
  document.body.classList.toggle('lit', m > .5); document.body.classList.toggle('acc', a > .5);
}
// ---------- chapter cards, the film frame's timecode and chapter name ----------
const chap = document.getElementById('chap'), chipEl = document.getElementById('chapchip'), tc = document.getElementById('tc');
S.forEach(s => { if (s.chapter) snd(s.start, 'pop'); });
function chapters(t) {
  chap.style.opacity = 0; let name = '';
  S.forEach((s, i) => { const n = nextStart(i); if (s.chapter && t >= s.start && t < n) name = `NO.${+s.number} · ${s.chapter.toUpperCase()}`;
    if (!s.chapter || t < s.start || t >= s.enter + .35) return;
    const a = expo(prog(t, s.start, .25)), out = inout(prog(t, s.enter - .1, .4));
    // "No.2" small over the chapter's name, giant (the size fits the name across the frame).
    chap.querySelector('b').textContent = 'No.' + (+s.number); const nm = chap.querySelector('span');
    nm.textContent = s.chapter; nm.style.fontSize = Math.min(110, 470 / (s.chapter.length * .47)).toFixed(0) + 'px';
    chap.style.opacity = a * (1 - out); chap.style.transform = `translateY(${(-260 * out).toFixed(1)}px) scale(${(1.12 - .12 * a - .5 * out).toFixed(3)})`; });
  chipEl.textContent = name; chipEl.style.opacity = name ? 1 : 0;
  const f = Math.round(t * 30), sec = Math.floor(f / 30); tc.textContent = `00:00:${String(sec).padStart(2, '0')}:${String(f % 30).padStart(2, '0')}`;
}
// ---------- the signature: one glowing dot that travels the frame's top edge from scene to scene ----------
const orb = document.getElementById('orb');
function orbAt(t) {
  let x = 70; S.forEach((s, i) => { const to = i % 2 ? 470 : 70, from = i ? ((i - 1) % 2 ? 470 : 70) : 70, p = inout(prog(t, s.start, .9)); if (t >= s.start) x = from + (to - from) * p; });
  const back = inout(prog(t, T - 1.0, .8)); x += (70 - x) * back;
  let pulse = 0; S.forEach(s => { pulse = Math.max(pulse, Math.sin(Math.PI * prog(t, s.beat, .5))); });
  orb.style.transform = `translate(${x.toFixed(1)}px,${(256 + 3 * Math.sin(t * 1.3)).toFixed(1)}px) scale(${(1 + .7 * pulse).toFixed(3)})`;
}
// ---------- captions ----------
const cap = document.getElementById('cap');
const groups = P.captions.map(g => { const d = el('div', 'grp'); cap.appendChild(d);
  const ws = g.words.map(([w, cls, a]) => { const e = el('span', 'w' + (cls ? ' ' + cls : '')); if (cls === 'key') e.innerHTML = '<i></i>' + esc(w); else e.textContent = w; d.appendChild(e);
    if (cls === 'key' && a >= 0) snd(a + .08, 'tick'); return [e, a]; });
  return {g, d, ws}; });
function captions(t) {
  groups.forEach(({g, d, ws}) => {
    const on = t >= g.start - .01 && t < g.end; d.style.display = on ? 'block' : 'none'; if (!on) return;
    const q = prog(t, g.end - .28, .28); d.style.opacity = 1 - q; d.style.transform = `translateY(${-14 * q}px)`; d.style.filter = q > 0 ? `blur(${8 * q}px)` : 'none';
    ws.forEach(([e, a], i) => {
      if (a < 0) { e.style.opacity = 1; e.style.setProperty('--k', 1); return; }
      const p = prog(t, a, .32); e.style.opacity = p; e.style.transform = `translateY(${(1 - out3(p)) * 10}px)`; e.style.filter = p < 1 ? `blur(${((1 - p) * 8).toFixed(1)}px)` : 'none';
      e.classList.toggle('past', i + 1 < ws.length && ws[i + 1][1] >= 0 && t >= ws[i + 1][1]);
      if (e.classList.contains('key')) e.style.setProperty('--k', expo(prog(t, a + .08, .22)));
    });
  });
}
// ---------- living background ----------
const cv = document.getElementById('bg'), cx = cv.getContext('2d');
const blobs = [[0.82, 0.2, 300, P.accentRgb, 0.20], [0.12, 0.8, 340, '70,95,230', 0.22], [0.45, 0.5, 260, '120,80,230', 0.10]];
function bg(t) { cx.fillStyle = '#07080C'; cx.fillRect(0, 0, 540, 960); cx.globalCompositeOperation = 'lighter';
  blobs.forEach(([x, y, r, c, a], i) => { const px = 540 * (x + .08 * Math.sin(t * .27 + i * 1.7)), py = 960 * (y + .05 * Math.sin(t * .21 + i * 2.3 + 1));
    const g = cx.createRadialGradient(px, py, 0, px, py, r); g.addColorStop(0, `rgba(${c},${a})`); g.addColorStop(1, `rgba(${c},0)`); cx.fillStyle = g; cx.fillRect(0, 0, 540, 960); });
  cx.globalCompositeOperation = 'source-over'; }
// ---------- light leaks: a warm flare sweeps across each cut (a white burn on the accent flip) ----------
const leakEl = document.getElementById('leak');
S.forEach((s, i) => { if (i) snd(s.start - .12, 'swish'); });
function leaks(t) {
  let best = 0, x = 0, white = 0;
  S.forEach((s, i) => { if (!i) return; const p = prog(t, s.start - .35, .8); if (p <= 0 || p >= 1) return;
    const a = Math.sin(Math.PI * p); if (a > best) { best = a; x = -30 + 160 * p; white = s.accent ? a : 0; } });
  leakEl.style.opacity = best.toFixed(3);
  leakEl.style.background = best > 0 ? `radial-gradient(ellipse 70% 55% at ${x.toFixed(1)}% 45%, rgba(255,${180 + 60 * white | 0},${110 + 130 * white | 0},.95), rgba(255,96,32,.55) 38%, rgba(160,40,10,0) 72%)` : 'none';
}
window.renderAt = t => { bg(t); light(t); place(t); carry(t); captions(t); chapters(t); orbAt(t); leaks(t); };
document.fonts.ready.then(() => { window.renderAt(0); window.SOUNDS = SOUNDS.filter(x => x[0] < T).sort((a, b) => a[0] - b[0]); window.READY = true; })
  .catch(e => { window.ERROR = String(e); });
window.onerror = (m) => { window.ERROR = String(m); };
</script></body></html>"""


def html(reel, slides, words):
    import motion
    params = plan(reel, slides, words)
    accent = params['accent'].lstrip('#')
    params['accentRgb'] = ','.join(str(int(accent[i:i + 2], 16)) for i in (0, 2, 4))
    return PAGE.replace('<head>', '<head><style>' + motion.font_css() + '</style><script>window.PARAMS = '
                        + json.dumps(params).replace('</', '<\\/') + ';</script>', 1), params


def workers():
    raw = os.environ.get('RENDER_WORKERS', '').strip()
    return max(1, int(raw)) if raw.isdigit() else max(1, min(4, os.cpu_count() or 1))


def frames(page_html, total, label='stage', n_workers=None):
    """(sounds, an iterator of every frame as JPEG bytes, in order). The frames are drawn by n_workers browsers at
    once, browser k drawing frames k, k + n, k + 2n...; each opens the same page, which is a pure function of time."""
    from playwright.sync_api import sync_playwright
    count = round(total * render.FPS)
    n = max(1, min(n_workers or workers(), count or 1))
    shots, failed, sounds = {}, [], []
    lock = threading.Condition()
    state = {'next': 0, 'stop': False}

    def draw(k):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': CSS_W, 'height': CSS_H}, device_scale_factor=2)
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.set_content(page_html, wait_until='domcontentloaded')
                    try:
                        page.wait_for_function('window.READY === true || window.ERROR', timeout=30000)
                    except Exception:
                        raise RuntimeError(f'{label} page did not load: {errors or "no error reported"}') from None
                    if errors or page.evaluate('window.ERROR || null'):
                        raise RuntimeError(f"{label} page failed: {(errors or [page.evaluate('window.ERROR')])[0][:300]}")
                    if k == 0:
                        with lock:
                            sounds.append(page.evaluate('window.SOUNDS'))
                            lock.notify_all()
                    for f in range(k, count, n):
                        with lock:
                            lock.wait_for(lambda: state['stop'] or f < state['next'] + AHEAD * n)
                            if state['stop']:
                                return
                        page.evaluate(SETTLE % (f / render.FPS))
                        shot = page.screenshot(type='jpeg', quality=JPEG_QUALITY)
                        with lock:
                            shots[f] = shot
                            lock.notify_all()
                finally:
                    browser.close()
        except Exception as e:
            with lock:
                failed.append(e)
                lock.notify_all()

    threads = [threading.Thread(target=draw, args=(k,), daemon=True) for k in range(n)]
    for t in threads:
        t.start()
    with lock:
        lock.wait_for(lambda: sounds or failed)
        if failed:
            state['stop'] = True           # the other browsers stop instead of waiting for frames to be taken
            lock.notify_all()
    if failed:
        for t in threads:
            t.join()
        raise failed[0]

    def ordered():
        try:
            for f in range(count):
                with lock:
                    lock.wait_for(lambda: f in shots or failed)
                    if f not in shots:
                        raise failed[0]
                    shot = shots.pop(f)
                    state['next'] = f + 1
                    lock.notify_all()
                yield shot
        finally:
            with lock:
                state['stop'] = True
                lock.notify_all()
            for t in threads:
                t.join()

    return sounds[0], ordered()


def film(page_html, total, frames_path, label='stage'):
    """Every frame of a page that draws itself with window.renderAt(t), encoded to frames_path (video only, film grain
    and a soft vignette, the standard encoding). Returns the page's sound effects, [(time, kind)]. Shared with
    showcase.py."""
    sounds, shots = frames(page_html, total, label)
    enc = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'image2pipe', '-vcodec', 'mjpeg',
                            '-framerate', str(render.FPS), '-i', '-',
                            '-vf', 'noise=alls=4:allf=t,vignette=PI/9', '-c:v', 'libx264', '-preset', 'slow',
                            '-crf', '21', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1',
                            '-maxrate', '5M', '-bufsize', '10M', '-g', str(render.FPS * 2), str(frames_path)],
                           stdin=subprocess.PIPE)
    try:
        for shot in shots:
            enc.stdin.write(shot)
    finally:
        shots.close()                      # stops and closes the browsers if the encoder failed part way
        enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError(f'ffmpeg failed on the {label} frames')
    return sounds


def mux(frames_path, wav, out_path):
    mastered = Path(wav).with_name('master.wav')
    render.master(wav, mastered)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(frames_path), '-i', str(mastered),
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest',
                    '-movflags', '+faststart', str(out_path)], check=True)


def render_stage(reel, slides, voice, out_path):
    """Draw every frame of the stage reel in Chromium and encode it with the voice and the scenes' sound effects."""
    words = render.spoken_words(voice, slides)
    page_html, params = html(reel, slides, words)
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp) / 'frames.mp4'
        sounds = film(page_html, params['total'], frames)
        wav = Path(tmp) / 'audio.wav'
        render.build_audio(slides, wav, voice, stage_sounds=sounds)
        mux(frames, wav, out_path)
    return out_path


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.path.insert(0, str(render.ROOT / 'tests'))
    from e2e_publish import silent_voice
    reel = render.load_reel(sys.argv[1])
    render.render_reel(reel, voice=silent_voice(reel['voiceover']))


if __name__ == '__main__':
    main()
