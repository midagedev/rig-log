#!/usr/bin/env python3
"""Answer a question in Korean while showing what the machine is doing to do it.

Runs ON the workstation, next to llama-server, because the numbers that make
this interesting are in /proc and on the local disks: how much of a 347 GB
model is actually resident, and how often a token has to go to the drive for
an engram row.

    v41-demo.py ["질문"] [n_predict]

The right panel is the point. A chat window answering in Korean looks like
every other chat window; the thing worth showing is that 84.6 GB of the model
never enters memory and it answers anyway.
"""
import json, os, sys, time, unicodedata, urllib.request
from collections import deque

URL      = os.environ.get("RIG_URL", "http://127.0.0.1:8001")
QUESTION = sys.argv[1] if len(sys.argv) > 1 else \
    "MoE 모델을 GPU 두 장과 시스템 RAM, NVMe에 나눠 올려 추론할 때 "\
    "토큰 생성 속도를 좌우하는 핵심 요인 세 가지를 각각 두세 문장으로 설명해줘."
NPRED    = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.environ.get("RIG_N", 2000))

W      = int(os.environ.get("COLUMNS", 132))
RIGHT  = 30
LEFT   = W - RIGHT - 3
ROWS   = int(os.environ.get("ROWS", 28))

C = dict(dim="\033[38;5;245m", txt="\033[38;5;252m", accent="\033[38;5;80m",
         hi="\033[38;5;229m", good="\033[38;5;114m", warn="\033[38;5;209m",
         rule="\033[38;5;238m", off="\033[0m", bold="\033[1m")


import re
ANSI = re.compile(r"\033\[[0-9;]*m")


def cw(s):
    """Printable width: CJK counts as two columns, ANSI colour as none.

    Forgetting the second half shifted every coloured line fifteen columns
    left and pushed the right panel's labels into the answer pane.
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in ANSI.sub("", s))


def pad(s, n):
    d = n - cw(s)
    return s + " " * d if d > 0 else s


def wrap(text, n):
    """Wrap on width, not character count, and break inside CJK runs."""
    lines, cur = [], ""
    for word in text.replace("\n", " \n ").split(" "):
        if word == "\n":
            lines.append(cur); cur = ""; continue
        for piece in ([word] if cw(word) <= n else
                      [word[i:i+n//2] for i in range(0, len(word), n//2)]):
            if cur and cw(cur) + 1 + cw(piece) > n:
                lines.append(cur); cur = piece
            else:
                cur = piece if not cur else cur + " " + piece
    if cur:
        lines.append(cur)
    return lines


def server_pid():
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if b"llama-server" in open(f"/proc/{d}/cmdline", "rb").read():
                return int(d)
        except OSError:
            pass
    return None


PID = server_pid()


def rss_gb():
    if not PID:
        return 0.0
    for line in open(f"/proc/{PID}/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1e6
    return 0.0


def majflt():
    if not PID:
        return 0
    return int(open(f"/proc/{PID}/stat").read().split()[11])


def model_gb():
    """Total size of the whole shard set, following symlinks off the model drive."""
    if not PID:
        return 0.0
    argv = open(f"/proc/{PID}/cmdline", "rb").read().decode().split("\0")
    try:
        m = argv[argv.index("-m") + 1]
    except ValueError:
        return 0.0
    import glob
    base = m.rsplit("-", 3)[0]
    return sum(os.path.getsize(f) for f in glob.glob(base + "-*.gguf")) / 1e9


TOTAL = model_gb()
# The two engram tensors, blk.1 and blk.14, [256, 384006168] at Q3_K. Measured
# from the tensor headers, not inferred from resident-set arithmetic: RSS is
# also short by whatever was copied to VRAM and then dropped from page cache,
# so total-minus-RSS overstates this by about 50 GB.
ENGRAM = 84.6


def vram_gb():
    try:
        import subprocess
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        return sum(int(x) for x in out.split() if x.isdigit()) * 1.048576 / 1000
    except Exception:
        return 0.0
SPARK = "▁▂▃▄▅▆▇█"


def spark(vals, n=12):
    v = list(vals)[-n:]
    if not v:
        return ""
    hi = max(v) or 1
    return "".join(SPARK[min(7, int(x / hi * 7))] for x in v)


def frame(body, tps, faults_hist, done):
    rss = rss_gb()
    off = TOTAL - rss
    out = ["\033[H\033[J"]
    r, t, a, d, g, h = C["rule"], C["txt"], C["accent"], C["dim"], C["good"], C["hi"]
    o = C["off"]

    out.append(f"{r}┌─{o} {a}DeepSeek-V4.1-Flash{o} {r}" + "─" * (LEFT - 20) +
               f"┬─{o} {a}this machine{o} {r}" + "─" * (RIGHT - 16) + f"┐{o}")

    vram = vram_gb()
    right = [
        f"{d}model file{o}     {t}{TOTAL:6.1f} GB{o}",
        f"{d}mapped in RAM{o}  {t}{rss:6.1f} GB{o}",
        f"{d}in VRAM{o}        {t}{vram:6.1f} GB{o}",
        "",
        f"{h}never loaded{o}   {g}{ENGRAM:6.1f} GB{o}",
        f"{d}engram, read a few{o}",
        f"{d}rows at a time off{o}",
        f"{d}the NVMe{o}",
        "",
        f"{d}engram reads{o}   {h}{spark(faults_hist)}{o}",
        f"{d}decode{o}        {g}{tps:6.1f} tok/s{o}" if tps else f"{d}decode{o}            {d}—{o}",
    ]
    rawr = ["model file     %6.1f GB" % TOTAL,
            "mapped in RAM  %6.1f GB" % rss,
            "in VRAM        %6.1f GB" % vram,
            "",
            "never loaded   %6.1f GB" % ENGRAM,
            "engram, read a few",
            "rows at a time off",
            "the NVMe",
            "",
            "engram reads   " + spark(faults_hist),
            ("decode        %6.1f tok/s" % tps) if tps else "decode            —"]

    for i in range(ROWS):
        l = body[i] if i < len(body) else ""
        rr = right[i] if i < len(right) else ""
        rrw = rawr[i] if i < len(rawr) else ""
        out.append(f"{r}│{o} " + pad(l, LEFT) + f" {r}│{o} " +
                   rr + " " * max(0, RIGHT - 2 - cw(rrw)) + f"{r}│{o}")

    out.append(f"{r}└" + "─" * (LEFT + 2) + "┴" + "─" * (RIGHT - 1) + f"┘{o}")
    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()


def main():
    q = wrap("❯ " + QUESTION, LEFT)
    body = [C["hi"] + l + C["off"] for l in q] + [""]
    faults, f0, t0 = deque(maxlen=12), majflt(), time.time()
    frame(body, 0, faults, False)

    # /v1/chat/completions, not /completion: the raw endpoint skips the chat
    # template and an instruct model handed a bare question answers it with
    # "1. 1. 1. 1." forever.
    req = urllib.request.Request(
        URL + "/v1/chat/completions",
        # reasoning_effort "none". Set RIG_THINK=1 to show the thinking instead:
        # compose() renders it dimmed above the answer and it is worth watching,
        # but it is not short. Measured on this model, the same question thinks
        # for 3,500-4,700 characters before writing anything at every effort
        # level -- 'low' and 'medium' barely move it, because this template only
        # special-cases 'max'. A recording that fits in a tweet never reaches
        # the answer.
        #
        # Do NOT substitute chat_template_kwargs {"thinking": false}: it leaks a
        # stray "</think>" into content, because the template appends that tag
        # to the prompt and the parser does not strip it back out.
        data=json.dumps({"messages": [{"role": "user", "content": QUESTION}],
                         "max_tokens": NPRED, "temperature": 0.3, "top_p": 0.9,
                         **({} if os.environ.get("RIG_THINK") else
                            {"reasoning_effort": "none"}),
                         "stream": True}).encode(),
        headers={"Content-Type": "application/json"})

    def compose(reasoning, answer):
        out = [C["hi"] + l + C["off"] for l in q] + [""]
        if reasoning:
            out.append(C["dim"] + "추론 " + "·" * (LEFT - 5) + C["off"])
            out += [C["dim"] + l + C["off"] for l in wrap(reasoning, LEFT - 2)]
            out.append("")
        if answer:
            out.append(C["accent"] + "답변 " + "─" * (LEFT - 5) + C["off"])
            out += wrap(answer, LEFT)
        return out

    # Rate is measured over the content window only: tokens that carried text,
    # between the first and the last of them. Three things got this wrong at
    # first and each one dragged the figure down -- counting the empty role
    # chunk and the finish chunk as tokens, dividing by wall time that kept
    # running after generation stopped, and a render throttle whose `continue`
    # jumped over the finish_reason check so the loop never broke. The recording
    # that came out of it read 4.5 tok/s for a model doing 18.
    reasoning, answer, ntok = "", "", 0
    start = stop = None
    last = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            if not raw.startswith(b"data: "):
                continue
            try:
                ev = json.loads(raw[6:])
            except ValueError:
                continue
            ch = (ev.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            rc = delta.get("reasoning_content") or ""
            ct = delta.get("content") or ""
            reasoning += rc
            answer += ct
            if rc or ct:
                ntok += 1
                now = time.time()
                if start is None:
                    start = now
                stop = now

            done = bool(ch.get("finish_reason"))
            now = time.time()
            if not done and now - last < 0.12:
                continue
            last = now
            if now - t0 >= 0.5:
                f1 = majflt(); faults.append(f1 - f0); f0, t0 = f1, now
            tps = ntok / (stop - start) if start and stop and stop > start else 0
            lines = compose(reasoning, answer)
            frame(lines[-ROWS:] if len(lines) > ROWS else lines, tps, faults, done)
            if done:
                break


main()
