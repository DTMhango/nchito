/**
 * TEMPORARY. Shapes for wave 3 endpoints that have no generated type yet (portal accounts,
 * runner tasks, runner caps, blocker details on pending actions). The backend streams build
 * these in parallel. When `docs/openapi.json` carries them, delete this file and import from
 * `@/lib/api/types` instead. Never hand-edit `schema.d.ts`.
 *
 * Endpoints assumed:
 *   GET  /api/portal-accounts            -> PortalAccount[]
 *   POST /api/portal-accounts            <- PortalAccountIn   -> PortalAccount
 *   PUT  /api/portal-accounts/{id}       <- PortalAccountIn   -> PortalAccount
 *   GET  /api/runners/{token_id}/tasks   -> RunnerTask[]
 *   GET  /api/runners/{token_id}/caps    -> RunnerCaps
 *   PUT  /api/runners/{token_id}/caps    <- RunnerCaps        -> RunnerCaps
 */

/** What a portal account row says about sign-in (DESIGN 8.4). Never a password. */
export type PortalAccountStatus = "none" | "created" | "signed_in"

export type PortalAccount = {
  id: string
  /** The portal tenant, for example one employer's Workday site. */
  portal_name: string
  portal_url: string
  status: PortalAccountStatus
  /** Set when status is signed_in: the runner whose browser profile holds the session. */
  signed_in_runner: string | null
  /** The email address used to register. Not a secret. */
  email_used: string | null
  last_sign_in_at: string | null
  /** Applications that cannot go on until this account is ready. */
  applications_waiting: number
}

export type PortalAccountIn = {
  portal_name: string
  portal_url: string
  status: PortalAccountStatus
  signed_in_runner?: string | null
  email_used?: string | null
}

/** Blockers a runner can raise (DESIGN 8.3). */
export type BlockerKind =
  | "sign_in"
  | "create_account"
  | "captcha"
  | "email_verification"
  | "two_factor"
  | "assessment"
  | "declaration"
  | "unsupported_form"
  | "off_domain_redirect"

/** Optional fields a blocker's pending action may carry in `detail`. */
export type BlockerDetail = {
  blocker?: BlockerKind
  url?: string
  portal_name?: string
  runner_token_id?: string
  runner_name?: string
  /** Which browser profile the owner must use, e.g. "Chrome, profile Job search". */
  browser_profile?: string
  reminders?: { sent: number; next_at: string | null }
}

export type PermitEvent = {
  at: string
  outcome: "granted" | "denied" | "wait_for_owner"
  /** The reason on a denial or wait. */
  reason: string | null
}

export type TaskEvidence = {
  kind: "screenshot" | "confirmation_text" | "link"
  label: string
  /** Image or page address; omitted for plain text evidence. */
  url: string | null
}

export type RunnerTaskResult = {
  outcome: "submitted" | "uncertain" | "failed"
  detail: string | null
  evidence: TaskEvidence[]
}

export type RunnerTask = {
  id: string
  application_id: string | null
  title: string
  kind: "apply" | "sweep" | "check"
  status: "queued" | "running" | "blocked" | "done" | "failed"
  started_at: string
  checkpoints: { at: string; step: string }[]
  blockers: { at: string; kind: BlockerKind; action_id: string | null }[]
  permits: PermitEvent[]
  result: RunnerTaskResult | null
}

/** Per-runner limits. `null` means no limit set by the owner. */
export type RunnerCaps = {
  max_tasks_per_day: number | null
  max_steps_per_task: number | null
  cost_ceiling_per_task: number | null
}
