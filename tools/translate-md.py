#!/usr/bin/env python3
"""translate-md.py — one markdown file, one request, one measured pair of numbers.

The point of this script is not the translation. It is that a translation round on
this machine produces the same kind of row every other measurement here does: the
exact model, the exact prompt, prefill and decode rates read out of the server's own
accounting, and the **output-to-input token ratio**, which is what projects a
1 700-word pilot onto a 134 000-word repo. A rate alone does not.

    translate-md.py --in docs/quiet-machine.md --out /tmp/quiet-machine.ko.md \
        --url http://127.0.0.1:8001/v1/chat/completions --timings /tmp/t.json

Two assertions are built in because this repo has paid for both:

- **The answer is read, not the request.** `--no-think` and its template kwarg are a
  request llama-server ignores unless it was started with `--jinja` (measured
  2026-09-17, two hero takes published with `<think>` in every stream). So a reply
  that opens a reasoning block fails here rather than being trusted.
- **A model that wraps the whole document in a fence has not preserved the document.**
  It is stripped so the gate can see the content, and the stripping is recorded as a
  finding rather than hidden.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

# The glossary is the part of this file that outlives the pilot. Forty-five more
# documents inherit whatever is decided here, and a term that drifts between files
# is a defect the preservation gate cannot see.
SYSTEM = """\
너는 기술 문서 번역가다. 아래 영어 마크다운 문서를 한국어로 번역한다.

규칙:
1. 마크다운 구조를 글자 그대로 보존한다. 제목 레벨, 목록 기호, 표의 행과 열,
   빈 줄, 굵게/기울임 표시, 취소선(~~...~~)을 원문과 같은 개수·같은 순서로 둔다.
2. 코드 펜스(``` 사이) 안은 **한 글자도 바꾸지 않는다.** 주석도 영어 그대로 둔다.
3. 백틱 인라인 코드, 파일 경로, 명령어, 플래그, 환경변수, 식별자, URL,
   링크 대상([텍스트](대상)의 대상)은 원문 그대로 둔다. 링크의 텍스트만 번역한다.
4. 숫자와 단위는 바꾸지 않는다. 129 tok/s, 24 GB, 0.20 ms, 2026-09-13 그대로.
   숫자를 한글로 풀어쓰지 않는다.
5. 문단을 합치거나 나누지 않는다. 요약하지 않는다. 설명을 덧붙이지 않는다.
   원문 한 문단은 번역문 한 문단이다.
6. 문체는 평서체 '-다'로 끝나는 기술 문서체다. 존댓말을 쓰지 않는다.

용어(이 레포 전체에서 고정한다):

| 영어 | 한국어 |
|---|---|
| lease | 임대 |
| witness | 증인 |
| gate | 게이트 |
| quiet machine | 조용한 머신 |
| load average | load average (그대로) |
| prefill / decode | prefill / decode (그대로) |
| throughput, rate | 속도 |
| struck / strike | 취소선을 긋다 |
| entry (log entry) | 엔트리 |
| measured | 실측 |
| claim | 주장 |
| upstream | 업스트림 |
| card (GPU) | 카드 |
| board | 보드 |
| slot | 슬롯 |
| run (a measurement run) | 런 |
| harness | 하네스 |
| delegate (a subagent) | 위임 에이전트 |

출력은 번역된 마크다운 본문만 낸다. 앞뒤에 설명이나 코드 펜스를 두르지 않는다.
"""


MARK = "\u27e6CODE%d\u27e7"


def split_sections(text, max_words):
    """Cut at `## ` headings, never inside a fenced block, and only when it is needed.

    Each piece is translated on its own, so the model never sees the whole argument at once.
    That is a real cost: a term it settles in part two cannot inform part one, and the
    glossary check is the only thing left holding them together. Whole-document is the
    default for exactly this reason.
    """
    if not max_words or len(text.split()) <= max_words:
        return [text]
    lines, out, cur, fence = text.split("\n"), [], [], None
    for line in lines:
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            fence = None if fence else m.group(1)
        if (fence is None and re.match(r"^## ", line) and cur
                and len("\n".join(cur).split()) >= max_words // 2):
            out.append("\n".join(cur).rstrip())
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(cur).rstrip())
    out = out or [text]

    # A heading split is not always enough: README's `## Log` is one 7 000-word index table
    # under a single heading. An oversized part is cut again at a blank line or a table-row
    # boundary — never inside a fence, and never mid-row, so a row is always whole.
    final = []
    for part in out:
        if len(part.split()) <= max_words:
            final.append(part)
            continue
        buf, words, fence = [], 0, None
        for line in part.split("\n"):
            m = re.match(r"^\s*(`{3,}|~{3,})", line)
            if m:
                fence = None if fence else m.group(1)
            buf.append(line)
            words += len(line.split())
            can_cut = fence is None and (not line.strip() or line.strip().startswith("|"))
            if words >= max_words and can_cut:
                final.append("\n".join(buf).rstrip())
                buf, words = [], 0
        if buf:
            final.append("\n".join(buf).rstrip())
    return [f for f in final if f.strip()]


def mask_fences(text):
    """Replace every fenced block with one marker line and keep the blocks.

    The marker has to be something the model will copy through untouched and will not
    translate: a bracketed ASCII word inside mathematical brackets does both, and it
    cannot collide with markdown.
    """
    out, held, i = [], [], 0
    lines = text.split("\n")
    while i < len(lines):
        m = re.match(r"^(\s*)(`{3,}|~{3,})(.*)$", lines[i])
        if m:
            indent, mark = m.group(1), m.group(2)
            block, i = [lines[i]], i + 1
            while i < len(lines) and not re.match(rf"^\s*{mark[0]}{{{len(mark)},}}\s*$", lines[i]):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
                i += 1
            held.append("\n".join(block))
            out.append(indent + MARK % len(held))
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), held


def restore_fences(text, held):
    missing = 0
    for n, block in enumerate(held, 1):
        marker = MARK % n
        if marker not in text:
            missing += 1
            continue
        text = text.replace(marker, block, 1)
    return text, missing


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="dst", required=True)
    p.add_argument("--url", default="http://127.0.0.1:8001/v1/chat/completions")
    p.add_argument("--model", default="local")
    p.add_argument("--timings", help="write the measured row here as JSON")
    p.add_argument("--max-tokens", type=int, default=16384)
    p.add_argument("--temp", type=float, default=0.0)
    p.add_argument("--prompt-file", help="override the built-in system prompt")
    p.add_argument("--timeout", type=float, default=3600.0)
    p.add_argument("--max-chunk-words", type=int, default=0, metavar="N",
                   help="split a document larger than N words at its top-level headings and send "
                        "each part as its own request, then join them back. README.md is 10 365 "
                        "words, about 19 000 prompt tokens, and asking for it whole would need a "
                        "context the placement does not have. 0 (the default) always sends the "
                        "whole document, which is what every row in log/2026-09-18-c was measured "
                        "with — a chunked run is a different measurement and the timings say so")
    p.add_argument("--dump-request", metavar="DIR",
                   help="write the exact system and user text this would send, and exit without "
                        "calling anything. A model reached some other way -- a hosted one, a "
                        "different client -- can then be given byte-identical input, which is the "
                        "only way its row belongs in the same table")
    p.add_argument("--prompt-in-user", action="store_true",
                   help="send the instruction as the first half of the user turn rather than as "
                        "a system message. Some models weight the two very differently: measured "
                        "2026-09-18, K-EXAONE-236B ignored a system instruction to translate and "
                        "rewrote the document instead, where five other models obeyed the same text")
    p.add_argument("--stream", action="store_true",
                   help="read the answer as it arrives and time it here, rather than trusting the "
                        "server's own accounting. Necessary for any server that does not report "
                        "llama.cpp's `timings` block -- TabbyAPI does not -- and useful even where "
                        "it does, because running both on one request says whether the two agree")
    p.add_argument("--extra-json", metavar="JSON",
                   help="merged into the request body. For a server whose thinking is a template "
                        "variable rather than a flag, e.g. "
                        "'{\"template_vars\": {\"enable_thinking\": false}}'")
    p.add_argument("--raw-chatml", action="store_true",
                   help="build a ChatML prompt here and post it to /completions, instead of "
                        "sending messages to /v1/chat/completions. Measured 2026-09-18: "
                        "llama-server answers every chat completion from Qwen3-Coder-Next with "
                        "HTTP 500, \"the model produced output that does not match the expected "
                        "peg-native format\" -- the model writes a perfectly good answer and the "
                        "server throws it away parsing it against that model's tool-call grammar. "
                        "Neither --reasoning-format none nor --chat-template chatml takes the "
                        "parser out of the path. This does, at the cost of the prompt being "
                        "built here rather than by the template in the GGUF: say so in the row")
    p.add_argument("--mask-fences", action="store_true",
                   help="hold the fenced blocks back and put them in afterwards, instead of "
                        "asking the model to leave them alone. Measured 2026-09-18: asked "
                        "politely and in its own language, Qwen3.6-35B-A3B translated the "
                        "comments inside the one fence in docs/quiet-machine.md anyway. A rule "
                        "the model can disobey is not a rule, and the block it never sees is "
                        "one it cannot change -- so this is the structural form of the same "
                        "requirement, and it is cheaper in tokens as well. **The fence check "
                        "in check-translation.py then passes by construction**, which is not "
                        "evidence about the model: say which mode a row was taken in")
    p.add_argument("--save-stream", metavar="FILE",
                   help="write every SSE line the server sent, byte for byte, here. A streamed "
                        "row is otherwise unfalsifiable after the fact: measured 2026-09-18, "
                        "GLM-5.3 through exl3-serve returned 18 U+FFFD in 6356 characters "
                        "(`\uc5c5\ufffd\ufffd\ufffd\uc774\ud2b8` for \uc5c5\ub370\uc774\ud2b8 -- one 3-byte syllable arriving as three "
                        "separate broken deltas), and with the stream gone there was no way to "
                        "tell a server that splits a codepoint across deltas from a client that "
                        "reassembles them wrongly. Keep the file next to the row")
    a = p.parse_args()

    system = open(a.prompt_file, encoding="utf-8").read() if a.prompt_file else SYSTEM
    source = open(a.src, encoding="utf-8").read()

    if a.max_chunk_words and len(split_sections(source, a.max_chunk_words)) > 1:
        sys.exit(f"{a.src} is larger than --max-chunk-words; this tool always sends one request. "
                 f"Use tools/translate-batch.py, which imports the same splitter and the same "
                 f"prompt but posts each part — a chunked run is a different measurement and "
                 f"belongs to a different tool.")
    sent, held = mask_fences(source) if a.mask_fences else (source, [])

    if a.dump_request:
        os.makedirs(a.dump_request, exist_ok=True)
        open(os.path.join(a.dump_request, "system.txt"), "w", encoding="utf-8").write(system)
        open(os.path.join(a.dump_request, "user.txt"), "w", encoding="utf-8").write(sent)
        json.dump({"held_blocks": held, "mask_fences": a.mask_fences},
                  open(os.path.join(a.dump_request, "held.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"{a.dump_request}: system.txt, user.txt, held.json ({len(held)} block(s) held)")
        return

    if a.raw_chatml:
        url = a.url.replace("/v1/chat/completions", "/completions")
        body = {"prompt": (f"<|im_start|>system\n{system}<|im_end|>\n"
                           f"<|im_start|>user\n{sent}<|im_end|>\n"
                           f"<|im_start|>assistant\n"),
                "temperature": a.temp, "n_predict": a.max_tokens, "stream": False,
                "cache_prompt": False, "stop": ["<|im_end|>"]}
    else:
        url = a.url
        msgs = ([{"role": "user", "content": system + "\n\n---\n\n" + sent}]
                if a.prompt_in_user else
                [{"role": "system", "content": system}, {"role": "user", "content": sent}])
        body = {"model": a.model, "messages": msgs,
                "temperature": a.temp, "max_tokens": a.max_tokens, "stream": False}
    if a.extra_json:
        body.update(json.loads(a.extra_json))
    if a.stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})

    stream_timing = None
    if a.stream:
        pieces, usage, t_first, n_deltas = [], None, None, 0
        # A reasoning delta is a token the server spent and this client used to throw away.
        # Measured 2026-09-18: GLM-5.3 reported 4096 completion tokens against 3398 content
        # deltas, and with reasoning_content dropped there was no way to say whether the
        # missing ~700 were thinking, MTP tokens batched into one delta, or a miscount. A row
        # whose out-in ratio counts tokens the file does not contain is not a measurement, so
        # count them here and put the count in the row rather than inferring it later.
        reasoning, n_reasoning, fin = [], 0, None
        sink = open(a.save_stream, "wb") if a.save_stream else None
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=a.timeout) as r:
            for raw in r:
                if sink:
                    sink.write(raw)
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if ev.get("usage"):
                    usage = ev["usage"]
                for ch in ev.get("choices") or []:
                    if ch.get("finish_reason"):
                        fin = ch["finish_reason"]
                    d = ch.get("delta") or {}
                    think = d.get("reasoning_content") or d.get("reasoning") or ""
                    if think:
                        reasoning.append(think)
                        n_reasoning += 1
                    piece = d.get("content") or ch.get("text") or ""
                    if piece:
                        if t_first is None:
                            t_first = time.time()
                        pieces.append(piece)
                        n_deltas += 1
        if sink:
            sink.close()
        wall = time.time() - t0
        ttft = (t_first - t0) if t_first else wall
        payload = {"content": "".join(pieces), "usage": usage or {}}
        # The split the server would have reported: everything up to the first token is the
        # prefill, everything after it is the decode. One token has already been produced when
        # the clock starts, hence n-1.
        # TabbyAPI reported completion_tokens exactly equal to prompt_tokens on a reply that
        # carried 8 270 content deltas (measured 2026-09-18), which is not a completion count,
        # it is the prompt count echoed back. A usage figure that equals the prompt or is
        # missing is not used; the deltas this client counted itself are.
        u_out = (usage or {}).get("completion_tokens")
        n_in0 = (usage or {}).get("prompt_tokens")
        trust = bool(u_out) and u_out != n_in0
        n_out = u_out if trust else n_deltas
        n_in = (usage or {}).get("prompt_tokens")
        stream_timing = {
            "ttft_s": round(ttft, 3),
            "client_prefill_tok_s": round(n_in / ttft, 1) if n_in and ttft else None,
            "client_decode_tok_s": round((n_out - 1) / (wall - ttft), 1) if n_out > 1 and wall > ttft else None,
            "content_deltas": n_deltas,
            "usage_completion_tokens": u_out,
            "token_count_from": "server usage" if trust else "content deltas counted here",
            "reasoning_deltas": n_reasoning,
            "reasoning_chars": sum(len(x) for x in reasoning),
        }
    else:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=a.timeout) as r:
            payload = json.load(r)
        wall = time.time() - t0

    findings = []
    if a.stream:
        text = payload["content"]
        # This used to read `{"finish_reason": "stop"}`, flat, invented here and never read off
        # the wire -- so every streamed row in this ladder says "stop" whatever the server said,
        # including the GLM row that was clamped in the middle of a table. A field the client
        # fills in itself is not an observation. Corrected 2026-09-18; rows taken before that
        # date have a finish_reason that means nothing.
        choice = {"finish_reason": fin}
    elif a.raw_chatml:
        text = payload["content"]
        # Only `stopped_limit` means the answer was cut. Measured 2026-09-18: keying on
        # stopped_eos/stopped_word instead labelled a complete Coder-Next translation
        # "length" -- this build reports the stop another way, and an instrument that
        # calls a finished answer truncated is worse than one that says nothing.
        choice = {"finish_reason": "length" if payload.get("stopped_limit") else "stop",
                  "stop_fields": {k: payload.get(k) for k in
                                  ("stopped_eos", "stopped_word", "stopped_limit", "stop_type")}}
    else:
        choice = payload["choices"][0]
        text = choice["message"]["content"]

    if choice.get("finish_reason") not in (None, "stop"):
        findings.append(f"finish_reason={choice.get('finish_reason')} — the answer is cut")

    # Read the answer, not the request. A reply that opens a reasoning block has not obeyed
    # the request to turn thinking off -- but a closed block with an answer after it is still
    # an answer, and throwing it away would report "no translation" for a model that produced
    # one. So a *closed* block is taken off and counted; an unclosed one is still a failure,
    # because then there is no answer to keep.
    m_think = re.match(r"\s*<think(?:ing)?>(.*?)</think(?:ing)?>\s*", text, re.S)
    if m_think:
        findings.append(f"the reply opened a reasoning block despite the request; "
                        f"{len(m_think.group(1))} characters of it were removed, and the tokens "
                        f"it cost are still in this row's time")
        text = text[m_think.end():]
    elif re.match(r"\s*<think", text):
        sys.exit("FAIL: the reply opens a reasoning block that never closes; there is no answer in it")

    # A whole-document fence means the structure was not preserved; strip it so the
    # gate can read the content, and say so.
    m = re.match(r"\s*```[a-zA-Z]*\n(.*)\n```\s*\Z", text, re.S)
    if m:
        findings.append("the whole document came back wrapped in a code fence; stripped")
        text = m.group(1)

    if a.mask_fences:
        text, missing = restore_fences(text, held)
        if missing:
            findings.append(f"{missing} of {len(held)} held code block(s) had no place to go back to")

    if not text.endswith("\n"):
        text += "\n"
    open(a.dst, "w", encoding="utf-8").write(text)

    t = payload.get("timings") or {}
    if a.stream:
        u = payload.get("usage") or {}
        t = {"prompt_n": u.get("prompt_tokens"),
             "predicted_n": (stream_timing or {}).get("content_deltas")
             if stream_timing and stream_timing["token_count_from"] != "server usage"
             else u.get("completion_tokens")}
        if stream_timing:
            t["prompt_ms"] = stream_timing["ttft_s"] * 1000 if stream_timing["ttft_s"] else None
            t["predicted_ms"] = (wall - stream_timing["ttft_s"]) * 1000
    pn, pms = t.get("prompt_n"), t.get("prompt_ms")
    dn, dms = t.get("predicted_n"), t.get("predicted_ms")
    row = {
        "source": a.src, "output": a.dst, "model": a.model,
        "raw_chatml": a.raw_chatml,
        "source_words": len(source.split()),
        "fences_masked": a.mask_fences,
        "prompt_in_user": a.prompt_in_user,
        "prompt_tokens": pn, "predicted_tokens": dn,
        "prefill_tok_s": round(pn / (pms / 1000), 1) if pn and pms else None,
        "decode_tok_s": round(dn / (dms / 1000), 1) if dn and dms else None,
        # The ratio, not the rate, is what projects onto the rest of the repo.
        "out_in_ratio": round(dn / pn, 3) if pn and dn else None,
        "wall_s": round(wall, 2),
        "finish_reason": choice.get("finish_reason"),
        "streamed": a.stream,
        "stream_timing": stream_timing,
        "stop_fields": choice.get("stop_fields"),
        "findings": findings,
    }
    if a.timings:
        open(a.timings, "w", encoding="utf-8").write(json.dumps(row, indent=2) + "\n")
    print(json.dumps(row, ensure_ascii=False, indent=2))
    for f in findings:
        print("finding:", f, file=sys.stderr)


if __name__ == "__main__":
    main()
