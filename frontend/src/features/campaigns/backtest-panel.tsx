import { useState } from "react"
import { ArrowDown, ArrowUp, FlaskConical, Minus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip, type ChipTone } from "@/components/chip"
import { DataTable, type Column } from "@/components/data-table"
import { Segmented } from "@/components/segmented"
import { cn } from "@/lib/utils"
import type { BacktestResult, BacktestRow, JobSummary } from "./types"

const CROSSING: Record<
  BacktestRow["crossed"][number],
  { label: string; tone: ChipTone }
> = {
  shortlist_up: { label: "Now shortlisted", tone: "good" },
  shortlist_down: { label: "No longer shortlisted", tone: "danger" },
  tailor_up: { label: "Now gets documents prepared", tone: "good" },
  tailor_down: { label: "No longer gets documents", tone: "danger" },
  auto_up: { label: "Now eligible to auto-apply", tone: "good" },
  auto_down: { label: "No longer eligible to auto-apply", tone: "danger" },
}

export function formatMinor(minor: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en", {
      style: "currency",
      currency,
    }).format(minor / 100)
  } catch {
    return `${currency} ${(minor / 100).toFixed(2)}`
  }
}

export function BacktestTable({ rows }: { rows: BacktestRow[] }) {
  const columns: Column<BacktestRow>[] = [
    {
      id: "role",
      header: "Role",
      sortValue: (r) => r.title,
      cell: (r) => (
        <div>
          <div className="font-medium">{r.title}</div>
          <div className="text-sm text-muted-foreground">{r.employer}</div>
        </div>
      ),
    },
    {
      id: "old",
      header: "Old score",
      align: "right",
      sortValue: (r) => r.old_score ?? -1,
      cell: (r) => <span className="num">{r.old_score ?? "none"}</span>,
    },
    {
      id: "new",
      header: "New score",
      align: "right",
      sortValue: (r) => r.new_score ?? -1,
      cell: (r) => {
        const d = (r.new_score ?? 0) - (r.old_score ?? 0)
        return (
          <span className="num">
            {r.new_score ?? "none"}
            {r.old_score !== null && r.new_score !== null && d !== 0 && (
              <span
                className={cn(
                  "ml-1 text-xs",
                  d > 0 ? "text-good" : "text-danger"
                )}
              >
                {d > 0 ? `+${d}` : d}
              </span>
            )}
          </span>
        )
      },
    },
    {
      id: "rank",
      header: "Rank",
      align: "right",
      sortValue: (r) => (r.old_rank ?? 0) - (r.new_rank ?? 0),
      cell: (r) => <RankChange row={r} />,
    },
    {
      id: "crossed",
      header: "Crosses a threshold",
      hideBelow: "sm",
      cell: (r) =>
        r.crossed.length ? (
          <div className="flex flex-wrap gap-1">
            {r.crossed.map((c) => (
              <Chip key={c} tone={CROSSING[c].tone}>
                {CROSSING[c].label}
              </Chip>
            ))}
          </div>
        ) : (
          <span className="text-faint">No change</span>
        ),
    },
  ]
  return (
    <DataTable
      caption="Old and new scores for each role"
      columns={columns}
      rows={rows}
      getRowId={(r) => r.job_id}
      minWidth={520}
    />
  )
}

function RankChange({ row }: { row: BacktestRow }) {
  if (row.old_rank === null || row.new_rank === null)
    return <span className="text-faint">none</span>
  const moved = row.old_rank - row.new_rank
  const Icon = moved > 0 ? ArrowUp : moved < 0 ? ArrowDown : Minus
  return (
    <span
      className="inline-flex items-center justify-end gap-1 num"
      aria-label={`Rank ${row.old_rank} to ${row.new_rank}`}
    >
      {row.old_rank} to {row.new_rank}
      <Icon
        className={cn(
          "size-3",
          moved > 0 && "text-good",
          moved < 0 && "text-danger"
        )}
        aria-hidden="true"
      />
    </span>
  )
}

type Props = {
  jobs: JobSummary[]
  disabledReason: string | null
  running: boolean
  result: BacktestResult | null
  error: string | null
  onRun: (jobIds: string[] | null) => void
  onActivate: () => void
  activating: boolean
  canActivate: boolean
}

/** Pick saved jobs or "last 30 days", run, then compare old and new scores. */
export function BacktestPanel({
  jobs,
  disabledReason,
  running,
  result,
  error,
  onRun,
  onActivate,
  activating,
  canActivate,
}: Props) {
  const [source, setSource] = useState<"recent" | "pick">("recent")
  const [picked, setPicked] = useState<string[]>([])
  const count = source === "recent" ? jobs.length : picked.length
  const blocked =
    disabledReason ?? (count === 0 ? "Pick at least one saved job." : null)

  const moved = result
    ? result.rows.filter((r) => r.crossed.length > 0).length
    : 0

  return (
    <div className="grid gap-3 rounded-lg border border-border bg-surface-2 p-3.5">
      <div className="flex items-center gap-2">
        <FlaskConical className="size-4 text-faint" aria-hidden="true" />
        <h4 className="text-md">Backtest this draft</h4>
      </div>
      <p className="text-sm text-muted-foreground">
        See how roles you have already saved would score under this draft,
        before it replaces the active rubric. Nothing changes until you make it
        active.
      </p>
      <Segmented
        aria-label="Which saved jobs to test"
        value={source}
        onValueChange={setSource}
        options={[
          { value: "recent", label: "Last 30 days" },
          { value: "pick", label: "Pick saved jobs" },
        ]}
      />
      {source === "pick" && (
        <ul
          className="grid max-h-56 gap-1 overflow-y-auto rounded-md border border-border bg-surface p-2"
          aria-label="Saved jobs"
        >
          {jobs.map((j) => (
            <li key={j.id}>
              <label className="flex items-center gap-2 py-0.5 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={picked.includes(j.id)}
                  onChange={(e) =>
                    setPicked(
                      e.target.checked
                        ? [...picked, j.id]
                        : picked.filter((x) => x !== j.id)
                    )
                  }
                />
                <span className="min-w-0 truncate">
                  {j.title}, {j.employer}
                </span>
                <span className="ml-auto num text-muted-foreground">
                  {j.best_score ?? "none"}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <p className="text-sm" aria-live="polite">
        {source === "recent"
          ? "Scores every role saved in the last 30 days."
          : `${picked.length} saved ${picked.length === 1 ? "job" : "jobs"} picked.`}{" "}
        The cost estimate appears with the results and counts against this
        campaign's budget.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          disabled={!!blocked || running}
          onClick={() => onRun(source === "recent" ? null : picked)}
        >
          {running ? "Scoring..." : "Run backtest"}
        </Button>
        {blocked && (
          <span className="text-sm text-muted-foreground">{blocked}</span>
        )}
      </div>
      {error && (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="grid gap-3" aria-label="Backtest results" role="region">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span>
              {result.rows.length} roles scored, {moved}{" "}
              {moved === 1 ? "crosses" : "cross"} a threshold.
            </span>
            <span className="text-muted-foreground">
              Estimated cost{" "}
              <b className="num text-foreground">
                {formatMinor(result.estimated_cost_minor, result.cost_currency)}
              </b>
            </span>
          </div>
          <BacktestTable rows={result.rows} />
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              disabled={!canActivate || activating}
              onClick={onActivate}
            >
              Make this rubric active
            </Button>
            {!canActivate && (
              <span className="text-sm text-muted-foreground">
                Fix the problems above first.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
