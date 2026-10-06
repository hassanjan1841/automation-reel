---
name: automation-reel
description: Everything needed to work on the automation-reel project, the pipeline that researches, writes, voices, renders, reviews and posts one Instagram Reel a day (plus a weekly carousel) to @hassanjan.k. Use for any task in this repo - the daily writer and news editor, fact-check and honesty review, slide rendering and visuals (code, diff, terminal, post, chat, quote, screenshot, recorded demos), voiceover and pronunciation, carousels, the weekly learning loop, Instagram publishing, insights, token refresh, GitHub Actions runs, or debugging a failed daily post.
---

# automation-reel

Python 3.12 + ffmpeg + Playwright pipeline, run entirely by GitHub Actions (the creator's machine can be off). No server, no database: `reels.json` records posted reels and `carousels.json` posted carousels; nothing is written ahead of time.

Hard rules from the creator, never relax them: no music (sound effects only); everything halal and honest (no invented results, stories, numbers or quotes, no one else's work as his own, AI-made content is fine but not deceptive); no Reddit; no faces or animals in visuals (initials instead of photos).

## Pipeline at a glance

```
daily-reel.yml, three times a day  ->  publish.py
  slot 1: starts 11:07 UTC, posts at POST_AT_UTC 12:00 (5 PM Pakistan): the day's teaching series (generate.TEACH)
  slot 2: starts 15:07 UTC, posts at 16:00 (9 PM Pakistan): SLOT=2, practical (generate.RELATE: Freelance playbook, Myth vs fact, Ranked)
  slot 3: starts 19:07 UTC, posts at 20:00 (1 AM Pakistan): SLOT=3, generate.slot3_format picks news, trick,
          versus, series or build at random per date (news only with a strong fact-checked story, else another);
          slot 1 teaches (generate.TEACH); only slot 3 runs the trend scan; each slot has its own 3D coin flip
  0. a reel added by hand (posted_at: null) is used as is; otherwise today's reel is written now:
  1. trends.performance()    recent reels' insights (views, skip rate, watch time...) steer what gets written
  2. trends.timely_reel()    scrape -> Claude picks up to 3 (web search, newer developments, no motives) ->
                             validate -> generate.repair -> Claude fact-check (sources + quotes verbatim)
                             pass/fix -> today's reel, pillar "timely"; any failure or reach < 7 -> fall back
  3. else generate.today()   a fresh evergreen reel for today's pillar (generate.PILLARS), labelled with its
                             series and episode (generate.series_label, e.g. "Freelance playbook #4"); both writers
                             read learnings.md (generate.learned) and the weekly test's option for this reel
                             (generate.experiment_today), which validate enforces; the evergreen writer (and the
                             carousel) also get the comment topics (generate.asked), the news writer does not
  3a. generate.pick_hook()   on any freshly written reel (news or evergreen): a second Claude scores the hook and
                             its 3 alternatives against playbook.md (generate.playbook, generate.HOOK_JUDGE) and the
                             winner replaces hook, hook_type and voiceover line 1, the others become `alternatives`
                             (publish.todays_reel; a pick that fails validate, or any failure, keeps the writer's)
  3b. voice.synthesize()      Fish (one continuous take, cut per slide with Whisper word times) or Kokoro
                             (one clip per line); takes are transcribed with Whisper, misheard words get
                             Claude respellings or phonemes, fixes saved to pronounce.json per engine
  4. render.render_reel()    Pillow frames -> ffmpeg -> out/reel-<id>.mp4 (1080x1920, 30fps) + cover jpg:
                             camera motion, captions from the voiceover word times, point visuals from
                             visuals.build() (recorded demos come from demos.record at this point)
  4b. publish.check_visuals()  qa.review() with the reel's sources: Claude reads one frame per slide, plus frame 0
                             and the payoff (qa.first_frame; playbook warnings are printed and saved as reel["review"],
                             never blocking); a rejected hook_visual is dropped and the reel re-rendered.
                             honest=false raises publish.Dishonest: a freshly written reel (news or evergreen)
                             is dropped and a new evergreen reel is written and reviewed instead; a second
                             dishonest verdict posts nothing (a hand-added reel is never replaced);
                             a rejected visual is replaced by the point's next choice or its text
  4c. publish.wait_for_post_time()  sleep until POST_AT_UTC when ready early (not in DRY_RUN)
  5. upload the video and out/reel-<id>-cover.jpg to Supabase bucket "reels" (public) -> Instagram REELS container (cover_url, thumb_offset as fallback) -> poll -> media_publish
  6. delete uploads, write posted_at + media_id, and for the learning loop shown (publish.shown: what each
     slide really showed), slot and seconds (the reel's length); workflow commits reels.json + pronounce.json
     ("Commit queue", `if: always()` once posted, so a later failing step never loses the record)
     (per slot: a real run exits when this slot already posted today, scheduler.posted_slots, unless FORCE_POST)
  7. test_voice.py          pronunciation regression test (text rules only in CI)

learn.yml (daily from 06:00 UTC via scheduler.py, LEARN_DAYS; backup cron 06:30: learn.backup_skip skips a
           scheduled run, GITHUB_EVENT_NAME == 'schedule', on days not in LEARN_DAYS or when today's report exists)
  learn.py           the learning loop (see "Learning loop" below): snapshots -> metrics/, rules.json judged ->
                     learnings.md, the running test (experiments.json), ideas.json, reports/<date>.md + a comment on
                     the week's "Reel reports <year>-W<week>" issue

weekly.yml (Sun 10:00 UTC)
  refresh_token.py   refreshes IG_TOKEN (60-day expiry) and writes it back with gh secret set
  carousel.py        weekly cheat-sheet carousel -> Instagram CAROUSEL, logged in carousels.json
                     (a manual run posts it only with the post_carousel input ticked)

dm.yml (every 15 min)      dm.py            keyword comments -> post's dm_guide as a private reply + public "Sent you a DM" (the dedupe marker)
demo-preview.yml (manual)  demos.py record <spec>   records one demo on GitHub and uploads the mp4

insights.yml (manual)  insights.py 60   per-reel metrics table + cover thumbs artifact

post-video.yml (manual)  post_video.py <video> <caption file> [cover]   posts a ready-made video from extras/ as a Reel
                     (upload, publish, delete upload), recorded in extras.json; never twice without FORCE_POST
                     post_video.py --voice <lines>: records a voiceover (voice.synthesize) to out/voice/ instead, as an artifact
                     queued: an extras.json entry with post_at and media_id null is started by scheduler.due_extra
                     (EXTRA_LEAD before post_at, not past EXTRA_LATE); post_video.py waits up to MAX_WAIT for the minute

scheduler.yml (every 10 min + dispatch)  scheduler.py   starts a dropped Daily reel slot (in its window, not
                     posted, nothing running, at most 2 tries), the day's Learning run (LEARN_DAYS) or a missed
                     Sunday Weekly, or the Sunday Study (study.yml auto, from 08:00; issue runs do not count);
                     a cron-job.org job dispatches it every 10 minutes

study.yml (Sun 08:00 UTC --auto, also started by scheduler.py; issue labelled "study" by the repo owner; or manual
           with videos / search / top / auto)
  study.py --auto    study.auto_picks: this week's study.TOPICS (study.week_topics) + watchlist studies/channels.json
                     (study.channel_outliers; grows from 5x-subscriber outliers, MAX_CHANNELS), kept only if on topic
                     (study.relevant, one Claude call on titles; off-topic channels leave the watchlist; all kept
                     if Claude fails), never a studied source,
                     one per channel; then study.digest (patterns in >= 2 studies, counted in code) -> <date>-digest.md
  study.py --issue | <links> | --search "q" --top N   download (yt-dlp, or issue attachments with GH_TOKEN),
                     measure (study.measure: cuts, beats, blank start, loudness, Whisper words), Claude breakdown
                     (study.breakdown, retried once when a field comes back empty or "placeholder"),
                     studies/<date>-<slug>.md + studies/index.jsonl; out/study.md -> issue comment, studies/ committed

tests.yml (every push except data-only ones: reels.json, metrics/, reports/; and PRs)
                                     test_learn.py   offline tests of the learning loop (requests, pillow, numpy only)
                                     test_study.py   offline tests of study.py (plus ffmpeg)
                                     test_motion.py  renders every animation, the build visual and the closing card
docs-check.yml (every push except reels.json-only ones, and PRs)  docs_check.py   fails if the docs drifted from the code
docs-sync.yml (code push + Sat 09:00) docs_sync.py   Claude fixes the docs, opens a PR from docs-sync
```

Claude is called through the Claude Code CLI (`claude -p ... --json-schema`), billed to the Max plan via `CLAUDE_CODE_OAUTH_TOKEN`, not the API. The writer and hook judge use `generate.MODEL`; `CLAUDE_MODEL` overrides the model in trends, qa, learn, study, carousel review (`carousel.review_once`) and docs_sync (default `claude-sonnet-5`, docs_sync's `generate.MODEL`; an empty value means the default). Only daily-reel.yml (trends, qa) and study.yml pass the repo variable.

## Files

| File | Role | Key entry points |
| --- | --- | --- |
| `post_video.py` | One-off: post a ready-made video as a Reel, recorded in extras.json | `main`, `load`, `record_voice`, `LOG`, `MAX_CAPTION`, `MAX_WAIT` |
| `reels.json` | Record of posted reels; one added by hand with posted_at null is posted next | list of reel objects |
| `publish.py` | Orchestrates one daily post | `main`, `todays_reel`, `research_reel`, `new_entry`, `make_video`, `check_visuals`, `Dishonest`, `shown`, `credits`, `wait_for_post_time`, `upload`, `delete_upload`, `allow_type`, `publish_to_instagram`, `redact`, `paced` |
| `trends.py` | Scrape + news editor + fact-checker | `collect`, `performance`, `insights_of`, `pick`, `quotes_allowed`, `fact_check`, `timely_reel`, `claude`, `SYSTEM`, `CHECK_SYSTEM`, `FEEDS`, `MIN_REACH`, `MAX_AGE` |
| `generate.py` | The writer and the validator; manual backfills | `today`, `generate`, `repair`, `tidy`, `validate`, `pick_hook`, `playbook`, `HOOK_TYPES`, `HOOK_VISUALS`, `MIN_HOOK_SCORE`, `visual_errors`, `cue_errors`, `series_label`, `learned`, `dm_errors`, `DM_PILLARS`, `pillar_errors`, `build_errors`, `BUILD_BLOCKED`, `reveal_errors`, `REVEAL_VISUALS`, `slot`, `pillar_for`, `slot3_format`, `TEACH`, `RELATE`, `EXTRA_FORMATS`, `package_errors`, `three_d_today`, `three_d_note`, `three_d_count`, `strip_3d`, `EXPERIMENTS`, `experiment_today`, `experiment_note`, `experiment_errors`, `vo_words`, `asked`, `add_voiceovers`, `add_cues`, `add_visuals`, `SYSTEM`, `SCHEMA`, `VISUAL_SCHEMA`, `QUOTE_PLATFORMS`, `PILLARS`, `MOTION`, `FLAT_VISUALS`, `motion_errors`, `motion_reel_errors`, `NEW_FIELDS`, `norm`, `similar`, `MODEL`, `HOOK_JUDGE`, `CUE_GAP`, `VO_MIN_WORDS`, `VO_MAX_WORDS`, `THREE_D_CHANCE`, `SCENES_3D`, `SLOT3_FORMATS`, `append` |
| `visuals.py` | Floating cards (shadow, 3D tilt, sheen): code with a hand-drawn circle, diff, typed terminal, post card, POV chat, credited quote, targeted screenshot with cursor click, recorded demo clip, 2D animation (`Motion`) | `build`, `Card`, `Motion`, `MOTION_TYPES`, `Code`, `Diff`, `Terminal`, `Post`, `Quote`, `Chat`, `Screenshot`, `Clip`, `recorded`, `Scene`, `capture`, `code_image`, `sketch_ellipse`, `stroke`, `Build`, `build_shots`, `BUILDS`, `BUILD_BASE`, `BUILD_ROWS` |
| `demos.py` | Screencast recorder: website walkthroughs and live VS Code (openvscode-server, clean env, allowed commands) | `record`, `record_walkthrough`, `record_ide`, `Screencast`, `web_step`, `ide_step`, `IDE_SETTINGS`, `ALLOWED`, `allowed`, `REEL_SHELL` |
| `scene3d.py` | three.js 3D moments rendered frame by frame in headless Chromium (transparent PNG frames for reels, mp4 from the CLI) | `render_scene`, `device_image`, `brand`, `slug_of`, `PAGE`, `ANIMAL_LOGOS` |
| `learn.py` | Learning loop (daily by default): measure, score against the usual, judge rules and the test, new rules, report | `main`, `measure`, `looks`, `slot_of`, `table`, `groups`, `verdict`, `clearly`, `evaluate_rules`, `run_experiment`, `check_new_rules`, `topic_ideas`, `review_openings`, `write_up`, `report`, `views_curve`, `views_life`, `SCORE_MIN_DAYS`, `HARD_RULES`, `RULE_FIELDS`, `MIN_EVIDENCE`, `MIN_AGE_HOURS`, `backup_skip`, `ranked`, `GROUP_FIELDS`, `CLEAR_SKIP`, `CLEAR_WATCHED`, `MAX_RULE_WORDS`, `MAX_NEW_RULES`, `MAX_ACTIVE_RULES`, `RULE_TRIAL_DAYS`, `RULE_GIVE_UP_DAYS`, `EXPERIMENT_MAX_DAYS`, `IDEA_DAYS` |
| `history.py` | The learning loop's files: metrics snapshots, rules, the test, ideas, reports; learnings.md from rules | `snapshots`, `append_snapshots`, `by_post`, `settled`, `snapshot_due`, `value_at`, `DAILY_DAYS`, `rules`, `active`, `save_rules`, `import_learnings`, `experiments`, `save_experiments`, `ideas`, `save_ideas`, `learnings_text`, `key`, `save_report`, `last_report`, `SETTLED_DAYS` |
| `scheduler.py` | Catch-up for dropped GitHub schedules: slot windows, what posted today, start what is due | `main`, `start`, `window`, `slot_of`, `posted_slots`, `due_reel`, `due_weekly`, `started_in_window`, `learn_days`, `due_learn`, `due_study`, `SLOT_STARTS`, `WEEKLY_START`, `STUDY_START`, `LEARN_START`, `MAX_ATTEMPTS`, `due_extra`, `waiting_extras`, `EXTRA_LEAD`, `EXTRA_LATE` |
| `motion.py` | 2D explainer animations: SVG built by our own engine (eases, spring, seeked timeline, glow, one sweep) in headless Chromium, captured as transparent frames like scene3d; the page reports its length, `settle` frame and sound moments | `render_motion`, `prepare`, `tokens`, `words`, `morph_plan`, `PAGE`, `TYPES`, `EXAMPLES`, `MAX_SECONDS`, `FRAMES` |
| `test_motion.py` | morph plan tests and a real render of every template (transparent, sized, settles, sounds, motion) | `MorphPlan`, `Render` |
| `study.py` | Deep study of other creators' videos: download, measure, Claude breakdown into adoptable / not adoptable patterns; saved in studies/ | `sources_in`, `fetch`, `search`, `channel_outliers`, `relevant`, `auto_picks`, `week_topics`, `digest`, `TOPICS`, `probe`, `motion`, `measure`, `breakdown`, `empty_fields`, `report`, `save`, `study`, `studied`, `ours`, `main`, `CHANNELS`, `MAX_CHANNELS` |
| `test_study.py` | Offline tests of study.py on synthetic ffmpeg videos, fake Claude and YouTube | `make_video`, `Measure`, `Breakdown`, `Main` |
| `test_learn.py` | Offline tests of the learning loop and what feeds it, with a six-week simulation | `Sandbox`, `FakeInstagram`, `SimulationTest` |
| `carousel.py` | Weekly carousel: write (Claude), draw 1080x1350 slides, review, post as CAROUSEL with alt_text | `write`, `check`, `draw`, `content_slide`, `centred`, `title_slide`, `end_slide`, `review`, `review_once`, `post`, `SYSTEM`, `SCHEMA`, `LOG`, `CALL_TO_ACTION` |
| `qa.py` | Claude reviews one frame per slide after rendering: ok, visual_ok, honest (with the reel's sources); and frame 0 and the payoff against the playbook | `review`, `frames`, `first_frame`, `SYSTEM`, `SCHEMA` |
| `playbook.md` | The researched rules for hooks, scripts, visuals and sound; read by the writer, the hook judge and qa | data, read by `generate.playbook` |
| `render.py` | Slides, camera motion, captions, finishing, SFX, ffmpeg, cover | `build_slides`, `Camera`, `speech_beats`, `Captions`, `finishing`, `render_frames`, `build_audio`, `sound_kit`, `make_cover`, `render_reel`, `load_reel`, `ensure_fonts`, `Slide`, `THEMES`, `SAFE_TOP`, `SAFE_BOTTOM`, `MARGIN`, `VOICE_LEAD`, `VOICE_TAIL`, `KEYWORD_SIZE`, `HOLD_TICK`, `GLIDE`, `exit_progress` |
| `voice.py` | Fish/Kokoro voiceover + Whisper listen-back | `COMMON_RULES`, `KOKORO_RULES`, `CUE`, `strip_cues`, `lexicon`, `speakable`, `script`, `engine`, `Fish`, `Kokoro`, `synthesize`, `say_whole`, `say_checked`, `clean_take`, `verify`, `islands`, `mute`, `report`, `split`, `learn`, `misheard`, `heard_alone`, `BEAT`, `FINAL_TAKES`, `ask_respellings`, `align`, `by_line`, `transcribe`, `Voiceover`, `hold`, `tempo`, `HOLD`, `FAST_HOOK` |
| `test_voice.py` | Pronunciation and voice-verifier regression test | `SPEAKABLE`, `MISHEARD`, `SENTENCES`, `KNOWN`, `STRAY`, `check_verifier` |
| `pronounce.json` | Learned respellings per engine, word to spoken form | data, written by `voice.learn` |
| `learnings.md` | The active rules, read by the writers (reels, news, carousel) | data, generated from `rules.json` by `history.save_rules` |
| `rules.json`, `experiments.json`, `ideas.json`, `metrics/`, `reports/` | The learning loop's data | data, written by `learn.py` only |
| `carousels.json` | Posted carousels | data, written by `carousel.py` |
| `dm.py` | Comment-to-DM for reels and carousels with dm_keyword/dm_guide | `main`, `posts`, `asks`, `comments`, `answer`, `PRIVATE_REPLY_DAYS`, `PUBLIC_REPLY`, `GUIDE_LIMIT` (the guide is cut to 1000 characters), `DMError` |
| `insights.py` | Account + per-reel metrics | `main`, `metric` |
| `refresh_token.py` | IG token refresh | script |
| `docs_check.py` | Docs vs code drift check, stdlib only | `check`, `main`, `file_table` |
| `docs_sync.py` | Claude proposes doc edits, only doc files are changed | `main`, `ask_claude`, `apply`, `default_base`, `CONTENT`, `MODEL` |
| `.claude/hooks/docs_guard.py` | Stop hook, blocks once when docs look stale | `main` |

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # needs ffmpeg on PATH
.venv/bin/python generate.py --check     # validate every reel; exit 1 on any error or duplicate hook
.venv/bin/python render.py <id>          # out/reel-<id>.mp4, no voice, so no captions or visuals
.venv/bin/python render.py --fonts       # download fonts only
.venv/bin/python voice.py <id> [voice]   # out/reel-<id>-<voice>.mp4 with voiceover (listen-back check on)
.venv/bin/python test_learn.py          # learning loop, offline (-v lists every test)
.venv/bin/python history.py             # what the learning loop has stored
.venv/bin/python test_study.py          # study.py, offline (needs ffmpeg)
.venv/bin/python study.py <file or link> # study a video: studies/<date>-<slug>.md (needs claude CLI; yt-dlp for links)
.venv/bin/python study.py --auto         # the Sunday study: finds its own videos (YOUTUBE_API_KEY), then the digest
.venv/bin/python test_voice.py          # pronunciation rules; add --audio to speak and transcribe every test sentence
.venv/bin/python test_voice.py --verify # the voice verifier still catches and cuts the recorded "uhh" (Whisper, no voice calls)
.venv/bin/python scene3d.py '<json>' 980 620 6   # render one 3D scene to out/scenes/
.venv/bin/python generate.py --voiceover  # Claude writes voiceovers for unposted reels missing one
.venv/bin/python generate.py --cues       # add delivery cues to queued voiceovers (--redo: every queued one), keeping every word
.venv/bin/python generate.py --visuals    # pick visuals for queued reels that have none
.venv/bin/python generate.py --force      # queue 14 reels by hand (posted before any freshly written reel)
.venv/bin/python qa.py <id>              # render reel <id> with its voice and print Claude's frame review
.venv/bin/python motion.py <type> [light|dark]   # render an animation's built-in example to out/motion-<type>.mp4
.venv/bin/python demos.py record '<json>' [w h]  # record one walkthrough/ide demo to out/clips/
.venv/bin/python learn.py                # one run of the learning loop (IG_TOKEN, claude CLI)
.venv/bin/python scheduler.py --dry      # what the scheduler would start now (gh CLI)
.venv/bin/python trends.py               # list scraped trend candidates
.venv/bin/python trends.py --pick        # also ask Claude to pick/write (prints only, saves nothing; needs claude CLI)
DRY_RUN=true .venv/bin/python publish.py # full daily path, render only, posts nothing
DRY_RUN=true .venv/bin/python carousel.py # write, draw and review the carousel, posts nothing
DRY_RUN=true .venv/bin/python dm.py      # print the DMs it would send; dm.py --check only checks the token
IG_TOKEN=... .venv/bin/python insights.py 20
python3 docs_check.py                    # docs match the code? no dependencies needed
python3 docs_sync.py                     # let Claude fix stale docs locally (needs claude CLI; --base REF, --force)
```

First run downloads Poppins and JetBrains Mono into `fonts/`, the Kokoro model into `models/` and Whisper `small.en` into `models/whisper/` (all gitignored). Output goes to `out/` (gitignored).

## Reel schema

```jsonc
{
  "id": 31,                         // next integer; never reuse
  "pillar": "devtip",               // ai|devtip|relatable|freelance|concept|saas|timely, slot 3: trick|versus|series (older reels: take, productivity)
  "series": "Dev mistake",          // evergreen reels: the day's series; "episode": its number
  "style": "light",                 // light|dark, alternates with the last posted reel (publish.new_entry)
  "kicker": "Dev tip",              // 1-3 words, <= 24 chars (not checked with a series); "<series> #<episode>" on
                                    // freshly written evergreen reels (not news or hand-added reels)
  "payoff": "The exact thing the viewer gets", // written first; the points are its steps (playbook.md)
  "hook": "Three to six *words*",   // a phrase on screen; voiceover line 1 says the full sentence
  "hook_type": "mistake",           // problem|before_after|shortcut|mistake|test|news (generate.HOOK_TYPES)
  "hook_visual": {"type": "diff", ...}, // code|diff|screenshot|morph|stepper|build under the hook, complete on frame 0 (HOOK_VISUALS)
  "alternatives": [{"hook": "...", "spoken": "[cue] ...", "hook_type": "problem"}], // 3; generate.pick_hook
  "review": {"first_frame": {"ok": true, "problem": ""}, "payoff": {...}}, // set by publish.check_visuals
  "hook_word": "RLS",               // older reels only, 3D days: one word of the hook as 3D text (not with hook_visual)
  "points": [                       // exactly 3
    { "title": "Max three words", "body": "Max eight words, no asterisks.",
      "visual": [ { "type": "code", "language": "ts", "title": "user.ts", "code": "...", "highlight": [2] } ] }
  ],                                // visual: optional, 1-3 choices best first: code, diff (before/after), terminal,
                                    // quote (real post: author, handle, platform, url, exact text), screenshot
                                    // (url + find), walkthrough (url + steps), ide (files, setup, steps); 2D
                                    // animations: stepper, flow, morph, git, eventloop, structure, sequence, states,
                                    // race, xray, memory, outputmap, kinetic, inspect, variants, wall, drawn, dots, board, blueprint, command, palette (generate.MOTION, generate.motion_errors);
                                    // build (html + 2-4 CSS stages, generate.build_errors, visuals.Build); on 3D
                                    // days also diagram (nodes, edges, flow), device (laptop + code, phone +
                                    // screenshot), bars (real numbers + source), logos (Simple Icons slugs);
                                    // tweet and chat are no longer allowed -- see generate.SYSTEM and generate.visual_errors
  "cta": "A short question with one *highlighted* word?",
  "dm_keyword": "MCP", "dm_guide": "...", // optional comment-to-DM: capitals 3-10, guide 150-900 chars (generate.dm_errors)
  "reveal": 3,                      // optional: the point whose first visual lands a result (generate.REVEAL_VISUALS)
                                    // while the voice holds a silent beat (voice.hold, publish.paced)
  "caption": "Line one.\nLine two.\nA question to end on? 👇",
  "hashtags": ["#nextjs", "..."],   // 3-5, unique, ^#[A-Za-z0-9_]+$ (older posted reels have 8-12)
  "voiceover": ["..."],             // 5 spoken lines (hook, 3 points, cta); required on unposted reels
  "sources": ["https://..."],       // timely reels only, primary source first; used to block reposting a story
  "posted_at": null,                // ISO timestamp, set by publish.py
  "media_id": null,                 // Instagram media id, set by publish.py
  "shown": ["word", "code", "text", "diagram", "text"], // set by publish.py when posted (publish.shown): what each
                                    // slide really showed (hook, points, cta), after fallbacks and review swaps
  "slot": 1, "seconds": 21.6,       // set when posted: the day's slot and the reel's length (for share watched)
  "test": {"name": "hook_style", "arm": "question"}  // the weekly test option it was written under (generate.EXPERIMENTS)
}
```

Rules enforced by `generate.validate` (the single source of truth, also run on Claude output):
- Hook 3-6 words with at least one balanced `*highlight*`. Titles max 3 words (a label; the voice carries the detail). Bodies max 8 (shown only without a visual), no `*`.
- Kicker 1-3 words and at most 24 characters, unless the reel has a `series` (then any non-empty label).
- Playbook fields (unposted reels; `generate.NEW_FIELDS` exempts posted ones in `--check`): `payoff` 10-220 characters, `hook_type` in `HOOK_TYPES`, `hook_visual` one of `HOOK_VISUALS` (passing `visual_errors`), 3 `alternatives` (3-6 word hook with a highlight, a `hook_type` in `HOOK_TYPES`, spoken line starting with a cue and opening with a high-energy one (not low-energy or flat), at most 14 words, `CUE_GAP` between cues, and swapped in for line 1 it keeps the voiceover at 40-55 words), no `hook_word` with a `hook_visual`, and no tweet or chat visuals (invented posts and conversations).
- CTA ends with `?` (unless the reel has a `dm_keyword`: then it is the offer, e.g. "Comment *MCP* for the setup") and has exactly one highlight.
- No emojis on slide text; emojis only in the caption.
- Caption 2-3 non-empty lines, the first naming the topic in searchable words; last line contains `?` (or the `dm_keyword`) and ends with 👇 (`generate.tidy` adds a missing 👇 to a question).
- Hooks must be unique after lowercasing and stripping non-alphanumerics (`generate.norm`; checked by `generate.generate`, `trends.timely_reel` and `--check`, not by validate).
- Voiceover: exactly 5 non-empty lines, 40 to 55 words in total, line 1 max 14 words, no symbols, `*` or emojis, points' lines no more than 60% similar to their slides and the hook and closing lines no more than 90% (`generate.similar`), and delivery cues per `generate.cue_errors`: every line starts with a `[cue]`, a fresh cue at least every 10 spoken words, a high-energy cue on the hook, at most one low-energy cue, at least 5 different cues. `--check` skips any error mentioning voiceover (dm_errors' too), cue or hashtags, hook, title and body length errors and `NEW_FIELDS` errors on posted reels, which predate those rules.
- Visuals per `generate.visual_errors`: 1-3 choices; packages named in code, commands or files must exist (`package_errors`); code max 12x40 with a language and `highlight` line numbers inside the code, diff before/after max 12x40 and different, terminal 1-6 commands of 40, quote with `author`, a known platform (`QUOTE_PLATFORMS`), an https url and the exact text (10-220 chars), walkthrough an https url and 1-4 steps (scroll, scroll_to, click, hover, type or wait; no open/run/save), ide `files` and 1-8 steps with allowed commands only (`demos.allowed`) and max 12 typed lines of 60, screenshot an https url and `find` of 3-80 chars. Animations per `generate.motion_errors` (one per reel, with a flat backup: `motion_reel_errors`). Tweet and chat are rejected by validate (no invented posts or conversations). 3D: diagram 2-5 nodes (labels max 12) with edges and a 1-8 hop flow over node ids, device phone only with a screenshot, bars 2-5 (labels max 10) with an https `source`, logos 1-4 `[a-z0-9]+` slugs that resolve via `scene3d.brand`, none in `scene3d.ANIMAL_LOGOS`, `hook_word` one word of the hook, at most 2 3D moments per reel (`generate.three_d_count`).

Content rules (in `generate.SYSTEM`): evergreen reels have no news, versions, prices or dates; no invented stories or stats; the honesty rules (no fake results, invented scenes framed as POV, "I tested" only with a real run, no one else's work as his own, hooks never promise more than the reel delivers). The voiceover adds to the slides (the why, an example, what goes wrong) instead of reading them, sounds like a developer talking to a friend, writes numbers as spoken, and its last line asks for a comment without saying "comment below" or "follow". Timely reels drop the evergreen rule but every claim must be backed by a fetched source.

Pillar and series come from `generate.pillar_for`: reel 1 rotates the teaching series by weekday (`TEACH`: AI tool in 30s, Dev mistake, Explained, Build smart), reel 2 the practical ones (`RELATE`: Freelance playbook, Myth vs fact, Freelance playbook, Ranked; 2026-10-01 they replaced the invented client-chat and POV skits, which Instagram barely showed), reel 3 its day's format (`EXTRA_FORMATS`: Quick trick, X vs Y, Next.js from zero, Build it live, or a news reel); the beginner series is given its earlier episodes to continue from. 3D is allowed on a random share of days (`generate.three_d_today`, seeded by the date, plus the slot for slots 2 and 3, so reruns agree, `THREE_D_CHANCE` default 0.5, `THREE_D=on|off` forces it); both writers are told via `three_d_note`, and `publish.todays_reel` strips 3D (`generate.strip_3d`) on other days. Real-post quotes are allowed at most once in six days (`trends.quotes_allowed`), and the caption credits every quoted author (`publish.credits`).

## Common tasks

**Add a reel by hand**: append with the next `id`, `posted_at`/`media_id` null, then `generate.py --voiceover` and `--cues` if you did not write the voiceover, `generate.py --check` and `voice.py <id>`. The first unposted entry is posted at the next daily run instead of a freshly written reel. A dry run saves `out/reel-<id>.json` beside its video, which can be added this way to post exactly what was reviewed.

**A word is mispronounced**: the listen-back check usually fixes it on its own and records it in `pronounce.json` (keyed by engine, applied before the rules). If a learned respelling sounds wrong, edit or delete it there. For patterns (numbers, acronyms, symbols) add a `(regex, respelling)` tuple to `voice.COMMON_RULES` (every engine) or `voice.KOKORO_RULES`; order matters, specific terms go before the generic acronym/plural rules. Add a case to `test_voice.SPEAKABLE` or `SENTENCES`, then run `test_voice.py --audio`.

**Change the look**: `render.THEMES` for colors, layout constants at the top of `render.py`. Keep text inside the Instagram safe zone (`SAFE_TOP`, `SAFE_BOTTOM`, `MARGIN`). With a Fish voiceover each slide lasts exactly as long as its part of the one continuous take; without a voice, timing is driven by word count (3-6s per slide, 15-25s total).

**Change the voice**: repo variable `VOICE` (a Fish voice id, a Kokoro voice, or `none` for SFX only, and then no captions or visuals: `build_slides` adds them only with the voice's word times); `VOICE_ENGINE` forces `fish` or `kokoro`. Fish needs the secret `FISH_API_KEY`; with `VOICE_ENGINE` unset it falls back to Kokoro without it (`VOICE_ENGINE=fish` with no key raises `KeyError`). `FISH_MODEL` defaults to `s2.1-pro-free` (free until 2026-11-30). `VOICE_PITCH` exists but shifted voices sound robotic; pick a different voice instead.

**Skip the news, always evergreen**: repo variable `TRENDING=off`. **Post time**: `POST_AT_UTC` (HH:MM, default 12:00) sets slot 1 only; slots 2 and 3 post at 16:00 and 20:00, set in `daily-reel.yml`. Move the crons in `daily-reel.yml` with it so each job still starts about an hour early, and `scheduler.SLOT_STARTS` with the crons.

**Pause**: disable the Daily reel workflow. The Scheduler keeps trying to start it inside slot windows; `scheduler.start` prints the refused dispatch and the other checks (Weekly, Learning, Study) still run. Keep Weekly on, or the IG token expires after 60 days.

**Run in CI by hand**: Actions > Daily reel > Run workflow. `dry_run` defaults to true; the MP4 is uploaded as an artifact either way.

## Secrets and variables

Secrets: `IG_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `YOUTUBE_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `FISH_API_KEY`, `GH_PAT` (fine-grained, this repo, Secrets read/write).
Variables/env: `POST_AT_UTC`, `SLOT`, `REEL_FORMAT` (local only, no workflow passes it: forces slot 3's format: news, trick, versus, series or build), `FORCE_POST` (a real run skips when this slot's reel already went out today, UTC, unless true), `VOICE`, `VOICE_ENGINE`, `VOICE_PITCH`, `VOICE_SPEED`, `FISH_MODEL`, `TRENDING`, `THREE_D`, `THREE_D_CHANCE`, `EXPERIMENT` (`off` or a test's name), `LEARN_DAYS` (empty/`daily` or e.g. `sun,wed`), `DRY_RUN`, `GRAPH_VERSION` (default `v25.0`, also when empty; trends.performance follows it too), `CLAUDE_MODEL` (empty means the default; see above for who reads it), `GITHUB_EVENT_NAME` (set by Actions; `learn.backup_skip` acts only on `schedule`), and for study.py `GH_TOKEN` (fetches issue attachments) and `ISSUE_BODY` (the links, with `--issue`). daily-reel.yml passes `VOICE_PITCH`, `CLAUDE_MODEL` and `GRAPH_VERSION`; learn.yml passes `LEARN_DAYS`.
Never print a token; `publish.redact` and the `replace(token, '***')` calls exist for that. Keep new error paths redacted too.

## Gotchas

- No music, ever: the creator does not use music in his videos. Sound is the voiceover plus non-tonal sound effects (shaped noise: whooshes, clicks, key taps, scribbles, thuds). Never add a music bed, beat, melodic riser or pitched drone.
- Honesty is a hard gate: `qa.review` gets the reel's `sources`; honest=false is reserved for deception (fake results, invented scenes as real, unshown "I tested", passing off others' work, claims the sources contradict). A mismatched visual is only visual_ok=false.
- The fact-checker must look for newer developments (fixes, reversals) after a source's date; a reel once claimed "no fix yet" when the official changelog had the fix.
- Recorded demos: walkthroughs work anywhere; the IDE (openvscode-server) only on Linux (Docker on macOS), so test it with the Demo preview workflow. The headless screencast needs `--force-device-scale-factor` or frames come at half resolution. The IDE terminal runs `demos.REEL_SHELL` (commands are queued, typed out and run for real) because keys sent by Playwright never reached the shell. Clips speed up at most 1.5x (`visuals.Clip.MAX_SPEED`) and otherwise cut to their end.
- 3D scenes (`scene3d.py`): three.js loads from jsDelivr, so rendering needs the network. Chromium runs with SwiftShader (software WebGL), about 3 to 4 seconds of render per second of scene. `set_content` skips init scripts, so params and the Poppins fonts are injected into the page HTML. The cache key includes the page source, so editing `PAGE` re-renders. A scene is rendered once at `visuals.Scene.SECONDS` and its frames are stretched to the slide. Logos come from Simple Icons in their brand colour with the name underneath (`scene3d.brand`; a grey logo was rejected as unrecognisable), black ones turned light on the dark theme and very light ones darkened on the light theme. Simple Icons contains animal mascots; keep `ANIMAL_LOGOS` up to date (the no-animals rule).
- The voice verifier (`voice.verify`, used by `clean_take` (and so `say_checked`), `say_whole`, `report`) listens to every take four ways, because each alone missed a real fault: with the script as a hint (names; respelled via `learn`), without it (an everyday word said badly, like "Check" heard as "you correct"; the hint hides these), each burst of sound alone (`islands` + `heard_alone`: a burst with no script word is a stray sound, like the "uhh" Fish invented after a long pause), and the bursts' words together. Faults cost a retake (up to `FINAL_TAKES`); stray sounds left in the best take are cut to silence (`mute`, never into a word) and verified again; a line still unclear is recorded alone and swapped in; a whole voiceover still not clean is recorded once more. `clips.verdict` ('clean' or what is unclear) is printed as "Voice check" in the daily log. The beat between slides is silence added in `split` (`BEAT`), never a Fish `(long-break)`; `say_whole` joins the lines with a short `(break)`. `test_voice.py --verify` replays the recorded "uhh" (`tests/stray-uhh.wav`) and fails if the verifier misses it or the cut damages a word.
- Writer rules learned from posts with thousands of comments (2026-09-28): the hook promises one concrete result ("in 2 minutes", "one afternoon"), one doubt or tension beat per voiceover ("You might think...", "Most people stop right here"), how-tos show the real steps. Slot 1 rotates `TEACH` by weekday % 4: Mon/Fri AI how-tos with a real result (Claude, MCP, automations), Tue/Sat Dev mistake, Wed/Sun Explained, Thu "Build X in one afternoon". Topic filter in `generate.SYSTEM` and `carousel.SYSTEM`: no gambling, betting, interest-based lending, adult content or deceptive tools.
- Packages in any code, command, ide file or carousel snippet must exist on npm or PyPI (`generate.package_errors`, used by `visual_errors` and `carousel.check`); the writer is told to use only official packages, because a lookalike package that asks for credentials would hurt viewers.
- Comment-to-DM (2026-09-28, learned from posts with more comments than likes; widened 2026-10-01): every format in `generate.DM_PILLARS` (AI, dev mistake, build smart, freelance playbook, trick, versus, beginner, build it live; not myth, ranked or explained), and every carousel, carry `dm_keyword`; `generate.pillar_errors` (run by `generate.generate` and its repair, which know the day's pillar) enforces it, and the offer names a concrete freebie ("Comment CODE for the code"). Carry `dm_keyword` (capitals, 3 to 10) and `dm_guide` (150 to 900 characters, the whole promised guide). `generate.dm_errors` makes the cta, caption and last voiceover line offer it, and checks the guide's packages; `qa.review` fails honesty if the reel promises more than the guide holds. The CTA slide then shows the keyword big in the hook's style (`render.KEYWORD_SIZE`, bold accent with a marker stroke) and says "I'll send it to your DMs". `dm.py` never stores state: our public reply under a comment marks it as done; it sends at most `dm.GUIDE_LIMIT` (1000) characters of the guide.
- GitHub drops scheduled runs (2026-09-28: the Daily reel's crons fired twice in three days, none on the 28th).
  `scheduler.py` fills the gaps: each slot owns a window from its start to the next slot's start, and a missing
  slot is started once its window opens if nothing is running (at most `MAX_ATTEMPTS` tries); a passed window is
  skipped, never stacked. `publish.main` skips a slot already posted today (`scheduler.posted_slots`), so any
  number of triggers is safe. Scheduler runs on a cron too; an outside trigger dispatching scheduler.yml is what
  makes timing reliable (README, "Reliable timing"). Keep `SLOT_STARTS` in step with daily-reel.yml's crons.
- 2D animations (2026-10-01, `motion.py`): written by the writer like any visual (`generate.MOTION`, fields in
  `VISUAL_SCHEMA`, limits in `generate.motion_errors`), at most one per reel and always with a flat backup choice
  after it (`generate.motion_reel_errors`, `FLAT_VISUALS`); morph and stepper may be a `hook_visual`. Our own JS engine,
  no CDN or library: each template builds all its SVG up front, the timeline is seeked per frame
  (`window.renderAt`), and the layout is fitted inside a 36 px margin so soft shadows are never cut at the box edge.
  `visuals.Motion` plays at the animation's own pace and holds its last frame; only a slide shorter than the
  animation speeds it up (`speed`), and its `sounds` follow. The page reports `settle` (layout complete) so a hook
  proof is drawn from there. Test with `test_motion.py` (real renders; `E2E_CHROMIUM` in the sandbox) and look at
  `python motion.py <type>` output; frames are cached in `out/motion/` by spec, theme accent and ink, size and page source. Text and
  lines drawn straight on the reel's background use the theme's `ink`/`muted` (`C.ink`, `C.mute`, `C.guide`), not
  the dark panels' `C.text`/`C.dim`, or they vanish on the light theme (2026-10-01: sequence labels, git ids and the
  race were unreadable there; `test_motion.py` renders the race on light and checks every template reads only
  fields its prepared spec has, after the race showed "Source: undefined").
- Frame 0 (2026-10-01, playbook.md): the hook's words are revealed before frame 0 (`build_slides`; its click at 0 is audible
  only without a voice: with a voice the clicks are muted and the voice starts at `VOICE_LEAD` 0.25s) and its `hook_visual` is drawn from its `settle` time (`visuals.Card.settle`; a Code card
  once all lines are in, so only the circle still draws) with `Slide.ready`/`Slide.lead`; its entrance sounds are
  skipped. The camera's frame-0 zoom-out is 3% (10% cropped the hook's edges). A terminal is not allowed as a hook
  visual because it types itself out from empty. `learn.looks` adds `hook_type` and `opening` (proof or text),
  both in `GROUP_FIELDS` and `RULE_FIELDS` and named as evidence fields in `learn.SYSTEM`.
- Study-driven formats (2026-10-01, from three studied reels in `studies/`, 14k to 48k likes; the two with thousands of
  comments both offered a file or tool for a keyword):
  - `visuals.Build`: the real page (`build_shots`: Chromium with scripts off and every request blocked, cached in
    `out/builds/`) above the CSS typed in stage by stage; each stage's preview swaps in with a pop, the stage pace
    shrinks to fit a short slide (`Build.step`), and its settle shows the plain page and its HTML, so it may be a
    hook proof. Stages are padded to the same lines and width so the code size never jumps, and the panel title
    names the step (`style.css, step 2 of 3`): the first real review rejected both builds when the panel showed
    only the newest stage, so `qa.SYSTEM` says to judge a build by its page. It ends on `Build.closing`: a shorter
    window on the finished page above every step's CSS together (`FINAL` seconds; skipped when the slide is too
    short, `final_at`), which is why all stages together are max 8 lines. `generate.build_errors`
    keeps html and stages to 4 lines of 40 and rejects anything that could load or run (`BUILD_BLOCKED`).
  - `reveal` (`generate.reveal_errors`): `publish.paced` calls `voice.hold`, which adds `voice.HOLD` seconds of
    silence before that point's line and shifts its word times; `Voiceover.holds` reaches `Slide.hold`, and
    `render.build_audio` plays soft ticks every `HOLD_TICK` in the gap and a pop as the voice returns.
  - `hook_pace` test (`generate.EXPERIMENTS`, next after `hook_style`): "dense" line 1 of 12 to 14 words, played
    `voice.FAST_HOOK` times faster by `voice.tempo` (ffmpeg atempo, same pitch); "relaxed" at most 10 words.
  - Slide changes glide: `render.Camera` no longer punches on a slide start, only on spoken sentences, and a
    slide's exit runs `GLIDE` seconds into the next one (`render.exit_progress`), so no frame between them is empty.
  - `wall` (motion.py): perspective grid of tiles (own projection, tilted ~57 degrees) revealed by a pull back, then
    counters (`stats`, real numbers only) over a dark scrim; SETTLE is when the grid is revealed.
  - `command` and `palette` (motion.py): `command` is a tilted terminal card (scale 1.15 to 1, skew and squash easing to
    flat) that types, shrinks to a bar and grows the result panel (SETTLE when the rows are in); `palette` scrolls
    `items` one line per 0.17 s, slows over its last 3 steps and lands on `pick` (validated to be past the first 3
    items so it scrolls). `chips` are optional; both only show real commands, files and options.
  - `kinetic` (motion.py): a takeaway in big type word by word; the marker under the key word draws after the
    layout settles. The page loads Poppins 700 before layout, or text measures with a fallback font and overlaps.
  - `inspect` and `variants` (motion.py): selection boxes with label pills on code lines, and one card swapping
    between real alternatives under a light sweep; both settle once the code or card is in.
  - `drawn` and `dots` (motion.py): `drawn` computes Poppins Bold glyph outlines with fontTools in `prepare()`
    (`glyph_outlines`) and the page draws each outline, fills it, then drops its anchor dots; `dots` rasterises a
    word with Pillow into a dot grid (`dot_raster`) that appears with seeded delays, then a mono caption scramble.
  - `board` and `blueprint` (motion.py): a typed goal with task cards moving To do, Doing, Done and a ring; outline
    parts that draw in with callouts whose text resolves from a seeded scramble. `board` captions use Instrument Serif
    (OFL), fetched by `render.ensure_fonts` and embedded by `motion.font_css`.
  - `learn.looks` adds `reveal` (held beat / no beat) and `offer` (freebie / question), in `GROUP_FIELDS` and
    `RULE_FIELDS`.
- 3D tracking (2026-09-28): `learn.looks` tags each measured reel with its visual types, `hook_word` ("3D word" or
  "text only") and `three_d` ("3D" or "flat"). It reads `shown`, because the queue keeps rejected choices and
  `visuals.build` falls back to text when a scene fails, so a first choice is not proof it was on screen; reels posted
  before `shown` existed fall back to their first choices and `hook_word`. Decide whether to raise `THREE_D_CHANCE`
  or the 2-moment limit from these numbers, not before.
- Beats (2026-09-28, something changes every 1 to 2 seconds): `render.Camera` punches on each spoken sentence and after pauses over 0.35s (`render.speech_beats`, from the voice's word times, at least 1.2s apart; a timer only without a voice) and pushes into each point's visual on slides of at least 3s (`Camera.focus`: from 40% of the slide, ease out 0.8s before its end; a wide visual gets a smaller push so it never runs off the frame), so a point is show, focus, release. `qa.frames` grabs each slide 0.9s before its end, after every visual has finished animating and while the push still holds; at 60% it caught diffs mid-change and rejected them as garbled. `build_audio` uses the same camera, so the air sounds follow the beats.
- Carousels end with "THE TAKEAWAY" (the `takeaway` field, max 8 words) above the question. Few words and lots of space (the creator's ask, 2026-09-28): headings max 5 words, 2 to 3 bullets of max 7 words, enforced by `carousel.check`.
- Carousel layout: every tip slide starts at the same height, centred for the tallest slide (`carousel.centred`), so slides are not half empty and headings do not jump between swipes. Only the automatic last slide asks to save or follow; `carousel.check` rejects a tip slide that does (`CALL_TO_ACTION`), since the first carousel had two.
- Pacing (researched 2026-09-27, the creator found 1.1x speed and long lines rushed): about 2.6 spoken words a second (`VOICE_SPEED` 1.0, 40-55 words), a silent beat between slides that we add ourselves (`voice.BEAT`, never a Fish `(long-break)`), short on-screen labels (hook 3-6, titles 3; the creator found the earlier text too big and wordy, 2026-10-01) and captions of up to 3 words at 56 px. The screen is the quick layer, voice and captions the full one, and the loop gives slower viewers a second pass; do not raise these limits to fit more in.
- Fish's free model `s2.1-pro-free` ends 2026-11-30: top up and set `FISH_MODEL=s2.1-pro`, or reels quietly fall back to Kokoro. Dropped Fish connections retry, then fall back to Kokoro rather than missing a day.
- Supabase Storage needs the legacy `service_role` JWT. New `sb_secret_` keys are rejected there. The bucket was created for video only; `publish.allow_type` adds a MIME type (the cover JPEG, carousel slides) when an upload is refused.
- The `reels` bucket must be public; `upload` HEADs the public URL and fails loudly if not.
- The upload is deleted in `finally`, even on success, since Instagram has already fetched it.
- The daily workflow uses the `reels-queue` concurrency group and `git pull --rebase` before pushing so `reels.json` commits do not collide. Keep that when adding workflows that write it.
- The trend scan is best effort: fewer than 10 fresh items, any exception, reach below 7, no sources, a reused primary source, a duplicate hook or a fact-check reject all fall back to `generate.today`. Do not let a trends change raise past `publish.research_reel`'s try/except.
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

What `docs_check.py` enforces: every script has a docstring; every script and workflow is named in README and this skill; every env var, secret and repo variable the code reads is named in both; every `module.name` and `.py` path in the docs exists; every documented `python <script> --flag` is handled by that script; every cron time appears in README; every entry point in this skill's Files table is defined in that file. Extend it when a new kind of drift bites.

Automation around it:
- Stop hook `.claude/hooks/docs_guard.py` (registered in `.claude/settings.json`) blocks once per distinct change set when `docs_check.py` fails or code changed without doc changes. It remembers the last flagged state in `.git/docs-guard-ack`.
- `docs-sync.yml` runs `docs_sync.py`: diff of code since the docs were last committed (`--base REF` to choose; ignoring the bots' data files in `docs_sync.CONTENT`, studies/ included, and the docs themselves) plus `docs_check.py` output goes to Claude with read-only tools (Read/Glob/Grep). Claude returns `{file, old, new}` edits as structured output; `apply` accepts only the three doc files and each `old` must match exactly once (an empty `old` creates a missing doc file). With no code diff and `docs_check.py` passing it does nothing unless `--force`. One retry reports failed edits back. `docs_check.py` must pass, then a PR is opened from `docs-sync`. Claude never gets write tools because Claude Code protects `.claude/` from edits in non-interactive runs. Needs "Allow GitHub Actions to create and approve pull requests" in repo settings.

## Learning loop

`learn.py` runs daily by default (learn.yml, started by scheduler.py); `history.py` holds its files. Rules of thumb when changing it:
- The loop runs daily by default (the creator's choice, 2026-09-29: daily until results are proven, then e.g.
  `LEARN_DAYS=sun,wed`). It is safe to run any day: rule trials and tests are judged by dates and reel counts, new
  rules are capped at 3 per 7 days, and yesterday's report is passed to the write-up.
- Data lives in plain files in the repo, no database (the creator's choice, 2026-09-28): `metrics/<month>.jsonl` is
  append-only, one line per post per snapshot; `history.snapshot_due` reads a post every day up to age `DAILY_DAYS` + 1
  (8 days, to see how long it keeps getting views: `learn.views_curve`), then weekly until a snapshot at
  `history.SETTLED_DAYS` (28) exists, then never again. A post is first read after `MIN_AGE_HOURS` (about a day)
  and scored only from `SCORE_MIN_DAYS` (2). Only the learning job writes these files (never the daily runs), so
  commits never collide. Move to Supabase Postgres only for a live dashboard, a second account or hourly numbers; the jsonl rows
  map one-to-one onto a table.
- Reels are scored against the account's usual (median): `skip_vs_usual` (lower is better) and `watched_vs_usual`
  (share of the reel watched, from `seconds`). Views only at the same age (`views_7d`). `learn.clearly` decides:
  2 skip points (`CLEAR_SKIP`), or 5% of the reel watched (`CLEAR_WATCHED`) when skip is not 2 points the other way.
- Rules (`rules.json`): trial -> kept or retired. `learn.evaluate_rules` compares reels since the rule with the 4
  weeks before it, after 2 weeks; no clear effect by 4 weeks retires it (a short prompt is worth more), and so does never having
  `MIN_EVIDENCE` reels on each side by 6 weeks (3 x `RULE_TRIAL_DAYS`). Before/after
  is confounded by anything else that changed then (other rules, the test, the news cycle); the weekly test is the
  clean comparison, which is why its winner goes straight to kept. New rules from Claude must cite groups of
  `MIN_EVIDENCE` (5) reels that clearly differ (`learn.check_new_rules`), in fields the writer controls
  (`learn.RULE_FIELDS`: not the slot; a real run once proposed "move the 8pm post" as a writer rule, which belongs in
  the report's decision), and never match `learn.HARD_RULES`; at most 30 words each (`MAX_RULE_WORDS`), 3 new a week and 10 active. `learnings.md` is generated; edit `rules.json`, not it.
- The weekly test (`generate.EXPERIMENTS`): each option is `(instruction, check, error)`; the arm is random per date
  and slot (`generate.experiment_today`), the writers are told (`experiment_note`), the reel carries `test` and
  `generate.validate` enforces it (so `repair` fixes a miss). Only add tests the writer controls, code can check,
  and that never bend the honesty rules. `learn.run_experiment` ends a test when each option has 5 measured reels
  (or after 3 weeks), turns a clear winner into a kept rule, and starts the next untried test.
- Comment topics go to `ideas.json` as topics only (no usernames, no quotes); the writers are told never to say a
  named person asked. The openings review downloads covers (`thumbnail_url`) and gives them to Claude with Read.
- With fewer than 2 scored reels a run saves nothing (no rules, test or report).
- Claude failures never lose the week: numbers, rule verdicts and the test still save, and the report says the
  write-up was unavailable. Test with `test_learn.py`; the `verify` skill has the full procedure.

## Before calling a change done

1. `.venv/bin/python generate.py --check` passes.
2. `python3 docs_check.py` passes.
3. `.venv/bin/python test_learn.py` and `test_study.py` pass (learning loop, writer tests, publish records; study.py), and `test_motion.py` for motion changes (CI runs it). For anything bigger,
   follow the `verify` skill (`.claude/skills/verify/SKILL.md`).
4. For render/voice changes: render one light and one dark reel and look at the MP4 (safe zone, overflow, timing, audio). Voice changes also need `test_voice.py --audio` to pass.
5. For publish/trends changes: `DRY_RUN=true .venv/bin/python publish.py` end to end; for the carousel, `DRY_RUN=true .venv/bin/python carousel.py`; for demos, the Demo preview workflow.
6. Workflow changes: trigger Daily reel with `dry_run` on and check the run log and artifact.
