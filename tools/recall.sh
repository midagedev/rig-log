#!/usr/bin/env bash
# 이 리포가 이미 쥔 답을 먼저 찾는다. 증상 키워드를 받아 log/ 산문과 README 타임라인 표를
# 한 번에 훑고, 날짜순으로 제목과 맞은 줄을 낸다.
#
#   tools/recall.sh Xid                     # 한 낱말
#   tools/recall.sh 'Xid 79|fallen off'     # 확장 정규식(따옴표)
#   tools/recall.sh -n 3 재부팅              # 파일당 맞은 줄 3개까지(기본 2)
#
# 막는 실패: 리포가 이미 기록한 것을 안 읽고 라운드를 여는 것. 2026-09-22 아침에 두 번 밟았다 —
# Xid 79 뒤의 재부팅이 사람을 요구한다는 것을 09-18-b가 적어 뒀는데 안 읽어 15분을 태웠고,
# "CUDA 순서는 nvidia-smi 인덱스가 아니라 UUID"도 이미 규칙인데 다시 어겼다. 검색이 습관보다 싸다.
#
# 위임 스펙과 라운드 시작의 첫 줄로 쓴다: "이 증상으로 recall을 돌렸는가."
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PER=2
while getopts "n:" o; do case $o in n) PER=$OPTARG ;; *) exit 64 ;; esac; done
shift $((OPTIND - 1))
[ $# -ge 1 ] || { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 64; }
PAT=$*

hits=0
# 로그: 파일명이 날짜순이라 그대로 정렬된다. 제목은 첫 번째 '# ' 줄.
while IFS= read -r f; do
  n=$(grep -icE -- "$PAT" "$f" || true)
  [ "$n" -gt 0 ] || continue
  hits=$((hits + 1))
  printf '\n\033[1m%s\033[0m  (%s곳)\n  %s\n' \
    "${f#"$ROOT"/}" "$n" "$(grep -m1 '^# ' "$f" | sed 's/^# //')"
  grep -inE -- "$PAT" "$f" | head -n "$PER" | while IFS=: read -r ln rest; do
    printf '  %s:%s  %s\n' "${f#"$ROOT"/}" "$ln" "$(echo "$rest" | cut -c1-150)"
  done
done < <(find "$ROOT/log" -name '*.md' | sort)

# README 타임라인 표: 한 줄이 한 라운드라 줄 그대로가 요약이다.
readme=$(grep -inE -- "$PAT" "$ROOT/README.md" | head -n 6 || true)
if [ -n "$readme" ]; then
  hits=$((hits + 1))
  printf '\n\033[1mREADME.md\033[0m  (타임라인)\n'
  echo "$readme" | while IFS=: read -r ln rest; do
    printf '  README.md:%s  %s\n' "$ln" "$(echo "$rest" | cut -c1-150)"
  done
fi

# docs/: 방법·하드웨어 노트·업스트림 서류. 제목만 낸다(본문은 길다).
docs=$(grep -rilE --include='*.md' -- "$PAT" "$ROOT/docs" | sort || true)
if [ -n "$docs" ]; then
  printf '\n\033[1mdocs/\033[0m\n'
  echo "$docs" | while IFS= read -r f; do
    printf '  %s  — %s\n' "${f#"$ROOT"/}" "$(grep -m1 '^# ' "$f" | sed 's/^# //')"
  done
fi

if [ "$hits" -eq 0 ] && [ -z "$docs" ]; then
  echo "recall: '$PAT' 없음 — 이 리포에 기록이 없다는 뜻이지, 일어난 적이 없다는 뜻은 아니다."
  exit 1
fi
