# dspark

The 2026-09-13 DSpark wiring for DeepSeek-V4.1-Flash on ik_llama.cpp, as it ran.

`ik-dsv41-draft.py` — the exact-string patch applied to the ik tree (commit
`7b79b229` there): V4.1 draft flavor detected by the missing `output_hc_base`,
head tensors optional, per-head q norm skipped, hyper-connection mix carried
one sublayer behind, last FFN mix as the output collapse.

`fix-target-layers.py` — rewrites `dflash.target_layers` in the converted
draft from `[38,39,40]` to `[37,38,39]`, tensors untouched. The docstring says
why (V4 captures after the layer, V4.1 before it; the converter inherited V4).

`dspark-test.sh` — the gate: no draft, corrected draft, original draft, same
three prompts, greedy, acceptance from the server's timings. Stops the serving
process first and restarts it last. Do not edit it while it runs; bash reads
scripts incrementally and the third run died that way.

`set-gguf-keys.py` — the general form of the rewrite above: copy a GGUF with
metadata keys replaced or added, tensors byte for byte. Used to add
`dflash.attention.causal=false`, which the converted draft lacks; without it
ik falls back to a causal mask inside the proposal block, while the reference
lets every block position see the whole block.

`dspark-sweep.sh` — the faster gate. One server load per draft file, and every
prompt (twenty) and every `n_max` inside that load, through the per-request
`speculative.n_max` override. Rows go to a JSONL file with the load average
next to each, since acceptance does not depend on load but tok/s does. It
drops `/tmp/cpu-busy.flag` so a CPU benchmark running alongside holds its
timing runs, and an EXIT trap restarts the serving process even on failure.
