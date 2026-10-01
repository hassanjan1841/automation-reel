# Reel playbook

What makes a reel worth watching, researched on 2026-10-01: Instagram's and TikTok's own guidance, studies of
millions of short videos, and learning research. Our first reels lost 80 to 92% of viewers in 3 seconds (a
normal reel loses about 60%). The writer (`generate.py`), the hook judge (`generate.pick_hook`) and the frame
review (`qa.py`) all read this file, so a rule changed here changes all three.

## 1. The reel gives one useful thing

- One idea per reel: one command, one snippet, one setting, one prompt or one mistake and its fix that the
  viewer can use today. Not three loose tips. The three points are steps of that one thing: the problem, the
  fix, the proof (or: what, how, check it).
- Write the payoff first (`payoff`: the exact thing they get), then the hook as an honest summary of it.
- Specific beats general: name the tool, the file, the flag, the exact error. "Use indexes" is worthless;
  "this one line makes the query use an index" is a reel.
- Show it, do not claim it: real code, a real diff, a real recording (ide, walkthrough). Never an invented
  result, number, chat or post. If it cannot be shown honestly, pick another topic.
- The useful part stays on screen long enough to screenshot (2 seconds or more) and is in dm_guide or the
  caption, so people save it.
- Reels people send to a friend are surprising ("this is wrong and here is proof") or a pain they share; reels
  people save are exact steps they will need again. Aim for one of the two on purpose.

## 2. The hook (seconds 0 to 3, where most viewers leave)

In the first second a viewer must know four things:
1. Is this for me? A specific developer: "your Supabase query", "your Next.js app", "your API key".
2. What do I get, or what am I losing? A concrete payoff or danger, not a topic.
3. Can I see it? The problem or the result is on screen in frame one (`hook_visual`).
4. What is still missing? One thing held back that the reel delivers within seconds.

Rules:
- Frame 0 already shows the whole hook and its visual. Nothing fades in from an empty screen.
- One promise said three ways: on screen a 3 to 6 word phrase (people glance at a feed, they do not read
  sentences); spoken, one sentence of about 9 to 14 words; the visual is the evidence. Same promise, not the
  same words.
- Talk to "you" (hooks about the viewer beat hooks about "I" by about half again in a 14,000-video study).
- Numbers alone do not help; a specific outcome does.
- Plain words: no term the viewer must already know to decide whether to stay.
- Never bait: the hook is a literal summary of what the reel proves. A hook that over-promises loses the
  viewer later and breaks the honesty rule.

Hook types that fit this account (all honest):
- problem: the real error or bad line on screen. "This one line puts your API key in the browser."
- before_after: slow, then fast; wrong, then right. "One change took this page from 50 queries to 1."
- shortcut: the command or key on screen. "Stop renaming variables by hand. Press F2."
- mistake: the bad line highlighted. "You're storing login tokens where any script can read them."
- test: a real comparison we ran, real outputs only. "Same prompt, two AI tools. Only one caught the bug."
- news: a real change with stakes. "Using Next.js 15? Your dev server can leak source code."

Hook mistakes that make people swipe:
- a question with an obvious yes or no ("Can Claude query your database?");
- a topic instead of a payoff ("Why is your query slow?" without what they get);
- a joke or a feeling everyone already knows ("Every client says it's a tiny change");
- vague words ("This changed everything", "game changer");
- a slow start: context, greetings or a logo before the point;
- jargon or an acronym the viewer has not met yet;
- a text-only first frame with nothing to look at.

## 3. The script

- 0 to 2 s: the problem or result on screen with the on-screen hook. 2 to 5 s: the spoken hook.
  5 to 15 s: one concrete worked example. Last seconds: the exact fix or command, then a closing line that
  links back to the hook, so a replay feels natural.
- Each voiceover line adds what the screen does not say: the why, what breaks, the result.
- At most one new term, explained the moment it appears.
- About 2.6 spoken words a second, complete sentences, no filler.
- One short ask at the very end, after the payoff. Never hold the payoff back for a comment.

## 4. What is on screen

- Something real fills most frames: code, terminal, diff, diagram, recording. Text is a short label only;
  Instagram shows "majority text" reels less.
- Little text, never sentences: hook 3 to 6 words, titles 3, captions 3 words at a time, and modest type
  sizes so the screen does not shout. The voice carries the sentences.
- Code: at most about 10 lines, big type (it is what people read), the one line that matters highlighted (`highlight`); the voice names
  it at that moment.
- The headline never repeats the spoken sentence word for word (saying the same thing in two places makes it
  harder to follow, not easier).
- Keep key content inside the safe zone: clear of the top 14%, the bottom 30% and the right edge.
- Something changes every 1.5 to 3 seconds (a highlight, a zoom, a new line); no slide holds a still frame.
- Captions show 3 to 6 words at a time in the lower band, high contrast.
- No invented chats or posts presented as real. No faces, no animals, no music.

## 5. Sound

- Sound starts at once: the voice or a short effect under the first word, never silence on frame 0.
- Effects only where they mean something (a key tap on a line, a whoosh between slides), always well under the
  voice. No music.
