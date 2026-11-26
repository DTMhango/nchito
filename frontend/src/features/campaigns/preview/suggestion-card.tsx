import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { toast } from "sonner"
import { Chip } from "@/components/chip"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { reasonLabel } from "@/features/matches/feedback/reasons"
import {
  acceptSuggestion,
  backtestSuggestion,
  dismissSuggestion,
  type BacktestChangeRow,
  type ChangeIn,
  type Suggestion,
  type SuggestionBacktest,
  type SuggestionChange,
} from "./api"
import { acceptedText, actionLabel, KIND_LABEL } from "./words"

type Props = { suggestion: Suggestion; onDecided: () => void }

/** One open suggestion: what it would change, why, what it would have done, and the decision. */
export function SuggestionCard({ suggestion: s, onDecided }: Props) {
  const [editing, setEditing] = useState(false)
  const [change, setChange] = useState<SuggestionChange>(s.change)
  const [backtest, setBacktest] = useState<SuggestionBacktest | null>(
    s.backtest
  )
  const [error, setError] = useState<string | null>(null)
  const edited = JSON.stringify(change) !== JSON.stringify(s.change)
  const asInput = edited ? (change as unknown as ChangeIn) : null

  const retest = useMutation({
    mutationFn: () => backtestSuggestion(s.id, asInput),
    onSuccess: (b) => {
      setError(null)
      setBacktest(b)
    },
    onError: (e) => setError(e.message),
  })
  const accept = useMutation({
    mutationFn: () => acceptSuggestion(s.id, asInput),
    onSuccess: (done) => {
      toast.success(acceptedText(done))
      onDecided()
    },
    onError: (e) => {
      setError(e.message)
      toast.error(e.message)
    },
  })
  const dismiss = useMutation({
    mutationFn: () => dismissSuggestion(s.id),
    onSuccess: () => {
      toast.success("Suggestion dismissed.")
      onDecided()
    },
    onError: (e) => {
      setError(e.message)
      toast.error(e.message)
    },
  })
  const busy = accept.isPending || dismiss.isPending

  return (
    <article
      aria-label={s.title}
      className="grid gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <header className="flex flex-wrap items-center gap-2">
        <h5 className="min-w-0 flex-1 font-semibold">{s.title}</h5>
        <Chip tone="line">{KIND_LABEL[s.kind]}</Chip>
      </header>

      <Evidence s={s} />

      <ChangeView
        change={change}
        editing={editing}
        onChange={(c) => {
          setChange(c)
          setBacktest(null)
        }}
      />

      {backtest ? (
        <BacktestView b={backtest} />
      ) : (
        <p className="text-sm text-muted-foreground">
          Edited: re-run the test to see what this version would have done.
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={busy || (edited && !backtest)}
          onClick={() => accept.mutate()}
        >
          Accept
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => dismiss.mutate()}
        >
          Dismiss
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setEditing((e) => !e)}
        >
          {editing ? "Done editing" : "Edit"}
        </Button>
        {edited && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={retest.isPending}
            onClick={() => retest.mutate()}
          >
            Re-run the test
          </Button>
        )}
      </div>
    </article>
  )
}

function Evidence({ s }: { s: Suggestion }) {
  const e = s.evidence
  const chips = Object.entries(e.reasons).filter(([, n]) => n > 0)
  return (
    <div className="grid gap-1.5 text-sm">
      <p>
        Based on <b className="num">{e.down}</b> thumbs down and{" "}
        <b className="num">{e.up}</b> thumbs up
        {e.application_ids.length > 0 &&
          ` and ${e.application_ids.length} application outcomes`}
        . {e.summary}
      </p>
      {chips.length > 0 && (
        <ul aria-label="Reasons given" className="flex flex-wrap gap-1.5">
          {chips.map(([r, n]) => (
            <li key={r}>
              <Chip tone="neutral">
                {reasonLabel(r)} ×{n}
              </Chip>
            </li>
          ))}
        </ul>
      )}
      {e.notes.map((n, i) => (
        <blockquote
          key={i}
          className="border-l-2 border-border pl-2.5 text-muted-foreground italic"
        >
          “{n}”
        </blockquote>
      ))}
    </div>
  )
}

function ChangeView({
  change,
  editing,
  onChange,
}: {
  change: SuggestionChange
  editing: boolean
  onChange: (c: SuggestionChange) => void
}) {
  if (change.kind === "reweight_criterion") {
    const entries = Object.entries(change.weights)
    const total = entries.reduce((s, [, w]) => s + w, 0)
    return (
      <div className="grid gap-1 text-sm">
        <p className="font-medium">New weights (total {total})</p>
        <ul className="grid gap-1 sm:grid-cols-2">
          {entries.map(([name, w]) => (
            <li key={name} className="flex items-center gap-2">
              <span className="min-w-0 flex-1">{name}</span>
              {editing ? (
                <NumberBox
                  label={`Weight for ${name}`}
                  value={w}
                  onChange={(v) =>
                    onChange({
                      ...change,
                      weights: { ...change.weights, [name]: v },
                    })
                  }
                />
              ) : (
                <b className="num">{w}</b>
              )}
            </li>
          ))}
        </ul>
      </div>
    )
  }
  const textKey =
    change.kind === "add_penalty" || change.kind === "add_saved_view"
      ? "name"
      : change.kind === "add_tag_rule"
        ? "tag"
        : "reason"
  const textLabel =
    textKey === "name" ? "Name" : textKey === "tag" ? "Tag" : "Reason"
  const text = (change as unknown as Record<string, string>)[textKey]
  const points =
    change.kind === "add_penalty" || change.kind === "add_bonus"
      ? change.points
      : null
  return (
    <div className="grid gap-1 text-sm">
      {editing ? (
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid gap-1">
            <span className="font-medium">{textLabel}</span>
            <Input
              value={text}
              onChange={(e) =>
                onChange({ ...change, [textKey]: e.target.value } as never)
              }
              className="w-64"
            />
          </label>
          {points !== null && (
            <NumberBox
              label="Points"
              value={points}
              onChange={(v) => onChange({ ...change, points: v } as never)}
              showLabel
            />
          )}
        </div>
      ) : (
        <p>
          <span className="text-muted-foreground">{textLabel}:</span> {text}
          {points !== null && (
            <>
              {" "}
              ·{" "}
              <span className="text-muted-foreground">
                {change.kind === "add_penalty" ? "minus" : "plus"}
              </span>{" "}
              <b className="num">{points}</b> points
            </>
          )}
        </p>
      )}
    </div>
  )
}

function NumberBox({
  label,
  value,
  onChange,
  showLabel,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  showLabel?: boolean
}) {
  // The box keeps what is typed (even empty) and reports only whole numbers.
  const [text, setText] = useState(String(value))
  return (
    <label className="grid gap-1">
      {showLabel ? (
        <span className="font-medium">{label}</span>
      ) : (
        <span className="sr-only">{label}</span>
      )}
      <Input
        type="number"
        inputMode="numeric"
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          const n = Number(e.target.value)
          if (e.target.value.trim() !== "" && Number.isInteger(n)) onChange(n)
        }}
        className="w-24"
      />
    </label>
  )
}

function BacktestView({ b }: { b: SuggestionBacktest }) {
  return (
    <div className="grid gap-2 text-sm" aria-label="Backtest">
      <p>
        Tested on {b.jobs} roles from the last {b.window_days} days:{" "}
        <b className="num">{b.matched}</b> matched,{" "}
        <b className="num">{b.score_changed}</b> scores changed.
      </p>
      <Rows title="Would newly pass" rows={b.newly_pass} />
      <Rows title="Would newly drop" rows={b.newly_drop} />
      <Rows
        title="Past applications this would have excluded"
        rows={b.excluded_past_applications}
        warn
      />
    </div>
  )
}

function Rows({
  title,
  rows,
  warn,
}: {
  title: string
  rows: BacktestChangeRow[]
  warn?: boolean
}) {
  if (rows.length === 0) return null
  return (
    <div
      className={
        warn ? "grid gap-1 rounded-md bg-warn-soft p-2 text-warn" : "grid gap-1"
      }
    >
      <p className="font-medium">
        {title} ({rows.length})
      </p>
      <ul aria-label={title} className="grid gap-0.5">
        {rows.map((r) => (
          <li key={r.job_id}>
            {r.title} · {r.employer}:{" "}
            <span className="num">
              {r.old_score ?? "—"} → {r.new_score ?? "—"}
            </span>{" "}
            ({actionLabel(r.old_verdict)} → {actionLabel(r.new_verdict)})
          </li>
        ))}
      </ul>
    </div>
  )
}
