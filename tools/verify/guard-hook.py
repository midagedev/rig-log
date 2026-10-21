#!/usr/bin/env python3
"""PreToolUse 가드 — bloomery 트리에서 빌드·게이트 명령을 막는다.

Claude Code 의 PreToolUse 훅이다. stdin 으로 JSON 이 들어온다.
  deny  → 종료 코드 0 + hookSpecificOutput JSON (사유는 모델이 본다)
  allow → 종료 코드 0, 출력 없음
가드는 자기 때문에 일을 막지 않는다: 본문 전체가 try/except 안에 있고, 예외나
파싱 실패는 allow 다(guard.log 에 한 줄 남긴다).

환경변수
  VERIFY_GUARD_MODE=off|warn|deny   설정 파일의 mode 를 덮어쓴다
  VERIFY_GUARD_CONFIG=<file>        설정 파일 (기본 ~/.config/bloomery/verify-guard)
  VERIFY_GUARD_BLOOMERY=<dir>       bloomery 주 트리 (기본 ~/repo/bloomery)
  VERIFY_GUARD_LOG=<file>           warn/deny 로그 (기본 ~/.cache/bloomery/verify/guard.log)

설정 파일 (없으면 warn + 주 트리 허용)
  mode warn|deny|off
  allow /abs/dir
"""
import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")

CARGO_BUILD = ("build", "check", "test", "clippy", "nextest", "run", "bench", "oxide")
JUST_RECIPES = ("mac-*", "gate-*", "check*", "lint", "test*", "build*", "smoke",
                "contrib-check", "canon-check", "ptx-*", "narrow")
# mac-* is a blanket, but mac-locks only reads the second Mac's pool and its
# track locks (tools/mac-remote.sh --locks): it builds nothing and runs no gate.
# The lead's list keeps mac-static and mac-check out of this set.
JUST_ALLOWED = ("mac-locks",)
BUILD_SCRIPTS = ("tools/box.sh", "tools/gate-batch.sh", "tools/mac-check.sh",
                 "tools/mac-static.sh", "tools/mac-remote.sh", "tools/static-sched.py",
                 "tools/box-static.sh", "tools/check-recipes.sh")
BUILD_SCRIPT_NAMES = tuple(sorted(set(os.path.basename(s) for s in BUILD_SCRIPTS)))
SELFTEST_SCRIPTS = ("check-recipes.sh", "recipes.py", "gate-batch.sh", "mac-static.sh",
                     "mac-remote.sh", "mac-check.sh", "wt.sh", "narrow-scan.sh",
                     "box.sh", "gpu-gate.sh")
# 이 머리말의 명령은 해롭지 않다: build word 는 그 인자일 뿐이다.
EXEMPT_HEAD = ("grep", "echo", "sed", "printf", "git")
SHELL_HEADS = ("bash", "sh", "zsh")


def default_config():
    return {
        "mode": os.environ.get("VERIFY_GUARD_MODE") or None,
        "bloomery": os.environ.get("VERIFY_GUARD_BLOOMERY") or os.path.join(HOME, "repo", "bloomery"),
        "config": os.path.expanduser(os.environ.get("VERIFY_GUARD_CONFIG")
                                     or os.path.join(HOME, ".config", "bloomery", "verify-guard")),
        "log": os.path.expanduser(os.environ.get("VERIFY_GUARD_LOG")
                                  or os.path.join(HOME, ".cache", "bloomery", "verify", "guard.log")),
    }


def read_config(path):
    """설정 파일 → (mode, allow 목록). 파일이 없으면 (warn, [])."""
    mode = "warn"
    allowed = []
    try:
        with open(path) as fh:
            lines = fh.read().splitlines()
    except OSError:
        return mode, allowed
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if parts[0] == "mode" and len(parts) == 2 and parts[1].strip() in ("off", "warn", "deny"):
            mode = parts[1].strip()
        elif parts[0] == "allow" and len(parts) == 2:
            allowed.append(os.path.abspath(os.path.expanduser(parts[1].strip())))
    return mode, allowed


def split_segments(cmd):
    """연산자(&&, ||, ;, |, 개행, $(, ())를 따옴표 밖에서만 잘라 세그먼트를 낸다."""
    segs, cur = [], []
    quote = None
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                cur.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            cur.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            cur.append(ch)
            cur.append(cmd[i + 1])
            i += 2
            continue
        if ch == "\n":
            segs.append("".join(cur))
            cur = []
            i += 1
            continue
        if cmd.startswith("&&", i) or cmd.startswith("||", i):
            segs.append("".join(cur))
            cur = []
            i += 2
            continue
        if ch in ";|()":
            segs.append("".join(cur))
            cur = []
            i += 1
            continue
        if ch == "$" and cmd.startswith("$(", i):
            segs.append("".join(cur))
            cur = []
            i += 2
            continue
        cur.append(ch)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def tokenize(seg):
    """따옴표를 없앤 단어 목록."""
    words, cur = [], []
    quote = None
    i, n = 0, len(seg)
    while i < n:
        ch = seg[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                cur.append(seg[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            cur.append(seg[i + 1])
            i += 2
            continue
        if ch.isspace():
            if cur:
                words.append("".join(cur))
                cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    if cur:
        words.append("".join(cur))
    return words


def strip_prefixes(words):
    """env/nice/time/timeout/nohup/caffeinate/VAR=x 앞 장어를 걷어낸다."""
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            i += 1
            continue
        if w in ("env", "nohup", "caffeinate"):
            i += 1
            continue
        if w == "nice":
            i += 1
            while i < len(words) and (words[i].startswith("-") or words[i].isdigit()):
                i += 1
            continue
        if w == "time":
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 1
            continue
        if w == "timeout":
            i += 1
            if i < len(words) and not words[i].startswith("-"):
                i += 1
            continue
        break
    words = words[i:]
    if len(words) > 1 and words[0] == "cargo" and words[1].startswith("+"):
        words = [words[0]] + words[2:]
    return words


def recipe_matches(recipe):
    import fnmatch
    return any(fnmatch.fnmatchcase(recipe, pat) for pat in JUST_RECIPES)


def build_hit(words):
    """세그먼트가 build 명령이면 (표현, 종류)를 돌려준다. 아니면 None."""
    if not words:
        return None
    head = os.path.basename(words[0])
    if head in EXEMPT_HEAD:
        return None
    if head == "cargo":
        for w in words[1:]:
            if w.startswith("-"):
                continue
            if w in CARGO_BUILD:
                return ("cargo " + w, "cargo")
            return None
        return None
    if head == "just":
        for w in words[1:]:
            if w.startswith("-"):
                continue
            if w in JUST_ALLOWED:
                return None
            if recipe_matches(w):
                return ("just " + w, "just")
            return None
        return None
    for w in words:
        if os.path.basename(w) in BUILD_SCRIPT_NAMES:
            return (w, "script")
    if any(w == "--self-test" for w in words):
        for w in words:
            if os.path.basename(w) in SELFTEST_SCRIPTS:
                return (w + " --self-test", "self-test")
    return None


def shell_inner(words):
    """bash|sh|zsh -c '문자열' 안의 문자열."""
    if not words or os.path.basename(words[0]) not in SHELL_HEADS:
        return None
    for i, w in enumerate(words[1:], 1):
        if w == "-c" or (w.startswith("-") and not w.startswith("--") and "c" in w[1:]):
            if i + 1 < len(words):
                return words[i + 1]
    return None


def resolve_dir(path, base):
    if not path:
        return base
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(base, p)
    return os.path.abspath(p)


def common_dir(path):
    """`git rev-parse --git-common-dir` 과 같은 값. .git 표시를 파일로 읽는다.

    워크트리는 .git 이 파일이고 그 안에 `gitdir: <주>/.git/worktrees/<name>` 가
    있다. 주 트리는 .git 이 디렉터리다. git 를 부르지 않는 이유는 이 훅이 모든
    Bash 호출마다 돈다는 것(그리고 outsource 가드와 겹치지 않으려면).
    """
    p = os.path.abspath(path)
    while True:
        marker = os.path.join(p, ".git")
        if os.path.isdir(marker):
            return os.path.realpath(marker)
        if os.path.isfile(marker):
            try:
                with open(marker) as fh:
                    line = fh.readline().strip()
            except OSError:
                return None
            if not line.startswith("gitdir:"):
                return None
            gd = os.path.realpath(os.path.join(p, line[len("gitdir:"):].strip()))
            parts = gd.split(os.sep)
            if len(parts) >= 2 and parts[-2] == "worktrees":
                gd = os.sep.join(parts[:-2])
            return gd
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def under(path, base):
    p = os.path.realpath(path)
    b = os.path.realpath(base)
    return p == b or p.startswith(b.rstrip(os.sep) + os.sep)


def tree_hint(words, cwd):
    """이 세그먼트가 어느 트리에서 도는지."""
    for w in words:
        if w.startswith("/") and os.path.basename(w) in BUILD_SCRIPT_NAMES:
            return os.path.dirname(w), "script"
    for opt in ("--tree", "-C", "--manifest-path"):
        for i, w in enumerate(words):
            if w == opt and i + 1 < len(words):
                p = resolve_dir(words[i + 1], cwd)
                if opt == "--manifest-path":
                    p = os.path.dirname(p)
                return p, opt
    return cwd, "cwd"


def scan(command, cwd):
    """(matched, tree) 목록. matched 는 build word, tree 는 그 명령의 트리."""
    hits = []

    def walk(segs, cur):
        for seg in segs:
            words = strip_prefixes(tokenize(seg))
            if not words:
                continue
            head = os.path.basename(words[0])
            if head in ("cd", "pushd"):
                target = None
                for w in words[1:]:
                    if not w.startswith("-"):
                        target = w
                        break
                cur = resolve_dir(target, cur) if target else os.path.expanduser("~")
                continue
            hit = build_hit(words)
            if hit:
                tree, _ = tree_hint(words, cur)
                hits.append((hit[0], tree))
            inner = shell_inner(words)
            if inner:
                walk(split_segments(inner), cur)

    walk(split_segments(command), os.path.abspath(cwd))
    return hits


def decide(command, cwd, cfg, mode, allowed):
    """(decision, matched, tree). decision 은 allow | warn | deny."""
    if mode == "off":
        return ("allow", None, None)
    bloomery_common = os.path.realpath(os.path.join(cfg["bloomery"], ".git"))
    guarded = []
    for matched, tree in scan(command, cwd):
        if common_dir(tree) != bloomery_common:
            continue
        if any(under(tree, a) for a in allowed):
            continue
        guarded.append((matched, tree))
    if not guarded:
        return ("allow", None, None)
    matched, tree = guarded[0]
    if mode == "warn":
        return ("warn", matched, tree)
    return ("deny", matched, tree)


def log_event(path, data, matched, tree, decision):
    rec = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session_id": data.get("session_id"),
        "agent_id": data.get("agent_id"),
        "agent_type": data.get("agent_type"),
        "cwd": data.get("cwd"),
        "tree": tree,
        "matched": matched,
        "decision": decision,
        "command": (data.get("tool_input") or {}).get("command"),
    }
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


DENY_MSG = ("verify 가드가 이 명령을 막았습니다: {matched}\n"
            "트리: {tree}\n"
            "이 트리에서 직접 빌드·게이트를 돌리지 마세요. "
            "`verify submit --phase fast` 로 요청을 내면 두 번째 맥의 검증 스테이션이 "
            "빌드하고 결과를 돌려줍니다.")


def run_hook(raw, cfg=None, mode=None, allowed=None):
    """(stdout, rc). deny 만 stdout 이 있다."""
    try:
        cfg = cfg or default_config()
        file_mode, file_allowed = read_config(cfg["config"])
        if mode is None:
            mode = cfg["mode"] if cfg["mode"] in ("off", "warn", "deny") else file_mode
        if allowed is None:
            allowed = [os.path.abspath(cfg["bloomery"])] + file_allowed
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return ("", 0)
        if data.get("hook_event_name") not in (None, "PreToolUse"):
            return ("", 0)
        if data.get("tool_name") not in (None, "Bash"):
            return ("", 0)
        command = (data.get("tool_input") or {}).get("command")
        if not isinstance(command, str) or not command.strip():
            return ("", 0)
        cwd = data.get("cwd") or os.getcwd()
        decision, matched, tree = decide(command, cwd, cfg, mode, allowed)
        if decision in ("warn", "deny"):
            log_event(cfg["log"], data, matched, tree, decision)
        if decision == "deny":
            out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": "deny",
                                          "permissionDecisionReason": DENY_MSG.format(
                                              matched=matched, tree=tree)}}
            return (json.dumps(out, ensure_ascii=False), 0)
        return ("", 0)
    except Exception as exc:  # 가드는 자기 때문에 일을 막지 않는다
        try:
            cfg = cfg or default_config()
            log_event(cfg["log"], {"session_id": None, "cwd": None,
                                   "tool_input": {"command": None}},
                      "guard-error: %s" % exc.__class__.__name__, None, "error")
        except Exception:
            pass
        return ("", 0)


def main(argv):
    if len(argv) > 1 and argv[1] == "--self-test":
        return selftest()
    raw = sys.stdin.buffer.read()
    out, rc = run_hook(raw)
    if out:
        sys.stdout.write(out + "\n")
    return rc


# 표 하나(cwd, 명령, 모드 → allow|warn|deny)를 한 드라이버로 돌린다.
# 환경변수와 임시 설정 파일만 쓴다(사용자의 설정 파일은 건드리지 않는다).

SELFTEST_ROWS = [
    ("{wt}", "cargo check", "deny", "deny"),
    ("{wt}", "cargo build --release", "deny", "deny"),
    ("{wt}", "cargo test -p bloomery-serve", "deny", "deny"),
    ("{wt}", "cargo clippy --workspace", "deny", "deny"),
    ("{wt}", "cargo +nightly-2026-08-28 check", "deny", "deny"),
    ("{wt}", "cargo fmt", "deny", "allow"),
    ("{wt}", "cargo metadata --no-deps", "deny", "allow"),
    ("{wt}", "cargo --version", "deny", "allow"),
    ("{wt}", "just mac-static", "deny", "deny"),
    ("{wt}", "just gate-smoke", "deny", "deny"),
    ("{wt}", "just check", "deny", "deny"),
    ("{wt}", "just lint", "deny", "deny"),
    ("{wt}", "just affected", "deny", "allow"),
    ("{wt}", "just mac-locks", "deny", "allow"),  # 읽기 전용 (원격 락과 슬롯을 본다)
    ("{wt}", "bash tools/check-recipes.sh", "deny", "deny"),
    ("{wt}", "bash tools/box.sh 'cargo check'", "deny", "deny"),
    ("{wt}", "{box}", "deny", "deny"),
    ("{plain}", "bash {box}", "deny", "deny"),
    ("{wt}", "python3 tools/static-sched.py", "deny", "deny"),
    ("{wt}", "python3 tools/recipes.py affected", "deny", "allow"),
    ("{wt}", "python3 tools/recipes.py --self-test", "deny", "deny"),
    ("{wt}", "bash tools/check-recipes.sh --self-test", "deny", "deny"),
    ("{wt}", "grep -r 'cargo build' crates", "deny", "allow"),
    ("{wt}", "echo 'cargo check'", "deny", "allow"),
    ("{wt}", "printf 'cargo test'", "deny", "allow"),
    ("{wt}", "sed -n 1p tools/box.sh", "deny", "allow"),
    ("{wt}", "git log --oneline -1", "deny", "allow"),
    ("{wt}", "git diff --stat", "deny", "allow"),
    ("{wt}", "bash -c 'cargo check'", "deny", "deny"),
    ("{wt}", "bash -lc 'cd {plain} && cargo check'", "deny", "allow"),
    ("{wt}", "cd {plain} && cargo check", "deny", "allow"),
    ("{wt}", "cd {wt2} && cargo check", "deny", "deny"),
    ("{wt}", "cd {wt} && cargo check", "deny", "deny"),
    ("{plain}", "cargo check", "deny", "allow"),
    ("{plain}", "cargo check", "warn", "allow"),
    ("{wt}", "cargo check", "warn", "warn"),
    ("{wt}", "cargo check", "off", "allow"),
    ("{main}", "cargo check", "deny", "allow"),
    ("{wt}", "verify submit --phase fast", "deny", "allow"),
    ("{wt}", "python3 tools/verify/verify status", "deny", "allow"),
    ("{wt}", "nice -n 5 cargo check", "deny", "deny"),
    ("{wt}", "timeout 300 cargo check", "deny", "deny"),
    ("{wt}", "env FOO=1 cargo check", "deny", "deny"),
    ("{wt}", "nohup cargo check > /tmp/x 2>&1 &", "deny", "deny"),
    ("{wt}", "cargo check | tee log", "deny", "deny"),
    ("{wt}", "echo $(cargo check)", "deny", "deny"),
    ("{wt}", "cd {plain}", "deny", "allow"),
    ("{wt}", "cargo check --manifest-path {wt}/crates/serve/Cargo.toml", "deny", "deny"),
    ("{wt}", "bash tools/mac-check.sh check", "deny", "deny"),
    ("{wt}", "bash tools/mac-static.sh --native", "deny", "deny"),
    ("{wt}", "cargo test -p bloomery-serve -- --nocapture", "deny", "deny"),
    ("{wt2}", "cargo check", "deny", "deny"),
]


def _log_lines(path):
    try:
        with open(path) as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def selftest():
    import shutil
    import tempfile

    bad = []
    tmp = tempfile.mkdtemp(prefix="verify-guard-selftest-")
    saved = {k: os.environ.get(k) for k in
             ("VERIFY_GUARD_MODE", "VERIFY_GUARD_BLOOMERY", "VERIFY_GUARD_CONFIG", "VERIFY_GUARD_LOG")}
    try:
        main_tree = os.path.join(tmp, "bloomery")
        os.makedirs(os.path.join(main_tree, ".git", "worktrees"))
        paths = {"main": main_tree}
        for name in ("wt", "wt2"):
            d = os.path.join(tmp, name)
            os.makedirs(d)
            with open(os.path.join(d, ".git"), "w") as fh:
                fh.write("gitdir: %s\n" % os.path.join(main_tree, ".git", "worktrees", name))
            paths[name] = d
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        paths["plain"] = plain
        tools = os.path.join(paths["wt"], "tools")
        os.makedirs(tools)
        for s in ("box.sh", "mac-check.sh", "mac-static.sh", "check-recipes.sh", "recipes.py",
                  "gate-batch.sh", "static-sched.py"):
            with open(os.path.join(tools, s), "w") as fh:
                fh.write("#!/bin/sh\n")
        paths["box"] = os.path.join(tools, "box.sh")
        cfgfile = os.path.join(tmp, "verify-guard")
        with open(cfgfile, "w") as fh:
            fh.write("mode warn\n")
        log = os.path.join(tmp, "guard.log")
        os.environ["VERIFY_GUARD_BLOOMERY"] = main_tree
        os.environ["VERIFY_GUARD_CONFIG"] = cfgfile
        os.environ["VERIFY_GUARD_LOG"] = log

        def run(cwd, command, mode):
            os.environ["VERIFY_GUARD_MODE"] = mode
            data = {"session_id": "selftest", "cwd": cwd, "hook_event_name": "PreToolUse",
                    "tool_name": "Bash", "tool_input": {"command": command},
                    "agent_id": "agent-1", "agent_type": "round"}
            before = _log_lines(log)
            out, rc = run_hook(json.dumps(data).encode())
            grew = _log_lines(log) > before
            if out:
                got = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
            elif grew:
                got = "warn"
            else:
                got = "allow"
            return got, out, rc

        for cwd, command, mode, want in SELFTEST_ROWS:
            got, out, rc = run(cwd.format(**paths), command.format(**paths), mode)
            if got != want:
                bad.append("row %r mode %s: got %s want %s" % (command, mode, got, want))
            if rc != 0:
                bad.append("row %r: rc %s" % (command, rc))
            if want == "deny" and not out:
                bad.append("row %r: deny 인데 출력이 없다" % command)
            if want == "allow" and out:
                bad.append("row %r: allow 인데 출력이 있다" % command)

        # 설정 파일의 allow 줄: 허용된 트리는 절대 막히지 않는다.
        with open(cfgfile, "w") as fh:
            fh.write("mode deny\nallow %s\n" % paths["wt2"])
        os.environ["VERIFY_GUARD_MODE"] = ""
        got, out, _ = run(paths["wt2"], "cargo check", "")
        if got != "allow":
            bad.append("설정 파일의 allow: got %s want allow" % got)
        got, out, _ = run(paths["wt"], "cargo check", "")
        if got != "deny":
            bad.append("설정 파일의 mode deny: got %s want deny" % got)
        # 로그에 한 줄이 남는다.
        if _log_lines(log) < 1:
            bad.append("guard.log 에 줄이 없다")

        # 파싱 불가한 입력은 allow 다.
        out, rc = run_hook(b"not json at all")
        if out or rc != 0:
            bad.append("파싱 불가 입력: out %r rc %s (allow 여야 한다)" % (out, rc))
        # 다른 도구는 건드리지 않는다.
        out, rc = run_hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Read",
                                       "tool_input": {}}).encode())
        if out or rc != 0:
            bad.append("Read 도구: out %r rc %s" % (out, rc))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    if bad:
        for line in bad:
            sys.stderr.write("guard-hook self-test FAIL: %s\n" % line)
        sys.stderr.write("guard-hook: self-test %d failed\n" % len(bad))
        return 1
    print("guard-hook: self-test ok (%d rows)" % len(SELFTEST_ROWS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
