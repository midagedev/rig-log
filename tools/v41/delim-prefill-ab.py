#!/usr/bin/env python3
"""구분자가 콜드 프리필을 느리게 하는가 — 재빌드 없는 A/B.

ggml-org/llama.cpp#29008(우리 것, 머지됨)에 @NovNovikov 가 남긴 반론을 재는 도구다:
"유저 턴마다 체크포인트를 만드는 방식이 긴 세션의 프리필 속도를 완전히 망친다."
원본 증상은 #25320(2026-07-05, 3배)이고 7월 9일에 min-step 그룹화로 닫혔다.
코멘트는 그 뒤(9/17)에 달렸으므로 남은 질문은 "지금도 그런가"뿐이다.

A/B 를 빌드 두 개로 하지 않는다. 구분자는 파서가 **요청 데이터**에 실어 보내는 것이라
(server-common.cpp: llama_params["message_delimiters"]), 같은 서버·같은 토큰에서

    ON  = /v1/chat/completions  (파서가 구분자를 싣는다)
    OFF = /completion + 토큰 배열 (요청에 구분자 필드가 없다 = 패치 이전 동작)

로 갈린다. 토큰 배열은 /apply-template 의 렌더 결과를 /tokenize(add_special=false)
한 것이라, 두 팔이 같은 토큰을 프리필한다. prompt_n 이 다르면 그 행은 무효다.

측정 행마다 lease.sh 증인을 남긴다.
"""
import json, sys, time, urllib.request, subprocess, argparse, os

def post(port, path, payload, timeout=1800):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def witness(lease):
    try:
        return json.loads(subprocess.run([lease, "witness"], capture_output=True,
                                         text=True, timeout=30).stdout.strip())
    except Exception as e:
        return {"error": str(e)}

# ── 대화 두 모양 ──────────────────────────────────────────────────────────────
# A "agent": 거대한 system + 유저 턴 하나. 우리 PR 이 실제로 잰 모양이다
#            (4200 system + 8950 tool schema + 20 user = 13167).
# B "many":  작은 턴이 아주 많은 긴 세션. NovNovikov 가 가리키는 모양이다
#            (#25320: 284 메시지). 기본 min-step 8192 에서 가드가 몇 번 걸리도록
#            전체 길이를 3만 토큰 급으로 잡는다 — 짧으면 가드가 한 번도 안 걸려
#            A/B 가 아무 말도 하지 않는다.
LOREM = ("The scheduler assigns each routed expert to a core group so that the level-three "
         "cache is not shared across block boundaries, and the weights for one layer are read "
         "exactly once per forward pass regardless of how many tokens are in flight. ")

def para(seed, n):
    out = []
    for i in range(n):
        out.append(f"[{seed}.{i}] " + LOREM * 2)
    return "\n".join(out)

def shape_agent():
    system = "You are a coding agent.\n" + para("sys", 60)
    tools  = "\n\n".join(f"## tool {i}\n" + para(f"tool{i}", 6) for i in range(20))
    return [{"role": "system", "content": system + "\n\n# Tools\n" + tools},
            {"role": "user", "content": "Summarise the placement rules in one sentence."}]

def shape_many(n_turns):
    msgs = [{"role": "system", "content": "You are a helpful assistant.\n" + para("sys", 4)}]
    for i in range(n_turns):
        msgs.append({"role": "user",      "content": f"Question {i}. " + para(f"u{i}", 2)})
        msgs.append({"role": "assistant", "content": f"Answer {i}. "   + para(f"a{i}", 2)})
    msgs.append({"role": "user", "content": "Now summarise everything above."})
    return msgs

# ── 한 행 ────────────────────────────────────────────────────────────────────
def run_arm(port, lease, log_path, shape, arm, msgs, tokens):
    off0 = os.path.getsize(log_path) if log_path and os.path.exists(log_path) else 0
    w0 = witness(lease)
    t0 = time.time()
    if arm == "on":
        r = post(port, "/v1/chat/completions",
                 {"messages": msgs, "max_tokens": 1, "temperature": 0,
                  "cache_prompt": False, "id_slot": 0, "stream": False})
        tm = r["timings"]
    else:
        r = post(port, "/completion",
                 {"prompt": tokens, "n_predict": 1, "temperature": 0,
                  "cache_prompt": False, "id_slot": 0, "stream": False})
        tm = r["timings"]
    wall = time.time() - t0
    w1 = witness(lease)
    chunks = []
    if log_path and os.path.exists(log_path):
        with open(log_path, "rb") as f:
            f.seek(off0)
            for line in f.read().decode("utf-8", "replace").splitlines():
                if "prompt processing, n_tokens" in line:
                    try:
                        chunks.append(int(line.split("n_tokens =")[1].split(",")[0]))
                    except Exception:
                        pass
    # 청크 경계는 누적값으로 찍히므로 차분이 실제 배치 크기다
    sizes = [b - a for a, b in zip([0] + chunks, chunks)] if chunks else []
    return {"shape": shape, "arm": arm,
            "prompt_n": tm.get("prompt_n"), "prompt_ms": round(tm.get("prompt_ms", 0), 1),
            "prompt_per_second": round(tm.get("prompt_per_second", 0), 2),
            "wall_s": round(wall, 2),
            "n_chunks": len(sizes), "min_chunk": min(sizes) if sizes else None,
            "median_chunk": sorted(sizes)[len(sizes)//2] if sizes else None,
            "chunks": sizes,
            "w_start": w0, "w_end": w1}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--lease", default="/home/user/lease.sh")
    ap.add_argument("--log", default="")
    ap.add_argument("--turns", type=int, default=120)
    ap.add_argument("--out", default="/dev/stdout")
    a = ap.parse_args()

    shapes = {"agent": shape_agent(), "many": shape_many(a.turns)}

    # 워밍업 한 번 — 로드 직후 첫 패스는 버린다(NVMe 첫 읽기가 섞이면 팔이 거짓말한다)
    post(a.port, "/completion", {"prompt": "hello", "n_predict": 1, "cache_prompt": False})

    rows = []
    for name, msgs in shapes.items():
        rendered = post(a.port, "/apply-template", {"messages": msgs})["prompt"]
        toks = post(a.port, "/tokenize", {"content": rendered, "add_special": False})["tokens"]
        print(f"# {name}: rendered {len(rendered)} chars -> {len(toks)} tokens", file=sys.stderr)
        for arm in ("on", "off"):
            row = run_arm(a.port, a.lease, a.log, name, arm, msgs, toks)
            rows.append(row)
            print(f"  {name:6} {arm:3}  prompt_n={row['prompt_n']:>7}  "
                  f"{row['prompt_ms']:>9.1f} ms  {row['prompt_per_second']:>7.2f} tok/s  "
                  f"chunks={row['n_chunks']:>3} min={row['min_chunk']}", file=sys.stderr)
    with open(a.out, "w") as f:
        json.dump(rows, f, indent=1)

if __name__ == "__main__":
    main()
