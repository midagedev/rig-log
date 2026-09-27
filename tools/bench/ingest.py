#!/usr/bin/env python3
"""Append one bloomery depth-runner log to the bench ledger (data/bloomery-bench.tsv).

    ingest.py <log> --window W --anchor log/YYYY-MM-DD.md#slug --date YYYY-MM-DD
              --bloomery-tree PATH (--status status.log [--section NAME] | --bloomery-commit SHA)
              [--provisional REASON] [--lower-bound ARM:REASON]... [--exclude-row ARM:METRIC:SIZE:ROUND:REASON]...
              [--replace-window W] [--ledger PATH] [--root DIR] [--dry-run]
    ingest.py --self-test

It reads the three runners' format (bloomery tools/ref/depth-ds41.sh, depth-qwen3moe.sh,
depth-glm5next.sh): the ROW / DISCARD / WARMUP / FAIL lines, the `[config]`, `[lease]` and
`[binary]` lines and the witness block's tree and timing-card lines. One ledger row per (arm,
metric, size): `value` is the mean over the rounds no runner tag marks ([cold], [cpu-busy],
[other-busy]) and over all rounds when none is clean (then `tags` says `no-clean-round`). A
decode row of our engine also gives a prompt row at its depth when the depth is at least 128
and the row's `pp_tok/s` counts that many ids.

Nothing is guessed. The bloomery commit comes from the sitting's status.log (`head=` of the last
`plan:` line before the section's `rc=` line) or from --bloomery-commit, and either way the
commit's copy of the log's lease card must hash to the `[lease] card:` sha256. A status other
than `clean` and its reason come only from this command line. A log already in the ledger (same
sha256) is refused, and so is a window already in the ledger unless --replace-window names it: then
that window's rows are removed and the new rows take their place. Every field it cannot read is a
BenchError naming the field.
"""
import argparse
import datetime
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (BLOOMERY, FAIL, LEDGER, BenchError, assert_public, model_of, read_table,  # noqa: E402
                    repo_root, section, write_table)

RUNNERS = ("depth-ds41.sh", "depth-qwen3moe.sh", "depth-glm5next.sh")
HEAD = re.compile(r"^(ROW|DISCARD|WARMUP|FAIL) r(\d+) (\S+) ([dp])=(\d+)\b(.*)$")
DECODE = re.compile(r"\| tok/s(?:\(mean\))? ([0-9.]+) @ n=\d+, depth (\d+), (\S+) \|")
PROMPT = re.compile(r"\| tok/s\(pp\) ([0-9.]+) @ n=0, prompt (\d+), (\S+) \|")
OURS_PP = re.compile(r"\| pp_tok/s ([0-9.]+) \(n=(\d+), passes=\d+(?:, kind=(\w+))?\)")
TAG = re.compile(r" \[(cold|cpu-busy|other-busy)\b[^\]]*\]")
ANY_TAG = re.compile(r" \[([a-z][a-z-]*)\b[^\]]*\]\s*$")
TREE = re.compile(r"^    ([a-z0-9]+): .*?(\S+) sha256=([0-9a-f]+) head=(\S+) dirty_files=(\S+)")
MIN_PROMPT = 128


def basename_tokens(text):
    """Every whitespace token that is a path keeps only its last component (a `key=/a/b` token
    keeps its key: `key=b`)."""
    out = []
    for t in text.split(" "):
        if "/" in t:
            key = t.split("=", 1)[0] + "=" if "=" in t.split("/", 1)[0] else ""
            t = key + t.rstrip("/").rsplit("/", 1)[-1]
        out.append(t)
    return " ".join(out)


def tree_base(path):
    parts = path.split("/")[:-1]
    while parts and parts[-1] in ("bin", "build", "release", "debug", "target", "eval"):
        parts.pop()
    if not parts:
        raise BenchError(f"tree line: no tree directory in {path!r}")
    return parts[-1]


class Log:
    def __init__(self, path, text):
        self.path, self.name = path, os.path.basename(path)
        self.lines = text.split("\n")
        first = self.lines[0] if self.lines else ""
        found = [r for r in RUNNERS if f"tools/ref/{r}" in first]
        if len(found) != 1:
            raise BenchError(f"{self.name}: line 1 names no single runner of {RUNNERS}")
        self.runner = found[0]
        self.config = [ln for ln in self.lines if ln.startswith("[config] ")]
        self._model()
        self._card()
        self._lease()
        self._trees()
        self._arms()
        self._rows()

    def one(self, what, values):
        values = sorted(set(values))
        if len(values) != 1:
            raise BenchError(f"{self.name}: {what}: expected one value, found {values or 'none'}")
        return values[0]

    def _model(self):
        paths = [m.group(1) for ln in self.config for m in [re.match(r"\[config\] model=(\S+)", ln)] if m]
        self.file = os.path.basename(self.one("[config] model=", paths))
        self.model = model_of(self.file)

    def _card(self):
        cfg = [m.group(1) for ln in self.config for m in [re.search(r"\bcard=(\S+)", ln)] if m]
        self.card_token = self.one("[config] card=", cfg)
        names = [m.group(1) for ln in self.lines for m in [re.match(r"^\s+timing-card: ([^,]+),", ln)] if m]
        name = self.one("witness timing-card", names)
        name = re.sub(r"^NVIDIA ", "", name)
        name = re.sub(r"^GeForce ", "", name)
        if self.card_token not in name:
            raise BenchError(f"{self.name}: [config] card={self.card_token} is not the witness's card {name!r}")
        self.card = name

    def _lease(self):
        cards = [(m.group(1), m.group(2)) for ln in self.lines
                 for m in [re.match(r"^\[lease\] card: (docs/cards/\S+\.card) sha256=([0-9a-f]{64})$", ln)] if m]
        self.lease_card = self.one("[lease] card: <file> sha256=", cards)
        held = [m.group(1) for ln in self.lines for m in [re.match(r"^\[lease\] held by pid \d+ at (\S+)Z$", ln)] if m]
        t = datetime.datetime.fromisoformat(self.one("[lease] held … at", held))
        self.lease_dates = {t.date().isoformat(), (t + datetime.timedelta(hours=9)).date().isoformat()}
        bins = [(m.group(1), m.group(2)) for ln in self.lines
                for m in [re.match(r"^\[binary\] (\S+) sha256=([0-9a-f]+) ", ln)] if m]
        self.binary = self.one("[binary] <path> sha256=", bins) if bins else None
        self.stats = any(ln.startswith("stat summary") or " stat summary" in ln for ln in self.lines)

    def _trees(self):
        self.trees = {}
        for ln in self.lines:
            m = TREE.match(ln)
            if not m:
                continue
            key, path, sha, head, dirty = m.groups()
            build = head + ("" if dirty == "0" else f" dirty_files={dirty}") + f" ({tree_base(path)})"
            if self.trees.setdefault(key, build) != build:
                raise BenchError(f"{self.name}: tree line {key}: two builds ({self.trees[key]!r}, {build!r})")
        self.flags = {}
        for ln in self.config:
            for piece in ln[len("[config] "):].split(" | "):
                m = re.match(r"([a-z0-9]+):? (?:(.*?) )?flags=(.*)$", piece)
                if not m:
                    continue
                key, mid, fl = m.group(1), m.group(2) or "", m.group(3)
                fl = fl.split(" (", 1)[0]
                env = re.findall(r"env=(\S+)", mid)
                self.flags[key] = basename_tokens(" ".join(env + [fl]))
        ours = [m.group(2) for ln in self.config for m in [re.match(r"^\[config\] ours: (\S+) (.*)$", ln)] if m]
        # The hot list is the setup's (`hot=`), per arm; the shared config line names it for every arm.
        self.ours_flags = re.sub(r" ?\bhot=\S+", "", basename_tokens(ours[0])) if ours else None
        self.ours_cfg = ours[0] if ours else ""
        exl3 = [m.group(1) for ln in self.config for m in [re.match(r"^\[config\] exl3: (\S+)", ln)] if m]
        self.exl3_file = os.path.basename(exl3[0].rstrip("/")) if exl3 else None

    def _arms(self):
        spec = [m.group(1) for ln in self.config for m in [re.match(r"^\[config\] arms=(.*)$", ln)] if m]
        arms = self.one("[config] arms=", spec).split(" timing_gpu=", 1)[0].split()
        self.arms = []
        for a in arms:
            if "@" in a or a.startswith("bin:"):
                raise BenchError(f"{self.name}: arm {a!r} is a lever or a second binary, an A/B arm, not a bench row")
            label, _, size = a.rpartition(":")
            if not label:
                label, size = "ours", a
            if not size.isdigit():
                raise BenchError(f"{self.name}: arm {a!r}: no size after the colon")
            self.arms.append((label, int(size)))

    def _rows(self):
        self.rows, self.fails = [], []
        for i, ln in enumerate(self.lines, 1):
            if not re.match(r"^(ROW|DISCARD|WARMUP|FAIL) ", ln):
                continue
            m = HEAD.match(ln)
            if not m:
                raise BenchError(f"{self.name}:{i}: unreadable row line {ln[:80]!r}")
            kind, rnd, label, dp, size, rest = m.groups()
            rnd, size = int(rnd), int(size)
            if kind == "FAIL":
                rc = re.search(r"\brc=(\d+)", rest)
                self.fails.append(dict(label=label, metric="prompt" if dp == "p" else "decode", size=size,
                                       rnd=rnd, rc=rc.group(1) if rc else "?"))
                continue
            if kind != "ROW":
                continue
            tags = TAG.findall(rest)
            stray = ANY_TAG.search(re.sub(TAG, "", rest))
            if stray:
                raise BenchError(f"{self.name}:{i}: unknown row tag [{stray.group(1)}]")
            got = []
            if dp == "p":
                v = PROMPT.search(rest)
                if not v:
                    raise BenchError(f"{self.name}:{i}: prompt row without `tok/s(pp) … @ n=0, prompt P, <card> |`")
                got.append(("prompt", v, None))
            else:
                v = DECODE.search(rest)
                if not v:
                    raise BenchError(f"{self.name}:{i}: decode row without `tok/s … @ n=N, depth D, <card> |`")
                got.append(("decode", v, None))
                p = OURS_PP.search(rest)
                if p and int(p.group(2)) == size and size >= MIN_PROMPT:
                    got.append(("prompt", None, p))
            for metric, v, p in got:
                if v:
                    if int(v.group(2)) != size or v.group(3) != self.card_token:
                        raise BenchError(f"{self.name}:{i}: the row's `{v.group(2)}, {v.group(3)}` is not "
                                         f"{size}, {self.card_token}")
                    val = float(v.group(1))
                else:
                    val = float(p.group(1))
                self.rows.append(dict(label=label, metric=metric, size=size, rnd=rnd, val=val, tags=tags,
                                      feed=(p.group(3) or "unstated") if p else None, line=i, text=rest))
        planned = set()
        for label, size in self.arms:
            planned.add((label, size))
        for r in self.rows + self.fails:
            if (r["label"], r["size"]) not in planned:
                raise BenchError(f"{self.name}: row {r['label']} {r['metric']} {r['size']} belongs to no arm of "
                                 "[config] arms=")

    # --- what an arm is -------------------------------------------------------------------
    def engine(self, label):
        if label in ("ours", "hot", "prose", "code"):
            if label == "hot" and self.runner != "depth-glm5next.sh":
                raise BenchError(f"{self.name}: arm `hot` belongs to depth-glm5next.sh only")
            return BLOOMERY, None
        for prefix, eng in (("lcpp", "llama.cpp"), ("mrs", "mistral.rs"), ("exl3", "exllamav3"), ("ik", "ik_llama.cpp")):
            if label.startswith(prefix):
                keys = [k for k in self.trees if label.startswith(k) and k.startswith(prefix)]
                if not keys:
                    raise BenchError(f"{self.name}: arm {label}: no witness tree line `{prefix}…: <path> sha256= head=`")
                return eng, max(keys, key=len)
        raise BenchError(f"{self.name}: arm {label!r}: no engine this tool knows")

    def setup(self, label, tree):
        parts = []
        if tree is None:
            if self.runner == "depth-ds41.sh":
                plans = [m.groups() for ln in self.lines for m in [re.match(r"^\s+plan place=(\S+) .*\bhot_list=(\S+)", ln)] if m]
                place, hot = self.one("ours plan line (place=, hot_list=)", plans)
                parts = [f"prompt={'lcg' if label == 'ours' else label}", f"hot={os.path.basename(hot)}",
                         f"place={place}", f"stats={'on' if self.stats else 'off'}"]
            elif self.runner == "depth-qwen3moe.sh":
                if label != "ours":
                    raise BenchError(f"{self.name}: arm {label}: depth-qwen3moe.sh has no such bloomery arm")
                parts = ["prompt=lcg"]
            else:
                prose = re.search(r"\bprose=(\S+)", self.ours_cfg)
                place = re.search(r"--place (\S+)", self.ours_cfg)
                if not prose or not place:
                    raise BenchError(f"{self.name}: [config] ours: without prose= or --place")
                hot = "none"
                if label == "hot":
                    h = re.search(r"\bhot=(\S+)", self.ours_cfg)
                    if not h:
                        raise BenchError(f"{self.name}: arm hot: [config] ours: names no hot=")
                    hot = os.path.basename(h.group(1))
                parts = ["prompt=prose", f"hot={hot}", f"place={place.group(1)}"]
        else:
            if label.endswith("srv") or label.endswith("mtp"):
                if self.runner != "depth-glm5next.sh":
                    raise BenchError(f"{self.name}: server arm {label} outside depth-glm5next.sh")
                parts = ["prompt=prose"] + (["draft=mtp"] if label.endswith("mtp") else [])
            else:
                parts = ["prompt=engine"]
        return " ".join(parts)

    def arm_flags(self, label, tree, rows, metric):
        if tree is None:
            if self.ours_flags is None:
                raise BenchError(f"{self.name}: arm {label}: no `[config] ours:` line")
            fl = [self.ours_flags]
            if metric == "prompt":
                feeds = sorted({r["feed"] for r in rows})
                fl.append("feed=" + "/".join(feeds) if feeds else "feed=unstated")
            return "; ".join(fl)
        key = tree + ("fit" if "fit" in label[len(tree):] else "")
        if key not in self.flags:
            raise BenchError(f"{self.name}: arm {label}: no `[config] {key}` flags")
        fl = [self.flags[key]]
        m = re.fullmatch(r"lcpp(\d+)(.*)", label)
        if m and tree == "lcpp":
            fl.append(f"--n-cpu-moe {m.group(1)}")
        ubs = sorted({f"-ub {u.group(1)} -b {u.group(2)}" for r in rows for u in [re.search(r"\| ub (\d+) b (\d+)", r["text"])] if u})
        if not ubs:
            u = re.search(r"pp(?:fit)?(\d+)$", label)
            if u:
                ubs = [f"-ub {u.group(1)} -b {max(int(u.group(1)), 2048)} (from the arm's name)"]
        fl += ubs
        if label.endswith("srv") or label.endswith("mtp"):
            fl.append("llama-server /completion")
        return "; ".join(fl)

    def arm_file(self, eng):
        if eng == "exllamav3":
            if not self.exl3_file:
                raise BenchError(f"{self.name}: exllamav3 arm without `[config] exl3: <model dir>`")
            return self.exl3_file
        return self.file

    def build_check(self, label, tree, rows):
        for r in rows:
            b = re.search(r"\| build ([0-9a-f]{7,}) ", r["text"])
            if b:
                head = self.trees[tree].split(" ", 1)[0]
                if not (head.startswith(b.group(1)) or b.group(1).startswith(head)):
                    raise BenchError(f"{self.name}:{r['line']}: arm {label}: the row's build {b.group(1)} is not the "
                                     f"tree line's head {head}")


def bloomery_commit(log, args):
    if bool(args.status) == bool(args.bloomery_commit):
        raise BenchError("bloomery commit: give exactly one of --status (a sitting's status.log) and --bloomery-commit")
    if args.status:
        sec = args.section or os.path.splitext(log.name)[0]
        lines = open(args.status, encoding="utf-8").read().split("\n")
        rc = [i for i, ln in enumerate(lines) if re.match(rf"^\S+ {re.escape(sec)} rc=\d+$", ln)]
        if len(rc) != 1:
            raise BenchError(f"{args.status}: section {sec!r}: expected one `<time> {sec} rc=` line, found {len(rc)}")
        heads = [m.group(1) for ln in lines[:rc[0]] for m in [re.search(r" plan: .*\bhead=([0-9a-f]{7,})\b", ln)] if m]
        if not heads:
            raise BenchError(f"{args.status}: no `plan: … head=` line before `{sec} rc=`")
        commit = heads[-1]
    else:
        commit = args.bloomery_commit
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        raise BenchError(f"bloomery commit {commit!r} is not a hex commit")
    card, sha = log.lease_card
    try:
        blob = subprocess.run(["git", "-C", args.bloomery_tree, "show", f"{commit}:{card}"],
                              capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise BenchError(f"bloomery commit {commit}: `git show {commit}:{card}` in {args.bloomery_tree} failed ({e})")
    got = hashlib.sha256(blob).hexdigest()
    if got != sha:
        raise BenchError(f"bloomery commit {commit}: its {card} hashes to {got[:12]}, the log's lease card to {sha[:12]}")
    return commit


def build_rows(log, args, commit, source_sha):
    lower = {}
    for lb in args.lower_bound:
        arm, _, why = lb.partition(":")
        if not why:
            raise BenchError(f"--lower-bound {lb!r}: ARM:REASON")
        lower[arm] = why
    excluded = {}
    for ex in args.exclude_row:
        f = ex.split(":", 4)
        if len(f) != 5 or f[1] not in ("decode", "prompt") or not f[2].isdigit() or not f[3].isdigit() or not f[4]:
            raise BenchError(f"--exclude-row {ex!r}: ARM:decode|prompt:SIZE:ROUND:REASON")
        excluded[(f[0], f[1], int(f[2]), int(f[3]))] = f[4]
    labels = {a for a, _ in log.arms}
    for arm in lower:
        if arm not in labels:
            raise BenchError(f"--lower-bound {arm}: no such arm in {log.name} ({sorted(labels)})")
    used = set()
    out = []
    keys = []
    for label, size in log.arms:
        eng, _ = log.engine(label)
        metrics = ["decode", "prompt"] if eng == BLOOMERY else \
            ["prompt"] if "pp" in re.sub(r"^(lcpp|mrs|exl3|ik)", "", label) else ["decode"]
        for metric in metrics:
            if metric == "prompt" and eng == BLOOMERY and size < MIN_PROMPT:
                continue
            if (label, metric, size) not in keys:
                keys.append((label, metric, size))
    for label, metric, size in keys:
        eng, tree = log.engine(label)
        rows = [r for r in log.rows if (r["label"], r["metric"], r["size"]) == (label, metric, size)]
        fails = [f for f in log.fails if (f["label"], f["metric"], f["size"]) == (label, metric, size)]
        if tree:
            log.build_check(label, tree, rows)
        tags, notes, excl_reasons = [], [], []
        for r in rows:
            k = (label, metric, size, r["rnd"])
            if k in excluded:
                r["tags"] = r["tags"] + ["excluded"]
                tags_x = f"excluded r{r['rnd']}"
                notes.append(tags_x)
                excl_reasons.append(f"{tags_x}: {excluded[k]}")
                used.add(k)
        if rows:
            clean = [r["val"] for r in rows if not r["tags"]]
            vals = clean or [r["val"] for r in rows]
            value = f"{sum(vals) / len(vals):.3f}"
            for t in sorted({t for r in rows for t in r["tags"]} - {"excluded"}):
                tags.append(f"{t} {sum(t in r['tags'] for r in rows)}/{len(rows)}")
            if not clean:
                tags.append("no-clean-round")
            rounds, nclean = len(rows), len(clean)
        else:
            value, nclean = FAIL, 0
            rounds = len([f for f in fails if f["rnd"] >= 1])
            if not fails:
                tags.append("no-row")
        if fails:
            rcs = sorted({f["rc"] for f in fails})
            tags.append("fail " + ",".join(f"r{f['rnd']}" for f in fails) + " rc=" + "/".join(rcs))
        tags += notes
        status, reason = "clean", []
        if args.provisional:
            status = "provisional"
            reason.append(args.provisional)
        if label in lower:
            status = "lower-bound"
            reason.insert(0, lower[label])
        reason += excl_reasons
        out.append(dict(
            date=args.date, window=args.window, anchor=args.anchor, source=log.name, source_sha256=source_sha,
            model=log.model, file=log.arm_file(eng), card=log.card, setup=log.setup(label, tree),
            arm=label, engine=eng,
            engine_build=log.trees[tree] if tree else ours_build(log, label),
            flags=log.arm_flags(label, tree, rows, metric), metric=metric, size=str(size), value=value,
            rounds=str(rounds), clean_rounds=str(nclean), tags="; ".join(tags) or "-",
            status=status, status_reason="; ".join(reason) or "-", bloomery_commit=commit))
    left = set(excluded) - used
    if left:
        raise BenchError(f"--exclude-row: no such ROW in {log.name}: {sorted(left)}")
    for r in out:
        for k, v in r.items():
            assert_public(f"{log.name} {r['arm']} {k}", str(v))
    return out


def ours_build(log, label):
    if not log.binary:
        raise BenchError(f"{log.name}: arm {label}: no `[binary] <path> sha256=` line for our engine's build")
    return f"{os.path.basename(log.binary[0])} {log.binary[1]}"


def ingest(args):
    root = args.root or repo_root()
    ledger = args.ledger or os.path.join(root, LEDGER)
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", args.date or ""):
        raise BenchError(f"--date {args.date!r} is not YYYY-MM-DD")
    for opt in ("window", "anchor", "bloomery_tree"):
        if not getattr(args, opt):
            raise BenchError(f"--{opt.replace('_', '-')} is required")
    section(root, args.anchor)
    raw = open(args.log, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()[:16]
    have = read_table(ledger) if os.path.exists(ledger) and os.path.getsize(ledger) else []
    at = None
    if args.replace_window:
        if args.replace_window != args.window:
            raise BenchError(f"--replace-window {args.replace_window} is not --window {args.window}")
        idx = [i for i, r in enumerate(have) if r["window"] == args.window]
        if not idx:
            raise BenchError(f"--replace-window {args.window}: the window is not in the ledger")
        at = idx[0]
        have = [r for r in have if r["window"] != args.window]
    dup = [r for r in have if r["source_sha256"] == sha]
    if dup:
        raise BenchError(f"{args.log}: already in the ledger (sha256 {sha}, window {dup[0]['window']})")
    if any(r["window"] == args.window for r in have):
        raise BenchError(f"--window {args.window}: already in the ledger from another log")
    log = Log(args.log, raw.decode("utf-8", errors="replace"))
    if args.date not in log.lease_dates:
        raise BenchError(f"--date {args.date}: the lease was held on {sorted(log.lease_dates)} (UTC, KST)")
    commit = bloomery_commit(log, args)
    rows = build_rows(log, args, commit, sha)
    if args.dry_run:
        for r in rows:
            print("\t".join(f"{k}={v}" for k, v in r.items()))
        return rows
    if at is None:
        write_table(ledger, rows, append=True)
    else:
        write_table(ledger, have[:at] + rows + have[at:])
    print(f"ingest: {len(rows)} rows from {log.name} into {os.path.relpath(ledger, root)} (window {args.window}"
          + (", replaced)" if at is not None else ")"))
    return rows


def parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("log", nargs="?")
    p.add_argument("--window")
    p.add_argument("--anchor")
    p.add_argument("--date")
    p.add_argument("--provisional")
    p.add_argument("--lower-bound", action="append", default=[])
    p.add_argument("--exclude-row", action="append", default=[])
    p.add_argument("--status")
    p.add_argument("--section")
    p.add_argument("--bloomery-commit")
    p.add_argument("--bloomery-tree")
    p.add_argument("--replace-window")
    p.add_argument("--ledger")
    p.add_argument("--root")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p


# --- self-test ---------------------------------------------------------------------------------
CARD_TEXT = b"# a lease card\nkind = baseline\n"

SYNTH = """BLOOMERY_MODEL=deepseek41 ./tools/box.sh 'bash tools/ref/depth-ds41.sh 512 lcpp:512 lcpppp:512 lcppfit:512'
[lease] card: docs/cards/t.card sha256={card}
[binary] target/release/generate_ds41 sha256=aaaaaaaaaaaa mtime=2026-09-27T19:19:25Z (newer than its sources: dep-info)
[lease] held by pid 1 at 2026-09-27T19:19:26Z
[config] model=/models/DeepSeek-V4.1-Flash-Q3_K_M/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf n=96 rounds=2 card=A6000
[config] ours: target/release/generate_ds41 (--place a, default ctx)
[config] lcpp: /home/user/llama.cpp-v41/build/bin/llama-bench flags=-ngl 999 --n-cpu-moe 33 -fa on (lcpp<K>: --n-cpu-moe K)
[config] lcppfit: /home/user/llama.cpp-v41/build/bin/llama-bench flags=-fa on -fitt 1024 (fit)
[config] arms=512 lcpp:512 lcpppp:512 lcppfit:512 timing_gpu=GPU-uuid-elided
--- witness pre
    timing-card: NVIDIA RTX A6000, 300.00 W, 2100 MHz
    lcpp: /home/user/llama.cpp-v41/build/bin/llama-bench sha256=1d2670921473 head=5210c7c5e dirty_files=0
    plan place=a card=A6000 ctx_max=32768 card_budget=none hot_list=none
ROW r1 ours d=512 n=96 | tok/s(mean) 29.80 @ n=96, depth 512, A6000 | place a | pp_tok/s 192.83 (n=512, passes=1, kind=batch) | wall 6s [cpu-busy]
ROW r2 ours d=512 n=96 | tok/s(mean) 29.36 @ n=96, depth 512, A6000 | place a | pp_tok/s 188.42 (n=512, passes=1, kind=batch) | wall 6s
ROW r1 lcpp d=512 n=96 | tok/s 20.00 @ n=96, depth 512, A6000 | build 5210c7c (40) | wall 1s [cold]
ROW r2 lcpp d=512 n=96 | tok/s 22.00 @ n=96, depth 512, A6000 | build 5210c7c (40) | wall 1s [cold]
ROW r1 lcpppp p=512 n=0 | tok/s(pp) 104.91 @ n=0, prompt 512, A6000 | ub 512 b 2048 (llama-bench defaults) | build 5210c7c (40) | wall 2s
FAIL r1 lcppfit d=512 n=96 rc=1 | the fit failed
FAIL r2 lcppfit d=512 n=96 rc=1 | the fit failed
"""
STATUS = """2026-09-28T04:17:39+0900 plan: t(1) = 1 min [derived], budget 2 min, head={old}
2026-09-28T04:17:40+0900 plan: t(1) = 1 min [derived], budget 2 min, head={head}
2026-09-28T04:17:44+0900 lease: free
2026-09-28T04:45:35+0900 t rc=0
"""


def self_test():
    tmp = tempfile.mkdtemp(prefix="bench-ingest-")
    try:
        return _self_test(tmp)
    finally:
        shutil.rmtree(tmp)


def _self_test(tmp):
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C"]
    tree = os.path.join(tmp, "bloomery")
    os.makedirs(os.path.join(tree, "docs/cards"))
    subprocess.run(["git", "init", "-q", tree], check=True)
    open(os.path.join(tree, "docs/cards/t.card"), "wb").write(b"# an older card\n")
    subprocess.run(git + [tree, "add", "."], check=True)
    subprocess.run(git + [tree, "commit", "-qm", "old"], check=True)
    old = subprocess.run(git + [tree, "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True).stdout.strip()
    open(os.path.join(tree, "docs/cards/t.card"), "wb").write(CARD_TEXT)
    subprocess.run(git + [tree, "commit", "-qam", "card"], check=True)
    head = subprocess.run(git + [tree, "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True).stdout.strip()
    root = os.path.join(tmp, "rig")
    os.makedirs(os.path.join(root, "log"))
    os.makedirs(os.path.join(root, "data"))
    open(os.path.join(root, "log/2026-09-28.md"), "w").write('<a name="t-release"></a>\n## t\n')
    good = SYNTH.format(card=hashlib.sha256(CARD_TEXT).hexdigest())

    def run(text, status=STATUS.format(old=old, head=head), extra=(), fresh=True, name="t.log", window="2026-09-28/t"):
        if fresh and os.path.exists(os.path.join(root, LEDGER)):
            os.remove(os.path.join(root, LEDGER))
        lp = os.path.join(tmp, name)
        open(lp, "w").write(text)
        sp = os.path.join(tmp, "status.log")
        open(sp, "w").write(status)
        argv = [lp, "--window", window, "--anchor", "log/2026-09-28.md#t-release", "--date", "2026-09-28",
                "--bloomery-tree", tree, "--status", sp, "--root", root] + list(extra)
        a = parser().parse_args(argv)
        return ingest(a)

    bad = 0
    try:
        rows = run(good)
    except BenchError as e:
        print(f"SELF-TEST BROKEN: the synthetic log does not ingest: {e}")
        return 1
    got = {(r["arm"], r["metric"]): r for r in rows}
    expect = {
        ("ours", "decode"): ("29.360", "2", "1", "cpu-busy 1/2", "clean"),
        ("ours", "prompt"): ("188.420", "2", "1", "cpu-busy 1/2", "clean"),
        ("lcpp", "decode"): ("21.000", "2", "0", "cold 2/2; no-clean-round", "clean"),
        ("lcpppp", "prompt"): ("104.910", "1", "1", "-", "clean"),
        ("lcppfit", "decode"): (FAIL, "2", "0", "fail r1,r2 rc=1", "clean"),
    }
    for k, want in expect.items():
        r = got.get(k)
        have = r and (r["value"], r["rounds"], r["clean_rounds"], r["tags"], r["status"])
        if have != want:
            print(f"  WRONG — {k}: {have} != {want}")
            bad += 1
    if got[("ours", "decode")]["bloomery_commit"] != head:
        print(f"  WRONG — the commit is not the last plan head {head}")
        bad += 1
    if got[("ours", "decode")]["setup"] != "prompt=lcg hot=none place=a stats=off":
        print(f"  WRONG — setup {got[('ours', 'decode')]['setup']!r}")
        bad += 1
    if "--n-cpu-moe 33" not in got[("lcpp", "decode")]["flags"] or got[("lcpp", "decode")]["engine_build"] != "5210c7c5e (llama.cpp-v41)":
        print(f"  WRONG — lcpp flags/build {got[('lcpp', 'decode')]['flags']!r} {got[('lcpp', 'decode')]['engine_build']!r}")
        bad += 1
    print(f"self-test: the synthetic log ingests to {len(rows)} rows with the expected values")
    # the same log twice is refused
    try:
        run(good, fresh=False)
        print("  NOT CAUGHT — the same log ingested twice")
        bad += 1
    except BenchError as e:
        print(f"  FAIL as required — ingested twice: {e}")
    card_sha = hashlib.sha256(CARD_TEXT).hexdigest()
    mangles = [
        ("no [lease] card line", good.replace(f"[lease] card: docs/cards/t.card sha256={card_sha}\n", ""), (), "[lease] card"),
        ("the card is not the commit's", good.replace(card_sha, "0" * 64), (), "hashes to"),
        ("no [config] card=", good.replace(" card=A6000\n", "\n"), (), "card="),
        ("a row on another card", good.replace("depth 512, A6000 | build", "depth 512, 3090 | build", 1), (), "is not 512, A6000"),
        ("the row's build is not the tree's", good.replace("build 5210c7c (40) | wall 1s [cold]\nROW r2", "build 1234567 (40) | wall 1s [cold]\nROW r2"), (), "not the tree line's head"),
        ("no [binary] line", good.replace("[binary] target/release/generate_ds41 sha256=aaaaaaaaaaaa mtime", "[bin] x mtime"), (), "[binary]"),
        ("an unknown arm", good.replace("lcppfit", "zzzfit"), (), "no engine"),
        ("a lever arm", good.replace("arms=512 ", "arms=512 512@BLOOMERY_X=1 "), (), "lever"),
        ("an unknown row tag", good.replace("wall 6s\n", "wall 6s [hot]\n", 1), (), "unknown row tag"),
        ("an unreadable row", good.replace("ROW r2 ours d=512", "ROW r2 ours x=512"), (), "unreadable"),
        ("a row outside arms=", good + "ROW r1 ours d=6 n=96 | tok/s(mean) 29.10 @ n=96, depth 6, A6000 | wall 4s\n", (), "no arm"),
        ("no plan line for ours", good.replace("    plan place=a", "    nplan place=a"), (), "plan line"),
        ("the date is not the lease's", good.replace("at 2026-09-27T19:19:26Z", "at 2026-09-20T19:19:26Z"), (), "--date"),
        ("--lower-bound on an arm the log lacks", good, ("--lower-bound", "hot:warm rows"), "no such arm"),
        ("--exclude-row on a row the log lacks", good, ("--exclude-row", "ours:decode:512:3:cold"), "no such ROW"),
        ("a private address in a flag", good.replace("(--place a, default ctx)", "--host " + ".".join(["192", "168", "0", "9"])), (), "private"),
    ]
    for name, text, extra, needle in mangles:
        if text == good and not extra:
            print(f"  ?? {name}: the mangle changed nothing")
            bad += 1
            continue
        try:
            run(text, extra=extra)
            print(f"  NOT CAUGHT — {name}")
            bad += 1
        except BenchError as e:
            if needle in str(e):
                print(f"  FAIL as required — {name}: {e}")
            else:
                print(f"  CAUGHT FOR ANOTHER REASON — {name}: {e}")
                bad += 1
    try:
        run(good, status=STATUS.format(old=old, head=head).replace(" t rc=0", " u rc=0"))
        print("  NOT CAUGHT — status.log without the section's rc line")
        bad += 1
    except BenchError as e:
        print(f"  FAIL as required — status.log without the section's rc line: {e}")
    try:
        run(good, status=STATUS.format(old=head, head=old))
        print("  NOT CAUGHT — the last plan head is a commit whose card differs")
        bad += 1
    except BenchError as e:
        print(f"  FAIL as required — the last plan head's card differs: {e}")
    # an excluded row and a status from the command line
    rows = run(good, extra=("--exclude-row", "ours:decode:512:2:cold PLE rows", "--provisional", "cold refs"))
    r = [x for x in rows if (x["arm"], x["metric"]) == ("ours", "decode")][0]
    if (r["value"], r["clean_rounds"], r["status"], r["status_reason"]) != \
            ("29.580", "0", "provisional", "cold refs; excluded r2: cold PLE rows") or "excluded r2" not in r["tags"]:
        print(f"  WRONG — --exclude-row/--provisional: {r['value']} {r['clean_rounds']} {r['status']} {r['tags']}")
        bad += 1
    else:
        print("self-test: --exclude-row and --provisional land in the row")
    bad += replace_window_cases(run, good, root)
    print("self-test:", "all mangles caught" if not bad else f"{bad} not caught")
    return 1 if bad else 0


def replace_window_cases(run, good, root):
    """--replace-window: a corrected log replaces its window's rows where they stood, and only then."""
    bad = 0
    ledger = os.path.join(root, LEDGER)
    fixed = good.replace("tok/s(mean) 29.36", "tok/s(mean) 29.26")
    T = ("--section", "t")
    try:
        run(good)
        run(good.replace("tok/s 20.00", "tok/s 20.10"), fresh=False, name="u.log", window="2026-09-28/u", extra=T)
        before = read_table(ledger)
        try:
            run(fixed, fresh=False, name="t2.log", extra=T)
            print("  NOT CAUGHT — a corrected log ingested into its window without --replace-window")
            bad += 1
        except BenchError as e:
            print(f"  FAIL as required — a corrected log without --replace-window: {e}")
        for name, window, extra, needle in (
                ("--replace-window names a window not in the ledger", "2026-09-28/v", ("--replace-window", "2026-09-28/v"),
                 "not in the ledger"),
                ("--replace-window names another window than --window", "2026-09-28/t", ("--replace-window", "2026-09-28/u"),
                 "is not --window")):
            try:
                run(fixed, fresh=False, name="t2.log", window=window, extra=extra + T)
                print(f"  NOT CAUGHT — {name}")
                bad += 1
            except BenchError as e:
                ok = needle in str(e)
                print(f"  {'FAIL as required' if ok else 'CAUGHT FOR ANOTHER REASON'} — {name}: {e}")
                bad += not ok
        if read_table(ledger) != before:
            print("  WRONG — a refused --replace-window changed the ledger")
            bad += 1
        run(fixed, fresh=False, name="t2.log", extra=("--replace-window", "2026-09-28/t") + T)
        after = read_table(ledger)
        windows = [r["window"] for r in after]
        ours = [r for r in after if (r["window"], r["arm"], r["metric"]) == ("2026-09-28/t", "ours", "decode")]
        if len(after) != len(before) or windows != [r["window"] for r in before] \
                or [r for r in after if r["window"] == "2026-09-28/u"] != [r for r in before if r["window"] == "2026-09-28/u"] \
                or len(ours) != 1 or ours[0]["value"] != "29.260":
            print(f"  WRONG — --replace-window: {len(before)} -> {len(after)} rows, ours decode {[r['value'] for r in ours]}")
            bad += 1
        else:
            print("self-test: --replace-window replaced the window's rows in place and left the other window as it was")
    except (BenchError, SystemExit) as e:
        print(f"  WRONG — --replace-window: {e!r}")
        bad += 1
    return bad


def main():
    a = parser().parse_args()
    if a.self_test:
        return self_test()
    if not a.log:
        parser().error("give a log, or --self-test")
    try:
        ingest(a)
    except BenchError as e:
        print(f"ingest.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
