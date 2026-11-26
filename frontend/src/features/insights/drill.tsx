/**
 * Insights drill-through on the lists it links to (Applications, Matches): the URL carries the
 * clicked number's filters, the list endpoint narrows to exactly the rows that number counted,
 * and a bar shows each filter as a removable chip.
 */
import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { campaignsQuery, tracksQuery } from "@/features/campaigns/api"
import { sourcesQuery } from "@/features/sources/api"
import { cn } from "@/lib/utils"
import { DRILL_KEYS, type AnyDrill, type DrillKey } from "./drill-search"

const REACHED_LABEL: Record<string, string> = {
  found: "Found",
  passed_filters: "Passed filters",
  scored_above: "Scored above threshold",
  tailored: "Tailored",
  approved: "Approved",
  sent: "Sent",
  reply: "Replied",
  interview: "Reached interview",
  offer: "Reached offer",
}
const CHANNEL_LABEL: Record<string, string> = {
  email: "Email",
  browser: "Browser",
  manual: "Manual",
}

/** One chip per drill filter, each removable, plus "Clear all". Renders nothing when no drill. */
export function DrillBar({
  drill,
  onRemove,
  onClear,
  note,
  className,
}: {
  drill: AnyDrill | undefined
  onRemove: (key: DrillKey) => void
  onClear: () => void
  /** A line after the chips (Matches: how many of the roles sit in each tab). */
  note?: string
  className?: string
}) {
  const on = !!drill
  const campaigns = useQuery({
    ...campaignsQuery(),
    enabled: on && !!drill?.campaign_id,
  })
  const tracks = useQuery({
    ...tracksQuery(),
    enabled: on && !!drill?.track_id,
  })
  const sources = useQuery({
    ...sourcesQuery(),
    enabled: on && !!drill?.source_id,
  })
  if (!drill) return null
  const nameOf = (
    list: { id: string; name: string }[] | undefined,
    id: string
  ) => list?.find((x) => x.id === id)?.name ?? "…"
  const label = (k: DrillKey, v: string): string => {
    switch (k) {
      case "since":
        return `From ${v}`
      case "until":
        return `To ${v}`
      case "campaign_id":
        return `Campaign: ${nameOf(campaigns.data, v)}`
      case "track_id":
        return `Track: ${nameOf(tracks.data, v)}`
      case "source_id":
        return `Source: ${nameOf(sources.data, v)}`
      case "country":
        return `Market: ${v}`
      case "channel":
        return `Channel: ${CHANNEL_LABEL[v] ?? v}`
      case "reached":
        return `Step: ${REACHED_LABEL[v] ?? v}`
    }
  }
  const set = DRILL_KEYS.flatMap((k) => {
    const v = (drill as Record<string, string | undefined>)[k]
    return v ? [{ k, v }] : []
  })
  return (
    <div
      role="group"
      aria-label="Filters from Insights"
      className={cn(
        "mb-3 flex flex-wrap items-center gap-1.5 rounded-sm border border-border bg-sunken px-3 py-2 text-sm",
        className
      )}
    >
      <span className="mr-1 text-muted-foreground">From Insights:</span>
      {set.map(({ k, v }) => (
        <span
          key={k}
          data-slot="chip"
          className="inline-flex items-center gap-1 rounded-full border border-border bg-surface py-0.5 pr-1 pl-2.5 text-[0.8rem] text-foreground"
        >
          {label(k, v)}
          <button
            type="button"
            aria-label={`Remove ${label(k, v)}`}
            className="grid size-5 place-items-center rounded-full text-muted-foreground hover:bg-sunken hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
            onClick={() => onRemove(k)}
          >
            <X className="size-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      {note && <span className="text-muted-foreground">{note}</span>}
      <Button variant="ghost" size="sm" className="ml-auto" onClick={onClear}>
        Clear all
      </Button>
    </div>
  )
}
