/** Bulk actions: typed against the generated contract (CONTRACTS "Wave 4 bulk additions"). */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]

export type PreviewIn = S["PreviewIn"]
export type PreviewOut = S["PreviewOut"]
export type OperationOut = S["OperationOut"]
export type ItemOut = S["ItemOut"]
export type BulkOptionsOut = S["BulkOptionsOut"]
export type ReasonGroup = S["ReasonGroupOut"]
export type BulkParams = S["ParamsIn"]
export type ViewSelection = S["ViewSelectionIn"]
export type BulkAction = PreviewIn["action"]
export type BulkSubject = PreviewIn["subject"]
export type ItemOutcome = ItemOut["outcome"]

/** What a bulk action runs on: the ticked ids, or everything a view matches (the server resolves it). */
export type BulkTarget = { ids: string[] } | { view: ViewSelection }

export const bulkKeys = {
  options: ["bulk", "options"] as const,
  operation: (id: string) => ["bulk", "operation", id] as const,
  items: (id: string, outcome?: string) =>
    ["bulk", "items", id, outcome ?? "all"] as const,
}

export const ACTION_LABEL: Record<BulkAction, string> = {
  tag: "Tag",
  untag: "Remove tag",
  skip: "Skip",
  snooze: "Snooze",
  move_stage: "Move stage",
  assign_campaign: "Assign to campaign",
  queue_tailoring: "Queue tailoring",
  send_for_approval: "Send for approval",
  approve_reviewed: "Approve all reviewed",
  archive: "Archive",
  recheck: "Recheck",
  export_csv: "Export CSV",
}

export const bulkPreview = (body: PreviewIn) =>
  unwrap(api.POST("/api/bulk/preview", { body }))

export const bulkRun = (operationId: string, confirmCount: number) =>
  unwrap(
    api.POST("/api/bulk/{operation_id}/run", {
      params: { path: { operation_id: operationId } },
      body: { confirm_count: confirmCount },
    })
  )

export const getOperation = (operationId: string) =>
  unwrap(
    api.GET("/api/bulk/{operation_id}", {
      params: { path: { operation_id: operationId } },
    })
  )

export const listItems = (operationId: string, outcome?: ItemOutcome) =>
  unwrap(
    api.GET("/api/bulk/{operation_id}/items", {
      params: {
        path: { operation_id: operationId },
        query: { outcome: outcome ?? undefined, limit: 200 },
      },
    })
  )

export const undoOperation = (operationId: string) =>
  unwrap(
    api.POST("/api/bulk/{operation_id}/undo", {
      params: { path: { operation_id: operationId } },
    })
  )

/** The export link; the file is served by the backend. */
export const csvUrl = (operationId: string) => `/api/bulk/${operationId}/csv`

export const bulkOptionsQuery = () =>
  queryOptions({
    queryKey: bulkKeys.options,
    queryFn: () => unwrap(api.GET("/api/bulk/options")),
    staleTime: 60_000,
  })

export const isRunning = (s: OperationOut["status"]) =>
  s === "queued" || s === "running"

/** Poll cadence while a run is going (fast in tests so a mock run finishes quickly). */
export const POLL_MS = import.meta.env.MODE === "test" ? 40 : 1000
