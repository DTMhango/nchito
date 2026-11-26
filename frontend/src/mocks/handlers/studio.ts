/**
 * Mock backend for the Studio: tailor, spec, check, documents and packets, plus the
 * tailoring runs. The application itself stays in the applications mock; this store adds
 * the spec and check results for the applications it knows, and falls through otherwise.
 */
import { http, HttpResponse } from "msw"
import type { Schemas } from "@/lib/api/types"
import { db } from "../db"
import {
  draftedSpec,
  newTailorRun,
  seedStudio,
  type MockStudio,
} from "../dataset/studio"
import { appliedJobId, applicationIdFor } from "../dataset/jobs"
import { toDetail } from "../dataset/applications"
import { applicationsMock } from "./applications"
import { kitStore, kitWaivers } from "./kit"
import { matchesMock } from "./matches"

type Spec = Schemas["ApplicationSpec-Output"]
type CheckResult = Schemas["CheckResult"]
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

let state: MockStudio = seedStudio(reqsFor, check)
export const resetStudioMock = () => {
  state = seedStudio(reqsFor, check)
}
export const studioMock = () => state

const summaryOf = (id: string) =>
  applicationsMock().apps.find((a) => a.id === id)

function detail(id: string) {
  const a = summaryOf(id)
  const e = state.entries[id]
  if (!a || !e) return null
  return { ...toDetail(a), spec: e.spec, check_results: e.check_results }
}

/** Advance a live run: running on the first poll, finished (and drafted) on the second. */
function tick(runId: string) {
  const run = state.runs.find((r) => r.id === runId)
  if (!run || !["queued", "running"].includes(run.status)) return run
  const n = (state.polls[runId] = (state.polls[runId] ?? 0) + 1)
  const at = new Date().toISOString()
  if (n === 1) Object.assign(run, { status: "running", updated_at: at })
  else {
    Object.assign(run, {
      status: "succeeded",
      updated_at: at,
      finished_at: at,
      cost_micros: 38_400,
      cost_minor: 4,
    })
    const app = String(run.config_versions.application_id)
    const e = state.entries[app]
    if (e) {
      e.spec = draftedSpec(reqsFor(app))
      e.check_results = check(app, e.spec)
    }
    const a = summaryOf(app)
    if (a && a.stage === "shortlisted") a.stage = "tailoring"
  }
  return run
}

const PDF = "%PDF-1.4\n% mock document\n"

export const studioHandlers = [
  http.get("*/api/applications/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const d = detail(String(params.id))
    return d ? HttpResponse.json(d) : undefined
  }),
  http.post("*/api/applications/:id/tailor", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = (state.entries[id] ??= {
      spec: draftedSpec([]),
      check_results: [],
      packets: [],
      outcome: "draft",
    })
    const run = newTailorRun(crypto.randomUUID(), e.outcome === "budget_paused")
    run.config_versions = { application_id: id }
    state.runs.push(run)
    return HttpResponse.json(
      { run_id: run.id, queued: run.status === "queued" },
      { status: 202 }
    )
  }),
  http.get("*/api/runs/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const run = tick(String(params.id))
    return run ? HttpResponse.json(run) : undefined
  }),
  http.put("*/api/applications/:id/spec", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = state.entries[id]
    if (!e) return undefined
    const body = (await request.json()) as { spec: Spec }
    e.spec = body.spec
    const a = summaryOf(id)
    if (a) a.updated_at = new Date().toISOString()
    return HttpResponse.json(detail(id))
  }),
  http.post("*/api/applications/:id/check", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    const e = state.entries[id]
    if (!e) return undefined
    e.check_results = check(id, e.spec)
    return HttpResponse.json(e.check_results)
  }),
  http.get("*/api/applications/:id/packets", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const packets = state.entries[String(params.id)]?.packets
    // No studio packets: fall through to the autopilot handler (see handlers.ts order).
    return packets?.length ? HttpResponse.json(packets) : undefined
  }),
  http.get("*/api/applications/:id/documents/:kind", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const fmt = new URL(request.url).searchParams.get("fmt") ?? "pdf"
    const type =
      fmt === "docx"
        ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        : fmt === "html"
          ? "text/html"
          : "application/pdf"
    return new HttpResponse(PDF, { headers: { "Content-Type": type } })
  }),
]
