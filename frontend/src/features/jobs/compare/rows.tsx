import { CircleHelp, Trophy } from "lucide-react"
import { Chip } from "@/components/chip"
import { payBand } from "@/features/matches/format"
import type { CompareCell, CompareRow } from "./api"

export const GROUP_TITLES: Record<CompareRow["group"], string> = {
  score: "Fit",
  pay: "Pay",
  facets: "Facets",
  gates: "Gates",
  employer: "Employer",
  timing: "Timing",
  apply: "How to apply",
}
const GROUP_ORDER = Object.keys(GROUP_TITLES) as CompareRow["group"][]

/** Rows by group, in a fixed reading order; groups with no rows are left out. */
export function groupRows(rows: CompareRow[]) {
  return GROUP_ORDER.map((g) => ({
    group: g,
    title: GROUP_TITLES[g],
    rows: rows.filter((r) => r.group === g),
  })).filter((s) => s.rows.length > 0)
}

/** The roles differ on this row (state or value). */
export const differs = (row: CompareRow) =>
  new Set(row.cells.map((c) => `${c.state}|${c.value ?? ""}`)).size > 1

const text = (v: CompareCell["value"]) =>
  v == null ? "" : String(v).replace(/_/g, " ")

/** The per-year amount a pay cell was normalised to, in the posting's currency. */
const perYear = (c: CompareCell) =>
  c.amount_minor == null
    ? null
    : payBand({
        state: "stated",
        min_minor: c.amount_minor,
        max_minor: c.amount_minor,
        currency: c.currency ?? null,
        period: "year",
        estimate_source: null,
        estimate_assumptions: null,
        estimated_on: null,
      })

/** One cell. "No" and "Not stated" are different answers and look different; unknown is never a guess. */
export function CellView({ cell, pay }: { cell: CompareCell; pay?: boolean }) {
  const note = cell.note && (
    <span className="mt-0.5 block text-xs text-faint">{cell.note}</span>
  )
  switch (cell.state) {
    case "not_stated":
      return (
        <span data-state="not_stated">
          <Chip tone="line" icon={CircleHelp} className="border-dashed italic">
            Not stated
          </Chip>
          {note}
        </span>
      )
    case "unknown":
      return (
        <span data-state="unknown">
          <Chip tone="warn" icon={CircleHelp}>
            Unknown
          </Chip>
          {note}
        </span>
      )
    case "yes":
      return (
        <span data-state="yes">
          <Chip tone="good">Yes</Chip>
          {note}
        </span>
      )
    case "no":
      return (
        <span data-state="no">
          <Chip tone="neutral">No</Chip>
          {note}
        </span>
      )
    case "pass":
    case "fail":
      return (
        <span data-state={cell.state}>
          <Chip tone={cell.state === "pass" ? "good" : "danger"}>
            {cell.state === "pass" ? "Passed" : "Failed"}
          </Chip>
          {cell.value != null && (
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {text(cell.value)}
            </span>
          )}
          {note}
        </span>
      )
    default: {
      const year = pay ? perYear(cell) : null
      return (
        <span data-state={cell.state} className={pay ? "num" : undefined}>
          <span>{text(cell.value)}</span>
          {cell.state === "estimated" && (
            <Chip tone="info" className="ml-1">
              Estimated
            </Chip>
          )}
          {year && (
            <span className="block text-xs text-muted-foreground">
              {year} (midpoint)
            </span>
          )}
          {note}
        </span>
      )
    }
  }
}

/** The "best on this row" marker; only rows that can rank every role have one. */
export function BestMark() {
  return (
    <Chip tone="good" icon={Trophy} className="ml-1">
      Best
    </Chip>
  )
}
