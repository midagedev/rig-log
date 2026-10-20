#!/usr/bin/env python3
"""boxres: the one command for the box's resource ledger, for people and scripts. It is a client of
signalbox (client.py: POST /grants, DELETE /grants/<id>, GET /ledger) and owns no state.

    boxres status [--json]
        the ledger: RAM, cards, cpus, nvme, the leases, the class slices, the holders with their
        needs and measured use, the jobs that wait and why
    boxres why <job|grant|name>
        one holder, wait, ended grant or refusal with its holder and the numbers
    boxres run --class C [--holder N] [--card 3090] [--cpus 0-5 | --threads N] [--io nvme0:bulk|/models:bulk]
               [--need ram.anon=2G --need host_lock=1 ...] [--expected S] [--bound S] -- CMD...
        ask a grant, start CMD as a transient scope in the class slice with the grant's caps
        (MemoryHigh and MemoryMax from the grant's need, AllowedCPUs from its cpus), release the
        grant when CMD ends, and return CMD's rc. Class `tape` also writes the tape hold, so direct
        tools/box.sh calls wait at their guard, and defaults its cpus and nvme from the config
        (--threads N holds the cpus an N-worker host pool occupies, siblings included).
    boxres --self-test

Sizes are bytes, or a number with K M G T (decimal, like the plan prints) or KiB MiB GiB TiB.

Exit: CMD's own rc for run; 75 a refusal (it names its holder and the numbers), 64 usage, 66 not
there, 69 signalbox is unreachable, a slice or systemd-run is missing, or a hold cannot be written
(BOXRES_OFF=1 bypasses the ledger: one line says so, CMD runs as it would have), 78 the config.

Environment: BOXRES_CONFIG (/home/user/signalbox/box-resources.json), BOXRES_URL, BOXRES_HOLD_DIR
(/root, where bloomery's lease_guard looks for bloomery-<owner>-hold), BOXRES_SYSTEMD_RUN,
BOXRES_SYSTEMCTL. The command CMD runs with BOXRES_GRANT and BOXRES_CLASS set.

stdlib only, like signalbox.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (HERE, os.path.join(HERE, "..", "signalbox")):
    if os.path.exists(os.path.join(_d, "client.py")) and _d not in sys.path:
        sys.path.append(_d)
import client  # noqa: E402
import ledger  # noqa: E402

CONFIG = os.environ.get("BOXRES_CONFIG", "/home/user/signalbox/box-resources.json")
HOLD_DIR = os.environ.get("BOXRES_HOLD_DIR", "/root")
SYSTEMD_RUN = os.environ.get("BOXRES_SYSTEMD_RUN", "systemd-run")
SYSTEMCTL = os.environ.get("BOXRES_SYSTEMCTL", "systemctl")
OOM_ADJ = "/proc/self/oom_score_adj"
RC_USAGE, RC_NOT_THERE, RC_DOWN, RC_BUSY, RC_CONFIG = 64, 66, 69, 75, 78
FORWARD = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
UNITS = {"k": 10 ** 3, "m": 10 ** 6, "g": 10 ** 9, "t": 10 ** 12,
         "kib": 1 << 10, "mib": 1 << 20, "gib": 1 << 30, "tib": 1 << 40}


class Fail(Exception):
    """A named end: the message goes to stderr, rc is the exit code."""

    def __init__(self, msg, rc):
        super().__init__(msg)
        self.rc = rc


def parse_size(text):
    """Bytes of "2G", "99GB", "12GiB", "1.5g" or a plain number; a Fail 64 names the text."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*", text)
    unit = m.group(2).lower() if m else None
    if unit in ("", "b"):
        mult = 1
    elif unit in UNITS:                                   # g, gib
        mult = UNITS[unit]
    elif unit and unit.endswith("b") and unit[:-1] in ("k", "m", "g", "t"):    # gb
        mult = UNITS[unit[:-1]]
    else:
        raise Fail("boxres: %r is not a size (bytes, or a number with K M G T / KiB MiB GiB TiB)" % text,
                   RC_USAGE)
    return int(float(m.group(1)) * mult)


def proc_start(pid, proc="/proc"):
    """Field 22 of /proc/<pid>/stat, or None when the pid is not there. The command name may hold
    spaces and parentheses, so the fields are counted from the last ')'."""
    try:
        with open(os.path.join(proc, str(pid), "stat")) as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


class Box:
    """Everything boxres touches outside itself, in one place: tests replace the methods."""

    def __init__(self, env=None, out=None, err=None):
        self.env = os.environ if env is None else env
        self.out = sys.stdout if out is None else out
        self.err = sys.stderr if err is None else err
        self.config_path = self.env.get("BOXRES_CONFIG", CONFIG)
        self.hold_dir = self.env.get("BOXRES_HOLD_DIR", HOLD_DIR)
        self.systemd_run = self.env.get("BOXRES_SYSTEMD_RUN", SYSTEMD_RUN)
        self.systemctl = self.env.get("BOXRES_SYSTEMCTL", SYSTEMCTL)
        self.oom_path = OOM_ADJ

    def say(self, text):
        print(text, file=self.err, flush=True)

    def ask(self, method, path, body=None):
        """(status, object), or None when BOXRES_OFF=1 bypassed the ledger; Fail 69 when signalbox
        cannot be reached."""
        try:
            return client.ask(method, path, body, env=self.env, err=self.err)
        except client.Down as e:
            raise Fail(str(e), RC_DOWN)

    def config(self):
        try:
            return ledger.load_config(self.config_path)
        except ledger.ConfigError as e:
            missing = not os.path.exists(self.config_path)
            raise Fail("boxres: the resource config: %s" % e, RC_NOT_THERE if missing else RC_CONFIG)

    def slice_installed(self, name):
        """Is slice `name` a unit file here (systemd makes an implicit slice with no caps out of any
        name, so LoadState says nothing)? Fail 69 names it when not."""
        if not shutil.which(self.systemctl):
            raise Fail("boxres: cannot check slice %s: %s is not here" % (name, self.systemctl), RC_DOWN)
        for unit in ledger.slice_chain(name):      # boxres-round.slice is inside boxres.slice
            try:
                p = subprocess.run([self.systemctl, "show", unit, "-p", "FragmentPath"], capture_output=True,
                                   text=True, stdin=subprocess.DEVNULL, timeout=15, env=dict(self.env))
            except (OSError, subprocess.TimeoutExpired) as e:
                raise Fail("boxres: cannot ask %s about slice %s (%s)" % (self.systemctl, unit, e), RC_DOWN)
            path = p.stdout.partition("=")[2].strip()
            if p.returncode != 0 or not path:
                raise Fail("boxres: slice %s is not installed (systemctl show: %s)%s: without its unit file it is "
                           "an implicit slice with no caps; install it from configs/ (cp configs/%s "
                           "/etc/systemd/system/ && systemctl daemon-reload)"
                           % (unit, ("rc %d" % p.returncode) if p.returncode else "no FragmentPath",
                              "" if unit == name else ", and %s is inside it" % name, unit), RC_DOWN)

    def proc_start(self, pid):
        return proc_start(pid)

    def launch(self, argv, env, oom):
        """Start argv; `oom` is the oom_score_adj to give it before it execs, or None."""
        pre = None
        if oom is not None:
            path = self.oom_path

            def pre():
                with open(path, "w") as f:
                    f.write(str(oom))
        try:
            return subprocess.Popen(argv, env=env, preexec_fn=pre)
        except (OSError, subprocess.SubprocessError) as e:
            raise Fail("boxres: cannot start %s (%s)" % (argv[0], e), RC_DOWN)


# ---------------------------------------------------------------- status and why

def fmt_gb(n):
    return "-" if n is None else "%.2f GB" % (n / ledger.GB)


def fmt_mib(n):
    return "-" if n is None else ("%.1f GiB" % (n / 1024) if n >= 10240 else "%d MiB" % n)


def need_text(need, full=False):
    """A need on one line: RAM by page class in GB, host_lock, cards, cpus (a count, or the list
    when `full`), nvme drive modes."""
    ram = need.get("ram", {})
    parts = []
    if any(ram.values()):
        parts.append("ram " + " ".join("%s %.1fG" % (k, v / ledger.GB) for k, v in ram.items() if v))
    if need.get("host_lock"):
        parts.append("host_lock")
    if need.get("cards"):
        parts.append("cards " + ",".join(need["cards"]))
    cpus = need.get("cpus")
    if cpus:
        if isinstance(cpus, list):
            parts.append("cpus %s" % (ledger.fmt_cpus(cpus) if full else "%dc" % len(cpus)))
        else:
            parts.append("cpus %d" % cpus)           # a queued job's count
    if need.get("nvme"):
        parts.append("nvme " + ",".join("%s:%s" % kv for kv in need["nvme"].items()))
    return "; ".join(parts) or "no need declared"


def ncpus(text):
    """How many cpus a kernel-style list holds ("" is none)."""
    return len(ledger.parse_cpus(text)) if text else 0


def fmt_status(v):
    """The ledger as `boxres status` prints it."""
    ram, out = v["ram"], []
    if ram.get("blind"):
        out.append("ledger %s  MEMORY UNREADABLE: %s" % (v["at"], ram["blind"]))
    else:
        out.append("ledger %s  MemTotal %s - os %s - headroom %s = G %s   unowned %s   (snapshot %.1f s old)"
                   % (v["at"], fmt_gb(ram["mem_total"]), fmt_gb(ram["os_other"]), fmt_gb(ram["headroom"]),
                      fmt_gb(ram["g"]), fmt_gb(ram["unowned"]), v.get("snapshot_age_s", 0)))
    waiters = v.get("waiters", [])
    held_by = {}
    for r in v["holders"]:
        for c in r["need"].get("cards", []):
            held_by[c] = r
    out.append("%-13s %-11s %-11s %-11s %-11s %s" % ("resource", "capacity", "charged", "measured", "free", "waiters"))
    out.append("%-13s %-11s %-11s %-11s %-11s %d" % (
        "ram", fmt_gb(ram.get("g")), fmt_gb(ram["charged"]), fmt_gb(ram["measured"]), fmt_gb(ram.get("free")),
        sum(1 for w in waiters if "ram needs" in (w.get("why") or ""))))
    for card, c in sorted(v.get("cards", {}).items(), reverse=True):
        who = held_by.get(card)
        state = "" if c.get("state") == "ok" else "  %s: %s" % (c.get("state"), ", ".join(c.get("reasons", []))[:100])
        out.append("%-13s %-11s %-11s %-11s %-11s %d%s" % (
            "card." + card, "1", ("%s %s" % (who["class"], who["holder"])) if who else "-",
            fmt_mib(c.get("used_mib")), "0" if who or c.get("lane_busy") else "1",
            sum(1 for w in waiters if "card %s" % card in (w.get("why") or "") or "card.%s" % card in (w.get("why") or "")),
            state))
    cpu = v["cpu"]
    out.append("%-13s %-11s %-11s %-11s %-11s %d" % (
        "cpu", ncpus(cpu["all"]), ", ".join("%s:%dc" % (g, ncpus(c)) for g, c in cpu["exclusive"].items()) or "-", "-",
        "%dc" % ncpus(cpu["free"]), sum(1 for w in waiters if "cpus:" in (w.get("why") or ""))))
    if cpu["exclusive"]:
        out.append("  free cpus %s" % (cpu["free"] or "none"))
    for drive, row in sorted(v["nvme"].items()):
        out.append("%-13s lat: %-14s bulk: %s" % (drive, row["lat"] or "-", ",".join(row["bulk"]) or "-"))
    lease = v.get("lease", {})
    t = lease.get("timing") or {}
    out.append("timing lease  %s" % (("HELD by " + t["text"]) if t.get("state") == "held" else
                                     "cannot be tested" if t.get("state") == "unreadable" else "free"))
    bl = lease.get("box_lease")
    if bl:
        out.append("rig-log lease %s by pid %s (%s)" % ("HELD" if bl.get("live") else "stale, owner dead", bl.get("pid"), bl.get("reason")))
    for klass, sl in sorted(v.get("slices", {}).items()):
        if sl.get("running"):
            out.append("slice %-7s %s  %d procs  memory %s (high %s, max %s)  cpus %s" % (
                klass, sl["unit"], sl.get("procs") or 0, fmt_gb(sl.get("memory_current")),
                fmt_gb(sl.get("memory_high")), fmt_gb(sl.get("memory_max")), sl.get("cpus") or "-"))
        else:
            out.append("slice %-7s %s  no unit running" % (klass, sl["unit"]))
    out.append("holders")
    for r in v["holders"]:
        flag = "" if r.get("status", "ok") == "ok" else "  [%s: %s]" % (r["status"], r.get("status_why"))
        over = "  [over its need by %s]" % fmt_gb(r["over_by"]) if r.get("over") else ""
        out.append("  %-5s %-7s %-12s %-8s %s" % (r["id"], r["class"], r["holder"], r["state"], r.get("unit") or "-"))
        out.append("        %s" % need_text(r["need"]))
        out.append("        declared %s, measured %s, charged %s%s%s" % (
            fmt_gb(r["declared"]), fmt_gb(r["measured"]), fmt_gb(r["charge"]), over, flag))
    if not v["holders"]:
        out.append("  none")
    for h in v.get("holds", []):
        out.append("  hold %-24s %s%s" % (h["name"], h["state"], " (grant %s)" % h["grant"] if h.get("grant") else ""))
    out.append("waiters")
    for w in waiters:
        out.append("  %-8s %-7s %-22s card %-5s %s -- %s" % (
            w["id"], w["class"], w["name"], w["card"], need_text(w["need"]) if w.get("need") else "no need declared",
            w.get("why") or "starts at the next tick"))
    if not waiters:
        out.append("  none")
    out.append("recent decisions")
    for d in v.get("recent", [])[-8:]:
        out.append("  %s %-9s %s" % (d["at"][11:], d["kind"], d["text"]))
    if not v.get("recent"):
        out.append("  none")
    return "\n".join(out)


def explain(v, jobs, name):
    """The lines that answer `boxres why <name>`: every holder, waiter, ended grant, job or recent
    decision the name matches, each with its numbers. [] when nothing matches."""
    out = []
    for r in v["holders"]:
        if name in (r["id"], r["holder"], r.get("unit")):
            out.append("%s (%s, class %s, holder %s, owner %s) is %s since %s on %s" % (
                r["id"], r["kind"], r["class"], r["holder"], r.get("owner"), r["state"], r.get("since"), r.get("unit")))
            out.append("  need %s" % need_text(r["need"], full=True))
            out.append("  declared %s, measured %s, charged %s%s" % (
                fmt_gb(r["declared"]), fmt_gb(r["measured"]), fmt_gb(r["charge"]),
                ", over its need by %s" % fmt_gb(r["over_by"]) if r.get("over") else ""))
            if r.get("status", "ok") != "ok":
                out.append("  %s: %s" % (r["status"], r.get("status_why")))
            if r.get("text"):
                out.append("  owner: %s" % r["text"])
            if not v["ram"].get("blind"):
                out.append("  the ledger: free %s of cap %s (charged %s, unowned %s, headroom %s)" % (
                    fmt_gb(v["ram"]["free"]), fmt_gb(v["ram"]["g"]), fmt_gb(v["ram"]["charged"]),
                    fmt_gb(v["ram"]["unowned"]), fmt_gb(v["ram"]["headroom"])))
    for w in v.get("waiters", []):
        if name in (w["id"], w["name"]):
            out.append("%s (queued job, class %s, owner %s) waits on card %s: %s" % (
                w["id"], w["class"], w["owner"], w["card"], w.get("why") or "it starts at the next tick"))
            out.append("  need %s" % (need_text(w["need"], full=True) if w.get("need") else "none declared"))
    for e in v.get("ended", []):
        if name in (e["id"], e["holder"]):
            out.append("%s (class %s, holder %s) %s at %s: %s" % (
                e["id"], e["class"], e["holder"], e["state"], e.get("ended"), e.get("ended_why")))
    if jobs is not None and not out:
        out.append("%s (job, class %s) is %s on card %s%s" % (
            jobs["id"], jobs.get("job_class"), jobs["status"], jobs.get("resolved_card") or jobs.get("card"),
            (": " + jobs["wait_reason"]) if jobs.get("wait_reason") else
            ", rc %s" % jobs.get("rc") if jobs.get("rc") is not None else ""))
        if jobs.get("sentinel"):
            out.append("  %s" % jobs["sentinel"])
    hits = [d for d in v.get("recent", []) if name in d["text"]]
    if hits:
        out.append("decisions that name %s (newest last)" % name)
        out += ["  %s %-9s %s" % (d["at"][11:], d["kind"], d["text"]) for d in hits[-5:]]
    return out


def cmd_status(box, args):
    reply = box.ask("GET", "/ledger")
    if reply is None:
        return 0
    code, obj = reply
    if code != 200:
        raise Fail("boxres: GET /ledger answered %s: %s" % (code, obj.get("error", obj)), RC_DOWN)
    print(json.dumps(obj, indent=1, ensure_ascii=False) if args.json else fmt_status(obj), file=box.out)
    return 0


def cmd_why(box, args):
    reply = box.ask("GET", "/ledger?recent=200")
    if reply is None:
        return 0
    code, v = reply
    if code != 200:
        raise Fail("boxres: GET /ledger answered %s: %s" % (code, v.get("error", v)), RC_DOWN)
    job = None
    if re.fullmatch(r"[A-Za-z0-9._-]+", args.name):
        j = box.ask("GET", "/jobs/" + args.name)
        job = j[1] if j and j[0] == 200 else None
    lines = explain(v, job, args.name)
    if not lines:
        raise Fail("boxres: nothing in the ledger, the queue or the last decisions is named %r" % args.name,
                   RC_NOT_THERE)
    print("\n".join(lines), file=box.out)
    return 0


# ---------------------------------------------------------------- run

def build_need(cfg, args):
    """The grant's need from the flags, with the tape's defaults (cpus, nvme) from the config.
    A Fail 64 names a flag that cannot be read."""
    need, ram = {}, {}
    for item in args.need:
        key, eq, value = item.partition("=")
        if not eq:
            raise Fail("boxres: --need %r: use KEY=VALUE (ram.anon=2G, ram.locked=99G, host_lock=1, "
                       "churn_hosting=unhosted)" % item, RC_USAGE)
        if key.startswith("ram."):
            if key[4:] not in ledger.RAM_KEYS:
                raise Fail("boxres: --need %s: %s is not a page class (%s)" % (item, key[4:], ", ".join(ledger.RAM_KEYS)),
                           RC_USAGE)
            ram[key[4:]] = parse_size(value)
        elif key == "host_lock":
            if value not in ("0", "1", "true", "false"):
                raise Fail("boxres: --need host_lock must be 0, 1, true or false, got %r" % value, RC_USAGE)
            need["host_lock"] = value in ("1", "true")
        elif key == "churn_hosting":
            need["churn_hosting"] = value
        else:
            raise Fail("boxres: --need %s: the keys are ram.<class>, host_lock and churn_hosting; use --card, "
                       "--cpus and --io for the rest" % item, RC_USAGE)
    if ram:
        need["ram"] = ram
    if args.card:
        need["cards"] = list(args.card)
    nvme = {}
    for item in args.io:
        where, colon, mode = item.rpartition(":")
        if not colon or mode not in ledger.NVME_MODES:
            raise Fail("boxres: --io %r: use DRIVE:MODE or PATH:MODE with MODE one of %s" % (item, ledger.NVME_MODES),
                       RC_USAGE)
        drive = where
        if "/" in where:
            drive = cfg.drive_of(os.path.realpath(where))
            if drive is None:
                raise Fail("boxres: --io %s: %s is on no drive the config names (%s)"
                           % (item, os.path.realpath(where), ", ".join("%s %s" % kv for kv in cfg.nvme_mount.items())),
                           RC_USAGE)
        if drive not in cfg.nvme:
            raise Fail("boxres: --io %s: %r is not a drive (%s)" % (item, drive, ", ".join(cfg.nvme)), RC_USAGE)
        nvme[drive] = mode
    cpus = args.cpus
    if args.threads is not None:
        if args.klass != "tape" or args.cpus:
            raise Fail("boxres: --threads is for class tape and instead of --cpus: it holds the cpus an N-worker "
                       "pool occupies", RC_USAGE)
        if not cfg.topology:
            raise Fail("boxres: --threads needs cpus.ccds, cpus.cores_per_ccd and cpus.smt_offset in %s" % cfg.path, RC_CONFIG)
        try:
            cpus = ledger.fmt_cpus(ledger.pool_cpus(args.threads, **cfg.topology))
        except ValueError as e:
            raise Fail("boxres: --threads %d: %s" % (args.threads, e), RC_USAGE)
    if args.klass == "tape" and cfg.tape:
        cpus = cpus or ledger.fmt_cpus(cfg.tape["cpus"])
        for drive, mode in cfg.tape["nvme"].items():
            nvme.setdefault(drive, mode)
    if cpus:
        try:
            need["cpus"] = ledger.fmt_cpus(ledger.parse_cpus(cpus, "--cpus"))
        except ValueError as e:
            raise Fail("boxres: %s" % e, RC_USAGE)
    if nvme:
        need["nvme"] = nvme
    try:
        ledger.normalize_need(need, "grant")
    except ValueError as e:
        raise Fail("boxres: the need is not valid: %s" % e, RC_USAGE)
    return need


def hold_path(box, name):
    return os.path.join(box.hold_dir, "bloomery-%s-hold" % name)


def read_hold(path):
    try:
        with open(path) as f:
            return f.read(400).strip()
    except OSError:
        return None


def put_hold(box, name, holder, pid, start):
    """Write the hold file `name` (/root/bloomery-<name>-hold) with pid= and start= so a reader can
    tell its owner is gone. Exclusive: a hold that is up and whose owner runs is a Fail 75 that
    names it; a hold whose owner is dead is replaced and said. Returns (path, the text written)."""
    path = hold_path(box, name)
    text = "pid=%d start=%d holder=%s\n" % (pid, start, holder)
    for attempt in (0, 1):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            was = read_hold(path) or ""
            kv = dict(w.split("=", 1) for w in was.split() if "=" in w)
            owner_pid, owner_start = kv.get("pid", ""), kv.get("start", "")
            dead = owner_pid.isdigit() and owner_start.isdigit() and \
                box.proc_start(int(owner_pid)) != int(owner_start)
            if not dead or attempt:
                raise Fail("boxres: hold %s is up (%s): its owner is running or none is recorded, so it comes "
                           "down by its owner's hand; the run does not start under it" % (path, was or "empty"),
                       RC_BUSY)
            box.say("boxres: hold %s names a dead owner (%s): replaced" % (path, was))
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            continue
        except OSError as e:
            raise Fail("boxres: cannot write hold %s (%s)" % (path, e.strerror), RC_DOWN)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        return path, text
    raise Fail("boxres: hold %s keeps reappearing" % path, RC_BUSY)


def drop_hold(path, text):
    """Take the hold down if it is still the one we wrote."""
    if path and read_hold(path) == text.strip():
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def scope_argv(box, unit, unit_slice, grant, bound):
    """The systemd-run command line of the scope: caps from the grant's limits, cpus from its
    confine, the slice, RuntimeMaxSec when a bound was asked."""
    argv = [box.systemd_run, "--scope", "--quiet", "--collect", "--unit", unit]
    if unit_slice:
        argv += ["--slice", unit_slice]
    lim = grant.get("limits") or {}
    for key, prop in (("memory_high", "MemoryHigh"), ("memory_max", "MemoryMax")):
        if lim.get(key):
            argv += ["-p", "%s=%d" % (prop, lim[key])]
    cpus = (grant.get("confine") or {}).get("cpus")
    if cpus:
        argv += ["-p", "AllowedCPUs=" + cpus]
    if bound:
        argv += ["-p", "RuntimeMaxSec=%d" % bound]
    return argv


def cmd_run(box, args, cmd):
    cfg = box.config()
    if args.klass not in cfg.class_priority:
        raise Fail("boxres: --class %r is not a class (%s)" % (args.klass, ", ".join(sorted(cfg.class_priority))), RC_USAGE)
    if not cmd:
        raise Fail("boxres run: nothing to run: put the command after --", RC_USAGE)
    if box.env.get("BOXRES_OFF") == "1":
        box.ask("GET", "/ledger")      # prints the one bypass line and asks nothing
        return subprocess.call(cmd, env=dict(box.env))
    need = build_need(cfg, args)
    holder = args.holder or re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(cmd[0])) or args.klass
    if not ledger.NAME_RE.fullmatch(holder):
        raise Fail("boxres: --holder must be a name [A-Za-z0-9._-]+, got %r" % holder, RC_USAGE)
    unit_slice = cfg.slices.get(args.klass)
    if unit_slice:
        box.slice_installed(unit_slice)
    tape = cfg.tape if args.klass == "tape" else None
    if args.klass == "tape" and not tape:
        raise Fail("boxres: class tape needs the config's tape section (hold, threads, cpus)", RC_CONFIG)
    unit = "boxres-%s-%s-%d.scope" % (args.klass, holder, os.getpid())
    body = {"holder": holder, "class": args.klass, "owner": args.owner or holder, "need": need,
            "liveness": {"unit": unit}}
    if args.expected:
        body["expected_s"] = args.expected
    if args.bound:
        body["bound_s"] = args.bound
    hold = held_text = None
    me = os.getpid()
    try:
        if tape:
            start = box.proc_start(me)
            if start is None:
                raise Fail("boxres: cannot read this process's start time from /proc/%d/stat, which the hold "
                           "records" % me, RC_DOWN)
            hold, held_text = put_hold(box, tape["hold"], holder, me, start)
            body["hold"] = os.path.basename(hold)
        code, grant = box.ask("POST", "/grants", body)
        if code != 201:
            for line in (grant.get("refusals") or [grant.get("error", json.dumps(grant))]):
                box.say(line)
            raise Fail("boxres: %s (class %s) was not started" % (holder, args.klass), client.exit_code(code, grant))
        gid = grant["id"]
        box.say("boxres: admitted %s (class %s, holder %s): %s; unit %s%s" % (
            gid, args.klass, holder, need_text(grant["need"]), unit,
            " in %s" % unit_slice if unit_slice else ""))
        try:
            env = dict(box.env, BOXRES_GRANT=gid, BOXRES_CLASS=args.klass)
            if tape:
                env["BLOOMERY_HOLD_OWNER"] = tape["hold"]
            argv = scope_argv(box, unit, unit_slice, grant, args.bound) + ["--"] + cmd
            oom = tape["oom_score_adj"] if tape else None
            child = box.launch(argv, env, oom)
            return supervise(child)
        finally:
            released = None
            try:
                released = box.ask("DELETE", "/grants/" + gid)
            except Fail as e:
                box.say("%s -- grant %s is reclaimed by signalbox within a tick of its unit ending" % (e, gid))
            if released is not None and released[0] >= 300:
                box.say("boxres: releasing %s answered %s: %s" % (gid, released[0], released[1].get("error", released[1])))
    finally:
        drop_hold(hold, held_text)


def supervise(child):
    """Wait for the child; INT, TERM and HUP go to it (the pid we started, never a group). Its rc,
    or 128 + the signal that killed it."""
    def forward(signum, frame):
        try:
            child.send_signal(signum)
        except ProcessLookupError:
            pass
    old = {sig: signal.signal(sig, forward) for sig in FORWARD}
    try:
        rc = child.wait()
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
    return 128 - rc if rc < 0 else rc


# ---------------------------------------------------------------- main

def parser():
    ap = argparse.ArgumentParser(prog="boxres", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true", help="run the stubbed self-test and exit")
    sub = ap.add_subparsers(dest="cmd")
    st = sub.add_parser("status", help="print the ledger")
    st.add_argument("--json", action="store_true", help="the raw GET /ledger object")
    wy = sub.add_parser("why", help="one holder, wait, ended grant or decision with its numbers")
    wy.add_argument("name", help="a grant id (g12), a job id, a holder or job name, or a unit")
    rn = sub.add_parser("run", help="ask a grant, run CMD in the class slice, release at exit")
    rn.add_argument("--class", dest="klass", required=True)
    rn.add_argument("--holder", help="who is asking (default: the command's name)")
    rn.add_argument("--owner", help="the owner the ledger shows (default: the holder)")
    rn.add_argument("--card", action="append", default=[], help="a card the run holds (a6000, 3090); repeatable")
    rn.add_argument("--cpus", help="the cpus it holds exclusively, as a list: 0-5,8-13")
    rn.add_argument("--threads", type=int, help="class tape: hold the cpus an N-worker host pool occupies (default: the "
                                                "config's tape.threads)")
    rn.add_argument("--io", action="append", default=[], help="DRIVE:MODE or PATH:MODE, MODE bulk or lat; repeatable")
    rn.add_argument("--need", action="append", default=[], help="ram.<class>=SIZE, host_lock=1, churn_hosting=...")
    rn.add_argument("--expected", type=int, help="seconds it is expected to run (overdue past 2x)")
    rn.add_argument("--bound", type=int, help="seconds after which its unit is stopped (RuntimeMaxSec)")
    return ap


def main(argv, box=None):
    box = box or Box()
    cmd = []
    if "--" in argv:
        cut = argv.index("--")
        argv, cmd = argv[:cut], argv[cut + 1:]
    if "--self-test" in argv:
        return self_test()
    ap = parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return RC_USAGE if e.code else 0
    try:
        if args.cmd == "status":
            return cmd_status(box, args)
        if args.cmd == "why":
            return cmd_why(box, args)
        if args.cmd == "run":
            return cmd_run(box, args, cmd)
    except Fail as e:
        box.say(str(e))
        return e.rc
    ap.print_usage(box.err)
    return RC_USAGE


# ---------------------------------------------------------------- self-test

def self_test():
    """The commands against a stub client (canned replies, every request recorded) and a stub
    systemd-run (a script that logs its argv and execs the command after --), on temp files. No
    signalbox, systemd or box is touched."""
    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(here, "..", "..", "configs", "box-resources.json")
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(here, "box-resources.json")
    results = []

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print("%s %s%s" % ("ok  " if cond else "FAIL", name, "" if cond else " %s" % (detail,)), flush=True)

    tmp = tempfile.mkdtemp(prefix="boxres-selftest-")
    log = os.path.join(tmp, "systemd-run.log")
    stub = os.path.join(tmp, "systemd-run")
    with open(stub, "w") as f:
        f.write('#!/bin/bash\nprintf "%s\\n" "$*" >> ' + log + '\n'
                'while [ "$1" != "--" ]; do shift; done; shift\nexec "$@"\n')
    os.chmod(stub, 0o755)
    ctl = os.path.join(tmp, "systemctl")
    with open(ctl, "w") as f:         # FragmentPath is empty for any slice not in $SLICES_INSTALLED
        f.write('#!/bin/bash\nfor s in $SLICES_INSTALLED; do [ "$2" = "$s" ] && '
                'echo "FragmentPath=/etc/systemd/system/$s" && exit 0; done\necho "FragmentPath="\n')
    os.chmod(ctl, 0o755)
    hold_dir = os.path.join(tmp, "holds")
    os.makedirs(hold_dir)
    oom_file = os.path.join(tmp, "oom_score_adj")
    installed = "boxres.slice boxres-round.slice boxres-fill.slice rounds.slice"

    class Stub(Box):
        """A Box with a canned signalbox: `replies` maps "METHOD path" to (status, object) or to a
        callable; every request is kept in `calls`."""

        def __init__(self, replies, env=None):
            e = {"BOXRES_CONFIG": cfg_path, "BOXRES_HOLD_DIR": hold_dir, "BOXRES_SYSTEMD_RUN": stub,
                 "BOXRES_SYSTEMCTL": ctl, "SLICES_INSTALLED": installed, "PATH": os.environ["PATH"]}
            e.update(env or {})
            self.o, self.e = [], []
            super().__init__(env=e, out=_Sink(self.o), err=_Sink(self.e))
            self.oom_path = oom_file
            self.replies, self.calls = replies, []

        def ask(self, method, path, body=None):
            if self.env.get("BOXRES_OFF") == "1":
                self.say(client.BYPASS_LINE)
                return None
            self.calls.append((method, path, body))
            r = self.replies.get("%s %s" % (method, path)) or self.replies.get("%s %s" % (method, path.split("?")[0]))
            if r is None:
                raise Fail("boxres: the stub has no reply for %s %s" % (method, path), RC_DOWN)
            return r(body) if callable(r) else r

        def proc_start(self, pid):
            return self.starts.get(pid) if hasattr(self, "starts") else proc_start(pid)

        def text(self):
            return "".join(self.o), "".join(self.e)

    class _Sink:
        def __init__(self, into):
            self.into = into

        def write(self, s):
            self.into.append(s)

        def flush(self):
            pass

    def grant(body, **kw):
        g = {"id": "g1", "holder": body["holder"], "class": body["class"], "need": ledger.normalize_need(body["need"], "grant"),
             "state": "pending", "limits": {"memory_high": 2_200_000_000, "memory_max": 5_000_000_000}}
        g.update(kw)
        return 201, g

    def run(box, *argv):
        box.starts = {os.getpid(): 4242}
        return main(list(argv), box)

    def last_scope():
        with open(log) as f:
            return f.read().splitlines()[-1]

    # -- run: the grant, the scope, the rc, the release
    box = Stub({"POST /grants": grant, "DELETE /grants/g1": (200, {"state": "released"})})
    rc = run(box, "run", "--class", "fill", "--holder", "hf-x", "--io", "/models:bulk", "--need", "ram.anon=2G",
             "--bound", "600", "--", "bash", "-c", "exit 7")
    method, path, body = box.calls[0]
    line = last_scope()
    check("run: the command's own rc comes back (7), after one POST /grants and one DELETE /grants/g1",
          rc == 7 and [c[0] + " " + c[1] for c in box.calls] == ["POST /grants", "DELETE /grants/g1"], (rc, box.calls))
    check("run: the grant asks the class, a unit liveness, the need in bytes, the drive a path names and the bound",
          body["class"] == "fill" and body["liveness"]["unit"].startswith("boxres-fill-hf-x-")
          and body["liveness"]["unit"].endswith(".scope") and body["need"]["ram"] == {"anon": 2_000_000_000}
          and body["need"]["nvme"] == {"nvme0": "bulk"} and body["bound_s"] == 600, body)
    check("run: the scope starts in the class slice with the grant's caps and the bound, then `--` and the command",
          "--scope" in line and "--slice boxres-fill.slice" in line and "-p MemoryHigh=2200000000" in line
          and "-p MemoryMax=5000000000" in line and "-p RuntimeMaxSec=600" in line
          and line.endswith(" -- bash -c exit 7"), line)
    check("run: it says what was admitted on stderr, and nothing on stdout", "admitted g1" in box.text()[1]
          and box.text()[0] == "", box.text())

    # -- run: a refusal names its holder and is rc 75, nothing starts
    refusal = (409, {"error": "boxres: bulk (class fill) refused rc 75: nvme0 bulk is refused while a latency holder is up "
                              "-- held by g4 tape tape boxres-tape-tape-1.scope since 2026-10-20T15:00:00; unowned 1.00 GB; headroom 4.29 GB",
                     "rc": 75, "refusals": ["boxres: bulk (class fill) refused rc 75: nvme0 bulk is refused while a latency "
                                            "holder is up -- held by g4 tape tape"]})
    n_runs = len(open(log).read().splitlines())
    box = Stub({"POST /grants": refusal})
    rc = run(box, "run", "--class", "fill", "--io", "nvme0:bulk", "--", "true")
    check("run: a refusal is rc 75, prints the daemon's line that names the holder, starts nothing and releases nothing",
          rc == 75 and "held by g4 tape tape" in box.text()[1] and len(box.calls) == 1
          and len(open(log).read().splitlines()) == n_runs, (rc, box.text(), box.calls))

    # -- run: a broker that is down is 69, BOXRES_OFF=1 runs the command with one bypass line
    class Down(Stub):
        def ask(self, method, path, body=None):
            if self.env.get("BOXRES_OFF") == "1":
                return super().ask(method, path, body)
            raise Fail("boxres: signalbox is unreachable at http://127.0.0.1:8030 (refused); systemctl is-active "
                       "signalbox: failed; refused rc 69, nothing was admitted", RC_DOWN)
    box = Down({})
    rc = run(box, "run", "--class", "round", "--", "true")
    check("run: signalbox down is rc 69 and the command does not run", rc == 69 and "unreachable" in box.text()[1], (rc, box.text()))
    marker = os.path.join(tmp, "ran")
    box = Down({}, env={"BOXRES_OFF": "1"})
    rc = run(box, "run", "--class", "round", "--", "touch", marker)
    check("run: BOXRES_OFF=1 prints the bypass line and runs the command, with no grant and no scope",
          rc == 0 and os.path.exists(marker) and client.BYPASS_LINE in box.text()[1]
          and len(open(log).read().splitlines()) == n_runs, (rc, box.text()))

    # -- run: a slice that is not installed is 69 by name, before anything is asked
    box = Stub({"POST /grants": grant}, env={"SLICES_INSTALLED": "boxres.slice rounds.slice boxres-fill.slice"})
    rc = run(box, "run", "--class", "round", "--", "true")
    check("run: a class whose slice is not installed is refused rc 69, naming the slice, with no request made",
          rc == 69 and "boxres-round.slice is not installed" in box.text()[1] and box.calls == [], (rc, box.text(), box.calls))
    box = Stub({"POST /grants": grant}, env={"SLICES_INSTALLED": "boxres-round.slice rounds.slice"})
    rc = run(box, "run", "--class", "round", "--", "true")
    check("run: a slice whose parent (the slice before the dash) is not installed is refused rc 69, naming the parent and the "
          "slice inside it",
          rc == 69 and "slice boxres.slice is not installed" in box.text()[1]
          and "boxres-round.slice is inside it" in box.text()[1] and box.calls == [], (rc, box.text()))
    box = Stub({"POST /grants": grant, "DELETE /grants/g1": (200, {})})
    rc = run(box, "run", "--class", "lead", "--", "true")
    check("run: a class with no slice in the config runs where it did, with no --slice", rc == 0 and "--slice" not in last_scope(),
          (rc, last_scope()))
    check("run: a class that is not in the config is usage, 64",
          run(Stub({}), "run", "--class", "nope", "--", "true") == 64)

    # -- run: the cpus a grant leaves, from confine
    box = Stub({"POST /grants": lambda b: grant(b, confine={"cpus": "6-7,14-15"}), "DELETE /grants/g1": (200, {})})
    rc = run(box, "run", "--class", "round", "--", "true")
    check("run: AllowedCPUs comes from the grant's confine (what the exclusive sets leave)",
          rc == 0 and "-p AllowedCPUs=6-7,14-15" in last_scope(), last_scope())

    # -- run: the tape writes the hold with pid and start, takes the config's cpus and nvme, lowers its oom score
    cfg = ledger.load_config(cfg_path)
    box = Stub({"POST /grants": lambda b: grant(b, confine={"cpus": ledger.fmt_cpus(cfg.tape["cpus"])}),
                "DELETE /grants/g1": (200, {})})
    seen = {}

    def during(b):
        with open(os.path.join(hold_dir, "bloomery-tape-hold")) as f:
            seen["hold"] = f.read()
        return grant(b, confine={"cpus": ledger.fmt_cpus(cfg.tape["cpus"])})
    box.replies["POST /grants"] = during
    rc = run(box, "run", "--class", "tape", "--card", "3090", "--need", "ram.locked=99G", "--need", "host_lock=1", "--holder", "tape",
             "--", "bash", "-c", 'echo "$BLOOMERY_HOLD_OWNER $BOXRES_GRANT $BOXRES_CLASS" > ' + os.path.join(tmp, "tape-env"))
    body = box.calls[0][2]
    check("run: class tape defaults its cpus and nvme from the config (the 24-worker set, nvme0 latency) and names its hold",
          body["need"]["cpus"] == ledger.fmt_cpus(cfg.tape["cpus"]) and body["need"]["nvme"] == {"nvme0": "lat"}
          and body["hold"] == "bloomery-tape-hold" and body["need"]["cards"] == ["3090"], body)
    check("run: the hold exists with pid= and start= before the grant is asked, and is gone when the command ends",
          seen.get("hold") == "pid=%d start=4242 holder=tape\n" % os.getpid()
          and not os.path.exists(os.path.join(hold_dir, "bloomery-tape-hold")), seen)
    with open(os.path.join(tmp, "tape-env")) as f:
        env_line = f.read().strip()
    check("run: the command sees BLOOMERY_HOLD_OWNER=tape (its own box.sh calls pass the hold), BOXRES_GRANT and BOXRES_CLASS",
          env_line == "tape g1 tape", env_line)
    with open(oom_file) as f:
        oom = f.read()
    check("run: the tape's process gets the config's oom_score_adj before it execs", oom == "-900", oom)

    # -- run: --threads holds what that many pool workers occupy (the config's list for 24, every cpu for 32)
    box = Stub({"POST /grants": grant, "DELETE /grants/g1": (200, {})})
    run(box, "run", "--class", "tape", "--threads", "24", "--", "true")
    n24 = box.calls[0][2]["need"]["cpus"]
    box = Stub({"POST /grants": grant, "DELETE /grants/g1": (200, {})})
    run(box, "run", "--class", "tape", "--threads", "32", "--", "true")
    n32 = box.calls[0][2]["need"]["cpus"]
    box = Stub({"POST /grants": grant})
    bad = run(box, "run", "--class", "round", "--threads", "24", "--", "true")
    box = Stub({"POST /grants": grant})
    bad2 = run(box, "run", "--class", "tape", "--threads", "33", "--", "true")
    check("run: --threads 24 holds the config's tape cpus, --threads 32 every cpu (the rounds are drained), and --threads is "
          "usage 64 for another class or a pool wider than the primaries",
          n24 == ledger.fmt_cpus(cfg.tape["cpus"]) and n32 == "0-63" and bad == 64 and bad2 == 64, (n24, n32, bad, bad2))

    # -- run: a live hold is refused 75 by name; a dead owner's is replaced
    hold_file = os.path.join(hold_dir, "bloomery-tape-hold")
    with open(hold_file, "w") as f:
        f.write("pid=%d start=4242 holder=other\n" % os.getpid())
    box = Stub({"POST /grants": grant})
    rc = run(box, "run", "--class", "tape", "--", "true")
    check("run: a tape hold that is up with a running owner is rc 75 naming the file and its words; no request is made",
          rc == 75 and hold_file in box.text()[1] and "holder=other" in box.text()[1] and box.calls == [], (rc, box.text()))
    with open(hold_file, "w") as f:
        f.write("pid=99999999 start=1 holder=ghost\n")
    box = Stub({"POST /grants": grant, "DELETE /grants/g1": (200, {})})
    rc = run(box, "run", "--class", "tape", "--", "true")
    check("run: a hold whose owner is dead is replaced, said, and the run goes on",
          rc == 0 and "names a dead owner" in box.text()[1] and not os.path.exists(hold_file), (rc, box.text()))
    # a refused tape grant takes its hold down again
    box = Stub({"POST /grants": refusal})
    rc = run(box, "run", "--class", "tape", "--", "true")
    check("run: a refused tape run leaves no hold behind", rc == 75 and not os.path.exists(hold_file), rc)

    # -- run: a signal reaches the command, the grant is released, rc is 128 + the signal
    box = Stub({"POST /grants": grant, "DELETE /grants/g1": (200, {})})
    pidfile = os.path.join(tmp, "child.pid")
    me = os.getpid()
    killer = subprocess.Popen(["bash", "-c", 'for i in $(seq 100); do [ -s "$1" ] && break; sleep 0.1; done; '
                              'kill -TERM "$2"', "x", pidfile, str(me)])
    rc = run(box, "run", "--class", "round", "--", "bash", "-c", 'echo $$ > "%s"; exec sleep 30' % pidfile)
    killer.wait()
    check("run: a TERM to boxres is forwarded to the command; rc is 143 and the grant is released",
          rc == 143 and box.calls[-1][0] == "DELETE", (rc, box.calls))

    # -- status and why
    view = {
        "at": "2026-10-20T15:55:26", "snapshot_age_s": 0.1,
        "ram": {"os_other": 6_694_629_376, "headroom": 4_294_967_296, "charged": 132_000_000_000, "measured": 120_000_000_000,
                "held_back": 0, "mem_total": 270_071_005_184, "mem_available": 100_000_000_000, "unowned": 8_000_000_000,
                "g": 257_000_000_000, "free": 125_000_000_000},
        "cpu": {"all": "0-63", "free": "6-7,14-15", "exclusive": {"g4": "0-5,8-13"}},
        "nvme": {"nvme0": {"lat": "g4", "bulk": []}, "nvme1": {"lat": None, "bulk": []}},
        "holders": [{"id": "g4", "kind": "grant", "holder": "tape", "class": "tape", "owner": "lead", "unit": "boxres-tape-tape-9.scope",
                     "since": "2026-10-20T15:00:00", "state": "live", "declared": 132_000_000_000, "measured": 120_000_000_000,
                     "charge": 132_000_000_000, "over_by": 0, "over": False, "status": "held",
                     "status_why": "card 3090 has read 0 % utilization for 700 s while this grant holds it", "text": "ok",
                     "need": {"ram": {"locked": 99_000_000_000}, "cards": ["3090"], "cpus": [0, 1, 2], "nvme": {"nvme0": "lat"}, "host_lock": True}}],
        "cards": {"a6000": {"state": "ok", "used_mib": 1, "lane_busy": False, "reasons": []},
                  "3090": {"state": "ok", "used_mib": 22_000, "lane_busy": False, "reasons": []}},
        "holds": [{"name": "bloomery-tape-hold", "state": "up", "grant": "g4"}],
        "waiters": [{"id": "q-9", "name": "gate-gpu-lib", "class": "round", "owner": "t", "card": "3090",
                     "need": {"ram": {"anon": 1_000_000_000}}, "why": "card 3090 is held by grant g4 (tape tape, unit boxres-tape-tape-9.scope)"}],
        "ended": [{"id": "g2", "holder": "dump", "class": "fill", "state": "reclaimed", "since": "x", "ended": "2026-10-20T14:00:00",
                   "ended_why": "owner is dead: unit dump.scope is not-found"}],
        "recent": [{"at": "2026-10-20T15:30:00", "kind": "refused",
                    "text": "boxres: bulk (class fill) refused rc 75: nvme0 bulk is refused while a latency holder is up -- held by g4 tape tape"}],
        "lease": {"timing": {"state": "held", "text": "pid 77 lease-take (card file docs/cards/x.card), up 600 s", "holders": [], "record": None},
                  "box_lease": None, "quiet": "the timing lease is held by pid 77"},
        "slices": {"fill": {"unit": "boxres-fill.slice", "running": False},
                   "static": {"unit": "rounds.slice", "running": True, "procs": 3, "memory_current": 12_000_000_000,
                              "memory_high": 40_000_000_000, "memory_max": 56_000_000_000, "cpus": "16-31,48-63"}},
    }
    box = Stub({"GET /ledger": (200, view), "GET /jobs/q-9": (404, {"error": "no such job"}), "GET /jobs/g4": (404, {"error": "no"}),
                "GET /jobs/nothing": (404, {"error": "no"})})
    rc = run(box, "status")
    out, _ = box.text()
    check("status: ram, cards, cpus, nvme, lease, slices, holders and waiters are all printed, with the holder's need and use",
          rc == 0 and "G 257.00 GB" in out and "card.3090" in out and "tape tape" in out and "g4:12c" in out and "free cpus 6-7,14-15" in out and "lat: g4" in out and "timing lease  HELD by pid 77" in out and "rounds.slice" in out
          and "no unit running" in out and "declared 132.00 GB, measured 120.00 GB" in out and "ram locked 99.0G" in out
          and "[held: card 3090 has read 0 %" in out and "q-9" in out and "card 3090 is held by grant g4" in out, out)
    rc = run(box, "why", "g4")
    out, _ = box.text()
    check("why: a grant prints its state, need, declared/measured/charged and the ledger's free of cap",
          rc == 0 and "g4 (grant, class tape" in out and "free 125.00 GB of cap 257.00 GB" in out and "held:" in out, out)
    box = Stub({"GET /ledger": (200, view), "GET /jobs/q-9": (404, {"error": "no"})})
    rc = run(box, "why", "q-9")
    check("why: a queued job prints what it waits on, naming the holder", rc == 0 and "q-9 (queued job" in box.text()[0]
          and "held by grant g4" in box.text()[0], box.text())
    box = Stub({"GET /ledger": (200, view), "GET /jobs/g2": (404, {"error": "no"})})
    run(box, "why", "g2")
    check("why: an ended grant prints how and why it ended", "reclaimed" in box.text()[0] and "not-found" in box.text()[0], box.text())
    box = Stub({"GET /ledger": (200, view), "GET /jobs/tape": (404, {"error": "no"})})
    run(box, "why", "tape")
    check("why: a name that matches a refusal prints the decision", "refused" in box.text()[0] or "g4 (grant" in box.text()[0], box.text())
    box = Stub({"GET /ledger": (200, view), "GET /jobs/nothing": (404, {"error": "no"})})
    check("why: a name nothing has is rc 66", run(box, "why", "nothing") == 66 and "nothing in the ledger" in box.text()[1])
    box = Stub({"GET /ledger": (200, view)}, env={"BOXRES_OFF": "1"})
    check("status: BOXRES_OFF=1 prints the bypass line and asks nothing", run(box, "status") == 0 and box.calls == []
          and client.BYPASS_LINE in box.text()[1])

    # -- hf-fetch: the download worker as a fill grant, the drive from the directory
    wrapper = os.path.join(here, "..", "..", "configs", "hf-fetch", "hf-fetch.sh")
    if not os.path.exists(wrapper):
        wrapper = os.path.join(here, "hf-fetch", "hf-fetch.sh")
    dl = os.path.join(tmp, "dl")
    os.makedirs(dl)
    argv_file = os.path.join(tmp, "boxres-argv")
    fake = os.path.join(tmp, "fake-boxres")
    with open(fake, "w") as f:
        f.write('#!/bin/bash\nprintf "%s\\n" "$@" > ' + argv_file + '\nexit ${FAKE_RC:-0}\n')
    os.chmod(fake, 0o755)
    p = subprocess.run([wrapper, "user/repo-x", dl, "5M"], env=dict(os.environ, BOXRES=fake, FAKE_RC="75"),
                       capture_output=True, text=True)
    with open(argv_file) as f:
        got = f.read().split("\n")[:-1]
    want = ["run", "--class", "fill", "--holder", "hf-user_repo-x", "--io", os.path.realpath(dl) + ":bulk", "--need",
            "ram.anon=2G", "--", os.path.realpath(os.path.join(os.path.dirname(wrapper), "hf-worker.sh")), "user/repo-x", dl, "5M"]
    check("hf-fetch: the worker runs as `boxres run --class fill` with its directory as nvme bulk IO, 2G of anon for its "
          "caps, and hf-worker.sh after `--`; a refusal (75) is the wrapper's rc", got == want and p.returncode == 75, (got, p.returncode))
    p = subprocess.run([wrapper, "user/repo-x", os.path.join(tmp, "none")], env=dict(os.environ, BOXRES=fake),
                       capture_output=True, text=True)
    q = subprocess.run([wrapper, "user/repo-x", dl], env=dict(os.environ, BOXRES=os.path.join(tmp, "absent")),
                       capture_output=True, text=True)
    check("hf-fetch: a directory that is not there is 66 and says to run hf-manifest.py first; no boxres is 66 and says where "
          "it installs from", p.returncode == 66 and "hf-manifest.py" in p.stderr and q.returncode == 66 and "ln -s" in q.stderr,
          (p.returncode, p.stderr, q.returncode, q.stderr))

    # -- sizes
    sizes = {"2G": 2 * 10 ** 9, "99GB": 99 * 10 ** 9, "12GiB": 12 << 30, "1.5g": 1_500_000_000, "512": 512, "3MiB": 3 << 20}
    got = {k: parse_size(k) for k in sizes}
    check("sizes: G and GB are decimal, GiB binary, a bare number is bytes", got == sizes, got)
    try:
        parse_size("2 parsecs")
        bad = None
    except Fail as e:
        bad = e.rc
    check("sizes: a size that is not one is usage 64", bad == 64)

    ok = all(results)
    print("\n%d passed, %d failed" % (sum(results), len(results) - sum(results)))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
