import { http, HttpResponse } from "msw"
import type { ResolveIn } from "@/features/applications/api"
import { db } from "../db"
import {
  buildToday,
  groupActions,
  seedApplications,
  toDetail,
  type MockApplications,
} from "@/mocks/dataset/applications"

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

const REPLY = ["screening", "interview", "offer", "accepted"]
/**
 * Insights drill-through, roughly: the mock has no stage history, so "reached" reads the current
 * stage (the server uses the stage-change events). Date, track, source and market are ignored.
 */
function mockReached(a: MockApplications["apps"][number], step: string) {
  const sent = !!a.applied_at
  switch (step) {
    case "sent":
    case "approved":
    case "tailored":
      return sent
    case "reply":
      return sent && (REPLY.includes(a.stage) || a.stage === "rejected")
    case "interview":
      return ["interview", "offer", "accepted"].includes(a.stage)
    case "offer":
      return ["offer", "accepted"].includes(a.stage)
    default:
      return true
  }
}

/** Application, Today and pending-action endpoints for dev:mock and tests. */
export const applicationsHandlers = [
  http.get("*/api/applications", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const url = new URL(request.url)
    const stage = url.searchParams.get("stage")
    const q = url.searchParams.get("q")?.toLowerCase()
    const campaign = url.searchParams.get("campaign_id")
    const hide = url.searchParams.get("hide_snoozed") === "true"
    const now = Date.now()
    for (const a of state.apps)
      a.snoozed = !!a.snoozed_until && Date.parse(a.snoozed_until) > now
    const channel = url.searchParams.get("channel")
    const reached = url.searchParams.get("reached")
    const items = state.apps.filter(
      (a) =>
        !(hide && a.snoozed) &&
        (!stage || a.stage === stage) &&
        (!campaign || a.campaign_id === campaign) &&
        (!channel || a.channel === channel) &&
        (!reached || mockReached(a, reached)) &&
        (!q || `${a.employer} ${a.title}`.toLowerCase().includes(q))
    )
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.get("*/api/applications/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = find(params.id)
    return a ? HttpResponse.json(toDetail(a)) : notFound("Application")
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
    if ("snoozed_until" in body)
      a.snoozed_until = (body.snoozed_until as string | null) ?? null
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
      action.resolution = { ...body }
      const app = state.apps.find((a) => a.id === action.application_id)
      // An approved mailbox proposal applies its stage change (the real resolver does the same).
      const proposed = action.detail.proposed_stage
      if (
        app &&
        body.resolution === "approved" &&
        action.detail.kind === "mail_stage_proposal" &&
        typeof proposed === "string"
      )
        app.stage = proposed as typeof app.stage
      if (app)
        app.open_pending_actions = Math.max(0, app.open_pending_actions - 1)
      return HttpResponse.json(action)
    }
  ),
]
