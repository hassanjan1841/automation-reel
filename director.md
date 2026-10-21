# Director

How our reels should look, move and sound: the creator's taste, written down so that every reel follows it. The
playbook (`playbook.md`) decides what a reel says; this file decides how it is made. The writers, the hook judge
and the frame review read both (`generate.playbook`). Every note the creator gives on a reel becomes a rule here, with
its date in the log at the end, so it is never lost in a chat.

The bar, from the reels the creator picked as the standard (2026-10-20: @speedy_devv's explainers made with Keyframes,
@princegupta.ai's Harness² reel, @louis_rlee's all-code motion piece, @withian.t's motion tips): a reel must look
made by a motion designer, never like slides a beginner put together.

## 1. Pacing

- Something on screen changes every 1 to 2 seconds: a new word, a card arriving, a line lighting, a counter ticking,
  the camera moving. A frame that sits still for more than 1.5 seconds is a mistake.
- Big moves land on the voice's stressed words (the word the sentence is about), small accents between them. A
  card arrives as its name is said, a number ticks up while it is said, a highlight lands on its word, not on a
  timer.
- The payoff (the fix, the command, the real output) holds still for at least 2 seconds, long enough to screenshot.
- Hold the ending one beat (about half a second) after the last word before the loop.
- Daily reels stay under 20 seconds (our own numbers). A weekly showcase may run to 30.

## 2. Motion

- Show the trick happening, never only tell it: an editor shortcut is performed on screen (the key, a press
  counter, a cursor landing on each match, the text typed at every cursor), not listed as steps.
- One continuous world per chapter. Things transform rather than cut: the circle around a logo becomes the next
  scene's circle, the line a viewer just read flies into the file where it belongs, the same card stays and changes.
  A hard cut is used at most once, on purpose, at the reel's turn.
- Depth: the new thing arrives sharp in front; the old thing blurs, shrinks and sinks back (about 5 px of blur), so
  the screen reads as layers, not a flat slide.
- Entrances ease out fast and settle (expo or power3 out, 0.3 to 0.8 s); camera moves ease in and out (expo in-out);
  overshoot only on scale, never on position.
- Things travel on arcs, not straight lines, with a little motion blur at full speed, and land sharply.
- Nothing is ever frozen: the background drifts slowly (`render.Background`), and the camera breathes.
- A light/dark flip once per reel, at its turn ("but", "here is the catch"), wakes the viewer up; one bold full
  accent-colour beat may punch the turn or the close instead.
- A method in steps gets numbered chapter cards ("01 INTERVIEW", "02 TOOLBOX"), and its proof can be a "done means"
  checklist that ticks off to a PASSED or FAILED stamp (only checks the reel really shows: 2026-10-21 a draft
  ticked "logs once in production" without ever running a production build, and the honesty review stopped it).
- Every stage reel wears the same frame: corner marks, a running timecode, the chapter name, and one glowing dot that
  travels from scene to scene: the channel's signature, so the reels feel like one series.
- Abstract shapes only (boxes, dots, lines, arrows, orbs, rings, code). Borrowed open-source effects are welcome when
  their licence allows it (for example brush strokes, hand-drawn lines, particles, physics).

## 3. Composition

- One hero object at a time, near the centre, with empty space around it. Nothing crammed.
- Big enough to read on a phone: code at least 36 px tall at 1080 wide, labels at least 24 px.
- Real objects, not slides: the actual docs page with the quoted line highlighted, the repo card, the terminal, the
  settings file, the tweet with its real view count. Each one framed as a clean window or card with a soft shadow.
- Keep everything inside the safe zone (`render.SAFE_TOP`, `SAFE_BOTTOM`, `MARGIN`).

## 4. Type and captions

- Captions are part of the design, never a box of subtitles. Today's reels: up to 3 words near the bottom, no box,
  the word being said on an accent pill. Stage reels (the explainer and showcase formats): the sentence builds up
  word by word at the top, the word being said bright and the earlier words grey; stressed words switch to the serif
  italic; the one key word gets a "selected text" box.
- On-screen text is a label or a few big words, never a paragraph. Big words are set in a condensed capital face
  (Anton) that fills the card. Code is shown exactly as typed (no ligatures).
- One accent colour per reel, plus the theme's ink. The serif italic is for emphasis only.

## 5. Sound

- No music, ever. Sound comes from the voice and our own effects, all shaped noise (`render.sound_kit`).
- Sound starts on frame 0. Every effect means something: a whoosh when a scene moves, a pop when something arrives, a
  tick on a key word or a counter, a thud when something is blocked, key taps when code types. Always well under
  the voice; lower it rather than raise it.
- With no voice (the showcase), the sound carries the piece and must be designed, never a few plain swishes: a riser
  building into each beat, a deep impact on it, a swirl through the morph, sparkles as things land, over a soft noise
  bed (`showcase.fx_kit`). Still shaped noise with no pitch or melody.

## 6. Truth on screen

- Every value shown is real: real program output, real star and view counts at the time, numbers quoted from the
  source. A counter ticks up to the real number, never past it.
- Every result follows from the steps on screen: the key pressed as many times as it really takes, typing once at
  several cursors puts the same text on every line, a command prints what the files shown would give. An edit
  scene's result is worked out by the code (`stage.edited`), not written.
- A value that only illustrates an idea (probabilities in a diagram, a sketch of a curve) carries a small
  "illustration" tag.
- The source is on screen when a fact comes from a page (its address, small, near the bottom).
- Claims about a product are that product's own docs. Others' claims are stated as theirs.

## 7. Never

Faces, people, characters, mascots, pixel or cartoon figures, animals; music; fake or AI-made images of real people;
swearing; sponsored hype; anything meant to hide that a post was written with AI; a number, quote, chat or result
that is not real.

## Creator notes (newest first)

- 2026-10-21: On the multi-cursor reel ("Three edits become one"): "not that good, we need more improvements". It
  only told the trick (cards listing Ctrl+D), said "twice" for three matches, and ended on an output typing once
  could not give. Now an edit scene performs the trick on screen, its result worked out by the code; code reads
  bigger; the honesty review rejects results the steps could not give (sections 2 and 6).
- 2026-10-21: On the showcase: "it should be very interesting, not some sho sho sounds and simple boring": the
  showcase is now a 3D swarm of glowing particles with a shockwave and camera punch on every beat, and full sound
  design (section 5).
- 2026-10-21: Liked @borja.obeso's "AI delegation" reel: bold palette flips, a film frame with timecode, giant
  condensed type, numbered chapter cards, a checklist stamped PASSED, one recurring glowing dot. "Go for all":
  added to the stage kit (section 2, and big words in a condensed capital face, section 4).
- 2026-10-20: "It should not look like some newbie is doing it": premium motion is the bar (sections 1 to 4).
  Loved every motion of @speedy_devv's explainer: word-synced counters and bars, building captions with a selection
  box, depth, chapter flips (sections 1, 2, 4). Wants a fully animated showcase reel once or twice a week.
- 2026-10-20: "The demo of yours is static images, that I don't want": demos are moving video (real recordings, 3D
  devices playing real screens), never a still screenshot alone.
- 2026-10-19: "Not just simple, good animations and styles": every scene moves (section 1).
- 2026-10-19: Broader than coding: new things in Claude and Claude Code, interesting repos and tools, the AI era, and
  "demo then how": show the result first, then how it was done.
- 2026-10-19: "I don't want you to create some dummy and some basic": every sample is a finished, real piece.
