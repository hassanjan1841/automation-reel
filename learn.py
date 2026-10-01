"""The learning loop: measure how every post did, judge the writer's rules and the running test, and turn what
the numbers show into rules the daily writer follows (learnings.md) plus a report for the creator. It runs every
day by default (learn.yml, started by scheduler.py; repo variable LEARN_DAYS picks the days, e.g. "sun,wed").

Each run:
  1. measure    reads each post's Instagram numbers every day for its first week, then weekly until they settle
                (history.snapshot_due), and appends them to metrics/ (history.py); keyword comments and comment
                topics are read too; the daily readings show how long a reel keeps getting views
  2. score      every reel against the account's usual (median) skip rate and share of the reel watched, by
                pillar, series, visual, 3D, slot and test option; views are compared at the same age (7 days)
  3. judge      rules on trial for 2 weeks are compared with the reels before them: kept, retired or still on trial;
                the running test is concluded once each option has enough reels, and the next test starts
  4. write      Claude proposes new rules; each must cite groups of at least MIN_EVIDENCE reels that differ
                clearly, and never touch the creator's hard rules, or it is dropped
  5. report     reports/<week>.md and out/report.md (the workflow opens a GitHub issue with it)

Env: IG_TOKEN, CLAUDE_CODE_OAUTH_TOKEN (write-up, comment topics and the look at the covers), CLAUDE_MODEL,
     GRAPH_VERSION, EXPERIMENT=off (no test running)
Usage: python learn.py            one run of the loop
"""

import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import dm
import generate
import history
import render
import scheduler

GRAPH = f"https://graph.instagram.com/{os.environ.get('GRAPH_VERSION', 'v25.0')}"
REPORT = render.OUT_DIR / 'report.md'
CAROUSELS = render.ROOT / 'carousels.json'
# One request per metric: one unsupported metric fails the whole request. follows and profile_visits are read when
# Instagram offers them for the post and stay empty otherwise.
REEL_METRICS = ('views', 'reach', 'reels_skip_rate', 'ig_reels_avg_watch_time', 'saved', 'shares', 'likes',
                'comments', 'follows', 'profile_visits')
CAROUSEL_METRICS = ('views', 'reach', 'saved', 'shares', 'likes', 'comments', 'follows', 'profile_visits')
# A post is first measured about a day after it went out (views at day 1); it is scored against the others only
# from two days old, when skip rate and watch time have settled.
MIN_AGE_HOURS = 20
SCORE_MIN_DAYS = 2
MIN_EVIDENCE = 5            # reels on each side of any comparison before it can become or judge a rule
CLEAR_SKIP = 2.0            # skip rate points that count as a real difference
CLEAR_WATCHED = 0.05        # share of the reel watched that counts as a real difference
RULE_TRIAL_DAYS = 14        # a new rule is judged after this long
RULE_GIVE_UP_DAYS = 28      # still no clear effect by then: retired, so the writer's prompt stays short
MAX_ACTIVE_RULES = 10
MAX_NEW_RULES = 3           # per 7 days, however often the loop runs
MAX_RULE_WORDS = 30         # a rule is one short instruction; the writer's prompt stays short
EXPERIMENT_MAX_DAYS = 21    # a test that cannot get enough reels in 3 weeks ends without a verdict
IDEA_DAYS = 14              # comments on posts from the last two weeks become topic ideas
# The creator's hard rules live in the writer's prompt; a learned rule may never touch them.
HARD_RULES = re.compile(r'\b(music|songs?|soundtrack|melod\w*|reddit|faces?|talking head|animals?|mascots?|fake|'
                        r'invent\w*|made.up|comment below|follow (me|us|for))\b', re.I)
GROUP_FIELDS = ('pillar', 'series', 'visuals', 'hook_word', 'three_d', 'hook_type', 'opening', 'slot', 'test')
# What the writer controls. A rule rests only on these; the slot (posting time) is a setting for the creator's
# decision, not something the writer can act on.
RULE_FIELDS = ('pillar', 'series', 'visuals', 'hook_word', 'three_d', 'hook_type', 'opening', 'test')


def redact(error, token):
    """An error's text without the token: a failed request's message can include its URL, access_token and all."""
    return str(error).replace(token, '***') if token else str(error)


def utcnow():
    return datetime.now(timezone.utc)


def metric(media_id, name, token):
    try:
        resp = requests.get(f'{GRAPH}/{media_id}/insights', params={'metric': name, 'access_token': token}, timeout=30)
        data = resp.json().get('data', []) if resp.ok else []
        return data[0]['values'][0]['value'] if data else None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


# ---------- 1. measure ----------

def posts(reels, carousels):
    """Every published post: (kind, id, entry)."""
    out = [('reel', r['id'], r) for r in reels if r.get('media_id') and r.get('posted_at')]
    out += [('carousel', c['media_id'], c) for c in carousels if c.get('media_id') and c.get('posted_at')]
    return out


def age_hours(entry, now):
    return (now - datetime.fromisoformat(entry['posted_at'])).total_seconds() / 3600


def measure(reels, carousels, token, stored):
    """New snapshots for posts that are due one (history.snapshot_due), and the text of recent comments (for topic
    ideas)."""
    now, rows, texts = utcnow(), [], []
    for kind, post_id, entry in posts(reels, carousels):
        hours = age_hours(entry, now)
        if hours < MIN_AGE_HOURS or not history.snapshot_due(stored.get(history.key(kind, post_id), []), hours / 24,
                                                                  now.date()):
            continue
        names = REEL_METRICS if kind == 'reel' else CAROUSEL_METRICS
        row = {'date': now.date().isoformat(), 'kind': kind, 'id': post_id, 'media_id': entry['media_id'],
               'age_days': round(hours / 24, 1), **{n: metric(entry['media_id'], n, token) for n in names}}
        if entry.get('dm_keyword') or hours <= IDEA_DAYS * 24:
            try:
                found = dm.comments(entry['media_id'], token)
            except (dm.DMError, requests.RequestException, ValueError) as e:
                print(f'Comments of {kind} {post_id} unavailable: {redact(e, token)}')
                found = None
            if found is not None:
                if entry.get('dm_keyword'):
                    row['dm_asks'] = sum(dm.asks(c.get('text'), entry['dm_keyword']) for c in found)
                if hours <= IDEA_DAYS * 24:
                    # Only the words, never who wrote them; bare keyword requests carry no topic.
                    texts += [c['text'] for c in found if c.get('text') and not (
                        entry.get('dm_keyword') and dm.asks(c['text'], entry['dm_keyword']) and len(c['text'].split()) <= 3)]
        rows.append(row)
    return rows, texts


# ---------- 2. score ----------

def looks(reel):
    """The reel's visual types, whether its hook word spun in as 3D text, whether it had any 3D at all, its hook
    type (playbook.md) and its opening: "proof" when a code, diff or screenshot sat under the hook from frame 0,
    else "text". Uses what was actually shown (publish.shown) when recorded; older reels fall back to each
    point's first choice."""
    shown = reel.get('shown')
    if shown:
        visuals = sorted({t for t in shown[1:1 + len(reel['points'])] if t != 'text'})
        hook_3d = shown[0] == 'word'
        opening = 'proof' if shown[0] in generate.HOOK_VISUALS else 'text'
    else:
        visuals = sorted({v['type'] for p in reel['points'] for v in (p.get('visual') or [])[:1]})
        hook_3d = bool(reel.get('hook_word'))
        opening = 'proof' if reel.get('hook_visual') else 'text'
    three_d = hook_3d or any(v in generate.SCENES_3D for v in visuals)
    return {'visuals': visuals or ['text'], 'hook_word': '3D word' if hook_3d else 'text only',
            'three_d': '3D' if three_d else 'flat', 'hook_type': reel.get('hook_type') or 'untagged',
            'opening': opening}


def slot_of(reel):
    """The day's slot: recorded since slots were tracked, else from the post hour (12:00, 16:00, 20:00 UTC)."""
    return scheduler.slot_of(reel)


def median(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return statistics.median(values) if values else None


def views_curve(post_snapshots):
    """Views at 1, 3 and 7 days old, and the share of the first week's views that came after day 1 (how long a reel
    kept being shown)."""
    v1, v3, v7 = (history.value_at(post_snapshots, 'views', d) for d in (1, 3, 7))
    return {'views_1d': v1, 'views_3d': v3, 'views_7d': v7,
            'late_views': round((v7 - v1) / v7, 3) if v1 is not None and v7 else None}


def table(reels, carousels, snaps):
    """One row per measured post from its latest snapshot, reels scored against the account's usual."""
    rows = []
    for kind, post_id, entry in posts(reels, carousels):
        s = snaps.get(history.key(kind, post_id))
        if not s:
            continue
        latest = {k: v for k, v in s[-1].items() if k not in ('date', 'kind', 'id', 'media_id')}
        row = {'kind': kind, 'id': post_id, 'media_id': entry['media_id'], 'posted_at': entry['posted_at'][:16],
               **latest, **views_curve(s)}
        if kind == 'reel':
            watch = latest.get('ig_reels_avg_watch_time')
            seconds = entry.get('seconds')
            test = entry.get('test') or {}
            row.update({'hook': entry['hook'].replace('*', ''), 'pillar': entry.get('pillar', '?'),
                        'series': entry.get('series') or ('news' if entry.get('pillar') == 'timely' else 'none'),
                        **looks(entry), 'slot': f'slot {slot_of(entry)}',
                        'test': f"{test['name']}: {test['arm']}" if test.get('name') else 'none',
                        'seconds': seconds,
                        'watched_share': round(watch / 1000 / seconds, 3) if watch and seconds else None})
        else:
            row['title'] = entry.get('title', '')
        rows.append(row)
    reel_rows = [r for r in rows if r['kind'] == 'reel']
    # The usual is taken from reels at least SCORE_MIN_DAYS old; a day-old reel's numbers are still moving.
    old = [r for r in reel_rows if r.get('age_days', 0) >= SCORE_MIN_DAYS]
    usual_skip = median(r.get('reels_skip_rate') for r in old)
    usual_watched = median(r.get('watched_share') for r in old)
    usual_watched = round(usual_watched, 3) if usual_watched is not None else None
    for r in reel_rows:
        r['skip_vs_usual'] = round(r['reels_skip_rate'] - usual_skip, 1) \
            if isinstance(r.get('reels_skip_rate'), (int, float)) and usual_skip is not None else None
        r['watched_vs_usual'] = round(r['watched_share'] - usual_watched, 3) \
            if r.get('watched_share') is not None and usual_watched is not None else None
    return rows, {'skip_rate': usual_skip, 'watched_share': usual_watched}


def mean(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(statistics.mean(vals), 3 if key in ('watched_share', 'watched_vs_usual') else 1) if vals else None


STATS = ('skip_vs_usual', 'watched_vs_usual', 'reels_skip_rate', 'watched_share', 'views_7d', 'late_views', 'saved', 'shares',
         'dm_asks', 'follows')


def stats(rows):
    return {'reels': len(rows), **{m: mean(rows, m) for m in STATS}}


def groups(rows):
    """Averages per group for every field reels differ in. Lower skip_vs_usual and higher watched_vs_usual are
    better than the account's usual."""
    out = {}
    for field in GROUP_FIELDS:
        buckets = defaultdict(list)
        for r in rows:
            for k in (r[field] if isinstance(r[field], list) else [r[field]]):
                buckets[k].append(r)
        out[field] = {k: stats(v) for k, v in buckets.items()}
    return out


def verdict(better, worse):
    """How much better one set of reels did than another: (skip points lower, share watched higher), None when
    either side has fewer than MIN_EVIDENCE reels with numbers."""
    b = [r for r in better if r.get('skip_vs_usual') is not None]
    w = [r for r in worse if r.get('skip_vs_usual') is not None]
    if len(b) < MIN_EVIDENCE or len(w) < MIN_EVIDENCE:
        return None
    skip = round(mean(w, 'skip_vs_usual') - mean(b, 'skip_vs_usual'), 1)
    bw, ww = mean(b, 'watched_vs_usual'), mean(w, 'watched_vs_usual')
    return skip, (round(bw - ww, 3) if bw is not None and ww is not None else None)


def clearly(diff):
    """+1 clearly better, -1 clearly worse, 0 no clear difference."""
    skip, watched = diff
    if skip >= CLEAR_SKIP or (watched is not None and watched >= CLEAR_WATCHED and skip > -CLEAR_SKIP):
        return 1
    if skip <= -CLEAR_SKIP or (watched is not None and watched <= -CLEAR_WATCHED and skip < CLEAR_SKIP):
        return -1
    return 0


# ---------- 3. judge ----------

def posted_day(row):
    return datetime.fromisoformat(row['posted_at']).date()


def evaluate_rules(rules, reel_rows, today):
    """Judge each rule on trial against the reels before it. Changes the rules in place; returns what changed."""
    changes = []
    for rule in rules:
        if rule['status'] != 'trial':
            continue
        since = datetime.fromisoformat(rule['since']).date()
        days = (today - since).days
        if days < RULE_TRIAL_DAYS:
            continue
        after = [r for r in reel_rows if posted_day(r) >= since]
        before = [r for r in reel_rows if since - timedelta(days=RULE_GIVE_UP_DAYS) <= posted_day(r) < since]
        diff = verdict(after, before)
        rule['checked'] = today.isoformat()
        if diff is None:
            if days >= 3 * RULE_TRIAL_DAYS:
                rule.update(status='retired', verdict=f'never had {MIN_EVIDENCE} reels on each side to judge it')
                changes.append(('retired', rule))
            continue
        said = f'skip rate {diff[0]:+.1f} points better' + (f', share watched {diff[1]:+.3f}' if diff[1] is not None else '') \
               + f' ({len(after)} reels after vs {len(before)} before)'
        effect = clearly(diff)
        if effect > 0:
            rule.update(status='kept', verdict='helped: ' + said)
            changes.append(('kept', rule))
        elif effect < 0:
            rule.update(status='retired', verdict='hurt: ' + said)
            changes.append(('retired', rule))
        elif days >= RULE_GIVE_UP_DAYS:
            rule.update(status='retired', verdict='no clear effect: ' + said)
            changes.append(('retired', rule))
        else:
            rule['verdict'] = 'so far no clear effect: ' + said
    return changes


def run_experiment(exp, reel_rows, rules, today):
    """Conclude the running test when each option has enough reels (or after EXPERIMENT_MAX_DAYS) and start the
    next one. A clear winner becomes a proven rule. Returns (experiments, what to report)."""
    if os.environ.get('EXPERIMENT', '').strip() == 'off':
        return exp, 'Tests are switched off (EXPERIMENT=off).'
    lines = []
    active = exp.get('active')
    if active and active['name'] in generate.EXPERIMENTS:
        name = active['name']
        arms = {arm: [r for r in reel_rows if r['test'] == f'{name}: {arm}'] for arm in sorted(generate.EXPERIMENTS[name])}
        counts = ', '.join(f'{a} {len(v)}' for a, v in arms.items())
        (a1, r1), (a2, r2) = arms.items()
        diff = verdict(r1, r2)
        days = (today - datetime.fromisoformat(active['since']).date()).days
        if diff is not None:
            effect = clearly(diff)
            winner = a1 if effect > 0 else a2 if effect < 0 else None
            skip = abs(diff[0])
            result = (f'{winner} won: skip rate {skip:.1f} points lower ({counts} reels)' if winner
                      else f'no clear difference ({counts} reels, skip rate {diff[0]:+.1f})')
            exp['done'].append({**active, 'until': today.isoformat(), 'result': result})
            exp['active'] = None
            lines.append(f'Test "{name}" finished: {result}.')
            if winner:
                rules.append({'id': 1 + max((r['id'] for r in rules), default=0),
                              'text': generate.EXPERIMENTS[name][winner][0], 'since': today.isoformat(),
                              'status': 'kept', 'source': 'experiment', 'evidence': f'test {name}: {result}',
                              'verdict': 'won a test', 'checked': today.isoformat()})
                lines.append('Its winner is now a proven rule for the writer.')
        elif days >= EXPERIMENT_MAX_DAYS:
            result = f'not enough reels to decide ({counts})'
            exp['done'].append({**active, 'until': today.isoformat(), 'result': result})
            exp['active'] = None
            lines.append(f'Test "{name}" ended without a verdict: {result}.')
        else:
            lines.append(f'Test "{name}" is still running since {active["since"]}: {counts} reels measured so far '
                         f'(needs {MIN_EVIDENCE} on each side).')
    elif active:
        exp['active'] = None
    if not exp.get('active'):
        tried = {d['name'] for d in exp['done']}
        todo = [n for n in generate.EXPERIMENTS if n not in tried]
        if todo:
            exp['active'] = {'name': todo[0], 'since': today.isoformat()}
            arms = ' vs '.join(sorted(generate.EXPERIMENTS[todo[0]]))
            lines.append(f'New test from today: "{todo[0]}" ({arms}), decided by chance for each reel.')
        else:
            lines.append('Every test in generate.EXPERIMENTS has run; add a new one to keep learning.')
    return exp, ' '.join(lines)


def check_new_rules(proposed, summary, rules, today):
    """Keep only proposed rules that cite clear evidence from groups of at least MIN_EVIDENCE reels and stay away
    from the hard rules. Returns (accepted rules, dropped [(text, why)])."""
    accepted, dropped = [], []
    known = {re.sub(r'\W+', ' ', r['text'].lower()).strip() for r in rules}
    room = max(0, MAX_ACTIVE_RULES - len(history.active(rules)))
    this_week = sum(1 for r in rules if r.get('source') == 'weekly'
                    and (today - datetime.fromisoformat(r['since']).date()).days < 7)
    for p in proposed:
        text, why = clean(p.get('text')), None
        if not text:
            continue
        if HARD_RULES.search(text):
            why = 'touches the creator\'s hard rules'
        elif len(text.split()) > MAX_RULE_WORDS:
            why = f'longer than {MAX_RULE_WORDS} words'
        elif re.sub(r'\W+', ' ', text.lower()).strip() in known:
            why = 'already a rule'
        else:
            clear = []
            for e in p.get('evidence') or []:
                if e.get('field') not in RULE_FIELDS:
                    continue
                g = summary.get(e.get('field'), {})
                b, w = g.get(e.get('better')), g.get(e.get('worse'))
                if not b or not w:
                    continue
                if b['reels'] < MIN_EVIDENCE or w['reels'] < MIN_EVIDENCE:
                    continue
                if b['skip_vs_usual'] is None or w['skip_vs_usual'] is None:
                    continue
                diff = (round(w['skip_vs_usual'] - b['skip_vs_usual'], 1),
                        round(b['watched_vs_usual'] - w['watched_vs_usual'], 3)
                        if b['watched_vs_usual'] is not None and w['watched_vs_usual'] is not None else None)
                if clearly(diff) > 0:
                    clear.append(f"{e['field']} {e['better']} ({b['reels']} reels) beat {e['worse']} ({w['reels']} reels): "
                                 f"skip rate {diff[0]:+.1f} points")
            if not clear:
                why = f'no clear difference between groups of {MIN_EVIDENCE}+ reels the writer controls behind it'
            elif len(accepted) >= min(MAX_NEW_RULES - this_week, room):
                why = 'too many rules already (at most 3 new a week, 10 in all); the writer\'s prompt stays short'
        if why:
            dropped.append((text, why))
            continue
        accepted.append({'id': 1 + max((r['id'] for r in rules + accepted), default=0), 'text': text,
                         'since': today.isoformat(), 'status': 'trial', 'source': 'weekly',
                         'evidence': '; '.join(clear), 'verdict': '', 'checked': ''})
        known.add(re.sub(r'\W+', ' ', text.lower()).strip())
    return accepted, dropped


# ---------- Claude ----------

def claude(prompt, system, schema, tools=(), folder=None, timeout=600):
    tool_args = ['--tools', *tools, '--allowedTools', *tools] if tools else ['--tools', '']
    proc = subprocess.run(['claude', '-p', prompt, '--model', os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5'),
                           '--system-prompt', system, *tool_args, *(['--add-dir', str(folder)] if folder else []),
                           '--setting-sources', '', '--no-session-persistence',
                           '--output-format', 'json', '--json-schema', json.dumps(schema)],
                          capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
    out = json.loads(proc.stdout).get('structured_output')
    if not out:
        raise RuntimeError('claude returned no structured output')
    return out


IDEAS_SYSTEM = """You read comments people left on a developer's Instagram posts and list the topics they asked
him to cover or questions he could answer in a future reel. Only topics really asked for in the comments; no names,
no quotes, nothing about the commenters. Merge the same request said different ways and count how many comments
asked. Skip praise, spam, bare keyword requests and anything that is not about software, AI, freelancing or SaaS.
Skip gambling, betting, interest-based lending and adult topics. Skip topics already covered (listed below)."""
IDEAS_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['ideas'],
                'properties': {'ideas': {'type': 'array', 'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['topic', 'asked'],
                    'properties': {'topic': {'type': 'string'}, 'asked': {'type': 'integer'}}}}}}


def topic_ideas(texts, reels, old, today):
    """This week's requested topics, most asked first; last weeks' ideas stay for a month when nobody commented."""
    fresh = [i for i in old if (today - datetime.fromisoformat(i['since']).date()).days <= 30]
    if not texts:
        return fresh
    covered = [r['hook'].replace('*', '') for r in reels][-40:]
    try:
        out = claude('Comments:\n' + '\n'.join(f'- {t[:300]}' for t in texts[:300])
                     + '\n\nAlready covered:\n' + '\n'.join(f'- {h}' for h in covered), IDEAS_SYSTEM, IDEAS_SCHEMA)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f'Topic ideas unavailable: {e}')
        return fresh
    new = [{'topic': i['topic'].strip(), 'asked': i['asked'], 'since': today.isoformat()}
           for i in out['ideas'] if i['topic'].strip() and i['asked'] > 0]
    return sorted(new, key=lambda i: -i['asked'])[:8] or fresh


OPENINGS_SYSTEM = """You look at the covers (the opening frame) of a developer's Instagram reels: the ones that
kept the most viewers past the first 3 seconds and the ones that lost the most. Say in 2 to 4 short sentences what
the strong openings have in common that the weak ones lack (words, size, contrast, what the hook promises). Only
what you can see; no guesses about the algorithm. The reels never show faces, people or animals and use no music;
never suggest that."""
OPENINGS_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['observations'],
                   'properties': {'observations': {'type': 'string'}}}


def review_openings(best, worst, token):
    """What the best openings share, from their covers, or '' when there is too little to compare."""
    if len(best) < 2 or len(worst) < 2:
        return ''
    try:
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            for label, rows in (('kept viewers best', best), ('lost the most viewers', worst)):
                for r in rows:
                    resp = requests.get(f"{GRAPH}/{r['media_id']}", params={'fields': 'thumbnail_url',
                                                                            'access_token': token}, timeout=30)
                    url = resp.json().get('thumbnail_url') if resp.ok else None
                    if not url:
                        continue
                    path = Path(tmp) / f"reel-{r['id']}.jpg"
                    path.write_bytes(requests.get(url, timeout=60).content)
                    lines.append(f"{label}: {path} (hook: {r['hook']}; skip rate {r.get('reels_skip_rate')}%)")
            if len(lines) < 4:
                return ''
            out = claude('Open each cover with the Read tool.\n\n' + '\n'.join(lines), OPENINGS_SYSTEM,
                         OPENINGS_SCHEMA, tools=('Read',), folder=tmp)
            return out['observations'].strip()
    except (RuntimeError, ValueError, requests.RequestException, subprocess.TimeoutExpired) as e:
        print(f'Openings review unavailable: {redact(e, token)}')
        return ''


SYSTEM = """You analyse an Instagram creator's own reel results and propose rules for the writer of the next reels.
Lower skip rate (share of viewers who scroll away in the first 3 seconds) and a higher share of the reel watched
are the main goals; saves, shares and keyword comments (dm_asks) come next. Each reel is scored against the account's
usual: skip_vs_usual (negative is better) and watched_vs_usual (positive is better). Views are compared at 7 days old;
views_1d, views_3d and late_views (the share of the first week's views that came after day 1) show how long a reel
kept being shown by Instagram.
The creator's hard rules come first; never suggest breaking them: no faces, people or animals on screen (no
talking head), no music (sound effects and the AI voiceover only), halal and honest content (no invented results,
stories or numbers), never Reddit. The reels are faceless: text slides, code, diffs, terminals, screenshots, screen
recordings, chats, quotes and 3D scenes, so only suggest formats from that list.
The writer's own instructions are included: never propose what it already does or something its checks forbid.

Return:
- new_rules: at most 3 instructions the writer can follow while writing a reel (hook, words, structure, visuals,
  topics), each tied to the averages by group: one sentence of at most 30 words, stating only what the numbers
  show, no guessed reasons. Never about posting times, slots or settings: those belong in decision. For each, "evidence" names the groups it rests on:
  {"field": one of pillar, series, visuals, hook_word, three_d, test; "better": the group that did better;
  "worse": the group it beat}. A rule without two groups of at least 5 reels that clearly differ is thrown away,
  so return none rather than guess. Not a rule that already exists.
- summary: a short, friendly summary for the creator in plain words: what worked, what did not, what the test
  showed, what changes next week. Say how many reels each claim rests on; say "early sign" below 5.
- decision: one concrete change for the creator to approve (a setting such as THREE_D_CHANCE, a slot's format, a
  series to drop), with the numbers behind it; or "none this time" when the numbers do not support one. The loop
  runs daily: do not repeat yesterday's decision unless the numbers now make a stronger case."""

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['new_rules', 'summary', 'decision'],
          'properties': {'new_rules': {'type': 'array', 'items': {
              'type': 'object', 'additionalProperties': False, 'required': ['text', 'evidence'],
              'properties': {'text': {'type': 'string'}, 'evidence': {'type': 'array', 'items': {
                  'type': 'object', 'additionalProperties': False, 'required': ['field', 'better', 'worse'],
                  'properties': {'field': {'type': 'string'}, 'better': {'type': 'string'}, 'worse': {'type': 'string'}}}}}}},
              'summary': {'type': 'string'}, 'decision': {'type': 'string'}}}


def write_up(rows, summary, rules, test, ideas, openings, last):
    keep = ('id', 'kind', 'hook', 'title', 'posted_at', 'pillar', 'series', 'visuals', 'hook_word', 'three_d',
            'hook_type', 'opening',
            'slot', 'test', 'seconds', 'age_days', 'views_1d', 'views_3d', 'views_7d', 'late_views', 'reels_skip_rate', 'skip_vs_usual', 'watched_share',
            'watched_vs_usual', 'saved', 'shares', 'dm_asks', 'follows', 'profile_visits')
    prompt = ('Per-post results:\n' + json.dumps([{k: r[k] for k in keep if r.get(k) is not None} for r in rows],
                                                 ensure_ascii=False)
              + '\n\nAverages by group (reels, and the scores against the usual):\n'
              + json.dumps(summary, indent=1, ensure_ascii=False)
              + '\n\nThe writer\'s rules now (status, since, verdict):\n'
              + json.dumps([{k: r[k] for k in ('text', 'status', 'since', 'verdict')} for r in rules], ensure_ascii=False)
              + f'\n\nThe running test: {test}'
              + ('\n\nTopics viewers asked for: ' + '; '.join(i['topic'] for i in ideas) if ideas else '')
              + (f'\n\nWhat the best openings share (from their covers): {openings}' if openings else '')
              + ('\n\nLast week\'s report:\n' + last[:3000] if last else '')
              + '\n\nThe writer\'s instructions:\n' + generate.SYSTEM)
    return claude(prompt, SYSTEM, SCHEMA)


# ---------- 5. report ----------

# Claude's structured text once ended with leftover markup ("</summary></invoke>") in a real run.
STRAY_MARKUP = re.compile(r'\s*</?(summary|decision|new_rules|invoke|parameter|function_calls)\b[^>]*>\s*')


def clean(text):
    return STRAY_MARKUP.sub(' ', text or '').strip()


def fmt(value, kind=''):
    if value is None:
        return '-'
    if kind == 'share':
        return f'{value:.0%}'
    if kind == 'pct':
        return f'{value:.1f}%'
    if kind == 'ms':
        return f'{value / 1000:.1f}s'
    return f'{value:g}' if isinstance(value, float) else str(value)


def week_table(reel_rows, today):
    """The last 7 days' reels next to the 7 days before, by post date."""
    def pick(start, end):
        return [r for r in reel_rows if start <= posted_day(r) < end]
    this, last = pick(today - timedelta(days=7), today), pick(today - timedelta(days=14), today - timedelta(days=7))
    lines = ['| | Last 7 days | The 7 before |', '| --- | --- | --- |', f'| Reels measured | {len(this)} | {len(last)} |']
    for label, key, kind in (('Skip rate', 'reels_skip_rate', 'pct'), ('Watch time', 'ig_reels_avg_watch_time', 'ms'),
                             ('Share of the reel watched', 'watched_share', 'share'),
                             ('Views at 7 days', 'views_7d', ''), ('Saves', 'saved', ''), ('Shares', 'shares', ''),
                             ('Keyword comments', 'dm_asks', '')):
        lines.append(f'| {label} (average) | {fmt(mean(this, key), kind)} | {fmt(mean(last, key), kind)} |')
    return '\n'.join(lines)


def views_life(rows):
    """How long reels keep getting views: the average curve over the reels a week old, and the latest few."""
    done = [r for r in rows if r.get('views_7d') is not None and r.get('views_1d') is not None]
    if not done:
        return ''
    lines = [f"Reels a week old: {len(done)}. On average {fmt(mean(done, 'views_1d'))} views on day 1, "
             f"{fmt(mean(done, 'views_3d'))} by day 3, {fmt(mean(done, 'views_7d'))} by day 7; "
             f"{fmt(mean(done, 'late_views'), 'share')} of a week's views came after day 1."]
    for r in sorted(done, key=lambda r: r['posted_at'])[-5:]:
        lines.append(f"- #{r['id']} {r['hook']}: {fmt(r['views_1d'])} / {fmt(r.get('views_3d'))} / {fmt(r['views_7d'])} "
                     f"(day 1 / 3 / 7)")
    return '\n'.join(lines)


def ranked(reel_rows):
    scored = sorted((r for r in reel_rows if r.get('skip_vs_usual') is not None), key=lambda r: r['skip_vs_usual'])
    n = min(3, len(scored) // 2)
    return scored[:n], scored[::-1][:n]


def report(today, rows, usual, changes, test, rules, accepted, dropped, ideas, openings, write):
    reel_rows = [r for r in rows if r['kind'] == 'reel']
    best, worst = ranked(reel_rows)
    parts = [f'# Reel report {today.isoformat()}',
             f"Usual skip rate {fmt(usual['skip_rate'], 'pct')}, usual share watched {fmt(usual['watched_share'], 'share')} "
             f'({len(reel_rows)} reels measured).',
             '## Last 7 days vs the 7 before', week_table(reel_rows, today)]
    life = views_life([r for r in rows if r['kind'] == 'reel'])
    if life:
        parts.append('## How long reels keep getting views\n' + life)
    if best:
        parts.append('## Best and worst openings')
        for label, group in (('Kept the most viewers', best), ('Lost the most viewers', worst)):
            parts.append(f'**{label}**\n' + '\n'.join(
                f"- #{r['id']} {r['hook']}: skip rate {fmt(r.get('reels_skip_rate'), 'pct')} "
                f"({r['skip_vs_usual']:+.1f} vs usual), watched {fmt(r.get('ig_reels_avg_watch_time'), 'ms')}"
                + (f" ({fmt(r['watched_share'], 'share')} of it)" if r.get('watched_share') is not None else '') for r in group))
        if openings:
            parts.append(f'What the strong openings share: {openings}')
    carousels = [r for r in rows if r['kind'] == 'carousel']
    if carousels:
        parts.append('## Carousels\n' + '\n'.join(
            f"- {r['title']}: {fmt(r.get('saved'))} saves, {fmt(r.get('shares'))} shares, {fmt(r.get('reach'))} reach, "
            f"{fmt(r.get('dm_asks'))} keyword comments" for r in carousels))
    parts.append(f'## The running test\n{test}')
    rule_lines = [f"- {status}: {r['text']} ({r['verdict']})" for status, r in changes]
    rule_lines += [f"- new, on trial: {r['text']} ({r['evidence']})" for r in accepted]
    rule_lines += [f'- not added: {text} ({why})' for text, why in dropped]
    counts = {s: sum(r['status'] == s for r in rules) for s in ('kept', 'trial', 'retired')}
    parts.append('## Rules\n' + (('\n'.join(rule_lines) + '\n\n') if rule_lines else '')
                 + f"{counts['kept']} proven, {counts['trial']} on trial, {counts['retired']} retired.")
    if ideas:
        parts.append('## What people asked for\n' + '\n'.join(f"- {i['topic']} ({i['asked']})" for i in ideas))
    parts.append('## Summary\n' + (clean(write.get('summary')) or 'The write-up was unavailable this time; the numbers above '
                                                             'are complete.'))
    parts.append('## One decision for you\n' + (clean(write.get('decision')) or 'None this time.'))
    return '\n\n'.join(parts) + '\n'


def main():
    token = os.environ.get('IG_TOKEN', '').strip()
    if not token:
        raise SystemExit('Missing env var IG_TOKEN')
    today = utcnow().date()
    reels = json.loads(render.QUEUE.read_text())
    carousels = json.loads(CAROUSELS.read_text()) if CAROUSELS.exists() else []

    stored = history.snapshots()
    new, texts = measure(reels, carousels, token, history.by_post(stored))
    history.append_snapshots(new)
    print(f'Measured {len(new)} posts ({len(stored)} earlier snapshots kept)')
    rows, usual = table(reels, carousels, history.by_post(stored + new))
    reel_rows = [r for r in rows if r['kind'] == 'reel' and r.get('skip_vs_usual') is not None
                 and r.get('age_days', 0) >= SCORE_MIN_DAYS]
    if len(reel_rows) < 2:
        print(f'Only {len(reel_rows)} reel(s) with settled numbers; nothing to learn yet')
        return

    rules = history.rules() or history.import_learnings(today.isoformat())
    changes = evaluate_rules(rules, reel_rows, today)
    exp, test = run_experiment(history.experiments(), reel_rows, rules, today)
    summary = groups(reel_rows)
    ideas = topic_ideas(texts, reels, history.ideas(), today)
    best, worst = ranked(reel_rows)
    openings = review_openings(best, worst, token)
    try:
        write = write_up(rows, summary, rules, test, ideas, openings, history.last_report(today))
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:  # the numbers and rules still count
        print(f'Write-up unavailable: {e}')
        write = {'new_rules': [], 'summary': '', 'decision': ''}
    accepted, dropped = check_new_rules(write['new_rules'], summary, rules, today)
    rules += accepted

    history.save_rules(rules)
    history.save_experiments(exp)
    history.save_ideas(ideas)
    text = report(today, rows, usual, changes, test, rules, accepted, dropped, ideas, openings, write)
    history.save_report(today, text)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    print(text)


if __name__ == '__main__':
    sys.exit(main())
