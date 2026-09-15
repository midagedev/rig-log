# A quiet machine is a protocol, not a state

*Written 2026-09-13 after one day in which three measurement jobs ran into
each other five times on one workstation. The incidents are in
[`log/2026-09-13-deepseek-v41-on-ik-llama.md`](../log/2026-09-13-deepseek-v41-on-ik-llama.md);
this is the method that comes out of them.*

Every number in this repo is supposed to come from a quiet box. Today showed
that "quiet" was being decided by three different signals owned by three
different scripts, and that none of them could see the thing that actually
made the box busy. The fix has three layers, in the order this repo's method
asks for: close the class of failure structurally, turn it into a check that
fails, and make the next occurrence diagnosable from the data rather than
from a hand-built timeline.

## What went wrong, concretely

Five collisions, one root:

1. A CPU kernel benchmark ran two baselines while a 200 GB model was loading
   alongside. Its gate was the load average, which stayed under 4 for the
   first minutes of a load that is bound on NVMe reads, not CPU.
2. A stopped orchestration chain had already launched a sweep with `setsid`.
   Stopping the local waiter did not stop the remote script. A second sweep
   was launched to the same log path in the same minute; two 200 GB loads
   overlapped, one server died allocating 27 GB of VRAM that the other held.
3. The first sweep's exit handler removed the shared busy flag from under the
   second, and the kernel benchmark, seeing no flag, ran a five-minute thread
   sweep into the second load.
4. The kernel benchmark's follow-up runs used a load-average gate of their own
   and ran into two more loads (15:13, 15:25) for the same reason as in 1.
5. Every one of these was found afterwards by reading timestamps in three log
   files and lining them up by hand. Twice.

The three signals in play were `/tmp/rig-quiet` (the repack scripts pause on
it), `/tmp/cpu-busy.flag` (the sweep sets it, the benchmark was asked to honour
it), and `loadavg < 4` (what the benchmark actually checked). Each was right
for the script that wrote it and invisible to the others.

## Layer 1 — one owner for "busy"

There is one lease, one file, one tool. `tools/quiet/lease.sh`:

```
lease.sh acquire <reason>   # flock the lease file, write "<pid> <reason> <start>"; refuse if held
lease.sh wait               # block until the lease is free AND the box is quiet (below)
lease.sh release            # remove the lease only if the pid in it is ours
lease.sh status             # print holder, age, and the quietness signals
```

"Quiet" is not the load average. It is all of:

- no lease held by a live pid;
- `/proc/pressure/io` `some avg10` under a threshold (a model load pins this
  high from the first second, long before `loadavg` moves);
- no `llama-server` or `llama-bench` process other than the one on the
  serving port, if any;
- one-minute load average under a threshold, last, as the coarse check it is.

Every script that measures — sweep, perplexity, repack, kernel bench, tok/s —
starts with `lease.sh wait && lease.sh acquire "<what>"` and ends, in its
exit trap, with `lease.sh release`. A second copy of the same script cannot
start while the first holds the lease, which also closes incident 2. A script
that launches remote work with `setsid` writes the child's pid to a file
next to its log so the chain can be stopped from either end.

The serving process on the published port is not "busy": measurements that
need the GPUs stop it and restart it, as they always did, and the lease is
what says whose turn that is.

## Layer 2 — give delegates the tool, not the instruction

The benchmark agent was told, in its spec, to honour the flag. It wrote its
own gate instead, and the gate it wrote was the load average. This is not a
compliance failure to be fixed by a sterner sentence; a protocol expressed
as prose is one the delegate re-implements from memory. The lead hands over
the runner script, and the delegate changes arguments. The runner calls the
lease. There is nothing to re-implement.

The same rule applies to the lead's own chains: the orchestration that
launches a sweep goes through the same script the delegate would get.

## Layer 3 — record the witness with the measurement

Every measurement row carries its own evidence of quietness, taken at start
and at end: one-minute load average, `/proc/pressure/io` `some avg10`, the
list of live `llama-*` processes with their ages, and the page-cache size
from `/proc/meminfo`. The sweep's JSONL gets these fields; the perplexity
and benchmark wrappers print them on the first and last line of every raw
file. When a row is suspect, the row says so; nobody reconstructs a
timeline.

`toktape` records a `contended: yes/no` label on its cards from the same
kind of signals. A measurement that will end up on a card should carry the
same witness, so the card and the raw row agree about what the box was
doing.

## Two smaller rules from the same day

- **A single failed request never ends a measurement arm.** One `500` on
  one prompt stopped a twenty-prompt arm at eleven. The harness logs the
  failure as a row and continues.
- **Before flipping a flag, grep every use of it.** The first attempt at a
  mask fix flipped a model-wide `causal_attn`; that flag also gates the
  KV-cache update, batch sizing, and defragmentation. The correct patch
  touched exactly the two lines that differed from the reference, through a
  flag that nothing else reads. The number of lines changed should match
  the number of lines that were wrong.

## Starting and stopping a remote server (2026-09-15)

Three facts about bash, measured on the workstation after a TabbyAPI check
runner stopped the wrong process, kept both cards held, and released the
lease anyway:

- **`$!` is the server only when the background job is a simple command.**
  `cd dir && setsid nohup server … &` backgrounds a compound command, so
  bash forks a subshell and `$!` is that subshell. The runner's SIGINT and
  SIGKILL went to it; the server ran on with 46.1 GB and 18.7 GB held.
  Launch with `cd dir` on its own line, then `ENV=… setsid nohup server … &`,
  and assert straight after launch that `ps -o sid= -p $!` equals `$!`.
- **A background job starts with SIGINT ignored.** A non-interactive bash
  gives asynchronous commands SIGINT and SIGQUIT as ignored
  (`/proc/<pid>/status` `SigIgn` ended in `7`), and Python keeps an ignored
  SIGINT ignored. A server that installs its own handler still stops on
  SIGINT; a plain script does not. Stop with SIGTERM.
- **The session outlives its leader.** exllamav3's CPU expert worker is a
  spawned child; when the leader exits, members of its session can remain
  and hold VRAM. Teardown waits for the leader, then signals the remaining
  members of the session it created, and never escalates to SIGKILL on its
  own. If the cards are not back, the lease stays held and the run reports
  failure, so the next load cannot start on top of it.

The runners that follow this are `tools/tabby/tabby-check.sh` and
`tools/exl3/exl3serve-check.sh`. The cleanup that day identified the holder
from `nvidia-smi --query-compute-apps`, verified its working directory, user
and start time, unloaded through the server's own API, and then signalled
that one pid.

## What reading bought

The largest saving of the day was not a tool. Three hypotheses (YaRN on the
draft rope, the draft re-quantization, and the size of the mask effect's
upper bound) were closed or bounded by reading the reference implementation
against the port, before or instead of a nine-minute load and a fifteen-minute
sweep each. The order for a hypothesis is now: read the reference and the
port side by side, decide what only an experiment can answer, and run only
that. Then the experiment measures a magnitude rather than an existence.

## Status

| layer | state on 2026-09-13 |
|---|---|
| lease tool | to be written (`tools/quiet/lease.sh`); until then the sweep writes its pid to `/tmp/cpu-busy.flag` and removes it only if it is its own |
| runner handed to delegates | the next benchmark round gets `tools/quiet/`-aware runner scripts from the lead |
| witness fields in rows | sweep rows carry `load1`; IO pressure, process list and page cache are to be added |
| request failure tolerated | done in `tools/dspark/dspark-sweep.sh` |
| grep-before-flip | rule only |
| remote server launch and teardown | done in `tools/tabby/tabby-check.sh` and `tools/exl3/exl3serve-check.sh` (2026-09-15); the lease file there is a plain `~/gpu-lease`, not yet `lease.sh` |
