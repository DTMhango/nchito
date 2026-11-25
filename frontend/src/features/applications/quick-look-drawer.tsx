import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowUpRight } from "lucide-react"
import { ScoreRing } from "@/components/score-ring"
import { StagePill } from "@/components/stage-pill"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { timelineQuery, type ApplicationSummary } from "./api"
import { ChannelIcon, CHANNEL_META, NextStep } from "./application-card"
import { daysSince, shortDate } from "./format"
import { PinButton, SnoozeButton } from "./row-actions"

const EVENT_LABEL: Record<string, string> = {
  "stage.changed": "Stage changed",
  "application.created": "Added to applications",
  "application.submitted": "Marked as applied",
  "application.approved": "Packet approved",
  "email.received": "Email received",
}

function eventText(kind: string, detail: Record<string, unknown>) {
  const note = typeof detail.note === "string" ? detail.note : null
  const label =
    EVENT_LABEL[kind] ??
    kind.replace(/[._]/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  return note ? `${label}: ${note}` : label
}

/** Quick look: summary, next step and the last events, with a link to the job page. */
export function QuickLookDrawer({
  app,
  timeZone,
  onClose,
}: {
  app: ApplicationSummary | null
  timeZone?: string
  onClose: () => void
}) {
  return (
    <Sheet open={app !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="gap-0 overflow-y-auto">
        {app && <Body app={app} timeZone={timeZone} />}
      </SheetContent>
    </Sheet>
  )
}

function Body({
  app,
  timeZone,
}: {
  app: ApplicationSummary
  timeZone?: string
}) {
  const events = useQuery(timelineQuery(app.id))
  const last = (events.data ?? []).slice(-5).reverse()
  return (
    <>
      <SheetHeader className="border-b border-border">
        <div className="flex items-start gap-3 pr-8">
          {app.score !== null && <ScoreRing score={app.score} size={44} />}
          <div className="min-w-0">
            <SheetTitle>{app.title}</SheetTitle>
            <SheetDescription>{app.employer}</SheetDescription>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <StagePill stage={app.stage} />
          {app.channel && (
            <span className="inline-flex items-center gap-1">
              <ChannelIcon channel={app.channel} />
              {CHANNEL_META[app.channel].label}
            </span>
          )}
          <span className="num">{daysSince(app.updated_at)}d in stage</span>
          {app.applied_at && (
            <span>Applied {shortDate(app.applied_at, timeZone)}</span>
          )}
        </div>
      </SheetHeader>

      <div className="grid gap-5 p-4">
        <section aria-labelledby="ql-next">
          <h3 id="ql-next" className="mb-1.5 eyebrow">
            Next step
          </h3>
          {app.next_step || app.next_due ? (
            <NextStep app={app} timeZone={timeZone} />
          ) : (
            <p className="text-sm text-faint">Nothing planned.</p>
          )}
          {app.open_pending_actions > 0 && (
            <p className="mt-1 text-sm text-warn">
              {app.open_pending_actions} decision
              {app.open_pending_actions === 1 ? "" : "s"} waiting on you, on
              Today.
            </p>
          )}
        </section>

        <section aria-labelledby="ql-events">
          <h3 id="ql-events" className="mb-1.5 eyebrow">
            Last events
          </h3>
          {events.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : events.isError ? (
            <p className="text-sm text-danger">Couldn't load the timeline.</p>
          ) : last.length === 0 ? (
            <p className="text-sm text-faint">No events yet.</p>
          ) : (
            <ol className="grid gap-2">
              {last.map((ev) => (
                <li key={ev.id} className="text-sm">
                  <span className="mr-2 num text-xs text-faint">
                    {shortDate(ev.created_at, timeZone)}
                  </span>
                  {eventText(ev.kind, ev.detail)}
                  <span className="ml-1 text-xs text-faint">by {ev.actor}</span>
                </li>
              ))}
            </ol>
          )}
        </section>

        <div className="flex flex-wrap gap-2">
          <PinButton app={app} />
          <SnoozeButton app={app} timeZone={timeZone} />
        </div>

        <Button asChild>
          <Link to="/jobs/$id" params={{ id: app.job_id }}>
            Open the full job page
            <ArrowUpRight aria-hidden="true" />
          </Link>
        </Button>
      </div>
    </>
  )
}
