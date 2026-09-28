"""Where the learning loop keeps what it knows, as plain files in the repo (no database): git gives the history,
Claude sessions can read them, and a daily post never depends on a database being up.

  metrics/YYYY-MM.jsonl   one line per post per weekly snapshot, only ever appended (month of the snapshot)
  rules.json              the writer's rules with their status (trial, kept, retired) and evidence
  experiments.json        the weekly test that is running and the ones that finished
  ideas.json              topics viewers asked for in comments (no names, no quotes)
  reports/YYYY-Www.md     every weekly report
  learnings.md            generated from the active rules in rules.json; the writers read this file

Only the weekly job (learn.py) writes these, so the three daily runs, which commit reels.json, never collide
with it. Standard library only.

Usage: python history.py    prints what is stored: snapshots, posts, rules by status, the running test
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METRICS = ROOT / 'metrics'
RULES = ROOT / 'rules.json'
EXPERIMENTS = ROOT / 'experiments.json'
IDEAS = ROOT / 'ideas.json'
REPORTS = ROOT / 'reports'
LEARNINGS = ROOT / 'learnings.md'

# A post whose numbers were read at this age has settled; it is not fetched from Instagram again.
SETTLED_DAYS = 28


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


# ---------- metrics snapshots ----------

def snapshots():
    """Every stored snapshot, oldest first."""
    rows = []
    for path in sorted(METRICS.glob('*.jsonl')):
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return sorted(rows, key=lambda r: (r['date'], r['kind'], str(r['id'])))


def append_snapshots(rows):
    """Append new snapshots to the file of their month. Never rewrites a line."""
    METRICS.mkdir(exist_ok=True)
    by_month = {}
    for r in rows:
        by_month.setdefault(r['date'][:7], []).append(r)
    for month, month_rows in sorted(by_month.items()):
        with open(METRICS / f'{month}.jsonl', 'a') as f:
            for r in month_rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')


def key(kind, post_id):
    return f'{kind}:{post_id}'


def by_post(rows=None):
    """{'reel:33': [snapshots oldest first]}."""
    out = {}
    for r in snapshots() if rows is None else rows:
        out.setdefault(key(r['kind'], r['id']), []).append(r)
    return out


def settled(post_snapshots):
    return any(s.get('age_days', 0) >= SETTLED_DAYS for s in post_snapshots)


def value_at(post_snapshots, name, days):
    """A metric from the first snapshot taken at least `days` old (views grow with age; compare like with like)."""
    for s in post_snapshots:
        if s.get('age_days', 0) >= days and isinstance(s.get(name), (int, float)):
            return s[name]
    return None


# ---------- rules ----------

def rules():
    return read_json(RULES, [])


def active(all_rules):
    """Rules the writer follows: proven ones first, then the ones on trial."""
    return [r for r in all_rules if r['status'] == 'kept'] + [r for r in all_rules if r['status'] == 'trial']


def learnings_text(all_rules):
    lines = [f"- {r['text']}" + (' (proven)' if r['status'] == 'kept' else '') for r in active(all_rules)]
    return '# What holds our viewers (updated weekly by learn.py)\n\n' + '\n'.join(lines) + '\n'


def save_rules(all_rules):
    write_json(RULES, all_rules)
    LEARNINGS.write_text(learnings_text(all_rules))


def import_learnings(today):
    """The first run: the bullets of an older learnings.md become rules on trial, so they get judged too."""
    if not LEARNINGS.exists():
        return []
    bullets = [l[2:].strip() for l in LEARNINGS.read_text().splitlines() if l.startswith('- ')]
    return [{'id': i, 'text': b.removesuffix(' (proven)'), 'since': today, 'status': 'trial', 'source': 'imported',
             'evidence': 'written before rules were tracked', 'verdict': '', 'checked': ''}
            for i, b in enumerate(bullets, 1)]


# ---------- experiments, ideas, reports ----------

def experiments():
    return read_json(EXPERIMENTS, {'active': None, 'done': []})


def save_experiments(data):
    write_json(EXPERIMENTS, data)


def ideas():
    return read_json(IDEAS, [])


def save_ideas(items):
    write_json(IDEAS, items)


def week_name(day):
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def save_report(day, text):
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f'{week_name(day)}.md'
    path.write_text(text.rstrip() + '\n')
    return path


def last_report(before):
    """The newest saved report from an earlier week, or ''."""
    older = sorted(p for p in REPORTS.glob('*.md') if p.stem < week_name(before)) if REPORTS.exists() else []
    return older[-1].read_text() if older else ''


def main():
    rows = snapshots()
    posts = by_post(rows)
    print(f'{len(rows)} snapshots of {len(posts)} posts ({sum(settled(s) for s in posts.values())} settled)')
    print('rules:', dict(Counter(r['status'] for r in rules())) or 'none')
    exp = experiments()
    print('test running:', (exp['active'] or {}).get('name', 'none'), f"({len(exp['done'])} finished)")
    print('ideas:', len(ideas()))


if __name__ == '__main__':
    sys.exit(main())
