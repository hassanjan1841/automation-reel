"""Post a ready-made video as a Reel, outside the daily pipeline: a one-off like a project showcase that was edited
elsewhere. It does not write, render or review anything; it uploads the file, publishes it with the caption and
cover, deletes the upload and records the post in extras.json (--voice records a voiceover for such a video first).
To post at a set time, add an entry to extras.json with video, caption_file, cover (optional), post_at (ISO time
with offset) and media_id null: scheduler.py starts post-video.yml shortly before, and this waits for the minute. A video already recorded there with a media id
is never posted twice (FORCE_POST=true overrides).

Usage: python post_video.py <video.mp4> <caption.txt> [cover.jpg]
       python post_video.py --voice <lines.txt>   records a voiceover for such a video with the daily reels'
           voice (voice.synthesize: one take, checked by listening back), one line per line of the file, into
           out/voice/line-<n>.wav plus out/voice/voice.json (each line's words with their times, and the verdict),
           for the video's editor to mix in and caption

Env:
  IG_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY, GRAPH_VERSION   as in publish.py
  DRY_RUN=true          check the files and print the caption, post nothing
  FORCE_POST=true       post even if extras.json already has this video
  VOICE_ENGINE, VOICE, VOICE_SPEED, VOICE_PITCH, FISH_API_KEY, FISH_MODEL   for --voice, as in voice.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import publish

LOG = Path(__file__).parent / 'extras.json'
MAX_CAPTION = 2200  # Instagram's caption limit
MAX_WAIT = 30 * 60  # longest wait for a queued post_at; the Scheduler starts the run about 15 minutes before


def load():
    return json.loads(LOG.read_text()) if LOG.exists() else []


def record_voice(lines_file):
    import soundfile

    import render
    import voice
    lines = [l.strip() for l in Path(lines_file).read_text().splitlines() if l.strip()]
    clips = voice.synthesize(lines, os.environ.get('VOICE') or None)
    out = Path(__file__).parent / 'out' / 'voice'
    out.mkdir(parents=True, exist_ok=True)
    info = {'verdict': clips.verdict, 'continuous': clips.continuous, 'sample_rate': render.SR, 'lines': []}
    for i, (line, clip) in enumerate(zip(lines, clips)):
        soundfile.write(out / f'line-{i + 1}.wav', clip, render.SR)
        info['lines'].append({'text': voice.strip_cues(line), 'file': f'line-{i + 1}.wav',
                              'seconds': round(len(clip) / render.SR, 3),
                              'words': [[w, round(a, 3), round(b, 3)] for w, a, b in clips.words[i]]})
    (out / 'voice.json').write_text(json.dumps(info, indent=2) + '\n')
    print(f'Voiceover: {len(lines)} lines, {sum(l["seconds"] for l in info["lines"]):.1f} s, {clips.verdict}')


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--voice':
        return record_voice(sys.argv[2])
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    video, caption_file = Path(sys.argv[1]), Path(sys.argv[2])
    cover = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None
    for p in (video, caption_file) + ((cover,) if cover else ()):
        if not p.is_file():
            sys.exit(f'{p} not found')
    caption = caption_file.read_text().strip()
    if not caption or len(caption) > MAX_CAPTION:
        sys.exit(f'caption must be 1 to {MAX_CAPTION} characters, got {len(caption)}')

    log = load()
    done = [e for e in log if e['video'] == str(video) and e.get('media_id')]
    if done and os.environ.get('FORCE_POST') != 'true':
        print(f"{video} was already posted ({done[-1]['media_id']}); set FORCE_POST=true to post it again")
        publish.output('posted', 'false')
        return

    print(f'Video {video} ({video.stat().st_size / 1e6:.1f} MB), cover {cover or "none"}\nCaption:\n{caption}\n')
    if os.environ.get('DRY_RUN') == 'true':
        print('DRY_RUN: not posting')
        publish.output('posted', 'false')
        return
    queued = next((e for e in log if e['video'] == str(video) and not e.get('media_id') and e.get('post_at')), None)
    if queued:
        wait = (datetime.fromisoformat(queued['post_at']) - datetime.now(timezone.utc)).total_seconds()
        if 0 < wait <= MAX_WAIT:
            print(f"Waiting {wait / 60:.0f} min for {queued['post_at']}", flush=True)
            time.sleep(wait)

    stamp = int(time.time())
    name = f'extra-{video.stem}-{stamp}.mp4'
    cover_name = f'extra-{video.stem}-{stamp}-cover.jpg' if cover else None
    url = publish.upload(video, name)
    cover_url = publish.upload(cover, cover_name, 'image/jpeg') if cover else None
    try:
        media_id = publish.publish_to_instagram(url, caption, 0, cover_url)
    finally:
        publish.delete_upload(name)
        if cover_name:
            publish.delete_upload(cover_name)
    record = {'video': str(video), 'caption': caption, 'media_id': media_id,
              'posted_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if queued:
        queued.update(record)
    else:
        log.append(record)
    LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False) + '\n')
    print(f'Posted {video} as {media_id}')
    publish.output('posted', 'true')


if __name__ == '__main__':
    main()
