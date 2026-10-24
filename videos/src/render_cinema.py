"""Renders a cinematic page (videos/src/<name>.html, drawn by window.renderAt(t)) to an MP4 with its sound effects:
python videos/src/render_cinema.py <page.html with fonts and PARAMS> <out.mp4> [seconds, default 60]. The fonts and PARAMS are added the way
showcase.page does (motion.font_css, {total, handle}). For YouTube, normalise the loudness after:
ffmpeg -i out.mp4 -c:v copy -af loudnorm=I=-15:TP=-1.5:LRA=11 -c:a aac -b:a 160k -ar 48000 final.mp4"""
import sys, tempfile, wave
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import render, stage, showcase
html = open(sys.argv[1]).read(); out = Path(sys.argv[2]); total = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
GAIN = {'impact': .55, 'riser': .25, 'sparkle': .16, 'swirl': .16, 'air': .1, 'key': .12, 'tick': .1, 'pop': .2, 'thud': .35, 'swish': .18, 'click': .2}
with tempfile.TemporaryDirectory() as tmp:
    frames = Path(tmp) / 'frames.mp4'
    sounds = stage.film(html, total, frames, label='cinema')
    rng = np.random.default_rng(7)
    fx, old = showcase.fx_kit(rng), render.sound_kit(rng)
    kit = {**old, **fx}
    n = int(render.SR * (total + 1)); t = np.arange(n) / render.SR
    track = showcase.band(rng, n, 50, 420) * .05 * (.7 + .3 * np.sin(2 * np.pi * t / 6.1))
    for at, kind in sounds:
        s = kit[kind]() * GAIN[kind]; i = int(at * render.SR); track[i:i + len(s)] += s[:max(0, n - i)]
    track = track[:int(render.SR * total)]; f = int(render.SR * .6); track[-f:] *= np.linspace(1, 0, f)
    track = track / (np.max(np.abs(track)) or 1) * .85
    wav = Path(tmp) / 'a.wav'
    with wave.open(str(wav), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(render.SR); w.writeframes((track * 32767).astype(np.int16).tobytes())
    stage.mux(frames, wav, out)
print('done', out, len(sounds), 'sounds')
