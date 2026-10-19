# Session handoff: automation-reel (2026-10-19)

Written at the end of a long Claude Code session so a new session can continue without the old transcript.
Read this, then `CLAUDE.md`, then load the `automation-reel` skill (`.claude/skills/automation-reel/SKILL.md`) and
the `verify` skill before changing anything. Those three are kept accurate against the code; this file is only the
state of play and the open threads.

## 1. Who and what

- Creator: Hassan, Instagram **@hassanjan.k** (developer tips; faceless; Pakistan, UTC+5). Writes in short, informal
  English; answer in plain simple English, lead with the result, show samples when possible.
- Repo: `hassanjan1841/automation-reel`. A Python 3.12 + ffmpeg + Playwright pipeline on GitHub Actions that writes,
  voices, renders, reviews and posts Instagram reels every day, plus a weekly carousel, comment replies, a daily
  learning loop and a weekly study of other creators. Claude is called through the Claude Code CLI (Max plan
  OAuth token), not the API.
- Working branch for Claude sessions: `claude/3d-scenes-design-auh4tw`. Work there, open a PR to `main`, and merge
  only after the full verify procedure (the creator's standing instruction: "merge after fully tested, verified").
  Never push to `main` directly. Never force-push (it was blocked as destructive); when the remote branch holds
  already-squash-merged history, restart the branch from `origin/main` and merge the old remote branch with
  `git merge -s ours` before pushing.
- Commit trailer used in this project:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and a `Claude-Session:` line for the current session.
  PR bodies end with the "Generated with Claude Code" line and the session link.

## 2. Hard rules (never relax)

- No music ever (sound effects and the AI voice only). Halal and honest: no invented results, stories, numbers,
  quotes or posts; nothing of anyone else's shown as his. Never Reddit. No faces, people or animals in visuals
  (3D and `motion.py` too). Claims about others' products are stated as *their* claims with sources.
- Never post for real while testing: `DRY_RUN=true`. A manual Daily reel run defaults to `dry_run: true`.
- Never store, print or put into secrets any token the creator pastes in chat (a PAT and a cron-job.org key were
  pasted early on; they were not used). Tell him where to put secrets himself.
- `study.py` learns patterns only, never content.
- Docs (README, CLAUDE.md, skill) change in the same PR as the code; `python3 docs_check.py` must pass.

## 3. What is live now (main at `75263fb`, 2026-10-18)

The growth plan from the 2026-10-14 analysis (PR #27) is live:

1. **Rules reset**: the 10 early rules are retired with reasons; 3 evidence-backed rules are active (open on the
   proof, a held beat before the result, end on a question). `rules.json` -> `learnings.md`.
2. **Two reels a day**: repo variable `REEL_SLOTS` (default `1,3`): 12:00 UTC (5 PM PKT) and 20:00 UTC (1 AM PKT).
   Slot 2 (16:00) is off; its cron exits. `1,2,3` brings it back.
3. **Myth vs fact is the main format**: slot 1 every day, slot 3 about a third of days (else news, trick, X vs Y,
   "Next.js from zero"). Famous basics (CORS, JWT, var/let, ==, caching, git, async), never niche setups.
   Freelance playbook removed. `playbook.md` has "What our own numbers say", which outranks studies.
4. **Under 20 s**: voiceover 36 to 46 words (`generate.VO_MIN_WORDS`, `VO_MAX_WORDS`).
5. **No comment-to-DM offers on written reels** (`generate.pillar_errors`); the `cta_style` test (question vs
   "send this to a dev who...") has been **running since 2026-10-15**; the closing card follows the ending
   (`render.closing_prompt`).
6. **Login alert**: `publish.check_login` stops a run in seconds on a dead Instagram token and the workflow opens
   an "Instagram login failed" issue.

Earlier work this session, all merged: playbook system (#13), 12 premium 2D animations in `motion.py` (#14),
full docs-vs-code audit plus bugs (#15), light-theme animation fix and the race "Source: undefined" fix (#16),
and the growth plan (#27). Other PRs on main (#17 to #26: study-driven formats, launch-video animations,
auto comment replies, a second Claude token fallback, ready-made video posting via `extras.json`) came from other
sessions; read the skill for them.

## 4. Numbers (Insights workflow, straight from Instagram, 2026-10-14; learning report 2026-10-19)

- Account: **55 followers, following 219**, ~100 posts. Typical reel: ~110 views, all on day 1 (0% after day 1),
  skip rate ~83%, ~14% of the reel watched, almost no saves/shares/likes.
- Only breakout: #63 "Your CORS header isn't *security*": 1,105 views, 58.6% skip, 7 saves, 2 shares.
- Creator's own "I put a cat in my terminal" reels (posted by hand): 26 to 29% skip, 8 s watched, but 142/181 views
  and 0 shares: retention alone does not push a reel; shares do.
- First week after the growth plan (report 2026-10-19, last 7 days vs the 7 before): skip rate **77.3% vs 81.8%**
  (better), share watched **18% vs 16%** (better), views at 7 days 153 vs 163 (flat), shares 0 vs 0.2.
- **Checkpoint 2026-10-28** (agreed targets): skip < 70%, >= 1 share per reel, median views >= 200, one 1,000+
  breakout a week, 100+ followers. Pull fresh numbers with Actions -> Insights (dispatch `insights.yml`) and read the
  latest `reports/<date>.md`; then decide whether to return to 3 reels a day.

## 5. Open threads (in priority order)

1. **Oct 17 lost both reels**: every run failed with `claude exited 1` (Claude CLI unavailable: usage limit or
   outage). The fallback exists (`.github/actions/claude`) but the secret `CLAUDE_CODE_OAUTH_TOKEN_2` is **not set**
   (logs show `TOKEN_2:` empty). Ask the creator to add it (from `claude setup-token` on a second Claude account)
   in repo Settings -> Secrets and variables -> Actions. Do not handle the token yourself.
2. **Weak code cards in myth reels** (proposed, not built; the creator was asked, no answer yet): the writer
   sometimes fills `diff`/`code` cards with comment lines explaining the point instead of real code, so the frame
   review rejects them and the reel falls back to text cards (reel #72: frame 0 was hook text only). Proposed fix:
   (a) a `generate.visual_errors` rule rejecting code/diff cards that are mostly comments, and diffs without a real
   removed-to-added change, so the writer repairs them before rendering; (b) when a `hook_visual` is rejected,
   fall back to its "after" code as a plain code card instead of dropping it. Later reels (#74 to #79) mostly
   showed code, so it is intermittent. Add tests and mutants; verify with real writer samples.
3. **Security incident (2026-09-29)**: a worm pushed a forged "Posted reel 37" commit as `github-actions[bot]`
   adding `.vscode/tasks.json` (runs a fake font `public/fonts/fa-solid-600.eot` on folder open) and hid spreader
   `.bat` files in `.gitignore`. Cleaned on 2026-10-03 on all branches (commit "Remove injected VS Code autorun
   task..."). Instagram invalidated the token around then (fixed by the creator). Still the creator's to-do, status
   unknown: clean the infected (likely Windows) machine, change GitHub password, revoke PATs/SSH keys, rotate
   Supabase, Fish, Claude, YouTube and cron-job.org keys. If anything new appears in `.vscode/` or odd files in a
   bot-authored commit, treat it as this worm.
4. **Step 3 of the growth plan (not started)**: a YouTube Shorts uploader (same reels, second platform), and check
   Meta's official docs on whether the Content Publishing API supports Trial Reels (`trial_params`); third-party
   sources disagree. Build only if confirmed.
5. **Two Instagram reels the creator wanted copied as animation styles** (techniques only):
   `https://www.instagram.com/reel/DcGvDkqioqS/` and `https://www.instagram.com/reel/Daa43CqoE_o/`. Instagram is
   blocked from the sandbox; ask for screen recordings (or a `study`-labelled issue with them attached), then compare
   with `motion.py`'s templates. A third link (DdhR21VBfQH) was about Jev (TypeSafe AI); done: reel queued and posted.
6. **YouTube downloads in `study.py`** fail from GitHub runner IPs (yt-dlp blocked). Options discussed: self-hosted
   runner on the creator's Mac, throwaway cookies, or study covers/metadata only. Undecided.
7. **The creator's own growth tasks** (matter more than code at 55 followers): 15 min a day of real comments on
   bigger dev creators' reels, unfollow most of the 219 followed accounts, pin the CORS reel, clearer bio, keep
   posting his own reels like the terminal cat one.

## 6. Sandbox notes (Claude Code on the web)

- Network: only GitHub (through the `gh api` proxy and the GitHub MCP tools) and package registries work. Instagram,
  graph.instagram.com, Hugging Face, `*.blob.core.windows.net` (Actions artifacts) and most sites are blocked. So:
  no real voice locally (Kokoro/Whisper models come from Hugging Face), no downloading run artifacts, no Instagram
  links. The creator can allow hosts in the environment's Network access settings
  (https://code.claude.com/docs/en/cloud-environments#network-access). WebSearch works; WebFetch is blocked for many
  sites.
- To show the creator a real voiced reel: dispatch `daily-reel.yml` with `dry_run=true` (outside a slot's window,
  so it does not use one of the slot's two attempts), then read the run log (hook, review, caption) and give him
  the artifact link (`https://github.com/<repo>/actions/runs/<run>/artifacts/<id>`; he downloads it on GitHub).
- Local renders: silent timed voice via `tests/e2e_publish.silent_voice`. Chromium:
  `E2E_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (patch `BrowserType.launch` to pass
  `executable_path`). ffmpeg: put the binary from `.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/` on
  `PATH` (a symlink named `ffmpeg`). three.js for 3D: `E2E_THREE=<folder with three@0.170.0>` (download the npm
  tarball `three-0.170.0.tgz` from registry.npmjs.org, which is allowed). The sandbox ffmpeg has no `drawtext`.
- Logs: `gh api repos/<repo>/actions/runs/<id>/jobs` for steps; the GitHub MCP `get_job_logs` tool for log text
  (the `gh` client refuses log redirects).
- Mutation check: `tests/mutants.py` (about 115 mutants; motion ones render in Chromium, slow; run in the
  background). After code edits, re-check that no mutant went STALE.

## 7. Verify procedure (short form; the `verify` skill is the full one)

`.venv/bin/python test_learn.py` (127 tests), `test_study.py`, `test_motion.py` (with `E2E_CHROMIUM`),
`test_voice.py`, `generate.py --check`, `python3 docs_check.py`, `.venv/bin/python -m pyflakes *.py tests/*.py`,
then mutants for every new behaviour, `tests/e2e_publish.py` for publish/render changes (11 checks), real-writer
samples (`generate.today` + `pick_hook`) for writer changes, CI green on the PR, then merge.

## 8. Suggested first message for the new session

"Read HANDOFF.md on branch claude/3d-scenes-design-auh4tw, then CLAUDE.md and the automation-reel skill. Check the
latest reels and learning report, then continue with the open threads."
