"""Bring README.md, CLAUDE.md and the project skill up to date with the code, using Claude.

Looks at what changed in the code since the docs were last committed, plus anything docs_check.py
flags, and asks Claude (Claude Code CLI, read-only tools) for exact text edits. Only edits to the
three doc files are applied, each must match its old text exactly once, and docs_check.py must pass.

Usage:
  python docs_sync.py              update the docs if the code moved on since they were last committed
  python docs_sync.py --base REF   compare against REF instead
  python docs_sync.py --force      run even if nothing changed

Env: CLAUDE_CODE_OAUTH_TOKEN (in CI), CLAUDE_MODEL (optional, defaults to MODEL in generate.py)
"""

import json
import os
import re
import subprocess
import sys

import docs_check

# Read from source rather than imported: generate.py pulls in numpy and Pillow, which this job does not need.
MODEL = os.environ.get('CLAUDE_MODEL') or re.search(
    r"^MODEL = '([^']+)'", (docs_check.ROOT / 'generate.py').read_text(), re.M).group(1)
DOC_PATHS = [str(p.relative_to(docs_check.ROOT)) for p in docs_check.DOCS]
# The bots commit content, not code the docs describe: reels.json daily, the learning loop's files and studies/ by their jobs.
CONTENT = ['reels.json', 'carousels.json', 'pronounce.json', 'learnings.md', 'rules.json', 'experiments.json',
           'ideas.json', 'metrics', 'reports', 'studies']
CODE_PATHSPEC = ['.'] + [f':(exclude){p}' for p in CONTENT + DOC_PATHS]
MAX_DIFF = 60_000
ATTEMPTS = 2

SCHEMA = {
    'type': 'object',
    'properties': {
        'edits': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'file': {'type': 'string', 'enum': DOC_PATHS},
                    'old': {'type': 'string'},
                    'new': {'type': 'string'},
                },
                'required': ['file', 'old', 'new'],
                'additionalProperties': False,
            },
        },
        'summary': {'type': 'string'},
    },
    'required': ['edits', 'summary'],
    'additionalProperties': False,
}

SYSTEM = """You maintain the documentation of automation-reel, a small Python pipeline that posts one
Instagram Reel a day. The docs are:
- README.md: for running the project (what it does, secrets, schedules, pausing, running by hand).
- CLAUDE.md: short working rules for Claude sessions in this repo.
- .claude/skills/automation-reel/SKILL.md: the developer reference (pipeline, files, schema, tasks, gotchas).

Return the edits that make these docs match the code. Rules:
- Read the code before changing a statement about it. The code is the source of truth. Describe what the
  code does, not what a comment or docstring claims it does.
- Change only what is wrong or missing. Keep everything that is still accurate word for word.
- Keep the existing structure, tone and brevity: short plain sentences, tables and bullets, no em dashes,
  no marketing language, no changelog or "updated on" notes.
- Each edit replaces `old` with `new` in `file`. `old` must be copied exactly from the current file and
  appear in it exactly once; include enough surrounding text to make it unique. Use an empty `old` only
  to create a file that does not exist yet.
- Return an empty list if nothing needs to change. summary: one line per file saying what changed."""


def git(*args):
    return subprocess.run(['git', *args], cwd=docs_check.ROOT, capture_output=True, text=True, check=True).stdout


def default_base():
    return git('log', '-1', '--format=%H', '--', *DOC_PATHS).strip()


def output(key, value):
    path = os.environ.get('GITHUB_OUTPUT')
    if path:
        with open(path, 'a') as f:
            f.write(f'{key}={value}\n')


def ask_claude(prompt):
    proc = subprocess.run(
        ['claude', '-p', prompt, '--model', MODEL, '--system-prompt', SYSTEM,
         '--tools', 'Read', 'Glob', 'Grep', '--allowedTools', 'Read', 'Glob', 'Grep',
         '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
         '--json-schema', json.dumps(SCHEMA)],
        cwd=docs_check.ROOT, capture_output=True, text=True, timeout=1200, stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise SystemExit(f'claude exited {proc.returncode}: {proc.stderr.strip()[-500:]}')
    result = json.loads(proc.stdout)
    if result.get('is_error') or not result.get('structured_output'):
        raise SystemExit(f"claude returned no structured output: {str(result.get('result'))[:300]}")
    return result['structured_output']


def apply(edits):
    """Apply edits to the doc files; returns the ones that could not be applied, with the reason."""
    failed = []
    for e in edits:
        path = docs_check.ROOT / e['file']
        if e['file'] not in DOC_PATHS:
            failed.append(f"{e['file']}: not a doc file")
        elif not e['old']:
            if path.exists():
                failed.append(f"{e['file']}: empty old text but the file exists")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(e['new'])
        elif not path.exists():
            failed.append(f"{e['file']}: file does not exist")
        else:
            text = path.read_text()
            count = text.count(e['old'])
            if count != 1:
                failed.append(f"{e['file']}: old text found {count} times: {e['old'][:80]!r}")
            else:
                path.write_text(text.replace(e['old'], e['new']))
    return failed


def main():
    args = sys.argv[1:]
    base = args[args.index('--base') + 1] if '--base' in args else default_base()
    output('changed', 'false')

    diff = git('diff', base, '--', *CODE_PATHSPEC) if base else ''
    problems = docs_check.check()
    if not diff.strip() and not problems and '--force' not in args:
        print(f'No code changes since {base[:9]} and docs_check passes; nothing to do')
        return
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + '\n... (diff truncated, read the files for the rest)'

    before = {p: (docs_check.ROOT / p).read_text() if (docs_check.ROOT / p).exists() else None for p in DOC_PATHS}
    feedback = ''
    for attempt in range(1, ATTEMPTS + 1):
        prompt = (
            f'The code changed since the docs were last updated (base {base[:9] or "none"}).\n\n'
            + ('docs_check.py reports:\n' + '\n'.join(f'- {p}' for p in problems) + '\n\n'
               if problems else 'docs_check.py passes.\n\n')
            + f'Code diff since then:\n```diff\n{diff or "(none)"}\n```\n\n'
            'Read the three doc files and the relevant code, then return the edits that make the docs '
            'match the code and make docs_check.py pass.'
            + feedback
        )
        result = ask_claude(prompt)
        failed = apply(result['edits'])
        problems = docs_check.check()
        print(f"Attempt {attempt}: {len(result['edits'])} edit(s), {len(failed)} failed, "
              f'{len(problems)} docs_check problem(s)\n{result["summary"].strip()}')
        if not failed and not problems:
            break
        # The docs on disk now include the edits that did apply, so the retry works from the current text.
        feedback = ('\n\nYour previous attempt was partly applied. Re-read the doc files. '
                    + ('These edits failed and were skipped:\n' + '\n'.join(f'- {f}' for f in failed) if failed else ''))

    for p in problems:
        print(f'- {p}')
    if problems:
        raise SystemExit(f'docs_check still reports {len(problems)} problem(s) after the update')
    after = {p: (docs_check.ROOT / p).read_text() if (docs_check.ROOT / p).exists() else None for p in DOC_PATHS}
    if after != before:
        output('changed', 'true')
        print(git('diff', '--stat', '--', *DOC_PATHS).strip() or 'New doc file(s) created')
    else:
        print('Docs unchanged')


if __name__ == '__main__':
    main()
