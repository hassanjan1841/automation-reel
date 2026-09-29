---
name: verify
description: How to verify a change in automation-reel robustly before calling it done - the fast offline checks, the mutation check that proves the tests would catch a bug, CI parity, the real end-to-end runs for the part you touched (writer, publish and render, learning loop, carousel, workflows), the sandbox workarounds for Claude Code on the web, an adversarial diff review, and how to report. Use after every change, and whenever asked to verify, test, check or prove that something works (/verify).
---

# verify

A change is done when it has been shown to work, not when it looks right. Run every level that applies, in order,
and report exactly what ran. Load the `automation-reel` skill first for how the code works.

## 1. Fast checks (always, offline, about a minute)

```bash
.venv/bin/python test_learn.py            # learning loop, the weekly test, writer and publish records
.venv/bin/python test_study.py            # study.py on synthetic videos (needs ffmpeg on PATH, else those tests skip)
.venv/bin/python generate.py --check      # every reel in reels.json still valid
python3 docs_check.py                     # docs match the code
.venv/bin/python test_voice.py            # pronunciation rules (text only)
.venv/bin/python -m pyflakes <changed .py files>   # pip install pyflakes into .venv if missing
```

All must pass. A failing test is a finding, never a flake: read it, fix the code or the test's wrong assumption,
and say which it was.

## 2. Prove the tests would catch a bug

```bash
.venv/bin/python tests/mutants.py
```

It breaks the code one known way at a time in a throwaway copy and expects `test_learn.py` (for `study.py`, `test_study.py`) to fail each time.
For every new behaviour you add, add a mutant to `tests/mutants.py` (the exact code, what to break it into, a
label). A mutant that survives means a behaviour no test protects: write the test, then rerun. A mutant marked
STALE means the code moved: update it.

## 3. CI parity

CI (`tests.yml`) and the learning job (`learn.yml`) install only `requests pillow numpy`. A new top-level import that
needs more breaks the next day's learning run, silently until then. Check it the same way:

```bash
python3.12 -m venv /tmp/ci && /tmp/ci/bin/pip install -q requests pillow numpy
/tmp/ci/bin/python test_learn.py
```

For a new env var: the workflow must pass it (`env:` with `${{ vars.X }}`), and README and the skill must name it
(`docs_check.py` checks the docs, not the workflow wiring). For a new file a job writes: the job's `git add` must
include it; `test_learn.py` checks the learning job's loop.

## 4. Real end-to-end runs for what you touched

Never post for real. These use temp copies of the data files and fake Instagram and uploads.

| You changed | Run |
| --- | --- |
| The writer, validation, the weekly test, prompts (`generate.py`, `trends.py`) | `.venv/bin/python tests/e2e_writer.py` (real Claude writes a reel per test option; each must be valid and follow it) |
| Publishing, rendering, visuals, 3D (`publish.py`, `render.py`, `visuals.py`, `scene3d.py`, `qa.py`) | `.venv/bin/python tests/e2e_publish.py`, then with `--reject`, and once with `--real-review`; look at frames (below) |
| The learning loop (`learn.py`, `history.py`) | `.venv/bin/python tests/e2e_learn.py 10` (ten days of daily runs, real Claude for rules, report, comment topics and covers) |
| The video study (`study.py`) | `.venv/bin/python study.py <an mp4, e.g. a dry-run render in out/>` with `STUDIES` pointed at a temp folder, or Actions > Study videos with one link; read the whole report: every section filled, measured numbers plausible, nothing in "What we could test" breaks a hard rule |
| The carousel | `DRY_RUN=true .venv/bin/python carousel.py` |
| The voice | `.venv/bin/python test_voice.py --audio` and `--verify` |
| A workflow | Actions > Daily reel > Run workflow with `dry_run` on; read the log and the artifact |
| The daily path as a whole | `DRY_RUN=true .venv/bin/python publish.py` |

Look at what a render produced, not just its exit code:

```bash
for t in 1.5 6.5 11 16; do ffmpeg -loglevel error -y -ss $t -i out/reel-<id>.mp4 -frames:v 1 -vf scale=360:-1 /tmp/f$t.png; done
```

Then open the frames (Read the PNGs): the text is inside the frame, 3D scenes and visuals actually appear, captions
are readable.

## 5. Sandbox workarounds (Claude Code on the web)

The web sandbox's network policy blocks jsDelivr, Hugging Face and raw GitHub downloads; npm and PyPI work.
Work around it for testing only; never change the code for the sandbox.

- Fonts: `npm pack @expo-google-fonts/poppins @expo-google-fonts/jetbrains-mono`, unpack, copy
  `Poppins_700Bold.ttf`, `Poppins_600SemiBold.ttf`, `Poppins_400Regular.ttf` to `fonts/Poppins-Bold.ttf`,
  `-SemiBold.ttf`, `-Regular.ttf` and `JetBrainsMono_500Medium.ttf` to `fonts/JetBrainsMono.ttf` (fonts/ is ignored).
- ffmpeg: `.venv/bin/pip install imageio-ffmpeg` and put a symlink named `ffmpeg` to its binary on `PATH`.
- three.js: `npm pack three@0.170.0`, unpack into `<dir>/three@0.170.0`, run with `E2E_THREE=<dir>`.
- Chromium: if Playwright wants a newer browser than `/opt/pw-browsers` has, set
  `E2E_CHROMIUM=/opt/pw-browsers/chromium-<n>/chrome-linux/chrome`.
- Voice: the models cannot download; `tests/e2e_publish.py` uses a silent voice with even word times by default.
- Claude: the `claude` CLI is usually logged in; check with `claude -p "Reply OK" --output-format json`.

Screenshots and scenes that need a blocked site fall back to the next visual; that fallback is itself worth seeing.

## 6. Adversarial review of the diff

Read `git diff` as a reviewer who wants to reject it:
- The creator's hard rules: no music, no faces or animals, nothing invented, never Reddit. Could any new prompt,
  rule or test option push the writer toward breaking one?
- Live state: `reels.json` and the learning loop's files changed only if the task was about them; a real run
  never wrote them during testing (check `git status`).
- Secrets: no token printed; new error paths redacted.
- Every file a workflow must commit is in its `git add`; every new env var reaches the job.
- Failure paths: what happens when Claude, Instagram or the network fails halfway? The daily post must still go
  out; the learning job must still save what it measured.
- Docs updated in the same change (`docs_check.py` passes and the words are true).

## 7. Report

Say what ran and what it showed, with numbers (tests run, mutants caught, e2e checks passed). Say plainly what could
not be run and why (e.g. no Instagram token, a blocked host), and what will be the first real check (the next daily
or weekly run, and what to look for in its log). Never describe something as tested that was not.
