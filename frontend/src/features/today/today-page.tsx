import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { CalendarDays, CheckCircle2, Inbox, Layers, Radar } from "lucide-react"
import { Button } from "@/components/ui/button"
import { CountBadge } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { SpendMeter } from "@/components/spend-meter"
import { View } from "@/components/view"
import { meQuery } from "@/lib/api/endpoints"

function greeting(hour: number) {
  if (hour < 12) return "Morning"
  if (hour < 18) return "Afternoon"
  return "Evening"
}

function nowIn(timezone: string) {
  const d = new Date()
  try {
    const hour = Number(
      new Intl.DateTimeFormat("en-GB", {
        hour: "numeric",
        hourCycle: "h23",
        timeZone: timezone,
      }).format(d)
    )
    const date = new Intl.DateTimeFormat("en-GB", {
      weekday: "long",
      day: "numeric",
      month: "long",
      timeZone: timezone,
    }).format(d)
    const time = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: timezone,
    }).format(d)
    const city = timezone.split("/").pop()?.replace(/_/g, " ") ?? timezone
    return { hour, line: `${date} · ${city} ${time}` }
  } catch {
    return { hour: d.getHours(), line: d.toDateString() }
  }
}

/**
 * Today (DESIGN 10.3, 18.4): what needs you first, then the last sweep, new matches and
 * what's coming. Decisions sit first on a phone; the funnel, spend and source health below.
 */
export function TodayPage() {
  const me = useQuery(meQuery())
  const tz = me.data?.timezone ?? "Africa/Lusaka"
  const { hour, line } = nowIn(tz)

  return (
    <View>
      <div className="mb-5 flex flex-wrap items-baseline gap-x-3.5 gap-y-1.5">
        <h2 className="text-2xl">
          {greeting(hour)}
          {me.data?.display_name ? `, ${me.data.display_name}` : ""}
        </h2>
        <span className="text-muted-foreground">{line}</span>
      </div>

      <div className="grid items-start gap-7 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="grid min-w-0 gap-7">
          <section aria-labelledby="needs-title" className="elev py-1.5">
            <div className="flex items-center gap-2.5 px-4.5 pt-2.5 pb-2">
              <h2 id="needs-title" className="text-[1.12rem]">
                Needs you
              </h2>
              <CountBadge>0</CountBadge>
              <span className="ml-auto text-[0.84rem] text-faint">
                Nothing is waiting on you
              </span>
            </div>
            <div className="border-t border-border px-4.5 py-6 text-center text-muted-foreground">
              <CheckCircle2
                className="mx-auto mb-1.5 size-5 text-good"
                strokeWidth={1.5}
                aria-hidden="true"
              />
              <p className="font-medium text-foreground">All clear.</p>
              <p className="mx-auto mt-1 max-w-[52ch] text-sm">
                Approvals, sign-in requests, new form questions and unconfirmed
                submissions land here, grouped by the decision they need from
                you and sorted by deadline.
              </p>
            </div>
          </section>

          <section aria-labelledby="sweep-title">
            <SectionHeader
              title={<span id="sweep-title">Last sweep</span>}
              aside="No sweeps yet"
              action={<Link to="/autopilot">Run history</Link>}
            />
            <div className="rounded-lg border border-dashed border-border-strong">
              <EmptyState
                icon={Radar}
                title="Nothing has been swept yet"
                description="Once a campaign runs, this shows how many roles were found, how many were new, passed your filters, scored above the line, were tailored and applied to, with the health of each source."
                actions={
                  <Button asChild size="sm">
                    <Link to="/onboarding">Start the set-up guide</Link>
                  </Button>
                }
              />
            </div>
          </section>

          <section aria-labelledby="top-title">
            <SectionHeader
              title={<span id="top-title">Top new matches</span>}
              action={<Link to="/matches">All matches</Link>}
            />
            <div className="border-t border-border">
              <EmptyState
                icon={Inbox}
                title="No new matches"
                description="The best new roles from the latest sweep appear here with their score, pay and deadline. Add one by hand with Add job."
                className="py-6"
              />
            </div>
          </section>
        </div>

        <div className="grid min-w-0 gap-7">
          <section aria-labelledby="coming-title">
            <SectionHeader title={<span id="coming-title">Coming up</span>} />
            <div className="border-t border-border">
              <EmptyState
                icon={CalendarDays}
                title="Nothing scheduled"
                description="Deadlines, follow-ups and interviews for the next two weeks, in your time zone."
                className="py-6"
              />
            </div>
          </section>

          <section aria-labelledby="sent-title">
            <SectionHeader
              title={<span id="sent-title">Applications sent</span>}
            />
            <div className="flex items-baseline gap-2">
              <span className="num text-[1.6rem] font-semibold">0</span>
              <span className="text-muted-foreground">in the last 14 days</span>
            </div>
            <p className="mt-1 text-sm text-faint">
              A day-by-day chart appears after your first application.
            </p>
          </section>

          <section aria-labelledby="spend-title" className="grid gap-2.5">
            <SectionHeader
              title={<span id="spend-title">AI spend</span>}
              className="mb-0"
            />
            <SpendMeter spentMinor={0} capMinor={null} />
          </section>

          <aside className="flex items-start gap-3 rounded-lg border border-dashed border-border-strong p-4">
            <Layers
              className="mt-0.5 size-[18px] shrink-0 text-primary-ink"
              strokeWidth={1.5}
              aria-hidden="true"
            />
            <div>
              <b className="font-semibold">Start with your Kit.</b>
              <p className="mt-1 text-[0.9rem] text-muted-foreground">
                Bring your CVs or an old kit. Everything imported waits for your
                review before it can drive anything automatic.
              </p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                <Button asChild size="sm">
                  <Link to="/onboarding" search={{ step: 3 }}>
                    Bring your material
                  </Link>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link to="/kit/library">Open the Kit</Link>
                </Button>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </View>
  )
}
