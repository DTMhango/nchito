/**
 * Typed calls for the job page, against the generated contract (`schema.d.ts`).
 * The shared client is cast to the generated `paths`; nothing else has to change.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

const gen = api
type S = components["schemas"]

export type JobDetail = S["JobDetail"]
export type JobSummary = S["JobSummary"]
export type JobPatch = S["JobPatch"]
export type WhyOut = S["WhyOut"]
export type AssessmentOut = S["AssessmentOut"]
export type ApplicationDetail = S["ApplicationDetail"]
export type TimelineEvent = S["TimelineEvent"]
export type ContactOut = S["ContactOut"]
export type ContactIn = S["ContactIn"]
export type PendingAction = S["PendingActionOut"]
export type AuditEvent = S["AuditEventOut"]
export type JobFacets = S["JobFacets"]
export type MailThread = S["MailThreadOut"]
export type ApplyEmailIn = S["ApplyEmailIn"]
export type ApplyEmailOut = S["ApplyEmailOut"]
export type ApplyChannelCandidate = S["ApplyChannelCandidate"]
export type DispatchOut = S["DispatchOut"]

export const jobKeys = {
  job: (id: string) => ["jobs", id] as const,
  why: (id: string) => ["jobs", id, "why"] as const,
  assessments: (id: string) => ["jobs", id, "assessments"] as const,
  application: (id: string) => ["applications", id] as const,
  timeline: (id: string) => ["applications", id, "timeline"] as const,
  mail: (id: string) => ["applications", id, "mail-threads"] as const,
  pending: ["pending-actions"] as const,
  audit: (id: string) => ["jobs", id, "audit"] as const,
  contacts: ["contacts"] as const,
  search: (q: string) => ["jobs", "search", q] as const,
  employerPeers: (employer: string) => ["jobs", "peers", employer] as const,
}

export const jobQuery = (id: string) =>
  queryOptions({
    queryKey: jobKeys.job(id),
    queryFn: () =>
      unwrap(
        gen.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })
      ),
    retry: false,
  })

export const whyQuery = (id: string, enabled: boolean) =>
  queryOptions({
    queryKey: jobKeys.why(id),
    queryFn: () =>
      unwrap(
        gen.GET("/api/jobs/{job_id}/why", { params: { path: { job_id: id } } })
      ),
    enabled,
  })

export const assessmentsQuery = (jobId: string) =>
  queryOptions({
    queryKey: jobKeys.assessments(jobId),
    queryFn: async () =>
      (
        await unwrap(
          gen.GET("/api/assessments", { params: { query: { job_id: jobId } } })
        )
      ).items,
  })

export const applicationQuery = (id: string | null | undefined) =>
  queryOptions({
    queryKey: jobKeys.application(id ?? "none"),
    enabled: !!id,
    queryFn: () =>
      unwrap(
        gen.GET("/api/applications/{application_id}", {
          params: { path: { application_id: id! } },
        })
      ),
  })

export const timelineQuery = (appId: string | null | undefined) =>
  queryOptions({
    queryKey: jobKeys.timeline(appId ?? "none"),
    enabled: !!appId,
    queryFn: () =>
      unwrap(
        gen.GET("/api/applications/{application_id}/timeline", {
          params: { path: { application_id: appId! } },
        })
      ),
  })

/** Mail threads linked to one application, newest first (CONTRACTS, wave 2 email). */
export const mailThreadsQuery = (appId: string | null | undefined) =>
  queryOptions({
    queryKey: jobKeys.mail(appId ?? "none"),
    enabled: !!appId,
    queryFn: async () =>
      (
        await unwrap(
          gen.GET("/api/mail-threads", {
            params: { query: { application_id: appId!, limit: 100 } },
          })
        )
      ).items,
  })

export const pendingActionsQuery = () =>
  queryOptions({
    queryKey: jobKeys.pending,
    queryFn: async () =>
      (
        await unwrap(
          gen.GET("/api/pending-actions", {
            params: { query: { status: "open" } },
          })
        )
      ).items,
  })

export const jobAuditQuery = (id: string) =>
  queryOptions({
    queryKey: jobKeys.audit(id),
    queryFn: async () =>
      (
        await unwrap(
          gen.GET("/api/audit", {
            params: {
              query: { subject_type: "job", subject_id: id, limit: 50 },
            },
          })
        )
      ).items,
  })

export const contactsQuery = () =>
  queryOptions({
    queryKey: jobKeys.contacts,
    queryFn: async () => (await unwrap(gen.GET("/api/contacts"))).items,
  })

/** Search roles by text (merge picker, wrong-employer picker, conflict winner lookup). */
export const searchJobsQuery = (q: string, enabled = true) =>
  queryOptions({
    queryKey: jobKeys.search(q),
    enabled: enabled && q.trim().length > 0,
    queryFn: async () =>
      (
        await unwrap(
          gen.GET("/api/jobs", {
            params: { query: { q: q.trim(), limit: 20 } },
          })
        )
      ).items,
  })

// ---- writes ----
const path = (job_id: string) => ({ params: { path: { job_id } } })

export const patchJob = (id: string, body: JobPatch) =>
  unwrap(gen.PATCH("/api/jobs/{job_id}", { ...path(id), body }))
export { recheckJob } from "./recheck"
export const releaseJob = (id: string, reason: string) =>
  unwrap(
    gen.POST("/api/jobs/{job_id}/release", { ...path(id), body: { reason } })
  )
export const mergeJobs = (id: string, duplicate_ids: string[]) =>
  unwrap(
    gen.POST("/api/jobs/{job_id}/merge", {
      ...path(id),
      body: { duplicate_ids },
    })
  )
export const splitJob = (id: string, sighting_urls: string[]) =>
  unwrap(
    gen.POST("/api/jobs/{job_id}/split", {
      ...path(id),
      body: { sighting_urls },
    })
  )
export const fixEmployer = (
  id: string,
  canonical_employer: string,
  remember_alias: boolean
) =>
  unwrap(
    gen.POST("/api/jobs/{job_id}/employer", {
      ...path(id),
      body: { canonical_employer, remember_alias },
    })
  )
/**
 * Set, correct, confirm or clear where this role's application email goes. `address` null goes
 * back to the posting's own address; `confirmed: false` withdraws a confirmation. 422
 * `{code: invalid_address | no_address, reason}`.
 */
export const setApplyEmail = (id: string, body: ApplyEmailIn) =>
  unwrap(gen.PUT("/api/jobs/{job_id}/apply-email", { ...path(id), body }))
export const appliedMyself = (id: string, body: S["AppliedMyselfIn"]) =>
  unwrap(gen.POST("/api/jobs/{job_id}/applied-myself", { ...path(id), body }))

export const overrideAssessment = (
  id: string,
  score: number | null,
  reason: string
) =>
  unwrap(
    gen.POST("/api/assessments/{assessment_id}/override", {
      params: { path: { assessment_id: id } },
      body: { score, reason },
    })
  )

export const createContact = (body: ContactIn) =>
  unwrap(gen.POST("/api/contacts", { body }))
export const updateContact = (id: string, body: ContactIn) =>
  unwrap(
    gen.PUT("/api/contacts/{item_id}", {
      params: { path: { item_id: id } },
      body,
    })
  )
export const deleteContact = (id: string) =>
  unwrap(
    gen.DELETE("/api/contacts/{item_id}", { params: { path: { item_id: id } } })
  )
