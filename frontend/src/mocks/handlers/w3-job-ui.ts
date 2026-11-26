/**
 * MSW handlers for the wave 3 job-page endpoints, typed from the generated contract:
 * interview pack (`routers/interview.py`), compare (`GET /api/jobs/compare/{ids}`) and posting
 * changes (`routers/job_changes.py`). Errors are `{detail: {code, reason}}` like the server's.
 */
import { http, HttpResponse } from "msw"
import type { components } from "@/lib/api/types"
import type {
  PracticeFeedback,
  SectionContent,
  SectionKey,
  Stories,
} from "@/features/jobs/interview/shapes"
import { db } from "../db"
import { applicationsMock } from "./applications"
import { matchesMock } from "./matches"
import {
  buildSection,
  makeVersion,
  mirror,
  MOCK_SECTIONS,
  MODEL_SECTIONS,
  newPackRecord,
  SECTION_ESTIMATE_MICROS,
  seedChanges,
  type PackRecord,
} from "../dataset/w3-job-ui"

type S = components["schemas"]

let packs = new Map<string, PackRecord>()
let practice = new Map<string, S["PracticeOut"][]>()
let seeded = false
let changes = seedChanges()

/** Test switches: run out of AI budget (generation pauses after STEP sections, practice pauses). */
export const w3JobUiMock = {
  budgetExhausted: false,
  /** Another tab or device saves a new `stories` version (for the version-conflict prompt). */
  editStoriesElsewhere(jobId: string) {
    const rec = packs.get(jobId)
    const list = rec?.versions.stories
    if (!rec || !list?.length) return
    const content = structuredClone(
      list[list.length - 1].content
    ) as unknown as Stories
    content.items[0].title = `${content.items[0].title} (edited elsewhere)`
    list.push(
      makeVersion("stories", list.length + 1, content, { origin: "owner" })
    )
    mirror(rec)
  },
  /** The server's auto-offer: a pack row with `offered_at` and nothing generated. */
  offer(jobId: string) {
    const a = applicationsMock().apps.find((x) => x.job_id === jobId)
    if (!a) return
    const rec = newPackRecord(jobId, a.id, a.title, a.employer, {
      ready: false,
      untraced: false,
    })
    rec.pack.offered_at = new Date(Date.now() - 3_600_000).toISOString()
    packs.set(jobId, rec)
  },
}

export function resetW3JobUiMock() {
  packs = new Map()
  practice = new Map()
  seeded = false
  changes = seedChanges()
  w3JobUiMock.budgetExhausted = false
}

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const refuse = (status: number, code: string, reason: string) =>
  HttpResponse.json({ detail: { code, reason } }, { status })
const notFound = (what: string) => refuse(404, "not_found", `${what} not found`)
const signedIn = () => db.get().session
const STEP = 3
const OPEN = new Set(["queued", "running"])
const isSection = (k: unknown): k is SectionKey =>
  MOCK_SECTIONS.includes(k as SectionKey)

/** The first application at the interview stage starts with a finished pack (one flagged claim). */
function seedPacks() {
  if (seeded) return
  seeded = true
  const a = applicationsMock().apps.find((x) => x.stage === "interview")
  if (a && !packs.has(a.job_id))
    packs.set(
      a.job_id,
      newPackRecord(a.job_id, a.id, a.title, a.employer, {
        ready: true,
        untraced: true,
      })
    )
}

function recordFor(jobId: string): PackRecord | null {
  const existing = packs.get(jobId)
  if (existing) return existing
  const app = applicationsMock().apps.find((x) => x.job_id === jobId)
  const job = matchesMock.get().jobs.find((j) => j.id === jobId)
  if (!app && !job) return null
  const rec = newPackRecord(
    jobId,
    app?.id ?? null,
    app?.title ?? job!.title,
    app?.employer ?? job!.employer,
    { ready: false, untraced: false }
  )
  packs.set(jobId, rec)
  return rec
}

/** Each look at an open pack moves it on: queued -> running -> a few sections per look. */
function advance(rec: PackRecord) {
  const p = rec.pack
  if (p.status === "queued") {
    p.status = "running"
    return
  }
  if (p.status !== "running") return
  const pending = [...(p.pending_sections ?? [])]
  const take = pending.splice(0, STEP)
  for (const k of take) if (isSection(k)) buildSection(rec, k)
  p.cost_micros =
    (p.cost_micros ?? 0) +
    take.filter((k) => MODEL_SECTIONS.includes(k as SectionKey)).length *
      SECTION_ESTIMATE_MICROS
  p.pending_sections = pending
  if (pending.length === 0) {
    p.status = "done"
    p.generated_at = new Date().toISOString()
  } else if (w3JobUiMock.budgetExhausted) p.status = "paused"
}

function request(rec: PackRecord, wanted?: string[] | null) {
  const p = rec.pack
  const list = wanted?.length ? [...wanted] : [...MOCK_SECTIONS]
  if (!list.includes("crib_sheet")) list.push("crib_sheet")
  p.generation = (p.generation ?? 0) + 1
  p.pending_sections = MOCK_SECTIONS.filter((k) => list.includes(k))
  p.status = "queued"
  p.error = null
  p.estimate_micros =
    p.pending_sections.filter((k) => MODEL_SECTIONS.includes(k as SectionKey))
      .length * SECTION_ESTIMATE_MICROS
}

/** The server checks owner edits; here a claim with a figure and no fact is flagged. */
function hasUntracedFigure(content: unknown): boolean {
  if (Array.isArray(content)) return content.some(hasUntracedFigure)
  if (content && typeof content === "object") {
    const o = content as Record<string, unknown>
    if (typeof o.text === "string" && Array.isArray(o.fact_ids))
      return o.fact_ids.length === 0 && /\d/.test(o.text)
    return Object.values(o).some(hasUntracedFigure)
  }
  return false
}

function ownerVersion(rec: PackRecord, key: SectionKey, content: unknown) {
  const list = (rec.versions[key] ??= [])
  const v = makeVersion(
    key,
    list.length + 1,
    content as SectionContent[SectionKey],
    {
      origin: "owner",
      flagged: hasUntracedFigure(content),
    }
  )
  list.push(v)
  mirror(rec)
  return v
}

/** The section's shape, loosely: an owner edit must keep its lists and claim wording within bounds. */
function validSection(key: SectionKey, content: unknown): boolean {
  if (!content || typeof content !== "object") return false
  const listKey: Partial<Record<SectionKey, string>> = {
    why_you: "points",
    questions: "items",
    stories: "items",
    questions_to_ask: "items",
    gaps: "items",
    pay_sheet: "lines",
  }
  const lk = listKey[key]
  if (lk && !Array.isArray((content as Record<string, unknown>)[lk]))
    return false
  const tooLong = (x: unknown): boolean =>
    typeof x === "string"
      ? x.length > 2000
      : Array.isArray(x)
        ? x.some(tooLong)
        : !!x && typeof x === "object" && Object.values(x).some(tooLong)
  return !tooLong(content)
}

function feedbackFor(question: string, draft: string): PracticeFeedback {
  return {
    feedback: `Clear and specific. Anchor it in your facts when you answer "${question}", and give the outcome last.`,
    strengths: ["Specific"],
    improve: draft.length < 60 ? ["Answer is short: add the result"] : [],
    suggested_answer: {
      text: "I led six analysts for four years and set one shared backlog.",
      fact_ids: ["F-101"],
    },
  }
}

const base = "*/api/jobs/:jobId/interview-pack"
const pack = (params: Record<string, unknown>) => {
  seedPacks()
  return packs.get(String(params.jobId)) ?? null
}

export const w3JobUiHandlers = [
  http.get(`${base}/estimate`, ({ request: req }) => {
    if (!signedIn()) return unauthorized()
    const asked = new URL(req.url).searchParams.getAll("sections")
    const wanted = MODEL_SECTIONS.filter(
      (k) => !asked.length || asked.includes(k)
    )
    const sections = Object.fromEntries(
      wanted.map((k) => [k, SECTION_ESTIMATE_MICROS])
    )
    const out: S["InterviewEstimateOut"] = {
      sections,
      total_micros: wanted.length * SECTION_ESTIMATE_MICROS,
      currency: "USD",
    }
    return HttpResponse.json(out)
  }),
  http.get(`${base}/export`, ({ params, request: req }) => {
    const rec = pack(params)
    if (!rec) return notFound("interview pack")
    if (!Object.keys(rec.pack.sections).length)
      return refuse(409, "empty", "nothing generated yet")
    const fmt = new URL(req.url).searchParams.get("fmt") ?? "pdf"
    return new HttpResponse("Interview pack (mock export)", {
      headers: {
        "content-type": "text/plain",
        "content-disposition": `attachment; filename="interview-pack-${rec.pack.job_id}.${fmt}"`,
        "x-flagged-sections": (rec.pack.flagged ?? []).join(","),
      },
    })
  }),
  http.get(`${base}/practice`, ({ params }) => {
    const rec = pack(params)
    if (!rec) return notFound("interview pack")
    return HttpResponse.json(practice.get(rec.pack.id) ?? [])
  }),
  http.post(`${base}/practice`, async ({ params, request: req }) => {
    if (!signedIn()) return unauthorized()
    seedPacks()
    const rec = recordFor(String(params.jobId))
    if (!rec) return notFound("job")
    const body = (await req.json()) as S["PracticeIn"]
    const paused = w3JobUiMock.budgetExhausted
    const at = new Date().toISOString()
    const row: S["PracticeOut"] = {
      id: `pr-${crypto.randomUUID()}`,
      created_at: at,
      updated_at: at,
      pack_id: rec.pack.id,
      question: body.question,
      category: body.category ?? null,
      draft_answer: body.draft_answer,
      status: paused ? "paused" : "done",
      feedback: paused ? null : feedbackFor(body.question, body.draft_answer),
      check_results: [],
      model: paused ? null : "mock-model",
      cost_micros: paused ? 0 : 4_000,
      error: paused ? "AI budget used up" : null,
    }
    practice.set(rec.pack.id, [row, ...(practice.get(rec.pack.id) ?? [])])
    return HttpResponse.json(row, { status: 201 })
  }),
  http.put(
    `${base}/sections/:section/note`,
    async ({ params, request: req }) => {
      const rec = pack(params)
      if (!rec) return notFound("interview pack")
      if (!isSection(params.section))
        return refuse(
          404,
          "unknown_section",
          `unknown section '${String(params.section)}'`
        )
      const { note } = (await req.json()) as S["InterviewNoteIn"]
      const notes = { ...(rec.pack.notes ?? {}) }
      if (note?.trim()) notes[params.section] = note
      else delete notes[params.section]
      rec.pack.notes = notes
      return HttpResponse.json(rec.pack)
    }
  ),
  http.get(`${base}/sections/:section/versions`, ({ params }) => {
    const rec = pack(params)
    if (!rec) return notFound("interview pack")
    const list = isSection(params.section)
      ? (rec.versions[params.section] ?? [])
      : []
    return HttpResponse.json(list)
  }),
  http.post(`${base}/sections/:section/regenerate`, ({ params }) => {
    const rec = pack(params)
    if (!rec) return notFound("interview pack")
    if (!isSection(params.section))
      return refuse(
        422,
        "unknown_section",
        `not a section of this pack: ${String(params.section)}`
      )
    if (OPEN.has(rec.pack.status ?? ""))
      return refuse(409, "still_queued", "the pack is already being generated")
    request(rec, [params.section])
    return HttpResponse.json(rec.pack, { status: 202 })
  }),
  http.put(`${base}/sections/:section`, async ({ params, request: req }) => {
    const rec = pack(params)
    if (!rec) return notFound("interview pack")
    if (OPEN.has(rec.pack.status ?? ""))
      return refuse(
        409,
        "still_queued",
        "the pack is being generated; edit it when it is done"
      )
    if (!isSection(params.section))
      return refuse(
        404,
        "unknown_section",
        `unknown section '${String(params.section)}'`
      )
    const { content } = (await req.json()) as S["InterviewSectionIn"]
    if (!validSection(params.section, content))
      return refuse(
        422,
        "invalid_section",
        `not a valid ${params.section} section`
      )
    return HttpResponse.json(ownerVersion(rec, params.section, content))
  }),
  http.put(
    `${base}/stories/:storyId/favourite`,
    async ({ params, request: req }) => {
      const rec = pack(params)
      const list = rec?.versions.stories
      if (!rec || !list?.length) return notFound("story bank")
      const { favourite } = (await req.json()) as S["FavouriteIn"]
      const content = structuredClone(
        list[list.length - 1].content
      ) as unknown as Stories
      const story = content.items.find((s) => s.id === params.storyId)
      if (!story) return notFound("story")
      story.favourite = favourite ?? true
      return HttpResponse.json(ownerVersion(rec, "stories", content))
    }
  ),
  http.put(`${base}/stories/:storyId`, async ({ params, request: req }) => {
    const rec = pack(params)
    const list = rec?.versions.stories
    if (!rec || !list?.length) return notFound("story bank")
    const body = (await req.json()) as S["StoryEditIn"]
    const current = list[list.length - 1]
    if (body.base_version != null && body.base_version !== current.version)
      return refuse(
        409,
        "version_conflict",
        `the stories changed since version ${body.base_version} (now ${current.version})`
      )
    const content = structuredClone(current.content) as unknown as Stories
    const story = content.items.find((s) => s.id === params.storyId)
    if (!story) return notFound("story")
    for (const k of [
      "title",
      "requirement",
      "situation",
      "task",
      "action",
      "result",
    ] as const)
      if (body[k] != null) story[k] = body[k]
    return HttpResponse.json(ownerVersion(rec, "stories", content))
  }),
  http.get(base, ({ params }) => {
    if (!signedIn()) return unauthorized()
    const rec = pack(params)
    if (!rec) return notFound("interview pack")
    advance(rec)
    return HttpResponse.json(rec.pack)
  }),
  http.post(base, async ({ params, request: req }) => {
    if (!signedIn()) return unauthorized()
    seedPacks()
    const rec = recordFor(String(params.jobId))
    if (!rec) return notFound("job")
    const text = await req.text()
    const body = (text ? JSON.parse(text) : null) as
      S["InterviewGenerateIn"] | null
    if (!OPEN.has(rec.pack.status ?? "")) {
      if (rec.pack.status === "paused") w3JobUiMock.budgetExhausted = false
      request(rec, body?.sections)
    }
    return HttpResponse.json(rec.pack, { status: 202 })
  }),
  http.post("*/api/interview-practice/:id/retry", ({ params }) => {
    for (const rows of practice.values()) {
      const row = rows.find((r) => r.id === params.id)
      if (!row) continue
      if (row.status !== "done" && !w3JobUiMock.budgetExhausted) {
        row.status = "done"
        row.feedback = feedbackFor(row.question, row.draft_answer)
        row.error = null
        row.cost_micros = 4_000
        row.updated_at = new Date().toISOString()
      }
      return HttpResponse.json(row)
    }
    return notFound("practice answer")
  }),

  // ---- compare (CONTRACTS, wave 3 browser-changes: CompareOut) ----
  http.get("*/api/jobs/compare/:ids", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const ids = String(params.ids)
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
    if (ids.length < 2 || ids.length > 4 || new Set(ids).size !== ids.length)
      return HttpResponse.json(
        { detail: "compare 2 to 4 different roles" },
        { status: 422 }
      )
    const st = matchesMock.get()
    const jobs = ids.map((id) => st.jobs.find((x) => x.id === id))
    const missing = ids.filter((_, i) => !jobs[i])
    if (missing.length)
      return HttpResponse.json(
        { detail: `no such role: ${missing.join(", ")}` },
        { status: 404 }
      )
    return HttpResponse.json(
      compareOut(jobs as NonNullable<(typeof jobs)[number]>[])
    )
  }),

  // ---- posting changes ----
  http.get("*/api/jobs/:id/changes", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const id = String(params.id)
    const job = matchesMock.get().jobs.find((j) => j.id === id)
    const c: S["JobChangesOut"] = changes[id] ?? {
      job_id: id,
      watch: null,
      changes: [],
    }
    return HttpResponse.json({
      ...c,
      changes: c.changes.map((x) => ({
        ...x,
        job_title: job?.title ?? x.job_title,
        employer: job?.employer ?? x.employer,
      })),
    })
  }),
  http.post("*/api/job-changes/:id/acknowledge", ({ params }) => {
    if (!signedIn()) return unauthorized()
    for (const c of Object.values(changes)) {
      const row = c.changes.find((x) => x.id === params.id)
      if (!row) continue
      row.acknowledged_at ??= new Date().toISOString()
      row.acknowledged_by ??= "owner"
      return HttpResponse.json(row)
    }
    return HttpResponse.json({ detail: "change not found" }, { status: 404 })
  }),
]

// ---- compare builder (mirrors app/pipeline/compare.py on the mock jobs) ----------------------

type MockJob = ReturnType<typeof matchesMock.get>["jobs"][number]
/** Cells and rows as built; `full` fills the contract's defaults. */
type Cell = Pick<S["CompareCell"], "state"> & Partial<S["CompareCell"]>
type Row = Omit<S["CompareRow"], "cells" | "note" | "best_index"> & {
  cells: Cell[]
  note?: string | null
  best_index?: number | null
}
const full = (r: Row): S["CompareRow"] => ({
  ...r,
  note: r.note ?? null,
  best_index: r.best_index ?? null,
  cells: r.cells.map((c) => ({
    value: null,
    note: null,
    amount_minor: null,
    currency: null,
    ...c,
  })),
})
const FACETS = [
  "work_model",
  "visa_sponsorship",
  "relocation_required",
  "relocation_assistance",
  "needs_account",
]
const ANNUALISE: Record<string, number> = { year: 1, month: 12, week: 52 }
const label = (k: string) =>
  k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " ")
const money = (minor: number, cur: string) =>
  `${(minor / 100).toLocaleString("en", { maximumFractionDigits: 0 })} ${cur}`

function facetCell(j: MockJob, name: string): Cell {
  const f = (j.facets as unknown as Record<string, { value?: unknown } | null>)[
    name
  ]
  const v = f?.value
  if (v == null || v === "not_stated")
    return { value: null, state: "not_stated" }
  const text = typeof v === "string" ? v.replace(/_/g, " ") : JSON.stringify(v)
  return { value: text, state: v === "yes" || v === "no" ? v : "stated" }
}

function payCell(j: MockJob): Cell {
  const p = j.pay
  if (p.state === "not_stated" || (p.min_minor == null && p.max_minor == null))
    return {
      value: null,
      state: "not_stated",
      note: "the posting does not state pay",
    }
  const low = (p.min_minor ?? p.max_minor)!
  const high = p.max_minor ?? low
  const cur = p.currency ?? "?"
  const period = p.period ?? "year"
  const shown =
    low === high ? money(low, cur) : `${money(low, cur)} to ${money(high, cur)}`
  const state = p.state === "estimated" ? "estimated" : "stated"
  const factor = ANNUALISE[period]
  if (!factor || !p.currency)
    return {
      value: `${shown} per ${period}`,
      state,
      currency: p.currency,
      note: `not normalised (${p.currency ? `per ${period}: hours per year are not known` : "no currency stated"})`,
    }
  return {
    value: `${shown} per ${period}`,
    state,
    amount_minor: Math.floor((low + high) / 2) * factor,
    currency: p.currency,
    note: state === "estimated" ? "estimate, not stated in the posting" : null,
  }
}

function compareOut(jobs: MockJob[]): S["CompareOut"] {
  const st = matchesMock.get()
  const rows: Row[] = FACETS.map((k) => ({
    key: `facet:${k}`,
    label: label(k),
    group: "facets",
    cells: jobs.map((j) => facetCell(j, k)),
    comparable: true,
  }))
  const pay = jobs.map(payCell)
  const missing = jobs
    .filter((_, i) => pay[i].state === "not_stated")
    .map((j) => j.title)
  const unconverted = jobs
    .filter(
      (_, i) => pay[i].state !== "not_stated" && pay[i].amount_minor == null
    )
    .map((j) => j.title)
  const currencies = new Set(
    pay.filter((c) => c.amount_minor != null).map((c) => c.currency)
  )
  const payNote = missing.length
    ? `pay is not stated for ${missing.join(", ")}: the roles cannot be ranked on pay`
    : unconverted.length
      ? `pay for ${unconverted.join(", ")} is hourly, daily or has no currency: not normalised`
      : currencies.size > 1
        ? `different currencies (${[...currencies].sort().join(", ")}); no exchange rate is applied`
        : null
  let best: number | null = null
  if (!payNote) {
    const amounts = pay.map((c) => c.amount_minor ?? 0)
    const top = Math.max(...amounts)
    best =
      amounts.filter((a) => a === top).length === 1
        ? amounts.indexOf(top)
        : null
  }
  rows.push({
    key: "pay",
    label: "Pay (per year)",
    group: "pay",
    cells: pay,
    comparable: !payNote,
    note: payNote,
    best_index: best,
  })

  const assessments = jobs.map((j) => st.assessments.get(j.id)?.[0] ?? null)
  const scores: Cell[] = assessments.map((a) =>
    a?.score == null
      ? {
          value: null,
          state: "unknown",
          note: a ? `assessment is ${a.state}` : "not assessed by any campaign",
        }
      : { value: a.score, state: "stated" }
  )
  const scored = scores.every((c) => c.value != null)
  const top = scored ? Math.max(...scores.map((c) => Number(c.value))) : null
  const winners = scores.filter((c) => c.value === top).length
  rows.push({
    key: "score",
    label: "Score",
    group: "score",
    cells: scores,
    comparable: scored,
    note: scored ? null : "not every role has a score",
    best_index:
      scored && winners === 1 ? scores.findIndex((c) => c.value === top) : null,
  })
  const gateNames = [
    ...new Set(
      assessments.flatMap((a) => a?.filter_results.map((f) => f.name) ?? [])
    ),
  ]
  for (const name of gateNames)
    rows.push({
      key: `gate:${name}`,
      label: name,
      group: "gates",
      comparable: true,
      cells: assessments.map((a) => {
        const r = a?.filter_results.find((f) => f.name === name)
        return r
          ? { value: r.reason ?? null, state: r.result }
          : { value: null, state: "unknown", note: "not evaluated" }
      }),
    })
  rows.push({
    key: "employer_group",
    label: "Employer group",
    group: "employer",
    comparable: false,
    note: "one role per employer is applied to (7.1)",
    cells: jobs.map((j) => ({
      value: j.canonical_employer,
      state: "stated",
      note: j.conflict_note
        ? `${j.conflict_state}: ${j.conflict_note}`
        : j.conflict_state,
    })),
  })
  rows.push({
    key: "deadline",
    label: "Deadline",
    group: "timing",
    comparable: true,
    cells: jobs.map((j) =>
      j.deadline.state === "dated" && j.deadline.on
        ? { value: j.deadline.on, state: "stated" }
        : j.deadline.state === "open_until_filled"
          ? { value: "open until filled", state: "stated" }
          : { value: null, state: "not_stated" }
    ),
  })
  rows.push({
    key: "apply_method",
    label: "How to apply",
    group: "apply",
    comparable: true,
    cells: jobs.map((j) =>
      j.apply_method === "unknown"
        ? { value: null, state: "not_stated" }
        : { value: j.apply_method, state: "stated" }
    ),
  })
  const sameEmployer = new Set(jobs.map((j) => j.canonical_employer)).size === 1
  const won = jobs.filter((j) => j.conflict_state === "winner")
  const winner = sameEmployer && won.length === 1 ? won[0] : null
  return {
    job_ids: jobs.map((j) => j.id),
    jobs: jobs.map((j, i) => ({
      id: j.id,
      title: j.title,
      employer: j.employer,
      location:
        [j.location.city, j.location.country].filter(Boolean).join(", ") ||
        j.location.raw ||
        null,
      availability: j.availability,
      campaign_id: assessments[i]?.campaign_id ?? null,
      campaign_name: null,
      score: assessments[i]?.score ?? null,
      assessment_state: assessments[i]?.state ?? null,
    })),
    rows: rows.map(full),
    winner_id: winner?.id ?? null,
    winner_reason: winner
      ? (winner.conflict_note ?? "chosen by the employer group's rules")
      : null,
  }
}
