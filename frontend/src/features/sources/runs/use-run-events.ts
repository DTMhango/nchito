import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { sourceKeys } from "../api"

/**
 * Listen to the server-sent event stream and refresh run data when a run starts or
 * finishes. Events carry ids only (CONTRACTS section 3), so the client refetches. Where
 * there is no EventSource (tests) or the stream drops, the queries' own polling covers it.
 */
export function useRunEvents(enabled = true) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return
    const es = new EventSource("/api/events", { withCredentials: true })
    const refresh = (e: MessageEvent) => {
      qc.invalidateQueries({ queryKey: sourceKeys.runs })
      try {
        const id = (JSON.parse(e.data) as { data?: { run_id?: string } }).data
          ?.run_id
        if (id) qc.invalidateQueries({ queryKey: sourceKeys.run(id) })
      } catch {
        // A malformed frame only costs us the targeted refresh.
      }
    }
    es.addEventListener("run.started", refresh)
    es.addEventListener("run.finished", refresh)
    return () => es.close()
  }, [enabled, qc])
}
