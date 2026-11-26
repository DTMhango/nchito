/** Runner and token wording and rules. No I/O. */
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
    hint: "Ask to press Submit. Each permit is for one application, lasts 10 minutes and works once.",
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
