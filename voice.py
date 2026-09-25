"""Spoken voiceover for a reel, synthesized locally with Kokoro (free, CPU).

Usage: python voice.py <id> [voice]   renders out/reel-<id>-voice.mp4
"""

import re
import sys
from pathlib import Path

import numpy as np

import render

MODEL_DIR = render.ROOT / 'models'
MODEL_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{}'
MODEL_FILES = ('kokoro-v1.0.onnx', 'voices-v1.0.bin')
DEFAULT_VOICE = 'am_michael'


def spell(letters):
    # A lone "A" is read as the article "uh".
    return ' '.join('Ay' if c == 'A' else c for c in letters)


# Plural acronyms lose their "s" otherwise ("MVPs" is read as "MVP").
PLURAL_LETTER = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', (
    'Ays Bees Sees Dees Ees Effs Gees Aitches Eyes Jays Kays Els Ems Ens Ohs Pees Cues Ars Esses Tees '
    'Yous Vees Doubleyous Exes Whys Zees').split()))

# Respellings for terms the voice gets wrong; checked against its phonemes. Order matters.
PRONOUNCE = [
    (r'\bPostgreSQL\b', 'post gress Q L'),
    (r'\bPostgres\b', 'post gress'),
    (r'\bSaaS\b', 'sass'),
    (r'\bSupabase\b', 'soopa base'),
    (r'\b([A-Z][A-Za-z]*)\.js\b', r'\1 J S'),
    (r'\bCI/CD\b', 'C I C D'),
    (r'\.env\b', 'dot env'),
    (r'\be\.g\.', 'for example'),
    (r'\bi\.e\.', 'that is'),
    (r'\bvs\.?(?=\s)', 'versus'),
    (r'\bVercel\b', 'ver sell'),
    (r'\bRedis\b', 'red iss'),
    (r'\bVite\b', 'veet'),
    (r'\bLinkedIn\b', 'Linked In'),
    (r'\b([A-Z]{2,5})s\b', lambda m: spell(m.group(1)[:-1]) + ' ' + PLURAL_LETTER[m.group(1)[-1]]),
    (r'\b(CLI|UX|IDE|ROI|SEO)\b', lambda m: spell(m.group(1))),
    (r'&', ' and '),
]


def plain(text):
    return text.replace('*', '')


def speakable(text):
    text = plain(text)
    for pattern, repl in PRONOUNCE:
        text = re.sub(pattern, repl, text)
    return re.sub(r'\s+', ' ', text).strip()


def script(reel):
    """One spoken line per slide. Uses the reel's own voiceover lines when present."""
    if reel.get('voiceover'):
        return reel['voiceover']
    lines = [plain(reel['hook'])]
    for p in reel['points']:
        lines.append(f"{plain(p['title'])}. {p['body']}")
    lines.append(f"{plain(reel['cta'])} Comment below, and follow for daily dev and AI tips.")
    return lines


def ensure_model():
    import urllib.request
    MODEL_DIR.mkdir(exist_ok=True)
    for name in MODEL_FILES:
        path = MODEL_DIR / name
        if not path.exists():
            print(f'Downloading {name}')
            urllib.request.urlretrieve(MODEL_URL.format(name), path)


def synthesize(lines, voice=DEFAULT_VOICE, speed=1.05):
    from kokoro_onnx import Kokoro
    ensure_model()
    tts = Kokoro(str(MODEL_DIR / MODEL_FILES[0]), str(MODEL_DIR / MODEL_FILES[1]))
    clips = []
    for line in lines:
        samples, sr = tts.create(speakable(line), voice=voice, speed=speed, lang='en-us')
        n = int(len(samples) * render.SR / sr)
        clips.append(np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples))
    return clips


def main():
    reel = render.load_reel(sys.argv[1])
    voice = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VOICE
    clips = synthesize(script(reel), voice)
    out = render.OUT_DIR / f"reel-{reel['id']}-{voice}.mp4"
    render.render_reel(reel, out, voice=clips)


if __name__ == '__main__':
    main()
