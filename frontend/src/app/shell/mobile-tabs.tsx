import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { Ellipsis } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { LiveSpendMeter } from "@/features/settings/ai/live-spend-meter"
import { cn } from "@/lib/utils"
import { NAV_FOOT, NAV_MAIN, NAV_SETUP, type NavItem } from "./nav"

const tabClass =
  "relative flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-sm py-1.5 text-[0.66rem] font-medium text-muted-foreground no-underline data-[status=active]:bg-primary-soft data-[status=active]:text-foreground data-[status=active]:[&>svg]:text-primary-ink"

/** Phone navigation: a bottom tab bar with the daily screens, and More for the rest. */
export function MobileTabs() {
  const [more, setMore] = useState(false)
  const tabs = NAV_MAIN.filter((n) => n.phone)
  const rest: NavItem[] = [
    ...NAV_MAIN.filter((n) => !n.phone),
    ...NAV_SETUP,
    ...NAV_FOOT,
  ]
  return (
    <>
      <nav
        aria-label="Main navigation"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-surface px-2.5 pt-1.5 pb-[calc(6px+env(safe-area-inset-bottom,0px))] md:hidden"
      >
        {tabs.map((t) => (
          <Link key={t.to} to={t.to} className={tabClass}>
            <t.icon
              className="size-[18px]"
              strokeWidth={1.5}
              aria-hidden="true"
            />
            <span className="max-w-full truncate">{t.label}</span>
          </Link>
        ))}
        <button
          type="button"
          className={cn(tabClass, more && "bg-primary-soft text-foreground")}
          onClick={() => setMore(true)}
          aria-haspopup="dialog"
        >
          <Ellipsis
            className="size-[18px]"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <span>More</span>
        </button>
      </nav>
      <Sheet open={more} onOpenChange={setMore}>
        <SheetContent
          side="bottom"
          className="gap-0 rounded-t-xl pb-[env(safe-area-inset-bottom,0px)]"
        >
          <SheetHeader>
            <SheetTitle className="heading">More</SheetTitle>
            <SheetDescription className="sr-only">
              Other screens
            </SheetDescription>
          </SheetHeader>
          <nav
            aria-label="More screens"
            className="grid grid-cols-3 gap-1 px-4 pb-3"
          >
            {rest.map((t) => (
              <Link
                key={t.to}
                to={t.to}
                onClick={() => setMore(false)}
                className={cn(tabClass, "py-3 text-xs")}
              >
                <t.icon
                  className="size-5"
                  strokeWidth={1.5}
                  aria-hidden="true"
                />
                {t.label}
              </Link>
            ))}
          </nav>
          <div className="px-4 pb-4">
            <LiveSpendMeter />
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
