/** MSW handlers for `/api/kit/*` (and skill aliases), backed by an in-memory fictional Kit. */
import { http, HttpResponse } from "msw"
import type { Resource } from "@/features/kit/api"
import { db } from "../db"
import { kitSeed } from "@/mocks/data/kit"
import { FACTS } from "@/mocks/data/jobs"

type Row = Record<string, unknown> & { id: string }

/** The Kit seed plus the facts the shared job assessments cite as evidence (data/jobs). */
function seed() {
  const s = kitSeed()
  s.facts.push(...(structuredClone(FACTS) as unknown as typeof s.facts))
  return s
}
let store = seed()
/** Reset the mock Kit to its seed (tests call this; the browser mock resets on reload). */
export const resetKitMock = () => {
  store = seed()
}
export const kitStore = () => store

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = () =>
  HttpResponse.json({ detail: "Not found." }, { status: 404 })
const now = () => new Date().toISOString()

const REVIEW_ENTITY: Partial<Record<Resource, string>> = {
  experiences: "experience",
  facts: "fact",
  skills: "skill",
  references: "reference",
  tracks: "track",
  guardrails: "guardrail",
  answers: "answer",
  templates: "template",
  vault: "vault_document",
}
const ENTITY_RESOURCE = Object.fromEntries(
  Object.entries(REVIEW_ENTITY).map(([r, e]) => [e, r])
) as Record<string, Resource>

function matches(r: string, row: Row, q: URLSearchParams): boolean {
  if (r !== "facts") return true
  const f = row as unknown as {
    tags: string[]
    tracks: string[]
    text: string
    code: string
  }
  const eq = (k: string) => !q.get(k) || row[k] === q.get(k)
  if (!eq("status") || !eq("review_state") || !eq("kind")) return false
  if (q.get("tag") && !f.tags.includes(q.get("tag")!)) return false
  if (q.get("track") && !f.tracks.includes(q.get("track")!)) return false
  const s = q.get("q")?.toLowerCase()
  if (s && !`${f.text} ${f.code}`.toLowerCase().includes(s)) return false
  return true
}

function crud(r: Resource, path: string) {
  const prefix = `*${path}`
  return [
    http.get(prefix, ({ request }) => {
      if (!db.get().session) return unauthorized()
      const q = new URL(request.url).searchParams
      const items = store[r].filter((x) => matches(r, x, q))
      return HttpResponse.json({
        items,
        total: items.length,
        next_cursor: null,
      })
    }),
    http.post(prefix, async ({ request }) => {
      if (!db.get().session) return unauthorized()
      const body = (await request.json()) as Record<string, unknown>
      const id = `${r}-${crypto.randomUUID().slice(0, 8)}`
      const row: Row = {
        id,
        created_at: now(),
        updated_at: now(),
        review_state: "confirmed",
        origin: "owner",
        confirmed_at: now(),
        ...defaults(r),
        ...body,
      }
      if (r === "facts") {
        row.code = body.code || `F-${200 + store.facts.length}`
        row.status = "draft"
      }
      if (r === "guardrails")
        row.type = (body.params as { type?: string })?.type ?? "never_mention"
      if (r === "templates") row.builtin = false
      store[r].push(row)
      return HttpResponse.json(row, { status: 201 })
    }),
    http.put(`${prefix}/:id`, async ({ params, request }) => {
      if (!db.get().session) return unauthorized()
      const i = store[r].findIndex((x) => x.id === params.id)
      if (i < 0) return notFound()
      const body = (await request.json()) as Record<string, unknown>
      const row = { ...store[r][i], ...body, updated_at: now() } as Row
      if (r === "guardrails")
        row.type = (body.params as { type?: string })?.type ?? row.type
      store[r][i] = row
      return HttpResponse.json(row)
    }),
    http.delete(`${prefix}/:id`, ({ params }) => {
      if (!db.get().session) return unauthorized()
      store[r] = store[r].filter((x) => x.id !== params.id)
      return new HttpResponse(null, { status: 204 })
    }),
  ]
}

function defaults(r: Resource) {
  if (r === "facts")
    return {
      tags: [],
      tracks: [],
      canonical_wording: false,
      keep_out_of_prompts: false,
    }
  if (r === "answers")
    return {
      answer_class: "ask_first",
      scope: "this_application",
      conditions: {
        version: 1,
        root: { type: "group", op: "and", negate: false, conditions: [] },
      },
      pending_applications_using: 0,
    }
  return {}
}

/** Plain code check over the texts: never_mention, never_together, require_wording. */
function runCheck(texts: Record<string, string>) {
  const text = Object.values(texts).join("\n").toLowerCase()
  const results: Record<string, unknown>[] = []
  for (const g of store.guardrails) {
    if (g.enabled === false) continue
    const p = g.params as Record<string, string[] | string>
    const sev = g.strictness === "advise" ? "warn" : "block"
    if (p.type === "never_mention") {
      for (const t of p.terms as string[])
        if (text.includes(t.toLowerCase()))
          results.push({
            check: String(g.name),
            status: sev,
            detail: `Mentions "${t}".`,
            guardrail_id: g.id,
            waived: false,
          })
    } else if (p.type === "never_together") {
      const a = (p.group_a as string[]).find((t) =>
        text.includes(t.toLowerCase())
      )
      const b = (p.group_b as string[]).find((t) =>
        text.includes(t.toLowerCase())
      )
      if (a && b)
        results.push({
          check: String(g.name),
          status: sev,
          detail: `"${a}" and "${b}" appear together.`,
          guardrail_id: g.id,
          waived: false,
        })
    } else if (p.type === "require_wording") {
      for (const t of p.instead_of as string[])
        if (text.includes(t.toLowerCase()))
          results.push({
            check: String(g.name),
            status: sev,
            detail: `Use "${String(p.use)}", not "${t}".`,
            guardrail_id: g.id,
            waived: false,
          })
    }
  }
  if (results.length === 0)
    results.push({
      check: "All rules",
      status: "pass",
      detail: null,
      guardrail_id: null,
      waived: false,
    })
  return { results, blocked: results.some((x) => x.status === "block") }
}

export const kitHandlers = [
  http.get("*/api/kit/review", ({ request }) => {
    if (!db.get().session) return unauthorized()
    const only = new URL(request.url).searchParams.get("entity")
    const items = Object.entries(REVIEW_ENTITY).flatMap(([r, entity]) =>
      only && only !== entity
        ? []
        : store[r as Resource]
            .filter((x) => x.review_state === "needs_review")
            .map((x, i) => ({
              entity,
              id: x.id,
              title: String(
                x.name ?? x.title ?? x.org ?? x.code ?? x.key ?? "Item"
              ),
              group: entity,
              stale_first_rank: i,
              conflicts_with: [],
            }))
    )
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),
  http.post("*/api/kit/review/:entity/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const r = ENTITY_RESOURCE[String(params.entity)]
    const i = r ? store[r].findIndex((x) => x.id === params.id) : -1
    if (i < 0) return notFound()
    const { decision } = (await request.json()) as { decision: string }
    if (decision === "drop") store[r].splice(i, 1)
    else
      store[r][i] = {
        ...store[r][i],
        review_state: "confirmed",
        confirmed_at: now(),
      }
    return HttpResponse.json({ ok: true })
  }),
  http.post("*/api/kit/facts/:id/:action", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const i = store.facts.findIndex((x) => x.id === params.id)
    if (i < 0) return notFound()
    store.facts[i] = {
      ...store.facts[i],
      status: params.action === "approve" ? "approved" : "retired",
    }
    return HttpResponse.json(store.facts[i])
  }),
  http.post("*/api/kit/guardrails/check", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as { texts: Record<string, string> }
    return HttpResponse.json(runCheck(body.texts ?? {}))
  }),
  http.post("*/api/kit/vault", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const form = await request.formData()
    const file = form.get("file") as File | null
    if (!file || !String(form.get("title") ?? "").trim())
      return HttpResponse.json(
        { detail: "Choose a file and give it a title." },
        { status: 422 }
      )
    const row: Row = {
      id: `vault-${crypto.randomUUID().slice(0, 8)}`,
      created_at: now(),
      updated_at: now(),
      review_state: "confirmed",
      origin: "owner",
      confirmed_at: now(),
      doc_type: String(form.get("doc_type") ?? "other"),
      title: String(form.get("title")),
      sha256: "d4".repeat(32),
      mime_type: file.type || "application/octet-stream",
      size_bytes: file.size,
      sensitivity: String(form.get("sensitivity") ?? "normal"),
      has_text_layer: file.type === "application/pdf",
    }
    store.vault.push(row)
    return HttpResponse.json(row, { status: 201 })
  }),
  http.get("*/api/kit/vault/:id/download", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const row = store.vault.find((x) => x.id === params.id)
    if (!row) return notFound()
    return new HttpResponse(
      `Sample file: ${String(row.title)}\nThis is mock content for preview.`,
      { headers: { "Content-Type": "text/plain" } }
    )
  }),
  ...crud("experiences", "/api/kit/experiences"),
  ...crud("facts", "/api/kit/facts"),
  ...crud("skills", "/api/kit/skills"),
  ...crud("references", "/api/kit/references"),
  ...crud("tracks", "/api/kit/tracks"),
  ...crud("guardrails", "/api/kit/guardrails"),
  ...crud("answers", "/api/kit/answers"),
  ...crud("templates", "/api/kit/templates"),
  ...crud("vault", "/api/kit/vault"),
  ...crud("skill-aliases", "/api/skill-aliases"),
]
