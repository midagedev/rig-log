#!/usr/bin/env bash
# WKS-37: 같은 f16·같은 imatrix에서 나온 두 GGUF를 3090의 ik CUDA에서 번갈아 잰다 (박스에서 실행).
#
#   bash kt-3090-ab.sh [file.gguf]...        # 기본: quant-kt.sh가 만든 두 파일
#   KT_PPL=/path/wiki.test.raw bash kt-3090-ab.sh    # 속도 뒤에 같은 하네스로 perplexity도
#
# 막는 실패: ① 파일마다 다른 시각·다른 기계 상태에서 잰 숫자를 비교하는 것 — 팔은 (파일, 깊이)이고
# 한 임대 안에서 바퀴마다 한 칸씩 돈다. ② A6000에 올라가는 것 — 3090을 이름으로 찾아 UUID로 고정하고,
# 못 찾으면 돌지 않는다. ③ 서빙이 카드를 쥔 채 재는 것 — llm.service가 active면 돌지 않는다.
set -uo pipefail
SRC=${KT_SRC:-/models/v2lite-src}
IK=${IK:-/home/user/ik_llama.cpp}
BENCH=$IK/build/bin/llama-bench
PPLBIN=$IK/build/bin/llama-perplexity
N=${KT_N:-96}
ROUNDS=${KT_ROUNDS:-3}
DEPTHS=${KT_DEPTHS:-0 4096}
FLAGS=${KT_FLAGS:--mla 3 -fa 1 -fmoe 1}
files=("$@")
[ ${#files[@]} -gt 0 ] || files=("$SRC/v2lite-q3km-imat.gguf" "$SRC/v2lite-iq3kt-mix.gguf")
for f in "${files[@]}"; do [ -f "$f" ] || { echo "missing $f" >&2; exit 2; }; done
[ "$(systemctl is-active llm.service)" = active ] && { echo "llm.service is active — stop it first" >&2; exit 3; }
UUID=$(nvidia-smi --query-gpu=name,uuid --format=csv,noheader | awk -F', ' '/RTX 3090/{print $2; exit}')
[ -n "$UUID" ] || { echo "no RTX 3090 found" >&2; exit 4; }
export CUDA_VISIBLE_DEVICES=$UUID
witness() {
  echo "--- witness $1 $(date -u +%Y-%m-%dT%H:%M:%SZ) load=$(cut -d' ' -f1-3 /proc/loadavg) io=$(grep '^some' /proc/pressure/io | cut -d' ' -f2) gpu=$(nvidia-smi --query-gpu=name,utilization.gpu,memory.used,power.draw --format=csv,noheader | sed 's/NVIDIA //' | tr '\n' ';')"
  echo "    gpu-apps: $(nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader | tr '\n' ';')"
  echo "    busiest: $(ps -eo comm,pcpu --sort=-pcpu --no-headers | head -n 4 | awk '{printf "%s %s%% | ", $1, $2}')"
}
exec 9>/root/bloomery-cpu.lock
flock -w 3600 9 || { echo "[lease] timed out" >&2; exit 75; }
witness pre
arms=()
sums=()
for dep in $DEPTHS; do for f in "${files[@]}"; do arms+=("$f:$dep"); done; done
for r in $(seq "$ROUNDS"); do
  for i in $(seq 0 $((${#arms[@]} - 1))); do
    a=${arms[$(((i + r - 1) % ${#arms[@]}))]}
    f=${a%:*}; dep=${a##*:}
    if [ "$dep" = 0 ]; then
      raw=$("$BENCH" -m "$f" -ngl 99 -p 0 -n "$N" -r 1 $FLAGS 2>&1); pat="tg$N"
    else
      raw=$("$BENCH" -m "$f" -ngl 99 -p 0 -n 0 -gp "$dep,$N" -r 1 $FLAGS 2>&1); pat="tg$N@pp$dep"
    fi
    v=$(echo "$raw" | grep -E "\| *$pat *\|" | awk -F'|' '{print $(NF-1)}' | sed 's/ ±.*//;s/ //g')
    [ -n "$v" ] || { echo "r$r $a produced no $pat line" >&2; echo "$raw" | tail -n 8 >&2; exit 1; }
    echo "r$r $(basename "$f") d=$dep | $v tok/s"
    sums+=("$(basename "$f") d=$dep|$v")
  done
done
printf '%s\n' "${sums[@]}" | awk -F'|' '{s[$1]+=$2; n[$1]++; if(!($1 in lo)||$2<lo[$1])lo[$1]=$2; if($2>hi[$1])hi[$1]=$2} END{for(k in s) printf "mean %-34s %.2f tok/s (n=%d, %.2f–%.2f)\n", k, s[k]/n[k], n[k], lo[k], hi[k]}' | sort
witness post-speed
if [ -n "${KT_PPL:-}" ]; then
  [ -f "$KT_PPL" ] || { echo "missing $KT_PPL" >&2; exit 2; }
  for f in "${files[@]}"; do
    echo "=== ppl $(basename "$f")"
    "$PPLBIN" -m "$f" -f "$KT_PPL" -ngl 99 -c 512 -b 512 $FLAGS 2>&1 | grep -E "Final estimate|^perplexity:|chunks"
  done
  witness post-ppl
fi
