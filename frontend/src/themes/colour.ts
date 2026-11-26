/**
 * Colour grammar and maths for theme tokens: strict parsing (the only colour syntaxes a theme may
 * store), OKLCH/OKLab conversion, alpha compositing, WCAG 2 contrast and hex output.
 * Mirrors `backend/app/themes/colour.py`; both are tested against the same known pairs.
 */

/** sRGB channels 0..1 and alpha 0..1. */
export type RGBA = readonly [number, number, number, number]
export type OKLCH = { l: number; c: number; h: number }
export type OKLab = { l: number; a: number; b: number }

const NUM = String.raw`[+-]?(?:\d+(?:\.\d*)?|\.\d+)`
const HEX = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/
const RGB_COMMA = new RegExp(
  String.raw`^rgba?\(\s*(${NUM})(%?)\s*,\s*(${NUM})(%?)\s*,\s*(${NUM})(%?)\s*(?:,\s*(${NUM})(%?)\s*)?\)$`,
  "i"
)
const RGB_SPACE = new RegExp(
  String.raw`^rgba?\(\s*(${NUM})(%?)\s+(${NUM})(%?)\s+(${NUM})(%?)\s*(?:/\s*(${NUM})(%?)\s*)?\)$`,
  "i"
)
const HSL = new RegExp(
  String.raw`^hsla?\(\s*(${NUM})(?:deg)?\s*[,\s]\s*(${NUM})%\s*[,\s]\s*(${NUM})%\s*(?:[,/]\s*(${NUM})(%?)\s*)?\)$`,
  "i"
)
const OKLCH_RE = new RegExp(
  String.raw`^oklch\(\s*(${NUM})(%?)\s+(${NUM})\s+(${NUM})(?:deg)?\s*(?:/\s*(${NUM})(%?)\s*)?\)$`,
  "i"
)
const VAR = /^var\(--t-([a-z][a-z0-9-]{0,40})\)$/

export class ColourError extends Error {}

const clamp = (x: number, lo = 0, hi = 1) => (x < lo ? lo : x > hi ? hi : x)

function alpha(raw: string | undefined, pct: string | undefined): number {
  if (raw === undefined) return 1
  return clamp(pct ? Number(raw) / 100 : Number(raw))
}

/** The token a `var(--t-<name>)` value points at, else null. */
export function varTarget(value: string): string | null {
  const m = VAR.exec(value.trim())
  return m ? m[1] : null
}

/** Parse a literal colour (not a `var()`). Throws ColourError for anything else. */
export function parseLiteral(value: string): RGBA {
  const v = value.trim()
  if (v.toLowerCase() === "transparent") return [0, 0, 0, 0]
  if (HEX.test(v)) {
    let h = v.slice(1)
    if (h.length <= 4)
      h = h
        .split("")
        .map((c) => c + c)
        .join("")
    const ch: number[] = []
    for (let i = 0; i < h.length; i += 2)
      ch.push(parseInt(h.slice(i, i + 2), 16) / 255)
    return [ch[0], ch[1], ch[2], ch.length === 4 ? ch[3] : 1]
  }
  const m = RGB_COMMA.exec(v) ?? RGB_SPACE.exec(v)
  if (m) {
    const c = [1, 3, 5].map((i) =>
      clamp(m[i + 1] ? Number(m[i]) / 100 : Number(m[i]) / 255)
    )
    return [c[0], c[1], c[2], alpha(m[7], m[8])]
  }
  const hm = HSL.exec(v)
  if (hm) {
    const h = ((Number(hm[1]) % 360) + 360) % 360
    const [r, g, b] = hslToRgb(
      h,
      clamp(Number(hm[2]) / 100),
      clamp(Number(hm[3]) / 100)
    )
    return [r, g, b, alpha(hm[4], hm[5])]
  }
  const om = OKLCH_RE.exec(v)
  if (om) {
    const l = om[2] ? Number(om[1]) / 100 : Number(om[1])
    const [r, g, b] = oklchToSrgb({
      l: clamp(l),
      c: Math.max(0, Number(om[3])),
      h: Number(om[4]),
    })
    return [r, g, b, alpha(om[5], om[6])]
  }
  throw new ColourError(`not a colour: ${value}`)
}

export function isLiteralColour(value: string): boolean {
  try {
    parseLiteral(value)
    return true
  } catch {
    return false
  }
}

/** Parse a token value, following `var(--t-x)` through the mode map (at most 4 hops). */
export function resolveColour(
  value: string,
  tokens: Record<string, string>,
  depth = 0
): RGBA {
  const target = varTarget(value)
  if (target === null) return parseLiteral(value)
  if (depth >= 4 || !(target in tokens))
    throw new ColourError(`unresolvable reference ${value}`)
  return resolveColour(tokens[target], tokens, depth + 1)
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const f = (n: number) => {
    const k = (n + h / 30) % 12
    const a = s * Math.min(l, 1 - l)
    return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))
  }
  return [f(0), f(8), f(4)]
}

const toLinear = (c: number) =>
  c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
const fromLinear = (c: number) =>
  c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055

/** OKLCH to linear sRGB, unclamped (for gamut checks). */
function oklchToLinear({ l, c, h }: OKLCH): [number, number, number] {
  const a = c * Math.cos((h * Math.PI) / 180)
  const b = c * Math.sin((h * Math.PI) / 180)
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b
  const s_ = l - 0.0894841775 * a - 1.291485548 * b
  const lc = l_ ** 3
  const mc = m_ ** 3
  const sc = s_ ** 3
  return [
    4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc,
    -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc,
    -0.0041960863 * lc - 0.7034186147 * mc + 1.707614701 * sc,
  ]
}

/** OKLCH to gamma-encoded sRGB, clamped to gamut. */
export function oklchToSrgb(c: OKLCH): [number, number, number] {
  const [r, g, b] = oklchToLinear(c)
  return [r, g, b].map((x) => clamp(fromLinear(clamp(x)))) as [
    number,
    number,
    number,
  ]
}

/** True when the OKLCH colour is inside the sRGB gamut (small tolerance). */
export function inGamut(c: OKLCH): boolean {
  return oklchToLinear(c).every((x) => x >= -1e-4 && x <= 1 + 1e-4)
}

/** OKLCH to sRGB with chroma reduced until it fits the gamut (keeps lightness and hue). */
export function oklchToSrgbMapped(c: OKLCH): [number, number, number] {
  if (inGamut(c)) return oklchToSrgb(c)
  let lo = 0
  let hi = c.c
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2
    if (inGamut({ ...c, c: mid })) lo = mid
    else hi = mid
  }
  return oklchToSrgb({ ...c, c: lo })
}

export function srgbToOklab(r: number, g: number, b: number): OKLab {
  const lr = toLinear(r)
  const lg = toLinear(g)
  const lb = toLinear(b)
  const l_ = Math.cbrt(
    0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb
  )
  const m_ = Math.cbrt(
    0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb
  )
  const s_ = Math.cbrt(
    0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb
  )
  return {
    l: 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_,
    a: 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_,
    b: 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_,
  }
}

export function srgbToOklch(r: number, g: number, b: number): OKLCH {
  const { l, a, b: bb } = srgbToOklab(r, g, b)
  const h = ((Math.atan2(bb, a) * 180) / Math.PI + 360) % 360
  return { l, c: Math.hypot(a, bb), h }
}

/** Euclidean distance in OKLab between two colours (alpha ignored). */
export function oklabDistance(x: RGBA, y: RGBA): number {
  const p = srgbToOklab(x[0], x[1], x[2])
  const q = srgbToOklab(y[0], y[1], y[2])
  return Math.hypot(p.l - q.l, p.a - q.a, p.b - q.b)
}

/** Composite `top` over `under` (source-over, straight alpha). */
export function over(top: RGBA, under: RGBA): RGBA {
  const a = top[3] + under[3] * (1 - top[3])
  if (a === 0) return [0, 0, 0, 0]
  const ch = (i: number) =>
    (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a
  return [ch(0), ch(1), ch(2), a]
}

export function luminance(c: RGBA): number {
  return (
    0.2126 * toLinear(c[0]) + 0.7152 * toLinear(c[1]) + 0.0722 * toLinear(c[2])
  )
}

/** WCAG 2 contrast ratio. `bg` must be opaque; `fg` is composited over it. */
export function contrastRatio(fg: RGBA, bg: RGBA): number {
  const top = over(fg, bg)
  const [hi, lo] = [luminance(top), luminance(bg)].sort((a, b) => b - a)
  return (hi + 0.05) / (lo + 0.05)
}

export function toHex(c: RGBA | readonly [number, number, number]): string {
  return (
    "#" +
    [c[0], c[1], c[2]]
      .map((x) =>
        Math.round(clamp(x) * 255)
          .toString(16)
          .padStart(2, "0")
          .toUpperCase()
      )
      .join("")
  )
}

/** `#rrggbb` from an OKLCH colour, gamut mapped. */
export function oklchHex(c: OKLCH): string {
  return toHex(oklchToSrgbMapped(c))
}

/** `#rrggbbaa` (or `#rrggbb` when opaque) for any colour. */
export function toHexAlpha(c: RGBA): string {
  const base = toHex(c)
  if (c[3] >= 1) return base
  return (
    base +
    Math.round(clamp(c[3]) * 255)
      .toString(16)
      .padStart(2, "0")
      .toUpperCase()
  )
}
