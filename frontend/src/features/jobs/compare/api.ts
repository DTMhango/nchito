import { queryOptions } from "@tanstack/react-query"
import { z } from "zod"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

export type CompareOut = components["schemas"]["CompareOut"]
export type CompareJob = components["schemas"]["CompareJob"]
export type CompareRow = components["schemas"]["CompareRow"]
export type CompareCell = components["schemas"]["CompareCell"]

export const MIN_COMPARE = 2
export const MAX_COMPARE = 4

/** `?ids=a,b,c` (kept as one string so the link is short and shareable). */
export const compareSearchSchema = z.object({
  ids: z.string().catch("").default(""),
})
export type CompareSearch = z.infer<typeof compareSearchSchema>

export const parseIds = (ids: string): string[] =>
  [
    ...new Set(
      ids
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    ),
  ].slice(0, MAX_COMPARE)
export const joinIds = (ids: string[]) => ids.join(",")

/** `GET /api/jobs/compare/{a,b,c}` (2 to 4 ids); `campaignId` picks whose assessment is shown. */
export const compareQuery = (ids: string[], campaignId?: string | null) =>
  queryOptions({
    queryKey: ["jobs", "compare", ...ids, campaignId ?? null] as const,
    enabled: ids.length >= MIN_COMPARE,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/compare/{job_ids}", {
          params: {
            path: { job_ids: joinIds(ids) },
            query: campaignId ? { campaign_id: campaignId } : undefined,
          },
        })
      ),
  })
