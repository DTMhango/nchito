/**
 * Self-hosted font registry (Fontsource). Nothing is fetched from a font CDN.
 *
 * A theme names its families ("Figtree", "IBM Plex Mono"); this table says how to load
 * each one and what to fall back to while it loads. Loading is lazy: a family's CSS
 * chunk is imported only when a theme that uses it is applied or previewed.
 * To support a new family, add a Fontsource package and one entry here.
 */

type FontEntry = {
  /** CSS family name(s) that Fontsource registers. */
  css: string
  /** System fallback stack used until the font arrives. */
  fallback: string
  load: () => Promise<unknown>
}

const SANS = '"Segoe UI", system-ui, -apple-system, sans-serif'
const SERIF = 'Georgia, "Times New Roman", serif'
const MONO = 'ui-monospace, "Cascadia Mono", Consolas, monospace'

export const FONTS: Record<string, FontEntry> = {
  "Bricolage Grotesque": {
    css: '"Bricolage Grotesque Variable", "Bricolage Grotesque"',
    fallback: SANS,
    load: () => import("@fontsource-variable/bricolage-grotesque/index.css"),
  },
  Figtree: {
    css: '"Figtree"',
    fallback: SANS,
    load: () =>
      Promise.all([
        import("@fontsource/figtree/latin-400.css"),
        import("@fontsource/figtree/latin-500.css"),
        import("@fontsource/figtree/latin-600.css"),
        import("@fontsource/figtree/latin-700.css"),
      ]),
  },
  "IBM Plex Sans": {
    css: '"IBM Plex Sans"',
    fallback: SANS,
    load: () =>
      Promise.all([
        import("@fontsource/ibm-plex-sans/latin-400.css"),
        import("@fontsource/ibm-plex-sans/latin-500.css"),
        import("@fontsource/ibm-plex-sans/latin-600.css"),
      ]),
  },
  "IBM Plex Mono": {
    css: '"IBM Plex Mono"',
    fallback: MONO,
    load: () =>
      Promise.all([
        import("@fontsource/ibm-plex-mono/latin-400.css"),
        import("@fontsource/ibm-plex-mono/latin-500.css"),
        import("@fontsource/ibm-plex-mono/latin-600.css"),
      ]),
  },
  Fraunces: {
    css: '"Fraunces Variable", "Fraunces"',
    fallback: SERIF,
    load: () => import("@fontsource-variable/fraunces/index.css"),
  },
  "Nunito Sans": {
    css: '"Nunito Sans"',
    fallback: SANS,
    load: () =>
      Promise.all([
        import("@fontsource/nunito-sans/latin-400.css"),
        import("@fontsource/nunito-sans/latin-600.css"),
        import("@fontsource/nunito-sans/latin-700.css"),
      ]),
  },
  Newsreader: {
    css: '"Newsreader Variable", "Newsreader"',
    fallback: SERIF,
    load: () => import("@fontsource-variable/newsreader/index.css"),
  },
  Inter: {
    css: '"Inter"',
    fallback: SANS,
    load: () =>
      Promise.all([
        import("@fontsource/inter/latin-400.css"),
        import("@fontsource/inter/latin-500.css"),
        import("@fontsource/inter/latin-600.css"),
        import("@fontsource/inter/latin-700.css"),
      ]),
  },
  "Space Grotesk": {
    css: '"Space Grotesk"',
    fallback: SANS,
    load: () =>
      Promise.all([
        import("@fontsource/space-grotesk/latin-400.css"),
        import("@fontsource/space-grotesk/latin-500.css"),
        import("@fontsource/space-grotesk/latin-600.css"),
        import("@fontsource/space-grotesk/latin-700.css"),
      ]),
  },
  "JetBrains Mono": {
    css: '"JetBrains Mono"',
    fallback: MONO,
    load: () =>
      Promise.all([
        import("@fontsource/jetbrains-mono/latin-400.css"),
        import("@fontsource/jetbrains-mono/latin-500.css"),
        import("@fontsource/jetbrains-mono/latin-600.css"),
      ]),
  },
}

/** Full CSS font-family stack for a family name (unknown names fall back to system UI). */
export function fontStack(
  family: string,
  kind: "sans" | "mono" = "sans"
): string {
  const entry = FONTS[family]
  if (entry) return `${entry.css}, ${entry.fallback}`
  return `"${family}", ${kind === "mono" ? MONO : SANS}`
}

const loaded = new Map<string, Promise<unknown>>()

/** Load a family once. Safe to call repeatedly; failures are swallowed (fallback stays). */
export function loadFont(family: string): Promise<unknown> {
  const entry = FONTS[family]
  if (!entry) return Promise.resolve()
  let p = loaded.get(family)
  if (!p) {
    p = entry.load().catch(() => undefined)
    loaded.set(family, p)
  }
  return p
}

export function loadThemeFonts(fonts: {
  display: string
  body: string
  mono: string
}) {
  return Promise.all([
    loadFont(fonts.display),
    loadFont(fonts.body),
    loadFont(fonts.mono),
  ])
}
