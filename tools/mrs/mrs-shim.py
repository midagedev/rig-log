#!/usr/bin/env python3
"""mrs-shim.py — a llama-server-protocol front for `mistralrs serve`, so toktape can attach.

toktape (0.2.4) attaches through GET /props and reads the rate out of the server's own
`timings` object on each stream chunk. mistral.rs serves neither (/props is 404, measured
2026-09-17) but does report its own prompt and completion times in the `usage` object of the
final chunk (`total_prompt_time_sec`, `total_completion_time_sec`, `prompt_tokens`,
`completion_tokens`). This shim sits in front of it and:

  GET  /props     answers as exl3-serve did (2026-09-15): model_path, total_slots, n_ctx and
                  an `engine` block naming mistral.rs — and no build_info, which would stamp
                  the card "llama-server".
  GET  /health    200 when the upstream /v1/models answers 200.
  GET  /slots     one row per --max-seqs, is_processing from the shim's in-flight count.
  POST /v1/chat/completions
                  forwarded byte-for-byte (mistral.rs ignores toktape's timings_per_token /
                  return_progress and honours chat_template_kwargs.enable_thinking — measured);
                  every chunk gets a provisional `timings` from the shim's wall clock, and the
                  chunk that carries `usage` gets the final `timings` copied from mistral.rs's
                  own figures: prompt_n/prompt_ms from prompt_tokens/total_prompt_time_sec,
                  predicted_n/predicted_ms from completion_tokens/total_completion_time_sec.
                  The wall-clock first-to-last-token time is printed beside the server's
                  completion time on stderr for every request, so the two can be compared.

Stdlib only (the box has no aiohttp). Configuration by environment, never argv, so that this
process's command line does not name the model: toktape's pid search scans cmdlines for
model_path AND requires the command to be a llama.cpp-family name (procmon.IsServerCommand), so
`mistralrs` is rejected either way and the recorder falls back to whoever holds the listening
port — which is this shim. Measured 2026-09-17: the card's MEMORY, page-fault and
"other GPU compute process" rows therefore describe the proxy, and `contended: yes` on every
mistral.rs card here is mistral.rs itself being counted as the other process.

  MRS_UPSTREAM   http://127.0.0.1:8013   MRS_MODEL   /path/to/model.gguf (required)
  SHIM_PORT      8014                    MRS_PID_FILE  file holding the mistralrs pid (argv)
  MRS_SLOTS      4                       MRS_NCTX    8192 (what --max-seq-len was given;
                                                     the paged pool is shared, not per slot)
  MRS_VERSION    "" (e.g. 0.9.3)         MRS_KV_BYTES  0 (paged KV allocation, if known)
"""
import http.client, json, os, struct, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

UP = urlparse(os.environ.get("MRS_UPSTREAM", "http://127.0.0.1:8013"))
PORT = int(os.environ.get("SHIM_PORT", "8014"))
MODEL = os.environ["MRS_MODEL"]
SLOTS = int(os.environ.get("MRS_SLOTS", "4"))
NCTX = int(os.environ.get("MRS_NCTX", "8192"))
VERSION = os.environ.get("MRS_VERSION", "")
KV_BYTES = int(os.environ.get("MRS_KV_BYTES", "0"))
PID_FILE = os.environ.get("MRS_PID_FILE", "")
SERVER_LOG = os.environ.get("MRS_SERVER_LOG", "")

inflight = 0
inflight_lock = threading.Lock()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


# --- GGUF header: the model in its own words, so the card's MODEL row is read, not guessed ---

def gguf_meta(path):
    """general.architecture, block/expert/context counts and the parameter count (sum of tensor
    element counts). Any failure returns {} and the engine block prints '?' for those fields."""
    T_U8, T_I8, T_U16, T_I16, T_U32, T_I32, T_F32, T_BOOL, T_STR, T_ARR, T_U64, T_I64, T_F64 = range(13)
    sizes = {T_U8: 1, T_I8: 1, T_U16: 2, T_I16: 2, T_U32: 4, T_I32: 4, T_F32: 4, T_BOOL: 1, T_U64: 8, T_I64: 8, T_F64: 8}
    fmts = {T_U8: "<B", T_I8: "<b", T_U16: "<H", T_I16: "<h", T_U32: "<I", T_I32: "<i", T_F32: "<f", T_BOOL: "<?", T_U64: "<Q", T_I64: "<q", T_F64: "<d"}
    try:
        with open(path, "rb") as f:
            def rd(n):
                b = f.read(n)
                if len(b) != n:
                    raise EOFError
                return b
            def u32(): return struct.unpack("<I", rd(4))[0]
            def u64(): return struct.unpack("<Q", rd(8))[0]
            def s(): return rd(u64()).decode("utf-8", "replace")
            def val(t):
                if t == T_STR:
                    return s()
                if t == T_ARR:
                    et, n = u32(), u64()
                    if et == T_STR:
                        return [s() for _ in range(n)]
                    if et == T_ARR:
                        return [val(T_ARR) for _ in range(n)]
                    f.seek(sizes[et] * n, 1)
                    return None
                return struct.unpack(fmts[t], rd(sizes[t]))[0]
            if rd(4) != b"GGUF":
                return {}
            u32()  # version
            n_tensors, n_kv = u64(), u64()
            kv = {}
            for _ in range(n_kv):
                k = s(); t = u32(); v = val(t)
                if not k.startswith("tokenizer.") or k == "tokenizer.chat_template":
                    kv[k] = v
            params = 0
            for _ in range(n_tensors):
                s(); nd = u32()
                n = 1
                for _ in range(nd):
                    n *= u64()
                u32(); u64()
                params += n
        arch = kv.get("general.architecture", "")
        g = lambda k: kv.get(f"{arch}.{k}") or 0
        return {"arch": arch, "n_layers": g("block_count"), "n_experts": g("expert_count"),
                "n_experts_used": g("expert_used_count"), "ctx_train": g("context_length"), "params": params,
                "chat_template": kv.get("tokenizer.chat_template", "")}
    except Exception as e:  # noqa: BLE001 — the header is a nicety; the take must not depend on it
        log("gguf header not read:", e)
        return {}


def quant_from_name(path):
    import re
    m = re.search(r"((?:UD-)?I?Q\d[A-Za-z0-9_]*|BF16|F16|F32)(?=\.gguf$|-|$)", os.path.basename(path))
    return m.group(1) if m else "?"


def upstream_pid():
    """The mistralrs pid, or 0. Declared to the recorder as engine.server_pid, which is what stops
    this shim from being the subject of its own measurement: toktape identifies the server it is
    attached to by process name, `mistralrs` is not a llama.cpp comm, and so every take recorded
    before this counted the shim's own process as a competing GPU process and stamped
    `contended: yes` (measured 2026-09-17 across eight takes, every witness reading io pressure 0).
    A declared pid outranks toktape's own searches; 0 means no declaration and the searches run as
    before, so an unreadable pid file degrades to the old behaviour rather than to a wrong subject."""
    try:
        return int(open(PID_FILE).read().split()[0])
    except Exception:  # noqa: BLE001
        return 0


def upstream_argv():
    pid = upstream_pid()
    if not pid:
        return []
    try:
        return open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", "replace").rstrip("\0").split("\0")
    except Exception:  # noqa: BLE001
        return []


def tensor_bytes(path):
    """Every tensor's size in bytes, from the differences between consecutive data offsets rather
    than from a ggml type table. The offsets are ordered and the last tensor runs to the end of the
    file, so this is exact (it counts each tensor's alignment padding with it) and needs no table of
    thirty quantization types that would rot the first time one is added. Returns {} on any failure,
    and the caller then sends no placement rather than a guessed one."""
    try:
        with open(path, "rb") as f:
            def rd(n):
                b = f.read(n)
                if len(b) != n:
                    raise EOFError
                return b
            def u32(): return struct.unpack("<I", rd(4))[0]
            def u64(): return struct.unpack("<Q", rd(8))[0]
            def st(): return rd(u64()).decode("utf-8", "replace")
            if rd(4) != b"GGUF":
                return {}
            u32()
            n_tensors, n_kv = u64(), u64()
            align = 32
            for _ in range(n_kv):
                k = st(); t = u32()
                # skip the value without interpreting it, except the one key that matters here
                if t == 8:      # string
                    v = st()
                elif t == 9:    # array
                    et, n = u32(), u64()
                    if et == 8:
                        for _ in range(n):
                            st()
                    elif et == 9:
                        raise ValueError("nested array")
                    else:
                        f.seek({0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}[et] * n, 1)
                    v = None
                else:
                    v = struct.unpack({0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f",
                                       7: "<?", 10: "<Q", 11: "<q", 12: "<d"}[t], rd({0: 1, 1: 1, 2: 2, 3: 2,
                                       4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}[t]))[0]
                if k == "general.alignment" and isinstance(v, int) and v > 0:
                    align = v
            infos = []
            for _ in range(n_tensors):
                name = st(); nd = u32()
                for _ in range(nd):
                    u64()
                u32(); off = u64()
                infos.append((name, off))
            pos = f.tell()
            data_start = pos + (-pos % align)
            data_bytes = os.stat(path).st_size - data_start
        infos.sort(key=lambda t: t[1])
        out = {}
        for i, (name, off) in enumerate(infos):
            end = infos[i + 1][1] if i + 1 < len(infos) else data_bytes
            out[name] = max(0, end - off)
        return out
    except Exception:  # noqa: BLE001
        return {}


def engine_devices():
    """The device rows, built from the lines mistral.rs prints at load:

        INFO mistralrs_quant::utils::log: Layers 0-38: cuda[0] (48 GB)
        INFO mistralrs_quant::utils::log: Layers 39-39: cpu (252 GB)

    The layer ranges are the engine's own words and go through verbatim. The parenthesised figures do
    not: they are the device's capacity, not the bytes placed on it, and a capacity sent as `bytes`
    would look exactly like an answer. So each row's bytes are the sum of that range's block tensors,
    read out of the GGUF. token_embd, output and the trunk norms are in no range and mistral.rs never
    says which device holds them, so they are left out of every row, which makes the card's VRAM
    figure honestly low rather than plausibly wrong (agreed with the toktape side 2026-09-17: device
    bytes need not sum to the file, and one honest class beats four fabricated ones).

    Returns [] when the log is unavailable or prints no such line, and the caller then falls back to
    the single whole-file row that was here before."""
    if not SERVER_LOG:
        return []
    try:
        text = open(SERVER_LOG, "rb").read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return []
    import re
    rows = re.findall(r"Layers (\d+)-(\d+): (cuda\[(\d+)\]|cpu)", text)
    if not rows:
        return []
    sizes = tensor_bytes(MODEL)
    if not sizes:
        return []
    per_block = {}
    for name, nb in sizes.items():
        m = re.match(r"blk\.(\d+)\.", name)
        if m:
            per_block[int(m.group(1))] = per_block.get(int(m.group(1)), 0) + nb
    devices, seen = [], set()
    for lo, hi, dev, ord_ in rows:
        key = (lo, hi, dev)
        if key in seen:
            continue
        seen.add(key)
        total = sum(per_block.get(n, 0) for n in range(int(lo), int(hi) + 1))
        devices.append({"device": "CPU" if dev == "cpu" else f"GPU{ord_}",
                        "bytes": total, "classes": {"weights": total},
                        "layers": f"{lo}-{hi}"})
    return devices


def props_body():
    size = os.stat(MODEL).st_size
    meta = gguf_meta(MODEL)
    model = {"format": "gguf", "arch": meta.get("arch", ""), "quant": quant_from_name(MODEL), "bytes": size, "files": 1,
             "params": meta.get("params", 0), "n_layers": meta.get("n_layers", 0), "n_experts": meta.get("n_experts", 0),
             "n_experts_used": meta.get("n_experts_used", 0), "ctx_train": meta.get("ctx_train", 0)}
    # Per device when the engine said where the layers went, else the whole file on the one visible
    # device, which is what this reported before and is still right for a launch with no device map.
    devices = engine_devices()
    kv = KV_BYTES
    if devices:
        # Any CPU layer turns PagedAttention off for the whole run ("Device mapping contains a mix of
        # GPU and CPU. There is no CPU support for PagedAttention, disabling PagedAttention.",
        # measured 2026-09-17), so the paged pool this would otherwise report does not exist. 0 reads
        # as unknown on the card rather than as none, which is a schema gap on the recorder side.
        if any(d["device"] == "CPU" for d in devices):
            kv = 0
    else:
        devices = [{"device": "GPU0", "bytes": size, "classes": {"weights": size},
                    "layers": f"0-{meta['n_layers'] - 1}" if meta.get("n_layers") else ""}]
    placement = {"devices": devices, "vram_kv_bytes": kv}
    return {"model_path": MODEL, "chat_template": "", "total_slots": SLOTS,
            "default_generation_settings": {"n_ctx": NCTX},
            "engine": {"name": "mistral.rs", "version": VERSION, "server_pid": upstream_pid(),
                       "args": upstream_argv(), "model": model, "placement": placement}}


META = gguf_meta(MODEL)
PROPS = json.dumps(props_body()).encode()


def render_template(messages, kwargs):
    """POST /apply-template: the prompt as the model sees it. mistral.rs has no such route, but it
    logs that it uses the GGUF's own chat template (measured 2026-09-17), so rendering that template
    here with jinja2 gives the same text; the recorder hashes it and counts it. Raises when jinja2 or
    the template is missing, and the caller answers 501 — the recorder then says "prompt unknown"
    rather than being handed a concatenation that is not the prompt."""
    import jinja2
    tpl = META.get("chat_template") or ""
    if not tpl:
        raise RuntimeError("GGUF has no tokenizer.chat_template")
    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = lambda v, **kw: json.dumps(v, ensure_ascii=False, **kw)
    def raise_exception(msg):
        raise jinja2.TemplateError(msg)
    return env.from_string(tpl).render(messages=messages, add_generation_prompt=True,
                                       raise_exception=raise_exception, **(kwargs or {}))


def upstream_conn():
    return http.client.HTTPConnection(UP.hostname, UP.port, timeout=600)


def timings_final(usage, wall_prompt_ms, wall_pred_ms, pred_n_seen):
    pn = usage.get("prompt_tokens") or 0
    pms = (usage.get("total_prompt_time_sec") or 0.0) * 1000.0
    dn = usage.get("completion_tokens") or pred_n_seen
    dms = (usage.get("total_completion_time_sec") or 0.0) * 1000.0
    src = "server"
    if dms <= 0:  # the engine did not time it: fall back to this shim's clock and say so
        dms, pms, src = wall_pred_ms, wall_prompt_ms, "shim-wall-clock"
    return {"prompt_n": pn, "prompt_ms": pms, "prompt_per_second": (pn / pms * 1000.0) if pms > 0 else 0.0,
            "predicted_n": dn, "predicted_ms": dms, "predicted_per_second": (dn / dms * 1000.0) if dms > 0 else 0.0,
            "cache_n": 0, "timings_source": src}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mrs-shim"

    def log_message(self, *a):  # quiet: the per-request line below is the log
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Server", f"mrs-shim mistral.rs/{VERSION}")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/props":
            return self._json(200, PROPS)
        if p == "/health":
            try:
                c = upstream_conn(); c.request("GET", "/v1/models"); r = c.getresponse(); r.read(); c.close()
                ok = r.status == 200
            except OSError:
                ok = False
            return self._json(200 if ok else 503, {"status": "ok" if ok else "loading"})
        if p == "/slots":
            with inflight_lock:
                n = inflight
            return self._json(200, [{"id": i, "is_processing": i < n, "n_ctx": NCTX, "n_past": 0} for i in range(SLOTS)])
        if p.startswith("/v1/"):
            return self._proxy_plain("GET", None)
        self._json(404, {"error": {"code": 404, "message": "not here", "type": "not_found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if urlparse(self.path).path == "/apply-template":
            try:
                req = json.loads(body or b"{}")
                return self._json(200, {"prompt": render_template(req.get("messages") or [], req.get("chat_template_kwargs"))})
            except Exception as e:  # noqa: BLE001
                log("apply-template failed:", e)
                return self._json(501, {"error": {"code": 501, "message": f"template not rendered: {e}", "type": "not_implemented"}})
        if urlparse(self.path).path == "/v1/chat/completions":
            try:
                stream = bool(json.loads(body or b"{}").get("stream"))
            except ValueError:
                stream = False
            if stream:
                return self._proxy_stream(body)
        self._proxy_plain("POST", body)

    def _proxy_plain(self, method, body):
        c = upstream_conn()
        c.request(method, self.path, body=body, headers={"Content-Type": "application/json"})
        r = c.getresponse(); data = r.read(); c.close()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() in ("content-type",):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy_stream(self, body):
        global inflight
        t0 = time.monotonic(); first = None; last = None; n_pred = 0
        c = upstream_conn()
        c.request("POST", self.path, body=body, headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        r = c.getresponse()
        if r.status != 200:
            data = r.read(); c.close()
            self.send_response(r.status); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            log(f"POST upstream {r.status}: {data[:200]!r}")
            return
        with inflight_lock:
            inflight += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        usage = None; src = "?"
        try:
            for raw in r:
                line = raw.rstrip(b"\r\n")
                if not line.startswith(b"data:"):
                    self.wfile.write(raw); continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush(); break
                try:
                    ev = json.loads(payload)
                except ValueError:
                    self.wfile.write(raw); continue
                now = time.monotonic()
                for ch in ev.get("choices") or []:
                    d = ch.get("delta") or {}
                    if d.get("content") or d.get("reasoning_content"):
                        n_pred += 1
                        if first is None:
                            first = now
                        last = now
                wall_prompt_ms = ((first or now) - t0) * 1000.0
                wall_pred_ms = ((last or now) - first) * 1000.0 if first is not None else 0.0
                if ev.get("usage"):
                    usage = ev["usage"]
                    ev["timings"] = timings_final(usage, wall_prompt_ms, wall_pred_ms, n_pred)
                    src = ev["timings"].pop("timings_source")
                else:
                    ev["timings"] = {"prompt_n": 0, "prompt_ms": wall_prompt_ms,
                                     "prompt_per_second": 0.0, "predicted_n": n_pred, "predicted_ms": wall_pred_ms,
                                     "predicted_per_second": (n_pred / wall_pred_ms * 1000.0) if wall_pred_ms > 0 else 0.0,
                                     "cache_n": 0}
                self.wfile.write(b"data: " + json.dumps(ev, separators=(",", ":")).encode() + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            log("client went away mid-stream")
        finally:
            c.close()
            with inflight_lock:
                inflight -= 1
        wall = ((last - first) * 1000.0) if (first is not None and last is not None) else 0.0
        srv = ((usage or {}).get("total_completion_time_sec") or 0.0) * 1000.0
        log(f"stream done: predicted_n={n_pred} usage.completion_tokens={(usage or {}).get('completion_tokens')} "
            f"server completion {srv:.0f} ms vs shim first-to-last {wall:.0f} ms "
            f"({(wall - srv) / srv * 100:+.1f} %) timings={src}" if srv > 0 else
            f"stream done: predicted_n={n_pred} no server completion time; timings={src}")


if __name__ == "__main__":
    log(f"mrs-shim on 127.0.0.1:{PORT} -> {UP.geturl()} model={MODEL} slots={SLOTS} n_ctx={NCTX} version={VERSION}")
    log("props:", PROPS.decode()[:400])
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
