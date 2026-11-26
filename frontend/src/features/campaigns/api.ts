/**
 * Campaign endpoints, typed from the generated OpenAPI types (schema.d.ts).
 * Kept inside the feature; the shared client only knows the wave 0 contract.
 */
import createClient from "openapi-fetch"
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { unwrap } from "@/lib/api/client"
import type {
  BacktestResult,
  Campaign,
  CampaignInput,
  ConditionSet,
  GenPaths,
  RubricBody,
} from "./types"

const origin =
  typeof window !== "undefined" ? window.location.origin : "http://localhost"
const api = createClient<GenPaths>({
  baseUrl: origin,
  credentials: "include",
  fetch: (request: Request) => globalThis.fetch(request),
})

export const ck = {
  campaigns: ["campaigns"] as const,
  campaign: (id: string) => ["campaigns", id] as const,
  rubrics: ["rubrics"] as const,
  facets: ["jobs", "facets"] as const,
  jobs: ["campaigns", "jobs"] as const,
  sources: ["sources"] as const,
  employers: ["watched-employers"] as const,
  tracks: ["kit", "tracks"] as const,
  settings: ["settings"] as const,
}

export const campaignsQuery = () =>
  queryOptions({
    queryKey: ck.campaigns,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/campaigns", { params: { query: { limit: 200 } } })
        )
      ).items,
  })
export const campaignQuery = (id: string) =>
  queryOptions({
    queryKey: ck.campaign(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/campaigns/{item_id}", {
          params: { path: { item_id: id } },
        })
      ),
  })
export const rubricsQuery = () =>
  queryOptions({
    queryKey: ck.rubrics,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/rubrics", { params: { query: { limit: 200 } } })
        )
      ).items,
  })
export const facetsQuery = () =>
  queryOptions({
    queryKey: ck.facets,
    queryFn: () => unwrap(api.GET("/api/jobs/facets")),
    staleTime: 5 * 60_000,
  })
export const jobsQuery = () =>
  queryOptions({
    queryKey: ck.jobs,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/jobs", { params: { query: { limit: 200 } } })
        )
      ).items,
  })
export const sourcesQuery = () =>
  queryOptions({
    queryKey: ck.sources,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/sources", { params: { query: { limit: 200 } } })
        )
      ).items,
  })
export const employersQuery = () =>
  queryOptions({
    queryKey: ck.employers,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/watched-employers", {
            params: { query: { limit: 200 } },
          })
        )
      ).items,
  })
export const tracksQuery = () =>
  queryOptions({
    queryKey: ck.tracks,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/kit/tracks", { params: { query: { limit: 200 } } })
        )
      ).items,
  })
export const settingsQuery = () =>
  queryOptions({
    queryKey: ck.settings,
    queryFn: () => unwrap(api.GET("/api/settings")),
    staleTime: 60_000,
  })

/** Flatten the grouped settings into a key -> setting map. */
export function settingsByKey(
  groups: { settings: { key: string; value?: unknown }[] }[] | undefined
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const g of groups ?? []) for (const s of g.settings) out[s.key] = s.value
  return out
}

export const saveCampaign = (id: string, body: CampaignInput) =>
  unwrap(
    api.PUT("/api/campaigns/{item_id}", {
      params: { path: { item_id: id } },
      body,
    })
  )

export const previewRule = (id: string, conditions: ConditionSet) =>
  unwrap(
    api.POST("/api/campaigns/{item_id}/preview", {
      params: { path: { item_id: id } },
      body: { conditions },
    })
  )

export const backtestRubric = (body: {
  rubric_id: string
  campaign_id: string
  job_ids: string[] | null
}) => unwrap(api.POST("/api/rubrics/backtest", { body }))

export function useCampaigns() {
  return useQuery(campaignsQuery())
}

export function useCampaignMutations() {
  const qc = useQueryClient()
  const refresh = (c?: Campaign) => {
    void qc.invalidateQueries({ queryKey: ck.campaigns })
    if (c) qc.setQueryData(ck.campaign(c.id), c)
  }
  return {
    create: useMutation({
      mutationFn: (body: CampaignInput) =>
        unwrap(api.POST("/api/campaigns", { body })),
      onSuccess: refresh,
    }),
    clone: useMutation({
      mutationFn: (id: string) =>
        unwrap(
          api.POST("/api/campaigns/{item_id}/clone", {
            params: { path: { item_id: id } },
          })
        ),
      onSuccess: refresh,
    }),
    setStatus: useMutation({
      mutationFn: (v: {
        id: string
        status: "active" | "paused" | "archived"
        paused_until?: string | null
      }) =>
        unwrap(
          api.POST("/api/campaigns/{item_id}/status", {
            params: { path: { item_id: v.id } },
            body: { status: v.status, paused_until: v.paused_until ?? null },
          })
        ),
      onSuccess: refresh,
    }),
    confirm: useMutation({
      mutationFn: (id: string) =>
        unwrap(
          api.POST("/api/campaigns/{item_id}/confirm", {
            params: { path: { item_id: id } },
          })
        ),
      onSuccess: refresh,
    }),
  }
}

export function useRubricMutations() {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ck.rubrics })
    void qc.invalidateQueries({ queryKey: ck.campaigns })
  }
  return {
    create: useMutation({
      mutationFn: (v: { name: string; body: RubricBody }) =>
        unwrap(api.POST("/api/rubrics", { body: v })),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: (v: { id: string; name: string; body: RubricBody }) =>
        unwrap(
          api.PUT("/api/rubrics/{item_id}", {
            params: { path: { item_id: v.id } },
            body: { name: v.name, body: v.body },
          })
        ),
    }),
    activate: useMutation({
      mutationFn: (id: string) =>
        unwrap(
          api.POST("/api/rubrics/{item_id}/activate", {
            params: { path: { item_id: id } },
          })
        ),
      onSuccess: refresh,
    }),
    backtest: useMutation<
      BacktestResult,
      Error,
      { rubric_id: string; campaign_id: string; job_ids: string[] | null }
    >({ mutationFn: backtestRubric }),
  }
}

export async function saveSetting(key: string, value: unknown) {
  return unwrap(
    api.PUT("/api/settings/{key}", {
      params: { path: { key } },
      body: { value: value as never },
    })
  )
}

export async function setAlwaysAsk(
  e: {
    id: string
    name: string
    board_type: string
    board_slug: string
    priority?: number
    cooldown_days?: number | null
  },
  always_ask_first: boolean
) {
  return unwrap(
    api.PUT("/api/watched-employers/{item_id}", {
      params: { path: { item_id: e.id } },
      body: {
        name: e.name,
        board_type: e.board_type,
        board_slug: e.board_slug,
        priority: e.priority ?? 0,
        cooldown_days: e.cooldown_days ?? null,
        always_ask_first,
      },
    })
  )
}
