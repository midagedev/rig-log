#!/usr/bin/env bash
# Start the lease's generation detached from the calling ssh, so a dropped connection cannot end it mid-run.
# Run from the bloomery tree on the box (through tools/box.sh, which has already waited out the lease and the holds):
#   bash /root/musicgen/lease-run.sh <run name> [gen.py flags…]
# lease-hold.sh takes the lease with docs/cards/musicgen-034.card and runs run.sh under it. The detached pid goes to
# out/<run>-lease.pid, lease-hold's exit code to out/<run>-lease.rc, its output to out/<run>-lease.log.
set -uo pipefail
RUN=${1:?run name}; shift
O=/root/musicgen/out; mkdir -p "$O"; rm -f "$O/$RUN-lease.rc"
setsid nohup bash -c 'bash tools/ref/lease-hold.sh --card docs/cards/musicgen-034.card -- bash /root/musicgen/run.sh "$@"
echo $? > "/root/musicgen/out/$1-lease.rc"' _ "$RUN" "$@" > "$O/$RUN-lease.log" 2>&1 < /dev/null &
echo $! > "$O/$RUN-lease.pid"
echo "lease-run: pid $(cat "$O/$RUN-lease.pid"), log $O/$RUN-lease.log"
