"""Mutation check for the offline tests: break the code on purpose, one known way at a time, in a throwaway copy of
the repo, and make sure test_learn.py fails for every one. A mutant that survives is a behaviour no test protects.

Add a mutant here for every new behaviour a change introduces (the exact old text, what to break it into, a label).

Usage: .venv/bin/python tests/mutants.py     exit 1 if any mutant survives
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MUTANTS = [
    ('generate.py', "    return errors + experiment_errors(reel)\n", "    return errors\n", 'validate ignores the test'),
    ('generate.py', "{'test': test} if test else {}", "{}", 'the writer drops the test'),
    ('generate.py', "f'test-{name}-{day.isoformat()}-{slot()}'", "f'test-{name}-{day.isoformat()}'", 'the option ignores the slot'),
    ('history.py', "open(METRICS / f'{month}.jsonl', 'a')", "open(METRICS / f'{month}.jsonl', 'w')", 'snapshots overwrite'),
    ('learn.py', "if hours < MIN_AGE_HOURS or history.settled(", "if hours < MIN_AGE_HOURS or False and history.settled(",
     'settled posts fetched again'),
    ('learn.py', "    if skip >= CLEAR_SKIP or", "    if skip >= -CLEAR_SKIP or", 'any difference counts as clear'),
    ('learn.py', "                if b['reels'] < MIN_EVIDENCE or w['reels'] < MIN_EVIDENCE:\n                    continue\n", "",
     'no minimum evidence for new rules'),
    ('learn.py', "if HARD_RULES.search(text):", "if False:", 'hard rules not checked'),
    ('learn.py', "        elif len(text.split()) > MAX_RULE_WORDS:", "        elif False:", 'rules of any length'),
    ('learn.py', "                if e.get('field') not in RULE_FIELDS:\n                    continue\n", "",
     'rules may rest on posting times'),
    ('learn.py', "history.import_learnings(today.isoformat())", "history.import_learnings(today)", 'rule dates not strings'),
    ('learn.py', "before = [r for r in reel_rows if since - timedelta(days=RULE_GIVE_UP_DAYS) <= posted_day(r) < since]",
     "before = [r for r in reel_rows if posted_day(r) <= since]", 'wrong before window'),
    ('learn.py', "            exp['active'] = {'name': todo[0], 'since': today.isoformat()}", "            pass",
     'the next test never starts'),
    ('learn.py', "            watch = latest.get('ig_reels_avg_watch_time')", "            watch = None", 'share watched lost'),
    ('learn.py', "'views_7d': history.value_at(s, 'views', 7)", "'views_7d': s[-1].get('views')", 'views not age-matched'),
    ('learn.py', "row['dm_asks'] = sum(", "row['dm_asks_x'] = sum(", 'keyword comments not counted'),
    ('learn.py', "        write = {'new_rules': [], 'summary': '', 'decision': ''}", "        raise",
     'a Claude failure loses the week'),
    ('generate.py', "    if not new and test:", "    if False:", 'a test can cost the day'),
    ('learn.py', "    return str(error).replace(token, '***') if token else str(error)", "    return str(error)",
     'the token can reach the log'),
    ('learn.py', "    return STRAY_MARKUP.sub(' ', text or '').strip()", "    return (text or '').strip()", 'stray markup in the report'),
    ('publish.py', "    reel['slot'] = generate.slot()\n", "", 'slot not recorded'),
    ('publish.py', "    reel['seconds'] = round(slides[-1].end, 1)\n", "", 'length not recorded'),
    ('trends.py', "    if vals:\n        return vals\n    for name in names:", "    return vals\n    for name in names:",
     'no per-metric fallback'),
    ('trends.py', "reel = generate.tidy({**check['reel'], **tested})", "reel = generate.tidy(check['reel'])",
     'news reels lose the test after the fact-check'),
    ('.github/workflows/weekly.yml',
     'for f in learnings.md rules.json experiments.json ideas.json metrics reports; do\n'
     '            if [ -e "$f" ]; then git add "$f"; fi\n          done',
     'for f in x; do\n            git add learnings.md rules.json experiments.json ideas.json metrics reports || true\n'
     '          done', 'git add is all or nothing'),
]


def main():
    survived = []
    for path, old, new, label in MUTANTS:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'repo'
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('.venv*', 'out', 'models', 'fonts', '.git', '__pycache__'))
            f = copy / path
            text = f.read_text()
            if text.count(old) != 1:
                print(f'STALE    {label}: the code it breaks has changed; update this mutant')
                survived.append(label)
                continue
            f.write_text(text.replace(old, new))
            proc = subprocess.run([sys.executable, 'test_learn.py'], cwd=copy, capture_output=True, text=True, timeout=900)
            caught = proc.returncode != 0
            print(f"{'caught  ' if caught else 'SURVIVED'} {label}")
            if not caught:
                survived.append(label)
    print(f'{len(MUTANTS) - len(survived)}/{len(MUTANTS)} mutants caught')
    sys.exit(1 if survived else 0)


if __name__ == '__main__':
    main()
