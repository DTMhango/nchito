/**
 * MSW handlers for the Matches screen: jobs (list, facets, detail, patch, bulk, why,
 * corrections), assessments, saved views, tag rules, custom facets and the campaign calls
 * "Use as campaign rule" needs. State lives here, in memory, and resets with `resetMatchesMock`.
 */
import { delay, http, HttpResponse } from "msw"
import { db } from "@/mocks/db"
import type { RecheckResult } from "@/lib/api/types"
import type {
  AppliedMyselfIn,
  AssessmentOut,
  ConditionSet,
  CustomFacetIn,
  CustomFacetOut,
  FacetCatalogEntry,
  JobPatch,
  SavedViewIn,
  SavedViewOut,
  TagRuleIn,
  TagRuleOut,
  WhyOut,
} from "@/features/matches/types"
import {
  assessmentFor,
  CAMPAIGNS,
  makeJobs,
  seedCustomFacets,
  seedTagRules,
  seedViews,
  type MockJob,
} from "@/mocks/dataset/jobs"
import { groupCounts, matches, NOT_STATED } from "./matches-evaluator"

type State = {
  jobs: MockJob[]
  assessments: Map<string, AssessmentOut[]>
  views: SavedViewOut[]
  tagRules: TagRuleOut[]
  customFacets: CustomFacetOut[]
}

function seed(): State {
  const jobs = makeJobs()
  const assessments = new Map<string, AssessmentOut[]>()
  jobs.forEach((j, i) => assessments.set(j.id, [assessmentFor(j, i)]))
  return {
    jobs,
    assessments,
    views: seedViews(),
    tagRules: seedTagRules(),
    customFacets: seedCustomFacets(),
  }
}

let state = seed()

/** Fresh fixtures (tests call this in beforeEach). */
export function resetMatchesMock() {
  state = seed()
}
/** Read access for tests. */
export const matchesMock = { get: () => state }

const latency = () =>
  import.meta.env.MODE === "test" ? Promise.resolve() : delay(90)
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const signedIn = () => db.get().session

// ---- helpers ----------------------------------------------------------------------------------

const now = () => new Date().toISOString()

function summary(j: MockJob) {
  // The contract's JobSummary, plus two display hints (work model, source) the list reads
  // when present.
  return {
    id: j.id,
    created_at: j.created_at,
    updated_at: j.updated_at,
    title: j.title,
    employer: j.employer,
    canonical_employer: j.canonical_employer,
    location: j.location,
    triage: j.triage,
    best_score: j.best_score,
    conflict_state: j.conflict_state,
    conflict_note: j.conflict_note,
    pay: j.pay,
    deadline: j.deadline,
    availability: j.availability,
    tags: j.tags,
    pinned: j.pinned,
    posted_at: j.posted_at,
    work_model: j.facets.work_model?.value ?? NOT_STATED,
    source: j.source,
  }
}

function detail(j: MockJob) {
  const { snoozed_until: _snoozed, ...rest } = j
  void _snoozed
  return rest
}

const isSnoozed = (j: MockJob) =>
  !!j.snoozed_until && Date.parse(j.snoozed_until) > Date.now()

function visible(set: ConditionSet | undefined, q?: string | null) {
  const text = q?.trim()
  const textSet: ConditionSet | undefined = text
    ? {
        version: 1,
        root: {
          type: "group",
          op: "and",
          negate: false,
          conditions: [
            {
              type: "text",
              query: text,
              fields: ["title", "employer", "raw_text"],
            },
          ],
        },
      }
    : undefined
  return state.jobs.filter(
    (j) => !isSnoozed(j) && matches(j, set) && matches(j, textSet)
  )
}

function sortJobs(list: MockJob[], sort: string | null) {
  const s = sort || "-best_score"
  const desc = s.startsWith("-")
  const field = s.replace(/^-/, "")
  const key = (j: MockJob): string | number => {
    switch (field) {
      case "posted_at":
        return j.posted_at ? Date.parse(j.posted_at) : 0
      case "deadline":
        return j.deadline.on
          ? Date.parse(j.deadline.on)
          : Number.MAX_SAFE_INTEGER
      case "employer":
        return j.employer.toLowerCase()
      case "title":
        return j.title.toLowerCase()
      default:
        return j.best_score ?? -1
    }
  }
  return [...list].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    const ka = key(a)
    const kb = key(b)
    const c = ka < kb ? -1 : ka > kb ? 1 : 0
    return desc ? -c : c
  })
}

function parseSet(raw: string | null): ConditionSet | undefined {
  if (!raw) return undefined
  try {
    return JSON.parse(raw) as ConditionSet
  } catch {
    return undefined
  }
}

/** The jobs a Matches list shows for these conditions and text (what "everything matching this view" means). */
export const viewJobs = (conditions: string | null, q?: string | null) =>
  visible(parseSet(conditions), q)

const FACETS: { facet: string; label: string; kind?: "range" }[] = [
  { facet: "facets.relocation_required", label: "Relocation required" },
  { facet: "facets.visa_sponsorship", label: "Sponsorship offered" },
  { facet: "facets.relocation_assistance", label: "Relocation assistance" },
  { facet: "facets.work_model", label: "Work model" },
  { facet: "facets.remote_scope", label: "Remote scope" },
  { facet: "facets.work_rights", label: "Work rights" },
  { facet: "pay.state", label: "Pay" },
  { facet: "facets.min_education.level", label: "Minimum education" },
  { facet: "facets.required_skills", label: "Requires skill" },
  { facet: "facets.employment_type", label: "Employment type" },
  { facet: "facets.hiring_arrangement", label: "Hiring arrangement" },
  { facet: "location.country", label: "Country" },
  { facet: "deadline.state", label: "Deadline" },
  { facet: "function", label: "Function" },
  { facet: "level", label: "Level" },
  { facet: "facets.industry", label: "Industry" },
  { facet: "source", label: "Source" },
  { facet: "tags", label: "Tags" },
  {
    facet: "facets.years_experience",
    label: "Years of experience",
    kind: "range",
  },
]

/** Enum facets keep "not stated" in the catalogue even when no job has it. */
const THREE_STATE = new Set([
  "facets.relocation_required",
  "facets.visa_sponsorship",
  "facets.relocation_assistance",
  "facets.work_model",
  "facets.remote_scope",
  "facets.work_rights",
  "facets.employment_type",
  "facets.hiring_arrangement",
  "pay.state",
  "deadline.state",
])

function catalog(): FacetCatalogEntry[] {
  const jobs = state.jobs
  const entries: FacetCatalogEntry[] = FACETS.map((f) => {
    if (f.kind === "range")
      return { facet: f.facet, label: f.label, kind: "range", values: [] }
    const counts = groupCounts(jobs, f.facet).filter(
      (c) => f.facet !== "tags" || c.value !== NOT_STATED
    )
    if (THREE_STATE.has(f.facet) && !counts.some((c) => c.value === NOT_STATED))
      counts.push({ value: NOT_STATED, count: 0 })
    return { facet: f.facet, label: f.label, kind: "values", values: counts }
  })
  for (const cf of state.customFacets.filter((c) => c.enabled !== false)) {
    const facet = `custom_facets.${cf.key}`
    const counts = groupCounts(jobs, facet)
    for (const v of ["yes", "no", NOT_STATED])
      if (!counts.some((c) => c.value === v))
        counts.push({ value: v, count: 0 })
    entries.push({ facet, label: cf.question, kind: "values", values: counts })
  }
  return entries
}

function why(j: MockJob, a: AssessmentOut | undefined): WhyOut {
  const rules: WhyOut["rules"] = []
  const score = j.best_score ?? 0
  const campaign =
    CAMPAIGNS.find((c) => c.id === a?.campaign_id) ?? CAMPAIGNS[0]
  let decision = "Waiting for you"
  if (j.conflict_state === "held") {
    decision = "Held"
    rules.push({
      rule: "One role per employer",
      effective_value: "Same department",
      source: "Settings default",
      version: "settings v12",
      outcome: "fail",
      reason:
        j.conflict_note ??
        "Outranked by a higher-scoring role at this employer",
      would_change_if:
        "The winning role closes, you skip it, or you release this one with a reason",
    })
  }
  rules.push({
    rule: "Shortlist threshold",
    effective_value: "75",
    source: `Campaign: ${campaign.name}`,
    version: "rubric v3",
    outcome: score >= 75 ? "pass" : "fail",
    reason:
      score >= 75 ? `Score ${score} meets 75` : `Score ${score} is below 75`,
    would_change_if:
      score >= 75 ? null : `The score rises by ${75 - score} or more`,
  })
  rules.push({
    rule: "Auto-apply threshold",
    effective_value: "90",
    source: "Settings default",
    version: "settings v12",
    outcome: score >= 90 ? "pass" : "fail",
    reason:
      score >= 90 ? `Score ${score} meets 90` : `Score ${score} is below 90`,
    would_change_if:
      score >= 90 ? null : "Lower the auto-apply threshold, or apply yourself",
  })
  if (j.pay.state !== "stated")
    rules.push({
      rule: "Unknown pay",
      effective_value: "Pass, blocks auto-apply",
      source: `Campaign: ${campaign.name}, unknown-data policy`,
      version: null,
      outcome: "unknown",
      reason:
        j.pay.state === "estimated"
          ? "Pay is only estimated, so automation waits for you"
          : "Pay is not stated, so automation waits for you",
      would_change_if: "The employer states the pay band",
    })
  rules.push({
    rule: "Quiet hours",
    effective_value: "21:00 to 07:00",
    source: "Settings default",
    version: null,
    outcome: "info",
    reason: "Sends wait until morning",
    would_change_if: null,
  })
  if (j.triage === "skipped") decision = "Skipped by you"
  else if (j.triage === "archived") decision = "Archived"
  else if (j.conflict_state !== "held" && score < 75)
    decision = "Below threshold"
  else if (j.conflict_state !== "held") decision = "Shortlisted, not applied"
  return {
    decision,
    rules,
    conditions: [
      {
        matched: j.facets.relocation_required?.value !== "yes",
        kind: "values",
        facet: "facets.relocation_required",
        actual: j.facets.relocation_required?.value ?? NOT_STATED,
        detail:
          "Campaign rule: exclude roles that need relocation outside southern Africa",
        children: [],
      },
    ],
  }
}

function applyTagRules(j: MockJob) {
  for (const r of state.tagRules)
    if (
      r.enabled !== false &&
      matches(j, r.conditions as ConditionSet) &&
      !j.tags.includes(r.tag)
    )
      j.tags = [...j.tags, r.tag]
}

const findJob = (id: string) => state.jobs.find((j) => j.id === id)

const counted = (v: SavedViewOut): SavedViewOut => {
  const set = v.body.conditions as ConditionSet | undefined
  return {
    ...v,
    count: visible(set).filter(
      (j) => j.triage !== "archived" && j.triage !== "skipped"
    ).length,
  }
}

// ---- handlers ----------------------------------------------------------------------------------

export const matchesHandlers = [
  http.get("*/api/jobs/facets", async () => {
    if (!signedIn()) return unauthorized()
    await latency()
    return HttpResponse.json(catalog())
  }),

  http.get("*/api/jobs", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    await latency()
    const url = new URL(request.url)
    const p = url.searchParams
    let set = parseSet(p.get("conditions"))
    const viewId = p.get("view_id")
    if (viewId) {
      const v = state.views.find((x) => x.id === viewId)
      if (v) set = v.body.conditions as ConditionSet
    }
    const triage = p.get("triage")
    let list = visible(set, p.get("q"))
    if (triage) list = list.filter((j) => j.triage === triage)
    list = sortJobs(list, p.get("sort"))
    const limit = Math.min(200, Number(p.get("limit") ?? 50))
    const start = Number(p.get("cursor") ?? 0)
    const page = list.slice(start, start + limit)
    const groupBy = p.get("group_by")
    return HttpResponse.json({
      items: page.map(summary),
      total: list.length,
      next_cursor: start + limit < list.length ? String(start + limit) : null,
      groups: groupBy ? groupCounts(list, groupBy) : null,
    })
  }),

  http.get("*/api/jobs/compare/:ids", () =>
    HttpResponse.json({ detail: "Compare arrives in wave 3." }, { status: 501 })
  ),

  http.get("*/api/jobs/:id", async ({ params }) => {
    if (!signedIn()) return unauthorized()
    await latency()
    const j = findJob(String(params.id))
    return j ? HttpResponse.json(detail(j)) : notFound("Job")
  }),

  http.patch("*/api/jobs/:id", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    await latency()
    const j = findJob(String(params.id))
    if (!j) return notFound("Job")
    const body = (await request.json()) as JobPatch
    if (body.triage) j.triage = body.triage
    if (body.pinned !== undefined && body.pinned !== null)
      j.pinned = body.pinned
    if (body.snoozed_until !== undefined) j.snoozed_until = body.snoozed_until
    if (body.notes !== undefined) j.notes = body.notes
    if (body.tags) j.tags = body.tags
    j.updated_at = now()
    return HttpResponse.json(detail(j))
  }),

  http.get("*/api/jobs/:id/why", async ({ params }) => {
    if (!signedIn()) return unauthorized()
    await latency()
    const j = findJob(String(params.id))
    if (!j) return notFound("Job")
    return HttpResponse.json(why(j, state.assessments.get(j.id)?.[0]))
  }),

  http.post("*/api/jobs/:id/applied-myself", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = findJob(String(params.id))
    if (!j) return notFound("Job")
    const body = (await request.json()) as AppliedMyselfIn
    if (!body.applied_on || !body.channel)
      return HttpResponse.json(
        { detail: "Say when and how you applied." },
        { status: 422 }
      )
    j.triage = "archived"
    j.application_id = crypto.randomUUID()
    return HttpResponse.json({ ok: true })
  }),

  http.post("*/api/jobs/:id/release", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const j = findJob(String(params.id))
    if (!j) return notFound("Job")
    const { reason } = (await request.json()) as { reason: string }
    if (!reason?.trim())
      return HttpResponse.json(
        { detail: "Give a reason for the record." },
        { status: 422 }
      )
    j.conflict_state = "released"
    j.conflict_note = `Released by you: ${reason.trim()}`
    return HttpResponse.json(detail(j))
  }),

  http.post("*/api/jobs/:id/recheck", async ({ params }) => {
    if (!signedIn()) return unauthorized()
    const j = findJob(String(params.id))
    if (!j) return notFound("Job")
    j.last_checked_at = now()
    const result: RecheckResult = {
      job: detail(j),
      availability_before: j.availability,
      availability_after: j.availability,
      content_changed: false,
      changed_fields: [],
      reassessed: false,
      note: null,
    }
    return HttpResponse.json(result)
  }),

  // ---- assessments, rubric, facts ----
  http.get("*/api/assessments", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const jobId = new URL(request.url).searchParams.get("job_id")
    const items = jobId ? (state.assessments.get(jobId) ?? []) : []
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.post("*/api/assessments/rescore", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const body = (await request.json()) as {
      job_ids: string[]
      campaign_id: string
    }
    if (!body.job_ids?.length)
      return HttpResponse.json(
        { detail: "Choose at least one job." },
        { status: 422 }
      )
    return HttpResponse.json({ run_id: crypto.randomUUID() }, { status: 202 })
  }),

  // ---- saved views ----
  http.get("*/api/views", async () => {
    if (!signedIn()) return unauthorized()
    await latency()
    const items = [...state.views].sort(
      (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)
    )
    return HttpResponse.json({
      items: items.map(counted),
      total: items.length,
      next_cursor: null,
    })
  }),
  http.post("*/api/views", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const body = (await request.json()) as SavedViewIn
    if (!body.name?.trim())
      return HttpResponse.json(
        { detail: "Give the view a name." },
        { status: 422 }
      )
    const v = {
      id: crypto.randomUUID(),
      created_at: now(),
      updated_at: now(),
      name: body.name.trim(),
      body: body.body,
      pinned: body.pinned ?? false,
      sort_order: body.sort_order ?? state.views.length + 1,
      count: null,
    } as SavedViewOut
    state.views.push(v)
    return HttpResponse.json(counted(v), { status: 201 })
  }),
  http.put("*/api/views/:id", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const idx = state.views.findIndex((v) => v.id === String(params.id))
    if (idx < 0) return notFound("View")
    const body = (await request.json()) as SavedViewIn
    if (!body.name?.trim())
      return HttpResponse.json(
        { detail: "Give the view a name." },
        { status: 422 }
      )
    const v = {
      ...state.views[idx],
      name: body.name.trim(),
      body: body.body,
      pinned: body.pinned ?? false,
      sort_order: body.sort_order ?? state.views[idx].sort_order,
      updated_at: now(),
    } as SavedViewOut
    state.views[idx] = v
    return HttpResponse.json(counted(v))
  }),
  http.delete("*/api/views/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    state.views = state.views.filter((v) => v.id !== String(params.id))
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- tag rules ----
  http.get("*/api/tag-rules", () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json({
      items: state.tagRules,
      total: state.tagRules.length,
      next_cursor: null,
    })
  }),
  http.post("*/api/tag-rules", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const body = (await request.json()) as TagRuleIn
    if (!body.tag?.trim())
      return HttpResponse.json({ detail: "Name the tag." }, { status: 422 })
    const r = {
      id: crypto.randomUUID(),
      created_at: now(),
      updated_at: now(),
      tag: body.tag.trim(),
      conditions: body.conditions,
      enabled: body.enabled ?? true,
    } as TagRuleOut
    state.tagRules.push(r)
    state.jobs.forEach(applyTagRules)
    return HttpResponse.json(r, { status: 201 })
  }),
  http.delete("*/api/tag-rules/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    state.tagRules = state.tagRules.filter((r) => r.id !== String(params.id))
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- custom facets ----
  http.get("*/api/custom-facets", () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json({
      items: state.customFacets,
      total: state.customFacets.length,
      next_cursor: null,
    })
  }),
  http.post("*/api/custom-facets", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const body = (await request.json()) as CustomFacetIn
    if (!body.question?.trim() || !body.key?.trim())
      return HttpResponse.json(
        { detail: "Write the question." },
        { status: 422 }
      )
    if (state.customFacets.some((c) => c.key === body.key))
      return HttpResponse.json(
        { detail: "A question with that key exists." },
        { status: 409 }
      )
    const cf: CustomFacetOut = {
      id: crypto.randomUUID(),
      created_at: now(),
      updated_at: now(),
      key: body.key,
      question: body.question.trim(),
      enabled: body.enabled ?? true,
    }
    state.customFacets.push(cf)
    return HttpResponse.json(cf, { status: 201 })
  }),
  http.delete("*/api/custom-facets/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    state.customFacets = state.customFacets.filter(
      (c) => c.id !== String(params.id)
    )
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/custom-facets/:id/backfill", ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const cf = state.customFacets.find((c) => c.id === String(params.id))
    if (!cf) return notFound("Custom facet")
    const confirm = new URL(request.url).searchParams.get("confirm") === "true"
    const jobs = state.jobs.filter((j) => !(cf.key in j.custom_facets))
    if (confirm)
      for (const j of jobs)
        j.custom_facets = {
          ...j.custom_facets,
          [cf.key]: { value: NOT_STATED, evidence: null, model: "mock-small" },
        }
    return HttpResponse.json(
      {
        jobs: jobs.length,
        estimated_cost_minor: jobs.length * 1,
        currency: "USD",
      },
      { status: 202 }
    )
  }),
]
