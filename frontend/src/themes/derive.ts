/**
 * Derive a full light + dark palette from one or two seed colours, in OKLCH. Deterministic: the
 * same seeds always give the same tokens. Text-like tokens are pushed in lightness until they
 * pass WCAG AA on every ground, so a generated theme saves without a contrast waiver. Status
 * colours keep fixed hue anchors (good green, warn amber, danger red, info blue), separate from
 * the accent (DESIGN 10.1).
 */
import {
  contrastRatio,
  oklchHex,
  parseLiteral,
  srgbToOklch,
  toHex,
  type OKLCH,
} from "./colour"
import type { Mode } from "./schema"

/** Hue anchors (degrees, OKLCH) for the semantic colours. */
const STATUS_HUES = { good: 150, warn: 70, danger: 27, info: 250 } as const

const AA = 4.5

type Lch = OKLCH
const hex = (c: Lch) => oklchHex(c)
const withAlpha = (c: Lch, a: number) =>
  hex(c) +
  Math.round(a * 255)
    .toString(16)
    .padStart(2, "0")
    .toUpperCase()

/** Move lightness (darker in light mode, lighter in dark) until `c` reaches `target` on every ground. */
function ensure(c: Lch, grounds: string[], mode: Mode, target = AA): Lch {
  const dir = mode === "light" ? -1 : 1
  let cur = c
  for (let i = 0; i < 100; i++) {
    const fg = parseLiteral(hex(cur))
    const worst = Math.min(
      ...grounds.map((g) => contrastRatio(fg, parseLiteral(g)))
    )
    if (worst >= target + 0.1) return cur
    const l = cur.l + dir * 0.01
    if (l < 0 || l > 1) return cur
    cur = { ...cur, l }
  }
  return cur
}

/** The better of near-white and near-black on a fill. */
function onFill(fill: string, hue: number): string {
  const light = hex({ l: 0.99, c: 0.005, h: hue })
  const dark = hex({ l: 0.16, c: 0.02, h: hue })
  const f = parseLiteral(fill)
  return contrastRatio(parseLiteral(light), f) >=
    contrastRatio(parseLiteral(dark), f)
    ? light
    : dark
}

export type Seeds = { primary: string; accent?: string | null }
export type DerivedPalette = {
  light: Record<string, string>
  dark: Record<string, string>
  chart: string[]
  score: { low: string; mid: string; high: string }
}

function seedLch(value: string): Lch {
  const c = parseLiteral(value)
  return srgbToOklch(c[0], c[1], c[2])
}

function modeTokens(p: Lch, a: Lch, mode: Mode): Record<string, string> {
  const L = mode === "light"
  const n = (l: number, c = 0.012): Lch => ({ l, c, h: p.h })
  const bg = hex(n(L ? 0.975 : 0.17, L ? 0.006 : 0.014))
  const sunken = hex(n(L ? 0.945 : 0.14, L ? 0.008 : 0.014))
  const surface = hex(n(L ? 0.997 : 0.205, L ? 0.002 : 0.016))
  const surface2 = hex(n(L ? 0.985 : 0.235, L ? 0.004 : 0.016))
  const grounds = [bg, sunken, surface, surface2]

  const chroma = (c: number, cap: number) => Math.min(c, cap)
  const primaryBase: Lch = {
    l: L ? 0.5 : 0.74,
    c: chroma(p.c, L ? 0.16 : 0.14),
    h: p.h,
  }
  const primary = ensure(primaryBase, grounds, mode, 3)
  const primarySoft: Lch = { l: L ? 0.93 : 0.3, c: chroma(p.c, 0.05), h: p.h }
  const primaryInk = ensure(primaryBase, [...grounds, hex(primarySoft)], mode)
  const accentBase: Lch = {
    l: L ? 0.55 : 0.76,
    c: chroma(a.c, L ? 0.15 : 0.13),
    h: a.h,
  }
  const accent = ensure(accentBase, grounds, mode, 3)
  const accentSoft: Lch = { l: L ? 0.94 : 0.29, c: chroma(a.c, 0.05), h: a.h }
  const accentInk = ensure(accentBase, [...grounds, hex(accentSoft)], mode)

  const t: Record<string, string> = {
    bg,
    "bg-sunken": sunken,
    surface,
    "surface-2": surface2,
    border: hex(n(L ? 0.9 : 0.3, 0.014)),
    "border-strong": hex(n(L ? 0.78 : 0.4, 0.02)),
    text: hex(ensure(n(L ? 0.2 : 0.94, 0.02), grounds, mode, 12)),
    "text-muted": hex(ensure(n(L ? 0.42 : 0.78, 0.025), grounds, mode)),
    "text-faint": hex(ensure(n(L ? 0.5 : 0.68, 0.02), grounds, mode)),
    primary: hex(primary),
    "primary-ink": hex(primaryInk),
    "primary-soft": hex(primarySoft),
    accent: hex(accent),
    "accent-ink": hex(accentInk),
    "accent-soft": hex(accentSoft),
    ring: withAlpha(primary, L ? 0.4 : 0.5),
    overlay: withAlpha(n(L ? 0.15 : 0.05, 0.02), L ? 0.3 : 0.55),
  }
  t["primary-fg"] = onFill(t.primary, p.h)

  for (const [name, h] of Object.entries(STATUS_HUES)) {
    const soft: Lch = { l: L ? 0.94 : 0.28, c: 0.045, h }
    const ink = ensure(
      { l: L ? 0.52 : 0.76, c: L ? 0.13 : 0.12, h },
      [...grounds, hex(soft)],
      mode
    )
    t[name] = hex(ink)
    t[`${name}-soft`] = hex(soft)
  }
  const chart = [t.primary, t.accent, t.info, t.good, t.warn]
  chart.forEach((c, i) => (t[`chart-${i + 1}`] = c))
  t["score-low"] = hex(n(L ? 0.72 : 0.45, 0.02))
  t["score-mid"] = t.primary
  t["score-high"] = t.accent
  return t
}

/** A full palette from one or two seeds. Without an accent seed the accent sits opposite-ish (+150 degrees). */
export function derivePalette(seeds: Seeds): DerivedPalette {
  const p = seedLch(seeds.primary)
  const a = seeds.accent
    ? seedLch(seeds.accent)
    : { l: p.l, c: Math.max(p.c, 0.1), h: (p.h + 150) % 360 }
  const light = modeTokens(p, a, "light")
  const dark = modeTokens(p, a, "dark")
  return {
    light,
    dark,
    chart: [1, 2, 3, 4, 5].map((i) => light[`chart-${i}`]),
    score: {
      low: light["score-low"],
      mid: light["score-mid"],
      high: light["score-high"],
    },
  }
}

/** Normalise any allowed literal colour to `#RRGGBB` (for the native colour input). */
export function asHex6(value: string): string | null {
  try {
    return toHex(parseLiteral(value))
  } catch {
    return null
  }
}

/** Value shown by a native colour input when the token is not a literal colour (it is disabled then). */
export const PICKER_PLACEHOLDER = "#000000"
