/**
 * Fictional calendar data (interview events, feed, Google state). Shapes are the generated
 * contract's (`EventOut`, `CalendarOut`, `GoogleState`); behaviour mirrors `app/pipeline/events.py`:
 * wall time plus an IANA zone in, UTC and both wall times out.
 */
import type { components } from "@/lib/api/types"
import { applicationsMock } from "../handlers/applications"
import { settingValues } from "./settings"

type S = components["schemas"]
export type MockEvent = S["EventOut"]
export type MockCalendar = S["CalendarOut"]

export const OWNER_ZONE = "Africa/Lusaka"
export const DEFAULT_MINUTES = 60

/** "YYYY-MM-DDTHH:MM" of an instant as seen in a zone. */
export function wallIn(ms: number, zone: string): string {
  const f = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
  const p = Object.fromEntries(
    f.formatToParts(new Date(ms)).map((x) => [x.type, x.value])
  )
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

/** The instant (ms) when a zone's clock reads the given wall time. */
export function instantOf(wall: string, zone: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(wall)!
  const asUtc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  let guess = asUtc
  for (let i = 0; i < 2; i++) {
    const seen = wallIn(guess, zone)
    const n = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(seen)!
    const diff = asUtc - Date.UTC(+n[1], +n[2] - 1, +n[3], +n[4], +n[5])
    guess += diff
  }
  return guess
}

export const isZone = (z: unknown): z is string => {
  if (typeof z !== "string" || !z.trim()) return false
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: z })
    return true
  } catch {
    return false
  }
}

/** Set the time fields of an event from wall times in the employer's zone. */
export function applyTimes(
  e: MockEvent,
  startsLocal: string | null,
  endsLocal: string | null,
  zone: string | null
) {
  e.timezone = zone
  if (!startsLocal || !zone) {
    e.starts_at = e.ends_at = null
    e.starts_local = startsLocal
    e.ends_local = endsLocal
    e.owner_starts_local = e.owner_ends_local = null
    e.needs_input = true
    return
  }
  const s = instantOf(startsLocal, zone)
  const en = endsLocal ? instantOf(endsLocal, zone) : null
  e.starts_at = new Date(s).toISOString()
  e.ends_at = en == null ? null : new Date(en).toISOString()
  e.starts_local = startsLocal
  e.ends_local = endsLocal
  e.owner_starts_local = wallIn(s, e.owner_timezone)
  e.owner_ends_local = en == null ? null : wallIn(en, e.owner_timezone)
  e.needs_input = false
}

let seq = 0
export function blankEvent(
  app: { id: string; job_id: string; employer: string; title: string },
  patch: Partial<MockEvent> = {}
): MockEvent {
  seq += 1
  const now = new Date().toISOString()
  return {
    id: `70000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    created_at: now,
    updated_at: now,
    application_id: app.id,
    job_id: app.job_id,
    employer: app.employer,
    job_title: app.title,
    round_number: 1,
    type: "video",
    status: "confirmed",
    source: "owner",
    starts_at: null,
    ends_at: null,
    timezone: null,
    owner_timezone: OWNER_ZONE,
    starts_local: null,
    ends_local: null,
    owner_starts_local: null,
    owner_ends_local: null,
    location: null,
    meeting_link: null,
    interviewers: [],
    notes: null,
    candidates: [],
    needs_input: false,
    conflicts: [],
    replaces_id: null,
    google_synced: false,
    google_error: null,
    outcome: null,
    debrief_due: false,
    ...patch,
  }
}

const DAY = 86_400_000
/** A wall time `days` from now at a fixed hour in a zone. */
const at = (days: number, hour: number, zone: string, minutes = 0) => {
  const d = new Date(Date.now() + days * DAY)
  const day = wallIn(d.getTime(), zone).slice(0, 10)
  return `${day}T${String(hour).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`
}

/**
 * Three events across two roles: a confirmed video call whose zones differ, a second confirmed
 * call on another role that overlaps it, and a proposal from an email with two candidates, one
 * of them without a time zone.
 */
export function seedEvents(): MockEvent[] {
  const apps = applicationsMock().apps
  const interview = apps.find((a) => a.stage === "interview")
  const others = apps.filter((a) => a.id !== interview?.id)
  const out: MockEvent[] = []
  if (interview) {
    const e = blankEvent(interview, {
      round_number: 2,
      type: "video",
      meeting_link: "https://meet.example.com/second-round",
      interviewers: ["Amara Okoye", "Tendai Moyo"],
      location: "Video",
      google_synced: false,
    })
    applyTimes(
      e,
      at(3, 10, "Europe/London"),
      at(3, 11, "Europe/London"),
      "Europe/London"
    )
    out.push(e)
  }
  if (others[0]) {
    // Starts 30 minutes into the first event whatever the date's UTC offsets: a real overlap.
    const base = instantOf(at(3, 10, "Europe/London"), "Europe/London")
    const zone = "Africa/Johannesburg"
    const e = blankEvent(others[0], { type: "phone" })
    applyTimes(
      e,
      wallIn(base + 30 * 60_000, zone),
      wallIn(base + 90 * 60_000, zone),
      zone
    )
    out.push(e)
  }
  if (others[1]) {
    const e = blankEvent(others[1], {
      status: "proposed",
      source: "mail",
      needs_input: true,
      candidates: [
        {
          starts_at: null,
          ends_at: null,
          starts_local: at(5, 14, "UTC"),
          ends_local: at(5, 15, "UTC"),
          timezone: null,
          label: "Option A",
        },
        {
          starts_at: null,
          ends_at: null,
          starts_local: at(6, 9, "UTC"),
          ends_local: at(6, 10, "UTC"),
          timezone: "Africa/Nairobi",
          label: "Option B",
        },
      ],
    })
    out.push(e)
  }
  return out
}

/** Recompute `conflicts` for every live event from UTC ranges (a warning, never a block). */
export function recomputeConflicts(events: MockEvent[]) {
  const dur =
    Number(settingValues["calendar.default_duration_minutes"]) ||
    DEFAULT_MINUTES
  const live = events.filter(
    (e) => (e.status === "confirmed" || e.status === "proposed") && e.starts_at
  )
  const range = (e: MockEvent): [number, number] => {
    const s = Date.parse(e.starts_at!)
    return [s, e.ends_at ? Date.parse(e.ends_at) : s + dur * 60_000]
  }
  for (const e of events) {
    e.conflicts = []
    if (!live.includes(e)) continue
    const [s, en] = range(e)
    for (const o of live) {
      if (o.id === e.id) continue
      const [os, oe] = range(o)
      if (s < oe && os < en)
        e.conflicts.push({
          event_id: o.id,
          employer: o.employer,
          job_title: o.job_title,
          starts_at: o.starts_at!,
          ends_at: o.ends_at,
        })
    }
  }
}

export type MockGoogle = S["GoogleState"]
export const seedGoogle = (): MockGoogle => ({
  configured: true,
  connected: false,
  enabled: false,
  connection_id: null,
  calendar_ready: false,
  health: null,
  last_checked_at: null,
  reads_description:
    "Writes interviews to its own calendar only. It never reads your other calendars.",
})
