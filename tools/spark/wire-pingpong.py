#!/usr/bin/env python3
"""TCP round trip between the workstation and the Spark, the probe behind log 2026-11-04 spark-direct-link and
2026-11-24 cx-link.

The client sends a 4-byte little-endian length and that many payload bytes; the server echoes the same frame back.
TCP_NODELAY on both ends. Per size, N round trips, the first SKIP dropped, µs percentiles printed. Both ends are
Python, so the numbers are an upper bound that carries both interpreters' cost.

    wire-pingpong.py serve [--bind 0.0.0.0] [--port 9500]          # one client at a time, forever
    wire-pingpong.py client HOST [--port 9500] [--sizes 64,8192,16384] [-n 2200] [--skip 200]
    wire-pingpong.py --self-test
"""
import argparse
import socket
import struct
import sys
import time


def recv_exact(s, n, buf=None):
    buf = bytearray(n) if buf is None else buf
    view = memoryview(buf)[:n]
    got = 0
    while got < n:
        k = s.recv_into(view[got:], n - got)
        if k == 0:
            raise ConnectionError(f"peer closed after {got} of {n} bytes")
        got += k
    return buf


def serve(bind, port):
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind((bind, port))
    ls.listen(1)
    buf = bytearray(1 << 24)
    while True:
        c, _ = ls.accept()
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            while True:
                (n,) = struct.unpack("<I", bytes(recv_exact(c, 4)))
                if n > len(buf):
                    raise ValueError(f"frame {n} B over the {len(buf)} B buffer")
                recv_exact(c, n, buf)
                c.sendall(struct.pack("<I", n) + bytes(memoryview(buf)[:n]))
        except ConnectionError:
            pass
        finally:
            c.close()


def pct(sorted_us, p):
    i = min(len(sorted_us) - 1, max(0, round(p / 100 * (len(sorted_us) - 1))))
    return sorted_us[i]


def summarize(samples_us):
    s = sorted(samples_us)
    return {"min": s[0], "p50": pct(s, 50), "p90": pct(s, 90), "p99": pct(s, 99)}


def client(host, port, sizes, n, skip):
    if skip >= n:
        sys.exit(f"--skip {skip} leaves no sample of -n {n}")
    s = socket.create_connection((host, port))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"# {host}:{port} n={n} skip={skip} µs")
    print(f"{'bytes':>8} {'min':>8} {'p50':>8} {'p90':>8} {'p99':>8}")
    for size in sizes:
        frame = struct.pack("<I", size) + bytes(size)
        back = bytearray(size + 4)
        us = []
        for i in range(n):
            t0 = time.perf_counter_ns()
            s.sendall(frame)
            recv_exact(s, size + 4, back)
            t1 = time.perf_counter_ns()
            if i >= skip:
                us.append((t1 - t0) / 1000)
        r = summarize(us)
        print(f"{size:>8} {r['min']:>8.1f} {r['p50']:>8.1f} {r['p90']:>8.1f} {r['p99']:>8.1f}", flush=True)
    s.close()


def self_test():
    # percentiles on a known list, and a loopback round trip that must echo the bytes it sent
    xs = summarize([float(v) for v in range(1, 101)])
    assert (xs["min"], xs["p50"], xs["p90"], xs["p99"]) == (1.0, 51.0, 90.0, 99.0), xs
    import threading
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    port = ls.getsockname()[1]
    ls.close()
    threading.Thread(target=serve, args=("127.0.0.1", port), daemon=True).start()
    for _ in range(100):
        try:
            s = socket.create_connection(("127.0.0.1", port))
            break
        except ConnectionRefusedError:
            time.sleep(0.01)
    payload = bytes(range(256)) * 40
    s.sendall(struct.pack("<I", len(payload)) + payload)
    back = recv_exact(s, len(payload) + 4)
    assert bytes(back[4:]) == payload and struct.unpack("<I", bytes(back[:4]))[0] == len(payload)
    s.close()
    print("self-test ok")


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("serve")
    a.add_argument("--bind", default="0.0.0.0")
    a.add_argument("--port", type=int, default=9500)
    b = sub.add_parser("client")
    b.add_argument("host")
    b.add_argument("--port", type=int, default=9500)
    b.add_argument("--sizes", default="64,8192,16384")
    b.add_argument("-n", type=int, default=2200)
    b.add_argument("--skip", type=int, default=200)
    o = ap.parse_args()
    if o.cmd == "serve":
        serve(o.bind, o.port)
    else:
        client(o.host, o.port, [int(x) for x in o.sizes.split(",")], o.n, o.skip)


if __name__ == "__main__":
    main()
