#!/bin/bash
# 두 번째 맥에서 도는 F(fast) 러너. station 이 ssh 로 이 스크립트를 보낸다.
#   f-remote.sh <payload-dir> <id> <sha> <mode> <packages> <tests> <features>
#
#   payload-dir  patch.diff 와 untracked.tar 이 있는 디렉터리
#   id           refs/verify/<id> 로 밀린 base
#   mode         workspace | packages
#   packages     콤마로 나눈 패키지 이름 (check 의 -p 목록)
#   tests        콤마로 나눈 패키지 이름 (native cargo test 목록)
#   features     콤마로 나눈 feature 목록 (비면 없음)
#
# 이 스크립트는 스테이션 클론(station-f)만 바꾼다: base 로 되돌린 뒤(base 로
# checkout), 패치를 씌우고, 미추적 파일을 푼다. 그 위에 check 와 native test 를
# 돌리고 파일:줄 이 붙은 오류를 그대로 찍는다.
set -u

PAY=$1
ID=$2
MODE=$4
PKGS=$5
TESTS=$6
FEATS=$7
TRACK=${VERIFY_TRACK:-station-f}
B="$HOME/repo/bloomery-mr/$TRACK"

say() { printf '%s\n' "$*"; }
load() { printf 'load: %s\n' "$(sysctl -n vm.loadavg 2>/dev/null | tr -d '{}')"; }

say "f: id $ID mode $MODE track $TRACK"
load

[ -d "$B/.git" ] || { say "f: 클론이 없다: $B"; exit 66; }
cd "$B" || exit 66

git update-index -q --refresh >/dev/null 2>&1
git checkout -q -f --detach "refs/verify/$ID" || { say "f: checkout 실패 (refs/verify/$ID)"; exit 70; }
git clean -qfdx -e target
if [ -s "$PAY/patch.diff" ]; then
  git apply --whitespace=nowarn "$PAY/patch.diff" || { say "f: 패치가 씌워지지 않았다"; exit 71; }
fi
if [ -f "$PAY/untracked.tar" ]; then
  tar -xf "$PAY/untracked.tar" -C "$B" || { say "f: 미추적 파일을 못 풀었다"; exit 72; }
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

cargo fetch --locked > "$B/target/fetch.log" 2>&1 || {
  say "f: cargo fetch --locked 실패"
  tail -5 "$B/target/fetch.log"
  exit 69
}

rc=0
if [ "$MODE" = workspace ]; then
  set -- check --target x86_64-unknown-linux-gnu --all-targets --workspace
else
  set -- check --target x86_64-unknown-linux-gnu --all-targets
  OLDIFS=$IFS
  IFS=,
  for p in $PKGS; do set -- "$@" -p "$p"; done
  IFS=$OLDIFS
fi
if [ -n "$FEATS" ]; then set -- "$@" --features "$FEATS"; fi
say "f: cargo $*"
cargo "$@" > "$B/target/check.log" 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  say "f: check 실패 (rc $rc)"
  grep -E '^error' "$B/target/check.log" | head -30
  grep -E '^ +--> ' "$B/target/check.log" | head -30
  tail -20 "$B/target/check.log"
else
  say "f: check 통과"
fi

OLDIFS=$IFS
IFS=,
for p in $TESTS; do
  say "f: cargo test -p $p"
  cargo test -p "$p" > "$B/target/test-$p.log" 2>&1
  trc=$?
  if [ "$trc" -ne 0 ]; then
    rc=$trc
    say "f: test 실패 $p (rc $trc)"
    grep -E '^error|FAILED|panicked' "$B/target/test-$p.log" | head -20
    tail -20 "$B/target/test-$p.log"
  else
    say "f: test 통과 $p"
  fi
done
IFS=$OLDIFS

load
say "f: rc $rc"
exit $rc
