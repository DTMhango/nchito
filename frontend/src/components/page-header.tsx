import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

type PageHeaderProps = {
  title: ReactNode
  /** Small label above the title ("Kit", "Tailoring · Ziina"). */
  eyebrow?: ReactNode
  description?: ReactNode
  /** Right-aligned controls. */
  actions?: ReactNode
  /** Status chips beside the title. */
  meta?: ReactNode
  className?: string
}

/**
 * The heading block at the top of a view's content. The top bar already names the screen,
 * so this carries the view's own headline ("Morning, Chanda") or a sub-page title.
 */
export function PageHeader({
  title,
  eyebrow,
  description,
  actions,
  meta,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={cn("mb-5 flex flex-wrap items-end gap-x-4 gap-y-2", className)}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <div className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1">
          <h2 className="text-2xl">{title}</h2>
          {meta}
        </div>
        {description && (
          <p className="max-w-[68ch] text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      )}
    </header>
  )
}

/** A section heading inside a view (mockup `.sec-h`). */
export function SectionHeader({
  title,
  aside,
  action,
  className,
  as: As = "h2",
}: {
  title: ReactNode
  aside?: ReactNode
  action?: ReactNode
  className?: string
  as?: "h2" | "h3"
}) {
  return (
    <div
      className={cn(
        "mb-2.5 flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-1",
        className
      )}
    >
      <As className="text-md">{title}</As>
      {aside && <span className="text-sm text-faint">{aside}</span>}
      {action && (
        <span className="ml-auto text-sm whitespace-nowrap">{action}</span>
      )}
    </div>
  )
}
