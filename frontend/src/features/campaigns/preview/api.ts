/** Policy preview and preference suggestions: typed from the generated contract (schema.d.ts). */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"

export type PolicyPreviewIn = Schemas["PolicyPreviewIn"]
export type PolicyPreviewOut = Schemas["PolicyPreviewOut"]
export type PreviewThresholds = Schemas["PreviewThresholds"]
export type PreviewChange = Schemas["PreviewChange"]
export type Summary = Schemas["PreferencesSummaryOut"]
export type OwnerOnlyNote = Schemas["OwnerOnlyNoteOut"]
export type Suggestion = Schemas["SuggestionOut"]
export type SuggestionChange = Suggestion["change"]
export type SuggestionBacktest = Schemas["SuggestionBacktest"]
export type BacktestChangeRow = Schemas["BacktestChangeRow"]
/** The change as the accept/backtest endpoints take it (condition sets in their input shape). */
export type ChangeIn = NonNullable<Schemas["AcceptIn"]["change"]>

export const pk = {
  previewRoot: "policy-preview" as const,
  preview: (campaignId: string, body: PolicyPreviewIn) =>
    ["policy-preview", campaignId, body] as const,
  summary: (campaignId: string) =>
    ["preferences", "summary", campaignId] as const,
  suggestions: (campaignId: string) =>
    ["preferences", "suggestions", campaignId] as const,
  all: ["preferences"] as const,
}

export const previewPolicy = (campaignId: string, body: PolicyPreviewIn) =>
  unwrap(
    api.POST("/api/campaigns/{campaign_id}/policy-preview", {
      params: { path: { campaign_id: campaignId } },
      body,
    })
  )

export const summaryQuery = (campaignId: string) =>
  queryOptions({
    queryKey: pk.summary(campaignId),
    queryFn: () =>
      unwrap(
        api.GET("/api/preferences/summary", {
          params: { query: { campaign_id: campaignId } },
        })
      ),
  })

export const openSuggestionsQuery = (campaignId: string) =>
  queryOptions({
    queryKey: pk.suggestions(campaignId),
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/preferences/suggestions", {
            params: {
              query: { campaign_id: campaignId, status: "open", limit: 100 },
            },
          })
        )
      ).items,
  })

export const analyse = (campaignId: string) =>
  unwrap(
    api.POST("/api/preferences/analyse", {
      body: { campaign_id: campaignId },
    })
  )

export const backtestSuggestion = (id: string, change: ChangeIn | null) =>
  unwrap(
    api.POST("/api/preferences/suggestions/{item_id}/backtest", {
      params: { path: { item_id: id } },
      body: { change },
    })
  )

export const acceptSuggestion = (id: string, change: ChangeIn | null) =>
  unwrap(
    api.POST("/api/preferences/suggestions/{item_id}/accept", {
      params: { path: { item_id: id } },
      body: change ? { change } : {},
    })
  )

export const dismissSuggestion = (id: string) =>
  unwrap(
    api.POST("/api/preferences/suggestions/{item_id}/dismiss", {
      params: { path: { item_id: id } },
      body: {},
    })
  )
