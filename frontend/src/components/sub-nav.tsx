import type { ComponentProps, ReactNode } from "react"
import { createLink } from "@tanstack/react-router"
import { cn } from "@/lib/utils"

/** Horizontal underline tabs made of links (mockup `.tabs`). Scrolls sideways on phones. */
export function SubNav({
  label,
  children,
  className,
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <nav
      aria-label={label}
      className={cn(
        "flex [scrollbar-width:none] gap-0.5 overflow-x-auto border-b border-border",
        className
      )}
    >
      {children}
    </nav>
  )
}

function TabAnchor({ className, ...props }: ComponentProps<"a">) {
  return (
    <a
      className={cn(
        "-mb-px inline-flex items-center gap-1.5 border-b-2 border-transparent px-2.5 pt-2 pb-2.5 text-[0.88rem] font-semibold whitespace-nowrap text-muted-foreground no-underline hover:text-foreground",
        "data-[status=active]:border-primary data-[status=active]:text-foreground",
        className
      )}
      {...props}
    />
  )
}

/** A typed router link styled as a tab. Accepts every <Link> prop (to, params, search). */
export const SubNavLink = createLink(TabAnchor)

function SideAnchor({ className, ...props }: ComponentProps<"a">) {
  return (
    <a
      className={cn(
        "flex items-center gap-2 rounded-sm px-2.5 py-1.5 font-medium whitespace-nowrap text-muted-foreground no-underline hover:bg-sunken hover:text-foreground",
        "data-[status=active]:bg-surface data-[status=active]:text-foreground data-[status=active]:shadow-sm data-[status=active]:outline-1 data-[status=active]:-outline-offset-1 data-[status=active]:outline-border",
        className
      )}
      {...props}
    />
  )
}

/** Vertical section link (Settings). */
export const SideNavLink = createLink(SideAnchor)

/** Small tab count, e.g. "New 12". */
export function TabCount({ children }: { children: ReactNode }) {
  return <span className="num text-xs font-medium text-faint">{children}</span>
}
