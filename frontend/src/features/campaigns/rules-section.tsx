import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Eye, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip, FilterChip } from "@/components/chip"
import { NativeSelect, Field } from "./bits"
import { ConditionBuilder } from "./condition-builder"
import {
  cleanConditionSet,
  emptyConditionSet,
  isEmptyConditionSet,
} from "./conditions"
import { previewRule } from "./api"
import { TagInput } from "./tag-input"
import type {
  CampaignCriteria,
  CampaignRule,
  FacetCatalogEntry,
  LocationRule,
  PayFloor,
} from "./types"

const EFFECTS: {
  value: CampaignRule["effect"]
  label: string
  plain: string
}[] = [
  {
    value: "exclude",
    label: "Rule out",
    plain: "Roles that match are dropped.",
  },
  {
    value: "include",
    label: "Must match",
    plain: "Roles that do not match are dropped.",
  },
  {
    value: "penalty",
    label: "Lower the score",
    plain: "Roles that match score less.",
  },
  {
    value: "bonus",
    label: "Raise the score",
    plain: "Roles that match score more.",
  },
]

const WORK_MODELS = [
  { value: "on_site", label: "On-site" },
  { value: "hybrid", label: "Hybrid" },
  { value: "remote", label: "Remote" },
] as const

const EMPLOYMENT = [
  { value: "permanent", label: "Permanent" },
  { value: "fixed_term", label: "Fixed term" },
  { value: "contract", label: "Contract" },
  { value: "eor", label: "Employer of record" },
] as const

const PERIODS = ["year", "month", "week", "day", "hour"] as const

type Props = {
  campaignId: string
  criteria: CampaignCriteria
  onChange: (next: CampaignCriteria) => void
  catalogue: FacetCatalogEntry[]
  /** Items still waiting for the owner's confirmation, highlighted in place. */
  unconfirmed: string[]
}

export function RulesSection({
  campaignId,
  criteria,
  onChange,
  catalogue,
  unconfirmed,
}: Props) {
  const set = (patch: Partial<CampaignCriteria>) =>
    onChange({ ...criteria, ...patch })
  const rules = criteria.rules ?? []
  const locations = criteria.locations ?? []
  const floors = criteria.pay_floors ?? []

  return (
    <>
      <div className="grid gap-3">
        <h4 className="text-md">Include and exclude rules</h4>
        {rules.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No rules yet. A rule says "drop roles like this", "only keep roles
            like this", or "score them lower or higher".
          </p>
        )}
        {rules.map((r, i) => (
          <RuleCard
            key={i}
            index={i}
            rule={r}
            campaignId={campaignId}
            catalogue={catalogue}
            onChange={(next) =>
              set({
                rules: next
                  ? rules.map((x, j) => (j === i ? next : x))
                  : rules.filter((_, j) => j !== i),
              })
            }
          />
        ))}
        <div>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              set({
                rules: [
                  ...rules,
                  { effect: "exclude", conditions: emptyConditionSet() },
                ],
              })
            }
          >
            <Plus aria-hidden="true" /> Add a rule
          </Button>
        </div>
      </div>

      <div
        className="grid gap-2"
        data-unconfirmed={unconfirmed.includes("locations") || undefined}
      >
        <h4 className="text-md">
          Countries and cities{" "}
          {unconfirmed.includes("locations") && (
            <Chip tone="warn">Confirm</Chip>
          )}
        </h4>
        <p className="text-sm text-muted-foreground">
          Allow a place, never accept it, or put it first when roles compete.
        </p>
        {locations.map((l, i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label={`Place ${i + 1}`}
              value={l.place}
              onChange={(e) =>
                set({
                  locations: locations.map((x, j) =>
                    j === i ? { ...x, place: e.target.value } : x
                  ),
                })
              }
            />
            <NativeSelect
              aria-label={`What to do with ${l.place || "this place"}`}
              className="max-w-40"
              value={l.kind}
              onChange={(e) =>
                set({
                  locations: locations.map((x, j) =>
                    j === i
                      ? { ...x, kind: e.target.value as LocationRule["kind"] }
                      : x
                  ),
                })
              }
            >
              <option value="allow">Allow</option>
              <option value="deny">Never</option>
              <option value="priority">Prefer</option>
            </NativeSelect>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove ${l.place || "place"}`}
              onClick={() =>
                set({ locations: locations.filter((_, j) => j !== i) })
              }
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </div>
        ))}
        <div>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              set({ locations: [...locations, { place: "", kind: "allow" }] })
            }
          >
            <Plus aria-hidden="true" /> Add a place
          </Button>
        </div>
      </div>

      <div className="grid gap-2">
        <h4 className="text-md">Work models</h4>
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label="Work models to accept"
        >
          {WORK_MODELS.map((w) => {
            const on = (criteria.work_models ?? []).includes(w.value)
            return (
              <FilterChip
                key={w.value}
                label={w.label}
                facet="Work model"
                state={on ? "include" : "off"}
                onStateChange={() =>
                  set({
                    work_models: on
                      ? (criteria.work_models ?? []).filter(
                          (x) => x !== w.value
                        )
                      : [...(criteria.work_models ?? []), w.value],
                  })
                }
              />
            )
          })}
        </div>
        <p className="text-sm text-muted-foreground">
          Leave all off to accept any work model.
        </p>
      </div>

      <div
        className="grid gap-2"
        data-unconfirmed={unconfirmed.includes("seniority") || undefined}
      >
        <h4 className="text-md">
          Seniority{" "}
          {unconfirmed.includes("seniority") && (
            <Chip tone="warn">Confirm</Chip>
          )}
        </h4>
        <TagInput
          label="seniority levels"
          values={criteria.seniority ?? []}
          onChange={(v) => set({ seniority: v })}
          placeholder="for example: Senior"
        />
      </div>

      <div
        className="grid gap-2"
        data-unconfirmed={unconfirmed.includes("pay_floors") || undefined}
      >
        <h4 className="text-md">
          Lowest pay you will consider{" "}
          {unconfirmed.includes("pay_floors") && (
            <Chip tone="warn">Confirm</Chip>
          )}
        </h4>
        <p className="text-sm text-muted-foreground">
          One floor per kind of employment. A role that states pay below the
          floor is dropped. Pay that is not stated follows the section below.
        </p>
        {floors.map((f, i) => (
          <PayFloorRow
            key={i}
            floor={f}
            onChange={(next) =>
              set({
                pay_floors: next
                  ? floors.map((x, j) => (j === i ? next : x))
                  : floors.filter((_, j) => j !== i),
              })
            }
          />
        ))}
        <div>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              set({
                pay_floors: [
                  ...floors,
                  {
                    employment_type: "permanent",
                    amount_minor: 0,
                    currency: "",
                    period: "year",
                  } as PayFloor,
                ],
              })
            }
          >
            <Plus aria-hidden="true" /> Add a pay floor
          </Button>
        </div>
      </div>

      <Field
        label="Themes to rank lower"
        hint="Roles that lean on these are not dropped, only pushed down."
      >
        <TagInput
          label="themes to rank lower"
          values={criteria.deprioritise_themes ?? []}
          onChange={(v) => set({ deprioritise_themes: v })}
          placeholder="for example: sales targets"
        />
      </Field>
    </>
  )
}

function PayFloorRow({
  floor,
  onChange,
}: {
  floor: PayFloor
  onChange: (next: PayFloor | null) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-2 rounded-md border border-border bg-surface p-2.5 sm:flex sm:flex-wrap sm:items-end">
      <label className="grid gap-1 text-sm">
        <span className="text-muted-foreground">Employment</span>
        <NativeSelect
          value={floor.employment_type}
          onChange={(e) =>
            onChange({
              ...floor,
              employment_type: e.target.value as PayFloor["employment_type"],
            })
          }
        >
          {EMPLOYMENT.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </label>
      <label className="grid gap-1 text-sm">
        <span className="text-muted-foreground">Currency</span>
        <Input
          className="sm:w-24"
          maxLength={3}
          value={floor.currency}
          placeholder="ZMW"
          onChange={(e) =>
            onChange({ ...floor, currency: e.target.value.toUpperCase() })
          }
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="text-muted-foreground">At least</span>
        <Input
          className="sm:w-36"
          type="number"
          inputMode="decimal"
          min={0}
          value={floor.amount_minor ? floor.amount_minor / 100 : ""}
          onChange={(e) =>
            onChange({
              ...floor,
              amount_minor: Math.round(Number(e.target.value || 0) * 100),
            })
          }
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="text-muted-foreground">Per</span>
        <NativeSelect
          value={floor.period ?? "year"}
          onChange={(e) =>
            onChange({ ...floor, period: e.target.value as PayFloor["period"] })
          }
        >
          {PERIODS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </NativeSelect>
      </label>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Remove this pay floor"
        onClick={() => onChange(null)}
      >
        <Trash2 aria-hidden="true" />
      </Button>
    </div>
  )
}

function RuleCard({
  index,
  rule,
  campaignId,
  catalogue,
  onChange,
}: {
  index: number
  rule: CampaignRule
  campaignId: string
  catalogue: FacetCatalogEntry[]
  onChange: (next: CampaignRule | null) => void
}) {
  const [shown, setShown] = useState<number | null>(null)
  const preview = useMutation({
    mutationFn: () =>
      previewRule(campaignId, cleanConditionSet(rule.conditions)),
    onSuccess: (r) => setShown(r.matched),
  })
  const scoring = rule.effect === "penalty" || rule.effect === "bonus"
  const effect = EFFECTS.find((e) => e.value === rule.effect)
  const empty = isEmptyConditionSet(rule.conditions)
  const n = index + 1
  const changed = (next: CampaignRule) => {
    setShown(null)
    onChange(next)
  }

  return (
    <article
      aria-label={`Rule ${n}`}
      className="grid gap-3 rounded-lg border border-border p-3.5"
    >
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">Rule {n}</span>
          <NativeSelect
            aria-label={`What rule ${n} does`}
            value={rule.effect}
            onChange={(e) =>
              changed({
                ...rule,
                effect: e.target.value as CampaignRule["effect"],
                points:
                  e.target.value === "penalty" || e.target.value === "bonus"
                    ? (rule.points ?? 10)
                    : null,
              })
            }
          >
            {EFFECTS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
        </label>
        {scoring && (
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">Points</span>
            <Input
              className="w-20"
              type="number"
              min={1}
              max={100}
              value={rule.points ?? ""}
              onChange={(e) =>
                changed({
                  ...rule,
                  points: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </label>
        )}
        <label className="grid min-w-40 flex-1 gap-1 text-sm">
          <span className="text-muted-foreground">
            Why (for your own notes)
          </span>
          <Input
            value={rule.reason ?? ""}
            onChange={(e) =>
              changed({ ...rule, reason: e.target.value || null })
            }
          />
        </label>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`Remove rule ${n}`}
          onClick={() => onChange(null)}
        >
          <Trash2 aria-hidden="true" />
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{effect?.plain}</p>
      <ConditionBuilder
        label={`Conditions for rule ${n}`}
        value={rule.conditions}
        catalogue={catalogue}
        onChange={(conditions) => changed({ ...rule, conditions })}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={empty || preview.isPending}
          onClick={() => preview.mutate()}
        >
          <Eye aria-hidden="true" /> Preview matches
        </Button>
        <span className="text-sm" aria-live="polite">
          {preview.isError
            ? "Could not check just now."
            : shown !== null
              ? `Would catch ${shown} of your saved jobs.`
              : empty
                ? "Add a condition to preview it."
                : ""}
        </span>
      </div>
    </article>
  )
}
