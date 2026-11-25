import {
  useEffect,
  useMemo,
  type CSSProperties,
  type HTMLAttributes,
} from "react"
import { cn } from "@/lib/utils"
import { themeVars } from "./engine"
import { loadThemeFonts } from "./fonts"
import { BUILTIN_THEMES, findTheme } from "./index"
import { useOptionalTheme } from "./provider"
import type { Mode, Theme } from "./schema"

type ThemeScopeProps = HTMLAttributes<HTMLDivElement> & {
  /** A theme record or a theme id. */
  theme: Theme | string
  /** Light or dark. Defaults to the app's current resolved mode. */
  mode?: Mode
  /**
   * Carry the owner's density and radius overrides into the scope. Off by default so
   * gallery previews show each theme as designed. The accent override never carries over.
   */
  inheritAppearance?: boolean
}

/**
 * Render a subtree in another theme. Writes the theme's `--t-*` variables on a wrapper and
 * marks it `data-theme-scope`, which re-runs the shadcn variable mapping in index.css for
 * everything inside. Used by the theme gallery and the component gallery.
 */
export function ThemeScope({
  theme,
  mode,
  inheritAppearance = false,
  className,
  style,
  children,
  ...rest
}: ThemeScopeProps) {
  const ctx = useOptionalTheme()
  const resolved =
    typeof theme === "string"
      ? findTheme(ctx?.themes ?? BUILTIN_THEMES, theme)
      : theme
  const m: Mode = mode ?? ctx?.mode ?? "light"
  const appearance = inheritAppearance ? ctx?.appearance : undefined

  const vars = useMemo(
    () =>
      themeVars(
        resolved,
        m,
        appearance
          ? { density: appearance.density, radius: appearance.radius }
          : undefined
      ),
    [resolved, m, appearance]
  )

  useEffect(() => {
    void loadThemeFonts(resolved.fonts)
  }, [resolved.fonts])

  return (
    <div
      data-theme-scope=""
      data-theme-id={resolved.id}
      data-mode={m}
      className={cn(
        "bg-background font-sans text-foreground",
        m === "dark" && "dark",
        className
      )}
      style={{ ...(vars as CSSProperties), colorScheme: m, ...style }}
      {...rest}
    >
      {children}
    </div>
  )
}
