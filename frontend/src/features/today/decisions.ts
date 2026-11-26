import type {
  PendingAction,
  AnswerScope,
  ResolveIn,
} from "@/features/applications/api"
import {
  blockerKind,
  choicesOf,
  continueRule,
  isHandoff,
  type BlockerKind,
} from "@/features/accounts/logic"

/** The handoff link of a blocker whose choices are on its handoff page, worded by kind. */
const HANDOFF_LABEL: Partial<Record<BlockerKind, string>> = {
  redirect_off_domain: "See where it went",
  page_instruction: "See what the page asked",
}

export const SCOPE_OPTIONS: {
  value: AnswerScope
  label: string
  hint: string
}[] = [
  {
    value: "this_application",
    label: "This application only",
    hint: "Used once, then forgotten.",
  },
  {
    value: "this_employer",
    label: "This employer",
    hint: "Reused for any role at the same employer.",
  },
  {
    value: "this_country",
    label: "This country",
    hint: "Reused for roles in the same country.",
  },
  {
    value: "all_matching",
    label: "All matching roles",
    hint: "Saved to your answer bank and reused wherever the question matches.",
  },
]

/** Fields the UI reads from a pending action's free-form `detail`. */
export type ActionDetail = {
  question?: string
  options?: string[]
  /** Material questions (pay, work rights, relocation, declarations) default to a narrower scope. */
  material?: boolean
  url?: string
  employer?: string
  role?: string
}

export function readDetail(action: PendingAction): ActionDetail {
  const d = action.detail as Record<string, unknown>
  const str = (v: unknown) => (typeof v === "string" ? v : undefined)
  return {
    question: str(d.question),
    options: Array.isArray(d.options)
      ? d.options.filter((o): o is string => typeof o === "string")
      : undefined,
    material: d.material === true,
    url: str(d.url) ?? str(d.portal_url),
    employer: str(d.employer),
    role: str(d.role),
  }
}

/** Pending-action kinds (`kind` = `detail.kind`) for posting changes, shown on the job's Changes tab. */
export const CHANGE_KINDS = ["posting_changed", "posting_closed"] as const
export type ChangeKind = (typeof CHANGE_KINDS)[number]

export const changeKind = (action: PendingAction): ChangeKind | null => {
  const k = action.kind ?? (action.detail as Record<string, unknown>).kind
  return (CHANGE_KINDS as readonly unknown[]).includes(k)
    ? (k as ChangeKind)
    : null
}

/** The job a change action is about (`detail.job_id`). */
export const changeJobId = (action: PendingAction): string | null => {
  const j = (action.detail as Record<string, unknown>).job_id
  return typeof j === "string" && j ? j : null
}

/**
 * How a button acts: a resolve body the backend accepts for the type, the inline answer form,
 * or a link: "link" (portal / approval / studio), "handoff" (`/accounts/handoff/$id`),
 * "changes" (the job's Changes tab).
 */
export type KitResolution =
  ResolveIn["resolution"] | "answer" | "link" | "handoff" | "changes" | "skip"

export type ActionKit = {
  primary: { label: string; resolution: KitResolution }
  secondary: { label: string; resolution: KitResolution } | null
}

/**
 * Primary and secondary action for a group, from its first action. Only resolutions the backend
 * accepts are offered: for a runner blocker, `continue` when its `choices` list it (other choices
 * are on the handoff page); `answered` for questions, `confirmed` for confirm_submission,
 * `dismissed` for everything else.
 */
export function actionKit(action: PendingAction, count: number): ActionKit {
  const these = count > 1 ? "these roles" : "this role"
  const change = changeKind(action)
  if (change)
    return {
      primary: {
        label:
          change === "posting_closed" ? "See the closure" : "See what changed",
        resolution: "changes",
      },
      secondary: { label: "Dismiss", resolution: "dismissed" },
    }
  // A runner blocker: the buttons follow the server's choices (`choices`), never the type.
  if (action.type !== "unknown_question" && isHandoff(action)) {
    const rule = continueRule(action)
    if (rule)
      return {
        primary: { label: rule.label, resolution: "continue" },
        secondary: { label: "Open portal", resolution: "link" },
      }
    const kind = blockerKind(action)
    return {
      primary: {
        label:
          (kind && HANDOFF_LABEL[kind]) ??
          (choicesOf(action).length ? "Choose what to do" : "See the details"),
        resolution: "handoff",
      },
      // Skip is the server's `skipped` choice (the give-up endpoint), offered only when it lists it.
      secondary: choicesOf(action).includes("skipped")
        ? { label: `Skip ${these}`, resolution: "skip" }
        : null,
    }
  }
  switch (action.type) {
    case "unknown_question":
      return {
        primary: { label: "Answer", resolution: "answer" },
        secondary: { label: `Skip ${these}`, resolution: "dismissed" },
      }
    case "approve":
      return {
        primary: { label: "Review and approve", resolution: "link" },
        secondary: { label: "Not now", resolution: "dismissed" },
      }
    case "confirm_submission":
      return {
        primary: { label: "Yes, it arrived", resolution: "confirmed" },
        secondary: { label: "It didn't go", resolution: "dismissed" },
      }
    default:
      return {
        primary: { label: "Done", resolution: "dismissed" },
        secondary: null,
      }
  }
}

export type Urgency = "danger" | "warn" | "info"

/** Hours until a deadline drives the stripe colour; no deadline is calm. */
export function urgency(deadline: string | null, now = Date.now()): Urgency {
  if (!deadline) return "info"
  const hours = (new Date(deadline).getTime() - now) / 3_600_000
  if (hours < 24) return "danger"
  if (hours < 72) return "warn"
  return "info"
}

/** "closes in 2 days", "due in 14 hours", "overdue". */
export function deadlineText(
  deadline: string,
  verb = "Due",
  now = Date.now()
): string {
  const hours = Math.round((new Date(deadline).getTime() - now) / 3_600_000)
  if (hours < 0) return "Overdue"
  if (hours < 1) return `${verb} within the hour`
  if (hours < 24) return `${verb} in ${hours} hour${hours === 1 ? "" : "s"}`
  const days = Math.round(hours / 24)
  return `${verb} in ${days} day${days === 1 ? "" : "s"}`
}
