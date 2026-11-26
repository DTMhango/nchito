import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  CalendarClock,
  FlaskConical,
  Pencil,
  Play,
  Plus,
  Trash2,
} from "lucide-react"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { Segmented } from "@/components/segmented"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  createRun,
  deleteSchedule,
  missedRunQuery,
  putMissedRun,
  schedulesQuery,
  sourceKeys,
  toScheduleInput,
  updateSchedule,
  type MissedRun,
  type Schedule,
} from "./api"
import { describeCron, formatWhen, nextRuns } from "./cron"
import { ScheduleDialog } from "./schedule-dialog"
import { useTimezone } from "./shared"
import { KIND_LABEL } from "./words"

export function SchedulesPanel() {
  const qc = useQueryClient()
  const tz = useTimezone()
  const q = useQuery(schedulesQuery())
  const missed = useQuery(missedRunQuery())
  const [editing, setEditing] = useState<Schedule | "new" | null>(null)

  const refresh = () => qc.invalidateQueries({ queryKey: sourceKeys.schedules })
  const toggle = useMutation({
    mutationFn: (s: Schedule) =>
      updateSchedule(s.id, { ...toScheduleInput(s), enabled: !s.enabled }),
    onSuccess: refresh,
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: (s: Schedule) => deleteSchedule(s.id),
    onSuccess: (_d, s) => {
      refresh()
      toast.success(`Deleted ${s.name}`)
    },
    onError: (e) => toast.error(e.message),
  })
  const run = useMutation({
    mutationFn: ({ s, dry }: { s: Schedule; dry: boolean }) =>
      createRun({
        kind: s.kind,
        campaign_id: s.campaign_id,
        dry_run: dry,
      }),
    onSuccess: (_d, { dry }) => {
      qc.invalidateQueries({ queryKey: sourceKeys.runs })
      toast.success(
        dry ? "Dry run started. Nothing will be changed." : "Run started"
      )
    },
    onError: (e) => toast.error(e.message),
  })
  const setMissed = useMutation({
    mutationFn: putMissedRun,
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: missedRunQuery().queryKey }),
    onError: (e) => toast.error(e.message),
  })

  if (q.isPending) return <Skeleton className="h-40 w-full" />
  if (q.isError)
    return (
      <EmptyState
        icon={CalendarClock}
        title="Could not load schedules"
        description={q.error.message}
      />
    )

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          When sweeps and checks run by themselves. Times are shown in your time
          zone ({tz}).
        </p>
        <Button onClick={() => setEditing("new")}>
          <Plus aria-hidden="true" />
          Add schedule
        </Button>
      </div>

      {q.data.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="Nothing is scheduled"
          description="Add a schedule and sweeps will run on their own."
        />
      ) : (
        <ul className="grid gap-3">
          {q.data.map((s) => {
            const stz = s.timezone || tz
            const upcoming = s.enabled ? nextRuns(s.cron, stz, 3) : []
            return (
              <li
                key={s.id}
                className="grid gap-3 rounded-lg border border-border bg-surface p-3.5"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <h3 className="text-md font-semibold">{s.name}</h3>
                  <Chip tone="line">{KIND_LABEL[s.kind]}</Chip>
                  {s.dry_run && <Chip tone="info">Dry run only</Chip>}
                  <span className="ml-auto flex items-center gap-2 text-sm">
                    <label htmlFor={`sch-on-${s.id}`}>
                      {s.enabled ? "On" : "Off"}
                    </label>
                    <Switch
                      id={`sch-on-${s.id}`}
                      checked={s.enabled ?? true}
                      onCheckedChange={() => toggle.mutate(s)}
                    />
                  </span>
                </div>
                <p>{describeCron(s.cron)}</p>
                <div className="text-sm">
                  <span className="eyebrow">Next three runs</span>
                  {upcoming.length ? (
                    <ol className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 num text-muted-foreground">
                      {upcoming.map((d) => (
                        <li key={d.toISOString()}>{formatWhen(d, stz)}</li>
                      ))}
                    </ol>
                  ) : (
                    <p className="mt-1 text-faint">
                      {s.enabled ? "No upcoming time found." : "Switched off."}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    onClick={() => run.mutate({ s, dry: false })}
                    disabled={run.isPending}
                  >
                    <Play aria-hidden="true" />
                    Run now
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => run.mutate({ s, dry: true })}
                    disabled={run.isPending}
                  >
                    <FlaskConical aria-hidden="true" />
                    Dry run
                  </Button>
                  <span className="ml-auto flex gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Edit ${s.name}`}
                      onClick={() => setEditing(s)}
                    >
                      <Pencil aria-hidden="true" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Delete ${s.name}`}
                      onClick={() => remove.mutate(s)}
                    >
                      <Trash2 aria-hidden="true" />
                    </Button>
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <section className="grid gap-2 border-t border-border pt-4">
        <h3 className="text-md font-semibold">
          If the app was off at run time
        </h3>
        <p className="text-sm text-muted-foreground">
          Applies to every schedule. A catch-up runs once, however many times
          were missed.
        </p>
        {missed.data && (
          <Segmented<MissedRun>
            aria-label="Missed runs"
            value={missed.data}
            onValueChange={(v) => setMissed.mutate(v)}
            options={[
              { value: "catch_up_once", label: "Run once to catch up" },
              { value: "skip", label: "Skip until the next time" },
            ]}
          />
        )}
      </section>

      <ScheduleDialog
        value={editing}
        onClose={() => setEditing(null)}
        timezone={tz}
      />
    </div>
  )
}
