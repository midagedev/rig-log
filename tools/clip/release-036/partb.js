"use strict";
// Part B of the 0.3.6 film in the Instrument look: real requests, each answer a count of 100 squares; the answers
// kept; the hard suite; DeepSeek-V4.1-Flash's two arms; the timed requests as rulers of squares; the end. Loaded after
// film.html's script, whose helpers it draws with (txt, ktxt, rect, iso, iso100, mxFrame, arrive, bt, q16, K, TY, Y); a
// made-up input (probe/bfx.py) stamps every frame through film.html's D.fixture.
// Every frame is a pure function of t; every string and number is data.json's (make_data_b.py: copy keys b_*, the
// block D.b). A grid's white squares are the pick's probability in the saved body, rounded, and its percentage says the
// same count; grey the runner-up's; the thin line under it the body's confidence, labelled so it never reads as one.
const PB = { top: 200, gap: 24, conf: 14, sig: 8, chip: 120 };
function bBlack() { mxFrame({ none: true }); }
const hasKR = s => /[가-힣]/.test(s);
// A face for s: Noto Sans KR heavy when it holds Hangul, Martian Mono otherwise.
const bFace = (s, o = {}) => hasKR(s) ? { kr: true, wght: 800, ...o } : { mono: true, wght: o.wght ?? 700, wdth: 75, ...o };
// The 16th-note count-up of a grid: none before the grid beat, a quarter more each 16th, all from the fourth.
function bCount(t, S, n) {
  const g = D.b.beats.grid * 4;
  let k = 0; for (let j = 0; j < 4; j++) if (t >= q16(S, g + j)) k = j + 1;
  return Math.round(n * k / 4);
}
// One answer: a 10 x 10 grid of s px at (x, y), its top option's count white, the runner-up's grey, the rest dark.
function bGrid(t, S, x, y, s, a, o = {}) {
  const nt = o.count ? bCount(t, S, a.top) : a.top, nr = o.count ? bCount(t, S, a.run) : a.run;
  iso(x, y, s, [[nt, o.topFill ?? K.w], [nr, K.mark]]);
}
// A check or a cross drawn as strokes (the faces have neither glyph), w px across, centred on the text's x-height.
function bMark(ok, x, y, w, col) {
  const p = ok ? `M ${x} ${y - w * 0.45} L ${x + w * 0.38} ${y - w * 0.08} L ${x + w} ${y - w * 0.9}`
               : `M ${x} ${y - w * 0.9} L ${x + w * 0.82} ${y - w * 0.08} M ${x + w * 0.82} ${y - w * 0.9} L ${x} ${y - w * 0.08}`;
  el("path", { d: p, fill: "none", stroke: col, "stroke-width": PB.sig, "stroke-linecap": "square" });
}

// ---- REQUESTS: the text on the cut, the grids count up on 16ths, the picks and figures on the answer beat --------------
function bRequest(i) {
  return (t, S) => {
    bBlack();
    const R = D.b.req[i], c = D.copy, k = R.key, qs = R.qs, n = qs.length;
    ktxt(c.q_jump, 72, Y.label, TY.label);
    ktxt(c[`${k}_id`], 1008, Y.label, TY.axis, { anchor: "end" });
    const lines = c[`${k}_txt`], lh = Math.round(R.size * 1.3);
    lines.forEach((s, j) => txt(s, 72, PB.top + j * lh, bFace(s, { size: R.size, fill: K.w })));
    const yq = PB.top + (lines.length - 1) * lh + 76;       // the questions' labels
    const ka = arrive(t, bt(S, D.b.beats.ans), "cut");
    const pick = (s, x, y) => txt(s, x, y, bFace(s, { size: 52, wght: 800, fill: K.sig }));
    if (n === 1) {         // one question: the grid at the left, its words beside it
      const a = qs[0], s = Math.min(48, Math.floor((940 - yq - 20) / 10)), x2 = 72 + 10 * s + 40;
      bGrid(t, S, 72, yq - 24, s, a, { count: true });
      ktxt(c[`${k}_q`][0], x2, yq + 20, hasKR(a.q) ? { ...TY.kr, fill: K.lab } : TY.label);
      if (ka) {
        pick(c[`${k}_pk`][0], x2, yq + 110);
        ktxt(c[`${k}_pc`][0], x2, yq + 216, TY.fig, { size: 104 });
      }
    } else {               // two or three: a column each, the words under the grid (the pick and its figure on one
                           // line in a column of two, one under the other in a column of three)
      const cw = (936 - (n - 1) * PB.gap) / n, one = n === 2, below = one ? 164 : 226;
      const s = Math.max(ISO_MIN, Math.min(Math.floor(cw / 10), Math.floor((880 - below - yq - 20) / 10)));
      qs.forEach((a, j) => {
        const x = 72 + j * (cw + PB.gap), gb = yq + 20 + 10 * s;
        ktxt(c[`${k}_q`][j], x, yq, hasKR(a.q) ? { ...TY.kr, fill: K.lab } : TY.label);
        bGrid(t, S, x, yq + 20, s, a, { count: true });
        if (!ka) return;
        const pk = c[`${k}_pk`][j];
        pick(pk, x, gb + 70);
        if (one) ktxt(c[`${k}_pc`][j], x + adv(pk, 52, bFace(pk, { size: 52, wght: 800 })) + 20, gb + 70, TY.fig, { size: 64 });
        else ktxt(c[`${k}_pc`][j], x, gb + 136, TY.fig, { size: 64 });
        // no confidence line on a card of two or three: its length matched none of the figures beside it
      });
    }
    ktxt(c.rq_post, 72, Y.foot - 56, TY.label);       // the route, and under it what its body holds
    ktxt(c.rq_body, 72, Y.foot, TY.label);
  };
}
for (let i = 0; i < 8; i++) SCN[`req${i}`] = bRequest(i);

// ---- SAME ANSWERS: schemajump's picks against plain structured output's, a square a request ----------------------------
SCN.bsame = (t, S) => {
  bBlack();
  const c = D.copy, B = D.b.same, s = Math.min(64, Math.floor(936 / B.of));
  ktxt(c.b_sa_head, 72, Y.head, TY.head, { fit: 936 });
  ktxt(c.b_sa_n, 72, 520, TY.fig, { size: 220 });
  c.b_sa_t.forEach((s_, j) => ktxt(s_, 72, 610 + j * 58, TY.cap));
  const ym = 610 + c.b_sa_t.length * 58 + 30;
  B.marks.forEach((m, j) => rect(72 + j * s, ym, s - 8, s - 8, { fill: m ? K.w : K.cell, floor: "same" }));
};

// ---- HARD QUESTIONS: correct of N per model, a square a question; then V4.1-Flash's two arms in a line ----------------
SCN.bhard = (t, S) => {
  bBlack();
  const c = D.copy, H = D.b.hard.head, n = H[0].n, s = Math.floor(936 / n);
  ktxt(c.b_hd_head, 72, Y.head, TY.head, { fit: 936 });
  if (c.b_hd_v41c) c.b_hd_v41c.forEach((s_, j, A_) => ktxt(s_, 72, Y.foot - 56 * (A_.length - j), TY.label));   // V4.1's conditions
  H.forEach((h, i) => {
    const y = 330 + i * 130;
    ktxt(c[h.key], 72, y, TY.cap);
    ktxt(c.b_hd_c[i], 1008, y, TY.cap, { anchor: "end", size: 52 });
    for (let j = 0; j < n; j++) rect(72 + j * s, y + 26, s - 5, s - 5, { fill: j < h.correct ? K.w : K.cell, floor: "hard" });
  });
  ktxt(c.b_hd_n, 72, Y.foot, TY.label);
};
// A hard question drawn as each model's pick: our label under the question, then per model an equal chip, empty on
// the cut, its pick and a check where it is our label, a cross where it is not, on the answer beat. No shares: the
// models' percentages are different kinds of number.
function bHardEx(e) {
  return (t, S) => {
    bBlack();
    const c = D.copy, X = D.b.hard.ex[e], k = X.key, n = X.cols.length, cw = (936 - (n - 1) * PB.gap) / n;
    ktxt(c.b_hd_ex, 72, Y.label, TY.label);
    ktxt(c[`${k}_id`], 1008, Y.label, TY.axis, { anchor: "end" });
    const ql = c[`${k}_q`];
    ql.forEach((s_, j) => txt(s_, 72, PB.top + j * 58, bFace(s_, { size: 44, fill: K.w })));
    const yg = PB.top + (ql.length - 1) * 58 + 70, gl = c[`${k}_gold`];
    txt(gl, 72, yg, bFace(gl, { size: 44, wght: 800, fill: K.sig }));
    const yn = yg + 84, yc = yn + 28, ch = PB.chip, ym = yc + ch / 2, ka = arrive(t, bt(S, D.b.beats.ans), "cut");
    X.cols.forEach((a, j) => {
      const x = 72 + j * (cw + PB.gap);
      ktxt(c[`${k}_nm`][j], x, yn, TY.label);
      rect(x, yc, cw, ch, { stroke: K.mark, sw: 3 });
      if (!ka) return;
      // the pick at 52 px, down to 44 where a chip of three is narrow, a clear gap before the mark
      const pk = c[`${k}_pk`][j], room = cw - 20 - 36 - 20 - 28;
      let sz = 52;
      while (sz > 44 && adv(pk, sz, bFace(pk, { size: sz, wght: 800 })) > room) sz -= 2;
      const fo = bFace(pk, { size: sz, wght: 800, fill: a.ok ? K.w : K.lab });
      txt(pk, x + 20, ym + 18, fo);
      bMark(a.ok, x + cw - 20 - 36, ym + 18, 36, K.sig);
    });
  };
}
for (let e = 0; e < 4; e++) SCN[`bhx${e}`] = bHardEx(e);

// ---- rulers of squares: a row's name, its value at the right, a square a unit of time ---------------------------------
// Rulers leave RULER_TXT px at the right for the value set on their line.
const RULER_TXT = 236;
const rulerS = n => Math.min(48, Math.floor((936 - RULER_TXT) / n));
function bRuler(x, y, s, n, col, done = n) {
  for (let j = 0; j < n; j++) rect(x + j * s, y, s - 5, s - 5, { fill: j < done ? (typeof col === "function" ? col(j) : col) : K.cell, floor: "ruler" });
}
// SHORT: the p50 walls of the short requests, Clef-Flash's decide seat and Qwen3.6's two arms.
SCN.bshort = (t, S) => {
  bBlack();
  const c = D.copy, R = D.b.short.rows, s = rulerS(Math.max(...R.map(r => r.sq)));
  ktxt(c.b_sh_sub, 72, Y.label, TY.label);
  ktxt(c.b_sh_head, 72, Y.head, TY.head, { fit: 936 });
  const cols = { clef: K.w, q_jump: K.w, q_step_m: K.mark };
  R.forEach((r, i) => {
    const y = 360 + i * 160;
    ktxt(c[r.key], 72, y, TY.cap);
    bRuler(72, y + 26, s, r.sq, cols[r.key]);
    ktxt(c.b_sh_v[i], 1008, y + 26 + s - 5, TY.cap, { anchor: "end" });
  });
  if (D.b.long_mode === "line") ktxt(c.b_sh_long, 72, 850, TY.cap);
  ktxt(c.b_foot, 72, 930, TY.label);
  ktxt(c.foot_rt, 72, Y.foot, TY.label);
};
// LONG: the two long requests sent on GO; each lane's squares land as its wall runs, the prompt's reading white and
// the rest grey; each model's own tokenizer counts its tokens.
SCN.blong = (t, S) => {
  bBlack();
  const c = D.copy, L = D.b.long, s = Math.min(48, Math.floor(936 / Math.max(...L.reqs.flatMap(r => r.lanes.map(l => l.sq)))));
  ktxt(c.b_lg_head, 72, Y.label, TY.label);
  const go = bt(S, D.b.beats.go), kf = arrive(t, bt(S, D.b.beats.finish), "cut");
  L.reqs.forEach((r, i) => {
    const y0 = 200 + i * 260;
    r.lanes.forEach((l, j) => {
      const y = y0 + j * 124;
      ktxt(c[`b_lg${i}_n`][j], 72, y, TY.cap);
      // the lane runs at its p50 wall from GO, filling square by square left to right (a steady fill: no cut)
      const f = clamp((t - go) / (l.wall / 1000)) * l.sq;
      for (let q = 0; q < l.sq; q++) {
        rect(72 + q * s, y + 24, s - 5, s - 5, { fill: K.cell, floor: "lane" });
        const w = clamp(f - q) * (s - 5);
        if (w > 0) rect(72 + q * s, y + 24, w, s - 5, { fill: q < l.sq_p ? K.w : K.mark });
      }
      // the ratio at the faster lane's end, once both lanes of the request are in
      if (j === 1 && kf) ktxt(c[`b_lg${i}_r`], 72 + l.sq * s + 16, y + 24 + s - 5, TY.cap);
    });
  });
  rect(72, 704, 36, 36, { fill: K.w, floor: "legend" });
  ktxt(c.b_lg_leg_p, 126, 740, TY.cap);
  const x2 = 126 + adv(c.b_lg_leg_p, 44, TY.cap) + 56;
  rect(x2, 704, 36, 36, { fill: K.mark, floor: "legend" });
  ktxt(c.b_lg_leg_r, x2 + 54, 740, TY.cap, { fill: K.lab });
  if (kf) ktxt(c.b_lg_why, 72, 830, TY.cap);
  ktxt(c.b_foot, 72, 930, TY.label);
  ktxt(c.foot_rt, 72, Y.foot, TY.label);
};

// ---- SOLAR: the slot for another model's numbers, shown only while inputs.json fills it --------------------------------
SCN.bsolar = (t, S) => {
  bBlack();
  const c = D.copy;
  ktxt(c.so_now, 72, Y.label, TY.label);
  ktxt(c.so_name, 72, Y.head, TY.head, { fit: 936 });
  [[c.so_dec, c.so_dec_v, 400], [c.so_pre, c.so_pre_v, 640]].forEach(([lab, val, y]) => {
    ktxt(lab, 72, y, TY.label);
    ktxt(val, 72, y + 120, TY.fig, { size: 104 });
  });
  ktxt(c.so_cond, 72, Y.foot, TY.label);
};

// ---- END: the matrix fades to one white cell; the name, the version, the address ---------------------------------------
SCN.bend = (t, S) => {
  const u = clamp((t - bt(S, 0)) / P);
  mxFrame({ base: 1 - u, cells: t < bt(S, 1) ? new Map([[key(20, MX.n), K.w]]) : null });
  const k = arrive(t, bt(S, 2), "cut");
  ktxt(D.copy.name, 72, Y.head, TY.head, { k, size: 150, fit: 560 });
  ktxt(D.copy.version, 1008, Y.head, TY.head, { k, size: 96, fill: K.lab, anchor: "end" });
  if (D.copy.and_line) ktxt(D.copy.and_line, 72, Y.cap, TY.cap, { k });
  ktxt(D.copy.url, 72, Y.foot, TY.cap, { k });
};
