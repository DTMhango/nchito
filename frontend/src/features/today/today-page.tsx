import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { View } from "@/components/view"
import { todayQuery } from "@/features/applications/api"
import { meQuery } from "@/lib/api/endpoints"
import { cn } from "@/lib/utils"
import { NeedsYou } from "./needs-you"
import {
  FailedBlock,
  SentSection,
  SpendSection,
  SweepSection,
  TopMatchesSection,
  UpcomingSection,
  sweepFailed,
} from "./today-sections"
import { useLiveUpdates } from "./use-live-updates"

function greeting(hour: number) {
  if (hour < 12) return "Morning"
  if (hour < 18) return "Afternoon"
  return "Evening"
}

/** Hour, long date and clock in the owner's zone. */
export function nowIn(timezone: string | undefined, d = new Date()) {
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
    const city = timezone?.split("/").pop()?.replace(/_/g, " ")
    return { hour, line: `${date} · ${city ? `${city} ` : ""}${time}` }
  } catch {
    return { hour: d.getHours(), line: d.toDateString() }
  }
}

/**
 * Today (DESIGN 10.3, 18.4): decisions first, then the last sweep, new matches and what's
 * coming. On a phone only the decisions show until you open "Everything else", unless a
 * source has failed.
 */
export function TodayPage() {
  const me = useQuery(meQuery())
  const today = useQuery(todayQuery())
  useLiveUpdates()
  const tz = me.data?.timezone
  const { hour, line } = nowIn(tz)
  const failed = today.data ? sweepFailed(today.data) : false
  const [more, setMore] = useState(false)
  const show = more || failed
  const hideOnPhone = show ? undefined : "max-md:hidden"

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
        <div className="min-w-0 xl:col-start-1 xl:row-start-1">
          <NeedsYou />
        </div>

        {failed && (
          <p
            role="status"
            className="flex items-center gap-2 text-sm text-warn md:hidden"
          >
            <TriangleAlert className="size-4" aria-hidden="true" />A source had
            a problem. Details are in the last sweep below.
          </p>
        )}

        {!failed && (
          <Button
            variant="outline"
            className="md:hidden"
            aria-expanded={more}
            aria-controls="today-rest"
            onClick={() => setMore((m) => !m)}
          >
            {more ? "Hide the rest" : "Everything else"}
            <ChevronDown
              className={cn(more && "rotate-180")}
              aria-hidden="true"
            />
          </Button>
        )}

        <div
          id="today-rest"
          className={cn(
            "grid min-w-0 gap-7 xl:col-start-1 xl:row-start-2",
            hideOnPhone
          )}
        >
          {today.isPending ? (
            <Skeleton className="h-28 w-full" />
          ) : today.isError ? (
            <FailedBlock
              what="the last sweep"
              onRetry={() => void today.refetch()}
            />
          ) : (
            <>
              <SweepSection today={today.data} />
              <TopMatchesSection ids={today.data.top_match_ids} />
            </>
          )}
        </div>

        <div
          className={cn(
            "grid min-w-0 gap-7 xl:col-start-2 xl:row-span-2 xl:row-start-1",
            hideOnPhone
          )}
        >
          {today.data ? (
            <>
              <UpcomingSection items={today.data.upcoming} timeZone={tz} />
              <SentSection timeZone={tz} />
              <SpendSection />
            </>
          ) : (
            <Skeleton className="h-40 w-full" />
          )}
        </div>
      </div>
    </View>
  )
}
