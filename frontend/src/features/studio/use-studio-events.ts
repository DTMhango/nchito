import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { studioKeys } from "./api"

/**
 * Refresh the open application and its tailoring run when the server says they changed.
 * Events carry ids only (CONTRACTS 3), so the client refetches. Without EventSource (tests)
 * or while the stream is down, the run query's own polling covers it.
 */
export function useStudioEvents(
  applicationId: string,
  runId: string | undefined
) {
  const qc = useQueryClient()
  useEffect(() => {
    if (typeof EventSource === "undefined") return
    const es = new EventSource("/api/events", { withCredentials: true })
    const onEvent = (e: MessageEvent) => {
      let data: Record<string, unknown> = {}
      try {
        data =
          (JSON.parse(e.data) as { data?: Record<string, unknown> }).data ?? {}
      } catch {
        // A malformed frame only costs us the targeted refresh.
      }
      if (!data.application_id || data.application_id === applicationId)
        void qc.invalidateQueries({
          queryKey: studioKeys.application(applicationId),
        })
      if (runId && (!data.run_id || data.run_id === runId))
        void qc.invalidateQueries({ queryKey: studioKeys.run(runId) })
    }
    es.addEventListener("application.updated", onEvent)
    es.addEventListener("run.started", onEvent)
    es.addEventListener("run.finished", onEvent)
    return () => es.close()
  }, [applicationId, runId, qc])
}
