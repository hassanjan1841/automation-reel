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
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import render
from voice import strip_cues

MODEL = 'claude-sonnet-5'
BATCH = 14
POST_HOUR_UTC = 14

PILLARS = {
    0: ('ai', 'AI tools for developers'),
    1: ('devtip', 'Dev tip on Next.js, React, TypeScript, Supabase, Stripe or Postgres'),
    2: ('take', 'Honest take on freelancing or dev life'),
    3: ('freelance', 'Freelance or Upwork lesson'),
    4: ('concept', 'Tech concept explained simply'),
    5: ('saas', 'SaaS building and validation'),
    6: ('productivity', 'Behind the scenes or productivity'),
}

EMOJI = re.compile('[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]')
HASHTAG = re.compile(r'^#[A-Za-z0-9_]+$')
SYMBOLS = re.compile(r'[/&%$#;()\[\]{}<>=_|\\]')
VO_MAX_WORDS = 70


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
    if not kicker or words(kicker) > 3 or len(kicker) > 24:
        errors.append('kicker must be a short label (max 3 words)')

    hook = reel.get('hook', '')
    if not 6 <= words(hook) <= 12:
        errors.append(f'hook has {words(hook)} words, needs 6 to 12')
    if not highlights(hook):
        errors.append('hook needs at least one *highlighted* word with balanced asterisks')

    points = reel.get('points', [])
    if len(points) != 3:
        errors.append(f'needs exactly 3 points, got {len(points)}')
    for i, p in enumerate(points, 1):
        title, body = p.get('title', ''), p.get('body', '')
        slide_text += [title, body]
        if not title or words(title) > 8:
            errors.append(f'point {i} title has {words(title)} words, max 8')
        if not body or words(body) > 16:
            errors.append(f'point {i} body has {words(body)} words, max 16')
        if highlights(title) is None:
            errors.append(f'point {i} title has unbalanced asterisks')
        if '*' in body:
            errors.append(f'point {i} body must not use highlights')
        errors += visual_errors(i, p.get('visual'))

    cta = reel.get('cta', '').strip()
    spans = highlights(cta)
    if not cta.endswith('?'):
        errors.append('cta must be a question')
    if not spans or len(spans) != 1:
        errors.append('cta needs exactly one *highlighted* word')

    if any(EMOJI.search(t) for t in slide_text):
        errors.append('no emojis allowed on slides')

    lines = [l for l in reel.get('caption', '').split('\n') if l.strip()]
    if not 2 <= len(lines) <= 3:
        errors.append(f'caption needs 2 to 3 lines, got {len(lines)}')
    elif not (lines[-1].rstrip().endswith('👇') and '?' in lines[-1]):
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
            elif similar(line, slide) > 0.6:
                errors.append(f'voiceover line {i} repeats the slide text; say it in different words')
        n = sum(words(l) for l in said)
        if not 35 <= n <= VO_MAX_WORDS:
            errors.append(f'voiceover has {n} words, needs 35 to {VO_MAX_WORDS}')
        if words(said[0]) > 14:
            errors.append(f'voiceover line 1 has {words(said[0])} words, max 14')
        errors += cue_errors(vo)

    tags = reel.get('hashtags', [])
    if not 8 <= len(tags) <= 12:
        errors.append(f'needs 8 to 12 hashtags, got {len(tags)}')
    if any(not HASHTAG.match(t) for t in tags) or len({t.lower() for t in tags}) != len(tags):
        errors.append('hashtags must be unique #words with no spaces')
    return errors


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


VISUAL_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['type'],
    'properties': {
        'type': {'type': 'string', 'enum': ['code', 'terminal', 'screenshot']},
        'language': {'type': 'string'}, 'title': {'type': 'string'}, 'code': {'type': 'string'},
        'highlight': {'type': 'array', 'items': {'type': 'integer'}},
        'commands': {'type': 'array', 'items': {'type': 'string'}},
        'url': {'type': 'string'}, 'find': {'type': 'string'},
    },
}


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
        if kind == 'code':
            lines = v.get('code', '').rstrip('\n').split('\n')
            if not v.get('code', '').strip() or not v.get('language'):
                errors.append(f'point {i} code visual needs code and a language')
            elif len(lines) > 12 or max(len(l) for l in lines) > 40:
                errors.append(f'point {i} code is {len(lines)} lines, longest {max(len(l) for l in lines)} '
                              'characters; max 12 lines of 40 characters')
            elif any(not 1 <= n <= len(lines) for n in v.get('highlight', [])):
                errors.append(f'point {i} code highlight must be line numbers inside the code')
        elif kind == 'terminal':
            cmds = v.get('commands', [])
            if not 1 <= len(cmds) <= 6 or any(len(c) > 40 for c in cmds):
                errors.append(f'point {i} terminal needs 1 to 6 commands of max 40 characters')
        elif kind == 'screenshot':
            if not v.get('url', '').startswith('https://'):
                errors.append(f'point {i} screenshot needs an https url')
            if not 3 <= len(v.get('find', '')) <= 80:
                errors.append(f'point {i} screenshot needs "find": short exact text on that page to outline')
        else:
            errors.append(f'point {i} visual type must be code, terminal or screenshot')
    return errors


SCHEMA = {
    'type': 'object',
    'properties': {
        'reels': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'kicker': {'type': 'string'},
                    'hook': {'type': 'string'},
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
                    'caption': {'type': 'string'},
                    'hashtags': {'type': 'array', 'items': {'type': 'string'}},
                    'voiceover': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': ['kicker', 'hook', 'points', 'cta', 'caption', 'hashtags', 'voiceover'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['reels'],
    'additionalProperties': False,
}

SYSTEM = """You write short Instagram Reels scripts for @hassanjan.k, a freelance full-stack developer who posts daily dev and AI tips. Each reel is a set of editorial text slides: a hook, three points, and a call to action.

Field rules:
- kicker: short label shown above the slides, 1 to 3 words, e.g. "Honest take", "Dev tip", "AI tools".
- hook: 6 to 12 words. Wrap the key word or two in *asterisks* to highlight them in the accent color.
- points: exactly 3. Each has a title (max 8 words) and a body (max 16 words, no asterisks).
- cta: a short question for the comments with exactly one *highlighted* word.
- caption: 2 to 3 short lines separated by newlines. The last line is a question ending with 👇.
- hashtags: 8 to 12 relevant tags, each like #nextjs, no spaces.
- voiceover: exactly 5 lines, what a narrator says out loud over the slides: one for the hook, one per point, one for the cta.

Voiceover rules (it is heard, not read, while the viewer reads the slides):
- Never read the slide out. Say the same idea in different words and add what the slide leaves out: the why, a quick example, or what goes wrong if you ignore it.
- Talk like a developer telling a friend something useful: contractions, "you", short sentences, a bit of personality. No announcer voice, no filler like "in this video" or "let's dive in".
- Line 1 is the spoken hook and must grab in the first two seconds: a surprising claim, a sharp question or a tension. Max 14 words.
- Lines 2 to 4 flow into each other, like one short explanation, not three separate reads.
- Line 5 asks for a comment in a natural way, tied to the topic. Do not say "comment below" or "follow"; the slide already says that.
- 35 to 70 words in total, so the reel stays under about 25 seconds.
- Write for the ear: no symbols, slashes, code, URLs, parentheses or asterisks. Write numbers and prices as they are said ("five point six", "ten cents per million", "twenty percent"). Product names are written normally.

Visuals (show the real thing instead of a text card; a reviewer looks at every frame and swaps out anything
that does not clearly show what is being said):
- Give each point a "visual": a list of 1 to 3 choices, best first. Each one must show exactly what that
  point's voiceover line says, on its own, to someone watching on a phone.
- code: a real, correct, minimal snippet; max 12 lines, max 40 characters per line; "language" (ts, tsx, js,
  sql, py, bash...), a short file name as "title", and "highlight" with the 1-based line numbers that carry
  the point. Show the mistake or the fix itself, not boilerplate.
- terminal: 1 to 6 real commands, max 40 characters each.
- screenshot: a public page that shows the point itself (a product screen, a pricing table, a setting, a docs
  heading) and "find": a short exact text on that page to scroll to and outline, like a heading or button
  label. Never a generic homepage, logo or login page. Docs pages often have small text, so always add a
  code or terminal choice after a screenshot when one fits.
- Only when nothing real can be shown (a pure opinion or habit), leave "visual" out; the slide then shows
  its body text.

Delivery cues (the voice follows them; without fresh cues it starts strong and fades within two seconds):
- Direct the narrator like an energetic creator talking to camera. Cues go in square brackets before the words they shape; "(break)" is a short beat. Cues and "(break)" are not spoken and do not count as words.
- Never more than 10 spoken words without a fresh cue. Put a new cue at the start of every sentence and at the turn inside a long one, so the energy is renewed before it can fade.
- Line 1 opens high: [fired up], [grinning, punchy], [urgent], [mock outraged]. If the hook has a twist, put "(break)" before it and flip the cue for contrast, e.g. "[grinning, punchy] Most SaaS ideas don't die because of bad code. (break) [deadpan] They die because nobody wanted them."
- Match each cue to what the words do: a punchline gets [deadpan] or [amused]; a warning gets [serious, fast]; a payoff or tip gets [excited] or [confident and fast]; a relatable pain gets [exasperated] or [knowing]; the closing question gets [warm, curious] or [teasing].
- Before the one word that carries a point, you may add [emphasis], e.g. "Nobody [emphasis] wanted it."
- Keep the energy up. At most one low-energy cue ([calm], [soft], [quiet]) in the whole reel, and only as a contrast. Vary the cues; never repeat the same pattern on every line.

Content rules:
- Evergreen only. No news, release dates, version numbers, prices or anything that goes stale.
- No invented personal stories, client anecdotes, testimonials, or made-up numbers and statistics.
- Technically accurate. If unsure about a detail, choose a different angle.
- Plain English, short words, concrete and useful. No hype.
- No emojis on the slides (kicker, hook, points, cta). Emojis are fine in the caption.
- Every hook must be clearly different from the existing hooks provided."""


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


def generate(reels, count, dates=None, context=None):
    plan = [(d, PILLARS[d.weekday()]) for d in (dates or next_post_dates(reels, count))]
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
            errs = validate(cand)
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


def today(reels, performance=()):
    """One fresh evergreen reel for today's pillar, written with how recent reels actually did."""
    context = None
    if performance:
        context = ('How the account\'s recent posts did (views, reach, skip rate, watch time, saves, shares). '
                   'Lean into the topics, angles and formats that held people; avoid what they skipped:\n'
                   + '\n'.join(performance))
    new = generate(reels, 1, dates=[datetime.now(timezone.utc).date()], context=context)
    return new[0] if new else None


def append(reels, new):
    next_id = max((int(r['id']) for r in reels), default=0) + 1
    last_style = reels[-1]['style'] if reels else 'dark'
    for reel in new:
        last_style = 'dark' if last_style == 'light' else 'light'
        reels.append({
            'id': next_id, 'pillar': reel['pillar'], 'style': last_style, 'kicker': reel['kicker'].strip(),
            'hook': reel['hook'].strip(), 'points': reel['points'], 'cta': reel['cta'].strip(),
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
        bad = [(r['id'], [e for e in validate(r) if not (r.get('posted_at') and 'voiceover' in e)]) for r in reels]
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
