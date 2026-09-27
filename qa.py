"""Look at a rendered reel the way a viewer would: Claude reviews one frame per slide.

A visual (code, terminal, screenshot) that is irrelevant, unreadable or broken (cookie banner, login wall,
error page, blank page) is reported so publish.py can re-render that slide as text. Other problems are
returned as warnings.

Usage: python qa.py <id>   renders reel <id> with its voice and prints the review
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import render
from voice import strip_cues

SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['slides'],
    'properties': {'slides': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['slide', 'ok', 'visual_ok', 'honest', 'problem'],
        'properties': {'slide': {'type': 'integer'}, 'ok': {'type': 'boolean'}, 'visual_ok': {'type': 'boolean'},
                       'honest': {'type': 'boolean'}, 'problem': {'type': 'string'}}}}},
}

SYSTEM = """You review frames of an Instagram Reel before it is posted, as a strict editor who wants every
second to be worth watching. For each slide you get one frame, the words spoken over it and, if it has one,
what its visual is meant to show.

Judge each frame:
- visual_ok: the visual (code window, terminal or website screenshot) clearly shows something that matches
  what is being said, is readable on a phone, and is not a cookie banner, login wall, error page, empty page,
  generic homepage or logo with nothing relevant. Use true when the slide has no visual.
- ok: the whole frame looks professional: no text cut off, overlapping or running outside the frame, nothing
  broken, captions readable.
- honest: false only for deception: claimed results that are not real (income, revenue, followers, metrics),
  an invented scene presented as a real event, "I tested/built" without the reel showing it, someone else's
  work shown as the creator's own, or a claim that the listed sources contradict. News claims that the
  sources support are honest even if dramatic. A visual that does not match what is said is not dishonest:
  mark visual_ok false instead. Otherwise true.
- problem: one short sentence on what is wrong, or an empty string.
Be strict about visuals: when in doubt whether a screenshot shows the point, visual_ok is false."""


def frames(video, slides, folder):
    """One frame per slide, late enough that its text and visual are fully in."""
    paths = []
    for i, s in enumerate(slides):
        t = s.start + min(max(1.2, (s.end - s.start) * 0.6), s.end - s.start - render.EXIT - 0.05)
        path = Path(folder) / f'slide-{i}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(video), '-frames:v', '1',
                        '-vf', 'scale=540:-1', str(path)], check=True)
        paths.append(path)
    return paths


def review(video, reel, slides, voiceover=None):
    """[{slide, ok, visual_ok, problem}] for every slide; slide 0 is the hook, 1 to 3 the points, 4 the CTA."""
    spoken = [strip_cues(l) for l in (voiceover or reel.get('voiceover') or [''] * len(slides))]
    with tempfile.TemporaryDirectory() as tmp:
        paths = frames(video, slides, tmp)
        lines = []
        for i, path in enumerate(paths):
            visual = slides[i].visual.spec if slides[i].visual else None
            meant = ''
            if visual:
                meant = {'code': 'a code window', 'terminal': 'a terminal typing commands',
                         'diff': 'code before and after (removed lines red, added lines green)',
                         'tweet': "a post card in the creator's own name", 'chat': 'a Client / Me chat (POV)',
                         'walkthrough': 'a real screen recording of ' + visual.get('url', ''),
                         'ide': 'a real VS Code recording typing and running code',
                         'quote': 'a credited quote of a real public post by ' + visual.get('author', ''),
                         'word': 'the hook word "' + visual.get('text', '') + '" as 3D text',
                         'diagram': 'a 3D diagram of ' + ', '.join(n.get('label', '') for n in visual.get('nodes', []))
                                    + ' with a packet moving along the flow',
                         'device': 'a 3D ' + visual.get('device', 'laptop') + ' showing '
                                   + (visual.get('show') or {}).get('type', 'code'),
                         'bars': '3D bars: ' + ', '.join(f"{b.get('label')} {b.get('value')}{visual.get('unit', '')}"
                                                         for b in visual.get('bars', []))
                                 + ', numbers from ' + visual.get('source', 'no source') + ' (check them)',
                         'logos': '3D logos: ' + ', '.join(visual.get('items', [])),
                         }.get(visual['type'], 'a screenshot of ' + visual.get('url', '') + ' with "'
                               + visual.get('find', '') + '" outlined')
            lines.append(f'Slide {i}: frame {path}\n  spoken: {spoken[i] if i < len(spoken) else ""}\n'
                         f'  visual: {meant or "none"}')
        sources = reel.get('sources') or []
        checked = ('\n\nThe reel\'s claims were fact-checked against these sources (open them if a claim looks '
                   'doubtful):\n' + '\n'.join(sources)) if sources else ''
        if reel.get('dm_guide'):
            checked += (f"\n\nPeople who comment {reel.get('dm_keyword')} are sent this guide by DM. honest is false for "
                        'the CTA slide if the reel promises more than this guide holds, or if the guide states '
                        f"something untrue:\n{reel['dm_guide']}")
        prompt = 'Open each frame with the Read tool and review it.\n\n' + '\n'.join(lines) + checked
        proc = subprocess.run(
            ['claude', '-p', prompt, '--model', os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5'),
             '--system-prompt', SYSTEM, '--tools', 'Read', 'WebFetch', '--allowedTools', 'Read', 'WebFetch',
             '--add-dir', tmp,
             '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(SCHEMA)],
            capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
        )
    if proc.returncode != 0:
        raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
    out = json.loads(proc.stdout).get('structured_output') or {}
    return out.get('slides', [])


def main():
    import sys
    import voice
    reel = render.load_reel(sys.argv[1])
    clips = voice.synthesize(voice.script(reel))
    path, slides = render.render_reel(reel, voice=clips)
    for r in review(path, reel, slides):
        print(r)


if __name__ == '__main__':
    main()
