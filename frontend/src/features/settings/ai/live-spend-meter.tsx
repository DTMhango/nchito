import { useEffect } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { SpendMeter } from "@/components/spend-meter"
import { aiKeys, spendMeterQuery } from "./api"

const SPEND_EVENTS = ["spend.updated", "budget.warning", "budget.exhausted"]

/**
 * Refetch spend when the ledger announces a change on `/api/events` (one stream per tab).
 * Skipped where EventSource is missing (tests) or in the mock backend.
 */
export function useSpendEvents() {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (typeof EventSource === "undefined" || import.meta.env.VITE_MOCK) return
    const source = new EventSource("/api/events", { withCredentials: true })
    const refresh = () =>
      void queryClient.invalidateQueries({ queryKey: aiKeys.spend })
    for (const name of SPEND_EVENTS) source.addEventListener(name, refresh)
    return () => source.close()
  }, [queryClient])
}

/** The shell's spend meter, fed by `GET /api/ai/spend/meter` and kept live by SSE. */
export function LiveSpendMeter({ className }: { className?: string }) {
  useSpendEvents()
  const { data } = useQuery(spendMeterQuery())
  return (
    <SpendMeter
      spentMinor={data?.month_to_date_minor ?? 0}
      capMinor={data?.cap_minor ?? null}
      currency={data?.currency ?? "USD"}
      className={className}
    />
  )
}
