/** Calls the set-up guide makes, typed from the generated contract. */
import { queryOptions, useQuery } from "@tanstack/react-query"
import { api, isApiError, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"
import { connectionsQuery } from "@/features/settings/connections/api"
import { listQuery, type TrackOut } from "@/features/kit/api"
import { campaignsQuery } from "@/features/campaigns/api"
import { sourcesQuery } from "@/features/sources/api"

type S = components["schemas"]
export type Person = S["PersonOut"]
export type PersonInput = S["PersonIn"]
export type CampaignIn = S["CampaignIn"]
export type RunOut = S["RunOut"]

export const personQuery = () =>
  queryOptions({
    queryKey: ["kit", "person"] as const,
    queryFn: async () => {
      try {
        return await unwrap(api.GET("/api/kit/person"))
      } catch (e) {
        if (isApiError(e, 404)) return null
        throw e
      }
    },
  })
export const savePerson = (body: PersonInput) =>
  unwrap(api.PUT("/api/kit/person", { body }))

export const startDryRun = (campaignId: string) =>
  unwrap(
    api.POST("/api/runs", {
      body: { kind: "sweep", campaign_id: campaignId, dry_run: true },
    })
  ) as unknown as Promise<RunOut>

export const dryRunsQuery = () =>
  queryOptions({
    queryKey: ["onboarding", "dry-runs"] as const,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/runs", {
            params: { query: { kind: "sweep", limit: 50 } },
          })
        )
      ).items.filter((r) => r.dry_run),
  })

/** Which steps are done, from what exists on the server. Never from the browser alone. */
export function useServerProgress() {
  const person = useQuery(personQuery())
  const tracks = useQuery(listQuery<TrackOut>("tracks"))
  const campaigns = useQuery(campaignsQuery())
  const sources = useQuery(sourcesQuery())
  const conns = useQuery(connectionsQuery())
  const runs = useQuery(dryRunsQuery())
  return {
    person: !!person.data?.full_name?.value,
    tracks: (tracks.data?.length ?? 0) > 0,
    campaign: (campaigns.data?.length ?? 0) > 0,
    sources: (sources.data ?? []).some((s) => s.enabled),
    mail: (conns.data ?? []).some(
      (c) => c.provider === "gmail" || c.provider === "imap_smtp"
    ),
    dryRun: (runs.data?.length ?? 0) > 0,
    loading: person.isPending || tracks.isPending || campaigns.isPending,
  }
}
