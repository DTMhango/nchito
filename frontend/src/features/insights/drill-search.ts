/**
 * Insights drill-through filters as URL search params (Applications, Matches). Kept apart from
 * the bar so the router imports only zod.
 */
import { z } from "zod"
import type { paths } from "@/lib/api/types"

type AppQuery = NonNullable<
  paths["/api/applications"]["get"]["parameters"]["query"]
>
type JobQuery = NonNullable<paths["/api/jobs"]["get"]["parameters"]["query"]>
export type AppReached = NonNullable<AppQuery["reached"]>
export type JobReached = NonNullable<JobQuery["reached"]>

const APP_REACHED = [
  "tailored",
  "approved",
  "sent",
  "reply",
  "interview",
  "offer",
] as const satisfies readonly AppReached[]
const JOB_REACHED = [
  "found",
  "passed_filters",
  "scored_above",
] as const satisfies readonly JobReached[]

const opt = z.string().optional().catch(undefined)

/** The filters both lists share; `reached` differs (application steps vs role steps). */
const base = {
  since: opt,
  until: opt,
  campaign_id: opt,
  track_id: opt,
  source_id: opt,
  country: opt,
}

export const appDrillSchema = z.object({
  ...base,
  channel: z.enum(["email", "browser", "manual"]).optional().catch(undefined),
  reached: z.enum(APP_REACHED).optional().catch(undefined),
})
export type AppDrill = z.infer<typeof appDrillSchema>

export const jobDrillSchema = z.object({
  ...base,
  reached: z.enum(JOB_REACHED).optional().catch(undefined),
})
export type JobDrill = z.infer<typeof jobDrillSchema>

export type AnyDrill = AppDrill | JobDrill
export const DRILL_KEYS = [
  "since",
  "until",
  "campaign_id",
  "track_id",
  "source_id",
  "country",
  "channel",
  "reached",
] as const
export type DrillKey = (typeof DRILL_KEYS)[number]

/** Only the drill keys that are set, or undefined when none is (the plain list). */
export function pickDrill<T extends AnyDrill>(search: T): T | undefined {
  const out: Record<string, string> = {}
  for (const k of DRILL_KEYS) {
    const v = (search as Record<string, string | undefined>)[k]
    if (v) out[k] = v
  }
  return Object.keys(out).length ? (out as T) : undefined
}

/** The search with every drill key removed (or only `key`). */
export function withoutDrill<T extends object>(search: T, key?: DrillKey): T {
  const next = { ...search } as Record<string, unknown>
  for (const k of key ? [key] : DRILL_KEYS) delete next[k]
  return next as T
}
