import { BellRing, Globe, Hand, Mail, Pin, type LucideIcon } from "lucide-react"
import { KanbanCard } from "@/components/kanban-board"
import { ScoreRing } from "@/components/score-ring"
import { cn } from "@/lib/utils"
import type { ApplicationSummary, Channel } from "./api"
import { daysSince, daysUntil, dueLabel, shortDate } from "./format"

export const CHANNEL_META: Record<
  Channel,
  { label: string; icon: LucideIcon }
> = {
  email: { label: "Email", icon: Mail },
  browser: { label: "Browser", icon: Globe },
  manual: { label: "By hand", icon: Hand },
}

export function ChannelIcon({
  channel,
  className,
}: {
  channel: ApplicationSummary["channel"]
  className?: string
}) {
  if (!channel) return null
  const m = CHANNEL_META[channel]
  return (
    <span title={m.label} className={cn("inline-flex", className)}>
      <m.icon className="size-3.5" strokeWidth={1.5} aria-hidden="true" />
      <span className="sr-only">{m.label}</span>
    </span>
  )
}

/** Next-step line with an overdue/soon tone. */
export function NextStep({
  app,
  timeZone,
}: {
  app: ApplicationSummary
  timeZone?: string
}) {
  if (!app.next_step && !app.next_due) return null
  const days = app.next_due ? daysUntil(app.next_due, timeZone) : null
  return (
    <span
      className={cn(
        "text-[0.82rem]",
        days !== null && days < 0
          ? "text-danger"
          : days !== null && days <= 2
            ? "text-warn"
            : "text-muted-foreground"
      )}
    >
      {app.next_step ?? "Next step"}
      {app.next_due && (
        <>
          {" · "}
          <span className="num">
            {shortDate(app.next_due)}, {dueLabel(days ?? 0)}
          </span>
        </>
      )}
    </span>
  )
}

/** A card on the board: employer, role, score, channel, days in stage, next step. */
export function ApplicationCard({
  app,
  timeZone,
}: {
  app: ApplicationSummary
  timeZone?: string
}) {
  const days = daysSince(app.updated_at)
  return (
    <KanbanCard className="gap-1.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1 font-semibold">
            <span className="truncate">{app.employer}</span>
            {app.pinned && (
              <Pin
                className="size-3 shrink-0 text-primary-ink"
                strokeWidth={1.5}
                aria-label="Pinned"
              />
            )}
          </div>
          <div className="truncate text-[0.88rem] text-muted-foreground">
            {app.title}
          </div>
        </div>
        {app.score !== null && <ScoreRing score={app.score} size={30} />}
      </div>
      <div className="flex items-center gap-2 text-xs text-faint">
        <ChannelIcon channel={app.channel} />
        <span className="num">
          {days === 0 ? "Today" : `${days}d`} in stage
        </span>
        {app.open_pending_actions > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 text-warn">
            <BellRing className="size-3" strokeWidth={1.5} aria-hidden="true" />
            Needs you
          </span>
        )}
      </div>
      <NextStep app={app} timeZone={timeZone} />
    </KanbanCard>
  )
}
