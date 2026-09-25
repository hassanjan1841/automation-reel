"""Top up reels.json with new reels written by Claude when the queue runs low.

Usage:
  python generate.py            add 14 reels if fewer than 7 are unposted
  python generate.py --force    add 14 reels regardless
  python generate.py --check    validate reels.json and exit
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone

import anthropic

import render

MODEL = 'claude-sonnet-5'
BATCH = 14
LOW_WATER = 7
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

    tags = reel.get('hashtags', [])
    if not 8 <= len(tags) <= 12:
        errors.append(f'needs 8 to 12 hashtags, got {len(tags)}')
    if any(not HASHTAG.match(t) for t in tags) or len({t.lower() for t in tags}) != len(tags):
        errors.append('hashtags must be unique #words with no spaces')
    return errors


def norm(hook):
    return re.sub(r'[^a-z0-9]', '', hook.lower())


def next_post_dates(reels, count):
    """Dates the new reels will go out, given one post per day at POST_HOUR_UTC."""
    now = datetime.now(timezone.utc)
    posted_today = any((r.get('posted_at') or '').startswith(now.date().isoformat()) for r in reels)
    first = now.date() if now.hour < POST_HOUR_UTC and not posted_today else now.date() + timedelta(days=1)
    queued = sum(1 for r in reels if not r.get('posted_at'))
    return [first + timedelta(days=queued + i) for i in range(count)]


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
                            'properties': {'title': {'type': 'string'}, 'body': {'type': 'string'}},
                            'required': ['title', 'body'],
                            'additionalProperties': False,
                        },
                    },
                    'cta': {'type': 'string'},
                    'caption': {'type': 'string'},
                    'hashtags': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': ['kicker', 'hook', 'points', 'cta', 'caption', 'hashtags'],
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

Content rules:
- Evergreen only. No news, release dates, version numbers, prices or anything that goes stale.
- No invented personal stories, client anecdotes, testimonials, or made-up numbers and statistics.
- Technically accurate. If unsure about a detail, choose a different angle.
- Plain English, short words, concrete and useful. No hype.
- No emojis on the slides (kicker, hook, points, cta). Emojis are fine in the caption.
- Every hook must be clearly different from the existing hooks provided."""


def ask_claude(client, plan, existing_hooks, feedback=None):
    lines = [f'{i + 1}. {date:%A}: {label}' for i, (date, (_, label)) in enumerate(plan)]
    prompt = (
        f'Write {len(plan)} reels, one per line below, in this order and matching each pillar:\n'
        + '\n'.join(lines)
        + '\n\nExisting hooks you must not repeat or closely paraphrase:\n'
        + '\n'.join(f'- {h}' for h in existing_hooks)
    )
    if feedback:
        prompt += f'\n\nA previous attempt had these problems, avoid them:\n{feedback}'

    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=SYSTEM,
        messages=[{'role': 'user', 'content': prompt}],
        output_config={'format': {'type': 'json_schema', 'schema': SCHEMA}},
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason in ('max_tokens', 'refusal'):
        raise ValueError(f'response stopped with {message.stop_reason}')
    text = next(b.text for b in message.content if b.type == 'text')
    return json.loads(text)['reels']


def generate(reels, count):
    client = anthropic.Anthropic()
    plan = [(d, PILLARS[d.weekday()]) for d in next_post_dates(reels, count)]
    seen = {norm(r['hook']) for r in reels}
    todo, accepted, feedback = list(plan), [], None

    for attempt in range(2):
        if not todo:
            break
        try:
            candidates = ask_claude(client, todo, [r['hook'] for r in reels] + [r['hook'] for _, r in accepted],
                                    feedback)
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


def append(reels, new):
    next_id = max((int(r['id']) for r in reels), default=0) + 1
    last_style = reels[-1]['style'] if reels else 'dark'
    for reel in new:
        last_style = 'dark' if last_style == 'light' else 'light'
        reels.append({
            'id': next_id, 'pillar': reel['pillar'], 'style': last_style, 'kicker': reel['kicker'].strip(),
            'hook': reel['hook'].strip(), 'points': reel['points'], 'cta': reel['cta'].strip(),
            'caption': reel['caption'].strip(), 'hashtags': reel['hashtags'], 'posted_at': None, 'media_id': None,
        })
        next_id += 1


def main():
    reels = json.loads(render.QUEUE.read_text())

    if '--check' in sys.argv:
        bad = [(r['id'], validate(r)) for r in reels]
        bad = [(i, e) for i, e in bad if e]
        dupes = len(reels) - len({norm(r['hook']) for r in reels})
        for i, errs in bad:
            print(f'Reel {i}: ' + '; '.join(errs))
        if dupes:
            print(f'{dupes} duplicate hook(s)')
        print(f'{len(reels)} reels, {sum(1 for r in reels if not r.get("posted_at"))} unposted, '
              f'{len(bad)} invalid')
        sys.exit(1 if bad or dupes else 0)

    unposted = sum(1 for r in reels if not r.get('posted_at'))
    if unposted >= LOW_WATER and '--force' not in sys.argv:
        print(f'{unposted} unposted reels in the queue, no top-up needed')
        return

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
