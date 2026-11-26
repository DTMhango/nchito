/**
 * MSW handlers for the Autopilot, approvals, dispatch, handoff and trusted-site endpoints.
 * Application, campaign, settings, job and pending-action endpoints are served by the wave 1
 * handlers; this file adds only what wave 2 needs and resets with `resetAutopilotMock`.
 */
import { http, HttpResponse } from "msw"
import { db } from "../db"
import { applicationsMock } from "./applications"
import {
  dispatchesFor,
  handoffFor,
  packetsFor,
  receiptFor,
  seedAutopilot,
  type MockAutopilot,
} from "../dataset/autopilot"

let state: MockAutopilot = seedAutopilot()

export const resetAutopilotMock = () => {
  state = seedAutopilot()
}
export const autopilotMock = () => state

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const app = (id: unknown) =>
  applicationsMock().apps.find((a) => a.id === String(id))

const dispatchesOf = (a: NonNullable<ReturnType<typeof app>>) =>
  (state.dispatches[a.id] ??= dispatchesFor(a))

export const autopilotHandlers = [
  // Pause cancels queued sends and lists what already left (DESIGN 8.1). Wins over the wave 0 stub.
  http.put("*/api/autopilot", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const { paused } = (await request.json()) as { paused: boolean }
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
      s.autopilot.paused_at = paused ? new Date().toISOString() : null
      if (paused)
        s.autopilot.summary = {
          cancelled,
          paused: [],
          already_out: alreadyOut,
        }
    })
    return HttpResponse.json(db.get().autopilot)
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
      return HttpResponse.json(
        {
          detail:
            "The packet changed since you opened it. Review the new version first.",
        },
        { status: 409 }
      )
    current.approved_at = new Date().toISOString()
    current.approved_by = "owner"
    a.stage = "applying"
    for (const p of applicationsMock().actions)
      if (p.application_id === a.id && p.type === "approve") {
        p.status = "resolved"
        a.open_pending_actions = Math.max(0, a.open_pending_actions - 1)
      }
    return HttpResponse.json(a)
  }),

  http.get("*/api/applications/:id/dispatches", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    return a ? HttpResponse.json(dispatchesOf(a)) : notFound("Application")
  }),
  http.post("*/api/applications/:id/dispatches/:did/cancel", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const a = app(params.id)
    if (!a) return notFound("Application")
    const d = dispatchesOf(a).find((x) => x.id === String(params.did))
    if (!d) return notFound("Dispatch")
    if (d.status !== "reserved")
      return HttpResponse.json(
        { detail: "It has already left the outbox, so it can't be cancelled." },
        { status: 409 }
      )
    d.status = "cancelled"
    return HttpResponse.json(d)
  }),
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
    const now = new Date().toISOString()
    const site = {
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
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
