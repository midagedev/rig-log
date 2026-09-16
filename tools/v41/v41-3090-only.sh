#!/bin/bash
# Can DeepSeek-V4.1 serve from the 3090 alone, every expert layer on the host?
#
set -u
TS=${1:?a unique tag; never reuse a path a previous launch used -- bash reads a script incrementally}
OUT=/home/user/v41-3090/$TS; LEASE=/home/user/gpu-lease; QUEUE=/home/user/gpu-queue; PORT=8021
B=/home/user/llama.cpp-v41-merged/build/bin/llama-server
M=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
D=/models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.tl37.gguf
OT0='exps=CPU'
LEASE_TAG="v41-3090-$TS"
mkdir -p $OUT
say(){ echo "$(date +%T) $*"; }
. /home/user/gpu-order.env
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
vram(){ nvidia-smi --query-gpu=uuid,name,memory.used --format=csv,noheader | sed 's/^/    /'; }
witness(){ echo "    witness: io $(awk '/some/{print $2}' /proc/pressure/io) | load $(cut -d' ' -f1 /proc/loadavg) | cache $(free -g | awk '/Mem:/{print $6}') GiB | gpus $(gpus)"; }

cleanup(){ rc=${1:-1}
  [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  [ -f $QUEUE ] && grep -q "^$LEASE_TAG " $QUEUE && rm -f $QUEUE && say "queue marker cleared"
  [ $rc -eq 0 ] && echo V41_3090_DONE || echo V41_3090_FAILED
  exit $rc; }

# --- gates ---
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo V41_3090_FAILED; exit 1; }
[ "$(systemctl is-active llm.service)" = "inactive" ] || { say "refused: llm.service active, it holds both GPUs"; echo V41_3090_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo V41_3090_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo V41_3090_FAILED; exit 1; }
[ -f $QUEUE ] && { say "refused: queue marker up: $(cat $QUEUE)"; echo V41_3090_FAILED; exit 1; }
[ -x "$B" ] && [ -f "$M" ] && [ -f "$D" ] || { say "refused: missing binary or model"; echo V41_3090_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date -Is)" > $QUEUE
echo "$LEASE_TAG $$ $(date -Is)" > $LEASE
trap 'say "INTERRUPTED"; cleanup 1' INT TERM

# --- one arm ---
SPID=""
stop_arm(){
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    say "  stopping server pid $SPID (session leader) SIGTERM"; kill -TERM $SPID
    for i in $(seq 180); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
    kill -0 $SPID 2>/dev/null && { say "  server $SPID alive after 180 s; NOT escalating"; return 1; }
  fi
  if [ -n "$SPID" ]; then
    members(){ ps -eo pid=,sid= | awk -v s=$SPID '$2==s && $1!=s{printf "%s ", $1}'; }
    for i in $(seq 20); do [ -z "$(members)" ] && break; sleep 1; done
    [ -n "$(members)" ] && { say "  session members left: $(members) -> SIGTERM"; kill -TERM $(members) 2>/dev/null; sleep 10; }
  fi
  for i in $(seq 60); do [ "$(maxgpu)" -lt 2000 ] && break; sleep 2; done
  SPID=""
  [ "$(maxgpu)" -lt 2000 ] || { say "  GPUS NOT RELEASED after arm: $(gpus)"; return 1; }
  return 0; }

ask(){ python3 -c 'import json,sys; print(json.dumps({"prompt":"<｜User｜>"+sys.argv[1]+"<｜Assistant｜></think>","n_predict":200,"temperature":0,"cache_prompt":False}))' "$1" > $OUT/req.json
  curl -s -m 900 "127.0.0.1:$PORT/completion" -d @$OUT/req.json > $OUT/$2.json
  python3 -c '
import json,sys
r=json.load(open(sys.argv[1]))
if "timings" not in r: print("    %s: NO TIMINGS %s"%(sys.argv[2],str(r)[:160])); sys.exit(0)
t=r["timings"]; d={k:v for k,v in t.items() if "draft" in k or "accept" in k}
print("    %-12s prefill %3d @ %6.1f | decode %3d @ %6.2f tok/s  %s"%(
  sys.argv[2], t["prompt_n"], t["prompt_per_second"], t["predicted_n"], t["predicted_per_second"], d or ""))' $OUT/$2.json $2; }

arm(){ NAME=$1; DEVS=$2; OT=$3; CTX=$4
  say "ARM $NAME  (devices=$DEVS)"
  say "  OT=$OT"
  witness
  t0=$(date +%s)
  CUDA_VISIBLE_DEVICES=$DEVS GGML_CUDA_NO_PINNED_WEIGHTS=1 setsid nohup "$B" \
    -m "$M" --alias v41 -c $CTX -ngl 99 -t 32 -b 2048 -ub 512 --lazy-mode auto \
    -ot "$OT" -md "$D" --spec-type draft-dspark --spec-draft-n-max 3 -otd "output_norm=CUDA0" \
    --jinja --host 127.0.0.1 --port $PORT > $OUT/$NAME-server.log 2>&1 < /dev/null &
  SPID=$!; echo $SPID > $OUT/$NAME-server.pid; sleep 2
  kill -0 $SPID 2>/dev/null || { say "  server exited immediately:"; grep -i -m4 "error\|fail\|alloc" $OUT/$NAME-server.log | cut -c1-200; SPID=""; return 1; }
  [ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "  launch assertion failed: pid $SPID is not a session leader"; return 1; }
  ready=""
  for i in $(seq 900); do
    kill -0 $SPID 2>/dev/null || { say "  server exited during load:"; grep -i -m8 "error\|failed\|alloc\|out of memory" $OUT/$NAME-server.log | cut -c1-220; SPID=""; return 1; }
    curl -s -m 10 "127.0.0.1:$PORT/completion" -d '{"prompt":"hi","n_predict":1,"temperature":0}' 2>/dev/null | grep -q '"timings"' && { ready=1; break; }
    sleep 2
  done
  [ -n "$ready" ] || { say "  never answered a completion"; tail -8 $OUT/$NAME-server.log; return 1; }
  say "  ready in $(( $(date +%s) - t0 )) s"
  vram | tee $OUT/$NAME-vram.txt
  grep -E "model buffer size|KV self size|compute buffer|CPU_Mapped|offloaded" $OUT/$NAME-server.log | cut -c1-140 | sed 's/^/    /' | tee $OUT/$NAME-placement.txt
  # wait for IO pressure to settle so the take is not measuring the tail of the load
  for i in $(seq 90); do p=$(awk '/some/{print $2}' /proc/pressure/io | cut -d= -f2); awk -v p="$p" 'BEGIN{exit !(p<3)}' && break; sleep 2; done
  witness
  n=0
  for p in "Explain in detail how a write-ahead log lets a database survive a crash." \
           "Describe step by step what happens when a process touches a swapped-out page." \
           "Why is floating point addition not associative? Give a worked example."; do
    n=$((n+1)); ask "$p" "$NAME-pass1-$n"
  done
  say "  second pass (same prompts, rows now in page cache)"
  n=0
  for p in "Explain in detail how a write-ahead log lets a database survive a crash." \
           "Describe step by step what happens when a process touches a swapped-out page."; do
    n=$((n+1)); ask "$p" "$NAME-pass2-$n"
  done
  witness
  stop_arm || return 1
  say "  arm $NAME done; gpus $(gpus)"
  return 0; }

say "=== V4.1 on the 3090 alone: attention, HC, KV and the draft on the 24 GB card, all 40 expert layers on the host ==="
say "reference 2026-09-16 (v41-one-card, A6000 alone, 4.5 expert layers on card): 16.05/22.41/20.05 cold, 21.59/25.93 warm"
say "A6000=$A6000_UUID  3090=$GF3090_UUID"
RC=0
arm 3090-16k "$GF3090_UUID" "$OT0" 16384 || RC=1
arm 3090-64k "$GF3090_UUID" "$OT0" 65536 || RC=1
say "=== all arms attempted, rc $RC ==="
cleanup $RC
