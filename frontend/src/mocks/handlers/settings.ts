/** Mock backend for the settings screens: registry, audit log, configuration history, security. */
import { http, HttpResponse } from "msw"
import { db } from "../db"
import { jobAudit } from "./jobs"
import type {
  AuditEvent,
  ConfigRevision,
  SettingGroupOut,
  SettingOut,
  SettingRevision,
} from "@/features/settings/api"

type Def = Pick<
  SettingOut,
  "key" | "label" | "description" | "kind" | "default"
> &
  Partial<SettingOut>

const g = (
  key: string,
  label: string,
  defs: Def[]
): { key: string; label: string; defs: Def[] } => ({ key, label, defs })

const REGISTRY = [
  g("general", "General", [
    { key: "general.app_name", label: "App name", description: "Shown in the title bar and notifications.", kind: "string", default: "Nchito" },
    { key: "general.timezone", label: "Time zone", description: "Used for schedules, quiet hours and deadlines.", kind: "timezone", default: "Africa/Lusaka" },
    { key: "general.display_currency", label: "Display currency", description: "Currency amounts are shown in.", kind: "currency", default: "USD" },
  ]),
  g("schedule", "Schedule", [
    { key: "schedule.sweep_cron", label: "Sweep schedule", description: "Default schedule for new campaign sweeps.", kind: "cron", default: "0 6 * * *" },
    { key: "schedule.missed_run", label: "Missed runs", description: "What to do after downtime.", kind: "enum", default: "catch_up_once", choices: ["catch_up_once", "skip"] },
    { key: "schedule.concurrent_sweeps", label: "Concurrent sweeps", description: "How many sweeps may run at once.", kind: "int", default: 1, minimum: 1, maximum: 4 },
  ]),
  g("scoring", "Scoring", [
    { key: "scoring.threshold_shortlist", label: "Shortlist threshold", description: "Minimum score to shortlist.", kind: "int", default: 60, minimum: 0, maximum: 100, unit: "points" },
    { key: "scoring.threshold_auto_apply", label: "Auto-apply threshold", description: "Minimum score to apply without asking.", kind: "int", default: 85, minimum: 0, maximum: 100, unit: "points" },
    { key: "scoring.unknown_pay", label: "Unknown pay", description: "How a role with no pay information is treated.", kind: "enum", default: "pass_blocks_auto", choices: ["review", "pass_with_penalty", "pass_blocks_auto", "fail"] },
  ]),
  g("matching", "Matching", [
    { key: "matching.dedupe_similarity", label: "Duplicate similarity", description: "How alike two postings must be to merge.", kind: "float", default: 0.9, minimum: 0.5, maximum: 1 },
    { key: "matching.employer_cooldown_days", label: "Employer cooldown", description: "Days before another role at the same employer.", kind: "int", default: 30, minimum: 0, maximum: 365, unit: "days" },
  ]),
  g("automation", "Automation", [
    { key: "automation.default_mode", label: "Default mode", description: "Automation mode for a new campaign.", kind: "enum", default: "prepare", choices: ["save_only", "prepare", "ask_then_apply", "auto_apply"] },
    { key: "automation.daily_cap", label: "Daily cap", description: "Maximum applications sent per day.", kind: "int", default: 5, minimum: 0, maximum: 100 },
    { key: "automation.quiet_hours_start", label: "Quiet hours start", description: "Nothing goes out from this time.", kind: "time", default: "21:00" },
    { key: "automation.paused", label: "Paused", description: "Stops every new outward action at once.", kind: "bool", default: false },
  ]),
  g("documents", "Documents", [
    { key: "documents.cv_pages", label: "CV pages", description: "Maximum CV length.", kind: "int", default: 2, minimum: 1, maximum: 6, unit: "pages" },
    { key: "documents.cv_template", label: "CV template", description: "Default CV template.", kind: "string", default: "classic" },
  ]),
  g("retention", "Retention", [
    { key: "retention.below_threshold_text_days", label: "Below-threshold text", description: "Days a below-threshold role keeps its full text.", kind: "int", default: 30, minimum: 1, maximum: 365, unit: "days" },
    { key: "retention.unsubmitted_archive_days", label: "Archive unsubmitted roles", description: "Days before an unsubmitted role is archived.", kind: "int", default: 60, minimum: 1, maximum: 730, unit: "days" },
  ]),
  g("reconcile", "Reconciliation", [
    { key: "reconcile.confirmation_wait_hours", label: "Wait for confirmation", description: "Hours to wait before asking you.", kind: "int", default: 24, minimum: 1, maximum: 168, unit: "hours" },
  ]),
  g("notifications", "Notifications", [
    { key: "notifications.digest", label: "Digest", description: "When the digest is sent.", kind: "enum", default: "after_sweep", choices: ["after_sweep", "morning", "off"] },
    { key: "notifications.channels", label: "Channels", description: "Where notifications go.", kind: "list", default: [], choices: ["telegram", "email", "webhook"] },
    { key: "notifications.webhook_label", label: "Webhook label", description: "A name for your webhook. Leave empty for none.", kind: "string", default: null, nullable: true },
  ]),
]

type Row = SettingOut
let rows: Row[] = []
let history: Record<string, SettingRevision[]> = {}
let audit: AuditEvent[] = []
let revisions: ConfigRevision[] = []

const iso = (daysAgo: number, h = 9) => {
  const d = new Date(Date.UTC(2026, 10, 26 - daysAgo, h, 12))
  return d.toISOString()
}

export function resetSettingsMock() {
  rows = REGISTRY.flatMap((grp) =>
    grp.defs.map(
      (d): Row => ({
        group: grp.key,
        nullable: false,
        choices: null,
        minimum: null,
        maximum: null,
        unit: null,
        version: 0,
        updated_by: null,
        updated_at: null,
        value: d.default,
        is_default: true,
        ...d,
      })
    )
  )
  history = {}
  audit = [
    { id: "a1", created_at: iso(0, 7), actor: "system", action: "sweep.completed", subject_type: "campaign", subject_id: "camp-1", detail: { found: 14 }, ip: null },
    { id: "a2", created_at: iso(1, 16), actor: "owner", action: "job.release", subject_type: "job", subject_id: "job-held", detail: { reason: "Different department, different team." }, ip: "127.0.0.1" },
    { id: "a3", created_at: iso(2, 8), actor: "owner", action: "session.login", subject_type: "session", subject_id: null, detail: {}, ip: "127.0.0.1" },
    { id: "a4", created_at: iso(3, 10), actor: "runner", action: "application.submitted", subject_type: "application", subject_id: "app-1", detail: { channel: "email" }, ip: null },
  ]
  revisions = [
    { id: "r3", kind: "rubric", subject_id: "rubric-1", version: 3, author: "owner", created_at: iso(1), diff: { "criteria.0.weight": { old: 20, new: 30 } }, rollback_of: null, note: "More weight on sector fit" },
    { id: "r2", kind: "rubric", subject_id: "rubric-1", version: 2, author: "owner", created_at: iso(6), diff: { "thresholds.shortlist": { old: 55, new: 60 } }, rollback_of: null, note: null },
    { id: "r1", kind: "automation_policy", subject_id: null, version: 1, author: "owner", created_at: iso(9), diff: { mode: { old: "save_only", new: "prepare" } }, rollback_of: null, note: "Start preparing documents" },
  ]
}
resetSettingsMock()

const signedIn = () => db.get().session
const unauthorized = () => HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const bad = (detail: string, status = 422) => HttpResponse.json({ detail }, { status })

function checkValue(r: Row, v: unknown): string | null {
  if (v === null) return r.nullable ? null : "This setting can't be empty."
  if (r.kind === "bool" && typeof v !== "boolean") return "Must be on or off."
  if (["int", "float", "money_minor"].includes(r.kind)) {
    if (typeof v !== "number") return "Must be a number."
    if (r.minimum != null && v < r.minimum) return `Must be at least ${r.minimum}.`
    if (r.maximum != null && v > r.maximum) return `Must be at most ${r.maximum}.`
  }
  if (r.kind === "enum" && !r.choices?.includes(String(v))) return "Not one of the allowed options."
  return null
}

export const settingsHandlers = [
  http.get("*/api/settings", () => {
    if (!signedIn()) return unauthorized()
    const groups: SettingGroupOut[] = REGISTRY.map((grp) => ({
      key: grp.key,
      label: grp.label,
      settings: rows.filter((r) => r.group === grp.key),
    }))
    return HttpResponse.json({ groups })
  }),
  http.get("*/api/settings/:key/history", ({ params }) => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json(history[String(params.key)] ?? [])
  }),
  http.put("*/api/settings/:key", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const row = rows.find((r) => r.key === String(params.key))
    if (!row) return bad("Setting not found.", 404)
    const body = (await request.json()) as { value: unknown; reason?: string | null }
    const err = checkValue(row, body.value)
    if (err) return bad(err)
    const old = row.value
    row.value = body.value
    row.is_default = JSON.stringify(body.value) === JSON.stringify(row.default)
    row.version += 1
    row.updated_by = "owner"
    row.updated_at = new Date().toISOString()
    ;(history[row.key] ??= []).unshift({
      version: row.version,
      old_value: old,
      new_value: body.value,
      changed_by: "owner",
      changed_at: row.updated_at,
      reason: body.reason ?? null,
    })
    audit.unshift({
      id: crypto.randomUUID(),
      created_at: row.updated_at,
      actor: "owner",
      action: "setting.update",
      subject_type: "setting",
      subject_id: row.key,
      detail: { old, new: body.value },
      ip: null,
    })
    return HttpResponse.json(row)
  }),

  http.get("*/api/audit", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const u = new URL(request.url).searchParams
    const action = u.get("action")
    const actor = u.get("actor")
    const st = u.get("subject_type")
    const items = [...jobAudit, ...audit].filter(
      (a) =>
        (!action || a.action.includes(action)) &&
        (!actor || a.actor === actor) &&
        (!st || a.subject_type === st) &&
        (!u.get("subject_id") || a.subject_id === u.get("subject_id"))
    )
    return HttpResponse.json({ items, next_before: null })
  }),

  http.get("*/api/data/config-history", ({ request }) => {
    if (!signedIn()) return unauthorized()
    const kind = new URL(request.url).searchParams.get("kind")
    return HttpResponse.json({
      items: revisions.filter((r) => !kind || r.kind === kind),
      total: revisions.length,
      next_cursor: null,
    })
  }),
  http.post("*/api/data/config-history/:id/rollback", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const target = revisions.find((r) => r.id === String(params.id))
    if (!target) return bad("Revision not found.", 404)
    const { note } = (await request.json()) as { note?: string | null }
    const rev: ConfigRevision = {
      id: crypto.randomUUID(),
      kind: target.kind,
      subject_id: target.subject_id,
      version: Math.max(...revisions.map((r) => r.version)) + 1,
      author: "owner",
      created_at: new Date().toISOString(),
      diff: target.diff,
      rollback_of: target.id,
      note: note ?? null,
    }
    revisions.unshift(rev)
    return HttpResponse.json(rev)
  }),

  // ---- security ----
  http.post("*/api/auth/password", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const b = (await request.json()) as { current_password: string; new_password: string }
    const owner = db.get().owner
    if (!owner || owner.password !== b.current_password) return bad("Current password is wrong.", 400)
    if (b.new_password.length < 12) return bad("Use a password of at least 12 characters.")
    db.update((s) => {
      if (s.owner) s.owner.password = b.new_password
    })
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/auth/totp/setup", () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json({
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_uri: "otpauth://totp/Nchito:owner%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=Nchito",
    })
  }),
  http.post("*/api/auth/totp/enable", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const { code } = (await request.json()) as { code: string }
    if (code !== "123456") return bad("That code is not right. Try the next one.", 400)
    db.update((s) => {
      if (s.owner) s.owner.totp_secret = "JBSWY3DPEHPK3PXP"
    })
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/auth/totp/disable", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const b = (await request.json()) as { password: string; code: string }
    if (db.get().owner?.password !== b.password || b.code !== "123456")
      return bad("Password or code is wrong.", 400)
    db.update((s) => {
      if (s.owner) s.owner.totp_secret = null
    })
    return new HttpResponse(null, { status: 204 })
  }),
]
