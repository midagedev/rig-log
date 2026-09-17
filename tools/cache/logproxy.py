#!/usr/bin/env python3
"""Logging reverse proxy: listens on 8002, forwards to 127.0.0.1:8001, writes each
request body to OUT/req-<n>.json and the full response bytes to OUT/res-<n>.txt.
Streaming responses are relayed chunk by chunk. stdlib only."""
import http.server, http.client, json, os, sys, threading, time
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/user/cache-probe"
os.makedirs(OUT, exist_ok=True)
lock = threading.Lock(); counter = [0]
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _relay(self):
        n = self.headers.get("Content-Length"); body = self.rfile.read(int(n)) if n else b""
        with lock:
            counter[0] += 1; i = counter[0]
        t0 = time.time()
        with open(f"{OUT}/req-{i}.json", "wb") as f: f.write(body)
        with open(f"{OUT}/req-{i}.meta", "w") as f: f.write(f"{time.strftime('%H:%M:%S')} {self.command} {self.path} {len(body)} bytes\n")
        c = http.client.HTTPConnection("127.0.0.1", 8001, timeout=3600)
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "accept-encoding")}
        hdrs["Content-Length"] = str(len(body))
        c.request(self.command, self.path, body=body, headers=hdrs)
        r = c.getresponse()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() in ("content-length", "transfer-encoding", "connection"): continue
            self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked"); self.send_header("Connection", "close"); self.end_headers()
        out = open(f"{OUT}/res-{i}.txt", "wb")
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
            if not chunk: break
            out.write(chunk)
            self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n"); self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n"); out.close(); c.close()
        with open(f"{OUT}/req-{i}.meta", "a") as f: f.write(f"done {time.time()-t0:.1f} s status {r.status}\n")
    do_POST = _relay; do_GET = _relay
http.server.ThreadingHTTPServer.allow_reuse_address = True
http.server.ThreadingHTTPServer(("127.0.0.1", 8002), H).serve_forever()
