"""End-to-end run of the real writer (generate.today, the Claude CLI) under given weekly-test options: each reel must
come back valid, carry its test and follow it. Nothing is saved; reels.json is only read.

Usage: .venv/bin/python tests/e2e_writer.py hook_style:question hook_style:statement [name:arm ...]
       (no arguments: every option of every test in generate.EXPERIMENTS, about a minute each)
"""

import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate  # noqa: E402
import render  # noqa: E402


def main():
    specs = sys.argv[1:] or [f'{n}:{a}' for n, arms in generate.EXPERIMENTS.items() for a in sorted(arms)]
    reels = json.loads(render.QUEUE.read_text())
    os.environ.setdefault('THREE_D', 'off')
    failed = []
    for spec in specs:
        name, arm = spec.split(':')
        test = {'name': name, 'arm': arm}
        with mock.patch.object(generate, 'experiment_today', return_value=test):
            reel = generate.today(reels)
        errors = ['no valid reel'] if not reel else generate.validate(reel) + (
            [] if reel.get('test') == test else [f"test not carried: {reel.get('test')}"])
        print(f"{'ok  ' if not errors else 'FAIL'} {spec}: {reel and reel['hook']!r} "
              f"({reel and generate.vo_words(reel)} words) {'; '.join(errors)}")
        if errors:
            failed.append(spec)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
