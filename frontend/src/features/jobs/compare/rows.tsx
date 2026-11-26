import type { ReactNode } from "react"
import { CircleHelp } from "lucide-react"
import { Chip } from "@/components/chip"
import { deadlineLabel, payBand } from "@/features/matches/format"
import type { CompareJob } from "../w3-pending-types"

/** One cell: what to show, and a plain key used to tell whether the roles differ here. */
export type Cell = { key: string; node: ReactNode }
export type Row = {
  id: string
  label: string
  cells: Cell[]
}

const FACET_WORDS: Record<string, string> = {
  yes: "Yes",
  no: "No",
  not_stated: "Not stated",
}

/** "No" and "Not stated" are different answers and look different. */
export function FacetValue({ value }: { value: string }) {
  if (value === "not_stated")
    return (
      <Chip tone="line" icon={CircleHelp} className="border-dashed italic">
        Not stated
      </Chip>
    )
  if (value === "no") return <Chip tone="neutral">No</Chip>
  if (value === "yes") return <Chip tone="good">Yes</Chip>
  return <span>{FACET_WORDS[value] ?? value.replace(/_/g, " ")}</span>
}

function payCell(j: CompareJob): Cell {
  const p = j.pay
  if (p.state === "comparable") {
    const text =
      payBand({
        state: "stated",
        min_minor: p.min_minor,
        max_minor: p.max_minor,
        currency: p.currency,
        period: p.period,
        estimate_source: null,
        estimate_assumptions: null,
        estimated_on: null,
      }) ?? "Pay not comparable"
    return {
      key: text,
      node: (
        <span className="num">
          {text}
          {p.note && <span className="block text-xs text-faint">{p.note}</span>}
        </span>
      ),
    }
  }
  const text = p.state === "not_stated" ? "Pay not stated" : "Not comparable"
  return {
    key: `${p.state}`,
    node: (
      <span className="text-muted-foreground italic">
        {text}
        {p.note && (
          <span className="block text-xs text-faint not-italic">{p.note}</span>
        )}
      </span>
    ),
  }
}

const GATE = {
  pass: { text: "Passed", tone: "good" },
  fail: { text: "Failed", tone: "danger" },
  unknown: { text: "Unknown", tone: "warn" },
} as const

const EFFORT_WORDS = {
  low: "Low effort",
  medium: "Medium effort",
  high: "High effort",
  unknown: "Effort unknown",
} as const

const union = (lists: string[][]) => [...new Set(lists.flat())]

/** Build the comparison grid: one row per thing worth comparing, one cell per role. */
export function buildRows(
  jobs: CompareJob[]
): { section: string; rows: Row[] }[] {
  const score: Row = {
    id: "score",
    label: "Score",
    cells: jobs.map((j) => ({
      key: String(j.score),
      node:
        j.score == null ? (
          <span className="text-faint">Not scored</span>
        ) : (
          <b className="num">{j.score}</b>
        ),
    })),
  }
  const facetKeys = union(jobs.map((j) => j.facets.map((f) => f.key)))
  const facetRows: Row[] = facetKeys.map((k) => ({
    id: `facet-${k}`,
    label: jobs.flatMap((j) => j.facets).find((f) => f.key === k)?.label ?? k,
    cells: jobs.map((j) => {
      const v = j.facets.find((f) => f.key === k)?.value ?? "not_stated"
      return { key: v, node: <FacetValue value={v} /> }
    }),
  }))
  const criteria = union(jobs.map((j) => j.criteria.map((c) => c.criterion)))
  const criterionRows: Row[] = criteria.map((c) => ({
    id: `criterion-${c}`,
    label: c,
    cells: jobs.map((j) => {
      const r = j.criteria.find((x) => x.criterion === c)?.rating ?? null
      return {
        key: String(r),
        node:
          r == null ? (
            <span className="text-faint italic">Not assessed</span>
          ) : (
            <span className="num">{r}</span>
          ),
      }
    }),
  }))
  const gates = union(jobs.map((j) => j.gates.map((g) => g.name)))
  const gateRows: Row[] = gates.map((g) => ({
    id: `gate-${g}`,
    label: g,
    cells: jobs.map((j) => {
      const r = j.gates.find((x) => x.name === g)?.result ?? "unknown"
      return {
        key: r,
        node: <Chip tone={GATE[r].tone}>{GATE[r].text}</Chip>,
      }
    }),
  }))
  const other: Row[] = [
    {
      id: "pay",
      label: "Pay",
      cells: jobs.map(payCell),
    },
    {
      id: "conflict",
      label: "Employer conflict group",
      cells: jobs.map((j) => {
        const s = j.conflict.state
        const text =
          s === "winner"
            ? "Winner at this employer"
            : s === "held"
              ? "Held"
              : s === "released"
                ? "Released"
                : "Only role at this employer"
        return {
          key: s,
          node: (
            <span>
              <Chip
                tone={s === "held" ? "warn" : s === "winner" ? "good" : "line"}
              >
                {text}
              </Chip>
              {j.conflict.note && (
                <span className="mt-1 block text-xs text-muted-foreground">
                  {j.conflict.note}
                </span>
              )}
            </span>
          ),
        }
      }),
    },
    {
      id: "deadline",
      label: "Deadline",
      cells: jobs.map((j) => {
        const t = deadlineLabel(j.deadline)
        return { key: t, node: t }
      }),
    },
    {
      id: "channel",
      label: "How to apply",
      cells: jobs.map((j) => ({
        key: `${j.channel.method}/${j.channel.effort}`,
        node: (
          <span>
            <span className="capitalize">
              {j.channel.method.replace(/_/g, " ")}
            </span>
            <span className="block text-xs text-muted-foreground">
              {EFFORT_WORDS[j.channel.effort]}
              {j.channel.note ? `. ${j.channel.note}` : ""}
            </span>
          </span>
        ),
      })),
    },
  ]
  const pick = (id: string) => other.find((r) => r.id === id)!
  return [
    { section: "Fit", rows: [score, ...criterionRows] },
    { section: "Pay", rows: [pick("pay")] },
    { section: "Facets", rows: facetRows },
    { section: "Gates", rows: gateRows },
    {
      section: "Employer and timing",
      rows: [pick("conflict"), pick("deadline"), pick("channel")],
    },
  ].filter((s) => s.rows.length > 0)
}

export const differs = (row: Row) =>
  new Set(row.cells.map((c) => c.key)).size > 1
