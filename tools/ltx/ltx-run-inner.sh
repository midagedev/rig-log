#!/bin/bash
# ltx-run-inner.sh <pipeline> <args...> — the generation itself, stamped.
# Its own script because ltx_pipelines logs at INFO with no asctime, so stage
# boundaries only become measurable if each line is stamped as it is written.
# Also its own script so ltx-take.sh's $! is this session leader and not the
# subshell of a pipeline (the pid it signals has to be the one it spawned).
set -u -o pipefail
export PYTHONUNBUFFERED=1
cd /home/user/LTX-2 || exit 1
P=$1; shift
/usr/bin/time -v /usr/local/bin/uv run python -m "ltx_pipelines.$P" "$@" 2>&1 \
  | awk '{ printf "%s %s\n", strftime("%H:%M:%S"), $0; fflush() }'
exit ${PIPESTATUS[0]}
