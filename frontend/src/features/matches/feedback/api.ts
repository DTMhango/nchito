/** Thumbs on a role: typed from the generated contract (schema.d.ts). */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"

export type FeedbackIn = Schemas["FeedbackIn"]
export type FeedbackOut = Schemas["FeedbackOut"]
export type FeedbackReason = FeedbackOut["reasons"][number]
export type Verdict = FeedbackOut["verdict"]

export const fk = {
  job: (jobId: string) => ["feedback", jobId] as const,
}

export const feedbackQuery = (jobId: string) =>
  queryOptions({
    queryKey: fk.job(jobId),
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/feedback", {
          params: { path: { job_id: jobId } },
        })
      ),
  })

export const putFeedback = (jobId: string, body: FeedbackIn) =>
  unwrap(
    api.PUT("/api/jobs/{job_id}/feedback", {
      params: { path: { job_id: jobId } },
      body,
    })
  )

export const withdrawFeedback = (jobId: string, campaignId: string | null) =>
  unwrap(
    api.DELETE("/api/jobs/{job_id}/feedback", {
      params: {
        path: { job_id: jobId },
        query: campaignId ? { campaign_id: campaignId } : {},
      },
    })
  )
