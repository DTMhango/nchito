import type { ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { ArrowRight, type LucideIcon } from "lucide-react"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { AppPath } from "@/app/shell/nav"
import { Chip } from "./chip"

type EmptyStateProps = {
  icon?: LucideIcon
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}

/** Compact, centred empty state for panels, popovers and lists. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  actions,
  className,
}: EmptyStateProps) {
  return (
    <Empty className={cn("gap-3 px-4 py-7", className)}>
      <EmptyHeader className="gap-1.5">
        {Icon && (
          <EmptyMedia
            variant="icon"
            className="bg-sunken text-muted-foreground"
          >
            <Icon aria-hidden="true" />
          </EmptyMedia>
        )}
        <EmptyTitle className="text-base font-semibold">{title}</EmptyTitle>
        {description && (
          <EmptyDescription className="text-sm text-muted-foreground">
            {description}
          </EmptyDescription>
        )}
      </EmptyHeader>
      {actions && (
        <EmptyContent className="flex-row flex-wrap justify-center gap-2">
          {actions}
        </EmptyContent>
      )}
    </Empty>
  )
}

export type WhatAppears = { icon: LucideIcon; title: string; body: string }

type FirstStep = {
  label: string
  to?: AppPath
  onClick?: () => void
  hint?: ReactNode
}

type ScreenEmptyProps = {
  icon?: LucideIcon
  /** "Matches" */
  title: ReactNode
  /** One or two sentences: what this screen is for. */
  lead: ReactNode
  /** What will appear here once there is data. */
  items?: WhatAppears[]
  /** The one thing to do first. */
  firstStep?: FirstStep
  /** Status chip text, e.g. "Nothing yet". */
  status?: string
  className?: string
  children?: ReactNode
}

/**
 * Route-level empty state: says what will appear and what to do first (no placeholder text).
 * Left-aligned like the mockup's planned screens, with a two-column list of what's coming.
 */
export function ScreenEmpty({
  icon: Icon,
  title,
  lead,
  items,
  firstStep,
  status = "Nothing here yet",
  className,
  children,
}: ScreenEmptyProps) {
  return (
    <section
      className={cn("max-w-[760px]", className)}
      aria-labelledby="screen-empty-title"
    >
      <div className="mb-4.5 grid gap-2">
        <div className="flex items-center gap-2">
          {Icon && (
            <span className="grid size-[30px] place-items-center rounded-sm bg-primary-soft text-primary-ink">
              <Icon
                className="size-[18px]"
                strokeWidth={1.5}
                aria-hidden="true"
              />
            </span>
          )}
          <Chip tone="info">{status}</Chip>
        </div>
        <h2 id="screen-empty-title" className="text-xl">
          {title}
        </h2>
        <p className="max-w-[62ch] text-muted-foreground">{lead}</p>
      </div>

      {firstStep && (
        <div className="mb-6 flex flex-wrap items-center gap-3">
          {firstStep.to ? (
            <Button asChild>
              <Link to={firstStep.to}>
                {firstStep.label}
                <ArrowRight data-icon="inline-end" aria-hidden="true" />
              </Link>
            </Button>
          ) : (
            <Button onClick={firstStep.onClick}>
              {firstStep.label}
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
          )}
          {firstStep.hint && (
            <span className="text-sm text-faint">{firstStep.hint}</span>
          )}
        </div>
      )}

      {items && items.length > 0 && (
        <>
          <div className="mb-2 eyebrow">What will appear here</div>
          <ul className="grid grid-cols-1 border-t border-border sm:grid-cols-2">
            {items.map((it) => (
              <li
                key={it.title}
                className="grid grid-cols-[30px_minmax(0,1fr)] gap-3 border-b border-border py-4 pr-4 sm:even:border-l sm:even:pl-4"
              >
                <span className="grid size-[30px] place-items-center rounded-sm bg-sunken text-muted-foreground">
                  <it.icon
                    className="size-[18px]"
                    strokeWidth={1.5}
                    aria-hidden="true"
                  />
                </span>
                <div>
                  <b className="mb-0.5 block font-semibold">{it.title}</b>
                  <p className="text-[0.9rem] text-muted-foreground">
                    {it.body}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {children}
    </section>
  )
}
