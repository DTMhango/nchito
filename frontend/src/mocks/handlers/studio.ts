/**
 * Mock backend for the Studio: spec state, owner versions, checks, tailoring requests,
 * rendering, documents, packet builds and mail threads. The application itself stays in the
 * applications mock; this store adds the spec for the applications it knows, and falls
 * through (returns undefined) otherwise. Handler order: see `../handlers.ts`.
 */
import { http, HttpResponse } from "msw"
import type { Schemas } from "@/lib/api/types"
import { db } from "../db"
import {
  BUDGET_ERROR,
  draftedAnswers,
  draftedSpec,
  newTailorRun,
  seedStudio,
  type MockStudio,
  type StudioEntry,
} from "../dataset/studio"
import { appliedJobId, applicationIdFor } from "../dataset/jobs"
import { toDetail } from "../dataset/applications"
import { applicationsMock } from "./applications"
import { kitStore, kitWaivers } from "./kit"
import { matchesMock } from "./matches"

type Spec = Schemas["ApplicationSpec-Output"]
type CheckResult = Schemas["CheckResult"]
type SpecStateOut = Schemas["SpecStateOut"]
type RenderIn = Schemas["RenderIn"]
type RenderWarning = Schemas["RenderWarning"]
type DocumentOut = Schemas["DocumentOut"]
type PacketBuildIn = Schemas["PacketBuildIn"]
type PacketOut = Schemas["PacketOut"]
type Row = Record<string, unknown> & { id: string }

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })

/** The posting requirements of an application's role. */
function reqsFor(app: string) {
  const n = Number(app.slice(-12))
  const jobId = applicationIdFor(n) === app ? appliedJobId(n) : null
  return matchesMock.get().jobs.find((j) => j.id === jobId)?.requirements ?? []
}

const textsOf = (spec: Spec) => {
  const items = [
    spec.headline,
    spec.summary,
    ...(spec.competencies ?? []),
    ...(spec.experience ?? []).flatMap((e) => e.bullets ?? []),
  ].filter((x): x is NonNullable<typeof x> => !!x)
  const cv = [
    ...items.map((x) => x.text),
    ...(spec.skills ?? []),
    ...(spec.experience ?? []).map((e) => e.title ?? ""),
  ].join("\n")
  const letter = (spec.letter ?? []).map((x) => x.text).join("\n")
  return { items: [...items, ...(spec.letter ?? [])], cv, letter }
}

/** A small stand-in for the code checker: fact tracing and the code-enforced guardrails. */
function check(app: string, spec: Spec): CheckResult[] {
  const { items, cv, letter } = textsOf(spec)
  const facts = kitStore().facts as Row[]
  const known = new Set(facts.flatMap((f) => [f.id, String(f.code)]))
  const untraced = items.filter(
    (x) => x.text.trim() && !(x.fact_ids ?? []).some((id) => known.has(id))
  )
  const out: CheckResult[] = [
    untraced.length
      ? {
          check: "fact_tracing",
          status: "block",
          detail: `${untraced.length} claim${untraced.length === 1 ? " has" : "s have"} no approved fact: "${untraced[0].text}"`,
          guardrail_id: null,
          waived: false,
        }
      : {
          check: "fact_tracing",
          status: "pass",
          detail: `All ${items.length} claims trace to approved facts.`,
          guardrail_id: null,
          waived: false,
        },
  ]
  const waived = kitWaivers().filter((w) => w.application_id === app)
  for (const g of kitStore().guardrails as Row[]) {
    if (!g.enabled) continue
    const scope = g.scope as string[]
    const text = [
      scope.some((s) => s === "cv" || s === "everywhere") ? cv : "",
      scope.some((s) => s === "letter" || s === "everywhere") ? letter : "",
    ]
      .join("\n")
      .toLowerCase()
    const p = g.params as Record<string, unknown>
    let hit: string | null = null
    if (g.type === "never_mention")
      hit =
        (p.terms as string[]).find((t) => text.includes(t.toLowerCase())) ??
        null
    if (g.type === "never_together") {
      const a = (p.group_a as string[]).find((t) =>
        text.includes(t.toLowerCase())
      )
      const b = (p.group_b as string[]).find((t) =>
        text.includes(t.toLowerCase())
      )
      hit = a && b ? `"${a}" with "${b}"` : null
    }
    if (g.type === "require_wording")
      hit =
        (p.instead_of as string[]).find((t) =>
          text.includes(t.toLowerCase())
        ) ?? null
    if (g.type === "omit_field")
      hit =
        (p.fields as string[]).find((t) => text.includes(t.toLowerCase())) ??
        null
    if (
      ![
        "never_mention",
        "never_together",
        "require_wording",
        "omit_field",
        "limit",
      ].includes(String(g.type))
    )
      continue
    if (g.type === "limit") {
      const pages = Math.max(1, Math.ceil(cv.length / 2600))
      const max = Number(p.pages ?? 0)
      out.push({
        check: "limit",
        status: max && pages > max ? "warn" : "pass",
        detail: `CV renders to ${pages} page${pages === 1 ? "" : "s"}${max ? ` (limit ${max})` : ""}.`,
        guardrail_id: g.id,
        waived: false,
      })
      continue
    }
    const blocks = g.severity === "block" && g.strictness !== "advise"
    out.push({
      check: "guardrail",
      status: hit ? (blocks ? "block" : "warn") : "pass",
      detail: hit
        ? g.type === "never_together"
          ? `Mentions ${hit} in one packet.`
          : `Mentions "${hit}".`
        : null,
      guardrail_id: g.id,
      waived:
        !!hit &&
        blocks &&
        g.strictness === "block_waivable_once" &&
        waived.some((w) => w.guardrail_id === g.id),
    })
  }
  return out
}

/** A canonical print of a spec's content (what the server's content hash stands for). */
const printOf = (spec: Spec) =>
  JSON.stringify([
    spec.headline,
    spec.summary,
    spec.competencies,
    spec.experience,
    spec.skills,
    spec.letter,
  ])
/** A short stand-in for sha256: equal content, equal hash. */
function hashOf(text: string) {
  let h = 2166136261
  for (let i = 0; i < text.length; i++)
    h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return (h >>> 0).toString(16).padStart(8, "0").repeat(8)
}

let state: MockStudio = seedStudio(reqsFor, check, printOf)
export const resetStudioMock = () => {
  state = seedStudio(reqsFor, check, printOf)
}
export const studioMock = () => state

/** Tests: the server reports the last check out of date (a cited fact changed). */
export function markStale(app: string, reasons: string[]) {
  const e = state.entries[app]
  if (e) e.stale_reasons = reasons
}

const summaryOf = (id: string) =>
  applicationsMock().apps.find((a) => a.id === id)

function detail(id: string) {
  const a = summaryOf(id)
  const e = state.entries[id]
  if (!a || !e) return null
  return { ...toDetail(a), spec: e.spec, check_results: e.check_results }
}

const worst = (rs: CheckResult[]): "pass" | "warn" | "block" =>
  rs.some((r) => r.status === "block" && !r.waived)
    ? "block"
    : rs.some((r) => r.status === "warn")
      ? "warn"
      : "pass"

/** Store a new version and run the code checks on it (PUT spec, and a finished tailoring). */
function addVersion(
  app: string,
  e: StudioEntry,
  spec: Spec,
  origin: "tailor" | "owner"
) {
  e.spec = spec
  e.check_results = check(app, spec)
  e.checked_print = printOf(spec)
  e.stale_reasons = []
  e.versions.push({
    version: e.versions.length + 1,
    origin,
    content_hash: hashOf(printOf(spec)),
    created_at: new Date().toISOString(),
    created_by: origin === "owner" ? "owner" : "system",
    status: worst(e.check_results),
  })
}

/** Advance open tailoring on each poll: running on the first, drafted on the second. */
function advance(app: string, e: StudioEntry) {
  const run = state.runs.find((r) => r.id === e.run_id)
  const now = new Date().toISOString()
  if (e.tailoring === "queued") {
    e.tailoring = "running"
    if (run) Object.assign(run, { status: "running", updated_at: now })
  } else if (e.tailoring === "running") {
    e.tailoring = "done"
    addVersion(app, e, draftedSpec(reqsFor(app)), "tailor")
    e.answers = draftedAnswers()
    if (run)
      Object.assign(run, {
        status: "succeeded",
        updated_at: now,
        finished_at: now,
        cost_micros: 38_400,
        cost_minor: 4,
      })
    const a = summaryOf(app)
    if (a && a.stage === "shortlisted") a.stage = "tailoring"
  }
}

function specState(app: string, e: StudioEntry): SpecStateOut {
  const latest = e.versions[e.versions.length - 1]
  const checked =
    !!latest &&
    e.checked_print === printOf(e.spec) &&
    e.stale_reasons.length === 0
  return {
    application_id: app,
    version: latest?.version ?? null,
    origin: latest?.origin ?? null,
    content_hash: latest ? hashOf(printOf(e.spec)) : null,
    spec: e.spec,
    check_results: e.check_results,
    checked,
    status: latest && e.checked_print ? worst(e.check_results) : null,
    stale_reasons: e.stale_reasons,
    answers: e.answers,
    tailoring: e.tailoring,
    tailoring_error: e.tailoring_error,
    versions: e.versions,
  }
}

/** The renderer's warnings: the compact layout allows four bullets per role. */
function renderWarnings(spec: Spec, body: RenderIn): RenderWarning[] {
  if (body.kind !== "cv" || body.template_key !== "compact") return []
  return (spec.experience ?? [])
    .filter((x) => (x.bullets ?? []).length > 4)
    .map((x) => ({
      code: "bullets_per_role",
      message: `${x.title ?? "A role"} has ${(x.bullets ?? []).length} bullets; Compact allows 4.`,
      detail: { count: (x.bullets ?? []).length, limit: 4 },
      severity: "warn" as const,
    }))
}

const MIME: Record<DocumentOut["fmt"], string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  txt: "text/plain",
  html: "text/html",
}

function render(app: string, e: StudioEntry, body: RenderIn) {
  const template =
    body.template_key ?? (body.kind === "cv" ? "classic" : "letter-plain")
  const specHash = hashOf(printOf(e.spec))
  const warnings = renderWarnings(e.spec, body)
  const docs = (body.formats ?? ["pdf", "docx", "txt"]).map((fmt) => {
    const found = e.documents.find(
      (d) =>
        d.kind === body.kind &&
        d.fmt === fmt &&
        d.template_key === template &&
        d.spec_hash === specHash
    )
    if (found) return found
    const now = new Date().toISOString()
    const doc: DocumentOut = {
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
      application_id: app,
      kind: body.kind,
      fmt,
      template_key: template,
      spec_hash: specHash,
      content_hash: hashOf(`${specHash}:${body.kind}:${fmt}:${template}`),
      size_bytes: 2048,
      mime_type: MIME[fmt],
      page_count: fmt === "pdf" ? 2 : null,
      warnings,
    }
    e.documents.unshift(doc)
    return doc
  })
  return { documents: docs, warnings }
}

const file = (fmt: DocumentOut["fmt"]) =>
  new HttpResponse("%PDF-1.4\n% mock document\n", {
    headers: { "Content-Type": MIME[fmt] },
  })

/** The packet the owner sent for approval: what the real build snapshots. */
function packetFrom(
  app: string,
  e: StudioEntry,
  body: PacketBuildIn
): PacketOut {
  const now = new Date().toISOString()
  const url = body.destination_url ?? ""
  const given = (q: string) => e.answers.find((a) => a.question === q)
  const contents = {
    requisition: body.requisition ?? null,
    destination: {
      url,
      domain: url ? new URL(url).hostname : "",
      verified: false,
      trusted: false,
    },
    sending_identity: body.sending_identity,
    answers: (body.answers ?? []).map((x) => ({
      question: x.question,
      value: x.value ?? given(x.question)?.value ?? "",
      answer_id: x.answer_id ?? null,
      material: !!given(x.question)?.material,
    })),
    email: body.email ?? null,
    files: body.files ?? [],
    link_permissions: body.link_permissions ?? [],
    channel: body.channel,
    job_version: hashOf(app),
  }
  return {
    id: crypto.randomUUID(),
    created_at: now,
    updated_at: now,
    application_id: app,
    version: e.packets.length + 1,
    content_hash: hashOf(JSON.stringify(contents)),
    approved_at: null,
    approved_by: null,
    invalidated_at: null,
    invalidated_reason: null,
    contents,
  }
}

const conflict = (detail: string) =>
  HttpResponse.json({ detail }, { status: 409 })
/** Stages after which the documents and packet are fixed. */
const GONE = new Set([
  "applying",
  "submitted_unconfirmed",
  "submitted",
  "screening",
  "interview",
  "offer",
  "accepted",
])
const gone = (id: string) => GONE.has(summaryOf(id)?.stage ?? "")

export const studioHandlers = [
  http.get("*/api/applications/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const d = detail(String(params.id))
    return d ? HttpResponse.json(d) : undefined
  }),
  http.get("*/api/applications/:id/spec", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = state.entries[id]
    if (!e) return undefined
    advance(id, e)
    return HttpResponse.json(specState(id, e))
  }),
  http.post("*/api/applications/:id/tailor", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = state.entries[id]
    if (!e) return undefined
    if (gone(id)) return conflict("the application has gone out")
    // Idempotent: an open request is returned as it is.
    if (e.tailoring === "queued" || e.tailoring === "running")
      return HttpResponse.json(
        { run_id: e.run_id, queued: true },
        { status: 202 }
      )
    const paused = e.outcome === "budget_paused"
    const run = newTailorRun(crypto.randomUUID(), paused)
    run.config_versions = { application_id: id }
    state.runs.push(run)
    e.run_id = run.id
    e.tailoring = paused ? "paused" : "queued"
    e.tailoring_error = paused ? BUDGET_ERROR : null
    return HttpResponse.json(
      { run_id: run.id, queued: !paused },
      { status: 202 }
    )
  }),
  http.get("*/api/runs/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const run = state.runs.find((r) => r.id === String(params.id))
    return run ? HttpResponse.json(run) : undefined
  }),
  http.put("*/api/applications/:id/spec", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = state.entries[id]
    if (!e) return undefined
    if (gone(id)) return conflict("the documents can no longer be edited")
    const body = (await request.json()) as { spec: Spec }
    addVersion(id, e, body.spec, "owner")
    const a = summaryOf(id)
    if (a) a.updated_at = new Date().toISOString()
    return HttpResponse.json(detail(id))
  }),
  http.post("*/api/applications/:id/check", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = state.entries[id]
    if (!e) return undefined
    if (e.versions.length === 0) return conflict("there is no draft to check")
    e.check_results = check(id, e.spec)
    e.checked_print = printOf(e.spec)
    e.stale_reasons = []
    return HttpResponse.json(e.check_results)
  }),
  http.post(
    "*/api/applications/:id/documents/render",
    async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const id = String(params.id)
      const e = state.entries[id]
      if (!e) return undefined
      return HttpResponse.json(
        render(id, e, (await request.json()) as RenderIn)
      )
    }
  ),
  http.get("*/api/applications/:id/documents", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const e = state.entries[String(params.id)]
    return e ? HttpResponse.json(e.documents) : undefined
  }),
  http.get("*/api/applications/:id/documents/:kind", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const fmt = new URL(request.url).searchParams.get("fmt") ?? "pdf"
    return file(fmt in MIME ? (fmt as DocumentOut["fmt"]) : "pdf")
  }),
  http.get("*/api/applications/:id/document-files/:doc", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const e = state.entries[String(params.id)]
    if (!e) return undefined
    const doc = e.documents.find((d) => d.id === String(params.doc))
    return doc
      ? file(doc.fmt)
      : HttpResponse.json({ detail: "document not found" }, { status: 404 })
  }),
  http.post("*/api/applications/:id/packet", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = state.entries[id]
    const a = summaryOf(id)
    if (!e || !a) return undefined
    if (!["shortlisted", "tailoring", "ready"].includes(a.stage))
      return conflict(`an application in ${a.stage} cannot be repacked`)
    const body = (await request.json()) as PacketBuildIn
    const st = specState(id, e)
    const generated = (body.files ?? []).some(
      (f) => f.kind === "cv" || f.kind === "letter"
    )
    if (generated && (!st.checked || st.status === "block"))
      return conflict(
        "the documents' checks are out of date or blocking; run the checks again"
      )
    const packet = packetFrom(id, e, body)
    for (const p of e.packets)
      if (!p.invalidated_at)
        Object.assign(p, {
          invalidated_at: packet.created_at,
          invalidated_reason: `replaced by version ${packet.version}`,
        })
    e.packets.unshift(packet)
    a.stage = "ready"
    return HttpResponse.json({
      packet,
      created: true,
      changes: [],
      approval: {
        approved: false,
        status: "wait_for_owner",
        reason: "waiting for your approval",
        pending_action_id: null,
      },
    })
  }),
  // Packets only for applications this mock built one for; else the autopilot handler answers.
  http.get("*/api/applications/:id/packet", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const current = state.entries[String(params.id)]?.packets.find(
      (p) => !p.invalidated_at
    )
    return current ? HttpResponse.json(current) : undefined
  }),
  http.get("*/api/applications/:id/packets", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const packets = state.entries[String(params.id)]?.packets
    return packets?.length ? HttpResponse.json(packets) : undefined
  }),
  http.get("*/api/mail-threads", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const q = new URL(request.url).searchParams
    const app = q.get("application_id")
    const review = q.get("needs_review")
    const items = state.mail
      .filter((t) => !app || t.application_id === app)
      .filter((t) => review === null || String(t.needs_review) === review)
      .sort((x, y) =>
        (y.last_message_at ?? "").localeCompare(x.last_message_at ?? "")
      )
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
]
