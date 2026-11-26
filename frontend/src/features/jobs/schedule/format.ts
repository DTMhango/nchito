/** Wall times arrive as `YYYY-MM-DDTHH:MM` in a named zone; they are shown as written, never shifted. */
import type { EventOut } from "./api"

const WALL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/

function parts(wall: string) {
  const m = WALL.exec(wall)
  if (!m) return null
  return { y: +m[1], mo: +m[2], d: +m[3], h: m[4], mi: m[5] }
}

/** "Tue 1 Dec 2026, 10:00". */
export function wallText(wall: string | null): string {
  if (!wall) return "No time yet"
  const p = parts(wall)
  if (!p) return wall
  const date = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(p.y, p.mo - 1, p.d)))
  return `${date}, ${p.h}:${p.mi}`
}

/** A range: the end shows only the time when it is the same day. */
export function wallRange(start: string | null, end: string | null): string {
  if (!start) return "No time yet"
  const a = wallText(start)
  if (!end) return a
  const ps = parts(start)
  const pe = parts(end)
  if (!ps || !pe) return a
  const sameDay = ps.y === pe.y && ps.mo === pe.mo && ps.d === pe.d
  return `${a} to ${sameDay ? `${pe.h}:${pe.mi}` : wallText(end)}`
}

/** The two zones of an event; one line when both zones are the same. */
export type Zoned = { label: string; text: string; zone: string }
export function eventZones(e: EventOut): Zoned[] {
  const theirs: Zoned | null =
    e.starts_local && e.timezone
      ? {
          label: "Their time",
          text: wallRange(e.starts_local, e.ends_local),
          zone: e.timezone,
        }
      : null
  const mine: Zoned | null = e.owner_starts_local
    ? {
        label: "Your time",
        text: wallRange(e.owner_starts_local, e.owner_ends_local),
        zone: e.owner_timezone,
      }
    : null
  if (theirs && mine && theirs.zone === mine.zone)
    return [{ ...mine, label: "Time" }]
  return [theirs, mine].filter((z): z is Zoned => z !== null)
}

export const TYPE_LABEL: Record<EventOut["type"], string> = {
  phone: "Phone call",
  video: "Video call",
  onsite: "On site",
  assessment: "Assessment",
}
export const STATUS_LABEL: Record<EventOut["status"], string> = {
  proposed: "Proposed",
  confirmed: "Confirmed",
  done: "Done",
  cancelled: "Cancelled",
  rescheduled: "Rescheduled",
}
