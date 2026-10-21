#!/bin/bash
# 두 번째 맥에서 도는 한 단계(single step) 러너. station 이 ssh 로 이 스크립트를 보낸다.
#   s-remote.sh <track> <base-sha> <payload-dir> <cmd-file>
#
#   track      스테이션 클론의 이름(리모트의 repo/bloomery-mr/<track>)
#   base-sha   되돌아갈 리비전(그 트리의 클론에 있는 객체)
#   payload-dir  patch.diff 와 untracked.tar 이 있는 디렉터리(없어도 된다)
#   cmd-file   실행할 명령 한 줄(정적 단계의 job 파일이 준 명령 그대로)
#
# 스테이션 클론 하나를 base 로 되돌린 뒤, 요청 하나의 패치(있다면)를 씌우고,
# 그 위에 명령 하나를 돈다. 정적 단계의 빨강을 요청 하나에 돌려 붙일 때 쓴다.
set -u

TRACK=$1
BASE=$2
PAY=$3
CMDF=$4
B="$HOME/repo/bloomery-mr/$TRACK"

say() { printf '%s\n' "$*"; }

[ -d "$B/.git" ] || { say "s: 클론이 없다: $B"; exit 66; }
cd "$B" || exit 66

git update-index -q --refresh >/dev/null 2>&1
git checkout -q -f --detach "$BASE" || { say "s: checkout 실패 ($BASE)"; exit 70; }
git clean -qfdx -e target
if [ -s "$PAY/patch.diff" ]; then
  git apply --whitespace=nowarn "$PAY/patch.diff" || { say "s: 패치가 씌워지지 않았다"; exit 71; }
fi
if [ -f "$PAY/untracked.tar" ]; then
  tar -xf "$PAY/untracked.tar" -C "$B" || { say "s: 미추적 파일을 못 풀었다"; exit 72; }
fi

# 환경: 고정 툴체인을 PATH 첫 자리에, CUDA 와 리눅스 시스루트는 env 파일에서.
if [ -f "$HOME/opt/bloomery-mac-env.sh" ]; then . "$HOME/opt/bloomery-mac-env.sh"; fi
export PATH="$HOME/opt/bloomery-bin:$HOME/.cargo/bin:$PATH"
CH=$(sed -nE 's/^[[:space:]]*channel[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' rust-toolchain.toml 2>/dev/null | head -1)
[ -n "$CH" ] || CH=nightly-2026-08-28
case "$(uname -m)" in
  arm64) HOSTT=aarch64-apple-darwin ;;
  *) HOSTT=x86_64-apple-darwin ;;
esac
if [ -d "$HOME/.rustup/toolchains/$CH-$HOSTT/bin" ]; then
  PATH="$HOME/.rustup/toolchains/$CH-$HOSTT/bin:$PATH"
fi
export PATH
mkdir -p "$B/target"

CMD=$(cat "$CMDF")
say "s: track $TRACK at ${BASE:0:12}"
say "s: $CMD"
bash -c "$CMD" > "$B/target/s-step.log" 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  say "s: 단계 실패 (rc $rc)"
  tail -40 "$B/target/s-step.log"
fi
say "s: rc $rc"
exit $rc
