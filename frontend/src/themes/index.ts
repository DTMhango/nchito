import copperbelt from "./builtin/copperbelt.json"
import midnightLedger from "./builtin/midnight-ledger.json"
import savannaDusk from "./builtin/savanna-dusk.json"
import paper from "./builtin/paper.json"
import workshop from "./builtin/workshop.json"
import highContrast from "./builtin/high-contrast.json"
import { themeSchema, type Theme } from "./schema"

export * from "./schema"
export * from "./engine"
export { loadFont, loadThemeFonts, fontStack } from "./fonts"

/** Built-in themes, in gallery order. Validated at import so a bad JSON edit fails fast. */
export const BUILTIN_THEMES: Theme[] = [
  copperbelt,
  midnightLedger,
  savannaDusk,
  paper,
  workshop,
  highContrast,
].map((t) => themeSchema.parse(t))

export const DEFAULT_THEME_ID = "copperbelt"

export function builtinTheme(id: string): Theme | undefined {
  return BUILTIN_THEMES.find((t) => t.id === id)
}

/**
 * Merge themes from the API with the bundled built-ins. The API is the source of truth
 * for custom themes; bundled built-ins fill in when the API is unreachable.
 */
export function mergeThemes(fromApi: Theme[] | undefined): Theme[] {
  if (!fromApi?.length) return BUILTIN_THEMES
  const byId = new Map<string, Theme>()
  for (const t of BUILTIN_THEMES) byId.set(t.id, t)
  for (const t of fromApi) {
    const parsed = themeSchema.safeParse(t)
    if (parsed.success) byId.set(t.id, parsed.data)
  }
  return [...byId.values()]
}

export function findTheme(themes: Theme[], id: string): Theme {
  return (
    themes.find((t) => t.id === id) ?? builtinTheme(id) ?? BUILTIN_THEMES[0]
  )
}
