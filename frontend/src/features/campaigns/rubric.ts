import type { RubricBody, RubricCriterion } from "./types"

/** Weights must total this (DESIGN 7: "weights summing to 100"). A rule of the scoring model, not a setting. */
export const WEIGHT_TOTAL = 100

export const RATINGS = ["0", "1", "2", "3", "4", "5"] as const

export const weightTotal = (criteria: RubricCriterion[]): number =>
  criteria.reduce(
    (sum, c) => sum + (Number.isFinite(c.weight) ? c.weight : 0),
    0
  )

export type RubricProblem = { id: string; message: string }

/** Everything that stops a rubric being activated or backtested. */
export function rubricProblems(body: RubricBody): RubricProblem[] {
  const out: RubricProblem[] = []
  const total = weightTotal(body.criteria)
  if (body.criteria.length === 0)
    out.push({ id: "empty", message: "Add at least one criterion." })
  else if (total !== WEIGHT_TOTAL)
    out.push({
      id: "weights",
      message:
        total < WEIGHT_TOTAL
          ? `Weights add up to ${total}. Add ${WEIGHT_TOTAL - total} more to reach ${WEIGHT_TOTAL}.`
          : `Weights add up to ${total}. Take off ${total - WEIGHT_TOTAL} to reach ${WEIGHT_TOTAL}.`,
    })
  if (body.criteria.some((c) => !c.name.trim()))
    out.push({ id: "names", message: "Every criterion needs a name." })
  const t = body.thresholds
  if (
    t?.shortlist != null &&
    t.tailor != null &&
    t.auto_apply != null &&
    !(t.shortlist <= t.tailor && t.tailor <= t.auto_apply)
  )
    out.push({
      id: "thresholds",
      message: "Thresholds must rise: shortlist, then tailor, then auto-apply.",
    })
  return out
}
