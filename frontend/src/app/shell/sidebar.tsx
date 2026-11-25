import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { PanelLeft } from "lucide-react"
import { BrandMark } from "@/components/brand-mark"
import { SpendMeter } from "@/components/spend-meter"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { useAppName } from "@/lib/use-app-name"
import { NAV_FOOT, NAV_MAIN, NAV_SETUP, type NavItem } from "./nav"

const KEY = "nchito.sidebar.collapsed"

export function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(KEY)
      if (v !== null) return v === "1"
    } catch {
      /* ignore */
    }
    return typeof window !== "undefined" && window.innerWidth < 1100
  })
  const toggle = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(KEY, c ? "0" : "1")
      } catch {
        /* ignore */
      }
      return !c
    })
  return [collapsed, toggle] as const
}

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const appName = useAppName()
  return (
    <aside
      aria-label="Main navigation"
      data-collapsed={collapsed || undefined}
      className={cn(
        "group/side flex min-w-0 flex-col gap-4.5 border-r border-border py-3.5 pr-3 transition-[width] duration-200 max-md:hidden",
        collapsed ? "w-16" : "w-[228px]"
      )}
    >
      <div
        className={cn(
          "flex min-h-[34px] items-center gap-2.5 px-2 py-0.5",
          collapsed && "flex-col gap-2 p-0"
        )}
      >
        <BrandMark />
        {!collapsed && (
          <span className="truncate heading text-[1.2rem] font-bold">
            {appName}
          </span>
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(
            "grid place-items-center rounded-sm p-1.5 text-faint hover:bg-sunken hover:text-foreground",
            !collapsed && "ml-auto"
          )}
        >
          <PanelLeft
            className="size-[18px]"
            strokeWidth={1.5}
            aria-hidden="true"
          />
        </button>
      </div>

      <nav className="flex flex-col gap-0.5" aria-label="Screens">
        {NAV_MAIN.map((item) => (
          <SideLink key={item.to} item={item} collapsed={collapsed} />
        ))}
        <div role="presentation" className="mx-2 my-2 h-px bg-border" />
        {NAV_SETUP.map((item) => (
          <SideLink key={item.to} item={item} collapsed={collapsed} />
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-3">
        {NAV_FOOT.map((item) => (
          <SideLink key={item.to} item={item} collapsed={collapsed} />
        ))}
        {!collapsed && <SpendMeter spentMinor={0} capMinor={null} />}
      </div>
    </aside>
  )
}

function SideLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const link = (
    <Link
      to={item.to}
      aria-label={collapsed ? item.label : undefined}
      className={cn(
        "relative flex min-w-0 items-center gap-2.75 rounded-sm px-2.5 py-1.75 font-medium text-muted-foreground no-underline hover:bg-sunken hover:text-foreground",
        "data-[status=active]:bg-surface data-[status=active]:text-foreground data-[status=active]:shadow-sm data-[status=active]:outline-1 data-[status=active]:-outline-offset-1 data-[status=active]:outline-border",
        "data-[status=active]:[&>svg]:text-primary-ink",
        collapsed && "justify-center px-0 py-2.25"
      )}
    >
      <item.icon
        className="size-[18px] shrink-0"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      {!collapsed && (
        <span className="min-w-0 flex-1 truncate">{item.label}</span>
      )}
    </Link>
  )
  if (!collapsed) return link
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{item.label}</TooltipContent>
    </Tooltip>
  )
}
