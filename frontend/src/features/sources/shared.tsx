import { useQuery } from "@tanstack/react-query"
import { meQuery } from "@/lib/api/endpoints"
import { cn } from "@/lib/utils"
import type { Source } from "./api"
import { HEALTH_LABEL } from "./words"

const DOT: Record<Source["health"]["status"], string> = {
  ok: "bg-good",
  degraded: "bg-warn",
  failing: "bg-danger",
  unknown: "bg-border-strong",
}

/** Coloured dot plus the status in words (never colour alone). */
export function HealthDot({
  status,
  className,
}: {
  status: Source["health"]["status"]
  className?: string
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        aria-hidden="true"
        className={cn("size-2 shrink-0 rounded-full", DOT[status])}
      />
      <span>{HEALTH_LABEL[status]}</span>
    </span>
  )
}

/** The owner's time zone (from their profile), else the browser's. */
export function useTimezone(): string {
  const me = useQuery(meQuery())
  return (
    me.data?.timezone ||
    Intl.DateTimeFormat().resolvedOptions().timeZone ||
    "UTC"
  )
}

/** Map of source id to name, for run results. */
export function sourceName(sources: Source[] | undefined, id: string): string {
  return sources?.find((s) => s.id === id)?.name ?? id
}
