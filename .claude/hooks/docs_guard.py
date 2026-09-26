"""Stop hook: before Claude ends a turn, make sure uncommitted code changes came with doc updates.

Blocks the stop (once per distinct set of changes) when docs_check.py fails, or when scripts or
workflows changed but README.md, CLAUDE.md and the skill did not.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = {'README.md', 'CLAUDE.md', '.claude/skills/automation-reel/SKILL.md'}
# Remembers what was already flagged so an unchanged tree is not blocked again every turn.
ACK = ROOT / '.git' / 'docs-guard-ack'


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True).stdout


def main():
    event = json.load(sys.stdin)
    if event.get('stop_hook_active'):
        return

    changed = [line[3:].split(' -> ')[-1] for line in git('status', '--porcelain', '-uall').splitlines()]
    code = [f for f in changed if f.endswith('.py') and not f.startswith('.claude/') or f.startswith('.github/')]
    docs = [f for f in changed if f in DOCS]

    check = subprocess.run([sys.executable, 'docs_check.py'], cwd=ROOT, capture_output=True, text=True)
    reasons = []
    if check.returncode != 0:
        reasons.append('docs_check.py fails:\n' + check.stdout.strip())
    if code and not docs:
        reasons.append(f"Code changed ({', '.join(code)}) but README.md, CLAUDE.md and the skill did not.")
    if not reasons:
        return

    state = hashlib.sha256((git('diff') + check.stdout + ' '.join(changed)).encode()).hexdigest()
    if ACK.exists() and ACK.read_text() == state:
        return
    ACK.write_text(state)
    print(json.dumps({
        'decision': 'block',
        'reason': '\n\n'.join(reasons) + '\n\nUpdate the docs that these changes made stale '
                  '(see the "Keeping docs current" section of the automation-reel skill). '
                  'If nothing needs updating, say so briefly and stop.',
    }))


if __name__ == '__main__':
    main()
