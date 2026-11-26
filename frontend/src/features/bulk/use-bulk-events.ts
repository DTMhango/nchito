import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { bulkKeys, type OperationOut } from "./api"

/**
 * Live progress for one bulk run from the server-sent stream (`bulk.progress`, `bulk.finished`;
 * CONTRACTS "Wave 4 bulk additions"). Events carry ids and counts only. Where there is no
 * EventSource (tests) or the stream drops, the operation query's polling covers it.
 */
export function useBulkEvents(operationId: string | null) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!operationId || typeof EventSource === "undefined") return
    const es = new EventSource("/api/events", { withCredentials: true })
    const parse = (e: MessageEvent) => {
      try {
        const d = (JSON.parse(e.data) as { data?: Record<string, unknown> })
          .data
        return d?.operation_id === operationId ? d : null
      } catch {
        return null
      }
    }
    es.addEventListener("bulk.progress", (e) => {
      const d = parse(e as MessageEvent)
      if (d && typeof d.done === "number")
        qc.setQueryData<OperationOut>(
          bulkKeys.operation(operationId),
          (old) => old && { ...old, done: d.done as number }
        )
    })
    es.addEventListener("bulk.finished", (e) => {
      if (parse(e as MessageEvent))
        void qc.invalidateQueries({ queryKey: bulkKeys.operation(operationId) })
    })
    return () => es.close()
  }, [operationId, qc])
}
