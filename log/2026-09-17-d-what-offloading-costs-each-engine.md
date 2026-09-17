# What offloading costs each engine

*2026-09-17, 21:19–21:37. RTX A6000 48G, one card, one lease per take, io pressure 0 at every
start. ik_llama.cpp c10fbbcc, mistral.rs at `d5ae0f1` plus [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430)
built from source on the box, toktape 0.2.4. Qwen3.6-35B-A3B UD-Q6_K, one stream, thinking on,
`-n 512`, the same single 238-token prompt in every row. Figures read out of the tapes by
[`tools/tape-row.py`](../tools/tape-row.py).*

[Entry -c](2026-09-17-c-what-mistral-rs-can-and-cannot-offload.md) settled which offload knobs each
engine *has*. It said nothing about the price, and the price turns out to be the entire answer: the
two engines do not implement the same feature more or less well, they implement two different
features with the same name.

## The design, and the two things that had to be controlled first

One level means "the experts of the last L of the model's 40 blocks are off the card", and each
engine expresses it its own way — `-ncmoe L` against `-n 0:$((40-L))`. Both put the *same* blocks on
the host, which was checked rather than assumed: ik names each tensor it moves (`blk.30.…` through
`blk.39.…` at L=10) and mistral.rs prints its ranges (`Layers 0-29: cuda[0]` / `Layers 30-39: cpu`).
The runner is [`tools/engine-ab/offload-cost-sweep.sh`](../tools/engine-ab/offload-cost-sweep.sh).

The plan had been to pair the rows on measured VRAM. That was wrong twice over, and the server log
said so in a line nobody had read before:

```
WARN mistralrs_core::pipeline::normal: Device mapping contains a mix of GPU and CPU.
     There is no CPU support for PagedAttention, disabling PagedAttention.
```

**Any CPU layer at all turns PagedAttention off for the whole run.** So the VRAM drop from offloading
one 760 MB block is 2 720 MiB, most of which is the vanished paged pool rather than weights, and
VRAM cannot be the pairing axis. Worse, it means a naive L0-to-L1 comparison moves two variables at
once. The control row is therefore all forty blocks on the card with PagedAttention off by hand
(`PA=off`, a new knob on `mrs-take.sh` whose default is `on` so that every earlier row stays
reproducible): **102.7 tok/s against 111.2 with it on, a 7 % effect.** Whatever the offload costs, it
is not that. The pairing axis is the weight bytes of the blocks in each range, summed from the GGUF's
own tensor sizes.

## mistral.rs: 442 ms per offloaded layer, per token

| blocks on host | weight bytes | srv each | ITL p50 | TTFT | tokens out |
|---:|---:|---:|---:|---:|---:|
| 0, PagedAttention on | 0 | **111.2** | 9.5 ms | 169 ms | 512 |
| 0, PagedAttention off | 0 | **102.7** | 10.2 ms | 120 ms | 512 |
| 1 | 0.76 GB | **2.2** | 453.9 ms | 4 709 ms | 512 |
| 4 | 3.0 GB | **0.6** | 1 779.1 ms | 15 998 ms | 126 |
| 10 | 7.6 GB | **0.2** | 4 425.4 ms | 42 716 ms | 64 |

The last two rows ran out the 240 s wall cap rather than reaching 512 tokens, which is why their
token counts are short; the rate is a rate either way.

Subtract the control and divide, and the sweep stops being a curve:

```
(453.9  - 10.2) /  1 = 443.7 ms
(1779.1 - 10.2) /  4 = 442.2 ms
(4425.4 - 10.2) / 10 = 441.5 ms
```

**A constant 442 ms per offloaded layer per token**, flat to a third of a percent across a tenfold
change in how much is offloaded. A cost that is exactly linear in the number of offloaded layers and
independent of anything else is not a bandwidth story — a bandwidth story would bend as the
transfers started to overlap. It is a fixed amount of work done once per layer per token.

The code says what that work is, in the function [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430)
patched, one line above where the patch landed (`mistralrs-quant/src/gguf/cpu.rs`):

```rust
// Dequantize all weights to f32
let weights = qtensor.dequantize(device)?;
let unquant = UnquantLinear::new(QuantMethodConfig::Unquantized(Linear::new(weights, None)))?;
```

Every forward pass dequantizes the block's **entire** expert stack to F32 and builds a fresh
`UnquantLinear` around it. In decode a forward pass is one token, so a Q6_K block of 630 MB of expert
matrices becomes about 2.5 GB of F32 per token, per offloaded layer, and is thrown away. 3.1 GB of
traffic in 442 ms is 7 GB/s, which is the right order for a single dequantize pass over host memory.
Nothing about this uses the fact that a MoE layer activates 8 of its 256 experts — the whole stack is
unpacked to serve eight of them.

That is worth saying plainly because it was missed while patching the very same function this
morning: the dtype bug was fixed on the line below a per-token full dequantize, and the bigger defect
was not noticed until the rate was measured. Reading the code found one bug; running it found the
one that matters.

## ik_llama.cpp: 0.20 ms per offloaded layer, per token

| blocks on host | srv each | ITL p50 | TTFT | eff GB/s |
|---:|---:|---:|---:|---:|
| 0 | **129.0** | 7.7 ms | 284 ms | 383 |
| 1 | **124.7** | 7.9 ms | 274 ms | 370 |
| 4 | **116.2** | 8.5 ms | 308 ms | 345 |
| 10 | **101.8** | 9.7 ms | 334 ms | 302 |

```
(7.9 - 7.7) /  1 = 0.20 ms
(8.5 - 7.7) /  4 = 0.20 ms
(9.7 - 7.7) / 10 = 0.20 ms
```

Also exactly linear, also a fixed cost per layer per token, and **0.20 ms against 442 ms — a factor
of 2 200.** Ten blocks, 6.3 GB of expert weight off a 48 GB card, costs 21 % of the rate.

## They are not the same feature. ik never moves the math

The reason is in ik's log, and it is not the word anyone would expect:

```
Tensor blk.39.ffn_up_exps.weight (size = 210.00 MiB) buffer type overridden to CUDA_Host
```

`CUDA_Host` is pinned host memory that CUDA kernels can read directly. The weights leave the card;
**the matmul does not.** So per token per layer the GPU reads only the experts the router actually
chose — 8 of 256, about 19.7 MB of that block's 630 MB. At PCIe 4.0 x16 line rate that is 0.79 ms,
and the measured marginal cost is 0.20 ms, so the transfer is largely overlapped with compute on the
layers that are still resident. Under-line-rate is the expected shape here, not a contradiction.

mistral.rs's `-n` does the opposite: the layer goes to the CPU *device* and the expert matmul runs
there, on all 256 experts, in F32. One engine relocates the weights and keeps the arithmetic where
the arithmetic is fast; the other relocates the arithmetic. That is the whole 2 200×, and it is why
"mistral.rs has layer-granular offload" is true and useless.

### The control arm that could not be built, and what it established instead

The obvious next question — is mistral.rs slow because CPU expert matmul is slow, or because it
dequantizes everything? — needs ik doing real CPU compute for comparison. This box's own daily recipe
looks like exactly that, `-ot exps=CPU`, so three rows were run with
`-ot 'blk\.3[0-9]\.ffn_.*_exps=CPU'`. They came back at 124.9, 116.9 and 101.9 tok/s: **identical to
the `-ncmoe` rows**, and the server log shows those tensors overridden to `CUDA_Host` again, not to
`CPU`.

ik's source explains it rather than the flag being ignored. `src/llama-load-tensors.cpp:265` sets
`default_cpu_buft = llama_default_buffer_type_cpu(true)`, and `src/llama.cpp:362-366` returns
`ggml_backend_cuda_host_buffer_type()` for that under `GGML_USE_CUDA`; line 270 then normalises *any*
host buffer type to it. **On a CUDA build, `-ot …=CPU` and `-ncmoe N` land in the same place, and
neither gives CPU-side expert compute.** So the arm is invalid as designed and is not a row in any
table above — what it establishes is that ik offers no CPU-compute tier at all here, which also means
this box's `-ot exps=CPU` recipe has never been CPU compute. Expert weights in host RAM, yes;
computed on the host, no. The question mistral.rs's 442 ms is measured against therefore has no ik
answer on this hardware, and the comparison is between two tiers rather than between two kernels.

## What this does to the choice, and what goes upstream

Entry -c called the missing tensor-level placement "a feature-sized hole, not a bug" and ranked it
above the dtype bug. That ordering survives and gets sharper: even if mistral.rs grew an
`-ot exps=CPU` equivalent tomorrow, at 442 ms per layer per token it would be unusable, because the
tier it can place weights into is the one where it also insists on doing the math. What it would need
is ik's tier — weights in pinned host memory, read sparsely by the GPU — which is a different feature
from the one it has.

The per-token dequantize is the upstream candidate and it is a bigger one than #2430. Two shapes, in
increasing order of how much of the engine they touch: cache the dequantized stack, which trades host
RAM for the repeated work and is a few lines; or gather only the routed experts before dequantizing,
which is what the sparsity is for. Not filed. A rate is not a diagnosis — 442 ms is consistent with
the dequantize and with several other things, and the next step is a profile of one offloaded layer
that attributes the milliseconds, the same discipline that kept ik's batch-2 finding
([entry -b](2026-09-17-b-where-the-four-stream-gap-actually-is.md)) unfiled.

## State

Twelve tapes in `/home/user/toktape-runs` from this sweep, three of them from the invalid `-ot …=CPU`
arm and kept as the evidence for what that flag resolves to. All the mistral.rs rows carry
`contended: yes` for the known reason — toktape identifies the attached server by process name and
`mistralrs` is not a llama.cpp comm — which the toktape side closed today as TTP-107 (`e4874f2`,
v0.2.5): `/props` may now declare `engine.server_pid`, and
[`tools/mrs/mrs-shim.py`](../tools/mrs/mrs-shim.py) now does, along with per-device `placement` rows
built from the engine's own layer ranges and `vram_kv_bytes: 0` when any CPU layer has taken
PagedAttention away. The box still runs toktape 0.2.4, so the flip from `contended: yes` to `no` is
**unobserved**; upgrading the recorder and re-taking one mistral.rs/ik pair is what closes it, and
neither belongs in the middle of a sweep. The A6000 is idle and the lease is released.
