import { ThemeScope } from "@/themes/scope"
import type { Mode, Theme } from "@/themes/schema"
import { useTheme } from "@/themes/provider"

/** Three-stripe swatch (ground, primary, accent) drawn in the theme's own tokens. */
export function ThemeSwatch({ theme, mode }: { theme: Theme; mode?: Mode }) {
  const ctx = useTheme()
  return (
    <ThemeScope
      theme={theme}
      mode={mode ?? ctx.mode}
      aria-hidden="true"
      className="inline-flex shrink-0 overflow-hidden rounded-full border border-border"
    >
      <i className="block h-[18px] w-2.5 bg-background" />
      <i className="block h-[18px] w-2.5 bg-primary" />
      <i className="block h-[18px] w-2.5 bg-highlight" />
    </ThemeScope>
  )
}
