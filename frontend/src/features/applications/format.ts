/** Date helpers in the owner's time zone. */

const MS_DAY = 86_400_000

export function daysSince(iso: string, now = new Date()): number {
  return Math.max(
    0,
    Math.floor((now.getTime() - new Date(iso).getTime()) / MS_DAY)
  )
}

/** "3 Dec" from a date or date-time, in the given zone. */
export function shortDate(value: string, timeZone?: string): string {
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(`${value}T12:00:00Z`)
    : new Date(value)
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: /^\d{4}-\d{2}-\d{2}$/.test(value) ? "UTC" : timeZone,
  }).format(d)
}

/** Whole days from now to a due date (negative when past), calendar-based in the zone. */
export function daysUntil(value: string, timeZone?: string, now = new Date()) {
  const ymd = (d: Date) =>
    new Intl.DateTimeFormat("en-CA", { timeZone }).format(d) // YYYY-MM-DD
  const target = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? value
    : ymd(new Date(value))
  return Math.round(
    (Date.parse(`${target}T00:00:00Z`) - Date.parse(`${ymd(now)}T00:00:00Z`)) /
      MS_DAY
  )
}

export function dueLabel(days: number): string {
  if (days < 0) return days === -1 ? "1 day overdue" : `${-days} days overdue`
  if (days === 0) return "today"
  if (days === 1) return "tomorrow"
  return `in ${days} days`
}

/** Today's date (YYYY-MM-DD) in the zone. */
export const todayIn = (timeZone?: string, now = new Date()) =>
  new Intl.DateTimeFormat("en-CA", { timeZone }).format(now)
