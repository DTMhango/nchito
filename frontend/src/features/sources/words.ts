import { formatCost, microsOf } from "@/lib/cost"
import type { ChipTone } from "@/components/chip"
import type { Source, RunKind, RunStatus } from "./api"
import { JOBSPY_INSTALL } from "./connectors"

/** Plain-words labels, kept in one place so wording is easy to change. */

export const ACCESS_LABEL: Record<Source["access"], string> = {
  api: "Official API",
  feed: "Feed",
  html: "Web page",
  agent: "Browser agent",
  email: "Alert emails",
}

export const ACTION_LABEL: Record<
  Source["permitted_actions"] extends (infer A)[] | undefined
    ? NonNullable<A>
    : never,
  { label: string; hint: string }
> = {
  search: { label: "Search for roles", hint: "Look for new postings." },
  fetch: {
    label: "Read a posting",
    hint: "Open a single posting to read it in full.",
  },
  check_open: {
    label: "Check a role is still open",
    hint: "Before tailoring and before sending.",
  },
  apply_email: {
    label: "Send applications by email",
    hint: "Only where the posting asks for an email application.",
  },
  apply_browser: {
    label: "Apply through the browser",
    hint: "Needs your PC runner and your approval rules.",
  },
}

export const HEALTH_LABEL = {
  ok: "Working",
  degraded: "Slow or partial",
  failing: "Failing",
  unknown: "Not checked yet",
} as const

export const HEALTH_TONE: Record<Source["health"]["status"], ChipTone> = {
  ok: "good",
  degraded: "warn",
  failing: "danger",
  unknown: "neutral",
}

export const KIND_LABEL: Record<RunKind, string> = {
  sweep: "Sweep",
  rescore: "Re-score",
  expiry_check: "Expiry check",
  digest: "Digest",
  backup: "Backup",
  retention: "Retention",
  tailoring: "Tailoring",
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Waiting to start",
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  partial: "Done with problems",
  cancelled: "Cancelled",
  skipped: "Skipped",
  paused: "Paused: monthly budget reached",
}

export const STATUS_TONE: Record<RunStatus, ChipTone> = {
  queued: "neutral",
  running: "info",
  succeeded: "good",
  failed: "danger",
  partial: "warn",
  cancelled: "neutral",
  skipped: "neutral",
  paused: "warn",
}

export const TRIGGER_LABEL: Record<string, string> = {
  schedule: "On schedule",
  manual: "You started it",
  api: "From the API",
  missed: "Catch-up for a missed run",
}
export const triggerLabel = (t: string) =>
  TRIGGER_LABEL[t] ?? t.replace(/_/g, " ")

/**
 * Turn a raw connector error into something an owner can act on. Unknown text is shown as
 * given, so nothing is hidden.
 */
export function plainError(raw: string | null | undefined): string {
  if (!raw) return ""
  const t = raw.toLowerCase()
  if (/not installed/.test(t))
    return `JobSpy is not installed on this server. Whoever runs it adds the optional extra (${JOBSPY_INSTALL}).`
  if (/switched off/.test(t))
    return "JobSpy is switched off. Turn it on under Discovery settings."
  if (/no api key/.test(t))
    return "Web search has no key. Add a Search API connection in Settings, Connections."
  if (/\b429\b|rate.?limit|too many requests/.test(t))
    return "The site asked us to slow down. The next run will go slower."
  if (/\b401\b|\b403\b|forbidden|unauthori[sz]ed/.test(t))
    return "The site refused access. It may need a key, or it blocks automated reads."
  if (/\b404\b|not found/.test(t))
    return "That board address no longer exists. Check the employer's careers link."
  if (/timeout|timed out|etimedout/.test(t))
    return "The site took too long to answer. It is often temporary."
  if (/dns|enotfound|getaddrinfo|connection refused|econn/.test(t))
    return "We could not reach the site. It may be down."
  if (/\b5\d\d\b|server error|bad gateway/.test(t))
    return "The site had a problem on its side. It is usually temporary."
  if (/parse|json|schema|unexpected|xml/.test(t))
    return "The site answered in a shape we did not expect. It may have changed."
  return raw
}

/** "3 min ago", "yesterday", or a date for older times. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "Never"
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000)
  if (s < 60) return "Just now"
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 172800) return "Yesterday"
  return `${Math.floor(s / 86400)} days ago`
}

export function duration(
  start: string | null,
  end: string | null,
  now = Date.now()
): string {
  if (!start) return "-"
  const ms = (end ? new Date(end).getTime() : now) - new Date(start).getTime()
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

/** Money in minor units (US cents); the AI ledger bills in dollars. */
/** A run's cost: "No cost" at zero, else the formatted amount (micros when present). */
export const cost = (run: object) => {
  const m = microsOf(run, "cost") ?? 0
  return m === 0 ? "No cost" : formatCost(m)
}
