import { useId, useState } from "react"
import { ChevronDown } from "lucide-react"
import { FilterChip } from "@/components/chip"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import {
  chipState,
  setChip,
  setMatch,
  setRange,
  valueLabel,
  type RangeSels,
  type ValueSels,
} from "./filters"
import type { FacetCatalogEntry } from "./types"

export type FacetSels = { f?: ValueSels; r?: RangeSels }

type FacetProps = {
  entry: FacetCatalogEntry
  sels: FacetSels
  onChange: (next: FacetSels) => void
  /** Hide counts (rule builders, where counts would mislead). */
  hideCounts?: boolean
}

const SHOW_FIRST = 12

/** One facet's controls: value chips (include, exclude, off) with any/all, or a range. */
export function FacetControl({
  entry,
  sels,
  onChange,
  hideCounts,
}: FacetProps) {
  if (entry.kind === "range")
    return <RangeControl entry={entry} sels={sels} onChange={onChange} />
  if (entry.kind !== "values") return null
  return (
    <ValueChips
      entry={entry}
      sels={sels}
      onChange={onChange}
      hideCounts={hideCounts}
    />
  )
}

function ValueChips({ entry, sels, onChange, hideCounts }: FacetProps) {
  const [all, setAll] = useState(false)
  const values = entry.values ?? []
  const sel = sels.f?.[entry.facet]
  const active = new Set([...(sel?.i ?? []), ...(sel?.e ?? [])])
  const shown =
    all || values.length <= SHOW_FIRST
      ? values
      : values.filter((v, i) => i < SHOW_FIRST || active.has(v.value))
  return (
    <div className="grid gap-2">
      <div
        className="flex flex-wrap gap-1.5"
        role="group"
        aria-label={entry.label}
      >
        {shown.map((v) => (
          <FilterChip
            key={v.value}
            facet={entry.label}
            label={valueLabel(v.value)}
            count={hideCounts ? undefined : v.count}
            state={chipState(sels.f, entry.facet, v.value)}
            onStateChange={(s) =>
              onChange({ ...sels, f: setChip(sels.f, entry.facet, v.value, s) })
            }
          />
        ))}
        {shown.length < values.length && (
          <Button variant="ghost" size="xs" onClick={() => setAll(true)}>
            Show all {values.length}
          </Button>
        )}
      </div>
      {(sel?.i?.length ?? 0) > 0 && (
        <MatchToggle
          label={entry.label}
          value={sel?.m === "all" ? "all" : "any"}
          onChange={(m) =>
            onChange({ ...sels, f: setMatch(sels.f, entry.facet, m) })
          }
        />
      )}
    </div>
  )
}

function MatchToggle({
  label,
  value,
  onChange,
}: {
  label: string
  value: "any" | "all"
  onChange: (v: "any" | "all") => void
}) {
  return (
    <div
      role="radiogroup"
      aria-label={`${label}: match`}
      className="inline-flex w-fit items-center gap-0.5 rounded-full bg-sunken p-0.5 text-xs"
    >
      {(["any", "all"] as const).map((m) => (
        <button
          key={m}
          type="button"
          role="radio"
          aria-checked={value === m}
          onClick={() => onChange(m)}
          className={cn(
            "rounded-full px-2.5 py-0.5 font-medium text-muted-foreground",
            value === m && "bg-surface text-foreground shadow-xs"
          )}
        >
          {m === "any" ? "Any of these" : "All of these"}
        </button>
      ))}
    </div>
  )
}

function RangeControl({ entry, sels, onChange }: FacetProps) {
  const id = useId()
  const sel = sels.r?.[entry.facet] ?? {}
  const num = (s: string) => (s.trim() === "" ? undefined : Number(s))
  const update = (patch: Partial<typeof sel>) =>
    onChange({
      ...sels,
      r: setRange(sels.r, entry.facet, { ...sel, ...patch }),
    })
  return (
    <div className="grid gap-2">
      <div className="flex items-center gap-2 text-sm">
        <label htmlFor={`${id}-min`} className="text-muted-foreground">
          From
        </label>
        <Input
          id={`${id}-min`}
          type="number"
          inputMode="numeric"
          className="h-7 w-20"
          value={sel.min ?? ""}
          onChange={(e) => update({ min: num(e.target.value) })}
        />
        <label htmlFor={`${id}-max`} className="text-muted-foreground">
          to
        </label>
        <Input
          id={`${id}-max`}
          type="number"
          inputMode="numeric"
          className="h-7 w-20"
          value={sel.max ?? ""}
          onChange={(e) => update({ max: num(e.target.value) })}
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <Checkbox
          checked={sel.ns === "include"}
          onCheckedChange={(c) => update({ ns: c ? "include" : undefined })}
        />
        Include roles where it is not stated
      </label>
    </div>
  )
}

export function facetActiveCount(entry: FacetCatalogEntry, sels: FacetSels) {
  if (entry.kind === "range") return sels.r?.[entry.facet] ? 1 : 0
  const s = sels.f?.[entry.facet]
  return (s?.i?.length ?? 0) + (s?.e?.length ?? 0)
}

/** A facet as a compact bar button that opens its chips in a popover. */
export function FacetButton(props: FacetProps) {
  const n = facetActiveCount(props.entry, props.sels)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "shrink-0 rounded-full font-medium",
            n > 0 && "border-primary bg-primary-soft text-primary-ink"
          )}
        >
          {props.entry.label}
          {n > 0 && <span className="num text-xs">{n}</span>}
          <ChevronDown data-icon="inline-end" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[min(420px,calc(100vw-32px))] pop-surface p-3"
      >
        <div className="mb-2 eyebrow">{props.entry.label}</div>
        <FacetControl {...props} />
        <p className="mt-2.5 text-xs text-faint">
          Click a value to include it, again to exclude it, again to clear.
        </p>
      </PopoverContent>
    </Popover>
  )
}

/** Every facet, stacked (phone sheet, rule builder). */
export function FacetPanel({
  catalog,
  sels,
  onChange,
  hideCounts,
}: {
  catalog: FacetCatalogEntry[]
  sels: FacetSels
  onChange: (next: FacetSels) => void
  hideCounts?: boolean
}) {
  return (
    <div className="grid gap-4">
      {catalog
        .filter((e) => e.kind !== "text")
        .map((entry) => (
          <section key={entry.facet} className="grid gap-1.5">
            <h3 className="eyebrow">{entry.label}</h3>
            <FacetControl
              entry={entry}
              sels={sels}
              onChange={onChange}
              hideCounts={hideCounts}
            />
          </section>
        ))}
    </div>
  )
}
