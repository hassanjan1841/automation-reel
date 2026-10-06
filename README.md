# automation-reel

Posts one Instagram Reel a day to @hassanjan.k with no manual work.

- **Daily, three reels** (`daily-reel.yml`, starts 11:07 UTC, 15:07 UTC and 19:07 UTC, about an hour before each post): reel 1 posts at 12:00 UTC = 5 PM Pakistan and teaches (AI tool in 30s, Dev mistake, Explained, Build smart); reel 2 posts at 16:00 UTC = 9 PM Pakistan and is a practical one (Freelance playbook most days: a copyable client message, clause or price; Myth vs fact; Ranked); reel 3 posts at 20:00 UTC = 1 AM Pakistan, 4 PM New York (3 PM in winter), and is picked at random each day from AI news (only a strong, fact-checked story), a one-line trick, X vs Y, the beginner series "Next.js from zero", or "Build it live" (a small UI piece built from plain HTML to finished on screen). Nothing is written ahead of time. About an hour before posting it researches today: it reads your recent reels' insights (views, reach, skip rate, watch time, saves, shares). Only for reel 3 on a news day it also scans what is trending (Hacker News, GitHub Trending, dev.to, Lobsters, YouTube via the Data API, AI and dev blog feeds); if a timely story scores 7/10 or more and survives an independent fact-check, that becomes reel 3 with its `sources`, otherwise reel 3 uses another format. Every other reel is a fresh evergreen reel Claude writes for today's pillar, steered by what held your viewers. Every reel follows `playbook.md` (see [What makes a reel work](#what-makes-a-reel-work)): one useful thing, a short hook with its proof on screen from the first frame, and the strongest of four hooks picked by a second Claude. Then it records the voiceover (Fish Audio, checked by listening back with Whisper), renders a 1080x1920 MP4 with camera motion, synced captions and real visuals plus a cover image, has Claude review the frames (bad visuals are swapped out; a dishonest claim stops the post, see [Honesty stop](#honesty-stop)), waits until the slot's post time (12:00, 16:00 or 20:00 UTC), uploads the video and its cover to the public Supabase bucket `reels`, publishes through the Instagram API with that cover, deletes the upload, and commits `reels.json` (the record of what was posted, including `shown`: what each slide really showed) plus `pronounce.json` if the voice learned a new fix. After posting it runs `python test_voice.py` (the pronunciation test); the commit still happens if that test fails, so a posted slot is never posted twice. A reel you add by hand with `posted_at: null` is posted instead of writing a new one. Every run saves the exact reel beside the video (`out/reel-<id>.json`, in the run's artifact), so a dry run you like can be added to `reels.json` and posted as is.
- **Learning** (`learn.yml`, every day from 06:00 UTC = 11 AM Pakistan, started by the Scheduler; a backup cron at 06:30 UTC): `learn.py` runs the learning loop (see [Learning](#learning)): it measures every post, judges the writer's rules and the running test, writes the rules the daily writer follows into `learnings.md`, and posts the day's report as a comment on that week's GitHub issue "Reel reports <year>-W<week>" (GitHub emails you each one). Repo variable `LEARN_DAYS` picks the days: empty or `daily` for every day (the default while there is little to go on), or e.g. `sun,wed` for twice a week once results are proven. The 06:30 backup cron skips days not in `LEARN_DAYS` and days that already have their report in `reports/` (`learn.py` reads `GITHUB_EVENT_NAME` to tell the backup cron apart); a run started by hand or by the Scheduler always runs.
- **Weekly** (`weekly.yml`, Sundays 10:00 UTC): refreshes the Instagram token so it never expires, then `carousel.py` writes, draws, reviews and posts the weekly cheat-sheet carousel (6 to 8 slides, alt text on every image), recorded in `carousels.json`.
- **Comment DMs** (`dm.yml`, every 15 minutes): `dm.py` answers keyword comments. How-to reels and every carousel end with an offer like "Comment MCP for the setup"; whoever comments the keyword gets the post's `dm_guide` as a private reply (Instagram's official way to message a commenter, allowed for 7 days) and a public "Sent you a DM" under their comment, which is also how it knows not to send twice. Run it by hand with `check` to confirm the token may read comments and send messages. The token needs the `instagram_business_manage_comments` and `instagram_business_manage_messages` permissions.
- **Demo preview** (`demo-preview.yml`, run by hand): records one walkthrough or IDE demo on GitHub's machine and attaches the video, to try a demo before it goes into a reel.
- **Post a video** (`post-video.yml`, run by hand): `post_video.py` posts a ready-made video from the repo (a one-off made elsewhere, kept in `extras/` with its caption and cover) as a Reel: it uploads it, publishes it with the caption and cover, deletes the upload and records it in `extras.json`. It writes, voices, renders and reviews nothing, and never posts the same video twice unless `FORCE_POST` is `true`. Start it with `dry_run` ticked first to check the files. To post at a set time, add an entry to `extras.json` with `video`, `caption_file`, `cover`, `post_at` (time with its offset, e.g. `2026-10-05T18:00:00+05:00`) and `media_id: null`: the Scheduler starts the run 15 minutes before and `post_video.py` waits for the minute. With a `voiceover` lines file it posts nothing and instead records the lines with the daily reels' voice (checked by listening back) as an artifact, `out/voice/` with one WAV per line and `voice.json` (word timings for captions), to mix into the video before posting: `python post_video.py --voice extras/chai-reel-voice.txt`.
- **Insights** (`insights.yml`, run by hand): prints account stats and per-reel views, reach, skip rate, watch time, likes, comments, saves and shares, and attaches each reel's cover as an artifact named `thumbs`, sorted by skip rate.
- **Scheduler** (`scheduler.yml`, every 10 minutes): `scheduler.py` starts any Daily reel slot, the day's Learning run, or the Sunday Study or Weekly run that GitHub's own schedule dropped. It also starts a ready-made video queued in `extras.json` when its `post_at` comes. See [Reliable timing](#reliable-timing).
- **Study videos** (`study.yml`, Sundays 08:00 UTC on its own, when you label an issue `study`, or run by hand): `study.py` studies other creators' short videos deeply to learn what holds viewers; on Sundays it finds what to study itself. See [Study other creators](#study-other-creators).
- **Tests** (`tests.yml` on every push and pull request, except pushes that only touch `reels.json`, `metrics/` or `reports/`): `python test_learn.py`, the offline tests of the learning loop, `python test_study.py`, the offline tests of the video study (with ffmpeg), and `python test_motion.py`, which renders every animation template for real in headless Chromium.
- **Docs** (`docs-check.yml` on every push except `reels.json`-only ones, `docs-sync.yml` on code pushes to `main` and Saturdays 09:00 UTC): keeps this README, `CLAUDE.md` and the project skill in step with the code. See [Docs](#docs).

## Files

| File | What it does |
| --- | --- |
| `reels.json` | The record of every posted reel. A reel added by hand with `posted_at: null` is posted next instead of a freshly written one. |
| `render.py` | Draws the slides and sound effects, encodes with ffmpeg. A camera layer moves the content like a filmed shot (zoom-out reveal at frame 0, breathing and drift, a zoom punch on every spoken sentence (about every 2.6 s without a voice) while slide changes glide, a shake on the hook and the call to action, motion blur on fast moves); entrances overshoot and settle; numbers in the hook count up; highlighted words get a hand-drawn marker stroke. With a voiceover, captions appear up to 3 words at a time on a frosted-glass box near the bottom, the spoken word on a glowing accent highlight. Every frame gets a soft vignette and film grain, and the video ends by easing back into its first frame so replays loop. Sound effects only, all shaped noise, never music. Also writes a cover image (`out/reel-<id>-cover.jpg`) with the hook inside the grid-safe centre square. `python render.py 3` writes `out/reel-3.mp4` without voice. |
| `visuals.py` | The real visuals on point slides, each a floating card with a two-layer shadow, a 3D tilt entrance and a light sheen: a syntax-highlighted code window (the key line gets circled by hand), a before/after diff (red, then green), a terminal typed at a human pace with key clicks, a quote of a real public post (verbatim, credited on screen and in the caption, at most one quote reel a week), or a live screenshot (Playwright, phone width) scrolled to the text in `find`, spotlit, clicked by a gliding cursor and circled by hand. A visual that cannot be made falls back to the slide's body text. The old post card and Client / Me chat are only drawn for old queued reels; new reels cannot use them. |
| `demos.py` | Real screen recordings: website walkthroughs (scroll, click, type with a visible cursor; floating widgets hidden; emails and keys blurred) and live coding in a real VS Code (openvscode-server) typing code and running commands in its terminal, with no secrets in its environment and only allowed commands. Recorded from Chrome's own screencast at full resolution. `python demos.py record '<json>' 980 620`. |
| `scene3d.py` | 3D moments, drawn with three.js in headless Chromium frame by frame and floating straight on the reel background with soft shadows: a tech diagram (blocks with a glowing packet travelling along the flow), the hook word in extruded 3D (only for older or hand-added reels without a `hook_visual`), a laptop or phone showing code or a screenshot, rising bars for real sourced numbers, and spinning tool logos in their brand colours with their names (Simple Icons; animal or mascot logos are blocked). Objects only, never people or animals. 3D is allowed on a random half of reels (`THREE_D_CHANCE`, fixed per date and slot), at most 2 moments per reel; `THREE_D=on` or `off` forces it. `python scene3d.py '<json>' 980 620 6` renders one to `out/scenes/`. |
| `learn.py` | The learning loop (daily by default), see [Learning](#learning). |
| `history.py` | Where the learning loop keeps its data, as files in the repo: `metrics/`, `rules.json`, `experiments.json`, `ideas.json`, `reports/`, and `learnings.md` generated from the rules. `python history.py` prints what is stored. |
| `scheduler.py` | Starts any reel slot, Learning, Sunday Study or Sunday Weekly run that GitHub's schedule dropped; safe to run any number of times. `python scheduler.py --dry` prints the decision. See [Reliable timing](#reliable-timing). |
| `study.py` | Deep study of other creators' videos: downloads each one, measures cuts, pace, blank openings, loudness and speech, and has Claude break down what holds viewers and which patterns we could test. Saves `studies/<date>-<title>.md` and `studies/index.jsonl`. `python study.py <file or link>`, `--search "<topic>"`, `--issue`, or `--auto` (the weekly study). |
| `motion.py` | The 2D explainer animations (code stepper, request flow, code morph, git graph, event loop, data structures, sequence diagram, state machine, real-number race, x-ray zoom, memory map, command output to diagram, takeaway in big type, command becoming its result, scrolling option list), drawn by our own engine in headless Chromium and captured frame by frame. `python motion.py <type>` renders an example to `out/motion-<type>.mp4`. |
| `motion.py` | The 2D explainer animations (code stepper, request flow, code morph, git graph, event loop, data structures, sequence diagram, state machine, real-number race, x-ray zoom, memory map, command output to diagram, big-type takeaway, stacked statements, typed quotes), drawn by our own engine in headless Chromium and captured frame by frame. `python motion.py <type>` renders an example to `out/motion-<type>.mp4`. |
| `test_motion.py` | Tests of `motion.py`: the code-morph plan and a real render of every template. CI runs it on every push. `E2E_CHROMIUM=<path>` points it (and `tests/e2e_publish.py`) at another browser. |
| `test_study.py` | Offline tests of `study.py` on synthetic videos made with ffmpeg, with a fake Claude and YouTube. `python test_study.py`; CI runs it on every push. |
| `test_learn.py` | Offline tests of the learning loop, including a six-week simulation against a fake Instagram. `python test_learn.py`; CI runs it on every push. |
| `carousel.py` | The weekly cheat-sheet carousel: Claude writes it, slides are drawn in the reel style (code slides in the editor window), reviewed for readability and honesty, posted as an Instagram carousel with alt text. `DRY_RUN=true python carousel.py` renders to `out/carousel/`. |
| `qa.py` | Visual review after rendering: Claude looks at one frame per slide and rejects visuals that are irrelevant, unreadable or broken (cookie banner, error page). `publish.py` then renders the point's next visual choice, or its text. It also flags dishonest claims, which stop the post (see [Honesty stop](#honesty-stop)). `python qa.py 3` renders reel 3 and prints the review. |
| `publish.py` | Researches and writes today's reel (or takes one added by hand), renders, reviews, waits for `POST_AT_UTC`, uploads and publishes. `DRY_RUN=true` renders only and does not wait. |
| `generate.py` | Writes reels with Claude via `claude -p` (`generate.today` writes today's evergreen reel); the validator. `--force` adds 14 to `reels.json` by hand (one per slot run, so about 5 days; all written for slot 1's series), `--check` validates it, `--voiceover` writes voiceovers for unposted reels that have none, `--cues` adds delivery cues to them (`--cues --redo` re-cues every queued voiceover), `--visuals` picks visuals for queued reels that have none. |
| `voice.py` | Voiceover with Fish Audio (voice ThatMob, recorded in one continuous take and cut per slide) or, without `FISH_API_KEY`, Kokoro (free, local). Every take is verified four ways with Whisper (with and without the script as a hint, burst by burst, and for stray sounds like an invented "uhh"); unclear takes are retaken, stray sounds cut out, unclear lines recorded again alone, and the result is printed as "Voice check" in the log; a misheard word gets respellings or exact phonemes from Claude until one comes back right, and that fix is saved to `pronounce.json`. `COMMON_RULES` and `KOKORO_RULES` hold the hand-written rules (numbers, prices, SaaS, Next.js). `python voice.py 3` previews reel 3 with voice. |
| `pronounce.json` | Respellings the listen-back check learned, e.g. `"Supabase": "Soo pa base"`. Edit or delete an entry if it sounds wrong. |
| `test_voice.py` | Pronunciation regression test. `python test_voice.py` checks the text rules, `--verify` replays a recorded stray "uhh" and checks the voice verifier catches and removes it, `--audio` also speaks every test sentence and listens back. |
| `trends.py` | The trend scan and editor. `python trends.py` lists what it scraped, `--pick` shows what Claude would post. Set repo variable `TRENDING=off` to skip the news and always write an evergreen reel. |
| `refresh_token.py` | Refreshes `IG_TOKEN` and saves it back as a repo secret. |
| `dm.py` | Comment-to-DM: sends each keyword commenter the post's guide as a private reply and answers publicly. `python dm.py --check` tests the token's permissions; `DRY_RUN=true` prints instead of sending. |
| `post_video.py` | Posts a ready-made video as a Reel outside the daily pipeline and records it in `extras.json`. `DRY_RUN=true python post_video.py extras/chai-reel.mp4 extras/chai-reel.txt extras/chai-reel-cover.jpg` checks the files and prints the caption. |
| `extras.json` | The record of every video posted with `post_video.py`. |
| `insights.py` | Account and per-reel metrics from the Instagram API. `python insights.py 20` covers the last 20 posts and saves covers to `out/thumbs`. |
| `docs_check.py` | Fails when the docs no longer match the code. No dependencies. |
| `docs_sync.py` | Has Claude update the docs to match the code. `--force` reviews them even if nothing changed. |
| `playbook.md` | The researched reel rules, read by the writer, the hook judge and the frame review. See [What makes a reel work](#what-makes-a-reel-work). |
| `carousels.json` | The record of every posted carousel. |
| `studies/` | What the video study saved: one report per video, `index.jsonl`, digests and the watched channels. |
| `tests/` | End-to-end runs and the mutation check used by the verify skill: `tests/e2e_learn.py`, `tests/e2e_publish.py`, `tests/e2e_writer.py`, `tests/mutants.py`, and `tests/stray-uhh.wav` for `test_voice.py --verify`. |
| `requirements.txt` | Python packages. |
| `CLAUDE.md`, `.claude/` | Instructions, the `automation-reel` skill and the docs Stop hook for Claude Code sessions. |

## Add a reel by hand

Append an object to `reels.json` with the next `id`, `posted_at: null` and `media_id: null`. This example passes `generate.validate` (a test checks it):

```json
{
  "id": 15,
  "pillar": "devtip",
  "style": "light",
  "kicker": "Dev tip",
  "hook": "Your *await* is missing",
  "hook_type": "mistake",
  "hook_visual": {"type": "diff", "language": "ts", "before": "const user = getUser()\nconsole.log(user.name)", "after": "const user = await getUser()\nconsole.log(user.name)"},
  "payoff": "Put await before an async call so you get its result, not a pending promise.",
  "alternatives": [
    {"hook": "This logs a *Promise*", "spoken": "[fired up] You wanted the user, but you logged a promise.", "hook_type": "problem"},
    {"hook": "One word fixes *this*", "spoken": "[grinning, punchy] One missing word is why your data never shows up.", "hook_type": "shortcut"},
    {"hook": "Before and *after* await", "spoken": "[fired up] Same line of code, one word added, now it works.", "hook_type": "before_after"}
  ],
  "points": [
    { "title": "The silent bug", "body": "It logs a promise, not the data.",
      "visual": [
        {"type": "code", "language": "ts", "title": "user.ts", "code": "const user = getUser()\nconsole.log(user)\n// Promise { <pending> }", "highlight": [1]}
      ] },
    { "title": "Add the *await*", "body": "Await the call inside an async function.",
      "visual": [
        {"type": "diff", "language": "ts", "before": "function load() {\n  const user = getUser()\n}", "after": "async function load() {\n  const user = await getUser()\n}"}
      ] },
    { "title": "Catch the error", "body": "Wrap it in try and catch.",
      "visual": [
        {"type": "code", "language": "ts", "title": "load.ts", "code": "try {\n  const user = await getUser()\n} catch (err) {\n  console.error(err)\n}", "highlight": [3]}
      ] }
  ],
  "cta": "Ever lost an hour to *this*?",
  "caption": "A missing await logs a promise, not your data.\nAwait the call and wrap it in try and catch.\nEver lost an hour to this? 👇",
  "hashtags": ["#javascript", "#typescript", "#webdev", "#coding"],
  "voiceover": [
    "[fired up] Your code runs fine, but the data is never there.",
    "[curious] Without await you are holding a promise. (break) [deadpan] Not the actual result.",
    "[grinning, punchy] Put await in front of the call, (break) [emphasis] then mark the function async.",
    "[serious] And if the request fails, (break) [knowing] the catch block tells you why.",
    "[warm, inviting] Has this one cost you an afternoon too?"
  ],
  "posted_at": null,
  "media_id": null
}
```

The rules `generate.py --check` enforces include: a 3 to 6 word hook with a `*highlight*`, titles of at most 3 words, bodies of at most 8, a `payoff` (10 to 220 characters), a `hook_type` (problem, before_after, shortcut, mistake, test or news), a `hook_visual` (code, diff, screenshot, morph or stepper), 3 `alternatives`, a question `cta` with one highlight, a 2 to 3 line caption ending in a question and 👇, and 3 to 5 hashtags. Each point's `visual` is a list of up to 3 choices, best first: `code`, `diff`, `terminal`, `screenshot`, `walkthrough`, `ide`, `quote`, `diagram`, `device`, `bars`, `logos`, or one of the 15 `motion.py` animations. `tweet` and `chat` are no longer allowed.

The voiceover is heard while the slides are read, so it must not repeat the slide text: 40 to 55 words at about 2.6 words a second, with a longer beat between slides, no symbols, numbers written as spoken. Every line starts with a delivery cue like `[grinning, punchy]`, with a fresh cue at least every 10 spoken words so the voice does not fade, at least 5 different cues, a high-energy cue to open line 1 and at most one low-energy cue; `(break)` is a short beat. Cues are not spoken. `python generate.py --cues` adds cues to voiceovers that have none. Leave it out and run `python generate.py --voiceover` to have Claude write it. Then run `python generate.py --check` and `python voice.py 15` to preview it. It is posted at the next slot's run instead of a freshly written reel, as is: hand-added reels skip the hook judge, the series label and the no-3D strip.

## Learning

Every day (or on the days in `LEARN_DAYS`) `learn.py` works out what holds viewers and feeds it back to the writers:

1. **Measure.** Each post's Instagram numbers (views, reach, skip rate, watch time, saves, shares, likes, comments, and follows and profile visits where Instagram offers them) are read every day for a post's first week, then once a week until it is 4 weeks old, then never again. The daily readings show how long each reel keeps getting views (views at day 1, 3 and 7, and the share of a week's views that came after day 1). Keyword comments are counted per post. Snapshots are appended to `metrics/<year>-<month>.jsonl`.
2. **Score.** Every reel is compared with the account's usual (the median): skip rate, and the share of the reel watched (watch time divided by the reel's length). Views are compared at 7 days old. A reel is scored only from 2 days old, when its numbers have settled. Reels are grouped by series, pillar, visual, hook word, hook type, opening (proof under the hook or text only), 3D, slot (5 PM, 9 PM or 1 AM Pakistan) and test option. Nothing is learned or reported until at least 2 reels have settled numbers.
3. **Judge the rules.** The writer's rules live in `rules.json` as *trial*, *kept* (proven) or *retired*. After 2 weeks a rule on trial is compared with the 4 weeks of reels before it: kept if it helped, retired if it hurt or showed no clear effect by 4 weeks. A rule that never gets 5 reels on each side is retired after 6 weeks. "Clearly" means 2 points of skip rate or 5 points of share watched. At most 10 rules are active, each at most 30 words. `learnings.md`, which the writers read, is generated from the active rules.
4. **The running test.** One thing at a time is decided by chance for each reel: first a question hook vs a statement, then a short vs a long voiceover, then a number in the hook or not (`generate.EXPERIMENTS`). The writer is told and the reel is checked for it. Once each option has 5 measured reels the test ends; a clear winner becomes a proven rule and the next test starts. A test that cannot get there in 21 days ends without a verdict. After the three tests no new one starts. `experiments.json` holds the running one and the results. Set repo variable `EXPERIMENT=off` to stop testing.
5. **New rules.** Claude proposes rules from the numbers (at most 3 new a week, however often the loop runs); one is only added when groups of at least 5 reels behind it clearly differ in something the writer controls (posting times go to the decision instead), and never if it touches your hard rules (music, faces, animals, Reddit, invented content).
6. **Comments and covers.** Topics people asked for in comments go to `ideas.json` (topics only, no names or quotes) and both writers see them. Claude also looks at the covers of the best and worst openings.
7. **Report.** Saved to `reports/<date>.md` and posted as a comment on the week's issue: the last 7 days vs the 7 before, how long reels keep getting views, best and worst openings, carousels, the test, rule changes, what people asked for, a summary, and one decision for you to approve (settings like `THREE_D_CHANCE` are never changed on their own).

Only the learning job writes these files, so it never collides with the daily posts committing `reels.json`. Each posted reel records what the loop needs: `shown` (what each slide really showed), `slot`, `seconds` and `test`.

Run it by hand any time: Actions → **Learning** → **Run workflow**. (Actions → **Weekly** → **Run workflow** only refreshes the token; tick `post_carousel` to also post the carousel.)

## What makes a reel work

`playbook.md` holds the researched rules (2026-10-01; our first reels lost 80 to 92% of viewers in the first 3 seconds, against about 60% for a normal reel). The writer, the hook judge and the frame review all read it, so changing a rule there changes all three.

- **One useful thing per reel**: the writer starts from the `payoff` (the exact command, line, setting or template the viewer gets) and the three points are its steps.
- **The hook**: a 3 to 6 word phrase on screen (people glance, they do not read sentences), the full sentence spoken, and the proof (`hook_visual`: code, a before/after diff, a screenshot, a code morph or a code stepper) under it, all complete on the very first frame.
- **Four hooks, the best one wins**: the writer gives its hook plus three alternatives of different types (problem, before/after, shortcut, mistake, test, news); a second Claude scores them against the playbook and the winner is used.
- **Little text**: smaller type, titles of 3 words, captions 3 words at a time, bigger code. No invented chats or posts.
- **Animations that explain** (`motion.py`, researched 2026-10-01): at most one per reel, on the point where movement explains better than a still: code running line by line with its variables, a request travelling between parts, before code turning into after code, a git rebase or merge, the event loop, an array or map changing, a sequence or state diagram, bars growing to real cited numbers, a zoom inside a part, references moving between objects, a real command's output turning into boxes, a command turning into its result panel, a command list scrolling onto the chosen option. Calm premium motion (soft springs, one change at a time with a pause, the active part glowing), abstract shapes only, and every value shown is true. Each has a still backup in case it cannot be drawn.
- **Checked before posting**: the frame review also looks at frame 0 and whether the payoff is really on screen. A weak first frame is printed as a warning in the run's log and saved with the reel (it never costs the day's post); a hook proof that does not show its point is dropped and the reel is rendered again.
- **Learned from studying three creators' reels** (2026-10-01, `studies/`; 14k to 48k likes each):
  - **Build it live**: the `build` visual draws a real page above its CSS, plain at first, updated by the browser after each typed stage, the finished look held at the end. Slot 3 has a "Build it live" format for it, and it can sit under the hook as the plain "before".
  - **A freebie on every how-to**: how-to, build, trick, versus, beginner, dev-mistake, AI and freelance-playbook reels must offer a `dm_keyword` with the full code or template in `dm_guide` ("Comment CODE for the code"); the closing card shows the keyword big, in the hook's style.
  - **Points escalate**: what it is, then it working, then the strongest proof.
  - **A held beat** (`reveal`): on the payoff point the voice goes quiet for about a second, with soft ticks, while the output prints or the page finishes, then a pop and the result.
  - **Calmer motion**: slide changes glide instead of jumping, and a `kinetic` animation shows a takeaway in big type word by word with one accent colour. New `inspect` (selection boxes and label pills on code lines) and `variants` (one card swapping between real alternatives) animations.
  - **Hook pace test**: `hook_pace` (dense, faster first line vs a short relaxed one) runs next after the current test.
- **Measured**: the learning loop compares reels by hook type, opening (proof under the hook or text only), reveal (held beat or not) and offer (freebie or question), and Claude's summary and new rules draw on those groups, so your own numbers decide which works.

## Honesty stop

The frame review also checks every claim. A dishonest one stops the post: a news reel is replaced by a fresh evergreen reel, and if that also fails nothing is posted that day. A reel added by hand is not posted and the run fails; it stays first in the queue, so every later run picks it again and fails until you fix or remove it. If the review itself is unavailable, screenshots are dropped and the rest is posted.

## Study other creators

`study.py` downloads a short video, measures it with code and has Claude break it down, so you learn *why* someone's reels work, not only that they do. Only patterns are learned: never their script, wording, visuals or ideas.

- **Measured** (ffmpeg, numpy, Whisper): length, cuts and "beats" (moments the picture changes noticeably) per 10 seconds, the first cut, how much of the time something moves, whether it opens on a blank frame, loudness every half second, when speech starts, words per second, words in the first 3 seconds, the longest pause.
- **Claude's breakdown**, from the key frames (0, 0.5, 1, 2 and 3 seconds, about a second after every cut or beat, and the end; at most 16), those numbers and the timed transcript: the first second, the hook (said, on screen, its type), the structure second by second, pacing, why it works, **what we could test** (each with how it would look in our reels and a test idea), and **not for us** (patterns that break your hard rules: faces, music, anything invented, Reddit, copying).
- **Saved** to `studies/<date>-<title>.md`, one line per video in `studies/index.jsonl`, so studies add up over time.

Four ways to use it:
1. **Every Sunday, on its own** (08:00 UTC, nothing to give it): it searches three of its own topics a week in turn (`study.TOPICS`: Claude Code, Cursor, coding tips, Next.js, freelancing...) with your existing `YOUTUBE_API_KEY`, keeps its own watchlist of creators whose Shorts got 5 times their subscriber count or more (`studies/channels.json`, up to 20) and checks their new Shorts that beat their own usual (from the last 14 days, 10,000 views or more and at least twice the channel's median). Claude first reads the titles and channels and keeps only videos on your topics (AI tools, coding, building apps, dev careers and freelancing), so viral gaming or prank channels are never studied, and a watched channel whose hits are off-topic leaves the list. It never studies a video twice, and studies the best 4 (one per creator). Then, once there are at least 3 studies, Claude reads the last 30 and writes **What keeps working for others**: the patterns that show up in at least two studies, with how many, each with a test for us (`studies/<date>-digest.md`). The whole report goes into a new issue "Study <date>"; with nothing new to study, no issue is created.
2. **An issue**: open an issue with the label `study`, paste video links (YouTube Shorts, TikTok, other public links) and/or drag screen recordings into it. The report arrives as a comment. Instagram usually refuses downloads without a login, so for Instagram reels record the screen and drop the recording in. Only your own issues start it.
3. **Run by hand**: Actions → **Study videos** → **Run workflow**, with links, the `auto` box (the Sunday study now), or a search like `claude code tips` (uses `YOUTUBE_API_KEY`): it finds the Shorts of the last 30 days that got the most views compared with their channel's size (views per subscriber, at least 10,000 views, at most 180 seconds long) and studies the top ones (`top`, default 3). The report goes into a new issue "Study <date>".
4. **Locally**: `python study.py <file or link> [...]`, `python study.py --auto`, `python study.py --search "claude code tips" --top 3`.

Downloading uses yt-dlp for public videos only, never a login. YouTube sometimes refuses downloads from GitHub's machines ("confirm you're not a bot"); those videos are listed under "Could not study", and a screen recording in a `study` issue works instead. Instagram's own search for other creators and hashtags needs a Facebook-login token, which this account's Instagram-login token is not, so the automatic study uses YouTube only. Platforms' terms may not allow downloading: keep it to studying, never repost anything. Videos are deleted after each run.

## Reliable timing

GitHub drops many scheduled runs when it is busy: in the first days the Daily reel's three crons fired only twice in three days, and a 15-minute cron fired about three times in half a day. So posting never depends on one cron firing:

- Each reel slot owns a window: slot 1 from 11:07 UTC, slot 2 from 15:07, slot 3 from 19:07 until midnight. `scheduler.py` (run by **Scheduler**) looks at `reels.json` and the running workflows; if the current slot has not posted today and nothing is running, it starts the Daily reel for that slot. That run waits for the post time, or posts at once when late. A slot whose window has passed is skipped rather than stacked on the next one. Once two Daily reel runs have started in a slot's window (the cron's own run and any manual run, dry or not, count) it is not started again and is left for you to look at.
- From 06:00 UTC it starts **Learning** once on each day in `LEARN_DAYS`, on Sundays from 08:00 UTC it starts **Study videos** (the weekly study) and from 10:00 UTC **Weekly**, each if it has not run that day (runs started from `study` issues do not count).
- Daily reel, Learning and Weekly share one concurrency group (`reels-queue`), so they wait for each other; if several are waiting, GitHub keeps only the newest pending one.
- A workflow GitHub refuses to start (say Daily reel is disabled to pause it) is printed and the other checks still run.
- `publish.py` never posts the same slot twice in a day, however many times it is started, so all of this is safe to repeat.

The Scheduler itself runs on a GitHub cron too, so for timing that never slips, have an outside service start it every 10 to 15 minutes: a `POST` to `https://api.github.com/repos/hassanjan1841/automation-reel/actions/workflows/scheduler.yml/dispatches` with body `{"ref":"main"}`, headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json` and `Content-Type: application/json` (without it GitHub answers 415 and nothing starts), and a fine-grained token that has **Actions: read and write** on this repo. A success is HTTP 204. This runs from a cron-job.org job every 10 minutes (set up 2026-09-29); if reels stop starting on time, check that job's history first.

## Pause it

GitHub → Actions → **Daily reel** → `...` → **Disable workflow** stops the posts; the Scheduler just prints that it could not start it. Disable **Scheduler** too to stop Learning and the Sunday runs it starts. Enable them again to resume. Keep **Weekly** on: if it stays off for more than 60 days the Instagram token expires and has to be generated again.

## Voice

The voice is Fish Audio's ThatMob (`s2.1-pro-free`, free until 2026-11-30; set `FISH_MODEL=s2.1-pro` after that). It needs the secret `FISH_API_KEY`; without it the voiceover falls back to Kokoro. `VOICE_ENGINE` forces `fish` or `kokoro`, `VOICE` picks another Fish voice id or Kokoro voice (or `none` for sound effects only), and `VOICE_PITCH` shifts it in semitones (avoid it: shifted voices sound robotic). Every reel carries its own `voiceover` (5 lines, one per slide) that adds to the slides instead of reading them; reels without one fall back to reading the slide text. `python voice.py 3 am_fenrir` writes `out/reel-3-am_fenrir.mp4` to compare voices.

## Run it by hand

Actions → **Daily reel** → **Run workflow**. `dry_run` is on by default; the rendered MP4 is attached to the run as an artifact either way. A manual run waits while another Daily reel, Learning or Weekly run is going, and counts toward its slot's two attempts.

## Secrets

`IG_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (the legacy `service_role` JWT; new `sb_secret_` keys are rejected by Storage), `FISH_API_KEY` (the voice), `YOUTUBE_API_KEY` (Google Cloud, restricted to YouTube Data API v3), `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, valid 1 year), `GH_PAT` (fine-grained, this repo only, **Secrets: read and write**; used to save the refreshed token).

Optional repo variables or env (an empty variable means the default): `POST_AT_UTC` (reel 1's post time, default `12:00`; reel 2 posts at `16:00`, reel 3 at `20:00`; it waits only when the post time is less than 2 hours away, otherwise it posts at once), `SLOT` (`2` or `3` for the later reels, set by their crons; a manual run has a `slot` choice), `REEL_FORMAT` (local only, no workflow passes it: forces reel 3's format, `news`, `trick`, `versus`, `series` or `build`), `FORCE_POST` (`true` posts even if this slot's reel already went out today; normally a second run for the same slot does nothing), `VOICE`, `VOICE_ENGINE`, `VOICE_PITCH`, `VOICE_SPEED` (default `1.0`; `1.1` felt rushed), `FISH_MODEL`, `TRENDING` (see above), `THREE_D` (`on` or `off` forces 3D; default random; a manual Daily reel run also has a `three_d` choice), `THREE_D_CHANCE` (share of reels 3D is allowed in, default `0.5`), `LEARN_DAYS` (days the learning loop runs: empty or `daily`, or e.g. `sun,wed`), `EXPERIMENT` (`off` stops the running test; a test's name forces it, for trying it out), `CLAUDE_MODEL` (model for the trend editor and fact-check, the frame review, the learning loop, the carousel, the video study and docs sync; the writer and hook judge always use `MODEL` in `generate.py`; as a repo variable only Daily reel and Study videos pass it), `GRAPH_VERSION` (Instagram Graph API version, default `v25.0`; as a repo variable only Daily reel passes it). The study workflow also passes `GH_TOKEN` (its own token, to fetch videos attached to the issue) and `ISSUE_BODY` (the issue's text, where `study.py --issue` finds the links).

## Local setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # plus ffmpeg on PATH
.venv/bin/python render.py 1
```

Screenshots, recordings, 3D and animations also need `.venv/bin/python -m playwright install chromium`. Writing and reviewing need the `claude` CLI. `study.py` needs `yt-dlp`, which is not in `requirements.txt`.

## Docs

Three docs, one job each: this README for running the project, `CLAUDE.md` for Claude Code sessions, and `.claude/skills/automation-reel/SKILL.md` for working on the code. Each script's docstring is the source of truth for its usage and env vars.

- `python3 docs_check.py` checks that every script, workflow, env var, schedule, `module.name` and documented flag in the docs still matches the code.
- **Docs check** runs it on every push and pull request.
- **Docs sync** runs `docs_sync.py` after code pushes to `main` and every Saturday. If the code moved on, Claude updates the docs and the workflow opens (or updates) a pull request from the `docs-sync` branch. It never pushes to `main` itself, and it can only change the three doc files.
- In Claude Code, a Stop hook blocks once when code changed without doc updates, so docs are fixed in the same change.

Docs sync needs **Settings → Actions → General → Allow GitHub Actions to create and approve pull requests** turned on.
