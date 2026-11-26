/**
 * Matches endpoints, typed against the generated contract. Kept in the feature so the shared
 * `lib/api` hand-written schema does not have to change for this screen.
 */
import {
  infiniteQueryOptions,
  queryOptions,
  type QueryClient,
} from "@tanstack/react-query"
import { api, ApiError, unwrap } from "@/lib/api/client"
import type {
  AppliedMyselfIn,
  CampaignRuleIn,
  ConditionSet,
  CustomFacetIn,
  JobListOut,
  JobPatch,
  SavedViewIn,
  TagRuleIn,
} from "./types"

/** 501 means the backend has the route but not the behaviour yet. */
export const isNotBuilt = (e: unknown) =>
  e instanceof ApiError && (e.status === 501 || e.status === 404)

// The generated types describe the request body loosely for discriminated unions; the
// condition shapes in ./types are the contract's (CONTRACTS 5).
type AnyConditions = never

export type ListParams = {
  conditions: ConditionSet
  q?: string
  group_by?: string
  sort?: string
  limit?: number
}

const PAGE = 100

function listQuery(p: ListParams, cursor?: string, limit = PAGE) {
  return {
    conditions: JSON.stringify(p.conditions),
    q: p.q?.trim() || undefined,
    group_by: p.group_by || undefined,
    sort: p.sort || undefined,
    cursor,
    limit,
  }
}

export const listJobs = (p: ListParams, cursor?: string, limit?: number) =>
  unwrap(
    api.GET("/api/jobs", {
      params: { query: listQuery(p, cursor, limit ?? p.limit) },
    })
  ) as Promise<JobListOut>

export const getFacetCatalog = () => unwrap(api.GET("/api/jobs/facets"))
export const getJob = (id: string) =>
  unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }))
export const patchJob = (id: string, body: JobPatch) =>
  unwrap(
    api.PATCH("/api/jobs/{job_id}", { params: { path: { job_id: id } }, body })
  )
export const getWhy = (id: string) =>
  unwrap(
    api.GET("/api/jobs/{job_id}/why", { params: { path: { job_id: id } } })
  )
export const appliedMyself = (id: string, body: AppliedMyselfIn) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/applied-myself", {
      params: { path: { job_id: id } },
      body,
    })
  )
export const releaseHeld = (id: string, reason: string) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/release", {
      params: { path: { job_id: id } },
      body: { reason },
    })
  )
export { recheckJob } from "@/features/jobs/recheck"
export const fixEmployer = (id: string, canonical_employer: string) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/employer", {
      params: { path: { job_id: id } },
      body: { canonical_employer, remember_alias: true },
    })
  )

export const listAssessments = (jobId: string) =>
  unwrap(api.GET("/api/assessments", { params: { query: { job_id: jobId } } }))
export const rescore = (job_ids: string[], campaign_id: string) =>
  unwrap(
    api.POST("/api/assessments/rescore", { body: { job_ids, campaign_id } })
  )
export const getRubric = (id: string) =>
  unwrap(
    api.GET("/api/rubrics/{item_id}", { params: { path: { item_id: id } } })
  )
export const listFacts = () =>
  unwrap(api.GET("/api/kit/facts", { params: { query: { limit: 200 } } }))

// ---- saved views ----
export const listViews = () =>
  unwrap(api.GET("/api/views", { params: { query: { limit: 200 } } }))
export const createView = (body: SavedViewIn) =>
  unwrap(api.POST("/api/views", { body: body as never }))
export const updateView = (id: string, body: SavedViewIn) =>
  unwrap(
    api.PUT("/api/views/{item_id}", {
      params: { path: { item_id: id } },
      body: body as never,
    })
  )
export const deleteView = (id: string) =>
  unwrap(
    api.DELETE("/api/views/{item_id}", { params: { path: { item_id: id } } })
  )

// ---- tags ----
export const listTagRules = () =>
  unwrap(api.GET("/api/tag-rules", { params: { query: { limit: 200 } } }))
export const createTagRule = (body: TagRuleIn) =>
  unwrap(api.POST("/api/tag-rules", { body: body as never }))
export const deleteTagRule = (id: string) =>
  unwrap(
    api.DELETE("/api/tag-rules/{item_id}", {
      params: { path: { item_id: id } },
    })
  )
export const listCustomFacets = () =>
  unwrap(api.GET("/api/custom-facets", { params: { query: { limit: 200 } } }))
export const createCustomFacet = (body: CustomFacetIn) =>
  unwrap(api.POST("/api/custom-facets", { body }))
export const deleteCustomFacet = (id: string) =>
  unwrap(
    api.DELETE("/api/custom-facets/{item_id}", {
      params: { path: { item_id: id } },
    })
  )
export const backfillCustomFacet = (id: string, confirm: boolean) =>
  unwrap(
    api.POST("/api/custom-facets/{item_id}/backfill", {
      params: { path: { item_id: id }, query: { confirm } },
    })
  )

// ---- campaigns (for "Use as campaign rule" and rescoring) ----
export const listCampaigns = () =>
  unwrap(api.GET("/api/campaigns", { params: { query: { limit: 200 } } }))
export const previewCampaignRule = (
  campaignId: string,
  conditions: ConditionSet
) =>
  unwrap(
    api.POST("/api/campaigns/{item_id}/preview", {
      params: { path: { item_id: campaignId } },
      body: { conditions: conditions as AnyConditions, limit: 50 },
    })
  )
export const addCampaignRule = (campaignId: string, body: CampaignRuleIn) =>
  unwrap(
    api.POST("/api/campaigns/{item_id}/rules", {
      params: { path: { item_id: campaignId } },
      body,
    })
  )

// ---- query keys and options ----

export const mkeys = {
  all: ["matches"] as const,
  jobs: ["matches", "jobs"] as const,
  list: (p: ListParams) => ["matches", "jobs", "list", p] as const,
  count: (p: ListParams) => ["matches", "jobs", "count", p] as const,
  job: (id: string) => ["matches", "job", id] as const,
  why: (id: string) => ["matches", "why", id] as const,
  assessments: (id: string) => ["matches", "assessments", id] as const,
  facets: ["matches", "facets"] as const,
  views: ["matches", "views"] as const,
  tagRules: ["matches", "tag-rules"] as const,
  customFacets: ["matches", "custom-facets"] as const,
  campaigns: ["matches", "campaigns"] as const,
  rubric: (id: string) => ["matches", "rubric", id] as const,
  facts: ["matches", "facts"] as const,
}

export const jobsInfiniteQuery = (p: ListParams) =>
  infiniteQueryOptions({
    queryKey: mkeys.list(p),
    queryFn: ({ pageParam }) => listJobs(p, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: (prev) => prev,
  })

export const jobCountQuery = (p: ListParams) =>
  queryOptions({
    queryKey: mkeys.count(p),
    queryFn: () => listJobs(p, undefined, 1).then((r) => r.total ?? null),
    placeholderData: (prev) => prev,
  })

export const groupJobsQuery = (p: ListParams) =>
  queryOptions({
    queryKey: mkeys.list(p),
    queryFn: () => listJobs(p, undefined, 200),
  })

export const facetCatalogQuery = () =>
  queryOptions({
    queryKey: mkeys.facets,
    queryFn: getFacetCatalog,
    staleTime: 60_000,
  })
export const jobQuery = (id: string) =>
  queryOptions({ queryKey: mkeys.job(id), queryFn: () => getJob(id) })
export const whyQuery = (id: string) =>
  queryOptions({
    queryKey: mkeys.why(id),
    queryFn: () => getWhy(id),
    retry: false,
  })
export const assessmentsQuery = (id: string) =>
  queryOptions({
    queryKey: mkeys.assessments(id),
    queryFn: () => listAssessments(id),
  })
export const viewsQuery = () =>
  queryOptions({ queryKey: mkeys.views, queryFn: listViews })
export const tagRulesQuery = () =>
  queryOptions({ queryKey: mkeys.tagRules, queryFn: listTagRules })
export const customFacetsQuery = () =>
  queryOptions({ queryKey: mkeys.customFacets, queryFn: listCustomFacets })
export const campaignsQuery = () =>
  queryOptions({
    queryKey: mkeys.campaigns,
    queryFn: listCampaigns,
    staleTime: 60_000,
  })
export const rubricQuery = (id: string) =>
  queryOptions({
    queryKey: mkeys.rubric(id),
    queryFn: () => getRubric(id),
    staleTime: 5 * 60_000,
    retry: false,
  })
export const factsQuery = () =>
  queryOptions({
    queryKey: mkeys.facts,
    queryFn: listFacts,
    staleTime: 5 * 60_000,
    retry: false,
  })

/** After any change to jobs: lists, counts, views (live counts) and the open job. */
export function invalidateJobs(qc: QueryClient, jobId?: string) {
  void qc.invalidateQueries({ queryKey: mkeys.jobs })
  void qc.invalidateQueries({ queryKey: mkeys.views })
  void qc.invalidateQueries({ queryKey: mkeys.facets })
  if (jobId) {
    void qc.invalidateQueries({ queryKey: mkeys.job(jobId) })
    void qc.invalidateQueries({ queryKey: mkeys.why(jobId) })
  }
}
