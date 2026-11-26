/**
 * MSW handlers for gateway tokens and runner status, portal accounts (incl. give-up and
 * refresh), one pending action by id, the resolve rules for blocker actions, and application
 * release records. All follow the generated contract (`docs/openapi.json`). Served before the
 * applications and autopilot handlers, so blocker resolves land here first.
 */
import { http, HttpResponse } from "msw"
import type {
  GiveUpIn,
  PendingAction,
  PortalAccountPatch,
  PortalAccountWrite,
  ResolveIn,
} from "@/features/accounts/api"
import { SECRET_WORDS } from "@/features/accounts/logic"
import type { ReinstateIn, TokenCreate } from "@/features/settings/runners/api"
import { db } from "../db"
import { applicationsMock } from "./applications"
import {
  blockerActions,
  seedReleases,
  seedRunners,
  uuid,
  type MockRunners,
} from "../dataset/runners"

let state: MockRunners = seedRunners()
let nextId = 100

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const refuse = (status: number, detail: unknown) =>
  HttpResponse.json({ detail }, { status })

export const runnersMock = () => state

/**
 * Runs after the applications reset: replaces the two seeded sign-in rows with one per portal
 * tenant (as `app.apply.accounts` keeps them) and adds the wave 3 blockers and a posting change.
 */
export const resetRunnersMock = () => {
  state = seedRunners()
  nextId = 100
  const apps = applicationsMock()
  apps.actions = apps.actions.filter((a) => a.type !== "sign_in")
  apps.actions.push(...blockerActions(apps.apps))
  state.releases = seedReleases(apps.apps)
}

const findAction = (id: unknown) =>
  applicationsMock().actions.find((a) => a.id === String(id))

/** `owner_actions.CONTINUABLE`; the account kinds `give_up` accepts. */
const CONTINUABLE = ["sign_in", "create_account", "captcha"]
const ACCOUNT_KINDS = [
  "sign_in",
  "create_account",
  "verification_code",
  "captcha",
  "assessment",
  "declaration",
  "unsupported_form",
]
const isAccountAction = (a: PendingAction) =>
  ACCOUNT_KINDS.includes(String(a.detail.kind))

/** The type/resolution pairs `pending_actions.resolve` accepts (anything else is a 422). */
function accepts(a: PendingAction, r: ResolveIn["resolution"]): boolean {
  switch (r) {
    case "dismissed":
      return true
    case "continue":
      return CONTINUABLE.includes(a.type)
    case "answered":
      return a.type === "unknown_question"
    case "approved":
      return a.type === "approve" || a.detail.kind === "mail_stage_proposal"
    case "chosen":
      return a.type === "conflict_choice"
    case "confirmed":
      return a.type === "confirm_submission"
  }
}

const secretKey = (body: object) =>
  Object.keys(body).find((k) =>
    SECRET_WORDS.some((w) => k.toLowerCase().includes(w))
  )

const close = (a: PendingAction, resolution: Record<string, unknown>) => {
  a.status = resolution.resolution === "dismissed" ? "dismissed" : "resolved"
  a.updated_at = new Date().toISOString()
  a.resolution = resolution
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
    if (!body.name?.trim()) return refuse(422, "Give the token a name.")
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
  http.post("*/api/tokens/:id/reinstate", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const t = state.tokens.find((x) => x.id === String(params.id))
    if (!t) return notFound("Token")
    const text = await request.text()
    const body = (text ? JSON.parse(text) : null) as ReinstateIn | null
    if (t.suspended_at && !body?.acknowledged)
      return refuse(422, {
        code: "acknowledgement_required",
        reason: "confirm you have read why this runner was paused",
      })
    if (t.revoked_at) return refuse(409, "a revoked token cannot be reinstated")
    t.suspended_at = null
    t.suspended_reason = null
    return HttpResponse.json(t)
  }),

  // ---- portal accounts ----
  http.get("*/api/portal-accounts", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const status = new URL(request.url).searchParams.get("status")
    const items = state.accounts.filter((a) => !status || a.status === status)
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.post("*/api/portal-accounts/refresh", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json({ raised: 0, joined: 0, closed: 0, reminded: 1 })
  }),
  http.post(
    "*/api/portal-accounts/actions/:id/give-up",
    async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const a = findAction(params.id)
      if (!a) return notFound("pending action")
      const body = (await request.json()) as GiveUpIn
      if (a.status !== "open" || !isAccountAction(a))
        return refuse(409, "this is not an open sign-in request")
      const entries = (a.detail.applications ?? []) as {
        application_id: string
      }[]
      const ids = entries.map((e) => e.application_id)
      const wanted = body.application_ids?.length ? body.application_ids : ids
      if (wanted.some((w) => !ids.includes(w)))
        return refuse(422, "an application is not waiting on this action")
      a.detail.applications = entries.filter(
        (e) => !wanted.includes(e.application_id)
      )
      const remaining = (a.detail.applications as unknown[]).length
      if (remaining === 0)
        close(a, {
          resolution: body.outcome,
          note: body.note ?? null,
          applications: wanted,
        })
      return HttpResponse.json({
        outcome: body.outcome,
        handled: wanted,
        remaining,
        closed: remaining === 0,
      })
    }
  ),
  http.post("*/api/portal-accounts", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as PortalAccountWrite
    const bad = secretKey(body)
    if (bad) return refuse(422, `${bad} is not accepted: no secrets are kept`)
    const key = `${body.portal.toLowerCase()}:${body.tenant.toLowerCase()}`
    if (state.accounts.some((a) => a.key === key))
      return refuse(
        409,
        "an account for this portal tenant is already recorded"
      )
    if (body.status === "signed_in" && !body.signed_in_runner)
      return refuse(
        422,
        "say which runner holds the session (signed_in_runner)"
      )
    const now = new Date().toISOString()
    const a = {
      id: uuid("a", nextId++),
      created_at: now,
      updated_at: now,
      portal: body.portal.toLowerCase(),
      tenant: body.tenant.toLowerCase(),
      key,
      url: body.url ?? null,
      status: body.status ?? "none",
      signed_in_runner: body.signed_in_runner ?? null,
      email_used: body.email_used ?? null,
      last_sign_in_at: body.status === "signed_in" ? now : null,
      notes: body.notes ?? null,
      waiting_applications: 0,
      open_action_id: null,
    }
    state.accounts.push(a)
    return HttpResponse.json(a, { status: 201 })
  }),
  http.get("*/api/portal-accounts/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = state.accounts.find((x) => x.id === String(params.id))
    return a ? HttpResponse.json(a) : notFound("portal account")
  }),
  http.patch("*/api/portal-accounts/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const a = state.accounts.find((x) => x.id === String(params.id))
    if (!a) return notFound("portal account")
    const body = (await request.json()) as PortalAccountPatch
    const bad = secretKey(body)
    if (bad) return refuse(422, `${bad} is not accepted: no secrets are kept`)
    Object.assign(a, body, { updated_at: new Date().toISOString() })
    return HttpResponse.json(a)
  }),
  http.delete("*/api/portal-accounts/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const before = state.accounts.length
    state.accounts = state.accounts.filter((x) => x.id !== String(params.id))
    return state.accounts.length < before
      ? new HttpResponse(null, { status: 204 })
      : notFound("portal account")
  }),

  // ---- releases (what a runner was given and entered) ----
  http.get("*/api/applications/:id/releases", ({ params }) => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(state.releases[String(params.id)] ?? [])
  }),

  // ---- pending actions: one by id, the list filters, and resolve rules ----
  http.get("*/api/pending-actions/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    if (id === "decisions") return undefined // falls through to the decisions handler
    const a = findAction(id)
    return a ? HttpResponse.json(a) : notFound("Pending action")
  }),
  http.get("*/api/pending-actions", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const q = new URL(request.url).searchParams
    const type = q.get("type")
    const kind = q.get("kind")
    if (!type && !kind) return undefined // the applications handler serves the plain list
    const items = applicationsMock().actions.filter(
      (a) =>
        a.status === (q.get("status") ?? "open") &&
        (!type || a.type === type) &&
        (!kind || a.detail.kind === kind)
    )
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.post(
    "*/api/pending-actions/:id/resolve",
    async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const a = findAction(params.id)
      if (!a) return notFound("Pending action")
      const body = (await request.clone().json()) as ResolveIn
      if (!accepts(a, body.resolution))
        return refuse(
          422,
          `'${body.resolution}' does not resolve a ${a.type} action`
        )
      if (body.resolution !== "continue") return undefined // the applications handler records it
      if (a.status !== "open") return refuse(409, "already handled")
      // continue: the tasks go back to the same runner; the group's other continuable actions close too.
      const group = applicationsMock().actions.filter(
        (x) =>
          x.status === "open" &&
          CONTINUABLE.includes(x.type) &&
          (x.id === a.id || (!!a.group_key && x.group_key === a.group_key))
      )
      for (const x of group) {
        const tasks = (x.detail.tasks ?? []) as { task_id: string }[]
        close(x, {
          resolution: "continue",
          note: body.note ?? null,
          via: x === a ? null : a.id,
          runner: x.detail.runner_kind ?? "pc",
          resumed_tasks: tasks.map((t) => t.task_id),
          not_resumed: [],
        })
      }
      return HttpResponse.json(a)
    }
  ),
]
