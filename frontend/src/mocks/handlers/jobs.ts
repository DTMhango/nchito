/** Mock backend for the job page: roles, assessments, application, people and corrections. */
import { http, HttpResponse } from "msw"
import { db } from "../db"
import {
  buildApplication,
  buildAssessments,
  buildContacts,
  buildJobs,
  buildPending,
  buildTimeline,
} from "../fixtures/jobs"
import type { JobDetail, JobPatch } from "@/features/jobs/api"

let jobs = buildJobs()
let assessments = buildAssessments()
let contacts = buildContacts()
const app = buildApplication()
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

export function resetJobsMock() {
  jobs = buildJobs()
  assessments = buildAssessments()
  contacts = buildContacts()
  jobAudit.length = 0
}

const signedIn = () => db.get().session
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const missing = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const bad = (detail: string) => HttpResponse.json({ detail }, { status: 422 })
const find = (id: unknown) => jobs.find((j) => j.id === String(id))
const touch = (j: JobDetail) => {
  j.updated_at = new Date().toISOString()
  return j
}
const log = (job: JobDetail, action: string, detail: Record<string, unknown>) =>
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
  http.get("*/api/jobs", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const q = new URL(request.url).searchParams.get("q")?.toLowerCase() ?? ""
    const items = jobs.filter(
      (j) =>
        !q ||
        [j.title, j.employer, j.canonical_employer].some((s) =>
          s.toLowerCase().includes(q)
        )
    )
    return HttpResponse.json({ items, total: items.length, next_cursor: null, groups: null })
  }),
  http.get("*/api/jobs/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    return j ? HttpResponse.json(j) : missing("Role")
  }),
  http.patch("*/api/jobs/:id", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const b = (await request.json()) as JobPatch
    if (b.triage != null) j.triage = b.triage
    if (b.pinned != null) j.pinned = b.pinned
    if (b.notes !== undefined) j.notes = b.notes
    if (b.tags != null) j.tags = b.tags
    return HttpResponse.json(touch(j))
  }),
  http.get("*/api/jobs/:id/why", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const held = j.conflict_state === "held"
    return HttpResponse.json({
      decision: held ? "Held" : "Shortlisted",
      rules: [
        {
          rule: "One role per employer",
          effective_value: "Same department",
          source: "Settings default",
          version: null,
          outcome: held ? "fail" : "pass",
          reason: held ? "A higher-scoring role at the same employer is ahead of it." : "It is the highest-scoring role at this employer.",
          would_change_if: held ? "You release this role, or the winner closes." : null,
        },
        {
          rule: "Shortlist threshold",
          effective_value: "60",
          source: "Settings default",
          version: "rubric v3",
          outcome: "pass",
          reason: `Score ${j.best_score ?? "unknown"} is at or above 60.`,
          would_change_if: null,
        },
      ],
      conditions: [],
    })
  }),
  http.post("*/api/jobs/:id/release", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const { reason } = (await request.json()) as { reason: string }
    if (!reason?.trim()) return bad("A reason is required.")
    j.conflict_state = "released"
    j.conflict_note = reason
    log(j, "job.release", { reason })
    return HttpResponse.json(touch(j))
  }),
  http.post("*/api/jobs/:id/recheck", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    j.last_checked_at = new Date().toISOString()
    return HttpResponse.json(touch(j))
  }),
  http.post("*/api/jobs/:id/applied-myself", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    log(j, "job.applied_myself", await request.json() as Record<string, unknown>)
    return HttpResponse.json({ ok: true })
  }),
  http.post("*/api/jobs/:id/merge", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const { duplicate_ids } = (await request.json()) as { duplicate_ids: string[] }
    for (const d of jobs.filter((x) => duplicate_ids.includes(x.id))) {
      j.sightings.push(...d.sightings)
      j.tags = [...new Set([...j.tags, ...d.tags])]
    }
    jobs = jobs.filter((x) => !duplicate_ids.includes(x.id))
    log(j, "job.merge", { duplicate_ids })
    return HttpResponse.json(touch(j))
  }),
  http.post("*/api/jobs/:id/split", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = find(params.id)
    if (!j) return missing("Role")
    const { sighting_urls } = (await request.json()) as { sighting_urls: string[] }
    const moved = j.sightings.filter((s) => sighting_urls.includes(s.url))
    j.sightings = j.sightings.filter((s) => !sighting_urls.includes(s.url))
    jobs.push({ ...j, id: `job-${jobs.length + 1}`, sightings: moved, application_id: null, tags: [] })
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

  http.get("*/api/assessments", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const id = new URL(request.url).searchParams.get("job_id")
    const items = assessments.filter((a) => !id || a.job_id === id)
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.post("*/api/assessments/:id/override", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const a = assessments.find((x) => x.id === String(params.id))
    if (!a) return missing("Assessment")
    const b = (await request.json()) as { score: number | null; reason: string }
    a.override = { by: "owner", reason: b.reason, at: new Date().toISOString(), score: b.score }
    if (b.score != null) a.score = b.score
    return HttpResponse.json(a)
  }),

  http.get("*/api/applications/:id", ({ params }) =>
    !signedIn() ? unauthorized() : String(params.id) === app.id ? HttpResponse.json(app) : missing("Application")
  ),
  http.get("*/api/applications/:id/timeline", () =>
    !signedIn() ? unauthorized() : HttpResponse.json(buildTimeline())
  ),
  http.get("*/api/pending-actions", () =>
    !signedIn() ? unauthorized() : HttpResponse.json({ items: buildPending(), total: 1, next_cursor: null })
  ),

  http.get("*/api/contacts", () =>
    !signedIn() ? unauthorized() : HttpResponse.json({ items: contacts, total: contacts.length, next_cursor: null })
  ),
  http.post("*/api/contacts", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const b = (await request.json()) as Omit<(typeof contacts)[number], "id" | "created_at" | "updated_at" | "origin">
    if (!b.name?.trim()) return bad("A name is required.")
    const now = new Date().toISOString()
    const c = { role: null, email: null, link: null, notes: null, ...b, id: crypto.randomUUID(), created_at: now, updated_at: now, origin: "owner" }
    contacts.push(c)
    return HttpResponse.json(c, { status: 201 })
  }),
  http.put("*/api/contacts/:id", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const i = contacts.findIndex((c) => c.id === String(params.id))
    if (i < 0) return missing("Person")
    contacts[i] = { ...contacts[i], ...((await request.json()) as object), updated_at: new Date().toISOString() }
    return HttpResponse.json(contacts[i])
  }),
  http.delete("*/api/contacts/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    contacts = contacts.filter((c) => c.id !== String(params.id))
    return new HttpResponse(null, { status: 204 })
  }),
]
