/**
 * Mock backend for the Job page's own calls: corrections (merge, split, employer), score
 * overrides and people. Roles, assessments and the application come from their owners
 * (matches.ts, applications.ts) so every screen shows the same data.
 */
import { http, HttpResponse } from "msw"
import { db } from "../db"
import { seedContacts } from "../data/contacts"
import { matchesMock } from "./matches"
import type { MockJob } from "../data/jobs"

let contacts = seedContacts()
export const jobAudit: {
  id: string
  created_at: string
  actor: string
  action: string
  subject_type: string
  subject_id: string
  detail: Record<string, unknown>
  ip: null
}[] = []

/** Contacts and the corrections log; the roles themselves are the shared Matches store. */
export function resetJobsMock() {
  contacts = seedContacts()
  jobAudit.length = 0
}

const jobs = () => matchesMock.get().jobs

const signedIn = () => db.get().session
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const missing = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const bad = (detail: string) => HttpResponse.json({ detail }, { status: 422 })
const find = (id: unknown) => jobs().find((j) => j.id === String(id))
const touch = (j: MockJob) => {
  j.updated_at = new Date().toISOString()
  return j
}
const log = (job: MockJob, action: string, detail: Record<string, unknown>) =>
  jobAudit.unshift({
    id: crypto.randomUUID(),
    created_at: new Date().toISOString(),
    actor: "owner",
    action,
    subject_type: "job",
    subject_id: job.id,
    detail,
    ip: null,
  })

export const jobHandlers = [
  http.post("*/api/jobs/:id/merge", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const { duplicate_ids } = (await request.json()) as {
      duplicate_ids: string[]
    }
    for (const d of jobs().filter((x) => duplicate_ids.includes(x.id))) {
      j.sightings.push(...d.sightings)
      j.tags = [...new Set([...j.tags, ...d.tags])]
    }
    matchesMock.get().jobs = jobs().filter((x) => !duplicate_ids.includes(x.id))
    log(j, "job.merge", { duplicate_ids })
    return HttpResponse.json(touch(j))
  }),
  http.post("*/api/jobs/:id/split", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const { sighting_urls } = (await request.json()) as {
      sighting_urls: string[]
    }
    const moved = j.sightings.filter((s) => sighting_urls.includes(s.url))
    j.sightings = j.sightings.filter((s) => !sighting_urls.includes(s.url))
    jobs().push({
      ...j,
      id: crypto.randomUUID(),
      sightings: moved,
      application_id: null,
      tags: [],
    })
    log(j, "job.split", { sighting_urls })
    return HttpResponse.json(touch(j))
  }),
  http.post("*/api/jobs/:id/employer", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const b = (await request.json()) as { canonical_employer: string }
    j.canonical_employer = b.canonical_employer
    log(j, "job.employer_fixed", b)
    return HttpResponse.json(touch(j))
  }),

  http.post("*/api/assessments/:id/override", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const a = [...matchesMock.get().assessments.values()]
      .flat()
      .find((x) => x.id === String(params.id))
    if (!a) return missing("Assessment")
    const b = (await request.json()) as { score: number | null; reason: string }
    a.override = {
      by: "owner",
      reason: b.reason,
      at: new Date().toISOString(),
      score: b.score,
    }
    if (b.score != null) a.score = b.score
    return HttpResponse.json(a)
  }),

  http.get("*/api/contacts", () =>
    !signedIn()
      ? unauthorized()
      : HttpResponse.json({
          items: contacts,
          total: contacts.length,
          next_cursor: null,
        })
  ),
  http.post("*/api/contacts", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const b = (await request.json()) as Omit<
      (typeof contacts)[number],
      "id" | "created_at" | "updated_at" | "origin"
    >
    if (!b.name?.trim()) return bad("A name is required.")
    const now = new Date().toISOString()
    const c = {
      ...b,
      role: b.role ?? null,
      email: b.email ?? null,
      link: b.link ?? null,
      notes: b.notes ?? null,
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
      origin: "owner",
    }
    contacts.push(c)
    return HttpResponse.json(c, { status: 201 })
  }),
  http.put("*/api/contacts/:id", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const i = contacts.findIndex((c) => c.id === String(params.id))
    if (i < 0) return missing("Person")
    contacts[i] = {
      ...contacts[i],
      ...((await request.json()) as object),
      updated_at: new Date().toISOString(),
    }
    return HttpResponse.json(contacts[i])
  }),
  http.delete("*/api/contacts/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    contacts = contacts.filter((c) => c.id !== String(params.id))
    return new HttpResponse(null, { status: 204 })
  }),
]
