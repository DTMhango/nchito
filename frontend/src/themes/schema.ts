import { z } from "zod"

/**
 * Theme schema (DESIGN 10.4). A theme is data: a record of semantic tokens for light and
 * dark, plus fonts, radius, density, chart palette and score ramp.
 *
 * Token names are the mockup's CSS custom properties without the leading `--`.
 * The engine writes each one to the root element as `--t-<name>`.
 */

/** Colour tokens every mode map must define. */
export const COLOR_TOKENS = [
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
  "overlay",
] as const

/**
 * Character tokens. Optional; the engine supplies the defaults below.
 * - `score-*`, `chart-1..5`: fall back to the top-level `score` and `chart`.
 * - `data-font`, `label-font`: "mono" or "body" (which family figures and labels use).
 * - `label-case`: "uppercase" or "none".
 * - `space-k`: multiplier on row padding (density character of the theme).
 * - `elev-top`, `elev-top-color`: top rule of elevated surfaces (Paper uses a 2px strong rule).
 * - `panel-border`: border colour of panels (Workshop uses the strong border).
 * - `shadow-pop`: shadow for popovers and menus.
 */
export const STYLE_TOKEN_DEFAULTS: Record<string, string> = {
  "shadow-sm": "none",
  shadow: "none",
  "display-weight": "600",
  "display-track": "-0.01em",
  "label-case": "uppercase",
  "label-track": ".07em",
  "space-k": "1",
  "data-font": "body",
  "label-font": "body",
  "elev-top": "1px",
  "elev-top-color": "var(--t-panel-border)",
  "panel-border": "var(--t-border)",
  "shadow-pop": "var(--t-shadow)",
}

export type ColorToken = (typeof COLOR_TOKENS)[number]

const tokenMap = z.record(z.string(), z.string()).superRefine((map, ctx) => {
  for (const t of COLOR_TOKENS) {
    if (!map[t])
      ctx.addIssue({
        code: "custom",
        message: `missing token "${t}"`,
        path: [t],
      })
  }
})

export const themeSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  builtin: z.boolean(),
  /** Short description shown under the gallery card. Optional. */
  description: z.string().optional(),
  fonts: z.object({
    display: z.string().min(1),
    body: z.string().min(1),
    mono: z.string().min(1),
  }),
  /** Base corner radius in px. Small and large radii derive from it (x0.6, x1.4). */
  radius: z.number().min(0).max(32),
  /** Suggested density when the theme is first chosen. */
  density: z.enum(["comfortable", "compact"]),
  light: tokenMap,
  dark: tokenMap,
  chart: z.array(z.string()).min(1),
  score: z.object({ low: z.string(), mid: z.string(), high: z.string() }),
  /** Arrived in a Kit with body text below AA and not accepted yet: shown, never applied. */
  needs_review: z.boolean().optional(),
})

export type Theme = z.infer<typeof themeSchema>
export type Mode = "light" | "dark"
export type ModePreference = Mode | "system"
export type Density = Theme["density"]

export const FONT_SCALES = [13 / 14, 1, 15 / 14, 16 / 14] as const

export const appearanceSchema = z.object({
  theme_id: z.string().min(1),
  mode: z.enum(["light", "dark", "system"]),
  density: z.enum(["comfortable", "compact"]),
  /** Base radius override in px, or null for the theme's own. */
  radius: z.number().int().min(0).max(24).nullable(),
  /** Root text size relative to 14px. */
  font_scale: z.number().min(0.85).max(1.25),
  /** An accent swatch id from accents.json, a hex colour, or null for the theme's primary. */
  accent_override: z.string().nullable(),
  reduced_motion: z.boolean(),
})

export type Appearance = z.infer<typeof appearanceSchema>

/** The one place appearance defaults live (DESIGN 16: Copperbelt, system, comfortable). */
export const DEFAULT_APPEARANCE: Appearance = {
  theme_id: "copperbelt",
  mode: "system",
  density: "comfortable",
  radius: null,
  font_scale: 1,
  accent_override: null,
  reduced_motion: false,
}
