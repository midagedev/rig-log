#!/bin/bash
# dma-stop.sh — stop everything this run started, from the pids it wrote at spawn.
# Never pattern-matches: /proc/*/cmdline scanning froze this machine's own ssh session
# once, because the pattern matched the shell holding it.
set -u
OUT=${1:?outdir}
for f in "$OUT"/*.pid; do
  [ -e "$f" ] || continue
  p=$(cat "$f"); n=$(basename "$f" .pid)
  if [ -d "/proc/$p" ]; then
    echo "stopping $n pid $p ($(cat /proc/$p/comm 2>/dev/null))"
    kill -TERM "$p" 2>/dev/null
  else
    echo "$n pid $p already gone"
  fi
done
sleep 3
for f in "$OUT"/*.pid; do
  [ -e "$f" ] || continue
  p=$(cat "$f"); n=$(basename "$f" .pid)
  [ -d "/proc/$p" ] && { echo "$n pid $p still up, SIGKILL"; kill -KILL "$p" 2>/dev/null; }
done
echo "stopped"
