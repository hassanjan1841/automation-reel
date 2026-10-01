"""Spoken voiceover for a reel: Fish Audio (API) or Kokoro (free, local CPU), checked by listening back.

Usage: python voice.py <id> [voice]   renders out/reel-<id>-<voice>.mp4

Env:
  VOICE_ENGINE   fish or kokoro (default fish when FISH_API_KEY is set, else kokoro)
  VOICE          read by publish.py (here pass [voice]): Fish voice reference id or Kokoro voice name
                 (default ThatMob / am_michael)
  VOICE_PITCH    semitones to shift the voice (default 0; shifting sounds robotic, pick a deeper voice instead)
  VOICE_SPEED    speaking speed (default 1.0, about 2.6 words a second; 1.1 felt rushed)
  FISH_API_KEY   Fish Audio API key
  FISH_MODEL     default s2.1-pro-free
"""

import difflib
import io
import json
import os
import re
import subprocess
import sys
import time

import numpy as np
import requests

import render

MODEL_DIR = render.ROOT / 'models'
MODEL_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{}'
MODEL_FILES = ('kokoro-v1.0.onnx', 'voices-v1.0.bin')
DEFAULT_VOICE = 'am_michael'
FISH_THATMOB = 'edaef7f06cf44fa58292b4c267bd61a9'


def spell(letters):
    # A lone "A" is read as the article "uh".
    return ' '.join('Ay' if c == 'A' else c for c in letters)


# Plural acronyms lose their "s" otherwise ("MVPs" is read as "MVP").
PLURAL_LETTER = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', (
    'Ays Bees Sees Dees Ees Effs Gees Aitches Eyes Jays Kays Els Ems Ens Ohs Pees Cues Ars Esses Tees '
    'Yous Vees Doubleyous Exes Whys Zees').split()))

# Kokoro reads these wrong from its own dictionary; checked against its phonemes. Order matters.
KOKORO_RULES = [
    (r'\bPostgreSQL\b', 'post gress Q L'),
    (r'\bPostgres\b', 'post gress'),
    (r'\bSaaS\b', 'sass'),
    (r'\bSupabase\b', 'soopa base'),
    (r'\b([A-Z][A-Za-z]*)\.js\b', r'\1 J S'),
    (r'\bCI/CD\b', 'C I C D'),
    (r'\.env\b', 'dot env'),
    (r'\bVercel\b', 'ver sell'),
    (r'\bRedis\b', 'red iss'),
    (r'\bVite\b', 'veet'),
    (r'\bLinkedIn\b', 'Linked In'),
    (r'\b([A-Z]{2,5})s\b', lambda m: spell(m.group(1)[:-1]) + ' ' + PLURAL_LETTER[m.group(1)[-1]]),
    (r'\b(CLI|UX|IDE|ROI|SEO)\b', lambda m: spell(m.group(1))),
    (r'\bog\b', 'O G'),
]

# Written forms every voice reads badly: numbers, prices and symbols.
COMMON_RULES = [
    (r'\be\.g\.', 'for example'),
    (r'\bi\.e\.', 'that is'),
    (r'\bvs\.?(?=\s)', 'versus'),
    (r'&', ' and '),
    (r'\b(\d+)\.(\d+)\.(\d+)\b', r'\1 point \2 point \3'),
    (r'\b(\d+)\.x\b', r'\1 point x'),
    (r'\$0\.(\d\d)\b', lambda m: f'{int(m.group(1))} cents'),
    (r'\band/or\b', 'and or'),
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

RULES = {'kokoro': KOKORO_RULES + COMMON_RULES, 'fish': COMMON_RULES}


LEXICON = render.ROOT / 'pronounce.json'
WHISPER_MODEL = 'small.en'
RESPELL_TRIES = 3
FINAL_TAKES = 3
# The beat between slides is silence added here, not asked of Fish: a "(long-break)" followed by a cue made it
# fill the gap with an "uhh" (2026-09-27).
BEAT = 0.3
# Whisper leaves out "uh" and "um" unless its prompt contains them; this pass is only for catching stray sounds.
FILLER_PROMPT = 'Umm, uh, er, hmm, ah. So, uh, like, you know.'
SMALL_WORDS = {'a', 'an', 'the', 'and', 'or', 'so', 'to', 'of', 'in', 'on', 'it', 'is', 'i', 'you', 'we', 'he', 'she',
               'they', 'that', 'this', 'but', 'be', 'at', 'as', 'do', 'for', 'with', 'if', 'yeah', 'yes', 'oh', 'okay'}
FILLERS = {'um', 'umm', 'uh', 'uhh', 'er', 'erm', 'ah', 'ahh', 'hmm', 'mm', 'hm', 'eh', 'r'}
EVERYDAY = set('''a an the in on at to of for and or but is are was be it its your you we they this that with
from by as not no so if then than too very just can do does did has have had will would should could file
files app apps data code server'''.split())
NUMBER_WORDS = set('''zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen
sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million
billion point percent dollars dollar cents x'''.split())


def everyday(word):
    """A common lowercase English word, as opposed to a name or tech term the voice may really get wrong."""
    if word.lower() in EVERYDAY:
        return True
    if not (word.isalpha() and word.islower()):
        return False
    from wordfreq import zipf_frequency
    return zipf_frequency(word, 'en') >= 4.0


def plain_word(word):
    """An ordinary English word, even capitalised at the start of a sentence ("Check"), but not an acronym or a
    name like "Redis"."""
    from wordfreq import zipf_frequency
    return word.isalpha() and word[1:].islower() and zipf_frequency(word.lower(), 'en') >= 4.0


def lexicon():
    """Respellings learned by the listen-back check, per engine: {"fish": {"Supabase": "Soopa base"}}."""
    data = json.loads(LEXICON.read_text()) if LEXICON.exists() else {}
    if data and all(isinstance(v, str) for v in data.values()):
        data = {'kokoro': data}
    return data


# Delivery cues for Fish: "[grinning, punchy]" directions and "(break)"-style sounds. Never spoken as words.
CUE = re.compile(r'\[[^\]]*\]|\((?:break|long-break|breath|laugh|cough|sigh|lip-smacking)\)')


def strip_cues(text):
    return re.sub(r'\s+', ' ', CUE.sub(' ', text)).strip()


def plain(text):
    return text.replace('*', '')


def speakable(text, extra=None, engine='kokoro'):
    text = plain(text) if engine == 'fish' else strip_cues(plain(text))
    for word, spoken in {**lexicon().get(engine, {}), **(extra or {})}.items():
        text = re.sub(rf'(?<![\w.]){re.escape(word)}(?![\w])', spoken, text)
    for pattern, repl in RULES[engine]:
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


def resample(samples, sr):
    n = int(len(samples) * render.SR / sr)
    return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)


def shift_pitch(clip, semitones):
    if not semitones:
        return clip
    from pedalboard import Pedalboard, PitchShift
    return Pedalboard([PitchShift(semitones=semitones)])(clip.astype(np.float32), render.SR).astype(np.float64)


class Kokoro:
    key = 'kokoro'

    def __init__(self, voice=None, speed=1.0, pitch=0.0):
        from kokoro_onnx import Kokoro as Model
        ensure_model()
        self.tts = Model(str(MODEL_DIR / MODEL_FILES[0]), str(MODEL_DIR / MODEL_FILES[1]))
        self.voice, self.speed, self.pitch = voice or DEFAULT_VOICE, speed, pitch

    def say(self, text):
        samples, sr = self.tts.create(text, voice=self.voice, speed=self.speed, lang='en-us')
        return shift_pitch(resample(samples, sr), self.pitch)


class Fish:
    key = 'fish'

    def __init__(self, voice=None, pitch=0.0, speed=1.0):
        self.token = os.environ['FISH_API_KEY'].strip()
        self.voice, self.pitch, self.speed = voice or FISH_THATMOB, pitch, speed
        self.model = os.environ.get('FISH_MODEL', '').strip() or 's2.1-pro-free'

    def say(self, text):
        import soundfile as sf
        resp = None
        for attempt in range(4):
            try:
                resp = requests.post('https://api.fish.audio/v1/tts', timeout=120,
                                     headers={'Authorization': f'Bearer {self.token}', 'model': self.model},
                                     json={'text': text, 'reference_id': self.voice, 'format': 'wav',
                                           'sample_rate': render.SR, 'normalize': True,
                                           'prosody': {'speed': self.speed}})
            except requests.RequestException as e:  # dropped or reset connections are worth another try
                print(f'  Fish request failed ({type(e).__name__}), retrying')
                time.sleep(5 * (attempt + 1))
                continue
            if resp.ok:
                samples, sr = sf.read(io.BytesIO(resp.content))
                samples = samples if samples.ndim == 1 else samples.mean(axis=1)
                return shift_pitch(resample(samples, sr), self.pitch)
            if resp.status_code not in (429, 500, 502, 503, 504):
                break
            time.sleep(5 * (attempt + 1))
        detail = f'HTTP {resp.status_code} {resp.text[:300].replace(self.token, "***")}' if resp is not None else 'no response'
        raise RuntimeError(f'Fish TTS failed: {detail}')


def engine(voice=None):
    """The configured voice engine. Fish when a key is set, otherwise the free local Kokoro."""
    name = os.environ.get('VOICE_ENGINE', '').strip().lower() or ('fish' if os.environ.get('FISH_API_KEY') else 'kokoro')
    pitch = os.environ.get('VOICE_PITCH', '').strip()
    speed = os.environ.get('VOICE_SPEED', '').strip()
    if name == 'fish':
        return Fish(voice, **({'pitch': float(pitch)} if pitch else {}), **({'speed': float(speed)} if speed else {}))
    return Kokoro(voice, **({'pitch': float(pitch)} if pitch else {}), **({'speed': float(speed)} if speed else {}))


# ---------- listen-back check ----------

_whisper = None
_written_lower = set()


def transcribe(clip, words=False, context=None):
    """The transcript, or with words=True a list of (word, start, end) in seconds. With context (the script),
    the recognizer spells names the way a viewer who reads the slides would hear them ("sass" as SaaS), so
    only real mispronunciations are left as mismatches."""
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8',
                                download_root=str(MODEL_DIR / 'whisper'))
    audio = np.interp(np.arange(0, len(clip), render.SR / 16000), np.arange(len(clip)), clip).astype(np.float32)
    segments, _ = _whisper.transcribe(audio, language='en', beam_size=5, word_timestamps=words,
                                      initial_prompt=strip_cues(plain(context)) if context else None)
    if words:
        return [(w.word, w.start, w.end) for s in segments for w in s.words]
    return ' '.join(s.text for s in segments)


def tokens(text):
    return re.sub(r'[^a-z0-9 ]', ' ', strip_cues(plain(text)).lower().replace('-', ' ').replace('.', ' ')).split()


def misheard(written, heard):
    """Words of the written line that did not come back in the transcript. Numbers are skipped:
    they are handled by the rules above and transcripts write them in too many ways."""
    a, b = tokens(written), tokens(heard)
    global _written_lower
    written = strip_cues(written)
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


def ask_respellings(words, line, phonemes=False):
    """Phonetic respellings from Claude, best first. Empty when Claude is unavailable.
    With phonemes, exact CMU ARPAbet pronunciations come first, wrapped in Fish Audio's phoneme tags."""
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['words'], 'properties': {'words': {
        'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                   'required': ['word', 'options', 'arpabet'],
                                   'properties': {'word': {'type': 'string'},
                                                  'options': {'type': 'array', 'items': {'type': 'string'}},
                                                  'arpabet': {'type': 'array', 'items': {'type': 'string'}}}}}}}
    prompt = (f'A text-to-speech voice mispronounces these words in the sentence "{line}": {", ".join(words)}.\n'
              f'For each word give {RESPELL_TRIES} respellings, best first, using plain English letters and spaces '
              'so the voice says it the way developers say it out loud (e.g. "Supabase" -> "Soopa base", '
              '"Nginx" -> "Engine X", ".env" -> "dot E N V"). Keep brand casing where it helps.\n'
              'Also give up to 2 CMU ARPAbet pronunciations of the whole word as developers say it, with stress '
              'digits, space separated (e.g. "Supabase" -> "S UW1 P AH0 B EY2 S").')
    try:
        proc = subprocess.run(['claude', '-p', prompt, '--model', 'claude-sonnet-5', '--tools', '',
                               '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
                               '--json-schema', json.dumps(schema)],
                              capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
        out = json.loads(proc.stdout).get('structured_output') or {}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f'  warning: could not ask for respellings ({type(e).__name__})')
        return {}
    tag = '<|phoneme_start|>{}<|phoneme_end|>'
    got = {w['word'].lower(): ([tag.format(p) for p in w.get('arpabet', [])[:2]] if phonemes else [])
           + w['options'][:RESPELL_TRIES] for w in out.get('words', [])}
    return {w: got.get(w.lower(), []) for w in words}


def learn(engine, line, bad):
    """Find a respelling or phoneme spelling for each misheard word and save it to pronounce.json."""
    # Everyday English ("in", "through") only looks misheard when the recognizer slips; never learn a fix for it.
    bad = [w for w in bad if not everyday(w)]
    if not bad:
        return
    everything = lexicon()
    learned = everything.setdefault(engine.key, {})
    for word, options in ask_respellings(bad, strip_cues(line), phonemes=engine.key == 'fish').items():
        best, best_score = None, None
        for option in [o for o in options if o.strip().lower() != word.lower()]:
            heard = transcribe(engine.say(speakable(line, {word: option}, engine.key)), context=line)
            if word not in misheard(line, heard):
                print(f'  fixed {word!r} -> {option!r}')
                learned[word] = option
                break
            score = closeness(word, line, heard)
            if best_score is None or score > best_score:
                best, best_score = option, score
        else:
            # Keep an earlier fix rather than swapping in a new guess that also failed.
            keep = word in learned
            print(f'  warning: no respelling of {word!r} was understood' +
                  (f', keeping {learned[word]!r}' if keep else f', using the closest: {best!r}' if best else ''))
            if best and not keep:
                learned[word] = best
    everything[engine.key] = dict(sorted(learned.items()))
    LEXICON.write_text(json.dumps(everything, indent=2, ensure_ascii=False) + '\n')


def say_checked(engine, line, with_faults=False):
    """Speak one line and keep the cleanest of a few takes (see clean_take)."""
    clip, faults = clean_take(engine, line)
    if faults:
        print(f'  warning: still unclear {faults} after {FINAL_TAKES} takes: {strip_cues(line)}')
    return (clip, faults) if with_faults else clip


class Voiceover(list):
    """Per-slide clips plus caption timing: words[i] is [(word as written, start, end)] in seconds from the
    start of clip i. continuous means the clips were cut from one recording and play back to back."""

    def __init__(self, clips, words, continuous):
        super().__init__(clips)
        self.words, self.continuous, self.verdict = words, continuous, 'not checked'


def align(line, heard):
    """Time every written word of a line from the transcript, so captions show the script's spelling
    ("Supabase", not what the recognizer wrote). Unmatched words get times between their neighbours."""
    shown = strip_cues(plain(line)).split()
    written = [(t, i) for i, w in enumerate(shown) for t in tokens(w)]
    heard_toks = [(t, start, end) for w, start, end in heard for t in tokens(w)]
    matcher = difflib.SequenceMatcher(None, [t for t, _ in written], [t for t, *_ in heard_toks], autojunk=False)
    times = {}
    for a, b, n in matcher.get_matching_blocks():
        for k in range(n):
            i = written[a + k][1]
            _, start, end = heard_toks[b + k]
            s0, e0 = times.get(i, (start, end))
            times[i] = (min(s0, start), max(e0, end))
    if not times:
        return []
    first, last = heard_toks[0][1], heard_toks[-1][2]
    out, i = [], 0
    while i < len(shown):
        if i in times:
            out.append((shown[i], *times[i]))
            i += 1
            continue
        j = i
        while j < len(shown) and j not in times:
            j += 1
        # Spread the unmatched run evenly over the gap between its matched neighbours.
        lo = times[i - 1][1] if i > 0 else min(first, times[j][0] if j < len(shown) else last)
        hi = times[j][0] if j < len(shown) else max(last, lo + 0.3 * (j - i))
        step = max(hi - lo, 0.05 * (j - i)) / (j - i)
        out += [(shown[k], lo + step * (k - i), lo + step * (k - i + 1)) for k in range(i, j)]
        i = j
    return out


def islands(audio, gap=0.12, shortest=0.08):
    """Bursts of sound separated by silence, as [(start, end)] in seconds. Quiet breaths fall below the level."""
    frame = int(render.SR * 0.01)
    rms = np.array([np.sqrt(np.mean(audio[k:k + frame] ** 2)) for k in range(0, len(audio) - frame, frame)])
    if not len(rms):
        return []
    on = rms > 0.15 * np.percentile(rms, 95)
    hold, found, k = round(gap / 0.01), [], 0
    while k < len(on):
        if not on[k]:
            k += 1
            continue
        j = k
        while j < len(on) and on[j:j + hold].any():
            j += 1
        if (j - k) * 0.01 >= shortest:
            found.append((k * 0.01, j * 0.01))
        k = j
    return found


def heard_alone(audio, start, end):
    """What one burst of sound says on its own, with no script to lean on, fillers included."""
    transcribe(audio[:render.SR // 10])  # loads the model
    c = audio[int(max(0.0, start - 0.05) * render.SR):int((end + 0.05) * render.SR)]
    c = np.interp(np.arange(0, len(c), render.SR / 16000), np.arange(len(c)), c).astype(np.float32)
    segments, _ = _whisper.transcribe(c, language='en', beam_size=5, initial_prompt=FILLER_PROMPT)
    return ' '.join(x.text for x in segments).strip()


def verify(audio, text):
    """Everything wrong with a take, listened to four ways, as (faults, strays):
    - with the script as a hint: names and tech words the voice got wrong (these get respelled);
    - without it: an everyday word said badly, which the hint papers over ("Check" as "you correct");
    - each burst of sound on its own: a burst with no word of the script in it is a stray sound (an "uhh" the
      voice invented, 2026-09-27), returned in strays as (heard, start, end) so it can be cut out;
    - the bursts' words together: an everyday word missing from either listen without the hint is a fault.
    faults are written words; an empty result is a clean take."""
    script = strip_cues(plain(text))
    bad = misheard(text, transcribe(audio, context=text))
    loose = [w for w in misheard(text, transcribe(audio)) if plain_word(w)]
    wanted = set(tokens(script))
    strays, alone = [], []
    for a, b in islands(audio):
        said = heard_alone(audio, a, b)
        heard = tokens(said)
        hits = [t for t in heard if t in wanted]
        # Mostly script words, one of them a real word: "you" alone does not make "Thank you" part of the script.
        if not heard or len(hits) < 0.6 * len(heard) or not any(t not in SMALL_WORDS for t in hits):
            strays.append((said or 'sound', a, b))
        else:
            alone.append(said)
    loose += [w for w in misheard(text, ' '.join(alone)) if plain_word(w)]
    return sorted(set(bad) | set(loose)), strays


def mute(audio, spans, keep):
    """Silence each stray span, widened to the quiet around it but never into a real word (keep: word spans)."""
    out = audio.copy()
    frame = int(render.SR * 0.01)
    level = lambda k: float(np.sqrt(np.mean(out[k:k + frame] ** 2))) if k + frame <= len(out) else 0.0
    quiet = 0.02 * float(np.max(np.abs(audio)) or 1.0)
    for _, start, end in spans:
        lo_limit = max([e for s, e in keep if e <= start + 0.02] + [0.0])
        hi_limit = min([s for s, e in keep if s >= end - 0.02] + [len(audio) / render.SR])
        a, b = int(start * render.SR), int(end * render.SR)
        while a - frame > lo_limit * render.SR and level(a - frame) > quiet:
            a -= frame
        while b + frame < hi_limit * render.SR and level(b) > quiet:
            b += frame
        a, b = max(a, int(lo_limit * render.SR)), min(b, int(hi_limit * render.SR))
        if b > a:
            fade = min(frame, (b - a) // 2)
            out[a:a + fade] *= np.linspace(1, 0, fade)
            out[a + fade:b - fade] = 0
            out[b - fade:b] *= np.linspace(0, 1, fade)
    return out


def split(audio, words, lines):
    """Cut one recording into per-line clips at the pause before each line's first word."""
    written = [(t, i) for i, line in enumerate(lines) for t in tokens(line)]
    heard = [(t, start, end) for w, start, end in words for t in tokens(w)]
    matcher = difflib.SequenceMatcher(None, [t for t, _ in written], [t for t, *_ in heard], autojunk=False)
    heard_at = {}
    for a, b, n in matcher.get_matching_blocks():
        for k in range(n):
            heard_at[a + k] = b + k
    cuts = []
    for i in range(1, len(lines)):
        firsts = [k for k, (_, li) in enumerate(written) if li == i and k in heard_at]
        if not firsts:
            return None
        h = heard_at[firsts[0]]
        if h == 0:
            return None
        cuts.append((heard[h - 1][2] + heard[h][1]) / 2)
    if cuts != sorted(cuts):
        return None
    edges = [0] + [int(c * render.SR) for c in cuts] + [len(audio)]
    beat = np.zeros(int(BEAT * render.SR), dtype=audio.dtype)
    clips = [np.concatenate([audio[a:b], beat]) if k < len(lines) - 1 else audio[a:b]
             for k, (a, b) in enumerate(zip(edges, edges[1:]))]
    offsets = [e / render.SR for e in edges[:-1]]
    ends = offsets[1:] + [len(audio) / render.SR]
    per_clip = []
    for line, off, end in zip(lines, offsets, ends):
        mine = [(w, a - off, b - off) for w, a, b in words if off - 0.05 <= (a + b) / 2 < end]
        per_clip.append(align(line, mine))
    return Voiceover(clips, per_clip, continuous=True)


def clean_take(engine, text, check=True):
    """The best of up to FINAL_TAKES recordings of text, as (audio, faults). A stray sound left in the best take
    is cut out and the take is verified again, so what comes back is what was checked."""
    best = None
    for take in range(FINAL_TAKES):
        audio = engine.say(speakable(text, engine=engine.key))
        if not check:
            return audio, []
        faults, strays = verify(audio, text)
        if strays:
            print(f"  stray sounds {[f'{h!r} at {a:.1f}s' for h, a, _ in strays]}")
        if faults:
            print(f'  unclear {faults}')
            if take == 0:
                learn(engine, text, [w for w in faults if not plain_word(w)])
        if best is None or len(faults) + len(strays) < len(best[1]) + len(best[2]):
            best = (audio, faults, strays)
        if not faults and not strays:
            break
    audio, faults, strays = best
    if strays:
        words = transcribe(audio, words=True, context=text)
        keep = [(a, b) for w, a, b in words if set(tokens(w)) - FILLERS]
        audio = mute(audio, strays, keep)
        faults, strays = verify(audio, text)
        print(f"  stray sounds cut out: {'clean' if not strays else f'still {strays}'}")
    return audio, faults + [h for h, *_ in strays]


def say_whole(engine, lines, check=True):
    """One continuous recording of every line, so the delivery flows instead of restarting per line. Each line is
    then verified on its own, and one that is still unclear is recorded again by itself and swapped in."""
    text = ' (break) '.join(l.strip() for l in lines)
    for attempt in range(2):
        audio, _ = clean_take(engine, text, check)
        clips = split(audio, transcribe(audio, words=True, context=text), lines)
        if clips is not None:
            break
        print('  warning: could not line up this take with the script, trying again')
    else:
        print('  warning: no take lined up with the script, recording line by line instead')
        return by_line(engine, lines, check)
    for i, line in enumerate(lines if check else []):
        faults, strays = verify(clips[i], line)
        if not faults and not strays:
            continue
        print(f"  line {i + 1} unclear ({', '.join(faults + [repr(h) for h, *_ in strays])}), recording it on its own")
        clip, left = say_checked(engine, line, with_faults=True)
        if len(left) < len(faults) + len(strays):
            pad = np.zeros(int(BEAT * render.SR), dtype=clip.dtype) if i < len(lines) - 1 else clip[:0]
            clips[i] = np.concatenate([clip, pad])
            clips.words[i] = align(line, transcribe(clip, words=True, context=line))
    report(clips, lines, check)
    return clips


def report(clips, lines, check=True):
    """Verify the finished voiceover line by line and record the verdict on it (clips.verdict), so the render
    log and the reviewer know whether it is clean."""
    if not check:
        clips.verdict = 'not checked'
        return
    left = []
    for line, clip in zip(lines, clips):
        faults, strays = verify(clip, line)
        left += faults + [f'stray {h!r}' for h, *_ in strays]
    clips.verdict = 'clean' if not left else 'unclear: ' + ', '.join(left)
    print(f'  voice verified: {clips.verdict}')


def by_line(engine, lines, check=True):
    clips = [say_checked(engine, line) if check else engine.say(speakable(line, engine=engine.key)) for line in lines]
    clips = Voiceover(clips, [align(line, transcribe(c, words=True, context=line)) for line, c in zip(lines, clips)],
                      continuous=False)
    report(clips, lines, check)
    return clips


def synthesize(lines, voice=None, check=True):
    eng = engine(voice)
    if eng.key == 'fish':
        try:
            first = say_whole(eng, lines, check)
            if first.verdict in ('clean', 'not checked'):
                return first
            # Still unclear after every retake and per-line fix: record the whole reel once more, keep the cleaner.
            print('  voice not clean, recording the whole voiceover once more')
            second = say_whole(eng, lines, check)
            return min((first, second), key=lambda v: 0 if v.verdict == 'clean' else len(v.verdict.split(',')))
        except RuntimeError as e:
            # A missed day costs more than a different voice for one reel.
            print(f'Warning: {e}; using the Kokoro voice for this reel')
            return by_line(Kokoro(), lines, check)
    return by_line(eng, lines, check)


def main():
    reel = render.load_reel(sys.argv[1])
    voice = sys.argv[2] if len(sys.argv) > 2 else None
    clips = synthesize(script(reel), voice)
    out = render.OUT_DIR / f"reel-{reel['id']}-{voice or 'voice'}.mp4"
    render.render_reel(reel, out, voice=clips)


if __name__ == '__main__':
    main()
