import type { PolicyPreviewOut, Suggestion } from "./api"

const plural = (n: number, one: string, many = `${one}s`) =>
  `${n} ${n === 1 ? one : many}`

/** What the pipeline would do with a role (dry-run actions and decision verdicts). */
export const ACTION_LABEL: Record<string, string> = {
  apply: "Apply automatically",
  ask_owner: "Ask you first",
  prepare: "Prepare documents",
  add_to_matches: "Add to matches",
  review: "Needs review",
  skip: "Skip",
  // Verdicts (backtest rows use these).
  auto_apply: "Apply automatically",
  tailor: "Prepare documents",
  shortlist: "Shortlist",
  below_threshold: "Below the lines",
  excluded: "Excluded",
}
export const actionLabel = (a: string) =>
  ACTION_LABEL[a] ?? a.replace(/_/g, " ")

export const CHANGE_LABEL: Record<string, string> = {
  newly_automatic: "Newly automatic",
  newly_blocked: "Newly blocked",
  changed: "Changed",
}

/** "At this setting N roles would have been applied to in the last X days (...)". */
export function lineSentence(p: PolicyPreviewOut): string {
  const l = p.line
  const ch = l.by_channel
  const parts = [
    `${ch.email ?? 0} by email`,
    `${ch.browser ?? 0} by browser`,
    ...(ch.other ? [`${ch.other} another way`] : []),
    `${l.held} held as runner-ups`,
  ]
  return `At this setting ${plural(l.would_apply, "role")} would have been applied to in the last ${plural(p.window_days, "day")} (${parts.join(", ")}).`
}

export function cappedSentence(p: PolicyPreviewOut): string | null {
  if (!p.line.capped) return null
  return `${plural(p.line.capped, "more role")} qualified but went over the daily or weekly cap.`
}

export function quietSentence(c: PolicyPreviewOut["caps"]): string | null {
  if (!c.quiet_hours) return null
  return c.quiet_now
    ? `Right now is inside quiet hours ${c.quiet_hours}: a run now would wait.`
    : `Quiet hours are ${c.quiet_hours}; right now is outside them.`
}

export const KIND_LABEL: Record<Suggestion["kind"], string> = {
  reweight_criterion: "Reweight criteria",
  add_penalty: "Add a penalty",
  add_bonus: "Add a bonus",
  add_tag_rule: "Add a tag rule",
  add_saved_view: "Add a saved view",
  tighten_filter: "Tighten a rule",
}

/** What accepting created, in words (from the suggestion's `result`). */
export function acceptedText(s: Suggestion): string {
  const r = s.result ?? {}
  if (typeof r.rubric_version === "number")
    return `Rubric version ${r.rubric_version} is now active.`
  if (s.kind === "add_tag_rule")
    return typeof r.tagged === "number"
      ? `Tag rule created. ${plural(r.tagged, "role")} tagged.`
      : "Tag rule created."
  if (s.kind === "add_saved_view") return "Saved view created."
  if (s.kind === "tighten_filter") return "Rule added to the campaign."
  return "Suggestion applied."
}
