#!/usr/bin/env python3
"""signalbox — the box's job dispatcher. One lane per card, job classes, cache groups,
reservation windows, and an HTTP face on loopback for the tailnet.

The laws it obeys (each from an incident recorded in rig-log):

  - The lease is owned by the runners. ltx/img/music/echo-take.sh and comfy-session.sh take
    and release /home/user/gpu-lease themselves, releasing only after the card's VRAM comes
    back. signalbox never writes that file, except to clear one whose pid is dead — a lease
    whose pid does not answer kill -0 is not a lease (2026-09-17).
  - Listening is not busy. The daemon touches no GPU while idle; a serving process on a port
    is not occupancy (docs/quiet-machine.md).
  - Cards are named by UUID via /home/user/gpu-order.env, never by index.
  - Bloomery's locks are observed, never taken: a shared flock probe (lease_free's exact
    semantics) fails only while an exclusive holder is in. box.sh, gate-batch and the trains
    keep working exactly as before; signalbox steps around them.
  - Jobs are bash runner scripts exec'd from a per-job snapshot, so deploying over a running
    script cannot change what a job does mid-statement (the chain-s lesson, 2026-09-16).
  - A job is a systemd transient unit (sb-<id>), not the daemon's child: a daemon restart
    never touches it, and stop is `systemctl stop` — TERM to the job's processes (a media
    unit signals only its runner, which tears down lawfully), KILL only after the unit's
    TimeoutStopSec. The job's rc is a file the unit's ExecStopPost writes, so a restarted
    daemon re-adopts a job by its unit and that file.
  - Scheduling is priority-first: higher priority, then older. Time windows are an optional
    config for whoever wants them, never the default basis — the box's rhythm is requests
    arriving, not the clock (2026-10-03: webuta's night window outlived webuta itself, which
    had ended 09-21; a stale window refused jobs for eight hours a night for nothing).
  - A job class other than normal, host and solo sets the priority (configs/box-resources.json,
    classes). A sitting owns the box and is a drain barrier: while one is queued no job of
    lower priority starts, and nothing running is preempted. Media sits below the sitting
    (user order, 2026-10-20), goes ahead of every other queued job, preempts nothing, and
    while one is queued for a card no other job starts on that card. A cache group separates
    media jobs from each other and bloomery jobs from each other, never the two kinds.
  - The resource ledger (ledger.py) is the one place that says what the box has and what is
    promised: host RAM by page class, the cards, the cpus as explicit lists, nvme bulk and
    latency. A job signalbox does not start itself asks for a grant (POST /grants, DELETE
    /grants/<id>; GET /ledger shows the holders) and gives a unit or a pid + start time as its
    liveness: the grant ends when its owner does, within one tick, by name. Probes run once a tick with no lock held (Probes.snapshot); admission
    answers from that snapshot. A hold file may carry its owner (`pid=N start=T` or
    `unit=NAME`): a hold whose owner is dead is named and ignored, a hold with no owner is up
    while it exists, as before. A hold that stands behind a live grant does not block a queued
    job that declared a need which fits beside it; that job starts confined to what the
    grant leaves.
  - A queued job of a class with a slice in the config (round, static, fill) starts in that
    slice (systemd-run --slice) and is refused rc 69 by name when the slice, or the slice its
    name sits inside, has no unit file: systemd makes an implicit slice with no caps out of any
    name, so only FragmentPath says it is installed. --check says the same before a restart.
  - The timing lease's holder (the shared lock probe, then the processes whose descriptor on the
    lock carries it) and the rig-log lease file are read each tick and shown in /ledger. While
    either is up, or a sitting's grant is, a grant for nvme bulk IO is refused rc 75 naming it.

stdlib only, like logproxy and mrs-shim before it. State under /home/user/signalbox/.
"""

import argparse
import fcntl
import glob as globmod
import hmac
import json
import math
import os
import pwd
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ledger

HOME = os.environ.get("SIGNALBOX_HOME", "/home/user/signalbox")
PORT = int(os.environ.get("SIGNALBOX_PORT", "8030"))
GPU_LEASE = os.environ.get("SIGNALBOX_GPU_LEASE", "/home/user/gpu-lease")
GPU_ORDER_ENV = os.environ.get("SIGNALBOX_GPU_ORDER", "/home/user/gpu-order.env")
BLOOMERY_LOCK_GLOB = os.environ.get("SIGNALBOX_BLOOMERY_LOCKS", "/root/bloomery-*.lock")
BLOOMERY_HOLD_GLOB = os.environ.get("SIGNALBOX_BLOOMERY_HOLDS", "/root/bloomery-*-hold")
FAKE = os.environ.get("SIGNALBOX_FAKE", "") == "1"
TOKEN_FILE = os.environ.get("SIGNALBOX_TOKEN_FILE", "/etc/signalbox/token")
# The ledger's config; empty means box-resources.json in the scheduler's home.
RESOURCES = os.environ.get("SIGNALBOX_RESOURCES", "")

# Which card a bloomery lock speaks for; everything unlisted is treated as box-wide, because
# a timing lease or a v41 load can touch either card and a wrong guess costs a contaminated row.
LOCK_CARDS = {
    "bloomery-gate.lock": ("3090",),
    "bloomery-gate-a6000.lock": ("a6000",),
}

RUNNERS = {
    "ltx": "/home/user/ltx-take.sh",
    "img": "/home/user/img-take.sh",
    "music": "/home/user/music-take.sh",
    "echo": "/home/user/echo-take.sh",
}
ARTIFACT_DIRS = {
    "ltx": "/home/user/ltx-runs",
    "img": "/home/user/img-runs",
    "music": "/home/user/music-runs",
    "echo": "/home/user/echo-runs",
}
SENTINELS = {
    "ltx": ("LTX_DONE", "LTX_FAILED"),
    "img": ("IMG_DONE", "IMG_FAILED"),
    "music": ("MUSIC_DONE", "MUSIC_FAILED"),
    "echo": ("ECHO_DONE", "ECHO_FAILED"),
}
COMFY_SESSION = os.environ.get("SIGNALBOX_COMFY_SESSION", "/home/user/comfy-session.sh")
COMFY_URL = os.environ.get("SIGNALBOX_COMFY_URL", "http://127.0.0.1:8188")

CARDS = ("a6000", "3090")
VRAM_IDLE_MIB = 2000
QUEUE_HISTORY = 500
KINDS = ("media-take", "comfy-session", "command", "fake")
# normal, host and solo take their priority from the body; every other class (the config's
# `classes`) sets it, and a body that names one carries no priority.
BODY_CLASSES = ("normal", "host", "solo")
# A job of these classes starts only on an empty box and nothing starts beside it.
EXCLUSIVE_CLASSES = ("host", "solo", "sitting")
# `any` is the first card that can take the job, `both` needs both, `none` holds no card.
CARD_CHOICES = CARDS + ("any", "both", "none")
EXPECTED_S_MAX = 604800
MEDIA_KINDS = ("media-take", "comfy-session")
BOUND_S_MAX = 86400
TAIL_LINE_BYTES = 1024
# A job unit's stop timeout. A media runner's finish() waits up to 60 + 15 + 10 + 45 * 2 =
# 175 s (the take scripts' loops), so its unit gets 240 s before the KILL.
STOP_S = 30
MEDIA_STOP_S = 240
# Seconds between ticks, between watchdog pings, and the oldest finished tick that still
# earns a ping: a tick wedged longer than that lets WatchdogSec kill a hung daemon.
TICK_S = 2
WATCHDOG_INTERVAL_S = 5
TICK_MAX_AGE_S = 60
# The owner every job a tailnet request creates carries: the token's holder. A body never
# sets it, and cancel from the tailnet reaches only jobs that carry it.
TAILNET_OWNER = "hermes"
# Media runs on the A6000 only: every runner, and the ComfyUI window, is sized for it.
MEDIA_CARD = "a6000"


def _fmt(pattern):
    return re.compile(pattern)


# Value classes of the tailnet knob allowlists. A value is checked as the string gen() will
# put in the runner's environment; only the classes below reach a runner.
INT = _fmt(r"[0-9]{1,6}")
FLOAT = _fmt(r"[0-9]{1,4}(\.[0-9]{1,4})?")
WH = _fmt(r"[0-9]{2,5} [0-9]{2,5}")
TEXT = "text"    # reaches the runner's argv inside double quotes; may not look like a flag
LABEL = "label"  # a display string that never reaches a runner's argv
TEXT_MAX, LABEL_MAX = 8000, 200

class Span:
    """An integer between lo and hi, both inclusive."""
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def ok(self, text):
        return INT.fullmatch(text) is not None and self.lo <= int(text) <= self.hi


# Knobs a tailnet /gen/<medium> body may carry, with the class each value must fall in.
# Every TEXT knob is double-quoted wherever its runner uses it. Left out on purpose: paths
# and flag pass-throughs (extra, image, images, loras, vidcond, model, lyrics_file, abc,
# plim) and mbs, which is a count with no enum.
TAILNET_KNOBS = {
    "video": {  # ltx-take.sh
        "prompt": TEXT, "neg": TEXT,
        "pipe": frozenset(("distilled", "dfr", "distilled_mgpu", "ti2vid_two_stages",
                           "ti2vid_two_stages_hq")),
        "frames": INT, "seed": INT, "steps": INT,
        "cfg": FLOAT, "stg": FLOAT, "rescale": FLOAT, "a2v": FLOAT,
        "wh": WH,                               # word-split in the runner on purpose
        "offload": frozenset(("none", "cpu", "disk")),
        "quant": frozenset(("fp8-cast",)),
    },
    "image": {  # img-take.sh
        "prompt": TEXT, "neg": TEXT,
        "wh": WH,                               # word-split in the runner on purpose
        "steps": INT, "seed": INT, "count": INT,
        "guidance": FLOAT,
    },
    "music": {  # music-take.sh
        "style": TEXT, "lyrics": TEXT,
        "seed": INT,
        "cot": frozenset(("full", "melody")),
        "plan_only": frozenset(("1",)),         # any non-empty value is the flag
    },
}
# Body keys that steer the scheduler rather than a runner. owner is not among them: it
# names a reservation window's owner, which lets a job through that window.
TAILNET_META = {
    "tag": _fmt(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"),  # a directory name in the runners: no leading dot
    "title": LABEL,
    "expected_min": _fmt(r"[0-9]{1,4}"),
    "card": frozenset((MEDIA_CARD,)),
    "wait": _fmt(r"[0-9]{1,3}"),
}
# Knobs a tailnet /comfy/session body may carry. ts_serve is left out on purpose: with it
# comfy-session.sh makes ComfyUI listen on the box's tailnet IP, which is the whole ComfyUI
# API (workflow submit, upload) with no token and no allowlist. minutes is bounded because
# the script reads 0 as "hold until stopped" and the tailnet has no stop route. port is only
# ComfyUI's --port and the script's own health-check port; a window is held to the
# 8188-8199 range.
TAILNET_SESSION = {
    "minutes": Span(1, 120),
    "port": Span(8188, 8199),
    **{k: TAILNET_META[k] for k in ("tag", "title", "card", "wait")},
}
# One table per tailnet POST route: the only routes a tailnet caller reaches, after the
# bearer token passes. /gen/audio stays local: its required knobs (cache, request and
# config paths) are paths the echo runner joins onto its repo. A cancel takes no body key.
TAILNET_ROUTES = {
    "/gen/video": {**TAILNET_KNOBS["video"], **TAILNET_META},
    "/gen/image": {**TAILNET_KNOBS["image"], **TAILNET_META},
    "/gen/music": {**TAILNET_KNOBS["music"], **TAILNET_META},
    "/comfy/session": TAILNET_SESSION,
    "/jobs/<id>/cancel": {},
}
# Keys a route refuses to default: absent, they would mean something the table forbids.
TAILNET_REQUIRED = {"/comfy/session": ("minutes",)}
CANCEL_RE = re.compile(r"^/jobs/([A-Za-z0-9._-]+)/cancel$")


def _value_ok(kind, value):
    if isinstance(value, bool) or value is None:
        return False
    if kind in (TEXT, LABEL):
        if not isinstance(value, str):
            return False
        try:
            value.encode("utf-8")  # a lone surrogate cannot go into an environment
        except UnicodeEncodeError:
            return False
        if "\0" in value:
            return False
        if kind == LABEL:
            return len(value) <= LABEL_MAX
        return 0 < len(value) <= TEXT_MAX and not value.startswith("-")
    if isinstance(value, (int, float)):
        value = str(value)
    elif not isinstance(value, str):
        return False
    if isinstance(kind, frozenset):
        return value in kind
    if isinstance(kind, Span):
        return kind.ok(value)
    return kind.fullmatch(value) is not None


def tailnet_route(path):
    """The TAILNET_ROUTES key a path falls under, or None."""
    if path in TAILNET_ROUTES:
        return path
    return "/jobs/<id>/cancel" if CANCEL_RE.match(path) else None


def tailnet_refusal(route, body):
    """Why a tailnet body for this route is refused, or None. Every key must be in the
    route's table, with a value in its class, and every required key must be present."""
    table = TAILNET_ROUTES[route]
    for key, value in body.items():
        kind = table.get(key)
        if kind is None:
            return "tailnet %s: %s is not an allowed key" % (route, key)
        if not _value_ok(kind, value):
            return "tailnet %s: the value of %s is not in its allowed form" % (route, key)
    for key in TAILNET_REQUIRED.get(route, ()):
        if key not in body:
            return "tailnet %s: %s is required" % (route, key)
    return None


def log(msg):
    sys.stderr.write("%s signalbox: %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def read_token(path):
    """(token bytes, None), or (None, why) when the file cannot be trusted: missing, not a
    regular file, empty, or readable by group or other. Read on every call, so a rotated
    token takes effect without a restart."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as e:
        return None, "is unreadable (%s)" % e.strerror
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "is not a regular file"
        if st.st_mode & 0o077:
            return None, "has mode %04o, readable by group or other" % (st.st_mode & 0o777)
        token = os.read(fd, 4096).rstrip(b"\r\n")
    except OSError as e:
        return None, "is unreadable (%s)" % e.strerror
    finally:
        os.close(fd)
    if not token:
        return None, "is empty"
    return token, None


# ---------------------------------------------------------------- probes (injectable for tests)

UNIT_ACTIVE = ("active", "activating", "deactivating", "reloading", "refreshing")
# What one snapshot may spend: two nvidia-smi calls (10 s each) and the unit reads (5 s each, 15 s
# in all), so a tick whose probes all hang ends in under 40 s, inside TICK_MAX_AGE_S (60 s) and
# the unit's WatchdogSec=30 plus its ping interval.
SMI_TIMEOUT_S = 10
UNIT_TIMEOUT_S = 5
UNIT_BUDGET_S = 15
# How often a grant that holds a card makes a tick read the driver when nothing else asks: the
# `held` word needs minutes of resolution, and a query every tick is a resident load beside a run.
CARD_POLL_S = 30
# The bloomery lock that is the timing lease, and the rig-log lease file's default path.
TIMING_LOCK = "bloomery-cpu.lock"
BOX_LEASE = os.environ.get("SIGNALBOX_BOX_LEASE", "/home/user/box-lease")
HOLDERS_MAX = 8      # the lease holders /ledger names; the rest are counted
XID_RE = re.compile(r"^(\S+) \S+ kernel: NVRM: Xid \(PCI:([0-9A-Fa-f:]+)\): 79\b")
Hold = namedtuple("Hold", "path name age_s owner reading")


def owner_key(live):
    """The key a liveness (a unit, or a pid with its start time) is watched and read under."""
    return ("unit", live["unit"]) if "unit" in live else ("pid", live["pid"], live["start"])


def parse_meminfo(text):
    """{name: bytes} of /proc/meminfo's lines; a ValueError names a line it cannot read."""
    out = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        words = rest.split()
        if not words:
            continue
        if not words[0].isdigit():
            raise ValueError("meminfo line %r" % line)
        out[name] = int(words[0]) * (1024 if words[1:] == ["kB"] else 1)
    for need in ("MemTotal", "MemAvailable"):
        if need not in out:
            raise ValueError("meminfo has no %s" % need)
    return out


def parse_status(text):
    """/proc/<pid>/status as {key: value text}."""
    out = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        out[key] = value.strip()
    return out


def status_bytes(status, key):
    """A kB line of /proc/<pid>/status in bytes; 0 for a line the kernel leaves out (a
    kernel thread has no Rss lines)."""
    words = status.get(key, "").split()
    return int(words[0]) * 1024 if words and words[0].isdigit() else 0


def parse_stat_start(text):
    """(state letter, start time in clock ticks) of one /proc/<pid>/stat line. The command
    name is in parentheses and may hold spaces and parentheses itself, so the fields are
    counted from the last ')'."""
    rest = text.rsplit(")", 1)[1].split()
    return rest[0], int(rest[19])


def parse_cards(uuids, gpus, apps, unit_of_pid=lambda pid: None):
    """The cards from nvidia-smi's two CSV answers (`uuid,memory.used,memory.total` with
    `,utilization.gpu,pci.bus_id` after them when asked, and `gpu_uuid,pid,used_gpu_memory`,
    noheader, nounits). A card whose uuid the first lists not is `lost`: it is off the bus."""
    listed = {}
    for line in gpus.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) in (3, 5) and f[1].isdigit() and f[2].isdigit():
            util = int(f[3]) if len(f) == 5 and f[3].isdigit() else None
            listed[f[0]] = (int(f[1]), int(f[2]), util, f[4] if len(f) == 5 else None)
    on = {}
    for line in apps.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) == 3 and f[1].isdigit():
            on.setdefault(f[0], []).append({"pid": int(f[1]),
                                            "mib": int(f[2]) if f[2].isdigit() else None,
                                            "unit": unit_of_pid(int(f[1]))})
    out = {}
    for card, uuid in uuids.items():
        if uuid in listed:
            out[card] = {"state": "ok", "why": "", "used_mib": listed[uuid][0],
                         "total_mib": listed[uuid][1], "apps": on.get(uuid, []),
                         "util": listed[uuid][2], "bus": listed[uuid][3]}
        else:
            out[card] = {"state": "lost", "why": "uuid %s is not listed by nvidia-smi" % uuid,
                         "used_mib": 1 << 30, "total_mib": None, "apps": [], "util": None, "bus": None}
    return out


def bus_key(pci):
    """The bus:device of a PCI address in either spelling (nvidia-smi's `00000000:41:00.0`, the
    kernel log's `0000:41:00`): `41:00`."""
    parts = pci.split(":")
    return ":".join(parts[-2:]).split(".")[0] if len(parts) >= 2 else pci


def xid_text(events, bus):
    """What the kernel log says about a card that left the bus: the latest Xid 79 on its PCI
    address, or, when its address is not known, the latest on any address. "" when the log has none."""
    if bus:
        mine = [e for e in events if bus_key(e["pci"]) == bus_key(bus)]
        return "; Xid 79 at %s on PCI %s" % (mine[-1]["at"], mine[-1]["pci"]) if mine else ""
    if events:
        return ("; the kernel log has Xid 79 at %s on PCI %s (this card's bus address was not "
                "read before it left)" % (events[-1]["at"], events[-1]["pci"]))
    return ""


class Snapshot:
    """Everything one tick read from the box, with no lock held. Admission and the ledger answer
    from it and never touch a probe themselves."""

    def __init__(self):
        self.mono = time.monotonic()
        self.lease = None
        self.locks = {}
        self.holds = []        # Hold rows
        self.mem, self.mem_why = None, "not read"
        self.cards = {}        # card -> {state, why, used_mib, total_mib, apps}; {} until read
        self.cards_read = False
        self.owners = {}       # owner_key -> {state, why, measured, cpus_allowed}
        self.nvme = {}         # drive -> (read bytes, write bytes), the kernel's counters
        self.timing = {"state": "free", "holders": [], "record": None}   # the bloomery timing lease
        self.box_lease = None  # the rig-log lease file: {pid, reason, live, raw} or None
        self.slices = {}       # slice unit -> its cgroup's reading


class Probes:
    """The read side of the box. Every method is side-effect free except clear_stale_lease."""

    def __init__(self, gpu_order=GPU_ORDER_ENV, lease=GPU_LEASE,
                 lock_glob=BLOOMERY_LOCK_GLOB, hold_glob=BLOOMERY_HOLD_GLOB,
                 proc="/proc", cgroup="/sys/fs/cgroup", sysblock="/sys/block",
                 systemctl="systemctl", nvidia_smi="nvidia-smi", unit_budget_s=UNIT_BUDGET_S,
                 journalctl="journalctl", box_lease=BOX_LEASE):
        self.gpu_order_path, self.lease_path = gpu_order, lease
        self.lock_glob, self.hold_glob = lock_glob, hold_glob
        self.proc, self.cgroup, self.sysblock = proc, cgroup, sysblock
        self.systemctl, self.nvidia_smi, self.journalctl = systemctl, nvidia_smi, journalctl
        self.box_lease_path = box_lease
        self.unit_budget_s, self._unit_deadline = unit_budget_s, None
        self._order = None
        self._buses = {}         # card -> its PCI address, read while it was on the bus
        self._holders = {}       # lock path -> ((dev, ino), [{pid, fd}], described): the last scan, kept while it holds

    def uuids(self):
        if self._order is None:
            order = {}
            try:
                with open(self.gpu_order_path) as f:
                    for line in f:
                        m = re.match(r"\s*export\s+(\w+_UUID)=(\S+)", line)
                        if m:
                            order[m.group(1)] = m.group(2)
            except OSError:
                pass
            self._order = {
                "a6000": order.get("A6000_UUID", ""),
                "3090": order.get("GF3090_UUID", ""),
            }
        return self._order

    def _run(self, argv, timeout=SMI_TIMEOUT_S):
        """(CompletedProcess, None), or (None, why) for a command that cannot run."""
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL), None
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, "%s: %s" % (argv[0], e)

    def _read(self, *parts):
        with open(os.path.join(*parts)) as f:
            return f.read()

    def meminfo(self):
        """{name: bytes} of /proc/meminfo; an OSError or ValueError when it cannot be read."""
        return parse_meminfo(self._read(self.proc, "meminfo"))

    def unit_of_pid(self, pid):
        """The systemd unit a pid runs in (the last path part of its cgroup), or None."""
        try:
            line = self._read(self.proc, str(pid), "cgroup").splitlines()[0]
        except (OSError, IndexError):
            return None
        return line.rsplit("/", 1)[-1] or None

    def card_readings(self):
        """card -> {state, why, used_mib, total_mib, apps}, from one nvidia-smi call for both
        cards and one for the compute apps. A failed query reads as busy (a big number) and says
        why; a card the query does not list is `lost`."""
        uuids = self.uuids()
        gpu = [self.nvidia_smi, "--query-gpu=uuid,memory.used,memory.total,utilization.gpu,pci.bus_id",
               "--format=csv,noheader,nounits"]
        p, err = self._run(gpu)
        if err is None and p.returncode != 0:
            err = "nvidia-smi rc %d: %s" % (p.returncode, (p.stderr or p.stdout).strip()[:160])
        if err is not None:
            cards = {c: {"state": "unreadable", "why": err, "used_mib": 1 << 30,
                         "total_mib": None, "apps": [], "util": None, "bus": None} for c in uuids}
        else:
            apps_cmd = [self.nvidia_smi, "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
                        "--format=csv,noheader,nounits"]
            a, aerr = self._run(apps_cmd)
            apps = a.stdout if aerr is None and a.returncode == 0 else ""
            cards = parse_cards(uuids, p.stdout, apps, self.unit_of_pid)
        for card, c in cards.items():
            if c.get("bus"):
                self._buses[card] = c["bus"]
        gone = [card for card, c in cards.items() if c["state"] != "ok"]
        if gone:
            events = self.xid79()
            for card in gone:
                cards[card]["why"] += xid_text(events, self._buses.get(card))
        return cards

    def xid79(self):
        """The kernel log's Xid 79 lines of this boot, oldest first: [{at, pci}]. Read only when a
        card is not answering, to say why. [] when the log cannot be read or holds none."""
        p, err = self._run([self.journalctl, "-k", "-b", "-g", r"NVRM: Xid \(PCI:[0-9a-fA-F:]+\): 79",
                            "-o", "short-iso", "--no-pager"])
        if err is not None:
            return []
        out = []
        for line in p.stdout.splitlines():
            m = XID_RE.match(line)
            if m:
                out.append({"at": m.group(1), "pci": m.group(2)})
        return out

    def gpu_lease(self):
        """The media lease file: {'tag','pid','live'} or None. A dead pid is live=False."""
        try:
            with open(self.lease_path) as f:
                fields = f.read().split()
        except OSError:
            return None
        if not fields:
            return None
        pid = None
        for fld in fields[1:3]:
            if fld.isdigit():
                pid = int(fld)
                break
        live = False
        if pid:
            try:
                os.kill(pid, 0)
                live = True
            except PermissionError:
                live = True
            except OSError:
                live = False
        return {"tag": fields[0], "pid": pid, "live": live,
                "raw": " ".join(fields), "path": self.lease_path}

    def clear_stale_lease(self, lease):
        try:
            os.unlink(self.lease_path)
            return True
        except OSError:
            return False

    def bloomery_locks(self):
        """{file: state} with state in held|unreadable. Free files are omitted."""
        out = {}
        for path in sorted(globmod.glob(self.lock_glob)):
            try:
                fd = os.open(path, os.O_RDONLY)
            except OSError:
                out[path] = "unreadable"
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                out[path] = "held"
            except OSError:
                out[path] = "unreadable"
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        return out

    def bloomery_holds(self):
        return sorted(p for p in globmod.glob(self.hold_glob) if os.path.exists(p))

    def hold_age_s(self, path):
        """Seconds since the hold file was last written; None when it cannot be read."""
        try:
            return max(0.0, time.time() - os.path.getmtime(path))
        except OSError:
            return None

    def hold_owner(self, path):
        """The owner a hold file names, from its words: {"pid", "start"} for `pid=N start=T`
        (T is field 22 of /proc/N/stat), {"unit"} for `unit=NAME`. None when the file names
        none (a hold made with touch is up while it exists). A file that names an owner badly
        answers {"bad": why}: the hold stays up and the reason is named."""
        try:
            with open(path) as f:
                words = f.read(4096).split()
        except OSError:
            return None
        kv = dict(w.split("=", 1) for w in words if "=" in w)
        if "unit" in kv:
            if not ledger.UNIT_RE.fullmatch(kv["unit"]):
                return {"bad": "unit=%s is not a unit name" % kv["unit"][:60]}
            return {"unit": kv["unit"]}
        if "pid" in kv or "start" in kv:
            if kv.get("pid", "").isdigit() and kv.get("start", "").isdigit() and int(kv["pid"]) >= 2:
                return {"pid": int(kv["pid"]), "start": int(kv["start"])}
            return {"bad": "pid=N start=T needs both numbers (pid >= 2), got %s"
                    % " ".join(w for w in words if w.startswith(("pid=", "start=")))[:60]}
        return None

    def owner_reading(self, live):
        """What a liveness says now: {state, why, measured, cpus_allowed}. state is alive, dead
        or unknown (the question could not be asked: the owner is kept, not reclaimed). measured
        is the resident bytes of the owner's processes, or None."""
        if "bad" in live:
            return {"state": "unknown", "why": live["bad"], "measured": None, "cpus_allowed": None}
        if "unit" in live:
            unit = live["unit"]
            if self._unit_deadline is not None and time.monotonic() > self._unit_deadline:
                return {"state": "unknown", "measured": None, "cpus_allowed": None,
                        "why": "the %d s budget for unit reads is spent this tick" % self.unit_budget_s}
            p, err = self._run([self.systemctl, "show", unit, "-p", "LoadState",
                                "-p", "ActiveState", "-p", "ControlGroup"], timeout=UNIT_TIMEOUT_S)
            if err is None and p.returncode != 0:
                err = "systemctl show %s: rc %d %s" % (unit, p.returncode, p.stderr.strip()[:120])
            if err is not None:
                return {"state": "unknown", "why": err, "measured": None, "cpus_allowed": None}
            props = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l)
            if props.get("LoadState") == "not-found":
                return {"state": "dead", "why": "unit %s is not-found" % unit,
                        "measured": None, "cpus_allowed": None}
            if props.get("ActiveState") not in UNIT_ACTIVE:
                return {"state": "dead", "why": "unit %s is %s" % (unit, props.get("ActiveState")),
                        "measured": None, "cpus_allowed": None}
            return dict(state="alive", why="unit %s is %s" % (unit, props["ActiveState"]),
                        **self._measure(self._cgroup_pids(props.get("ControlGroup", ""))))
        pid, start = live["pid"], live["start"]
        try:
            state, now_start = parse_stat_start(self._read(self.proc, str(pid), "stat"))
        except FileNotFoundError:
            return {"state": "dead", "why": "pid %d is gone" % pid, "measured": None,
                    "cpus_allowed": None}
        except (OSError, ValueError, IndexError) as e:
            return {"state": "unknown", "why": "pid %d: /proc/%d/stat: %s" % (pid, pid, e),
                    "measured": None, "cpus_allowed": None}
        if state in ("Z", "X"):
            return {"state": "dead", "why": "pid %d is %s" % (pid, "a zombie" if state == "Z" else "dead"),
                    "measured": None, "cpus_allowed": None}
        if now_start != start:
            return {"state": "dead", "why": "pid %d now has start %d, not %d (the pid was reused)"
                    % (pid, now_start, start), "measured": None, "cpus_allowed": None}
        return dict(state="alive", why="pid %d (start %d) is running" % (pid, start),
                    **self._measure([pid]))

    def _cgroup_pids(self, control_group):
        if not control_group:
            return []
        try:
            text = self._read(self.cgroup, control_group.lstrip("/"), "cgroup.procs")
        except OSError:
            return []
        return [int(w) for w in text.split() if w.isdigit()]

    def _measure(self, pids):
        """Resident bytes of these processes: anon + file + shmem pages mapped (locked and
        pinned pages are subsets of those, so they are reported and not added), and the cpus
        their masks allow."""
        anon = file = shmem = lck = pin = 0
        cpus, read = set(), 0
        for pid in pids:
            try:
                st = parse_status(self._read(self.proc, str(pid), "status"))
            except OSError:
                continue            # it exited between the two reads
            read += 1
            anon += status_bytes(st, "RssAnon")
            file += status_bytes(st, "RssFile")
            shmem += status_bytes(st, "RssShmem")
            lck += status_bytes(st, "VmLck")
            pin += status_bytes(st, "VmPin")
            try:
                cpus.update(ledger.parse_cpus(st.get("Cpus_allowed_list", ""), "Cpus_allowed_list"))
            except ValueError:
                pass
        if not read:
            return {"measured": None, "cpus_allowed": None}
        return {"measured": {"resident": anon + file + shmem, "anon": anon, "file": file + shmem,
                             "locked": lck, "pinned": pin},
                "cpus_allowed": ledger.fmt_cpus(cpus) if cpus else None}

    def nvme_counters(self, devs):
        """{drive: (read bytes, write bytes)} from /sys/block/<dev>/stat (512-byte sectors)."""
        out = {}
        for name, dev in devs.items():
            try:
                f = self._read(self.sysblock, dev, "stat").split()
                out[name] = (int(f[2]) * 512, int(f[6]) * 512)
            except (OSError, ValueError, IndexError):
                continue
        return out

    def lock_holders(self, path):
        """The processes that hold the flock on `path`, found the way lease_holders names them:
        every process with a descriptor on the file (matched by device and inode) whose
        /proc/<pid>/fdinfo carries a lock line. A runner's flock(1) exits after it takes the lock
        on the runner's descriptor 9, so the taker in /proc/locks is often gone and the holders are
        these. The scan is kept while its holders still hold, so a sitting costs one scan, not one a
        tick. [{pid, comm, started, card, argv}], oldest first, at most HOLDERS_MAX, and the total."""
        try:
            want = os.stat(path)
        except OSError:
            return [], 0
        key = (want.st_dev, want.st_ino)
        cached = self._holders.get(path)
        if cached and cached[0] == key and cached[1] and all(
                self._fd_locked(h["pid"], h["fd"], key) for h in cached[1]):
            return cached[2], len(cached[1])
        found = []
        try:
            names = os.listdir(self.proc)
        except OSError:
            return [], 0
        me = os.getpid()
        for name in names:
            if not name.isdigit() or int(name) == me:
                continue
            pid = int(name)
            try:
                fds = os.listdir(os.path.join(self.proc, name, "fd"))
            except OSError:
                continue
            for fd in fds:
                if fd.isdigit() and self._fd_locked(pid, int(fd), key):
                    found.append({"pid": pid, "fd": int(fd)})
                    break
        described = sorted((self._describe_holder(h["pid"]) for h in found),
                           key=lambda d: d["started"] or 0)
        self._holders[path] = (key, found, described[:HOLDERS_MAX])
        return described[:HOLDERS_MAX], len(found)

    def _fd_locked(self, pid, fd, key):
        """Does descriptor `fd` of `pid` point at the file `key` and carry a lock on it?"""
        try:
            st = os.stat(os.path.join(self.proc, str(pid), "fd", str(fd)))
            info = self._read(self.proc, str(pid), "fdinfo", str(fd))
        except OSError:
            return False
        return (st.st_dev, st.st_ino) == key and any(
            ln.startswith("lock:") and "->" not in ln for ln in info.splitlines())

    def _describe_holder(self, pid):
        """pid, comm, when it started (epoch seconds), the BLOOMERY_LEASE_CARD of its environment
        and the head of its argv: what a waiter needs to find the sitting."""
        def read(*parts, mode="r"):
            try:
                with open(os.path.join(self.proc, str(pid), *parts), mode) as f:
                    return f.read()
            except OSError:
                return None
        started = None
        try:
            _, ticks = parse_stat_start(read("stat"))
            up = float(self._read(self.proc, "uptime").split()[0])
            started = time.time() - (up - ticks / os.sysconf("SC_CLK_TCK"))
        except (TypeError, ValueError, IndexError, OSError):
            pass
        env = (read("environ", mode="rb") or b"").split(b"\0")
        card = next((v[len(b"BLOOMERY_LEASE_CARD="):].decode(errors="replace")
                     for v in env if v.startswith(b"BLOOMERY_LEASE_CARD=")), None)
        argv = (read("cmdline", mode="rb") or b"").replace(b"\0", b" ").decode(errors="replace").strip()
        return {"pid": pid, "comm": (read("comm") or "?").strip(), "started": started,
                "card": card, "argv": argv[:160]}

    def timing_lease(self, locks):
        """The bloomery timing lease (TIMING_LOCK among the locks the shared-lock probe found
        held): {state: held|unreadable|free, holders, holders_total, record}. `record` is the
        text of <lock>.card, the card the run was taken for. The probe is lease_free's: shared,
        never an exclusive flock -n."""
        for path, state in locks.items():
            if os.path.basename(path) != TIMING_LOCK:
                continue
            out = {"state": state, "path": path, "holders": [], "holders_total": 0, "record": None}
            try:
                with open(path + ".card") as f:
                    out["record"] = f.read(200).strip() or None
            except OSError:
                pass
            if state == "held":
                out["holders"], out["holders_total"] = self.lock_holders(path)
            return out
        return {"state": "free", "holders": [], "holders_total": 0, "record": None}

    def box_lease(self):
        """The rig-log lease file (tools/quiet/lease.sh): "<pid> <reason> <start>". {pid, reason,
        live, raw} or None when there is no file. A dead pid is live=False; the file is
        quiet/lease.sh's to clear, never ours."""
        try:
            with open(self.box_lease_path) as f:
                raw = f.read(400).strip()
        except OSError:
            return None
        if not raw:
            return None
        head, _, rest = raw.partition(" ")
        pid = int(head) if head.isdigit() and int(head) >= 2 else None
        live = False
        if pid:
            try:
                os.kill(pid, 0)
                live = True
            except PermissionError:
                live = True
            except OSError:
                live = False
        return {"pid": pid, "reason": rest, "live": live, "raw": raw, "path": self.box_lease_path}

    def slice_reading(self, unit):
        """One slice's cgroup, from cgroupfs alone (no systemd call): {running, memory_current,
        memory_high, memory_max, anon, file, cpus, procs}. A slice with no unit running has no
        cgroup: running False. Nested names are directories: boxres-round.slice is
        boxres.slice/boxres-round.slice."""
        base = os.path.join(self.cgroup, *ledger.slice_chain(unit))

        def num(fname):
            try:
                text = self._read(base, fname).strip()
            except OSError:
                return None
            return int(text) if text.isdigit() else None
        if not os.path.isdir(base):
            return {"running": False}
        try:
            stat = dict(l.split(None, 1) for l in self._read(base, "memory.stat").splitlines() if " " in l)
        except OSError:
            stat = {}
        try:
            cpus = self._read(base, "cpuset.cpus.effective").strip() or None
        except OSError:
            cpus = None
        try:
            procs = len(self._read(base, "cgroup.procs").split())
        except OSError:
            procs = None
        return {"running": True, "memory_current": num("memory.current"), "memory_high": num("memory.high"),
                "memory_max": num("memory.max"), "anon": int(stat.get("anon", 0)) or None,
                "file": int(stat.get("file", 0)) or None, "cpus": cpus, "procs": procs}

    def snapshot(self, watch):
        """One reading of everything admission and the ledger need, called once a tick with no
        lock held. `watch` is {"owners": [liveness...], "nvme": {drive: dev}, "cards": bool}: the
        grants and jobs whose owners to read, and whether to ask the driver at all (an idle box
        touches no GPU)."""
        s = Snapshot()
        self._unit_deadline = time.monotonic() + self.unit_budget_s
        s.lease, s.locks = self.gpu_lease(), self.bloomery_locks()
        s.timing, s.box_lease = self.timing_lease(s.locks), self.box_lease()
        for unit in watch.get("slices", ()):
            s.slices[unit] = self.slice_reading(unit)
        readings = {}
        for path in self.bloomery_holds():
            owner = self.hold_owner(path)
            reading = None
            if owner is not None:
                key = ("bad", path) if "bad" in owner else owner_key(owner)
                if key not in readings:
                    readings[key] = self.owner_reading(owner)
                reading = readings[key]
            s.holds.append(Hold(path, os.path.basename(path), self.hold_age_s(path), owner, reading))
        try:
            s.mem, s.mem_why = self.meminfo(), None
        except (OSError, ValueError) as e:
            s.mem, s.mem_why = None, str(e)
        if watch.get("cards"):
            s.cards, s.cards_read = self.card_readings(), True
        for live in watch.get("owners", []):
            key = owner_key(live)
            s.owners[key] = readings.get(key) or self.owner_reading(live)
        s.nvme = self.nvme_counters(watch.get("nvme", {}))
        return s


# ---------------------------------------------------------------- reservations

class Reservations:
    """Weekly windows from a JSON file, reloaded when its mtime moves. Box-local time (KST).

    [{"name": "train-13", "days": [0,1,2,3,4,5,6], "start": "13:00", "minutes": 120,
      "cards": ["a6000", "3090"], "owner": "gate-batch"}, ...]
    An active window blocks a card for everyone except its owner; a media job that would
    still be running when a window opens does not start."""

    def __init__(self, path):
        self.path = path
        self._mtime, self._windows, self.cooldown_s = None, [], 120
        self.reload()

    def reload(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self._windows = []
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self._windows = data.get("windows", [])
            self.cooldown_s = int(data.get("cache_cooldown_s", 120))
            self._mtime = mtime
        except (OSError, ValueError) as e:
            log("reservations unreadable (%s): keeping previous" % e)

    def _span(self, w, now, day_offset=0):
        parts = w["start"].split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        base = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
        start = base + timedelta(hours=h, minutes=m)
        return start, start + timedelta(minutes=int(w.get("minutes", 60)))

    def active(self, now, card, owner):
        self.reload()
        for w in self._windows:
            if card not in w.get("cards", list(CARDS)) and w.get("cards") != ["both"]:
                continue
            if w.get("owner") == owner:
                continue
            for off in (0, -1):  # a window started yesterday can still be running
                start, end = self._span(w, now, off)
                if start <= now < end and now.weekday() in w.get("days", list(range(7))):
                    return w
        return None

    def crossed_before(self, now, card, owner, est_end):
        """A window on this card that est_end falls inside: the job must not start."""
        self.reload()
        for w in self._windows:
            if card not in w.get("cards", list(CARDS)) and w.get("cards") != ["both"]:
                continue
            if w.get("owner") == owner:
                continue
            for off in (0, 1):  # today's and tomorrow's starts
                start, end = self._span(w, now, off)
                if start <= est_end < end:
                    return w
        return None


# ---------------------------------------------------------------- runners

class RunnerError(Exception):
    """A runner could not do what was asked. rc is the exit code a job refused for it carries."""

    def __init__(self, msg, rc=70):
        super().__init__(msg)
        self.rc = rc


def unit_of(jid):
    return "sb-%s" % jid


# The daemon's own environment a job unit inherits (a transient unit starts with systemd's
# bare PATH and no HOME); a job's env overrides these. HOME is the daemon user's home from
# passwd: a system service has none in its environment, and ~/ paths in a job need it.
PASS_ENV = ("LANG", "USER")

# Signal names as systemd prints them in $EXIT_STATUS, with their Linux numbers.
SIGNALS = {
    "HUP": 1, "INT": 2, "QUIT": 3, "ILL": 4, "TRAP": 5, "ABRT": 6, "BUS": 7, "FPE": 8,
    "KILL": 9, "USR1": 10, "SEGV": 11, "USR2": 12, "PIPE": 13, "ALRM": 14, "TERM": 15,
    "STKFLT": 16, "CHLD": 17, "CONT": 18, "STOP": 19, "TSTP": 20, "TTIN": 21, "TTOU": 22,
    "URG": 23, "XCPU": 24, "XFSZ": 25, "VTALRM": 26, "PROF": 27, "WINCH": 28, "IO": 29,
    "POLL": 29, "PWR": 30, "SYS": 31,
}


def write_scripts(jobdir, argv):
    """The two scripts of a job unit. <jobdir>/cmd.sh only execs argv, so the unit's main
    process is the job itself and every stop signal reaches it. <jobdir>/post.sh is the
    unit's ExecStopPost: it turns systemd's $EXIT_CODE and $EXIT_STATUS into the rc file
    (exited: the number; killed or dumped: 128 + the signal's number; anything it cannot
    read: 70), through tmp + mv so a reader never sees half a file."""
    rc_file = os.path.join(jobdir, "rc")
    tmp = shlex.quote(rc_file + ".tmp")
    arms = "\n".join("      %s) n=%d;;" % kv for kv in SIGNALS.items())
    post = "\n".join([
        "#!/bin/sh",
        'rc=70',
        'case "$EXIT_CODE" in',
        "  exited)",
        '    case "$EXIT_STATUS" in',
        "      ''|*[!0-9]*) ;;",
        '      *) rc=$EXIT_STATUS;;',
        "    esac;;",
        "  killed|dumped)",
        "    n=",
        '    case "$EXIT_STATUS" in',
        arms,
        "    esac",
        '    [ -n "$n" ] && rc=$((128 + n));;',
        "esac",
        'printf %%s "$rc" > %s && mv %s %s' % (tmp, tmp, shlex.quote(rc_file)),
    ]) + "\n"
    cmd = "#!/bin/bash\nexec %s\n" % " ".join(shlex.quote(a) for a in argv)
    for name, text in (("cmd.sh", cmd), ("post.sh", post)):
        with open(os.path.join(jobdir, name), "w") as f:
            f.write(text)


class PopenRunner:
    """--fake and the tests: the argv as a child of the daemon in its own process group. Stop
    is SIGTERM to that group. It writes <jobdir>/rc when it sees the job end. A restart
    cannot re-adopt such a job, and neither bound_s nor a confinement is enforced."""

    def launch(self, jid, argv, env, jobdir, media, bound_s=None, confine=None, unit_slice=None):
        full = {k: v for k, v in os.environ.items()
                if k not in ("NOTIFY_SOCKET", "WATCHDOG_PID", "WATCHDOG_USEC")}
        full.update(env)
        try:
            with open(os.path.join(jobdir, "out"), "ab") as out, \
                    open(os.path.join(jobdir, "err"), "ab") as err:
                proc = subprocess.Popen(argv, stdout=out, stderr=err,
                                        stdin=subprocess.DEVNULL, start_new_session=True,
                                        env=full, cwd=jobdir)
        except OSError as e:
            raise RunnerError("cannot start %s: %s" % (argv[0], e))
        proc.rc_file = os.path.join(jobdir, "rc")
        return proc

    def stop(self, proc):
        # a leader that has exited and been reaped no longer holds its pgid: never signal it
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def state(self, proc):
        rc = proc.poll()
        if rc is None:
            return "running"
        if not os.path.exists(proc.rc_file):
            with open(proc.rc_file + ".tmp", "w") as f:
                f.write(str(rc))
            os.replace(proc.rc_file + ".tmp", proc.rc_file)
        return ("exited", rc)

    def handle_of(self, job):
        return None

    def describe(self, proc):
        return {"pid": proc.pid}


class UnitHandle:
    def __init__(self, unit, rc_file):
        self.unit, self.rc_file = unit, rc_file


class UnitRunner:
    """Production: one transient unit `sb-<id>` per job. A job outlives the daemon, `systemctl
    stop` reaches every process of the job's tree, and the rc is read from <jobdir>/rc, which
    the unit's ExecStopPost writes even for a job that was killed.
    A unit that declared a need is confined: the cpus the grants leave (AllowedCPUs) and
    MemoryHigh / MemoryMax from its resident need. Any other unit sets no memory property and
    no OOMPolicy: it keeps systemd's own defaults.
    Everything that talks to systemd goes through _run, the one seam tests replace."""

    ACTIVE = UNIT_ACTIVE
    ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    def __init__(self, systemd_run="systemd-run", systemctl="systemctl"):
        self.systemd_run, self.systemctl = systemd_run, systemctl

    def _run(self, argv, timeout=30):
        """(rc, stdout+stderr) of one command; an unrunnable command is a RunnerError."""
        try:
            p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RunnerError("%s: %s" % (argv[0], e))
        return p.returncode, p.stdout

    def _props(self, unit):
        rc, text = self._run([self.systemctl, "show", unit,
                              "-p", "LoadState", "-p", "ActiveState"])
        props = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        if rc != 0 or "ActiveState" not in props or "LoadState" not in props:
            raise RunnerError("systemctl show %s: rc=%d %s" % (unit, rc, text.strip()[:200]))
        return props

    def run_argv(self, jid, env, jobdir, media, bound_s=None, confine=None, unit_slice=None):
        """The systemd-run command line of one job. `confine` is {"cpus": [..], "memory_high":
        bytes, "memory_max": bytes}, each key optional; `unit_slice` the class slice it starts in."""
        for name in env:
            if not self.ENV_NAME.fullmatch(name):
                raise RunnerError("env name %r is not a variable name" % name, rc=64)
        argv = [self.systemd_run, "--unit", unit_of(jid), "--collect", "--quiet",
                "-p", "StandardOutput=append:" + os.path.join(jobdir, "out"),
                "-p", "StandardError=append:" + os.path.join(jobdir, "err"),
                "-p", "WorkingDirectory=" + jobdir,
                "-p", "ExecStopPost=/bin/sh " + shlex.quote(os.path.join(jobdir, "post.sh"))]
        # a media runner's own teardown (trap finish INT TERM) needs the longer stop
        argv += ["-p", "KillMode=mixed", "-p", "TimeoutStopSec=%d" % MEDIA_STOP_S] if media \
            else ["-p", "TimeoutStopSec=%d" % STOP_S]
        if bound_s:
            argv += ["-p", "RuntimeMaxSec=%d" % bound_s]
        if unit_slice:
            argv += ["--slice", unit_slice]
        for key, prop in (("memory_high", "MemoryHigh"), ("memory_max", "MemoryMax")):
            if (confine or {}).get(key):
                argv += ["-p", "%s=%d" % (prop, confine[key])]
        if (confine or {}).get("cpus"):
            argv += ["-p", "AllowedCPUs=" + ledger.fmt_cpus(confine["cpus"])]
        merged = {"HOME": pwd.getpwuid(os.getuid()).pw_dir}
        merged.update({k: os.environ[k] for k in PASS_ENV if k in os.environ})
        merged.update(env)
        for name, value in merged.items():
            argv += ["--setenv", "%s=%s" % (name, value)]
        return argv + ["/bin/bash", os.path.join(jobdir, "cmd.sh")]

    def slice_installed(self, name):
        """Is slice `name`, and every slice a dash in its name puts it inside, a unit file on this
        box? systemd makes an implicit slice with no caps out of any name (LoadState=loaded, no
        FragmentPath), so only the file says it is installed. A RunnerError rc 69 names the slice
        that is not; rc 70 when systemd cannot be asked."""
        for unit in ledger.slice_chain(name):
            rc, text = self._run([self.systemctl, "show", unit, "-p", "LoadState", "-p", "FragmentPath"])
            props = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
            if rc != 0 or "FragmentPath" not in props:
                raise RunnerError("systemctl show %s: rc=%d %s" % (unit, rc, text.strip()[:200]))
            if not props["FragmentPath"]:
                raise RunnerError("slice %s is not installed (systemctl show: LoadState=%s, no FragmentPath)%s: "
                                  "without its unit file it is an implicit slice with no caps; install it from "
                                  "configs/ and daemon-reload"
                                  % (unit, props.get("LoadState"), "" if unit == name else ", and %s is inside it" % name),
                                  rc=69)

    def launch(self, jid, argv, env, jobdir, media, bound_s=None, confine=None, unit_slice=None):
        unit = unit_of(jid)
        rc_file = os.path.join(jobdir, "rc")
        if self._props(unit)["LoadState"] != "not-found":
            raise RunnerError("unit %s exists" % unit, rc=64)
        if os.path.exists(rc_file):
            raise RunnerError("%s exists: job id %s was used before" % (rc_file, jid), rc=64)
        if unit_slice:
            self.slice_installed(unit_slice)
        cmd = self.run_argv(jid, env, jobdir, media, bound_s, confine, unit_slice)
        write_scripts(jobdir, argv)
        rc, text = self._run(cmd)
        if rc != 0:
            raise RunnerError("systemd-run rc=%d: %s" % (rc, text.strip()[:300]))
        return UnitHandle(unit, rc_file)

    def stop(self, handle):
        rc, text = self._run([self.systemctl, "stop", "--no-block", handle.unit])
        # a unit that is already gone has nothing left to stop
        if rc != 0 and self._props(handle.unit)["LoadState"] != "not-found":
            raise RunnerError("systemctl stop %s: rc=%d %s" % (handle.unit, rc, text.strip()[:200]))

    def state(self, handle):
        """"running" while the unit is in any active state (ExecStopPost included), even when rc
        exists: the lane stays busy until the job's whole tree is gone. Then ("exited", rc)
        from the rc file, and "gone" for a unit that left none."""
        props = self._props(handle.unit)
        if props["ActiveState"] in self.ACTIVE:
            return "running"
        try:
            with open(handle.rc_file) as f:
                return ("exited", int(f.read().strip()))
        except FileNotFoundError:
            return "gone"
        except (OSError, ValueError):
            return ("exited", 70)

    def handle_of(self, job):
        return UnitHandle(unit_of(job["id"]), job["rc_file"]) if job.get("rc_file") else None

    def describe(self, handle):
        return {"unit": handle.unit}


# ---------------------------------------------------------------- scheduler

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# A grant is `pending` until its owner is first seen, then `live`; the rest are ended.
GRANT_OPEN = ("pending", "live")
GRANT_ENDED = ("released", "reclaimed", "expired")


def log_files(jobdir):
    """A job's log files in reading order: the merged log of jobs made before stdout and
    stderr were split, then stdout, then stderr."""
    return [os.path.join(jobdir, n) for n in ("log", "argv", "out", "err")]


def read_tail(path, nbytes=None):
    """The file's bytes, or only its last nbytes; b"" when it is not there."""
    try:
        with open(path, "rb") as f:
            if nbytes is not None:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - nbytes))
            return f.read()
    except OSError:
        return b""


Verdict = namedtuple("Verdict", "lane reason external confine", defaults=(None,))


class Scheduler:
    def __init__(self, probes=None, home=HOME, reservations=None, fake=FAKE,
                 now_fn=datetime.now, runner=None, resources=None):
        self.probes = probes or Probes()
        self.runner = runner or PopenRunner()
        self.home = home
        # the ledger's config: capacity, headroom, classes and their ranks (ledger.ConfigError
        # when it cannot be read: main() ends 78 naming it)
        self.res = resources or ledger.load_config(
            RESOURCES or os.path.join(home, "box-resources.json"))
        self.classes = BODY_CLASSES + tuple(self.res.class_priority)
        self.grants = []         # the grants (ledger.normalize_need's needs), live and ended
        self.gseq = 0
        self.decisions = []      # the last admissions, refusals and reclaims, newest last
        self.snap = None         # the last tick's Snapshot: admission answers from it
        self.ram_wait = {}       # queued job id -> (priority, bytes) held only by RAM this tick
        self.stale_seen = set()  # the dead holds already named
        self.over_seen = {}      # holder id -> the over_by last named
        self.idle_since = {}     # card -> when its utilization was first read as 0 % (and not since)
        self.status_seen = {}    # grant id -> the status word last named (overdue, held)
        self.cards_read_at = None  # monotonic time of the last snapshot that asked the driver
        self.reservations = reservations or Reservations(os.path.join(home, "reservations.json"))
        self.fake = fake
        self.now = now_fn
        self.jobs = []
        self.seq = 0
        self.events = []
        self.lock = threading.RLock()
        self.procs = {}          # id -> the runner's handle of a running job
        self.cache_free = {}     # bloomery cache_group -> datetime it last finished
        self.media_cache_free = {}  # the same for media jobs: a group never reaches across
        os.makedirs(os.path.join(home, "jobs"), exist_ok=True)
        self.load()

    # -- persistence --------------------------------------------------------

    def state_path(self):
        return os.path.join(self.home, "state.json")

    def load(self):
        try:
            with open(self.state_path()) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self.seq = data.get("seq", 0)
        self.jobs = data.get("jobs", [])
        self.events = data.get("events", [])[-100:]
        self.grants = data.get("grants", [])
        self.gseq = data.get("gseq", 0)
        self.decisions = data.get("decisions", [])
        for job in self.jobs:
            # a job written before these fields existed still answers with every wire key
            for key in ("out", "err", "rc_file", "resolved_card", "need", "confine", "slice"):
                job.setdefault(key, None)
            job.setdefault("expected_s", self.expected_s_of(job))
            rank = self.res.class_priority.get(job["job_class"])
            if job["status"] == "queued" and rank is not None and job["priority"] != rank:
                # a queued job of a ranked class takes the class's rank as the config has it now
                self.event("job %s (class %s) priority %d -> %d: the config's rank"
                           % (job["id"], job["job_class"], job["priority"], rank))
                job["priority"] = rank
            if job["status"] == "running":
                # a job whose unit is still up, or whose rc file is written, is still ours
                handle = self.runner.handle_of(job)
                if handle is not None:
                    try:
                        alive = self.runner.state(handle) != "gone"
                    except RunnerError as e:
                        log("job %s: cannot ask the runner (%s); kept, reap asks again"
                            % (job["id"], e))
                        alive = True
                    if alive:
                        self.procs[job["id"]] = handle
                        continue
                job["status"] = "lost"
                job["finished"] = iso(self.now())
                self.event("job %s lost (no unit, no rc file)" % job["id"])

    def persist(self):
        live = [g for g in self.grants if g["state"] in GRANT_OPEN]
        ended = [g for g in self.grants if g["state"] not in GRANT_OPEN][-self.res.history:]
        data = {"seq": self.seq, "jobs": self.jobs[-QUEUE_HISTORY:],
                "events": self.events[-100:], "grants": live + ended, "gseq": self.gseq,
                "decisions": self.decisions[-self.res.history:]}
        tmp = self.state_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path())

    def event(self, msg):
        self.events.append("%s %s" % (iso(self.now()), msg))

    def decide(self, kind, text):
        """An admission, refusal, reclaim or ignored hold: in the event list and in /ledger's
        recent decisions."""
        self.decisions.append({"at": iso(self.now()), "kind": kind, "text": text})
        self.event(text)

    # -- submission ---------------------------------------------------------

    def submit(self, spec):
        with self.lock:
            self.seq += 1
            kind = spec.get("kind", "command")
            named = spec.get("job_class", "normal")
            rank = self.res.class_priority
            if named not in self.classes:
                raise ValueError("job_class must be one of %s" % (self.classes,))
            if named in rank and "priority" in spec:
                raise ValueError('job_class %s sets the priority (%d): a body that names a class '
                                 'must not carry "priority"' % (named, rank[named]))
            # a media kind is always class media; its body priority is not read
            job_class = "media" if kind in MEDIA_KINDS else named
            priority = (rank[job_class] if job_class in rank
                        else max(-1000, min(1000, int(spec.get("priority", 0)))))
            need = ledger.normalize_need(spec["need"], "job") if spec.get("need") is not None else None
            expected_min = int(spec.get("expected_min", 0))
            expected_s = spec.get("expected_s")
            if expected_s is None:
                expected_s = max(0, expected_min * 60)
            elif not (isinstance(expected_s, int) and not isinstance(expected_s, bool)
                      and 1 <= expected_s <= EXPECTED_S_MAX):
                raise ValueError("expected_s must be an integer 1..%d" % EXPECTED_S_MAX)
            job = {
                "id": "s%d" % self.seq,
                "owner": spec.get("owner", "anon"),
                "name": spec.get("name") or "job%d" % self.seq,
                "title": spec.get("title", ""),
                "expected_min": expected_min,
                "expected_s": expected_s,
                "kind": kind,
                "job_class": job_class,
                "priority": priority,
                "script": spec.get("script", ""),
                "card": spec.get("card", "a6000"),
                "cache_group": spec.get("cache_group",
                                        "media" if kind in MEDIA_KINDS else ""),
                "env": {str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                "argv": spec.get("argv", ""),
                "bound_s": spec.get("bound_s"),
                "status": "queued",
                "submitted": iso(self.now()),
                "started": None, "finished": None, "rc": None, "sentinel": None,
                "pid": None, "wait_reason": None, "artifacts": [],
                "out": None, "err": None, "rc_file": None, "resolved_card": None,
                "need": need, "confine": None,
            }
            if job["kind"] not in KINDS:
                raise ValueError("kind must be one of %s" % (KINDS,))
            if job["kind"] == "media-take" and job["script"] not in RUNNERS:
                raise ValueError("script must be one of %s" % (sorted(RUNNERS),))
            if job["card"] not in CARD_CHOICES:
                raise ValueError("card must be a6000, 3090, any, both or none")
            if job["kind"] == "media-take" and job["card"] != MEDIA_CARD:
                raise ValueError("media runs on the A6000 only (card %s)" % job["card"])
            if job["kind"] == "comfy-session" and job["card"] not in CARDS:
                raise ValueError("a comfy window holds one card: a6000 or 3090 (card %s)" % job["card"])
            if not re.match(r"^[A-Za-z0-9._-]+$", job["name"]):
                raise ValueError("name must be [A-Za-z0-9._-]+")
            bound = job["bound_s"]
            if bound is not None and not (isinstance(bound, int) and not isinstance(bound, bool)
                                          and 1 <= bound <= BOUND_S_MAX):
                raise ValueError("bound_s must be an integer 1..%d" % BOUND_S_MAX)
            self.jobs.append(job)
            self.persist()
            return job

    def by_id(self, jid):
        """Jobs answer to their id (s12) or their name (the tag the caller chose)."""
        for job in self.jobs:
            if job["id"] == jid:
                return job
        for job in reversed(self.jobs):
            if job["name"] == jid:
                return job
        return None

    def cancel(self, jid):
        with self.lock:
            job = self.by_id(jid)
            if not job:
                return None
            if job["status"] == "queued":
                job["status"], job["finished"] = "cancelled", iso(self.now())
                self.event("job %s cancelled while queued" % jid)
                self.persist()
                return job
            if job["status"] == "running":
                # The runner stops the whole job tree; TERM reaches the media runner's own
                # finish() for its lawful teardown (VRAM wait, lease release-or-keep). The
                # job stays running until reap sees it end.
                self.event("job %s cancel: stop requested" % jid)
                handle = self.procs.get(jid)
                if handle is not None:
                    try:
                        self.runner.stop(handle)
                    except RunnerError as e:
                        self.event("job %s stop failed: %s" % (jid, e))
                        self.persist()
                        return job
                job["cancel_requested"] = True
                self.persist()
                return job
            return job

    # -- dispatch -----------------------------------------------------------

    def running_jobs(self):
        return [j for j in self.jobs if j["status"] == "running"]

    def lane_of(self, job):
        return job.get("resolved_card") or job["card"]

    @staticmethod
    def cards_of(card):
        """The cards a job with this `card` value may hold: the one named, either for `any`,
        both for `both`, none for `none`."""
        if card in CARDS:
            return (card,)
        return CARDS if card in ("any", "both") else ()

    @staticmethod
    def alternatives(card):
        """The sets of cards a job with this `card` value could start on, in the order they
        are tried: `any` is a choice of one card, `both` is one set of two, `none` holds none."""
        if card in CARDS:
            return [(card,)]
        if card == "any":
            return [(c,) for c in CARDS]
        return [CARDS] if card == "both" else [()]

    @staticmethod
    def lane_name(alt):
        return "both" if len(alt) == len(CARDS) else (alt[0] if alt else "none")

    def lanes_held(self, job):
        """The cards a running job holds the lane of."""
        lane = self.lane_of(job)
        if lane == "both":
            return CARDS
        return (lane,) if lane in CARDS else ()

    def lane_busy(self, card):
        return any(card in self.lanes_held(j) for j in self.running_jobs())

    # -- what admission reads: the tick's snapshot, never a probe ------------

    def view_snap(self):
        """The snapshot admission answers from: the last tick's. Before the first tick (a
        scheduler built and asked at once) one is taken here."""
        return self.snap or self.observe(cards=True)

    def watch_list(self, cards):
        """What the next snapshot reads: the liveness of each open grant and the unit of each
        running job that declared a need (its measured use is charged), the nvme drives, and the
        cards when a queued job or a request needs them: a box with nothing queued touches no GPU."""
        owners = [g["liveness"] for g in self.grants if g["state"] in GRANT_OPEN]
        owners += [{"unit": unit_of(j["id"])} for j in self.running_jobs()
                   if j.get("need") and isinstance(self.procs.get(j["id"]), UnitHandle)]
        if cards is None:
            cards = any(j["status"] == "queued" for j in self.jobs) or self.grant_cards_due()
        return {"owners": owners, "nvme": dict(self.res.nvme), "cards": cards,
                "slices": sorted(set(self.res.slices.values()))}

    def grant_cards_due(self):
        """Does an open grant hold a card whose utilization is due a reading? The `held` word needs
        minutes of resolution, so a grant alone makes a tick ask the driver every CARD_POLL_S."""
        if not self.res.idle_card_s or not any(
                g["state"] in GRANT_OPEN and g["need"].get("cards") for g in self.grants):
            return False
        return self.cards_read_at is None or time.monotonic() - self.cards_read_at >= CARD_POLL_S

    def observe(self, cards=None):
        """Take one snapshot with no lock held (the watch list is copied under it) and keep it
        when it is the newest. The tick calls it before it takes the lock; a request that answers
        from the box now calls it with cards=True."""
        with self.lock:
            watch = self.watch_list(cards)
        snap = self.probes.snapshot(watch)
        if self.snap is None or snap.mono >= self.snap.mono:
            self.snap = snap
        if snap.cards_read:
            self.cards_read_at = snap.mono
        return snap

    def lease_reasons(self):
        reasons = []
        lease = self.view_snap().lease
        if lease:
            if lease["live"]:
                reasons.append("gpu-lease held by %s (pid %s)" % (lease["tag"], lease["pid"]))
            elif self.probes.clear_stale_lease(lease):
                self.event("cleared stale gpu-lease: %s (pid %s dead)"
                           % (lease["tag"], lease["pid"]))
        return reasons

    @staticmethod
    def lease_text(t):
        """One line for the timing lease's holder: pid, comm, the card file, how long it has run,
        and the lease's own card record."""
        rec = "; record %s" % t["record"] if t.get("record") else ""
        if not t["holders"]:
            return "%s is held; no process with it locked was found%s" % (TIMING_LOCK, rec)
        h = t["holders"][0]
        up = ", up %d s" % max(0, time.time() - h["started"]) if h.get("started") else ""
        more = " and %d more" % (t["holders_total"] - 1) if t["holders_total"] > 1 else ""
        return "pid %d %s%s%s%s%s" % (h["pid"], h["comm"],
                                      " (card file %s)" % h["card"] if h.get("card") else "", up, more, rec)

    def quiet_reason(self, snap):
        """Why the box must be quiet now, or None: a sitting's grant is up, the bloomery timing
        lease (the shared lock probe found it held, or could not test it) or a live rig-log lease.
        An IO-heavy grant (nvme bulk) is refused while it stands."""
        sitting = next((g for g in self.grants if g["state"] in GRANT_OPEN and g["class"] == "sitting"), None)
        if sitting:
            return "sitting grant %s (%s) is up" % (sitting["id"], sitting["holder"])
        t = snap.timing
        if t["state"] == "held":
            return "the timing lease is held by " + Scheduler.lease_text(t)
        if t["state"] == "unreadable":
            return "the timing lease %s cannot be tested" % TIMING_LOCK
        if snap.box_lease and snap.box_lease["live"]:
            return "the rig-log lease is held by pid %d (%s)" % (snap.box_lease["pid"], snap.box_lease["reason"])
        return None

    @staticmethod
    def hold_state(hold):
        """(up|dead|unknown, why) of a hold: `dead` when the owner it names is gone (the hold is
        ignored), `unknown` when it names one that could not be asked (it stays up, named),
        `up` when it names none or the owner is running."""
        if hold.reading is None:
            return "up", "no owner recorded"
        r = hold.reading
        return ("up" if r["state"] == "alive" else r["state"]), r["why"]

    def grant_of_hold(self, name):
        """The open grant a hold file stands behind: the hold is its (the toktape's)."""
        return next((g for g in self.grants if g["state"] in GRANT_OPEN and g.get("hold") == name), None)

    def hold_reasons(self, job=None):
        """Why the holds up now block `job`. A hold whose owner is dead blocks nothing (settle
        names it). A hold that stands behind an open grant does not block a job that declared a
        need: need_reasons decides whether that need fits beside the grants."""
        reasons = []
        for hold in self.view_snap().holds:
            state, why = self.hold_state(hold)
            if state == "dead":
                continue
            grant = self.grant_of_hold(hold.name)
            if grant and job is not None and job.get("need"):
                continue
            text = "hold %s up %s" % (hold.name, "%d s" % hold.age_s if hold.age_s is not None
                                      else "(age unknown)")
            if state == "unknown":
                text += " (its owner cannot be asked: %s)" % why
            if grant:
                text += " (grant %s %s: a job that declared no need waits)" % (grant["id"], grant["holder"])
            reasons.append(text)
        return reasons

    def host_reasons(self, job=None):
        """Why a job that holds no card may not start: the timing lease and a bloomery hold
        are a quiet machine's; a host build disturbs it."""
        return self.lease_reasons() + self.hold_reasons(job)

    def card_text(self, card):
        """A card above the VRAM line, or one that cannot be read, with whatever the snapshot
        says holds it: the compute apps' units, named as a grant or a job when they are one."""
        c = self.view_snap().cards.get(card) or {"state": "unreadable", "why": "not read this tick",
                                                 "used_mib": 1 << 30, "apps": []}
        if c["state"] != "ok":
            return "card %s %s (%s)" % (card, c["state"], c["why"])
        if c["used_mib"] < VRAM_IDLE_MIB:
            return None
        who = []
        for app in c["apps"]:
            unit = app.get("unit")
            grant = next((g for g in self.grants if g["state"] in GRANT_OPEN
                          and g["liveness"].get("unit") == unit), None) if unit else None
            job = next((j for j in self.running_jobs() if unit == unit_of(j["id"]) + ".service"), None) \
                if unit else None
            name = ("grant %s %s" % (grant["id"], grant["holder"]) if grant
                    else "job %s %s" % (job["id"], job["name"]) if job else unit or "an unlisted unit")
            who.append("pid %d in %s" % (app["pid"], name))
        return "card %s above %d MiB (%d MiB used%s)" % (
            card, VRAM_IDLE_MIB, c["used_mib"], "; " + ", ".join(who) if who else "")

    def card_reasons(self, card, owner, job=None):
        """Hardware+lease+reservation reasons this card may not take a job now."""
        reasons = self.lease_reasons()
        for path, state in self.view_snap().locks.items():
            if card in LOCK_CARDS.get(os.path.basename(path), CARDS):
                reasons.append("%s: %s" % (os.path.basename(path), state))
        reasons += self.hold_reasons(job)
        text = self.card_text(card)
        if text:
            reasons.append(text)
        w = self.reservations.active(self.now(), card, owner)
        if w:
            reasons.append("reservation %s active until later (owner %s)"
                           % (w.get("name"), w.get("owner")))
        return reasons

    # -- the ledger -----------------------------------------------------------

    def ledger_rows(self, snap):
        """The holders: every open grant, and every running job that declared a need."""
        rows = []
        for g in self.grants:
            if g["state"] not in GRANT_OPEN:
                continue
            reading = snap.owners.get(owner_key(g["liveness"])) or {}
            word, why = self.grant_status(g)
            rows.append({"id": g["id"], "kind": "grant", "holder": g["holder"], "klass": g["class"],
                         "owner": g.get("owner"), "since": g["since"],
                         "unit": g["liveness"].get("unit") or "pid %d" % g["liveness"]["pid"],
                         "need": g["need"], "state": g["state"],
                         "measured": reading.get("measured"), "text": reading.get("why"),
                         "status": word, "status_why": why, "age_s": self.grant_age_s(g),
                         "expected_s": g.get("expected_s"), "bound_s": g.get("bound_s")})
        for j in self.running_jobs():
            if not j.get("need"):
                continue
            reading = snap.owners.get(("unit", unit_of(j["id"]))) or {}
            rows.append({"id": j["id"], "kind": "job", "holder": j["name"], "klass": j["job_class"],
                         "owner": j["owner"], "since": j["started"], "unit": unit_of(j["id"]),
                         "need": j["need"], "state": "running",
                         "measured": reading.get("measured"), "text": reading.get("why")})
        return rows

    def grant_age_s(self, grant):
        """Seconds a live grant has run (from the tick its owner was first seen); None while it
        is pending."""
        if grant["state"] != "live" or not grant.get("seen"):
            return None
        return max(0, int((self.now() - datetime.fromisoformat(grant["seen"])).total_seconds()))

    def grant_status(self, grant):
        """(word, why) of an open grant: `overdue` past overdue_factor x its expected_s, `held` when
        a card it holds has read 0 % utilization for idle_card_s; else ("ok", None). It names, never
        stops: the unit's RuntimeMaxSec (boxres run --bound) is what stops a run."""
        age, said, words = self.grant_age_s(grant), [], []
        exp, factor = grant.get("expected_s"), self.res.overdue_factor
        if age is not None and exp and factor and age > factor * exp:
            words.append("overdue")
            said.append("running %d s, expected %d s (x%d = %d s)%s" % (
                age, exp, factor, factor * exp,
                "; its bound is %d s" % grant["bound_s"] if grant.get("bound_s") else ""))
        if age is not None and self.res.idle_card_s:
            for card in grant["need"].get("cards", []):
                since = self.idle_since.get(card)
                idle = (self.now() - since).total_seconds() if since else 0
                if since and idle >= self.res.idle_card_s:
                    words.append("held")
                    said.append("card %s has read 0 %% utilization for %d s while this grant holds it"
                                % (card, idle))
                    break
        if not words:
            return "ok", None
        return ("overdue" if "overdue" in words else "held"), "; ".join(said)

    def held_back(self, priority):
        """Bytes the queued jobs of a higher priority wait for, held only by RAM: no lower job or
        grant takes them (the sitting barrier, for RAM)."""
        return sum(b for p, b in self.ram_wait.values() if p > priority)

    def ledger_now(self, priority=None):
        snap = self.view_snap()
        return ledger.Ledger(self.res, snap.mem, snap.mem_why, self.ledger_rows(snap),
                             held_back=self.held_back(priority) if priority is not None else 0,
                             quiet=self.quiet_reason(snap))

    def need_reasons(self, job, alt):
        """What the ledger says against this job on these cards: a card a grant holds (every job),
        and for a job that declared a need, RAM and cpus beside the grants. Outside the queue, so
        the eta of a job held here is unknown."""
        led = self.ledger_now(job["priority"])
        reasons = []
        for c in alt:
            if c in led.cards_held:
                g = next(g for g in self.grants if g["id"] == led.cards_held[c])
                reasons.append("card %s is held by grant %s (%s %s, unit %s)"
                               % (c, g["id"], g["class"], g["holder"], g["liveness"].get("unit", "pid")))
        need = job.get("need")
        if not need:
            return reasons
        for r in led.check(need, "job"):
            row = led.by_id(r.holder)
            reasons.append(r.text + (" — held by " + led.holder_text(row) if row else ""))
        left = led.cpu_free()
        if led.exclusive_cpus and not left:
            reasons.append("cpus: none left beside grants %s" % ", ".join(sorted(led.exclusive_cpus)))
        elif need.get("cpus") and len(left) < need["cpus"]:
            reasons.append("cpus: needs %d, %d left beside grants %s"
                           % (need["cpus"], len(left), ", ".join(sorted(led.exclusive_cpus))))
        return reasons

    def ram_short(self, job):
        """Does the ledger refuse this job's RAM now?"""
        led = self.ledger_now(job["priority"])
        return any(r.resource == "ram" for r in led.check(job["need"], "job"))

    def confine_for(self, job):
        """What a job that declared a need is confined to: the cpus the grants leave, and the
        memory caps of its resident need. None for a job with no need."""
        need = job.get("need")
        if not need:
            return None
        led = self.ledger_now()
        confine = {}
        if led.exclusive_cpus:
            confine["cpus"] = led.cpu_free()
        total = ledger.declared_total(need)
        if total:
            confine.update(ledger.limits_of(self.res, total))
        return confine or None

    @staticmethod
    def expected_s_of(job):
        return job.get("expected_s") or max(0, job.get("expected_min", 0) * 60)

    def sitting_ahead(self, job):
        """A queued sitting of higher priority: the drain barrier in front of this job."""
        return next((q for q in self.jobs if q["status"] == "queued"
                     and q["job_class"] == "sitting" and q["priority"] > job["priority"]), None)

    def media_queued_for(self, q, cards, job):
        """Is q a queued media job for one of these cards, that goes before `job`? Media goes
        before every job of its own priority or lower; a sitting is above it and does not wait
        for it."""
        return (q["status"] == "queued" and q["job_class"] == "media"
                and q["priority"] >= job["priority"]
                and bool(set(self.cards_of(q["card"])) & set(cards)))

    def media_ahead(self, job, cards):
        """A queued media job for one of these cards, which holds every other job of its
        priority or lower off them. An exclusive job takes every card once it starts, whichever
        card it names."""
        if job["job_class"] == "media":
            return None
        if job["job_class"] in EXCLUSIVE_CLASSES:
            cards = CARDS
        return next((q for q in self.jobs
                     if q is not job and self.media_queued_for(q, cards, job)), None)

    def cache_holds(self, job, now):
        """What the cache groups hold this job back for: ("running", job) for a job of another
        group on the same side, ("cooling", group, age, cooldown) for one that left age seconds
        ago. Media jobs are one side and every other job the other; a group never reaches
        across."""
        if not job["cache_group"]:
            return
        media = job["job_class"] == "media"
        for r in self.running_jobs():
            if ((r["job_class"] == "media") == media and r["cache_group"]
                    and r["cache_group"] != job["cache_group"]):
                yield "running", r
        cool = self.reservations.cooldown_s
        for group, freed in list((self.media_cache_free if media else self.cache_free).items()):
            age = (now - freed).total_seconds()
            if group != job["cache_group"] and 0 <= age < cool:
                yield "cooling", group, age, cool

    def alt_reasons(self, job, alt, now):
        """External reasons the job may not start on this set of cards. The --fake rehearsal
        skips the hardware probes, a fake *job* does not: a scheduler smoke on the box must
        still meet the real lease and locks. A job is also held back from a window it could
        not finish before; one with no estimate is the caller's reckoning."""
        if not alt:
            return ([] if self.fake else self.host_reasons(job)) + self.need_reasons(job, alt)
        reasons = [] if self.fake else list(dict.fromkeys(
            r for c in alt for r in self.card_reasons(c, job["owner"], job)))
        reasons += self.need_reasons(job, alt)
        if not reasons and self.expected_s_of(job) > 0:
            est_end = now + timedelta(seconds=self.expected_s_of(job))
            for c in alt:
                w = self.reservations.crossed_before(now, c, job["owner"], est_end)
                if w:
                    return ["would cross reservation %s (owner %s)"
                            % (w.get("name"), w.get("owner"))]
        return reasons

    def admit(self, job):
        """Verdict(lane, reason, external): the lane (a6000, 3090, both or none) the job may
        start on now, else why it may not. `external` lists the card sets whose blocker is
        outside the queue (lease, lock, hold, VRAM, reservation)."""
        now = self.now()
        running = self.running_jobs()
        if job["job_class"] in EXCLUSIVE_CLASSES and running:
            return Verdict(None, "class %s waits for an empty box" % job["job_class"], ())
        owner = next((r for r in running if r["job_class"] in EXCLUSIVE_CLASSES), None)
        if owner:
            return Verdict(None, "a %s job owns the box" % owner["job_class"], ())
        sitting = self.sitting_ahead(job)
        if sitting:
            return Verdict(None, "sitting %s is queued: no job of lower priority starts first"
                           % sitting["name"], ())
        alts = self.alternatives(job["card"])
        texts, open_alts = {}, []
        for alt in alts:
            if any(self.lane_busy(c) for c in alt):
                texts[alt] = "lanes busy"
                continue
            media = self.media_ahead(job, alt)
            if media:
                texts[alt] = "media job %s is queued for %s" % (media["name"], media["card"])
            else:
                open_alts.append(alt)
        if not open_alts:
            return Verdict(None, self.blocked_text(alts, texts), ())
        # cache warmth: a different group running, or one that just left (the GLM load that
        # evicts 186 GB of page cache and makes the next sitting cold — box-calendar law)
        for hold in self.cache_holds(job, now):
            if hold[0] == "running":
                return Verdict(None, "cache group %s running" % hold[1]["cache_group"], ())
            return Verdict(None, "cache group %s left %.0f s ago (cooldown %d s)"
                           % (hold[1], hold[2], hold[3]), ())
        external = []
        for alt in open_alts:
            reasons = self.alt_reasons(job, alt, now)
            if not reasons:
                return Verdict(self.lane_name(alt), None, (), self.confine_for(job))
            texts[alt] = "; ".join(reasons)
            external.append(alt)
        return Verdict(None, self.blocked_text(alts, texts), tuple(external))

    def blocked_text(self, alts, texts):
        """The wait reason of a job every alternative of which is blocked: the one text when
        they agree or there is one, else each card's own."""
        if len(alts) == 1 or len(set(texts.values())) == 1:
            return texts[alts[0]]
        return " | ".join("%s: %s" % (self.lane_name(a), texts[a]) for a in alts)

    def can_start(self, job):
        """(lane, None) when the job may start on that lane now, else (None, reason)."""
        verdict = self.admit(job)
        return verdict.lane, verdict.reason

    def build_cmd(self, job, jobdir):
        """(argv, env additions). Env flows only through what is returned here."""
        if job["kind"] == "fake":
            return ["bash", "-c", "sleep %s; echo FAKE_DONE" % job["env"].get("SLEEP", "3")], {}
        if job["kind"] == "command":
            return ["bash", "-c", job["argv"]], dict(job["env"])
        if job["kind"] == "comfy-session":
            snap = os.path.join(jobdir, "comfy-session.sh")
            shutil.copyfile(COMFY_SESSION, snap)
            env = {k: v for k, v in job["env"].items() if k in ("CARD", "PORT", "TS_SERVE")}
            minutes = job["env"].get("MINUTES", job["expected_min"] or 0)
            return ["bash", snap, "run", job["name"], str(minutes)], env
        # media-take: a snapshot of the runner, the tag as $1, everything else env
        src = RUNNERS[job["script"]]
        if not os.path.exists(src):
            raise RuntimeError("runner missing on the box: %s" % src)
        snap = os.path.join(jobdir, "runner.sh")
        shutil.copyfile(src, snap)
        env = dict(job["env"])
        env.setdefault("TAG", job["name"])
        return ["bash", snap, job["name"]], env

    def start(self, job, card, confine=None):
        """Start the job on lane `card` (a6000, 3090, both or none): the lane is in its
        environment as SIGNALBOX_CARD, whatever the body set. `confine` is what a job that
        declared a need is held to (its unit's AllowedCPUs and memory caps)."""
        jobdir = os.path.abspath(os.path.join(self.home, "jobs", job["id"]))
        os.makedirs(jobdir, exist_ok=True)
        try:
            cmd, extra_env = self.build_cmd(job, jobdir)
        except Exception as e:
            job["status"], job["finished"] = "failed", iso(self.now())
            job["rc"], job["sentinel"] = 64, str(e)
            self.event("job %s refused build: %s" % (job["id"], e))
            return
        extra_env["SIGNALBOX_CARD"] = card
        job.update(out=os.path.join(jobdir, "out"), err=os.path.join(jobdir, "err"),
                   rc_file=os.path.join(jobdir, "rc"))
        # the command line goes beside the job's output, never into it: out is the job's stdout only
        with open(os.path.join(jobdir, "argv"), "ab") as f:
            f.write(("[%s] argv: %s\n" % (iso(self.now()), " ".join(cmd))).encode())
        unit_slice = self.res.slices.get(job["job_class"])
        try:
            handle = self.runner.launch(job["id"], cmd, extra_env, jobdir,
                                        job["kind"] in MEDIA_KINDS, bound_s=job.get("bound_s"),
                                        confine=confine, unit_slice=unit_slice)
        except RunnerError as e:
            job["status"], job["finished"] = "failed", iso(self.now())
            job["rc"], job["sentinel"] = e.rc, str(e)
            self.event("job %s refused launch: %s" % (job["id"], e))
            return
        where = self.runner.describe(handle)
        job.update(status="running", started=iso(self.now()), resolved_card=card,
                   wait_reason=None, confine=confine, slice=unit_slice, **where)
        self.procs[job["id"]] = handle
        self.event("job %s started on %s (%s)%s%s"
                   % (job["id"], card, ", ".join("%s %s" % kv for kv in where.items()),
                      " in slice %s" % unit_slice if unit_slice else "",
                      " confined to cpus %s, memory max %s" % (
                          ledger.fmt_cpus(confine["cpus"]) if confine.get("cpus") else "all",
                          ledger.gb(confine["memory_max"]) if confine.get("memory_max") else "unset")
                      if confine else ""))

    def sentinel_of(self, job, jobdir):
        if job["kind"] != "media-take":
            return None
        want = SENTINELS.get(job["script"], ())
        # each file's own tail, so a long stderr cannot push a stdout sentinel out of view
        tails = [read_tail(p, 8192).decode(errors="replace") for p in log_files(jobdir)]
        for s in want:
            if any(s in t for t in tails):
                return s
        return None

    def artifacts_of(self, job):
        out = []
        if job["kind"] == "media-take":
            base = os.path.join(ARTIFACT_DIRS.get(job["script"], "/tmp"), job["name"])
            try:
                for name in sorted(os.listdir(base)):
                    p = os.path.join(base, name)
                    if os.path.isfile(p):
                        out.append({"path": p, "bytes": os.path.getsize(p)})
            except OSError:
                pass
        return out

    def reap(self):
        for job in list(self.running_jobs()):
            jid = job["id"]
            handle = self.procs.get(jid)
            try:
                st = self.runner.state(handle) if handle is not None else "gone"
            except RunnerError as e:
                log("job %s: cannot ask the runner (%s); asked again next tick" % (jid, e))
                continue
            if st == "running":
                continue
            jobdir = os.path.join(self.home, "jobs", jid)
            rc = None if st == "gone" else st[1]
            job["rc"] = rc
            job["sentinel"] = self.sentinel_of(job, jobdir)
            job["artifacts"] = self.artifacts_of(job)
            if job.pop("cancel_requested", False):
                job["status"] = "cancelled"
            elif st == "gone":
                # no unit and no rc file: how it ended is unknowable
                job["status"] = "lost"
            elif job["kind"] == "media-take":
                done_sentinel = SENTINELS.get(job["script"], ("?", "?"))[0]
                job["status"] = "done" if (rc == 0 and job["sentinel"] == done_sentinel) else "failed"
            else:
                job["status"] = "done" if rc == 0 else "failed"
            job["finished"] = iso(self.now())
            if job["cache_group"]:
                freed = self.media_cache_free if job["job_class"] == "media" else self.cache_free
                freed[job["cache_group"]] = self.now()
            self.procs.pop(jid, None)
            self.event("job %s %s rc=%s sentinel=%s" % (jid, job["status"], rc, job["sentinel"]))

    # -- grants ---------------------------------------------------------------

    def settle(self, snap):
        """Once a tick, under the lock, from the snapshot: a grant whose owner died is reclaimed
        and one whose owner never appeared is expired, each named; a hold whose owner is dead is
        named once; a holder that measures past its need is named `over`."""
        now = self.now()
        for grant in self.grants:
            if grant["state"] not in GRANT_OPEN:
                continue
            reading = snap.owners.get(owner_key(grant["liveness"]))
            if reading is None:        # posted after this snapshot's watch list: next tick
                continue
            if reading["state"] == "alive":
                if grant["state"] == "pending":
                    grant["state"], grant["seen"] = "live", iso(now)
            elif reading["state"] == "dead":
                if grant["state"] == "live":
                    self.end_grant(grant, "reclaimed", "owner is dead: " + reading["why"])
                elif (now - datetime.fromisoformat(grant["since"])).total_seconds() > self.res.appear_s:
                    self.end_grant(grant, "expired", "its owner did not appear within %d s: %s"
                                   % (self.res.appear_s, reading["why"]))
        if snap.cards_read:
            for card, c in snap.cards.items():
                if c.get("state") == "ok" and c.get("util") == 0:
                    self.idle_since.setdefault(card, now)
                else:
                    self.idle_since.pop(card, None)
        for grant in self.grants:
            if grant["state"] not in GRANT_OPEN:
                continue
            word, why = self.grant_status(grant)
            if word == "ok":
                self.status_seen.pop(grant["id"], None)
            elif self.status_seen.get(grant["id"]) != word:
                self.status_seen[grant["id"]] = word
                self.decide(word, "grant %s (%s %s) is %s: %s" % (grant["id"], grant["class"],
                                                                  grant["holder"], word, why))
        dead = {}
        for hold in snap.holds:
            if self.hold_state(hold)[0] == "dead":
                dead[(hold.name, repr(hold.owner))] = hold
        for key, hold in dead.items():
            if key not in self.stale_seen:
                self.decide("ignored", "hold %s ignored: its owner is dead (%s)"
                            % (hold.name, hold.reading["why"]))
        self.stale_seen = set(dead)
        led = ledger.Ledger(self.res, snap.mem, snap.mem_why, self.ledger_rows(snap))
        for row in led.rows:
            if row["over_by"] <= 0:
                self.over_seen.pop(row["id"], None)
                continue
            last = self.over_seen.get(row["id"], 0)
            if row["over_by"] > last + max(ledger.GB, last // 10):
                self.over_seen[row["id"]] = row["over_by"]
                self.decide("over", "%s %s (%s) is over its need by %s: declared %s, measures %s, "
                            "charged %s" % (row["kind"], row["id"], row["holder"],
                                            ledger.gb(row["over_by"]), ledger.gb(row["declared"]),
                                            ledger.gb(row["measured_total"]), ledger.gb(row["charge"])))

    def end_grant(self, grant, state, why):
        grant.update(state=state, ended=iso(self.now()), ended_why=why)
        self.over_seen.pop(grant["id"], None)
        self.status_seen.pop(grant["id"], None)
        self.decide(state, "grant %s (%s %s) %s: %s" % (grant["id"], grant["class"], grant["holder"],
                                                        state, why))

    def grant_view(self, grant):
        """The grant with the caps its unit takes (`limits`: MemoryHigh, MemoryMax) and, while it is
        open, the cpus it runs on (`confine`): its own explicit set, else what the exclusive sets of
        the other grants leave, else none (the unit keeps its slice's cpus)."""
        view = dict(grant)
        view["limits"] = ledger.limits_of(self.res, ledger.declared_total(grant["need"]))
        if grant["state"] in GRANT_OPEN:
            led = self.ledger_now()
            cpus = grant["need"].get("cpus") or (led.cpu_free() if led.exclusive_cpus else [])
            if cpus:
                view["confine"] = {"cpus": ledger.fmt_cpus(cpus)}
        return view

    def parse_grant(self, body):
        """The checked pieces of a POST /grants body, or a ValueError that names the field."""
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        extra = sorted(set(body) - {"holder", "class", "need", "liveness", "hold", "owner",
                                    "expected_s", "bound_s"})
        if extra:
            raise ValueError("the body has fields a grant does not take: %s" % ", ".join(extra))
        holder = body.get("holder")
        if not isinstance(holder, str) or not ledger.NAME_RE.fullmatch(holder):
            raise ValueError("holder must be a name [A-Za-z0-9._-]+")
        klass = body.get("class")
        if klass not in self.res.class_priority:
            raise ValueError("class must be one of %s" % (tuple(self.res.class_priority),))
        need = ledger.normalize_need(body.get("need"), "grant")
        for card in need["cards"]:
            if card not in CARDS:
                raise ValueError("need.cards: %r is not a card (%s)" % (card, ", ".join(CARDS)))
        for drive in need["nvme"]:
            if drive not in self.res.nvme:
                raise ValueError("need.nvme: %r is not a drive (%s)" % (drive, ", ".join(self.res.nvme)))
        outside = [c for c in need["cpus"] if c not in self.res.cpus]
        if outside:
            raise ValueError("need.cpus %s are not cpus of the box (%s)"
                             % (ledger.fmt_cpus(outside), ledger.fmt_cpus(self.res.cpus)))
        live = body.get("liveness")
        if isinstance(live, dict) and set(live) == {"unit"} and isinstance(live["unit"], str) \
                and ledger.UNIT_RE.fullmatch(live["unit"]):
            liveness = {"unit": live["unit"]}
        elif isinstance(live, dict) and set(live) == {"pid", "start"} and all(
                isinstance(live[k], int) and not isinstance(live[k], bool) for k in live) \
                and live["pid"] >= 2 and live["start"] >= 0:
            liveness = {"pid": live["pid"], "start": live["start"]}
        else:
            raise ValueError('liveness must be {"unit": "name.scope"} or {"pid": N (>= 2), '
                             '"start": field 22 of /proc/N/stat}: a grant lives as long as its owner')
        hold = body.get("hold")
        if hold is not None and not (isinstance(hold, str) and ledger.NAME_RE.fullmatch(hold)):
            raise ValueError("hold must be the name of the hold file the grant stands behind")
        expected = body.get("expected_s")
        if expected is not None and not (isinstance(expected, int) and not isinstance(expected, bool)
                                         and 1 <= expected <= EXPECTED_S_MAX):
            raise ValueError("expected_s must be an integer 1..%d" % EXPECTED_S_MAX)
        bound = body.get("bound_s")
        if bound is not None and not (isinstance(bound, int) and not isinstance(bound, bool)
                                      and 1 <= bound <= BOUND_S_MAX):
            raise ValueError("bound_s must be an integer 1..%d (the unit's RuntimeMaxSec)" % BOUND_S_MAX)
        owner = body.get("owner", holder)
        if not isinstance(owner, str) or not ledger.NAME_RE.fullmatch(owner):
            raise ValueError("owner must be a name [A-Za-z0-9._-]+")
        return holder, klass, need, liveness, hold, expected, owner, bound

    def grant_create(self, body):
        """POST /grants: (http status, body). 201 with the grant and its limits; 409 rc 75 with the
        refusal lines (RAM, cards, cpus, nvme) naming the holders and the numbers; 503 rc 69 when
        memory cannot be read; a ValueError (400, rc 64) for a body
        that is not a grant. One lock holds the check and the record: two requests on one tick
        cannot both fit."""
        holder, klass, need, liveness, hold, expected, owner, bound = self.parse_grant(body)
        self.observe(cards=True)        # every probe before the lock: the answer is the box now
        with self.lock:
            twin = next((g for g in self.grants if g["state"] in GRANT_OPEN
                         and owner_key(g["liveness"]) == owner_key(liveness)), None)
            if twin:
                raise ValueError("that liveness already holds grant %s (%s)" % (twin["id"], twin["holder"]))
            priority = self.res.class_priority[klass]
            led = self.ledger_now(priority)
            refusals = led.check(need, "grant")
            lost = []
            if not self.fake:
                for card in need["cards"]:
                    c = self.view_snap().cards.get(card)
                    if c and c["state"] != "ok":
                        lost.append(ledger.Refusal("card-lost.%s" % card, "card.%s is %s (%s)"
                                                   % (card, c["state"], c["why"]), None))
                        continue
                    if self.lane_busy(card):
                        job = next(j for j in self.running_jobs() if card in self.lanes_held(j))
                        refusals.append(ledger.Refusal("card.%s" % card, "card.%s: lane busy with job "
                                        "%s (%s, class %s, owner %s)" % (card, job["id"], job["name"],
                                                                       job["job_class"], job["owner"]), None))
                    for reason in dict.fromkeys(self.card_reasons(card, owner)):
                        refusals.append(ledger.Refusal("card.%s" % card, "card.%s: %s" % (card, reason), None))
            refusals = lost + refusals
            if refusals:
                blind = [r for r in refusals if r.resource == "ram-blind" or r.resource.startswith("card-lost.")]
                lines = [led.line(holder, klass, r) for r in refusals]
                if blind:
                    lines[0] = "boxres: %s (class %s) refused rc 69: %s" % (holder, klass, blind[0].text)
                self.decide("refused", lines[0] + (" (+%d more)" % (len(lines) - 1) if len(lines) > 1 else ""))
                self.persist()
                if blind:
                    return 503, {"error": lines[0], "rc": 69, "refusals": lines}
                return 409, {"error": lines[0], "rc": 75, "refusals": lines}
            self.gseq += 1
            grant = {"id": "g%d" % self.gseq, "holder": holder, "class": klass, "owner": owner,
                     "need": need, "liveness": liveness, "hold": hold, "expected_s": expected,
                     "bound_s": bound, "state": "pending", "since": iso(self.now()), "seen": None, "ended": None,
                     "ended_why": None}
            self.grants.append(grant)
            self.decide("admitted", "grant %s (%s %s) admitted: ram %s, cards %s, cpus %s, nvme %s"
                        % (grant["id"], klass, holder, ledger.gb(ledger.declared_total(need)),
                           ",".join(need["cards"]) or "-", ledger.fmt_cpus(need["cpus"]) or "-",
                           ",".join("%s:%s" % kv for kv in need["nvme"].items()) or "-"))
            self.persist()
            return 201, self.grant_view(grant)

    def grant_release(self, gid):
        """DELETE /grants/<id>: the grant ends (idempotent for one that has ended); None for an
        id no grant has."""
        with self.lock:
            grant = next((g for g in self.grants if g["id"] == gid), None)
            if grant is None:
                return None
            if grant["state"] in GRANT_OPEN:
                self.end_grant(grant, "released", "released by request")
                self.persist()
            return self.grant_view(grant)

    def ledger_view(self, recent=20):
        """GET /ledger: the holders with their needs, measured use and charge, the headroom, the
        cards, the holds, the leases, the class slices and why each job waits. `recent` is how many
        of the last decisions to list (at most the config's history)."""
        self.observe(cards=True)
        with self.lock:
            snap = self.view_snap()
            led = ledger.Ledger(self.res, snap.mem, snap.mem_why, self.ledger_rows(snap))
            view = led.view()
            view.update(at=iso(self.now()), snapshot_age_s=round(time.monotonic() - snap.mono, 1),
                        config=self.res.path)
            view["cards"] = {}
            for card in CARDS:
                c = snap.cards.get(card) or {}
                holder = led.cards_held.get(card)
                view["cards"][card] = {
                    "state": c.get("state"), "used_mib": c.get("used_mib"),
                    "total_mib": c.get("total_mib"), "apps": c.get("apps", []),
                    "grant": holder, "lane_busy": self.lane_busy(card),
                    "reasons": self.card_reasons(card, owner=None)}
            view["holds"] = []
            for hold in snap.holds:
                state, why = self.hold_state(hold)
                grant = self.grant_of_hold(hold.name)
                view["holds"].append({"name": hold.name, "age_s": hold.age_s, "owner": hold.owner,
                                      "state": state, "why": why,
                                      "grant": grant["id"] if grant else None})
            view["waiters"] = [{"id": j["id"], "name": j["name"], "class": j["job_class"],
                                "owner": j["owner"], "card": j["card"], "need": j.get("need"),
                                "why": j["wait_reason"]}
                               for j in self.jobs if j["status"] == "queued"]
            view["ended"] = [{k: g.get(k) for k in ("id", "holder", "class", "state", "since",
                                                    "ended", "ended_why")}
                             for g in self.grants[-self.res.history:] if g["state"] in GRANT_ENDED]
            view["recent"] = self.decisions[-max(1, min(recent, self.res.history)):]
            t = snap.timing
            view["lease"] = {
                "timing": dict(t, text=self.lease_text(t) if t["state"] == "held" else None),
                "box_lease": snap.box_lease,
                "quiet": self.quiet_reason(snap),
            }
            view["slices"] = {klass: dict(snap.slices.get(unit, {"running": False}), unit=unit)
                              for klass, unit in self.res.slices.items()}
            return view

    def tick(self):
        self.observe()                # every probe, once, before the lock is taken
        with self.lock:
            self.reap()
            self.settle(self.snap)
            # priority-first: higher priority wins a free lane, ties by arrival
            queued = sorted((j for j in self.jobs if j["status"] == "queued"),
                            key=lambda j: (-j["priority"], j["submitted"]))
            self.ram_wait = {}
            for job in queued:
                verdict = self.admit(job)
                if verdict.lane is None:
                    if verdict.reason != job.get("wait_reason"):
                        job["wait_reason"] = verdict.reason
                    # a job held by RAM keeps its bytes from every lower job and grant
                    if job.get("need") and self.ram_short(job):
                        self.ram_wait[job["id"]] = (job["priority"],
                                                    ledger.declared_total(job["need"]))
                    continue
                job["wait_reason"] = None
                self.start(job, verdict.lane, verdict.confine)
            self.persist()

    def set_priority(self, jid, priority):
        """Priority is adjustable while queued; a running job keeps its lane."""
        with self.lock:
            job = self.by_id(jid)
            if not job:
                return None
            if job["status"] != "queued":
                raise ValueError("priority applies to queued jobs only (this one is %s)"
                                 % job["status"])
            if job["job_class"] in self.res.class_priority:
                raise ValueError("job %s is class %s: the class sets its priority (%d)"
                                 % (jid, job["job_class"], job["priority"]))
            job["priority"] = max(-1000, min(1000, int(priority)))
            self.event("job %s priority -> %d" % (jid, job["priority"]))
            self.persist()
            return job

    def remaining_s(self, job, now):
        """Seconds a running job has left of its expected time; None when it carries no
        estimate or has outrun it."""
        expected = self.expected_s_of(job)
        if not expected:
            return None
        started = datetime.fromisoformat(job["started"]) if job.get("started") else now
        left = expected - (now - started).total_seconds()
        return left if left > 0 else None

    def cache_wait_s(self, job, now):
        """Seconds the cache groups still hold the job back, 0 when they do not; None when a
        job of another group that holds it has no estimate."""
        wait = 0.0
        for hold in self.cache_holds(job, now):
            if hold[0] == "cooling":
                wait = max(wait, hold[3] - hold[2])
                continue
            left = self.remaining_s(hold[1], now)
            if left is None:
                return None
            wait = max(wait, left + self.reservations.cooldown_s)
        return wait

    def eta_seconds(self, job):
        """Seconds until this job could start: 0 only when it could start now. Otherwise the
        longest remaining expected time of what holds its lanes (a `both` job holds each of
        its cards) and of the cache groups, plus the expected times of the queued jobs that
        go first on those lanes, a first-order sum; the shortest of a card's own for `any`.
        None when a blocker has no estimate or has outrun it, and when the wait is behind
        something outside the queue (lease, lock, hold, VRAM, reservation): an honest unknown
        beats a number that ignores it. A running sitting is a blocker inside the queue: it
        owns the box, so its remaining expected time is the wait."""
        verdict = self.admit(job)
        if verdict.lane is not None:
            return 0
        now = self.now()
        running = self.running_jobs()
        mine = set(CARDS if job["job_class"] in EXCLUSIVE_CLASSES else self.cards_of(job["card"]))
        idx = {j["id"]: i for i, j in enumerate(self.jobs)}
        # arrival order is list order (submit appends); timestamps can tie at 1 s granularity
        ahead = [q for q in self.jobs if q["status"] == "queued" and q is not job
                 and (q["priority"] > job["priority"]
                      or (q["priority"] == job["priority"] and idx[q["id"]] < idx[job["id"]])
                      or (job["job_class"] != "media" and self.media_queued_for(q, mine, job)))]
        # an exclusive job in line, or this one being exclusive, needs the whole box drained
        exclusive = (job["job_class"] in EXCLUSIVE_CLASSES
                     or any(q["job_class"] in EXCLUSIVE_CLASSES for q in ahead))
        cache = self.cache_wait_s(job, now)
        best = None
        for alt in self.alternatives(job["card"]):
            if cache is None or alt in verdict.external:
                continue
            seconds = cache
            for r in running:
                if (exclusive or r["job_class"] in EXCLUSIVE_CLASSES
                        or set(self.lanes_held(r)) & set(alt)):
                    left = self.remaining_s(r, now)
                    if left is None:
                        seconds = None
                        break
                    seconds = max(seconds, left)
            if seconds is None:
                continue
            for q in ahead:
                if (exclusive or q["job_class"] in EXCLUSIVE_CLASSES
                        or set(self.cards_of(q["card"])) & set(alt)):
                    if not self.expected_s_of(q):
                        seconds = None
                        break
                    seconds += self.expected_s_of(q)
            if seconds is None:
                continue
            best = seconds if best is None else min(best, seconds)
        return None if best is None else math.ceil(best)

    def job_view(self, job):
        """The job as the wire shows it: its record and eta_s, 0 for a job that is not queued."""
        view = dict(job)
        if job["status"] == "queued" and not self.view_snap().cards_read:
            self.observe(cards=True)    # an idle tick did not ask the driver; this answer needs it
        view["eta_s"] = self.eta_seconds(job) if job["status"] == "queued" else 0
        return view

    # -- views --------------------------------------------------------------

    def calendar_md(self):
        now = self.now()
        lines = ["# 신호소 달력 — %s" % now.strftime("%Y-%m-%d %H:%M"), "",
                 "| 요청 시각 | 세션 | 창 이름 | 모델 | 예상 분 | 결정하는 것 | 순서 | 끝 |",
                 "|---|---|---|---|---:|---|---:|---|"]
        order = 0
        rows = ([j for j in self.jobs if j["status"] in ("queued", "running")]
                + [j for j in reversed(self.jobs) if j["status"] in ("done", "failed", "cancelled", "lost")
                   and (j.get("finished") or "") >= now.strftime("%Y-%m-%d")])
        for j in rows:
            if j["status"] in ("queued", "running"):
                order += 1
            model = j.get("script") or j["kind"]
            end = j.get("finished") or (j["status"] if j["status"] != "running" else "…")
            wait = (" — %s" % j["wait_reason"]) if (j["status"] == "queued" and j.get("wait_reason")) else ""
            pos = order if j["status"] in ("queued", "running") else "—"
            if j["status"] == "queued" and j.get("priority"):
                pos = "%d (p%s%d)" % (pos, "+" if j["priority"] > 0 else "", j["priority"])
            lines.append("| %s | %s | %s | %s | %s | %s%s | %s | %s |" % (
                j["submitted"][11:19] if j.get("submitted") else "",
                j["owner"], j["name"], model,
                math.ceil(self.expected_s_of(j) / 60) or "—", j["title"] or "—", wait,
                pos, end))
        return "\n".join(lines) + "\n"

    def state_view(self):
        now = self.now()
        self.observe(cards=True)
        snap = self.view_snap()
        cards = {}
        for card in CARDS:
            cards[card] = {
                "uuid": self.probes.uuids().get(card),
                "vram_mib": (snap.cards.get(card) or {}).get("used_mib"),
                "lane_busy": self.lane_busy(card),
                "reasons": self.card_reasons(card, owner=None),
            }
        return {
            "now": iso(now), "fake": self.fake, "cards": cards,
            "gpu_lease": snap.lease, "bloomery_locks": snap.locks,
            "bloomery_holds": [h.path for h in snap.holds],
            "reservations_file": self.reservations.path,
            "jobs": [{k: j.get(k) for k in ("id", "owner", "name", "title", "status",
                                            "kind", "script", "card", "resolved_card",
                                            "job_class", "priority", "expected_min",
                                            "expected_s", "submitted", "started",
                                            "finished", "rc", "sentinel", "wait_reason")}
                     for j in self.jobs],
            "events": self.events[-20:],
        }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "signalbox/0.1"
    sched = None  # set in main
    token_file = TOKEN_FILE  # set in main

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, code=200, ctype="text/plain; charset=utf-8"):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    CTYPES = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4",
        ".webm": "video/webm", ".wav": "audio/wav", ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg", ".flac": "audio/flac", ".json": "application/json",
        ".txt": "text/plain; charset=utf-8",
    }

    def send_file(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def disk_file(self, path):
        with open(path, "rb") as f:
            return f.read(), self.CTYPES.get(os.path.splitext(path)[1].lower(),
                                             "application/octet-stream")

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except ValueError:
            raise ValueError("body is not JSON")

    def log_message(self, fmt, *args):
        log("http " + (fmt % args))

    def tailnet_request(self):
        """tailscale serve's proxy adds X-Forwarded-For and Tailscale-* headers to every
        request it forwards and the client cannot strip them; a request with none of them
        came to the loopback port directly, from the box itself."""
        return any(k.lower() == "x-forwarded-for" or k.lower().startswith("tailscale-")
                   for k in self.headers.keys())

    def bearer_ok(self, token):
        scheme, _, cred = self.headers.get("Authorization", "").partition(" ")
        return (scheme.lower() == "bearer"
                and hmac.compare_digest(cred.strip().encode("latin-1", "replace"), token))

    def door(self, method, path):
        """The one gate in front of every route. Local requests pass untouched. A tailnet
        request needs the bearer token (GET included), and a tailnet POST only reaches the
        routes of TAILNET_ROUTES, with listed keys only, never a priority, and cancel only
        for a job the tailnet owns. True means a refusal was already sent. For a POST the
        parsed body is left in self.req_body, and a tailnet cancel's resolved job id in
        self.cancel_id."""
        tailnet = self.tailnet = self.tailnet_request()
        self.cancel_id = None
        route = None
        if tailnet:
            token, why = read_token(self.token_file)
            if token is None:
                self.send_json({"error": "tailnet access is closed: token file %s %s"
                                % (self.token_file, why), "rc": 78}, 503)
                return True
            if not self.bearer_ok(token):
                self.send_json({"error": "tailnet requests need Authorization: Bearer <token>",
                                "rc": 77}, 401)
                return True
            if method == "DELETE":
                self.send_json({"error": "DELETE %s is not open to the tailnet" % path,
                                "rc": 77}, 403)
                return True
            if method == "POST":
                route = tailnet_route(path)
                if route is None:
                    self.send_json({"error": "POST %s is not open to the tailnet" % path,
                                    "rc": 77}, 403)
                    return True
        if method == "POST":
            try:
                self.req_body = self.body_json()
            except ValueError as e:
                self.send_json({"error": str(e), "rc": 64}, 400)
                return True
            if tailnet:
                if not isinstance(self.req_body, dict):
                    self.send_json({"error": "body must be a JSON object", "rc": 64}, 400)
                    return True
                if "priority" in self.req_body:
                    self.send_json({"error": "priority is not set from the tailnet; "
                                    "the dispatcher's rule applies", "rc": 77}, 403)
                    return True
                why = tailnet_refusal(route, self.req_body)
                if why:
                    self.send_json({"error": why, "rc": 77}, 403)
                    return True
                if route == "/jobs/<id>/cancel":
                    # resolved once here, so the job checked is the job cancelled
                    with self.sched.lock:
                        job = self.sched.by_id(CANCEL_RE.match(path).group(1))
                        jid, owner = (job["id"], job["owner"]) if job else (None, None)
                    if jid is None:
                        self.send_json({"error": "no such job"}, 404)
                        return True
                    if owner != TAILNET_OWNER:
                        self.send_json({"error": "job %s is not the tailnet's" % jid,
                                        "rc": 77}, 403)
                        return True
                    self.cancel_id = jid
        return False

    def owned(self, spec):
        """A job a tailnet request creates belongs to the token's holder, whatever the
        body says; a local request keeps the spec's own owner."""
        if self.tailnet:
            spec["owner"] = TAILNET_OWNER
        return spec

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if self.door("GET", path):
            return
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        s = self.sched
        if path == "/health":
            return self.send_json({"ok": True})
        if path == "/state":
            return self.send_json(s.state_view())
        if path == "/ledger":
            try:
                recent = int(q.get("recent", ["20"])[0])
            except ValueError:
                return self.send_json({"error": "recent must be a whole number", "rc": 64}, 400)
            return self.send_json(s.ledger_view(recent))
        if path == "/calendar.md":
            return self.send_text(s.calendar_md(), ctype="text/markdown; charset=utf-8")
        if path == "/jobs":
            return self.send_json([{k: j.get(k) for k in ("id", "owner", "name", "status",
                                                          "kind", "script", "card",
                                                          "resolved_card", "job_class",
                                                          "priority", "expected_s", "submitted",
                                                          "started", "finished", "rc",
                                                          "wait_reason")}
                                   for j in s.jobs])
        m = re.match(r"^/jobs/([A-Za-z0-9._-]+)$", path)
        if m:
            job = s.by_id(m.group(1))
            if not job:
                return self.send_json({"error": "no such job"}, 404)
            detail = s.job_view(job)
            detail["log_tail"] = self.tail(s, m.group(1), 40)
            return self.send_json(detail)
        m = re.match(r"^/jobs/([A-Za-z0-9._-]+)/log$", path)
        if m:
            return self.send_text(self.tail(s, m.group(1),
                                            int(q.get("tail", ["200"])[0])))
        m = re.match(r"^/jobs/([A-Za-z0-9._-]+)/files/([^/]+)$", path)
        if m:
            job = s.by_id(m.group(1))
            if not job:
                return self.send_json({"error": "no such job"}, 404)
            # the artifact listing is the allowlist: a name is served only from a
            # recorded artifact path, never by joining client input onto disk paths
            want = urllib.parse.unquote(m.group(2))
            for art in job.get("artifacts") or []:
                if os.path.basename(art["path"]) == want:
                    try:
                        data, ctype = self.disk_file(art["path"])
                    except OSError:
                        return self.send_json({"error": "artifact unreadable"}, 410)
                    return self.send_file(data, ctype)
            return self.send_json({"error": "no artifact named %r" % want}, 404)
        if path == "/comfy/view":
            # ComfyUI /view, proxied: outputs are reachable only while a session
            # holds the lane, and the tailnet has no other route to 127.0.0.1:8188
            query = urllib.parse.urlencode({k: q.get(k, [""])[0]
                                            for k in ("filename", "subfolder", "type")})
            try:
                with urllib.request.urlopen(COMFY_URL + "/view?" + query, timeout=120) as r:
                    return self.send_file(r.read(), r.headers.get("Content-Type",
                                                                  "application/octet-stream"))
            except urllib.error.HTTPError as e:
                return self.send_json({"error": "comfy /view %d" % e.code}, 502)
            except urllib.error.URLError as e:
                return self.send_json({"error": "comfy /view: %s" % e}, 502)
        return self.send_json({"error": "no such route"}, 404)

    @staticmethod
    def tail(s, jid, nlines):
        """The last nlines lines of a job's logs, the job found by id or by name. Each file is
        read from its last TAIL_LINE_BYTES * nlines bytes, a cut first line dropped."""
        job = s.by_id(jid)
        if not job:
            return ""
        window = TAIL_LINE_BYTES * max(nlines, 1)
        lines = []
        for path in log_files(os.path.join(s.home, "jobs", job["id"])):
            data = read_tail(path, window + 1)
            if len(data) > window:
                data = data.partition(b"\n")[2]
            lines += data.splitlines()
        return b"\n".join(lines[-nlines:]).decode(errors="replace")

    # -- submission with the caller's bargain: wait up to `wait` seconds (default 60) for
    # -- allocation when the estimate says it can happen in time; otherwise answer at once
    # -- with the estimate. A "wait" longer than the estimate never blocks the answer.

    def submit_and_maybe_wait(self, spec, wait_s):
        s = self.sched
        job = s.submit(spec)
        s.observe(cards=True)   # the submitter's answer is read from the box now, not from the last tick
        cap = int(wait_s if wait_s is not None else 60)
        if cap > 0:
            deadline = time.time() + cap + 10  # the dispatcher ticks every 2 s
            while time.time() < deadline:
                job = s.by_id(job["id"]) or job
                if job["status"] != "queued":
                    break
                eta = s.eta_seconds(job)
                if eta is None or eta > deadline - time.time():
                    break
                time.sleep(1)
        return s.job_view(s.by_id(job["id"]) or job)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if self.door("POST", path):
            return
        s = self.sched
        body = self.req_body
        try:
            if path == "/jobs":
                return self.send_json(self.submit_and_maybe_wait(body, body.get("wait", 60)), 201)
            if path == "/grants":
                code, obj = s.grant_create(body)
                return self.send_json(obj, code)
            m = re.match(r"^/jobs/([A-Za-z0-9._-]+)/priority$", path)
            if m:
                job = s.set_priority(m.group(1), body.get("priority"))
                if not job:
                    return self.send_json({"error": "no such job", "rc": 64}, 404)
                return self.send_json(job)
            m = CANCEL_RE.match(path)
            if m:
                job = s.cancel(self.cancel_id or m.group(1))
                if not job:
                    return self.send_json({"error": "no such job"}, 404)
                return self.send_json(job)
            if path in ("/gen/video", "/gen/image", "/gen/music", "/gen/audio"):
                return self.send_json(
                    self.submit_and_maybe_wait(self.owned(self.gen(path.rsplit("/", 1)[1], body)),
                                               body.get("wait", 60)), 201)
            if path == "/comfy/session":
                spec = {
                    "kind": "comfy-session",
                    "owner": body.get("owner", "comfy"),
                    "name": body.get("tag") or body.get("name") or "",
                    "title": body.get("title", "ComfyUI interactive window"),
                    "expected_min": int(body.get("minutes", 0)),
                    "priority": body.get("priority", 0),
                    "card": body.get("card", "a6000"),
                    "env": {"MINUTES": str(int(body.get("minutes", 0))),
                            "TS_SERVE": "1" if body.get("ts_serve") else "0"},
                }
                if body.get("port"):
                    spec["env"]["PORT"] = str(body["port"])
                return self.send_json(
                    self.submit_and_maybe_wait(self.owned(spec), body.get("wait", 60)), 201)
            if path == "/comfy/stop":
                # the documented convenience for ending a session window by its tag
                # (or the only running one); the lawful teardown is what cancel's stop starts
                running = [j for j in self.sched.running_jobs()
                           if j["kind"] == "comfy-session"]
                if not running:
                    return self.send_json({"error": "no comfy session running", "rc": 75})
                want = body.get("tag")
                job = next((j for j in running if j["name"] == want), None) if want else None
                if want and not job:
                    return self.send_json({"error": "no comfy session named %s" % want,
                                           "rc": 64}, 404)
                job = job or running[0]
                return self.send_json(self.sched.cancel(job["id"]))
            if path == "/comfy/batch":
                return self.send_json(self.comfy_batch(body))
            return self.send_json({"error": "no such route"}, 404)
        except ValueError as e:
            return self.send_json({"error": str(e), "rc": 64}, 400)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if self.door("DELETE", path):
            return
        m = re.match(r"^/grants/([A-Za-z0-9._-]+)$", path)
        if not m:
            return self.send_json({"error": "no such route"}, 404)
        grant = self.sched.grant_release(m.group(1))
        if grant is None:
            return self.send_json({"error": "no grant %s" % m.group(1), "rc": 66}, 404)
        return self.send_json(grant)

    # -- generation sugar: env knobs of the take runners, nothing more ------

    GEN = {
        "video": ("ltx", {
            "prompt": ("PROMPT", True), "neg": ("NEG", False), "pipe": ("PIPE", False),
            "frames": ("FRAMES", False), "wh": ("WH", False), "seed": ("SEED", False),
            "steps": ("STEPS", False), "cfg": ("CFG", False), "stg": ("STG", False),
            "rescale": ("RESCALE", False), "a2v": ("A2V", False), "quant": ("QUANT", False),
            "offload": ("OFFLOAD", False), "mbs": ("MBS", False), "image": ("IMAGE", False),
            "images": ("IMAGES", False), "loras": ("LORAS", False), "vidcond": ("VIDCOND", False),
            "extra": ("EXTRA", False), "plim": ("PLIM", False),
        }),
        "image": ("img", {
            "prompt": ("PROMPT", True), "neg": ("NEG", False), "model": ("MODEL", False),
            "wh": ("WH", False), "steps": ("STEPS", False), "guidance": ("GUIDANCE", False),
            "seed": ("SEED", False), "count": ("COUNT", False),
        }),
        "music": ("music", {
            "style": ("STYLE", True), "lyrics": ("LYRICS", False), "lyrics_file": ("LYRICS_FILE", False),
            "seed": ("SEED", False), "cot": ("COT", False), "abc": ("ABC", False),
            "plan_only": ("PLAN_ONLY", False),
        }),
        "audio": ("echo", {
            "mode": ("MODE", True), "cache": ("CACHE", True), "reqdir": ("REQDIR", False),
            "request": ("REQUEST", False), "config": ("CONFIG", False), "extra": ("EXTRA", False),
        }),
    }

    def gen(self, medium, body):
        script, knobs = self.GEN[medium]
        env = {}
        for key, (envname, required) in knobs.items():
            if key in body and body[key] is not None:
                env[envname] = str(body[key])
            elif required:
                raise ValueError("%s: %s is required" % (medium, key))
        if medium == "image" and "MODEL" not in env:
            env["MODEL"] = "/models/Z-Image-Turbo"
        spec = {
            "kind": "media-take", "script": script,
            "owner": body.get("owner", "api"),
            "name": body.get("tag") or "",
            "title": body.get("title", "gen/%s" % medium),
            "expected_min": int(body.get("expected_min", 0)),
            "priority": body.get("priority", 0),
            "card": body.get("card", "a6000"),
            "env": env,
        }
        if body.get("expected_s") is not None:
            spec["expected_s"] = body["expected_s"]
        return spec

    def comfy_batch(self, body):
        prompt = body.get("prompt")
        if not prompt:
            raise ValueError("prompt (API-format workflow) is required")
        timeout = int(body.get("timeout", 1800))
        # a session must be holding the lane for us to spend the card
        session = [j for j in self.sched.running_jobs()
                   if j["kind"] == "comfy-session"]
        if not session:
            return {"error": "no comfy session running (POST /comfy/session first)",
                    "rc": 75}
        data = json.dumps({"prompt": prompt,
                           "client_id": "signalbox"}).encode()
        req = urllib.request.Request(COMFY_URL + "/prompt", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                prompt_id = json.load(r).get("prompt_id")
        except (urllib.error.URLError, ValueError) as e:
            return {"error": "comfy /prompt failed: %s" % e, "rc": 70}
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(COMFY_URL + "/history/" + prompt_id,
                                             timeout=30) as r:
                    hist = json.load(r).get(prompt_id)
            except (urllib.error.URLError, ValueError):
                hist = None
            if hist:
                outputs = []
                for node_id, node_out in (hist.get("outputs") or {}).items():
                    for kind in ("images", "gifs", "videos", "audio"):
                        for item in node_out.get(kind, []) or []:
                            outputs.append({"node": node_id, "kind": kind,
                                            "subfolder": item.get("subfolder", ""),
                                            "name": item.get("filename", "")})
                return {"prompt_id": prompt_id, "status": hist.get("status", {}),
                        "outputs": outputs}
            time.sleep(2)
        return {"error": "timeout after %d s" % timeout, "prompt_id": prompt_id, "rc": 70}


# ---------------------------------------------------------------- systemd notify + main

def sd_notify(msg):
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.send(msg.encode())
    except OSError:
        pass


class Heartbeat:
    """When the ticker last finished a tick; the age is read by the watchdog thread alone."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last = clock()

    def beat(self):
        self.last = self.clock()

    def age(self):
        return self.clock() - self.last


def run_ticker(sched, beat, stop, interval=TICK_S):
    while not stop.is_set():
        try:
            sched.tick()
        except Exception as e:  # a dispatcher must outlive a bad tick
            log("tick error: %s" % e)
        beat.beat()
        stop.wait(interval)


def run_watchdog(beat, stop, notify, interval=WATCHDOG_INTERVAL_S, max_age=TICK_MAX_AGE_S):
    """WATCHDOG=1 every interval while the last finished tick is younger than max_age. It
    takes no lock and runs no probe: a slow nvidia-smi inside a tick cannot starve it, a
    tick wedged past max_age does."""
    while not stop.is_set():
        if beat.age() < max_age:
            notify("WATCHDOG=1")
        stop.wait(interval)


def start_threads(sched, notify=sd_notify, beat=None, tick_s=TICK_S,
                  interval=WATCHDOG_INTERVAL_S, max_age=TICK_MAX_AGE_S):
    """The ticker and the watchdog, each on its own thread. Returns the event that stops both."""
    stop, beat = threading.Event(), beat or Heartbeat()
    threading.Thread(target=run_ticker, args=(sched, beat, stop, tick_s), daemon=True).start()
    threading.Thread(target=run_watchdog, args=(beat, stop, notify, interval, max_age),
                     daemon=True).start()
    return stop


def check_slices(cfg, runner=None):
    """(line, missing): where the config's class slices stand on this box. A slice is installed when
    systemd knows its unit file (FragmentPath); the daemon refuses a queued job of a class whose slice
    is not, so a restart onto a missing one would fail every job of that class. `missing` is the list
    of slice units without a file; the line says "not checked" where there is no systemctl (a copy
    of the config on another machine)."""
    if not cfg.slices:
        return "slices: none configured", []
    if runner is None and not shutil.which("systemctl"):
        return "slices: not checked (no systemctl here)", []
    runner = runner or UnitRunner()
    state = []
    for klass, unit in sorted(cfg.slices.items()):
        try:
            runner.slice_installed(unit)
            state.append("%s %s (installed)" % (klass, unit))
        except RunnerError as e:
            state.append("%s %s (%s)" % (klass, unit, "NOT INSTALLED" if e.rc == 69 else "unreadable: %s" % e))
    missing = [u for (k, u), st in zip(sorted(cfg.slices.items()), state) if "(installed)" not in st]
    return "slices: " + ", ".join(state), missing


def main():
    ap = argparse.ArgumentParser(description="signalbox dispatcher")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--home", default=HOME)
    ap.add_argument("--token-file", default=TOKEN_FILE,
                    help="bearer token every tailnet request must carry (root-only file)")
    ap.add_argument("--fake", action="store_true",
                    help="fake jobs and no hardware gates: scheduler rehearsal")
    ap.add_argument("--resources", default=RESOURCES or None,
                    help="the ledger's config (default: box-resources.json in --home)")
    ap.add_argument("--check", action="store_true",
                    help="read the ledger's config, print what it says and exit; 78 when it "
                         "cannot be used (run it on the new file before a restart)")
    args = ap.parse_args()
    fake = args.fake or FAKE
    path = args.resources or os.path.join(args.home, "box-resources.json")
    try:
        cfg = ledger.load_config(path)
    except ledger.ConfigError as e:
        log("resource config: %s" % e)
        sys.exit(78)
    if args.check:
        line, missing = check_slices(cfg)
        if missing:
            log("%s: install them (cp configs/<slice> /etc/systemd/system/ && systemctl daemon-reload) "
                "before a restart, or take the class out of slices in %s" % (line, path))
            sys.exit(78)
        print("ok %s: classes %s; headroom %s; cpus %s; tape %s; %s" % (
            path, ", ".join("%s %d" % kv for kv in sorted(cfg.class_priority.items(),
                                                          key=lambda kv: -kv[1])),
            ledger.gb(cfg.headroom), ledger.fmt_cpus(cfg.cpus),
            "cpus %s, rounds keep %s" % (ledger.fmt_cpus(cfg.tape["cpus"]), ledger.fmt_cpus(cfg.tape["rounds_cpus"]))
            if cfg.tape else "none", line))
        return
    sched = Scheduler(home=args.home, fake=fake, runner=PopenRunner() if fake else UnitRunner(),
                      resources=cfg)
    Handler.sched = sched
    Handler.token_file = args.token_file
    _, why = read_token(args.token_file)
    if why:
        log("token file %s %s: every tailnet request is refused (503) until it is fixed"
            % (args.token_file, why))

    start_threads(sched)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    sd_notify("READY=1")
    log("listening on 127.0.0.1:%d (home %s, fake=%s, runner=%s)"
        % (args.port, args.home, fake, type(sched.runner).__name__))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
