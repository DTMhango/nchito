/** Blocker rules, handoff wording and account status text (DESIGN 8.3, 8.4). No I/O. */
import type { GiveUpIn, PendingAction, PortalAccount, ResolveIn } from "./api"

/**
 * Blocker kinds `app.apply.accounts` registers (`detail.kind`). Sign-in and create-account are one
 * action per portal tenant; the others are one action per task and kind, so a CAPTCHA and a
 * verification code on the same task are two separate actions.
 */
export const ACCOUNT_KINDS = [
  "sign_in",
  "create_account",
  "verification_code",
  "captcha",
  "assessment",
  "declaration",
  "unsupported_form",
] as const
/** Gateway blockers that are not account actions (`detail.kind = "blocker"`, `detail.blocker`). */
export const GATEWAY_KINDS = [
  "redirect_off_domain",
  "page_instruction",
] as const

export type AccountKind = (typeof ACCOUNT_KINDS)[number]
export type BlockerKind = AccountKind | (typeof GATEWAY_KINDS)[number]

const ALL_KINDS: readonly string[] = [...ACCOUNT_KINDS, ...GATEWAY_KINDS]
const isKind = (v: unknown): v is BlockerKind =>
  typeof v === "string" && ALL_KINDS.includes(v)
const isAccountKind = (v: unknown): v is AccountKind =>
  typeof v === "string" && (ACCOUNT_KINDS as readonly string[]).includes(v)

/** Pending action types the resolve endpoint continues (`owner_actions.CONTINUABLE`). */
const CONTINUABLE: readonly PendingAction["type"][] = [
  "sign_in",
  "create_account",
  "captcha",
]

export type WaitingApplication = {
  application_id: string
  job_id: string | null
  title: string | null
  employer: string | null
  deadline: string | null
}
export type BlockedTask = {
  task_id: string
  runner_id: string | null
  application_id: string | null
}
/** One `get_packet` release, as far as the handoff screen shows it. */
export type ReleaseSummary = {
  at: string | null
  runner: string | null
  destination: string | null
  fields: string[]
  answers: number
  files: string[]
  withheld_files: string[]
}

/** What the handoff screen reads from a blocker's free-form `detail`. All page-derived text is data. */
export type BlockerDetail = {
  kind: BlockerKind | null
  portalKey: string | null
  portalUrl: string | null
  /** The page the runner stopped on (gateway detail). */
  pageUrl: string | null
  runnerId: string | null
  runnerKind: "pc" | "server" | null
  runnerName: string | null
  applications: WaitingApplication[]
  tasks: BlockedTask[]
  /** What the runner said about the stop. Page-derived: shown as text, never followed. */
  note: string | null
  released: ReleaseSummary[]
  origin: string | null
}

const str = (v: unknown): string | null =>
  typeof v === "string" && v ? v : null
const obj = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null
const list = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v)
    ? v.map(obj).filter((x): x is Record<string, unknown> => x !== null)
    : []
const strings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []

/** The blocker kind: `kind` (= `detail.kind`) when it is one, the gateway's `detail.blocker`, else the type. */
export function blockerKind(action: PendingAction): BlockerKind | null {
  const d = action.detail as Record<string, unknown>
  const k = action.kind ?? d.kind
  if (isKind(k)) return k
  if (k === "blocker" && isKind(d.blocker)) return d.blocker
  return isKind(action.type) ? action.type : null
}

export function readBlocker(action: PendingAction): BlockerDetail {
  const d = action.detail as Record<string, unknown>
  const runnerKind = d.runner_kind === "server" || d.runner_kind === "pc"
  return {
    kind: blockerKind(action),
    portalKey: str(d.portal_key),
    portalUrl: str(d.portal_url) ?? str(d.url),
    pageUrl: str(d.url),
    runnerId: str(d.runner_id),
    runnerKind: runnerKind ? (d.runner_kind as "pc" | "server") : null,
    runnerName: str(d.runner),
    applications: list(d.applications).flatMap((e) => {
      const id = str(e.application_id)
      return id
        ? [
            {
              application_id: id,
              job_id: str(e.job_id),
              title: str(e.title),
              employer: str(e.employer),
              deadline: str(e.deadline),
            },
          ]
        : []
    }),
    tasks: list(d.tasks).flatMap((t) => {
      const id = str(t.task_id)
      return id
        ? [
            {
              task_id: id,
              runner_id: str(t.runner_id),
              application_id: str(t.application_id),
            },
          ]
        : []
    }),
    note: str(d.note) ?? str(d.detail),
    released: list(d.released).map((r) => ({
      at: str(r.at),
      runner: str(r.runner),
      destination: str(r.destination),
      fields: strings(r.fields),
      answers: Array.isArray(r.answers) ? r.answers.length : 0,
      files: list(r.files).flatMap((f) =>
        str(f.name) ? [String(f.name)] : []
      ),
      withheld_files: strings(r.withheld_files),
    })),
    origin: str(d.origin),
  }
}

/** Every blocker a runner (or the accounts pass) raised has a handoff screen. */
export const isHandoff = (action: PendingAction): boolean =>
  blockerKind(action) !== null

/** The resolve endpoint continues only sign_in (incl. verification code), create_account and captcha. */
export const canContinue = (action: PendingAction): boolean =>
  CONTINUABLE.includes(action.type)

/** "Apply myself" and "Skip" go through the portal-accounts give-up endpoint: account actions only. */
export const canGiveUp = (action: PendingAction): boolean =>
  isAccountKind((action.detail as Record<string, unknown>).kind)

export type ContinueRule = {
  /** The button label. */
  label: string
  /** Recorded on the resolution so the audit says what the owner did. */
  note: string
  /** What the owner is expected to have done before pressing it. */
  instruction: string
}

export const CONTINUE_RULES: Partial<Record<BlockerKind, ContinueRule>> = {
  sign_in: {
    label: "I've signed in, continue",
    note: "signed_in",
    instruction:
      "Open the portal in the runner's browser profile and sign in. Stay signed in, then come back here.",
  },
  create_account: {
    label: "I created the account, continue",
    note: "created_account",
    instruction:
      "Create the account yourself in the runner's browser profile. The agent never creates accounts or types passwords.",
  },
  captcha: {
    label: "I solved it, continue",
    note: "solved",
    instruction:
      "Solve the CAPTCHA in the open tab of the runner's browser, then come back here.",
  },
  verification_code: {
    label: "I entered the code, continue",
    note: "code_entered",
    instruction:
      "Enter the verification code from your email or phone in the open tab of the runner's browser, then come back here.",
  },
}

/** The continue rule for an action, or null when the backend does not continue its type. */
export function continueRule(action: PendingAction): ContinueRule | null {
  if (!canContinue(action)) return null
  const kind = blockerKind(action)
  return (kind && CONTINUE_RULES[kind]) || CONTINUE_RULES.sign_in!
}

export const BLOCKER_TITLE: Record<BlockerKind, string> = {
  sign_in: "Sign in needed",
  create_account: "Account needed",
  verification_code: "Verification code",
  captcha: "CAPTCHA",
  assessment: "Assessment",
  declaration: "Declaration",
  unsupported_form: "Form the agent cannot use",
  redirect_off_domain: "Left the employer's site",
  page_instruction: "The page asked for something else",
}

/** What the owner can do when the agent cannot carry on. */
export const STOP_TEXT: Partial<Record<BlockerKind, string>> = {
  assessment: "The employer wants an assessment only you can do.",
  declaration:
    "A declaration needs your own answer. It is never filled in for you.",
  unsupported_form:
    "The form is one the agent cannot fill in. You can apply yourself, or skip the role.",
  redirect_off_domain:
    "The form sent the runner off the employer's site, so it stopped. Any unused submit permit was withdrawn.",
  page_instruction:
    "The page asked for something outside the application, so the runner stopped. It never acts on what a page asks.",
}

export type HandoffChoice = "continue" | "apply_myself" | "skip" | "close"

export const continueBody = (rule: ContinueRule): ResolveIn => ({
  resolution: "continue",
  note: rule.note,
})

/** The give-up body for "Apply myself instead" or "Skip". No ids means every waiting application. */
export function giveUpBody(
  choice: "apply_myself" | "skip",
  applicationIds: string[] | null,
  note?: string
): GiveUpIn {
  return {
    outcome: choice === "apply_myself" ? "manual_handoff" : "skipped",
    application_ids:
      applicationIds && applicationIds.length ? applicationIds : null,
    note: note?.trim() || null,
  }
}

/** Applications that wait on this action: the detail's list, else the action's own application. */
export function waitingOn(action: PendingAction): WaitingApplication[] {
  const d = readBlocker(action)
  if (d.applications.length) return d.applications
  return action.application_id
    ? [
        {
          application_id: action.application_id,
          job_id: null,
          title: action.job_title ?? null,
          employer: action.employer ?? null,
          deadline: action.deadline,
        },
      ]
    : []
}

/** "2 applications are waiting". */
export const waitingText = (n: number) =>
  n === 0
    ? "Nothing else is waiting on this."
    : `${n} application${n === 1 ? " is" : "s are"} waiting.`

export const roleText = (e: WaitingApplication) =>
  [e.title, e.employer].filter(Boolean).join(" at ") || "A role"

/** The outcome of a continue, read from `resolution` (`resumed_tasks`, `not_resumed`). */
export function continueOutcome(action: PendingAction): {
  resumed: number
  notResumed: { application_id: string; reason: string }[]
} {
  const r = obj(action.resolution) ?? {}
  return {
    resumed: strings(r.resumed_tasks).length,
    notResumed: list(r.not_resumed).flatMap((x) =>
      str(x.application_id)
        ? [
            {
              application_id: String(x.application_id),
              reason: str(x.reason) ?? "it cannot go ahead",
            },
          ]
        : []
    ),
  }
}

export const ACCOUNT_STATUS_LABEL: Record<PortalAccountStatus, string> = {
  none: "No account yet",
  created: "Account created",
  signed_in: "Signed in",
}
type PortalAccountStatus = PortalAccount["status"]

export function accountStatusText(a: PortalAccount): string {
  if (a.status === "signed_in")
    return a.signed_in_runner
      ? `Signed in on ${a.signed_in_runner}`
      : "Signed in"
  return ACCOUNT_STATUS_LABEL[a.status]
}

/** The account's name on screen: the portal system and its tenant. */
export const accountName = (a: Pick<PortalAccount, "portal" | "tenant">) =>
  `${a.tenant} (${a.portal})`

/** Keys the backend refuses on a portal account (any containing these words is a 422). */
export const SECRET_WORDS = [
  "password",
  "secret",
  "token",
  "pin",
  "otp",
  "cookie",
  "credential",
] as const

export const dateText = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "never"
