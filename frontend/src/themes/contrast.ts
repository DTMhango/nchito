/**
 * Contrast check over every text/surface pair the app uses. The pairs are derived from the token
 * spec (`use` + `on`, `@ground` = the ground tokens), not listed by hand; the WCAG levels come
 * from the spec too. Mirrors `evaluate_contrast` in `backend/app/themes/tokens.py`.
 */
import {
  ColourError,
  contrastRatio,
  oklchHex,
  over,
  parseLiteral,
  resolveColour,
  srgbToOklch,
  type RGBA,
} from "./colour"
import { GROUND_TOKENS, TOKEN_SPEC, type ContrastUse } from "./spec"
import type { Mode } from "./schema"

export type Pair = { fg: string; bg: string; use: ContrastUse }

export type PairResult = Pair & {
  mode: Mode
  ratio: number
  aa: boolean
  aaa: boolean | null
  /** Below AA on a level that blocks saving (body text). */
  blocking: boolean
}

export function contrastPairs(): Pair[] {
  const pairs: Pair[] = []
  for (const [name, s] of Object.entries(TOKEN_SPEC.tokens)) {
    if (!s.use) continue
    for (const target of s.on ?? [])
      for (const bg of target === "@ground" ? GROUND_TOKENS : [target])
        pairs.push({ fg: name, bg, use: s.use })
  }
  return pairs
}

const STYLE_COLOUR_DEFAULTS: Record<string, string> = {
  "panel-border": "var(--t-border)",
  "elev-top-color": "var(--t-panel-border)",
}

/** The mode map plus top-level chart/score fallbacks, as the engine sees it. */
export function tokenEnv(
  tokens: Record<string, string>,
  chart: string[] = [],
  score: Record<string, string> = {}
): Record<string, string> {
  const env: Record<string, string> = { ...STYLE_COLOUR_DEFAULTS }
  chart.slice(0, 5).forEach((c, i) => (env[`chart-${i + 1}`] = c))
  for (const [k, v] of Object.entries(score)) env[`score-${k}`] = v
  return { ...env, ...tokens }
}

/** Page base under the theme's bg: white in light mode, black in dark (as a browser paints it). */
const pageBase = (mode: Mode): RGBA =>
  parseLiteral(mode === "light" ? "#FFFFFF" : "#000000")

function groundOf(env: Record<string, string>, bg: string, mode: Mode): RGBA {
  const page = over(resolveColour(env.bg, env), pageBase(mode))
  return over(resolveColour(env[bg], env), page)
}

export function evaluateContrast(
  tokens: Record<string, string>,
  mode: Mode,
  chart?: string[],
  score?: Record<string, string>
): PairResult[] {
  const env = tokenEnv(tokens, chart, score)
  const out: PairResult[] = []
  for (const p of contrastPairs()) {
    if (!(p.fg in env) || !(p.bg in env)) continue
    let ratio: number
    try {
      ratio = contrastRatio(
        resolveColour(env[p.fg], env),
        groundOf(env, p.bg, mode)
      )
    } catch (e) {
      if (e instanceof ColourError) continue
      throw e
    }
    const lvl = TOKEN_SPEC.levels[p.use]
    const aa = ratio >= lvl.aa
    out.push({
      ...p,
      mode,
      ratio: Math.round(ratio * 100) / 100,
      aa,
      aaa: lvl.aaa === null ? null : ratio >= lvl.aaa,
      blocking: lvl.blocking && !aa,
    })
  }
  return out
}

/**
 * The nearest colour to the pair's foreground that passes AA: same OKLCH hue and chroma, lightness
 * moved the least distance (searched both darker and lighter), passing on every ground the
 * token is used on. Null when nothing passes.
 */
export function suggestFix(
  tokens: Record<string, string>,
  mode: Mode,
  pair: Pair,
  chart?: string[],
  score?: Record<string, string>
): string | null {
  const env = tokenEnv(tokens, chart, score)
  let grounds: RGBA[]
  let fg: RGBA
  try {
    // Every ground this token is read on, so the suggestion fixes the whole row, not one pair.
    grounds = contrastPairs()
      .filter((p) => p.fg === pair.fg && p.bg in env)
      .map((p) => groundOf(env, p.bg, mode))
    fg = resolveColour(env[pair.fg], env)
  } catch {
    return null
  }
  const target = TOKEN_SPEC.levels[pair.use].aa
  const start = srgbToOklch(fg[0], fg[1], fg[2])
  let best: string | null = null
  let bestDelta = Infinity
  for (let step = 1; step <= 100; step++) {
    for (const dir of [-1, 1]) {
      const l = start.l + (dir * step) / 100
      if (l < 0 || l > 1) continue
      const hex = oklchHex({ ...start, l })
      const c = parseLiteral(hex)
      const ratio = Math.min(...grounds.map((g) => contrastRatio(c, g)))
      if (ratio >= target + 0.05 && step < bestDelta) {
        best = hex
        bestDelta = step
      }
    }
    if (best) break
  }
  return best
}
