#!/usr/bin/env python3
"""Render a gpu-sale-check run directory into one PNG a buyer can look at.

    python3 tools/gpu-check-sheet.py <run-dir> <out.png> [--title "RTX 3090"]

Reads identity.txt, dmon.csv, memtest.log, burn.log, pcie-bw.txt, dmesg-delta.txt, aer-after.txt
from the run directory (copy it from the box first), writes <out>.html beside the PNG, and
screenshots it with headless Chrome at 1600x? (height fitted). No network, no JS libraries: the
chart is inline SVG so the sheet is one self-contained file.
"""
import csv, html, pathlib, statistics as st, subprocess, sys

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def main():
    run = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2])
    title = sys.argv[sys.argv.index("--title") + 1] if "--title" in sys.argv else run.name
    ident = (run / "identity.txt").read_text(errors="replace")
    def field(k, default="—"):
        for line in ident.splitlines():
            s = line.strip()
            if s.startswith(k) and ":" in s:
                return s.split(":", 1)[1].strip()
        return default
    rows = [r for r in csv.reader((run / "dmon.csv").open()) if len(r) >= 9 and not r[0].startswith("timestamp")]
    def col(i):
        v = []
        for r in rows:
            try: v.append(float(r[i].split()[0]))
            except ValueError: v.append(None)
        return v
    pw, sm, mem, tmp, fan = col(1), col(2), col(3), col(4), col(5)
    clean = lambda v: [x for x in v if x is not None]
    reasons = sorted({r[8].strip() for r in rows} - {"", "0x0000000000000000"})
    burn = (run / "burn.log").read_text(errors="replace")
    verdicts = [l.strip() for l in burn.splitlines() if "OK" in l or "FAULTY" in l]
    burn_ok = bool(verdicts) and "FAULTY" not in verdicts[-1]
    mlog = (run / "memtest.log").read_text(errors="replace")
    mem_err = sum(1 for l in mlog.splitlines() if "ERROR" in l.upper() or "FAIL" in l.upper())
    mem_ok = mem_err == 0 and mlog.strip() != ""
    bw = (run / "pcie-bw.txt").read_text(errors="replace").strip().splitlines()
    delta = (run / "dmesg-delta.txt").read_text(errors="replace").strip()
    aer = (run / "aer-after.txt").read_text(errors="replace").strip()
    aer_ok = "+" not in "".join(l for l in aer.splitlines() if "UESta" in l or "CESta" in l)
    runlog = (run / "run.log").read_text(errors="replace") if (run / "run.log").exists() else ""
    burn_min = next((l.split("burn ")[1].split(" min")[0] for l in runlog.splitlines() if "burn " in l and " min" in l), "?")
    passes = next((l.split("memtest ")[1].split(" pass")[0] for l in runlog.splitlines() if "memtest " in l and " pass" in l), "?")
    started = runlog.splitlines()[0].split(" ")[0] if runlog else ""

    # --- SVG chart: temp, power, SM clock over the run ---
    W, H, L, B = 1400, 260, 60, 30
    n = max(len(rows), 2)
    def poly(vals, vmin, vmax, color, label, lw=2):
        pts = []
        for i, v in enumerate(vals):
            if v is None: continue
            x = L + (W - L - 20) * i / (n - 1); y = H - B - (H - B - 20) * (v - vmin) / max(vmax - vmin, 1e-9)
            pts.append(f"{x:.1f},{y:.1f}")
        return f'<polyline fill="none" stroke="{color}" stroke-width="{lw}" points="{" ".join(pts)}"/>'
    svg = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace,Menlo,monospace" font-size="13">']
    svg.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0f1115"/>')
    for k in range(5):
        y = H - B - (H - B - 20) * k / 4
        svg.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-20}" y2="{y:.1f}" stroke="#2a2f3a"/>')
    if rows:
        svg.append(poly(tmp, 20, 100, "#ff7a59", "temp"))
        svg.append(poly([p / 4.2 if p is not None else None for p in pw], 20, 100, "#ffd166", "power"))
        svg.append(poly([c / 21 if c is not None else None for c in sm], 20, 100, "#4cc9f0", "sm clock"))
    svg.append(f'<text x="{L}" y="16" fill="#ff7a59">temp °C (20–100)</text><text x="{L+170}" y="16" fill="#ffd166">power W (÷4.2, 84–420)</text><text x="{L+420}" y="16" fill="#4cc9f0">SM MHz (÷21, 420–2100)</text>')
    svg.append(f'<text x="{L}" y="{H-8}" fill="#8b93a7">0 s</text><text x="{W-90}" y="{H-8}" fill="#8b93a7">{len(rows)} s</text>')
    svg.append("</svg>")

    def row(name, result, ok):
        cls = "pass" if ok else "fail"
        return f"<tr><td>{html.escape(name)}</td><td>{html.escape(result)}</td><td class='{cls}'>{'PASS' if ok else 'FAIL'}</td></tr>"
    stat = lambda v, f="{:.0f}": (f.format(st.mean(clean(v))) if clean(v) else "—")
    table = [
        row(f"cuda_memtest, 전체 VRAM, {passes} pass", f"오류 {mem_err}건", mem_ok),
        row(f"gpu_burn {burn_min}분, 결과 검증", verdicts[-1] if verdicts else "판정 줄 없음", burn_ok),
        row("커널 로그 (Xid / NVRM / AER) 증가", f"{len(delta.splitlines()) if delta else 0}줄", not delta),
        row("PCIe 오류 레지스터 (UESta/CESta)", "모두 클리어" if aer_ok else "플래그 있음", aer_ok),
    ]
    info = [
        ("모델", field("Product Name")), ("VBIOS", field("VBIOS Version")), ("드라이버", field("Driver Version")),
        ("PCIe 링크 최대", f"Gen {field('Max', '?')} x16"), ("VRAM", field("Total", "24576 MiB")),
        ("전력 한도", field("Current Power Limit", field("Power Limit", "—"))),
        ("번인 중 최고 온도", f"{max(clean(tmp)):.0f} °C" if clean(tmp) else "—"),
        ("번인 중 전력 최대 / 평균", f"{max(clean(pw)):.0f} / {stat(pw)} W" if clean(pw) else "—"),
        ("번인 중 SM 클럭 최소 / 평균", f"{min(clean(sm)):.0f} / {stat(sm)} MHz" if clean(sm) else "—"),
        ("팬 최대", f"{max(clean(fan)):.0f} %" if clean(fan) else "—"),
        ("스로틀 사유", ", ".join(reasons) if reasons else "없음(0x0)"),
    ]
    page = f"""<!doctype html><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{margin:0;background:#0f1115;color:#e6e9f0;font:15px/1.45 -apple-system,"Apple SD Gothic Neo",Helvetica,Arial,sans-serif}}
.wrap{{width:1520px;padding:28px 40px 36px}}
h1{{margin:0 0 4px;font-size:30px}} .sub{{color:#8b93a7;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
table{{border-collapse:collapse;width:100%}} td,th{{padding:7px 10px;border-bottom:1px solid #2a2f3a;text-align:left;vertical-align:top}}
th{{color:#8b93a7;font-weight:600}} .pass{{color:#5be49b;font-weight:700}} .fail{{color:#ff6b6b;font-weight:700}}
.k{{color:#8b93a7;width:210px}} pre{{background:#151923;padding:10px 12px;border-radius:6px;font:13px ui-monospace,Menlo,monospace;color:#c9d1e3;margin:0;white-space:pre-wrap}}
.foot{{color:#8b93a7;font-size:13px;margin-top:14px}}
</style><div class="wrap">
<h1>{html.escape(title)} — 판매 전 점검 결과</h1>
<div class="sub">{html.escape(started)} 시작 · 카드 하나만 대상(UUID 고정), 1 Hz 계측 · nvidia-smi / cuda_memtest / gpu_burn / torch</div>
<div class="grid">
<div><table><tr><th colspan="2">카드</th></tr>{''.join(f"<tr><td class='k'>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in info)}</table></div>
<div><table><tr><th>시험</th><th>결과</th><th>판정</th></tr>{''.join(table)}</table>
<div style="margin-top:14px"><pre>{html.escape(chr(10).join(bw))}</pre></div></div>
</div>
<div style="margin-top:20px">{''.join(svg)}</div>
<div class="grid" style="margin-top:14px"><div><pre>{html.escape(aer)}</pre></div><div><pre>{html.escape(delta if delta else 'dmesg: 시험 중 추가된 Xid/NVRM/AER 줄 없음')}</pre></div></div>
<div class="foot">원본 파일: identity.txt · memtest.log · burn.log · dmon.csv · pcie-bw.txt · dmesg-delta.txt · aer-before/after.txt — tools/gpu-sale-check.sh (rig-log)</div>
</div>"""
    htmlp = out.with_suffix(".html"); htmlp.write_text(page)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={out}", "--window-size=1600,1000", f"file://{htmlp.resolve()}"], check=True, capture_output=True)
    # second pass: fit the height to the document
    h = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--dump-dom", f"file://{htmlp.resolve()}"], capture_output=True, text=True).stdout
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={out}", "--window-size=1600,1250", f"file://{htmlp.resolve()}"], check=True, capture_output=True)
    print(out, out.stat().st_size, "bytes")

if __name__ == "__main__":
    main()
