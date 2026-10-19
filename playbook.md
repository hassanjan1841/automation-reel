# Reel playbook

What makes a reel worth watching, researched on 2026-10-01: Instagram's and TikTok's own guidance, studies of
millions of short videos, and learning research. Our first reels lost 80 to 92% of viewers in 3 seconds (a
normal reel loses about 60%). The writers (`generate.py`, and `trends.py` for news), the hook judge
(`generate.pick_hook`) and the frame review (`qa.py`) all read this file, so a rule changed here changes all of them.

## 1. The reel gives one useful thing

- One idea per reel: one command, one snippet, one setting, one prompt or one mistake and its fix that the
  viewer can use today. Not three loose tips. The three points are steps of that one thing: the problem, the
  fix, the proof (or: what, how, check it).
- Write the payoff first (`payoff`: the exact thing they get), then the hook as an honest summary of it.
- Specific beats general: name the tool, the file, the flag, the exact error. "Use indexes" is worthless;
  "this one line makes the query use an index" is a reel.
- Show it, do not claim it: real code, a real diff, a real recording (ide, walkthrough). Never an invented
  result, number, chat or post. If it cannot be shown honestly, pick another topic.
- The useful part stays on screen long enough to screenshot (2 seconds or more) and is in the caption, so
  people save it.
- Reels people send to a friend are surprising ("this is wrong and here is proof") or a pain they share; reels
  people save are exact steps they will need again. Aim for one of the two on purpose.
- Watching something get built holds people (2026-10-01 study: a CSS login card built from a plain form, 47,800
  likes, held uncut for 7 seconds at the end): the plain "before" on frame 0, the change happening on screen, the
  finished result held long enough to screenshot. For UI and CSS use the build visual.
- The ending is a direct question about the viewer's own code, never a comment-to-DM freebie. Two studied big
  accounts got thousands of comments with freebies, but on this account 29 reels offered one, not one keyword
  comment came in, and they were watched less (13% against 22% for question endings, 2026-10-14).

What our own numbers say (42 reels measured, 2026-10-14; they outrank the studies above):
- The myth about a famous basic is the format people stay on: "Your CORS header isn't security" reached 1,105
  views at 58.6% skip with 7 saves and 2 shares; "JWT: signed, not secret" and var vs let came next. The rest sat
  near 110 views at 80 to 90% skip.
- Pick topics every web developer has met (CORS, JWT, cookies, git, async, caching, indexes, re-renders). Niche
  setups (one library's realtime API, one provider's webhook into another) got 6 to 20 views.
- Statement hooks beat questions (median 111 views against 68).
- Under 20 seconds: reels of 23 seconds or more got half the views of shorter ones.
- Shares push a reel past its first test audience; watch time alone did not (a reel held at 26% skip still
  stopped at 142 views with no shares). Aim each reel at a surprise people want to send on.

Update, 30 reels from 2026-10-05 to 10-18 (measured 2026-10-19):
- The second breakout was a myth too: "*await* doesn't pause everything" reached 1,938 views in its first day at
  46.6% skip, 10 seconds watched of 19, 6 saves and 2 shares. Its first frame was a 7-line code puzzle (A, await,
  C, then B outside the function): people stayed to find out the real print order, which a stepper then showed.
- Both breakouts share one shape: a famous basic, a statement hook that flips what people assume ("Your X isn't
  Y", "X doesn't Y"), real code on screen from frame 0, and a reveal that proves it. Use that shape.
- Myths, explainers and X vs Y (11 reels): median 172 views, 67% skip, 19 saves and shares. Everything else (19
  reels): median 112 views, 85% skip, 3 saves and shares. Beginner lessons ("Next.js from zero") averaged 86%
  skip; client and freelance topics 91%.
- The first frame decides it: reels that opened on code averaged 72% skip and 4.7 seconds watched; reels whose
  first frame ended up as text alone averaged 84% skip, 2.6 seconds, and not one save or share.
- A "guess the output" opening works when the myth is about what code does: 3 to 8 lines, an outcome most
  developers get wrong, the real output proven later. Never a made-up output. The predict animation is made for
  it: the same code with the usual wrong guess and the real output as answer chips, a short countdown during the
  held beat, then the real output and the right chip stamped. A quiz gives people a reason to stay (find out if
  they were right) and to send it on (quiz a friend).

## 2. The hook (seconds 0 to 3, where most viewers leave)

In the first second a viewer must know four things:
1. Is this for me? A specific developer: "your Supabase query", "your Next.js app", "your API key".
2. What do I get, or what am I losing? A concrete payoff or danger, not a topic.
3. Can I see it? The problem or the result is on screen in frame one (`hook_visual`).
4. What is still missing? One thing held back that the reel delivers within seconds.

Rules:
- Frame 0 already shows the whole hook and its visual (with a voiceover; VOICE=none renders the hook alone).
  Nothing fades in from an empty screen.
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

- From frame 0: the problem or result on screen with the on-screen hook, and the spoken hook starting at once
  (about 0.25 s in). Then to about 15 s: one concrete worked example. Last seconds: the exact fix or command, then a closing line that
  links back to the hook, so a replay feels natural.
- Each voiceover line adds what the screen does not say: the why, what breaks, the result.
- At most one new term, explained the moment it appears.
- About 2.6 spoken words a second, complete sentences, no filler.
- The three points escalate: what it is, then it working (a real result on screen), then the strongest proof or
  biggest example. Never three equal points.
- A held beat before the result (reveal): the voice goes quiet for about a second while the output prints or the
  page finishes, then says the result. Once per reel, only on a real result.
- One short ask at the very end, after the payoff. Never hold the payoff back for a comment.

## 4. What is on screen

- Something real fills most frames: code, terminal, diff, diagram, recording. Text is a short label only;
  Instagram shows "majority text" reels less.
- Little text, never sentences: hook 3 to 6 words, titles 3, captions 3 words at a time, and modest type
  sizes so the screen does not shout. The voice carries the sentences.
- Code: at most 12 lines (10 in an animation), fewer is better, big type (it is what people read), the one line that matters highlighted (`highlight`); the voice names
  it at that moment.
- The headline never repeats the spoken sentence word for word (saying the same thing in two places makes it
  harder to follow, not easier).
- Keep key content inside the safe zone the renderer uses (percent of the 1920 px height): content from about
  15% down to 75% (67% when captions run), captions in the 69 to 77% band, nothing in the bottom 23%, and 8%
  side margins so the right-hand buttons cover nothing.
- Something changes every 1.5 to 3 seconds (a highlight, a zoom, a new line); no slide holds a still frame.
- Captions show up to 3 words at a time in the lower band, high contrast.
- At most one animation per reel (motion.py), on the point where movement explains better than a still: one change
  at a time with a short hold, the active part glowing and the rest dimmed, values that are true.
- One accent colour, calm moves: sections glide into each other (no jump on a slide change), and the camera
  punches only on spoken sentences. A takeaway can be big kinetic type (2 to 4 words a line, the key word in the
  accent), never a paragraph.
- The closing card repeats the hook's style and puts the comment keyword big on screen, so the one word to type
  is the last thing people see.
- No invented chats or posts presented as real. No faces, no animals, no music.

## 5. Sound

- Sound starts at once: the voice or a short effect under the first word, never silence on frame 0.
- Effects only where they mean something (a key tap on a line, a whoosh between slides, a pop when a preview
  updates, soft ticks during a held beat), always well under the voice. No music: the studied reels timed their
  cuts to music, we time them to the voice and to these effects instead.
