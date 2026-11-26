import { TriangleAlert } from "lucide-react"
import { Chip } from "@/components/chip"
import type { EventOut } from "./api"
import { eventZones } from "./format"

/** Both zones, each with its zone name. Collapses to one line only when the zones are identical. */
export function EventTimes({ event }: { event: EventOut }) {
  const zones = eventZones(event)
  if (zones.length === 0)
    return <p className="text-sm text-muted-foreground">No time yet</p>
  return (
    <dl className="grid gap-0.5 text-sm">
      {zones.map((z) => (
        <div key={z.label} className="flex flex-wrap gap-x-2">
          <dt className="text-muted-foreground">{z.label}</dt>
          <dd>
            <b className="num">{z.text}</b>{" "}
            <span className="text-muted-foreground">({z.zone})</span>
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** An overlap is a warning, never a block. */
export function ConflictWarning({ event }: { event: EventOut }) {
  if (event.conflicts.length === 0) return null
  return (
    <p
      role="status"
      className="flex flex-wrap items-center gap-1.5 text-sm text-warn"
    >
      <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
      Overlaps with{" "}
      {event.conflicts.map((c) => `${c.employer} (${c.job_title})`).join(", ")}
    </p>
  )
}

export function ConflictBadge({ event }: { event: EventOut }) {
  if (event.conflicts.length === 0) return null
  return (
    <Chip tone="warn" icon={TriangleAlert}>
      Overlaps another event
    </Chip>
  )
}
