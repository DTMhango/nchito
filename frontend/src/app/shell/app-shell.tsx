import { useEffect, useState } from "react"
import { Outlet } from "@tanstack/react-router"
import { AddJobDialog } from "./add-job-dialog"
import { CommandPalette } from "./command-palette"
import { MobileTabs } from "./mobile-tabs"
import { Sidebar, useSidebarCollapsed } from "./sidebar"
import { TopBar } from "./top-bar"

/**
 * The signed-in frame (DESIGN 10.2): collapsible sidebar (bottom tabs on phones), top bar
 * with command palette, Add job, the Autopilot switch, theme popover and notifications.
 */
export function AppShell() {
  const [collapsed, toggleCollapsed] = useSidebarCollapsed()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        (e.ctrlKey || e.metaKey) &&
        !e.altKey &&
        e.key.toLowerCase() === "k"
      ) {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  return (
    <div className="grid h-dvh grid-cols-1 grid-rows-[minmax(0,1fr)] pr-[max(16px,env(safe-area-inset-right,0px))] pl-[max(16px,env(safe-area-inset-left,0px))] md:grid-cols-[auto_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only z-50 rounded-sm bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Sidebar collapsed={collapsed} onToggle={toggleCollapsed} />
      <div className="flex min-h-0 min-w-0 flex-col max-md:pb-[calc(60px+env(safe-area-inset-bottom,0px))]">
        <TopBar
          onOpenPalette={() => setPaletteOpen(true)}
          onAddJob={() => setAddOpen(true)}
        />
        <main
          id="main"
          tabIndex={-1}
          className="relative min-h-0 flex-1 overflow-auto outline-none"
        >
          <Outlet />
        </main>
      </div>
      <MobileTabs />
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onAddJob={() => setAddOpen(true)}
      />
      <AddJobDialog open={addOpen} onOpenChange={setAddOpen} />
    </div>
  )
}
