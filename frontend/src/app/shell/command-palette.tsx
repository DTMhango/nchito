import { useNavigate } from "@tanstack/react-router"
import {
  CirclePause,
  CirclePlay,
  LayoutGrid,
  LogOut,
  Monitor,
  Moon,
  Palette,
  Plus,
  Sparkles,
  Sun,
  type LucideIcon,
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command"
import { useTheme } from "@/themes/provider"
import { useSignOut } from "@/features/auth/use-sign-out"
import {
  KIT_SECTIONS,
  NAV_FOOT,
  NAV_MAIN,
  NAV_SETUP,
  PALETTE_PLACES,
  SETTINGS_SECTIONS,
  type AppPath,
} from "./nav"
import { useAutopilot } from "./autopilot-switch"

type Props = {
  open: boolean
  onOpenChange: (o: boolean) => void
  onAddJob: () => void
}

/** Ctrl K: go anywhere, switch theme, add a job, pause Autopilot. */
export function CommandPalette({ open, onOpenChange, onAddJob }: Props) {
  const navigate = useNavigate()
  const { themes, theme, setAppearance } = useTheme()
  const autopilot = useAutopilot()
  const signOut = useSignOut()

  const run = (fn: () => void) => {
    onOpenChange(false)
    fn()
  }
  const go = (to: AppPath) => run(() => void navigate({ to }))

  const screens = [...NAV_MAIN, ...NAV_SETUP, ...NAV_FOOT]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="top-[18%] translate-y-0 overflow-hidden pop-surface p-0 sm:max-w-[560px]"
      >
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">
          Search screens and commands. Use the arrow keys and Enter.
        </DialogDescription>
        <Command
          loop
          label="Search screens and commands"
          className="rounded-none! bg-transparent"
        >
          <CommandInput
            placeholder="Search screens and commands"
            aria-label="Search screens and commands"
          />
          <CommandList className="max-h-[min(60vh,420px)]">
            <CommandEmpty>
              Nothing matches. Try a screen name, a theme or "add".
            </CommandEmpty>
            <CommandGroup heading="Actions">
              <Item
                icon={Plus}
                label="Add job"
                keywords={["capture", "paste", "link", "new"]}
                onSelect={() => run(onAddJob)}
              />
              {autopilot.state.paused ? (
                <Item
                  icon={CirclePlay}
                  label="Resume Autopilot"
                  keywords={["start", "unpause"]}
                  onSelect={() => run(() => autopilot.setPaused(false))}
                />
              ) : (
                <Item
                  icon={CirclePause}
                  label="Pause Autopilot"
                  keywords={["stop", "halt"]}
                  onSelect={() => run(() => autopilot.setPaused(true))}
                />
              )}
              <Item
                icon={Sparkles}
                label="Set-up guide"
                keywords={["onboarding", "wizard", "import kit"]}
                onSelect={() => go("/onboarding")}
              />
            </CommandGroup>
            <CommandGroup heading="Go to">
              {screens.map((s) => (
                <Item
                  key={s.to}
                  icon={s.icon}
                  label={s.label}
                  keywords={s.keywords}
                  onSelect={() => go(s.to)}
                />
              ))}
              {PALETTE_PLACES.map((s) => (
                <Item
                  key={s.label}
                  icon={s.icon}
                  label={s.label}
                  keywords={s.keywords}
                  onSelect={() =>
                    run(() => void navigate({ to: s.to, search: s.search }))
                  }
                />
              ))}
              <Item
                icon={Palette}
                label="Theme studio"
                hint={theme.name}
                keywords={["theme", "colours", "colors", "edit theme", "brand"]}
                onSelect={() =>
                  run(
                    () =>
                      void navigate({
                        to: "/theme-studio/$themeId",
                        params: { themeId: theme.id },
                      })
                  )
                }
              />
              {KIT_SECTIONS.map((s) => (
                <Item
                  key={s.to}
                  label={`Kit: ${s.label}`}
                  onSelect={() => go(s.to)}
                />
              ))}
              {SETTINGS_SECTIONS.map((s) => (
                <Item
                  key={s.to}
                  label={`Settings: ${s.label}`}
                  onSelect={() => go(s.to)}
                />
              ))}
              {import.meta.env.DEV && (
                <Item
                  icon={LayoutGrid}
                  label="Component gallery (dev)"
                  onSelect={() => go("/dev/components")}
                />
              )}
            </CommandGroup>
            <CommandGroup heading="Theme">
              {themes.map((t) => (
                <Item
                  key={t.id}
                  icon={Palette}
                  label={`Theme: ${t.name}`}
                  hint={t.id === theme.id ? "In use" : undefined}
                  keywords={["theme", "skin", t.description ?? ""]}
                  onSelect={() => run(() => setAppearance({ theme_id: t.id }))}
                />
              ))}
              <Item
                icon={Sun}
                label="Mode: Light"
                keywords={["theme"]}
                onSelect={() => run(() => setAppearance({ mode: "light" }))}
              />
              <Item
                icon={Moon}
                label="Mode: Dark"
                keywords={["theme", "night"]}
                onSelect={() => run(() => setAppearance({ mode: "dark" }))}
              />
              <Item
                icon={Monitor}
                label="Mode: Follow system"
                keywords={["theme", "auto"]}
                onSelect={() => run(() => setAppearance({ mode: "system" }))}
              />
            </CommandGroup>
            <CommandGroup heading="Account">
              <Item
                icon={LogOut}
                label="Sign out"
                keywords={["log out", "logout"]}
                onSelect={() => run(signOut)}
              />
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  )
}

function Item({
  icon: Icon,
  label,
  hint,
  keywords,
  onSelect,
}: {
  icon?: LucideIcon
  label: string
  hint?: string
  keywords?: string[]
  onSelect: () => void
}) {
  return (
    <CommandItem value={label} keywords={keywords} onSelect={onSelect}>
      {Icon && <Icon strokeWidth={1.5} aria-hidden="true" />}
      <span>{label}</span>
      {hint && <CommandShortcut>{hint}</CommandShortcut>}
    </CommandItem>
  )
}
