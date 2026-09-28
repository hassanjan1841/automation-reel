# automation-reel

Daily Instagram Reel pipeline for @hassanjan.k. Python 3.12 + ffmpeg, run by GitHub Actions.

- Load the `automation-reel` skill (`.claude/skills/automation-reel/SKILL.md`) before any work here. It is the developer reference: pipeline, files, reel schema, common tasks, gotchas.
- `README.md` is the operator guide. Script docstrings are the source of truth for each script's usage and env vars.
- Use `.venv/bin/python`. Never post for real while testing: use `DRY_RUN=true` with `publish.py` and `carousel.py`.
- The creator's hard rules: no music ever (sound effects only); everything halal and honest (no invented results,
  stories, numbers or quotes, nothing of anyone else's presented as his); never Reddit; no faces or animals in visuals (3D scenes too: `scene3d.ANIMAL_LOGOS` blocks mascot logos).
- `reels.json` is live state that the daily workflow commits to. Edit it only when the task is about reels, and run `generate.py --check` after.
- The learning loop's files (`metrics/`, `rules.json`, `experiments.json`, `ideas.json`, `reports/`, `learnings.md`) are live state the weekly job writes. `learnings.md` is generated from `rules.json`; change a rule there, and only when the task is about rules.
- Verify every change with the `verify` skill (`.claude/skills/verify/SKILL.md`): the fast checks always (`test_learn.py`, `generate.py --check`, `docs_check.py`), and the real end-to-end runs it lists for the parts you touched.

## Docs stay in the same change as the code

When you change a script, a workflow, an env var, a schedule or a behavior the docs describe, update `README.md`, this file and the skill in the same change. Then run:

```bash
python3 docs_check.py
```

A Stop hook (`.claude/hooks/docs_guard.py`) runs it and blocks once if docs look stale. CI runs it on every push (`docs-check.yml`), and `docs-sync.yml` opens a pull request with Claude's fixes for anything that still slips through.
