#!/usr/bin/env python3
"""V4.1 에서 갈라지는 프리픽스가 이전 요청의 답을 내는가 — ik PR #2455 의 재현자.

배경: #2455 의 `llama_data_write` 는 V4.1(`hparams.dsv4_shared_streams`)에서 압축 스트림
상태를 저장하지 않고 layer_type=0 만 쓴다. 서버는 dsv4 에 대해 체크포인트를 기본으로 켜고
(server-context.cpp:1820, `llama_model_is_deepseek4`), 프리픽스가 중간에서 갈라지면
apply_checkpoint 가 체크포인트를 복원한다. raw 창은 돌아오지만 압축 상태는 앞 요청 것이
남는다. @rrusinov 가 #2438 에서 "모델이 예전 프롬프트에 답한다"고 보고한 것이 이것이다.

설계: 같은 대화를 두 번 보내되 **뒤쪽 한 군데**만 바꾼다.
  A  ... 금고 코드는 ALPHA-7 ... → "코드만 답해"   → ALPHA-7 이어야 한다
  B  ... 금고 코드는 BRAVO-3 ... → 같은 질문       → BRAVO-3 이어야 한다
  C  B 와 완전히 같은 요청을 cache_prompt=false 로 → BRAVO-3 (통제군: 모델은 읽을 수 있다)
B 가 ALPHA-7 을 내고 C 가 BRAVO-3 을 내면 캐시 경로의 결함이다. 둘 다 BRAVO-3 이면
이 배치에서는 재현되지 않는다 — 그대로 적는다.
"""
import json, sys, time, urllib.request, argparse

def post(port, path, payload, timeout=1800):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

FILL = ("The placement rules for this deployment are recorded in the operations manual. "
        "Routed experts are assigned to core groups so that a level-three cache is not "
        "shared across block boundaries. ")

def turn(i, n=3):
    return f"Section {i}. " + FILL * n

def convo(code, n_before=28, n_after=6):
    m = [{"role": "system", "content": "You are a terse operations assistant.\n" + FILL * 6}]
    for i in range(n_before):
        m.append({"role": "user",      "content": f"Question {i}: summarise section {i}. " + turn(i)})
        m.append({"role": "assistant", "content": f"Section {i} summary. " + turn(i)})
    # 갈라지는 지점 — 이 한 메시지만 팔마다 다르다
    m.append({"role": "user",      "content": f"Record this and acknowledge: the vault code is {code}."})
    m.append({"role": "assistant", "content": f"Recorded. The vault code is {code}."})
    for i in range(n_after):
        j = 100 + i
        m.append({"role": "user",      "content": f"Question {j}: summarise section {j}. " + turn(j)})
        m.append({"role": "assistant", "content": f"Section {j} summary. " + turn(j)})
    m.append({"role": "user", "content": "Reply with the vault code and nothing else."})
    return m

def ask(port, msgs, cache):
    t0 = time.time()
    r = post(port, "/v1/chat/completions",
             {"messages": msgs, "max_tokens": 96, "temperature": 0,
              "cache_prompt": cache, "stream": False,
              "chat_template_kwargs": {"thinking": False}})
    tm = r.get("timings", {})
    m = r["choices"][0]["message"]
    # V4.1 은 thinking 모드에서 본문을 reasoning 쪽에 넣을 수 있다. 둘 다 본다.
    text = (m.get("content") or "") + " " + (m.get("reasoning_content") or "")
    return {"text": text.strip(),
            "prompt_n": tm.get("prompt_n"), "cache_n": tm.get("cache_n"),
            "prompt_ms": round(tm.get("prompt_ms", 0), 1), "wall_s": round(time.time()-t0, 2)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8021)
    ap.add_argument("--out", default="/dev/stdout")
    a = ap.parse_args()

    A, B = convo("ALPHA-7"), convo("BRAVO-3")
    same = sum(1 for x, y in zip(A, B) if x == y)
    print(f"# {len(A)} messages, {len(A)-same} differ (the vault-code turn and its reply)", file=sys.stderr)

    rows = []
    for name, msgs, cache, want in (("A alpha, cached",      A, True,  "ALPHA-7"),
                                    ("B bravo, cached",      B, True,  "BRAVO-3"),
                                    ("C bravo, cache off",   B, False, "BRAVO-3"),
                                    ("D alpha again, cached",A, True,  "ALPHA-7")):
        r = ask(a.port, msgs, cache)
        r.update(arm=name, want=want, ok=(want in r["text"]))
        rows.append(r)
        print(f"  {name:22} want={want:8} got={r['text'][:40]!r:45} "
              f"prompt_n={r['prompt_n']} cache_n={r['cache_n']} {'OK' if r['ok'] else '<<< MISMATCH'}",
              file=sys.stderr)
    with open(a.out, "w") as f:
        json.dump(rows, f, indent=1)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n# {len(bad)} of {len(rows)} arms answered with the wrong code", file=sys.stderr)

if __name__ == "__main__":
    main()
