import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Segmented } from "@/components/segmented"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  createSchedule,
  sourceKeys,
  toScheduleInput,
  updateSchedule,
  type RunKind,
  type Schedule,
} from "./api"
import {
  formatWhen,
  nextRuns,
  parsePreset,
  presetToCron,
  validateCron,
  type Preset,
} from "./cron"
import { KIND_LABEL } from "./words"

type Mode = Preset["mode"]
const KINDS: RunKind[] = ["sweep", "expiry_check", "rescore", "digest"]

export function ScheduleDialog({
  value,
  onClose,
  timezone,
}: {
  value: Schedule | "new" | null
  onClose: () => void
  timezone: string
}) {
  return (
    <Dialog open={value !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {value !== null && (
          <Body
            key={value === "new" ? "new" : value.id}
            schedule={value === "new" ? null : value}
            onClose={onClose}
            timezone={timezone}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function Body({
  schedule,
  onClose,
  timezone,
}: {
  schedule: Schedule | null
  onClose: () => void
  timezone: string
}) {
  const qc = useQueryClient()
  const initial: Preset = schedule
    ? parsePreset(schedule.cron)
    : { mode: "daily", time: "07:30" }
  const [name, setName] = useState(schedule?.name ?? "")
  const [kind, setKind] = useState<RunKind>(schedule?.kind ?? "sweep")
  const [mode, setMode] = useState<Mode>(initial.mode)
  const [time, setTime] = useState("time" in initial ? initial.time : "07:30")
  const [every, setEvery] = useState(
    initial.mode === "hours" ? String(initial.every) : "6"
  )
  const [cron, setCron] = useState(
    initial.mode === "cron" ? initial.cron : (schedule?.cron ?? "0 7 * * *")
  )
  const [dry, setDry] = useState(schedule?.dry_run ?? false)
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true)

  const everyN = Number(every)
  const preset: Preset =
    mode === "hours"
      ? { mode, every: everyN }
      : mode === "cron"
        ? { mode, cron }
        : { mode, time }
  const cronOut = presetToCron(preset)
  const cronError =
    mode === "cron"
      ? validateCron(cron)
      : mode === "hours" &&
          !(Number.isInteger(everyN) && everyN >= 1 && everyN <= 23)
        ? "Use a whole number of hours from 1 to 23."
        : mode !== "hours" && !/^\d{2}:\d{2}$/.test(time)
          ? "Choose a time."
          : null
  const tz = schedule?.timezone || timezone
  const upcoming = cronError ? [] : nextRuns(cronOut, tz, 3)
  const invalid = !name.trim() || cronError !== null

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        ...(schedule
          ? toScheduleInput(schedule)
          : { campaign_id: null, timezone: null }),
        name: name.trim(),
        kind,
        cron: cronOut,
        enabled,
        dry_run: dry,
      }
      if (schedule) await updateSchedule(schedule.id, body)
      else await createSchedule(body)
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: sourceKeys.schedules })
      toast.success(schedule ? "Schedule saved" : "Schedule added")
      onClose()
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <>
      <DialogHeader>
        <DialogTitle>{schedule ? "Edit schedule" : "Add schedule"}</DialogTitle>
        <DialogDescription>
          Pick when it runs in plain terms. Cron is there for advanced use.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-4">
        <div className="grid gap-1.5">
          <Label htmlFor="sch-name">Name</Label>
          <Input
            id="sch-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="sch-kind">What runs</Label>
          <select
            id="sch-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as RunKind)}
            className="h-8 rounded-md border field-focus border-input bg-surface px-2 text-base"
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-2">
          <span className="eyebrow">When</span>
          <Segmented<Mode>
            aria-label="Schedule type"
            value={mode}
            onValueChange={setMode}
            options={[
              { value: "daily", label: "Daily" },
              { value: "weekdays", label: "Weekdays" },
              { value: "hours", label: "Every N hours" },
              { value: "cron", label: "Cron" },
            ]}
            className="max-w-full flex-wrap"
          />
          {(mode === "daily" || mode === "weekdays") && (
            <div className="grid gap-1.5">
              <Label htmlFor="sch-time">
                {mode === "daily" ? "Every day at" : "Monday to Friday at"}
              </Label>
              <Input
                id="sch-time"
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="w-32"
              />
            </div>
          )}
          {mode === "hours" && (
            <div className="grid gap-1.5">
              <Label htmlFor="sch-every">Every how many hours</Label>
              <Input
                id="sch-every"
                inputMode="numeric"
                value={every}
                onChange={(e) => setEvery(e.target.value)}
                className="w-24"
              />
            </div>
          )}
          {mode === "cron" && (
            <div className="grid gap-1.5">
              <Label htmlFor="sch-cron">Cron expression</Label>
              <Input
                id="sch-cron"
                value={cron}
                onChange={(e) => setCron(e.target.value)}
                className="font-mono"
                aria-invalid={cronError !== null}
                placeholder="30 7 * * 1-5"
              />
              <p className="text-xs text-muted-foreground">
                Minute, hour, day of month, month, day of week.
              </p>
            </div>
          )}
          {cronError && (
            <p role="alert" className="text-sm text-danger">
              {cronError}
            </p>
          )}
        </div>

        <div className="rounded-md bg-sunken p-3 text-sm">
          <span className="eyebrow">Next three runs ({tz})</span>
          {upcoming.length ? (
            <ol className="mt-1 grid gap-0.5 num">
              {upcoming.map((d) => (
                <li key={d.toISOString()}>{formatWhen(d, tz)}</li>
              ))}
            </ol>
          ) : (
            <p className="mt-1 text-faint">Fix the schedule to see times.</p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="sch-dry" className="grid gap-0.5 font-normal">
            <span className="font-medium">Dry run only</span>
            <span className="text-xs text-muted-foreground">
              Works out what it would do and changes nothing.
            </span>
          </Label>
          <Switch id="sch-dry" checked={dry} onCheckedChange={setDry} />
        </div>
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="sch-enabled">Switched on</Label>
          <Switch
            id="sch-enabled"
            checked={enabled}
            onCheckedChange={setEnabled}
          />
        </div>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          onClick={() => save.mutate()}
          disabled={invalid || save.isPending}
        >
          {save.isPending ? "Saving..." : "Save schedule"}
        </Button>
      </DialogFooter>
    </>
  )
}
