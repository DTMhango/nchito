import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  CalendarClock,
  CalendarDays,
  Inbox,
  MessageSquareReply,
  Radar,
  Video,
  type LucideIcon,
} from "lucide-react"
import { EmptyState } from "@/components/empty-state"
import { FunnelStrip } from "@/components/funnel-strip"
import { SectionHeader } from "@/components/page-header"
import { ScoreRing } from "@/components/score-ring"
import { Sparkbar } from "@/components/sparkbar"
import { SpendMeter } from "@/components/spend-meter"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import {
  applicationsQuery,
  topMatchesQuery,
  type ApplicationSummary,
  type JobSummary,
  type TodayOut,
} from "@/features/applications/api"
import {
  daysUntil,
  dueLabel,
  shortDate,
  todayIn,
} from "@/features/applications/format"

const FUNNEL_LABELS: Record<string, string> = {
  found: "Found",
  new: "New",
  passed_filters: "Passed filters",
  above_threshold: "Above threshold",
  tailored: "Tailored",
  applied: "Applied",
}
const label = (s: string) =>
  FUNNEL_LABELS[s] ??
  s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())

const HEALTH: Record<
  TodayOut["sources"][number]["status"],
  { text: string; dot: string }
> = {
  ok: { text: "Healthy", dot: "bg-good" },
  degraded: { text: "Slow or partial", dot: "bg-warn" },
  failing: { text: "Failing", dot: "bg-danger" },
  unknown: { text: "No data yet", dot: "bg-faint" },
}

export const sweepFailed = (t: TodayOut) =>
  t.sources.some((s) => s.status === "failing" || s.status === "degraded")

export function SweepSection({ today }: { today: TodayOut }) {
  return (
    <section aria-labelledby="sweep-title">
      <SectionHeader
        title={<span id="sweep-title">Last sweep</span>}
        aside={today.last_sweep_run_id ? undefined : "No sweeps yet"}
        action={<Link to="/autopilot">Run history</Link>}
      />
      {today.funnel.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border-strong">
          <EmptyState
            icon={Radar}
            title="Nothing has been swept yet"
            description="Once a campaign runs, this shows how many roles were found, how many were new, passed your filters, scored above the line, were tailored and applied to, with the health of each source."
          />
        </div>
      ) : (
        <FunnelStrip
          steps={today.funnel.map((f) => ({
            label: label(f.stage),
            value: f.count,
          }))}
        />
      )}
      {today.sources.length > 0 && (
        <ul
          aria-label="Source health"
          className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-[0.86rem] text-muted-foreground"
        >
          {today.sources.map((s) => (
            <li key={s.source_id} className="inline-flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className={cn("size-2 rounded-full", HEALTH[s.status].dot)}
              />
              {s.name}
              <span
                className={cn(
                  "text-xs",
                  s.status === "ok" ? "sr-only" : "text-faint"
                )}
              >
                {HEALTH[s.status].text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function TopMatchesSection({ ids }: { ids: string[] }) {
  const q = useQuery(topMatchesQuery())
  const all = q.data?.items ?? []
  const ranked = ids.length
    ? [...all].sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id))
    : all
  return (
    <section aria-labelledby="top-title">
      <SectionHeader
        title={<span id="top-title">Top new matches</span>}
        action={<Link to="/matches">All matches</Link>}
      />
      <div className="border-t border-border">
        {q.isPending ? (
          <Skeleton className="my-3 h-12 w-full" />
        ) : ranked.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title="No new matches"
            description="The best new roles from the latest sweep appear here with their score, pay and deadline. Add one by hand with Add job."
            className="py-6"
          />
        ) : (
          <ul>
            {ranked.slice(0, 5).map((j) => (
              <MatchRow key={j.id} job={j} />
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

function MatchRow({ job }: { job: JobSummary }) {
  const place = job.location.city ?? job.location.raw ?? job.location.country
  return (
    <li className="border-b border-border">
      <Link
        to="/jobs/$id"
        params={{ id: job.id }}
        className="grid grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 row-pad text-foreground no-underline hover:bg-sunken"
      >
        {job.best_score != null ? (
          <ScoreRing score={job.best_score} />
        ) : (
          <span />
        )}
        <span className="min-w-0">
          <span className="block truncate font-semibold">{job.title}</span>
          <span className="block truncate text-[0.88rem] text-muted-foreground">
            {job.employer}
            {place ? ` · ${place}` : ""}
          </span>
        </span>
        {job.deadline.state === "dated" && job.deadline.on && (
          <span className="num text-xs whitespace-nowrap text-faint">
            Closes {shortDate(job.deadline.on)}
          </span>
        )}
      </Link>
    </li>
  )
}

const UPCOMING_ICON: Record<
  TodayOut["upcoming"][number]["kind"],
  { icon: LucideIcon; text: string }
> = {
  deadline: { icon: CalendarClock, text: "Deadline" },
  follow_up: { icon: MessageSquareReply, text: "Follow-up" },
  interview: { icon: Video, text: "Interview" },
}

export function UpcomingSection({
  items,
  timeZone,
}: {
  items: TodayOut["upcoming"]
  timeZone?: string
}) {
  const sorted = [...items].sort((a, b) => a.at.localeCompare(b.at))
  return (
    <section aria-labelledby="coming-title">
      <SectionHeader title={<span id="coming-title">Coming up</span>} />
      <div className="border-t border-border">
        {sorted.length === 0 ? (
          <EmptyState
            icon={CalendarDays}
            title="Nothing scheduled"
            description="Deadlines, follow-ups and interviews for the next two weeks, in your time zone."
            className="py-6"
          />
        ) : (
          <ul>
            {sorted.map((u, i) => {
              const m = UPCOMING_ICON[u.kind]
              const days = daysUntil(u.at, timeZone)
              const body = (
                <>
                  <m.icon
                    className="size-4 shrink-0 text-muted-foreground"
                    strokeWidth={1.5}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="sr-only">{m.text}: </span>
                    <span className="block truncate">{u.title}</span>
                  </span>
                  <span
                    className={cn(
                      "num text-xs whitespace-nowrap",
                      days <= 1 ? "text-warn" : "text-faint"
                    )}
                  >
                    {shortDate(u.at, timeZone)}, {dueLabel(days)}
                  </span>
                </>
              )
              return (
                <li key={i} className="border-b border-border">
                  {u.job_id ? (
                    <Link
                      to="/jobs/$id"
                      params={{ id: u.job_id }}
                      className="flex items-center gap-2.5 row-pad text-foreground no-underline hover:bg-sunken"
                    >
                      {body}
                    </Link>
                  ) : (
                    <div className="flex items-center gap-2.5 row-pad">
                      {body}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}

const DAYS = 14

/** Applications per day over the last 14 days, in the owner's zone. */
export function perDay(
  apps: ApplicationSummary[],
  timeZone?: string,
  now = new Date()
) {
  const keys = Array.from({ length: DAYS }, (_, i) =>
    todayIn(timeZone, new Date(now.getTime() - (DAYS - 1 - i) * 86_400_000))
  )
  const counts = new Map(keys.map((k) => [k, 0]))
  for (const a of apps) {
    if (!a.applied_at) continue
    const k = todayIn(timeZone, new Date(a.applied_at))
    if (counts.has(k)) counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  return { keys, values: keys.map((k) => counts.get(k) ?? 0) }
}

export function SentSection({ timeZone }: { timeZone?: string }) {
  const q = useQuery(applicationsQuery())
  const { keys, values } = perDay(q.data?.items ?? [], timeZone)
  const total = values.reduce((a, b) => a + b, 0)
  return (
    <section aria-labelledby="sent-title">
      <SectionHeader title={<span id="sent-title">Applications sent</span>} />
      <div className="mb-2 flex items-baseline gap-2">
        <span className="num text-[1.6rem] font-semibold">{total}</span>
        <span className="text-muted-foreground">in the last 14 days</span>
      </div>
      {total === 0 ? (
        <p className="text-sm text-faint">
          A day-by-day chart appears after your first application.
        </p>
      ) : (
        <Sparkbar
          values={values}
          unit="sent"
          edgeLabels={[
            shortDate(keys[0], "UTC"),
            shortDate(keys[DAYS - 1], "UTC"),
          ]}
          label={`Applications sent per day, ${shortDate(keys[0], "UTC")} to ${shortDate(keys[DAYS - 1], "UTC")}`}
        />
      )}
    </section>
  )
}

export function SpendSection({ spend }: { spend: TodayOut["spend"] }) {
  return (
    <section aria-labelledby="spend-title" className="grid gap-2.5">
      <SectionHeader
        title={<span id="spend-title">AI spend</span>}
        className="mb-0"
      />
      <SpendMeter
        spentMinor={spend.month_to_date_minor}
        capMinor={spend.cap_minor}
        currency={spend.currency}
      />
    </section>
  )
}

export function FailedBlock({
  what,
  onRetry,
}: {
  what: string
  onRetry: () => void
}) {
  return (
    <div role="alert" className="text-sm text-danger">
      Couldn't load {what}.{" "}
      <Button variant="link" size="xs" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}
