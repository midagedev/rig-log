#!/bin/bash
# img-run-inner.sh — its own file for the same two reasons ltx-run-inner.sh is: `$!` in the
# caller must be a session leader so every process holding VRAM can be found by session id,
# and diffusers logs without timestamps, so each line is stamped on the way out.
set -u -o pipefail
export PYTHONUNBUFFERED=1
cd /home/user/imggen || exit 1
/usr/bin/time -v /usr/local/bin/uv run python /home/user/img-gen.py "$@" 2>&1 \
  | awk '{ printf "%s %s\n", strftime("%H:%M:%S"), $0; fflush() }'
exit ${PIPESTATUS[0]}
