/** Blocker rules, handoff wording and account status text (DESIGN 8.3, 8.4). No I/O. */
import type { PendingAction, ResolveIn } from "@/features/applications/api"
import type {
  BlockerDetail,
  BlockerKind,
  PortalAccount,
} from "./w3-pending-types"

export type ContinueRule = {
  /** The button label. Continue is offered only for kinds listed here. */
  label: string
  /** Recorded on the resolution so the audit says what the owner did. */
  note: string
  /** What the owner is expected to have done before pressing it. */
  instruction: string
}

/** Blocker kinds the owner can clear and then continue. Any kind not here has no continue button. */
export const CONTINUE_RULES: Partial<Record<BlockerKind, ContinueRule>> = {
  sign_in: {
    label: "I've signed in, continue",
    note: "signed_in",
    instruction:
      "Open the portal in the browser named below and sign in. Stay signed in, then come back here.",
  },
  create_account: {
    label: "I created the account, continue",
    note: "created_account",
    instruction:
      "Create the account yourself in the browser named below. The agent never creates accounts or types passwords.",
  },
  captcha: {
    label: "I solved it, continue",
    note: "solved",
    instruction:
      "Solve the CAPTCHA in the open tab of the browser named below, then come back here.",
  },
  email_verification: {
    label: "I solved it, continue",
    note: "solved",
    instruction:
      "Enter the verification code from your email in the open tab, then come back here.",
  },
  two_factor: {
    label: "I solved it, continue",
    note: "solved",
    instruction:
      "Complete the two-factor prompt in the open tab, then come back here.",
  },
  assessment: {
    label: "I've done it, continue",
    note: "assessment_done",
    instruction: "Complete the assessment yourself, then come back here.",
  },
}

export const BLOCKER_TITLE: Record<BlockerKind, string> = {
  sign_in: "Sign in needed",
  create_account: "Account needed",
  captcha: "CAPTCHA",
  email_verification: "Email verification",
  two_factor: "Two-factor prompt",
  assessment: "Assessment",
  declaration: "Declaration",
  unsupported_form: "Form the agent cannot use",
  off_domain_redirect: "Left the employer's site",
}

const ALL_KINDS = Object.keys(BLOCKER_TITLE) as BlockerKind[]
const isKind = (v: unknown): v is BlockerKind =>
  typeof v === "string" && (ALL_KINDS as string[]).includes(v)

export const readBlocker = (action: PendingAction): BlockerDetail =>
  action.detail as BlockerDetail

/** The blocker kind: the detail's own, else the pending action type when it is one. */
export function blockerKind(action: PendingAction): BlockerKind | null {
  const d = readBlocker(action)
  if (isKind(d.blocker)) return d.blocker
  return isKind(action.type) ? action.type : null
}

/** Pending actions the handoff screen covers: portal sign-in, account and CAPTCHA blockers. */
export const isHandoff = (action: PendingAction): boolean =>
  action.type === "sign_in" ||
  action.type === "create_account" ||
  action.type === "captcha"

export const continueRule = (kind: BlockerKind | null): ContinueRule | null =>
  kind ? (CONTINUE_RULES[kind] ?? null) : null

export type HandoffChoice = "continue" | "apply_myself" | "skip"

/** The resolution to send for each button. "Apply myself" and "Skip" both close the action without resuming the agent. */
export function resolveBody(
  choice: HandoffChoice,
  kind: BlockerKind | null
): ResolveIn {
  if (choice === "continue") {
    const rule = continueRule(kind)
    if (!rule) throw new Error("This blocker cannot be continued.")
    return { resolution: "continue", note: rule.note }
  }
  return {
    resolution: "dismissed",
    note: choice === "apply_myself" ? "apply_myself" : "skip",
  }
}

/** "2 applications are waiting". */
export const waitingText = (n: number) =>
  n === 0
    ? "Nothing else is waiting on this."
    : `${n} application${n === 1 ? " is" : "s are"} waiting.`

/** Actions in the same group share a portal: they unlock together. */
export const siblingsOf = (
  action: PendingAction,
  all: PendingAction[]
): PendingAction[] =>
  action.group_key
    ? all.filter((a) => a.group_key === action.group_key && a.status === "open")
    : all.filter((a) => a.id === action.id)

export const nearestDeadline = (actions: PendingAction[]): string | null =>
  actions
    .map((a) => a.deadline)
    .filter((d): d is string => !!d)
    .sort()[0] ?? null

export const ACCOUNT_STATUS_LABEL = {
  none: "No account yet",
  created: "Account created",
  signed_in: "Signed in",
} as const

export function accountStatusText(a: PortalAccount): string {
  if (a.status === "signed_in")
    return a.signed_in_runner
      ? `Signed in on ${a.signed_in_runner}`
      : "Signed in"
  return ACCOUNT_STATUS_LABEL[a.status]
}

export const dateText = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "never"
