/**
 * Applications, pending actions and Today: typed against the generated contract
 * (`schema.d.ts`, from docs/openapi.json). The wave 0 hand-written `paths` does not cover
 * these endpoints yet, so this feature keeps its own client until the swap in `types.ts`.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, toFormData, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

export const gen = api

type Schemas = components["schemas"]
export type ApplicationSummary = Schemas["ApplicationSummary"]
export type ApplicationDetail = Schemas["ApplicationDetail"]
export type TimelineEvent = Schemas["TimelineEvent"]
export type PendingAction = Schemas["PendingActionOut"]
export type DecisionGroup = Schemas["DecisionGroup"]
export type TodayOut = Schemas["TodayOut"]
export type JobSummary = Schemas["JobSummary"]
export type CampaignOut = Schemas["CampaignOut"]
export type AnswerScope = NonNullable<Schemas["ResolveIn"]["answer_scope"]>
export type ResolveIn = Schemas["ResolveIn"]
export type ApplicationPatch = Schemas["ApplicationPatch"]
export type Channel = NonNullable<ApplicationSummary["channel"]>
export type ApiStage = ApplicationSummary["stage"]

export const appKeys = {
  list: ["applications", "list"] as const,
  detail: (id: string) => ["applications", "detail", id] as const,
  timeline: (id: string) => ["applications", "timeline", id] as const,
  decisions: ["pending-actions", "decisions"] as const,
  pending: ["pending-actions", "list"] as const,
  today: ["today"] as const,
  topMatches: ["today", "top-matches"] as const,
  campaigns: ["campaigns", "names"] as const,
}

export const listApplications = () =>
  unwrap(
    gen.GET("/api/applications", {
      params: { query: { limit: 200, hide_snoozed: true } },
    })
  )
/** Keep the files the owner sent after "I applied myself" (their record, not evidence). */
export const attachFiles = (id: string, files: File[]) =>
  unwrap(
    gen.POST("/api/applications/{application_id}/files", {
      params: { path: { application_id: id } },
      // Multipart: the generated body types each file as a string; the Files go as they are.
      body: { files: files as unknown as string[] },
      bodySerializer: toFormData,
    })
  )
export const getApplication = (id: string) =>
  unwrap(
    gen.GET("/api/applications/{application_id}", {
      params: { path: { application_id: id } },
    })
  )
export const getTimeline = (id: string) =>
  unwrap(
    gen.GET("/api/applications/{application_id}/timeline", {
      params: { path: { application_id: id } },
    })
  )
export const changeStage = (id: string, stage: ApiStage, note?: string) =>
  unwrap(
    gen.POST("/api/applications/{application_id}/stage", {
      params: { path: { application_id: id } },
      body: { stage, note },
    })
  )
export const patchApplication = (id: string, body: ApplicationPatch) =>
  unwrap(
    gen.PATCH("/api/applications/{application_id}", {
      params: { path: { application_id: id } },
      body,
    })
  )
export const markSubmitted = (
  id: string,
  body: { reference?: string | null; note?: string | null }
) =>
  unwrap(
    gen.POST("/api/applications/{application_id}/mark-submitted", {
      params: { path: { application_id: id } },
      body,
    })
  )

export const getToday = () => unwrap(gen.GET("/api/today"))
export const getDecisions = () =>
  unwrap(gen.GET("/api/pending-actions/decisions"))
export const listPendingActions = () =>
  unwrap(
    gen.GET("/api/pending-actions", { params: { query: { status: "open" } } })
  )
export const resolveAction = (id: string, body: ResolveIn) =>
  unwrap(
    gen.POST("/api/pending-actions/{action_id}/resolve", {
      params: { path: { action_id: id } },
      body,
    })
  )
export const listNewJobs = () =>
  unwrap(
    gen.GET("/api/jobs", { params: { query: { triage: "new", limit: 5 } } })
  )
export const listCampaigns = () => unwrap(gen.GET("/api/campaigns"))

export const applicationsQuery = () =>
  queryOptions({ queryKey: appKeys.list, queryFn: listApplications })
export const timelineQuery = (id: string) =>
  queryOptions({
    queryKey: appKeys.timeline(id),
    queryFn: () => getTimeline(id),
  })
export const todayQuery = () =>
  queryOptions({ queryKey: appKeys.today, queryFn: getToday })
export const decisionsQuery = () =>
  queryOptions({ queryKey: appKeys.decisions, queryFn: getDecisions })
export const pendingQuery = () =>
  queryOptions({ queryKey: appKeys.pending, queryFn: listPendingActions })
export const topMatchesQuery = () =>
  queryOptions({ queryKey: appKeys.topMatches, queryFn: listNewJobs })
export const campaignsQuery = () =>
  queryOptions({
    queryKey: appKeys.campaigns,
    queryFn: listCampaigns,
    staleTime: 5 * 60_000,
  })
