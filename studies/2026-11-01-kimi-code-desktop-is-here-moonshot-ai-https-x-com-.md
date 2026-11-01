# Study: Kimi Code Desktop is here (Moonshot AI, https://x.com/Kimi_Moonshot/status/2113445757185606062, via whatships.com/videos/kimi-code-desktop/)

https://video.twimg.com/amplify_video/2113445550087708673/vid/avc1/1920x1080/vCo3DeWLOC3E0IuX.mp4 by Kimi_Moonshot · 2,184,070 views

## Measured

- 24.09s long, 1920x1080; 45 cuts (18.8 every 10 s), first cut at 2.3s; 11 beats (the picture changes noticeably: 4.6 every 10 s); moving 76% of the time; first change at 0.1s; something on screen from frame one

- Speech starts at 23.14s, 2.1 words a second, 0 words in the first 3 s, longest pause 0.0s

## First second

A cream-colored vintage all-in-one Macintosh-style computer sits centered on a plain grey background, its small CRT screen showing a dark terminal window with teal/white text already mid-type ("Welcome to Kimi Code!", a directory path, and a prompt). Nothing else moves yet; `first_change` is logged at 0.1s (a slight settle/zoom), and `blank_start` is false — the video never wastes a frame on black or logo before showing the product.

## Hook
- Said: no speech in the first seconds — the only line in the whole transcript is "Thanks for watching!" at 23.1s, so the entire 0–23s runs with no narration at all, just ambient sound/music and SFX under the picture
- On screen: the terminal on the retro Mac's screen types out a real CLI session: "Welcome to Kimi Code!", a project path, a version line, then the typed instruction "Build a complex procedural 3D scene in Three.js" followed by actual code scrolling (frames 0.0s–3.0s). This doubles as the hook text — it's not a big graphic title card, it's the product's own UI being used as the hook.
- Type: product-demo cold open, no spoken hook

## Structure
- 0.0–2.3s: static-camera shot of the Mac with terminal typing/scrolling code; this is the only slow stretch in the video (first_cut at 2.3s)
- 2.3–3.4s: screen 'glitches' into scrambled colored text blocks (frame 3.0s) — a transition effect bridging from 'real UI' to 'generated output' mode
- 3.4–21.0s: a very fast montage of ~15+ unrelated abstract/CG/stock images (particle cloud, agate geode, screws over a blurred train-station crowd, paint-splash, iridescent spinning torus, mechanical blueprint, aerial city-map collage with a galaxy, a melting globe, an anatomical head diagram, a DNA helix, a red liquid sphere, etc.), each on screen roughly 0.3–0.5s, often with faint code-like text printed over them — functioning as a 'look what this tool can render' proof reel rather than an explained point
- 21.0–23.1s: cut to pure black with the bold centered white wordmark 'KIMI' — a clean branded end-card
- 23.1–24.1s: voiceover 'Thanks for watching!' plays over/after the logo card as the sign-off; audio then drops to silence (-180dBFS) to close

## Pacing
Cutting is relentless: 18.8 cuts per 10s on average (roughly a new shot every 0.5s) with beats_per_10s at 4.6, and moving_share of 0.76 means three-quarters of frames contain motion (zooms, particle sims, camera drift). The only pause is the opening 2.3s on the terminal. Loudness stays in a tight, elevated band (-15 to -22 dBFS) almost continuously from ~1s to ~19s, consistent with a constant music/sound-design bed rather than isolated SFX hits — this is a wall-to-wall audio-visual barrage, not a stop-and-explain format. It only breaks down at the very end (dips to -37, -45, -63, then silence) as the logo card and sign-off play out."

## Why it works
- Opens on a concrete, tactile artifact (a real terminal running a real command) instead of an abstract title card, which reads as credible proof rather than marketing copy — the hook is 'watch it actually work,' not 'listen to a claim'
- Near-maximum visual novelty rate (new unrelated image every ~0.3-0.5s, moving_share 0.76) keeps the eye from settling, which is a known scroll-stopping mechanic independent of whether the viewer understands what they're looking at
- The imagery itself has no narrative logic (geode → screws → paint splash → DNA) — it isn't trying to explain features, it's using sheer variety/strangeness of outputs as the payoff, implying 'this tool can generate anything,' which needs zero cognitive load to appreciate
- Silence/no narration for 23 of 24 seconds removes any friction of listening or reading; the only spoken line is a one-breath sign-off at the very end, so there's nothing to 'catch up on' if a viewer joins mid-scroll
- The brand reveal is held back until the absolute end (bold word on plain black, frame 23.1s) after the spectacle, so branding never interrupts the hook — payoff first, logo last
- A guess: the steady -15 to -22dBFS loudness band strongly suggests a continuous music/whoosh soundtrack timed to the cuts, which is likely doing real work to make the rapid-fire images feel like one choreographed sequence rather than noise

## What we could test
- **Cold-open on a real, moving product artifact (live terminal/code typing) instead of a static text hook card**: Behind the first 1-3s of hook narration, show an actual terminal or editor window typing a real command/prompt live (screen capture) instead of a plain colored text card; the spoken hook plays over it Test: In half the reels, replace the static text hook card with a 2-3s live-typing terminal/code clip under the same hook VO; compare 3s-watch-through and skip rate against the current static-card reels
- **Very high shot/visual variety rate during the proof section**: Within each of the three point-slides, cut to a second distinct visual (e.g., code screenshot then immediately a diff or terminal output) instead of holding one static visual per point, roughly doubling visual changes per slide Test: On half of reels, add one extra visual swap inside each of the 3 point slides (so ~6 visual beats instead of 3); measure median watch time and skip rate vs the single-visual-per-slide control
- **A short wordless 'proof montage' of multiple real outputs right before the closing question**: Insert a 1.5-2s rapid flash (3-4 quick cuts, ~0.4-0.5s each) of different real screenshots (terminal, diff, code, chat) with no new VO, right after point 3 and before the closing question slide, to simulate the montage effect without inventing results Test: Add this flash-montage beat to half of the reels right before the CTA question; compare completion rate and skip rate against reels that go straight from point 3 to the question
- **Clean, bold, minimal branded end-card as the very last beat**: End on a 0.5-1s solid-background card with just bold text (e.g., tool name or 'Follow for more') instead of ending abruptly on the last slide/question text Test: Add this 0.5-1s end-card to half of reels; compare replay rate and follow-through (if trackable) against reels ending directly on the question slide

## Not for us
- Continuous music/sound-design bed under the whole middle section (steady -15 to -22dBFS for ~18s, consistent with a music track rather than isolated SFX) (no music)
- Montage includes a shot of blurred human commuters walking through a train station (frame ~6.3s) layered under the screws graphic (no people/faces on screen)
- The surreal/VFX stock-style footage (particle explosions, geode, paint splash, torus, globe) is specific sourced stock/CG footage, not something to reuse or re-skin (no copying another creator's/brand's specific footage or visuals)
