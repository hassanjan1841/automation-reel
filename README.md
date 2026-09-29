# automation-reel

Posts one Instagram Reel a day to @hassanjan.k with no manual work.

- **Daily, three reels** (`daily-reel.yml`, starts 11:07 UTC, 15:07 UTC and 19:07 UTC, about an hour before each post): reel 1 posts at 12:00 UTC = 5 PM Pakistan and teaches (AI tool in 30s, Dev mistake, Explained, Build smart); reel 2 posts at 16:00 UTC = 9 PM Pakistan and is relatable (Client vs Me most days, POV, rankings); reel 3 posts at 20:00 UTC = 1 AM Pakistan, 4 PM New York, and is picked at random each day from AI news (only a strong, fact-checked story), a one-line trick, X vs Y, or the beginner series "Next.js from zero". Nothing is written ahead of time. About an hour before posting it researches today: it reads your recent reels' insights (views, reach, skip rate, watch time, saves, shares) and scans what is trending (Hacker News, GitHub Trending, dev.to, Lobsters, YouTube via the Data API, AI and dev blog feeds). If a timely story is strong enough (7/10) and survives an independent fact-check, that becomes today's reel with its `sources`; otherwise Claude writes a fresh evergreen reel for today's pillar, steered by what held your viewers. Then it records the voiceover (Fish Audio, checked by listening back with Whisper), renders a 1080x1920 MP4 with camera motion, synced captions and real visuals plus a cover image, has Claude review the frames (bad visuals are swapped out), waits until 12:00 UTC, uploads the video and its cover to the public Supabase bucket `reels`, publishes through the Instagram API with that cover, deletes the upload, and commits `reels.json` (the record of what was posted, including `shown`: what each slide really showed) plus `pronounce.json` if the voice learned a new fix. A reel you add by hand with `posted_at: null` is posted instead of writing a new one. Every run saves the exact reel beside the video (`out/reel-<id>.json`, in the run's artifact), so a dry run you like can be added to `reels.json` and posted as is.
- **Learning** (`learn.yml`, every day from 06:00 UTC = 11 AM Pakistan, started by the Scheduler; a backup cron at 06:30 UTC): `learn.py` runs the learning loop (see [Learning](#learning)): it measures every post, judges the writer's rules and the running test, writes the rules the daily writer follows into `learnings.md`, and posts the day's report as a comment on that week's GitHub issue "Reel reports <year>-W<week>" (GitHub emails you each one). Repo variable `LEARN_DAYS` picks the days: empty or `daily` for every day (the default while there is little to go on), or e.g. `sun,wed` for twice a week once results are proven.
- **Weekly** (`weekly.yml`, Sundays 10:00 UTC): refreshes the Instagram token so it never expires, then `carousel.py` writes, draws, reviews and posts the weekly cheat-sheet carousel (6 to 8 slides, alt text on every image), recorded in `carousels.json`.
- **Comment DMs** (`dm.yml`, every 15 minutes): `dm.py` answers keyword comments. How-to reels and every carousel end with an offer like "Comment MCP for the setup"; whoever comments the keyword gets the post's `dm_guide` as a private reply (Instagram's official way to message a commenter, allowed for 7 days) and a public "Sent you a DM" under their comment, which is also how it knows not to send twice. Run it by hand with `check` to confirm the token may read comments and send messages. The token needs the `instagram_business_manage_comments` and `instagram_business_manage_messages` permissions.
- **Demo preview** (`demo-preview.yml`, run by hand): records one walkthrough or IDE demo on GitHub's machine and attaches the video, to try a demo before it goes into a reel.
- **Insights** (`insights.yml`, run by hand): prints account stats and per-reel views, reach, skip rate, watch time, likes, comments, saves and shares, and attaches each reel's cover as an artifact named `thumbs`, sorted by skip rate.
- **Scheduler** (`scheduler.yml`, every 10 minutes): `scheduler.py` starts any Daily reel slot, the day's Learning run or the Sunday Weekly run that GitHub's own schedule dropped. See [Reliable timing](#reliable-timing).
- **Tests** (`tests.yml` on every push and pull request): `python test_learn.py`, the offline tests of the learning loop.
- **Docs** (`docs-check.yml` on every push, `docs-sync.yml` on code pushes to `main` and Saturdays 09:00 UTC): keeps this README, `CLAUDE.md` and the project skill in step with the code. See [Docs](#docs).

## Files

| File | What it does |
| --- | --- |
| `reels.json` | The record of every posted reel. A reel added by hand with `posted_at: null` is posted next instead of a freshly written one. |
| `render.py` | Draws the slides and sound effects, encodes with ffmpeg. A camera layer moves the content like a filmed shot (zoom-in reveal at frame 0, breathing and drift, a zoom punch at every slide change and about every 2.5s, a shake on the hook and the call to action, motion blur on fast moves); entrances overshoot and settle; numbers in the hook count up; highlighted words get a hand-drawn marker stroke. With a voiceover, captions pop in word by word on a frosted-glass box near the bottom, the spoken word on a glowing accent highlight. Every frame gets a soft vignette and film grain, and the video ends by easing back into its first frame so replays loop. Sound effects only, all shaped noise, never music. Also writes a cover image (`out/reel-<id>-cover.jpg`) with the hook inside the grid-safe centre square. `python render.py 3` writes `out/reel-3.mp4` without voice. |
| `visuals.py` | The real visuals on point slides, each a floating card with a two-layer shadow, a 3D tilt entrance and a light sheen: a syntax-highlighted code window (the key line gets circled by hand), a before/after diff (red, then green), a terminal typed at a human pace with key clicks, a post card in your name, a Client / Me chat with typing dots, or a live screenshot (Playwright, phone width) scrolled to the text in `find`, spotlit, clicked by a gliding cursor and circled by hand. A visual that cannot be made falls back to the slide's body text. |
| `demos.py` | Real screen recordings: website walkthroughs (scroll, click, type with a visible cursor; floating widgets hidden; emails and keys blurred) and live coding in a real VS Code (openvscode-server) typing code and running commands in its terminal, with no secrets in its environment and only allowed commands. Recorded from Chrome's own screencast at full resolution. `python demos.py record '<json>' 980 620`. |
| `scene3d.py` | 3D moments, drawn with three.js in headless Chromium frame by frame and floating straight on the reel background with soft shadows: a tech diagram (blocks with a glowing packet travelling along the flow), the hook word in extruded 3D, a laptop or phone showing code or a screenshot, rising bars for real sourced numbers, and spinning tool logos in their brand colours with their names (Simple Icons; animal or mascot logos are blocked). Objects only, never people or animals. 3D is allowed on a random half of days (`THREE_D_CHANCE`, fixed per date), at most 2 moments per reel; `THREE_D=on` or `off` forces it. `python scene3d.py '<json>' 980 620 6` renders one to `out/scenes/`. |
| `learn.py` | The learning loop (daily by default), see [Learning](#learning). |
| `history.py` | Where the learning loop keeps its data, as files in the repo: `metrics/`, `rules.json`, `experiments.json`, `ideas.json`, `reports/`, and `learnings.md` generated from the rules. `python history.py` prints what is stored. |
| `scheduler.py` | Starts any reel slot or Sunday Weekly run that GitHub's schedule dropped; safe to run any number of times. `python scheduler.py --dry` prints the decision. See [Reliable timing](#reliable-timing). |
| `test_learn.py` | Offline tests of the learning loop, including a six-week simulation against a fake Instagram. `python test_learn.py`; CI runs it on every push. |
| `carousel.py` | The weekly cheat-sheet carousel: Claude writes it, slides are drawn in the reel style (code slides in the editor window), reviewed for readability and honesty, posted as an Instagram carousel with alt text. `DRY_RUN=true python carousel.py` renders to `out/carousel/`. |
| `qa.py` | Visual review after rendering: Claude looks at one frame per slide and rejects visuals that are irrelevant, unreadable or broken (cookie banner, error page). `publish.py` then renders the point's next visual choice, or its text. `python qa.py 3` renders reel 3 and prints the review. |
| `publish.py` | Researches and writes today's reel (or takes one added by hand), renders, reviews, waits for `POST_AT_UTC`, uploads and publishes. `DRY_RUN=true` renders only and does not wait. |
| `generate.py` | Writes reels with Claude via `claude -p` (`generate.today` writes today's evergreen reel); the validator. `--force` adds 14 to `reels.json` by hand, `--check` validates it, `--voiceover` writes voiceovers for unposted reels that have none, `--cues` adds delivery cues to them, `--visuals` picks visuals for queued reels that have none. |
| `voice.py` | Voiceover with Fish Audio (voice ThatMob, recorded in one continuous take and cut per slide) or, without `FISH_API_KEY`, Kokoro (free, local). Every take is verified four ways with Whisper (with and without the script as a hint, burst by burst, and for stray sounds like an invented "uhh"); unclear takes are retaken, stray sounds cut out, unclear lines recorded again alone, and the result is printed as "Voice check" in the log; a misheard word gets respellings or exact phonemes from Claude until one comes back right, and that fix is saved to `pronounce.json`. `COMMON_RULES` and `KOKORO_RULES` hold the hand-written rules (numbers, prices, SaaS, Next.js). `python voice.py 3` previews reel 3 with voice. |
| `pronounce.json` | Respellings the listen-back check learned, e.g. `"Supabase": "Soo pa base"`. Edit or delete an entry if it sounds wrong. |
| `test_voice.py` | Pronunciation regression test. `python test_voice.py` checks the text rules, `--verify` replays a recorded stray "uhh" and checks the voice verifier catches and removes it, `--audio` also speaks every test sentence and listens back. |
| `trends.py` | The trend scan and editor. `python trends.py` lists what it scraped, `--pick` shows what Claude would post. Set repo variable `TRENDING=off` to skip the news and always write an evergreen reel. |
| `refresh_token.py` | Refreshes `IG_TOKEN` and saves it back as a repo secret. |
| `dm.py` | Comment-to-DM: sends each keyword commenter the post's guide as a private reply and answers publicly. `python dm.py --check` tests the token's permissions; `DRY_RUN=true` prints instead of sending. |
| `insights.py` | Account and per-reel metrics from the Instagram API. `python insights.py 20` covers the last 20 posts and saves covers to `out/thumbs`. |
| `docs_check.py` | Fails when the docs no longer match the code. No dependencies. |
| `docs_sync.py` | Has Claude update the docs to match the code. `--force` reviews them even if nothing changed. |
| `CLAUDE.md`, `.claude/` | Instructions, the `automation-reel` skill and the docs Stop hook for Claude Code sessions. |

## Add a reel by hand

Append an object to `reels.json` with the next `id`, `posted_at: null` and `media_id: null`:

```json
{
  "id": 15,
  "pillar": "devtip",
  "style": "light",
  "kicker": "Dev tip",
  "hook": "Six to twelve words with the *key word* highlighted",
  "points": [
    { "title": "Max eight words", "body": "Max sixteen words, no asterisks.",
      "visual": [
        { "type": "screenshot", "url": "https://example.com/pricing", "find": "Exact text on the page" },
        { "type": "code", "language": "ts", "title": "user.ts", "code": "max 12 lines of 40 characters", "highlight": [1] }
      ] },
    // other visual types: { "type": "diff", "language": "ts", "before": "...", "after": "..." },
    //   { "type": "terminal", "commands": ["npm i zod"] }, { "type": "tweet", "text": "..." },
    //   { "type": "chat", "messages": [{ "from": "client", "text": "..." }, { "from": "me", "text": "..." }] }
    { "title": "...", "body": "..." },
    { "title": "...", "body": "..." }
  ],
  "cta": "A short question with one *highlighted* word?",
  "caption": "Line one.\nLine two.\nA question to end on? 👇",
  "hashtags": ["#nextjs", "#react", "#typescript", "#webdev", "#coding", "#programming", "#developer", "#devtips"],
  "voiceover": [
    "Spoken hook, max fourteen words.",
    "Point one said differently, with the why or an example.",
    "Point two, flowing on from the last line.",
    "Point three.",
    "A natural question that invites a comment."
  ],
  "posted_at": null,
  "media_id": null
}
```

The voiceover is heard while the slides are read, so it must not repeat the slide text: 40 to 55 words at about 2.6 words a second, with a longer beat between slides, no symbols, numbers written as spoken. Every line starts with a delivery cue like `[grinning, punchy]`, with a fresh cue at least every 10 spoken words so the voice does not fade; `(break)` is a short beat. Cues are not spoken. `python generate.py --cues` adds cues to voiceovers that have none. Leave it out and run `python generate.py --voiceover` to have Claude write it. Then run `python generate.py --check` and `python voice.py 15` to preview it. It is posted at the next daily run instead of a freshly written reel.

## Learning

Every day (or on the days in `LEARN_DAYS`) `learn.py` works out what holds viewers and feeds it back to the writers:

1. **Measure.** Each post's Instagram numbers (views, reach, skip rate, watch time, saves, shares, likes, comments, and follows and profile visits where Instagram offers them) are read every day for a post's first week, then once a week until it is 4 weeks old, then never again. The daily readings show how long each reel keeps getting views (views at day 1, 3 and 7, and the share of a week's views that came after day 1). Keyword comments are counted per post. Snapshots are appended to `metrics/<year>-<month>.jsonl`.
2. **Score.** Every reel is compared with the account's usual (the median): skip rate, and the share of the reel watched (watch time divided by the reel's length). Views are compared at 7 days old. A reel is scored only from 2 days old, when its numbers have settled. Reels are grouped by series, pillar, visual, 3D, slot (5 PM, 9 PM or 1 AM Pakistan) and test option.
3. **Judge the rules.** The writer's rules live in `rules.json` as *trial*, *kept* (proven) or *retired*. After 2 weeks a rule on trial is compared with the 4 weeks of reels before it: kept if it helped, retired if it hurt or showed no clear effect by 4 weeks. `learnings.md`, which the writers read, is generated from the active rules.
4. **The running test.** One thing at a time is decided by chance for each reel: first a question hook vs a statement, then a short vs a long voiceover, then a number in the hook or not (`generate.EXPERIMENTS`). The writer is told and the reel is checked for it. Once each option has 5 measured reels the test ends; a clear winner becomes a proven rule and the next test starts. `experiments.json` holds the running one and the results. Set repo variable `EXPERIMENT=off` to stop testing.
5. **New rules.** Claude proposes rules from the numbers (at most 3 new a week, however often the loop runs); one is only added when groups of at least 5 reels behind it clearly differ in something the writer controls (posting times go to the decision instead), and never if it touches your hard rules (music, faces, animals, Reddit, invented content).
6. **Comments and covers.** Topics people asked for in comments go to `ideas.json` (topics only, no names or quotes) and both writers see them. Claude also looks at the covers of the best and worst openings.
7. **Report.** Saved to `reports/<date>.md` and posted as a comment on the week's issue: the last 7 days vs the 7 before, how long reels keep getting views, best and worst openings, carousels, the test, rule changes, what people asked for, a summary, and one decision for you to approve (settings like `THREE_D_CHANCE` are never changed on their own).

Only the learning job writes these files, so it never collides with the daily posts committing `reels.json`. Each posted reel records what the loop needs: `shown` (what each slide really showed), `slot`, `seconds` and `test`.

Run it by hand any time: Actions → **Weekly** → **Run workflow**. A manual run refreshes the token and runs the learning loop; it posts the carousel only if you tick `post_carousel`.

## Reliable timing

GitHub drops many scheduled runs when it is busy: in the first days the Daily reel's three crons fired only twice in three days, and a 15-minute cron fired about three times in half a day. So posting never depends on one cron firing:

- Each reel slot owns a window: slot 1 from 11:07 UTC, slot 2 from 15:07, slot 3 from 19:07 until midnight. `scheduler.py` (run by **Scheduler**) looks at `reels.json` and the running workflows; if the current slot has not posted today and nothing is running, it starts the Daily reel for that slot. That run waits for the post time, or posts at once when late. A slot whose window has passed is skipped rather than stacked on the next one, and a slot that failed twice in its window is left for you to look at.
- From 06:00 UTC it starts **Learning** once on each day in `LEARN_DAYS`, and on Sundays from 10:00 UTC it starts **Weekly** if it has not run that day.
- `publish.py` never posts the same slot twice in a day, however many times it is started, so all of this is safe to repeat.

The Scheduler itself runs on a GitHub cron too, so for timing that never slips, have an outside service start it every 10 to 15 minutes: a `POST` to `https://api.github.com/repos/hassanjan1841/automation-reel/actions/workflows/scheduler.yml/dispatches` with body `{"ref":"main"}`, headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json` and `Content-Type: application/json` (without it GitHub answers 415 and nothing starts), and a fine-grained token that has **Actions: read and write** on this repo. A success is HTTP 204. This runs from a cron-job.org job every 10 minutes (set up 2026-09-29); if reels stop starting on time, check that job's history first.

## Pause it

GitHub → Actions → **Daily reel** and **Scheduler** → `...` → **Disable workflow**. Enable them again to resume. Keep **Weekly** on: if it stays off for more than 60 days the Instagram token expires and has to be generated again.

## Voice

The voice is Fish Audio's ThatMob (`s2.1-pro-free`, free until 2026-11-30; set `FISH_MODEL=s2.1-pro` after that). It needs the secret `FISH_API_KEY`; without it the voiceover falls back to Kokoro. `VOICE_ENGINE` forces `fish` or `kokoro`, `VOICE` picks another Fish voice id or Kokoro voice (or `none` for sound effects only), and `VOICE_PITCH` shifts it in semitones (avoid it: shifted voices sound robotic). Every reel carries its own `voiceover` (5 lines, one per slide) that adds to the slides instead of reading them; reels without one fall back to reading the slide text. `python voice.py 3 am_fenrir` writes `out/reel-3-am_fenrir.mp4` to compare voices.

## Run it by hand

Actions → **Daily reel** → **Run workflow**. `dry_run` is on by default; the rendered MP4 is attached to the run as an artifact either way.

## Secrets

`IG_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `YOUTUBE_API_KEY` (Google Cloud, restricted to YouTube Data API v3), `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, valid 1 year), `GH_PAT` (fine-grained, this repo only, **Secrets: read and write**; used to save the refreshed token).

Optional repo variables or env: `POST_AT_UTC` (reel 1's post time, default `12:00`; reel 2 posts at `16:00`, reel 3 at `20:00`), `SLOT` (`2` or `3` for the later reels, set by their crons; a manual run has a `slot` choice), `REEL_FORMAT` (forces reel 3's format: `news`, `trick`, `versus` or `series`), `FORCE_POST` (`true` posts even if this slot's reel already went out today; normally a second run for the same slot does nothing), `VOICE`, `VOICE_ENGINE`, `VOICE_PITCH`, `VOICE_SPEED` (default `1.0`; `1.1` felt rushed), `FISH_MODEL`, `TRENDING` (see above), `THREE_D` (`on` or `off` forces 3D for the day; default random; a manual Daily reel run also has a `three_d` choice), `THREE_D_CHANCE` (share of days 3D is allowed, default `0.5`), `LEARN_DAYS` (days the learning loop runs: empty or `daily`, or e.g. `sun,wed`), `EXPERIMENT` (`off` stops the weekly test; a test's name forces it, for trying it out), `CLAUDE_MODEL` (model for the trend editor, fact-check and docs sync; defaults to `MODEL` in `generate.py`), `GRAPH_VERSION` (Instagram Graph API version, default `v25.0`).

## Local setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # plus ffmpeg on PATH
.venv/bin/python render.py 1
```

## Docs

Three docs, one job each: this README for running the project, `CLAUDE.md` for Claude Code sessions, and `.claude/skills/automation-reel/SKILL.md` for working on the code. Each script's docstring is the source of truth for its usage and env vars.

- `python3 docs_check.py` checks that every script, workflow, env var, schedule, `module.name` and documented flag in the docs still matches the code.
- **Docs check** runs it on every push and pull request.
- **Docs sync** runs `docs_sync.py` after code pushes to `main` and every Saturday. If the code moved on, Claude updates the docs and the workflow opens (or updates) a pull request from the `docs-sync` branch. It never pushes to `main` itself, and it can only change the three doc files.
- In Claude Code, a Stop hook blocks once when code changed without doc updates, so docs are fixed in the same change.

Docs sync needs **Settings → Actions → General → Allow GitHub Actions to create and approve pull requests** turned on.
