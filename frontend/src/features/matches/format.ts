import type { JobSummary, PayOut } from "./types"
import { valueLabel } from "./filters"

/** A Matches list row: the contract's JobSummary (work_model, remote_scope, source, pay_state, conflict). */
export type ListJob = JobSummary

const compact = (n: number) =>
  new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n)

const PERIOD: Record<string, string> = {
  year: "/yr",
  month: "/mo",
  week: "/wk",
  day: "/day",
  hour: "/hr",
}

/** "ZMW 30K to 42K /yr"; pay figures are in minor units. */
export function payBand(pay: PayOut): string | null {
  if (pay.state === "not_stated") return null
  const min = pay.min_minor != null ? pay.min_minor / 100 : null
  const max = pay.max_minor != null ? pay.max_minor / 100 : null
  if (min == null && max == null) return null
  const cur = pay.currency ? `${pay.currency} ` : ""
  const range =
    min != null && max != null && min !== max
      ? `${compact(min)}–${compact(max)}`
      : compact((min ?? max) as number)
  return `${cur}${range}${pay.period ? ` ${PERIOD[pay.period] ?? `/${pay.period}`}` : ""}`
}

/** "2d", "3w", "today". */
export function age(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return ""
  const days = Math.floor((now - Date.parse(iso)) / 86_400_000)
  if (days <= 0) return "today"
  if (days < 14) return `${days}d`
  if (days < 60) return `${Math.floor(days / 7)}w`
  return `${Math.floor(days / 30)}mo`
}

export function placeLabel(loc: JobSummary["location"]): string {
  if (loc.raw) return loc.raw
  return (
    [loc.city, loc.country].filter(Boolean).join(", ") || "Location not stated"
  )
}

export function workModelLabel(v: string | null | undefined): string | null {
  if (!v || v === "not_stated") return null
  return valueLabel(v)
}

export function deadlineLabel(d: JobSummary["deadline"]): string {
  if (d.state === "dated" && d.on)
    return `Closes ${new Date(d.on).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
  if (d.state === "open_until_filled") return "Open until filled"
  return "No deadline stated"
}

const plural = (n: number, one: string, many = `${one}s`) =>
  `${n} ${n === 1 ? one : many}`
export { plural }
