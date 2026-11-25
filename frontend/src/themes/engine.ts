/**
 * Theme engine: turns a Theme record + appearance preferences into CSS custom properties.
 *
 * Every token is written as `--t-<name>`. src/index.css maps those onto shadcn's variable
 * contract (`--background`, `--primary`, ...) and onto Tailwind colour utilities
 * (`bg-sunken`, `text-faint`, `bg-good-soft`, ...). Components only ever see tokens.
 */
import accents from "./accents.json"
import { fontStack } from "./fonts"
import {
  STYLE_TOKEN_DEFAULTS,
  type Appearance,
  type Mode,
  type ModePreference,
  type Theme,
} from "./schema"

export type CssVars = Record<string, string>

/** Row padding per density, before the theme's `space-k` multiplier. */
export const DENSITY_PX = { comfortable: 11, compact: 6 } as const

/** Root text size at font_scale 1. */
export const BASE_FONT_PX = 14

export function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function")
    return false
  return window.matchMedia("(prefers-color-scheme: dark)").matches
}

export function resolveMode(pref: ModePreference, systemDark: boolean): Mode {
  if (pref === "system") return systemDark ? "dark" : "light"
  return pref
}

export type AccentSwatch = (typeof accents.swatches)[number]
export const ACCENT_SWATCHES: AccentSwatch[] = accents.swatches

function hexLuminance(hex: string): number | null {
  const m = hex.match(/^#([0-9a-f]{6})$/i)
  if (!m) return null
  const n = (i: number) => {
    const c = parseInt(m[1].slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * n(0) + 0.7152 * n(2) + 0.0722 * n(4)
}

/** Resolve an accent override (swatch id or hex) to a colour and its foreground for a mode. */
export function resolveAccent(
  override: string | null | undefined,
  mode: Mode
): { color: string; fg: string } | null {
  if (!override) return null
  const swatch = ACCENT_SWATCHES.find((s) => s.id === override)
  if (swatch) return { color: swatch[mode], fg: accents.foreground[mode] }
  const lum = hexLuminance(override)
  if (lum === null) return null
  return {
    color: override,
    fg: lum > 0.36 ? accents.foreground.dark : accents.foreground.light,
  }
}

/**
 * Compute the full set of `--t-*` properties for a theme in a mode.
 * `appearance` overrides apply on top (radius, density, accent). Font scale and reduced
 * motion are root-only and handled by applyRoot.
 */
export function themeVars(
  theme: Theme,
  mode: Mode,
  appearance?: Partial<
    Pick<Appearance, "radius" | "density" | "accent_override">
  >
): CssVars {
  const tokens = theme[mode]
  const out: CssVars = {}
  const set = (k: string, v: string) => {
    out[`--t-${k}`] = v
  }

  for (const [k, v] of Object.entries(STYLE_TOKEN_DEFAULTS)) set(k, v)
  set("score-low", theme.score.low)
  set("score-mid", theme.score.mid)
  set("score-high", theme.score.high)
  theme.chart.slice(0, 5).forEach((c, i) => set(`chart-${i + 1}`, c))

  for (const [k, v] of Object.entries(tokens)) {
    if (k === "data-font" || k === "label-font") continue
    set(k, v)
  }

  const display = fontStack(theme.fonts.display)
  const body = fontStack(theme.fonts.body)
  const mono = fontStack(theme.fonts.mono, "mono")
  set("font-display", display)
  set("font-body", body)
  set("font-mono", mono)
  set("font-data", tokens["data-font"] === "mono" ? mono : body)
  set("font-label", tokens["label-font"] === "mono" ? mono : body)

  const r = appearance?.radius ?? theme.radius
  set("radius", `${r}px`)
  set("radius-sm", `${Math.round(r * 0.6)}px`)
  set("radius-lg", `${Math.round(r * 1.4)}px`)

  const density = appearance?.density ?? theme.density
  set("dens", `${DENSITY_PX[density]}px`)

  const accent = resolveAccent(appearance?.accent_override, mode)
  if (accent) {
    set("primary", accent.color)
    set("primary-ink", accent.color)
    set("primary-fg", accent.fg)
    set(
      "primary-soft",
      `color-mix(in srgb, ${accent.color} 15%, var(--t-surface))`
    )
    set("ring", `color-mix(in srgb, ${accent.color} 45%, transparent)`)
    set("score-mid", accent.color)
    set("chart-1", accent.color)
  }
  return out
}

const ownedKeys = new WeakMap<HTMLElement, Set<string>>()

/** Write vars to an element, removing any `--t-*` it set before that are no longer present. */
export function writeVars(el: HTMLElement, vars: CssVars) {
  const prev = ownedKeys.get(el) ?? new Set<string>()
  for (const k of prev) if (!(k in vars)) el.style.removeProperty(k)
  for (const [k, v] of Object.entries(vars)) el.style.setProperty(k, v)
  ownedKeys.set(el, new Set(Object.keys(vars)))
}

export type RootState = {
  themeId: string
  mode: Mode
  vars: CssVars
  fontPx: number
  reducedMotion: boolean
}

export function rootState(
  theme: Theme,
  appearance: Appearance,
  systemDark: boolean
): RootState {
  const mode = resolveMode(appearance.mode, systemDark)
  return {
    themeId: theme.id,
    mode,
    vars: themeVars(theme, mode, appearance),
    fontPx: Math.round(BASE_FONT_PX * appearance.font_scale * 100) / 100,
    reducedMotion: appearance.reduced_motion,
  }
}

/** Apply a resolved root state to <html>. */
export function applyRoot(
  state: RootState,
  root: HTMLElement = document.documentElement
) {
  writeVars(root, { ...state.vars, "--t-font-size": `${state.fontPx}px` })
  root.dataset.themeId = state.themeId
  root.dataset.mode = state.mode
  root.dataset.reducedMotion = String(state.reducedMotion)
  root.classList.toggle("dark", state.mode === "dark")
  root.style.colorScheme = state.mode
}
