import { queryOptions } from "@tanstack/react-query"
import { pending, type PostingChanges } from "../w3-pending-types"

export const changeKeys = {
  changes: (jobId: string) => ["jobs", jobId, "changes"] as const,
}

export const changesQuery = (jobId: string) =>
  queryOptions({
    queryKey: changeKeys.changes(jobId),
    queryFn: () => pending<PostingChanges>("GET", `/api/jobs/${jobId}/changes`),
  })
