# automation-reel

Daily Instagram Reel pipeline for @hassanjan.k. Python 3.12 + ffmpeg, run by GitHub Actions.

- Load the `automation-reel` skill (`.claude/skills/automation-reel/SKILL.md`) before any work here. It is the developer reference: pipeline, files, reel schema, common tasks, gotchas.
- `README.md` is the operator guide. Script docstrings are the source of truth for each script's usage and env vars.
- Use `.venv/bin/python`. Never post for real while testing: use `DRY_RUN=true` with `publish.py` and `carousel.py`.
- The creator's hard rules: no music ever (sound effects only); everything halal and honest (no invented results,
  stories, numbers or quotes, nothing of anyone else's presented as his); never Reddit; no faces or animals in visuals (3D scenes too: `scene3d.ANIMAL_LOGOS` blocks mascot logos).
- `reels.json` and `pronounce.json` (daily workflow) and `carousels.json` (weekly.yml) are live state the bots commit to. Edit `reels.json` only when the task is about reels, and run `generate.py --check` after.
- `extras.json` is the record `post_video.py` (post-video.yml) commits after posting a ready-made video from `extras/`; such one-offs skip the writer and the frame review, so the creator decides on them himself.
- The learning loop's files (`metrics/`, `rules.json`, `experiments.json`, `ideas.json`, `reports/`, `learnings.md`) are live state the learning job (learn.yml, daily by default) writes. `learnings.md` is generated from `rules.json`; change a rule there, and only when the task is about rules.
- `build` visuals (`visuals.Build`) render only the given HTML and CSS, with scripts off and the network blocked; keep it that way (`generate.BUILD_BLOCKED`).
- `motion.py` animations show abstract shapes only (boxes, dots, arrows, code; no faces, people, characters or animals), and every value they show must be true (real program output, cited numbers).
- `playbook.md` is the researched reel playbook (hooks, script, visuals, sound); the writers (`generate.py`, and `trends.py` for news), the hook judge and `qa.py` read it, so change rules there, not in three prompts.
- `study.py` (study.yml) studies other creators' videos for patterns only: never copy their content, and keep its prompt's split into adoptable vs breaks-the-hard-rules. `studies/` is written by that workflow.
- Verify every change with the `verify` skill (`.claude/skills/verify/SKILL.md`): the fast checks of its §1 always (`test_learn.py`, `test_study.py`, `test_motion.py`, `test_voice.py`, `generate.py --check`, `docs_check.py`, pyflakes), and the real end-to-end runs it lists for the parts you touched.

## Docs stay in the same change as the code

When you change a script, a workflow, an env var, a schedule or a behavior the docs describe, update `README.md`, this file and the skill in the same change. Then run:

```bash
python3 docs_check.py
```

A Stop hook (`.claude/hooks/docs_guard.py`) runs it and blocks once per set of changes if it fails, or if code changed but none of the three docs did. CI runs it on every push except `reels.json`-only commits and on pull requests (`docs-check.yml`), and `docs-sync.yml` opens a pull request with Claude's fixes for anything that still slips through.
