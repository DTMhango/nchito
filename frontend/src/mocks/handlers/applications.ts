import { http, HttpResponse } from "msw"
import type { ResolveIn } from "@/features/applications/api"
import { db } from "../db"
import {
  buildToday,
  CAMPAIGNS,
  groupActions,
  NEW_JOBS,
  seedApplications,
  type MockApplications,
} from "./applications-data"

let state: MockApplications = seedApplications()

/** Reset the fictional applications data (tests, and `?mock=` switches). */
export const resetApplicationsMock = () => {
  state = seedApplications()
}
export const applicationsMock = () => state

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })

const find = (id: unknown) => state.apps.find((a) => a.id === String(id))

/** Application, today, pending-action, jobs-new and campaign endpoints for dev:mock and tests. */
export const applicationsHandlers = [
  http.get("*/api/applications", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const url = new URL(request.url)
    const stage = url.searchParams.get("stage")
    const q = url.searchParams.get("q")?.toLowerCase()
    const campaign = url.searchParams.get("campaign_id")
    const items = state.apps.filter(
      (a) =>
        !state.snoozed[a.id] &&
        (!stage || a.stage === stage) &&
        (!campaign || a.campaign_id === campaign) &&
        (!q || `${a.employer} ${a.title}`.toLowerCase().includes(q))
    )
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.get("*/api/applications/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = find(params.id)
    return a ? HttpResponse.json(a) : notFound("Application")
  }),
  http.get("*/api/applications/:id/timeline", ({ params }) => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(state.events[String(params.id)] ?? [])
  }),
  http.post("*/api/applications/:id/stage", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const a = find(params.id)
    if (!a) return notFound("Application")
    const body = (await request.json()) as {
      stage: typeof a.stage
      note?: string
    }
    if (["submitted", "submitted_unconfirmed", "applying"].includes(body.stage))
      return HttpResponse.json(
        {
          detail:
            "That stage is set by the dispatch record or by recording that you applied yourself.",
        },
        { status: 409 }
      )
    a.stage = body.stage
    a.updated_at = new Date().toISOString()
    ;(state.events[a.id] ??= []).push({
      id: crypto.randomUUID(),
      created_at: a.updated_at,
      kind: "stage.changed",
      actor: "owner",
      detail: { note: `Moved to ${body.stage.replace(/_/g, " ")}` },
    })
    return HttpResponse.json(a)
  }),
  http.patch("*/api/applications/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const a = find(params.id)
    if (!a) return notFound("Application")
    const body = (await request.json()) as Record<string, unknown>
    if (typeof body.pinned === "boolean") a.pinned = body.pinned
    if (body.channel) a.channel = body.channel as typeof a.channel
    if (typeof body.snoozed_until === "string")
      state.snoozed[a.id] = body.snoozed_until
    if ("next_step" in body) a.next_step = body.next_step as string | null
    if ("next_due" in body) a.next_due = body.next_due as string | null
    return HttpResponse.json(a)
  }),
  http.post(
    "*/api/applications/:id/mark-submitted",
    async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const a = find(params.id)
      if (!a) return notFound("Application")
      const body = (await request.json()) as { note?: string | null }
      a.stage = "submitted"
      a.applied_at = new Date().toISOString()
      a.updated_at = a.applied_at
      ;(state.events[a.id] ??= []).push({
        id: crypto.randomUUID(),
        created_at: a.applied_at,
        kind: "application.submitted",
        actor: "owner",
        detail: { note: body.note ?? "" },
      })
      return HttpResponse.json(a)
    }
  ),

  http.get("*/api/campaigns", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json({
      items: CAMPAIGNS.map((c) => ({ ...c, status: "active" })),
      total: CAMPAIGNS.length,
      next_cursor: null,
    })
  }),
  http.get("*/api/jobs", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const limit = Number(new URL(request.url).searchParams.get("limit") ?? 50)
    return HttpResponse.json({
      items: NEW_JOBS.slice(0, limit),
      total: NEW_JOBS.length,
      next_cursor: null,
      groups: null,
    })
  }),
  http.get("*/api/settings/:key", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const key = String(params.key)
    const defaults: Record<string, string> = {
      "answers.routine_default_scope": "all_matching",
      "answers.material_default_scope": "this_application",
    }
    if (!(key in defaults)) return notFound("Setting")
    return HttpResponse.json({
      key,
      value: defaults[key],
      default: defaults[key],
    })
  }),

  http.get("*/api/today", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(buildToday(state))
  }),
  http.get("*/api/pending-actions/decisions", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(groupActions(state.actions))
  }),
  http.get("*/api/pending-actions", () => {
    if (!db.get().session) return unauthorized()
    const items = state.actions.filter((a) => a.status === "open")
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.post(
    "*/api/pending-actions/:id/resolve",
    async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const action = state.actions.find((a) => a.id === String(params.id))
      if (!action) return notFound("Pending action")
      const body = (await request.json()) as ResolveIn
      action.status = body.resolution === "dismissed" ? "dismissed" : "resolved"
      action.updated_at = new Date().toISOString()
      const app = state.apps.find((a) => a.id === action.application_id)
      if (app)
        app.open_pending_actions = Math.max(0, app.open_pending_actions - 1)
      return HttpResponse.json(action)
    }
  ),

  // Server-sent events: an open stream with keepalives; the mock publishes nothing.
  http.get("*/api/events", () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(encoder.encode("retry: 5000\n\n: keepalive\n\n"))
      },
    })
    return new HttpResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-store",
      },
    })
  }),
]
