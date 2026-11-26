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
  KIT_FILE_DIFF,
  OLD_KIT_DIFF,
  SHARE_HITS,
  type DiffRow,
} from "../dataset/data"
import { aiMockState } from "./ai"
import { kitStore } from "./kit"

type S = components["schemas"]

let backups: S["BackupOut"][] = structuredClone(DEMO_BACKUPS)
let previews = new Map<string, { source: string; diff: DiffRow[] }>()
let person: S["PersonOut"] | null = null
/** Every write call the import flow made, so tests can check preview came first. */
export const importCalls: string[] = []
export const importFallback = { source: "kit_file" }

export function resetDataMock() {
  backups = structuredClone(DEMO_BACKUPS)
  previews = new Map()
  person = null
  importCalls.length = 0
  importFallback.source = "kit_file"
}

const now = () => new Date().toISOString()
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const mask = (s: string) => "********" + s.slice(-4)
const OWN = ["gmail", "imap_smtp", "gdrive", "telegram", "webhook"]

const READS: Record<string, string> = {
  gmail: "Only the label or search you choose. Nothing else is opened.",
  imap_smtp: "Only the folder you chose.",
  gdrive: "Only the files this app puts in its own folder.",
  telegram: "Nothing. It only sends messages to your chat.",
  webhook: "Nothing. It only sends signed messages.",
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
    const { kind } = (await request.json()) as S["ExportIn"]
    return HttpResponse.json({
      download_url: "/api/data/export/download/demo",
      file_name:
        kind === "share_setup" ? "setup-template.kit.zip" : "personal.kit.zip",
      sha256: "0".repeat(64),
      expires_at: new Date(Date.now() + 600_000).toISOString(),
    } satisfies S["ExportOut"])
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
    const diff = source === "old_kit_zip" ? OLD_KIT_DIFF : KIT_FILE_DIFF
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
        source === "old_kit_zip"
          ? ["Known files are read by code. No AI provider sees this folder."]
          : [],
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
      (d) => !skip.has(d.key) && d.change !== "unchanged"
    )
    if (p.source === "old_kit_zip") {
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
      needs_review: p.source === "old_kit_zip" ? taken.length : 0,
    } satisfies S["ImportCommitOut"])
  }),

  // ---- backups and retention ----
  http.get("*/api/data/backups", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(backups)
  }),
  http.post("*/api/data/backups", () => {
    if (!db.get().session) return unauthorized()
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
    return HttpResponse.json({
      authorize_url: `https://accounts.example.com/o/oauth2/auth?provider=${String(params.provider)}`,
    } satisfies S["OAuthStartOut"])
  }),
  http.post("*/api/connections", async ({ request }) => {
    // Clone: an AI provider falls through to the next handler, which reads the body again.
    const body = (await request.clone().json()) as S["ConnectionCreate"]
    if (!OWN.includes(body.provider)) return undefined
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
  http.post("*/api/connections/:id/test", ({ params }) => {
    const conn = aiMockState().connections.find((c) => c.id === params.id)
    if (!conn || !OWN.includes(conn.provider)) return undefined
    conn.last_checked_at = now()
    conn.health = "ok"
    return HttpResponse.json({ ok: true, detail: "Reached it.", cost_minor: 0 })
  }),
]
