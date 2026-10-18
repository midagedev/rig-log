#!/usr/bin/env bash
# drive.sh check|full N: render.py <mode> in N frame-range chunks under nice 19, CPU only, in /root/clip034-render/v3
# (the venv and chromium are the parent dir's). Starts when neither the timing lease nor a hold is up (lease_free, a
# shared probe); while one comes up mid-run, every chunk's python is stopped (SIGSTOP; its chromium sits idle) and
# continued when it is gone. Each chunk's pid is its own $! (nohup and nice exec the program), written to
# pids/<mode>-<i>.pid; its exit status comes from wait. rc 0 when every chunk is 0.
R=/root/clip034-render/v3; cd "$R" || exit 1
. ../lease-probe.sh
export PLAYWRIGHT_BROWSERS_PATH=$R/../ms-playwright FILM_URL=http://127.0.0.1:8797/film.html FILM=release-034-v3 \
       CHROME_ARGS=--disable-gpu NO_ENCODE=1
PY=$R/../.venv/bin/python
mode=$1; n=${2:-16}
quiet() { lease_free && [ -z "$(lease_holds_up)" ]; }
until quiet; do echo "[wait] $(date -u +%T) the lease or a hold is up"; sleep 30; done
frames=$($PY -c 'import json; print(round(json.load(open("data.json"))["timeline"]["T"] * 60))')
total=$frames; [ "$mode" = check ] && total=$((frames + 1))
mkdir -p pids logs
rm -f pids/"$mode"-*.pid logs/"$mode"-*.log
[ "$mode" = full ] && rm -rf sub
start=$(date +%s); pids=()
for ((i = 0; i < n; i++)); do
  f0=$((i * total / n)); f1=$(((i + 1) * total / n))
  F0=$f0 F1=$f1 nohup nice -n 19 $PY render.py "$mode" > "logs/$mode-$i.log" 2>&1 &
  echo $! > "pids/$mode-$i.pid"; pids+=($!)
done
echo "[start] $(date -u +%T) $mode: $n chunks over $total frames, pids ${pids[*]}"
stopped=
while :; do
  live=0; for p in "${pids[@]}"; do kill -0 "$p" 2> /dev/null && live=$((live + 1)); done
  [ "$live" -eq 0 ] && break
  if ! quiet; then
    [ -n "$stopped" ] || { for p in "${pids[@]}"; do kill -STOP "$p" 2> /dev/null; done; stopped=1; echo "[stop] $(date -u +%T) the lease or a hold came up"; }
  elif [ -n "$stopped" ]; then
    for p in "${pids[@]}"; do kill -CONT "$p" 2> /dev/null; done; stopped=; echo "[cont] $(date -u +%T)"
  fi
  sleep 5
done
rc=0; for ((i = 0; i < n; i++)); do wait "${pids[$i]}"; r=$?; [ "$r" -ne 0 ] && { rc=1; echo "[chunk $i] rc $r"; }; done
echo "[done] $(date -u +%T) $mode rc $rc in $(( $(date +%s) - start )) s"
exit $rc
