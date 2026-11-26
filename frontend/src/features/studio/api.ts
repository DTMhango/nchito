/**
 * Studio calls, typed against the generated contract (`schema.d.ts`). Components import from
 * here, never from openapi-fetch. Kit lists (facts, guardrails, templates, answers) come
 * through the Kit's own query options so both screens share one cache.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"

export type ApplicationDetail = Schemas["ApplicationDetail"]
export type ApplicationSummary = Schemas["ApplicationSummary"]
export type Spec = Schemas["ApplicationSpec-Output"]
export type SpecInput = Schemas["ApplicationSpec-Input"]
export type SpecItem = Schemas["SpecItem"]
export type SpecExperience = Schemas["SpecExperience"]
export type RequirementMatch = Schemas["RequirementMatch"]
export type CheckResult = Schemas["CheckResult"]
export type JobDetail = Schemas["JobDetail"]
export type Requirement = Schemas["Requirement"]
export type RunOut = Schemas["RunOut"]
export type PacketOut = Schemas["PacketOut"]
export type PacketAnswer = Schemas["PacketAnswer"]
export type PendingAction = Schemas["PendingActionOut"]
export type FactOut = Schemas["FactOut"]
export type FactIn = Schemas["FactIn"]
export type GuardrailOut = Schemas["GuardrailOut"]
export type TemplateOut = Schemas["TemplateOut"]
export type AnswerOut = Schemas["AnswerOut"]
export type ExperienceOut = Schemas["ExperienceOut"]
export type DocKind = "cv" | "letter" | "answers"
export type DocFormat = "pdf" | "docx"

export const studioKeys = {
  all: ["studio"] as const,
  application: (id: string) => ["studio", "application", id] as const,
  job: (id: string) => ["studio", "job", id] as const,
  run: (id: string) => ["studio", "run", id] as const,
  packets: (id: string) => ["studio", "packets", id] as const,
  pending: ["studio", "pending-actions"] as const,
  picker: ["studio", "picker"] as const,
}

const path = (id: string) => ({ params: { path: { application_id: id } } })

export const applicationQuery = (id: string) =>
  queryOptions({
    queryKey: studioKeys.application(id),
    queryFn: () =>
      unwrap(api.GET("/api/applications/{application_id}", path(id))),
    retry: false,
  })

export const jobQuery = (id: string | undefined) =>
  queryOptions({
    queryKey: studioKeys.job(id ?? "none"),
    enabled: !!id,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id! } } })
      ),
  })

/** Applications that can be opened in the Studio (drafting or waiting for approval). */
export const STUDIO_STAGES: ApplicationSummary["stage"][] = [
  "shortlisted",
  "tailoring",
  "ready",
]
export const pickerQuery = () =>
  queryOptions({
    queryKey: studioKeys.picker,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/applications", {
            params: { query: { limit: 200, hide_snoozed: true } },
          })
        )
      ).items.filter((a) => STUDIO_STAGES.includes(a.stage)),
  })

/** While a run is queued or running, poll it (the SSE stream also nudges a refetch). */
export const ACTIVE_RUN = new Set<RunOut["status"]>(["queued", "running"])
export const runQuery = (id: string | undefined, pollMs: number) =>
  queryOptions({
    queryKey: studioKeys.run(id ?? "none"),
    enabled: !!id,
    queryFn: () =>
      unwrap(
        api.GET("/api/runs/{run_id}", { params: { path: { run_id: id! } } })
      ),
    refetchInterval: (q) =>
      q.state.data && ACTIVE_RUN.has(q.state.data.status) ? pollMs : false,
  })

export const packetsQuery = (id: string) =>
  queryOptions({
    queryKey: studioKeys.packets(id),
    queryFn: () =>
      unwrap(api.GET("/api/applications/{application_id}/packets", path(id))),
  })

export const pendingQuery = () =>
  queryOptions({
    queryKey: studioKeys.pending,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/pending-actions", {
            params: { query: { status: "open" } },
          })
        )
      ).items,
  })

export const startTailoring = (id: string) =>
  unwrap(api.POST("/api/applications/{application_id}/tailor", path(id)))

export const saveSpec = (id: string, spec: SpecInput) =>
  unwrap(
    api.PUT("/api/applications/{application_id}/spec", {
      ...path(id),
      body: { spec },
    })
  )

export const runChecks = (id: string) =>
  unwrap(api.POST("/api/applications/{application_id}/check", path(id)))

export const waiveOnce = (
  guardrailId: string,
  applicationId: string,
  reason: string
) =>
  unwrap(
    api.POST("/api/kit/guardrails/{item_id}/waivers", {
      params: { path: { item_id: guardrailId } },
      body: { application_id: applicationId, reason },
    })
  )

export const sendForApproval = (id: string) =>
  unwrap(
    api.POST("/api/applications/{application_id}/stage", {
      ...path(id),
      body: { stage: "ready", note: "Sent for approval from the Studio" },
    })
  )

export const createDraftFact = (body: FactIn) =>
  unwrap(api.POST("/api/kit/facts", { body }))

/** The rendered file. A plain link, so the browser downloads it with the session cookie. */
export const documentUrl = (id: string, kind: DocKind, fmt: DocFormat) =>
  `/api/applications/${encodeURIComponent(id)}/documents/${kind}?fmt=${fmt}`
