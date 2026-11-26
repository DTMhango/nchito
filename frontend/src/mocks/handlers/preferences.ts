/**
 * Mock backend for feedback, preference suggestions and the policy preview (wave 4).
 * The preview computes its counts from the request's thresholds over the fictional
 * `PREVIEW_ROLES`, so dragging a handle changes the numbers like the real endpoint.
 */
import { delay, http, HttpResponse } from "msw"
import type { Schemas } from "@/lib/api/types"
import { db } from "../db"
import {
  analysedSuggestion,
  BASE_COUNTS,
  OWNER_ONLY,
  PREVIEW_BIN_WIDTH,
  PREVIEW_CAPS,
  PREVIEW_DEFAULT_THRESHOLDS,
  PREVIEW_ROLES,
  PREVIEW_WINDOW_DAYS,
  seedSuggestions,
  type PreviewRole,
} from "../dataset/preferences"
import { campaignsMock, rubricsMock } from "./campaigns"
import { matchesMock } from "./matches"

type FeedbackOut = Schemas["FeedbackOut"]
type FeedbackIn = Schemas["FeedbackIn"]
type Suggestion = Schemas["SuggestionOut"]
type PreviewIn = Schemas["PolicyPreviewIn"]
type PreviewOut = Schemas["PolicyPreviewOut"]
type Thresholds = Schemas["PreviewThresholds"]

/** Mirrors the default of the `preferences.note_max_length` setting. */
const NOTE_MAX_LENGTH = 500

const latency = () =>
  import.meta.env.MODE === "test" ? Promise.resolve() : delay(90)
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const guard = () => (db.get().session ? null : unauthorized())
const detail = (status: number, text: string) =>
  HttpResponse.json({ detail: text }, { status })

type State = {
  feedback: FeedbackOut[]
  suggestions: Suggestion[]
  lastAnalysed: string | null
  /** Request bodies, for tests. */
  requests: {
    feedback: FeedbackIn[]
    previews: PreviewIn[]
    accepts: { id: string; body: unknown }[]
    dismisses: { id: string; body: unknown }[]
    backtests: { id: string; body: unknown }[]
  }
}

const seed = (): State => ({
  feedback: [],
  suggestions: seedSuggestions(),
  lastAnalysed: null,
  requests: {
    feedback: [],
    previews: [],
    accepts: [],
    dismisses: [],
    backtests: [],
  },
})
let state = seed()

export function resetPreferencesMock() {
  state = seed()
}
export const preferencesMock = { get: () => state }

// ---- policy preview ----

type Outcome = { action: string; reason: string }

function outcome(r: PreviewRole, t: Thresholds, mode: string | null): Outcome {
  if (r.score === null) return { action: "review", reason: "Not scored yet." }
  if (r.score < t.shortlist)
    return { action: "skip", reason: "Below the shortlist line." }
  if (r.score < t.tailor)
    return { action: "add_to_matches", reason: "Below the tailor line." }
  if (r.score < t.auto_apply)
    return {
      action: "prepare",
      reason: `Score ${r.score} is below the auto-apply line ${t.auto_apply}.`,
    }
  if (!r.payKnown)
    return {
      action: "ask_owner",
      reason: "Pay is not stated: unknown never goes automatically.",
    }
  if (r.held)
    return {
      action: "skip",
      reason: "Held: outranked by another role at this employer.",
    }
  if (mode && mode !== "auto_apply")
    return { action: "ask_owner", reason: `Effective mode ${mode}.` }
  return { action: "apply", reason: "Every automation gate passes." }
}

function line(
  rows: { r: PreviewRole; o: Outcome }[],
  t: Thresholds,
  daily: number,
  weekly: number
) {
  const out = {
    would_apply: 0,
    by_channel: { email: 0, browser: 0, other: 0 } as Record<string, number>,
    held: rows.filter((x) => x.r.held && (x.r.score ?? 0) >= t.tailor).length,
    capped: 0,
    qualifying: 0,
  }
  const perDay = new Map<number, number>()
  const perWeek = new Map<number, number>()
  const qualifying = rows
    .filter((x) => x.o.action === "apply")
    .sort((a, b) => b.r.day - a.r.day || (b.r.score ?? 0) - (a.r.score ?? 0))
  out.qualifying = qualifying.length
  for (const { r } of qualifying) {
    const week = Math.floor(r.day / 7)
    const d = perDay.get(r.day) ?? 0
    const w = perWeek.get(week) ?? 0
    if (d >= daily || w >= weekly) {
      out.capped++
      continue
    }
    perDay.set(r.day, d + 1)
    perWeek.set(week, w + 1)
    out.would_apply++
    out.by_channel[r.channel]++
  }
  return out
}

function baselineThresholds(campaignId: string): Thresholds {
  const c = campaignsMock.get().find((x) => x.id === campaignId)
  const rubric = rubricsMock.get().find((r) => r.id === c?.rubric_id)
  const t = (rubric?.body as { thresholds?: Partial<Thresholds> } | undefined)
    ?.thresholds
  return {
    shortlist: t?.shortlist ?? PREVIEW_DEFAULT_THRESHOLDS.shortlist,
    tailor: t?.tailor ?? PREVIEW_DEFAULT_THRESHOLDS.tailor,
    auto_apply: t?.auto_apply ?? PREVIEW_DEFAULT_THRESHOLDS.auto_apply,
  }
}

function preview(
  campaignId: string,
  body: PreviewIn
): PreviewOut | { error: string } {
  const base = baselineThresholds(campaignId)
  const t = { ...base, ...(body.thresholds ?? {}) } as Thresholds
  if (!(t.shortlist <= t.tailor && t.tailor <= t.auto_apply))
    return {
      error: "Thresholds must rise: shortlist, then tailor, then auto-apply.",
    }
  const s = body.settings ?? {}
  const daily = Number(s["automation.daily_cap"] ?? PREVIEW_CAPS.daily_cap)
  const weekly = Number(s["automation.weekly_cap"] ?? PREVIEW_CAPS.weekly_cap)
  if (!Number.isInteger(daily) || !Number.isInteger(weekly) || weekly < daily)
    return { error: "The weekly cap must not be below the daily cap." }
  const qs = String(
    s["automation.quiet_hours_start"] ?? PREVIEW_CAPS.quiet_hours_start
  )
  const qe = String(
    s["automation.quiet_hours_end"] ?? PREVIEW_CAPS.quiet_hours_end
  )
  const mode = body.automation?.mode ?? null

  const before = PREVIEW_ROLES.map((r) => ({ r, o: outcome(r, base, null) }))
  const after = PREVIEW_ROLES.map((r) => ({ r, o: outcome(r, t, mode) }))

  const bins: PreviewOut["histogram"] = []
  for (let lo = 0; lo < 100; lo += PREVIEW_BIN_WIDTH)
    bins.push({
      start: lo,
      end: Math.min(lo + PREVIEW_BIN_WIDTH, 100),
      count: 0,
    })
  for (const { r } of after)
    if (r.score !== null)
      bins[Math.min(Math.floor(r.score / PREVIEW_BIN_WIDTH), bins.length - 1)]
        .count++

  const changes: PreviewOut["changes"] = []
  after.forEach(({ r, o }, i) => {
    const b = before[i].o
    if (o.action === b.action) return
    const kind =
      o.action === "apply"
        ? "newly_automatic"
        : b.action === "apply"
          ? "newly_blocked"
          : "changed"
    const reasons =
      kind === "newly_automatic"
        ? [`was ${b.action.replace(/_/g, " ")}`, b.reason]
        : [o.reason]
    changes.push({
      job_id: r.job_id,
      title: r.title,
      employer: r.employer,
      score: r.score,
      before: b.action,
      after: o.action,
      change: kind,
      reasons,
    })
  })
  const order: Record<string, number> = {
    newly_automatic: 0,
    newly_blocked: 1,
    changed: 2,
  }
  changes.sort((a, b) => order[a.change] - order[b.change])

  const unknownPay = after.filter(
    ({ r }) => r.score !== null && r.score >= t.auto_apply && !r.payKnown
  ).length
  const runNow: Record<string, number> = {}
  for (const { o } of after) runNow[o.action] = (runNow[o.action] ?? 0) + 1
  const todayApply = after.filter(
    ({ r, o }) => r.day === 0 && o.action === "apply"
  ).length

  return {
    campaign_id: campaignId,
    window_days: body.days ?? PREVIEW_WINDOW_DAYS,
    jobs: PREVIEW_ROLES.length,
    thresholds: t,
    baseline_thresholds: base,
    histogram: bins,
    unscored: after.filter(({ r }) => r.score === null).length,
    line: line(after, t, daily, weekly),
    baseline_line: line(
      before,
      base,
      PREVIEW_CAPS.daily_cap,
      PREVIEW_CAPS.weekly_cap
    ),
    run_now: runNow,
    changes,
    changes_total: changes.length,
    unknowns: unknownPay
      ? [
          {
            gate: "pay_known",
            count: unknownPay,
            message: `${unknownPay} ${unknownPay === 1 ? "role" : "roles"} with pay not stated: ${unknownPay === 1 ? "it" : "they"} will never go automatically.`,
          },
        ]
      : [],
    caps: {
      daily_cap: daily,
      weekly_cap: weekly,
      sent_today: PREVIEW_CAPS.sent_today,
      sent_week: PREVIEW_CAPS.sent_week,
      run_now_would_send: Math.min(
        todayApply,
        Math.max(0, daily - PREVIEW_CAPS.sent_today)
      ),
      quiet_hours: `${qs}-${qe}`,
      quiet_now: PREVIEW_CAPS.quiet_now,
      needs_open_check: 0,
    },
  }
}

// ---- suggestions ----

function resultFor(s: Suggestion): Record<string, unknown> {
  if (
    s.kind === "reweight_criterion" ||
    s.kind === "add_penalty" ||
    s.kind === "add_bonus"
  ) {
    const family = rubricsMock.get().find((r) => r.id === s.rubric_id)?.family
    const latest = Math.max(
      1,
      ...rubricsMock
        .get()
        .filter((r) => r.family === family)
        .map((r) => r.version)
    )
    return {
      rubric_id: s.rubric_id,
      rubric_version: latest + 1,
      from_version: latest,
    }
  }
  if (s.kind === "add_tag_rule")
    return { tag_rule_id: crypto.randomUUID(), tagged: 2 }
  if (s.kind === "add_saved_view") return { saved_view_id: crypto.randomUUID() }
  return { rule_index: 1, effect: "exclude" }
}

function summary(campaignId: string): Schemas["PreferencesSummaryOut"] {
  const mine = state.feedback.filter((f) => f.campaign_id === campaignId)
  return {
    campaign_id: campaignId,
    up: BASE_COUNTS.up + mine.filter((f) => f.verdict === "up").length,
    down: BASE_COUNTS.down + mine.filter((f) => f.verdict === "down").length,
    open_suggestions: state.suggestions.filter(
      (s) => s.campaign_id === campaignId && s.status === "open"
    ).length,
    owner_only: OWNER_ONLY,
    last_analysed_at: state.lastAnalysed,
  }
}

export const preferencesHandlers = [
  // ---- feedback ----
  http.get("*/api/jobs/:jobId/feedback", ({ params }) => {
    const g = guard()
    if (g) return g
    return HttpResponse.json(
      state.feedback.filter((f) => f.job_id === params.jobId)
    )
  }),
  http.put("*/api/jobs/:jobId/feedback", async ({ params, request }) => {
    const g = guard()
    if (g) return g
    await latency()
    const body = (await request.json()) as FeedbackIn
    state.requests.feedback.push(body)
    if ((body.note ?? "").length > NOTE_MAX_LENGTH)
      return detail(
        422,
        `Keep the note to ${NOTE_MAX_LENGTH} characters or fewer.`
      )
    const jobId = String(params.jobId)
    const job = matchesMock.get().jobs.find((j) => j.id === jobId)
    const now = new Date().toISOString()
    const campaignId = body.campaign_id ?? null
    const prev = state.feedback.find(
      (f) => f.job_id === jobId && f.campaign_id === campaignId
    )
    const out: FeedbackOut = {
      id: prev?.id ?? crypto.randomUUID(),
      created_at: prev?.created_at ?? now,
      updated_at: now,
      job_id: jobId,
      campaign_id: campaignId,
      verdict: body.verdict,
      reasons: body.reasons ?? [],
      note: body.note ?? null,
      score_at: job?.best_score ?? null,
      rubric_version: 1,
      actor: "owner",
      job_title: job?.title ?? null,
      employer: job?.employer ?? null,
    }
    state.feedback = [...state.feedback.filter((f) => f !== prev), out]
    return HttpResponse.json(out)
  }),
  http.delete("*/api/jobs/:jobId/feedback", ({ params, request }) => {
    const g = guard()
    if (g) return g
    const campaignId = new URL(request.url).searchParams.get("campaign_id")
    state.feedback = state.feedback.filter(
      (f) =>
        !(
          f.job_id === params.jobId &&
          (campaignId === null || f.campaign_id === campaignId)
        )
    )
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- summary, analyse, suggestions ----
  http.get("*/api/preferences/summary", ({ request }) => {
    const g = guard()
    if (g) return g
    const cid = new URL(request.url).searchParams.get("campaign_id") ?? ""
    return HttpResponse.json(summary(cid))
  }),
  http.post("*/api/preferences/analyse", async ({ request }) => {
    const g = guard()
    if (g) return g
    await latency()
    const { campaign_id } = (await request.json()) as { campaign_id: string }
    const kept = state.suggestions.filter(
      (s) => s.campaign_id === campaign_id && s.status === "open"
    ).length
    const created: Suggestion[] = []
    const fresh = { ...analysedSuggestion(), campaign_id }
    if (!state.suggestions.some((s) => s.id === fresh.id)) {
      state.suggestions.push(fresh)
      created.push(fresh)
    }
    state.lastAnalysed = new Date().toISOString()
    const s = summary(campaign_id)
    return HttpResponse.json({
      created,
      kept,
      up: s.up,
      down: s.down,
      owner_only: OWNER_ONLY,
    })
  }),
  http.get("*/api/preferences/suggestions", ({ request }) => {
    const g = guard()
    if (g) return g
    const q = new URL(request.url).searchParams
    const items = state.suggestions.filter(
      (s) =>
        (!q.get("campaign_id") || s.campaign_id === q.get("campaign_id")) &&
        (!q.get("status") || s.status === q.get("status"))
    )
    return HttpResponse.json({
      items,
      total: items.length,
      next_cursor: null,
    })
  }),
  http.post(
    "*/api/preferences/suggestions/:id/backtest",
    async ({ params, request }) => {
      const g = guard()
      if (g) return g
      const s = state.suggestions.find((x) => x.id === params.id)
      if (!s) return detail(404, "Suggestion not found.")
      const body = (await request.json()) as {
        change?: { points?: number } | null
      }
      state.requests.backtests.push({ id: s.id, body })
      const b = structuredClone(s.backtest)!
      const points = body.change?.points
      if (typeof points === "number") {
        // A bigger penalty moves more roles: one extra drop per 10 points over the original.
        b.score_changed = Math.min(b.jobs, b.matched + Math.floor(points / 10))
      }
      return HttpResponse.json(b)
    }
  ),
  http.post(
    "*/api/preferences/suggestions/:id/accept",
    async ({ params, request }) => {
      const g = guard()
      if (g) return g
      await latency()
      const s = state.suggestions.find((x) => x.id === params.id)
      if (!s) return detail(404, "Suggestion not found.")
      const body = (await request.json()) as {
        change?: Suggestion["change"] | null
        note?: string | null
      }
      state.requests.accepts.push({ id: s.id, body })
      if (s.status !== "open")
        return detail(409, "This suggestion was already decided.")
      if (body.change) s.change = body.change
      s.status = "accepted"
      s.decided_by = "owner"
      s.decided_at = new Date().toISOString()
      s.decision_note = body.note ?? null
      s.result = resultFor(s)
      return HttpResponse.json(s)
    }
  ),
  http.post(
    "*/api/preferences/suggestions/:id/dismiss",
    async ({ params, request }) => {
      const g = guard()
      if (g) return g
      const s = state.suggestions.find((x) => x.id === params.id)
      if (!s) return detail(404, "Suggestion not found.")
      const body = (await request.json()) as { note?: string | null }
      state.requests.dismisses.push({ id: s.id, body })
      if (s.status !== "open")
        return detail(409, "This suggestion was already decided.")
      s.status = "dismissed"
      s.decided_by = "owner"
      s.decided_at = new Date().toISOString()
      s.decision_note = body.note ?? null
      return HttpResponse.json(s)
    }
  ),

  // ---- policy preview ----
  http.post(
    "*/api/campaigns/:id/policy-preview",
    async ({ params, request }) => {
      const g = guard()
      if (g) return g
      await latency()
      const body = (await request.json()) as PreviewIn
      state.requests.previews.push(body)
      const out = preview(String(params.id), body)
      if ("error" in out) return detail(422, out.error)
      return HttpResponse.json(out)
    }
  ),
]
