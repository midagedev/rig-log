#!/bin/bash
# qwen21-first-sitting.sh — Qwen-Image-2.1 bf16's first measured sitting on the A6000,
# through signalbox: a session job holds the lane, /comfy/batch does the generations, and
# the witnesses are the same dmon columns every take writes. Two resolutions (1K, native 2K),
# cold then warm each, seed 42/43, steps 25 cfg 1.0 euler/simple — the official template's
# own starting point. Sentinel QWEN21_SITTING_DONE / QWEN21_SITTING_FAILED.
set -u
TAG=qwen21-t1
RUN=/home/user/comfy-runs/$TAG
API=http://127.0.0.1:8030
WF=/home/user/signalbox/qwen21-t2i.json
say(){ echo "$(date +%T) $*"; }
mkdir -p "$RUN"
. /home/user/gpu-order.env
maxgpu(){ nvidia-smi -i $A6000_UUID --query-gpu=memory.used --format=csv,noheader,nounits; }

say "gates: lease $([ -f /home/user/gpu-lease ] && echo held || echo free), a6000 $(maxgpu) MiB, $(date +%H%M) KST"
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo QWEN21_SITTING_FAILED; exit 1; }
[ -f /home/user/gpu-lease ] && { say "refused: lease held"; echo QWEN21_SITTING_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: card busy"; echo QWEN21_SITTING_FAILED; exit 1; }

# witness: the take runners' 1 Hz dmon, the session's own run.log aside
nvidia-smi -i $A6000_UUID --query-gpu=timestamp,uuid,power.draw,clocks.sm,temperature.gpu,memory.used,utilization.gpu,clocks_throttle_reasons.active,clocks.mem,fan.speed \
  --format=csv,noheader,nounits -l 1 > $RUN/dmon.csv 2>&1 &
DMPID=$!

# the session window, through the dispatcher like any other job
curl -sf -X POST $API/comfy/session -H "Content-Type: application/json" \
  -d "{\"tag\":\"$TAG\",\"minutes\":30,\"owner\":\"qwen21\",\"title\":\"Qwen-Image-2.1 bf16 첫 시팅\"}" >/dev/null \
  || { kill $DMPID 2>/dev/null; say "refused: dispatcher would not take the session"; echo QWEN21_SITTING_FAILED; exit 1; }
for _ in $(seq 120); do curl -sf -o /dev/null http://127.0.0.1:8188/ && break; sleep 1; done
curl -sf -o /dev/null http://127.0.0.1:8188/ || { kill $DMPID 2>/dev/null; curl -s -X POST $API/jobs/$TAG/cancel >/dev/null; say "ComfyUI never answered"; echo QWEN21_SITTING_FAILED; exit 1; }
say "session up (lease: $(cat /home/user/gpu-lease 2>/dev/null))"

gen(){ # gen <w> <h> <seed> <label>
  local w=$1 h=$2 seed=$3 label=$4 t0 rc
  python3 - "$WF" "$w" "$h" "$seed" "/tmp/qw.$$.json" <<'PY'
import json, sys
wf = json.load(open(sys.argv[1]))
wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"] = int(sys.argv[2]), int(sys.argv[3])
wf["6"]["inputs"]["seed"] = int(sys.argv[4])
json.dump(wf, open(sys.argv[5], "w"))
PY
  t0=$(date +%s)
  curl -sf -X POST $API/comfy/batch -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'prompt': json.load(open(sys.argv[1])), 'timeout': 1500}))" /tmp/qw.$$.json)" \
    > $RUN/$label.json
  rc=$?
  rm -f /tmp/qw.$$.json
  # the dispatcher reports refusals as HTTP 200 with an rc in the body: read it or a
  # "successful" sitting can be four refusals
  [ $rc -eq 0 ] && python3 -c "
import json, sys
d = json.load(open('$RUN/$label.json'))
sys.exit(1 if d.get('rc') not in (None, 0) else 0)" || rc=$?
  if [ $rc -ne 0 ]; then say "$label: batch failed rc=$rc"; return 1; fi
  say "$label: $(( $(date +%s) - t0 )) s wall — $(python3 -c "
import json
d = json.load(open('$RUN/$label.json'))
outs = d.get('outputs') or []
print('%d output(s): %s' % (len(outs), ', '.join('%s/%s' % (o['kind'], o['name']) for o in outs[:3])))")"
}

gen 1024 1024 42 1k-cold  && gen 1024 1024 43 1k-warm \
  && gen 2048 2048 42 2k-cold && gen 2048 2048 43 2k-warm
grc=$?

# lawful close: cancel the session job, wait for the lease and the card
curl -s -X POST $API/jobs/$TAG/cancel >/dev/null
for _ in $(seq 120); do [ ! -f /home/user/gpu-lease ] && [ "$(maxgpu)" -lt 2000 ] && break; sleep 2; done
kill $DMPID 2>/dev/null
say "lease: $( [ -f /home/user/gpu-lease ] && echo STILL-HELD || echo released), a6000 after: $(maxgpu) MiB"
say "peak VRAM: $(awk -F, '{gsub(/ /,"",$6); if($6+0>m)m=$6+0} END{printf "%d MiB", m}' $RUN/dmon.csv)"
say "A6000: $(awk -F, '{gsub(/ /,"",$3); gsub(/ /,"",$5); if($3+0>p)p=$3+0; if($5+0>t)t=$5+0} END{printf "peak %s W, max %s C", p, t}' $RUN/dmon.csv)"
say "throttle reasons: $(awk -F, '{print $8}' $RUN/dmon.csv | sort -u | tr '\n' '|')"
[ $grc -eq 0 ] && echo QWEN21_SITTING_DONE || echo QWEN21_SITTING_FAILED
exit $grc
