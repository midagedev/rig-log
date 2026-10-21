#!/bin/bash
# 자체 시험이 FAIL-first 인지 보인다: 각 규칙이 기대하는 한 줄을 복사본에서 깨고
# 그 복사본의 시험이 빨강인지 본다. 원본은 초록이어야 한다.
#
#   failfirst.sh            모든 규칙
#   failfirst.sh s-attr     그 규칙 하나
#
# 규칙 이름과 깨는 줄은 아래 표에 있다. 복사본은 임시 디렉터리에 만들어지고,
# 원본은 건드리지 않는다(읽기만).
set -u
SRC=$(cd "$(dirname "$0")" && pwd -P)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vfail-XXXXXX")
ONLY=${1:-}

break_run() {   # break_run NAME FILE OLD NEW TEST-COMMAND
  local name=$1 file=$2 old=$3 new=$4 cmd=$5
  [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && return 0
  local dir="$WORK/$name"
  rm -rf "$dir"; mkdir -p "$dir"
  cp -R "$SRC"/. "$dir"/
  if ! python3 - "$dir/$file" "$old" "$new" <<'EOF'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path).read()
if old not in s:
    sys.stderr.write("!! the line to break is not there: %r\n" % old[:60])
    sys.exit(3)
open(path, "w").write(s.replace(old, new, 1))
EOF
  then
    echo "== $name: the line to break was not found"
    return
  fi
  local out rc
  out=$(cd "$dir" && eval "$cmd" 2>&1); rc=$?
  echo "== $name: rc=$rc"
  echo "$out" | grep -E "FAIL|self-test" | head -4
}

echo "--- the real file (green) ---"
(cd "$SRC" && python3 phases.py; echo "phases rc=$?")
(cd "$SRC" && python3 verify --self-test >/dev/null 2>&1; echo "verify rc=$?")
(cd "$SRC" && python3 guard-hook.py --self-test 2>&1 | tail -1)

echo
echo "--- the broken copies (red) ---"

break_run s-attr phases.py \
  '            if one_rc != 0:
                attributed[e["id"]].append((name, one_rc))' \
  '            if False and one_rc != 0:
                attributed[e["id"]].append((name, one_rc))' \
  'python3 phases.py'

break_run s-defer phases.py \
  '            return "the patch does not apply (%s)" % (last[-1][:160] if last else "")' \
  '            return ""' \
  'python3 phases.py'

break_run s-main phases.py \
  '            mains.append(name)' \
  '            pass' \
  'python3 phases.py'

break_run s-same-mix phases.py \
  '    signature = mix_signature(base_sha, entries)
    last = read_last_run(cfg, "s", signature)' \
  '    signature = mix_signature(base_sha, entries)
    last = None' \
  'python3 phases.py'

break_run b-union phases.py \
  '            if g not in union:
                union.append(g)' \
  '            if not union:
                union.append(g)' \
  'python3 phases.py'

break_run b-attr phases.py \
  '                attributed[e["id"]].append(name)' \
  '                pass' \
  'python3 phases.py'

break_run hold phases.py \
  '    rc, out, err = run(["bash", box, "test -e %s" % BOX_GPU_HOLD], cwd=tree, env=env)
    return rc == 0' \
  '    rc, out, err = run(["bash", box, "test -e %s" % BOX_GPU_HOLD], cwd=tree, env=env)
    return False' \
  'python3 phases.py'

break_run nokey phases.py \
  '    return files or None' \
  '    return files' \
  'python3 phases.py'

break_run prune-age prune-remote.sh \
  '  if touched "$track/target"; then continue; fi' \
  '  if false; then continue; fi' \
  'python3 phases.py'

break_run prune-lock prune-remote.sh \
  '  if [ -e "$BASE/.lock-$name" ]; then continue; fi' \
  '  if false; then continue; fi' \
  'python3 phases.py'

break_run prune-keep prune-remote.sh \
  '  if keep_of "$name" "$@"; then continue; fi' \
  '  if false; then continue; fi' \
  'python3 phases.py'

break_run guard-just guard-hook.py \
  'JUST_ALLOWED = ("mac-locks",)' \
  'JUST_ALLOWED = ()' \
  'python3 guard-hook.py --self-test'

break_run guard-recipes guard-hook.py \
  '                 "tools/box-static.sh", "tools/check-recipes.sh")' \
  '                 "tools/box-static.sh")' \
  'python3 guard-hook.py --self-test'

echo
echo "work dir: $WORK"
