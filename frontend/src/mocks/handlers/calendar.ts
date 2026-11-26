/**
 * MSW handlers for the calendar endpoints (`routers/events.py`): a job's events, upcoming, the
 * event actions, the subscription feed and the Google Calendar connection toggle. Errors are
 * `{detail: {code, reason}}` like the server's.
 */
import { http, HttpResponse } from "msw"
import type { components } from "@/lib/api/types"
import { db } from "../db"
import { applicationsMock } from "./applications"
import {
  applyTimes,
  blankEvent,
  isZone,
  OWNER_ZONE,
  recomputeConflicts,
  seedEvents,
  seedGoogle,
  type MockEvent,
  type MockGoogle,
} from "../dataset/calendar"
import { settingValues } from "../dataset/settings"

type S = components["schemas"]

let events: MockEvent[] | null = null
let feedUrl: string | null = null
let google: MockGoogle = seedGoogle()
let rotations = 0

const store = () => {
  if (!events) {
    events = seedEvents()
    recomputeConflicts(events)
  }
  return events
}

export function resetCalendarMock() {
  events = null
  feedUrl = null
  google = seedGoogle()
  rotations = 0
}

/** Test switches. */
export const calendarMock = {
  events: () => store(),
  feedUrl: () => feedUrl,
  /** Google is connected (and, by default, off until the owner switches it on). */
  connectGoogle(enabled = false) {
    google = {
      ...google,
      connected: true,
      enabled,
      connection_id: "70000000-0000-4000-8000-0000000000aa",
      calendar_ready: enabled,
      health: "ok",
    }
  },
  google: () => google,
}

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const refuse = (status: number, code: string, reason: string) =>
  HttpResponse.json({ detail: { code, reason } }, { status })
const find = (id: unknown) => store().find((e) => e.id === String(id))
const signedIn = () => db.get().session

const OUTCOMES = ["went_well", "mixed", "went_badly", "did_not_happen"]

/** Keep the list consistent after any change, then answer with the event. */
function respond(e: MockEvent, status = 200) {
  e.updated_at = new Date().toISOString()
  recomputeConflicts(store())
  return HttpResponse.json(e, { status })
}

function detail(e: MockEvent, body: Partial<S["EventIn"]>) {
  if (body.round_number != null) e.round_number = body.round_number
  if (body.type) e.type = body.type
  if (body.location !== undefined) e.location = body.location ?? null
  if (body.meeting_link !== undefined) {
    if (body.meeting_link && !/^https?:\/\//.test(body.meeting_link))
      return refuse(
        422,
        "bad_link",
        "the meeting link must start with http or https"
      )
    e.meeting_link = body.meeting_link ?? null
  }
  if (body.interviewers) e.interviewers = body.interviewers
  if (body.notes !== undefined) e.notes = body.notes ?? null
  return null
}

const withTimes = (
  e: MockEvent,
  starts: string | null | undefined,
  ends: string | null | undefined,
  zone: string | null | undefined
) => {
  if (starts && !isZone(zone))
    return refuse(
      422,
      "bad_timezone",
      "use an IANA time zone such as Africa/Lusaka"
    )
  if (starts && ends && ends <= starts)
    return refuse(422, "bad_range", "the end must be after the start")
  applyTimes(e, starts ?? null, ends ?? null, zone ?? null)
  return null
}

export const calendarHandlers = [
  http.get("*/api/jobs/:id/events", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const app = applicationsMock().apps.find((a) => a.job_id === params.id)
    const list = store()
      .filter((e) => app && e.application_id === app.id)
      .sort((a, b) => (a.starts_at ?? "9").localeCompare(b.starts_at ?? "9"))
    return HttpResponse.json(list)
  }),
  http.post("*/api/jobs/:id/events", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const app = applicationsMock().apps.find((a) => a.job_id === params.id)
    if (!app)
      return refuse(
        409,
        "no_application",
        "start an application for this role before scheduling an interview"
      )
    const body = (await request.json()) as S["EventIn"]
    const e = blankEvent(app, {
      status: body.status === "proposed" ? "proposed" : "confirmed",
    })
    const bad =
      detail(e, body) ??
      withTimes(e, body.starts_local, body.ends_local, body.timezone)
    if (bad) return bad
    store().push(e)
    return respond(e, 201)
  }),
  http.get("*/api/interview-events/upcoming", () => {
    if (!signedIn()) return unauthorized()
    const open = store().filter(
      (e) => e.status === "confirmed" || e.status === "proposed"
    )
    open.sort((a, b) => (a.starts_at ?? "9").localeCompare(b.starts_at ?? "9"))
    return HttpResponse.json(open)
  }),
  http.get("*/api/interview-events/:id/ics", ({ params }) => {
    const e = find(params.id)
    if (!e) return refuse(404, "not_found", "event not found")
    return new HttpResponse("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", {
      headers: { "Content-Type": "text/calendar" },
    })
  }),
  http.get("*/api/interview-events/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const e = find(params.id)
    return e
      ? HttpResponse.json(e)
      : refuse(404, "not_found", "event not found")
  }),
  http.put("*/api/interview-events/:id", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const e = find(params.id)
    if (!e) return refuse(404, "not_found", "event not found")
    const body = (await request.json()) as S["EventUpdate"]
    const bad =
      detail(e, body) ??
      withTimes(e, body.starts_local, body.ends_local, body.timezone)
    return bad ?? respond(e)
  }),
  http.post(
    "*/api/interview-events/:id/confirm",
    async ({ params, request }) => {
      if (!signedIn()) return unauthorized()
      const e = find(params.id)
      if (!e) return refuse(404, "not_found", "event not found")
      if (e.status !== "proposed")
        return refuse(409, "not_proposed", "only a proposal can be confirmed")
      const body = (await request.json()) as S["ConfirmIn"]
      let starts = body.starts_local ?? e.starts_local
      let ends = body.ends_local ?? e.ends_local
      let zone = body.timezone ?? e.timezone
      if (body.candidate_index != null) {
        const c = e.candidates[body.candidate_index]
        if (!c) return refuse(422, "bad_candidate", "no such candidate")
        starts = c.starts_local
        ends = c.ends_local
        zone = c.timezone ?? body.timezone ?? null
      }
      if (!starts) return refuse(422, "needs_time", "choose a time to confirm")
      if (!zone)
        return refuse(
          422,
          "needs_timezone",
          "the invitation named no time zone: say which zone it is"
        )
      const bad = withTimes(e, starts, ends, zone)
      if (bad) return bad
      e.status = "confirmed"
      e.candidates = []
      return respond(e)
    }
  ),
  http.post(
    "*/api/interview-events/:id/reschedule",
    async ({ params, request }) => {
      if (!signedIn()) return unauthorized()
      const e = find(params.id)
      if (!e) return refuse(404, "not_found", "event not found")
      const body = (await request.json()) as S["RescheduleIn"]
      const bad = withTimes(
        e,
        body.starts_local,
        body.ends_local,
        body.timezone
      )
      return bad ?? respond(e)
    }
  ),
  http.post("*/api/interview-events/:id/cancel", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const e = find(params.id)
    if (!e) return refuse(404, "not_found", "event not found")
    e.status = "cancelled"
    return respond(e)
  }),
  http.post(
    "*/api/interview-events/:id/debrief",
    async ({ params, request }) => {
      if (!signedIn()) return unauthorized()
      const e = find(params.id)
      if (!e) return refuse(404, "not_found", "event not found")
      const body = (await request.json()) as S["DebriefIn"]
      if (!OUTCOMES.includes(body.outcome))
        return refuse(422, "bad_outcome", "unknown outcome")
      e.outcome = body.outcome
      e.debrief_due = false
      e.status = "done"
      recomputeConflicts(store())
      return HttpResponse.json({
        event: e,
        stage_changed_to: body.next_step === "rejected" ? "rejected" : null,
        follow_up_id: null,
      } satisfies S["DebriefOut"])
    }
  ),

  // ---- the subscription feed and Google Calendar (Settings > Connections) ----
  http.get("*/api/calendar", () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json({
      feed_url: feedUrl,
      detail_level: settingValues[
        "calendar.detail_level"
      ] as S["CalendarOut"]["detail_level"],
      reminder_offsets_minutes: settingValues[
        "calendar.reminder_offsets_minutes"
      ] as number[],
      prep_nudge_minutes: Number(settingValues["calendar.prep_nudge_minutes"]),
      owner_timezone: OWNER_ZONE,
      google,
    } satisfies S["CalendarOut"])
  }),
  http.post("*/api/calendar/feed", () => {
    if (!signedIn()) return unauthorized()
    rotations += 1
    feedUrl = `https://nchito.example.com/api/calendar/feed/token${rotations}.ics`
    return HttpResponse.json({ url: feedUrl } satisfies S["FeedOut"])
  }),
  http.delete("*/api/calendar/feed", () => {
    if (!signedIn()) return unauthorized()
    feedUrl = null
    return new HttpResponse(null, { status: 204 })
  }),
  http.put("*/api/connections/:id", async ({ params, request }) => {
    if (params.id !== google.connection_id) return undefined
    const body = (await request.json()) as S["ConnectionUpdate"]
    if (body.enabled != null) {
      google = {
        ...google,
        enabled: body.enabled,
        calendar_ready: body.enabled,
      }
    }
    const now = new Date().toISOString()
    return HttpResponse.json({
      id: google.connection_id!,
      created_at: now,
      updated_at: now,
      provider: "gcalendar",
      label: "Google Calendar",
      config: {},
      secrets_masked: {},
      scopes_granted: [],
      reads_description: google.reads_description,
      health: "ok",
      last_checked_at: null,
      enabled: google.enabled,
    } satisfies S["ConnectionOut"])
  }),
]
