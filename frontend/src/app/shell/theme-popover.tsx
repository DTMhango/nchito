import { Link } from "@tanstack/react-router"
import { Monitor, Moon, Palette, Sun } from "lucide-react"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import { Segmented } from "@/components/segmented"
import { ThemeSwatch } from "@/features/settings/theme-swatch"
import { useTheme } from "@/themes/provider"
import type { ModePreference } from "@/themes/schema"
import { cn } from "@/lib/utils"

/** Quick theme and mode switch in the top bar. Full options live in Settings, Appearance. */
export function ThemePopover() {
  const { themes, theme, appearance, setAppearance } = useTheme()
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="icon" aria-label="Theme and mode">
          <Palette strokeWidth={1.5} aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="grid w-[300px] gap-3 pop-surface p-3.5"
      >
        <div className="eyebrow">Theme</div>
        <div className="grid grid-cols-2 gap-1.5">
          {themes.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-pressed={t.id === theme.id}
              onClick={() => setAppearance({ theme_id: t.id })}
              className={cn(
                "flex min-w-0 items-center gap-2 rounded-sm border border-border bg-surface px-2 py-1.75 text-left text-[0.86rem] font-medium",
                "aria-pressed:border-primary aria-pressed:shadow-[0_0_0_2px_var(--t-ring)]"
              )}
            >
              <ThemeSwatch theme={t} />
              <span className="truncate">{t.name}</span>
            </button>
          ))}
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="eyebrow">Mode</span>
          <Segmented<ModePreference>
            aria-label="Mode"
            size="sm"
            value={appearance.mode}
            onValueChange={(mode) => setAppearance({ mode })}
            options={[
              { value: "light", label: "Light", icon: Sun },
              { value: "dark", label: "Dark", icon: Moon },
              { value: "system", label: "Auto", icon: Monitor },
            ]}
          />
        </div>
        <Link to="/settings/appearance" className="text-[0.86rem]">
          All appearance options
        </Link>
      </PopoverContent>
    </Popover>
  )
}
