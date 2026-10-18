# PR #420, the lines the film quotes

source: https://github.com/midagedev/bloomery/pull/420 (author @juliankang4, merged 2026-10-17T18:12:14Z), body read with `gh pr view 420 -R midagedev/bloomery --json body` on 2026-10-18
title: gpu: open GLM and V4.1 node expert tiers

body line 5: GLM-5.3-Flash and DeepSeek-V4.1-Flash can open an expert tier on another node through the common node loader. The adapters supply tensor geometry, activation format and the expert program. V4.1's Q8 activation staging reuses the existing quantized-slot layout and host executor.
body line 43: V4.1's ordinary generator completes 24 IDs locally and on two nodes with the stage R8 lever enabled. Its missing-sidecar fallback is explicit in the load log. All 24 IDs differ between placements `a` and `0+1`; they are not a same-placement oracle. That remote load uses a resident GPU tier, so a separate equal-ownership diagnostic is needed to exercise the repaired file-backed callback. The two-node run predates the arm state-check change and was not repeated.
body line 62: A fresh two-DGX-Spark GLM generation on `76b533fb5355e588f60f0bc5bb4fe32ca8dcf6ea` opens and closes the node tier and matches all 24 generated IDs from the pinned same-NextN oracle. It uses the same prompt, context 256, 16 GiB card budget, graph mode, step-fed prefill and MTP target load. Both processes exit 0 within the 600-second correctness bound.
body line 64: The model pins are `unsloth/GLM-5.3-Flash-GGUF` at `a38483c8cd5df544f53d70fb281afe97369d5ab6` (UD-Q4_K_XL) and `vcruz305/DeepSeek-V4.1-Flash-GGUF` at `c4a085541cb53f67ee5e57b63d255e80cef286e7` (Q3_K_M).
body line 105: Each model check uses two DGX Sparks with NVIDIA GB10 (SM 12.1), aarch64 host CPUs, 128 GB unified memory per system, driver 595.84 and CUDA 13.3.1, connected by a direct RoCE link. The two models use different pairs.
