# What the 3090 is actually worth: 20 GB of expert layers, and under 3 % of decode

**2026-09-16, 10:56–11:11.** The question came from a hardware decision rather
than a curiosity: the 24 GB card is due for replacement, and the first thing
worth knowing is what the machine loses when it comes out. The served
DeepSeek-V4.1 profile holds 45.8 GB on the A6000 and 20.0 GB on the 3090, and
the per-layer figures measured on other models — about 1 % of decode for each
expert layer moved onto a card on GLM-5.3-Flash, about 3 % on
Qwen3.8-Flash-Next — predict that the 3090's two-and-a-half expert-layer
equivalents are worth 3–7 %.

They are worth less than that, and the reason the experiment could say so is
also the reason it nearly could not.

## The design, and the confound it was built against

Four arms, **alternating**, because the bias here runs one way: the one-card
arm reads more of the model out of host memory, so it gains more from a warm
page cache than the two-card arm does. Running it second would have flattered
it — the same mistake E4 had to add a control for. So: `2card`, `1card`,
`2card`, `1card`, and the answer is the gap between the pairs rather than
between two runs.

Everything else is held. Same served file
(`…-engramQ8-tokembdBF16-attnQ8`, 444.2 GiB), same DSpark draft at
`--spec-draft-n-max 3`, `--lazy-mode auto`,
`GGML_CUDA_NO_PINNED_WEIGHTS=1`, `-c 16384 -t 32 -b 2048 -ub 512`, the same
five prompts at `n_predict` 200, `temperature` 0 and `cache_prompt` false —
three of them once and two of them again, so each arm reports a cold pass and
a warm one. The only thing that moves is `CUDA_VISIBLE_DEVICES` and the
tensor override that follows from it:

```
2card  blk\.[0-3]\.ffn_.*_exps=CUDA0,blk\.6\.ffn_down_exps=CUDA0,
       blk\.[4-5]\.ffn_.*_exps=CUDA1,blk\.6\.ffn_(gate|up)_exps=CUDA1,exps=CPU
1card  blk\.[0-3]\.ffn_.*_exps=CUDA0,blk\.6\.ffn_down_exps=CUDA0,exps=CPU
```

Quiet box throughout: one lease (`v41-1card-20260916-105632`), no peer claim,
`/proc/pressure/io` `some avg10` between 2.48 and 2.96 at the start of each
decode window, page cache steady at 245–246 GiB, and no other session on the
cards — `rig-log-f6` confirmed it was holding off for the duration.

## The first answer is that the other card cannot take the work

With only the A6000 visible the model loads to **47 260 MiB of 49 140** — 1 880
MiB free, against roughly 6 500 MiB for one expert layer. The attention and
hyper-connection tensors and the KV cache that had been split across two
devices all land on the one card and eat the headroom, so the 20 GB the 3090
was holding does not migrate to the A6000 at all. It goes to the host. The
conservative override above is therefore already the *best* one-card
placement, not a handicapped one, and there was no fifth arm to run.

## Then: under 3 % on the mean, and nothing at all on the warm rows

| prompt | 2 cards | 1 card | Δ | draft accepted, 2 cards | 1 card |
|---|---:|---:|---:|---:|---:|
| write-ahead log, cold | 18.16 | 16.05 | **−11.7 %** | 117/244 = 48.0 % | 114/252 = 45.2 % |
| swapped-out page, cold | 21.26 | 22.41 | **+5.4 %** | 120/237 = 50.6 % | 127/213 = **59.6 %** |
| float associativity, cold | 21.88 | 20.05 | **−8.4 %** | 123/226 = 54.4 % | 122/230 = 53.0 % |
| write-ahead log, warm | 23.26 | 21.59 | **−7.2 %** | 117/244 = 48.0 % | 114/252 = 45.2 % |
| swapped-out page, warm | 24.41 | 25.93 | **+6.2 %** | 120/237 = 50.6 % | 127/213 = **59.6 %** |
| **mean of all ten runs** | **21.80** | **21.21** | **−2.7 %** | | |
| **mean of the four warm runs** | **23.84** | **23.76** | **−0.3 %** | | |

Each cell is the mean of the two arms for that configuration, and the
replicates are tight: the same configuration on the same prompt differed by
0.54 tok/s on average and 1.13 at worst between arm *a* and arm *b*. So the
instrument resolves about ±2 %, and the spread that matters is not noise
between repeats — it is **between prompts**, where the same change is worth
−11.7 % on one and +5.4 % on another.

## The scatter is the draft, and it is a placement effect

The right-hand columns explain it. Within a configuration the draft statistics
are byte-identical across arms — greedy sampling with no prefix cache, so the
run is deterministic — but **they differ between configurations**: the
write-ahead-log prompt drafts 244 tokens on two cards and 252 on one, and the
swapped-page prompt accepts 50.6 % on two cards against 59.6 % on one.

That is the placement changing the numerics. A tensor reduced on a different
device in a different order gives a slightly different logit, the greedy
argmax eventually takes a different token, and from there the two
configurations are answering with different text — so the draft is right a
different fraction of the time. The prompt where one card wins by 6 % is
exactly the prompt where one card drafts nine points better, and nine points
of acceptance on a three-token block is worth more than two-and-a-half expert
layers of bandwidth.

So the honest statement of the result is two-sided:

- **The aggregate cost of removing the 3090 is somewhere between nothing and
  3 %**, and the warm rows — the ones that describe a served model answering
  its second question — put it at 0.3 %, which this instrument cannot
  distinguish from zero.
- **This design cannot separate the bandwidth cost from the draft-acceptance
  cost**, because the intervention changes both and they are the same size.
  The 3–7 % the per-layer figures predicted is an over-estimate at this end,
  but how much of the measured −2.7 % is the lost layers and how much is the
  draft is not established here.

The clean follow-up is a no-draft arm: with `-md` removed the acceptance
channel does not exist, and what is left is the bandwidth question on its own.

One more thing the load times say, in passing: 217 s, 153 s, 121 s, 86 s, in
the order the arms ran. The page cache warmed monotonically across the whole
session, and because the arms alternate, the one-card configuration got the
two warmer loads. If that biased anything it biased it toward one card, so the
true cost is if anything slightly above −2.7 % rather than below it.

## What it means for the card

For the decision that prompted this, the answer is that the 20 GB is not what
keeps the 3090 in the machine. Something else has to justify it — and after
the workload for this box turned toward video and image generation, the
argument that does is a different one: diffusion models do not pool across
cards, so a second card is a second independent worker rather than a bigger
GPU, and 24 GB at 936 GB/s is a real worker for 720p and for the
music-generation end of that pipeline. That is a question for the queue in
[`README.md`](../README.md), not a measurement here.

Runner: [`tools/v41/v41-one-card.sh`](../tools/v41/v41-one-card.sh), four arms,
sentinel `V41_1CARD_DONE`. It takes a unique tag as its argument and refuses
without one, because a chain script whose path is reused across launches can be
re-read mid-word by bash while it runs. Signals only the pid recorded at spawn;
the lease and the queue marker were both released on the way out.
