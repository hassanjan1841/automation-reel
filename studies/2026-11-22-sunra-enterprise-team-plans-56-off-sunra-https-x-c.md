# Study: Sunra Enterprise — team plans, 56% off (Sunra, https://x.com/sunra_ai/status/2120200688152248666, via whatships.com/videos/sunra-enterprise/)

https://video.twimg.com/amplify_video/2120199244208611328/vid/avc1/1920x1080/4VEkxbFWH91W-uIR.mp4 by sunra_ai · 7,813,362 views

## Measured

- 67.63s long, 1920x1080; 10 cuts (1.5 every 10 s), first cut at 6.8s; 19 beats (the picture changes noticeably: 2.8 every 10 s); moving 44% of the time; first change at 1.0s; something on screen from frame one

- Speech starts at 7.82s, 1.1 words a second, 0 words in the first 3 s, longest pause 9.1s

## First second

Frame 0.0s is almost pure black with only faint pinprick stars (no blank_start flag, but visually it reads as a cold-open space shot, not a text card). By frame 1.0s (first_change:1.0) the grey curved underside of a massive ship has entered from the top of frame and the painted letters "…A ENTERI…" (part of "SUNRA ENTERPRISE") are already visible on the hull — so the "hook text" in second 1 is diegetic signage on the ship, not a graphic title card. There is no spoken line yet; speech doesn't start until 7.82s. This is a slow, mysterious, trailer-style open, the opposite of an instant-payoff first frame.

## Hook
- Said: No speech in the first ~7.8s (silence/ambience only); the first line, at 7.82s, is a flight attendant saying 'Ladies and gentlemen, welcome aboard Sunra Enterprise.'
- On screen: No designed text card in the first 7s — the only 'text' is the ship's hull signage 'SUNRA ENTERPRISE' (frames 1.0s-3.0s), which doubles as an in-world title. The first actual graphic overlay (a small lower-third stat card) doesn't appear until about 18.7s.
- Type: cold-open visual tease + delayed in-scene spoken premise, not a text-card hook

## Structure
- 0.0-6.8s: Cold open: slow reveal of a giant retro spaceship hull in space, name painted on it, ambient score only, no cuts, no dialogue (first_cut 6.8s matches speech_start 7.8s)
- 6.8-14.6s: Cut to interior; flight attendant (actress in red 1970s-airline uniform) delivers the sketch premise direct-to-camera with Earth visible through a window behind her
- 14.6-18.7s: Wide shot of the cabin full of lounging passengers establishes the 'space flight' setting
- 18.7-34.8s: Three escalating price-reveal beats, each its own shot: '$0.095/sec from 2 seats*' (sleeping/reading passengers), then '$0.062/sec from 5 seats*' (bigger group), then '$0.046/sec from 10 seats*' (crowded group, champagne appears) — dialogue reacts to each falling number
- 42.3-45.8s: Three closely-spaced cuts (42.3/44.2/45.8, the densest cutting in the video) show a champagne-popping celebration; this is also where the audio loudness floor jumps to its loudest (~-9.2 to -9.8 dBFS) — cut-rate and loudness peak together at the comedic climax
- 46.2-49.0s: Voice-over states the single takeaway line: 'The more seats you fill, the less you pay per second'
- 50.8s: Calmer beat: confetti/feathers fall, flight attendant smiles at camera, a visual exhale after the party
- 52.4-56.7s: Plain spoken benefit list over the same scene: shared credit pool, admin controls, priority support
- 57.6-67.6s: Cut to a cinematic hero shot of a sleek spacecraft flying over Earth toward the sun; the URL 'sunra.ai/enterprise' fades in as the only CTA, with no spoken call to action

## Pacing
Cuts are slow for short-form (cuts_per_10s only 1.5, first_cut at 6.8s) — this behaves like a sketch/ad with sustained scenes, not a fast-cut meme reel. But beats_per_10s is 2.8, almost double the cut rate, and moving_share is 0.44: within each long shot there's continuous internal motion (camera push, pouring, gestures, confetti) so the frame never goes static even without a hard cut. The one exception is 42.3-45.8s, where three cuts land within 3.5 seconds — the fastest cutting in the video — and it coincides with the loudest audio (~-9.2 to -9.8 dBFS versus a -14 to -17 dBFS floor elsewhere), so the single moment of rapid-cut + loud audio is reserved for the emotional/comedic peak, not spread evenly through the video.

## Why it works
- Delaying both the first cut and first line of speech until ~7s (after a near-silent, slow-moving cold open) works like a trailer: it trades instant payoff for mystery/scale, which is viable here because it's a polished production (actors, sets, VFX) rather than a cold-audience organic short — a guess, since we can't see engagement-vs-time data, but the measured first_cut=6.8/speech_start=7.8 pairing is deliberate, not incidental.
- The three price reveals share one exact visual template (bottom-left icon + product name + '$X/sec from N seats*' + fine-print disclaimer), so each repetition costs the viewer no re-learning time — attention goes straight to the number, which is the actual joke/payoff.
- The core claim is stated three separate ways in close succession: visually (seats filling up), numerically (the falling price captions + the spoken numbers), and then explicitly in plain English by the voice-over ('the more seats you fill, the less you pay per second') — redundant encoding means the takeaway survives even if a viewer only catches one of the three.
- Cut-rate and loudness are synchronized at the climax (42-46s), which is a concrete production choice: visual and audio intensity spike at the same moment rather than independently, making the 'big reveal' feel bigger than either channel alone.
- The ending pairs a calm, upward/forward visual (spacecraft rising over Earth) with a minimal text-only CTA and no spoken sell — the ask is soft and visual, which suits a brand-awareness/shareability goal rather than a hard-conversion one.

## What we could test
- **Escalating three-step numeric reveal where each slide changes only one variable and the number visibly moves in one direction (here: seats up, price down) rather than three independent/equal-weight facts.**: In our three-point-slide format, instead of three separate tips, structure them as one metric escalating across the three slides (e.g., 'manual: 40 lines of code' -> 'with snippet: 12 lines' -> 'with this tool: 2 lines'), so slide 3 pays off slide 1's number directly. Test: Run half of a batch of reels with escalating single-metric slides and half with today's independent three-tips format; compare median watch time and skip rate on the matched pairs.
- **Stating the single takeaway in plain words right after the data, as its own beat, distinct from the data slides themselves (the voice-over line 'the more seats you fill, the less you pay' following the three price slides).**: Add one extra short caption/VO line right before the final question that restates the point in one plain sentence (e.g., 'fewer lines, same result'), separate from the code/terminal slides, so the takeaway isn't left implicit. Test: A/B half the reels with this explicit one-line recap beat added before the closing question vs. the current format that goes straight from slide 3 to the question; compare completion rate to the end.
- **Reusing one exact lower-third template (same position, icon, and field order) across all repeated stat beats so the eye doesn't need to re-orient.**: When a reel shows the same kind of stat more than once (e.g., before/after timings, token counts), lock the caption into one fixed template and position across all repeats rather than varying size/placement per slide. Test: Test a set of reels with a fixed-template repeated stat card against our current styling and compare skip rate specifically at the second/third slide transition.
- **Concentrating the fastest cuts/punch-ins at a single climax beat instead of spreading punches evenly across every sentence.**: Currently we punch on every sentence; test reserving the hardest/fastest punch-ins (and any SFX hit) specifically for the payoff slide or the final number, keeping earlier slides comparatively calmer. Test: Split reels into 'even punches on every sentence' vs. 'punches concentrated at the payoff moment only' and compare watch time curve around the final slide.
- **Ending on a clean, text-only CTA over a calm visual with no spoken call-to-action, rather than ending on a spoken question.**: Test closing some reels with just an on-screen line (tool name or one-line result) and no verbalized question, instead of our current closing question. Test: A/B our usual 'ends on a spoken question' format against a 'silent text-only CTA' ending on matched topics and compare completion/skip rate in the final 2 seconds.

## Not for us
- The entire video is carried by on-camera human actors (a flight attendant and a cabin full of passengers) performing a sketch, including close-up reaction shots. (no faces/people — the account must stay faceless)
- A continuous ambient/orchestral score plays under the whole video, swelling at the celebration beat. (no music)
- The video is a scripted, dramatized scenario (actors playing passengers reacting to pricing in a fictional space-airline setting) presented as if it were a real customer experience/testimonial. (no dishonest or invented content — don't present invented scenes/stories as real results)
