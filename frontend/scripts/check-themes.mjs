#!/usr/bin/env node
// Contrast check over the built-in theme JSON (DESIGN 10.5).
// Fails when any text token sits on its background below 4.5:1 (WCAG AA),
// or below 7:1 (AAA) for themes that declare themselves high contrast.
// Usage: node scripts/check-themes.mjs [dir-or-file ...]
import { readFileSync, readdirSync, statSync } from "node:fs"
import { join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const AA = 4.5
const AAA = 7

const REQUIRED = [
  "bg",
  "bg-sunken",
  "surface",
  "surface-2",
  "border",
  "border-strong",
  "text",
  "text-muted",
  "text-faint",
  "primary",
  "primary-ink",
  "primary-fg",
  "primary-soft",
  "accent",
  "accent-ink",
  "accent-soft",
  "good",
  "good-soft",
  "warn",
  "warn-soft",
  "danger",
  "danger-soft",
  "info",
  "info-soft",
  "ring",
  "score-low",
  "score-mid",
  "score-high",
]

const GROUNDS = ["bg", "bg-sunken", "surface", "surface-2"]

/** [foreground, background] pairs as used by the components. */
export const PAIRS = [
  ...["text", "text-muted", "text-faint"].flatMap((t) =>
    GROUNDS.map((g) => [t, g])
  ),
  ...["primary-ink", "accent-ink"].flatMap((t) =>
    ["bg", "surface"].map((g) => [t, g])
  ),
  ["primary-ink", "primary-soft"],
  ["text", "primary-soft"],
  ["primary-fg", "primary"],
  ["accent-ink", "accent-soft"],
  ["good", "good-soft"],
  ["warn", "warn-soft"],
  ["danger", "danger-soft"],
  ["info", "info-soft"],
  ...["good", "warn", "danger", "info"].flatMap((t) =>
    ["bg", "surface"].map((g) => [t, g])
  ),
]

export function parseColor(value) {
  const v = String(value).trim()
  let m = v.match(/^#([0-9a-f]{3,8})$/i)
  if (m) {
    let h = m[1]
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("")
    const n = (i) => parseInt(h.slice(i, i + 2), 16)
    return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 }
  }
  m = v.match(/^rgba?\(([^)]+)\)$/i)
  if (m) {
    const p = m[1]
      .split(/[\s,/]+/)
      .filter(Boolean)
      .map(Number)
    return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 }
  }
  return null
}

function luminance({ r, g, b }) {
  const f = (c) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

export function contrast(a, b) {
  const la = luminance(a)
  const lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

export function checkTheme(theme) {
  const problems = []
  const min =
    theme.id === "high-contrast" || theme.contrast === "aaa" ? AAA : AA
  for (const mode of ["light", "dark"]) {
    const tokens = theme[mode]
    if (!tokens) {
      problems.push(`${mode}: missing token map`)
      continue
    }
    for (const k of REQUIRED)
      if (!(k in tokens)) problems.push(`${mode}: missing token "${k}"`)
    for (const [fg, bg] of PAIRS) {
      const a = parseColor(tokens[fg])
      const b = parseColor(tokens[bg])
      if (!a || !b || a.a < 1 || b.a < 1) continue
      const ratio = contrast(a, b)
      if (ratio < min) {
        problems.push(
          `${mode}: ${fg} on ${bg} is ${ratio.toFixed(2)}:1 (needs ${min}:1)`
        )
      }
    }
  }
  return problems
}

function collect(target) {
  const st = statSync(target)
  if (st.isFile()) return [target]
  return readdirSync(target)
    .filter((f) => f.endsWith(".json"))
    .map((f) => join(target, f))
}

const isMain =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (isMain) {
  const targets = process.argv.slice(2)
  const files = (targets.length ? targets : ["src/themes/builtin"]).flatMap(
    collect
  )
  let failed = 0
  for (const file of files) {
    const theme = JSON.parse(readFileSync(file, "utf8"))
    const problems = checkTheme(theme)
    if (problems.length) {
      failed++
      console.error(`x ${theme.name ?? file}`)
      for (const p of problems) console.error(`    ${p}`)
    } else {
      console.log(`ok ${theme.name} (light and dark)`)
    }
  }
  if (failed) {
    console.error(`\n${failed} theme(s) fail the contrast check.`)
    process.exit(1)
  }
  console.log(`\nAll ${files.length} themes pass.`)
}
