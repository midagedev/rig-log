#!/bin/bash
# 무인 운전용 열/펌프 감시. 위험하면 추론 부하만 끄고 시스템은 살려둔다.
LOG=/var/log/thermal-guard.log
CRIT_CPU=93      # Tjmax 95 (5975WX). 90~93 은 하드웨어 자체 스로틀링에 맡긴다
WARN_CPU=88
CRIT_GPU=90      # A6000/3090 슬로우다운 시작점 위
CRIT_LIQ=59      # raised from 52 on 2026-09-14 (user): at 2.7 GHz a six-minute decode window reached 52 twice in one afternoon; pump spec is far above
MIN_PUMP=500     # 펌프 rpm 하한 (정상 ~2900)
STRIKES=6        # 5초 간격 => 30초 연속 위반에만 개입
s=0
say(){ echo "$(date -Is) $*" >> $LOG; }
stop_load(){
  say "STOP: $*"
  systemctl stop llm.service 2>/dev/null
  pkill -x llama-server; sleep 3; pkill -9 -x llama-server 2>/dev/null
  for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do kill -9 $p 2>/dev/null; done
  say "STOP done"
}
say "thermal-guard started (crit cpu=$CRIT_CPU gpu=$CRIT_GPU liq=$CRIT_LIQ pump>=$MIN_PUMP)"
while :; do
  cpu=0
  for h in /sys/class/hwmon/hwmon*; do
    [ "$(cat $h/name 2>/dev/null)" = k10temp ] && cpu=$(( $(cat $h/temp1_input 2>/dev/null || echo 0) / 1000 ))
  done
  gpu=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | sort -rn | head -1)
  gpu=${gpu:-0}
  why=""
  [ "$cpu" -ge "$CRIT_CPU" ] && why="CPU ${cpu}C"
  [ "$gpu" -ge "$CRIT_GPU" ] && why="$why GPU ${gpu}C"
  if st=$(liquidctl status 2>/dev/null); then
    liq=$(echo "$st" | awk '/Liquid temperature/{print int($4)}')
    rpm=$(echo "$st" | awk '/Pump speed/{print $4}')
    [ -n "$liq" ] && [ "$liq" -ge "$CRIT_LIQ" ] && why="$why LIQ ${liq}C"
    [ -n "$rpm" ] && [ "$rpm" -lt "$MIN_PUMP" ] && why="$why PUMP ${rpm}rpm"
  fi
  if [ -n "$why" ]; then
    s=$((s+1)); say "strike $s/$STRIKES:$why"
    [ "$s" -ge "$STRIKES" ] && { stop_load "$why"; s=0; sleep 300; }
  else
    [ "$s" -gt 0 ] && say "recovered (cpu=${cpu} gpu=${gpu})"
    s=0
    [ "$cpu" -ge "$WARN_CPU" ] && say "warn cpu=${cpu}C gpu=${gpu}C"
  fi
  sleep 5
done
