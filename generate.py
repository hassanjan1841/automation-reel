"""Write reels with Claude and validate reels.json.

Reels are normally written on the day by publish.py (generate.today). This script is for manual work.

Usage:
  python generate.py --force    queue 14 reels by hand (they are posted before any freshly written reel)
  python generate.py --check    validate reels.json and exit
  python generate.py --voiceover  write the spoken script for unposted reels that have none
  python generate.py --cues     add delivery cues to queued spoken scripts, keeping every word
  python generate.py --visuals  pick code, terminal or screenshot visuals for queued reels that have none

Uses the Claude Code CLI, so it runs on a Claude Pro/Max subscription via CLAUDE_CODE_OAUTH_TOKEN.
"""

import difflib
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import history
import render
from voice import strip_cues

MODEL = 'claude-sonnet-5'
BATCH = 14
POST_HOUR_UTC = 12

# The week's mix leans on what held viewers best (relatable dev life), with named series so people come back.
# Each day: (pillar key, what to write, series name). The series gets an episode number when posted.
PILLARS = {
    0: ('ai', 'AI how-to with one concrete result: a Claude or AI tool doing real work (connect Claude to a tool '
              'with MCP, a Claude Code skill, an automation that replies, sorts or builds something), shown with '
              'the real steps (walkthrough, ide recording or screenshots)', 'AI tool in 30s'),
    1: ('devtip', 'Dev tip on Next.js, React, TypeScript, Supabase, Stripe or Postgres: a mistake and its fix '
                  '(diff or ide recording)', 'Dev mistake'),
    2: ('relatable', 'Myth vs fact: a belief many developers hold that is wrong, proven wrong on screen with real '
                     'code, a real recording or the official docs, then what to do instead', 'Myth vs fact'),
    3: ('freelance', 'Freelance playbook: one copyable thing for a common client situation (the exact message to '
                     'send when the scope grows, a contract clause, how to price a fix, a line for the invoice), '
                     'shown as the real text on screen in a code card titled like "message.txt", plus why it works. '
                     'A template, never an invented conversation', 'Freelance playbook'),
    4: ('concept', 'Tech concept explained simply, or myth vs fact about a tool or practice', 'Explained'),
    5: ('relatable', 'Ranked: three real tools or habits for one job, ranked with the real reason for each, shown '
                     'with real code, docs or screenshots, and a clear verdict on which to pick', 'Ranked'),
    6: ('saas', 'Build X in one afternoon: one real feature with Next.js, Supabase or Stripe (auth, checkout, '
                'a webhook, a dashboard) in a few clear steps; or SaaS validation, or a stack reveal', 'Build smart'),
}

EMOJI = re.compile('[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]')
HASHTAG = re.compile(r'^#[A-Za-z0-9_]+$')
SYMBOLS = re.compile(r'[/&%$#;()\[\]{}<>=_|\\]')
VO_MIN_WORDS, VO_MAX_WORDS = 40, 55


def words(text):
    return len(text.replace('*', '').split())


def highlights(text):
    """Highlighted spans, or None when the asterisks are unbalanced or a span is empty."""
    if text.count('*') % 2:
        return None
    spans = text.split('*')[1::2]
    if any(not s.strip() for s in spans):
        return None
    return spans


def validate(reel):
    errors = []
    slide_text = [reel.get('kicker', ''), reel.get('hook', ''), reel.get('cta', '')]

    kicker = reel.get('kicker', '').strip()
    # A series label ("Client vs Me #4") replaces the kicker when posted and may be a little longer.
    if not kicker or (not reel.get('series') and (words(kicker) > 3 or len(kicker) > 24)):
        errors.append('kicker must be a short label (max 3 words)')

    hook = reel.get('hook', '')
    # On screen people glance, they do not read: a short phrase; the spoken hook carries the full sentence.
    if not 3 <= words(hook) <= 6:
        errors.append(f'hook has {words(hook)} words, needs 3 to 6')
    if not highlights(hook):
        errors.append('hook needs at least one *highlighted* word with balanced asterisks')

    points = reel.get('points', [])
    if len(points) != 3:
        errors.append(f'needs exactly 3 points, got {len(points)}')
    for i, p in enumerate(points, 1):
        title, body = p.get('title', ''), p.get('body', '')
        slide_text += [title, body]
        if not title or words(title) > 3:
            errors.append(f'point {i} title has {words(title)} words, max 3')
        if not body or words(body) > 8:
            errors.append(f'point {i} body has {words(body)} words, max 8')
        if highlights(title) is None:
            errors.append(f'point {i} title has unbalanced asterisks')
        if '*' in body:
            errors.append(f'point {i} body must not use highlights')
        errors += visual_errors(i, p.get('visual'))

    payoff = reel.get('payoff', '')
    if not 10 <= len(payoff.strip()) <= 220:
        errors.append('payoff must say in 10 to 220 characters the one exact thing the viewer gets')
    if reel.get('hook_type') not in HOOK_TYPES:
        errors.append(f"hook_type must be one of {', '.join(HOOK_TYPES)}")
    hv = reel.get('hook_visual')
    if not isinstance(hv, dict) or hv.get('type') not in HOOK_VISUALS:
        errors.append(f"hook_visual must be one {', '.join(HOOK_VISUALS)} visual: the problem or result, shown from "
                      'the first frame')
    else:
        errors += [e.replace('point hook', 'hook_visual') for e in visual_errors('hook', [hv])]
    alts = reel.get('alternatives')
    if not isinstance(alts, list) or len(alts) != 3:
        errors.append('alternatives needs 3 other hooks, each {hook, spoken, hook_type}')
    else:
        for k, a in enumerate(alts, 1):
            if not 3 <= words(a.get('hook', '')) <= 6 or not highlights(a.get('hook', '')) \
                    or a.get('hook_type') not in HOOK_TYPES or not a.get('spoken', '').lstrip().startswith('['):
                errors.append(f'alternative {k} needs a 3 to 6 word hook with a *highlight*, a spoken line starting '
                              'with a [cue] and a hook_type')
            elif words(strip_cues(a['spoken'])) > 14:
                errors.append(f'alternative {k} spoken line has more than 14 words')
            elif any(len(strip_cues(part).split()) > CUE_GAP for part in re.split(r'\[[^\]]*\]', a['spoken'])):
                errors.append(f'alternative {k} spoken line runs more than {CUE_GAP} words without a fresh cue')
    if any(v.get('type') in ('tweet', 'chat') for p in points
           for v in (p.get('visual') if isinstance(p.get('visual'), list) else [p.get('visual')] if p.get('visual') else [])):
        errors.append('tweet and chat visuals are no longer used: no invented posts or conversations; show real '
                      'code, a template, docs or a recording')

    word = reel.get('hook_word')
    if word is not None and hv:
        errors.append('leave hook_word out: the hook slide shows hook_visual under the hook')
    if word is not None and (not re.fullmatch(r'[A-Za-z0-9.#+-]{2,10}', word)
                             or word.lower() not in re.sub(r'\*', '', hook).lower()):
        errors.append('hook_word must be one word from the hook, 2 to 10 letters')
    if three_d_count(reel) > 2:
        errors.append(f'{three_d_count(reel)} 3D moments; use at most 2 (hook_word and 3D visuals together)')

    cta = reel.get('cta', '').strip()
    spans = highlights(cta)
    keyword = reel.get('dm_keyword')
    errors += dm_errors(reel, cta)
    if not keyword and not cta.endswith('?'):
        errors.append('cta must be a question')
    if not spans or len(spans) != 1:
        errors.append('cta needs exactly one *highlighted* word')

    if any(EMOJI.search(t) for t in slide_text):
        errors.append('no emojis allowed on slides')

    lines = [l for l in reel.get('caption', '').split('\n') if l.strip()]
    if not 2 <= len(lines) <= 3:
        errors.append(f'caption needs 2 to 3 lines, got {len(lines)}')
    elif not (lines[-1].rstrip().endswith('👇') and ('?' in lines[-1] or (keyword and keyword in lines[-1]))):
        errors.append('caption must end with a question followed by 👇')

    vo = reel.get('voiceover')
    if not isinstance(vo, list) or len(vo) != 5:
        errors.append('voiceover needs exactly 5 lines (hook, 3 points, cta)')
    else:
        spoken_slides = [reel.get('hook', '')] + [f"{p.get('title', '')} {p.get('body', '')}" for p in points] + [cta]
        said = [strip_cues(l) for l in vo]
        for i, (line, slide) in enumerate(zip(said, spoken_slides), 1):
            if not line.strip():
                errors.append(f'voiceover line {i} is empty')
            elif SYMBOLS.search(line) or '*' in line or EMOJI.search(line):
                errors.append(f'voiceover line {i} has symbols; write it the way it is said')
            # The hook and the closing question may be said as shown (hearing the hook helps it land);
            # the points must add something the slide does not say.
            elif similar(line, slide) > (0.6 if 2 <= i <= 4 else 0.9):
                errors.append(f'voiceover line {i} repeats the slide text; say it in different words')
        n = sum(words(l) for l in said)
        if not VO_MIN_WORDS <= n <= VO_MAX_WORDS:
            errors.append(f'voiceover has {n} words, needs {VO_MIN_WORDS} to {VO_MAX_WORDS}')
        if words(said[0]) > 14:
            errors.append(f'voiceover line 1 has {words(said[0])} words, max 14')
        errors += cue_errors(vo)

    tags = reel.get('hashtags', [])
    if not 3 <= len(tags) <= 5:
        errors.append(f'needs 3 to 5 focused hashtags, got {len(tags)}')
    if any(not HASHTAG.match(t) for t in tags) or len({t.lower() for t in tags}) != len(tags):
        errors.append('hashtags must be unique #words with no spaces')
    return errors + experiment_errors(reel)


CUE_GAP = 10
FLAT = re.compile(r'\b(deadpan|knowing|curious|matter.of.fact|dry|serious|neutral|friendly|warm)\b', re.I)
LOW_ENERGY = re.compile(r'\b(calm|soft|quiet|gentle|sleepy|tired|bored|whisper\w*|slow|satisfied|relaxed)\b', re.I)


def cue_errors(vo):
    """Cues must keep the delivery from fading: fresh every few words, varied, and mostly high energy."""
    errors = []
    cues = [c for line in vo for c in re.findall(r'\[([^\]]*)\]', line)]
    if not all(l.lstrip().startswith('[') for l in vo):
        errors.append('every voiceover line must start with a [delivery cue]')
    for i, line in enumerate(vo, 1):
        # Spoken words between cues; "(break)" does not renew the energy.
        for stretch in re.split(r'\[[^\]]*\]', line):
            n = len(strip_cues(stretch).split())
            if n > CUE_GAP:
                errors.append(f'voiceover line {i} runs {n} words without a fresh cue, max {CUE_GAP}')
                break
    first = re.match(r'\s*\[([^\]]*)\]', vo[0]) if vo else None
    if first and (LOW_ENERGY.search(first.group(1)) or FLAT.search(first.group(1))):
        errors.append('line 1 must open with a high-energy cue like [fired up] or [grinning, punchy]; '
                      'save [deadpan] or [knowing] for the twist after a (break)')
    if sum(bool(LOW_ENERGY.search(c)) for c in cues) > 1:
        errors.append('at most one low-energy cue in the whole voiceover')
    if len({c.strip().lower() for c in cues if c.strip().lower() != 'emphasis'}) < 5:
        errors.append('use at least 5 different cues, not the same one repeated')
    return errors


def similar(a, b):
    a, b = (re.sub(r'[^a-z0-9 ]', '', t.lower().replace('*', '')).split() for t in (a, b))
    return difflib.SequenceMatcher(None, a, b).ratio()


def norm(hook):
    return re.sub(r'[^a-z0-9]', '', hook.lower())


def next_post_dates(reels, count):
    """Dates the new reels will go out, given one post per day at POST_HOUR_UTC."""
    now = datetime.now(timezone.utc)
    posted_today = any((r.get('posted_at') or '').startswith(now.date().isoformat()) for r in reels)
    first = now.date() if now.hour < POST_HOUR_UTC and not posted_today else now.date() + timedelta(days=1)
    queued = sum(1 for r in reels if not r.get('posted_at'))
    return [first + timedelta(days=queued + i) for i in range(count)]


# Hook types from playbook.md; the writer names one and learn.py compares them.
HOOK_TYPES = ('problem', 'before_after', 'shortcut', 'mistake', 'test', 'news')
# What the hook slide shows under the hook from frame 0: the problem or the result itself (flat and complete at
# once; a terminal types itself out and a recording or a 3D scene needs time to start).
HOOK_VISUALS = ('code', 'diff', 'screenshot')
PLAYBOOK = render.ROOT / 'playbook.md'


def playbook():
    """The researched rules for hooks, scripts and visuals (playbook.md), read by the writer, the hook judge and
    the frame review."""
    return PLAYBOOK.read_text().strip() if PLAYBOOK.exists() else ''


NODE_KINDS = ('client', 'server', 'db', 'cache', 'queue', 'cloud', 'phone', 'lock')
SCENES_3D = ('diagram', 'device', 'bars', 'logos')
THREE_D_CHANCE = 0.5


# Reel 1 teaches, reel 2 is relatable; each rotates through its own series (indexes into PILLARS) by weekday,
# so the two reels of a day are always different kinds. The freelance playbook comes up most (2026-10-01: the
# relatable POV and client-chat skits were invented scenes with nothing to take away, and Instagram barely showed
# them: 5 and 9 views).
TEACH = (0, 1, 4, 6)
RELATE = (3, 2, 3, 5)


# Reel 3 of the day picks one of these at random (fixed per date), so it never becomes a routine. "news" is only
# used when the trend scan finds a strong, fact-checked story; otherwise another one is picked.
EXTRA_FORMATS = {
    'trick': ('trick', 'One-line trick: a single VS Code shortcut, git command, terminal or CSS trick that saves '
                       'real time, shown with a terminal or code visual. One trick, not a list', 'Quick trick'),
    'versus': ('versus', 'X vs Y: two real tools developers choose between (Supabase vs Firebase, Prisma vs '
                         'Drizzle, Cursor vs Claude Code). Three honest differences and a clear verdict on who should '
                         'pick which; no invented benchmarks or prices', 'X vs Y'),
    'series': ('series', 'Beginner series "Next.js from zero": the next lesson after the episodes listed below, one '
                         'small concept a beginner can follow, with a code visual', 'Next.js from zero'),
}
SLOT3_FORMATS = ('news', 'trick', 'versus', 'series')


def slot():
    """Which of the day's reels this run writes: 1 (a how-to), 2 (the evening, relatable reel) or 3 (news, a
    trick, X vs Y or the beginner series)."""
    value = os.environ.get('SLOT', '').strip()
    return int(value) if value in ('2', '3') else 1


def slot3_format(day=None, skip=()):
    """Reel 3's format for the day, random but fixed per date; skip formats already ruled out (news with no story)."""
    forced = os.environ.get('REEL_FORMAT', '').strip()
    if forced in SLOT3_FORMATS and forced not in skip:
        return forced
    day = day or datetime.now(timezone.utc).date()
    options = [f for f in SLOT3_FORMATS if f not in skip]
    return random.Random(f'format-{day.isoformat()}-{len(skip)}').choice(options)


def pillar_for(day):
    """(pillar key, what to write, series name) for a reel on this day in this run's slot."""
    if slot() == 3:
        fmt = slot3_format(day)
        return EXTRA_FORMATS[fmt if fmt != 'news' else slot3_format(day, skip=('news',))]
    return PILLARS[(TEACH if slot() == 1 else RELATE)[day.weekday() % 4]]


def three_d_today(day=None):
    """Whether 3D may be used today. Random so it never becomes a routine, but fixed per date so a rerun or a
    repair on the same day agrees. THREE_D=on or off overrides; THREE_D_CHANCE sets the odds."""
    forced = os.environ.get('THREE_D', '').strip().lower()
    if forced in ('on', 'off'):
        return forced == 'on'
    day = day or datetime.now(timezone.utc).date()
    chance = float(os.environ.get('THREE_D_CHANCE', '').strip() or THREE_D_CHANCE)
    return random.Random(f'3d-{day.isoformat()}' + (f'-{slot()}' if slot() > 1 else '')).random() < chance


def three_d_note():
    return ('3D is allowed today: use it for at most 2 moments in the reel (a hook_word and/or 3D visuals), only '
            'where it explains better than a flat visual.' if three_d_today()
            else '3D is NOT allowed today: no hook_word and no diagram, device, bars or logos visuals.')


# The weekly test (learn.py starts one at a time, in experiments.json): each reel gets one option by chance, fixed
# per date and slot, the writer is told which, validate() holds the reel to it, and learn.py compares the options.
# Only things the writer controls and code can check; none of them bends the honesty rules.
NUMBER = re.compile(r'\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|sixty|'
                    r'hundred|thousand)\b', re.I)
EXPERIMENTS = {
    'hook_style': {
        'question': ('The hook is a question the reel answers, ending with "?".',
                     lambda r: r.get('hook', '').strip().endswith('?'), 'the hook must end with "?" (a question)'),
        'statement': ('The hook is a bold statement, not a question: no "?" in it.',
                      lambda r: '?' not in r.get('hook', ''), 'the hook must be a statement with no "?"'),
    },
    'length': {
        'short': ('Keep the voiceover short: 40 to 46 words in total.',
                  lambda r: 40 <= vo_words(r) <= 46, 'the voiceover must have 40 to 46 words'),
        'long': ('Use the full voiceover length: 49 to 55 words in total.',
                 lambda r: 49 <= vo_words(r) <= 55, 'the voiceover must have 49 to 55 words'),
    },
    'hook_number': {
        'number': ('The hook contains a number (a time, a count or a size), written as digits.',
                   lambda r: bool(NUMBER.search(r.get('hook', ''))), 'the hook must contain a number'),
        'no_number': ('The hook contains no numbers at all.',
                      lambda r: not NUMBER.search(r.get('hook', '')), 'the hook must not contain any number'),
    },
}


def vo_words(reel):
    return sum(words(strip_cues(l)) for l in reel.get('voiceover') or [])


def experiment_today(day=None):
    """{'name', 'arm'} of the running test for this reel, or None. EXPERIMENT=off stops it, EXPERIMENT=<name>
    forces a test (for trying it out)."""
    forced = os.environ.get('EXPERIMENT', '').strip()
    if forced == 'off':
        return None
    name = forced if forced in EXPERIMENTS else ((history.experiments().get('active') or {}).get('name'))
    if name not in EXPERIMENTS:
        return None
    day = day or datetime.now(timezone.utc).date()
    arms = sorted(EXPERIMENTS[name])
    return {'name': name, 'arm': random.Random(f'test-{name}-{day.isoformat()}-{slot()}').choice(arms)}


def experiment_note():
    test = experiment_today()
    return f"This week's test, follow it exactly: {EXPERIMENTS[test['name']][test['arm']][0]}" if test else ''


def experiment_errors(reel):
    """Whether a reel follows the test option it was written under (its "test" field)."""
    test = reel.get('test') or {}
    arm = EXPERIMENTS.get(test.get('name'), {}).get(test.get('arm'))
    return [] if not arm or arm[1](reel) else [f"{arm[2]} (this week's test)"]


def three_d_count(reel):
    """3D moments a reel would show: the hook word plus each point whose first choice is a 3D scene."""
    firsts = [(p.get('visual') or [None]) for p in reel.get('points', [])]
    firsts = [f if isinstance(f, list) else [f] for f in firsts]
    return bool(reel.get('hook_word')) + sum(1 for f in firsts if f and f[0] and f[0].get('type') in SCENES_3D)


def strip_3d(reel):
    """The same reel with no 3D, for a day when 3D is not allowed."""
    points = []
    for p in reel.get('points', []):
        choices = p.get('visual')
        choices = [c for c in (choices if isinstance(choices, list) else [choices] if choices else [])
                   if c.get('type') not in SCENES_3D]
        points.append({**{k: v for k, v in p.items() if k != 'visual'}, **({'visual': choices} if choices else {})})
    return {**{k: v for k, v in reel.items() if k != 'hook_word'}, 'points': points}


QUOTE_PLATFORMS = ('X', 'Hacker News', 'GitHub', 'Bluesky', 'Threads', 'LinkedIn', 'Mastodon', 'YouTube', 'Blog')

VISUAL_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['type'],
    'properties': {
        'type': {'type': 'string', 'enum': ['code', 'diff', 'terminal', 'screenshot', 'walkthrough',
                                            'ide', 'quote', 'diagram', 'device', 'bars', 'logos']},
        'author': {'type': 'string'}, 'handle': {'type': 'string'}, 'platform': {'type': 'string'},
        'language': {'type': 'string'}, 'title': {'type': 'string'}, 'code': {'type': 'string'},
        'highlight': {'type': 'array', 'items': {'type': 'integer'}},
        'before': {'type': 'string'}, 'after': {'type': 'string'},
        'commands': {'type': 'array', 'items': {'type': 'string'}},
        'text': {'type': 'string'},
        'messages': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['from', 'text'],
            'properties': {'from': {'type': 'string', 'enum': ['client', 'me']}, 'text': {'type': 'string'}}}},
        'url': {'type': 'string'}, 'find': {'type': 'string'},
        'nodes': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['id', 'label', 'kind'],
            'properties': {'id': {'type': 'string'}, 'label': {'type': 'string'},
                           'kind': {'type': 'string', 'enum': list(NODE_KINDS)}}}},
        'edges': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['from', 'to'],
            'properties': {'from': {'type': 'string'}, 'to': {'type': 'string'}}}},
        'flow': {'type': 'array', 'items': {'type': 'string'}},
        'device': {'type': 'string', 'enum': ['laptop', 'phone']},
        'show': {'type': 'object', 'additionalProperties': False, 'required': ['type'],
                 'properties': {'type': {'type': 'string', 'enum': ['code', 'screenshot']},
                                'language': {'type': 'string'}, 'title': {'type': 'string'},
                                'code': {'type': 'string'}, 'url': {'type': 'string'}, 'find': {'type': 'string'}}},
        'unit': {'type': 'string'}, 'source': {'type': 'string'},
        'bars': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['label', 'value'],
            'properties': {'label': {'type': 'string'}, 'value': {'type': 'number'}}}},
        'items': {'type': 'array', 'items': {'type': 'string'}},
        'files': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['name', 'content'],
            'properties': {'name': {'type': 'string'}, 'content': {'type': 'string'}}}},
        'setup': {'type': 'array', 'items': {'type': 'string'}},
        'steps': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['do'],
            'properties': {'do': {'type': 'string', 'enum': ['scroll', 'scroll_to', 'click', 'hover', 'type', 'wait',
                                                             'open', 'run', 'save']},
                           'text': {'type': 'string'}, 'into': {'type': 'string'}, 'file': {'type': 'string'},
                           'command': {'type': 'string'}, 'screens': {'type': 'number'},
                           'seconds': {'type': 'number'}, 'enter': {'type': 'boolean'}}}},
    },
}


# An install command and the rest of its line; every word on it that is not a flag is a package.
INSTALL = re.compile(r'\b(?:npm\s+(?:i|install|add)|pnpm\s+add|bun\s+add|yarn\s+add|npx(?:\s+-y)?|pip3?\s+install)\s+([^\n;&|]+)')
ARGS = re.compile(r'"args"\s*:\s*\[\s*(?:"-y"\s*,\s*)?"(@?[a-z0-9][\w.@/-]*)"')
_registry = {}


def package_errors(text):
    """Packages a snippet tells people to install that do not exist on npm or PyPI (an invented name would send
    viewers to a typo-squatter). Offline, nothing is reported."""
    wanted = []
    for m in INSTALL.finditer(text):
        kind = 'pypi' if m.group(0).startswith('pip') else 'npm'
        words = [w for w in m.group(1).split() if not w.startswith('-')]
        # npx runs one package; the words after it are its own arguments.
        for w in words[:1] if m.group(0).startswith('npx') else words:
            if kind == 'npm':
                w = '@' + w[1:].split('@')[0] if w.startswith('@') else w.split('@')[0]
            else:
                w = re.split(r'[=<>\[]', w)[0]
            if re.fullmatch(r'@?[A-Za-z0-9][\w.@/-]*', w) and '/' not in w.lstrip('@').split('/', 1)[0]:
                wanted.append((kind, w))
    wanted += [('npm', m) for m in ARGS.findall(text)]
    missing = []
    for kind, name in wanted:
        name = name.rstrip('.,;')
        if name in ('-y', '') or name.startswith('-'):
            continue
        if (kind, name) not in _registry:
            url = (f'https://registry.npmjs.org/{name.replace("/", "%2f")}' if kind == 'npm'
                   else f'https://pypi.org/pypi/{name}/json')
            try:
                import urllib.request
                urllib.request.urlopen(urllib.request.Request(url, method='HEAD' if kind == 'npm' else 'GET'), timeout=10)
                _registry[(kind, name)] = True
            except urllib.error.HTTPError as e:
                _registry[(kind, name)] = e.code != 404
            except OSError:
                _registry[(kind, name)] = True
        if not _registry[(kind, name)]:
            missing.append(name)
    return missing


def dm_errors(post, offer):
    """A comment-to-DM offer must be deliverable: a keyword people can type, a guide that holds what the post
    promises, and the offer made where people see it (the cta or last slide, the voice and the caption)."""
    keyword, guide = post.get('dm_keyword'), post.get('dm_guide')
    if not keyword and not guide:
        return []
    if not keyword or not guide:
        return ['dm_keyword and dm_guide go together']
    errors = []
    if not re.fullmatch(r'[A-Z0-9]{3,10}', keyword):
        errors.append('dm_keyword must be one word in capitals, 3 to 10 letters')
    if not 150 <= len(guide) <= 900:
        errors.append(f'dm_guide is {len(guide)} characters, needs 150 to 900')
    said = strip_cues(post['voiceover'][-1]) if post.get('voiceover') else keyword
    for where, text in (('the cta', offer), ('the caption', post.get('caption', '')), ('the last voiceover line', said)):
        if keyword.lower() not in text.lower().replace('*', ''):
            errors.append(f'{where} must offer the guide with "Comment {keyword}"')
    missing = package_errors(guide)
    if missing:
        errors.append(f'dm_guide names packages that do not exist: {", ".join(missing)}')
    return errors


def visual_errors(i, visual):
    """A point's visuals: a list of up to 3 choices, best first, each small enough to read on a phone."""
    if visual is None:
        return []
    choices = visual if isinstance(visual, list) else [visual]
    if not 1 <= len(choices) <= 3:
        return [f'point {i} visual needs 1 to 3 choices']
    errors = []
    for v in choices:
        kind = v.get('type')
        texts = [v.get('code', ''), v.get('after', ''), ' '.join(v.get('commands', [])), ' '.join(v.get('setup', [])),
                 ' '.join(s.get('command', '') + ' ' + s.get('text', '') for s in v.get('steps', []))]
        texts += [f.get('content', '') for f in v.get('files', [])] + [(v.get('show') or {}).get('code', '')]
        missing = package_errors('\n'.join(texts))
        if missing:
            errors.append(f'point {i} names packages that do not exist: {", ".join(missing)}; use the real, '
                          'official package')
        if kind == 'code':
            lines = v.get('code', '').rstrip('\n').split('\n')
            if not v.get('code', '').strip() or not v.get('language'):
                errors.append(f'point {i} code visual needs code and a language')
            elif len(lines) > 12 or max(len(l) for l in lines) > 40:
                errors.append(f'point {i} code is {len(lines)} lines, longest {max(len(l) for l in lines)} '
                              'characters; max 12 lines of 40 characters')
            elif any(not 1 <= n <= len(lines) for n in v.get('highlight', [])):
                errors.append(f'point {i} code highlight must be line numbers inside the code')
        elif kind == 'diff':
            for part in ('before', 'after'):
                lines = v.get(part, '').rstrip('\n').split('\n')
                if not v.get(part, '').strip() or len(lines) > 12 or max(len(l) for l in lines) > 40:
                    errors.append(f'point {i} diff needs "before" and "after", each max 12 lines of 40 characters')
                    break
            else:
                if v['before'].strip() == v['after'].strip():
                    errors.append(f'point {i} diff "before" and "after" are the same')
        elif kind == 'tweet':
            text = v.get('text', '').strip()
            if not 10 <= len(text) <= 200 or text.count('\n') > 5:
                errors.append(f'point {i} tweet text needs 10 to 200 characters and at most 6 lines')
        elif kind == 'chat':
            msgs = v.get('messages', [])
            if not 2 <= len(msgs) <= 5 or any(not 1 <= len(m.get('text', '')) <= 60 for m in msgs):
                errors.append(f'point {i} chat needs 2 to 5 messages of max 60 characters')
        elif kind == 'terminal':
            cmds = v.get('commands', [])
            if not 1 <= len(cmds) <= 6 or any(len(c) > 40 for c in cmds):
                errors.append(f'point {i} terminal needs 1 to 6 commands of max 40 characters')
        elif kind == 'quote':
            if not 10 <= len(v.get('text', '')) <= 220 or not v.get('url', '').startswith('https://') \
                    or not v.get('author') or v.get('platform') not in QUOTE_PLATFORMS:
                errors.append(f'point {i} quote needs author, platform ({", ".join(QUOTE_PLATFORMS)}), an https url '
                              'and the exact text (10 to 220 characters)')
        elif kind == 'walkthrough':
            steps = v.get('steps', [])
            if not v.get('url', '').startswith('https://') or not 1 <= len(steps) <= 4:
                errors.append(f'point {i} walkthrough needs an https url and 1 to 4 steps (short and focused)')
            elif any(s.get('do') in ('open', 'run', 'save') for s in steps):
                errors.append(f'point {i} walkthrough steps are scroll, scroll_to, click, hover, type or wait')
        elif kind == 'ide':
            import demos
            steps, files = v.get('steps', []), v.get('files', [])
            typed = '\n'.join(s.get('text', '') for s in steps if s.get('do') == 'type')
            if not files or not 1 <= len(steps) <= 8:
                errors.append(f'point {i} ide needs files and 1 to 8 steps')
            elif any(not demos.allowed(c) for c in v.get('setup', []) + [s.get('command', '') for s in steps
                                                                           if s.get('do') == 'run']):
                errors.append(f'point {i} ide commands must start with npm, npx, node, python, pip, git... and '
                              'use no pipes, redirects, ; or $')
            elif len(typed.split('\n')) > 12 or any(len(l) > 60 for l in typed.split('\n')):
                errors.append(f'point {i} ide typed code is max 12 lines of 60 characters')
        elif kind == 'screenshot':
            if not v.get('url', '').startswith('https://'):
                errors.append(f'point {i} screenshot needs an https url')
            if not 3 <= len(v.get('find', '')) <= 80:
                errors.append(f'point {i} screenshot needs "find": short exact text on that page to outline')
        elif kind == 'diagram':
            nodes, ids = v.get('nodes', []), {n.get('id') for n in v.get('nodes', [])}
            flow = [f.split('>') for f in v.get('flow', [])]
            if not 2 <= len(nodes) <= 5 or any(not 1 <= len(n.get('label', '')) <= 12 for n in nodes):
                errors.append(f'point {i} diagram needs 2 to 5 nodes with labels of max 12 characters')
            elif any(e.get('from') not in ids or e.get('to') not in ids for e in v.get('edges', [])) \
                    or not 1 <= len(flow) <= 8 or any(len(f) != 2 or f[0] not in ids or f[1] not in ids for f in flow):
                errors.append(f'point {i} diagram edges and flow ("a>b", 1 to 8 hops) must use node ids')
        elif kind == 'device':
            show = v.get('show') or {}
            if v.get('device') == 'phone' and show.get('type') != 'screenshot':
                errors.append(f'point {i} phone device shows a screenshot only; use a laptop for code')
            elif show.get('type') == 'code':
                errors += visual_errors(i, [{**show, 'type': 'code'}])
            elif show.get('type') == 'screenshot':
                errors += visual_errors(i, [{**show, 'type': 'screenshot'}])
            else:
                errors.append(f'point {i} device needs "show": a code or screenshot visual')
        elif kind == 'bars':
            bars = v.get('bars', [])
            if not 2 <= len(bars) <= 5 or any(not 1 <= len(b.get('label', '')) <= 10 or b.get('value', 0) <= 0
                                              for b in bars):
                errors.append(f'point {i} bars needs 2 to 5 bars with short labels and positive values')
            if not v.get('source', '').startswith('https://'):
                errors.append(f'point {i} bars needs "source": the https page the numbers come from')
        elif kind == 'logos':
            import scene3d
            items = v.get('items', [])
            if not 1 <= len(items) <= 4 or any(not re.fullmatch(r'[a-z0-9]+', x) for x in items):
                errors.append(f'point {i} logos needs 1 to 4 Simple Icons slugs like "nextdotjs"')
            elif set(items) & scene3d.ANIMAL_LOGOS:
                errors.append(f'point {i} logos may not include animal or mascot logos: '
                              + ', '.join(sorted(set(items) & scene3d.ANIMAL_LOGOS)))
            else:
                for slug in items:
                    try:
                        scene3d.brand(slug, True)
                    except ValueError as e:
                        errors.append(f'point {i} logos: {e}')
                    except OSError:
                        break  # offline: the render will fall back to the next choice if a slug is wrong
        else:
            errors.append(f'point {i} visual type must be code, diff, terminal, tweet, chat, screenshot, walkthrough, '
                          'ide, quote, diagram, device, bars or logos')
    return errors


SCHEMA = {
    'type': 'object',
    'properties': {
        'reels': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'payoff': {'type': 'string'},
                    'kicker': {'type': 'string'},
                    'hook': {'type': 'string'},
                    'hook_type': {'type': 'string', 'enum': list(HOOK_TYPES)},
                    'hook_visual': VISUAL_SCHEMA,
                    'alternatives': {'type': 'array', 'items': {
                        'type': 'object', 'additionalProperties': False, 'required': ['hook', 'spoken', 'hook_type'],
                        'properties': {'hook': {'type': 'string'}, 'spoken': {'type': 'string'},
                                       'hook_type': {'type': 'string', 'enum': list(HOOK_TYPES)}}}},
                    'points': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {'title': {'type': 'string'}, 'body': {'type': 'string'},
                                           'visual': {'type': 'array', 'items': VISUAL_SCHEMA}},
                            'required': ['title', 'body'],
                            'additionalProperties': False,
                        },
                    },
                    'cta': {'type': 'string'},
                    'dm_keyword': {'type': 'string'}, 'dm_guide': {'type': 'string'},
                    'caption': {'type': 'string'},
                    'hashtags': {'type': 'array', 'items': {'type': 'string'}},
                    'voiceover': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': ['payoff', 'kicker', 'hook', 'hook_type', 'hook_visual', 'alternatives', 'points', 'cta',
                             'caption', 'hashtags', 'voiceover'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['reels'],
    'additionalProperties': False,
}

SYSTEM = """You write short Instagram Reels scripts for @hassanjan.k, a freelance full-stack developer who posts daily dev and AI tips. Each reel is a set of editorial text slides: a hook, three points, and a call to action.

Before anything else, follow the playbook at the end of these instructions: one useful thing per reel, the
payoff written first, a hook that passes its four questions, and real things on screen.

Field rules:
- payoff: the one exact thing the viewer gets, written first (the command, the line of code, the setting, the
  message template, the fix), e.g. "select('*, users(name)') loads posts and authors in one query instead of
  one query per post". Everything else serves it; the three points are its steps (problem, fix, proof).
- hook_type: which playbook hook type the hook is: problem, before_after, shortcut, mistake, test or news.
- hook_visual: the proof under the hook from the very first frame: a code, diff or screenshot visual
  showing the problem or the result itself (the bad line, the error, the slow version next to the fast one).
  Same size limits as point visuals. It is what makes a viewer stop scrolling, so it must be readable at a glance.
- alternatives: 3 more hooks for the same payoff, each a different hook_type where it fits, each with "hook" (the
  on-screen text, same rules as hook) and "spoken" (a replacement for voiceover line 1 with the same rules: it
  starts with a [cue], has at most 14 words and a fresh cue within every 10 spoken words). A
  reviewer picks the strongest of the four, so make every one good and honest.
- kicker: short label shown above the slides, 1 to 3 words, e.g. "Honest take", "Dev tip", "AI tools".
- hook: 3 to 6 words on screen, a phrase people take in at a glance, not a sentence to read ("Your API key is
  *public*", "Stale *cache* after every save"). The spoken line 1 carries the full sentence.
  Wrap the key word or two in *asterisks* to highlight them in the accent color.
- points: exactly 3. Each has a title (max 3 words, a label like "Delete the key", not a
  sentence; it says less than the voice, which carries the detail) and a body (max 8 words, no asterisks; shown only when there is no visual). Few words on screen, lots of space:
  the voice carries the detail.
- cta: a short question for the comments with exactly one *highlighted* word. With a dm_keyword it is instead the
  offer, e.g. "Comment *MCP* for the setup", with the keyword highlighted.
- dm_keyword and dm_guide (comment-to-DM; people who comment the keyword get dm_guide as a private message):
  give them to how-to, trick, versus, beginner and freelance-playbook reels that have more worth sending (the
  full steps, every template); leave them out of myth and ranked reels, which end with a question instead. The
  reel itself always delivers its payoff; the guide is the extended version, never the payoff held back. dm_keyword: one short word in capitals
  (3 to 10 letters) tied to the topic, e.g. "MCP", "STRIPE", "RLS". dm_guide: the full thing the reel promises,
  written as a plain message: the steps, the exact commands or code and the official links, 150 to 900
  characters, no invented facts. The reel only promises what dm_guide really contains.
- caption: 2 to 3 short lines separated by newlines. The last line is a question ending with 👇.
- hashtags: 3 to 5 focused tags that name the topic exactly, each like #nextjs, no spaces. Instagram now reads
  captions for topics more than hashtags, so fewer and precise beats many.
- caption: the first line says the topic in plain searchable words (what someone would type into Instagram
  search, e.g. "Zod schema validation in TypeScript"), not a teaser.
- voiceover: exactly 5 lines, what a narrator says out loud over the slides: one for the hook, one per point, one for the cta.

Voiceover rules (it is heard, not read, while the viewer reads the slides):
- Never read the slide out. Say the same idea in different words and add what the slide leaves out: the why, a quick example, or what goes wrong if you ignore it.
- Talk like a developer telling a friend something useful: contractions, "you", short sentences, a bit of personality. No announcer voice, no filler like "in this video" or "let's dive in".
- Line 1 is the spoken hook: the full promise in about 9 to 14 words, to "you", the same promise as the on-screen
  hook in different words (the screen shows the short version).
- Lines 2 to 4 flow into each other, like one short explanation, not three separate reads. Line 2 is heard
  over point 1, line 3 over point 2 and line 4 over point 3, together with that point's visual, so each line
  must talk about its own point; never jump ahead to a later point.
- Line 5 asks for a comment in a natural way, tied to the topic. Do not say "comment below" or "follow"; the slide already says that. With a dm_keyword, line 5 says the keyword and what they get, e.g. "Comment MCP and I'll send you the whole setup."
- 40 to 55 words in total. The voice speaks at a relaxed pace (about 2.6 words a second) with a beat between
  lines, so every idea lands for slower viewers too; saying less, clearly, beats saying more, fast.
- Write for the ear: no symbols, slashes, code, URLs, parentheses or asterisks. Write numbers and prices as they are said ("five point six", "ten cents per million", "twenty percent"). Product names are written normally.

Visuals (show the real thing instead of a text card; a reviewer looks at every frame and swaps out anything
that does not clearly show what is being said):
- Give each point a "visual": a list of 1 to 3 choices, best first. Each one must show exactly what that
  point's voiceover line says, on its own, to someone watching on a phone.
- code: a real, correct, minimal snippet; max 12 lines, max 40 characters per line; "language" (ts, tsx, js,
  sql, py, bash...), a short file name as "title", and "highlight" with the 1-based line numbers that carry
  the point. Show the mistake or the fix itself, not boilerplate.
- diff: "before" and "after" code (each max 12 lines of 40 characters) plus "language" and "title": the
  mistake turns red and struck through, then the fix arrives in green. The best choice for any "stop doing X,
  do Y" point about code.
- terminal: 1 to 6 real commands, max 40 characters each; they are typed out live.
- No tweet or chat visuals: invented posts and conversations look fake and say nothing useful. For a freelance
  situation, show the template itself as a code card (title like "reply.txt" or "clause.md", language "md").
- screenshot: a public page that shows the point itself (a product screen, a pricing table, a setting, a docs
  heading) and "find": a short exact text on that page to scroll to and outline, like a heading or button
  label. Never a generic homepage, logo or login page. Docs pages often have small text, so always add a
  code or terminal choice after a screenshot when one fits.
- A point with a walkthrough or ide recording needs time on screen: make its voiceover line 18 to 24 words
  (with cues), so the recording plays at a natural speed instead of being rushed.
- walkthrough: a real recording of a public website (no logins): "url" plus 2 to 4 "steps" with "do" one of
  scroll ("screens"), scroll_to ("text" visible on the page), click ("text" of a button or link), hover,
  type ("into" a field's placeholder or label, "text"), wait ("seconds"). Use it to show a tool, a docs page
  or a pricing page the way a person would click through it; texts must exist on the page.
- ide: a real VS Code recording that types code and runs it, so the output on screen is real: "files" (name +
  starting content), optional "setup" commands run off camera (e.g. "npm init -y", "npm i zod tsx"), and up
  to 8 "steps": open ("file"), type ("text", max 12 lines of 60 characters), save, run ("command"), wait.
  Commands start with npm, npx, node, python, pip, git, curl..., with no pipes, redirects, ";" or "$". Use
  current, non-deprecated APIs. This is the strongest visual for "try this" dev tips and for honest "I tested
  it" reels, because it really runs. Add a code or diff choice after it as a backup.
- Only when nothing real can be shown (a pure opinion or habit), leave "visual" out; the slide then shows
  its body text.

3D (only on days the prompt allows it; at most 2 moments per reel, only where 3D explains better; never
people, faces or animals):
- hook_word: not used any more; the hook slide shows hook_visual instead. Leave it out.
- diagram: how something flows between parts, shown as 3D blocks with a glowing packet travelling along
  "flow". "nodes" (2 to 5: id, label max 12 characters, kind one of client, server, db, cache, queue,
  cloud, phone, lock), "edges" ({"from", "to"}), "flow" (1 to 8 hops like "app>api", in the order the
  voiceover describes them). The best choice for caching, webhooks, queues, auth flows and "how X works".
- device: {"device": "laptop", "show": a code visual} puts the code on a 3D laptop that turns into view;
  {"device": "phone", "show": a screenshot visual} for a mobile page. Use it for a product feel.
- bars: 3D bars that rise, only for real numbers from a page you can cite: "title", "unit", 2 to 5 "bars"
  ({"label", "value"}) and "source" (its https url). Never estimate or round beyond the source.
- logos: 1 to 4 tool logos as Simple Icons slugs ("nextdotjs", "supabase", "stripe", "vercel") spinning in.
  No animal or mascot logos (PostgreSQL, Docker, GitHub, Linux, Python...). For "the stack" or a tool intro.
- Packages: only real, official ones (from the tool's maker, e.g. "@modelcontextprotocol/server-postgres",
  "@supabase/supabase-js"), never a lookalike or a random third-party package, least of all for anything that
  handles credentials. Every package name is checked against npm and PyPI.
- Always add a flat choice after a 3D one (code, diff, screenshot) as a backup.

Delivery cues (the voice follows them; without fresh cues it starts strong and fades within two seconds):
- Direct the narrator like an energetic creator talking to camera. Cues go in square brackets before the words they shape; "(break)" is a short beat. Cues and "(break)" are not spoken and do not count as words.
- Never more than 10 spoken words without a fresh cue. Put a new cue at the start of every sentence and at the turn inside a long one, so the energy is renewed before it can fade.
- Line 1 opens high: [fired up], [grinning, punchy], [urgent], [mock outraged]. If the hook has a twist, put "(break)" before it and flip the cue for contrast, e.g. "[grinning, punchy] Most SaaS ideas don't die because of bad code. (break) [deadpan] They die because nobody wanted them."
- Match each cue to what the words do: a punchline gets [deadpan] or [amused]; a warning gets [serious, fast]; a payoff or tip gets [excited] or [confident and fast]; a relatable pain gets [exasperated] or [knowing]; the closing question gets [warm, curious] or [teasing].
- Before the one word that carries a point, you may add [emphasis], e.g. "Nobody [emphasis] wanted it."
- Keep the energy up. At most one low-energy cue ([calm], [soft], [quiet]) in the whole reel, and only as a contrast. Vary the cues; never repeat the same pattern on every line.

What makes reels spread (learned from posts with thousands of comments and saves):
- The hook promises one concrete result the viewer can get: "with one line", "before you deploy". Not a
  general tip; something they can do, and the reel really does it on screen.
- One tension beat in the voiceover: name the doubt the viewer has ("You might think this is slow...") or the
  point where people get stuck ("Most people stop right here"), then answer it. Once per reel, not every line.
- For a how-to, show the real steps on screen (walkthrough, ide, screenshots, code) in the order they happen.

Content rules:
- Never promote or explain tools for gambling, betting, interest-based loans or trading on credit, adult content,
  or anything deceptive (fake reviews, spam, scraping personal data, bypassing paywalls).
- Evergreen only. No news, release dates, version numbers, prices or anything that goes stale.
- No invented personal stories, client anecdotes, testimonials, or made-up numbers and statistics.

Honesty rules (the creator's hard line; deceptive marketing is not allowed even for a good product):
- Never claim results that did not happen: no income, revenue, follower or "I made $X" claims, no fake
  screenshots of earnings or dashboards, no invented metrics.
- Never present a made-up scenario as a real event. A chat or story is illustrative: frame it as POV or as a
  common situation ("every freelancer has had this chat"), never as "my client said".
- Only say "I tested", "I built" or "I tried" when the reel shows a real run of it.
- Never present someone else's code, post or idea as the creator's own; quote and credit it instead.
- The hook may not promise more than the reel delivers. No bait, no exaggerated urgency.
- Technically accurate. If unsure about a detail, choose a different angle.
- Plain English, short words, concrete and useful. No hype.
- No emojis on the slides (kicker, hook, points, cta). Emojis are fine in the caption.
- Every hook must be clearly different from the existing hooks provided.

The playbook (researched rules for what makes people stay, save and send; follow it):

""" + playbook()


def ask_claude(plan, existing_hooks, feedback=None, context=None):
    lines = [f'{i + 1}. {date:%A}: {label}' for i, (date, (_, label)) in enumerate(plan)]
    prompt = (
        f'Write {len(plan)} reels, one per line below, in this order and matching each pillar:\n'
        + '\n'.join(lines)
        + '\n\nExisting hooks you must not repeat or closely paraphrase:\n'
        + '\n'.join(f'- {h}' for h in existing_hooks)
    )
    if context:
        prompt += '\n\n' + context
    if feedback:
        prompt += f'\n\nA previous attempt had these problems, avoid them:\n{feedback}'

    # Claude Code CLI in print mode bills the Claude subscription (CLAUDE_CODE_OAUTH_TOKEN), not the API.
    proc = subprocess.run(
        ['claude', '-p', prompt, '--model', MODEL, '--system-prompt', SYSTEM, '--tools', '',
         '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
         '--json-schema', json.dumps(SCHEMA)],
        capture_output=True, text=True, timeout=900,
    )
    if proc.returncode != 0:
        raise ValueError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-500:]}')
    result = json.loads(proc.stdout)
    if result.get('is_error') or not result.get('structured_output'):
        raise ValueError(f"claude returned no structured output: {str(result.get('result'))[:300]}")
    return result['structured_output']['reels']


HOOK_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['scores', 'best', 'why'],
    'properties': {'scores': {'type': 'array', 'items': {'type': 'integer'}},
                   'best': {'type': 'integer'}, 'why': {'type': 'string'}},
}
HOOK_JUDGE = """You judge hooks for an Instagram Reel by a faceless developer account, as a viewer scrolling fast.
For each numbered hook, score 0 to 10 how well it passes the playbook's four questions in the first second:
is this for me, what do I get or lose, can I see it (the hook_visual shown under it), and what is still missing
that the reel delivers. Score 0 for any hook that promises more than the payoff and the points deliver, or that
needs a term the viewer does not know yet. Prefer specific over clever. "best" is the number of the strongest
hook; "why" says in one sentence what makes it stop the scroll.

""" + playbook()
MIN_HOOK_SCORE = 6


def pick_hook(reel):
    """The strongest of the writer's hook and its alternatives, judged by a second Claude against the playbook.
    The chosen one replaces the hook, its type and voiceover line 1. Any failure keeps the writer's own hook."""
    alts = reel.get('alternatives') or []
    vo = reel.get('voiceover') or []
    options = [{'hook': reel.get('hook', ''), 'spoken': vo[0] if vo else '', 'hook_type': reel.get('hook_type')}] + alts
    if len(options) < 2:
        return reel
    listing = '\n'.join(f"{k}. on screen: {o['hook']} | spoken: {strip_cues(o['spoken'])} | type: {o['hook_type']}"
                         for k, o in enumerate(options, 1))
    prompt = (f"Payoff: {reel.get('payoff', '')}\nhook_visual: {json.dumps(reel.get('hook_visual'), ensure_ascii=False)}\n"
              f"Points: {json.dumps([p.get('title') for p in reel.get('points', [])], ensure_ascii=False)}\n\n"
              f"Hooks:\n{listing}")
    try:
        proc = subprocess.run(['claude', '-p', prompt, '--model', MODEL, '--system-prompt', HOOK_JUDGE, '--tools', '',
                               '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
                               '--json-schema', json.dumps(HOOK_SCHEMA)],
                              capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        verdict = json.loads(proc.stdout).get('structured_output') or {}
        best = int(verdict['best'])
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as e:
        print(f'Hook judge unavailable ({type(e).__name__}); keeping the writer\'s hook')
        return reel
    scores = verdict.get('scores') or []
    print(f"Hook judge: {scores} -> {best}: {verdict.get('why', '')[:200]}")
    if not 1 <= best <= len(options):
        return reel
    if scores and max(scores) < MIN_HOOK_SCORE:
        print(f'  every hook scored below {MIN_HOOK_SCORE}; the best is used, the report will show it')
    if best == 1:
        return reel
    chosen = options[best - 1]
    swapped = {**reel, 'hook': chosen['hook'], 'hook_type': chosen['hook_type'], 'voiceover': [chosen['spoken']] + vo[1:],
               'alternatives': [o for k, o in enumerate(options, 1) if k != best]}
    errors = validate(swapped)
    if errors:
        print(f"  the judge's pick breaks the rules ({'; '.join(errors)[:200]}); keeping the writer's hook")
        return reel
    return swapped


def tidy(reel):
    """Mechanical fixes that need no rewrite: the caption's closing emoji."""
    lines = [l for l in reel.get('caption', '').split('\n') if l.strip()]
    if lines and '?' in lines[-1] and not lines[-1].rstrip().endswith('👇'):
        lines[-1] = lines[-1].rstrip() + ' 👇'
        reel = {**reel, 'caption': '\n'.join(lines)}
    return reel


def repair(reel, errors, rounds=2):
    """Have Claude fix only the listed problems in a draft, keeping everything else. The fixed reel, or None."""
    reel = tidy(reel)
    errors = validate(reel)
    for _ in range(rounds):
        if not errors:
            return reel
        prompt = ('This reel breaks some rules. Fix only these problems and keep everything else as it is, '
                  'including the topic, facts and sources:\n' + '\n'.join(f'- {e}' for e in errors)
                  + '\n\nReturn it as the single item of "reels".\n\n' + json.dumps(reel, indent=2, ensure_ascii=False))
        proc = subprocess.run(
            ['claude', '-p', prompt, '--model', MODEL, '--system-prompt', SYSTEM, '--tools', '',
             '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(SCHEMA)],
            capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
        )
        try:
            fixed = (json.loads(proc.stdout).get('structured_output') or {}).get('reels', [])
        except ValueError:
            fixed = []
        if not fixed:
            continue
        reel = tidy({**reel, **fixed[0]})
        errors = validate(reel)
        print(f"  repair: {'fixed' if not errors else '; '.join(errors)}")
    return None if errors else reel


def generate(reels, count, dates=None, context=None, test=None):
    """Valid new reels for the planned dates. With a test ({'name', 'arm'}), every reel carries it and must follow it."""
    plan = [(d, pillar_for(d)[:2]) for d in (dates or next_post_dates(reels, count))]
    seen = {norm(r['hook']) for r in reels}
    todo, accepted, feedback = list(plan), [], None

    for attempt in range(2):
        if not todo:
            break
        try:
            candidates = ask_claude(todo, [r['hook'] for r in reels] + [r['hook'] for _, r in accepted],
                                    feedback, context)
        except (json.JSONDecodeError, KeyError, StopIteration, ValueError) as e:
            print(f'Attempt {attempt + 1}: invalid JSON from Claude ({e})')
            feedback = 'The response was not valid JSON matching the schema.'
            continue

        problems, missed = [], todo[len(candidates):]
        for slot, cand in zip(todo, candidates):
            date, (pillar, _) = slot
            cand = tidy({**cand, **({'test': test} if test else {})})
            errs = validate(cand)
            if errs and norm(cand.get('hook', '')) not in seen:
                print(f"Repairing {cand.get('hook', '?')!r}: {'; '.join(errs)}")
                fixed = repair(cand, errs)
                if fixed:
                    cand, errs = fixed, []
            if norm(cand.get('hook', '')) in seen:
                errs.append('duplicate hook')
            if errs:
                problems.append(f"- {cand.get('hook', '?')}: {'; '.join(errs)}")
                missed.append(slot)
                continue
            seen.add(norm(cand['hook']))
            accepted.append((date, {**cand, 'pillar': pillar}))
        todo = sorted(missed)
        print(f'Attempt {attempt + 1}: {len(accepted)}/{count} valid reels')
        feedback = '\n'.join(problems) or None
        if problems:
            print('Rejected:\n' + '\n'.join(problems))

    return [reel for _, reel in sorted(accepted, key=lambda a: a[0])]


def learned():
    """The weekly rules from learn.py, or an empty string before there are any."""
    path = render.ROOT / 'learnings.md'
    return path.read_text().strip() if path.exists() else ''


def asked():
    """Topics viewers asked for in comments (learn.py writes them to ideas.json), as a note for the writers."""
    items = history.ideas()
    if not items:
        return ''
    return ('Topics viewers asked for in comments (take one only if it fits what you are writing today; never say '
            'a named person asked, never quote them):\n' + '\n'.join(f"- {i['topic']}" for i in items))


def today(reels, performance=()):
    """One fresh evergreen reel for today's pillar, written with how recent reels actually did."""
    parts = []
    if learned():
        parts.append('Rules learned from this account\'s own results (follow them):\n' + learned())
    if performance:
        parts.append('How the account\'s recent posts did (views, reach, skip rate, watch time, saves, shares). '
                     'Lean into the topics, angles and formats that held people; avoid what they skipped:\n'
                     + '\n'.join(performance))
    series = pillar_for(datetime.now(timezone.utc).date())[2]
    if series == EXTRA_FORMATS['series'][2]:
        done = [r['hook'].replace('*', '') for r in reels if r.get('series') == series]
        parts.append('Episodes of this series so far, in order (continue from the last one; never repeat one):\n'
                     + ('\n'.join(f'{k}. {h}' for k, h in enumerate(done, 1)) or 'none yet: start with lesson 1'))
    if asked():
        parts.append(asked())
    parts.append(three_d_note())
    test = experiment_today()
    if test:
        parts.append(experiment_note())
    context = '\n\n'.join(parts)
    new = generate(reels, 1, dates=[datetime.now(timezone.utc).date()], context=context, test=test)
    if not new and test:
        # A missed day costs more than one reel outside the test; it is simply left out of the comparison.
        print(f"No valid reel that follows the test ({test['name']}: {test['arm']}); writing one without it")
        new = generate(reels, 1, dates=[datetime.now(timezone.utc).date()], context=context)
    return new[0] if new else None


def series_label(reels, day):
    """The day's series and its next episode number, e.g. ('Client vs Me', 4)."""
    name = pillar_for(day)[2]
    return name, 1 + sum(1 for r in reels if r.get('series') == name and r.get('posted_at'))


def append(reels, new):
    next_id = max((int(r['id']) for r in reels), default=0) + 1
    last_style = reels[-1]['style'] if reels else 'dark'
    for reel in new:
        last_style = 'dark' if last_style == 'light' else 'light'
        reels.append({
            'id': next_id, 'pillar': reel['pillar'], 'style': last_style, 'kicker': reel['kicker'].strip(),
            'hook': reel['hook'].strip(), **({'hook_word': reel['hook_word']} if reel.get('hook_word') else {}),
            **{k: reel[k] for k in ('payoff', 'hook_type', 'hook_visual', 'alternatives') if reel.get(k)},
            'points': reel['points'], 'cta': reel['cta'].strip(),
            **{k: reel[k] for k in ('dm_keyword', 'dm_guide') if reel.get(k)},
            'caption': reel['caption'].strip(), 'hashtags': reel['hashtags'],
            'voiceover': [l.strip() for l in reel['voiceover']], 'posted_at': None, 'media_id': None,
        })
        next_id += 1


VO_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['reels'],
    'properties': {'reels': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['id', 'voiceover'],
        'properties': {'id': {'type': 'integer'}, 'voiceover': {'type': 'array', 'items': {'type': 'string'}}}}}},
}


def add_voiceovers(reels):
    """Write the spoken script for unposted reels that were queued before voiceovers existed."""
    todo = [r for r in reels if not r.get('posted_at') and not r.get('voiceover')]
    feedback = {}
    for attempt in range(3):
        if not todo:
            break
        slides = [{**{k: r[k] for k in ('id', 'kicker', 'hook', 'points', 'cta')},
                   **({'previous_attempt_problems': feedback[r['id']]} if r['id'] in feedback else {})} for r in todo]
        prompt = ('Write the voiceover for each of these existing reels. Keep the slides exactly as they are; '
                  'return only each reel id with its 5 voiceover lines.\n\n' + json.dumps(slides, indent=2))
        proc = subprocess.run(
            ['claude', '-p', prompt, '--model', MODEL, '--system-prompt', SYSTEM, '--tools', '',
             '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(VO_SCHEMA)],
            capture_output=True, text=True, timeout=900,
        )
        out = (json.loads(proc.stdout).get('structured_output') or {}) if proc.returncode == 0 else {}
        by_id = {r['id']: r['voiceover'] for r in out.get('reels', [])}
        for r in todo:
            if r['id'] in by_id:
                errs = validate({**r, 'voiceover': by_id[r['id']]})
                if errs:
                    print(f"Reel {r['id']}: " + '; '.join(errs))
                    feedback[r['id']] = errs
                else:
                    r['voiceover'] = [l.strip() for l in by_id[r['id']]]
        todo = [r for r in todo if not r.get('voiceover')]
        print(f'Attempt {attempt + 1}: {len(todo)} reels still without a voiceover')
    return todo


def add_cues(reels):
    """Add delivery cues to queued voiceovers written before cues existed, keeping every spoken word."""
    todo = [r for r in reels if not r.get('posted_at') and r.get('voiceover')
            and ('--redo' in sys.argv or cue_errors(r['voiceover']))]
    feedback, done = {}, set()
    for attempt in range(3):
        if not todo:
            break
        items = [{'id': r['id'], 'hook': r['hook'], 'voiceover': r['voiceover'],
                  **({'previous_attempt_problems': feedback[r['id']]} if r['id'] in feedback else {})} for r in todo]
        prompt = ('Add delivery cues to each voiceover, following the cue rules. Do not change, add or remove any '
                  'spoken word; only insert [cues] and (break). Return each reel id with its 5 cued lines.\n\n'
                  + json.dumps(items, indent=2, ensure_ascii=False))
        proc = subprocess.run(
            ['claude', '-p', prompt, '--model', MODEL, '--system-prompt', SYSTEM, '--tools', '',
             '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(VO_SCHEMA)],
            capture_output=True, text=True, timeout=900,
        )
        out = (json.loads(proc.stdout).get('structured_output') or {}) if proc.returncode == 0 else {}
        by_id = {r['id']: r['voiceover'] for r in out.get('reels', [])}
        for r in todo:
            new = by_id.get(r['id'])
            if not new:
                continue
            errs = validate({**r, 'voiceover': new})
            if [re.sub(r'\W', '', strip_cues(l)).lower() for l in new] != \
               [re.sub(r'\W', '', strip_cues(l)).lower() for l in r['voiceover']]:
                errs.append('the spoken words changed; keep every word exactly and only add cues')
            if errs:
                print(f"Reel {r['id']}: " + '; '.join(errs))
                feedback[r['id']] = errs
            else:
                r['voiceover'] = [l.strip() for l in new]
                done.add(r['id'])
        todo = [r for r in todo if r['id'] not in done]
        print(f'Attempt {attempt + 1}: {len(todo)} reels still without good cues')
    return todo


VISUALS_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['reels'],
    'properties': {'reels': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['id', 'visuals'],
        'properties': {'id': {'type': 'integer'},
                       'visuals': {'type': 'array', 'items': {'type': 'array', 'items': VISUAL_SCHEMA}}}}}},
}


def add_visuals(reels):
    """Pick code, terminal or screenshot visuals for queued reels written before visuals existed.
    Returns the reels that still have none; a point may legitimately stay without one."""
    todo = [r for r in reels if not r.get('posted_at') and not any('visual' in p for p in r['points'])]
    feedback, done = {}, set()
    for attempt in range(3):
        if not todo:
            break
        items = [{'id': r['id'], 'kicker': r['kicker'], 'hook': r['hook'], 'points': r['points'],
                  'voiceover': [strip_cues(l) for l in r['voiceover']],
                  **({'previous_attempt_problems': feedback[r['id']]} if r['id'] in feedback else {})} for r in todo]
        prompt = ('Pick visuals for each reel, following the visual rules. For each reel return "visuals": exactly '
                  '3 lists, one per point in order (voiceover lines 2 to 4 are spoken over points 1 to 3). Use an '
                  'empty list for a point with nothing real to show.\n\n' + json.dumps(items, indent=2, ensure_ascii=False))
        proc = subprocess.run(
            ['claude', '-p', prompt, '--model', MODEL, '--system-prompt', SYSTEM, '--tools', '',
             '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(VISUALS_SCHEMA)],
            capture_output=True, text=True, timeout=1200,
        )
        out = (json.loads(proc.stdout).get('structured_output') or {}) if proc.returncode == 0 else {}
        by_id = {r['id']: r['visuals'] for r in out.get('reels', [])}
        for r in todo:
            vis = by_id.get(r['id'])
            if vis is None:
                continue
            errs = [] if len(vis) == 3 else ['return exactly 3 lists, one per point']
            errs += [e for i, v in enumerate(vis[:3], 1) if v for e in visual_errors(i, v)]
            if errs:
                print(f"Reel {r['id']}: " + '; '.join(errs))
                feedback[r['id']] = errs
                continue
            for point, v in zip(r['points'], vis):
                if v:
                    point['visual'] = v
            done.add(r['id'])
        todo = [r for r in todo if r['id'] not in done]
        print(f'Attempt {attempt + 1}: {len(todo)} reels still without visuals')
    return todo


# Reels posted before the playbook (2026-10-01) have none of these.
NEW_FIELDS = ('payoff', 'hook_type', 'hook_visual', 'alternative', 'no longer used', 'leave hook_word out')


def main():
    reels = json.loads(render.QUEUE.read_text())

    if '--visuals' in sys.argv:
        missing = add_visuals(reels)
        render.QUEUE.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')
        if missing:
            raise SystemExit(f'{len(missing)} reels still have no visuals')
        return

    if '--cues' in sys.argv:
        missing = add_cues(reels)
        render.QUEUE.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')
        if missing:
            raise SystemExit(f'{len(missing)} reels still have no cues')
        return

    if '--voiceover' in sys.argv:
        missing = add_voiceovers(reels)
        render.QUEUE.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')
        if missing:
            raise SystemExit(f'{len(missing)} reels still have no voiceover')
        return

    if '--check' in sys.argv:
        # Posted reels predate later rules (voiceover, cues, 3 to 5 hashtags); only unposted ones must meet them.
        bad = [(r['id'], [e for e in validate(r) if not (r.get('posted_at') and ('voiceover' in e or 'cue' in e
                                                                                   or 'hashtags' in e or 'hook has' in e or 'body has' in e
                                                                                   or 'title has' in e
                                                                                   or any(k in e for k in NEW_FIELDS)))])
               for r in reels]
        bad = [(i, e) for i, e in bad if e]
        dupes = len(reels) - len({norm(r['hook']) for r in reels})
        for i, errs in bad:
            print(f'Reel {i}: ' + '; '.join(errs))
        if dupes:
            print(f'{dupes} duplicate hook(s)')
        print(f'{len(reels)} reels, {sum(1 for r in reels if not r.get("posted_at"))} unposted, '
              f'{len(bad)} invalid')
        sys.exit(1 if bad or dupes else 0)

    # Reels are written on the day by publish.py; queuing a batch is a deliberate, manual act.
    if '--force' not in sys.argv:
        raise SystemExit(__doc__)
    unposted = sum(1 for r in reels if not r.get('posted_at'))
    new = generate(reels, BATCH)
    if not new:
        raise SystemExit('ERROR: Claude returned no valid reels')
    append(reels, new)
    render.QUEUE.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')
    print(f'Added {len(new)} reels, queue now has {unposted + len(new)} unposted')
    if len(new) < BATCH:
        print(f'Warning: only {len(new)} of {BATCH} reels passed validation')


if __name__ == '__main__':
    main()
