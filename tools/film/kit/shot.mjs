// shot.mjs: the screenshot tool of the dsh task (the agent calls it as `shot index.html 0`) and the kit's page capture.
// A page at a CSS viewport of 1280x720, deviceScaleFactor 1, at a given second of its own clock: Playwright's fake clock
// (Date, timers, requestAnimationFrame, performance.now) installed at 0 and run forward t s, every CSS/Web animation paused
// at t, and an SVG's SMIL timeline set to t. So a shot at t is the same picture however long the machine took.
//   node shot.mjs <page.html> <seconds> [out.png]           one shot; prints the PNG path and the page's console errors
//   node shot.mjs <page.html> --loop <fps> <n> <outdir>      n frames at t = k / fps (f_000.png ...), for the film's loop
// PW names a directory holding node_modules/playwright-core (default /home/user/clipdsh/pw). Network: the page gets none
// (every request outside file:// is aborted and printed as an error), as the task asks for one file with nothing external.
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const PW = process.env.PW || '/home/user/clipdsh/pw'
const { chromium } = createRequire(path.join(PW, 'x.js'))('playwright-core')
const [html, a2, ...rest] = process.argv.slice(2)
if (!html || a2 === undefined) {
  console.error('usage: shot <page.html> <seconds> [out.png] | shot <page.html> --loop <fps> <n> <outdir>')
  process.exit(64)
}
const file = path.resolve(html)
if (!fs.existsSync(file)) {
  console.error(`shot: ${html}: no such file`)
  process.exit(66)
}
const loop = a2 === '--loop'
const times = loop ? Array.from({ length: Number(rest[1]) }, (_, k) => k / Number(rest[0])) : [Number(a2)]
if (times.some((t) => !Number.isFinite(t) || t < 0 || t > 600)) {
  console.error('shot: seconds is a number from 0 to 600')
  process.exit(64)
}
const outs = loop
  ? times.map((_, k) => path.join(rest[2], `f_${String(k).padStart(3, '0')}.png`))
  : [path.resolve(rest[0] || `shot-${a2}.png`)]
if (loop) fs.mkdirSync(rest[2], { recursive: true })

const browser = await chromium.launch({ headless: true })
const errors = []
// A loop is one page whose clock runs forward from frame to frame: a fresh page a frame would restart the page at every
// frame, and a page that draws from Math.random (a ball's first direction) would show a different game in each frame.
if (loop) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 })
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`console.error: ${m.text()}`) })
  page.on('pageerror', (e) => errors.push(`pageerror: ${String(e.message ?? e)}`))
  await page.route(/^(?!file:)/, (r) => { errors.push(`blocked request: ${r.request().url()}`); r.abort() })
  if (!page.clock) { console.error('shot: --loop needs Playwright\'s page.clock'); process.exit(69) }
  await page.clock.install({ time: 0 })
  await page.goto('file://' + file, { waitUntil: 'load', timeout: 30000 })
  let now = 0
  for (let i = 0; i < times.length; i++) {
    const ms = Math.round(times[i] * 1000)
    await page.clock.runFor(ms - now)
    now = ms
    await page.evaluate((ms) => {
      for (const a of document.getAnimations()) { a.pause(); a.currentTime = ms }
      for (const s of document.querySelectorAll('svg')) if (s.pauseAnimations) { s.pauseAnimations(); s.setCurrentTime(ms / 1000) }
    }, ms)
    await page.screenshot({ path: outs[i], type: 'png' })
  }
  await page.close()
}
for (let i = 0; i < (loop ? 0 : times.length); i++) {
  const t = times[i]
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 })
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`console.error: ${m.text()}`) })
  page.on('pageerror', (e) => errors.push(`pageerror: ${String(e.message ?? e)}`))
  await page.route(/^(?!file:)/, (r) => { errors.push(`blocked request: ${r.request().url()}`); r.abort() })
  if (page.clock) await page.clock.install({ time: 0 })
  await page.goto('file://' + file, { waitUntil: 'load', timeout: 30000 })
  if (page.clock) await page.clock.runFor(Math.round(t * 1000))
  await page.evaluate((ms) => {
    for (const a of document.getAnimations()) { a.pause(); a.currentTime = ms }
    for (const s of document.querySelectorAll('svg')) if (s.pauseAnimations) { s.pauseAnimations(); s.setCurrentTime(ms / 1000) }
  }, t * 1000)
  await page.screenshot({ path: outs[i], type: 'png' })
  await page.close()
}
await browser.close()
if (!loop) console.log(`saved ${outs[0]} (1280x720, t = ${times[0]} s)`)
else console.log(`saved ${outs.length} frames in ${rest[2]} (1280x720, ${rest[0]} fps)`)
const uniq = [...new Set(errors)]
console.log(uniq.length ? `console errors (${uniq.length}):\n` + uniq.join('\n') : 'console errors: none')
