# automation-reel

Posts one Instagram Reel a day to @hassanjan.k with no manual work.

- **Daily** (`daily-reel.yml`, 14:00 UTC = 7 PM Pakistan): takes the first reel in `reels.json` with `posted_at: null`, renders it to a 1080x1920 MP4 with a spoken voiceover (voice `am_michael`), uploads it to the public Supabase bucket `reels`, publishes it through the Instagram API, deletes the upload, and commits `reels.json` with `posted_at` and `media_id` filled in.
- **Weekly** (`weekly-content.yml`, Sundays 10:00 UTC): if fewer than 7 reels are unposted, asks Claude (through the Claude Code CLI, billed to your Max plan) for 14 new ones, validates them and appends them. The same workflow refreshes the Instagram token so it never expires.

## Files

| File | What it does |
| --- | --- |
| `reels.json` | The queue. Posted in order, top to bottom. |
| `render.py` | Draws the slides and sound effects, encodes with ffmpeg. `python render.py 3` writes `out/reel-3.mp4`. |
| `publish.py` | Render, upload, publish, update the queue. `DRY_RUN=true` renders only. |
| `generate.py` | Tops up the queue with Claude via `claude -p`. `--force` always adds 14, `--check` validates the queue. |
| `voice.py` | Voiceover with Kokoro (free, runs in Actions). `PRONOUNCE` fixes tech terms like SaaS, CLI, Next.js; add a line there if a word sounds wrong. `python voice.py 3` previews reel 3 with voice. |
| `refresh_token.py` | Refreshes `IG_TOKEN` and saves it back as a repo secret. |

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
    { "title": "Max eight words", "body": "Max sixteen words, no asterisks." },
    { "title": "...", "body": "..." },
    { "title": "...", "body": "..." }
  ],
  "cta": "A short question with one *highlighted* word?",
  "caption": "Line one.\nLine two.\nA question to end on? 👇",
  "hashtags": ["#nextjs", "#react", "#typescript", "#webdev", "#coding", "#programming", "#developer", "#devtips"],
  "posted_at": null,
  "media_id": null
}
```

Then run `python generate.py --check` and `python render.py 15` to preview it. To post something sooner, move it up the list.

## Pause it

GitHub → Actions → **Daily reel** → `...` → **Disable workflow**. Enable it again to resume. Disable **Weekly content** too if you do not want new reels generated, but keep in mind it also refreshes the Instagram token: if it stays off for more than 60 days the token expires and has to be generated again.

## Voice

Set a repo variable or env `VOICE` to another Kokoro voice (e.g. `am_fenrir`), or `none` for sound effects only. The spoken script is the slide text; add a `voiceover` array (one line per slide, 5 lines) to a reel to override it.

## Run it by hand

Actions → **Daily reel** → **Run workflow**. `dry_run` is on by default; the rendered MP4 is attached to the run as an artifact either way.

## Secrets

`IG_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, valid 1 year), `GH_PAT` (fine-grained, this repo only, **Secrets: read and write**; used to save the refreshed token).

## Local setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # plus ffmpeg on PATH
.venv/bin/python render.py 1
```
