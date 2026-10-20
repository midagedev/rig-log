#!/usr/bin/env python3
"""The one way a box-side tool asks signalbox's ledger (POST /grants, DELETE /grants/<id>,
GET /ledger). It fails closed: a client that cannot reach signalbox ends rc 69 with a line that
says where it looked and what systemd says about the unit, and nothing is admitted. The operator's
override is BOXRES_OFF=1: the client prints one line saying the ledger is bypassed, asks nothing,
and the caller goes on.

    client.py GET /ledger
    client.py POST /grants '{"holder": "tape", "class": "tape", ...}'

Exit: 0 for a 2xx reply or a bypass, the reply's own rc for a refusal (75 contention, 64 usage,
66 not there, 69 the broker is blind), 69 when signalbox is unreachable. stdlib only.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

URL = os.environ.get("BOXRES_URL", "http://127.0.0.1:8030")
BYPASS_LINE = ("boxres: BOXRES_OFF=1: the resource ledger is bypassed; this call is not admitted, "
               "reserved or measured")
UNREACHABLE_RC = 69
_bypass_said = False


class Down(Exception):
    """signalbox cannot be reached or answers outside its wire: rc 69, the message names it."""

    rc = UNREACHABLE_RC


def unit_state(unit="signalbox"):
    """What `systemctl is-active` says about the daemon, for the line a refusal carries."""
    if not shutil.which("systemctl"):
        return "unknown (no systemctl here)"
    try:
        p = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True,
                           timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "unknown (%s)" % e
    return p.stdout.strip() or "unknown (rc %d)" % p.returncode


def ask(method, path, body=None, env=None, url=None, timeout=10, err=None):
    """(status, JSON object) of one request; None when BOXRES_OFF=1 bypassed the ledger (the
    bypass line is printed once per process). Down when signalbox cannot be reached."""
    global _bypass_said
    env = os.environ if env is None else env
    err = sys.stderr if err is None else err
    if env.get("BOXRES_OFF") == "1":
        if not _bypass_said:
            print(BYPASS_LINE, file=err, flush=True)
            _bypass_said = True
        return None
    base = (url or env.get("BOXRES_URL") or URL).rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        raise Down("boxres: signalbox is unreachable at %s (%s); systemctl is-active signalbox: %s; "
                   "refused rc %d, nothing was admitted; BOXRES_OFF=1 bypasses the ledger"
                   % (base, getattr(e, "reason", e), unit_state(), UNREACHABLE_RC))
    try:
        obj = json.loads(raw)
    except ValueError:
        raise Down("boxres: signalbox at %s answered %s with something that is not JSON: %r; "
                   "refused rc %d" % (base, code, raw[:80], UNREACHABLE_RC))
    return code, obj


def exit_code(code, obj):
    """The process exit of a reply: 0 for a 2xx, else the reply's rc (70 when it names none)."""
    if 200 <= code < 300:
        return 0
    rc = obj.get("rc") if isinstance(obj, dict) else None
    return rc if isinstance(rc, int) and not isinstance(rc, bool) and 1 <= rc <= 255 else 70


def main(argv, env=None, out=None, err=None):
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if len(argv) not in (2, 3) or argv[0] not in ("GET", "POST", "DELETE"):
        print("usage: client.py GET|POST|DELETE PATH [JSON]", file=err)
        return 64
    try:
        body = json.loads(argv[2]) if len(argv) == 3 else None
    except ValueError as e:
        print("boxres: the body is not JSON (%s)" % e, file=err)
        return 64
    try:
        reply = ask(argv[0], argv[1], body, env=env, err=err)
    except Down as e:
        print(e, file=err)
        return e.rc
    if reply is None:
        return 0
    code, obj = reply
    rc = exit_code(code, obj)
    if rc:
        print(obj.get("error", json.dumps(obj)) if isinstance(obj, dict) else obj, file=err)
    print(json.dumps(obj, ensure_ascii=False, indent=1), file=out)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
