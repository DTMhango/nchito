/**
 * MSW handlers for bulk actions (`/api/bulk/*`) and employers (`/api/employers/*`), mirroring
 * CONTRACTS "Wave 4 bulk additions". A preview plans every item with the same rules the run
 * applies, so the counts match. A run applies at once; the operation then reports progress a
 * step at a time on each read, so the screen shows a live run.
 */
import { http, HttpResponse } from "msw"
import type {
  BulkAction,
  BulkOptionsOut,
  ItemOut,
  OperationOut,
  PreviewIn,
  PreviewOut,
  ReasonGroup,
} from "@/features/bulk/api"
import type { ApplicationSummary } from "@/features/applications/api"
import { checkMove } from "@/features/applications/stages"
import type { EmployerPolicy } from "@/features/employers/api"
import { db } from "@/mocks/db"
import {
  chipFor,
  emptyPolicy,
  employerDetail,
  employerKey,
  listEmployers,
  seedEmployerStore,
  type EmployerStore,
  type Source,
} from "@/mocks/dataset/employers"
import type { MockJob } from "@/mocks/dataset/jobs"
import { applicationsMock } from "./applications"
import { matchesMock, viewJobs } from "./matches"

type Planned = ItemOut["planned"]

type Item = ItemOut & {
  before?: unknown
  after?: unknown
}
type Operation = {
  body: PreviewIn
  op: OperationOut
  items: Item[]
  /** How many items the progress shows as done; grows with each read after the run starts. */
  shown: number
  started: boolean
  finalStatus: OperationOut["status"]
  chunk: number
}

type State = {
  ops: Map<string, Operation>
  employers: EmployerStore
}

const seed = (): State => ({ ops: new Map(), employers: seedEmployerStore() })
let state = seed()

/** Test controls: items that fail when run, and the approve-reviewed setting. */
export const bulkMock = {
  failIds: new Set<string>(),
  approveReviewed: false,
  undoWindowMinutes: 15,
  /** Items per progress step (a small number makes the run visibly staged). */
  chunk: 2,
}

export function resetBulkMock() {
  state = seed()
  bulkMock.failIds = new Set()
  bulkMock.approveReviewed = false
}
export const employersMock = { get: () => state.employers }

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const signedIn = () => db.get().session
const nowIso = () => new Date().toISOString()
const uid = () => crypto.randomUUID()

const REVERSIBLE: BulkAction[] = ["tag", "untag", "skip", "snooze", "archive"]
const COMMON: BulkAction[] = [
  "tag",
  "untag",
  "skip",
  "snooze",
  "queue_tailoring",
  "send_for_approval",
  "archive",
  "export_csv",
]

function options(): BulkOptionsOut {
  const extra: BulkAction[] = bulkMock.approveReviewed
    ? ["approve_reviewed"]
    : []
  return {
    max_selection: 500,
    undo_window_minutes: bulkMock.undoWindowMinutes,
    approve_reviewed_enabled: bulkMock.approveReviewed,
    reversible: REVERSIBLE,
    actions: {
      jobs: [...COMMON, "assign_campaign", "recheck", ...extra],
      applications: [...COMMON, "move_stage", ...extra],
    },
  }
}

const source = (): Source => ({
  jobs: matchesMock.get().jobs,
  apps: applicationsMock().apps,
})

// ---- resolving a selection ----------------------------------------------------------------------

type Subj = {
  id: string
  label: string
  job: MockJob | undefined
  app?: ApplicationSummary
}

function resolve(body: PreviewIn): Subj[] {
  const jobs = matchesMock.get().jobs
  const apps = applicationsMock().apps
  const sel = body.selection
  if (body.subject === "jobs") {
    let list = jobs
    if (sel.ids) list = jobs.filter((j) => sel.ids!.includes(j.id))
    else if (sel.view) {
      const v = sel.view
      list = viewJobs(v.conditions ?? null, v.q).filter(
        (j) => !v.triage || j.triage === v.triage
      )
    }
    return list.map((j) => ({
      id: j.id,
      label: `${j.title}, ${j.canonical_employer}`,
      job: j,
    }))
  }
  let list = apps
  if (sel.ids) list = apps.filter((a) => sel.ids!.includes(a.id))
  else if (sel.view) {
    const v = sel.view
    list = apps.filter(
      (a) =>
        (!v.stage || a.stage === v.stage) &&
        (!v.channel || a.channel === v.channel) &&
        (!v.campaign_id || a.campaign_id === v.campaign_id) &&
        (!v.q ||
          `${a.title} ${a.employer}`.toLowerCase().includes(v.q.toLowerCase()))
    )
  }
  return list.map((a) => ({
    id: a.id,
    label: `${a.title}, ${a.employer}`,
    job: jobs.find((j) => j.id === a.job_id),
    app: a,
  }))
}

// ---- planning and applying one item -------------------------------------------------------------

type Plan = { planned: Planned; code?: string; reason?: string }
const change = (): Plan => ({ planned: "change" })
const same = (reason: string): Plan => ({
  planned: "unchanged",
  code: "already",
  reason,
})
const refuse = (code: string, reason: string): Plan => ({
  planned: "refused",
  code,
  reason,
})

const NEEDS_EMPLOYER_GATES: BulkAction[] = [
  "queue_tailoring",
  "send_for_approval",
  "assign_campaign",
  "approve_reviewed",
]

function plan(body: PreviewIn, s: Subj): Plan {
  const { action } = body
  const p = body.params ?? {}
  const job = s.job
  if (job && NEEDS_EMPLOYER_GATES.includes(action)) {
    const pol = state.employers.policies.get(
      employerKey(job.canonical_employer)
    )
    if (pol?.never_apply)
      return refuse(
        "never_apply",
        `Never apply: ${pol.never_reason ?? "no reason recorded"}`
      )
    if (job.conflict_state === "held")
      return refuse(
        "held",
        `Held: ${job.conflict?.note ?? "another role at this employer outranks it"}`
      )
  }
  switch (action) {
    case "tag":
      return job?.tags.includes(p.tag ?? "")
        ? same(`Already tagged "${p.tag}"`)
        : change()
    case "untag":
      return job?.tags.includes(p.tag ?? "")
        ? change()
        : same(`Not tagged "${p.tag}"`)
    case "skip":
      if (!p.reason)
        return refuse("reason_required", "A reason is required to skip")
      return (s.app ? s.app.stage === "skipped" : job?.triage === "skipped")
        ? same("Already skipped")
        : change()
    case "archive":
      return job?.triage === "archived" ? same("Already archived") : change()
    case "move_stage": {
      if (!s.app)
        return refuse("illegal_stage", "Only applications have stages")
      const col = p.stage === "closed" ? "closed" : (p.stage ?? "")
      const r = checkMove(s.app.stage, col)
      if (r.kind === "refused")
        return r.reason.includes("already")
          ? same("Already there")
          : refuse("illegal_transition", r.reason)
      if (r.kind === "applied-myself")
        return refuse(
          "illegal_transition",
          "Only you can mark it applied, one at a time"
        )
      return change()
    }
    case "queue_tailoring":
    case "send_for_approval":
    case "approve_reviewed":
      if (!s.app)
        return refuse("no_packet", "No application yet, so there is no packet")
      if (
        action === "send_for_approval" &&
        !["ready", "tailoring"].includes(s.app.stage)
      )
        return refuse("no_packet", "No checked packet is ready to send")
      return change()
    default:
      return change()
  }
}

/** Apply one planned change to the mock data; returns what undo needs to put it back. */
function apply(body: PreviewIn, s: Subj): { before: unknown; after: unknown } {
  const p = body.params ?? {}
  const job = s.job
  switch (body.action) {
    case "tag":
    case "untag": {
      if (!job) break
      const before = [...job.tags]
      job.tags =
        body.action === "tag"
          ? [...job.tags, p.tag as string]
          : job.tags.filter((t) => t !== p.tag)
      return { before, after: [...job.tags] }
    }
    case "skip": {
      if (s.app) {
        const before = s.app.stage
        s.app.stage = "skipped"
        return { before, after: "skipped" }
      }
      if (!job) break
      const before = job.triage
      job.triage = "skipped"
      return { before, after: "skipped" }
    }
    case "archive": {
      if (!job) break
      const before = job.triage
      job.triage = "archived"
      return { before, after: "archived" }
    }
    case "snooze": {
      if (s.app) {
        const before = s.app.snoozed_until
        s.app.snoozed_until = p.until ?? null
        return { before, after: p.until ?? null }
      }
      if (!job) break
      const before = job.snoozed_until ?? null
      job.snoozed_until = p.until ?? null
      return { before, after: p.until ?? null }
    }
    case "move_stage": {
      if (!s.app) break
      const before = s.app.stage
      s.app.stage = p.stage as ApplicationSummary["stage"]
      return { before, after: s.app.stage }
    }
  }
  return { before: null, after: null }
}

function restore(body: { action: BulkAction }, s: Subj, it: Item) {
  const job = s.job
  switch (body.action) {
    case "tag":
    case "untag":
      if (job) job.tags = it.before as string[]
      break
    case "skip":
      if (s.app) s.app.stage = it.before as ApplicationSummary["stage"]
      else if (job) job.triage = it.before as MockJob["triage"]
      break
    case "archive":
      if (job) job.triage = it.before as MockJob["triage"]
      break
    case "snooze":
      if (s.app) s.app.snoozed_until = it.before as string | null
      else if (job) job.snoozed_until = it.before as string | null
      break
  }
}

/** Is the item still as the run left it? (An undo leaves an item alone if it changed since.) */
function unchangedSince(body: { action: BulkAction }, s: Subj, it: Item) {
  const job = s.job
  const cur: unknown =
    body.action === "tag" || body.action === "untag"
      ? job?.tags
      : body.action === "skip"
        ? (s.app?.stage ?? job?.triage)
        : body.action === "archive"
          ? job?.triage
          : body.action === "snooze"
            ? (s.app?.snoozed_until ?? job?.snoozed_until ?? null)
            : null
  return JSON.stringify(cur) === JSON.stringify(it.after)
}

// ---- preview ------------------------------------------------------------------------------------

const TITLES: Record<string, string> = {
  held: "Held: another role at the same employer outranks it",
  never_apply: "The employer is set to never apply",
  no_packet: "No packet to send",
  illegal_transition: "That move is not allowed",
  illegal_stage: "That stage does not apply",
  reason_required: "A reason is required",
  already: "Already as asked",
}

function groups(items: Item[], planned: Planned, sample = 5): ReasonGroup[] {
  const by = new Map<string, Item[]>()
  for (const i of items.filter((x) => x.planned === planned))
    by.set(i.planned_code ?? "other", [
      ...(by.get(i.planned_code ?? "other") ?? []),
      i,
    ])
  return [...by].map(([code, list]) => ({
    code,
    title: TITLES[code] ?? code,
    count: list.length,
    samples: list.slice(0, sample).map((i) => ({
      id: i.subject_id,
      label: i.label,
      reason: i.planned_reason ?? "",
    })),
  }))
}

const baseOp = (body: PreviewIn, items: Item[]): OperationOut => ({
  id: uid(),
  created_at: nowIso(),
  updated_at: nowIso(),
  subject: body.subject,
  action: body.action,
  status: "previewed",
  selected: items.length,
  params: (body.params ?? {}) as Record<string, unknown>,
  counts: {},
  done: 0,
  created_by: "owner@example.com",
  started_at: null,
  finished_at: null,
  undo_until: null,
  can_undo: false,
  error: null,
})
function counts(items: Item[]) {
  const c: Record<string, number> = {}
  for (const i of items) c[i.outcome] = (c[i.outcome] ?? 0) + 1
  return c
}

function view(o: Operation): OperationOut {
  if (!o.started) return o.op
  o.shown = Math.min(o.op.selected, o.shown + o.chunk)
  const finished = o.shown >= o.op.selected
  const status = finished ? o.finalStatus : "running"
  if (o.op.status === "undone") return o.op
  const out: OperationOut = {
    ...o.op,
    status,
    done: o.shown,
    counts: finished ? counts(o.items) : {},
    finished_at: finished ? o.op.finished_at : null,
    can_undo:
      finished &&
      REVERSIBLE.includes(o.op.action) &&
      (status === "done" || status === "partial") &&
      (counts(o.items).changed ?? 0) > 0 &&
      !!o.op.undo_until &&
      new Date(o.op.undo_until) > new Date(),
  }
  return out
}

// ---- handlers -----------------------------------------------------------------------------------

export const bulkHandlers = [
  http.get("*/api/bulk/options", () =>
    signedIn() ? HttpResponse.json(options()) : unauthorized()
  ),

  http.post("*/api/bulk/preview", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const body = (await request.json()) as PreviewIn
    if (body.action === "skip" && !body.params?.reason?.trim())
      return HttpResponse.json(
        {
          detail: {
            code: "reason_required",
            reason: "A reason is required to skip.",
          },
        },
        { status: 422 }
      )
    const subjects = resolve(body)
    const items: Item[] = subjects.map((s) => {
      const p = plan(body, s)
      return {
        id: uid(),
        subject_id: s.id,
        label: s.label,
        planned: p.planned,
        planned_code: p.code ?? null,
        planned_reason: p.reason ?? null,
        outcome: "pending",
        code: null,
        reason: null,
      }
    })
    const op = baseOp(body, items)
    state.ops.set(op.id, {
      body,
      op,
      items,
      shown: 0,
      started: false,
      finalStatus: "done",
      chunk: bulkMock.chunk,
    })
    const refused = groups(items, "refused")
    const unchanged = groups(items, "unchanged")[0] ?? null
    const out: PreviewOut = {
      operation_id: op.id,
      subject: body.subject,
      action: body.action,
      selected: items.length,
      will_change: items.filter((i) => i.planned === "change").length,
      unchanged,
      refused,
      refused_total: refused.reduce((n, g) => n + g.count, 0),
      reversible: REVERSIBLE.includes(body.action),
    }
    return HttpResponse.json(out)
  }),

  http.post("*/api/bulk/:id/run", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const o = state.ops.get(String(params.id))
    if (!o) return notFound("Operation")
    const { confirm_count } = (await request.json()) as {
      confirm_count: number
    }
    if (confirm_count !== o.op.selected)
      return HttpResponse.json(
        {
          detail: {
            code: "count_mismatch",
            reason: "The count changed. Preview again.",
          },
        },
        { status: 409 }
      )
    const subjects = new Map(resolve(o.body).map((s) => [s.id, s]))
    const retry = o.op.status === "partial" || o.op.status === "failed"
    for (const it of o.items) {
      if (retry && it.outcome !== "failed") continue
      const s = subjects.get(it.subject_id)
      if (it.planned === "unchanged") {
        it.outcome = "unchanged"
        continue
      }
      if (it.planned === "refused") {
        it.outcome = "refused"
        it.code = it.planned_code
        it.reason = it.planned_reason
        continue
      }
      if (!s || bulkMock.failIds.has(it.subject_id)) {
        it.outcome = "failed"
        it.code = "unavailable"
        it.reason = "The source could not be reached. Try again."
        continue
      }
      const r = apply(o.body, s)
      it.before = r.before
      it.after = r.after
      it.outcome = "changed"
      it.code = null
      it.reason = null
    }
    const c = counts(o.items)
    o.finalStatus = c.failed
      ? c.changed || c.unchanged || c.refused
        ? "partial"
        : "failed"
      : "done"
    o.started = true
    o.shown = retry ? o.op.selected - (c.failed ?? 0) : 0
    o.op = {
      ...o.op,
      status: "queued",
      started_at: nowIso(),
      undo_until: new Date(
        Date.now() + bulkMock.undoWindowMinutes * 60_000
      ).toISOString(),
    }
    return HttpResponse.json(view(o), { status: 202 })
  }),

  http.get("*/api/bulk/:id/items", ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const o = state.ops.get(String(params.id))
    if (!o) return notFound("Operation")
    const outcome = new URL(request.url).searchParams.get("outcome")
    const items = o.items
      .filter((i) => !outcome || i.outcome === outcome)
      .map((i) => ({ ...i, before: undefined, after: undefined }))
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),

  http.post("*/api/bulk/:id/undo", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const o = state.ops.get(String(params.id))
    if (!o) return notFound("Operation")
    if (!REVERSIBLE.includes(o.op.action))
      return HttpResponse.json(
        {
          detail: {
            code: "not_reversible",
            reason: "This action cannot be undone.",
          },
        },
        { status: 409 }
      )
    const subjects = new Map(resolve(o.body).map((s) => [s.id, s]))
    for (const it of o.items) {
      if (it.outcome !== "changed") continue
      const s = subjects.get(it.subject_id)
      if (!s) continue
      if (unchangedSince(o.body, s, it)) {
        restore(o.body, s, it)
        it.outcome = "undone"
      } else {
        it.outcome = "undo_skipped"
        it.code = "changed_since"
        it.reason = "It changed since, so it was left alone."
      }
    }
    o.op = {
      ...o.op,
      status: "undone",
      counts: counts(o.items),
      done: o.op.selected,
      can_undo: false,
    }
    return HttpResponse.json(o.op)
  }),

  http.get("*/api/bulk/:id/csv", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const o = state.ops.get(String(params.id))
    if (!o) return notFound("Operation")
    const rows = ["label", ...o.items.map((i) => JSON.stringify(i.label))]
    return new HttpResponse(rows.join("\n"), {
      headers: { "content-type": "text/csv" },
    })
  }),

  http.get("*/api/bulk/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const o = state.ops.get(String(params.id))
    return o ? HttpResponse.json(view(o)) : notFound("Operation")
  }),

  http.get("*/api/bulk", () => {
    if (!signedIn()) return unauthorized()
    const items = [...state.ops.values()].map((o) => o.op)
    return HttpResponse.json({ items, total: items.length, next_cursor: null })
  }),

  // ---- employers ----
  http.post("*/api/employers/states", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const { job_ids } = (await request.json()) as { job_ids: string[] }
    const src = source()
    const states: Record<string, ReturnType<typeof chipFor>> = {}
    for (const id of job_ids) {
      const j = src.jobs.find((x) => x.id === id)
      if (j) states[id] = chipFor(src, state.employers, j.canonical_employer)
    }
    return HttpResponse.json({ states })
  }),

  http.get("*/api/employers/detail", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const key = new URL(request.url).searchParams.get("key") ?? ""
    const d = employerDetail(source(), state.employers, key)
    return d ? HttpResponse.json(d) : notFound("Employer")
  }),

  http.patch("*/api/employers/policy", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const key = new URL(request.url).searchParams.get("key") ?? ""
    if (!employerDetail(source(), state.employers, key))
      return notFound("Employer")
    const b = (await request.json()) as EmployerPolicy
    const bad = (reason: string) =>
      HttpResponse.json(
        { detail: { code: "invalid", reason } },
        { status: 422 }
      )
    if (
      b.cooldown_days != null &&
      (b.cooldown_days < 0 || b.cooldown_days > 3650)
    )
      return bad("Cooldown must be 0 to 3650 days.")
    if (b.priority != null && (b.priority < -100 || b.priority > 100))
      return bad("Priority must be -100 to 100.")
    if (b.never_apply && !b.never_reason?.trim())
      return bad("Never apply needs a reason.")
    const cur = state.employers.policies.get(key) ?? emptyPolicy()
    const next = { ...cur }
    if ("cooldown_days" in b) next.cooldown_days = b.cooldown_days ?? null
    if (b.always_ask_first != null) next.always_ask_first = b.always_ask_first
    if (b.never_apply != null) {
      next.never_apply = b.never_apply
      next.never_reason = b.never_apply ? (b.never_reason ?? null) : null
    }
    if (b.priority != null) next.priority = b.priority
    if (b.watched != null) next.watched = b.watched
    if ("notes" in b) next.notes = b.notes ?? null
    state.employers.policies.set(key, next)
    const row = listEmployers(source(), state.employers, {}).find(
      (r) => r.key === key
    )
    return HttpResponse.json(row)
  }),

  http.post("*/api/employers/end-cooldown", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const key = new URL(request.url).searchParams.get("key") ?? ""
    const { reason } = (await request.json()) as { reason: string }
    if (!reason?.trim())
      return HttpResponse.json(
        {
          detail: {
            code: "reason_required",
            reason: "Say why you are ending it.",
          },
        },
        { status: 422 }
      )
    state.employers.endedEarly.set(key, {
      at: nowIso(),
      by: "owner@example.com",
      reason: reason.trim(),
    })
    const row = listEmployers(source(), state.employers, {}).find(
      (r) => r.key === key
    )
    return row ? HttpResponse.json(row) : notFound("Employer")
  }),

  http.post("*/api/employers/merge", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const key = new URL(request.url).searchParams.get("key") ?? ""
    const { into } = (await request.json()) as { into: string }
    const src = source()
    const jobs = src.jobs.filter(
      (j) => employerKey(j.canonical_employer) === key
    ).length
    state.employers.aliases.set(key, into.trim())
    return HttpResponse.json({ jobs })
  }),

  http.post("*/api/employers/split", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const { alias } = (await request.json()) as { alias: string }
    state.employers.aliases.delete(employerKey(alias))
    return HttpResponse.json({ jobs: 0 })
  }),

  http.get("*/api/employers", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const p = new URL(request.url).searchParams
    return HttpResponse.json(
      listEmployers(source(), state.employers, {
        state: p.get("state"),
        q: p.get("q"),
      })
    )
  }),
]
