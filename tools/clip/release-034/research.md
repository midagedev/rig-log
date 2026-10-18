# Research: motion-graphics release films (for the 0.3.4 film)

Three research rounds on 2026-10-18 studied 22 films from 20 sources, five of them recent OpenAI and Anthropic
release films (the user's must-include). For each film they fetched the page, copied one
line from it, downloaded the video at 480p or lower, and measured it:

- cuts found by ffmpeg scene detection at a 0.30 threshold, and the average shot length (ASL) over the first 40 s;
- the share of saturated and near-black pixels;
- type sizes as a percentage of frame height (H);
- for some films, how close the cuts fall to sound onsets.

Each film then got a contact sheet that the round looked at. The design round that wrote this file spot-checked five
of the first two rounds' copied lines against the fetched pages (basement, DIA, Stash, Lago, Motionographer), and all
five are word for word. It checked all five lines of the third round the same way. The sheets and measurements are in
`scratch/research/{a,b,c}/` (gitignored). Below: the source, the copied line, and what this film
takes from it: techniques, not looks. No footage, logo, music or recognisable look from these films is used.

## Product launch films

| Source | Copied line | Measured | Taken |
|---|---|---|---|
| Linear, "Introducing Linear Releases" (youtube.com/watch?v=6dIwFoQ0eVg), "Linear Agent" (…=mRql2VJ99gM); write-up https://getlago.com/blog/we-killed-our-motion-design-job | "The camera moves through the real product, one action at a time." | 0 hard cuts (fades through black); 0.0 % saturated, 95 % near-black; tracked mono caps ~5 % H; words typed at 3 frames a character, "RELEASES" held 1.4 s | Restraint as a premium cue: near-black ground, the accent kept off everything but data; tracked mono caps as the tag voice |
| Raycast, "New Raycast. Coming 2026" (…=Mi173xGb0ZA), "Raycast for Windows" (…=QTcUR5BjN2M) | "It's our biggest update yet, and we think you'll love it." | 5 cuts, ASL 6.4 s; then a list ticking on every 0.40 s, and a last card held 5.0 s while the music fades from −14 to −37 dBFS | Open on something too big for the frame, then pull back; the last card holds 3 s or more over the music's tail |
| Arc 1.0, "Everything or nothing" (…=n5Vwrj1gEWs) | "1.0s could mean everything, or they could mean nothing." | 19 cuts, ASL 1.71 s; 1–2 word cards of 0.73–1.44 s; "v1.0" 25 % H; 88 % of the saturated pixels in the final card | Keep the accent back until the payoff; short word cards between the image shots |
| Framer, "That's Framer" (…=8AHPXm9Y6mI) | "This quick intro shows how professional designers can turn their ideas into live, responsive websites without writing code." | 3 cuts in the first 5.4 s, then one 32.1 s take; 90 % of the saturated pixels are one hue | Zoom through instead of cutting: each scene is a region of the next one, and the last element becomes the mark |
| Vercel Ship 2025 opener by basement.studio (https://basement.studio/post/behind-the-ship), teaser (…=vbhNyRNNYjc) | "This gives the animation a rhythm of 12 frames per second, even when the camera or environment moves at 24 fps." | Teaser text: 0.4 s in, ~2.3 s hold, 0.5 s out. Opener: 13 cuts in 40 s, ASL 2.86 s, each cut going from a cause to its effect | Texture on twos (grain and the strike's flicker re-seed every second frame) while type and camera stay at full rate; cut from cause to effect |
| GitHub Universe '24 intro by Buck (https://buck.co/work/github-universe-2024) | "We brought these monuments to life through animations for GitHub’s event assets and online campaign, and even extended them into an intro film that lit up their event stages." | Year labels each held 2.0–2.4 s on a moving surface; a two-tier label (mono caps tag ~3.5 % H over a condensed grotesk ~7 %); text always flat white over colourful ground | The two-tier label: a tracked mono tag over the big value, at the same place in every shot |
| Figma Config 2024 open (…=n5gJgkO2Dg0); write-up https://www.itsnicethat.com/features/figma-config-2024-identity-graphic-design-spotlight-090724 | "Attendees audibly counted down the one-minute open film each day and, inside the Moscone Center in San Francisco, there was a huge amount of enthusiasm for both the Config branding and the newly launched features in the collaborative design tool." | Countdown numeral ~21 % H, centred and locked in place while the shapes around it change; 0 cuts in 9 s; at most 5 flat hues. The 2025 recap runs at ASL 0.93 s | Change the container, not the digit: in a number shot only the slot changes (decode → prompt) while the label and frame stay put |
| Stripe Sessions 2024 recap (…=KH0_HM6e66w) | "Stripe announced the biggest set of product updates ever at Stripe Sessions, its annual user conference that brought together thousands of business leaders and builders who gathered at the Moscone Center in San Francisco in April 2024." | 30 cuts, ASL 1.29 s; captions as tab-stopped fields with pipe separators | Conditions as tab-stopped fields with a separator ("RTX 3090 · 250 W"), not free prose |

## Motion-design canon

| Source | Copied line | Measured | Taken |
|---|---|---|---|
| Apple M3 event segment (…=ctkW3V0Mh-k; newsroom page for M3), M5 MacBook Pro film (…=GriXfu4tL30) | "Rendering speeds are now up to 2.5x faster than on the M1 family of chips." | M5: ASL 1.74 s, six spec lines built one word per keystroke sound and then held only 1–1.5 s. M3: "3 nanometer" alone on black in a thin grotesk at ~6 % H | A spec line built word by word on the hits, with the number on its own hit. Apple's 1–1.5 s holds are too short for a phone, so our read floor stands |
| Teenage Engineering, "introducing OP–1 field" (…=Fab7sp30pg0) | "if it feels thinner. it is." | 8 cuts, ASL 3.1 s; one orange accent; "thinner," grows into "thinner, louder, better." on a line that does not move | Add to a line that stays put instead of replacing it |
| Rive, "GPU Canvas" (…=mxTCQQscTcU) | "GPU Canvas enables Rive files to render 3D and shader content in the web runtime." | ASL 3.3 s; extended caps title ~10 % H, with a 3D shard passing through and hiding parts of the letters | An object passing through the type (our current runs behind the 74B and cuts out of it in the squeeze) |
| ManvsMachine for Canva, "Affinity" (…=QKu4EyBsd0k); https://www.stashmedia.tv/?p=119582 | "It's a smooth blast of motion, typography, and product demo all rolled into one satisfying brand film." | 31 cuts, ASL 0.94 s; 14 of 31 cuts within 40 ms of an onset, the picture about 2 frames ahead; a 1.3 s burst of 3-frame shots, then a 7.6 s end card | The tool's own marks are the transition (our traces, pads and connector fingers are the edit); the picture leads the hit by 0–2 frames; one short burst, then a long still end |
| Buck for Anthropic, "Claude Opus 4.6" (…=dPn3GBI8lII) | "Claude Opus 4.6 plans more carefully, stays on task longer, and works more autonomously, so you can do more with less back-and-forth." | 23 cuts, ASL 1.64 s; in the first 8 s, 8 of 10 cuts within 30 ms of an onset (the tightest sync of all); the version shown as an edit: the label lands first, then the name is typed in steps of ~0.17 s | A label lands first, then the value; the title stays still while only a small tag beside it changes |
| Buck for Nothing, "Playground" (https://buck.co/work/nothing-playground); https://www.stashmedia.tv/?p=115653 | "Each frame was built from Nothing's visual DNA: grids, pixels, dots, typography, and their signature transparency." | ASL 2.2 s; grid blocks slide in and fill the next frame; the end drops to black with one line at a time for 2–3 s each | Build the look from a small set of the subject's own marks (for us: traces, pads, fans, expert cells); a sharp drop in density at the end |
| DIA, Coinbase State of Crypto (https://www.dia.studio/work/coinbase-state-of-crypto-summit) and Coinbase Davos stat film (https://www.dia.studio/work/coinbase-davos) | "Identity system and motion language for the third-annual State of Crypto Summit, held at Casa Cipriani in New York City on June 12, 2025." | Davos: numbers "46%" "22.5M" in a regular-weight grotesk at ~27 % H, flush left, arriving whole in ~1 s with no count-up; the caption types in after the number lands; each number held 8–10 s while only a dot field moves. State of Crypto: word passages at ~8 % H, the payoff word 3–4× larger or cropped off the frame | The hero-number rule (regular weight, ~27 % H, flush left, arrives whole, caption after, only the current moves during the hold); the payoff word cropped by the frame (74B) |
| Ordinary Folk, School of Motion "Join the Movement" (…=Er04BDbtSIg); https://motionographer.com/2019/09/16/join-the-movement/ | "We brought him in as soon as the script was done, to help us find the right voice and to help establish the music." | Real shots ~6 s long, carried by one line that changes shape from scene to scene; the hard cuts spent in a single 1 s strobe burst | One element carries every scene (our current); the music is settled before the cut, so the edit is built on its grid |
| Google I/O '23 opening film (…=AxHXEPwPsZY) | "While our ambition is bold, our approach will always be responsible, because our goal is to make AI helpful for everyone." | ASL 2.9 s; not cut to the music; "Making AI helpful for [people / businesses / everyone]", where only the last word changes | The one-changing-slot line (used in the slot swap) |

All "…=" links are `https://www.youtube.com/watch?v=…`.

## OpenAI and Anthropic release films (2026)

| Source | Copied line | Measured | Taken |
|---|---|---|---|
| OpenAI, "GPT-Live-1.1 has new voices and better accents." (…=GyO8Ao7yKJc); quoted from that upload's description (openai.com answers 403 from here) | "New voices. Better accents. And less "checking..."" | 1 cut in 40.75 s: one top-down take, the camera sliding between phones; each voice is one orb colour changed in place; end line built word by word in its final spot (~0.25 s a word, 5.4 % H), then the wordmark draws on in 0.76 s | Keep one locked frame for a run of items and change the accent in place instead of cutting; spend the cut on the end card |
| OpenAI, "Build faster with Ultrafast" (…=sKltfHvsDQM); https://developers.openai.com/api/docs/guides/ultrafast-mode | "Ultrafast mode is the fastest service tier in the OpenAI API." | 8 cuts, ASL 4.44 s; 39 % near-black; opening card of two centred lines ~10 % H, words fading from grey in ~0.7 s; speed shown as live counters ticking at their rates, but the counters are 1.9 % H | A speed number is felt when something runs at that rate on screen; make it phone-sized. (We show only our own rate, never a race against another engine) |
| OpenAI, "Introducing GPT-6 Astra" (…=1QNsdr-Qx_I); OpenAI's news RSS item for /index/gpt-6-astra (the page answers 403) | "Introducing GPT-6 Astra, our most intelligent and aligned model yet, with state-of-the-art capabilities across computer use, coding, cybersecurity, and science." | ASL 4.44 s in the first 40 s; a numeral at 21.9 % H wiped in and out by horizontal slices and held ~2.5 s; a match cut keeps the numeral's size and place; the opening's cursor dot is carried through every scene into the end card | Carry one object from the first frame into the end card (our pulse); keep a hero numeral's size and place across a cut |
| Anthropic, "Introducing Claude Fable 5" (…=Y9Wz2PV404E); https://www.anthropic.com/news/claude-fable-5-mythos-5 | "Fable 5’s capabilities exceed those of any model we’ve ever made generally available." | 8 cuts, ASL 4.44 s; a list built bottom-up in 1.0 s, a highlighter swipe over one word in 0.5 s, then a 3 s hold; a 6×7 dot field collapsing to one dot in ~0.7 s, held ~2 s | Mark the one word that matters with a single fast gesture after the line lands, then hold still |
| Anthropic, "Introducing Claude Fable 5.1" (…=ROF2Nv_KjOM); https://www.anthropic.com/claude-fable-and-mythos-5-1 | "Claude Fable 5.1 sets a new standard for coding, knowledge work, and long-running problem-solving tasks." | 10 cuts, ASL 3.64 s; one dot grows a stem and branches 1→2→6→~20→hundreds in 4.7 s, then holds 2 s; the wordmark is built letter by letter (10 steps in 2.7 s) and held 3.6 s | Show scale as growth from one: one Spark branches into several along the traces, then the frame holds |

None of these five cut on the beat (cuts on onsets 1/8, 2/8 and 1/10 against 34–39 % chance; Fable 5's 4/8 is
chance): the voice sets their rhythm. They are studied for type, colour and staging, not for sync.

## What the film takes, ranked

1. **One hero number per shot.** Regular weight, about 27 % H, flush left. It arrives whole (no count-up), its caption
   comes after it, and nothing moves during the hold except the current. (DIA Davos, Apple M3)
2. **A two-tier label.** A tracked Martian Mono caps tag at 44 px over the value, in the same place in every data shot
   (the y-128 tag line). (Buck/GitHub, Linear, Raycast)
3. **One accent, held back.** At least 75 % of the frame near-black. Volt goes only to the current, the hero number,
   the version, and the lit expert ranges. (Linear, Arc, Framer)
4. **Change the container, not the digit, or change one slot and nothing else.** Decode becomes prompt in the same
   frame: only the label, the number and the caption swap. (Figma Config, Google I/O, Buck Claude)
5. **Continuity over cuts in the main run.** One current carries every scene, and the camera follows it along a trace
   or zooms through a connector finger into the next shot. Hard cuts are kept for the beat-locked montage. (Framer,
   Ordinary Folk, Linear)
6. **Type as an act.** The width axis squeezes 74B from too wide for the frame down to exactly the card's width. The
   payoff word is cropped by both edges on the way in. (DIA State of Crypto, Rive)
7. **The cut leads the hit.** Cuts and landings sit on the beat grid with the picture 0–2 frames early, never late; in
   our pipeline every change switches half a frame early. (Buck Claude, ManvsMachine, Apple M5)
8. **Density curve.** A sparse open (the stepped leader, one element), a montage at ASL of about 1 s (TEXT / VIDEO
   FRAMES / AUDIO), and a still end lockup held at least 3 s. (Apple, Buck, ManvsMachine, Raycast)
9. **Texture on twos.** Grain and the strike's flicker re-seed every second frame; type, camera and numbers run at the
   full 60 fps and stay crisp. (basement/Vercel)
10. **Conditions as tab-stopped fields** with `·` separators. (Stripe)
11. **The subject's own marks are the graphics.** Traces with 45° bends, pads, the edge connector's fingers, fan
    blades, expert cells. No borrowed iconography. (Buck/Nothing, ManvsMachine)
12. **One object carries from the first frame into the end card** and one accent changes in place inside a locked
    frame. (OpenAI Astra, OpenAI GPT-Live; both confirm rule 5)
13. **A rate is shown running.** The decode hold runs the pulse along the trace at a pace the number names, so 86.69
    is seen as speed, not only read. Our own number only; no race against another engine. (OpenAI Ultrafast)
14. **Scale as growth from one.** The Sparks shot starts as one node and branches into three along the bus on beats.
    (Anthropic Fable 5.1)
15. **Not taken.** Apple's 1–1.5 s spec holds and Teenage Engineering's 3 % H type: both are under our phone floor
    (44 px text at 1080, hold time from the 0.3.1 read rule).

## What the rounds could not check

- No round listened to the audio. Cut-to-onset numbers come from an onset detector, and most films measured at
  or near chance. So cutting on the beat is our own rule, carried over from the 0.3.1 sync check, not something
  these films prove (Buck Claude and ManvsMachine are the exceptions).
- openai.com answers 403 from here: two OpenAI quotes come from OpenAI's own YouTube description and news RSS feed.
- Not found: Vimeo-only uploads (403 or 401 from here), the Stripe Sessions opening titles (only the recap), the
  Figma Config 2025 open film (only its blog line), and the studio behind the Google I/O '23 film.
