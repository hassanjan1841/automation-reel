---
name: automation-reel
description: Everything needed to work on the automation-reel project, the pipeline that posts one Instagram Reel a day to @hassanjan.k. Use for any task in this repo - adding or editing reels in reels.json, changing slide rendering, voiceover pronunciation, the trend scan and fact-check, queue generation, Instagram publishing, insights, token refresh, GitHub Actions runs, or debugging a failed daily post.
---

# automation-reel

Python 3.12 + ffmpeg pipeline, run by GitHub Actions. No server, no database: `reels.json` is the record of what was posted; nothing is written ahead of time.

## Pipeline at a glance

```
daily-reel.yml (starts 13:07 UTC, posts at POST_AT_UTC 14:00)  ->  publish.py
  0. a reel added by hand (posted_at: null) is used as is; otherwise today's reel is written now:
  1. trends.performance()    recent reels' insights (views, skip rate, watch time...) steer what gets written
  2. trends.timely_reel()    scrape -> Claude picks up to 3 (web search) -> validate -> Claude fact-check
                             pass/fix -> today's reel, pillar "timely"; any failure or reach < 7 -> fall back
  3. else generate.today()   a fresh evergreen reel for today's pillar
  3. voice.synthesize()      Fish (one continuous take, cut per slide with Whisper word times) or Kokoro
                             (one clip per line); takes are transcribed with Whisper, misheard words get
                             Claude respellings or phonemes, fixes saved to pronounce.json per engine
  4. render.render_reel()    Pillow frames -> ffmpeg -> out/reel-<id>.mp4 (1080x1920, 30fps), captions from
                             the voiceover word times, point visuals from visuals.build()
  4b. publish.check_visuals()  qa.review(): Claude reads one frame per slide; a rejected visual is replaced by
                             the point's next choice or its body text and the reel is rendered again
  4c. publish.wait_for_post_time()  sleep until POST_AT_UTC when ready early (not in DRY_RUN)
  5. upload to Supabase bucket "reels" (public) -> Instagram REELS container -> poll -> media_publish
  6. delete upload, write posted_at + media_id, workflow commits reels.json + pronounce.json
  7. test_voice.py          pronunciation regression test (text rules only in CI)

token-refresh.yml (Sun 10:00 UTC)
  refresh_token.py   refreshes IG_TOKEN (60-day expiry) and writes it back with gh secret set

insights.yml (manual)  insights.py 60   per-reel metrics table + cover thumbs artifact

docs-check.yml (every push)          docs_check.py   fails if the docs drifted from the code
docs-sync.yml (code push + Sat 09:00) docs_sync.py   Claude fixes the docs, opens a PR from docs-sync
```

Claude is called through the Claude Code CLI (`claude -p ... --json-schema`), billed to the Max plan via `CLAUDE_CODE_OAUTH_TOKEN`, not the API. Model is `generate.MODEL` (override in trends with `CLAUDE_MODEL`).

## Files

| File | Role | Key entry points |
| --- | --- | --- |
| `reels.json` | Record of posted reels; one added by hand with posted_at null is posted next | list of reel objects |
| `publish.py` | Orchestrates one daily post | `main`, `upload`, `publish_to_instagram` |
| `trends.py` | Scrape + editor + fact-checker | `collect`, `performance`, `pick`, `fact_check`, `timely_reel` |
| `generate.py` | Evergreen top-up, voiceover/cue/visual backfill, the validator | `validate`, `visual_errors`, `cue_errors`, `generate`, `append`, `add_voiceovers`, `add_cues`, `add_visuals`, `SYSTEM`, `SCHEMA`, `VISUAL_SCHEMA`, `PILLARS` |
| `visuals.py` | Code window, terminal, targeted screenshot (scroll to `find`, outline, spotlight) | `build`, `code_panel`, `terminal_panel`, `capture`, `Screenshot`, `Panel` |
| `qa.py` | Claude reviews one frame per slide after rendering | `review`, `frames`, `SYSTEM`, `SCHEMA` |
| `render.py` | Slides, animation, SFX, ffmpeg | `build_slides`, `render_frames`, `build_audio`, `render_reel` |
| `voice.py` | Fish/Kokoro voiceover + Whisper listen-back | `COMMON_RULES`, `KOKORO_RULES`, `CUE`, `strip_cues`, `lexicon`, `speakable`, `script`, `engine`, `Fish`, `Kokoro`, `synthesize`, `say_whole`, `say_checked`, `split`, `learn`, `misheard` |
| `test_voice.py` | Pronunciation regression test | `SPEAKABLE`, `MISHEARD`, `SENTENCES`, `KNOWN` |
| `pronounce.json` | Learned respellings, word to spoken form | data, written by `say_checked` |
| `insights.py` | Account + per-reel metrics | `main`, `metric` |
| `refresh_token.py` | IG token refresh | script |
| `docs_check.py` | Docs vs code drift check, stdlib only | `check` |
| `docs_sync.py` | Claude proposes doc edits, only doc files are changed | `main`, `ask_claude`, `apply` |
| `.claude/hooks/docs_guard.py` | Stop hook, blocks once when docs look stale | `main` |

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # needs ffmpeg on PATH
.venv/bin/python generate.py --check     # validate every reel; exit 1 on any error or duplicate hook
.venv/bin/python render.py <id>          # out/reel-<id>.mp4, no voice
.venv/bin/python voice.py <id> [voice]   # out/reel-<id>-<voice>.mp4 with voiceover (listen-back check on)
.venv/bin/python test_voice.py          # pronunciation rules; add --audio to speak and transcribe every test sentence
.venv/bin/python generate.py --voiceover  # Claude writes voiceovers for unposted reels missing one
.venv/bin/python trends.py               # list scraped trend candidates
.venv/bin/python trends.py --pick        # also ask Claude to pick/write (prints only, saves nothing; needs claude CLI)
DRY_RUN=true .venv/bin/python publish.py # full daily path, render only, posts nothing
IG_TOKEN=... .venv/bin/python insights.py 20
python3 docs_check.py                    # docs match the code? no dependencies needed
python3 docs_sync.py                     # let Claude fix stale docs locally (needs claude CLI)
```

First run downloads Poppins into `fonts/`, the Kokoro model into `models/` and Whisper `small.en` into `models/whisper/` (all gitignored). Output goes to `out/` (gitignored).

## Reel schema

```jsonc
{
  "id": 31,                         // next integer; never reuse
  "pillar": "devtip",               // ai|devtip|take|freelance|concept|saas|productivity|timely
  "style": "light",                 // light|dark, alternate with the previous reel
  "kicker": "Dev tip",              // 1-3 words, <= 24 chars
  "hook": "Six to twelve words with the *key word* highlighted",
  "points": [                       // exactly 3
    { "title": "Max eight words", "body": "Max sixteen words, no asterisks.",
      "visual": [ { "type": "code", "language": "ts", "title": "user.ts", "code": "...", "highlight": [2] } ] }
  ],                                // visual: optional, 1-3 choices best first (code, terminal, screenshot + find)
  "cta": "A short question with one *highlighted* word?",
  "caption": "Line one.\nLine two.\nA question to end on? 👇",
  "hashtags": ["#nextjs", "..."],   // 8-12, unique, ^#[A-Za-z0-9_]+$
  "voiceover": ["..."],             // 5 spoken lines (hook, 3 points, cta); required on unposted reels
  "sources": ["https://..."],       // timely reels only, primary source first; used to block reposting a story
  "posted_at": null,                // ISO timestamp, set by publish.py
  "media_id": null                  // Instagram media id, set by publish.py
}
```

Rules enforced by `generate.validate` (the single source of truth, also run on Claude output):
- Hook 6-12 words with at least one balanced `*highlight*`. Titles max 8 words. Bodies max 16, no `*`.
- CTA ends with `?` and has exactly one highlight.
- No emojis on slide text; emojis only in the caption.
- Caption 2-3 non-empty lines; last line contains `?` and ends with 👇.
- Hooks must be unique after lowercasing and stripping non-alphanumerics (`generate.norm`).
- Voiceover: exactly 5 non-empty lines, 35 to 70 words in total, line 1 max 14 words, no symbols, `*` or emojis, no line more than 60% similar to its slide (`generate.similar`), and delivery cues per `generate.cue_errors`: every line starts with a `[cue]`, a fresh cue at least every 10 spoken words, a high-energy cue on the hook, at most one low-energy cue, at least 5 different cues. `--check` skips voiceover errors on posted reels, which predate it.

Content rules (in `generate.SYSTEM`): evergreen reels have no news, versions, prices or dates; no invented stories or stats. The voiceover adds to the slides (the why, an example, what goes wrong) instead of reading them, sounds like a developer talking to a friend, writes numbers as spoken, and its last line asks for a comment without saying "comment below" or "follow". Timely reels drop the evergreen rule but every claim must be backed by a fetched source.

Evergreen pillar is chosen by the weekday the reel will post (`generate.PILLARS`, Monday = `ai`).

## Common tasks

**Add a reel by hand**: append with the next `id`, `posted_at`/`media_id` null, then `generate.py --voiceover` if you did not write the voiceover, `generate.py --check` and `voice.py <id>`. Move it up the list to post sooner (order of unposted entries is the posting order).

**A word is mispronounced**: the listen-back check usually fixes it on its own and records it in `pronounce.json` (keyed by engine, applied before the rules). If a learned respelling sounds wrong, edit or delete it there. For patterns (numbers, acronyms, symbols) add a `(regex, respelling)` tuple to `voice.COMMON_RULES` (every engine) or `voice.KOKORO_RULES`; order matters, specific terms go before the generic acronym/plural rules. Add a case to `test_voice.SPEAKABLE` or `SENTENCES`, then run `test_voice.py --audio`.

**Change the look**: `render.THEMES` for colors, layout constants at the top of `render.py`. Keep text inside the Instagram safe zone (`SAFE_TOP`, `SAFE_BOTTOM`, `MARGIN`). Slide timing is driven by word count, clamped to 3-6s per slide and 15-25s total, then stretched to fit the voice.

**Change the voice**: repo variable `VOICE` (a Fish voice id, a Kokoro voice, or `none` for SFX only); `VOICE_ENGINE` forces `fish` or `kokoro`. Fish needs the secret `FISH_API_KEY` and falls back to Kokoro without it. `FISH_MODEL` defaults to `s2.1-pro-free` (free until 2026-11-30). `VOICE_PITCH` exists but shifted voices sound robotic; pick a different voice instead.

**Skip the news, always evergreen**: repo variable `TRENDING=off`. **Post time**: `POST_AT_UTC` (HH:MM, default 14:00); move the cron in `daily-reel.yml` with it so the job still starts about an hour early.

**Pause**: disable the Daily reel workflow. Keep Token refresh on, or the IG token expires after 60 days.

**Run in CI by hand**: Actions > Daily reel > Run workflow. `dry_run` defaults to true; the MP4 is uploaded as an artifact either way.

## Secrets and variables

Secrets: `IG_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `YOUTUBE_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `GH_PAT` (fine-grained, this repo, Secrets read/write).
Variables/env: `POST_AT_UTC`, `FORCE_POST` (a real run skips when a reel already went out today, UTC, unless true), `VOICE`, `VOICE_ENGINE`, `VOICE_PITCH`, `FISH_API_KEY`, `FISH_MODEL`, `TRENDING`, `DRY_RUN`, `GRAPH_VERSION` (default `v25.0`), `CLAUDE_MODEL`.
Never print a token; `publish.redact` and the `replace(token, '***')` calls exist for that. Keep new error paths redacted too.

## Gotchas

- Supabase Storage needs the legacy `service_role` JWT. New `sb_secret_` keys are rejected there.
- The `reels` bucket must be public; `upload` HEADs the public URL and fails loudly if not.
- The upload is deleted in `finally`, even on success, since Instagram has already fetched it.
- The daily workflow uses the `reels-queue` concurrency group and `git pull --rebase` before pushing so `reels.json` commits do not collide. Keep that when adding workflows that write it.
- The trend scan is best effort: fewer than 10 fresh items, any exception, reach below 7, no sources, a reused primary source, a duplicate hook or a fact-check reject all fall back to `generate.today`. Do not let a trends change raise past `publish.main`'s try/except.
- Instagram insights: request one metric per call (`insights.metric`); one unsupported metric fails the whole request.
- YouTube search costs 100 quota units per query; 8 queries a day is under the free 10,000.
- `thumb_offset` (the cover) is the last fully visible frame of the hook slide.
- The listen-back check writes `pronounce.json` during a real run; the daily workflow commits it with `reels.json`. Numbers are not checked (transcripts spell them too many ways). Some names are said right but Whisper cannot spell them back; those go in `test_voice.KNOWN`.
- `voice.ask_respellings` pins `claude-sonnet-5` instead of following `CLAUDE_MODEL`. If Claude is unavailable it returns no options and the line is spoken as is.
- The daily workflow caches `models/` under key `kokoro-v1.0-whisper-small.en`; change the key when a model changes.
- Write `reels.json` with `indent=2, ensure_ascii=False` plus a trailing newline so diffs stay clean.

## Keeping docs current

Three docs, one job each. Put a fact in the one it belongs to, not in all three:
- Script docstrings: usage, flags and env vars of that script (source of truth).
- `README.md`: running the project (schedules, secrets, variables, pausing, manual runs).
- `CLAUDE.md`: short rules for Claude sessions.
- This skill: how the code works and how to change it safely.

When a change adds, renames or removes a script, workflow, env var, flag, schedule, function named here, or changes a behavior described here, update the docs in the same change and run `python3 docs_check.py`.

What `docs_check.py` enforces: every script has a docstring; every script and workflow is named in README and this skill; every env var, secret and repo variable the code reads is named in both; every `module.name` and `.py` path in the docs exists; every documented `python <script> --flag` is handled by that script; every cron time appears in README. Extend it when a new kind of drift bites.

Automation around it:
- Stop hook `.claude/hooks/docs_guard.py` (registered in `.claude/settings.json`) blocks once per distinct change set when `docs_check.py` fails or code changed without doc changes. It remembers the last flagged state in `.git/docs-guard-ack`.
- `docs-sync.yml` runs `docs_sync.py`: diff of code since the docs were last committed (ignoring `reels.json`) plus `docs_check.py` output goes to Claude with read-only tools (Read/Glob/Grep). Claude returns `{file, old, new}` edits as structured output; `apply` accepts only the three doc files and each `old` must match exactly once. One retry reports failed edits back. `docs_check.py` must pass, then a PR is opened from `docs-sync`. Claude never gets write tools because Claude Code protects `.claude/` from edits in non-interactive runs. Needs "Allow GitHub Actions to create and approve pull requests" in repo settings.

## Before calling a change done

1. `.venv/bin/python generate.py --check` passes.
2. `python3 docs_check.py` passes.
3. For render/voice changes: render one light and one dark reel and look at the MP4 (safe zone, overflow, timing, audio). Voice changes also need `test_voice.py --audio` to pass.
4. For publish/trends changes: `DRY_RUN=true .venv/bin/python publish.py` end to end.
5. Workflow changes: trigger Daily reel with `dry_run` on and check the run log and artifact.
