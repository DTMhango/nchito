import { delay, http, HttpResponse } from "msw"
import { db } from "../db"
import type {
  BacktestRow,
  Campaign,
  CampaignInput,
  ConditionSet,
  Rubric,
  RubricBody,
} from "@/features/campaigns/types"
import type { CampaignRuleIn } from "@/features/matches/types"
import {
  rubrics as seedRubrics,
  seedCampaigns,
} from "@/mocks/dataset/campaigns"
import { RUBRIC } from "@/mocks/dataset/jobs"
import { matchesMock } from "./matches"
import { matches as evaluate } from "./matches-evaluator"

const latency = () =>
  import.meta.env.MODE === "test" ? Promise.resolve() : delay(100)
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const page = <T>(items: T[]) => ({
  items,
  total: items.length,
  next_cursor: null,
})

// ---- in-memory state (reset between tests) ----
// The rubric the shared jobs were scored with (data/jobs) is one of the rubrics here too.
const allRubrics = () => [
  ...structuredClone(seedRubrics),
  structuredClone(RUBRIC) as unknown as Rubric,
]
let campaigns: Campaign[] = seedCampaigns()
let rubrics: Rubric[] = allRubrics()

export function resetCampaignMocks() {
  campaigns = seedCampaigns()
  rubrics = allRubrics()
}

/** The shared jobs (Matches owns them): preview, backtest and counts read the same roles. */
const jobs = () => matchesMock.get().jobs

/** Assessed roles by triage for a campaign, and held by a conflict group. */
function withCounts(c: Campaign): Campaign {
  const mine = jobs().filter((j) =>
    (matchesMock.get().assessments.get(j.id) ?? []).some(
      (a) => a.campaign_id === c.id
    )
  )
  return {
    ...c,
    match_counts: {
      new: mine.filter((j) => j.triage === "new").length,
      shortlisted: mine.filter((j) => j.triage === "shortlisted").length,
      held: mine.filter((j) => j.conflict_state === "held").length,
    },
  }
}

function previewCount(set: ConditionSet, limit = 5) {
  const all = jobs()
  const matched = all.filter((j) => evaluate(j, set as never))
  return {
    matched: matched.length,
    total: all.length,
    sample_job_ids: matched.slice(0, limit).map((j) => j.id),
  }
}

function hash(s: string) {
  let h = 0
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h
}

function backtest(rubric: Rubric, jobIds: string[] | null) {
  const all = jobs()
  const chosen = jobIds ? all.filter((j) => jobIds.includes(j.id)) : all
  const t = {
    shortlist: 60,
    tailor: 70,
    auto: 85,
    ...(rubric.body.thresholds ?? {}),
  } as Record<string, number | null>
  const bias = rubric.version % 3 === 0 ? 2 : 4
  const scored = chosen.map((j) => {
    const old = j.best_score ?? 0
    const delta = (hash(j.id + rubric.id) % 17) - 8 + bias
    return { j, old, next: Math.max(0, Math.min(100, old + delta)) }
  })
  const rank = (key: "old" | "next") => {
    const sorted = [...scored].sort((a, b) => b[key] - a[key])
    return new Map(sorted.map((s, i) => [s.j.id, i + 1]))
  }
  const oldRank = rank("old")
  const newRank = rank("next")
  const lines: [string, string, string, number | null | undefined][] = [
    ["shortlist_up", "shortlist_down", "shortlist", t.shortlist],
    ["tailor_up", "tailor_down", "tailor", t.tailor],
    ["auto_up", "auto_down", "auto", t.auto_apply ?? t.auto],
  ]
  const rows: BacktestRow[] = scored.map((s) => {
    const crossed: BacktestRow["crossed"] = []
    for (const [up, down, , line] of lines) {
      if (line == null) continue
      if (s.old < line && s.next >= line) crossed.push(up as never)
      if (s.old >= line && s.next < line) crossed.push(down as never)
    }
    return {
      job_id: s.j.id,
      title: s.j.title,
      employer: s.j.employer,
      old_score: s.old,
      new_score: s.next,
      old_rank: oldRank.get(s.j.id) ?? null,
      new_rank: newRank.get(s.j.id) ?? null,
      crossed,
    }
  })
  return { rows, estimated_cost_minor: rows.length * 3, cost_currency: "USD" }
}

function estimate(jobIds: string[] | null) {
  const all = jobs()
  const n = jobIds
    ? all.filter((j) => jobIds.includes(j.id)).length
    : all.length
  return {
    jobs: n,
    to_score: n,
    estimated_cost_minor: n * 3,
    cost_currency: "USD",
  }
}

function applyInput(c: Campaign, body: CampaignInput): Campaign {
  return {
    ...c,
    name: body.name,
    track_id: body.track_id ?? null,
    priority: body.priority ?? 0,
    criteria: body.criteria as Campaign["criteria"],
    unknown_data_policy: body.unknown_data_policy ?? {},
    rubric_id: body.rubric_id ?? null,
    automation: body.automation ?? { mode: "prepare", per_channel: {} },
    budget: body.budget ?? {},
    source_ids: body.source_ids ?? [],
    schedule_cron: body.schedule_cron ?? null,
    preferred_seniority: body.preferred_seniority ?? null,
    updated_at: new Date().toISOString(),
  }
}

const ceilingFor = (
  review: Campaign["review_state"]
): Campaign["mode_ceiling"] =>
  review === "confirmed" ? "auto_apply" : "prepare"

const guard = () => (db.get().session ? null : unauthorized())

export const campaignHandlers = [
  http.get("*/api/campaigns", async () => {
    const g = guard()
    if (g) return g
    await latency()
    return HttpResponse.json(page(campaigns.map(withCounts)))
  }),
  http.post("*/api/campaigns", async ({ request }) => {
    const g = guard()
    if (g) return g
    const body = (await request.json()) as CampaignInput
    const base = seedCampaigns()[1]
    const now = new Date().toISOString()
    const c: Campaign = {
      ...applyInput(base, {
        ...body,
        criteria: body.criteria ?? { titles: [] },
      }),
      id: crypto.randomUUID(),
      created_at: now,
      status: "draft",
      review_state: "needs_review",
      confirmed_at: null,
      paused_until: null,
      last_sweep_checkpoint: null,
      mode_ceiling: "prepare",
    }
    campaigns.push(c)
    return HttpResponse.json(c, { status: 201 })
  }),
  http.get("*/api/campaigns/:id", async ({ params }) => {
    const g = guard()
    if (g) return g
    await latency()
    const c = campaigns.find((x) => x.id === params.id)
    return c ? HttpResponse.json(withCounts(c)) : notFound("Campaign")
  }),
  http.put("*/api/campaigns/:id", async ({ params, request }) => {
    const g = guard()
    if (g) return g
    const idx = campaigns.findIndex((x) => x.id === params.id)
    if (idx < 0) return notFound("Campaign")
    const body = (await request.json()) as CampaignInput
    if (!body.name?.trim())
      return HttpResponse.json(
        { detail: "Give the campaign a name." },
        { status: 422 }
      )
    campaigns[idx] = applyInput(campaigns[idx], body)
    return HttpResponse.json(campaigns[idx])
  }),
  http.post("*/api/campaigns/:id/status", async ({ params, request }) => {
    const g = guard()
    if (g) return g
    const idx = campaigns.findIndex((x) => x.id === params.id)
    if (idx < 0) return notFound("Campaign")
    const b = (await request.json()) as {
      status: Campaign["status"]
      paused_until?: string | null
    }
    campaigns[idx] = {
      ...campaigns[idx],
      status: b.status,
      paused_until: b.status === "paused" ? (b.paused_until ?? null) : null,
    }
    return HttpResponse.json(campaigns[idx])
  }),
  http.post("*/api/campaigns/:id/confirm", ({ params }) => {
    const g = guard()
    if (g) return g
    const idx = campaigns.findIndex((x) => x.id === params.id)
    if (idx < 0) return notFound("Campaign")
    campaigns[idx] = {
      ...campaigns[idx],
      review_state: "confirmed",
      confirmed_at: new Date().toISOString(),
      mode_ceiling: ceilingFor("confirmed"),
      unconfirmed: [],
    }
    return HttpResponse.json(campaigns[idx])
  }),
  http.post("*/api/campaigns/:id/confirm/:item", ({ params }) => {
    const g = guard()
    if (g) return g
    const idx = campaigns.findIndex((x) => x.id === params.id)
    if (idx < 0) return notFound("Campaign")
    const c = campaigns[idx]
    const unconfirmed = c.unconfirmed.filter((i) => i !== params.item)
    const done = unconfirmed.length === 0
    campaigns[idx] = {
      ...c,
      unconfirmed,
      review_state: done ? "confirmed" : c.review_state,
      confirmed_at: done ? new Date().toISOString() : c.confirmed_at,
      mode_ceiling: ceilingFor(done ? "confirmed" : c.review_state),
    }
    return HttpResponse.json(withCounts(campaigns[idx]))
  }),
  http.post("*/api/campaigns/:id/rules", async ({ params, request }) => {
    const g = guard()
    if (g) return g
    const idx = campaigns.findIndex((x) => x.id === params.id)
    if (idx < 0) return notFound("Campaign")
    const rule = (await request.json()) as CampaignRuleIn
    if ((rule.effect === "penalty" || rule.effect === "bonus") && !rule.points)
      return HttpResponse.json(
        { detail: "Say how many points." },
        { status: 422 }
      )
    const c = campaigns[idx]
    campaigns[idx] = {
      ...c,
      criteria: {
        ...c.criteria,
        rules: [...(c.criteria?.rules ?? []), rule],
      } as Campaign["criteria"],
    }
    return HttpResponse.json(withCounts(campaigns[idx]))
  }),
  http.post("*/api/campaigns/:id/clone", ({ params }) => {
    const g = guard()
    if (g) return g
    const src = campaigns.find((x) => x.id === params.id)
    if (!src) return notFound("Campaign")
    const copy: Campaign = {
      ...structuredClone(src),
      id: crypto.randomUUID(),
      name: `${src.name} (copy)`,
      status: "draft",
      review_state: "needs_review",
      confirmed_at: null,
      paused_until: null,
      last_sweep_checkpoint: null,
      mode_ceiling: "prepare",
    }
    campaigns.push(copy)
    return HttpResponse.json(copy, { status: 201 })
  }),
  http.post("*/api/campaigns/:id/preview", async ({ request }) => {
    const g = guard()
    if (g) return g
    await latency()
    const body = (await request.json()) as {
      conditions: ConditionSet
      limit?: number
    }
    return HttpResponse.json(previewCount(body.conditions, body.limit ?? 50))
  }),

  // ---- rubrics ----
  http.get("*/api/rubrics", () => {
    const g = guard()
    if (g) return g
    return HttpResponse.json(page(rubrics))
  }),
  http.post("*/api/rubrics", async ({ request }) => {
    const g = guard()
    if (g) return g
    const b = (await request.json()) as {
      name: string
      body: RubricBody
      family?: string
    }
    const fam =
      rubrics.find((r) => r.name === b.name)?.family ?? crypto.randomUUID()
    const version =
      Math.max(
        0,
        ...rubrics.filter((r) => r.family === fam).map((r) => r.version)
      ) + 1
    const now = new Date().toISOString()
    const r = {
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
      name: b.name,
      body: b.body,
      family: fam,
      version,
      status: "draft",
    } as Rubric
    rubrics.push(r)
    return HttpResponse.json(r, { status: 201 })
  }),
  http.get("*/api/rubrics/:id", ({ params }) => {
    const r = rubrics.find((x) => x.id === params.id)
    return r ? HttpResponse.json(r) : notFound("Rubric")
  }),
  http.put("*/api/rubrics/:id", async ({ params, request }) => {
    const idx = rubrics.findIndex((x) => x.id === params.id)
    if (idx < 0) return notFound("Rubric")
    if (rubrics[idx].status !== "draft")
      return HttpResponse.json(
        { detail: "Only a draft can be edited. Start a new draft." },
        { status: 409 }
      )
    const b = (await request.json()) as { name: string; body: RubricBody }
    rubrics[idx] = {
      ...rubrics[idx],
      name: b.name,
      body: b.body as Rubric["body"],
    }
    return HttpResponse.json(rubrics[idx])
  }),
  http.post("*/api/rubrics/:id/activate", ({ params }) => {
    const target = rubrics.find((x) => x.id === params.id)
    if (!target) return notFound("Rubric")
    const total = target.body.criteria.reduce((s, c) => s + c.weight, 0)
    if (total !== 100)
      return HttpResponse.json(
        { detail: "Weights must add up to 100." },
        { status: 422 }
      )
    for (const r of rubrics)
      if (r.family === target.family && r.status === "active")
        r.status = "retired"
    target.status = "active"
    return HttpResponse.json(target)
  }),
  http.post("*/api/rubrics/backtest/estimate", async ({ request }) => {
    const g = guard()
    if (g) return g
    const b = (await request.json()) as { job_ids: string[] | null }
    return HttpResponse.json(estimate(b.job_ids))
  }),
  http.post("*/api/rubrics/backtest", async ({ request }) => {
    const g = guard()
    if (g) return g
    await latency()
    const b = (await request.json()) as {
      rubric_id: string
      job_ids: string[] | null
    }
    const r = rubrics.find((x) => x.id === b.rubric_id)
    if (!r) return notFound("Rubric")
    return HttpResponse.json(backtest(r, b.job_ids))
  }),
]

/** Read access for tests. */
export const campaignsMock = { get: () => campaigns }
