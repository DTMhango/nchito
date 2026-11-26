import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { errorText } from "@/features/autopilot/api"
import {
  accountKeys,
  runnerCapsQuery,
  saveRunnerCaps,
} from "@/features/accounts/api"
import type { RunnerCaps } from "@/features/accounts/w3-pending-types"
import { RunnerActivity } from "./activity-view"
import {
  reinstateToken,
  tokenKeys,
  tokensQuery,
  runnerStatusQuery,
} from "./api"
import {
  canUnpause,
  KIND_LABEL,
  runnerRows,
  seenText,
  type RunnerRow,
} from "./logic"

/** Every runner: kind, last seen (stale highlighted), current task, pause state, caps, activity. */
export function RunnersSection() {
  const runners = useQuery(runnerStatusQuery())
  const tokens = useQuery(tokensQuery())
  const rows = runnerRows(runners.data ?? [], tokens.data ?? [])
  return (
    <section aria-labelledby="runners-h" className="grid gap-3">
      <SectionHeader
        as="h3"
        title={<span id="runners-h">Runners</span>}
        aside="A runner appears here once it has used a token."
      />
      {runners.isSuccess && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No runner has connected yet. Create a token and follow a setup guide
          below.
        </p>
      )}
      {runners.isError && (
        <p role="alert" className="text-sm text-danger">
          Could not load runners. Reload to try again.
        </p>
      )}
      <ul aria-label="Runners" className="grid gap-2.5">
        {rows.map((r) => (
          <RunnerCard key={r.status.token_id} row={r} />
        ))}
      </ul>
    </section>
  )
}

function RunnerCard({ row }: { row: RunnerRow }) {
  const { status: s } = row
  const [showActivity, setShowActivity] = useState(false)
  return (
    <li
      aria-label={s.name}
      data-stale={row.stale || undefined}
      data-paused={row.paused || undefined}
      className={
        "grid gap-2 rounded-lg border bg-surface p-3.5 " +
        (row.paused
          ? "border-danger"
          : row.stale
            ? "border-warn"
            : "border-border")
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-md">{s.name}</h4>
        <Chip tone="line">{KIND_LABEL[s.runner_kind]}</Chip>
        {row.paused ? (
          <Chip tone="danger">Paused</Chip>
        ) : (
          <Chip tone={s.online ? "good" : "warn"}>
            {s.online ? "Online" : "Not responding"}
          </Chip>
        )}
        <span
          className={row.stale ? "text-sm text-warn" : "text-sm text-faint"}
        >
          {seenText(s.last_seen_at)}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {s.current_task_id
          ? "Working on a task now."
          : "Not working on anything right now."}
        {row.stale &&
          !row.paused &&
          " It has stopped checking in. Is Claude Code or the container still running?"}
      </p>
      {row.paused && row.token && <PausedNotice row={row} />}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          aria-expanded={showActivity}
          onClick={() => setShowActivity((v) => !v)}
        >
          {showActivity ? "Hide activity" : "Show activity"}
        </Button>
      </div>
      {showActivity && <RunnerActivity tokenId={s.token_id} name={s.name} />}
      <CapsEditor tokenId={s.token_id} name={s.name} />
    </li>
  )
}

/** Why a runner was paused, and an un-pause that needs the owner to say they read it. */
function PausedNotice({ row }: { row: RunnerRow }) {
  const qc = useQueryClient()
  const [ack, setAck] = useState(false)
  const reinstate = useMutation({
    mutationFn: () => reinstateToken(row.status.token_id),
    onSuccess: () => {
      toast.success("Runner un-paused.")
      void qc.invalidateQueries({ queryKey: tokenKeys.tokens })
      void qc.invalidateQueries({ queryKey: tokenKeys.runners })
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const id = `ack-${row.status.token_id}`
  return (
    <div
      role="group"
      aria-label="Paused for a violation"
      className="grid gap-2 rounded-md bg-danger-soft p-3 text-sm"
    >
      <p className="font-medium text-danger">
        This runner was paused and cannot take work.
      </p>
      <p>
        <span className="text-faint">Reason: </span>
        {row.pausedReason ?? "No reason was recorded."}
      </p>
      <label htmlFor={id} className="flex items-start gap-2">
        <input
          id={id}
          type="checkbox"
          className="mt-1"
          checked={ack}
          onChange={(e) => setAck(e.target.checked)}
        />
        I have read why it was paused and checked what it did. I want it to work
        again.
      </label>
      <div>
        <Button
          size="sm"
          disabled={!canUnpause(ack, row.paused) || reinstate.isPending}
          onClick={() => reinstate.mutate()}
        >
          Un-pause runner
        </Button>
      </div>
    </div>
  )
}

const FIELDS: { key: keyof RunnerCaps; label: string; step: string }[] = [
  { key: "max_tasks_per_day", label: "Tasks per day", step: "1" },
  { key: "max_steps_per_task", label: "Steps per task", step: "1" },
  {
    key: "cost_ceiling_per_task",
    label: "Cost ceiling per task",
    step: "0.01",
  },
]

/** Per-runner limits. An empty box means no limit from you. */
function CapsEditor({ tokenId, name }: { tokenId: string; name: string }) {
  const q = useQuery(runnerCapsQuery(tokenId))
  if (!q.data) return null
  return (
    <CapsForm
      key={JSON.stringify(q.data)}
      tokenId={tokenId}
      name={name}
      caps={q.data}
    />
  )
}

function CapsForm({
  tokenId,
  name,
  caps,
}: {
  tokenId: string
  name: string
  caps: RunnerCaps
}) {
  const qc = useQueryClient()
  const [vals, setVals] = useState<Record<keyof RunnerCaps, string>>({
    max_tasks_per_day: caps.max_tasks_per_day?.toString() ?? "",
    max_steps_per_task: caps.max_steps_per_task?.toString() ?? "",
    cost_ceiling_per_task: caps.cost_ceiling_per_task?.toString() ?? "",
  })
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (b: RunnerCaps) => saveRunnerCaps(tokenId, b),
    onSuccess: () => {
      toast.success("Limits saved.")
      void qc.invalidateQueries({ queryKey: accountKeys.caps(tokenId) })
    },
    onError: (e) => setError(errorText(e)),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const out = {} as RunnerCaps
    for (const f of FIELDS) {
      const raw = vals[f.key].trim()
      if (raw === "") {
        out[f.key] = null
        continue
      }
      const n = Number(raw)
      if (!Number.isFinite(n) || n <= 0)
        return setError(`${f.label} must be a number above zero, or empty.`)
      if (f.step === "1" && !Number.isInteger(n))
        return setError(`${f.label} must be a whole number.`)
      out[f.key] = n
    }
    setError(null)
    save.mutate(out)
  }
  return (
    <form
      onSubmit={submit}
      aria-label={`Limits for ${name}`}
      className="grid gap-2 border-t border-border pt-2"
    >
      <h5 className="eyebrow">Limits</h5>
      <div className="grid gap-2 sm:grid-cols-3">
        {FIELDS.map((f) => (
          <label key={f.key} className="grid gap-1 text-sm">
            {f.label}
            <Input
              inputMode="decimal"
              value={vals[f.key]}
              placeholder="No limit"
              onChange={(e) =>
                setVals((v) => ({ ...v, [f.key]: e.target.value }))
              }
            />
          </label>
        ))}
      </div>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div>
        <Button
          type="submit"
          size="sm"
          variant="outline"
          disabled={save.isPending}
        >
          Save limits
        </Button>
      </div>
    </form>
  )
}
