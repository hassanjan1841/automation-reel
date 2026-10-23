"""Temporary benchmark (not merged): write today's reel once with WRITER_EFFORT and report the time and result."""
import json, os, sys, time
sys.path.insert(0, '.')
import generate, render
reels = json.loads(render.QUEUE.read_text())
start = time.monotonic()
reel = generate.today(reels, [])
if reel and reel.get('alternatives'):
    reel = generate.pick_hook(reel)
took = time.monotonic() - start
level = os.environ.get('WRITER_EFFORT') or 'default'
print(f"BENCH effort={level} total={took:.0f}s valid={bool(reel) and not generate.validate(reel)} hook={reel and reel.get('hook')!r}")
os.makedirs('out', exist_ok=True)
json.dump({'effort': level, 'seconds': round(took), 'reel': reel}, open(f"out/bench-{level}-{os.environ.get('TRIAL', '1')}.json", 'w'), indent=2, ensure_ascii=False)
