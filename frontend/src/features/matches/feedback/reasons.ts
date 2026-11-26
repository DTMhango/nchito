import type { FeedbackReason } from "./api"

/** Frontend copy for the reason chips; the order is the order they are shown in. */
export const REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "too_junior", label: "Too junior" },
  { value: "too_senior", label: "Too senior" },
  { value: "wrong_stack", label: "Wrong skills or tools" },
  { value: "pay", label: "Pay" },
  { value: "location", label: "Location" },
  { value: "employer_type", label: "Kind of employer" },
  { value: "commute_remote", label: "Commute or remote" },
  { value: "more_like_this", label: "More like this" },
]

/** The label of a reason, or the raw value for one this build does not know. */
export const reasonLabel = (r: string): string =>
  REASONS.find((x) => x.value === r)?.label ?? r.replace(/_/g, " ")

export const FEEDBACK_EXPLAINER =
  "Feedback is kept as evidence. It never changes a score by itself; suggestions you approve do."
