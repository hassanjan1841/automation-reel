"""Look at a rendered reel the way a viewer would: Claude reviews one frame per slide.

A visual (code, terminal, screenshot) that is irrelevant, unreadable or broken (cookie banner, login wall,
error page, blank page) is reported so publish.py re-renders that slide with the point's next visual choice (or as text); a rejected hook
proof is dropped. A dishonest claim (honest=false) stops the post. The frame-0 and payoff checks and other problems
are returned as warnings.

Env: CLAUDE_MODEL (optional, defaults to claude-sonnet-5)

Usage: python qa.py <id>   renders reel <id> with its voice and prints the review
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import render
from voice import strip_cues


def generate_playbook():
    import generate
    return generate.playbook()

SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['slides', 'first_frame', 'payoff'],
    'properties': {
        'first_frame': {'type': 'object', 'additionalProperties': False, 'required': ['ok', 'problem'],
                        'properties': {'ok': {'type': 'boolean'}, 'problem': {'type': 'string'}}},
        'payoff': {'type': 'object', 'additionalProperties': False, 'required': ['ok', 'problem'],
                   'properties': {'ok': {'type': 'boolean'}, 'problem': {'type': 'string'}}},
        'slides': {'type': 'array', 'items': {
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
Be strict about visuals: when in doubt whether a screenshot shows the point, visual_ok is false.

Then judge the reel as a whole, by the playbook below:
- first_frame: the very first frame (frame 0) is what the feed shows before anyone decides to stay. ok only if
  the whole hook is readable at a glance (a short phrase, not a sentence), its proof (the code, diff or screenshot
  under it) is already there and readable, and the frame is not mostly empty. problem: what to fix, or "".
- payoff: ok only if the reel really shows the promised payoff on screen (given below), clearly enough to copy or
  screenshot, and does not hold it back for a comment. problem: what is missing, or "".

""" + generate_playbook()


def first_frame(video, folder):
    path = Path(folder) / 'frame-0.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-frames:v', '1', '-vf', 'scale=540:-1', str(path)],
                   check=True)
    return path


def frames(video, slides, folder):
    """One frame per slide, as late as possible: every visual has finished animating (a diff caught mid-change
    looks garbled) and the camera still holds its push into the visual, before the release and the exit."""
    paths = []
    for i, s in enumerate(slides):
        t = s.start + max(min(1.2, s.end - s.start - 0.3), s.end - s.start - 0.9)
        path = Path(folder) / f'slide-{i}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(video), '-frames:v', '1',
                        '-vf', 'scale=540:-1', str(path)], check=True)
        paths.append(path)
    return paths


def review(video, reel, slides, voiceover=None):
    """{'slides': [{slide, ok, visual_ok, honest, problem}] (slide 0 is the hook, 1 to 3 the points, 4 the CTA),
    'first_frame': {ok, problem}, 'payoff': {ok, problem}}."""
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
                         'stepper': 'an animation stepping through code line by line with its variables changing '
                                    '(check the values are what the code really does)',
                         'flow': 'an animated request travelling between ' + ', '.join(n.get('label', '') for n in visual.get('nodes', [])),
                         'morph': 'an animation turning the before code into the after code',
                         'git': 'an animated git graph (' + visual.get('op', 'none') + ')',
                         'eventloop': 'an animation of the JavaScript event loop (call stack, Web APIs, queues, console)',
                         'structure': 'an animated ' + visual.get('structure', 'data structure') + ' changing step by step',
                         'sequence': 'an animated sequence diagram between ' + ', '.join(visual.get('actors', [])),
                         'states': 'an animated state machine: ' + ' -> '.join(visual.get('states', [])),
                         'race': 'animated bars: ' + ', '.join(f"{b.get('label')} {b.get('value')}{visual.get('unit', '')}"
                                                               for b in visual.get('bars', []))
                                 + ', numbers from ' + visual.get('source', 'no source') + ' (check them)',
                         'xray': 'an animated zoom into ' + str(visual.get('focus')) + ' showing ' + ', '.join(visual.get('inside', [])),
                         'memory': 'an animation of variables pointing at objects, references moving',
                         'outputmap': 'the output of `' + visual.get('command', '') + '` lifting out into boxes '
                                      '(check it is what that command really prints)',
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
        zero = first_frame(video, tmp)
        whole = (f"\n\nFrame 0 (the first frame): {zero}\nPromised payoff: {reel.get('payoff') or 'not stated'}")
        prompt = 'Open each frame with the Read tool and review it.\n\n' + '\n'.join(lines) + checked + whole
        proc = subprocess.run(
            ['claude', '-p', prompt, '--model', (os.environ.get('CLAUDE_MODEL') or 'claude-sonnet-5'),
             '--system-prompt', SYSTEM, '--tools', 'Read', 'WebFetch', '--allowedTools', 'Read', 'WebFetch',
             '--add-dir', tmp,
             '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
             '--json-schema', json.dumps(SCHEMA)],
            capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
        )
    if proc.returncode != 0:
        raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
    out = json.loads(proc.stdout).get('structured_output') or {}
    return {'slides': out.get('slides', []), 'first_frame': out.get('first_frame') or {},
            'payoff': out.get('payoff') or {}}


def main():
    import sys
    import voice
    reel = render.load_reel(sys.argv[1])
    clips = voice.synthesize(voice.script(reel))
    path, slides = render.render_reel(reel, voice=clips)
    print(json.dumps(review(path, reel, slides), indent=1))


if __name__ == '__main__':
    main()
