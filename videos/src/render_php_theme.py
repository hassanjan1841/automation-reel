"""Render the PHP2Shell reel in PHP's colours: the stage page's orange swapped for php.net's purple (#8892BF, the
logo's #777BB3 family). No PHP logo or elephant: colours only."""
import json, sys
sys.path.insert(0, '.')
import render, stage, publish, voice
SWAP = [('255,106,61', '119,123,179'), ('255,96,32', '136,146,191'), ('160,40,10', '50,52,110'), ('FFE3D6', 'E4E6F7'),
        ('rgba(255,${180 + 60 * white | 0},${110 + 130 * white | 0},.95)', 'rgba(${190 + 65 * white | 0},${195 + 60 * white | 0},255,.95)')]
for a, b in SWAP:
    assert a in stage.PAGE, a
    stage.PAGE = stage.PAGE.replace(a, b)
render.THEMES['dark']['accent'] = '#777BB3'
reel = {**json.load(open(sys.argv[1])), 'id': int(sys.argv[2]), 'style': 'dark'}
v = publish.paced(reel, voice.synthesize(voice.script(reel)))
path, slides = render.render_reel(reel, voice=v)
print('OUT', path, [(round(s.start, 1), s.visual.spec.get('type') if s.visual else 'text') for s in slides], flush=True)
