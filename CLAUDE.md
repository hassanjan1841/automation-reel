# automation-reel

Daily Instagram Reel pipeline for @hassanjan.k. Python 3.12 + ffmpeg, run by GitHub Actions.

- Load the `automation-reel` skill (`.claude/skills/automation-reel/SKILL.md`) before any work here. It is the developer reference: pipeline, files, reel schema, common tasks, gotchas.
- `README.md` is the operator guide. Script docstrings are the source of truth for each script's usage and env vars.
- Use `.venv/bin/python`. Never post for real while testing: use `DRY_RUN=true` with `publish.py` and `carousel.py`.
- The creator's hard rules: no music ever (sound effects only); everything halal and honest (no invented results,
  stories, numbers or quotes, nothing of anyone else's presented as his); never Reddit; no faces or animals in visuals (3D scenes too: `scene3d.ANIMAL_LOGOS` blocks mascot logos).
- `reels.json` and `pronounce.json` (daily workflow) and `carousels.json` (weekly.yml) and `showcases.json` (showcase.yml) are live state the bots commit to. Edit `reels.json` only when the task is about reels, and run `generate.py --check` after.
- `extras.json` is the record `post_video.py` (post-video.yml) commits after posting a ready-made video from `extras/`; such one-offs skip the writer and the frame review, so the creator decides on them himself. An entry with `post_at` and `media_id` null is queued: scheduler.py starts it at that time.
- The learning loop's files (`metrics/`, `rules.json`, `experiments.json`, `ideas.json`, `reports/`, `learnings.md`) are live state the learning job (learn.yml, daily by default) writes. `learnings.md` is generated from `rules.json`; change a rule there, and only when the task is about rules.
- `build` visuals (`visuals.Build`) render only the given HTML and CSS, with scripts off and the network blocked; keep it that way (`generate.BUILD_BLOCKED`).
- `dm.py` replies to comments on its own (scheduler.py starts it every 10 minutes): its replies state only what the post, its guide or its sources say; anything else goes to the "Comments for you" issue for the creator.
- `motion.py` animations show abstract shapes only (boxes, dots, arrows, code; no faces, people, characters or animals), and every value they show must be true (real program output, cited numbers; `race`, `bignumber`, `latency` and `launch` require a `source`; `regex` and `sql` show what Python's re and a read-only SQLite query work out).
- The account's own numbers outrank studies (playbook.md, "What our own numbers say"): two reels a day by default (`REEL_SLOTS`), Myth vs fact as the main format, under 20 seconds, and no comment-to-DM offer on reels the bot writes. Myths open on real code (ideally a "guess the output" puzzle) under a statement hook, never a question, and prove the real output on their last point (`reveal` 3) (`generate.pillar_errors`). News, freelance and client formats are out of the rotation. News (by hand) and Explained reels are a small story told plainly: the problem first, then what happened, then the fix; never a teaser (director.md, 2026-10-23).
- `ai_facts.md` is the only source of AI-coding-tool facts the writer may use (the `topic` test's ai_tool side, whose reels must cite those official pages in `sources`). Add a fact only after reading it on its official page, quoted as it says.
- `playbook.md` is the researched reel playbook (hooks, script, visuals, sound); the writers (`generate.py`, and `trends.py` for news), the hook judge and `qa.py` read it, so change rules there, not in three prompts.
- `stage.py` draws stage reels (the explainer style; `scenes`, one per slide, on a random half of days, `STAGE`/`STAGE_CHANCE`): every value on a scene is real, a docs scene quotes its page (one of `sources`) exactly, and a rejected scene falls back to the classic slides.
- `stories.py` posts Instagram stories after each reel: a "Guess the output" still (myth reels that open on code that prints, one a day) and a teaser (the reel's first seconds and a "new reel" card); both use only the reel's own code, hook and video, and record `stories` on the reel.
- `youtube.py` uploads each reel and showcase as a YouTube Short; its title and description come from the reel (hook, caption, sources, hashtags) and say plainly when the voice is an AI voice; it records `youtube_id` on the entry and never blocks the Instagram record.
- `linkedin.py` cross-posts each reel, carousel and showcase to the creator's LinkedIn with its own Claude-written text (same honesty rules; never anything that hides that it was written with AI); it records `linkedin_id` on the entry and never blocks the Instagram record.
- `director.md` is the creator's taste as rules (pacing, motion, composition, captions, sound, truth on screen) plus a dated log of his notes; `generate.playbook` appends it to the playbook for the same readers. When the creator gives a note on how reels look or feel, add it to the log and turn it into a rule there.
- `study.py` (study.yml) studies other creators' videos for patterns only: never copy their content, and keep its prompt's split into adoptable vs breaks-the-hard-rules, and credit whatships.com launches (product, company, X post) as its terms ask. `studies/` is written by that workflow.
- Final mixes are mastered to -14 LUFS (`render.master`); never go back to peak scaling. Entrances use `render.spring`, not overshoot eases.
- Speed: a reel is about 10 minutes of work and the rest of a run waits for the post time on purpose (GitHub starts crons late). Setup never waits on apt (`.github/actions/ffmpeg`, capped browser packages), stage reels and showcases draw frames in several browsers at once (`stage.frames`, `RENDER_WORKERS`; pages must stay pure functions of time), and `publish.took` logs each part's time. The voice check must keep its verdicts when made faster (compare old and new on real audio, `test_voice.py --verify`).
- Verify every change with the `verify` skill (`.claude/skills/verify/SKILL.md`): the fast checks of its §1 always (`test_learn.py`, `test_study.py`, `test_motion.py`, `test_voice.py`, `generate.py --check`, `docs_check.py`, pyflakes), and the real end-to-end runs it lists for the parts you touched.

## Docs stay in the same change as the code

When you change a script, a workflow, an env var, a schedule or a behavior the docs describe, update `README.md`, this file and the skill in the same change. Then run:

```bash
python3 docs_check.py
```

A Stop hook (`.claude/hooks/docs_guard.py`) runs it and blocks once per set of changes if it fails, or if code changed but none of the three docs did. CI runs it on every push except `reels.json`-only commits and on pull requests (`docs-check.yml`), and `docs-sync.yml` opens a pull request with Claude's fixes for anything that still slips through.
