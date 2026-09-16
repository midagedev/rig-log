#!/bin/bash
# echo-run-inner.sh — a session leader for the take runner, timestamps on every line, and
# /usr/bin/time -v so the host RSS is recorded: under the consumer profile the whole 46 GB
# DiT lives in pinned host memory, and that number belongs in the log next to the VRAM peak.
set -u -o pipefail
export PYTHONUNBUFFERED=1
cd /home/user/echo/echo_longvideo || exit 1
source .venv/bin/activate
/usr/bin/time -v python inference.py "$@" 2>&1 \
  | awk '{ printf "%s %s\n", strftime("%H:%M:%S"), $0; fflush() }'
exit ${PIPESTATUS[0]}
