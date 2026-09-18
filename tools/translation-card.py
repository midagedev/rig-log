#!/usr/bin/env python3
"""translation-card.py — the translation ladder as two shareable pages.

Two numbers per model and they pull against each other: how long it takes to translate a
page, and how often it changes what the source said. One card held the table, the chart,
the examples and the caveats, and at the width a timeline gives it nothing was legible.
So it is two: **the result**, and **what a script cannot see**. Each stands alone -- the
hardware and the date are on both -- because the second one gets read first as often as not.

    translation-card.py scores.json --out-dir assets --lang ko --stem translation-ladder-2026-09-18

Reads the file the rows are collected into, so a new rung is a new object in that file and
nothing here changes. Render each page at 1200x1500 and screenshot at 2x.
"""

import argparse
import json
import os

STR = {
  "en": {
    "h1a": "{n} local models translate the same page.",
    "h1b": "The fastest is {mult:.0f}× wronger. The most accurate takes {slower:.0f}× longer.",
    "h2a": "What no script can see",
    "h2b": "Every Korean line below reads perfectly.",
    "sub": ("One 1 711-word engineering document, English&nbsp;→&nbsp;Korean, sent whole at "
            "<code>temperature 0</code>. One workstation: RTX A6000 48&nbsp;GB + RTX 3090 "
            "24&nbsp;GB, 251&nbsp;GB RAM, 64 threads. Measured 2026-09-18."),
    "asof": "This page × 78 is the whole repo, 134k words — a multiplication, not a measurement.",
    "t_rungs": "every rung", "t_plot": "speed against accuracy · circle area is file size",
    "c_model": "model", "c_page": "this<br>page", "c_repo": "whole repo<br>134k words",
    "c_tps": "tok/s", "c_struct": "structure", "c_gloss": "glossary",
    "c_mean": "meaning<br>changed /1k",
    "clean": "clean", "fail": "{n} FAIL", "worse": "▲ worse", "better": "▼ better",
    "found": "{n} found", "h3a": "Speed against accuracy.",
    "h3b": "Circle area is the file on disk.",
    "xaxis": "decode tok/s  →  faster", "yaxis": "meaning changed / 1k words",
    "hosted": "{name} — hosted, no rate on this machine",
    "notmachine": "not this machine", "cards": "both cards", "card3090": "3090",
    "carda6000": "A6000",
    "foot": ("<b>Structure</b> is a script: numbers, links, inline code, code fences, table shape "
             "and block count must survive byte-identical; it fails on six deliberate manglings "
             "before it is trusted. <b>Glossary</b> is a script too — the share of agreed terms "
             "that came out in the agreed Korean word. <b>Meaning changed</b> cannot be a script, "
             "so every version was read interleaved, one source paragraph at a time, with the "
             "model names hidden: one reader, one document per model, ±2, so models within 2 of "
             "each other are tied. Rates are the server's own accounting, not a toktape card, and "
             "fenced code blocks are held back from the request rather than protected by an "
             "instruction."),
  },
  "ko": {
    "h1a": "로컬 모델 {n}개가 같은 문서를 번역했다.",
    "h1b": "가장 빠른 쪽이 {mult:.0f}배 더 틀리고, 가장 정확한 쪽이 {slower:.0f}배 더 걸린다.",
    "h2a": "스크립트로는 볼 수 없는 것",
    "h2b": "아래 한국어는 전부 자연스럽게 읽힌다.",
    "sub": ("영어 기술 문서 1,711단어를 통째로 <code>temperature 0</code>으로 한 번에. "
            "워크스테이션 한 대 — RTX A6000 48&nbsp;GB + RTX 3090 24&nbsp;GB, RAM 251&nbsp;GB, "
            "64스레드. 2026-09-18 실측."),
    "asof": "이 문서 한 장 × 78이 레포 전체 13.4만 단어다 — 곱셈이고, 따로 잰 값이 아니다.",
    "t_rungs": "전체 결과", "t_plot": "속도 대 정확도 · 원 크기는 파일 크기",
    "c_model": "모델", "c_page": "이 문서<br>한 장", "c_repo": "레포 전체<br>13.4만 단어",
    "c_tps": "tok/s", "c_struct": "구조", "c_gloss": "용어",
    "c_mean": "뜻이 바뀐 곳<br>1천 단어당",
    "clean": "통과", "fail": "{n}건 실패", "worse": "▲ 나쁨", "better": "▼ 좋음",
    "found": "{n}건", "h3a": "속도와 정확도.", "h3b": "원 크기는 디스크 위의 파일 크기.",
    "xaxis": "decode tok/s  →  빠름", "yaxis": "1천 단어당 뜻이 바뀐 곳",
    "hosted": "{name} — 호스티드, 이 기계의 수치가 아님",
    "notmachine": "이 기계 아님", "cards": "카드 2장", "card3090": "3090",
    "carda6000": "A6000",
    "foot": ("<b>구조</b>는 스크립트가 잰다. 숫자·링크·인라인 코드·코드 펜스·표 모양·블록 수가 "
             "한 글자도 안 바뀌고 살아남아야 하며, 일부러 훼손한 여섯 가지에 전부 실패하는 걸 "
             "먼저 확인하고 걸었다. <b>용어</b>도 스크립트다 — 약속한 용어가 약속한 한국어로 나온 "
             "비율. <b>뜻이 바뀐 곳</b>은 스크립트가 될 수 없어서, 모든 번역을 원문 한 문단씩 "
             "교차 배치해 모델 이름을 가린 채 읽었다. 판독자 한 명, 모델당 문서 하나, ±2이므로 "
             "서로 2 이내는 동률로 본다. 속도는 서버 자신의 계측값이고 toktape 카드가 아니다. "
             "코드 펜스는 “건드리지 말라”고 지시하는 대신 요청에서 아예 빼고 나중에 되꽂았다."),
  },
}

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--ink:#e6edf3;--dim:#8b949e;
 --good:#3fb950;--bad:#f85149;--accent:#58a6ff;--ref:#a371f7}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
 font:22px/1.45 -apple-system,"Apple SD Gothic Neo","Segoe UI",Roboto,"Noto Sans KR",sans-serif;
 width:1200px;height:1500px;padding:24px 30px;display:flex;flex-direction:column;gap:11px}
h1{font-size:54px;font-weight:700;letter-spacing:-.025em;line-height:1.18}
h1 span{color:var(--accent)}
.sub{color:var(--dim);font-size:21px;line-height:1.45}
.sub b{color:#c9d1d9;font-weight:600}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:13px 18px}
.panel h2{font-size:17px;font-weight:700;color:var(--dim);text-transform:uppercase;
 letter-spacing:.12em;margin-bottom:9px}
table{border-collapse:collapse;width:100%;font-size:31px}
th+th,td+td{padding-left:22px}
th{text-align:right;color:var(--dim);font-weight:600;font-size:18px;padding:0 0 10px;
 border-bottom:1px solid var(--line);letter-spacing:.04em;line-height:1.35}
th:first-child,td:first-child{text-align:left}
td{padding:9px 0;border-bottom:1px solid #21262d;text-align:right;white-space:nowrap;
 font-variant-numeric:tabular-nums;font-feature-settings:"tnum"}
td.name,td[colspan]{white-space:normal}
tr:last-child td{border-bottom:none}
td.name{font-weight:600}
td.name small{color:var(--dim);font-weight:400;font-size:19px;margin-left:9px}
td.name em{color:#d29922;font-style:normal;font-size:18px;display:block;margin-top:2px}
sup.dag{color:#8b949e;font-size:19px;font-weight:400}
td.partial{font-size:24px;font-weight:600;color:#8b949e}
.win td{color:var(--good)} .win td.name{color:var(--ink)}
.ref td{color:var(--ref)} .ref td.name{color:var(--ink)}
.dead td{color:var(--dim)} .dead td.name{color:#8b949e}
.big{font-size:36px;font-weight:700}
.ex{border-top:1px solid #21262d;padding:11px 0 3px}
.ex:first-of-type{border-top:none;padding-top:4px}
.ex .en{font-size:26px;margin-bottom:5px}
.ex .en b{color:var(--accent);font-weight:700}
.ex .why{color:var(--dim);font-size:19px;margin-bottom:9px}
.r{display:grid;grid-template-columns:240px 1fr;gap:18px;align-items:baseline;padding:5px 0}
.r .who{font-size:18px;color:var(--dim);text-align:right}
.r .ko{font-size:27px}
.r .ko b{font-weight:700}
.r .back{display:block;font-size:19px;color:var(--dim);margin-top:4px}
.r .back b{color:#c9d1d9}
.ok .ko b{color:var(--good)} .ok .who::after{content:" ✓";color:var(--good)}
.no .ko b{color:var(--bad)}  .no .who::after{content:" ✗";color:var(--bad)}
.foot{color:var(--dim);font-size:16px;line-height:1.5;border-top:1px solid var(--line);
 padding-top:10px;margin-top:auto}
.foot b{color:#c9d1d9;font-weight:600}
.tag{float:right;background:#1f2937;border:1px solid var(--line);border-radius:6px;
 padding:4px 11px;font-size:16px;color:var(--dim);margin-left:12px}
text{font-family:-apple-system,"Apple SD Gothic Neo","Segoe UI",Roboto,sans-serif}
"""


def prep(d):
    w = d["source_words"]
    for r in d["rows"]:
        r["m1k"] = (1000.0 * r["meaning"] / w) if r.get("meaning") is not None else None
        r.setdefault("short", r["name"])
    # Ordered by meaning, with the rows that have no meaning number last -- they are ranked by
    # nothing, so they are not ranked among the rows that are.
    scored = sorted([r for r in d["rows"] if r["m1k"] is not None], key=lambda r: r["m1k"])
    unscored = sorted([r for r in d["rows"] if r["m1k"] is None and not r.get("failed")],
                      key=lambda r: r.get("wall") or 0)
    rows = scored + unscored
    plotted = [r for r in rows if r.get("decode") and r["m1k"] is not None]
    failed = [r for r in d["rows"] if r.get("failed")]
    return rows, plotted, failed


def where(r, L):
    """Placement reads as a phrase, not a key -- "both cards + RAM + NVMe" has to translate too."""
    t = r["where"]
    for a, b in (("not this machine", L["notmachine"]), ("both cards", L["cards"]),
                 ("TabbyAPI", "TabbyAPI"), ("exl3-serve", "exl3-serve")):
        t = t.replace(a, b)
    return t


def scatter(rows, plotted, L):
    W, H, Lf, R, T, B = 1104, 980, 76, 22, 26, 62
    xs = [r["decode"] for r in plotted]
    ys = [r["m1k"] for r in plotted]
    x1 = max(xs) * 1.15
    step = next(t for t in (1, 2, 5, 10, 20) if max(ys) / t <= 5)
    y1 = (int(max(ys) / step) + 1.35) * step

    y0 = -0.06 * y1
    def px(v): return Lf + v / x1 * (W - Lf - R)
    def py(v): return H - B - (v - y0) / (y1 - y0) * (H - T - B)

    g = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         f'<rect x="{Lf}" y="{T}" width="{W-Lf-R}" height="{H-T-B}" fill="#0d1117" '
         f'stroke="#30363d" rx="7"/>']
    tick = step
    while tick < y1:
        g.append(f'<line x1="{Lf}" y1="{py(tick):.1f}" x2="{W-R}" y2="{py(tick):.1f}" stroke="#21262d"/>')
        g.append(f'<text x="{Lf-9}" y="{py(tick)+4:.1f}" fill="#8b949e" font-size="20" '
                 f'text-anchor="end">{tick:.0f}</text>')
        tick += step
    for xv in (0, 50, 100, 150, 200):
        if xv <= x1:
            g.append(f'<text x="{px(xv):.1f}" y="{H-B+19}" fill="#8b949e" font-size="20" '
                     f'text-anchor="middle">{xv}</text>')
    g.append(f'<text x="{(Lf+W-R)/2:.0f}" y="{H-6}" fill="#8b949e" font-size="21" '
             f'text-anchor="middle">{L["xaxis"]}</text>')
    g.append(f'<text x="14" y="{(T+H-B)/2:.0f}" fill="#8b949e" font-size="21" text-anchor="middle" '
             f'transform="rotate(-90 14 {(T+H-B)/2:.0f})">{L["yaxis"]}</text>')
    g.append(f'<text x="{Lf+12}" y="{T+19}" fill="#f85149" font-size="20">{L["worse"]}</text>')
    g.append(f'<text x="{Lf+12}" y="{H-B-10}" fill="#3fb950" font-size="20">{L["better"]}</text>')

    for r in rows:
        if r.get("reference") and r["m1k"] is not None:
            yy = py(r["m1k"])
            g.append(f'<line x1="{Lf}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="#a371f7" '
                     f'stroke-width="1.5" stroke-dasharray="7 5"/>')
            g.append(f'<text x="{W-R-9}" y="{yy-8:.1f}" fill="#a371f7" font-size="21" '
                     f'text-anchor="end">{L["hosted"].format(name=r["short"])}</text>')

    # Labels are placed as boxes, not as offsets. The version before this one reasoned about a
    # side and a nudge and then wrote the text wherever that landed: on a card 1104 px wide it
    # clipped "DeepSeek-V4.1-Flash" to "pSeek-V4.1-Flash" against the left edge and ran
    # "Qwen3-Coder-Next" straight through "gpt-oss-20b". Here every candidate box is checked
    # against the plot rectangle, against every circle, and against every box already placed,
    # and the first one that fits wins.
    CH, FS = 27.0, 23          # label line box and font size
    boxes = []                 # (x0, y0, x1, y1) of what is already on the plot
    circles = [(px(q["decode"]), py(q["m1k"]),
                11 + (q["gb"] / max(t["gb"] for t in plotted)) * 19) for q in plotted]

    def free(x0, y0, x1, y1):
        if x0 < Lf + 4 or x1 > W - R - 4 or y0 < T + 2 or y1 > H - B - 2:
            return False
        for cx, cy, cr in circles:
            if x0 - 4 < cx + cr and cx - cr < x1 + 4 and y0 - 2 < cy + cr and cy - cr < y1 + 2:
                return False
        return not any(x0 < b2 and b0 < x1 and y0 < b3 and b1 < y1
                       for b0, b1, b2, b3 in boxes)

    for r in sorted(plotted, key=lambda q: -q["gb"]):
        x, y = px(r["decode"]), py(r["m1k"])
        rad = 11 + (r["gb"] / max(q["gb"] for q in plotted)) * 19
        col = "#3fb950" if r is min(plotted, key=lambda q: q["m1k"]) else "#58a6ff"
        # A row read on a weaker instrument is drawn as a weaker circle: no fill, a dashed
        # edge. Without it the picture says two local models beat the hosted reference on
        # meaning, which is a claim the reading behind those two points cannot carry.
        part = r.get("read") == "partial"
        g.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" '
                 f'fill="{col}" fill-opacity="{0.06 if part else 0.22}" stroke="{col}" '
                 f'stroke-width="2"{" stroke-dasharray=\"5 4\"" if part else ""}/>')
        label = r["short"] + ("\u2009†" if part else "")
        wide = len(label) * 11.5
        for dy in (0, -CH, CH, -2 * CH, 2 * CH, -3 * CH, 3 * CH):
            for side in ("start", "end"):
                dx = (rad + 10) if side == "start" else -(rad + 10)
                lx = x + dx
                x0, x1 = (lx, lx + wide) if side == "start" else (lx - wide, lx)
                cy = y + dy
                if free(x0, cy - CH * 0.55, x1, cy + CH * 0.35):
                    boxes.append((x0, cy - CH * 0.55, x1, cy + CH * 0.35))
                    g.append(f'<text x="{lx:.1f}" y="{cy+FS*0.35:.1f}" fill="#e6edf3" '
                             f'font-size="{FS}" text-anchor="{side}">{label}</text>')
                    dy = None
                    break
            if dy is None:
                break

    g.append("</svg>")
    return "".join(g)


def page(title, sub, body, foot, lang):
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<title>translation ladder</title><style>{CSS}</style></head><body>'
            f'{title}<p class="sub">{sub}</p>{body}'
            f'<p class="foot"><span class="tag">github.com/midagedev/rig-log</span>{foot}</p>'
            f'</body></html>')


def part1(d, L, lang):  # noqa: C901
    rows, plotted, failed = prep(d)
    w, scale = d["source_words"], d["repo_words"] / d["source_words"]
    n = len([r for r in d["rows"] if not r.get("reference")])
    # The headline compares the ladder against itself, so it is computed only over rows scored
    # on the ladder's own instrument. Two rows arrived later and were read a weaker way (GLM,
    # whose column its own broken characters identify, and Solar Open 2, read on the densest
    # blocks against two versions rather than four). They keep their place in the table with a
    # dagger; they do not get to set the sentence at the top, and a row that scored zero would
    # divide by zero if it did.
    full = list(plotted)
    bl = min(full, key=lambda r: r["m1k"])
    fa = max(full, key=lambda r: r["decode"])
    mult, slower = fa["m1k"] / bl["m1k"], bl["wall"] / fa["wall"]

    body = []
    for r in rows + failed:
        cls = (' class="ref"' if r.get("reference") else
               ' class="dead"' if r.get("failed") else
               ' class="win"' if r is bl else "")
        defect = r.get("defect_" + lang, r.get("defect"))
        name = (f'<td class="name">{r["short"]}'
                f'<small>{(format(r["gb"], "g") + " GB · ") if r["gb"] else ""}{where(r, L)}</small>'
                + (f'<em>{defect}</em>' if defect else "") + '</td>')
        if r.get("failed"):
            body.append(f'<tr{cls}>{name}<td class="big">{r["wall"]:.0f} s</td>'
                        f'<td colspan="4">{r.get("failed_note_" + lang, r.get("failed_note", ""))}</td></tr>')
            continue
        gate = (f'<span style="color:#3fb950">{L["clean"]}</span>' if not r["gate_fail"]
                else f'<span style="color:#f85149">{L["fail"].format(n=r["gate_fail"])}</span>')
        if r["wall"]:
            m = r["wall"] * scale / 60.0
            repo = f"{m:.0f} min" if m < 90 else f"{m/60:.1f} h"
            page_s, tps = f'{r["wall"]:.0f} s', f'{r["decode"]:.0f}'
        else:
            repo = page_s = tps = "—"
        # A row read on a weaker instrument does not get to print a rate per thousand words.
        # `0.0` is a rate; what was actually done for GLM and Solar Open 2 was a count over a
        # subset of blocks, and formatting it as `.1f` in the same weight as the ladder's own
        # numbers made two rows that were never scored the same way outrank every row that was.
        if r["m1k"] is None:
            mean_cell = '<td class="partial">—<sup class="dag">†</sup></td>'
        else:
            mean_cell = f'<td class="big">{r["m1k"]:.1f}</td>'
        body.append(f'<tr{cls}>{name}<td class="big">{page_s}</td><td>{tps}</td>'
                    f'<td>{gate}</td><td>{r["glossary"]}%</td>{mean_cell}</tr>')

    inner = (f'<div class="panel" style="flex:1"><h2>{L["t_rungs"]}</h2><table><thead><tr>'
             f'<th>{L["c_model"]}</th><th>{L["c_page"]}</th>'
             f'<th>{L["c_tps"]}</th><th>{L["c_struct"]}</th><th>{L["c_gloss"]}</th>'
             f'<th>{L["c_mean"]}</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')
    title = (f'<h1>{L["h1a"].format(n=n)}<br>'
             f'<span>{L["h1b"].format(mult=mult, slower=slower)}</span></h1>')
    rn = d.get("read_note_" + lang, d.get("read_note"))
    foot = (L["foot"] + f' {rn}') if any(r["m1k"] is None for r in rows) and rn else L["foot"]
    return page(title, L["sub"] + f' <b>{L["asof"]}</b>', inner, foot, lang)


def part3(d, L, lang):
    """The plot alone. On page 1 it was a quarter of the card with 15 px labels, which is
    nothing at the width a timeline gives an image. Here it gets the whole page."""
    rows, plotted, _ = prep(d)
    inner = f'<div class="panel" style="flex:1;display:flex;align-items:center">{scatter(rows, plotted, L)}</div>'
    title = f'<h1>{L["h3a"]}<br><span>{L["h3b"]}</span></h1>'
    rn = d.get("read_note_" + lang, d.get("read_note"))
    return page(title, L["sub"], inner, rn or L["foot"], lang)


def part2(d, L, lang):
    ex = []
    for e in d.get("examples", []):
        rs = []
        for r in e["renderings"]:
            cls = "ok" if r["ok"] else "no"
            rs.append(f'<div class="r {cls}"><div class="who">{r["who"]}</div>'
                      f'<div class="ko">{r["ko"]}<span class="back">→ {r["back"]}</span></div></div>')
        why = e.get("why_" + lang, e["why"])
        rs = "".join(rs)
        ex.append(f'<div class="ex"><div class="en">EN &nbsp;{e["en"]}</div>'
                  f'<div class="why">{why}</div>{rs}</div>')
    inner = f'<div class="panel" style="flex:1">{"".join(ex)}</div>'
    title = f'<h1>{L["h2a"]}<br><span>{L["h2b"]}</span></h1>'
    return page(title, L["sub"], inner, L["foot"], lang)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scores")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--stem", required=True)
    p.add_argument("--lang", default="ko", choices=["ko", "en"])
    a = p.parse_args()
    d = json.load(open(a.scores, encoding="utf-8"))
    L = STR[a.lang]
    os.makedirs(a.out_dir, exist_ok=True)
    for n, html in ((1, part1(d, L, a.lang)), (2, part2(d, L, a.lang)), (3, part3(d, L, a.lang))):
        f = os.path.join(a.out_dir, f"{a.stem}-{a.lang}-{n}.html")
        open(f, "w", encoding="utf-8").write(html)
        print(f)


if __name__ == "__main__":
    main()
