/**
 * MSW handlers for the wave 3 job-ui endpoints (interview pack, compare, posting changes).
 * TEMPORARY with `features/jobs/w3-pending-types.ts`: replace with handlers typed from the
 * generated contract once the backend routes are in `docs/openapi.json`.
 */
import { http, HttpResponse } from "msw"
import { db } from "../db"
import { applicationsMock } from "./applications"
import { matchesMock } from "./matches"
import {
  makeSection,
  newPackRecord,
  seedChanges,
  SECTION_ORDER,
  type PackRecord,
} from "../dataset/w3-job-ui"
import type {
  CompareJob,
  PackSectionKey,
  PostingChanges,
} from "@/features/jobs/w3-pending-types"

let packs = new Map<string, PackRecord>()
let seeded = false
let changes = seedChanges()
/** Tests set this to make the next generation run out of budget after three sections. */
export const w3JobUiMock = { budgetExhausted: false }

export function resetW3JobUiMock() {
  packs = new Map()
  seeded = false
  changes = seedChanges()
  w3JobUiMock.budgetExhausted = false
}

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const signedIn = () => db.get().session
const STEP = 3

/** The first application at the interview stage starts with a finished pack. */
function seedPacks() {
  if (seeded) return
  seeded = true
  const a = applicationsMock().apps.find((x) => x.stage === "interview")
  if (a)
    packs.set(
      a.id,
      newPackRecord(a.id, a.title, a.employer, { ready: true, untraced: true })
    )
}

/** Each look at a generating pack builds a few more sections. */
function advance(rec: PackRecord) {
  const p = rec.pack
  if (p.status !== "generating") return
  const target = Math.min(p.progress.done + STEP, p.progress.total)
  const stopAt = w3JobUiMock.budgetExhausted ? Math.min(target, STEP) : target
  for (const key of SECTION_ORDER.slice(p.sections.length, stopAt)) {
    const s = makeSection(key, rec)
    p.sections.push(s)
    rec.history[key] = { 1: structuredClone(s.items) }
  }
  p.progress.done = stopAt
  if (w3JobUiMock.budgetExhausted && stopAt >= STEP) {
    p.status = "paused_budget"
    p.paused = { spent_micros: 1_000_000, cap_micros: 1_000_000 }
  } else if (stopAt >= p.progress.total) p.status = "ready"
}

const section = (rec: PackRecord, key: unknown) =>
  rec.pack.sections.find((s) => s.key === (key as PackSectionKey))

const base = "*/api/applications/:id/interview-pack"

export const w3JobUiHandlers = [
  http.get(`${base}/estimate`, () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json({
      cost_micros: 180_000,
      currency: "USD",
      sections: SECTION_ORDER.length,
      model: "Sonnet",
    })
  }),
  http.get(base, ({ params }) => {
    if (!signedIn()) return unauthorized()
    seedPacks()
    const rec = packs.get(String(params.id))
    if (!rec) return notFound("Interview pack")
    advance(rec)
    return HttpResponse.json(rec.pack)
  }),
  http.post(base, ({ params }) => {
    if (!signedIn()) return unauthorized()
    seedPacks()
    const a = applicationsMock().apps.find((x) => x.id === params.id)
    if (!a) return notFound("Application")
    const rec = newPackRecord(a.id, a.title, a.employer, {
      ready: false,
      untraced: false,
    })
    packs.set(a.id, rec)
    return HttpResponse.json(rec.pack, { status: 201 })
  }),
  http.post(`${base}/resume`, ({ params }) => {
    if (!signedIn()) return unauthorized()
    const rec = packs.get(String(params.id))
    if (!rec) return notFound("Interview pack")
    w3JobUiMock.budgetExhausted = false
    rec.pack.status = "generating"
    rec.pack.paused = null
    return HttpResponse.json(rec.pack)
  }),
  http.put(`${base}/sections/:key/notes`, async ({ params, request }) => {
    const rec = packs.get(String(params.id))
    const s = rec && section(rec, params.key)
    if (!s) return notFound("Section")
    s.notes = ((await request.json()) as { notes: string }).notes
    return HttpResponse.json(rec.pack)
  }),
  http.put(
    `${base}/sections/:key/items/:itemId`,
    async ({ params, request }) => {
      const rec = packs.get(String(params.id))
      const s = rec && section(rec, params.key)
      const it = s?.items.find((i) => i.id === params.itemId)
      if (!rec || !s || !it) return notFound("Item")
      const body = (await request.json()) as { text: string }
      it.text = body.text
      // Re-traced by the server: a changed figure no longer matches its fact.
      if (it.owner_claim && it.fact_ids.length === 0) it.flag = "untraced"
      return HttpResponse.json(rec.pack)
    }
  ),
  http.post(`${base}/sections/:key/regenerate`, ({ params }) => {
    const rec = packs.get(String(params.id))
    const s = rec && section(rec, params.key)
    if (!rec || !s) return notFound("Section")
    const next = s.versions.length + 1
    s.versions.push({
      version: next,
      created_at: new Date().toISOString(),
      note: "Regenerated",
    })
    s.version = next
    s.items = s.items.map((i) => ({
      ...i,
      text: i.text ? `${i.text.replace(/ \(v\d+\)$/, "")} (v${next})` : i.text,
    }))
    rec.history[s.key][next] = structuredClone(s.items)
    return HttpResponse.json(rec.pack)
  }),
  http.post(`${base}/sections/:key/restore`, async ({ params, request }) => {
    const rec = packs.get(String(params.id))
    const s = rec && section(rec, params.key)
    if (!rec || !s) return notFound("Section")
    const { version } = (await request.json()) as { version: number }
    const items = rec.history[s.key]?.[version]
    if (!items) return notFound("Version")
    s.version = version
    s.items = structuredClone(items)
    return HttpResponse.json(rec.pack)
  }),
  http.put(`${base}/items/:itemId/favourite`, async ({ params, request }) => {
    const rec = packs.get(String(params.id))
    if (!rec) return notFound("Interview pack")
    const { favourite } = (await request.json()) as { favourite: boolean }
    for (const s of rec.pack.sections)
      for (const i of s.items)
        if (i.id === params.itemId) i.favourite = favourite
    return HttpResponse.json(rec.pack)
  }),
  http.post(`${base}/practice`, async ({ params, request }) => {
    const rec = packs.get(String(params.id))
    if (!rec) return notFound("Interview pack")
    const body = (await request.json()) as {
      question_id: string
      draft: string
    }
    const q = section(rec, "questions")?.items.find(
      (i) => i.id === body.question_id
    )
    return HttpResponse.json({
      feedback: `Clear and specific. Anchor it in the facts below${q?.question ? ` when you answer "${q.question}"` : ""}, and give the outcome last.`,
      fact_ids: q?.fact_ids ?? [],
      gaps: body.draft.length < 60 ? ["Answer is short: add the result"] : [],
    })
  }),
  http.get(`${base}/export`, ({ request }) => {
    const format = new URL(request.url).searchParams.get("format") ?? "txt"
    return new HttpResponse("Interview pack (mock export)", {
      headers: {
        "content-type": "text/plain",
        "content-disposition": `attachment; filename="interview-pack.${format}"`,
      },
    })
  }),

  // ---- compare ----
  http.get("*/api/jobs/compare", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const ids = (new URL(request.url).searchParams.get("ids") ?? "")
      .split(",")
      .filter(Boolean)
    const st = matchesMock.get()
    const jobs: CompareJob[] = []
    for (const id of ids) {
      const j = st.jobs.find((x) => x.id === id)
      if (!j) return notFound("Role")
      const a = st.assessments.get(id)?.[0]
      const facets = j.facets as unknown as Record<
        string,
        { value: unknown } | null
      >
      const yn = (k: string, label: string) => ({
        key: k,
        label,
        value: String(facets[k]?.value ?? "not_stated"),
      })
      const pay = j.pay
      const perYear =
        pay.period === "year" ? 1 : pay.period === "month" ? 12 : null
      jobs.push({
        job_id: j.id,
        title: j.title,
        employer: j.canonical_employer,
        score: j.best_score,
        facets: [
          yn("relocation_required", "Relocation required"),
          yn("visa_sponsorship", "Visa sponsorship"),
          yn("relocation_assistance", "Relocation help"),
          yn("needs_account", "Needs an account to apply"),
          yn("work_model", "Work model"),
        ],
        pay:
          pay.state === "stated" && perYear && pay.currency
            ? {
                state: "comparable",
                min_minor:
                  pay.min_minor == null ? null : pay.min_minor * perYear,
                max_minor:
                  pay.max_minor == null ? null : pay.max_minor * perYear,
                currency: pay.currency,
                period: "year",
                note: perYear === 1 ? null : "Yearly equivalent",
              }
            : {
                state:
                  pay.state === "not_stated" ? "not_stated" : "not_comparable",
                min_minor: null,
                max_minor: null,
                currency: null,
                period: null,
                note:
                  pay.state === "estimated"
                    ? "Estimated, not from the posting"
                    : null,
              },
        criteria: (a?.ratings ?? []).map((r) => ({
          criterion: r.criterion,
          rating: r.rating,
        })),
        gates: (a?.filter_results ?? []).map((f) => ({
          name: f.name,
          result: f.result,
        })),
        conflict: { state: j.conflict_state, note: j.conflict_note },
        deadline: j.deadline,
        channel: {
          method: j.apply_method,
          effort:
            j.apply_method === "email"
              ? "low"
              : j.apply_method === "browser"
                ? "medium"
                : "unknown",
          note: null,
        },
      })
    }
    return HttpResponse.json({ jobs })
  }),

  // ---- posting changes ----
  http.get("*/api/jobs/:id/changes", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const c: PostingChanges = changes[String(params.id)] ?? {
      items: [],
      stale_packet: null,
    }
    return HttpResponse.json(c)
  }),
]
