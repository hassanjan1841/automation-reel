"""Post a ready-made video as a Reel, outside the daily pipeline: a one-off like a project showcase that was edited
elsewhere. It does not write, voice, render or review anything; it uploads the file, publishes it with the caption
and cover, deletes the upload and records the post in extras.json. A video already recorded there with a media id
is never posted twice (FORCE_POST=true overrides).

Usage: python post_video.py <video.mp4> <caption.txt> [cover.jpg]

Env:
  IG_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY, GRAPH_VERSION   as in publish.py
  DRY_RUN=true          check the files and print the caption, post nothing
  FORCE_POST=true       post even if extras.json already has this video
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


def load():
    return json.loads(LOG.read_text()) if LOG.exists() else []


def main():
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
    log.append({'video': str(video), 'caption': caption, 'media_id': media_id,
                'posted_at': datetime.now(timezone.utc).isoformat(timespec='seconds')})
    LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False) + '\n')
    print(f'Posted {video} as {media_id}')
    publish.output('posted', 'true')


if __name__ == '__main__':
    main()
