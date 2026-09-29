#!/usr/bin/env python3
"""log/ 쓰기 규칙을 커밋 전에 잰다. pre-commit 훅(tools/hooks/pre-commit)이 부른다.

규칙의 근거는 CLAUDE.md 「관례」다. 이 파일은 그 규칙을 숫자로 옮긴 것이고, 한도는 잘 읽히던
주(09-15–09-21)의 실측에서 잡았다. 2026-09-30 도입: 09-23–09-29에 절 110개가 2.5 KB를 넘고
제목 중앙값이 62–83자로 자라는 동안 글로 적힌 규칙은 아무것도 막지 못했다.

  python3 tools/check-log.py            # 스테이징된 변경만 (훅이 쓰는 모드)
  python3 tools/check-log.py --rev C    # 커밋 C가 바꾼 것만 (FAIL-first 확인용)
  python3 tools/check-log.py --all      # 트리 전체 감사, 위반 목록만 출력

막는 것:
  S1 절 본문 > 2,500 B (UTF-8). 이미 넘던 옛 절은 한 번에 600 B 넘게 자라지 않으면 통과
     (선 긋기 정정은 들어가야 하니까).
  S2 새 절이나 바뀐 제목이 60자 초과. 09-15–09-21 최대가 57자였다.
  S3 `## ` 바로 위에 `<a name="slug"></a>`가 없거나 slug가 파일 안에서 겹침.
  F1 log/에 날짜 파일(YYYY-MM-DD.md)이 아닌 새 파일. moved.tsv에 오른 이름의 "옮겨졌다" 스텁은 예외.
  F2 날짜 파일이 `# YYYY-MM-DD` 제목과 첫 절 앞 머리 문단으로 시작하지 않음.
  R1 가장 최근 날짜보다 앞선 날짜 파일에 README 기록 색인 행이 없음.
  R2 색인 행의 보이는 글자(링크 대상 제외)가 200자 초과.
못 막는 것: 내부 은어(라운드 이름, 절 간 참조 남발). 그것은 읽어서 잡는다.
"""
import os
import re
import subprocess
import sys

SECTION_CAP = int(os.environ.get("LOG_SECTION_CAP", 2500))
LEGACY_GROWTH = 600
TITLE_CAP = 60
ROW_CAP = 200
DAY_RE = re.compile(r"^log/(\d{4})-(\d\d)-(\d\d)\.md$")
ANCHOR_RE = re.compile(r'^<a name="([^"]+)"></a>\s*$')
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                      text=True, check=True).stdout.strip()


def git(*args, ok_fail=False):
    p = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    if p.returncode and not ok_fail:
        sys.exit(f"git {' '.join(args)} failed: {p.stderr}")
    return p.stdout if p.returncode == 0 else None


def sections(text):
    """[(slug or None, title, body_bytes, line_no)] — body는 `## ` 줄부터 다음 절 앞까지."""
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    out = []
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        # 합친 절은 옛 앵커를 `## ` 위에 여러 줄 쌓는다(2026-09-30~). 쌓인 줄은 전부 다음 절 몫이다.
        while k + 1 < len(heads) and end > i + 1 and (ANCHOR_RE.match(lines[end - 1]) or not lines[end - 1].strip()):
            end -= 1
        stacked, j = [], i - 1
        while j >= 0 and ANCHOR_RE.match(lines[j]):
            stacked.insert(0, ANCHOR_RE.match(lines[j]).group(1))
            j -= 1
        body = "\n".join(lines[i:end]).strip()
        out.append((stacked[-1] if stacked else None, lines[i][3:].strip(), len(body.encode()), i + 1, stacked[:-1]))
    return out


def head_errs(path, text):
    date = os.path.basename(path)[:-3]
    out = []
    first = text.split("\n", 1)[0].strip()
    if first != f"# {date}":
        out.append(f"{path}:1 F2 첫 줄은 `# {date}`여야 한다 (지금: {first[:40]!r})")
    secs = sections(text)
    if secs:
        head = text.split("\n")[1:secs[0][3] - 1]
        if not any(l.strip() and not ANCHOR_RE.match(l) and not l.startswith("#") for l in head):
            out.append(f"{path}:1 F2 첫 절 앞에 그날을 요약하는 머리 문단이 없다")
    return out


def title_len(title):
    # 선 그은 옛 제목은 정정 기록이라 세지 않는다.
    return len(re.sub(r"~~.*?~~", "", title).strip())


def check_day(path, new, old, errs, warns):
    # 새 파일이거나 전에 통과하던 파일만 머리를 잰다 — 09-30 전 파일의 결손이 덧붙이기를 막지 않게.
    if old is None or not head_errs(path, old):
        errs.extend(head_errs(path, new))
    else:
        warns.extend(e + " (옛 결손)" for e in head_errs(path, new))
    secs = sections(new)
    old_secs = {(s[0] or s[1]): s[:4] for s in sections(old)} if old is not None else {}
    seen = {}
    for slug, title, size, ln, extra in secs:
        for a in extra:
            if not SLUG_RE.match(a):
                errs.append(f"{path}:{ln} S3 쌓인 slug {a!r}는 소문자·숫자·`-`·`.`만 쓴다")
            if a in seen:
                errs.append(f"{path}:{ln} S3 쌓인 slug {a!r}가 {seen[a]}행과 겹친다")
            seen.setdefault(a, ln)
        key = slug or title
        prev = old_secs.get(key)
        changed = prev is None or prev[1:3] != (title, size)
        if slug is None:
            if changed:
                errs.append(f"{path}:{ln} S3 `## {title[:30]}` 바로 위에 <a name=\"slug\"></a>가 없다")
        elif not SLUG_RE.match(slug):
            errs.append(f"{path}:{ln} S3 slug {slug!r}는 소문자·숫자·`-`·`.`만 쓴다")
        if slug in seen and slug is not None:
            errs.append(f"{path}:{ln} S3 slug {slug!r}가 {seen[slug]}행과 겹친다")
        seen.setdefault(slug, ln)
        if not changed:
            continue
        if (prev is None or prev[1] != title) and title_len(title) > TITLE_CAP:
            errs.append(f"{path}:{ln} S2 제목 {title_len(title)}자 > {TITLE_CAP}자. 제목은 목차다 — "
                        f"숫자와 결론은 본문 첫 문단에 쓴다: {title[:50]}…")
        if size > SECTION_CAP:
            if prev is not None and prev[2] > SECTION_CAP:
                if size - prev[2] > LEGACY_GROWTH:
                    errs.append(f"{path}:{ln} S1 이미 {prev[2]:,} B이던 절이 {size:,} B로 자랐다 "
                                f"(+{size - prev[2]} > {LEGACY_GROWTH}). 새 절로 쓰거나 줄인다")
                else:
                    warns.append(f"{path}:{ln} S1 옛 절 {size:,} B (한도 전부터 넘음)")
            else:
                errs.append(f"{path}:{ln} S1 절 {size:,} B > {SECTION_CAP:,} B. 질문 → 한 일 → 숫자 → "
                            f"판명된 것만 남기고, 긴 상세는 docs/나 bloomery 쪽에 두고 링크한다")


def is_moved_stub(path, text, moved):
    # 날짜 파일로 합친 옛 파일명을 외부 링크 때문에 남기는 스텁은 moved.tsv에 올라 있을 때만 허용한다.
    name = os.path.basename(path)
    return text.startswith("# 옮겨졌다 / Moved") and any(
        l.split("\t", 1)[0] == name for l in (moved or "").splitlines())


def visible(row):
    return re.sub(r"\]\([^)]*\)", "]", row)


def check_readme(readme, day_files, errs):
    dates = sorted(f[4:14] for f in day_files)
    if not dates:
        return
    rows = {}
    for m in re.finditer(r"(?m)^\| \[?(\d\d-\d\d)\]?[^\n]*$", readme):
        rows[m.group(1)] = m.group(0)
    for d in dates[:-1]:
        mmdd = d[5:]
        row = rows.get(mmdd)
        if row is None:
            errs.append(f"README.md R1 기록 색인에 {mmdd} 행이 없다 — 날짜가 넘어가면 전날 행을 쓴다")
        elif f"(log/{d}.md)" not in row:
            errs.append(f"README.md R1 {mmdd} 행이 log/{d}.md를 링크하지 않는다")
    for mmdd, row in rows.items():
        n = len(visible(row))
        if n > ROW_CAP:
            errs.append(f"README.md R2 {mmdd} 행 {n}자 > {ROW_CAP}자. 색인은 하루 한 줄, 상세는 날짜 파일이 진다")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--staged"
    errs, warns = [], []
    if mode == "--all":
        files = git("ls-files", "log").split()
        read_new = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()
        read_old = lambda p: None
        added = set()
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        tree = files
    else:
        if mode == "--rev":
            rev = sys.argv[2]
            base, new_ref = f"{rev}^", rev
            diff = git("diff", "--name-status", "--no-renames", base, rev)
            tree = git("ls-tree", "-r", "--name-only", rev, "log").split()
            readme = git("show", f"{rev}:README.md")
        else:
            base, new_ref = "HEAD", ""
            diff = git("diff", "--cached", "--name-status", "--no-renames")
            tree = git("ls-files", "log").split()
            readme = git("show", ":README.md")
        files, added = [], set()
        for line in diff.splitlines():
            st, p = line.split("\t", 1)
            if p.startswith("log/") and st != "D":
                files.append(p)
                if st == "A":
                    added.add(p)
        if not files and "README.md" not in diff:
            return 0
        read_new = lambda p: git("show", f"{new_ref}:{p}")
        read_old = lambda p: git("show", f"{base}:{p}", ok_fail=True)
    for p in files:
        if p.endswith(".tsv"):
            continue
        if DAY_RE.match(p):
            check_day(p, read_new(p), read_old(p), errs, warns)
        elif p in added and not is_moved_stub(p, read_new(p), read_new("log/moved.tsv")):
            errs.append(f"{p} F1 log/에는 날짜 파일(YYYY-MM-DD.md)만 새로 만든다 — 실험은 그날 파일의 절이다")
    day_files = [p for p in tree if DAY_RE.match(p)]
    check_readme(readme, day_files, errs)
    for w in warns:
        print("warn", w)
    for e in errs:
        print("FAIL", e)
    if errs:
        print(f"\ncheck-log: {len(errs)}건. 규칙은 tools/check-log.py 머리말과 CLAUDE.md 「관례」. "
              f"한도를 고치려면 근거와 날짜를 같이 적는다. `--no-verify`로 넘기지 않는다.")
        return 1
    if files or mode == "--all":
        print(f"check-log: ok ({len(files)} files, {len(warns)} warn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
