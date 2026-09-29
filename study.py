"""Study other creators' short videos deeply, to learn what holds viewers (patterns, never their content).

For each video: download it (a file, a GitHub issue attachment, or a public link yt-dlp can fetch, like a
YouTube Short), then
  - measure it with code: length, cuts and how often the picture changes, a blank first frame, loudness, when
    speech starts, words per second, pauses (ffmpeg, numpy, the same Whisper model as voice.py);
  - show Claude the key frames (0, 0.5, 1, 2 and 3 seconds, a second after every cut, and the end) with those numbers and the timed
    transcript, and get a breakdown: the first second, the hook, the structure, pacing, why it works, and which
    patterns this account could test (split from anything that breaks the creator's hard rules: faces, music...).
Each study is saved to studies/<date>-<slug>.md and summed up in studies/index.jsonl; out/study.md holds this
run's reports (the study workflow posts it on the issue). Only patterns are learned; scripts, visuals and wording
are never copied, and the videos are deleted after the run.

Sources:
  python study.py <file or url> [...]           study these videos
  python study.py --search "claude code tips"   find the Shorts that beat their channel most (YouTube Data API,
                  [--top 3]                     last 30 days) and study the top ones
  python study.py --issue                       the links and attachments in ISSUE_BODY (the study workflow)

Env: CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_MODEL, YOUTUBE_API_KEY (for --search), GH_TOKEN (to fetch issue attachments),
     ISSUE_BODY (with --issue)
"""

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

import history
import render

STUDIES = render.ROOT / 'studies'
INDEX = STUDIES / 'index.jsonl'
OUT = render.OUT_DIR / 'study.md'
FPS = 10                   # frames a second read for motion
CUT = 28.0                 # mean brightness change (0-255) between two frames that counts as a cut
MOVING = 3.0               # change that counts as something moving
BEAT = 15.0                # change summed over half a second that counts as a beat: a cut, a slide change or a
                           # camera punch (our own reels peak at 17 to 45 on slide changes, 3 to 9 in between)
KEY_TIMES = (0.0, 0.5, 1.0, 2.0, 3.0)
MAX_FRAMES = 16
SETTLE = 1.0               # seconds after a cut or beat to take its frame
URL = re.compile(r'https?://[^\s)<>\]"\']+')
YOUTUBE_API = 'https://www.googleapis.com/youtube/v3'


# ---------- getting the video ----------

def sources_in(text):
    """The links in a text (an issue body), in order, without duplicates; image links are skipped."""
    seen, out = set(), []
    for url in URL.findall(text or ''):
        url = url.rstrip('.,')
        if url not in seen and not re.search(r'\.(png|jpe?g|gif|webp)(\?|$)', url, re.I):
            seen.add(url)
            out.append(url)
    return out


def fetch(source, folder, token=None):
    """(path to the video, what we know about it). Local files as they are; GitHub attachments with the token;
    anything else with yt-dlp (public videos only, never a login)."""
    if Path(source).is_file():
        return Path(source), {'source': source, 'title': Path(source).stem}
    if 'github.com/user-attachments/' in source or 'githubusercontent.com' in source:
        path = Path(folder) / f'attachment-{abs(hash(source)) % 10**8}.mp4'
        headers = {'Authorization': f'token {token}'} if token else {}
        with requests.get(source, headers=headers, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(path, 'wb') as f:
                for chunk in resp.iter_content(1 << 20):
                    f.write(chunk)
        return path, {'source': source, 'title': 'uploaded recording'}
    out = subprocess.run(['yt-dlp', '--no-playlist', '--no-simulate', '-j', '--max-filesize', '300M',
                          '-f', 'bv*[height<=1920]+ba/b[height<=1920]/b', '--merge-output-format', 'mp4',
                          '-o', str(Path(folder) / '%(id)s.%(ext)s'), source],
                         capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(f'could not download {source}: {out.stderr.strip()[-300:]}')
    info = json.loads(out.stdout.strip().splitlines()[-1])
    path = Path(folder) / f"{info['id']}.mp4"
    if not path.exists():
        path = next(Path(folder).glob(f"{info['id']}.*"))
    return path, {'source': source, 'title': info.get('title'), 'channel': info.get('channel') or info.get('uploader'),
                  'views': info.get('view_count'), 'likes': info.get('like_count'),
                  'comments': info.get('comment_count'), 'followers': info.get('channel_follower_count'),
                  'uploaded': info.get('upload_date')}


def search(query, top=3, key=None, days=30):
    """Shorts on a topic that beat their channel most (views per subscriber), from the last `days` days."""
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    found = requests.get(f'{YOUTUBE_API}/search', timeout=30, params={
        'part': 'snippet', 'q': query, 'type': 'video', 'videoDuration': 'short', 'order': 'viewCount',
        'publishedAfter': after, 'relevanceLanguage': 'en', 'maxResults': 25, 'key': key}).json()
    if 'error' in found:
        raise RuntimeError(found['error'].get('message', 'YouTube error'))
    ids = [i['id']['videoId'] for i in found.get('items', [])]
    if not ids:
        return []
    videos = requests.get(f'{YOUTUBE_API}/videos', timeout=30, params={
        'part': 'snippet,statistics,contentDetails', 'id': ','.join(ids), 'key': key}).json().get('items', [])
    channels = {c['id']: c['statistics'] for c in requests.get(f'{YOUTUBE_API}/channels', timeout=30, params={
        'part': 'statistics', 'id': ','.join({v['snippet']['channelId'] for v in videos}), 'key': key}).json().get('items', [])}
    picks = []
    for v in videos:
        seconds = iso_seconds(v['contentDetails']['duration'])
        views = int(v['statistics'].get('viewCount', 0))
        subs = int(channels.get(v['snippet']['channelId'], {}).get('subscriberCount', 0) or 0)
        if seconds > 180 or views < 10_000:
            continue
        picks.append({'url': f"https://www.youtube.com/shorts/{v['id']}", 'title': v['snippet']['title'],
                      'channel': v['snippet']['channelTitle'], 'views': views, 'followers': subs,
                      'outlier': round(views / max(subs, 1000), 1)})
    return sorted(picks, key=lambda p: -p['outlier'])[:top]


def iso_seconds(duration):
    h, m, s = (int(x or 0) for x in re.fullmatch(r'P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration).groups())
    return h * 3600 + m * 60 + s


# ---------- measuring it ----------

def probe(path):
    """Length, size and whether it has sound, from ffmpeg's own description of the file."""
    err = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path)], capture_output=True, text=True).stderr
    d = re.search(r'Duration: (\d+):(\d+):([\d.]+)', err)
    v = re.search(r'Video:.*?, (\d{2,5})x(\d{2,5})', err)
    fps = re.search(r'([\d.]+) fps', err)
    return {'seconds': round(int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]), 2) if d else None,
            'width': int(v[1]) if v else None, 'height': int(v[2]) if v else None,
            'fps': float(fps[1]) if fps else None, 'has_audio': 'Audio:' in err}


def frames_gray(path, fps=FPS, w=90, h=160):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', f'fps={fps},scale={w}:{h},format=gray',
                          '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def motion(frames, fps=FPS):
    """Cuts, how much of the video is moving, and whether it opens on a blank frame."""
    if len(frames) < 2:
        return {'cuts': [], 'first_cut': None, 'cuts_per_10s': 0, 'beats': [], 'beats_per_10s': 0, 'moving_share': 0,
                'blank_start': True, 'first_change': None}
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    half = max(1, fps // 2)
    window = np.convolve(diffs, np.ones(half), 'same')
    beats, last = [], -1.0
    for i, w in enumerate(window):
        t = (i + 1) / fps
        if w >= BEAT and w == window[max(0, i - half):i + half + 1].max() and t - last >= 0.8:
            beats.append(round(t, 1))
            last = t
    cuts, last = [], -1.0
    for i, d in enumerate(diffs):
        t = (i + 1) / fps
        if d >= CUT and t - last >= 0.3:
            cuts.append(round(t, 1))
            last = t
    seconds = len(frames) / fps
    moving = diffs >= MOVING
    first_change = next(((i + 1) / fps for i, m in enumerate(moving) if m), None)
    return {'cuts': cuts, 'first_cut': cuts[0] if cuts else None,
            'cuts_per_10s': round(len(cuts) / seconds * 10, 1),
            'beats': beats, 'beats_per_10s': round(len(beats) / seconds * 10, 1),
            'moving_share': round(float(moving.mean()), 2),
            'blank_start': bool(frames[0].std() < 6),
            'first_change': round(first_change, 1) if first_change is not None else None}


def audio(path, sr=render.SR):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.float32)


def loudness(samples, sr=render.SR, step=0.5):
    """Loudness (dBFS) every half second."""
    n = int(sr * step)
    return [round(float(20 * np.log10(np.sqrt(np.mean(samples[i:i + n] ** 2)) + 1e-9)), 1)
            for i in range(0, len(samples) - n + 1, n)]


def transcribe(samples):
    """[(word, start, end)] with the same Whisper model as the voice check, or [] when it is not available."""
    if len(samples) == 0:
        return []
    try:
        import voice
        return voice.transcribe(samples, words=True)
    except Exception as e:  # no model or no network: the study goes on without the words
        print(f'  transcript unavailable ({type(e).__name__}: {str(e)[:120]})')
        return []


def speech(words, seconds):
    """When speech starts, how fast it goes, how much is said in the first 3 seconds, and the longest pause."""
    if not words:
        return {'speech_start': None, 'words_per_second': None, 'words_first_3s': 0, 'longest_pause': None}
    starts = [w[1] for w in words]
    pauses = [b[1] - a[2] for a, b in zip(words, words[1:])]
    spoken = max(words[-1][2] - words[0][1], 0.1)
    return {'speech_start': round(starts[0], 2), 'words_per_second': round(len(words) / spoken, 1),
            'words_first_3s': sum(1 for s in starts if s < 3), 'longest_pause': round(max(pauses), 1) if pauses else 0}


def key_frames(path, times, folder):
    paths = []
    for t in times:
        out = Path(folder) / f'frame-{t:05.1f}s.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(path), '-frames:v', '1',
                        '-vf', 'scale=540:-2', str(out)], check=True)
        if out.exists():
            paths.append((t, out))
    return paths


def measure(path, folder):
    info = probe(path)
    m = motion(frames_gray(path))
    samples = audio(path) if info['has_audio'] else np.zeros(0, np.float32)
    words = transcribe(samples)
    end = info['seconds'] or 0
    # after every cut or beat once the picture has settled (a slide animates in for about a second), and the ending
    times = sorted({*KEY_TIMES, *[c + SETTLE for c in (m['cuts'] or m['beats'])], *([end - 1.0] if end else [])})
    times = [round(t, 1) for t in times if not end or t < end]
    times = times[:MAX_FRAMES - 1] + times[-1:] if len(times) > MAX_FRAMES else times
    return {**info, **m, **speech(words, info['seconds'] or 0), 'loudness': loudness(samples)[:60]}, words, \
        key_frames(path, times, folder)


# ---------- Claude's breakdown ----------

SYSTEM = """You study a short vertical video (an Instagram Reel or YouTube Short) that did well, for a faceless
developer account (@hassanjan.k: AI tools, coding tips, freelancing) that wants to learn what holds viewers.
You get the key frames (open each with the Read tool), numbers measured by code, and a timed transcript.

Explain what the video does, second by second where it matters, and why it holds people: what is on screen in the
first second, the hook (spoken and on screen), how fast the picture changes, the structure, the text style, the
payoff and the call to action. Be concrete and tie claims to the frames and numbers; say when something is a guess.

Then split what could be learned into:
- adoptable: patterns this account could try, each with how it would look in its reels and a test idea (one
  thing to change in half of the reels, so the numbers decide). Patterns only: never copy the video's script,
  wording, visuals, jokes or ideas as the creator's own.
- not_adoptable: patterns that would break the creator's hard rules: showing faces, people or animals, any music,
  anything dishonest or invented (fake results, made-up stories), content from Reddit, or copying. Say which rule.
The account's own reels today, for comparison, are described in the prompt.
Fill every field with real observations, never a placeholder. If the video has no speech, say so in hook.spoken
("no speech"); if there is no text on screen, say so in hook.on_screen ("no text on screen")."""

SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['first_second', 'hook', 'structure', 'pacing', 'why_it_works', 'adoptable', 'not_adoptable'],
          'properties': {
              'first_second': {'type': 'string'},
              'hook': {'type': 'object', 'additionalProperties': False, 'required': ['spoken', 'on_screen', 'type'],
                       'properties': {'spoken': {'type': 'string'}, 'on_screen': {'type': 'string'},
                                      'type': {'type': 'string'}}},
              'structure': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                                       'required': ['at', 'what'],
                                                       'properties': {'at': {'type': 'string'}, 'what': {'type': 'string'}}}},
              'pacing': {'type': 'string'},
              'why_it_works': {'type': 'array', 'items': {'type': 'string'}},
              'adoptable': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                                       'required': ['pattern', 'for_us', 'test'],
                                                       'properties': {'pattern': {'type': 'string'},
                                                                      'for_us': {'type': 'string'},
                                                                      'test': {'type': 'string'}}}},
              'not_adoptable': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                                           'required': ['pattern', 'rule'],
                                                           'properties': {'pattern': {'type': 'string'},
                                                                          'rule': {'type': 'string'}}}}}}


def ours():
    """How the account's own reels open and do, for the comparison."""
    latest = {}
    for s in history.snapshots():
        if s['kind'] == 'reel':
            latest[s['id']] = s
    skip = [s['reels_skip_rate'] for s in latest.values() if isinstance(s.get('reels_skip_rate'), (int, float))]
    watch = [s['ig_reels_avg_watch_time'] for s in latest.values() if isinstance(s.get('ig_reels_avg_watch_time'), (int, float))]
    numbers = (f'Across {len(skip)} measured reels: median skip rate {statistics.median(skip):.1f}%, median watch '
               f'time {statistics.median(watch) / 1000:.1f}s.' if skip and watch else 'No numbers yet.')
    return ('Our reels: 15 to 25 seconds, faceless, an AI voiceover (about 2.6 words a second) with burnt-in captions '
            'and sound effects, no music. They open on a big text card with the hook for 4 to 5 seconds, then three '
            'point slides, each with a visual (code, terminal, diff, screenshot, chat, 3D diagram), then a question. '
            'The picture changes mostly at slide changes, with camera punches on each sentence. ' + numbers)


def claude(prompt, folder):
    proc = subprocess.run(['claude', '-p', prompt, '--model', os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5'),
                           '--system-prompt', SYSTEM, '--tools', 'Read', '--allowedTools', 'Read', '--add-dir', str(folder),
                           '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
                           '--json-schema', json.dumps(SCHEMA)],
                          capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
    out = json.loads(proc.stdout).get('structured_output')
    if not out:
        raise RuntimeError('claude returned no structured output')
    return out


def breakdown(meta, metrics, words, frames, folder):
    said = ' '.join(f'[{s:.1f}] {w.strip()}' for w, s, _ in words) or '(no speech found, or no transcript)'
    prompt = ('The video: ' + json.dumps(meta, ensure_ascii=False)
              + '\n\nMeasured: ' + json.dumps({k: v for k, v in metrics.items() if k != 'loudness'})
              + '\nLoudness every 0.5s (dBFS): ' + json.dumps(metrics['loudness'])
              + '\n\nTranscript with start times:\n' + said
              + '\n\nKey frames (open each):\n' + '\n'.join(f'{t:.1f}s: {p}' for t, p in frames)
              + '\n\n' + ours())
    analysis = claude(prompt, folder)
    problems = empty_fields(analysis)
    if problems:  # it once came back with "placeholder" in the hook: ask again, naming what was missing
        analysis = claude(prompt + '\n\nYour last answer left these empty or as placeholders: ' + ', '.join(problems)
                          + '. Fill every field from the frames, numbers and transcript.', folder)
        problems = empty_fields(analysis)
        if problems:
            raise RuntimeError('the breakdown left fields empty: ' + ', '.join(problems))
    return analysis


PLACEHOLDER = re.compile(r'^\s*(placeholder|todo|tbd|n/?a|none|null|-|\.\.\.)?\s*$', re.I)


def empty_fields(a):
    """The fields of a breakdown that are empty or a placeholder word."""
    missing = [k for k in ('first_second', 'pacing') if PLACEHOLDER.match(a.get(k) or '')]
    missing += [f'hook.{k}' for k in ('spoken', 'on_screen', 'type') if PLACEHOLDER.match(a.get('hook', {}).get(k) or '')]
    missing += [k for k in ('structure', 'why_it_works') if not a.get(k)]
    return missing


# ---------- saving ----------

def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', (text or 'video').lower()).strip('-')[:50] or 'video'


def report(meta, m, a):
    f = lambda v, unit='': '-' if v is None else f'{v}{unit}'
    lines = [f"# Study: {meta.get('title') or meta['source']}",
             f"{meta['source']}" + (f" by {meta['channel']}" if meta.get('channel') else '')
             + (f" · {meta['views']:,} views" if meta.get('views') else '')
             + (f" · {meta['followers']:,} followers" if meta.get('followers') else ''),
             '## Measured',
             f"- {f(m['seconds'], 's')} long, {f(m['width'])}x{f(m['height'])}; {len(m['cuts'])} cuts "
             f"({m['cuts_per_10s']} every 10 s), first cut at {f(m['first_cut'], 's')}; {len(m['beats'])} beats (the "
             f"picture changes noticeably: {m['beats_per_10s']} every 10 s); moving {m['moving_share']:.0%} "
             f"of the time; first change at {f(m['first_change'], 's')}; "
             + ('opens on a blank frame' if m['blank_start'] else 'something on screen from frame one'),
             f"- Speech starts at {f(m['speech_start'], 's')}, {f(m['words_per_second'])} words a second, "
             f"{m['words_first_3s']} words in the first 3 s, longest pause {f(m['longest_pause'], 's')}",
             '## First second', a['first_second'],
             f"## Hook\n- Said: {a['hook']['spoken']}\n- On screen: {a['hook']['on_screen']}\n- Type: {a['hook']['type']}",
             '## Structure\n' + '\n'.join(f"- {s['at']}: {s['what']}" for s in a['structure']),
             '## Pacing\n' + a['pacing'],
             '## Why it works\n' + '\n'.join(f'- {w}' for w in a['why_it_works']),
             '## What we could test\n' + ('\n'.join(f"- **{p['pattern']}**: {p['for_us']} Test: {p['test']}"
                                                   for p in a['adoptable']) or '- nothing new'),
             '## Not for us\n' + ('\n'.join(f"- {p['pattern']} ({p['rule']})" for p in a['not_adoptable']) or '- nothing')]
    return '\n\n'.join(lines) + '\n'


def save(meta, m, a, text, day):
    STUDIES.mkdir(exist_ok=True)
    path = STUDIES / f"{day.isoformat()}-{slug(meta.get('title') or meta['source'])}.md"
    path.write_text(text)
    with open(INDEX, 'a') as fh:
        fh.write(json.dumps({'date': day.isoformat(), **{k: meta.get(k) for k in ('source', 'title', 'channel', 'views', 'followers')},
                             **{k: m[k] for k in ('seconds', 'cuts_per_10s', 'beats_per_10s', 'first_cut', 'moving_share', 'blank_start',
                                                  'speech_start', 'words_per_second', 'words_first_3s')},
                             'adoptable': [p['pattern'] for p in a['adoptable']], 'file': path.name},
                            ensure_ascii=False) + '\n')
    return path


def study(source, token=None, extra=None):
    with tempfile.TemporaryDirectory() as tmp:
        path, meta = fetch(source, tmp, token)
        meta.update({k: v for k, v in (extra or {}).items() if v is not None})
        print(f"Studying {meta.get('title') or source}")
        metrics, words, frames = measure(path, tmp)
        analysis = breakdown(meta, metrics, words, frames, tmp)
        text = report(meta, metrics, analysis)
        saved = save(meta, metrics, analysis, text, datetime.now(timezone.utc).date())
        print(f'  saved studies/{saved.name}')
        return text


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if not shutil.which('ffmpeg'):
        raise SystemExit('ffmpeg is needed on PATH')
    todo = []  # (source, extra meta)
    if '--search' in args:
        top = int(args[args.index('--top') + 1]) if '--top' in args else 3
        key = os.environ.get('YOUTUBE_API_KEY', '').strip()
        if not key:
            raise SystemExit('--search needs YOUTUBE_API_KEY')
        for pick in search(args[args.index('--search') + 1], top, key):
            print(f"Found {pick['url']}: {pick['views']:,} views, {pick['followers']:,} subscribers ({pick['outlier']}x)")
            todo.append((pick['url'], {k: pick[k] for k in ('title', 'channel', 'views', 'followers')}))
    elif '--issue' in args:
        todo = [(s, None) for s in sources_in(os.environ.get('ISSUE_BODY', ''))]
    else:
        todo = [(s, None) for s in args if not s.startswith('--')]
    if not todo:
        raise SystemExit('No videos to study')
    texts, failed = [], []
    for source, extra in todo:
        try:
            texts.append(study(source, os.environ.get('GH_TOKEN'), extra))
        except Exception as e:  # one bad link must not stop the others
            print(f'  failed: {source}: {type(e).__name__}: {str(e)[:300]}')
            failed.append(f'- {source}: {str(e)[:200]}')
    render.OUT_DIR.mkdir(exist_ok=True)
    OUT.write_text('\n\n---\n\n'.join(texts) + ('\n\n**Could not study:**\n' + '\n'.join(failed) if failed else '') + '\n')
    if not texts:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
