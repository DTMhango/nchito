import type { ReactNode } from "react"
import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

export type Severity = "good" | "warn" | "danger" | "info" | "neutral"

const SEVERITY_TEXT: Record<Severity, string> = {
  good: "Ready",
  warn: "Attention",
  danger: "Blocked",
  info: "Question",
  neutral: "",
}

type SeverityItemProps = {
  severity: Severity
  icon?: LucideIcon
  title: ReactNode
  meta?: ReactNode
  /** "12 min ago" */
  age?: ReactNode
  /** Buttons, right-aligned. Put the primary action last. */
  actions?: ReactNode
  /** Expands below the row (an inline answer field, a list of affected roles). */
  children?: ReactNode
  className?: string
}

/**
 * A row in a "needs you" list: a coloured stripe for severity, an icon, what needs doing,
 * and the actions. Used on Today, the Action centre and job pages.
 */
export function SeverityItem({
  severity,
  icon: Icon,
  title,
  meta,
  age,
  actions,
  children,
  className,
}: SeverityItemProps) {
  return (
    <div
      data-slot="severity-item"
      data-severity={severity}
      className={cn(
        "grid grid-cols-[4px_minmax(0,1fr)] items-center gap-3 border-t border-border px-3.5 row-pad-lg first:border-t-0 sm:grid-cols-[4px_30px_minmax(0,1fr)_auto] sm:px-4.5",
        className
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-[30px] w-1 self-center rounded-full",
          severity === "good" && "bg-good",
          severity === "warn" && "bg-warn",
          severity === "danger" && "bg-danger",
          severity === "info" && "bg-info",
          severity === "neutral" && "bg-faint"
        )}
      />
      <span className="hidden size-[30px] place-items-center rounded-sm bg-sunken text-muted-foreground sm:grid">
        {Icon && (
          <Icon className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
        )}
      </span>
      <div className="min-w-0">
        <div className="font-semibold">
          {SEVERITY_TEXT[severity] && (
            <span className="sr-only">{SEVERITY_TEXT[severity]}: </span>
          )}
          {title}
        </div>
        {meta && (
          <div className="mt-px text-[0.9rem] text-muted-foreground">
            {meta}
          </div>
        )}
      </div>
      {(actions || age) && (
        <div className="col-start-2 flex flex-wrap items-center gap-1.5 sm:col-start-auto sm:flex-nowrap">
          {age && (
            <span className="mr-1 text-xs whitespace-nowrap text-faint">
              {age}
            </span>
          )}
          {actions}
        </div>
      )}
      {children && (
        <div className="col-start-2 flex flex-wrap gap-2 sm:col-start-3 sm:col-end-[-1]">
          {children}
        </div>
      )}
    </div>
  )
}
