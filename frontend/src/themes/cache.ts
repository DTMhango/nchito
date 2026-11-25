/**
 * Local appearance cache, so the app paints in the owner's theme before the API answers.
 *
 * Two keys:
 * - `nchito.appearance.v1`: the appearance record and the active theme (validated on read).
 * - `nchito.paint.v1`: pre-computed root CSS variables for light and dark. index.html reads
 *   this with a tiny inline script before any JavaScript bundle loads, so there is no flash.
 */
import {
  appearanceSchema,
  themeSchema,
  type Appearance,
  type Theme,
} from "./schema"
import type { CssVars } from "./engine"

export const APPEARANCE_KEY = "nchito.appearance.v1"
export const PAINT_KEY = "nchito.paint.v1"

export type PaintCache = {
  mode: Appearance["mode"]
  themeId: string
  fontPx: number
  reducedMotion: boolean
  light: CssVars
  dark: CssVars
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null
  } catch {
    return null
  }
}

export function readAppearanceCache(): {
  appearance: Appearance
  theme: Theme | null
} | null {
  const s = storage()
  if (!s) return null
  try {
    const raw = s.getItem(APPEARANCE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as { appearance?: unknown; theme?: unknown }
    const appearance = appearanceSchema.safeParse(data.appearance)
    if (!appearance.success) return null
    const theme = themeSchema.safeParse(data.theme)
    return {
      appearance: appearance.data,
      theme: theme.success ? theme.data : null,
    }
  } catch {
    return null
  }
}

export function writeAppearanceCache(
  appearance: Appearance,
  theme: Theme,
  paint: PaintCache
) {
  const s = storage()
  if (!s) return
  try {
    s.setItem(APPEARANCE_KEY, JSON.stringify({ appearance, theme }))
    s.setItem(PAINT_KEY, JSON.stringify(paint))
  } catch {
    /* storage full or blocked: the API copy still holds the truth */
  }
}

export function clearAppearanceCache() {
  const s = storage()
  try {
    s?.removeItem(APPEARANCE_KEY)
    s?.removeItem(PAINT_KEY)
  } catch {
    /* ignore */
  }
}
