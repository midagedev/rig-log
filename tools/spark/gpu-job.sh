#!/bin/bash
# A GPU job with no server (a kernel micro-benchmark, a profile of one binary) under the same quiet rules as take.sh:
# the lease, the model fetches paused (SIGSTOP) for the job and resumed on every exit path, a witness line before and
# after (load, io pressure, GPU apps, MemAvailable). Output goes to /root/takes/<tag>/job.log.
# usage: gpu-job.sh <tag> <command...>
set -u
TAG=${1:?tag}; shift; H=/root/health; OUT=/root/takes/$TAG; mkdir -p "$OUT"
export QUIET_LEASE=/root/spark-lease
FETCH_UNITS=${FETCH_UNITS:-"spark-fetch spark-fetch2 spark-fetch3 spark-fetch4"}; PAUSED=""
wit(){ printf '{"edge":"%s","t":"%s","load1":%s,"io_avg10":%s,"gpu_apps":%s,"memavail_kb":%s}\n' "$1" "$(date +%FT%T%z)" \
  "$(cut -d' ' -f1 /proc/loadavg)" "$(awk '/^some/{sub("avg10=","",$2);print $2}' /proc/pressure/io)" \
  "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -c .)" "$(awk '/MemAvailable/{print $2}' /proc/meminfo)" >> "$OUT/witness.jsonl"; }
done_(){ for u in $PAUSED; do systemctl kill -s SIGCONT $u; done; "$H/lease.sh" release >/dev/null 2>&1; }
QUIET_LEASE_PID=$$ "$H/lease.sh" acquire "gpu-job $TAG" || { echo GPU_JOB_FAILED lease; exit 1; }
trap done_ EXIT
for u in $FETCH_UNITS; do systemctl is-active -q $u && { systemctl kill -s SIGSTOP $u; PAUSED="$PAUSED $u"; }; done
sleep 5; wit start
"$@" > "$OUT/job.log" 2>&1; rc=$?
wit end; echo "GPU_JOB_DONE rc=$rc"; exit $rc
