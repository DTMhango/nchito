import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"

/** Events (CONTRACTS 3) that change what Today, the bell or the board show. */
export const LIVE_EVENTS = [
  "pending_action.created",
  "pending_action.resolved",
  "application.updated",
  "dispatch.updated",
  "notification.created",
  "job.created",
  "job.updated",
  "run.started",
  "run.finished",
] as const

const LIVE_KEYS = [["today"], ["pending-actions"], ["applications"]] as const

/**
 * Listens on the existing SSE stream and refetches the affected queries. Payloads carry ids
 * only, so the client always refetches. EventSource reconnects by itself (the server sends
 * `retry: 5000`).
 */
export function useLiveUpdates(enabled = true) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return
    const source = new EventSource("/api/events", { withCredentials: true })
    let timer: ReturnType<typeof setTimeout> | undefined
    const refresh = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        for (const queryKey of LIVE_KEYS)
          void qc.invalidateQueries({ queryKey: [...queryKey] })
      }, 250)
    }
    for (const name of LIVE_EVENTS) source.addEventListener(name, refresh)
    return () => {
      clearTimeout(timer)
      source.close()
    }
  }, [enabled, qc])
}
