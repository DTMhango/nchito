/**
 * TEMPORARY. Hand-written shapes for the wave 3 job-ui endpoints (interview pack, compare,
 * posting changes) while the three backend streams that build them are in flight.
 * At integration, replace every type here with the generated one from `@/lib/api/types`
 * (regenerate from `docs/openapi.json` once it carries the routes), delete this file,
 * and swap `pending()` for the typed `api` client. Do not hand-edit `schema.d.ts` instead.
 */

// ---- shared request helper (untyped paths, so the generated client cannot be used yet) ------

import { ApiError } from "@/lib/api/client"

export async function pending<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown
): Promise<T> {
  const res = await globalThis.fetch(
    new Request(new URL(path, window.location.origin), {
      method,
      credentials: "include",
      headers: body === undefined ? {} : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  )
  const text = await res.text()
  const data: unknown = text ? JSON.parse(text) : null
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

// ---- interview pack (DESIGN 10.3a) -----------------------------------------------------------

export type PackSectionKey =
  | "role_brief"
  | "why_you"
  | "questions"
  | "stories"
  | "ask"
  | "gaps"
  | "logistics"
  | "crib"

export type PackItem = {
  id: string
  text: string
  /** Kit fact ids or codes the claim rests on. Empty means the claim is not traced. */
  fact_ids: string[]
  /** The server's own verdict: "untraced" or "stray_figure" when its fact tracing flagged it. */
  flag: "untraced" | "stray_figure" | null
  /** True when the line is a claim about the owner, so it must trace to Kit facts. */
  owner_claim: boolean
  /** Likely questions: the question itself (`text` is the suggested answer). */
  question?: string | null
  /** Question category (questions), the requirement a story answers (stories). */
  category?: string | null
  requirement?: string | null
  favourite?: boolean
  /** A story's situation, action and result. */
  star?: { situation: string; action: string; result: string } | null
  /** Logistics rows: the label, and the value, which is null while it is unknown. */
  label?: string | null
  value?: string | null
}

export type PackSection = {
  key: PackSectionKey
  title: string
  version: number
  /** Every version kept, oldest first. */
  versions: { version: number; created_at: string; note: string }[]
  notes: string
  items: PackItem[]
}

export type InterviewPack = {
  id: string
  application_id: string
  status: "generating" | "ready" | "paused_budget" | "failed"
  progress: { done: number; total: number }
  /** What the pack was built from. */
  based_on: {
    packet_label: string
    cv_version: string
    generated_at: string
  }
  paused: { spent_micros: number; cap_micros: number } | null
  sections: PackSection[]
}

export type InterviewEstimate = {
  cost_micros: number
  currency: string
  sections: number
  model: string
}

export type PracticeFeedback = {
  feedback: string
  fact_ids: string[]
  gaps: string[]
}

// ---- compare roles (DESIGN 18.4) -------------------------------------------------------------

export type CompareJob = {
  job_id: string
  title: string
  employer: string
  score: number | null
  /** Facet rows. A value is "yes", "no", "not_stated" (never the same as "no"), or a word. */
  facets: { key: string; label: string; value: string }[]
  pay: {
    state: "comparable" | "not_comparable" | "not_stated"
    /** Normalised to one period and currency; present only when state is "comparable". */
    min_minor: number | null
    max_minor: number | null
    currency: string | null
    period: string | null
    note: string | null
  }
  criteria: { criterion: string; rating: number | null }[]
  gates: { name: string; result: "pass" | "fail" | "unknown" }[]
  conflict: {
    state: "none" | "winner" | "held" | "released"
    note: string | null
  }
  deadline: {
    state: "dated" | "open_until_filled" | "not_stated"
    on: string | null
  }
  channel: {
    method: string
    effort: "low" | "medium" | "high" | "unknown"
    note: string | null
  }
}

export type CompareOut = { jobs: CompareJob[] }

// ---- posting change alerts (DESIGN 18.4) -----------------------------------------------------

export type PostingChangeKind =
  | "closed"
  | "deadline_moved"
  | "pay_changed"
  | "requirements_changed"
  | "method_changed"
  | "check_failed"

export type PostingChange = {
  id: string
  at: string
  kind: PostingChangeKind
  /** A material change reassesses the role; a wording change does not. */
  material: boolean
  field: string | null
  before: string | null
  after: string | null
  note: string | null
}

export type PostingChanges = {
  items: PostingChange[]
  /** Set when an approved packet was built on a posting that has since changed. */
  stale_packet: {
    application_id: string
    changed_at: string
    reason: string
  } | null
}
