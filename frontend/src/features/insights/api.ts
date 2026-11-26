import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"

export type InsightsReport = Schemas["InsightsOut"]
export type RateRow = Schemas["RateRow"]
export type FunnelStep = Schemas["FunnelStep"]
export type CampaignFunnel = Schemas["CampaignFunnel"]
export type DurationRow = Schemas["DurationRow"]
export type SourceRow = Schemas["SourceRow"]
export type CountRow = Schemas["CountRow"]
export type SpendReport = Schemas["SpendReport"]

/** The filters the screen holds in its URL (the query the API takes). */
export type InsightsFilters = {
  since?: string
  until?: string
  campaign_id?: string
  track_id?: string
  source_id?: string
  country?: string
  channel?: "email" | "browser" | "manual"
  period?: "week" | "month"
}

export const insightsQuery = (filters: InsightsFilters) =>
  queryOptions({
    queryKey: ["insights", filters] as const,
    queryFn: () =>
      unwrap(api.GET("/api/insights", { params: { query: filters } })),
  })
