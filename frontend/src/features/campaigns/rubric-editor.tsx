import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { cn } from "@/lib/utils"
import { ConditionBuilder } from "./condition-builder"
import { emptyConditionSet } from "./conditions"
import { RATINGS, rubricProblems, WEIGHT_TOTAL, weightTotal } from "./rubric"
import type { FacetCatalogEntry, RubricBody, RubricCriterion } from "./types"

type Props = {
  body: RubricBody
  onChange: (next: RubricBody) => void
  readOnly?: boolean
  catalogue: FacetCatalogEntry[]
}

const ANCHOR_HELP: Record<string, string> = {
  "0": "What a 0 looks like",
  "1": "What a 1 looks like",
  "2": "What a 2 looks like",
  "3": "What a 3 looks like",
  "4": "What a 4 looks like",
  "5": "What a 5 looks like",
}

/** Criteria with weights that must total 100, anchored ratings, and penalties. */
export function RubricEditor({ body, onChange, readOnly, catalogue }: Props) {
  const total = weightTotal(body.criteria)
  const problems = rubricProblems(body).filter((p) => p.id !== "thresholds")
  const setCrit = (i: number, patch: Partial<RubricCriterion>) =>
    onChange({
      ...body,
      criteria: body.criteria.map((c, j) => (j === i ? { ...c, ...patch } : c)),
    })
  const penalties = body.penalties ?? []

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-md">Criteria</h4>
        <Chip
          tone={total === WEIGHT_TOTAL ? "good" : "danger"}
          aria-label={`Weights total ${total} of ${WEIGHT_TOTAL}`}
          data-testid="weight-total"
        >
          <span className="num">
            {total} / {WEIGHT_TOTAL}
          </span>
        </Chip>
      </div>
      {problems.length > 0 && !readOnly && (
        <ul className="text-sm text-danger" role="status">
          {problems.map((p) => (
            <li key={p.id}>{p.message}</li>
          ))}
        </ul>
      )}

      {body.criteria.map((c, i) => (
        <div
          key={i}
          className="grid gap-2 rounded-lg border border-border p-3"
          role="group"
          aria-label={`Criterion ${i + 1}`}
        >
          <div className="flex items-end gap-2">
            <label className="grid min-w-0 flex-1 gap-1 text-sm">
              <span className="text-muted-foreground">Criterion {i + 1}</span>
              <Input
                value={c.name}
                disabled={readOnly}
                onChange={(e) => setCrit(i, { name: e.target.value })}
              />
            </label>
            <label className="grid gap-1 text-sm">
              <span className="text-muted-foreground">Weight</span>
              <Input
                className="w-20"
                type="number"
                inputMode="numeric"
                min={0}
                max={100}
                disabled={readOnly}
                value={c.weight}
                onChange={(e) =>
                  setCrit(i, {
                    weight: Math.max(
                      0,
                      Math.min(100, Number(e.target.value) || 0)
                    ),
                  })
                }
              />
            </label>
            {!readOnly && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove criterion ${c.name || i + 1}`}
                onClick={() =>
                  onChange({
                    ...body,
                    criteria: body.criteria.filter((_, j) => j !== i),
                  })
                }
              >
                <Trash2 aria-hidden="true" />
              </Button>
            )}
          </div>
          <details className="group">
            <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
              What each rating means ({Object.keys(c.anchors ?? {}).length} of 6
              described)
            </summary>
            <div className="mt-2 grid gap-2">
              {RATINGS.map((r) => (
                <label key={r} className="grid gap-1 text-sm">
                  <span className="text-muted-foreground">
                    {ANCHOR_HELP[r]}
                  </span>
                  <Textarea
                    rows={1}
                    disabled={readOnly}
                    value={c.anchors?.[r] ?? ""}
                    onChange={(e) => {
                      const anchors = { ...(c.anchors ?? {}) }
                      if (e.target.value) anchors[r] = e.target.value
                      else delete anchors[r]
                      setCrit(i, { anchors })
                    }}
                  />
                </label>
              ))}
            </div>
          </details>
        </div>
      ))}
      {!readOnly && (
        <div>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              onChange({
                ...body,
                criteria: [
                  ...body.criteria,
                  { name: "", weight: 0, anchors: {} },
                ],
              })
            }
          >
            <Plus aria-hidden="true" /> Add a criterion
          </Button>
        </div>
      )}

      <div className="grid gap-3">
        <h4 className="text-md">Penalties</h4>
        <p className="text-sm text-muted-foreground">
          Points taken off when a role matches. To add points instead, use a
          "Raise the score" rule in section 2.
        </p>
        {penalties.map((p, i) => (
          <div
            key={i}
            className={cn("grid gap-2 rounded-lg border border-border p-3")}
            role="group"
            aria-label={`Penalty ${i + 1}`}
          >
            <div className="flex items-end gap-2">
              <label className="grid min-w-0 flex-1 gap-1 text-sm">
                <span className="text-muted-foreground">Penalty {i + 1}</span>
                <Input
                  value={p.name}
                  disabled={readOnly}
                  onChange={(e) =>
                    onChange({
                      ...body,
                      penalties: penalties.map((x, j) =>
                        j === i ? { ...x, name: e.target.value } : x
                      ),
                    })
                  }
                />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="text-muted-foreground">Points off</span>
                <Input
                  className="w-20"
                  type="number"
                  min={1}
                  max={100}
                  disabled={readOnly}
                  value={p.points}
                  onChange={(e) =>
                    onChange({
                      ...body,
                      penalties: penalties.map((x, j) =>
                        j === i
                          ? {
                              ...x,
                              points: Math.max(
                                1,
                                Math.min(100, Number(e.target.value) || 1)
                              ),
                            }
                          : x
                      ),
                    })
                  }
                />
              </label>
              {!readOnly && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove penalty ${p.name || i + 1}`}
                  onClick={() =>
                    onChange({
                      ...body,
                      penalties: penalties.filter((_, j) => j !== i),
                    })
                  }
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              )}
            </div>
            {!readOnly && (
              <ConditionBuilder
                label={`Conditions for penalty ${i + 1}`}
                value={p.conditions}
                catalogue={catalogue}
                onChange={(conditions) =>
                  onChange({
                    ...body,
                    penalties: penalties.map((x, j) =>
                      j === i ? { ...x, conditions } : x
                    ),
                  })
                }
              />
            )}
          </div>
        ))}
        {!readOnly && (
          <div>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                onChange({
                  ...body,
                  penalties: [
                    ...penalties,
                    { name: "", points: 5, conditions: emptyConditionSet() },
                  ],
                })
              }
            >
              <Plus aria-hidden="true" /> Add a penalty
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
