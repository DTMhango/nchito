import { queryOptions } from "@tanstack/react-query"
import { z } from "zod"
import { pending, type CompareOut } from "../w3-pending-types"

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

export const compareQuery = (ids: string[]) =>
  queryOptions({
    queryKey: ["jobs", "compare", ...ids] as const,
    enabled: ids.length >= MIN_COMPARE,
    queryFn: () =>
      pending<CompareOut>(
        "GET",
        `/api/jobs/compare?ids=${encodeURIComponent(joinIds(ids))}`
      ),
  })
