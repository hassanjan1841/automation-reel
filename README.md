# automation-reel

Posts one Instagram Reel a day to @hassanjan.k with no manual work.

- **Daily** (`daily-reel.yml`, starts 11:07 UTC = 4:07 PM Pakistan, posts at 12:00 UTC = 5 PM): nothing is written ahead of time. About an hour before posting it researches today: it reads your recent reels' insights (views, reach, skip rate, watch time, saves, shares) and scans what is trending (Hacker News, GitHub Trending, dev.to, Lobsters, YouTube via the Data API, AI and dev blog feeds). If a timely story is strong enough (7/10) and survives an independent fact-check, that becomes today's reel with its `sources`; otherwise Claude writes a fresh evergreen reel for today's pillar, steered by what held your viewers. Then it records the voiceover (Fish Audio, checked by listening back with Whisper), renders a 1080x1920 MP4 with synced captions and real visuals, has Claude review the frames (bad visuals are swapped out), waits until 12:00 UTC, uploads to the public Supabase bucket `reels`, publishes through the Instagram API, deletes the upload, and commits `reels.json` (the record of what was posted) plus `pronounce.json` if the voice learned a new fix. A reel you add by hand with `posted_at: null` is posted instead of writing a new one. Every run saves the exact reel beside the video (`out/reel-<id>.json`, in the run's artifact), so a dry run you like can be added to `reels.json` and posted as is.
- **Token refresh** (`token-refresh.yml`, Sundays 10:00 UTC): refreshes the Instagram token so it never expires.
- **Insights** (`insights.yml`, run by hand): prints account stats and per-reel views, reach, skip rate, watch time, likes, comments, saves and shares, and attaches each reel's cover as an artifact named `thumbs`, sorted by skip rate.
- **Docs** (`docs-check.yml` on every push, `docs-sync.yml` on code pushes to `main` and Saturdays 09:00 UTC): keeps this README, `CLAUDE.md` and the project skill in step with the code. See [Docs](#docs).

## Files

| File | What it does |
| --- | --- |
| `reels.json` | The record of every posted reel. A reel added by hand with `posted_at: null` is posted next instead of a freshly written one. |
| `render.py` | Draws the slides and sound effects, encodes with ffmpeg. With a voiceover it adds captions synced to the speech (a dark pill near the bottom, the spoken word highlighted) and shows each point's visual. `python render.py 3` writes `out/reel-3.mp4` without voice. |
| `visuals.py` | The real visuals on point slides: a syntax-highlighted code window, a terminal, or a live screenshot (Playwright, phone width) scrolled to the text in `find`, outlined and spotlit. A visual that cannot be made falls back to the slide's body text. |
| `qa.py` | Visual review after rendering: Claude looks at one frame per slide and rejects visuals that are irrelevant, unreadable or broken (cookie banner, error page). `publish.py` then renders the point's next visual choice, or its text. `python qa.py 3` renders reel 3 and prints the review. |
| `publish.py` | Researches and writes today's reel (or takes one added by hand), renders, reviews, waits for `POST_AT_UTC`, uploads and publishes. `DRY_RUN=true` renders only and does not wait. |
| `generate.py` | Writes reels with Claude via `claude -p` (`generate.today` writes today's evergreen reel); the validator. `--force` adds 14 to `reels.json` by hand, `--check` validates it, `--voiceover` writes voiceovers for unposted reels that have none, `--cues` adds delivery cues to them, `--visuals` picks visuals for queued reels that have none. |
| `voice.py` | Voiceover with Fish Audio (voice ThatMob, recorded in one continuous take and cut per slide) or, without `FISH_API_KEY`, Kokoro (free, local). Every take is transcribed with Whisper; a misheard word gets respellings or exact phonemes from Claude until one comes back right, and that fix is saved to `pronounce.json`. `COMMON_RULES` and `KOKORO_RULES` hold the hand-written rules (numbers, prices, SaaS, Next.js). `python voice.py 3` previews reel 3 with voice. |
| `pronounce.json` | Respellings the listen-back check learned, e.g. `"Supabase": "Soo pa base"`. Edit or delete an entry if it sounds wrong. |
| `test_voice.py` | Pronunciation regression test. `python test_voice.py` checks the text rules, `--audio` also speaks every test sentence and listens back. |
| `trends.py` | The trend scan and editor. `python trends.py` lists what it scraped, `--pick` shows what Claude would post. Set repo variable `TRENDING=off` to skip the news and always write an evergreen reel. |
| `refresh_token.py` | Refreshes `IG_TOKEN` and saves it back as a repo secret. |
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

The voiceover is heard while the slides are read, so it must not repeat the slide text: 35 to 70 words, no symbols, numbers written as spoken. Every line starts with a delivery cue like `[grinning, punchy]`, with a fresh cue at least every 10 spoken words so the voice does not fade; `(break)` is a short beat. Cues are not spoken. `python generate.py --cues` adds cues to voiceovers that have none. Leave it out and run `python generate.py --voiceover` to have Claude write it. Then run `python generate.py --check` and `python voice.py 15` to preview it. It is posted at the next daily run instead of a freshly written reel.

## Pause it

GitHub → Actions → **Daily reel** → `...` → **Disable workflow**. Enable it again to resume. Keep **Token refresh** on: if it stays off for more than 60 days the Instagram token expires and has to be generated again.

## Voice

The voice is Fish Audio's ThatMob (`s2.1-pro-free`, free until 2026-11-30; set `FISH_MODEL=s2.1-pro` after that). It needs the secret `FISH_API_KEY`; without it the voiceover falls back to Kokoro. `VOICE_ENGINE` forces `fish` or `kokoro`, `VOICE` picks another Fish voice id or Kokoro voice (or `none` for sound effects only), and `VOICE_PITCH` shifts it in semitones (avoid it: shifted voices sound robotic). Every reel carries its own `voiceover` (5 lines, one per slide) that adds to the slides instead of reading them; reels without one fall back to reading the slide text. `python voice.py 3 am_fenrir` writes `out/reel-3-am_fenrir.mp4` to compare voices.

## Run it by hand

Actions → **Daily reel** → **Run workflow**. `dry_run` is on by default; the rendered MP4 is attached to the run as an artifact either way.

## Secrets

`IG_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `YOUTUBE_API_KEY` (Google Cloud, restricted to YouTube Data API v3), `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, valid 1 year), `GH_PAT` (fine-grained, this repo only, **Secrets: read and write**; used to save the refreshed token).

Optional repo variables or env: `POST_AT_UTC` (post time, default `12:00`), `FORCE_POST` (`true` posts even if a reel already went out today; normally a second run the same day does nothing), `VOICE`, `VOICE_ENGINE`, `VOICE_PITCH`, `FISH_MODEL`, `TRENDING` (see above), `CLAUDE_MODEL` (model for the trend editor, fact-check and docs sync; defaults to `MODEL` in `generate.py`), `GRAPH_VERSION` (Instagram Graph API version, default `v25.0`).

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
