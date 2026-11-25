#!/usr/bin/env node
// Screenshot key screens against the mock dev server (npm run dev:mock).
// Usage: node scripts/screenshots.mjs [baseUrl] [outDir]
import { mkdirSync } from "node:fs"
import { join } from "node:path"
import { launch } from "./browser.mjs"

const base = process.argv[2] ?? "http://localhost:5173"
const out = process.argv[3] ?? "screenshots"
mkdirSync(out, { recursive: true })

const SHOTS = [
  { theme: "copperbelt", mode: "light" },
  { theme: "copperbelt", mode: "dark" },
  { theme: "midnight-ledger", mode: "dark" },
]
const PAGES = [
  { name: "today", path: "/today", height: 1000 },
  { name: "appearance", path: "/settings/appearance", height: 1400 },
  { name: "components", path: "/dev/components", height: 2600 },
]

const browser = await launch()

async function setAppearance(page, theme, mode) {
  await page.evaluate(
    async ({ theme, mode }) => {
      const r = await fetch("/api/settings/appearance")
      const a = await r.json()
      await fetch("/api/settings/appearance", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...a, theme_id: theme, mode }),
      })
    },
    { theme, mode }
  )
}

for (const shot of SHOTS) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: shot.mode,
  })
  const page = await ctx.newPage()
  await page.goto(`${base}/today?mock=signed-in`, { waitUntil: "networkidle" })
  await setAppearance(page, shot.theme, shot.mode)
  for (const p of PAGES) {
    await page.setViewportSize({ width: 1440, height: p.height })
    await page.goto(base + p.path, { waitUntil: "networkidle" })
    await page.waitForTimeout(900)
    const file = join(out, `${p.name}-${shot.theme}-${shot.mode}.png`)
    await page.screenshot({ path: file })
    console.log("wrote", file)
  }
  await ctx.close()
}

// Phone width
const phone = await browser.newContext({
  viewport: { width: 400, height: 860 },
  deviceScaleFactor: 2,
  colorScheme: "light",
  hasTouch: true,
  isMobile: true,
})
const pp = await phone.newPage()
await pp.goto(`${base}/today?mock=signed-in`, { waitUntil: "networkidle" })
await setAppearance(pp, "copperbelt", "light")
for (const p of [
  { name: "today", path: "/today" },
  { name: "appearance", path: "/settings/appearance" },
  { name: "matches", path: "/matches" },
]) {
  await pp.goto(base + p.path, { waitUntil: "networkidle" })
  await pp.waitForTimeout(900)
  const file = join(out, `${p.name}-phone-400.png`)
  await pp.screenshot({ path: file })
  console.log("wrote", file)
}
// Sign-in screen
await pp.goto(`${base}/sign-in?mock=signed-out`, { waitUntil: "networkidle" })
await pp.waitForTimeout(600)
await pp.screenshot({ path: join(out, "sign-in-phone-400.png") })
const desk = await browser.newContext({
  viewport: { width: 1440, height: 900 },
})
const dp = await desk.newPage()
await dp.goto(`${base}/setup?mock=fresh`, { waitUntil: "networkidle" })
await dp.waitForTimeout(700)
await dp.screenshot({ path: join(out, "setup-desktop.png") })
console.log("wrote auth screens")

await browser.close()
