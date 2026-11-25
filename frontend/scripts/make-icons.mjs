#!/usr/bin/env node
// Render the PWA PNG icons from public/icon.svg and public/icon-maskable.svg.
// Usage: npm run icons
import { readFileSync } from "node:fs"
import { launch } from "./browser.mjs"

const svg = readFileSync("public/icon.svg", "utf8")
const maskable = readFileSync("public/icon-maskable.svg", "utf8")

const browser = await launch()
const page = await browser.newPage()
async function render(markup, size, out, pad = 0) {
  await page.setViewportSize({ width: size, height: size })
  await page.setContent(
    `<html><body style="margin:0;background:transparent"><div style="width:${size}px;height:${size}px;padding:${pad}px;box-sizing:border-box">${markup.replace("<svg ", '<svg width="100%" height="100%" ')}</div></body></html>`
  )
  await page.screenshot({ path: out, omitBackground: true })
  console.log("wrote", out)
}
await render(svg, 192, "public/icon-192.png")
await render(svg, 512, "public/icon-512.png")
await render(svg, 180, "public/apple-touch-icon.png")
await render(maskable, 512, "public/icon-maskable-512.png")
await browser.close()
