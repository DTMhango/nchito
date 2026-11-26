import { Link } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { CalendarClock } from "lucide-react"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { upcomingEventsQuery } from "@/features/jobs/schedule/api"
import { ConflictBadge, EventTimes } from "@/features/jobs/schedule/event-times"

/**
 * Interviews in the next stretch (the server's `calendar.upcoming_days`), both zones, with
 * overlap warnings and the proposals still waiting for you to settle a time.
 */
export function UpcomingInterviews() {
  const q = useQuery(upcomingEventsQuery())
  const items = q.data ?? []
  return (
    <section aria-labelledby="interviews-title">
      <SectionHeader
        title={<span id="interviews-title">Upcoming interviews</span>}
      />
      <div className="border-t border-border">
        {q.isPending ? (
          <Skeleton className="mt-2 h-16 w-full" />
        ) : q.isError ? (
          <p role="alert" className="py-3 text-sm text-danger">
            Could not load your interviews.
          </p>
        ) : items.length === 0 ? (
          <EmptyState
            icon={CalendarClock}
            title="No interviews coming up"
            description="Confirmed and proposed interviews show here, in their time zone and yours."
            className="py-6"
          />
        ) : (
          <ul>
            {items.map((e) => (
              <li
                key={e.id}
                className="grid gap-1 border-t border-border row-pad first:border-t-0"
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <Link
                    to="/jobs/$id"
                    params={{ id: e.job_id }}
                    search={{ tab: "schedule" }}
                    className="font-semibold text-primary-ink underline-offset-2 hover:underline"
                  >
                    {e.employer}
                  </Link>
                  <span className="text-sm text-muted-foreground">
                    {e.job_title}
                  </span>
                  {e.status === "proposed" && (
                    <Chip tone="warn">
                      {e.needs_input ? "Needs a time from you" : "Proposed"}
                    </Chip>
                  )}
                  <ConflictBadge event={e} />
                </div>
                {e.status === "proposed" && e.candidates.length > 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {e.candidates.length} possible times from an email. Open the
                    schedule to choose one.
                  </p>
                ) : (
                  <EventTimes event={e} />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
