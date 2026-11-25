import { useEffect } from "react"
import { useMatches } from "@tanstack/react-router"
import { Plus, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { KeyHint } from "@/components/key-hint"
import { useAppName } from "@/lib/use-app-name"
import { AutopilotSwitch } from "./autopilot-switch"
import { Notifications } from "./notifications"
import { ThemePopover } from "./theme-popover"

/** Title of the deepest matched route that declares one (staticData.title). */
export function useRouteTitle(): string {
  const matches = useMatches()
  for (let i = matches.length - 1; i >= 0; i--) {
    const t = matches[i].staticData?.title
    if (t) return t
  }
  return ""
}

export function TopBar({
  onOpenPalette,
  onAddJob,
}: {
  onOpenPalette: () => void
  onAddJob: () => void
}) {
  const title = useRouteTitle()
  const appName = useAppName()

  useEffect(() => {
    document.title = title ? `${title} · ${appName}` : appName
  }, [title, appName])

  return (
    <header className="relative flex min-w-0 items-center gap-2 border-b border-border py-3 md:gap-2.5 md:pl-5.5">
      <h1 className="truncate text-[1.15rem] whitespace-nowrap md:text-lg">
        {title}
      </h1>
      {import.meta.env.VITE_MOCK === "1" && (
        <span
          title="Running against the built-in mock backend. Nothing is saved to a server."
          className="rounded-full border border-dashed border-border-strong px-2 py-0.5 eyebrow text-[0.68rem] whitespace-nowrap max-md:hidden"
        >
          Mock data
        </span>
      )}

      <button
        type="button"
        onClick={onOpenPalette}
        aria-label="Search and commands"
        aria-keyshortcuts="Control+K Meta+K"
        className="ml-auto flex h-[34px] min-w-0 items-center gap-2 rounded-sm border border-border bg-surface pr-2 pl-2.5 text-faint hover:border-border-strong max-md:size-[34px] max-md:justify-center max-md:p-0 md:w-[min(300px,32vw)] lg:w-[300px]"
      >
        <Search
          className="size-[15px] shrink-0"
          strokeWidth={1.5}
          aria-hidden="true"
        />
        <span className="flex-1 truncate text-left max-md:hidden">
          Search jobs, screens, commands
        </span>
        <KeyHint keys="Mod K" className="max-md:hidden" />
      </button>

      <Button
        variant="outline"
        onClick={onAddJob}
        aria-label="Add job"
        className="max-md:size-[34px] max-md:px-0"
      >
        <Plus strokeWidth={1.75} aria-hidden="true" />
        <span className="max-md:hidden">Add job</span>
      </Button>
      <AutopilotSwitch />
      <ThemePopover />
      <Notifications />
    </header>
  )
}
