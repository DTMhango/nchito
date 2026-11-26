import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { errorText } from "@/features/autopilot/api"
import { settingsQuery, type SettingOut } from "@/features/settings/api"
import { displayValue } from "@/features/settings/setting-value"
import { RunnerActivity } from "./activity-view"
import {
  reinstateToken,
  tokenKeys,
  tokensQuery,
  runnerStatusQuery,
  type RunnerStatus,
} from "./api"
import {
  canUnpause,
  KIND_LABEL,
  reinstateErrorText,
  RUNNER_LIMIT_KEYS,
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
      {showActivity && <RunnerActivity runner={s} />}
      <RunnerLimits runner={s} />
    </li>
  )
}

/** Why a runner was paused, and an un-pause that needs the owner to say they read it. */
function PausedNotice({ row }: { row: RunnerRow }) {
  const qc = useQueryClient()
  const [ack, setAck] = useState(false)
  const [note, setNote] = useState("")
  const reinstate = useMutation({
    mutationFn: () =>
      reinstateToken(row.status.token_id, {
        acknowledged: ack,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Runner un-paused.")
      void qc.invalidateQueries({ queryKey: tokenKeys.tokens })
      void qc.invalidateQueries({ queryKey: tokenKeys.runners })
    },
    onError: (e) => toast.error(reinstateErrorText(e, errorText(e))),
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
      <label className="grid max-w-md gap-1">
        Note for the record (optional)
        <Input value={note} onChange={(e) => setNote(e.target.value)} />
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

/** The gateway settings that bound this runner, read-only. One set for every runner of a kind. */
function RunnerLimits({ runner }: { runner: RunnerStatus }) {
  const q = useQuery(settingsQuery())
  const all = (q.data ?? []).flatMap((g) => g.settings)
  const rows = RUNNER_LIMIT_KEYS[runner.runner_kind]
    .map((k) => all.find((s) => s.key === k))
    .filter((s): s is SettingOut => !!s)
  if (!q.isSuccess) return null
  return (
    <section
      aria-label={`Limits for ${runner.name}`}
      className="grid gap-2 border-t border-border pt-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h5 className="eyebrow">Limits</h5>
        <span className="text-sm text-faint">
          The same for every {KIND_LABEL[runner.runner_kind].toLowerCase()}{" "}
          runner.
        </span>
        <a
          href="#runner-settings"
          className="ml-auto text-sm text-primary underline underline-offset-2"
        >
          Change in runner settings
        </a>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No runner settings are registered.
        </p>
      ) : (
        <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
          {rows.map((s) => (
            <div key={s.key} className="contents">
              <dt className="text-faint">{s.label}</dt>
              <dd>{displayValue(s, s.value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}
