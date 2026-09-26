"""Spoken voiceover for a reel, synthesized locally with Kokoro (free, CPU).

Usage: python voice.py <id> [voice]   renders out/reel-<id>-<voice>.mp4
"""

import difflib
import json
import re
import subprocess
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
    (r'\b(\d+)\.(\d+)\.(\d+)\b', r'\1 point \2 point \3'),
    (r'\b(\d+)\.x\b', r'\1 point x'),
    (r'\$0\.(\d\d)\b', lambda m: f'{int(m.group(1))} cents'),
    (r'\band/or\b', 'and or'),
    (r'\bog\b', 'O G'),
    (r'(?<=\w)@(?=\w)', ' at '),
    (r'(?<=\w)/(?=\w)', ' slash '),
    (r'\$(\d+(?:\.\d+)?)([KMB]?)\b', lambda m: m.group(1) + {'K': ' thousand', 'M': ' million', 'B': ' billion', '': ''}[m.group(2)] + ' dollars'),
    (r'\b(\d+(?:\.\d+)?)K\b', r'\1 thousand'),
    (r'\b(\d+(?:\.\d+)?)M\b', r'\1 million'),
    (r'\b(\d+(?:\.\d+)?)B\b', r'\1 billion'),
    # Otherwise "5.6" is read as the end of a sentence ("GPT 5. Six").
    (r'\b(\d+)\.(\d+)\b', r'\1 point \2'),
    (r'(\d)%', r'\1 percent'),
]


LEXICON = render.ROOT / 'pronounce.json'
WHISPER_MODEL = 'small.en'
RESPELL_TRIES = 3
NUMBER_WORDS = set('''zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen
sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million
billion point percent dollars dollar cents x'''.split())


def lexicon():
    """Respellings learned by the listen-back check, e.g. {"Supabase": "Soopa base"}."""
    return json.loads(LEXICON.read_text()) if LEXICON.exists() else {}


def plain(text):
    return text.replace('*', '')


def speakable(text, extra=None):
    text = plain(text)
    for word, spoken in {**lexicon(), **(extra or {})}.items():
        text = re.sub(rf'(?<![\w.]){re.escape(word)}(?![\w])', spoken, text)
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


class Engine:
    def __init__(self, voice=DEFAULT_VOICE, speed=1.05):
        from kokoro_onnx import Kokoro
        ensure_model()
        self.tts = Kokoro(str(MODEL_DIR / MODEL_FILES[0]), str(MODEL_DIR / MODEL_FILES[1]))
        self.voice, self.speed = voice, speed

    def say(self, text):
        samples, sr = self.tts.create(text, voice=self.voice, speed=self.speed, lang='en-us')
        n = int(len(samples) * render.SR / sr)
        return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)


# ---------- listen-back check ----------

_whisper = None
_written_lower = set()


def transcribe(clip):
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8',
                                download_root=str(MODEL_DIR / 'whisper'))
    audio = np.interp(np.arange(0, len(clip), render.SR / 16000), np.arange(len(clip)), clip).astype(np.float32)
    segments, _ = _whisper.transcribe(audio, language='en', beam_size=5)
    return ' '.join(s.text for s in segments)


def tokens(text):
    return re.sub(r'[^a-z0-9 ]', ' ', plain(text).lower().replace('-', ' ').replace('.', ' ')).split()


def misheard(written, heard):
    """Words of the written line that did not come back in the transcript. Numbers are skipped:
    they are handled by the rules above and transcripts write them in too many ways."""
    a, b = tokens(written), tokens(heard)
    global _written_lower
    _written_lower = set(re.findall(r'\b[a-z]+\b', plain(written)))
    bad = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == 'equal':
            continue
        want, got = ''.join(a[i1:i2]), ''.join(b[j1:j2])
        # "next js" vs "nextjs", or "ORMs" vs "ORM"
        if want == got or (got and want.rstrip('s') == got.rstrip('s')):
            continue
        # A correctly spoken common word can come back as its homophone ("caches" as "cashes").
        # Brand and tech names stay strict: they are the words the voice actually gets wrong.
        if i2 - i1 == j2 - j1 and all(common(w) and metaphone(w) == metaphone(h) for w, h in zip(a[i1:i2], b[j1:j2])):
            continue
        bad += [w for w in a[i1:i2] if not w.isdigit() and w not in NUMBER_WORDS]
    # Map lowercased tokens back to how the word is written in the line, keeping a leading dot (".env").
    written_words = [w.rstrip('.') for w in re.findall(r"[\w.'-]+", plain(written))]
    return sorted({next((w for w in written_words if t in tokens(w)), t) for t in bad})


def common(word):
    return word.isalpha() and word == word.lower() and word in _written_lower


def metaphone(word):
    import jellyfish
    return jellyfish.metaphone(word)


def closeness(word, line, heard):
    """How close the transcript came to the written line, used to pick the least bad respelling."""
    return difflib.SequenceMatcher(None, ''.join(tokens(line)), ''.join(tokens(heard))).ratio()


def ask_respellings(words, line):
    """Phonetic respellings from Claude, best first. Empty when Claude is unavailable."""
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['words'], 'properties': {'words': {
        'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['word', 'options'],
                                   'properties': {'word': {'type': 'string'},
                                                  'options': {'type': 'array', 'items': {'type': 'string'}}}}}}}
    prompt = (f'A text-to-speech voice mispronounces these words in the sentence "{line}": {", ".join(words)}.\n'
              f'For each word give {RESPELL_TRIES} respellings, best first, using plain English letters and spaces '
              'so the voice says it the way developers say it out loud (e.g. "Supabase" -> "Soopa base", '
              '"Nginx" -> "Engine X", ".env" -> "dot E N V"). Keep brand casing where it helps.')
    try:
        proc = subprocess.run(['claude', '-p', prompt, '--model', 'claude-sonnet-5', '--tools', '',
                               '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
                               '--json-schema', json.dumps(schema)],
                              capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
        out = json.loads(proc.stdout).get('structured_output') or {}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f'  warning: could not ask for respellings ({type(e).__name__})')
        return {}
    got = {w['word'].lower(): w['options'][:RESPELL_TRIES] for w in out.get('words', [])}
    return {w: got.get(w.lower(), []) for w in words}


def say_checked(engine, line):
    """Speak a line, listen back, and respell any word the voice gets wrong. Learned fixes go in pronounce.json."""
    clip = engine.say(speakable(line))
    bad = misheard(line, transcribe(clip))
    if not bad:
        return clip
    print(f'  misheard {bad} in: {line}')
    learned = lexicon()
    for word, options in ask_respellings(bad, line).items():
        best, best_score = None, closeness(word, line, transcribe(clip))
        for option in options:
            heard = transcribe(engine.say(speakable(line, {word: option})))
            if word not in misheard(line, heard):
                print(f'  fixed {word!r} -> {option!r}')
                learned[word] = option
                break
            if closeness(word, line, heard) > best_score:
                best, best_score = option, closeness(word, line, heard)
        else:
            print(f'  warning: no respelling of {word!r} was understood' + (f', using the closest: {best!r}' if best else ''))
            if best:
                learned[word] = best
    LEXICON.write_text(json.dumps(dict(sorted(learned.items())), indent=2, ensure_ascii=False) + '\n')
    # Re-speak with every fix applied together.
    return engine.say(speakable(line))


def synthesize(lines, voice=DEFAULT_VOICE, speed=1.05, check=True):
    engine = Engine(voice, speed)
    return [say_checked(engine, line) if check else engine.say(speakable(line)) for line in lines]


def main():
    reel = render.load_reel(sys.argv[1])
    voice = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VOICE
    clips = synthesize(script(reel), voice)
    out = render.OUT_DIR / f"reel-{reel['id']}-{voice}.mp4"
    render.render_reel(reel, out, voice=clips)


if __name__ == '__main__':
    main()
