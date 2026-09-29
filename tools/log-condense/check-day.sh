#!/bin/bash
# 날짜 파일 하나를 제자리에서 줄인 결과를 잰다 (2026-09-30~, 09-23–09-29 축약에 만들었다).
#   tools/log-condense/check-day.sh <새 파일> <YYYY-MM-DD> [원본 커밋, 기본 HEAD]
# 두 게이트를 차례로 돈다: check-condense(숫자·취소선·앵커·업스트림 URL·분량)와
# check-log의 절 규칙(새 파일의 모든 절을 새 절로 본다: 2,500 B, 제목 60자, 앵커, 머리 문단).
set -u
root=$(cd "$(dirname "$0")/../.." && pwd)
new=$1; day=$2; src=${3:-$(git -C "$root" rev-parse --short HEAD)}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git -C "$root" show "$src:log/$day.md" > "$tmp/$day.md" || exit 2
rc=0
CONDENSE_SRC_COMMIT=$src CONDENSE_CAP=${CONDENSE_CAP:-0.45} CONDENSE_LINK_BASE="$root/log" \
  python3 "$root/tools/log-condense/check-condense.py" "$new" "$tmp/$day.md" || rc=1
python3 - "$root" "$new" "$day" <<'PY' || rc=1
import sys, runpy
root, new, day = sys.argv[1:]
sys.argv = ["check-log"]
g = runpy.run_path(f"{root}/tools/check-log.py", run_name="check_log_lib")
errs, warns = [], []
g["check_day"](f"log/{day}.md", open(new, encoding="utf-8").read(), None, errs, warns)
for e in errs: print("FAIL", e)
secs = g["sections"](open(new, encoding="utf-8").read())
for slug, title, size, ln, extra in secs:
    print(f"  {size:5d} B  {len(title):3d}자  {title[:40]}")
print(f"check-log sections: {'FAIL' if errs else 'ok'} ({len(secs)} sections)")
sys.exit(1 if errs else 0)
PY
exit $rc
