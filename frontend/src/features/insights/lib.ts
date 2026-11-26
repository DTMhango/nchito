import { z } from "zod"
import type { InsightsFilters, RateRow } from "./api"

/** Insights keeps its whole filter in the URL, so a view is linkable and the back button works. */
export const insightsSearchSchema = z.object({
  since: z.string().optional().catch(undefined),
  until: z.string().optional().catch(undefined),
  campaign_id: z.string().optional().catch(undefined),
  track_id: z.string().optional().catch(undefined),
  source_id: z.string().optional().catch(undefined),
  country: z.string().optional().catch(undefined),
  channel: z.enum(["email", "browser", "manual"]).optional().catch(undefined),
  period: z.enum(["week", "month"]).optional().catch(undefined),
})
export type InsightsSearch = z.infer<typeof insightsSearchSchema>

export const FILTER_KEYS = [
  "since",
  "until",
  "campaign_id",
  "track_id",
  "source_id",
  "country",
  "channel",
] as const

export function activeFilterCount(f: InsightsFilters): number {
  return FILTER_KEYS.filter((k) => f[k]).length
}

// ---- drill-through -------------------------------------------------------------------------

/** What a clicked number links to: the Applications or Matches list carrying the same filters. */
export type Drill =
  | { to: "/applications"; search: Record<string, string> }
  | { to: "/matches"; search: Record<string, unknown> }

const clean = (o: Record<string, string | undefined>) =>
  Object.fromEntries(
    Object.entries(o).filter(([, v]) => v !== undefined && v !== "")
  ) as Record<string, string>

/**
 * A number about applications opens Applications with the page's filters plus the cell's own
 * (`reached`: how far the roles got; the dimension of the row). Numbers about roles that have
 * no application yet open Matches, which filters by country.
 */
export function drill(
  filters: InsightsFilters,
  cell: { reached?: string; stage?: string } & Partial<InsightsFilters>,
  list: "applications" | "matches" = "applications"
): Drill {
  const merged = { ...filters, ...cell }
  if (list === "matches") {
    return {
      to: "/matches",
      search: merged.country
        ? { tab: "new", f: { country: { i: [merged.country] } } }
        : { tab: "new" },
    }
  }
  return {
    to: "/applications",
    search: clean({
      since: merged.since,
      until: merged.until,
      campaign_id: merged.campaign_id,
      track_id: merged.track_id,
      source_id: merged.source_id,
      country: merged.country,
      channel: merged.channel,
      reached: cell.reached,
      stage: cell.stage,
    }),
  }
}

/** The dimension a rate row stands for, as a filter. */
export function rowFilter(
  dim: "track" | "source" | "market",
  row: RateRow
): Partial<InsightsFilters> {
  if (row.key === "none") return {}
  if (dim === "track") return { track_id: row.key }
  if (dim === "source") return { source_id: row.key }
  return { country: row.key }
}

// ---- formatting ----------------------------------------------------------------------------

export const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`

export const days = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v.toFixed(1)} d`

const STAGE_LABELS: Record<string, string> = {
  first_reply: "Sent to first reply",
  shortlisted: "Shortlisted",
  tailoring: "Tailoring",
  ready: "Ready",
  applying: "Applying",
  submitted_unconfirmed: "Sent, unconfirmed",
  submitted: "Sent",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
}
export const stageLabel = (s: string) =>
  STAGE_LABELS[s] ?? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ")

// ---- CSV -----------------------------------------------------------------------------------

const cell = (v: string | number | null | undefined) => {
  const s = v === null || v === undefined ? "" : String(v)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCsv(
  headers: string[],
  rows: (string | number | null | undefined)[][]
): string {
  return [headers, ...rows].map((r) => r.map(cell).join(",")).join("\r\n")
}

export function downloadCsv(name: string, csv: string) {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }))
  const a = document.createElement("a")
  a.href = url
  a.download = `${name}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
