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
    url: str(d.url),
    employer: str(d.employer),
    role: str(d.role),
  }
}

export type ActionKit = {
  /** How the primary button resolves, or "answer" to open the inline form, or "link". */
  primary: {
    label: string
    resolution: ResolveIn["resolution"] | "answer" | "link"
  }
  secondary: { label: string; resolution: ResolveIn["resolution"] | "link" }
}

/** Primary and secondary action for a group, by the type of its first action. */
export function actionKit(
  type: PendingAction["type"],
  count: number
): ActionKit {
  const these = count > 1 ? "these roles" : "this role"
  switch (type) {
    case "unknown_question":
      return {
        primary: { label: "Answer", resolution: "answer" },
        secondary: { label: `Skip ${these}`, resolution: "dismissed" },
      }
    case "sign_in":
      return {
        primary: { label: "I've signed in", resolution: "continue" },
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
        primary: { label: "Done", resolution: "continue" },
        secondary: { label: "Dismiss", resolution: "dismissed" },
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
