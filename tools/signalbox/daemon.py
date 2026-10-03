#!/usr/bin/env python3
"""signalbox — the box's job dispatcher. One lane per card, cache groups, reservation
windows, and an HTTP face on loopback for the tailnet.

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
  - Stop is SIGTERM to the recorded pid, waited on; never a blind escalation.

stdlib only, like logproxy and mrs-shim before it. State under /home/user/signalbox/.
"""

import argparse
import fcntl
import glob as globmod
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.environ.get("SIGNALBOX_HOME", "/home/user/signalbox")
PORT = int(os.environ.get("SIGNALBOX_PORT", "8030"))
GPU_LEASE = os.environ.get("SIGNALBOX_GPU_LEASE", "/home/user/gpu-lease")
GPU_ORDER_ENV = os.environ.get("SIGNALBOX_GPU_ORDER", "/home/user/gpu-order.env")
BLOOMERY_LOCK_GLOB = os.environ.get("SIGNALBOX_BLOOMERY_LOCKS", "/root/bloomery-*.lock")
BLOOMERY_HOLD_GLOB = os.environ.get("SIGNALBOX_BLOOMERY_HOLDS", "/root/bloomery-*-hold")
FAKE = os.environ.get("SIGNALBOX_FAKE", "") == "1"

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
CLASSES = ("normal", "host", "solo")


def log(msg):
    sys.stderr.write("%s signalbox: %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


# ---------------------------------------------------------------- probes (injectable for tests)

class Probes:
    """The read side of the box. Every method is side-effect free except clear_stale_lease."""

    def __init__(self, gpu_order=GPU_ORDER_ENV, lease=GPU_LEASE,
                 lock_glob=BLOOMERY_LOCK_GLOB, hold_glob=BLOOMERY_HOLD_GLOB):
        self.gpu_order_path, self.lease_path = gpu_order, lease
        self.lock_glob, self.hold_glob = lock_glob, hold_glob
        self._order = None

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

    def vram_mib(self, card):
        """VRAM used on the card; a failed query reads as busy (a big number)."""
        uuid = self.uuids().get(card, "")
        try:
            out = subprocess.run(
                ["nvidia-smi", "-i", uuid, "--query-gpu=memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            return int(out)
        except Exception:
            return 1 << 30

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


# ---------------------------------------------------------------- scheduler

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class Scheduler:
    def __init__(self, probes=None, home=HOME, reservations=None, fake=FAKE,
                 now_fn=datetime.now):
        self.probes = probes or Probes()
        self.home = home
        self.reservations = reservations or Reservations(os.path.join(home, "reservations.json"))
        self.fake = fake
        self.now = now_fn
        self.jobs = []
        self.seq = 0
        self.events = []
        self.lock = threading.RLock()
        self.procs = {}          # id -> Popen (None for pidfile-watched comfy runs)
        self.cache_free = {}     # cache_group -> datetime it last finished
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
        for job in self.jobs:
            if job["status"] == "running":
                pid = job.get("pid")
                if pid:
                    try:
                        os.kill(pid, 0)
                        self.procs[job["id"]] = None  # re-adopted; reap polls os.kill
                        continue
                    except OSError:
                        pass
                job["status"] = "lost"
                job["finished"] = iso(self.now())
                self.event("job %s lost (daemon restart, pid gone)" % job["id"])

    def persist(self):
        data = {"seq": self.seq, "jobs": self.jobs[-QUEUE_HISTORY:],
                "events": self.events[-100:]}
        tmp = self.state_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path())

    def event(self, msg):
        self.events.append("%s %s" % (iso(self.now()), msg))

    # -- submission ---------------------------------------------------------

    def submit(self, spec):
        with self.lock:
            self.seq += 1
            job = {
                "id": "s%d" % self.seq,
                "owner": spec.get("owner", "anon"),
                "name": spec.get("name") or "job%d" % self.seq,
                "title": spec.get("title", ""),
                "expected_min": int(spec.get("expected_min", 0)),
                "kind": spec.get("kind", "command"),
                "job_class": spec.get("job_class", "normal"),
                "script": spec.get("script", ""),
                "card": spec.get("card", "a6000"),
                "cache_group": spec.get("cache_group",
                                        "media" if spec.get("kind") in ("media-take", "comfy-session") else ""),
                "env": {str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                "argv": spec.get("argv", ""),
                "status": "queued",
                "submitted": iso(self.now()),
                "started": None, "finished": None, "rc": None, "sentinel": None,
                "pid": None, "wait_reason": None, "artifacts": [],
            }
            if job["kind"] not in KINDS:
                raise ValueError("kind must be one of %s" % (KINDS,))
            if job["job_class"] not in CLASSES:
                raise ValueError("job_class must be one of %s" % (CLASSES,))
            if job["kind"] == "media-take" and job["script"] not in RUNNERS:
                raise ValueError("script must be one of %s" % (sorted(RUNNERS),))
            if job["card"] not in CARDS + ("any",):
                raise ValueError("card must be a6000, 3090 or any")
            if not re.match(r"^[A-Za-z0-9._-]+$", job["name"]):
                raise ValueError("name must be [A-Za-z0-9._-]+")
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
                # SIGTERM to the runner we recorded; the runner's own finish() does the
                # lawful teardown (VRAM wait, lease release-or-keep).
                self.event("job %s cancel: SIGTERM to pid %s" % (jid, job.get("pid")))
                proc = self.procs.get(jid)
                if proc:
                    proc.terminate()
                elif job.get("pid"):
                    try:
                        os.kill(job["pid"], 15)
                    except OSError:
                        pass
                job["cancel_requested"] = True
                self.persist()
                return job
            return job

    # -- dispatch -----------------------------------------------------------

    def running_jobs(self):
        return [j for j in self.jobs if j["status"] == "running"]

    def lane_of(self, job):
        return job.get("resolved_card") or job["card"]

    def lane_busy(self, card):
        return any(self.lane_of(j) == card for j in self.running_jobs())

    def card_reasons(self, card, owner):
        """Hardware+lease+reservation reasons this card may not take a job now."""
        reasons = []
        lease = self.probes.gpu_lease()
        if lease:
            if lease["live"]:
                reasons.append("gpu-lease held by %s (pid %s)" % (lease["tag"], lease["pid"]))
            else:
                if self.probes.clear_stale_lease(lease):
                    self.event("cleared stale gpu-lease: %s (pid %s dead)"
                               % (lease["tag"], lease["pid"]))
        locks = self.probes.bloomery_locks()
        for path, state in locks.items():
            cards = LOCK_CARDS.get(os.path.basename(path), CARDS)
            if card in cards:
                reasons.append("%s: %s" % (os.path.basename(path), state))
        for hold in self.probes.bloomery_holds():
            reasons.append("bloomery hold up: %s" % os.path.basename(hold))
        if self.probes.vram_mib(card) >= VRAM_IDLE_MIB:
            reasons.append("card %s above %d MiB" % (card, VRAM_IDLE_MIB))
        w = self.reservations.active(self.now(), card, owner)
        if w:
            reasons.append("reservation %s active until later (owner %s)"
                           % (w.get("name"), w.get("owner")))
        return reasons

    def can_start(self, job):
        """(card, None) when the job may start on that lane now, else (None, reason)."""
        now = self.now()
        running = self.running_jobs()
        if job["job_class"] in ("host", "solo") and running:
            return None, "class %s waits for an empty box" % job["job_class"]
        if any(r["job_class"] in ("host", "solo") for r in running):
            return None, "a %s job owns the box" % running[0]["job_class"]
        # card / lane
        order = [job["card"]] if job["card"] in CARDS else list(CARDS)
        chosen = None
        for card in order:
            if not self.lane_busy(card):
                chosen = card
                break
        if chosen is None:
            return None, "lanes busy"
        # cache warmth: a different group running, or one that just left (the GLM load that
        # evicts 186 GB of page cache and makes the next sitting cold — box-calendar law)
        if job["cache_group"]:
            for r in running:
                if r["cache_group"] and r["cache_group"] != job["cache_group"]:
                    return None, "cache group %s running" % r["cache_group"]
            cool = self.reservations.cooldown_s
            for group, freed in self.cache_free.items():
                if group != job["cache_group"]:
                    age = (now - freed).total_seconds()
                    if 0 <= age < cool:
                        return None, "cache group %s left %.0f s ago (cooldown %d s)" % (group, age, cool)
        # hardware gates; the --fake rehearsal skips them, a fake *job* does not — a
        # scheduler smoke on the box must still meet the real lease and locks
        reasons = [] if self.fake else self.card_reasons(chosen, job["owner"])
        if reasons:
            return None, "; ".join(reasons)
        # do not start what cannot finish before the next window (expected_min is the
        # calendar's 예상 분 column; unbounded jobs are the caller's reckoning)
        if job["expected_min"] > 0:
            est_end = now + timedelta(minutes=job["expected_min"])
            w = self.reservations.crossed_before(now, chosen, job["owner"], est_end)
            if w:
                return None, "would cross reservation %s (owner %s)" % (w.get("name"), w.get("owner"))
        return chosen, None

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

    def start(self, job, card):
        jobdir = os.path.join(self.home, "jobs", job["id"])
        os.makedirs(jobdir, exist_ok=True)
        try:
            cmd, extra_env = self.build_cmd(job, jobdir)
        except Exception as e:
            job["status"], job["finished"] = "failed", iso(self.now())
            job["rc"], job["sentinel"] = 64, str(e)
            self.event("job %s refused build: %s" % (job["id"], e))
            return
        env = dict(os.environ)
        env.update(extra_env)
        logf = open(os.path.join(jobdir, "log"), "ab")
        logf.write(("[%s] argv: %s\n" % (iso(self.now()), " ".join(cmd))).encode())
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True, env=env,
                                 cwd=jobdir)
        job.update(status="running", started=iso(self.now()), pid=proc.pid,
                   resolved_card=card, wait_reason=None)
        self.procs[job["id"]] = proc
        self.event("job %s started on %s (pid %d)" % (job["id"], card, proc.pid))

    def sentinel_of(self, job, jobdir):
        if job["kind"] != "media-take":
            return None
        want = SENTINELS.get(job["script"], ())
        try:
            with open(os.path.join(jobdir, "log"), "rb") as f:
                tail = f.read()[-8192:].decode(errors="replace")
        except OSError:
            return None
        for s in want:
            if s in tail:
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
            proc = self.procs.get(jid)
            if proc is not None:
                rc = proc.poll()
                if rc is None:
                    continue
            else:
                # re-adopted job: watch the recorded pid
                try:
                    os.kill(job.get("pid") or -1, 0)
                    continue
                except OSError:
                    rc = job.get("rc", 0)
            jobdir = os.path.join(self.home, "jobs", jid)
            job["rc"] = rc
            job["sentinel"] = self.sentinel_of(job, jobdir)
            job["artifacts"] = self.artifacts_of(job)
            if job.pop("cancel_requested", False):
                job["status"] = "cancelled"
            elif proc is None:
                # a re-adopted job whose pid went away across a daemon restart: rc unknowable
                job["status"], job["rc"] = "lost", None
            elif job["kind"] == "media-take":
                done_sentinel = SENTINELS.get(job["script"], ("?", "?"))[0]
                job["status"] = "done" if (rc == 0 and job["sentinel"] == done_sentinel) else "failed"
            else:
                job["status"] = "done" if rc == 0 else "failed"
            job["finished"] = iso(self.now())
            if job["cache_group"]:
                self.cache_free[job["cache_group"]] = self.now()
            self.procs.pop(jid, None)
            self.event("job %s %s rc=%s sentinel=%s" % (jid, job["status"], rc, job["sentinel"]))

    def tick(self):
        with self.lock:
            self.reap()
            for job in [j for j in self.jobs if j["status"] == "queued"]:
                card, reason = self.can_start(job)
                if card is None:
                    if reason != job.get("wait_reason"):
                        job["wait_reason"] = reason
                    continue
                job["wait_reason"] = None
                self.start(job, card)
            self.persist()

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
            lines.append("| %s | %s | %s | %s | %s | %s%s | %s | %s |" % (
                j["submitted"][11:19] if j.get("submitted") else "",
                j["owner"], j["name"], model,
                j["expected_min"] or "—", j["title"] or "—", wait,
                order if j["status"] in ("queued", "running") else "—", end))
        return "\n".join(lines) + "\n"

    def state_view(self):
        now = self.now()
        cards = {}
        for card in CARDS:
            lease = self.probes.gpu_lease()
            cards[card] = {
                "uuid": self.probes.uuids().get(card),
                "vram_mib": self.probes.vram_mib(card),
                "lane_busy": self.lane_busy(card),
                "reasons": self.card_reasons(card, owner=None),
            }
        return {
            "now": iso(now), "fake": self.fake, "cards": cards,
            "gpu_lease": lease, "bloomery_locks": self.probes.bloomery_locks(),
            "bloomery_holds": self.probes.bloomery_holds(),
            "reservations_file": self.reservations.path,
            "jobs": [{k: j.get(k) for k in ("id", "owner", "name", "title", "status",
                                            "kind", "script", "card", "resolved_card",
                                            "expected_min", "submitted", "started",
                                            "finished", "rc", "sentinel", "wait_reason")}
                     for j in self.jobs],
            "events": self.events[-20:],
        }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "signalbox/0.1"
    sched = None  # set in main

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

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        s = self.sched
        if path == "/health":
            return self.send_json({"ok": True})
        if path == "/state":
            return self.send_json(s.state_view())
        if path == "/calendar.md":
            return self.send_text(s.calendar_md(), ctype="text/markdown; charset=utf-8")
        if path == "/jobs":
            return self.send_json([{k: j.get(k) for k in ("id", "owner", "name", "status",
                                                          "kind", "script", "card",
                                                          "submitted", "started", "finished",
                                                          "rc", "wait_reason")}
                                   for j in s.jobs])
        m = re.match(r"^/jobs/([A-Za-z0-9._-]+)$", path)
        if m:
            job = s.by_id(m.group(1))
            if not job:
                return self.send_json({"error": "no such job"}, 404)
            detail = dict(job)
            detail["log_tail"] = self.tail(s, m.group(1), 40)
            return self.send_json(detail)
        m = re.match(r"^/jobs/([A-Za-z0-9._-]+)/log$", path)
        if m:
            return self.send_text(self.tail(s, m.group(1),
                                            int(q.get("tail", ["200"])[0])))
        return self.send_json({"error": "no such route"}, 404)

    @staticmethod
    def tail(s, jid, nlines):
        path = os.path.join(s.home, "jobs", jid, "log")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return ""
        return b"\n".join(data.splitlines()[-nlines:]).decode(errors="replace")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        s = self.sched
        try:
            body = self.body_json()
        except ValueError as e:
            return self.send_json({"error": str(e), "rc": 64}, 400)
        try:
            if path == "/jobs":
                job = s.submit(body)
                return self.send_json(job, 201)
            m = re.match(r"^/jobs/([A-Za-z0-9._-]+)/cancel$", path)
            if m:
                job = s.cancel(m.group(1))
                if not job:
                    return self.send_json({"error": "no such job"}, 404)
                return self.send_json(job)
            if path in ("/gen/video", "/gen/image", "/gen/music", "/gen/audio"):
                return self.send_json(self.gen(path.rsplit("/", 1)[1], body), 201)
            if path == "/comfy/session":
                spec = {
                    "kind": "comfy-session",
                    "owner": body.get("owner", "comfy"),
                    "name": body.get("tag") or body.get("name") or "",
                    "title": body.get("title", "ComfyUI interactive window"),
                    "expected_min": int(body.get("minutes", 0)),
                    "card": body.get("card", "a6000"),
                    "env": {"MINUTES": str(int(body.get("minutes", 0))),
                            "TS_SERVE": "1" if body.get("ts_serve") else "0"},
                }
                if body.get("port"):
                    spec["env"]["PORT"] = str(body["port"])
                job = s.submit(spec)
                return self.send_json(job, 201)
            if path == "/comfy/stop":
                # the documented convenience for ending a session window by its tag
                # (or the only running one); the lawful teardown is cancel's SIGTERM
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
            "style": ("STYLE", True), "lyrics_file": ("LYRICS_FILE", False),
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
            "card": body.get("card", "a6000"),
            "env": env,
        }
        return self.sched.submit(spec)

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


def main():
    ap = argparse.ArgumentParser(description="signalbox dispatcher")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--home", default=HOME)
    ap.add_argument("--fake", action="store_true",
                    help="fake jobs and no hardware gates: scheduler rehearsal")
    args = ap.parse_args()
    sched = Scheduler(home=args.home, fake=args.fake or FAKE)
    Handler.sched = sched

    def ticker():
        while True:
            try:
                sched.tick()
            except Exception as e:  # a dispatcher must outlive a bad tick
                log("tick error: %s" % e)
            sd_notify("WATCHDOG=1")
            time.sleep(2)

    threading.Thread(target=ticker, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    sd_notify("READY=1")
    log("listening on 127.0.0.1:%d (home %s, fake=%s)" % (args.port, args.home, args.fake or FAKE))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
