#!/bin/bash
# ik-v41-verify.sh <branch> <tag> [draft]
#
# Build one branch of the DeepSeek-V4.1 port and re-measure the two claims the
# PR makes: wikitext-2 perplexity CPU-only, and decode at the published split.
# With a third argument it also runs the DSpark draft arm.
#
# Gates: before 23:30 KST, both GPUs idle, lease free. The server pid is the one
# recorded at spawn (asserted session leader) and is stopped with SIGTERM only;
# nothing is ever matched by command line. Sentinel IK_V41_DONE / IK_V41_FAILED.
set -u
BRANCH=$1; TAG=$2; DRAFT=${3:-}
TREE=${TREE:-/home/user/ik_llama.cpp}; BIN=${BIN:-build/bin/llama-server}; OUT=/home/user/ik-v41/$TAG; LEASE=/home/user/gpu-lease; PORT=8011
PLAIN=/models/DeepSeek-V4.1-Flash-Q3_K_M/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
# 2026-09-16: the draft arm's file, `-engramQ8-tokembdBF16`, was deleted in the storage
# pass. It is re-graftable in about forty minutes from the two sources that were kept
# (`-Q3_K_M` and `-Q8_0-engram-src`, tools/engram-repack/repack_all.sh). Until it is,
# the draft arm runs against the served file below, which is that file plus the WKS-13
# attention graft: its decode is about 10 % higher, so a number from this arm is NOT
# comparable to the 20.4-20.7 tok/s rows recorded for PR #2455 on 2026-09-15.
# The perplexity claim is unaffected — it uses PLAIN, which is still on disk.
BF16=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
DMODEL=/models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.tl37.gguf
OT='blk\.[0-3]\.ffn_.*_exps=CUDA0,blk\.[4-5]\.ffn_.*_exps=CUDA1,exps=CPU'
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
SPID=""; LEASE_TAG="ik-v41-$TAG"
finish(){ rc=$1
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    say "stopping server pid $SPID (session leader) with SIGTERM"; kill -TERM $SPID
    for i in $(seq 120); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
    kill -0 $SPID 2>/dev/null && { say "server $SPID alive after 120 s; not escalating"; rc=1; }
  fi
  if [ -n "$SPID" ]; then
    members(){ ps -eo pid=,sid= | awk -v s=$SPID '$2==s && $1!=s{printf "%s ", $1}'; }
    for i in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
    [ -n "$(members)" ] && { say "session members left: $(members) -> SIGTERM"; kill -TERM $(members) 2>/dev/null; sleep 10; }
  fi
  for i in $(seq 45); do [ "$(maxgpu)" -lt 2000 ] && break; sleep 2; done
  say "gpus after: $(gpus)"
  if [ "$(maxgpu)" -lt 2000 ]; then
    [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  else
    say "GPUS NOT RELEASED: lease kept ($(cat $LEASE 2>/dev/null))"; rc=1
  fi
  [ $rc -eq 0 ] && echo IK_V41_DONE || echo IK_V41_FAILED
  exit $rc; }

[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo IK_V41_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo IK_V41_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo IK_V41_FAILED; exit 1; }
echo "$LEASE_TAG $(date -Is) $$" > $LEASE

cd $TREE || finish 1
[ -z "$(git status --porcelain)" ] || { say "refused: $TREE is dirty"; finish 1; }
if [ -z "${SKIP_BUILD:-}" ]; then
git fetch -q fork "$BRANCH" || finish 1
git checkout -q --detach FETCH_HEAD || finish 1
fi
say "$TAG at $(git log -1 --format='%h %s')"
say "io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"

if [ -z "${SKIP_BUILD:-}" ]; then
say "building"
cmake -B build -DGGML_CUDA=ON -DGGML_SCHED_MAX_COPIES=1 -DCMAKE_CUDA_ARCHITECTURES=86 -DGGML_NATIVE=ON > $OUT/cmake.log 2>&1 || { say "cmake failed"; tail -20 $OUT/cmake.log; finish 1; }
cmake --build build -j 32 --target llama-server llama-perplexity > $OUT/build.log 2>&1 || { say "build failed"; grep -i -m20 error $OUT/build.log; finish 1; }
say "build ok"
fi

if [ -z "${SKIP_PPL:-}" ]; then
say "gate 1: wikitext-2, 4 chunks, CPU only (reference 2.2258 +/- 0.0622)"
CUDA_VISIBLE_DEVICES="" ./build/bin/llama-perplexity -m $PLAIN -f /home/user/eval/wiki.test.raw \
  -c 2048 --chunks 4 -b 2048 -ngl 0 -t 32 > $OUT/ppl.log 2>&1
grep -E "^\[[0-9]\]|Final estimate" $OUT/ppl.log | tail -3
fi

M=$PLAIN; EXTRA=""
if [ -n "$DRAFT" ]; then M=$BF16; EXTRA="-md $DMODEL --spec-type draft-dspark --spec-draft-n-max 3 -otd output_norm=CUDA0"; fi
say "gate 2: decode at the published split${DRAFT:+ with the DSpark draft}"
# -ot to the CPU drops mmap, and 283 GiB of pinned weights do not fit 251 GB of RAM (#2444)
CUDA_DEVICE_ORDER=PCI_BUS_ID GGML_CUDA_NO_PINNED_WEIGHTS=1 setsid nohup ./$BIN -m $M -c 16384 -ngl 99 -t 32 -b 2048 -ub 512 \
  -ot "$OT" ${EXTRA_FLAGS:-} $EXTRA --host 127.0.0.1 --port $PORT > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid; sleep 1
if ! kill -0 $SPID 2>/dev/null; then say "server exited immediately: $(head -1 $OUT/server.log)"; SPID=""; finish 1; fi
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "server pid $SPID"
# /health answers 200 while some servers are still loading, so readiness is a completion
# that actually came back with timings -- not a health code
ready=""
for i in $(seq 900); do
  kill -0 $SPID 2>/dev/null || { say "server exited during load"; tail -20 $OUT/server.log; SPID=""; finish 1; }
  if curl -s -m 10 "127.0.0.1:$PORT/completion" -d '{"prompt":"hi","n_predict":1,"temperature":0}' 2>/dev/null | grep -q '"timings"'; then ready=1; break; fi
  sleep 2
done
[ -n "$ready" ] || { say "server never answered a completion"; tail -10 $OUT/server.log; finish 1; }
say "ready; gpus loaded: $(gpus)"

ask(){ python3 -c 'import json,sys; print(json.dumps({"prompt":"<｜User｜>"+sys.argv[1]+"<｜Assistant｜></think>","n_predict":200,"temperature":0,"cache_prompt":False}))' "$1" > /tmp/ik-v41-req.json
  curl -s -m 900 "127.0.0.1:$PORT/completion" -d @/tmp/ik-v41-req.json > $OUT/resp-$2.json
  python3 -c '
import json,sys
r=json.load(open(sys.argv[1]))
if "timings" not in r: sys.exit("  %s: no timings in the response: %s" % (sys.argv[2], str(r)[:200]))
t=r["timings"]
d={k:v for k,v in t.items() if "draft" in k or "accept" in k}
print("  %s: prefill %d @ %.1f | decode %d @ %.2f tok/s %s" % (
    sys.argv[2], t["prompt_n"], t["prompt_per_second"], t["predicted_n"], t["predicted_per_second"], d or ""))' $OUT/resp-$2.json $2 || finish 1; }

i=0
for p in "Explain in detail how a write-ahead log lets a database survive a crash." \
         "Describe step by step what happens when a process touches a swapped-out page." \
         "Why is floating point addition not associative? Give a worked example."; do
  i=$((i+1)); ask "$p" "pass1-$i"
done
say "second pass (rows already in page cache)"
i=0
for p in "Explain in detail how a write-ahead log lets a database survive a crash." \
         "Describe step by step what happens when a process touches a swapped-out page."; do
  i=$((i+1)); ask "$p" "pass2-$i"
done
head -c 400 $OUT/resp-pass1-1.json > $OUT/sample.txt
finish 0
