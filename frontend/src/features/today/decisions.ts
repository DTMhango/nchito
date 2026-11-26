import type {
  PendingAction,
  AnswerScope,
  ResolveIn,
} from "@/features/applications/api"

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
  ResolveIn["resolution"] | "answer" | "link" | "handoff" | "changes"

export type ActionKit = {
  primary: { label: string; resolution: KitResolution }
  secondary: { label: string; resolution: KitResolution } | null
}

/**
 * Primary and secondary action for a group, from its first action. Only resolutions the backend
 * accepts for that type are offered: `continue` for sign_in / create_account / captcha,
 * `answered` for questions, `confirmed` for confirm_submission, `dismissed` for everything else.
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
  const kind = action.kind ?? (action.detail as Record<string, unknown>).kind
  switch (action.type) {
    case "unknown_question":
      return {
        primary: { label: "Answer", resolution: "answer" },
        secondary: { label: `Skip ${these}`, resolution: "dismissed" },
      }
    case "sign_in":
      return {
        primary: {
          label:
            kind === "verification_code"
              ? "I entered the code"
              : "I've signed in",
          resolution: "continue",
        },
        secondary: { label: "Open portal", resolution: "link" },
      }
    case "create_account":
      return {
        primary: { label: "I created the account", resolution: "continue" },
        secondary: { label: "Open portal", resolution: "link" },
      }
    case "captcha":
      return {
        primary: { label: "I solved it", resolution: "continue" },
        secondary: { label: "Open portal", resolution: "link" },
      }
    case "assessment":
    case "declaration":
    case "unsupported_form":
      return {
        primary: { label: "Choose what to do", resolution: "handoff" },
        secondary: null,
      }
    case "redirect_off_domain":
      return {
        primary: { label: "See where it went", resolution: "handoff" },
        secondary: { label: "Close it", resolution: "dismissed" },
      }
    case "page_instruction":
      return {
        primary: { label: "See what the page asked", resolution: "handoff" },
        secondary: { label: "Close it", resolution: "dismissed" },
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
