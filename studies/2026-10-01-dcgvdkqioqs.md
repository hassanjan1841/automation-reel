# Study: DcGvDkqioqS

out/ig/DcGvDkqioqS.mp4

## Measured

- 15.74s long, 1080x1920; 2 cuts (1.3 every 10 s), first cut at 6.2s; 6 beats (the picture changes noticeably: 3.8 every 10 s); moving 24% of the time; first change at 0.2s; something on screen from frame one

- Speech starts at 14.34s, 2.9 words a second, 0 words in the first 3 s, longest pause 0.0s

## First second

Frame at 0.0s: a static screen recording split horizontally. Top half (~45% of frame) is a browser window showing a plain, unstyled-looking "Login" and "Sign Up" form pair on a flat gray background, basic boxes, default button styling, no visual polish. Bottom half is VS Code: tabs for index.html and code-with-nazia.css, the CSS file open and mostly empty (cursor sitting on line 38). No caption, no title card, no face, no logo, just a raw "about to build something" screen capture. moving_share is low (0.24) and first_change is logged at 0.2s, meaning something (a cursor blink/tiny scroll) is already moving before 1s, but there is no text or spoken hook yet.

## Hook
- Said: No speech. words_first_3s = 0 and speech_start is 14.34s, the entire video is silent of voice until the very last line, 'Thanks for watching guys!', which plays from 14.34s to ~15.7s over the outro card, functioning as a sign-off, not a hook.
- On screen: No text on screen at the start. The only on-screen text in the whole 15.74s video appears on the outro card starting around the 13.8s cut: 'Up Next', 'FRONTEND CHALLENGE' (large, bold, with a glitchy cyan/magenta chromatic-aberration edge, visible in the 14.7s/14.8s frames), then smaller lines 'For Your Daily Frontend Dose' and 'Hit subscribe and code with me!', with thin white bars and horizontal glitch/scan-line streaks flashing across the black background.
- Type: Visual-only "build is about to happen" tease, no spoken or written hook, just an unglamorous before-state (plain form + near-empty CSS file) that implies a transformation is coming.

## Structure
- 0.0-6.2s: Continuous split-screen timelapse: the browser preview (top) and the live CSS file (bottom) are shown simultaneously while the creator types styling rules; the plain form gradually gains shadows/rounding. Loudness is quiet and dipping (down to -28.3 dBFS around 1.5s), consistent with a quiet music build-up rather than narration.
- 6.2s (first_cut): Hard cut lands exactly as loudness jumps from roughly -20dBFS to a sustained ~-9 to -8dBFS plateau - a loud 'drop' that lines up with the visual reveal of a glossy, soft-shadow circular ('neumorphic') panel behind the Sign Up card.
- 6.2-13.8s: One long uncut ~7.6s take (no further cuts here, matching the overall cuts_per_10s of just 1.3) that finishes the design: icon-labeled inputs, inset/outset shadow combos, a toggle switch, and by 7.2s a fully finished Login card with a pink-glow focused input and 'SIGN IN' button - held on screen as the visual payoff.
- 13.8s (second cut): Hard cut to black for the outro / call-to-action card.
- 14.0-15.3s: The outro text staggers in with glitch/scan-line flashes (matches the detected beats at 14.0s and 15.3s): 'Up Next' -> 'FRONTEND CHALLENGE' -> 'For Your Daily Frontend Dose' -> 'Hit subscribe and code with me!'
- 14.34-15.7s: Spoken sign-off 'Thanks for watching guys!' plays over the CTA card, ending as the 15.74s video terminates.

## Pacing
Very slow cutting for a short-form video: only 2 hard cuts in 15.74s (cuts_per_10s 1.3), versus a typical fast-cut Reel. moving_share is only 0.24, meaning three-quarters of frames show little movement beyond cursor/typing - the video leans on a continuous "watch it get built" feel rather than rapid visual change. The rhythm that does exist (beats at 0.4, 2.5, 3.5, 6.0, 14.0, 15.3s; beats_per_10s 3.8) tracks the loudness curve (a quiet build from 0-5.5s to a loud plateau at 6.0s, held until ~13s), strongly suggesting these beats are music-driven, not speech-driven - there are effectively zero spoken words until the last 1.4 seconds (words_per_second 2.9 is an average dragged almost entirely from that short final phrase).

## Why it works
- Nothing is asked of the viewer in the first seconds - no text to read, no claim to evaluate (words_first_3s = 0) - so the plain-looking UI plus a code file sitting open reads as "a build is about to start," which for a frontend-adjacent audience is enough curiosity to keep watching past the first second.
- Extremely low cut rate (only 2 cuts total) lets the audience watch uninterrupted, continuous progress for stretches of 6+ seconds - this "proof of work" pacing (common in satisfying build/transformation clips) is the opposite of typical fast-cut short-form editing and seems to be the core retention mechanism here, not spoken hooks.
- The loudness curve is a clear quiet-build-then-loud-plateau shape (-28.3dBFS trough near 1.5s rising to a sustained ~-9dBFS from 6.0s onward) landing precisely on the first hard cut and the first big visual payoff (the neumorphic card appearing) - classic anticipation-then-release editing that rewards viewers who stuck through the quiet opening.
- The finished, polished design is held on screen uncut for ~7.6 seconds (6.2-13.8s) - long enough to be admired/screenshotted, which plausibly drives saves and shares from a code-audience that values the finished visual result.
- All three asks (sign-off, "coming next" tease naming a specific future video, and an explicit subscribe request) are compressed into the final ~2 seconds, delivered only after the full payoff has already been shown - the CTA is a reward for finishing, not an interruption.

## What we could test
- **Treat one of the 3 point-slides as a literal before/after of the same artifact (same code or output evolving) instead of three unrelated points, so the video reads as one continuous "watch it get built/fixed" arc rather than a list.**: Keep our hook card and voiceover, but make point 1 = the broken/ugly version of a script or config, point 2 = the mid-fix diff, point 3 = the clean working result of that same artifact - visually it should look like a progression, not three separate topics. Test: For half of the next batch of reels, restructure the 3 points as one evolving artifact (progressive reveal); keep the other half as independent points as today. Compare median watch time and completion rate between the two groups.
- **Hold one visual significantly longer without cutting to create a "continuous build" feel, reserving fast punches only for the final payoff slide.**: Our reels currently punch on every sentence; for one slide (e.g. the code/diff slide), let the camera hold still through 2 full sentences before the next punch, instead of punching every sentence. Test: On half of reels, merge the punches on the middle slide into one longer hold; keep the rest punch-per-sentence as usual. Compare skip rate in that time window and overall completion.
- **Pair the hook text with an immediate "before" visual on screen (rather than a text-only hook card) so the mismatch between the plain before-state and the promised result does the hooking work, not just the words.**: During the first 4-5s hook card, show a small inset/background of the "ugly/broken" screenshot or terminal error behind or beside the hook text, instead of the hook text alone on a plain background. Test: For half the reels, overlay a relevant before-state screenshot behind the hook text for the first 4-5s; keep the other half as plain text-only hook cards. Compare 3-second retention (currently median watch time 3.4s on a 84.6% median skip rate).
- **End with a specific forward-looking tease ("next up: X topic") stacked right before the usual question/CTA, rather than the question alone.**: Add one line naming the next planned reel's topic (e.g. "Next: the terminal trick for Y") directly before our usual closing question, in the same caption style we already use. Test: Run half the reels with "question only" endings and half with "next-topic tease + question" endings; compare follow rate and saves between the two groups.

## Not for us
- Background music driving the pacing - a quiet build-up from roughly -28dBFS up to a sustained ~-9dBFS plateau, with hard cuts and the visual payoff timed to that music's loudness jump (the beats at 0.4/2.5/3.5/6.0/14.0/15.3s track the music curve, not speech). (No music - this account's reels use AI voiceover plus sound effects only, never a music track, so beat-matching cuts to a music drop isn't something we can replicate; we'd need to fake the same effect with voiceover pacing or SFX hits instead, which is a different pattern, not this one.)
