// summarize.mjs OUT: the film's JSON (OUT/film.json) from record.sh's run directory. Per model: the requests dsh sent to
// the chat endpoint (from the proxy's index.jsonl: each request's prompt, cached and completion tokens as the server's
// usage/timings reported them, its images, its tool calls), the task's wall (dsh's start to its exit, epoch ms taken by
// record.sh around the fenced run), dsh's exit code, the fence's findings, and the page: index.html, page.png (t = 1 s),
// loop/f_NNN.png. Exit 65 names a run the film cannot show (no request, a request without usage, no page, a fence finding).
// The schema is promo0315v2.dsh/1; dsh-parse.mjs in the film reads it.
import fs from 'node:fs'
import path from 'node:path'

const OUT = process.argv[2]
if (!OUT) { console.error('usage: node summarize.mjs OUT'); process.exit(64) }
const kit = JSON.parse(fs.readFileSync(path.join(OUT, 'meta.json'), 'utf8'))
const fail = (why) => { console.error('summarize: ' + why); process.exitCode = 65 }
const runs = []
for (const id of kit.models) {
  const dir = path.join(OUT, id)
  const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'))
  const idx = path.join(dir, 'task-proxy', 'index.jsonl')
  const recs = fs.existsSync(idx) ? fs.readFileSync(idx, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []
  const chat = recs.filter((r) => r.method === 'POST' && /\/chat\/completions/.test(r.url)).sort((a, b) => a.n - b.n)
  const reqs = chat.map((r) => {
    const u = r.usage ?? {}, t = r.timings ?? {}
    const prompt = u.prompt_tokens ?? (t.prompt_n !== undefined ? t.prompt_n + (t.cache_n ?? 0) : null)
    const cached = u.prompt_tokens_details?.cached_tokens ?? t.cache_n ?? null
    const out = u.completion_tokens ?? t.predicted_n ?? null
    return {
      n: r.n, status: r.status ?? null, t_start: r.t_start, t_end: r.t_end ?? null, images: r.images ?? 0,
      prompt_tokens: prompt, cached_tokens: cached, completion_tokens: out,
      predicted_per_second: t.predicted_per_second ?? null, finish: r.finish_reason ?? null,
      tools: r.tools ?? [], aborted: !!r.aborted, error: r.error ?? null,
    }
  })
  if (!reqs.length) fail(`${id}: the proxy logged no chat request`)
  for (const q of reqs) if (q.status === 200 && (q.prompt_tokens === null || q.completion_tokens === null)) fail(`${id}: request ${q.n} has no usage or timings`)
  const ok = reqs.filter((q) => q.status === 200 && !q.aborted)
  const sum = (k) => ok.reduce((s, q) => s + (q[k] ?? 0), 0)
  const tools = ok.flatMap((q) => q.tools)
  const page = fs.existsSync(path.join(dir, 'work', 'index.html'))
  if (!page) fail(`${id}: the workspace holds no index.html`)
  const loop = fs.existsSync(path.join(dir, 'loop')) ? fs.readdirSync(path.join(dir, 'loop')).filter((f) => /^f_\d{3}\.png$/.test(f)).sort() : []
  if (page && loop.length !== kit.loop.n) fail(`${id}: ${loop.length} loop frames, want ${kit.loop.n}`)
  if (meta.fence.findings.length) fail(`${id}: fence findings: ${meta.fence.findings.join('; ')}`)
  runs.push({
    id, model: meta.name, file: meta.file, mmproj: meta.mmproj, ctx: meta.ctx,
    requests: ok.length, requests_failed: reqs.length - ok.length,
    tokens_in: sum('prompt_tokens'), tokens_cached: sum('cached_tokens'), tokens_out: sum('completion_tokens'),
    images_sent_last: ok.length ? ok[ok.length - 1].images : 0,
    read_image_calls: tools.filter((t) => t.name === 'read_image').length,
    shot_calls: tools.filter((t) => typeof t.command === 'string' && /(^|[\s;&|])shot\s/.test(t.command)).length,
    wall_s: (meta.t_task_end - meta.t_task_start) / 1000, dsh_rc: meta.dsh_rc, capped: meta.capped,
    fence: meta.fence,
    page: page ? `${id}/work/index.html` : null, still: page ? `${id}/page.png` : null,
    loop: { dir: `${id}/loop`, fps: kit.loop.fps, n: loop.length, w: 1280, h: 720 },
    requests_log: reqs,
  })
}
const film = {
  schema: 'promo0315v2.dsh/1', standin: false, recorded: kit.recorded, prompt: kit.prompt, dsh_version: kit.dsh_version,
  bloomery: kit.bloomery, card: kit.card, host: kit.host, settings: kit.settings, runs,
}
fs.writeFileSync(path.join(OUT, 'film.json'), JSON.stringify(film, null, 1))
for (const r of runs) {
  console.log(`${r.model}: ${r.requests} requests (${r.requests_failed} failed), in ${r.tokens_in} (cached ${r.tokens_cached}), out ${r.tokens_out}, wall ${r.wall_s.toFixed(1)} s, dsh rc ${r.dsh_rc}${r.capped ? ' (capped)' : ''}, read_image ${r.read_image_calls}, shot ${r.shot_calls}, loop ${r.loop.n} frames`)
}
console.log(`film.json: ${path.join(OUT, 'film.json')}`)
