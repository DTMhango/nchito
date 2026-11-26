/** Runner and token wording and rules. No I/O. */
import { isApiError } from "@/lib/api/client"
import type { RunnerStatus, Scope, Token } from "./api"

export const SCOPES: { value: Scope; label: string; hint: string }[] = [
  {
    value: "gateway:tasks",
    label: "Take tasks",
    hint: "Claim the next task, save checkpoints, raise blockers and report results.",
  },
  {
    value: "gateway:packets",
    label: "Read application packets",
    hint: "Get the field values and files for one application at a time.",
  },
  {
    value: "gateway:permits",
    label: "Ask for submit permits",
    hint: "Ask to press Submit. Each permit is for one application and one claimed task, and works once.",
  },
  {
    value: "gateway:sweep",
    label: "Report jobs found",
    hint: "For sweep tasks: send back the postings it visited.",
  },
]

export const scopeLabel = (s: string) =>
  SCOPES.find((x) => x.value === s)?.label ?? s

export const KIND_LABEL = { pc: "Your PC", server: "Server" } as const

/** What the owner sees when a runner is not online: how long since it was last seen. */
export function seenText(iso: string | null, now = Date.now()): string {
  if (!iso) return "never seen"
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000))
  if (mins < 2) return "seen just now"
  if (mins < 60) return `seen ${mins} minutes ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `seen ${hours} hour${hours === 1 ? "" : "s"} ago`
  return `seen ${Math.round(hours / 24)} days ago`
}

/** One row for a runner: its live status joined with its token (suspension, scopes). */
export type RunnerRow = {
  status: RunnerStatus
  token: Token | null
  /** Offline runners are "stale": highlighted so a stopped runner is noticed. */
  stale: boolean
  /** Suspended by the server (a submission without a permit, or by hand). */
  paused: boolean
  pausedReason: string | null
}

export function runnerRows(
  runners: RunnerStatus[],
  tokens: Token[]
): RunnerRow[] {
  return runners.map((status) => {
    const token = tokens.find((t) => t.id === status.token_id) ?? null
    const paused = !!token?.suspended_at && !token.revoked_at
    return {
      status,
      token,
      stale: !status.online,
      paused,
      pausedReason: paused ? (token?.suspended_reason ?? null) : null,
    }
  })
}

/** Un-pausing a violation is allowed only once the owner has said they read the reason. */
export const canUnpause = (acknowledged: boolean, paused: boolean) =>
  paused && acknowledged

export const tokenState = (t: Token) =>
  t.revoked_at ? "revoked" : t.suspended_at ? "paused" : "active"

/**
 * Gateway settings (group `runners`) shown read-only on each runner card. They apply to every
 * runner of that kind; there are no per-runner caps. Edited in the runner settings section.
 */
export const RUNNER_LIMIT_KEYS: Record<RunnerStatus["runner_kind"], string[]> =
  {
    pc: [
      "runners.task_lease_minutes",
      "runners.max_claimed_tasks",
      "runners.claims_per_hour",
      "runners.calls_per_minute",
      "runners.evidence_max_kb",
    ],
    server: [
      "runners.server_runner_enabled",
      "runners.task_lease_minutes",
      "runners.max_claimed_tasks",
      "runners.claims_per_hour",
      "runners.calls_per_minute",
      "runners.server_day_cap_minor",
      "runners.server_task_max_tokens",
      "runners.server_day_max_tokens",
      "runners.evidence_max_kb",
    ],
  }

/** Plain words for a refused un-pause. */
export function reinstateErrorText(e: unknown, fallback: string): string {
  if (isApiError(e, 409))
    return "This token was revoked. A revoked token cannot work again; create a new one."
  if (isApiError(e, 422)) {
    const d = e.body?.detail
    if (
      d &&
      !Array.isArray(d) &&
      typeof d === "object" &&
      d.code === "acknowledgement_required"
    )
      return "Tick the box to say you have read why it was paused."
  }
  return fallback
}
