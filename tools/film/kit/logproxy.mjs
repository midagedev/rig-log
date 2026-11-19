// logproxy.mjs: a loopback logging proxy between dsh and bloomery-serve (after clipdsh1's, without its V4.1 DSML shim:
// the 0.3.15 server parses both models' tool calls itself). It forwards bytes as they come, so a stream's pacing is the
// server's, and keeps, for request n: req-NNN.json (the body dsh sent), resp-NNN.sse (the server's bytes) and one line
// in index.jsonl: epoch-ms times (start, first byte, end), sizes, the request's shape (messages, images, tools), the
// tool calls the answer made (name and, for bash, its command's first 200 characters), and the stream's usage and
// timings objects as the server sent them.
// With --effort-none, a chat request with no top-level `reasoning_effort` gets "none" added before it is forwarded (the
// kit's one setting for both models: thinking off); req-NNN.json keeps dsh's own body, the index line says it was added.
//   node logproxy.mjs <listenPort> <targetPort> <outDir> [--effort-none]
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'

const [listenPort, targetPort, outDir] = [Number(process.argv[2]), Number(process.argv[3]), process.argv[4]]
const effortNone = process.argv[5] === '--effort-none'
if (!listenPort || !targetPort || !outDir) {
  console.error('usage: node logproxy.mjs <listenPort> <targetPort> <outDir>')
  process.exit(64)
}
fs.mkdirSync(outDir, { recursive: true })
fs.writeFileSync(path.join(outDir, 'proxy.pid'), String(process.pid))
let n = 0
const pad = (k) => String(k).padStart(3, '0')

function shape(body) {
  let j
  try { j = JSON.parse(body) } catch { return { parse: 'not json' } }
  const m = Array.isArray(j.messages) ? j.messages : []
  const roles = {}
  let images = 0
  for (const x of m) {
    roles[x.role] = (roles[x.role] ?? 0) + 1
    if (Array.isArray(x.content)) images += x.content.filter((p) => p && (p.type === 'image_url' || p.type === 'image')).length
  }
  return {
    model: j.model, stream: j.stream, n_messages: m.length, roles, images,
    n_tools: Array.isArray(j.tools) ? j.tools.length : 0,
    max_tokens: j.max_tokens ?? j.max_completion_tokens ?? null,
    kwargs: j.chat_template_kwargs ?? null, reasoning_effort: j.reasoning_effort ?? null,
  }
}

const server = http.createServer((req, res) => {
  const k = ++n
  const t0 = Date.now()
  const chunks = []
  req.on('data', (c) => chunks.push(c))
  req.on('end', () => {
    const body = Buffer.concat(chunks)
    if (body.length > 0) fs.writeFileSync(path.join(outDir, `req-${pad(k)}.json`), body)
    const rec = { n: k, method: req.method, url: req.url, t_start: t0, req_bytes: body.length, ...shape(body.toString('utf8')) }
    let fwd = body
    if (effortNone && req.method === 'POST' && /\/chat\/completions/.test(req.url)) {
      try {
        const j = JSON.parse(body.toString('utf8'))
        if (j.reasoning_effort === undefined || j.reasoning_effort === null) {
          j.reasoning_effort = 'none'
          fwd = Buffer.from(JSON.stringify(j))
          rec.added_effort_none = true
        }
      } catch {}
    }
    const headers = { ...req.headers, host: `127.0.0.1:${targetPort}`, 'content-length': String(fwd.length) }
    delete headers['transfer-encoding']
    let logged = false
    const log = () => { if (!logged) { logged = true; fs.appendFileSync(path.join(outDir, 'index.jsonl'), JSON.stringify(rec) + '\n') } }
    const up = http.request({ host: '127.0.0.1', port: targetPort, path: req.url, method: req.method, headers }, (ur) => {
      rec.status = ur.statusCode
      res.writeHead(ur.statusCode, ur.headers)
      const out = fs.createWriteStream(path.join(outDir, `resp-${pad(k)}.sse`))
      const calls = new Map() // tool call index -> { name, args }
      let buf = ''
      let bytes = 0
      ur.on('data', (c) => {
        if (rec.t_first_byte === undefined) rec.t_first_byte = Date.now()
        bytes += c.length
        out.write(c)
        res.write(c)
        buf += c.toString('utf8')
        let i
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const ev = buf.slice(0, i)
          buf = buf.slice(i + 2)
          const line = ev.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          const data = line.slice(5).trim()
          if (data === '[DONE]') continue
          let o
          try { o = JSON.parse(data) } catch { continue }
          const d = o.choices?.[0]?.delta
          for (const tc of d?.tool_calls ?? []) {
            const c0 = calls.get(tc.index ?? 0) ?? { name: '', args: '' }
            if (tc.function?.name) c0.name += tc.function.name
            if (tc.function?.arguments) c0.args += tc.function.arguments
            calls.set(tc.index ?? 0, c0)
          }
          if (d?.reasoning_content) rec.reasoning_chunks = (rec.reasoning_chunks ?? 0) + 1
          if (d?.content) rec.content_chunks = (rec.content_chunks ?? 0) + 1
          if (o.choices?.[0]?.finish_reason) rec.finish_reason = o.choices[0].finish_reason
          if (o.usage) rec.usage = o.usage
          if (o.timings) rec.timings = o.timings
        }
      })
      ur.on('end', () => {
        rec.t_end = Date.now()
        rec.resp_bytes = bytes
        rec.tools = [...calls.values()].map((c) => {
          let cmd = null
          try { const a = JSON.parse(c.args); cmd = typeof a.command === 'string' ? a.command.slice(0, 200) : null } catch {}
          return cmd === null ? { name: c.name } : { name: c.name, command: cmd }
        })
        res.end()
        out.end(() => {
          if (bytes > 0 && !String(ur.headers['content-type'] ?? '').includes('event-stream')) {
            const head = fs.readFileSync(path.join(outDir, `resp-${pad(k)}.sse`), 'utf8')
            rec.resp_head = head.slice(0, 600)
            try { const j = JSON.parse(head); if (j.usage) rec.usage = j.usage; if (j.timings) rec.timings = j.timings } catch {}
          }
          log()
        })
      })
    })
    up.on('error', (e) => {
      rec.t_end = Date.now()
      rec.error = String(e)
      log()
      if (!res.headersSent) res.writeHead(502, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ error: { message: `proxy: ${e}` } }))
    })
    res.on('close', () => {
      if (res.writableEnded) return
      rec.aborted = true
      rec.t_end = Date.now()
      log()
      up.destroy()
    })
    up.end(fwd)
  })
})
server.listen(listenPort, '127.0.0.1', () => console.error(`logproxy ${listenPort} -> ${targetPort}, out ${outDir}`))
