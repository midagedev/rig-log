#!/bin/bash
# The 11-03/04 night queue, behind queue-q36.sh (start it with q-after.sh). HOME is set here: a systemd unit has none,
# and bloomery's scale store for a checkpoint folder's compressed block scales lives under it (11-03 23:39, the
# ids probes refused at load without it). Jobs, one after another; a failed one is logged and the next runs:
#   the README-method and nsys probes (FP4-Local ids; Qwen3.6 MTP GGUF prefill, decode and ids),
#   Flare on its exported package, the julian GB10 tape set beside ours (lmstudio Q4_K_M, toktape's own run),
#   the Q8_0 gemv micro-benchmark, Strata's IQ3_S setup and rows, and bloomery and llama.cpp on the same IQ3_S file.
# Sentinel QUEUE_NIGHT_DONE.
set -u; export HOME=/root; cd /root/health
B=$(ls -d /opt/engines/bloomery-v0.3.12/*/bin)/bloomery-serve; L=/opt/engines/llama.cpp-b12069/build/bin/llama-server
LMS=/models/Qwen3.6-35B-A3B-LMS-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf; IQ=/models/Qwen3.8-Flash-Next-GSQ-RCO-GGUF
job(){ echo "$(date -u +%TZ) start $*"; "$@"; echo "$(date -u +%TZ) end rc=$? $1"; }
job ./probes-lag.sh ids nsys-prefill-q36mtp nsys-decode-q36mtp ids-q36mtp
pkg=$(ls -d /root/.cache/flare/packages/models/nvidia_2FQwen3.8-Flash-Next-FP4-Local/gb10-tp1-* 2>/dev/null | tail -1)
[ -n "$pkg" ] && job ./rows-flare.sh q38-fp4-local "$pkg" flare-default flare-nomtp
if [ -f /models/Qwen3.6-35B-A3B-LMS-GGUF/.fetch-verified ]; then
  PROBE=/root/health/tape-probe.sh PORT=18731 ENGINE="bloomery 0.3.12" SERVE="$B -m $LMS --host 127.0.0.1 --port 18731" \
    job ./take.sh probe-tape-q36lms-q4km-bloomery-default
  PROBE=/root/health/tape-probe.sh PORT=18732 ENGINE="llama.cpp b12069" SERVE="$L -m $LMS --host 127.0.0.1 --port 18732" \
    job ./take.sh probe-tape-q36lms-q4km-llamacpp-default
  job ./rows-gguf.sh q36lms-q4km $LMS bloomery-default llamacpp-default
fi
job ./gpu-job.sh bench-q8gemv /root/health/bench/q8gemv-bench 300
job ./gpu-job.sh strata-setup-iq3s ./strata-setup.sh iq3s
run=$(ls /opt/engines/strata-src-v0.2.10/run-iq3_s.sh 2>/dev/null)
[ -n "$run" ] && job ./rows-strata.sh q38-iq3s "$run" strata-default strata-nomtp
job ./rows-gguf.sh q38-iq3s $IQ/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf bloomery-default bloomery-nomtp llamacpp-c16k
DRAFT=/models/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  job ./rows-gguf.sh q38-iq3s-shared $IQ/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf bloomery-rec
echo "QUEUE_NIGHT_DONE"
