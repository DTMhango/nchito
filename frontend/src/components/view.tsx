import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/**
 * Content frame for a screen inside the shell. `flush` removes padding for full-height
 * layouts such as SplitView.
 */
export function View({
  children,
  className,
  flush = false,
}: {
  children: ReactNode
  className?: string
  flush?: boolean
}) {
  return (
    <div
      className={cn(
        "min-w-0 animate-view-in",
        flush ? "h-full" : "pt-4 pb-10 md:pt-5.5 md:pr-1 md:pl-5.5",
        className
      )}
    >
      {children}
    </div>
  )
}
