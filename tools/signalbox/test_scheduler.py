#!/usr/bin/env python3
"""Scheduler policy tests with a fake clock and fake probes — no GPU, no box.
Run: python3 test_scheduler.py"""
import configparser
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daemon as D

# The exact argv checks expect a unit to inherit nothing from the test's own environment.
for _k in D.PASS_ENV:
    os.environ.pop(_k, None)


class FakeProbes(D.Probes):
    def __init__(self, lease=None, locks=(), holds=(), vram=None, hold_ages=None):
        super().__init__(gpu_order="/nonexistent", lease="/nonexistent",
                         lock_glob="/nonexistent/*", hold_glob="/nonexistent/*")
        self.lease_state, self.lock_state = lease, dict(locks)
        self.hold_state, self.vram_state = list(holds), dict(vram or {})
        self.hold_age_state = dict(hold_ages or {})   # hold file name -> seconds since written

    def uuids(self):
        return {"a6000": "GPU-fake-a6000", "3090": "GPU-fake-3090"}

    def vram_mib(self, card):
        return self.vram_state.get(card, 0)

    def gpu_lease(self):
        if not self.lease_state or not self.lease_state.get("tag"):
            return None
        d = dict(self.lease_state)
        pid = d.get("pid")
        live = False
        if pid:
            try:
                os.kill(pid, 0)
                live = True
            except PermissionError:
                live = True
            except OSError:
                live = False
        d["live"] = live
        return d

    def bloomery_locks(self):
        return dict(self.lock_state)

    def bloomery_holds(self):
        return list(self.hold_state)

    def hold_age_s(self, path):
        return self.hold_age_state.get(os.path.basename(path))


class FakeUnitRunner(D.UnitRunner):
    """The real UnitRunner with only _run replaced: it records every argv UnitRunner would run
    and answers from a table of units, so argv building, state parsing and rc-file reading are
    the production code. end() ends a unit the way systemd does: it runs the unit's own
    ExecStopPost command, for real, with $EXIT_CODE and $EXIT_STATUS set, then unloads it."""
    GONE = {"LoadState": "not-found", "ActiveState": "inactive"}

    def __init__(self):
        super().__init__()
        self.calls, self.units, self.posts = [], {}, {}
        self.run_fails = self.stop_fails = None   # (rc, text) the command answers instead
        self.show_fails = False

    def _run(self, argv, timeout=30):
        self.calls.append(list(argv))
        if argv[0] == self.systemd_run:
            if self.run_fails:
                return self.run_fails
            unit = argv[argv.index("--unit") + 1]
            self.units[unit] = {"LoadState": "loaded", "ActiveState": "active"}
            props = [argv[i + 1] for i, a in enumerate(argv) if a == "-p"]
            post = [p[len("ExecStopPost="):] for p in props if p.startswith("ExecStopPost=")]
            wd = [p[len("WorkingDirectory="):] for p in props if p.startswith("WorkingDirectory=")]
            self.posts[unit] = (shlex.split(post[0]), wd[0]) if post else None
            return 0, ""
        if argv[:2] == [self.systemctl, "show"]:
            if self.show_fails:
                return 1, "Failed to connect to bus"
            p = self.units.get(argv[2], self.GONE)
            return 0, "".join("%s=%s\n" % kv for kv in p.items())
        if argv[:2] == [self.systemctl, "stop"]:
            if self.stop_fails:
                return self.stop_fails
            unit = argv[-1]
            if unit not in self.units:
                return 5, "Unit %s.service not loaded." % unit
            self.units[unit]["ActiveState"] = "deactivating"
            return 0, ""
        raise AssertionError("unexpected command %r" % (argv,))

    def systemd_runs(self):
        return [c for c in self.calls if c[0] == self.systemd_run]

    def end(self, job, exit_code, exit_status):
        """The job's main process ended as systemd reports it, ExecStopPost ran, --collect
        unloaded the unit."""
        unit = D.unit_of(job["id"])
        if self.posts[unit]:     # a unit without an ExecStopPost leaves no rc
            argv, wd = self.posts[unit]
            env = {"PATH": os.environ["PATH"]}
            if exit_code is not None:
                env["EXIT_CODE"] = exit_code
            if exit_status is not None:
                env["EXIT_STATUS"] = exit_status
            subprocess.run(argv, cwd=wd, env=env, check=True)
        self.units.pop(unit, None)

    def finish(self, job, rc):
        self.end(job, "exited", str(rc))


def make_sched(lease=None, locks=(), holds=(), vram=None, windows=(), now=None,
               fake=True, cooldown=0, runner=None, home=None, hold_ages=None):
    tmp = home or tempfile.mkdtemp(prefix="signalbox-test-")
    res_path = os.path.join(tmp, "reservations.json")
    with open(res_path, "w") as f:
        json.dump({"windows": list(windows), "cache_cooldown_s": cooldown}, f)
    clock = {"now": now or datetime(2026, 10, 3, 15, 0, 0)}
    s = D.Scheduler(probes=FakeProbes(lease, locks, holds, vram, hold_ages), home=tmp,
                    reservations=D.Reservations(res_path), fake=fake,
                    now_fn=lambda: clock["now"], runner=runner)
    return s, clock


PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok   %s" % name)
    else:
        FAIL += 1
        print("FAIL %s %s" % (name, detail))


# ---------------------------------------------------------------- lanes
s, _ = make_sched()
a = s.submit({"kind": "fake", "name": "a", "owner": "t", "card": "a6000", "env": {"SLEEP": "30"}})
b = s.submit({"kind": "fake", "name": "b", "owner": "t", "card": "a6000", "env": {"SLEEP": "30"}})
c = s.submit({"kind": "fake", "name": "c", "owner": "t", "card": "3090", "env": {"SLEEP": "30"}})
s.tick()
check("lane: first a6000 job starts", a["status"] == "running", a["status"])
check("lane: second a6000 job waits", b["status"] == "queued" and "lanes busy" in (b["wait_reason"] or ""), b["wait_reason"])
check("lane: other card free", c["status"] == "running", c["status"])

# ---------------------------------------------------------------- class host/solo
s, _ = make_sched()
h = s.submit({"kind": "fake", "name": "h", "owner": "t", "job_class": "solo"})
o = s.submit({"kind": "fake", "name": "o", "owner": "t", "card": "3090"})
s.tick()
check("solo: starts alone", h["status"] == "running")
check("solo: blocks the other card too", o["status"] == "queued" and "solo" in (o["wait_reason"] or ""), o["wait_reason"])

# ---------------------------------------------------------------- cache groups
s, _ = make_sched(cooldown=60)
g1 = s.submit({"kind": "fake", "name": "g1", "owner": "t", "cache_group": "glm", "env": {"SLEEP": "1"}})
g2 = s.submit({"kind": "fake", "name": "g2", "owner": "t", "card": "3090", "cache_group": "qwen"})
s.tick()
check("cache: different groups never parallel", g2["status"] == "queued" and "cache group" in (g2["wait_reason"] or ""), g2["wait_reason"])
time.sleep(1.2)
s.tick()  # g1 done; cooldown now applies
check("cache: cooldown holds after finish", g2["status"] == "queued" and "cooldown" in (g2["wait_reason"] or ""), g2["wait_reason"])
s.cache_free["glm"] = s.now() - D.timedelta(seconds=120)
s.tick()
check("cache: cooldown expiry releases", g2["status"] == "running", g2["status"])

# media jobs get an implicit group
s, _ = make_sched(cooldown=0)
m1 = s.submit({"kind": "media-take", "script": "img", "name": "m1", "owner": "t"})
check("cache: media jobs default to a group", m1["cache_group"] == "media", m1["cache_group"])

# ---------------------------------------------------------------- lease law
dead = {"tag": "ltx-old", "pid": 99999999}
s, _ = make_sched(lease=dead, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("lease: dead pid is no lease (cleared, job runs)", j["status"] == "running", j["wait_reason"])
live = subprocess.Popen(["sleep", "60"])
s, _ = make_sched(lease={"tag": "img-x", "pid": live.pid}, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("lease: live pid blocks", j["status"] == "queued" and "gpu-lease" in (j["wait_reason"] or ""), j["wait_reason"])
live.terminate(); live.wait()

# ---------------------------------------------------------------- bloomery observation
s, _ = make_sched(locks={"bloomery-gate-a6000.lock": "held"}, fake=False)
j1 = s.submit({"kind": "fake", "name": "j1", "owner": "t", "card": "a6000"})
j2 = s.submit({"kind": "fake", "name": "j2", "owner": "t", "card": "3090"})
s.tick()
check("bloomery: card-specific lock blocks only its card",
      j1["status"] == "queued" and j2["status"] == "running",
      "%s / %s" % (j1["status"], j2["status"]))
s, _ = make_sched(locks={"bloomery-cpu.lock": "held"}, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("bloomery: box-wide lock blocks both", j["status"] == "queued")
s, _ = make_sched(holds=["bloomery-03-hold"], fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("bloomery: a hold is occupancy", j["status"] == "queued")

# vram
s, _ = make_sched(vram={"a6000": 24000}, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t", "card": "a6000"})
s.tick()
check("vram: busy card refuses", j["status"] == "queued" and "above" in (j["wait_reason"] or ""), j["wait_reason"])

# ---------------------------------------------------------------- reservations
train = {"name": "train-13", "days": list(range(7)), "start": "13:00", "minutes": 120,
         "cards": ["a6000", "3090"], "owner": "gate-batch"}
night = {"name": "webuta", "days": list(range(7)), "start": "23:30", "minutes": 480,
         "cards": ["a6000"], "owner": "webuta"}
s, clock = make_sched(windows=[train], now=datetime(2026, 10, 3, 13, 30), fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "someone"})
own = s.submit({"kind": "fake", "name": "own", "owner": "gate-batch"})
s.tick()
check("res: active window blocks outsiders", j["status"] == "queued" and "reservation" in (j["wait_reason"] or ""), j["wait_reason"])
check("res: window owner passes", own["status"] == "running", own["status"])
# crossing: a 30-min media job at 12:45 would run past 13:00
s, clock = make_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45), fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "someone", "expected_min": 30})
s.tick()
check("res: job that cannot finish before the window holds",
      j["status"] == "queued" and "would cross" in (j["wait_reason"] or ""), j["wait_reason"])
s, clock = make_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45), fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "someone", "expected_min": 10})
s.tick()
check("res: short job before the window passes", j["status"] == "running", j["status"])
# night window only binds the a6000
s, clock = make_sched(windows=[night], now=datetime(2026, 10, 3, 23, 45), fake=False)
ja = s.submit({"kind": "fake", "name": "ja", "owner": "t", "card": "a6000"})
jt = s.submit({"kind": "fake", "name": "jt", "owner": "t", "card": "3090"})
s.tick()
check("res: night window binds a6000 only",
      ja["status"] == "queued" and jt["status"] == "running",
      "%s / %s" % (ja["status"], jt["status"]))

# ---------------------------------------------------------------- gen sugar + validation
s, _ = make_sched()
job = s.submit({"kind": "media-take", "script": "ltx", "name": "v1", "owner": "api",
                "env": {"PROMPT": "a watch movement", "FRAMES": "121"}})
check("gen: ltx env flows", job["env"]["PROMPT"] == "a watch movement" and job["script"] == "ltx")
D.Handler.sched = s
try:
    D.Handler.gen(D.Handler, "video", {})  # the sugar layer enforces the required knobs
    check("gen: missing PROMPT refused", False)
except ValueError:
    check("gen: missing PROMPT refused", True)
try:
    s.submit({"kind": "command", "argv": "true", "name": "c1", "owner": "t", "card": "gpu"})
    check("validation: bad card refused", False)
except ValueError:
    check("validation: bad card refused", True)
try:
    s.submit({"kind": "command", "argv": "true", "name": "bad name!", "owner": "t"})
    check("validation: bad name refused", False)
except ValueError:
    check("validation: bad name refused", True)

# ---------------------------------------------------------------- command job, real rc passthrough
s, _ = make_sched(fake=False)
ok = s.submit({"kind": "command", "argv": "exit 0", "name": "ok", "owner": "t", "card": "a6000"})
rc75 = s.submit({"kind": "command", "argv": "exit 75", "name": "r75", "owner": "t", "card": "3090"})
s.tick(); time.sleep(0.5); s.tick()
check("command: rc 0 is done", ok["status"] == "done", ok["status"])
check("command: rc 75 is failed, rc preserved", rc75["status"] == "failed" and rc75["rc"] == 75,
      "%s/%s" % (rc75["status"], rc75["rc"]))

# ---------------------------------------------------------------- calendar + state views
s, _ = make_sched()
s.submit({"kind": "fake", "name": "k1", "owner": "line1", "title": "GLM 깊이 6 재측정",
          "expected_min": 15, "env": {"SLEEP": "1"}})
s.tick()
md = s.calendar_md()
check("calendar: columns match the box-calendar shape",
      "| 요청 시각 | 세션 | 창 이름 | 모델 | 예상 분 | 결정하는 것 | 순서 | 끝 |" in md)
check("calendar: row carries owner and title", "line1" in md and "GLM 깊이 6 재측정" in md)
view = s.state_view()
check("state: cards carry reasons list", isinstance(view["cards"]["a6000"]["reasons"], list))

# ---------------------------------------------------------------- priority + eta
s, clock = make_sched(cooldown=0)
blocker = s.submit({"kind": "fake", "name": "blk", "owner": "t", "card": "a6000",
                    "expected_min": 10, "env": {"SLEEP": "30"}})
s.tick()
check("priority: blocker running", blocker["status"] == "running")
low = s.submit({"kind": "fake", "name": "low", "owner": "t", "card": "a6000",
                "priority": -5, "expected_min": 1, "env": {"SLEEP": "1"}})
high = s.submit({"kind": "fake", "name": "high", "owner": "t", "card": "a6000",
                 "priority": 5, "expected_min": 1, "env": {"SLEEP": "1"}})
eta = s.eta_seconds(low)
check("eta: blocker known -> finite", eta is not None and 500 <= eta <= 660, eta)
# unblock the lane; the higher priority takes it first
blocker["expected_min"] = 0
s.procs[blocker["id"]].terminate()
time.sleep(0.3)
s.tick()
check("priority: high jumps low", high["status"] == "running" and low["status"] == "queued",
      "%s / %s" % (high["status"], low["status"]))
s2, _ = make_sched(cooldown=0)
b2 = s2.submit({"kind": "fake", "name": "b2", "owner": "t", "card": "a6000",
                "expected_min": 0, "env": {"SLEEP": "30"}})
s2.tick()
q2 = s2.submit({"kind": "fake", "name": "q2", "owner": "t", "card": "a6000"})
check("eta: unbounded blocker -> honest unknown", s2.eta_seconds(q2) is None)
free = s2.submit({"kind": "fake", "name": "free", "owner": "t", "card": "3090"})
check("eta: startable lane -> 0", s2.eta_seconds(free) == 0)
s2.tick()
s2.procs[b2["id"]].terminate(); s2.procs[free["id"]].terminate()

# queued-ahead durations are in the estimate
s3, _ = make_sched(cooldown=0)
b3 = s3.submit({"kind": "fake", "name": "b3", "owner": "t", "card": "a6000",
                "expected_min": 5, "env": {"SLEEP": "30"}})
s3.tick()
s3.submit({"kind": "fake", "name": "mid", "owner": "t", "card": "a6000",
           "expected_min": 7})
last = s3.submit({"kind": "fake", "name": "last", "owner": "t", "card": "a6000"})
eta = s3.eta_seconds(last)
check("eta: queued-ahead included (5+7 min)", eta is not None and 660 <= eta <= 840, eta)
s3.procs[b3["id"]].terminate()

# priority adjust while queued
s4, _ = make_sched(cooldown=0)
b4 = s4.submit({"kind": "fake", "name": "b4", "owner": "t", "card": "a6000",
                "expected_min": 10, "env": {"SLEEP": "30"}})
s4.tick()
late = s4.submit({"kind": "fake", "name": "late", "owner": "t", "card": "a6000"})
s4.set_priority(late["id"], 50)
check("priority: adjustable while queued", late["priority"] == 50)
b4["expected_min"] = 0
s4.procs[b4["id"]].terminate(); time.sleep(0.3)
early = s4.submit({"kind": "fake", "name": "early", "owner": "t", "card": "a6000"})
s4.tick()
check("priority: bumped job dispatches ahead of newer same-priority",
      late["status"] == "running" and early["status"] == "queued",
      "%s / %s" % (late["status"], early["status"]))
s4.procs[late["id"]].terminate()

# ---------------------------------------------------------------- the tailnet door
import http.server

TOKEN = "door-test-token-0123456789"
tok_dir = tempfile.mkdtemp(prefix="signalbox-token-")
tok_path = os.path.join(tok_dir, "token")


def write_token(text, mode=0o600):
    with open(tok_path, "w") as f:
        f.write(text)
    os.chmod(tok_path, mode)


write_token(TOKEN + "\n")
sd, _ = make_sched()
D.Handler.sched, D.Handler.token_file = sd, tok_path
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
TAILNET = {"X-Forwarded-For": "203.0.113.7"}
AUTH = {"Authorization": "Bearer " + TOKEN}


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


code, out = call("POST", "/jobs", {"kind": "fake", "name": "local1", "owner": "t", "wait": 0})
check("door: local POST /jobs kind=fake, no token, is unchanged (201)",
      code == 201 and out["kind"] == "fake", (code, out))

code, out = call("GET", "/health", headers=TAILNET)
check("door: tailnet GET /health without a token is 401", code == 401 and "rc" in out, (code, out))
code, out = call("GET", "/health", headers={**TAILNET, **AUTH})
check("door: tailnet GET /health with the token is 200", code == 200 and out == {"ok": True},
      (code, out))

code, _ = call("GET", "/health", headers={**TAILNET, "Authorization": "Bearer wrong-token"})
code_prefix, _ = call("GET", "/health",
                      headers={**TAILNET, "Authorization": "Bearer " + TOKEN[:-1]})
check("door: a wrong token and a prefix of the right one are both 401",
      code == 401 and code_prefix == 401, (code, code_prefix))

before = len(sd.jobs)
code, out = call("POST", "/jobs", {"kind": "command", "argv": "id", "wait": 0},
                 headers={**TAILNET, **AUTH})
check("door: tailnet POST /jobs kind=command is 403 and queues nothing",
      code == 403 and "tailnet" in out["error"] and "/jobs" in out["error"]
      and len(sd.jobs) == before, (code, out, len(sd.jobs) - before))

victim = sd.submit({"kind": "fake", "name": "victim", "owner": "t", "priority": 3})
code, out = call("POST", "/jobs/%s/priority" % victim["id"], {"priority": 900},
                 headers={**TAILNET, **AUTH})
check("door: tailnet POST /jobs/<id>/priority is 403 and the priority is unchanged",
      code == 403 and "not open to the tailnet" in out["error"] and victim["priority"] == 3,
      (code, out, victim["priority"]))

before = len(sd.jobs)
code, out = call("POST", "/gen/image", {"prompt": "a red kite", "wait": 0},
                 headers={**TAILNET, **AUTH})
check("door: tailnet POST /gen/image with the token is 201 and queues a media-take",
      code == 201 and out["kind"] == "media-take" and len(sd.jobs) == before + 1, (code, out))

before = len(sd.jobs)
code, out = call("POST", "/gen/image", {"prompt": "a red kite", "wait": 0, "priority": 50},
                 headers={**TAILNET, **AUTH})
check("door: tailnet /gen/image carrying priority is 403 and queues nothing",
      code == 403 and "priority" in out["error"] and len(sd.jobs) == before, (code, out))

code, out = call("GET", "/health", headers={"Tailscale-User-Login": "someone@example.com"})
check("door: Tailscale-* header alone marks a tailnet request (401 without a token)",
      code == 401, (code, out))

def refused(path, body, why_in_error):
    """True when a tailnet POST with the token is 403, names `why_in_error`, queues nothing."""
    before = len(sd.jobs)
    code, out = call("POST", path, dict(body, wait=0), headers={**TAILNET, **AUTH})
    return (code == 403 and why_in_error in out.get("error", "")
            and len(sd.jobs) == before), (code, out)


VIDEO = {"prompt": "a kite over a field", "frames": 49, "wh": "1024 576", "seed": 7}
ok, det = refused("/gen/video", dict(VIDEO, extra="x --output-path /tmp/y"), "extra")
check("knobs: tailnet extra is 403 by name and queues nothing", ok, det)
ok, det = refused("/gen/music", {"style": "lofi", "lyrics_file": "/etc/passwd"}, "lyrics_file")
check("knobs: tailnet lyrics_file is 403 by name", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, plim=100), "plim")
check("knobs: tailnet plim is 403 by name", ok, det)
ok, det = refused("/gen/audio", {"mode": "encode", "cache": "cache/x"}, "tailnet")
check("knobs: tailnet /gen/audio is 403", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, wh="1024 --x"), "wh")
check("knobs: tailnet wh \"1024 --x\" is 403 by name", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, seed="42\n"), "seed")
check("knobs: a value with a trailing newline does not pass its format", ok, det)
ok, det = refused("/gen/image", {"prompt": "--output-path /x"}, "prompt")
check("knobs: tailnet text that starts with '-' is 403", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, owner="bloomery"), "owner")
check("knobs: tailnet owner is 403 (it would pass a reservation window)", ok, det)

before = len(sd.jobs)
code, out = call("POST", "/gen/video", dict(VIDEO, wait=0), headers={**TAILNET, **AUTH})
check("knobs: tailnet /gen/video with prompt, frames, wh, seed is 201",
      code == 201 and out["kind"] == "media-take" and out["script"] == "ltx"
      and out["env"]["WH"] == "1024 576" and len(sd.jobs) == before + 1, (code, out))
code, out = call("POST", "/gen/music", {"style": "lofi", "lyrics": "la la", "seed": 3, "wait": 0},
                 headers={**TAILNET, **AUTH})
check("knobs: tailnet /gen/music with style, lyrics, seed is 201", code == 201, (code, out))
code, out = call("POST", "/gen/video", dict(VIDEO, extra="--skip-stage-2", wait=0))
check("knobs: local /gen/video with extra is unchanged (201)",
      code == 201 and out["env"]["EXTRA"] == "--skip-stage-2", (code, out))

# ---- v3: the tailnet owner, comfy session, own-job cancel, one media lane
T = {**TAILNET, **AUTH}
before = len(sd.jobs)
code, out = call("POST", "/comfy/session", {"minutes": 30, "tag": "win1", "wait": 0}, headers=T)
check("v3: tailnet /comfy/session minutes=30 is 201, kind comfy-session, owner hermes",
      code == 201 and out["kind"] == "comfy-session" and out["owner"] == "hermes"
      and out["card"] == "a6000" and out["env"]["MINUTES"] == "30" and out["env"]["TS_SERVE"] == "0"
      and len(sd.jobs) == before + 1, (code, out))
ok, det = refused("/comfy/session", {"minutes": 30, "ts_serve": 1}, "ts_serve")
check("v3: tailnet /comfy/session ts_serve is 403 by name and queues nothing", ok, det)
ok, det = refused("/comfy/session", {"minutes": 0}, "minutes")
check("v3: tailnet /comfy/session minutes=0 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 121}, "minutes")
check("v3: tailnet /comfy/session minutes=121 is 403", ok, det)
ok, det = refused("/comfy/session", {}, "minutes is required")
check("v3: tailnet /comfy/session without minutes (unbounded) is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "port": 22}, "port")
check("v3: tailnet /comfy/session port=22 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "port": 8200}, "port")
check("v3: tailnet /comfy/session port=8200 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "card": "3090"}, "card")
check("v3: tailnet /comfy/session card=3090 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "owner": "bloomery"}, "owner")
check("v3: tailnet /comfy/session owner is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "tag": ".."}, "tag")
check("v3: tailnet /comfy/session tag \"..\" (a directory name) is 403", ok, det)
code, out = call("POST", "/comfy/session", {"minutes": 20, "port": 8190, "wait": 0}, headers=T)
check("v3: tailnet /comfy/session port=8190 is 201 with PORT in its env",
      code == 201 and out["env"].get("PORT") == "8190", (code, out))

code, out = call("POST", "/gen/image", {"prompt": "a blue kite", "wait": 0}, headers=T)
img = out
check("v3: tailnet /gen/image creates a job owned by hermes",
      code == 201 and out["owner"] == "hermes", (code, out))
code, out = call("POST", "/jobs/%s/cancel" % img["id"], headers=T)
check("v3: tailnet cancel of a hermes job is 200 and the job is cancelled",
      code == 200 and sd.by_id(img["id"])["status"] == "cancelled", (code, out))

local = sd.submit({"kind": "fake", "name": "local2", "owner": "t"})
code, out = call("POST", "/jobs/%s/cancel" % local["id"], headers=T)
check("v3: tailnet cancel of a locally submitted job is 403 by name and it stays queued",
      code == 403 and local["id"] in out["error"] and "not the tailnet's" in out["error"]
      and sd.by_id(local["id"])["status"] == "queued", (code, out))
code, out = call("POST", "/jobs/local2/cancel", headers=T)
check("v3: tailnet cancel by the name of a local job is 403 too",
      code == 403 and sd.by_id(local["id"])["status"] == "queued", (code, out))
code, out = call("POST", "/jobs/s9999/cancel", headers=T)
check("v3: tailnet cancel of a missing id is 404", code == 404, (code, out))
code, mine = call("POST", "/gen/image", {"prompt": "a green kite", "wait": 0}, headers=T)
code, out = call("POST", "/jobs/%s/cancel" % mine["id"], {"tag": "x"}, headers=T)
check("v3: tailnet cancel of its own job carrying a body key is 403 and the job stays queued",
      code == 403 and "tag" in out["error"] and sd.by_id(mine["id"])["status"] == "queued",
      (code, out))
code, out = call("POST", "/jobs/%s/cancel" % local["id"])
check("v3: local cancel of a local job is unchanged (200, cancelled)",
      code == 200 and sd.by_id(local["id"])["status"] == "cancelled", (code, out))

before = len(sd.jobs)
code_s, out_s = call("POST", "/comfy/stop", {}, headers=T)
code_b, out_b = call("POST", "/comfy/batch", {}, headers=T)
check("v3: tailnet /comfy/stop and /comfy/batch are 403 and queue nothing",
      code_s == 403 and code_b == 403 and len(sd.jobs) == before, (code_s, code_b))

before = len(sd.jobs)
code, out = call("POST", "/gen/music", {"style": "lofi", "card": "3090", "wait": 0})
check("v3: local /gen/music card=3090 is 400 by name (A6000 only) and queues nothing",
      code == 400 and "A6000 only" in out["error"] and len(sd.jobs) == before, (code, out))
code, out = call("POST", "/gen/music", {"style": "lofi", "card": "any", "wait": 0})
check("v3: local /gen/music card=any is 400 too", code == 400 and len(sd.jobs) == before, (code, out))
code, out = call("POST", "/gen/music", {"style": "lofi", "wait": 0})
check("v3: local /gen/music with no card is 201 on a6000, owner api (unchanged)",
      code == 201 and out["card"] == "a6000" and out["owner"] == "api"
      and len(sd.jobs) == before + 1, (code, out))
ok, det = refused("/gen/music", {"style": "lofi", "card": "3090"}, "card")
check("v3: tailnet /gen/music card=3090 is 403 by name", ok, det)
code, out = call("POST", "/comfy/session", {"minutes": 0, "ts_serve": 1, "owner": "x", "wait": 0})
check("v3: local /comfy/session keeps its rule (ts_serve, minutes=0, owner x pass)",
      code == 201 and out["owner"] == "x" and out["env"]["TS_SERVE"] == "1", (code, out))

os.remove(tok_path)
code_gone, out_gone = call("GET", "/health", headers={**TAILNET, **AUTH})
local_gone, _ = call("GET", "/health")
write_token(TOKEN + "\n", mode=0o644)
code_open, out_open = call("GET", "/health", headers={**TAILNET, **AUTH})
local_open, _ = call("GET", "/health")
check("door: a missing token file and a 0644 token file are both 503 naming the file; local works",
      code_gone == 503 and code_open == 503 and tok_path in out_gone["error"]
      and tok_path in out_open["error"] and local_gone == 200 and local_open == 200,
      (code_gone, code_open, local_gone, local_open))
httpd.shutdown()

# ---------------------------------------------------------------- units: runner seam, argv, reap
def wait_for(pred, timeout=5.0, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def unit_job(s, name="u", **kw):
    spec = {"kind": "command", "argv": "true", "name": name, "owner": "t"}
    spec.update(kw)
    return s.submit(spec)


# a stand-in for a media runner script: build_cmd copies it, the box's own scripts are not here
media_dir = tempfile.mkdtemp(prefix="signalbox-media-")
media_script = os.path.join(media_dir, "img-take.sh")
with open(media_script, "w") as f:
    f.write("echo IMG_DONE\n")
D.RUNNERS = dict(D.RUNNERS, img=media_script)
D.COMFY_SESSION = media_script

fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
jd = os.path.join(os.path.abspath(s.home), "jobs", "s1")
cmd_job = unit_job(s, "cmdjob", env={"A": "1", "B": "x y"})
s.tick()
want = ["systemd-run", "--unit", "sb-s1", "--collect", "--quiet",
        "-p", "StandardOutput=append:%s/out" % jd, "-p", "StandardError=append:%s/err" % jd,
        "-p", "WorkingDirectory=%s" % jd, "-p", "ExecStopPost=/bin/sh %s/post.sh" % jd,
        "-p", "TimeoutStopSec=30",
        "--setenv", "A=1", "--setenv", "B=x y",
        "--setenv", "SIGNALBOX_CARD=a6000",     # the resolved lane, after the job's own env
        "/bin/bash", "%s/cmd.sh" % jd]
check("runner: a started job went through the runner, one systemd-run", fk.systemd_runs() == [want],
      fk.systemd_runs())
print("     command job argv:", " ".join(shlex.quote(a) for a in fk.systemd_runs()[0]))
check("runner: the job is running, with its unit recorded",
      cmd_job["status"] == "running" and cmd_job["unit"] == "sb-s1", cmd_job)
check("logs: the job JSON carries out, err and rc_file as absolute paths in its jobdir",
      (cmd_job["out"], cmd_job["err"], cmd_job["rc_file"])
      == (jd + "/out", jd + "/err", jd + "/rc"), cmd_job)
check("runner: cmd.sh was written for the unit", os.path.isfile(jd + "/cmd.sh"))
check("scripts: cmd.sh only execs the argv (the unit's main process is the job itself)",
      open(jd + "/cmd.sh").read() == "#!/bin/bash\nexec bash -c true\n", open(jd + "/cmd.sh").read())
check("scripts: post.sh was written for the unit's ExecStopPost", os.path.isfile(jd + "/post.sh"))

fk.finish(cmd_job, 0)
s.tick()
media_job = s.submit({"kind": "media-take", "script": "img", "name": "mjob", "owner": "t",
                      "env": {"PROMPT": "a kite"}})
s.tick()
mrun = fk.systemd_runs()[1]
mjd = os.path.join(os.path.abspath(s.home), "jobs", "s2")
print("     media job argv:  ", " ".join(shlex.quote(a) for a in mrun))
check("argv: media adds KillMode=mixed and the 240 s stop (a runner's finish() waits up to 175 s)",
      "KillMode=mixed" in mrun and "TimeoutStopSec=240" in mrun and "TimeoutStopSec=30" not in mrun
      and mrun[mrun.index("KillMode=mixed") - 1] == "-p", mrun)
check("argv: a command job has neither KillMode nor the 240 s stop",
      not any("KillMode" in a or a == "TimeoutStopSec=240" for a in want))
check("argv: every job's unit ends through ExecStopPost=/bin/sh <jobdir>/post.sh",
      "ExecStopPost=/bin/sh %s/post.sh" % mjd in mrun and "ExecStopPost=/bin/sh %s/post.sh" % jd in want)
check("argv: the media job carries its env through --setenv and runs its own cmd.sh",
      "PROMPT=a kite" in mrun and "TAG=mjob" in mrun and mrun[-2:] == ["/bin/bash", mjd + "/cmd.sh"], mrun)
cs = s.submit({"kind": "comfy-session", "name": "cs1", "owner": "t", "card": "3090",
               "env": {"MINUTES": "5"}})
s.tick()
check("argv: a comfy session is a media job too (KillMode=mixed)",
      "KillMode=mixed" in fk.systemd_runs()[-1], fk.systemd_runs()[-1])
check("argv: no memory property and no OOMPolicy in any job's command line",
      not any("Memory" in a or "OOMPolicy" in a for c in fk.systemd_runs() for a in c))
_saved = {k: os.environ.get(k) for k in D.PASS_ENV}
os.environ["LANG"], os.environ["USER"] = "C.UTF-8", "root"
_pa = D.UnitRunner().run_argv("s9", {"USER": "job"}, "/tmp/jd", False)
for k, v in _saved.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v
check("argv: the daemon's LANG and USER reach the unit, and the job's env overrides them",
      "LANG=C.UTF-8" in _pa and "USER=job" in _pa and "USER=root" not in _pa, _pa)
_s, _ = make_sched()
_refused = []
for _c in ("both", "none", "any"):
    try:
        _s.submit({"kind": "comfy-session", "name": "cw-" + _c, "owner": "t", "card": _c, "env": {"MINUTES": "5"}})
    except ValueError as e:
        _refused.append(_c if "one card" in str(e) else "?")
check("comfy: a comfy window on both, none or any is refused by name", _refused == ["both", "none", "any"], _refused)
check("argv: no RuntimeMaxSec unless the job carries bound_s",
      not any("RuntimeMaxSec" in a for c in fk.systemd_runs() for a in c))

fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
unit_job(s, "bounded", bound_s=90)
s.tick()
bound_argv = fk.systemd_runs()[0]
check("argv: bound_s=90 adds -p RuntimeMaxSec=90",
      "RuntimeMaxSec=90" in bound_argv and bound_argv[bound_argv.index("RuntimeMaxSec=90") - 1] == "-p",
      bound_argv)
bad = []
for v in (0, 86401, True, "5", 1.5, -3):
    try:
        unit_job(s, "bad%s" % len(bad), bound_s=v)
        bad.append(v)
    except ValueError:
        pass
check("bound_s: 0, 86401, a bool, a string, a float and a negative are refused", not bad, bad)
ok_edges = [unit_job(s, "edge1", bound_s=1)["bound_s"], unit_job(s, "edge2", bound_s=86400)["bound_s"]]
check("bound_s: 1 and 86400 are accepted", ok_edges == [1, 86400], ok_edges)

# a unit that already exists is a named failure, never a reuse, never retried
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
fk.units["sb-s1"] = {"LoadState": "loaded", "ActiveState": "active"}
j = unit_job(s, "dup")
s.tick(); s.tick()
check("launch: an existing unit sb-s1 fails the job, rc 64, named",
      j["status"] == "failed" and j["rc"] == 64 and "unit sb-s1 exists" in (j["sentinel"] or ""), j)
check("launch: ...and systemd-run never ran, on either tick", fk.systemd_runs() == [], fk.calls)
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
os.makedirs(os.path.join(s.home, "jobs", "s1"))
with open(os.path.join(s.home, "jobs", "s1", "rc"), "w") as f:
    f.write("0")
j = unit_job(s, "stalerc")
s.tick()
check("launch: a jobdir that already holds an rc fails the job, rc 64 (a stale rc would end it at once)",
      j["status"] == "failed" and j["rc"] == 64 and "was used before" in j["sentinel"]
      and fk.systemd_runs() == [], j)
fk = FakeUnitRunner()
fk.run_fails = (1, "Failed to start transient service unit: Access denied")
s, _ = make_sched(runner=fk)
j = unit_job(s, "denied")
s.tick(); s.tick()
check("launch: systemd-run failing fails the job, rc 70, with its message, once",
      j["status"] == "failed" and j["rc"] == 70 and "Access denied" in j["sentinel"]
      and len(fk.systemd_runs()) == 1, j)
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
j = unit_job(s, "badenv", env={"BAD-NAME": "1"})
s.tick()
check("launch: an env name that is not a variable name fails the job, rc 64",
      j["status"] == "failed" and j["rc"] == 64 and "BAD-NAME" in j["sentinel"]
      and fk.systemd_runs() == [], j)

# cancel = runner.stop, which is a non-blocking systemctl stop
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
j = unit_job(s, "cancelme")
s.tick()
s.cancel(j["id"])
check("cancel: a running job's cancel is `systemctl stop --no-block sb-<id>`",
      fk.calls[-1] == ["systemctl", "stop", "--no-block", "sb-s1"], fk.calls[-1])
check("cancel: the job stays running with cancel_requested until the unit ends",
      j["status"] == "running" and j.get("cancel_requested") is True, j)
s.tick()
check("cancel: an unit still deactivating keeps the job running", j["status"] == "running", j)
fk.end(j, "killed", "TERM")
s.tick()
check("cancel: once the unit ends the job is cancelled, rc kept",
      j["status"] == "cancelled" and j["rc"] == 143 and "cancel_requested" not in j, j)
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
j = unit_job(s, "cancelfail")
s.tick()
fk.stop_fails = (1, "Access denied")
s.cancel(j["id"])
check("cancel: a stop that failed is an event, and the job is not marked cancelled",
      j["status"] == "running" and "cancel_requested" not in j
      and any("stop failed" in e and "Access denied" in e for e in s.events), (j, s.events))

# reap reads runner.state
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk, cooldown=0)
ok_job = unit_job(s, "ok1", card="a6000")
bad_job = unit_job(s, "bad1", card="3090")
s.tick()
fk.finish(ok_job, 0); fk.finish(bad_job, 3)
s.tick()
check("reap: an exited unit's rc comes from its rc file (0 is done, 3 is failed with rc 3)",
      ok_job["status"] == "done" and ok_job["rc"] == 0 and bad_job["status"] == "failed"
      and bad_job["rc"] == 3, (ok_job["status"], bad_job["status"], bad_job["rc"]))
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
j = unit_job(s, "gone1")
s.tick()
fk.units.pop("sb-s1")
s.tick()
check("reap: no unit and no rc file is lost with rc None",
      j["status"] == "lost" and j["rc"] is None, j)
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
j = unit_job(s, "killed1", card="a6000")
j2 = unit_job(s, "odd1", card="3090")
s.tick()
fk.end(j, "killed", "KILL")
fk.end(j2, "killed", "RTMIN+3")
s.tick()
check("reap: a job killed by KILL left rc 137 through ExecStopPost and is failed with it",
      j["status"] == "failed" and j["rc"] == 137 and j["sentinel"] is None, j)
check("reap: a job killed by a signal the table does not name left rc 70 and is failed",
      j2["status"] == "failed" and j2["rc"] == 70, j2)
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
j = unit_job(s, "tail1")
s.tick()
with open(j["rc_file"], "w") as f:
    f.write("0")
s.tick()
check("reap: a unit still active holds its lane even after rc is written", j["status"] == "running", j)
fk.units.pop("sb-s1")
s.tick()
check("reap: ...and ends the job once the unit is gone", j["status"] == "done", j)
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
j = unit_job(s, "blind")
s.tick()
fk.show_fails = True
try:
    s.tick()
    raised = False
except Exception:
    raised = True
check("reap: systemctl failing leaves the job running and the tick standing",
      not raised and j["status"] == "running")
fk.show_fails = False
fk.finish(j, 0)
s.tick()
check("reap: ...and the next tick that can ask reaps it", j["status"] == "done", j)
fk = FakeUnitRunner()
s, _ = make_sched(runner=fk)
mj = s.submit({"kind": "media-take", "script": "img", "name": "mdone", "owner": "t"})
mn = s.submit({"kind": "media-take", "script": "img", "name": "mnone", "owner": "t"})
s.tick()
check("reap: only one media job runs on the lane", mj["status"] == "running" and mn["status"] == "queued")
with open(mj["out"], "a") as f:
    f.write("12:00:00 take\nIMG_DONE\n")
fk.finish(mj, 0)
s.tick()
check("reap: a media job with rc 0 and its sentinel in out is done",
      mj["status"] == "done" and mj["sentinel"] == "IMG_DONE", mj)
s.tick()
fk.finish(mn, 0)
s.tick()
check("reap: a media job with rc 0 and no sentinel is failed", mn["status"] == "failed", mn)

# ---------------------------------------------------------------- units: re-adoption
fk = FakeUnitRunner()
s1, _ = make_sched(runner=fk)
home = s1.home
act = unit_job(s1, "act")
rco = unit_job(s1, "rconly", card="3090")
nei = unit_job(s1, "neither", card="any")
s1.tick()
check("adopt: three jobs running before the restart",
      [j["status"] for j in (act, rco, nei)] == ["running"] * 2 + ["queued"],
      [j["status"] for j in (act, rco, nei)])
nei2 = unit_job(s1, "neither2", card="3090")
s1.cancel(nei["id"]); s1.cancel(nei2["id"])
# the lane limit is one job per card: use a fresh pair for the third case below
fk.finish(rco, 5)                       # the unit ended and left its rc while the daemon was down
s2, _ = make_sched(runner=fk, home=home)
a2, r2 = s2.by_id(act["id"]), s2.by_id(rco["id"])
check("adopt: a job whose unit is active is still running after a restart, adopted",
      a2["status"] == "running" and act["id"] in s2.procs, a2)
check("adopt: a job whose rc file exists is still running at load (reaped on the next tick)",
      r2["status"] == "running" and rco["id"] in s2.procs, r2)
s2.tick()
check("adopt: ...and that tick reaps it with the rc from the file",
      r2["status"] == "failed" and r2["rc"] == 5 and a2["status"] == "running",
      (r2["status"], r2["rc"], a2["status"]))
fk.finish(a2, 0)
s2.tick()
check("adopt: the adopted active job ends with its own rc later", a2["status"] == "done", a2)
fk = FakeUnitRunner()
s1, _ = make_sched(runner=fk)
lost = unit_job(s1, "lostone")
s1.tick()
fk.units.pop("sb-s1")                   # no unit, no rc file
s2, _ = make_sched(runner=fk, home=s1.home)
l2 = s2.by_id(lost["id"])
check("adopt: neither a unit nor an rc file is lost at load, rc None",
      l2["status"] == "lost" and l2["rc"] is None and "sb-s1" not in str(s2.procs)
      and l2["id"] not in s2.procs, l2)
fk = FakeUnitRunner()
s1, _ = make_sched(runner=fk)
kept = unit_job(s1, "keptone")
s1.tick()
fk.show_fails = True
s2, _ = make_sched(runner=fk, home=s1.home)
check("adopt: systemctl failing at load keeps the job (it is asked again by reap)",
      s2.by_id(kept["id"])["status"] == "running" and kept["id"] in s2.procs)

# ---------------------------------------------------------------- cmd.sh and post.sh, real processes
wd = tempfile.mkdtemp(prefix="signalbox-scripts-")
D.write_scripts(wd, ["bash", "-c", 'printf "%s|%s" "$0" "$1" > out.txt',
                     "a'b \"c\" $HOME\nline2 `x`", "$(echo hi)"])
subprocess.run(["/bin/bash", wd + "/cmd.sh"], cwd=wd)
with open(wd + "/out.txt") as f:
    got = f.read()
check("scripts: an argv with quotes, $, backticks and a newline reaches the job untouched",
      got == "a'b \"c\" $HOME\nline2 `x`|$(echo hi)", got)
wd = tempfile.mkdtemp(prefix="signalbox-scripts-")
D.write_scripts(wd, ["bash", "-c", "exit 7"])
check("scripts: cmd.sh's exit code is the job's own (it execs, nothing stands in between)",
      subprocess.run(["/bin/bash", wd + "/cmd.sh"], cwd=wd).returncode == 7)
check("scripts: no TERM forwarding or trap anywhere: cmd.sh is the exec line alone",
      "trap" not in open(wd + "/cmd.sh").read() and "kill" not in open(wd + "/cmd.sh").read())


def post_rc(exit_code, exit_status):
    """The rc post.sh writes for the way systemd reports the main process's end (None: the
    variable is not set at all)."""
    d = tempfile.mkdtemp(prefix="signalbox-post-")
    D.write_scripts(d, ["true"])
    env = {"PATH": os.environ["PATH"]}
    if exit_code is not None:
        env["EXIT_CODE"] = exit_code
    if exit_status is not None:
        env["EXIT_STATUS"] = exit_status
    subprocess.run(["/bin/sh", d + "/post.sh"], cwd=d, env=env, check=True)
    left = sorted(os.listdir(d))
    return open(d + "/rc").read(), left


got = [post_rc("exited", st)[0] for st in ("0", "3", "75", "255")]
check("post: an exited main process's rc is its exit status", got == ["0", "3", "75", "255"], got)
got = [post_rc(c, st)[0] for c, st in (("killed", "KILL"), ("killed", "TERM"), ("dumped", "SEGV"),
                                      ("killed", "HUP"), ("dumped", "ABRT"))]
check("post: killed or dumped is 128 + the signal's number from the fixed table",
      got == ["137", "143", "139", "129", "134"], got)
got = [post_rc(c, st)[0] for c, st in (("killed", "RTMIN+3"), ("killed", ""), ("killed", None),
                                      ("exited", "abc"), ("exited", ""), ("exited", None),
                                      ("weird", "9"), (None, None))]
check("post: an unknown signal name, an odd status or missing variables is rc 70",
      got == ["70"] * 8, got)
rc_txt, left = post_rc("exited", "4")
pd = tempfile.mkdtemp(prefix="signalbox-post-")
D.write_scripts(pd, ["true"])
post_text = open(pd + "/post.sh").read()
check("post: rc is written through rc.tmp and mv; no rc.tmp is left",
      "rc.tmp" in post_text and " && mv " in post_text and "rc.tmp" not in left, (post_text, left))
check("post: every signal of the table maps to 128 + its Linux number",
      all(post_rc("killed", n)[0] == str(128 + v) for n, v in D.SIGNALS.items()))

# ---------------------------------------------------------------- the tree-kill clause (real processes)
s, _ = make_sched(fake=False)
tree_dir = tempfile.mkdtemp(prefix="signalbox-tree-")
pidf = os.path.join(tree_dir, "child.pid")
tj = s.submit({"kind": "command", "name": "tree", "owner": "t", "card": "a6000",
               "argv": "sleep 300 & echo $! > %s; wait" % pidf})
s.tick()
child = None
try:
    started = wait_for(lambda: os.path.exists(pidf) and open(pidf).read().strip().isdigit())
    child = int(open(pidf).read().strip()) if started else None
    s.cancel(tj["id"])
    gone = child is not None and wait_for(lambda: not pid_alive(child), 5)
    check("tree-kill: cancel kills the job's whole process group; the backgrounded sleep is gone in 5 s",
          started and gone, (started, child, gone))
    wait_for(lambda: (s.tick(), tj["status"] != "running")[1])
    check("tree-kill: ...and the job ends cancelled", tj["status"] == "cancelled", tj["status"])
finally:
    if child is not None and pid_alive(child):
        os.kill(child, signal.SIGKILL)  # only the pid the job wrote to its own file

# ---------------------------------------------------------------- logs: out, err, rc_file, legacy log
s, _ = make_sched(fake=False)
lg = s.submit({"kind": "command", "name": "lg", "owner": "t", "card": "a6000",
               "argv": 'echo to-out; echo to-err >&2; echo "[$NOTIFY_SOCKET][$MARK]"',
               "env": {"MARK": "m1"}})
os.environ["NOTIFY_SOCKET"] = "/run/not-for-jobs"
try:
    s.tick()
    wait_for(lambda: (s.tick(), lg["status"] != "running")[1])
finally:
    del os.environ["NOTIFY_SOCKET"]
out_txt, err_txt = open(lg["out"]).read(), open(lg["err"]).read()
out_body = out_txt.split("\n", 1)[1]
check("logs: stdout goes to out (after the argv header), stderr to err, neither in the other",
      out_txt.startswith("[") and "] argv: " in out_txt.split("\n", 1)[0]
      and out_body == "to-out\n[][m1]\n" and err_txt == "to-err\n", (out_txt, err_txt))
check("logs: a job gets its env and not the daemon's NOTIFY_SOCKET", "[][m1]" in out_txt, out_txt)
check("logs: the rc file holds the rc of an ended job (PopenRunner too)",
      lg["status"] == "done" and open(lg["rc_file"]).read() == "0", (lg["status"], lg["rc_file"]))
check("logs: the tail reads out first, then err",
      D.Handler.tail(s, lg["id"], 100).splitlines()[-2:] == ["[][m1]", "to-err"]
      and D.Handler.tail(s, lg["id"], 100).index("to-out") < D.Handler.tail(s, lg["id"], 100).index("to-err"),
      D.Handler.tail(s, lg["id"], 100))
legacy = s.submit({"kind": "command", "name": "legacy", "argv": "true", "owner": "t"})
old_dir = os.path.join(s.home, "jobs", legacy["id"])
os.makedirs(old_dir)
with open(os.path.join(old_dir, "log"), "w") as f:
    f.write("legacy line 1\nIMG_DONE\n")
check("logs: the merged <jobdir>/log of a job made before the split is still read",
      D.Handler.tail(s, legacy["id"], 10) == "legacy line 1\nIMG_DONE")
check("logs: sentinel_of still finds a sentinel in a legacy log",
      s.sentinel_of({"kind": "media-take", "script": "img"}, old_dir) == "IMG_DONE")
sent_dir = os.path.join(s.home, "jobs", "s78")
os.makedirs(sent_dir)
with open(os.path.join(sent_dir, "out"), "w") as f:
    f.write("work\nIMG_DONE\n")
with open(os.path.join(sent_dir, "err"), "w") as f:
    f.write("x" * 20000)
check("logs: a sentinel on stdout is found past 20 KB of stderr",
      s.sentinel_of({"kind": "media-take", "script": "img"}, sent_dir) == "IMG_DONE")
with open(os.path.join(sent_dir, "out"), "w") as f:
    f.write("work\n")
with open(os.path.join(sent_dir, "err"), "w") as f:
    f.write("noise\nIMG_FAILED\n")
check("logs: a sentinel on stderr is found too",
      s.sentinel_of({"kind": "media-take", "script": "img"}, sent_dir) == "IMG_FAILED")
check("logs: no sentinel in any file is None",
      s.sentinel_of({"kind": "media-take", "script": "img"}, os.path.join(s.home, "jobs", "s79")) is None)

# the tail finds a job by id or name and reads only the end of a long log
tj = s.submit({"kind": "command", "name": "bigtail", "argv": "true", "owner": "t"})
tdir = os.path.join(s.home, "jobs", tj["id"])
os.makedirs(tdir)
with open(os.path.join(tdir, "out"), "w") as f:
    f.write("".join("line %d\n" % i for i in range(20000)))
with open(os.path.join(tdir, "err"), "w") as f:
    f.write("e1\ne2\n")
sizes, real_read_tail = [], D.read_tail
D.read_tail = lambda path, nbytes=None: (sizes.append(nbytes), real_read_tail(path, nbytes))[1]
try:
    by_name = D.Handler.tail(s, "bigtail", 5)
    by_id = D.Handler.tail(s, tj["id"], 5)
finally:
    D.read_tail = real_read_tail
check("tail: the job is found by its name as well as its id",
      by_name == by_id == "line 19997\nline 19998\nline 19999\ne1\ne2", (by_name, by_id))
check("tail: only the end of each file is read, never the whole log",
      sizes and all(n is not None and n < 10000 for n in sizes), sizes)
check("tail: an unknown job is an empty tail", D.Handler.tail(s, "no-such-job", 5) == "")
with open(os.path.join(tdir, "out"), "w") as f:
    f.write("".join("%04d%s\n" % (i, "x" * 2000) for i in range(50)))
cut = D.Handler.tail(s, tj["id"], 40).splitlines()
check("tail: a line the read window cut in half is dropped, every line returned is whole",
      0 < len(cut) < 40 and all(len(l) == 2004 for l in cut[:-2]), [len(l) for l in cut])

# ---------------------------------------------------------------- the watchdog on its own thread
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


clock_w = Clock()
beat = D.Heartbeat(clock_w)
check("watchdog: the heartbeat's age follows its clock and resets on a beat",
      beat.age() == 0 and (clock_w.__setattr__("t", 7.0) or beat.age()) == 7.0
      and (beat.beat() or beat.age()) == 0)


class StuckSched:
    """tick() blocks until released: a probe that does not come back."""
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def tick(self):
        self.entered.set()
        self.release.wait(20)


clock_w = Clock()
beat = D.Heartbeat(clock_w)
sent = []
stuck = StuckSched()
stop = D.start_threads(stuck, notify=sent.append, beat=beat, tick_s=0.01, interval=0.02, max_age=60)
try:
    in_tick = stuck.entered.wait(5)
    clock_w.t += 3.0                     # the tick has been running for 3 s
    n0 = len(sent)
    out_during = wait_for(lambda: len(sent) > n0 + 1, 3)
    check("watchdog: WATCHDOG=1 keeps going out while a 3 s tick is still running",
          in_tick and out_during and set(sent) == {"WATCHDOG=1"}, (in_tick, out_during, sent[:3]))
    clock_w.t += 58.0                    # 61 s since the last finished tick
    time.sleep(0.15)
    n1 = len(sent)
    time.sleep(0.2)
    check("watchdog: a tick stuck past 60 s stops WATCHDOG=1", len(sent) == n1, (n1, len(sent)))
    stuck.release.set()
    resumed = wait_for(lambda: len(sent) > n1, 3)
    check("watchdog: ...and the tick finishing brings it back", resumed)
finally:
    stuck.release.set()
    stop.set()


class RaisingSched:
    def __init__(self):
        self.n = 0

    def tick(self):
        self.n += 1
        raise RuntimeError("probe blew up")


clock_w = Clock()
rs, sent = RaisingSched(), []
stop = D.start_threads(rs, notify=sent.append, beat=D.Heartbeat(clock_w), tick_s=0.01,
                       interval=0.02, max_age=60)
wait_for(lambda: rs.n >= 3, 3)
clock_w.t += 70                      # no tick has beaten for 70 s of this clock, but ticks keep finishing
n_before = len(sent)
check("watchdog: a tick that raised still counts as finished; the ticker keeps ticking",
      rs.n >= 3 and wait_for(lambda: len(sent) > n_before, 3), (rs.n, len(sent)))
stop.set()

# ---------------------------------------------------------------- environment of the PopenRunner, unit file
cfg = configparser.ConfigParser(interpolation=None, strict=False)
here = os.path.dirname(os.path.abspath(__file__))
unit_path = os.path.join(here, "..", "..", "configs", "signalbox.service")
with open(unit_path) as f:
    unit_text = f.read()
cfg.read_string(unit_text)
svc = cfg["Service"]
check("service: KillMode=process, so a restart never touches the daemon's children",
      svc.get("KillMode") == "process", dict(svc))
check("service: the live unit's keys are kept (notify, WatchdogSec=30, restart policy, ExecStart)",
      svc.get("Type") == "notify" and svc.get("WatchdogSec") == "30"
      and svc.get("Restart") == "always" and svc.get("RestartSec") == "5"
      and svc.get("TimeoutStopSec") == "10"
      and svc.get("ExecStart") == "/usr/bin/python3 /home/user/signalbox/daemon.py --home /home/user/signalbox",
      dict(svc))
check("service: its header says how it is installed (cp to /etc/systemd/system, daemon-reload)",
      "cp configs/signalbox.service /etc/systemd/system/" in unit_text
      and "systemctl daemon-reload" in unit_text)
check("service: it says jobs are transient units re-adopted by unit and rc file, not 'by pid'",
      "transient unit" in unit_text and "rc file" in unit_text and "by pid" not in unit_text)
check("service: configs/signalbox.service is the only copy of the unit in the repo",
      not os.path.exists(os.path.join(here, "signalbox.service")))

# ---------------------------------------------------------------- S2a: classes, lanes, sitting, media, eta
def new_sched(**kw):
    fk = FakeUnitRunner()
    s, clock = make_sched(runner=fk, **kw)
    return s, clock, fk


def why(j):
    return j["wait_reason"] or ""


def later(clock, seconds):
    clock["now"] += D.timedelta(seconds=seconds)


NEW_CLASSES = ("media", "sitting", "lead", "round", "fill")

# -- 1. classes and priority
s, _, fk = new_sched()
got = {c: unit_job(s, "c-" + c, job_class=c)["priority"] for c in NEW_CLASSES}
check("class: media, sitting, lead, round and fill set the priority 950, 900, 700, 400 and -500",
      got == {"media": 950, "sitting": 900, "lead": 700, "round": 400, "fill": -500}, got)
kept = {c: unit_job(s, "k-" + c, job_class=c, priority=7)["priority"] for c in ("normal", "host", "solo")}
plain, clamped = unit_job(s, "plain"), unit_job(s, "clamped", priority=5000)
check("class: normal, host and solo keep the body's priority (default 0, clamped to 1000)",
      kept == {"normal": 7, "host": 7, "solo": 7} and plain["job_class"] == "normal"
      and (plain["priority"], clamped["priority"]) == (0, 1000), (kept, plain["priority"], clamped["priority"]))
mk = unit_job(s, "mk", kind="media-take", script="img", job_class="round")
ck = unit_job(s, "ck", kind="comfy-session", job_class="fill", card="3090")
pk = unit_job(s, "pk", kind="media-take", script="img", priority=-9)
check("class: media-take and comfy-session are always class media at 950, whatever the body says",
      all((j["job_class"], j["priority"]) == ("media", 950) for j in (mk, ck, pk)),
      [(j["job_class"], j["priority"]) for j in (mk, ck, pk)])
bad = []
for c in NEW_CLASSES:
    for pr in (0, 5):
        try:
            unit_job(s, "cp-%s-%d" % (c, pr), job_class=c, priority=pr)
            bad.append((c, pr, "accepted"))
        except ValueError as e:
            if not (c in str(e) and '"priority"' in str(e)):
                bad.append((c, pr, str(e)))
check("class: a body that names one of the five classes and carries priority is refused, by name",
      not bad, bad)
refused_other = []
for v in ("vip", None, 5):
    try:
        unit_job(s, "vip", job_class=v)
        refused_other.append(v)
    except ValueError:
        pass
check("class: an unknown or null job_class is still refused", not refused_other, refused_other)
lead_job = unit_job(s, "leadjob", job_class="lead")
try:
    s.set_priority(lead_job["id"], 5)
    set_ok = True
except ValueError as e:
    set_ok = False
check("class: /priority is refused on a job whose class sets it, and the priority is unchanged",
      not set_ok and lead_job["priority"] == 700, lead_job["priority"])

# -- 2. lanes: both and none
s, clock, fk = new_sched()
a = unit_job(s, "a", card="a6000", job_class="round", expected_s=600)
s.tick()
b = unit_job(s, "b", card="both", job_class="lead")
s.tick()
check("lanes: a both job waits while one lane is busy",
      b["status"] == "queued" and why(b) == "lanes busy", (b["status"], why(b)))
fk.finish(a, 0)
s.tick()
check("lanes: a both job starts when both lanes are free, holds both, resolves to both",
      b["status"] == "running" and b["resolved_card"] == "both"
      and s.lane_busy("a6000") and s.lane_busy("3090"), (b["status"], b["resolved_card"]))
c1 = unit_job(s, "c1", card="a6000")
c2 = unit_job(s, "c2", card="3090")
c3 = unit_job(s, "c3", card="any")
s.tick()
check("lanes: a running both job keeps a job on either card, and an any job, waiting",
      [j["status"] for j in (c1, c2, c3)] == ["queued"] * 3, [j["status"] for j in (c1, c2, c3)])
for lock_name, card_name in (("bloomery-gate-a6000.lock", "a6000"), ("bloomery-gate.lock", "3090")):
    s, _, fk = new_sched(fake=False, locks={lock_name: "held"})
    b = unit_job(s, "b", card="both", job_class="lead")
    s.tick()
    check("lanes: a both job needs %s's reasons empty too (%s held)" % (card_name, lock_name),
          b["status"] == "queued" and lock_name in why(b), (b["status"], why(b)))
s, _, fk = new_sched(fake=False, locks={"bloomery-gate-a6000.lock": "held"},
                     vram={"a6000": 24000})
busy_a = unit_job(s, "busy", card="3090", job_class="round", expected_s=600)
host = unit_job(s, "host", card="none", job_class="round")
s.tick()
t3090 = unit_job(s, "t3090", card="3090")
s.tick()
check("lanes: a none job runs beside a busy lane and past a card's lock and VRAM, holding no lane",
      host["status"] == "running" and host["resolved_card"] == "none"
      and not s.lane_busy("a6000") and s.lane_busy("3090")
      and busy_a["status"] == "running" and t3090["status"] == "queued", (host["status"], why(host)))
s, _, fk = new_sched(fake=False, holds=["bloomery-03-hold"], hold_ages={"bloomery-03-hold": 12})
host = unit_job(s, "host", card="none", job_class="lead")
s.tick()
check("lanes: a none job waits on a bloomery hold",
      host["status"] == "queued" and "bloomery-03-hold" in why(host), (host["status"], why(host)))
s, _, fk = new_sched(fake=False, lease={"tag": "ltx-x", "pid": os.getpid()})
host = unit_job(s, "host", card="none", job_class="lead")
s.tick()
check("lanes: a none job waits on the gpu-lease (timing)",
      host["status"] == "queued" and "gpu-lease" in why(host), (host["status"], why(host)))

# -- 3. sitting: solo semantics and the drain barrier
s, clock, fk = new_sched()
a = unit_job(s, "a", card="a6000", job_class="round", expected_s=300)
b = unit_job(s, "b", card="3090", job_class="round", expected_s=300)
s.tick()
sit = unit_job(s, "sit", card="both", job_class="sitting", expected_s=900)
r = unit_job(s, "r", card="a6000", job_class="round")
n = unit_job(s, "n", card="none", job_class="fill")
s.tick()
check("sitting: a queued sitting starts only on an empty box",
      sit["status"] == "queued" and "empty box" in why(sit), (sit["status"], why(sit)))
check("sitting: while it is queued a later round and a none job of lower priority are not admitted",
      r["status"] == "queued" and "sitting sit" in why(r)
      and n["status"] == "queued" and "sitting sit" in why(n), (why(r), why(n)))
fk.finish(a, 0)
s.tick()
check("sitting: ...even on a lane that has drained, while one job still runs",
      sit["status"] == "queued" and r["status"] == "queued" and b["status"] == "running",
      (sit["status"], r["status"]))
fk.finish(b, 0)
s.tick()
check("sitting: it starts on the empty box; the round and a none job wait for it, it is solo",
      sit["status"] == "running" and r["status"] == "queued" and "a sitting job owns the box" in why(r)
      and n["status"] == "queued", (sit["status"], r["status"], why(r), n["status"]))
fk.finish(sit, 0)
s.tick()
check("sitting: the round starts once the sitting has run", r["status"] == "running", r["status"])
s, clock, fk = new_sched()
a = unit_job(s, "a", card="a6000", job_class="round", expected_s=300)
b = unit_job(s, "b", card="3090", job_class="round", expected_s=300)
s.tick()
sit = unit_job(s, "sit", card="both", job_class="sitting", expected_s=900)
m = unit_job(s, "m", kind="media-take", script="img")
fk.finish(a, 0)
s.tick()
check("sitting: a queued sitting does not hold media, which has the higher priority",
      m["status"] == "running" and sit["status"] == "queued", (m["status"], sit["status"]))

# -- 4. media: ahead of the queue, never preempting, holding its card
s, clock, fk = new_sched()
x = unit_job(s, "x", job_class="round", card="a6000", expected_s=600)
s.tick()
lead = unit_job(s, "lead", job_class="lead", card="a6000")
m = unit_job(s, "m", kind="media-take", script="img")
s.tick()
fk.finish(x, 0)
s.tick()
check("media: started at 950 ahead of a queued lead at 700 on the a6000",
      m["status"] == "running" and lead["status"] == "queued", (m["status"], lead["status"]))
s, clock, fk = new_sched()
x = unit_job(s, "x", job_class="round", card="a6000", expected_s=600)
s.tick()
m = unit_job(s, "m", kind="media-take", script="img")
s.tick()
s.tick()
check("media: a running round is not preempted by a queued media job, nothing is stopped",
      x["status"] == "running" and m["status"] == "queued" and why(m) == "lanes busy"
      and not any(c[:2] == ["systemctl", "stop"] for c in fk.calls), (x["status"], m["status"], why(m)))
s, clock, fk = new_sched(fake=False, vram={"a6000": 24000})
m = unit_job(s, "m", kind="media-take", script="img")
lead = unit_job(s, "lead", job_class="lead", card="a6000")
s.tick()
check("media: with media queued on the a6000 (blocked by VRAM) a lead there waits for it, by name",
      m["status"] == "queued" and "above" in why(m) and lead["status"] == "queued"
      and "media job m is queued for a6000" in why(lead), (why(m), why(lead)))
s, clock, fk = new_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45))
m = unit_job(s, "m", kind="media-take", script="img", expected_s=1800)
lead = unit_job(s, "lead", job_class="lead", card="a6000")
n = unit_job(s, "n", card="none")
t = unit_job(s, "t", card="3090")
s.tick()
check("media: a lane that is free and a media job blocked on its own (a window) still holds the lead off",
      m["status"] == "queued" and "would cross" in why(m) and lead["status"] == "queued"
      and "media job m" in why(lead), (why(m), lead["status"], why(lead)))
check("media: ...and holds nothing on the 3090 or a job with no card",
      n["status"] == "running" and t["status"] == "running", (n["status"], t["status"]))
s, clock, fk = new_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45))
m = unit_job(s, "m", kind="media-take", script="img", expected_s=1800)
anyj = unit_job(s, "anyj", card="any")
s.tick()
check("media: an any job goes to the 3090 while media is queued for the a6000",
      anyj["status"] == "running" and anyj["resolved_card"] == "3090", (anyj["status"], anyj["resolved_card"]))

seen = []
for cls, card in (("sitting", "3090"), ("solo", "none")):
    s, clock, fk = new_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45))
    m = unit_job(s, "m", kind="media-take", script="img", expected_s=1800)
    ex = unit_job(s, "ex", card=card, job_class=cls, expected_s=100)
    s.tick()
    seen.append((m["status"], ex["status"], why(ex)))
check("media: a sitting or solo job naming the 3090 or no card takes every card once it starts, "
      "so media queued for the a6000 goes first",
      all(m_st == ex_st == "queued" and "media job m" in w for m_st, ex_st, w in seen), seen)

# cache groups reach only between media jobs, and only between bloomery jobs
s, clock, fk = new_sched(cooldown=60)
g = unit_job(s, "g", card="3090", cache_group="glm", job_class="round")
s.tick()
m = unit_job(s, "m", kind="media-take", script="img")
s.tick()
check("cache: media is not held by a bloomery cache group that is running",
      m["status"] == "running", why(m))
fk.finish(m, 0); fk.finish(g, 0)
s.tick()
m2 = unit_job(s, "m2", kind="media-take", script="img")
s.tick()
check("cache: media takes no cooldown from a bloomery group that just left",
      m2["status"] == "running", why(m2))
s, clock, fk = new_sched(cooldown=60)
m = unit_job(s, "m", kind="media-take", script="img")
s.tick()
g = unit_job(s, "g", card="3090", cache_group="glm", job_class="round")
s.tick()
check("cache: a bloomery cache group is not held by a media job that is running",
      g["status"] == "running", why(g))
fk.finish(m, 0)
s.tick()
q = unit_job(s, "q", card="a6000", cache_group="glm", job_class="round")
s.tick()
check("cache: a bloomery job takes no cooldown from the media group that just left",
      q["status"] == "running", why(q))
s, clock, fk = new_sched(cooldown=60)
m1 = unit_job(s, "m1", kind="media-take", script="img")
s.tick()
cs = unit_job(s, "cs", kind="comfy-session", card="3090", cache_group="other")
s.tick()
check("cache: the exclusion still holds between media jobs",
      cs["status"] == "queued" and "cache group media running" in why(cs), (cs["status"], why(cs)))
fk.finish(m1, 0)
s.tick()
check("cache: ...and so does the cooldown after one leaves",
      cs["status"] == "queued" and "cooldown" in why(cs), (cs["status"], why(cs)))
later(clock, 61)
s.tick()
check("cache: ...until it expires", cs["status"] == "running", (cs["status"], why(cs)))

# -- 5. expected_s
s, clock, fk = new_sched()
vals = [unit_job(s, "e1", expected_s=90)["expected_s"], unit_job(s, "e2", expected_min=2)["expected_s"],
        unit_job(s, "e3")["expected_s"], unit_job(s, "e4", expected_min=2, expected_s=45)["expected_s"],
        unit_job(s, "e5", expected_s=None, expected_min=1)["expected_s"]]
check("expected_s: the job's value, else expected_min x 60, else 0 (unknown); null is absent",
      vals == [90, 120, 0, 45, 60], vals)
bad = []
for v in (0, 604801, True, "5", 1.5, -3, [1]):
    try:
        unit_job(s, "bad%d" % len(bad), expected_s=v)
        bad.append(v)
    except ValueError:
        pass
edges = [unit_job(s, "lo", expected_s=1)["expected_s"], unit_job(s, "hi", expected_s=604800)["expected_s"]]
check("expected_s: 0, 604801, a bool, a string, a float, a negative and a list are refused; 1 and 604800 pass",
      not bad and edges == [1, 604800], (bad, edges))
s, clock, fk = new_sched()
r = unit_job(s, "r", card="a6000", job_class="round", expected_s=300)
s.tick()
q = unit_job(s, "q", card="a6000", job_class="round")
check("expected_s: eta counts the running job's remaining expected_s (no expected_min given)",
      s.eta_seconds(q) == 300, s.eta_seconds(q))
later(clock, 100)
check("expected_s: ...less what has run", s.eta_seconds(q) == 200, s.eta_seconds(q))
s, clock, fk = new_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45))
long_j = unit_job(s, "long", expected_s=1800)
short_j = unit_job(s, "short", card="3090", expected_s=300)
s.tick()
check("expected_s: a job that would run into a window is held by its expected_s alone",
      long_j["status"] == "queued" and "would cross" in why(long_j) and short_j["status"] == "running",
      (long_j["status"], why(long_j), short_j["status"]))

# -- 6. eta honesty
s, clock, fk = new_sched(fake=False, locks={"bloomery-gate-a6000.lock": "held"})
j = unit_job(s, "j", card="a6000", job_class="lead")
s.tick()
check("eta: behind an external lock on a free lane it is unknown (None), never 0",
      j["status"] == "queued" and "bloomery-gate-a6000.lock" in why(j) and s.eta_seconds(j) is None,
      (why(j), s.eta_seconds(j)))
s, clock, fk = new_sched(fake=False, holds=["bloomery-03-hold"], hold_ages={"bloomery-03-hold": 125.7})
j = unit_job(s, "j", card="a6000", job_class="lead")
s.tick()
check("eta: a hold that is not a queue job puts its age in the wait reason, `hold <name> up <s> s`",
      "hold bloomery-03-hold up 125 s" in why(j) and s.eta_seconds(j) is None, (why(j), s.eta_seconds(j)))
hold_dir = tempfile.mkdtemp(prefix="signalbox-holds-")
hold_file = os.path.join(hold_dir, "bloomery-t-hold")
open(hold_file, "w").close()
os.utime(hold_file, (time.time() - 120, time.time() - 120))
s, clock, fk = new_sched(fake=False)
s.probes = D.Probes(gpu_order="/nonexistent", lease="/nonexistent", lock_glob="/nonexistent/*",
                    hold_glob=hold_dir + "/bloomery-*-hold")
age, reasons = s.probes.hold_age_s(hold_file), s.hold_reasons()
check("hold: the real probe reads a hold file's age from its mtime (120 s), the reason is `hold <name> up <s> s`",
      119 <= age <= 125 and reasons in (["hold bloomery-t-hold up %d s" % n] for n in range(119, 126)),
      (age, reasons))
check("hold: a hold file that is gone has no age", s.probes.hold_age_s(hold_dir + "/nope") is None)
s, clock, fk = new_sched(fake=False)
sit = unit_job(s, "sit", job_class="sitting", card="both", expected_s=600)
s.tick()
s.probes.hold_state = ["bloomery-03-hold"]
s.probes.hold_age_state = {"bloomery-03-hold": 30}
s.probes.lock_state = {"bloomery-gate.lock": "held", "bloomery-gate-a6000.lock": "held"}
later(clock, 100)
r = unit_job(s, "r", job_class="round", card="a6000")
n = unit_job(s, "n", job_class="lead", card="none")
s.tick()
check("eta: behind a running sitting it is the sitting's remaining expected_s (600 - 100)",
      sit["status"] == "running" and s.eta_seconds(r) == 500 and s.eta_seconds(n) == 500
      and "a sitting job owns the box" in why(r), (s.eta_seconds(r), s.eta_seconds(n), why(r)))
later(clock, 300)
check("eta: ...less what has run since", s.eta_seconds(r) == 200, s.eta_seconds(r))
later(clock, 300)
check("eta: a sitting past its estimate is unknown, never 0", s.eta_seconds(r) is None, s.eta_seconds(r))
s, clock, fk = new_sched(fake=False)
sit = unit_job(s, "sit", job_class="sitting", card="both")
s.tick()
s.probes.hold_state = ["bloomery-03-hold"]
r = unit_job(s, "r", job_class="round", card="a6000")
s.tick()
check("eta: a running sitting with no estimate is unknown", s.eta_seconds(r) is None, s.eta_seconds(r))
etas = []
for card in ("both", "any"):
    s, clock, fk = new_sched()
    unit_job(s, "x", card="a6000", expected_s=100)
    unit_job(s, "y", card="3090", expected_s=300)
    s.tick()
    etas.append(s.eta_seconds(unit_job(s, "q", card=card, job_class="round")))
check("eta: a both job waits for the later lane (300 s), an any job for the earlier (100 s)",
      etas == [300, 100], etas)
s, clock, fk = new_sched()
bj = unit_job(s, "bj", card="both", job_class="lead", expected_s=300)
s.tick()
qa, qb = unit_job(s, "qa", card="a6000"), unit_job(s, "qb", card="3090")
check("eta: a running both job counts on each card",
      s.eta_seconds(qa) == 300 and s.eta_seconds(qb) == 300, (s.eta_seconds(qa), s.eta_seconds(qb)))
free_j = unit_job(s, "fj", card="none")
check("eta: 0 when the job could start now", s.eta_seconds(free_j) == 0, s.eta_seconds(free_j))


def scenario_lock():
    s, clock, fk = new_sched(fake=False, locks={"bloomery-gate-a6000.lock": "held"})
    return s, unit_job(s, "j", card="a6000")


def scenario_hold():
    s, clock, fk = new_sched(fake=False, holds=["bloomery-03-hold"], hold_ages={"bloomery-03-hold": 5})
    return s, unit_job(s, "j", card="a6000")


def scenario_lease():
    s, clock, fk = new_sched(fake=False, lease={"tag": "img-x", "pid": os.getpid()})
    return s, unit_job(s, "j", card="a6000")


def scenario_vram():
    s, clock, fk = new_sched(fake=False, vram={"a6000": 24000})
    return s, unit_job(s, "j", card="a6000")


def scenario_reservation():
    s, clock, fk = new_sched(fake=False, windows=[train], now=datetime(2026, 10, 3, 13, 30))
    return s, unit_job(s, "j", card="a6000")


def scenario_crossing():
    s, clock, fk = new_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45))
    return s, unit_job(s, "j", card="a6000", expected_s=1800)


def scenario_lane_known():
    s, clock, fk = new_sched()
    unit_job(s, "r", card="a6000", expected_s=600)
    s.tick()
    return s, unit_job(s, "j", card="a6000")


def scenario_lane_unknown():
    s, clock, fk = new_sched()
    unit_job(s, "r", card="a6000")
    s.tick()
    return s, unit_job(s, "j", card="a6000")


def scenario_owner():
    s, clock, fk = new_sched()
    unit_job(s, "r", job_class="solo", expected_s=100)
    s.tick()
    return s, unit_job(s, "j", card="3090")


def scenario_barrier():
    s, clock, fk = new_sched()
    unit_job(s, "r", card="a6000", expected_s=50)
    s.tick()
    unit_job(s, "sit", job_class="sitting", card="both", expected_s=100)
    return s, unit_job(s, "j", card="3090", job_class="round")


def scenario_media_queued():
    s, clock, fk = new_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45))
    unit_job(s, "m", kind="media-take", script="img", expected_s=1800)
    return s, unit_job(s, "j", card="a6000", job_class="lead")


def scenario_cache_running():
    s, clock, fk = new_sched(cooldown=60)
    unit_job(s, "g", card="3090", cache_group="glm", expected_s=100)
    s.tick()
    return s, unit_job(s, "j", card="a6000", cache_group="qwen")


def scenario_cache_cooling():
    s, clock, fk = new_sched(cooldown=60)
    g = unit_job(s, "g", card="3090", cache_group="glm", expected_s=100)
    s.tick()
    fk.finish(g, 0)
    s.tick()
    return s, unit_job(s, "j", card="a6000", cache_group="qwen")


s, j = scenario_barrier()
check("eta: behind a queued sitting it is the box's drain (50 s) plus the sitting's expected time (100 s)",
      s.eta_seconds(j) == 150, s.eta_seconds(j))
leaks = []
for name, build in sorted(globals().items()):
    if not name.startswith("scenario_"):
        continue
    s, j = build()
    s.tick()
    lane, reason = s.can_start(j)
    eta = s.eta_seconds(j)
    if lane is not None or not (eta is None or eta > 0):
        leaks.append((name, lane, reason, eta))
check("eta: for every blocker (lock, hold, lease, VRAM, reservation, window, lane, owner, barrier, "
      "queued media, cache group) a blocked job's eta is None or above 0, never 0", not leaks, leaks)

# -- 7. SIGNALBOX_CARD in the unit's environment
s, clock, fk = new_sched(fake=False, locks={"bloomery-gate-a6000.lock": "held"})
unit_job(s, "ca", card="3090", env={"SIGNALBOX_CARD": "set-by-the-body"})
unit_job(s, "cn", card="none")
s.tick()
cards_seen = [[a for a in c if a.startswith("SIGNALBOX_CARD=")] for c in fk.systemd_runs()]
check("env: the job's env carries SIGNALBOX_CARD=<lane> once, the daemon's value over the body's",
      sorted(cards_seen) == [["SIGNALBOX_CARD=3090"], ["SIGNALBOX_CARD=none"]]
      and all(c[c.index(seen[0]) - 1] == "--setenv"
              for c, seen in zip(fk.systemd_runs(), cards_seen) if seen), cards_seen)
s, clock, fk = new_sched()
a = unit_job(s, "a", card="a6000", job_class="round", expected_s=300)
s.tick()
unit_job(s, "b", card="both", job_class="lead")
fk.finish(a, 0)
s.tick()
check("env: a both job runs with SIGNALBOX_CARD=both",
      any("SIGNALBOX_CARD=both" in c for c in fk.systemd_runs()), fk.systemd_runs())
s, clock, fk = new_sched(fake=False, locks={"bloomery-gate-a6000.lock": "held"})
anyj = unit_job(s, "anyj", card="any", job_class="lead")
s.tick()
check("env: an any job's SIGNALBOX_CARD is the card it resolved to (3090) and the job records it",
      any("SIGNALBOX_CARD=3090" in c for c in fk.systemd_runs()) and anyj["resolved_card"] == "3090",
      (fk.systemd_runs(), anyj["resolved_card"]))

# -- 8. any tries every card
s, clock, fk = new_sched(fake=False, locks={"bloomery-gate-a6000.lock": "held"})
a_any = unit_job(s, "a", card="any", job_class="lead")
s.tick()
check("any: starts on the 3090 while the a6000 has a lock reason",
      a_any["status"] == "running" and a_any["resolved_card"] == "3090", (a_any["status"], why(a_any)))
s, clock, fk = new_sched(fake=False, vram={"a6000": 24000})
a_any = unit_job(s, "a", card="any", job_class="lead")
s.tick()
check("any: ...and while the a6000 is above the VRAM line", a_any["resolved_card"] == "3090", why(a_any))
s, clock, fk = new_sched(fake=False)
a_any = unit_job(s, "a", card="any", job_class="lead")
s.tick()
check("any: takes the first card in CARDS order when both qualify", a_any["resolved_card"] == "a6000",
      a_any["resolved_card"])
s, clock, fk = new_sched(fake=False, locks={"bloomery-gate-a6000.lock": "held", "bloomery-gate.lock": "held"})
a_any = unit_job(s, "a", card="any", job_class="lead")
s.tick()
check("any: when no card qualifies the wait reason names each card's reasons",
      a_any["status"] == "queued"
      and "a6000: bloomery-gate-a6000.lock: held" in why(a_any)
      and "3090: bloomery-gate.lock: held" in why(a_any), why(a_any))

# -- 9. the wire: fields the client reads, refusals as rc 64
s, clock, fk = new_sched()
D.Handler.sched = s
httpd2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
threading.Thread(target=httpd2.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd2.server_address[1]
WIRE = ("id", "status", "rc", "wait_reason", "eta_s", "out", "err", "rc_file", "resolved_card")
old_home = tempfile.mkdtemp(prefix="signalbox-oldstate-")
with open(os.path.join(old_home, "state.json"), "w") as f:
    json.dump({"seq": 1, "events": [], "jobs": [{
        "id": "s1", "owner": "t", "name": "old", "title": "", "expected_min": 5, "kind": "command",
        "job_class": "normal", "priority": 0, "script": "", "card": "a6000", "cache_group": "",
        "env": {}, "argv": "true", "bound_s": None, "status": "queued",
        "submitted": "2026-10-10T20:00:00", "started": None, "finished": None, "rc": None,
        "sentinel": None, "pid": None, "wait_reason": None, "artifacts": []}]}, f)
old_s, _ = make_sched(home=old_home)
old_view = old_s.job_view(old_s.by_id("s1"))
check("wire: a queued job written before the wire fields existed answers with all of them, "
      "its expected_s from expected_min", all(k in old_view for k in WIRE)
      and old_view["expected_s"] == 300 and old_view["eta_s"] == 0, old_view)
body = {"kind": "command", "argv": "true", "owner": "t", "card": "a6000", "wait": 0}
code, out = call("POST", "/jobs", dict(body, name="w1", job_class="lead", expected_s=60))
check("wire: POST /jobs of a queued job is 201 with every field the client reads, class and priority set",
      code == 201 and all(k in out for k in WIRE) and out["status"] == "queued"
      and (out["job_class"], out["priority"], out["expected_s"], out["eta_s"]) == ("lead", 700, 60, 0),
      (code, out))
s.tick()
code, out = call("GET", "/jobs/w1")
check("wire: GET /jobs/<id> of a running job carries them too, with absolute out, err, rc_file",
      code == 200 and all(k in out for k in WIRE) and out["status"] == "running"
      and out["resolved_card"] == "a6000" and out["eta_s"] == 0
      and all(os.path.isabs(out[k]) for k in ("out", "err", "rc_file")), (code, out))
code, out = call("POST", "/jobs", dict(body, name="w2", job_class="round", expected_s=30))
s.tick()
code2, out2 = call("GET", "/jobs/w2")
check("wire: a queued job behind it reports eta_s (the running job's remaining 60 s) and why it waits",
      code == 201 and out.get("eta_s") == 60 and out2.get("eta_s") == 60
      and out2.get("wait_reason") == "lanes busy",
      (out, out2))
s.fake = False
s.probes.lock_state = {"bloomery-gate.lock": "held"}
code, out = call("POST", "/jobs", dict(body, name="w3", card="3090", job_class="round"))
s.tick()
code2, out2 = call("GET", "/jobs/w3")
check("wire: behind an external lock eta_s is null (not 0) and wait_reason names the lock",
      code == 201 and out.get("eta_s", "missing") is None and out2.get("eta_s", "missing") is None
      and "bloomery-gate.lock: held" in (out2.get("wait_reason") or ""), (out, out2))
before = len(s.jobs)
code, out = call("POST", "/jobs", dict(body, name="w4", job_class="lead", priority=5))
check("wire: a body naming a class and carrying priority is 400 with rc 64, by name, and queues nothing",
      code == 400 and out.get("rc") == 64 and "lead" in out["error"] and "priority" in out["error"]
      and len(s.jobs) == before, (code, out))
code, out = call("POST", "/jobs/w1/priority", {"priority": 1})
check("wire: /jobs/<id>/priority on a class job is 400 with rc 64",
      code == 400 and out.get("rc") == 64 and s.by_id("w1")["priority"] == 700, (code, out))
code, out = call("POST", "/jobs", dict(body, name="w5", expected_s=0))
check("wire: expected_s 0 is 400 with rc 64", code == 400 and out.get("rc") == 64, (code, out))
code, listing = call("GET", "/jobs")
check("wire: GET /jobs lists job_class, expected_s and resolved_card",
      code == 200 and {"job_class", "expected_s", "resolved_card"} <= set(listing[0]), listing[0])
code, out = call("POST", "/gen/image", {"prompt": "a red kite", "priority": 3, "wait": 0})
check("wire: a /gen body's priority is not read: the job is media at 950",
      code == 201 and (out["job_class"], out["priority"]) == ("media", 950), (code, out))
httpd2.shutdown()

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
