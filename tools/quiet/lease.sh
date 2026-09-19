#!/usr/bin/env bash
# 이 박스에서 "바쁨"의 단일 소유자. 설계는 docs/quiet-machine.md 계층 1이고,
# 이 파일은 그 설계의 구현이다. 측정하는 모든 스크립트가 이것을 거친다 —
# 지시가 아니라 도구를 준다(계층 2). 재구현할 것이 없어야 한다.
#
#   lease.sh wait [--timeout S]  임대가 비고 박스가 조용해질 때까지 블록
#   lease.sh acquire "<reason>"  flock으로 잡고 "<pid> <reason> <start>"를 쓴다
#   lease.sh release             파일 안의 pid가 우리 것일 때만 지운다
#   lease.sh status              보유자, 나이, 조용함 신호를 찍는다
#   lease.sh witness             한 줄 JSON 증인 — 측정 행마다 시작·끝에 붙인다
#
# "조용함"은 load average가 아니다(2026-09-13 실측: 200 GB 모델 로드는 I/O
# 바운드라 loadavg가 늦게 올라 게이트가 열린 채 벤치 5건이 오염됐다). 네 가지
# 전부를 본다: 살아 있는 보유자 없음, /proc/pressure/io some avg10, 서빙 포트의
# 것을 뺀 llama-* 프로세스 없음, 그리고 마지막으로 1분 loadavg.
set -euo pipefail

LEASE=${QUIET_LEASE:-/home/user/box-lease}
IO_MAX=${QUIET_IO_MAX:-5.0}
LOAD_MAX=${QUIET_LOAD_MAX:-4.0}
SERVE_PORT=${QUIET_SERVE_PORT:-8000}

io_avg10()  { awk '/^some/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/){sub("avg10=","",$i); print $i; exit}}' /proc/pressure/io; }
load1()     { awk '{print $1}' /proc/loadavg; }
# 서빙 포트를 듣고 있는 pid는 "바쁨"이 아니다(문서: 공개 포트의 서빙 프로세스는 바쁨이 아니다).
serving_pid() { ss -lntp 2>/dev/null | awk -v p=":$SERVE_PORT" '$4 ~ p {print}' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }
other_llama() {
  local sp; sp=$(serving_pid || true)
  pgrep -a 'llama-' 2>/dev/null | while read -r pid rest; do
    [ -n "$sp" ] && [ "$pid" = "$sp" ] && continue
    echo "$pid $rest"
  done
}
holder_pid() { [ -f "$LEASE" ] && awk '{print $1}' "$LEASE" || true; }
holder_alive() { local p; p=$(holder_pid); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

quiet_reason() {   # 조용하면 빈 문자열, 아니면 왜 아닌지
  holder_alive && { echo "lease held by $(cat "$LEASE")"; return; }
  local io; io=$(io_avg10)
  awk -v a="$io" -v m="$IO_MAX" 'BEGIN{exit !(a>m)}' && { echo "io pressure some avg10=$io > $IO_MAX"; return; }
  local others; others=$(other_llama)
  [ -n "$others" ] && { echo "llama processes running: $(echo "$others" | tr '\n' ';')"; return; }
  local l; l=$(load1)
  awk -v a="$l" -v m="$LOAD_MAX" 'BEGIN{exit !(a>m)}' && { echo "load1=$l > $LOAD_MAX"; return; }
  echo ""
}

witness() {
  printf '{"t":"%s","io_avg10":%s,"load1":%s,"lease":"%s","other_llama":%d,"page_cache_kb":%s}\n' \
    "$(date -Is)" "$(io_avg10)" "$(load1)" \
    "$( [ -f "$LEASE" ] && tr '\n' ' ' < "$LEASE" || echo none )" \
    "$(other_llama | grep -c . || true)" \
    "$(awk '/^Cached:/{print $2}' /proc/meminfo)"
}

case "${1:-status}" in
  wait)
    timeout=0
    [ "${2:-}" = "--timeout" ] && timeout=${3:-0}
    start=$(date +%s)
    while :; do
      why=$(quiet_reason)
      [ -z "$why" ] && { echo "quiet"; exit 0; }
      now=$(date +%s)
      if [ "$timeout" -gt 0 ] && [ $((now-start)) -ge "$timeout" ]; then
        echo "still not quiet after ${timeout}s: $why" >&2; exit 124
      fi
      echo "waiting: $why" >&2
      sleep 10
    done ;;
  acquire)
    reason=${2:?acquire needs a reason}
    # flock으로 경쟁을 닫는다. 죽은 보유자의 파일은 여기서만 치운다.
    exec 9>"$LEASE.lock"
    flock -w 5 9 || { echo "another acquire is in flight" >&2; exit 75; }
    if holder_alive; then echo "lease held: $(cat "$LEASE")" >&2; exit 75; fi
    [ -f "$LEASE" ] && echo "clearing stale lease: $(cat "$LEASE")" >&2
    # 임대에 적는 pid는 이 스크립트가 아니라 **부르는 쪽**이다. 자기 $$를 적으면
    # acquire가 반환하는 순간 보유자가 죽은 것이 되고, 다음 quiet_reason이 임대를
    # 비어 있다고 읽는다(2026-09-19 자기검사에서 잡았다: acquire 직후 status가
    # 곧바로 [HOLDER DEAD] + quiet: yes였다). 측정 스크립트가 살아 있는 동안만
    # 임대가 유효해야 하므로 기본값은 $PPID이고, setsid 사슬처럼 부모가 바뀌는
    # 경우를 위해 QUIET_LEASE_PID로 덮어쓴다.
    printf '%d %s %s\n' "${QUIET_LEASE_PID:-$PPID}" "$reason" "$(date -Is)" > "$LEASE"
    echo "acquired: $(cat "$LEASE")" ;;
  release)
    p=$(holder_pid)
    if [ -z "$p" ]; then echo "no lease to release"; exit 0; fi
    # 우리 것만 지운다. 부모 셸이 호출하므로 $PPID도 우리 것으로 친다.
    if [ "$p" = "${QUIET_LEASE_PID:-$PPID}" ] || [ "$p" = "$$" ] || ! kill -0 "$p" 2>/dev/null; then
      rm -f "$LEASE"; echo "released"
    else
      echo "lease belongs to pid $p, not us ($$/$PPID) — not removing" >&2; exit 1
    fi ;;
  status)
    if [ -f "$LEASE" ]; then
      echo "lease: $(cat "$LEASE")$(holder_alive || echo '   [HOLDER DEAD]')"
    else echo "lease: free"; fi
    why=$(quiet_reason)
    [ -z "$why" ] && echo "quiet: yes" || echo "quiet: no — $why"
    witness ;;
  witness) witness ;;
  *) echo "usage: lease.sh wait|acquire <reason>|release|status|witness" >&2; exit 64 ;;
esac
