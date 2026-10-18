## Qwen3.8 on two DGX Sparks

These numbers were measured on `e009f1e3da353019cb890f86321c83f0e45180f8` (base `ce1c310ff39080bd4ef885447737cab426e06ff5`) and are carried to this head, not re-measured. The host and verbs source is identical between the two heads, and the later changes add nothing to a successful token (range-diff in the evidence folder). Both arms ran Qwen3.8-Flash-Next UD-Q4_K_XL with a 32-token prompt, context 3072 and a 45 GiB card budget. Each run was a fresh process load, then 32 stepped warm tokens and 64 timed greedy tokens. Arm A is one Spark: one process with the stage and the expert tier on its card (`BLOOMERY_TIER_LINK=shared`). Arm B is two Sparks: the stage on node 0, the tier on node 1 under `tier_server`, one process on each card, `BLOOMERY_TIER_LINK=rdma`. The order was A1 B1 A2 B2 in one sitting under `tools/ref/lease-hold.sh --card docs/cards/node-decode.card` on both Sparks.

| Run | Sparks | 64 timed tokens | tok/s | Read ceiling, tok/s [derived] | Fraction of the ceiling [derived] | Control round trips a token | go/done pairs a token |
|---|---|---|---|---|---|---|---|
| A1 | one | 3.152 s | 20.31 | 38.66 | 0.525 | 0 | 48 |
| B1 | two | 2.877 s | 22.24 | 43.94 | 0.506 | 1 | 48 |
| A2 | one | 3.119 s | 20.52 | 38.66 | 0.531 | 0 | 48 |
| B2 | two | 2.865 s | 22.34 | 43.94 | 0.508 | 1 | 48 |

The read ceiling is the plain-read rate a card reached in the same sitting divided by the bytes the plan reads a token. The plan reads 6,373,736,000 B a token [derived]: the serial bytes, each layer's shared bytes and 10 routed experts a layer, from the `decode read terms` line. On one Spark, node 0's card reads all of it at its best plain stream read of the sitting, 246.4 GB/s. On two Sparks, the routed hits put 766,321,600 B of each token on node 1 (242.9 GB/s) and 5,607,414,400 B on node 0 [derived], and the slower card sets the ceiling. Both arms reach about half of their ceiling.

The card predicted 1 to 4 control round trips a token; the two-Spark runs counted 64 round trips in 64 tokens, and the one-Spark runs 0. Both arms hand off 3072 go/done pairs in 64 tokens, one pair for each of the 48 tier layers; in B these cross the RDMA link. One pair is 41,220 B of go and 409,612 B of done, so a token sends 21,639,936 B [derived]. At B's rate that is 0.48 GB/s [derived], 3.5% of the 13.59 GB/s byte ceiling that `link_probe --size 33554432` measured on the same link in the same sitting (one-way p50 2469.03 us) [derived].
source: https://github.com/midagedev/bloomery/pull/358 (author @juliankang4), section 'Qwen3.8 on two DGX Sparks'
