/**
 * Token value grammar, mirroring `backend/app/themes/tokens.py`. A theme may hold only colours,
 * lengths, numbers and enumerated words: never CSS, URLs or script. The server enforces the same
 * rules; the studio checks first so a bad value is caught while typing.
 */
import { isLiteralColour, resolveColour, varTarget } from "./colour"
import { COLOUR_TOKEN_NAMES, FONT_FAMILIES, TOKEN_SPEC } from "./spec"

const NUM = String.raw`[+-]?(?:\d+(?:\.\d*)?|\.\d+)`
const LENGTH = new RegExp(String.raw`^(${NUM})(px)?$`)
const TRACK = new RegExp(String.raw`^(${NUM})em$`)
const FACTOR = new RegExp(String.raw`^(${NUM})$`)
const WEIGHT = /^[1-9]\d{2}$/
const SHADOW_LEN = new RegExp(String.raw`^${NUM}(?:px|em|rem)?$`)
const TOKEN_NAME = /^[a-z][a-z0-9-]{0,40}$/
// eslint-disable-next-line no-control-regex
const CONTROL = /[\x00-\x1f\x7f]/

/** Engine defaults for optional colour tokens that may be referenced. */
const STYLE_COLOUR_DEFAULTS: Record<string, string> = {
  "panel-border": "var(--t-border)",
  "elev-top-color": "var(--t-panel-border)",
}

const inRange = (raw: string, lo?: number, hi?: number) => {
  const x = Number(raw)
  return (
    Number.isFinite(x) &&
    (lo === undefined || x >= lo) &&
    (hi === undefined || x <= hi)
  )
}

export function validColour(value: string): boolean {
  if (value.includes("var(")) {
    const t = varTarget(value)
    return t !== null && COLOUR_TOKEN_NAMES.has(t)
  }
  return isLiteralColour(value)
}

function splitLayers(value: string): string[] | null {
  const out: string[] = []
  let depth = 0
  let cur = ""
  for (const ch of value) {
    if (ch === "(") depth++
    else if (ch === ")" && --depth < 0) return null
    if (ch === "," && depth === 0) {
      out.push(cur.trim())
      cur = ""
    } else cur += ch
  }
  out.push(cur.trim())
  return out.filter(Boolean)
}

export function validShadow(value: string): boolean {
  const v = value.trim()
  if (v === "none") return true
  const layers = splitLayers(v)
  if (!layers || !layers.length || layers.length > 4) return false
  return layers.every((layer) => {
    let parts = layer.split(/\s+/)
    if (parts[0] === "inset") parts = parts.slice(1)
    let i = 0
    while (i < parts.length && SHADOW_LEN.test(parts[i])) i++
    const colour = parts.slice(i).join(" ")
    return i >= 2 && i <= 4 && !!colour && validColour(colour)
  })
}

/** Is `value` allowed for token `name`? Unknown names accept a colour or a plain length. */
export function validTokenValue(name: string, value: unknown): boolean {
  if (typeof value !== "string" || !value.trim()) return false
  if (value.length > TOKEN_SPEC.limits.value_length || CONTROL.test(value))
    return false
  const v = value.trim()
  const s = TOKEN_SPEC.tokens[name]
  if (!s) return validColour(v) || LENGTH.test(v)
  switch (s.type) {
    case "colour":
      return validColour(v)
    case "shadow":
      return validShadow(v)
    case "enum":
      return (s.values ?? []).includes(v)
    case "weight":
      return WEIGHT.test(v) && inRange(v, s.min, s.max)
    case "track": {
      const m = TRACK.exec(v)
      return !!m && inRange(m[1], s.min, s.max)
    }
    case "factor":
      return FACTOR.test(v) && inRange(v, s.min, s.max)
    case "length": {
      const m = LENGTH.exec(v)
      return !!m && inRange(m[1], s.min, s.max)
    }
  }
  return false
}

export type ThemeIssue = { path: string; message: string }

/** Every problem with a draft theme body, in the server's terms. Empty means it will save. */
export function themeIssues(t: {
  name: string
  fonts: Record<string, string | null | undefined>
  radius: number
  light: Record<string, string>
  dark: Record<string, string>
  chart: string[]
  score: Record<string, string>
}): ThemeIssue[] {
  const issues: ThemeIssue[] = []
  if (!t.name.trim() || t.name.length > 80 || CONTROL.test(t.name))
    issues.push({
      path: "name",
      message: "Give it a name (up to 80 characters).",
    })
  for (const [slot, family] of Object.entries(t.fonts))
    if (family && !FONT_FAMILIES.includes(family))
      issues.push({
        path: `fonts.${slot}`,
        message: `${family} is not a bundled font.`,
      })
  if (!Number.isInteger(t.radius) || t.radius < 0 || t.radius > 32)
    issues.push({ path: "radius", message: "Radius is 0 to 32 px." })
  for (const mode of ["light", "dark"] as const) {
    const map = t[mode]
    for (const [name, s] of Object.entries(TOKEN_SPEC.tokens))
      if (s.required && !map[name])
        issues.push({ path: `${mode}.${name}`, message: "Required." })
    for (const [name, value] of Object.entries(map)) {
      if (!TOKEN_NAME.test(name))
        issues.push({ path: `${mode}.${name}`, message: "Invalid token name." })
      else if (!validTokenValue(name, value))
        issues.push({
          path: `${mode}.${name}`,
          message: "Not an allowed value.",
        })
      else if (varTarget(value) !== null) {
        try {
          resolveColour(value, { ...STYLE_COLOUR_DEFAULTS, ...map })
        } catch {
          issues.push({
            path: `${mode}.${name}`,
            message: "Refers to a token that does not resolve.",
          })
        }
      }
    }
  }
  if (!t.chart.length || t.chart.length > TOKEN_SPEC.limits.chart_colours)
    issues.push({ path: "chart", message: "1 to 12 chart colours." })
  t.chart.forEach((c, i) => {
    if (c.includes("var(") || !isLiteralColour(c))
      issues.push({ path: `chart.${i}`, message: "Not a colour." })
  })
  for (const [k, c] of Object.entries(t.score))
    if (c.includes("var(") || !isLiteralColour(c))
      issues.push({ path: `score.${k}`, message: "Not a colour." })
  return issues
}
