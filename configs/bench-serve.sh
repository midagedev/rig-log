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

PROMPT='Explain, in one paragraph, why a mixture-of-experts model can have far more parameters than it reads per token.'
BODY=$(printf '{"prompt":%s,"n_predict":%d,"temperature":0,"seed":42,"cache_prompt":false}' \
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

python3 - "$tmp" "$LABEL" "$NPAR" "$T0" "$T1" \
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
PY
