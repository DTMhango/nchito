/**
 * MSW handlers for the Autopilot, approvals, dispatch, restore, handoff and trusted-site
 * endpoints, shaped like the real wave 2 API. Application, campaign, settings, job and
 * pending-action endpoints are served by the wave 1 handlers; this file adds only what wave 2
 * needs and resets with `resetAutopilotMock`.
 */
import { http, HttpResponse } from "msw"
import type {
  DispatchCreateOut,
  DispatchOut,
  ReconcileIn,
  RestoreStateOut,
} from "@/features/autopilot/api"
import { db } from "../db"
import { applicationsMock } from "./applications"
import {
  dispatchEvents,
  dispatchesFor,
  gatesFor,
  handoffFor,
  mailProposalFor,
  packetsFor,
  receiptFor,
  seedAutopilot,
  type MockAutopilot,
} from "../dataset/autopilot"

type Restore = Omit<RestoreStateOut, "outstanding">
const NO_RESTORE: Restore = {
  active: false,
  entered_at: null,
  backup_taken_at: null,
  held_application_ids: [],
}

let state: MockAutopilot = seedAutopilot()
let restore: Restore = { ...NO_RESTORE }

/** Runs after `resetApplicationsMock` (see reset.ts): adds the dispatch timeline and a mail proposal. */
export const resetAutopilotMock = () => {
  state = seedAutopilot()
  restore = { ...NO_RESTORE }
  const apps = applicationsMock()
  for (const a of apps.apps)
    (apps.events[a.id] ??= []).push(...dispatchEvents(a, dispatchesOf(a)))
  const fintech = apps.apps.find((a) => a.employer === "Lusaka Fintech Co")
  if (fintech) {
    apps.actions.push(mailProposalFor(fintech))
    fintech.open_pending_actions += 1
  }
}
export const autopilotMock = () => state

/** Enter paused-for-restore (what `nchito restore --yes` does), for tests and demos. */
export const enterRestoreMock = (backupTakenAt: string) => {
  restore = {
    active: true,
    entered_at: new Date().toISOString(),
    backup_taken_at: backupTakenAt,
    held_application_ids: [],
  }
  db.update((s) => {
    s.autopilot.paused = true
    s.autopilot.paused_at = restore.entered_at
    s.autopilot.paused_by = "system"
    s.autopilot.reason = "restored from a backup"
  })
}

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const refused = (detail: Record<string, unknown>) =>
  HttpResponse.json({ detail }, { status: 409 })
const app = (id: unknown) =>
  applicationsMock().apps.find((a) => a.id === String(id))

const dispatchesOf = (a: NonNullable<ReturnType<typeof app>>) =>
  (state.dispatches[a.id] ??= dispatchesFor(a))

/** Uncertain attempts made after the backup was taken: these block the resume. */
const outstanding = (): DispatchOut[] =>
  restore.active
    ? applicationsMock()
        .apps.flatMap((a) => dispatchesOf(a))
        .filter((d) => d.uncertain)
    : []

const now = () => new Date().toISOString()

export const autopilotHandlers = [
  // Pause cancels queued sends and lists what already left (DESIGN 8.1). Wins over the wave 0 stub.
  http.put("*/api/autopilot", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const { paused, reason } = (await request.json()) as {
      paused: boolean
      reason?: string | null
    }
    if (!paused && restore.active)
      return refused({
        code: "restore_paused",
        reason: "paused for a restore: use resume-after-restore",
      })
    const cancelled: { id: string; label: string; detail: string }[] = []
    const alreadyOut: typeof cancelled = []
    if (paused)
      for (const a of applicationsMock().apps) {
        for (const d of dispatchesOf(a)) {
          const item = {
            id: d.id,
            label: `${a.title}, ${a.employer}`,
            detail: "",
          }
          if (d.status === "reserved") {
            d.status = "cancelled"
            cancelled.push({ ...item, detail: "Queued email cancelled." })
          } else if (["sent", "acknowledged", "handed_off"].includes(d.status))
            alreadyOut.push({
              ...item,
              detail: "Already handed over. It can't be recalled.",
            })
        }
      }
    db.update((s) => {
      s.autopilot.paused = paused
      s.autopilot.paused_at = paused ? now() : null
      s.autopilot.paused_by = paused ? "owner" : null
      s.autopilot.reason = paused ? (reason ?? null) : null
      s.autopilot.summary = paused
        ? { cancelled, paused: [], already_out: alreadyOut }
        : { cancelled: [], paused: [], already_out: [] }
    })
    return HttpResponse.json(db.get().autopilot)
  }),
  http.get("*/api/autopilot/restore", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json({ ...restore, outstanding: outstanding() })
  }),
  http.post("*/api/autopilot/resume-after-restore", () => {
    if (!db.get().session) return unauthorized()
    const left = outstanding()
    if (left.length > 0)
      return refused({
        code: "restore_unreconciled",
        reason: "uncertain sends must be reconciled first",
        outstanding: left.map((d) => d.id),
      })
    restore = { ...NO_RESTORE }
    db.update((s) => {
      s.autopilot.paused = false
      s.autopilot.paused_at = null
      s.autopilot.paused_by = null
      s.autopilot.reason = null
    })
    return HttpResponse.json({ ok: true })
  }),
  http.get("*/api/tokens/runners", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(state.runners)
  }),

  http.get("*/api/applications/:id/packets", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    return a ? HttpResponse.json(packetsFor(a, state)) : notFound("Application")
  }),
  http.get("*/api/applications/:id/packet", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    if (!a) return notFound("Application")
    const current = [...packetsFor(a, state)]
      .filter((p) => !p.invalidated_at)
      .sort((x, y) => y.version - x.version)[0]
    return current
      ? HttpResponse.json(current)
      : HttpResponse.json(
          { detail: "no packet has been built" },
          { status: 404 }
        )
  }),
  http.get("*/api/applications/:id/receipt", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    if (!a) return notFound("Application")
    return HttpResponse.json(receiptFor(a, packetsFor(a, state)))
  }),
  http.post("*/api/applications/:id/approve", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    if (!a) return notFound("Application")
    const body = (await request.json()) as {
      packet_version: number
      packet_hash: string
    }
    const packets = packetsFor(a, state)
    const current = [...packets].sort((x, y) => y.version - x.version)[0]
    if (
      current.version !== body.packet_version ||
      current.content_hash !== body.packet_hash
    )
      return refused({
        code: "approval_refused",
        reason:
          "The packet changed since you opened it. Review the new version first.",
      })
    if (state.refuseApproval)
      return refused({
        code: "approval_refused",
        reason: state.refuseApproval,
        gates: gatesFor(a).filter((g) => g.outcome !== "pass"),
      })
    current.approved_at = now()
    current.approved_by = "owner"
    for (const p of applicationsMock().actions)
      if (p.application_id === a.id && p.type === "approve") {
        p.status = "resolved"
        a.open_pending_actions = Math.max(0, a.open_pending_actions - 1)
      }
    return HttpResponse.json(a)
  }),
  http.post("*/api/applications/:id/reject", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    if (!a) return notFound("Application")
    const body = (await request.json()) as { reason?: string | null }
    a.stage = "skipped"
    state.decisions.push({
      id: a.id,
      kind: "reject",
      text: body.reason ?? null,
    })
    return HttpResponse.json(a)
  }),
  http.post(
    "*/api/applications/:id/request-changes",
    async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const a = app(params.id)
      if (!a) return notFound("Application")
      const body = (await request.json()) as { note: string }
      for (const p of packetsFor(a, state))
        if (!p.invalidated_at) {
          p.invalidated_at = now()
          p.invalidated_reason = `Changes requested: ${body.note}`
        }
      a.stage = "tailoring"
      state.decisions.push({ id: a.id, kind: "changes", text: body.note })
      return HttpResponse.json(a)
    }
  ),

  http.get("*/api/applications/:id/dispatches", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    return a ? HttpResponse.json(dispatchesOf(a)) : notFound("Application")
  }),
  http.post("*/api/applications/:id/dispatches", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    if (!a) return notFound("Application")
    const approved = packetsFor(a, state).find(
      (p) => p.approved_at && !p.invalidated_at
    )
    const out: DispatchCreateOut = {
      status: "denied",
      reason: "nothing approved is waiting",
      dispatch: null,
      gates: [],
      pending_action_id: null,
    }
    if (db.get().autopilot.paused)
      return HttpResponse.json({
        ...out,
        reason: "automatic sending is paused",
      })
    if (!approved) return HttpResponse.json(out)
    const d: DispatchOut = {
      id: crypto.randomUUID(),
      created_at: now(),
      updated_at: now(),
      application_id: a.id,
      packet_hash: approved.content_hash,
      channel: a.channel ?? "email",
      status: "reserved",
      send_after: new Date(Date.now() + 10 * 60_000).toISOString(),
      provider_message_id: null,
      outcome_at: null,
      gate_results: gatesFor(a),
      error: null,
      started_at: null,
      evidence: null,
      uncertain: false,
      reconcile_attempts: 0,
      last_reconciled_at: null,
    }
    dispatchesOf(a).unshift(d)
    a.stage = "applying"
    return HttpResponse.json({
      ...out,
      status: "queued",
      reason: "every gate passed",
      dispatch: d,
      gates: d.gate_results,
    })
  }),
  http.post("*/api/applications/:id/dispatches/:did/cancel", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    if (!a) return notFound("Application")
    const d = dispatchesOf(a).find((x) => x.id === String(params.did))
    if (!d) return notFound("Dispatch")
    if (d.status !== "reserved" || d.started_at)
      return HttpResponse.json(
        { detail: "already handed over: it can no longer be cancelled" },
        { status: 409 }
      )
    d.status = "cancelled"
    return HttpResponse.json(d)
  }),
  http.post(
    "*/api/applications/:id/dispatches/:did/reconcile",
    async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const a = app(params.id)
      if (!a) return notFound("Application")
      const d = dispatchesOf(a).find((x) => x.id === String(params.did))
      if (!d) return notFound("Dispatch")
      if (!d.uncertain)
        return HttpResponse.json(
          { detail: "this send is not uncertain" },
          { status: 409 }
        )
      const body = (await request.json()) as ReconcileIn
      d.reconcile_attempts += 1
      d.last_reconciled_at = now()
      if (body.decision === "check")
        return HttpResponse.json({ result: "waiting", dispatch: d })
      d.uncertain = false
      d.outcome_at = now()
      if (body.decision === "sent") {
        d.status = "sent"
        d.evidence = {
          kind: "owner_marked",
          value: body.reference || "Confirmed by you",
          screenshot_ref: null,
          at: now(),
        }
        a.stage = "submitted"
      } else {
        d.status = "failed"
        d.error = "You checked: it did not go out."
        a.stage = "ready"
      }
      return HttpResponse.json({ result: body.decision, dispatch: d })
    }
  ),
  http.get("*/api/applications/:id/handoff", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    return a ? HttpResponse.json(handoffFor(a)) : notFound("Application")
  }),

  http.get("*/api/trusted-sites", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json({
      items: state.trusted,
      total: state.trusted.length,
      next_cursor: null,
    })
  }),
  http.post("*/api/trusted-sites", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as {
      domain: string
      system?: string | null
      note?: string | null
    }
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(body.domain))
      return HttpResponse.json(
        { detail: "Enter a domain such as careers.example.com." },
        { status: 422 }
      )
    if (state.trusted.some((t) => t.domain === body.domain))
      return HttpResponse.json(
        { detail: "That site is already trusted." },
        { status: 409 }
      )
    const site = {
      id: crypto.randomUUID(),
      created_at: now(),
      updated_at: now(),
      domain: body.domain,
      system: body.system ?? null,
      note: body.note ?? null,
      trusted_by: "owner",
    }
    state.trusted.push(site)
    return HttpResponse.json(site, { status: 201 })
  }),
  http.delete("*/api/trusted-sites/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    state.trusted = state.trusted.filter((t) => t.id !== String(params.id))
    return new HttpResponse(null, { status: 204 })
  }),
]
