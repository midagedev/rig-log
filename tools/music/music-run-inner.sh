#!/bin/bash
# its own file so $! in the caller is a session leader, and so each line is stamped
set -u -o pipefail
export PYTHONUNBUFFERED=1
cd /home/user/yue2 || exit 1
/usr/bin/time -v /usr/local/bin/uv run python /home/user/yue2-gen.py "$@" 2>&1 \
  | awk '{ printf "%s %s\n", strftime("%H:%M:%S"), $0; fflush() }'
exit ${PIPESTATUS[0]}
