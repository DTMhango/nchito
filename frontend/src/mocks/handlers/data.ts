/**
 * Mock backend for Settings > Data, Connections (mail, Drive, Telegram, webhook), system health
 * and the person record. In-memory and fictional. The AI provider records stay in handlers/ai.ts;
 * these handlers only take the other providers and let the rest fall through.
 */
import { http, HttpResponse } from "msw"
import type { components } from "@/lib/api/types"
import { db } from "../db"
import {
  DEMO_BACKUPS,
  DEMO_HEALTH,
  KIT_FILE_DIFF,
  OLD_KIT_DIFF,
  SHARE_HITS,
  type DiffRow,
} from "../dataset/data"
import { aiMockState } from "./ai"
import { kitStore } from "./kit"
import { campaignsMock } from "./campaigns"
import { settingRow } from "../dataset/settings"

type S = components["schemas"]

let backups: S["BackupOut"][] = structuredClone(DEMO_BACKUPS)
let previews = new Map<string, { source: string; diff: DiffRow[] }>()
let person: S["PersonOut"] | null = null
/** Every write call the import flow made, so tests can check preview came first. */
export const importCalls: string[] = []
export const importFallback = { source: "kit_file" }
/** Switches tests flip to reach the server's refusals. */
export const dataMock = {
  /** False: OAuth start answers 409 (no Google client configured on the server). */
  googleConfigured: true,
  /** False: backups answer 503 (pg_dump missing). */
  pgDump: true,
  /** True: every export link has expired (download answers 404). */
  exportsExpired: false,
  /** Overrides the computed onboarding state when set. */
  onboarding: null as S["OnboardingOut"] | null,
  health: structuredClone(DEMO_HEALTH),
}
let exportsMade = new Map<string, string>()

export function resetDataMock() {
  backups = structuredClone(DEMO_BACKUPS)
  previews = new Map()
  person = null
  importCalls.length = 0
  importFallback.source = "kit_file"
  dataMock.googleConfigured = true
  dataMock.pgDump = true
  dataMock.exportsExpired = false
  dataMock.onboarding = null
  dataMock.health = structuredClone(DEMO_HEALTH)
  exportsMade = new Map()
}

/** The wizard state, computed from the mock stores the way the server computes it. */
function onboardingState(): S["OnboardingOut"] {
  const facts = (kitStore().facts ?? []).filter((f) => f.status !== "retired")
  const pending = facts.filter((f) => f.review_state === "needs_review").length
  const kit = person !== null || facts.length > 0
  const camps = campaignsMock.get().filter((c) => c.status !== "archived")
  const campPending = camps.filter(
    (c) => c.review_state === "needs_review"
  ).length
  const mail = aiMockState().connections.some(
    (c) => (c.provider === "gmail" || c.provider === "imap_smtp") && c.enabled
  )
  const steps: S["OnboardingStepOut"][] = [
    {
      key: "kit_present",
      label: "Your kit is loaded",
      done: kit,
      detail: kit
        ? "A profile or facts are in the library."
        : "Upload your CV, old kit or a kit file.",
    },
    {
      key: "facts_confirmed",
      label: "Facts confirmed",
      done: kit && pending === 0 && facts.length > 0,
      detail: pending
        ? `${pending} item(s) still need review.`
        : "Every fact is confirmed.",
    },
    {
      key: "campaign_exists",
      label: "A campaign exists",
      done: camps.length > 0,
      detail: camps.length
        ? `${camps.length} campaign(s).`
        : "Create a campaign for the roles you want.",
    },
    {
      key: "criteria_confirmed",
      label: "Campaign criteria confirmed",
      done: camps.length > 0 && campPending === 0,
      detail: campPending
        ? `${campPending} campaign(s) have criteria to confirm.`
        : "All campaign criteria are confirmed.",
    },
    {
      key: "mail_connected",
      label: "A mail connection exists",
      done: mail,
      detail: mail
        ? "Mail is connected."
        : "Connect the mailbox you use for the search.",
    },
  ]
  const next = steps.find((st) => !st.done)?.key ?? null
  return { steps, complete: next === null, next_step: next }
}

/** Server-side checks for the connections this file owns (records.py, mail_connections.py). */
function checkConnection(
  provider: string,
  config: Record<string, unknown>,
  secrets: Record<string, string>,
  creating: boolean
): string | null {
  if (provider === "telegram") {
    const chat = String(config.chat_id ?? "")
    if ((creating || "chat_id" in config) && !/^(-?\d+|@\w+)$/.test(chat))
      return "chat_id must be a number (or @channelname)"
    const token = secrets.bot_token ?? ""
    if ((creating || token) && !/^\d+:[\w-]{20,}$/.test(token))
      return "bot_token looks wrong; paste the whole token from BotFather"
  }
  if (provider === "webhook") {
    const url = String(config.url ?? "")
    if ((creating || "url" in config) && !url.startsWith("https://"))
      return "url must start with https://"
    const secret = secrets.signing_secret ?? ""
    if ((creating || secret) && secret.length < 16)
      return "signing_secret must be at least 16 characters"
  }
  if (provider === "search_api") {
    // search_api.py: known config keys only, endpoint http(s), the key as header or param.
    const known = [
      "endpoint",
      "query_param",
      "limit_param",
      "key_header",
      "key_param",
      "result_path",
      "url_field",
      "title_field",
    ]
    const unknown = Object.keys(config).filter((k) => !known.includes(k))
    if (unknown.length)
      return `unknown config keys: ${unknown.sort().join(", ")} (the key goes in 'secrets')`
    const endpoint = String(config.endpoint ?? "")
    if (
      (creating || "endpoint" in config) &&
      !/^https?:\/\/[^/\s]+/.test(endpoint)
    )
      return `'${endpoint}' is not an http(s) URL`
    if (config.key_header && config.key_param)
      return "give the key as a header or a query parameter, not both"
    if (creating && !(secrets.api_key ?? "").trim())
      return "api_key is required"
  }
  if (provider === "imap_smtp" && creating) {
    const missing = ["from_address", "imap_host", "smtp_host"].filter(
      (k) => !config[k]
    )
    if (missing.length) return `missing: ${missing.join(", ")}`
    if (!secrets.password) return "the app password is required"
  }
  return null
}

const now = () => new Date().toISOString()
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const mask = (s: string) => "********" + s.slice(-4)
const OWN = [
  "gmail",
  "imap_smtp",
  "gdrive",
  "telegram",
  "webhook",
  "search_api",
]

const READS: Record<string, string> = {
  gmail: "Only the label or search you choose. Nothing else is opened.",
  imap_smtp: "Only the folder you chose.",
  gdrive: "Only the files this app puts in its own folder.",
  telegram: "Nothing. It only sends messages to your chat.",
  webhook: "Nothing. It only sends signed messages.",
  search_api:
    "Sends search phrases built from your campaigns' titles and places to the search provider. Reads only the result links.",
}
const SCOPES: Record<string, string[]> = {
  gmail: [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
  ],
  gdrive: ["https://www.googleapis.com/auth/drive.file"],
}

export const dataHandlers = [
  // ---- person ----
  http.get("*/api/kit/person", () => {
    if (!db.get().session) return unauthorized()
    if (!person)
      return HttpResponse.json({ detail: "No person yet." }, { status: 404 })
    return HttpResponse.json(person)
  }),
  http.put("*/api/kit/person", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as S["PersonIn"]
    person = {
      id: "person-1",
      created_at: person?.created_at ?? now(),
      updated_at: now(),
      review_state: "confirmed",
      origin: "owner",
      confirmed_at: now(),
      links: {},
      extra_fields: {},
      ...body,
    } as S["PersonOut"]
    return HttpResponse.json(person)
  }),

  // ---- export ----
  http.post("*/api/data/export/preview", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const { kind } = (await request.json()) as S["ExportIn"]
    return HttpResponse.json({
      kind,
      counts:
        kind === "share_setup"
          ? { rubrics: 2, templates: 3, themes: 1, sources: 6 }
          : { facts: 42, answers: 18, documents: 7, applications: 31 },
      personal_details_found: kind === "share_setup" ? SHARE_HITS : [],
    } satisfies S["ExportPreviewOut"])
  }),
  http.post("*/api/data/export", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as S["ExportIn"]
    if (body.kind === "share_setup" && !body.acknowledge_personal_details)
      return HttpResponse.json(
        {
          detail: `the preview found ${SHARE_HITS.length} personal detail(s); remove them or export with acknowledge_personal_details`,
        },
        { status: 409 }
      )
    const id = crypto.randomUUID()
    const name =
      body.kind === "share_setup"
        ? "setup-template.kit.zip"
        : "personal.kit.zip"
    exportsMade.set(id, name)
    const minutes = Number(settingRow("data.export_link_minutes")?.value ?? 0)
    return HttpResponse.json({
      download_url: `/api/data/exports/${id}`,
      file_name: name,
      sha256: "0".repeat(64),
      expires_at: new Date(Date.now() + minutes * 60_000).toISOString(),
    } satisfies S["ExportOut"])
  }),
  http.get("*/api/data/exports/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    if (!exportsMade.has(id) || dataMock.exportsExpired)
      return HttpResponse.json(
        { detail: "this export has expired; prepare it again" },
        { status: 404 }
      )
    return new HttpResponse(new Blob(["PK"]), {
      headers: { "Content-Type": "application/zip" },
    })
  }),

  // ---- onboarding ----
  http.get("*/api/data/onboarding", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(dataMock.onboarding ?? onboardingState())
  }),

  // ---- import ----
  http.post("*/api/data/import", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    importCalls.push("preview")
    // In the test runner, reading a jsdom File body back aborts the request, so tests pick the
    // source with `importFallback.source`. The browser reads the real form field.
    let source: string = importFallback.source
    if (import.meta.env.MODE !== "test")
      source = String((await request.formData()).get("source"))
    const diff =
      source === "old_kit_zip" || source === "free_form"
        ? OLD_KIT_DIFF
        : KIT_FILE_DIFF
    const import_id = crypto.randomUUID()
    previews.set(import_id, { source, diff })
    return HttpResponse.json({
      import_id,
      source,
      diff: diff.map((d) => ({
        entity: d.entity,
        key: d.key,
        change: d.change,
        before: d.before,
        after: d.after,
      })),
      notices:
        source !== "old_kit_zip"
          ? []
          : settingRow("data.old_kit_ai_extraction")?.value === true
            ? [
                "Files the built-in reader did not recognise were sent to your AI provider.",
              ]
            : [
                "Known files were read by code. No AI provider saw this folder.",
              ],
    })
  }),
  http.post("*/api/data/import/commit", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    importCalls.push("commit")
    const body = (await request.json()) as S["ImportCommitIn"]
    const p = previews.get(body.import_id)
    if (!p)
      return HttpResponse.json({ detail: "Unknown import." }, { status: 404 })
    const skip = new Set(body.exclude_keys ?? [])
    const taken = p.diff.filter(
      (d) => !skip.has(`${d.entity}:${d.key}`) && d.change !== "unchanged"
    )
    if (p.source === "old_kit_zip" || p.source === "free_form") {
      for (const d of taken)
        kitStore().answers.push({
          id: `answer-${crypto.randomUUID().slice(0, 8)}`,
          created_at: now(),
          updated_at: now(),
          review_state: "needs_review",
          origin: "import",
          confirmed_at: null,
          title: d.key,
          group: d.group ?? d.entity,
          patterns: { canonical: d.key, variants: [] },
          value: String(d.after ?? ""),
          value_type: "text",
          conditions: {},
          answer_class: "ask_first",
          material: true,
          settled: false,
          scope: "all_matching",
          scope_ref: null,
          forced_choice: null,
          review_after: null,
        })
    }
    previews.delete(body.import_id)
    return HttpResponse.json({
      created: taken.filter((d) => d.change === "add").length,
      updated: taken.filter((d) => d.change !== "add").length,
      needs_review: p.source === "kit_file" ? 0 : taken.length,
    } satisfies S["ImportCommitOut"])
  }),

  // ---- backups and retention ----
  http.get("*/api/data/backups", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(backups)
  }),
  http.post("*/api/data/backups", () => {
    if (!db.get().session) return unauthorized()
    if (!dataMock.pgDump)
      return HttpResponse.json(
        { detail: "pg_dump was not found; set PG_BIN_DIR" },
        { status: 503 }
      )
    const b: S["BackupOut"] = {
      id: `bk-${backups.length + 1}`,
      created_at: now(),
      size_bytes: 18_600_000,
      target: "local",
      encrypted: true,
    }
    backups = [b, ...backups]
    return HttpResponse.json(b, { status: 202 })
  }),
  http.post("*/api/data/retention/run", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json({ ok: true }, { status: 202 })
  }),

  // ---- health ----
  http.get("*/api/health/detail", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json({ ...dataMock.health, time: now() })
  }),
  http.get("*/api/health", () =>
    HttpResponse.json({
      status: "ok",
      version: "0.2.0",
      time: now(),
      db: { ok: true, latency_ms: 2.1, error: null },
      worker: {
        ok: true,
        last_beat_at: new Date(Date.now() - 20_000).toISOString(),
        age_seconds: 20,
        workers: 1,
      },
    } satisfies S["Health"])
  ),

  // ---- connections other than the AI providers (those fall through to handlers/ai.ts) ----
  http.post("*/api/connections/oauth/:provider/start", ({ params }) => {
    if (!db.get().session) return unauthorized()
    if (!dataMock.googleConfigured)
      return HttpResponse.json(
        {
          detail:
            "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are not set",
        },
        { status: 409 }
      )
    return HttpResponse.json({
      authorize_url: `https://accounts.example.com/o/oauth2/auth?provider=${String(params.provider)}`,
    } satisfies S["OAuthStartOut"])
  }),
  http.post("*/api/connections", async ({ request }) => {
    // Clone: an AI provider falls through to the next handler, which reads the body again.
    const body = (await request.clone().json()) as S["ConnectionCreate"]
    if (!OWN.includes(body.provider)) return undefined
    if (body.provider === "gmail" || body.provider === "gdrive")
      return HttpResponse.json(
        { detail: `${body.provider} connects through Google sign-in` },
        { status: 422 }
      )
    const err = checkConnection(
      body.provider,
      body.config ?? {},
      body.secrets ?? {},
      true
    )
    if (err) return HttpResponse.json({ detail: err }, { status: 422 })
    const conn: S["ConnectionOut"] = {
      id: crypto.randomUUID(),
      created_at: now(),
      updated_at: now(),
      provider: body.provider,
      label: body.label,
      config: body.config ?? {},
      secrets_masked: Object.fromEntries(
        Object.entries(body.secrets ?? {}).map(([k, v]) => [k, mask(v)])
      ),
      scopes_granted: SCOPES[body.provider] ?? [],
      reads_description: READS[body.provider] ?? null,
      health: "unknown",
      last_checked_at: null,
      enabled: true,
    }
    aiMockState().connections.push(conn)
    return HttpResponse.json(conn, { status: 201 })
  }),
  // PUT merges config (the server does too); secrets given replace the saved ones.
  http.put("*/api/connections/:id", async ({ params, request }) => {
    const conn = aiMockState().connections.find((c) => c.id === params.id)
    if (!conn || !OWN.includes(conn.provider)) return undefined
    const body = (await request.clone().json()) as S["ConnectionUpdate"]
    const err = checkConnection(
      conn.provider,
      body.config ?? {},
      body.secrets ?? {},
      false
    )
    if (err) return HttpResponse.json({ detail: err }, { status: 422 })
    if (body.label) conn.label = body.label
    if (body.enabled != null) conn.enabled = body.enabled
    conn.config = { ...conn.config, ...(body.config ?? {}) }
    for (const [k, v] of Object.entries(body.secrets ?? {}))
      if (v) conn.secrets_masked[k] = mask(v)
    conn.updated_at = now()
    return HttpResponse.json(conn)
  }),
  http.post("*/api/connections/:id/test", ({ params }) => {
    const conn = aiMockState().connections.find((c) => c.id === params.id)
    if (!conn || !OWN.includes(conn.provider)) return undefined
    conn.last_checked_at = now()
    if (conn.provider === "search_api") {
      // One search for a neutral phrase; an endpoint on a ".invalid" host stands for a refusal.
      const ok = !String(conn.config.endpoint ?? "").includes(".invalid")
      conn.health = ok ? "ok" : "failing"
      return HttpResponse.json({
        ok,
        detail: ok
          ? "the provider answered (1 result)"
          : "ConnectError: could not reach the search provider",
        cost_minor: 0,
      })
    }
    conn.health = "ok"
    return HttpResponse.json({ ok: true, detail: "Reached it.", cost_minor: 0 })
  }),
]
