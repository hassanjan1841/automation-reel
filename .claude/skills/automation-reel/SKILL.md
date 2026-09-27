---
name: automation-reel
description: Everything needed to work on the automation-reel project, the pipeline that researches, writes, voices, renders, reviews and posts one Instagram Reel a day (plus a weekly carousel) to @hassanjan.k. Use for any task in this repo - the daily writer and news editor, fact-check and honesty review, slide rendering and visuals (code, diff, terminal, post, chat, quote, screenshot, recorded demos), voiceover and pronunciation, carousels, the weekly learning loop, Instagram publishing, insights, token refresh, GitHub Actions runs, or debugging a failed daily post.
---

# automation-reel

Python 3.12 + ffmpeg + Playwright pipeline, run entirely by GitHub Actions (the creator's machine can be off). No server, no database: `reels.json` records posted reels and `carousels.json` posted carousels; nothing is written ahead of time.

Hard rules from the creator, never relax them: no music (sound effects only); everything halal and honest (no invented results, stories, numbers or quotes, no one else's work as his own, AI-made content is fine but not deceptive); no Reddit; no faces or animals in visuals (initials instead of photos).

## Pipeline at a glance

```
daily-reel.yml, twice a day  ->  publish.py
  slot 1: starts 11:07 UTC, posts at POST_AT_UTC 12:00 (5 PM Pakistan): the day's series or news
  slot 2: starts 15:07 UTC, posts at 16:00 (9 PM Pakistan): SLOT=2, relatable (generate.RELATE)
  slot 3: starts 19:07 UTC, posts at 20:00 (1 AM Pakistan): SLOT=3, generate.slot3_format picks news, trick,
          versus or series at random per date (news only with a strong fact-checked story, else another);
          slot 1 teaches (generate.TEACH); only slot 3 runs the trend scan; each slot has its own 3D coin flip
  0. a reel added by hand (posted_at: null) is used as is; otherwise today's reel is written now:
  1. trends.performance()    recent reels' insights (views, skip rate, watch time...) steer what gets written
  2. trends.timely_reel()    scrape -> Claude picks up to 3 (web search, newer developments, no motives) ->
                             validate -> generate.repair -> Claude fact-check (sources + quotes verbatim)
                             pass/fix -> today's reel, pillar "timely"; any failure or reach < 7 -> fall back
  3. else generate.today()   a fresh evergreen reel for today's pillar (generate.PILLARS), labelled with its
                             series and episode (generate.series_label, e.g. "Client vs Me #4"); both writers
                             read learnings.md (generate.learned)
  3b. voice.synthesize()      Fish (one continuous take, cut per slide with Whisper word times) or Kokoro
                             (one clip per line); takes are transcribed with Whisper, misheard words get
                             Claude respellings or phonemes, fixes saved to pronounce.json per engine
  4. render.render_reel()    Pillow frames -> ffmpeg -> out/reel-<id>.mp4 (1080x1920, 30fps) + cover jpg:
                             camera motion, captions from the voiceover word times, point visuals from
                             visuals.build() (recorded demos come from demos.record at this point)
  4b. publish.check_visuals()  qa.review() with the reel's sources: Claude reads one frame per slide.
                             honest=false raises publish.Dishonest: a news reel is dropped and an evergreen
                             reel is written and reviewed instead (a hand-added reel is never replaced);
                             a rejected visual is replaced by the point's next choice or its text
  4c. publish.wait_for_post_time()  sleep until POST_AT_UTC when ready early (not in DRY_RUN)
  5. upload the video and out/reel-<id>-cover.jpg to Supabase bucket "reels" (public) -> Instagram REELS container (cover_url, thumb_offset as fallback) -> poll -> media_publish
  6. delete uploads, write posted_at + media_id, workflow commits reels.json + pronounce.json
     (per slot: a real run exits when today already has `slot` posts, unless FORCE_POST)
  7. test_voice.py          pronunciation regression test (text rules only in CI)

weekly.yml (Sun 10:00 UTC)
  refresh_token.py   refreshes IG_TOKEN (60-day expiry) and writes it back with gh secret set
  learn.py           per-reel insights -> learnings.md (rules the writer reads) + GitHub issue report
  carousel.py        weekly cheat-sheet carousel -> Instagram CAROUSEL, logged in carousels.json

demo-preview.yml (manual)  demos.py record <spec>   records one demo on GitHub and uploads the mp4

insights.yml (manual)  insights.py 60   per-reel metrics table + cover thumbs artifact

docs-check.yml (every push)          docs_check.py   fails if the docs drifted from the code
docs-sync.yml (code push + Sat 09:00) docs_sync.py   Claude fixes the docs, opens a PR from docs-sync
```

Claude is called through the Claude Code CLI (`claude -p ... --json-schema`), billed to the Max plan via `CLAUDE_CODE_OAUTH_TOKEN`, not the API. Model is `generate.MODEL` (override in trends with `CLAUDE_MODEL`).

## Files

| File | Role | Key entry points |
| --- | --- | --- |
| `reels.json` | Record of posted reels; one added by hand with posted_at null is posted next | list of reel objects |
| `publish.py` | Orchestrates one daily post | `main`, `todays_reel`, `new_entry`, `make_video`, `check_visuals`, `Dishonest`, `credits`, `wait_for_post_time`, `upload`, `allow_type`, `publish_to_instagram` |
| `trends.py` | Scrape + news editor + fact-checker | `collect`, `performance`, `pick`, `quotes_allowed`, `fact_check`, `timely_reel` |
| `generate.py` | The writer and the validator; manual backfills | `today`, `generate`, `repair`, `tidy`, `validate`, `visual_errors`, `cue_errors`, `series_label`, `learned`, `slot`, `pillar_for`, `slot3_format`, `TEACH`, `RELATE`, `EXTRA_FORMATS`, `package_errors`, `three_d_today`, `three_d_note`, `three_d_count`, `strip_3d`, `add_voiceovers`, `add_cues`, `add_visuals`, `SYSTEM`, `SCHEMA`, `VISUAL_SCHEMA`, `QUOTE_PLATFORMS`, `PILLARS` |
| `visuals.py` | Floating cards (shadow, 3D tilt, sheen): code with a hand-drawn circle, diff, typed terminal, post card, POV chat, credited quote, targeted screenshot with cursor click, recorded demo clip | `build`, `Card`, `Code`, `Diff`, `Terminal`, `Post`, `Quote`, `Chat`, `Screenshot`, `Clip`, `recorded`, `Scene`, `capture`, `code_image`, `sketch_ellipse`, `stroke` |
| `demos.py` | Screencast recorder: website walkthroughs and live VS Code (openvscode-server, clean env, allowed commands) | `record`, `record_walkthrough`, `record_ide`, `Screencast`, `web_step`, `ide_step`, `IDE_SETTINGS`, `ALLOWED` |
| `scene3d.py` | three.js 3D moments rendered frame by frame in headless Chromium (transparent PNG frames for reels, mp4 from the CLI) | `render_scene`, `device_image`, `brand`, `slug_of`, `PAGE`, `ANIMAL_LOGOS` |
| `learn.py` | Weekly: measure posted reels, group by pillar/series/visual, write learnings.md + report | `measure`, `groups`, `write_up`, `LEARNINGS`, `MIN_AGE_HOURS` |
| `carousel.py` | Weekly carousel: write (Claude), draw 1080x1350 slides, review, post as CAROUSEL with alt_text | `write`, `check`, `draw`, `content_slide`, `centred`, `review`, `post`, `SCHEMA`, `LOG`, `CALL_TO_ACTION` |
| `qa.py` | Claude reviews one frame per slide after rendering: ok, visual_ok, honest (with the reel's sources) | `review`, `frames`, `SYSTEM`, `SCHEMA` |
| `render.py` | Slides, camera motion, captions, finishing, SFX, ffmpeg, cover | `build_slides`, `Camera`, `Captions`, `finishing`, `render_frames`, `build_audio`, `sound_kit`, `make_cover`, `render_reel` |
| `voice.py` | Fish/Kokoro voiceover + Whisper listen-back | `COMMON_RULES`, `KOKORO_RULES`, `CUE`, `strip_cues`, `lexicon`, `speakable`, `script`, `engine`, `Fish`, `Kokoro`, `synthesize`, `say_whole`, `say_checked`, `clean_take`, `verify`, `islands`, `mute`, `report`, `split`, `learn`, `misheard` |
| `test_voice.py` | Pronunciation and voice-verifier regression test | `SPEAKABLE`, `MISHEARD`, `SENTENCES`, `KNOWN`, `STRAY`, `check_verifier` |
| `pronounce.json` | Learned respellings per engine, word to spoken form | data, written by `voice.learn` |
| `learnings.md` | Rules from the weekly learning loop, read by both writers | data, written by `learn.py` |
| `carousels.json` | Posted carousels | data, written by `carousel.py` |
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
.venv/bin/python test_voice.py --verify # the voice verifier still catches and cuts the recorded "uhh" (Whisper, no voice calls)
.venv/bin/python scene3d.py '<json>' 980 620 6   # render one 3D scene to out/scenes/
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
  "pillar": "devtip",               // ai|devtip|relatable|freelance|concept|saas|timely (older reels: take, productivity)
  "series": "Dev mistake",          // evergreen reels: the day's series; "episode": its number
  "style": "light",                 // light|dark, alternate with the previous reel
  "kicker": "Dev tip",              // 1-3 words, <= 24 chars; replaced by "<series> #<episode>" when posted
  "hook": "Six to twelve words with the *key word* highlighted",
  "hook_word": "RLS",               // optional, 3D days only: one word of the hook, spun in as 3D text above it
  "points": [                       // exactly 3
    { "title": "Max eight words", "body": "Max sixteen words, no asterisks.",
      "visual": [ { "type": "code", "language": "ts", "title": "user.ts", "code": "...", "highlight": [2] } ] }
  ],                                // visual: optional, 1-3 choices best first: code, diff (before/after), terminal,
                                    // tweet (post in his name), chat (POV), quote (real post: author, handle, platform,
                                    // url, exact text), screenshot (url + find), walkthrough (url + steps),
                                    // ide (files, setup, steps); on 3D days also diagram (nodes, edges, flow),
                                    // device (laptop + code, phone + screenshot), bars (real numbers + source),
                                    // logos (Simple Icons slugs) -- see generate.SYSTEM and generate.visual_errors
  "cta": "A short question with one *highlighted* word?",
  "caption": "Line one.\nLine two.\nA question to end on? 👇",
  "hashtags": ["#nextjs", "..."],   // 3-5, unique, ^#[A-Za-z0-9_]+$ (older posted reels have 8-12)
  "voiceover": ["..."],             // 5 spoken lines (hook, 3 points, cta); required on unposted reels
  "sources": ["https://..."],       // timely reels only, primary source first; used to block reposting a story
  "posted_at": null,                // ISO timestamp, set by publish.py
  "media_id": null                  // Instagram media id, set by publish.py
}
```

Rules enforced by `generate.validate` (the single source of truth, also run on Claude output):
- Hook 5-8 words with at least one balanced `*highlight*`. Titles max 4 words (a label; the voice carries the detail). Bodies max 8 (shown only without a visual), no `*`.
- CTA ends with `?` and has exactly one highlight.
- No emojis on slide text; emojis only in the caption.
- Caption 2-3 non-empty lines, the first naming the topic in searchable words; last line contains `?` and ends with 👇 (`generate.tidy` adds a missing 👇).
- Hooks must be unique after lowercasing and stripping non-alphanumerics (`generate.norm`).
- Voiceover: exactly 5 non-empty lines, 40 to 55 words in total, line 1 max 12 words, no symbols, `*` or emojis, points' lines no more than 60% similar to their slides and the hook and closing lines no more than 90% (`generate.similar`), and delivery cues per `generate.cue_errors`: every line starts with a `[cue]`, a fresh cue at least every 10 spoken words, a high-energy cue on the hook, at most one low-energy cue, at least 5 different cues. `--check` skips voiceover, cue, hashtag-count, hook, title and body length errors on posted reels, which predate those rules.
- Visuals per `generate.visual_errors`: code max 12x40, diff before/after max 12x40, terminal 1-6 commands of 40, tweet 10-200 chars, chat 2-5 messages of 60, quote on a known platform with an https url, walkthrough 1-4 steps, ide 1-8 steps with allowed commands only (`demos.allowed`) and max 12 typed lines of 60. 3D: diagram 2-5 nodes (labels max 12) with edges and a 1-8 hop flow over node ids, device phone only with a screenshot, bars 2-5 with an https `source`, logos 1-4 slugs none in `scene3d.ANIMAL_LOGOS`, `hook_word` one word of the hook, at most 2 3D moments per reel (`generate.three_d_count`).

Content rules (in `generate.SYSTEM`): evergreen reels have no news, versions, prices or dates; no invented stories or stats; the honesty rules (no fake results, invented scenes framed as POV, "I tested" only with a real run, no one else's work as his own, hooks never promise more than the reel delivers). The voiceover adds to the slides (the why, an example, what goes wrong) instead of reading them, sounds like a developer talking to a friend, writes numbers as spoken, and its last line asks for a comment without saying "comment below" or "follow". Timely reels drop the evergreen rule but every claim must be backed by a fetched source.

Pillar and series come from `generate.pillar_for`: reel 1 rotates the teaching series by weekday (`TEACH`: AI tool in 30s, Dev mistake, Explained, Build smart), reel 2 the relatable ones (`RELATE`: Client vs Me, POV, Client vs Me, POV ranking), reel 3 its day's format (`EXTRA_FORMATS`: Quick trick, X vs Y, Next.js from zero, or a news reel); the beginner series is given its earlier episodes to continue from. 3D is allowed on a random share of days (`generate.three_d_today`, seeded by the date so reruns agree, `THREE_D_CHANCE` default 0.5, `THREE_D=on|off` forces it); both writers are told via `three_d_note`, and `publish.todays_reel` strips 3D (`generate.strip_3d`) on other days. Real-post quotes are allowed at most once in six days (`trends.quotes_allowed`), and the caption credits every quoted author (`publish.credits`).

## Common tasks

**Add a reel by hand**: append with the next `id`, `posted_at`/`media_id` null, then `generate.py --voiceover` and `--cues` if you did not write the voiceover, `generate.py --check` and `voice.py <id>`. The first unposted entry is posted at the next daily run instead of a freshly written reel. A dry run saves `out/reel-<id>.json` beside its video, which can be added this way to post exactly what was reviewed.

**A word is mispronounced**: the listen-back check usually fixes it on its own and records it in `pronounce.json` (keyed by engine, applied before the rules). If a learned respelling sounds wrong, edit or delete it there. For patterns (numbers, acronyms, symbols) add a `(regex, respelling)` tuple to `voice.COMMON_RULES` (every engine) or `voice.KOKORO_RULES`; order matters, specific terms go before the generic acronym/plural rules. Add a case to `test_voice.SPEAKABLE` or `SENTENCES`, then run `test_voice.py --audio`.

**Change the look**: `render.THEMES` for colors, layout constants at the top of `render.py`. Keep text inside the Instagram safe zone (`SAFE_TOP`, `SAFE_BOTTOM`, `MARGIN`). With a Fish voiceover each slide lasts exactly as long as its part of the one continuous take; without a voice, timing is driven by word count (3-6s per slide, 15-25s total).

**Change the voice**: repo variable `VOICE` (a Fish voice id, a Kokoro voice, or `none` for SFX only); `VOICE_ENGINE` forces `fish` or `kokoro`. Fish needs the secret `FISH_API_KEY` and falls back to Kokoro without it. `FISH_MODEL` defaults to `s2.1-pro-free` (free until 2026-11-30). `VOICE_PITCH` exists but shifted voices sound robotic; pick a different voice instead.

**Skip the news, always evergreen**: repo variable `TRENDING=off`. **Post time**: `POST_AT_UTC` (HH:MM, default 12:00); move the cron in `daily-reel.yml` with it so the job still starts about an hour early.

**Pause**: disable the Daily reel workflow. Keep Weekly on, or the IG token expires after 60 days.

**Run in CI by hand**: Actions > Daily reel > Run workflow. `dry_run` defaults to true; the MP4 is uploaded as an artifact either way.

## Secrets and variables

Secrets: `IG_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `YOUTUBE_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `FISH_API_KEY`, `GH_PAT` (fine-grained, this repo, Secrets read/write).
Variables/env: `POST_AT_UTC`, `SLOT`, `REEL_FORMAT`, `FORCE_POST` (a real run skips when a reel already went out today, UTC, unless true), `VOICE`, `VOICE_ENGINE`, `VOICE_PITCH`, `VOICE_SPEED`, `FISH_MODEL`, `TRENDING`, `THREE_D`, `THREE_D_CHANCE`, `DRY_RUN`, `GRAPH_VERSION` (default `v25.0`), `CLAUDE_MODEL`.
Never print a token; `publish.redact` and the `replace(token, '***')` calls exist for that. Keep new error paths redacted too.

## Gotchas

- No music, ever: the creator does not use music in his videos. Sound is the voiceover plus non-tonal sound effects (shaped noise: whooshes, clicks, key taps, scribbles, thuds). Never add a music bed, beat, melodic riser or pitched drone.
- Honesty is a hard gate: `qa.review` gets the reel's `sources`; honest=false is reserved for deception (fake results, invented scenes as real, unshown "I tested", passing off others' work, claims the sources contradict). A mismatched visual is only visual_ok=false.
- The fact-checker must look for newer developments (fixes, reversals) after a source's date; a reel once claimed "no fix yet" when the official changelog had the fix.
- Recorded demos: walkthroughs work anywhere; the IDE (openvscode-server) only on Linux, so test it with the Demo preview workflow. The headless screencast needs `--force-device-scale-factor` or frames come at half resolution. The IDE terminal runs `demos.REEL_SHELL` (commands are queued, typed out and run for real) because keys sent by Playwright never reached the shell. Clips speed up at most 1.5x (`visuals.Clip.MAX_SPEED`) and otherwise cut to their end.
- 3D scenes (`scene3d.py`): three.js loads from jsDelivr, so rendering needs the network. Chromium runs with SwiftShader (software WebGL), about 3 to 4 seconds of render per second of scene. `set_content` skips init scripts, so params and the Poppins fonts are injected into the page HTML. The cache key includes the page source, so editing `PAGE` re-renders. A scene is rendered once at `visuals.Scene.SECONDS` and its frames are stretched to the slide. Logos come from Simple Icons in their brand colour with the name underneath (`scene3d.brand`; a grey logo was rejected as unrecognisable), black ones turned light on the dark theme. Simple Icons contains animal mascots; keep `ANIMAL_LOGOS` up to date (the no-animals rule).
- The voice verifier (`voice.verify`, used by `clean_take`, `say_whole`, `say_checked`, `report`) listens to every take four ways, because each alone missed a real fault: with the script as a hint (names; respelled via `learn`), without it (an everyday word said badly, like "Check" heard as "you correct"; the hint hides these), each burst of sound alone (`islands` + `heard_alone`: a burst with no script word is a stray sound, like the "uhh" Fish invented after a long pause), and the bursts' words together. Faults cost a retake (up to `FINAL_TAKES`); stray sounds left in the best take are cut to silence (`mute`, never into a word) and verified again; a line still unclear is recorded alone and swapped in; a whole voiceover still not clean is recorded once more. `clips.verdict` ('clean' or what is unclear) is printed as "Voice check" in the daily log. The beat between slides is silence added in `split` (`BEAT`), never a Fish `(long-break)`. `test_voice.py --verify` replays the recorded "uhh" (`tests/stray-uhh.wav`) and fails if the verifier misses it or the cut damages a word.
- Writer rules learned from posts with thousands of comments (2026-09-28): the hook promises one concrete result ("in 2 minutes", "one afternoon"), one doubt or tension beat per voiceover ("You might think...", "Most people stop right here"), how-tos show the real steps. Monday is AI how-tos with a real result (Claude, MCP, automations), Sunday "Build X in one afternoon". Topic filter in `generate.SYSTEM` and `carousel.SYSTEM`: no gambling, betting, interest-based lending, adult content or deceptive tools.
- Packages in any code, command, ide file or carousel snippet must exist on npm or PyPI (`generate.package_errors`, used by `visual_errors` and `carousel.check`); the writer is told to use only official packages, because a lookalike package that asks for credentials would hurt viewers.
- Carousels end with "THE TAKEAWAY" (the `takeaway` field, max 8 words) above the question. Few words and lots of space (the creator's ask, 2026-09-28): headings max 5 words, 2 to 3 bullets of max 7 words, enforced by `carousel.check`.
- Carousel layout: every tip slide starts at the same height, centred for the tallest slide (`carousel.centred`), so slides are not half empty and headings do not jump between swipes. Only the automatic last slide asks to save or follow; `carousel.check` rejects a tip slide that does (`CALL_TO_ACTION`), since the first carousel had two.
- Pacing (researched 2026-09-27, the creator found 1.1x speed and long lines rushed): about 2.6 spoken words a second (`VOICE_SPEED` 1.0, 40-55 words), a silent beat between slides that we add ourselves (`voice.BEAT`, never a Fish `(long-break)`), short on-screen labels (hook 5-8, titles 4) and full 2-3 word captions. The screen is the quick layer, voice and captions the full one, and the loop gives slower viewers a second pass; do not raise these limits to fit more in.
- Fish's free model `s2.1-pro-free` ends 2026-11-30: top up and set `FISH_MODEL=s2.1-pro`, or reels quietly fall back to Kokoro. Dropped Fish connections retry, then fall back to Kokoro rather than missing a day.
- Supabase Storage needs the legacy `service_role` JWT. New `sb_secret_` keys are rejected there. The bucket was created for video only; `publish.allow_type` adds a MIME type (the cover JPEG, carousel slides) when an upload is refused.
- The `reels` bucket must be public; `upload` HEADs the public URL and fails loudly if not.
- The upload is deleted in `finally`, even on success, since Instagram has already fetched it.
- The daily workflow uses the `reels-queue` concurrency group and `git pull --rebase` before pushing so `reels.json` commits do not collide. Keep that when adding workflows that write it.
- The trend scan is best effort: fewer than 10 fresh items, any exception, reach below 7, no sources, a reused primary source, a duplicate hook or a fact-check reject all fall back to `generate.today`. Do not let a trends change raise past `publish.main`'s try/except.
- Instagram insights: request one metric per call (`insights.metric`); one unsupported metric fails the whole request.
- YouTube search costs 100 quota units per query; 8 queries a day is under the free 10,000.
- The cover is `out/reel-<id>-cover.jpg` sent as `cover_url` (JPEG, hook inside the centre square); `thumb_offset` (last fully visible hook frame) stays as the fallback.
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
4. For publish/trends changes: `DRY_RUN=true .venv/bin/python publish.py` end to end; for the carousel, `DRY_RUN=true .venv/bin/python carousel.py`; for demos, the Demo preview workflow.
5. Workflow changes: trigger Daily reel with `dry_run` on and check the run log and artifact.
