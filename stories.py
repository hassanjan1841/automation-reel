"""Instagram stories after each reel (asked 2026-10-22: "is it possible for you to set the stories", then "do
both"). Right after a reel posts:

1. Guess the output (at most one a day): when the reel is a Myth vs fact that opens on real code that prints
   something (console.log, print), a still story shows that same code under "GUESS THE OUTPUT" and says the answer
   is in the new reel. The reel proves the real output, so the story asks nothing the reel does not answer.
2. The teaser: the reel's first seconds, then a card "NEW REEL / on my profile" with the reel's hook.

Both go up through Instagram's content publishing API (media_type=STORIES, read 2026-10-22 on
developers.facebook.com: images or videos; link, poll and location stickers are not supported, and stories expire
after 24 hours). Nothing is written fresh: the code, the hook and the video are the reel's own. The story ids are
recorded on the reel (`stories` in reels.json), so nothing goes up twice; a failure never touches the reel's record.

Usage:
  python stories.py reel <id>    make and post the stories for reel <id> (out/reel-<id>.mp4)
Env: IG_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY, GRAPH_VERSION (as in publish.py); STORIES=off posts none;
     DRY_RUN=true makes the files in out/stories/ and posts nothing.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

import render

OUT = render.OUT_DIR / 'stories'
TEASER_SECONDS = 5.0      # how much of the reel the teaser shows
CARD_SECONDS = 2.5        # the "new reel" card after it
PRINTS = re.compile(r'\bconsole\.log\(|\bprint\(|\becho\b')
BG, INK, MUTE = (9, 10, 15), (242, 243, 247), (140, 147, 166)


# ---------- what to post ----------

def puzzle_code(reel):
    """The reel's opening code when it is a guess-the-output puzzle (a Myth vs fact that opens on code that prints),
    else None."""
    hv = reel.get('hook_visual') or {}
    code = str(hv.get('code') or '')
    if reel.get('series') != 'Myth vs fact' or hv.get('type') != 'code' or not PRINTS.search(code):
        return None
    return code


def puzzled_today(reels, now):
    """True when a reel posted today already carried the day's puzzle story."""
    day = now.date().isoformat()
    return any(str(r.get('posted_at', ''))[:10] == day and any(s.get('kind') == 'puzzle' for s in r.get('stories') or [])
               for r in reels)


# ---------- the images and the teaser ----------

def display(size):
    """Anton, the reels' big condensed face (render.DISPLAY), or Poppins Bold when it is missing."""
    from PIL import ImageFont
    render.ensure_fonts()
    return ImageFont.truetype(str(render.DISPLAY), size) if render.DISPLAY.exists() else render.font('Bold', size)


def centered(draw, y, text, font, fill):
    w = draw.textlength(text, font=font)
    draw.text(((render.W - w) / 2, y), text, font=font, fill=fill)


def wrap(draw, text, font, width):
    lines, line = [], ''
    for word in text.split():
        test = f'{line} {word}'.strip()
        if draw.textlength(test, font=font) <= width or not line:
            line = test
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def canvas():
    img = Image.new('RGB', (render.W, render.H), BG)
    glow = Image.new('L', (render.W, render.H), 0)
    ImageDraw.Draw(glow).ellipse((140, 520, 940, 1320), fill=60)
    from PIL import ImageFilter
    img.paste(Image.new('RGB', img.size, (255, 106, 61)), mask=glow.filter(ImageFilter.GaussianBlur(220)))
    return img


def puzzle_image(reel, code, path):
    import visuals
    img = canvas()
    d = ImageDraw.Draw(img)
    accent = render.THEMES['dark']['accent']
    centered(d, 400, 'GUESS THE', display(130), INK)
    centered(d, 540, 'OUTPUT', display(130), accent)
    hv = reel['hook_visual']
    card, _ = visuals.code_image(code, hv.get('language'), hv.get('title', ''), 900, 760)
    img.paste(card, ((render.W - card.width) // 2, 760), card if card.mode == 'RGBA' else None)
    y = 760 + card.height + 80
    centered(d, y, 'What does it print?', render.font('SemiBold', 52), INK)
    centered(d, y + 80, 'The answer is in my new reel', render.font('Regular', 40), MUTE)
    centered(d, render.H - 230, render.HANDLE, render.font('Regular', 34), MUTE)
    img.save(path, quality=92)
    return path


def card_image(reel, path):
    img = canvas()
    d = ImageDraw.Draw(img)
    accent = render.THEMES['dark']['accent']
    centered(d, 640, 'NEW REEL', display(140), accent)
    centered(d, 800, 'on my profile', render.font('SemiBold', 56), INK)
    hook = reel['hook'].replace('*', '')
    for k, line in enumerate(wrap(d, hook, render.font('Regular', 46), 860)):
        centered(d, 960 + k * 64, line, render.font('Regular', 46), MUTE)
    centered(d, render.H - 230, render.HANDLE, render.font('Regular', 34), MUTE)
    img.save(path, quality=92)
    return path


def teaser_video(reel, video, path):
    """The reel's first seconds, then the card, as one 9:16 MP4 with the reel's own sound and silence under the card."""
    card = card_image(reel, OUT / f"card-{reel['id']}.jpg")
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y', '-t', str(TEASER_SECONDS), '-i', str(video),
        '-loop', '1', '-t', str(CARD_SECONDS), '-i', str(card),
        '-f', 'lavfi', '-t', str(CARD_SECONDS), '-i', f'anullsrc=r={render.SR}:cl=mono',
        '-filter_complex',
        f'[0:v]scale={render.W}:{render.H},setsar=1,fps={render.FPS},format=yuv420p[a];'
        f'[1:v]scale={render.W}:{render.H},setsar=1,fps={render.FPS},format=yuv420p,fade=t=in:d=0.3[b];'
        f'[0:a]aresample={render.SR},aformat=channel_layouts=mono,afade=t=out:st={TEASER_SECONDS - 0.4}:d=0.4[x];'
        '[a][x][b][2:a]concat=n=2:v=1:a=1[v][au]',
        '-map', '[v]', '-map', '[au]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-c:a', 'aac',
        '-b:a', '128k', '-movflags', '+faststart', str(path)], check=True)
    return path


# ---------- posting ----------

def post_story(kind, path, content_type):
    """Upload the file, publish it as a story, delete the upload; returns the story's media id."""
    import publish
    token = publish.env('IG_TOKEN')
    me = publish.ig_get('me', token, fields='user_id,username')
    ig_id = me.get('user_id') or me.get('id')
    name = f'story-{int(time.time())}-{Path(path).name}'
    url = publish.upload(path, name, content_type)
    try:
        media = {'video_url': url} if content_type == 'video/mp4' else {'image_url': url}
        cid = publish.ig_post(f'{ig_id}/media', token, media_type='STORIES', **media)['id']
        deadline = time.time() + publish.POLL_LIMIT
        while True:
            code = publish.ig_get(cid, token, fields='status_code').get('status_code')
            if code == 'FINISHED':
                break
            if code in ('ERROR', 'EXPIRED') or time.time() > deadline:
                raise publish.PublishError(f'story container {code}')
            time.sleep(publish.POLL_EVERY)
        story_id = publish.ig_post(f'{ig_id}/media_publish', token, creation_id=cid)['id']
    finally:
        publish.delete_upload(name)
    print(f'Posted the {kind} story: {story_id}')
    return story_id


def run(reel_id, now=None):
    if os.environ.get('STORIES', '').strip().lower() == 'off':
        print('STORIES=off: no stories')
        return []
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    now = now or datetime.now(timezone.utc)
    reels = json.loads(render.QUEUE.read_text())
    reel = next((r for r in reels if str(r.get('id')) == str(reel_id)), None)
    if reel is None:
        raise SystemExit(f'no reel {reel_id} in reels.json')
    if reel.get('stories'):
        print(f"Stories already posted for reel {reel_id}")
        return reel['stories']
    video = render.OUT_DIR / f'reel-{reel_id}.mp4'
    if not video.exists():
        raise SystemExit(f'{video} not found: no teaser to make')
    OUT.mkdir(parents=True, exist_ok=True)
    plan = []
    code = puzzle_code(reel)
    if code and not puzzled_today(reels, now):
        plan.append(('puzzle', puzzle_image(reel, code, OUT / f'puzzle-{reel_id}.jpg'), 'image/jpeg'))
    plan.append(('teaser', teaser_video(reel, video, OUT / f'teaser-{reel_id}.mp4'), 'video/mp4'))
    for kind, path, _ in plan:
        print(f'{kind} story: {path}')
    if dry:
        print('DRY_RUN: not posting the stories')
        return []
    posted = []
    for kind, path, content_type in plan:
        posted.append({'kind': kind, 'id': post_story(kind, path, content_type)})
        reel['stories'] = posted
        render.QUEUE.write_text(json.dumps(reels, indent=2, ensure_ascii=False) + '\n')
    return posted


def main():
    args = sys.argv[1:]
    if len(args) != 2 or args[0] != 'reel':
        raise SystemExit(__doc__)
    run(args[1])


if __name__ == '__main__':
    main()
