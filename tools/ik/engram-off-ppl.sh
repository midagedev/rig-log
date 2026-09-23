#!/bin/bash
# engram-off-ppl.sh — DeepSeek-V4.1에서 engram 가지를 빼면 무엇을 잃는가.
#
# 계기: mlx-lm#1895(V4.1 텍스트 백본)는 sanitize에서 engram 텐서를 버리고 engram
# 모듈이 없다. 같은 모델을 engram 없이 돌리는 것이 얼마나 다른 모델인지를 ik의
# 한 바이너리로 잰다: IK_NO_ENGRAM=1이면 build_deepseek4.cpp의 층 입구 engram
# 덧셈을 건너뛴다(그 외 그래프는 같다). 켠 쪽 로짓을 기준으로 끈 쪽의 KLD·top-1
# 일치율·PPL을 받는다. wikitext-2 c2048 4청크, CPU만 — 09-15 기준값 2.2355와 같은 설정.
#
# 트리: /home/user/ik-engram-probe (upstream main의 워크트리, 공용 트리를 더럽히지 않는다).
# 임대: /home/user/lease.sh wait && acquire, exit 트랩에서 release. 매 팔 앞뒤 증인.
# 센티널: 마지막 줄 ENGRAM_PROBE_DONE / ENGRAM_PROBE_FAILED.
set -u
U=/home/user; SRC=$U/ik_llama.cpp; WT=$U/ik-engram-probe; OUT=$U/engram-probe
LEASE=$U/lease.sh
M=/models/DeepSeek-V4.1-Flash-Q3_K_M/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
TXT=$U/eval/wiki.test.raw
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
HELD=""
finish(){ [ -n "$HELD" ] && bash $LEASE release && say "lease released"
  [ "$1" -eq 0 ] && echo ENGRAM_PROBE_DONE || echo ENGRAM_PROBE_FAILED; exit "$1"; }
trap 'finish 1' INT TERM

bash $LEASE wait --timeout 3600 || { say "box not quiet within 1 h"; finish 1; }
bash $LEASE acquire "engram-off-ppl" || { say "lease refused"; finish 1; }
HELD=1

# git 쓰기는 user로 — root로 fetch/worktree add를 하면 공용 .git에 root 소유 객체가 남아
# user의 커밋이 막힌다(2026-09-17, 2026-09-23 두 번; 두 번째는 이 스크립트가 만들었다).
G(){ sudo -u user -H git "$@"; }
if [ ! -d $WT ]; then
  G -C $SRC fetch -q origin main || finish 1
  G -C $SRC worktree add -q --detach $WT origin/main || finish 1
fi
cd $WT || finish 1
say "tree $(git log -1 --format='%h %cd %s' --date=short)"

F=src/graphs/build_deepseek4.cpp
if ! grep -q IK_NO_ENGRAM $F; then
  python3 - "$F" <<'EOF' || finish 1
import sys
p = sys.argv[1]; s = open(p).read()
old = "        if (model.layers[il].engram_embd) {\n"
assert s.count(old) == 1, "engram block anchor not unique"
new = ("        static const bool ik_no_engram = getenv(\"IK_NO_ENGRAM\") != nullptr;\n"
       "        if (model.layers[il].engram_embd && !ik_no_engram) {\n")
open(p, "w").write(s.replace(old, new))
EOF
fi
git diff --stat
git diff > $OUT/probe.diff

cmake -B build-cpu -DGGML_CUDA=OFF -DGGML_NATIVE=ON > $OUT/cmake.log 2>&1 || { say "cmake failed"; tail -20 $OUT/cmake.log; finish 1; }
cmake --build build-cpu -j 48 --target llama-perplexity > $OUT/build.log 2>&1 || { say "build failed"; grep -i -m20 error $OUT/build.log; finish 1; }
say "build ok"

run(){ tag=$1; shift
  echo "{\"arm\":\"$tag\",\"at\":\"start\",\"witness\":$(bash $LEASE witness)}" >> $OUT/witness.jsonl
  say "arm $tag"
  "$@" > $OUT/$tag.log 2>&1; rc=$?
  echo "{\"arm\":\"$tag\",\"at\":\"end\",\"rc\":$rc,\"witness\":$(bash $LEASE witness)}" >> $OUT/witness.jsonl
  grep -E "Final estimate|Mean +KLD|Same top|RMS Δp|^\[[0-9]+\]" $OUT/$tag.log | tail -12
  return $rc; }

COMMON="-m $M -f $TXT -c 2048 --chunks 4 -b 2048 -ngl 0 -t 32"
CUDA_VISIBLE_DEVICES="" run on  ./build-cpu/bin/llama-perplexity $COMMON --kl-divergence-base $OUT/on.kld || finish 1
CUDA_VISIBLE_DEVICES="" IK_NO_ENGRAM=1 run off ./build-cpu/bin/llama-perplexity $COMMON --kl-divergence-base $OUT/on.kld --kl-divergence || finish 1
# 대조: 켠 쪽을 켠 쪽에 대 KLD가 0인지(도구가 차이를 만들어 내지 않음)
CUDA_VISIBLE_DEVICES="" run on2 ./build-cpu/bin/llama-perplexity $COMMON --kl-divergence-base $OUT/on.kld --kl-divergence || finish 1
finish 0
