/** Mock backend for the settings screens: registry, audit log, configuration history, security. */
import { http, HttpResponse } from "msw"
import { db } from "../db"
import { jobAudit } from "./jobs"
import {
  resetSettingsStore,
  SETTING_GROUPS,
  settingHistory,
  settingRow,
  settingRows,
  writeSetting,
} from "../dataset/settings"
import type {
  AuditEvent,
  ConfigRevision,
  SettingGroupOut,
  SettingOut,
} from "@/features/settings/api"
import type { Session } from "@/lib/api/types"

type Row = SettingOut
let audit: AuditEvent[] = []
let sessions: Session[] = []
let revisions: ConfigRevision[] = []

const iso = (daysAgo: number, h = 9) => {
  const d = new Date(Date.UTC(2026, 10, 26 - daysAgo, h, 12))
  return d.toISOString()
}

export function resetSettingsMock() {
  resetSettingsStore()
  sessions = [
    {
      id: "sess-current",
      created_at: iso(3, 8),
      last_seen_at: iso(0, 9),
      user_agent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
      ip: "127.0.0.1",
      current: true,
    },
    {
      id: "sess-phone",
      created_at: iso(9, 18),
      last_seen_at: iso(1, 20),
      user_agent:
        "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36",
      ip: "192.0.2.24",
      current: false,
    },
  ]
  audit = [
    {
      id: "a1",
      created_at: iso(0, 7),
      actor: "system",
      action: "sweep.completed",
      subject_type: "campaign",
      subject_id: "camp-1",
      detail: { found: 14 },
      ip: null,
    },
    {
      id: "a2",
      created_at: iso(1, 16),
      actor: "owner",
      action: "job.release",
      subject_type: "job",
      subject_id: "job-held",
      detail: { reason: "Different department, different team." },
      ip: "127.0.0.1",
    },
    {
      id: "a3",
      created_at: iso(2, 8),
      actor: "owner",
      action: "session.login",
      subject_type: "session",
      subject_id: null,
      detail: {},
      ip: "127.0.0.1",
    },
    {
      id: "a4",
      created_at: iso(3, 10),
      actor: "runner",
      action: "application.submitted",
      subject_type: "application",
      subject_id: "app-1",
      detail: { channel: "email" },
      ip: null,
    },
  ]
  revisions = [
    {
      id: "r4",
      kind: "setting",
      subject_id: null,
      version: 2,
      author: "owner",
      created_at: iso(0, 8),
      diff: {
        key: "notifications.quiet_hours_start",
        old: "21:00",
        new: "22:00",
      },
      rollback_of: null,
      note: null,
    },
    {
      id: "r3",
      kind: "rubric",
      subject_id: "rubric-1",
      version: 3,
      author: "owner",
      created_at: iso(1),
      diff: { "criteria.0.weight": { old: 20, new: 30 } },
      rollback_of: null,
      note: "More weight on sector fit",
    },
    {
      id: "r2",
      kind: "rubric",
      subject_id: "rubric-1",
      version: 2,
      author: "owner",
      created_at: iso(6),
      diff: { "thresholds.shortlist": { old: 55, new: 60 } },
      rollback_of: null,
      note: null,
    },
    {
      id: "r1",
      kind: "automation_policy",
      subject_id: null,
      version: 1,
      author: "owner",
      created_at: iso(9),
      diff: { mode: { old: "save_only", new: "prepare" } },
      rollback_of: null,
      note: "Start preparing documents",
    },
  ]
}
resetSettingsMock()

const signedIn = () => db.get().session
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const bad = (detail: string, status = 422) =>
  HttpResponse.json({ detail }, { status })

function checkValue(r: Row, v: unknown): string | null {
  if (v === null) return r.nullable ? null : "This setting can't be empty."
  if (r.kind === "bool" && typeof v !== "boolean") return "Must be on or off."
  if (["int", "float", "money_minor"].includes(r.kind)) {
    if (typeof v !== "number") return "Must be a number."
    if (r.minimum != null && v < r.minimum)
      return `Must be at least ${r.minimum}.`
    if (r.maximum != null && v > r.maximum)
      return `Must be at most ${r.maximum}.`
  }
  if (r.kind === "enum" && !r.choices?.includes(String(v)))
    return "Not one of the allowed options."
  if (r.kind === "time" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(String(v)))
    return "Use a 24-hour time such as 07:30."
  if (r.kind === "list" && r.choices && Array.isArray(v)) {
    const wrong = v.filter((x) => !r.choices?.includes(String(x)))
    if (wrong.length) return `Not allowed: ${wrong.join(", ")}.`
  }
  return null
}

export const settingsHandlers = [
  http.get("*/api/settings", () => {
    if (!signedIn()) return unauthorized()
    const groups: SettingGroupOut[] = SETTING_GROUPS.map((grp) => ({
      key: grp.key,
      label: grp.label,
      settings: settingRows().filter((r) => r.group === grp.key),
    })).filter((grp) => grp.settings.length > 0)
    return HttpResponse.json({ groups })
  }),
  http.get("*/api/settings/:key/history", ({ params }) => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json(settingHistory(String(params.key)))
  }),
  http.get("*/api/settings/:key", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const row = settingRow(String(params.key))
    return row ? HttpResponse.json(row) : bad("Setting not found.", 404)
  }),
  http.put("*/api/settings/:key", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const row = settingRow(String(params.key))
    if (!row) return bad("Setting not found.", 404)
    const body = (await request.json()) as {
      value: unknown
      reason?: string | null
    }
    const err = checkValue(row, body.value)
    if (err) return bad(err)
    const old = writeSetting(row, body.value, body.reason ?? null)
    audit.unshift({
      id: crypto.randomUUID(),
      created_at: row.updated_at ?? new Date().toISOString(),
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
  // Rollback is not built on the server yet (501), so the mock answers the same.
  http.post("*/api/data/config-history/:id/rollback", () =>
    signedIn() ? bad("Rollback is not available yet.", 501) : unauthorized()
  ),

  // ---- security ----
  http.get("*/api/auth/sessions", () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json(sessions)
  }),
  http.post("*/api/auth/sessions/revoke-others", () => {
    if (!signedIn()) return unauthorized()
    const revoked = sessions.filter((x) => !x.current).length
    sessions = sessions.filter((x) => x.current)
    return HttpResponse.json({ revoked })
  }),
  http.delete("*/api/auth/sessions/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const target = sessions.find((x) => x.id === String(params.id))
    if (!target) return bad("Session not found.", 404)
    sessions = sessions.filter((x) => x !== target)
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/auth/password", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const b = (await request.json()) as {
      current_password: string
      new_password: string
    }
    const owner = db.get().owner
    if (!owner || owner.password !== b.current_password)
      return bad("Current password is wrong.", 400)
    if (b.new_password.length < 12)
      return bad("Use a password of at least 12 characters.")
    db.update((s) => {
      if (s.owner) s.owner.password = b.new_password
    })
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/auth/totp/setup", () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json({
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_uri:
        "otpauth://totp/Nchito:owner%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=Nchito",
    })
  }),
  http.post("*/api/auth/totp/enable", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const { code } = (await request.json()) as { code: string }
    if (code !== "123456")
      return bad("That code is not right. Try the next one.", 400)
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
