#!/bin/bash
# 두 번째 맥의 디스크를 정리하는 스테이션의 가지치기. station 이 ssh 로 이 스크립트를 보낸다.
#   prune-remote.sh <age-hours> [keep-track...]
#
#   age-hours   target/ 이 이 시간(시간) 동안 건드려지지 않았으면 지운다
#   keep-track  지우지 않을 트랙 이름(스테이션 자신 것: station-f, station-s, station-b)
#
# 각 트랙은 ~/repo/bloomery-mr/<track>/ 에 있고, 그 target/ 이 8–14 GiB 다. 하나도
# 지워지지 않던 것이 2026-10-21 에 디스크를 100 % 로 채웠다(정적 단계가 ENOSPC 로
# 18 개 빨강처럼 보였다). 지우는 조건: 그 target/ 안의 아무것도 age 시간 안에
# 건드려지지 않았고, 그 트랙의 락(.lock-<track>)이 없는 것. 스테이션의 클론은 절대
# 지우지 않는다. 한 줄로 보고한다.
set -u

AGE=$1
shift 2>/dev/null || true
BASE="$HOME/repo/bloomery-mr"

# 기준 시각: age 시간 전. macOS 의 date -v 로 만든다(두 번째 맥과 이 맥 모두 macOS).
STAMP=$(date -v-"${AGE}"H '+%Y%m%d%H%M.%S' 2>/dev/null)
[ -n "$STAMP" ] || { echo "prune: no reference time"; exit 64; }
REF=$(mktemp "${TMPDIR:-/tmp}/verify-prune-ref.XXXXXX") || exit 70
trap 'rm -f "$REF"' EXIT
touch -t "$STAMP" "$REF" || { echo "prune: no reference file"; exit 70; }

keep_of() {
  local n=$1; shift
  for k in "$@"; do
    [ "$k" = "$n" ] && return 0
  done
  return 1
}

# touched DIR: 그 아래(깊이 3까지) 기준 시각보다 새 것이 하나라도 있으면 0.
# 깊이 3은 카고가 새 산출물을 남기는 자리(target/<triple>/<profile>/<deps|build>)다.
touched() {
  local d=$1 f g h
  for f in "$d" "$d"/*; do
    [ -e "$f" ] || continue
    [ "$f" -nt "$REF" ] && return 0
    [ -d "$f" ] || continue
    for g in "$f"/*; do
      [ -e "$g" ] || continue
      [ "$g" -nt "$REF" ] && return 0
      [ -d "$g" ] || continue
      for h in "$g"/*; do
        [ -e "$h" ] || continue
        [ "$h" -nt "$REF" ] && return 0
      done
    done
  done
  return 1
}

removed=0
[ -d "$BASE" ] || { echo "prune: tracks removed 0, free after 0 GiB"; exit 0; }
for track in "$BASE"/*; do
  [ -d "$track" ] || continue
  name=$(basename "$track")
  [ -d "$track/target" ] || continue
  if keep_of "$name" "$@"; then continue; fi
  if [ -e "$BASE/.lock-$name" ]; then continue; fi
  if touched "$track/target"; then continue; fi
  rm -rf "$track/target" || continue
  removed=$((removed + 1))
done

free=$(df -k "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')
[ -n "$free" ] || free=0
echo "prune: tracks removed $removed, free after $((free / 1024 / 1024)) GiB"
