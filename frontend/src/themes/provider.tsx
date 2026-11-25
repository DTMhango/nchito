import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  appearanceQuery,
  keys,
  meQuery,
  putAppearance,
  themesQuery,
} from "@/lib/api/endpoints"
import { readAppearanceCache, writeAppearanceCache } from "./cache"
import { applyRoot, resolveMode, rootState, themeVars } from "./engine"
import { loadThemeFonts } from "./fonts"
import { BUILTIN_THEMES, findTheme, mergeThemes } from "./index"
import {
  DEFAULT_APPEARANCE,
  type Appearance,
  type Mode,
  type Theme,
} from "./schema"

export type ThemeContextValue = {
  /** Every theme the owner can pick: built-ins plus their own. */
  themes: Theme[]
  /** The active theme. */
  theme: Theme
  /** The active appearance, including unsaved optimistic changes. */
  appearance: Appearance
  /** Light or dark, after resolving "system". */
  mode: Mode
  /**
   * Change appearance. Applies at once and is cached locally; persists to the API when
   * signed in. Pass `{ persist: false }` for a live preview while a control is dragged.
   */
  setAppearance: (
    patch: Partial<Appearance>,
    opts?: { persist?: boolean }
  ) => void
  saving: boolean
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

const darkQuery = "(prefers-color-scheme: dark)"
function subscribeSystem(cb: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {}
  const mq = window.matchMedia(darkQuery)
  mq.addEventListener?.("change", cb)
  return () => mq.removeEventListener?.("change", cb)
}
function getSystemDark() {
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia(darkQuery).matches
  )
}

export function useSystemDark() {
  return useSyncExternalStore(subscribeSystem, getSystemDark, () => false)
}

/**
 * Apply the cached (or default) theme to <html> synchronously, before React renders.
 * Called once from main.tsx so the first paint is already themed.
 */
export function bootTheme() {
  const cached = readAppearanceCache()
  const appearance = cached?.appearance ?? DEFAULT_APPEARANCE
  const theme =
    cached?.theme && cached.theme.id === appearance.theme_id
      ? cached.theme
      : findTheme(BUILTIN_THEMES, appearance.theme_id)
  applyRoot(rootState(theme, appearance, getSystemDark()))
  void loadThemeFonts(theme.fonts)
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient()
  const [cached] = useState(readAppearanceCache)
  const me = useQuery(meQuery())
  const authed = !!me.data
  const themesQ = useQuery(themesQuery(authed))
  const appearanceQ = useQuery(appearanceQuery(authed))
  const systemDark = useSystemDark()

  // Optimistic layer: set while a change is unsaved, cleared when the latest save settles.
  const [override, setOverride] = useState<Appearance | null>(null)
  const seq = useRef(0)

  const appearance: Appearance =
    override ?? appearanceQ.data ?? cached?.appearance ?? DEFAULT_APPEARANCE

  const themes = useMemo(() => {
    const list = mergeThemes(themesQ.data)
    if (cached?.theme && !list.some((t) => t.id === cached.theme!.id))
      list.push(cached.theme)
    return list
  }, [themesQ.data, cached])

  const theme = findTheme(themes, appearance.theme_id)
  const mode = resolveMode(appearance.mode, systemDark)

  const mutation = useMutation({ mutationFn: putAppearance })

  const setAppearance = useCallback<ThemeContextValue["setAppearance"]>(
    (patch, opts) => {
      const next = { ...appearance, ...patch }
      setOverride(next)
      if (opts?.persist === false || !authed) return
      const mine = ++seq.current
      mutation.mutate(next, {
        onSuccess: (saved) => {
          qc.setQueryData(keys.appearance, saved)
          if (mine === seq.current) setOverride(null)
        },
        onError: () => {
          if (mine === seq.current) setOverride(null)
          toast.error("Couldn't save your appearance. It's back to how it was.")
        },
      })
    },
    [appearance, authed, mutation, qc]
  )

  useLayoutEffect(() => {
    const state = rootState(theme, appearance, systemDark)
    applyRoot(state)
    void loadThemeFonts(theme.fonts)
    writeAppearanceCache(appearance, theme, {
      mode: appearance.mode,
      themeId: theme.id,
      fontPx: state.fontPx,
      reducedMotion: appearance.reduced_motion,
      light: themeVars(theme, "light", appearance),
      dark: themeVars(theme, "dark", appearance),
    })
  }, [theme, appearance, systemDark])

  const value = useMemo<ThemeContextValue>(
    () => ({
      themes,
      theme,
      appearance,
      mode,
      setAppearance,
      saving: mutation.isPending,
    }),
    [themes, theme, appearance, mode, setAppearance, mutation.isPending]
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>")
  return ctx
}

/** Like useTheme, but returns null outside a provider (for components that also render standalone). */
export function useOptionalTheme(): ThemeContextValue | null {
  return useContext(ThemeContext)
}
