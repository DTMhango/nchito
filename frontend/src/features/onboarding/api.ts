/** Calls the set-up guide makes, typed from the generated contract. */
import { queryOptions, useQuery } from "@tanstack/react-query"
import { api, isApiError, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"
import { listQuery, type TrackOut } from "@/features/kit/api"
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

/** The wizard state the server computes (`GET /api/data/onboarding`). */
export type Onboarding = S["OnboardingOut"]
export type OnboardingStep = S["OnboardingStepOut"]

export const onboardingKey = ["onboarding", "state"] as const
export const onboardingQuery = () =>
  queryOptions({
    queryKey: onboardingKey,
    queryFn: () => unwrap(api.GET("/api/data/onboarding")),
  })

/** A step is done only when the server says so; a missing or unknown key is not done. */
export const stepDone = (o: Onboarding | undefined, key: string) =>
  o?.steps.find((s) => s.key === key)?.done === true

/**
 * Which guide steps are done. The server's onboarding state answers kit, facts, campaign
 * criteria and mail; tracks, sources and the dry run are read from what exists on the server.
 * Never from the browser alone.
 */
export function useServerProgress() {
  const state = useQuery(onboardingQuery())
  const tracks = useQuery(listQuery<TrackOut>("tracks"))
  const sources = useQuery(sourcesQuery())
  const runs = useQuery(dryRunsQuery())
  const o = state.data
  return {
    state: o,
    kit: stepDone(o, "kit_present"),
    facts: stepDone(o, "facts_confirmed"),
    tracks: (tracks.data?.length ?? 0) > 0,
    criteria:
      stepDone(o, "campaign_exists") && stepDone(o, "criteria_confirmed"),
    sources: (sources.data ?? []).some((s) => s.enabled),
    mail: stepDone(o, "mail_connected"),
    dryRun: (runs.data?.length ?? 0) > 0,
    complete: o?.complete === true,
    next: o?.steps.find((s) => s.key === o.next_step) ?? null,
    loading: state.isPending,
    error: state.isError,
  }
}
