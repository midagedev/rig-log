"use strict";
// Part A of the 0.3.6 film in the Instrument look, in plain sentences: the request; one token's trip through the 40
// layers (8 of 256 experts a layer, + 1 shared: a picture, the routing is seeded); plain structured output writing the
// answer a token a call, the schema's fixed text spotlighted; a rewind, and schemajump writing it again, the ids of a
// call fed together under one bar and each decision picked among the schema's options; both answers the same text;
// one decision's pick and its percentage.
// Loaded after film.html's script, whose helpers it draws with (txt, ktxt, rect, poly, el, adv, mxFrame, route, bt,
// q16, K, TY, Y, stampBox); the title is film.html's scene. Every frame is a pure function of t; every
// string and beat is data.json's (make_data_a.py: the block D.a, the shared copy keys).
const PA = { size: 76, x: 72, y: 560, bar: 24, gap: 8, under: 24, cy: 330, csize: 200, reel: 0.30, spotY: 470 };
function aBlack() { mxFrame({ none: true }); }
const aFace = f => f === "kr" ? { kr: true, wght: 800 } : { mono: true, wght: 600, wdth: 75 };
// The answer as the tokenizer cuts it, a question a line (the pieces' line), every line at one size fitted to the
// width: {j, s, kind, li, o, x, y, w, size} a piece. A line's baseline is `pitch` below the one before (the bars fit
// between).
function aLay(y, size0 = PA.size, room = 60) {
  const ps = D.copy.pieces, wl = [];
  ps.forEach(([s, f, , li]) => { wl[li] = (wl[li] || 0) + adv(s, size0, aFace(f)); });
  const size = size0 * Math.min(1, 936 / Math.max(...wl)), pitch = Math.round(0.8 * size + room), xs = [];
  return ps.map(([s, f, kind, li], j) => {
    const o = aFace(f), w = adv(s, size, o), x = xs[li] ?? PA.x, p = { j, s, kind, li, o, x, y: y + li * pitch, w, size };
    xs[li] = x + w; return p;
  });
}
// A call's bar under the ids it feeds (spans: [first, n, colour?] a call), a gap between calls. Where the answer
// breaks its line the bar runs open to the right margin and on from the left one, so a call reads as one bar.
function aBars(L, spans, col, under = PA.under) {
  for (const [f, n, c2] of spans) {
    for (let a = f; a < f + n;) {
      let b = a; while (b + 1 < f + n && L[b + 1].li === L[a].li) b++;
      const x0 = a > f ? PA.x - 10 : L[a].x + PA.gap / 2, x1 = b < f + n - 1 ? 1018 : L[b].x + L[b].w - PA.gap / 2;
      rect(x0, L[a].y + under, x1 - x0, PA.bar, { fill: c2 ?? col, floor: "call" });
      a = b + 1;
    }
  }
}
// A bar of no call: its outline only.
function aNoCall(L, f, n, under = PA.under) {
  const a = L[f], b = L[f + n - 1];
  rect(a.x + PA.gap / 2, a.y + under, b.x + b.w - a.x - PA.gap, PA.bar, { stroke: K.lab, sw: 3 });
}
// A token's bounds: a thin box round each piece, so a token of many letters reads as one piece.
function aBoxes(L) {
  for (const p of L) rect(p.x + 3, p.y - 0.80 * p.size, p.w - 6, 1.08 * p.size, { stroke: K.mark, sw: 2 });
}
const aTy = s => /[가-힣]/.test(s) ? TY.kr : TY.cap;     // a question's or an option's face
// The counter: "engine calls" at the left, its value at the right of the same line.
function aCounter(v) {
  ktxt(D.copy.calls_label, 72, PA.cy, TY.cap, { fill: K.lab });
  ktxt(D.copy.ticks[v], 1008, PA.cy, TY.fig, { size: PA.csize, anchor: "end" });
}

// ---- REQUEST: the decision request's text on the cut, its questions and their options on a beat ------------------
SCN.areq = (t, S) => {
  aBlack();
  const c = D.copy, lh = 66, y0 = 236;
  ktxt(c.rq_post, 72, Y.label, TY.label);
  rect(72, y0 - 50, 12, (c.state.length - 1) * lh + 66, { fill: K.mark, floor: "request" });
  c.state.forEach((s, i) => ktxt(s, 112, y0 + i * lh, TY.req));
  if (!arrive(t, bt(S, D.a.rq.qs), "cut")) return;
  const row = (q, opts, y) => {
    ktxt(q, 72, y, aTy(q), { fill: K.lab });
    let x = 72 + adv(q, 44, aTy(q)) + 36;
    for (const s of opts) {
      const o = aTy(s), w = adv(s, 44, o);
      rect(x, y - 48, w + 36, 68, { stroke: K.mark, sw: 3 });
      ktxt(s, x + 18, y, o, { fill: K.w });
      x += w + 36 + 18;
    }
  };
  const n = c.rq_qs.length;
  c.rq_qs.forEach((q, i) => row(q, c.rq_opts[i], 590 - (n - 2) * 70 + i * 104));
  ktxt(c.rq_served, 72, Y.cap, TY.cap, { fill: K.lab });
  ktxt(c.q_model, 72 + adv(c.rq_served, 44, TY.cap) + 24, Y.cap, TY.cap);
};

// ---- ONE TOKEN, ONE TRIP: the token goes down the 40 layers on 16ths; one layer opens into its 256 experts ---------
const TRP = { x: 128, w: 272, y: 300, p: 13.5, h: 9, gx: 492, gy: 300, gs: 28, tok: 28 };
SCN.atrip = (t, S) => {
  aBlack();
  const c = D.copy, A = D.a.tr, ry = l => TRP.y + l * TRP.p;
  ktxt(c.a_tr_head, 72, Y.head, TY.head, { fit: 936 });
  ktxt(c.a_tr_cap1, 72, Y.cap, TY.cap);
  let k = -1; for (let j = 0; j < 8; j++) if (t >= q16(S, 4 * A.down + j)) k = j;     // the token in layers 5k..5k+4
  const zoom = A.zoom != null && t >= bt(S, A.zoom);
  for (let l = 0; l < 40; l++) {
    const fill = zoom ? (l === A.layer ? K.w : K.lab) : k < 0 ? K.mark : l < 5 * k ? K.lab : l < 5 * k + 5 ? K.w : K.mark;
    rect(TRP.x, ry(l), TRP.w, TRP.h, { fill });
  }
  const tl = k < 0 ? 0 : 5 * k;       // the token: a square beside the layers it is in
  rect(TRP.x + TRP.w + 12, ry(tl) + (4 * TRP.p + TRP.h) / 2 - TRP.tok / 2, TRP.tok, TRP.tok, { fill: K.w, floor: "token" });
  ktxt(c.a_ax_l0, 72, ry(0) + 10, TY.axis);
  ktxt(c.a_ax_l39, 72, ry(39) + 10, TY.axis);
  if (!zoom) return;
  ktxt(c.a_tr_l, 72, ry(A.layer) + 10, TY.axis);
  const g = TRP.gs, n = 16, gh = n * g - 4, yl = ry(A.layer) + TRP.h / 2;
  for (const yy of [TRP.gy, TRP.gy + gh]) el("line", { x1: TRP.x + TRP.w, y1: yl, x2: TRP.gx, y2: yy, stroke: K.mark, "stroke-width": 2 });
  const lit = new Set(route(0, A.layer));
  for (let e = 0; e < 256; e++)
    rect(TRP.gx + (e % n) * g, TRP.gy + Math.floor(e / n) * g, g - 4, g - 4, { fill: lit.has(e) ? K.w : K.past[3], floor: "expert" });
  const ys = TRP.gy + gh + 24;        // the shared expert, read by every token
  rect(TRP.gx, ys, g - 4, g - 4, { fill: K.w, floor: "expert" });
  ktxt(c.a_tr_sh, TRP.gx + g + 16, ys + g - 4, TY.cap);
  ktxt(c.a_tr_cap2, 72, Y.foot, TY.cap);
};

// ---- PLAIN STRUCTURED OUTPUT: one token a 16th, each its own call and bar; then the fixed text in the spotlight ----
SCN.aplain = (t, S) => {
  aBlack();
  const c = D.copy, A = D.a.pl, L = aLay(PA.y), spot = t >= bt(S, A.spot);
  ktxt(c.st_head, 72, Y.label, TY.label);
  let n = 0; L.forEach(p => { if (t >= q16(S, 4 * A.at + p.j)) n = p.j + 1; });
  aCounter(n);
  const fixed = p => p.kind[0] === "F";
  // the spotlight: the fixed pieces white boxes, their text black; the decisions dimmed (K.dim, over 3:1)
  if (spot) L.forEach(p => { if (fixed(p)) rect(p.x - 2, p.y - 0.86 * p.size, p.w + 4, 1.16 * p.size, { fill: K.w }); });
  else aBoxes(L.slice(0, n));
  L.slice(0, n).forEach(p => txt(p.s, p.x, p.y, { ...p.o, size: p.size, fill: spot ? (fixed(p) ? K.bg : K.dim) : K.w, grp: "answer" }));
  aBars(L, L.slice(0, n).map(p => [p.j, 1, p.kind[0] === "D" ? K.sig : null]), K.w);    // a decision's id: its call picked it
  ktxt(c.a_pl_cap, 72, Y.cap, TY.cap);
  if (spot) ktxt(c.spot, 72, PA.spotY, TY.cap);
};

// ---- SCHEMAJUMP: the rewind (the rest bar), then the program's calls on beats: a call's ids land together over one bar;
// the call before a decision picks it, its options running on a reel to the pick ---------------------------------------
SCN.ajump = (t, S) => {
  aBlack();
  const c = D.copy, A = D.a.jp, L = aLay(PA.y), r1 = bt(S, A.rew);
  ktxt(c.jp_head, 72, Y.label, TY.label);
  if (t < r1) {        // the step's answer leaves last first over three beats and its counter runs back to 0
    let k = 0; for (let j = 1; j <= 4 * A.rew; j++) if (t >= q16(S, j)) k = j;
    const u = Math.min(1, k / (4 * (A.rew - 1))), left = Math.round((1 - u) * L.length);
    aBoxes(L.slice(0, left));
    L.slice(0, left).forEach(p => txt(p.s, p.x, p.y, { ...p.o, size: p.size, fill: K.lab, transient: true }));
    aBars(L, L.slice(0, left).map(p => [p.j, 1]), K.mark);
    aCounter(Math.round((1 - u) * +c.count_step));
    for (const dx of [0, 60]) poly([[520 + dx + 56, 240], [520 + dx, 290], [520 + dx + 56, 340]], K.w);   // the rewind mark
    return;
  }
  // the engine's order: the prompt call (the lead's ids ride in it) picks decision 1; each call feeds a decision's id
  // and the fixed run after it and picks the next; the tail is written with no call. Without the server's counts, the
  // program's plan: calls only.
  const calls = A.calls, pr = A.prompt, tl = A.tail, off = pr ? 1 : 0;
  const at = calls.map((_, i) => bt(S, A.rew + (i + off) * A.step)), t0 = bt(S, A.rew), tt = bt(S, A.rew + (calls.length + off) * A.step);
  let n = 0; for (const x of at) if (t >= x) n++;
  aCounter(n);
  const fed = new Array(L.length).fill(false), picked = {};
  if (pr && t >= t0) { for (let j = pr.first; j < pr.first + pr.n; j++) fed[j] = true; picked[pr.pick] = t - t0; }
  calls.slice(0, n).forEach((cl, i) => {
    for (let j = cl.first; j < cl.first + cl.n; j++) fed[j] = true;
    if (cl.pick) picked[cl.pick] = t - at[i];
  });
  if (tl && t >= tt) for (let j = tl.first; j < tl.first + tl.n; j++) fed[j] = true;
  const reel = (d, u) => {       // a decision's options run past its place and stop on the pick
    const r = A.runs[d], ps = L.slice(r.first, r.first + r.n), p0 = ps[0], size = p0.size;
    const x0 = p0.x, x1 = ps[ps.length - 1].x + ps[ps.length - 1].w, y0 = p0.y - 0.86 * size, h = 1.16 * size;
    const list = c.options[+d.slice(1) - 1], pick = ps.map(p => p.s).join(""), pi = list.indexOf(pick), nn = list.length;
    if (pi < 0) console.error(`decision "${pick}" is not one of its options`);
    const id = `areel${d}`, cp = el("clipPath", { id }, el("defs", {}));
    el("rect", { x: x0 - 40, y: y0, width: Math.max(x1 - x0, ...list.map(s => adv(s, size, p0.o))) + 80, height: h }, cp);
    const g = el("g", { "clip-path": `url(#${id})` }), f = pi + (1 - oexp(u / PA.reel)) * 2 * nn;
    for (let j = Math.floor(f) - 1; j <= Math.floor(f) + 1; j++)
      txt(list[((j % nn) + nn) % nn], x0, p0.y + (j - f) * h, { ...p0.o, size, fill: K.lab, parent: g, transient: true });
  };
  for (const [d, u] of Object.entries(picked)) if (u < PA.reel) reel(d, u);
  const shown = L.filter(p => p.kind[0] === "D" ? picked[p.kind] >= PA.reel : fed[p.j]);
  aBoxes(shown);
  shown.forEach(p => txt(p.s, p.x, p.y, { ...p.o, size: p.size, fill: p.kind[0] === "D" ? K.sig : K.w, grp: "answer" }));
  if (pr && t >= t0 && pr.n) aBars(L, [[pr.first, pr.n]], K.mark);                     // riding in the prompt call
  aBars(L, calls.slice(0, n).map(cl => [cl.first, cl.n, cl.d ? null : cl.pick ? K.sig : null]), K.w);
  aBars(L, calls.slice(0, n).filter(cl => cl.d).map(cl => [cl.d[0], cl.d[1], K.sig]), K.w);   // the pick's part
  if (tl && t >= tt) aNoCall(L, tl.first, tl.n);
  // the legend: a bar is one call; the signal colour is what the model picks
  rect(72, Y.cap - 22, 56, PA.bar, { fill: K.w, floor: "legend" });
  ktxt(c.leg_fixed, 148, Y.cap, TY.cap);
  const x2 = 148 + adv(c.leg_fixed, 44, TY.cap) + 64;
  rect(x2, Y.cap - 30, 28, 28, { fill: K.sig, floor: "legend" });
  ktxt(c.leg_dec, x2 + 44, Y.cap, TY.cap);
  if (pr) {             // the second row: the prompt call's bar and the outline of no call
    rect(72, Y.foot - 22, 56, PA.bar, { fill: K.mark, floor: "legend" });
    ktxt(c.leg_lead, 148, Y.foot, TY.cap);
    const x3 = 148 + adv(c.leg_lead, 44, TY.cap) + 64;
    rect(x3, Y.foot - 22, 56, PA.bar, { stroke: K.lab, sw: 3 });
    ktxt(c.leg_none, x3 + 76, Y.foot, TY.cap);
  }
  if (t >= bt(S, A.same)) c.a_jp_same.forEach((s_, j) => ktxt(s_, 72, PA.spotY - 56 + j * 56, TY.cap));     // the same text as plain's calls wrote
};

// ---- A DECISION: the question's options, the pick and its percentage (the saved body's); the JSON line completes -----
SCN.adec = (t, S) => {
  aBlack();
  const c = D.copy, pick = c.dn_pick;
  ktxt(c.dn_head, 72, Y.label, TY.label);
  const ny = c.answer.length, qy = Y.head + (ny - 1) * 68 + 140;    // the question's row under the JSON's lines
  ktxt(c.rq_q1, 72, qy, aTy(c.rq_q1), { fill: K.lab });
  let x = 72 + adv(c.rq_q1, 44, aTy(c.rq_q1)) + 36;
  for (const s of c.options1) {         // the options as the request showed them, the pick's in the signal colour
    const on_ = s === pick, o = aTy(s), w = adv(s, 44, o);
    rect(x, qy - 48, w + 36, 68, { stroke: on_ ? K.sig : K.mark, sw: on_ ? 5 : 3 });
    ktxt(s, x + 18, qy, o, { fill: on_ ? K.sig : K.lab });
    x += w + 36 + 18;
  }
  const pf = { ...TY.pick, size: 96 }, py = qy + 200;
  ktxt(pick, 72, py, pf);
  ktxt(c.dn_pct, 72 + adv(pick, 96, pf) + 32, py, TY.fig, { size: 120, fill: K.sig });
  ktxt(c.a_dn_cap, 72, Y.cap, TY.cap);
  if (D.draft_body) stampBox(c.dn_stamp, 540, py + 120, -2);
  // the lines last (a string drawn twice keeps its n-th order): what was fed from the cut, the picks a beat on; a
  // question a line, the second and later indented by the space the program writes there
  const kj = arrive(t, bt(S, D.a.dn.json), "cut");
  const size = 56, lines = c.answer.map((line, li) => (li ? [["F", " ", "mono"]] : []).concat(line));
  const wmax = Math.max(...lines.map(ln => ln.reduce((a, [, s, f]) => a + adv(s, size, aFace(f)), 0)));
  const sc = Math.min(1, 936 / wmax);
  let seen = false;
  lines.forEach((line, li) => {
    let xj = 72;
    line.forEach(([kind, s, f]) => {
      const o = { ...aFace(f), size: size * sc };
      if (kind === "D1") seen = true;
      if ((!seen || kj) && s.trim()) txt(s, xj, Y.head + li * 68, { ...o, fill: kind === "D1" ? K.sig : K.w, grp: "json" });
      xj += adv(s, size * sc, o);
    });
  });
};
