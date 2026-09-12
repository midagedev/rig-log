#!/usr/bin/env bash
# Measure one run against a running llama-server, and record everything that
# would be needed to explain the number later.
#
#   usage: bench-serve.sh <label> [n_predict] [n_parallel] [port]
#
# Built for a model that lives in three tiers at once. Throughput alone cannot
# tell a slow run caused by expert weights missing from the page cache from one
# caused by engram rows coming off the drive, so this captures both: the
# process's resident set split into anonymous and file-backed pages, its major
# fault count, and the model drive's own read counters, each as a delta across
# the run. Per-token figures come out of those deltas.
#
# Run it on a quiet machine. A download writing to the same drive will both
# evict expert pages and compete for the IOPS this is trying to attribute to
# engram, and the resulting numbers are not wrong so much as meaningless.
set -euo pipefail

LABEL=${1:?usage: bench-serve.sh <label> [n_predict] [n_parallel] [port]}
NPRED=${2:-128}
NPAR=${3:-1}
PORT=${4:-8001}
HOST=127.0.0.1

PID=$(pgrep -f '[l]lama-server' | head -1)
[ -n "$PID" ] || { echo "no llama-server running" >&2; exit 1; }

# The drive holding the model, for /proc/diskstats. Read the server's own -m
# argument so this cannot drift from what is actually loaded.
MODEL=$(tr '\0' '\n' < "/proc/$PID/cmdline" | grep -A1 -x -- '-m' | tail -1)
DEV=$(lsblk -no PKNAME "$(findmnt -no SOURCE --target "$(dirname "$MODEL")")")

field() { awk -v k="$1" '$1==k":"{print $2}' "/proc/$PID/status"; }
faults() { awk '{print $10, $12}' "/proc/$PID/stat"; }   # min_flt, maj_flt
diskrd() { awk -v d="$DEV" '$3==d{print $4, $6}' /proc/diskstats; }  # reads, sectors

read -r MIN0 MAJ0 <<<"$(faults)"
read -r RD0 SEC0 <<<"$(diskrd)"

# Which prompt to use. This matters more than it looks: engram is a hash-indexed
# lookup over token history, so the SAME prompt at temperature 0 generates the
# same tokens, touches the same rows, and finds them all in the page cache the
# second time. Repeating one prompt measured 20.14 tok/s with zero major faults
# -- a number the model can never produce on work it has not already done.
#
# So each run takes a different prompt. Rotate the index to measure steady
# state; hold it fixed only when deliberately measuring the cached ceiling.
PROMPTS=(
 'Explain, in one paragraph, why a mixture-of-experts model can have far more parameters than it reads per token.'
 'Describe how a write-ahead log lets a database survive a crash without losing committed transactions.'
 'What makes reproducing a distributed systems bug harder than reproducing a single-process one? Be concrete.'
 'Walk through what happens, step by step, when a process touches a page that has been swapped out.'
 'Compare optimistic and pessimistic concurrency control, and say when each one wins.'
 'Explain why floating point addition is not associative, and give an example where it matters.'
 'How does a modern branch predictor work, and what kinds of code defeat it?'
 'Describe the tradeoffs between column-oriented and row-oriented storage for analytic queries.'
)
IDX=${BENCH_PROMPT:-0}
PROMPT=${PROMPTS[$(( IDX % ${#PROMPTS[@]} ))]}

# ignore_eos: a benchmark decides how many tokens it measures. Letting the
# model stop where it likes gave a 19-token sample on the first run, which is
# too few to separate steady-state cost from the cold-cache warmup in it.
BODY=$(printf '{"prompt":%s,"n_predict":%d,"temperature":0,"seed":42,"cache_prompt":false,"ignore_eos":true}' \
       "$(printf '%s' "$PROMPT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" "$NPRED")

T0=$(date +%s.%N)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for i in $(seq 1 "$NPAR"); do
    curl -s --max-time 1800 -H 'Content-Type: application/json' \
         -d "$BODY" "http://$HOST:$PORT/completion" > "$tmp/r$i.json" &
done
wait
T1=$(date +%s.%N)

read -r MIN1 MAJ1 <<<"$(faults)"
read -r RD1 SEC1 <<<"$(diskrd)"

BENCH_PID="$PID" python3 - "$tmp" "$LABEL" "$NPAR" "$T0" "$T1" \
         "$MIN0" "$MAJ0" "$MIN1" "$MAJ1" "$RD0" "$SEC0" "$RD1" "$SEC1" \
         "$(field VmRSS)" "$(field RssAnon)" "$(field RssFile)" "$MODEL" <<'PY'
import glob, json, os, sys
(d, label, npar, t0, t1, min0, maj0, min1, maj1,
 rd0, sec0, rd1, sec1, vmrss, anon, rfile, model) = sys.argv[1:]
npar = int(npar); wall = float(t1) - float(t0)

runs = []
for p in sorted(glob.glob(os.path.join(d, "r*.json"))):
    try:
        runs.append(json.load(open(p))["timings"])
    except Exception:
        pass
if not runs:
    sys.exit("no usable response; is the server still up?")

dec_n  = sum(r["predicted_n"] for r in runs)
pre_n  = sum(r["prompt_n"] for r in runs)
dec_ms = max(r["predicted_ms"] for r in runs)
pre_ms = max(r["prompt_ms"] for r in runs)

maj = int(maj1) - int(maj0)
rd  = int(rd1) - int(rd0)
sec = int(sec1) - int(sec0)

def kb(x): return int(x.split()[0])
size = os.path.getsize(model)
# sharded gguf: the whole set, not just the shard named on the command line
base = model.rsplit("-", 3)[0]
total = sum(os.path.getsize(f) for f in glob.glob(base + "-*.gguf"))

print("== %s ==" % label)
print("  decode          %8.2f tok/s   (%d tokens, %.0f ms%s)"
      % (dec_n / (dec_ms / 1000), dec_n, dec_ms,
         ", %d streams" % npar if npar > 1 else ""))
print("  prefill         %8.2f tok/s   (%d tokens)" % (pre_n / (pre_ms / 1000), pre_n))
print("  wall            %8.2f s" % wall)
print("  --")
print("  VmRSS           %8.1f GB" % (kb(vmrss) / 1e6))
print("    RssAnon       %8.1f GB   (copied into memory)" % (kb(anon) / 1e6))
print("    RssFile       %8.1f GB   (mapped from the file)" % (kb(rfile) / 1e6))
print("  model on disk   %8.1f GB" % (total / 1e9))
print("  not resident    %8.1f GB   <- engram stays off memory if this is ~84.6"
      % (total / 1e9 - kb(vmrss) / 1e6))
print("  --")
print("  major faults    %8d      %.1f per token" % (maj, maj / dec_n))
print("  drive reads     %8d      %.1f per token" % (rd, rd / dec_n))
print("  drive bytes     %8.1f MB   %.1f KB per token"
      % (sec * 512 / 1e6, sec * 512 / dec_n / 1e3))

# Append the run so the dashboard can show it next to the live charts. A run
# that is only printed to a terminal is a run nobody can compare against.
import datetime, subprocess
cmdline = open("/proc/%s/cmdline" % os.environ["BENCH_PID"], "rb").read().decode().split("\0")
def flagval(f):
    return cmdline[cmdline.index(f)+1] if f in cmdline else None
try:
    vram = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                           "--format=csv,noheader,nounits"],
                          capture_output=True, text=True, timeout=10).stdout.split()
    vram = [int(x) for x in vram if x.isdigit()]
except Exception:
    vram = []
rec = {
    "t":        datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "label":    label,
    "decode":   round(dec_n/(dec_ms/1000), 2),
    "prefill":  round(pre_n/(pre_ms/1000), 2),
    "tokens":   dec_n,
    "streams":  npar,
    "rss_gb":   round(kb(vmrss)/1e6, 1),
    "offmem_gb": round(total/1e9 - kb(vmrss)/1e6, 1),
    "majflt_tok": round(maj/dec_n, 1),
    "drive_kb_tok": round(sec*512/dec_n/1e3, 1),
    "vram_mib": vram,
    "ot":       flagval("-ot"),
    "ctx":      flagval("-c"),
    "lazy":     flagval("--lazy-mode"),
    "prompt_idx": int(os.environ.get("BENCH_PROMPT", "0")),
}
path = os.environ.get("BENCH_LOG", "/usr/share/netdata/web/rig-runs.jsonl")
try:
    with open(path, "a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("  --\n  recorded to %s" % path)
except OSError as e:
    print("  --\n  not recorded: %s" % e)
PY
