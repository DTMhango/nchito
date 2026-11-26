import { useRef, type ReactNode } from "react"
import { Link, useNavigate } from "@tanstack/react-router"
import {
  Check,
  Download,
  Layers,
  Monitor,
  Moon,
  Paintbrush,
  Pencil,
  Sun,
  Upload,
  X,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { Segmented } from "@/components/segmented"
import { useTheme } from "@/themes/provider"
import {
  ACCENT_SWATCHES,
  DEFAULT_APPEARANCE,
  FONT_SCALES,
  type Density,
  type ModePreference,
} from "@/themes"
import { cn } from "@/lib/utils"
import { ThemePreview } from "./theme-preview"
import {
  downloadJson,
  exportTheme,
  fileSlug,
} from "@/features/theme-studio/api"
import { useThemeFiles } from "@/features/theme-studio/use-theme-files"

const TOKEN_NAMES = [
  "bg",
  "surface",
  "border",
  "text",
  "text-muted",
  "primary",
  "accent",
  "good",
  "warn",
  "danger",
]

/** Settings, Appearance (DESIGN 10.4): theme gallery and every appearance preference. */
export function AppearancePage() {
  const { themes, theme, appearance, mode, setAppearance } = useTheme()
  const navigate = useNavigate()
  const fileInput = useRef<HTMLInputElement>(null)
  const files = useThemeFiles()
  const radius = appearance.radius ?? theme.radius
  const fontPx = String(Math.round(14 * appearance.font_scale))

  const tokenJson = JSON.stringify(
    {
      name: theme.name,
      mode,
      fonts: theme.fonts,
      radius,
      tokens: Object.fromEntries(TOKEN_NAMES.map((n) => [n, theme[mode][n]])),
    },
    null,
    2
  )

  return (
    <div className="grid gap-7">
      <section aria-labelledby="themes-title">
        <SectionHeader
          title={<span id="themes-title">Themes</span>}
          aside="Each preview uses its own theme. Click one to use it."
        />
        <div className="-m-1 grid auto-cols-[minmax(200px,240px)] grid-flow-col gap-4 overflow-x-auto p-1 pb-2.5 xl:auto-cols-auto xl:grid-flow-row xl:grid-cols-3 2xl:grid-cols-6">
          {themes.map((t) => {
            const active = t.id === theme.id
            return (
              <button
                key={t.id}
                type="button"
                aria-pressed={active}
                aria-label={`${t.name}${active ? ", in use" : ""}${t.needs_review ? ", needs review" : ""}`}
                onClick={() => {
                  if (t.needs_review) {
                    void navigate({
                      to: "/theme-studio/$themeId",
                      params: { themeId: t.id },
                    })
                    return
                  }
                  setAppearance({ theme_id: t.id })
                  if (!active) toast.success(`${t.name} theme on.`)
                }}
                className="group/card grid gap-2 rounded-lg bg-transparent p-0 text-left text-foreground"
              >
                <span
                  className={cn(
                    "block rounded-lg transition-transform group-hover/card:-translate-y-0.5",
                    active &&
                      "shadow-[0_0_0_2px_var(--t-bg),0_0_0_4px_var(--t-primary)]"
                  )}
                >
                  <ThemePreview theme={t} mode={mode} />
                </span>
                <span className="flex items-center gap-2 font-semibold">
                  {t.name}
                  {active && <Chip tone="primary">In use</Chip>}
                  {t.needs_review && <Chip tone="warn">Needs review</Chip>}
                </span>
                <span className="text-[0.8rem] text-faint">
                  {t.description ? `${t.description} · ` : ""}
                  {[...new Set([t.fonts.display, t.fonts.body])].join(", ")}
                </span>
              </button>
            )
          })}
        </div>
      </section>

      <section
        aria-label="Preferences"
        className="grid gap-x-10 lg:grid-cols-2"
      >
        <div>
          <Pref title="Mode" hint="Follow system matches your device">
            <Segmented<ModePreference>
              aria-label="Mode"
              value={appearance.mode}
              onValueChange={(m) => setAppearance({ mode: m })}
              options={[
                { value: "light", label: "Light", icon: Sun },
                { value: "dark", label: "Dark", icon: Moon },
                { value: "system", label: "Follow system", icon: Monitor },
              ]}
            />
          </Pref>
          <Pref title="Accent" hint="Overrides the theme's primary colour">
            <div
              role="radiogroup"
              aria-label="Accent"
              className="flex flex-wrap items-center gap-2"
            >
              <AccentButton
                label="Theme default"
                selected={!appearance.accent_override}
                onSelect={() => setAppearance({ accent_override: null })}
              >
                <X className="size-3.5" aria-hidden="true" />
              </AccentButton>
              {ACCENT_SWATCHES.map((s) => (
                <AccentButton
                  key={s.id}
                  label={s.name}
                  selected={appearance.accent_override === s.id}
                  onSelect={() => setAppearance({ accent_override: s.id })}
                  color={s[mode]}
                />
              ))}
            </div>
          </Pref>
          <Pref title="Density" hint="Row padding in lists and tables">
            <Segmented<Density>
              aria-label="Density"
              value={appearance.density}
              onValueChange={(d) => setAppearance({ density: d })}
              options={[
                { value: "comfortable", label: "Comfortable" },
                { value: "compact", label: "Compact" },
              ]}
            />
          </Pref>
        </div>
        <div>
          <Pref title="Corner radius" hint="Theme value until you move it">
            <div className="flex items-center gap-3">
              <Slider
                aria-label="Corner radius"
                className="min-w-0 flex-1"
                min={0}
                max={22}
                step={1}
                value={[radius]}
                onValueChange={([v]) =>
                  setAppearance({ radius: v }, { persist: false })
                }
                onValueCommit={([v]) => setAppearance({ radius: v })}
              />
              <span className="min-w-9 num text-sm">{radius}px</span>
              <Button
                variant="ghost"
                size="sm"
                disabled={appearance.radius === null}
                onClick={() => setAppearance({ radius: null })}
              >
                Reset
              </Button>
            </div>
          </Pref>
          <Pref title="Text size" hint="Scales the whole interface">
            <Segmented
              aria-label="Text size"
              value={fontPx}
              onValueChange={(v) =>
                setAppearance({ font_scale: Number(v) / 14 })
              }
              options={FONT_SCALES.map((s) => {
                const px = String(Math.round(14 * s))
                return { value: px, label: <span className="num">{px}</span> }
              })}
            />
          </Pref>
          <Pref title="Reduced motion" hint="Turns off animation everywhere">
            <Switch
              aria-label="Reduced motion"
              checked={appearance.reduced_motion}
              onCheckedChange={(v) => setAppearance({ reduced_motion: v })}
            />
          </Pref>
          <Pref title="Reset" hint="Back to the theme's own values" last>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setAppearance({
                  accent_override: DEFAULT_APPEARANCE.accent_override,
                  density: DEFAULT_APPEARANCE.density,
                  radius: DEFAULT_APPEARANCE.radius,
                  font_scale: DEFAULT_APPEARANCE.font_scale,
                  reduced_motion: DEFAULT_APPEARANCE.reduced_motion,
                })
                toast("Back to the theme defaults.")
              }}
            >
              Reset accent, density, radius, size and motion
            </Button>
          </Pref>
        </div>
      </section>

      <section
        className="grid items-start gap-6 lg:grid-cols-2"
        aria-label="Theme files"
      >
        <div className="flex items-start gap-3 rounded-lg border border-dashed border-border-strong p-4">
          <Layers
            className="mt-0.5 size-[18px] shrink-0 text-primary-ink"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <div>
            <b className="font-semibold">
              Themes are data: export, import, or build your own.
            </b>
            <p className="mt-1 text-[0.9rem] text-muted-foreground">
              A theme is one small file of tokens: colours for light and dark,
              two or three typefaces, a corner radius and a shadow style. Every
              screen reads only these tokens, so a new theme needs no code.
            </p>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    downloadJson(
                      `${fileSlug(theme.name)}.theme.json`,
                      await exportTheme(theme.id)
                    )
                  } catch (e) {
                    toast.error((e as Error).message)
                  }
                }}
              >
                <Download aria-hidden="true" />
                Export current
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => fileInput.current?.click()}
              >
                <Upload aria-hidden="true" />
                Import
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept="application/json,.json"
                className="sr-only"
                aria-label="Theme file to import"
                tabIndex={-1}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ""
                  if (f) void files.importFile(f)
                }}
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => void files.buildFrom(theme.id)}
              >
                <Paintbrush aria-hidden="true" />
                Build your own
              </Button>
              <Button size="sm" variant="ghost" asChild>
                <Link
                  to="/theme-studio/$themeId"
                  params={{ themeId: theme.id }}
                >
                  <Pencil aria-hidden="true" />
                  {theme.builtin ? "Open in studio" : "Edit current"}
                </Link>
              </Button>
            </div>
            <p className="mt-2.5 flex items-center gap-1.5 text-xs text-faint">
              <Check className="size-3.5" aria-hidden="true" />
              Build your own copies the current theme into the studio: live
              preview, contrast check, undo and history.
            </p>
          </div>
        </div>
        <div>
          <div className="mb-1.5 eyebrow">Current tokens</div>
          <pre className="overflow-x-auto rounded-lg bg-sunken p-3.5 font-mono text-[0.8rem] leading-[1.55] text-muted-foreground">
            {tokenJson}
          </pre>
        </div>
      </section>
    </div>
  )
}

function Pref({
  title,
  hint,
  children,
  last,
}: {
  title: string
  hint: string
  children: ReactNode
  last?: boolean
}) {
  return (
    <div
      className={cn(
        "grid items-center gap-2 py-3.5 sm:grid-cols-[minmax(0,150px)_minmax(0,1fr)] sm:gap-3.5",
        !last && "border-b border-border"
      )}
    >
      <div>
        <div className="font-semibold">{title}</div>
        <div className="text-[0.82rem] text-faint">{hint}</div>
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

function AccentButton({
  label,
  selected,
  onSelect,
  color,
  children,
}: {
  label: string
  selected: boolean
  onSelect: () => void
  color?: string
  children?: ReactNode
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={label}
      title={label}
      onClick={onSelect}
      className={cn(
        "grid size-[26px] place-items-center rounded-full border-2 border-surface p-0 text-muted-foreground shadow-[0_0_0_1px_var(--t-border)]",
        !color && "bg-sunken",
        selected && "shadow-[0_0_0_2px_var(--t-text)]"
      )}
      style={color ? { background: color } : undefined}
    >
      {children}
    </button>
  )
}
