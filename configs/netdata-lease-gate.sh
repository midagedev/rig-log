#!/bin/bash
# 측정 임대가 잡혀 있는 동안 netdata 유닛 전체를 얼리고(cgroup freezer), 풀리면 녹인다.
#
# netdata의 python.d nvidia_smi 수집기는 `nvidia-smi -x -q -l 2`로 두 카드를 2초마다 통째로 조회하고,
# apps.plugin은 매초 /proc를 훑는다. 조용한 기계 규약 밖에서 도는 상주 부하다. netdata가 임대를 직접
# 보게 하는 길은 막혀 있다 — netdata 사용자는 /root의 락을 열 수 없고, 루프 모드 nvidia-smi는 락을
# 잡으면 놓지 않는다. 그래서 root가 임대를 보고 유닛을 얼린다. 얼린 동안 대시보드도 멈춘다.
#
# 임대는 둘이다.
#   bloomery  /root/bloomery-cpu.lock — 러너가 fd 9에 배타 flock을 쥔다(bloomery tools/ref/lease.sh).
#             공유 락 시도가 즉시 실패하면 잡힌 것이다. 시도는 마이크로초라 러너의 대기에 안 보인다.
#   rig-log   /home/user/box-lease — "<pid> <reason> <start>"를 적은 파일이고, 그 pid가 살아 있으면
#             잡힌 것이다(tools/quiet/lease.sh).
# 폴링 자체가 소음이 되지 않게, 잡힌 동안은 2초, 빈 동안은 0.5초 간격으로 본다. systemctl은 전이 때와
# 30초마다 한 번만 부른다 — netdata가 재시작되면 녹은 채로 올라오므로 그 30초가 실제 상태를 맞춘다.
set -u
UNIT=netdata.service
BLOOMERY_LOCK=${GATE_BLOOMERY_LOCK:-/root/bloomery-cpu.lock}
RIGLOG_LEASE=${GATE_RIGLOG_LEASE:-/home/user/box-lease}
LOG=/var/log/netdata-lease-gate.log
say() { echo "$(date -Is) $*" >> "$LOG"; }

# 잡혀 있으면 보유자를 who에 적고 0, 아니면 1. 서브셸 없이 부른다(폴링마다 fork 하나를 줄인다).
held() {
  who=
  if [ -e "$BLOOMERY_LOCK" ] && ! flock -s -n "$BLOOMERY_LOCK" true; then
    who=bloomery
    return 0
  fi
  local pid=
  [ -f "$RIGLOG_LEASE" ] && read -r pid _ < "$RIGLOG_LEASE"
  if [ -n "$pid" ] && kill -0 "$pid" 2> /dev/null; then
    who="rig-log pid $pid"
    return 0
  fi
  return 1
}

say "started (bloomery $BLOOMERY_LOCK, rig-log $RIGLOG_LEASE)"
last=
ticks=0 # systemctl에 마지막으로 물은 뒤 지난 반초 수
while :; do
  if held; then want=frozen; else want=running; fi
  if [ "$want" != "$last" ] || [ "$ticks" -ge 60 ]; then
    cur=$(systemctl show -p FreezerState --value "$UNIT" 2> /dev/null)
    if [ "$want" = frozen ] && [ "$cur" = running ] && systemctl is-active --quiet "$UNIT"; then
      systemctl freeze "$UNIT" && say "froze: $who holds a lease"
    elif [ "$want" = running ] && [ "$cur" = frozen ]; then
      systemctl thaw "$UNIT" && say "thawed"
    fi
    last=$want
    ticks=0
  fi
  if [ "$want" = frozen ]; then
    sleep 2
    ticks=$((ticks + 4))
  else
    sleep 0.5
    ticks=$((ticks + 1))
  fi
done
