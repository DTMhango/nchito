/** Posting change alerts (`backend/app/api/routers/job_changes.py`), typed from the contract. */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

export type JobChanges = components["schemas"]["JobChangesOut"]
export type JobChange = components["schemas"]["JobChangeOut"]
export type FieldChange = components["schemas"]["FieldChange"]
export type ChangeKind = FieldChange["kind"]
export type Watch = components["schemas"]["WatchOut"]

export const changeKeys = {
  changes: (jobId: string) => ["jobs", jobId, "changes"] as const,
}

export const changesQuery = (jobId: string) =>
  queryOptions({
    queryKey: changeKeys.changes(jobId),
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/changes", {
          params: { path: { job_id: jobId } },
        })
      ),
  })

/** "Seen": clears the alert; pending actions the change opened stay. */
export const acknowledgeChange = (changeId: string) =>
  unwrap(
    api.POST("/api/job-changes/{change_id}/acknowledge", {
      params: { path: { change_id: changeId } },
    })
  )
