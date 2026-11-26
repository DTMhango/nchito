/**
 * MSW handlers for gateway tokens, runner status, runner tasks and caps, portal accounts, and
 * one pending action by id. `/api/tokens*` follow the real contract; portal accounts, runner
 * tasks and caps follow `features/accounts/w3-pending-types.ts` (temporary, until the backend
 * streams publish them). Served before the autopilot handlers so token changes show up in
 * the Autopilot channels panel too.
 */
import { http, HttpResponse } from "msw"
import type {
  PortalAccountIn,
  RunnerCaps,
} from "@/features/accounts/w3-pending-types"
import type { TokenCreate } from "@/features/settings/runners/api"
import { db } from "../db"
import { applicationsMock } from "./applications"
import { PC_ID, seedRunners, uuid, type MockRunners } from "../dataset/runners"

let state: MockRunners = seedRunners()
let nextId = 100

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const HOUR = 3_600_000
const ago = (h: number) => new Date(Date.now() - h * HOUR).toISOString()

export const runnersMock = () => state

/** Runs after the applications reset: ties the sign-in actions and tasks together. */
export const resetRunnersMock = () => {
  state = seedRunners()
  nextId = 100
  const apps = applicationsMock()
  const byEmployer = (e: string) => apps.apps.find((a) => a.employer === e)
  const signIns = apps.actions.filter((a) => a.type === "sign_in")
  for (const a of signIns) {
    Object.assign(a.detail, {
      blocker: "sign_in",
      portal_name: "Zambezi Mining careers",
      runner_token_id: PC_ID,
      runner_name: "Office PC",
      browser_profile: "Chrome, profile Job search",
      reminders: {
        sent: 1,
        next_at: new Date(Date.now() + 6 * HOUR).toISOString(),
      },
    })
  }
  const blocked = signIns.map((a, i) => ({
    id: uuid("e", 10 + i),
    application_id: a.application_id,
    title: `Apply: ${a.job_title ?? "role"} at ${a.employer ?? "employer"}`,
    kind: "apply" as const,
    status: "blocked" as const,
    started_at: ago(3 + i),
    checkpoints: [
      { at: ago(3 + i), step: "Opened the posting" },
      { at: ago(3 + i), step: "Reached the portal sign-in" },
    ],
    blockers: [{ at: ago(3 + i), kind: "sign_in" as const, action_id: a.id }],
    permits: [],
    result: null,
    blocked_by: a.id,
  }))
  const kafue = byEmployer("Kafue Analytics")
  state.tasks[PC_ID] = [
    ...blocked,
    {
      id: uuid("e", 1),
      application_id: kafue?.id ?? null,
      title: `Apply: ${kafue?.title ?? "role"} at Kafue Analytics`,
      kind: "apply",
      status: "done",
      started_at: ago(26),
      checkpoints: [
        { at: ago(26), step: "Opened the posting" },
        { at: ago(26), step: "Filled the form" },
        { at: ago(26), step: "Attached CV" },
      ],
      blockers: [],
      permits: [
        {
          at: ago(25.9),
          outcome: "wait_for_owner",
          reason: "Approval is needed first.",
        },
        { at: ago(25.5), outcome: "granted", reason: null },
      ],
      result: {
        outcome: "submitted",
        detail: "Thank you for applying, reference KA-2041.",
        evidence: [
          {
            kind: "screenshot",
            label: "Confirmation page",
            url: "data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='64'%3E%3Crect width='96' height='64' fill='%23ddd'/%3E%3C/svg%3E",
          },
          {
            kind: "confirmation_text",
            label: "Thank you for applying (KA-2041)",
            url: null,
          },
        ],
      },
    },
    {
      id: uuid("e", 2),
      application_id: null,
      title: "Apply: Risk Analyst at Copperline Energy",
      kind: "apply",
      status: "failed",
      started_at: ago(48),
      checkpoints: [{ at: ago(48), step: "Opened the posting" }],
      blockers: [],
      permits: [
        {
          at: ago(47.9),
          outcome: "denied",
          reason: "The posting closed on 20 Nov.",
        },
      ],
      result: { outcome: "failed", detail: "Not submitted.", evidence: [] },
    },
  ]
}

const tasksFor = (tokenId: string) => {
  const apps = applicationsMock()
  return (state.tasks[tokenId] ?? []).map((t) => {
    if (!t.blocked_by) return t
    const a = apps.actions.find((x) => x.id === t.blocked_by)
    if (a?.status === "resolved" && a.resolution?.resolution === "continue")
      return { ...t, status: "running" as const }
    if (a?.status === "dismissed") return { ...t, status: "failed" as const }
    return t
  })
}

export const runnersHandlers = [
  // ---- tokens ----
  http.get("*/api/tokens/runners", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(state.statuses)
  }),
  http.get("*/api/tokens", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(state.tokens)
  }),
  http.post("*/api/tokens", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as TokenCreate
    if (!body.name?.trim())
      return HttpResponse.json(
        { detail: "Give the token a name." },
        { status: 422 }
      )
    const n = nextId++
    const secret = `nch_live_${n}_${crypto.randomUUID().replace(/-/g, "")}`
    const now = new Date().toISOString()
    const t = {
      id: uuid("c", n),
      created_at: now,
      updated_at: now,
      name: body.name.trim(),
      prefix: secret.slice(0, 12),
      scopes: body.scopes ?? [],
      runner_kind: body.runner_kind ?? "pc",
      last_used_at: null,
      revoked_at: null,
      suspended_at: null,
      suspended_reason: null,
    }
    state.tokens.push(t)
    state.statuses.push({
      token_id: t.id,
      name: t.name,
      runner_kind: t.runner_kind,
      last_seen_at: null,
      online: false,
      current_task_id: null,
    })
    state.caps[t.id] = {
      max_tasks_per_day: null,
      max_steps_per_task: null,
      cost_ceiling_per_task: null,
    }
    state.tasks[t.id] = []
    // The secret is in this one response and nowhere else: GET /api/tokens never returns it.
    return HttpResponse.json({ ...t, token: secret }, { status: 201 })
  }),
  http.post("*/api/tokens/:id/revoke", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const t = state.tokens.find((x) => x.id === String(params.id))
    if (!t) return notFound("Token")
    t.revoked_at = new Date().toISOString()
    state.statuses = state.statuses.filter((s) => s.token_id !== t.id)
    return HttpResponse.json(t)
  }),
  http.post("*/api/tokens/:id/reinstate", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const t = state.tokens.find((x) => x.id === String(params.id))
    if (!t) return notFound("Token")
    t.suspended_at = null
    t.suspended_reason = null
    return HttpResponse.json(t)
  }),

  // ---- runner tasks and caps (pending contract) ----
  http.get("*/api/runners/:id/tasks", ({ params }) => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(tasksFor(String(params.id)))
  }),
  http.get("*/api/runners/:id/caps", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const caps = state.caps[String(params.id)]
    return caps ? HttpResponse.json(caps) : notFound("Runner")
  }),
  http.put("*/api/runners/:id/caps", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    if (!state.caps[id]) return notFound("Runner")
    state.caps[id] = (await request.json()) as RunnerCaps
    return HttpResponse.json(state.caps[id])
  }),

  // ---- portal accounts (pending contract) ----
  http.get("*/api/portal-accounts", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(state.accounts)
  }),
  http.post("*/api/portal-accounts", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as PortalAccountIn
    const a = {
      id: uuid("a", nextId++),
      portal_name: body.portal_name,
      portal_url: body.portal_url,
      status: body.status,
      signed_in_runner: body.signed_in_runner ?? null,
      email_used: body.email_used ?? null,
      last_sign_in_at: null,
      applications_waiting: 0,
    }
    state.accounts.push(a)
    return HttpResponse.json(a, { status: 201 })
  }),
  http.put("*/api/portal-accounts/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const a = state.accounts.find((x) => x.id === String(params.id))
    if (!a) return notFound("Portal account")
    Object.assign(a, (await request.json()) as PortalAccountIn)
    return HttpResponse.json(a)
  }),

  // ---- one pending action (the wave 1 handlers serve only the lists) ----
  http.get("*/api/pending-actions/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    if (id === "decisions") return undefined // falls through to the decisions handler
    const a = applicationsMock().actions.find((x) => x.id === id)
    return a ? HttpResponse.json(a) : notFound("Pending action")
  }),
]
