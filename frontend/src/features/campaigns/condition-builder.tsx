/**
 * Condition builder: builds the shared condition schema (DESIGN 6.1) from the facet
 * catalogue. Self-contained: it takes a ConditionSet and hands back a new one.
 * Facet values are three-state chips (include, exclude, off); "not stated" is a value.
 */
import { useId, useMemo } from "react"
import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FilterChip } from "@/components/chip"
import { Segmented } from "@/components/segmented"
import { NativeSelect } from "./bits"
import {
  addCondition,
  chipState,
  conditionsOf,
  newCondition,
  NOT_STATED,
  replaceCondition,
  rootOf,
  setRootOp,
  valueLabel,
  withChipState,
  withMatch,
  type Condition,
} from "./conditions"
import type {
  ConditionSet,
  FacetCatalogEntry,
  RangeFilter,
  TextFilter,
  ValueFilter,
} from "./types"

type Props = {
  value: ConditionSet
  onChange: (next: ConditionSet) => void
  catalogue: FacetCatalogEntry[]
  /** Names the builder for assistive tech, e.g. "Conditions for rule 2". */
  label: string
}

export function ConditionBuilder({ value, onChange, catalogue, label }: Props) {
  const byFacet = useMemo(
    () => new Map(catalogue.map((e) => [e.facet, e])),
    [catalogue]
  )
  const conds = conditionsOf(value)
  const addId = useId()

  return (
    <div className="grid gap-3" role="group" aria-label={label}>
      {conds.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No conditions yet. Add one below; a rule with no conditions matches
          nothing.
        </p>
      )}
      {conds.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">A role must match</span>
          <Segmented
            size="sm"
            aria-label="Match all or any condition"
            value={rootOf(value).op === "or" ? "or" : "and"}
            onValueChange={(op) => onChange(setRootOp(value, op))}
            options={[
              { value: "and", label: "all of these" },
              { value: "or", label: "any of these" },
            ]}
          />
        </div>
      )}
      {conds.map((c, i) => (
        <ConditionRow
          key={i}
          cond={c}
          entry={c.type === "group" ? undefined : byFacet.get(facetOf(c))}
          onChange={(next) => onChange(replaceCondition(value, i, next))}
        />
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={addId} className="sr-only">
          Add a condition on
        </label>
        <NativeSelect
          id={addId}
          className="max-w-[16rem]"
          value=""
          onChange={(e) => {
            const entry = byFacet.get(e.target.value)
            if (entry) onChange(addCondition(value, newCondition(entry)))
          }}
        >
          <option value="">Add a condition on...</option>
          {catalogue.map((e) => (
            <option key={e.facet} value={e.facet}>
              {e.label}
            </option>
          ))}
        </NativeSelect>
        <Plus className="size-4 text-faint" aria-hidden="true" />
      </div>
    </div>
  )
}

function facetOf(c: Condition): string {
  if (c.type === "values" || c.type === "range") return c.facet
  if (c.type === "text") return c.fields?.[0] ?? "title"
  return ""
}

function ConditionRow({
  cond,
  entry,
  onChange,
}: {
  cond: Condition
  entry: FacetCatalogEntry | undefined
  onChange: (next: Condition | null) => void
}) {
  const title =
    cond.type === "group"
      ? "Group of conditions"
      : (entry?.label ?? facetOf(cond).replaceAll("_", " "))
  return (
    <div className="grid gap-2 rounded-md border border-border bg-surface p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="ml-auto"
          aria-label={`Remove condition: ${title}`}
          onClick={() => onChange(null)}
        >
          <Trash2 aria-hidden="true" />
        </Button>
      </div>
      {cond.type === "values" && (
        <ValuesEditor
          cond={cond}
          entry={entry}
          title={title}
          onChange={onChange}
        />
      )}
      {cond.type === "range" && (
        <RangeEditor cond={cond} title={title} onChange={onChange} />
      )}
      {cond.type === "text" && <TextEditor cond={cond} onChange={onChange} />}
      {cond.type === "group" && (
        <p className="text-sm text-muted-foreground">
          A nested group, kept as it is. Edit it in the Matches filter.
        </p>
      )}
    </div>
  )
}

function ValuesEditor({
  cond,
  entry,
  title,
  onChange,
}: {
  cond: ValueFilter
  entry: FacetCatalogEntry | undefined
  title: string
  onChange: (next: Condition) => void
}) {
  const known = entry?.values ?? []
  // Keep any value already in the rule even if the catalogue no longer lists it.
  const extra = [...(cond.include ?? []), ...(cond.exclude ?? [])]
    .map(String)
    .filter((v) => !known.some((k) => k.value === v))
  const hasNotStated = known.some((k) => k.value === NOT_STATED)
  const options = [
    ...known,
    ...extra.map((v) => ({ value: v, count: undefined as number | undefined })),
    ...(hasNotStated || extra.includes(NOT_STATED)
      ? []
      : [{ value: NOT_STATED, count: undefined as number | undefined }]),
  ]
  return (
    <>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <FilterChip
            key={o.value}
            facet={title}
            label={o.value === NOT_STATED ? "Not stated" : valueLabel(o.value)}
            count={o.count}
            state={chipState(cond, o.value)}
            onStateChange={(s) => onChange(withChipState(cond, o.value, s))}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>Click a value once to require it, twice to rule it out.</span>
        {(cond.include?.length ?? 0) > 1 && (
          <Segmented
            size="sm"
            aria-label={`${title}: match any or all included values`}
            value={cond.match === "all" ? "all" : "any"}
            onValueChange={(m) => onChange(withMatch(cond, m))}
            options={[
              { value: "any", label: "any" },
              { value: "all", label: "all" },
            ]}
          />
        )}
      </div>
    </>
  )
}

function RangeEditor({
  cond,
  title,
  onChange,
}: {
  cond: RangeFilter
  title: string
  onChange: (next: Condition) => void
}) {
  const num = (s: string) => (s.trim() === "" ? null : Number(s))
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      <label className="grid gap-1 text-sm">
        <span className="text-muted-foreground">{title}: at least</span>
        <Input
          type="number"
          inputMode="numeric"
          value={cond.min ?? ""}
          onChange={(e) => onChange({ ...cond, min: num(e.target.value) })}
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="text-muted-foreground">{title}: at most</span>
        <Input
          type="number"
          inputMode="numeric"
          value={cond.max ?? ""}
          onChange={(e) => onChange({ ...cond, max: num(e.target.value) })}
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="text-muted-foreground">When it is not stated</span>
        <NativeSelect
          value={cond.not_stated ?? "exclude"}
          onChange={(e) =>
            onChange({
              ...cond,
              not_stated: e.target.value as "include" | "exclude",
            })
          }
        >
          <option value="exclude">Leave the role out</option>
          <option value="include">Keep the role</option>
        </NativeSelect>
      </label>
    </div>
  )
}

function TextEditor({
  cond,
  onChange,
}: {
  cond: TextFilter
  onChange: (next: Condition) => void
}) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="text-muted-foreground">
        Words that must all appear in the title
      </span>
      <Input
        value={cond.query}
        onChange={(e) => onChange({ ...cond, query: e.target.value })}
        placeholder="for example: actuarial"
      />
    </label>
  )
}
