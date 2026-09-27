"""Weekly learning loop: measure how every posted reel did, find what holds viewers, and turn it into rules the
daily writer follows (learnings.md). Also writes a short report for the creator.

Env: IG_TOKEN, CLAUDE_CODE_OAUTH_TOKEN (for the write-up)
Usage: python learn.py            refresh learnings.md and write out/report.md
"""

import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict

import requests

import render

GRAPH = f"https://graph.instagram.com/{os.environ.get('GRAPH_VERSION', 'v25.0')}"
LEARNINGS = render.ROOT / 'learnings.md'
REPORT = render.OUT_DIR / 'report.md'
METRICS = ('views', 'reach', 'reels_skip_rate', 'ig_reels_avg_watch_time', 'saved', 'shares', 'likes', 'comments')
# Insights settle over about two days; newer posts would look worse than they are.
MIN_AGE_HOURS = 48


def metric(media_id, name, token):
    try:
        resp = requests.get(f'{GRAPH}/{media_id}/insights', params={'metric': name, 'access_token': token}, timeout=30)
        data = resp.json().get('data', []) if resp.ok else []
        return data[0]['values'][0]['value'] if data else None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def measure(reels, token):
    """One row per posted reel old enough to have settled numbers."""
    from datetime import datetime, timezone
    rows = []
    for r in reels:
        if not (r.get('media_id') and r.get('posted_at')):
            continue
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(r['posted_at'])).total_seconds() / 3600
        if age < MIN_AGE_HOURS:
            continue
        m = {name: metric(r['media_id'], name, token) for name in METRICS}
        visuals = sorted({v['type'] for p in r['points'] for v in (p.get('visual') or [])[:1]})
        rows.append({'id': r['id'], 'hook': r['hook'].replace('*', ''), 'pillar': r.get('pillar', '?'),
                     'series': r.get('series') or ('news' if r.get('pillar') == 'timely' else 'none'),
                     'visuals': visuals or ['text'], 'posted_at': r['posted_at'][:10], **m})
    return rows


def average(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(statistics.mean(vals), 1) if vals else None


def groups(rows):
    """Average skip rate, watch time, views, saves and shares per pillar, series and visual type."""
    out = {}
    for field in ('pillar', 'series', 'visuals'):
        buckets = defaultdict(list)
        for r in rows:
            for key in (r[field] if isinstance(r[field], list) else [r[field]]):
                buckets[key].append(r)
        out[field] = {k: {'reels': len(v), **{m: average(v, m) for m in ('reels_skip_rate', 'ig_reels_avg_watch_time',
                                                                        'views', 'saved', 'shares')}}
                      for k, v in buckets.items()}
    return out


SYSTEM = """You analyse an Instagram creator's own reel results and write short, concrete rules for the writer of
the next reels. The account is small, so be careful with small numbers: say "early sign" when a group has fewer
than 3 reels, and never invent a pattern the data does not show. Lower skip rate (share of viewers who scroll away
in the first 3 seconds) and longer average watch time are the main goals; shares and saves come next.
Return two parts: "rules" (at most 8 bullets the writer should follow, each tied to the numbers) and "report"
(a short, friendly summary for the creator in plain words: what worked, what did not, what changes next week)."""

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['rules', 'report'],
          'properties': {'rules': {'type': 'array', 'items': {'type': 'string'}}, 'report': {'type': 'string'}}}


def write_up(rows, summary):
    prompt = ('Per-reel results (watch time in ms, skip rate in %):\n' + json.dumps(rows, indent=1, ensure_ascii=False)
              + '\n\nAverages by group:\n' + json.dumps(summary, indent=1, ensure_ascii=False))
    proc = subprocess.run(['claude', '-p', prompt, '--model', os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5'),
                           '--system-prompt', SYSTEM, '--tools', '', '--setting-sources', '', '--no-session-persistence',
                           '--output-format', 'json', '--json-schema', json.dumps(SCHEMA)],
                          capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise SystemExit(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
    return json.loads(proc.stdout)['structured_output']


def main():
    token = os.environ.get('IG_TOKEN', '').strip()
    if not token:
        raise SystemExit('Missing env var IG_TOKEN')
    reels = json.loads(render.QUEUE.read_text())
    rows = measure(reels, token)
    if len(rows) < 2:
        print(f'Only {len(rows)} reel(s) with settled numbers; nothing to learn yet')
        return
    out = write_up(rows, groups(rows))
    LEARNINGS.write_text('# What holds our viewers (updated weekly by learn.py)\n\n'
                         + '\n'.join(f'- {r}' for r in out['rules']) + '\n')
    render.OUT_DIR.mkdir(exist_ok=True)
    REPORT.write_text(out['report'].strip() + '\n')
    print(out['report'])


if __name__ == '__main__':
    sys.exit(main())
