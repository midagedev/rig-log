# engram-repack

Scripts behind `log/2026-09-13-engram-q8-repack.md`: graft the Q8_0
engram tensors from the uploader's Q8_0 GGUF into the Q3_K_M shards, then
measure whether it mattered.

- `repack.py`, `test_roundtrip.py`, `repack_all.sh`, `finalize.sh`,
  `load_check.sh` — the repack itself (streaming, 1 GiB slices, flock per
  output, verify-then-rename). Paths are the ones on this machine.
- `probe.py`, `probe2.py` — the two hand-written factual probes (24 and 29
  scored questions); both saturated.
- `make-sample.py`, `popqa.py`, `popcmp.py` — the PopQA sample (200 from
  popularity 5–128, 200 from 656–1494, seed 13), the greedy runner with
  alias exact-match, and the comparison by band.
- `run-probe.sh` — serve each variant in turn with `configs/v41-serve.sh`
  and run one probe against it.
