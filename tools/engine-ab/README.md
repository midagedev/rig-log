# engine-ab

Two scripts from the 2026-09-13 session, copied as they ran.

`engine-ab.sh` — ik_llama.cpp versus mainline `llama-server` on the same
file and placement, one after the other, three greedy 200-token completions
each through `/completion`. It refuses to start a server while any
`llama-perplexity`, `llama-server`, `sha256sum` or repack is running, while
anything holds a GPU, or while the target port has a listener — the first
version of this comparison measured a stranger's server through `/health`,
which is why the gate is this paranoid. It waits for the engine's own
readiness line; the pattern here is the corrected one (mainline prints
`listening on http://`, ik prints `HTTP server listening`).

`embd-takeover.sh` — the lead's takeover of the engram attribution round:
waits on the two repack pids, finalizes the table-only variant and runs
its perplexity. Kept because the numbers in the engram entry came out of it.

Both assume the workstation's paths and are not portable.
