import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  createEvent,
  rescheduleEvent,
  scheduleKeys,
  updateEvent,
  type EventOut,
} from "./api"
import { TYPE_LABEL } from "./format"

const SELECT_CLASS =
  "h-8 w-full min-w-0 rounded-md border field-focus border-input bg-surface px-2 text-base text-foreground outline-none"

export type FormMode = "new" | "edit" | "reschedule"

export const validZone = (z: string) => {
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: z.trim() })
    return z.trim().length > 0
  } catch {
    return false
  }
}

const trimWall = (w: string | null) => (w ? w.slice(0, 16) : "")
const orNull = (s: string) => s.trim() || null

type Props = {
  mode: FormMode
  jobId: string
  event: EventOut | null
  /** Zone to suggest for a new event (the owner's). */
  defaultZone: string
  onDone: () => void
  onCancel: () => void
}

/** Add, edit or reschedule an event: wall times in a named IANA zone, as the employer wrote them. */
export function EventForm({
  mode,
  jobId,
  event,
  defaultZone,
  onDone,
  onCancel,
}: Props) {
  const qc = useQueryClient()
  const [start, setStart] = useState(trimWall(event?.starts_local ?? null))
  const [end, setEnd] = useState(trimWall(event?.ends_local ?? null))
  const [zone, setZone] = useState(event?.timezone ?? defaultZone)
  const [type, setType] = useState<EventOut["type"]>(event?.type ?? "video")
  const [round, setRound] = useState(String(event?.round_number ?? 1))
  const [location, setLocation] = useState(event?.location ?? "")
  const [link, setLink] = useState(event?.meeting_link ?? "")
  const [people, setPeople] = useState((event?.interviewers ?? []).join(", "))
  const [notes, setNotes] = useState(event?.notes ?? "")
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () => {
      const when = {
        starts_local: start,
        ends_local: orNull(end),
        timezone: zone.trim(),
      }
      if (mode === "reschedule")
        return rescheduleEvent(event!.id, {
          starts_local: when.starts_local,
          ends_local: when.ends_local,
          timezone: when.timezone,
        })
      const detail = {
        round_number: Number(round) || 1,
        type,
        location: orNull(location),
        meeting_link: orNull(link),
        interviewers: people
          .split(",")
          .map((p) => p.trim())
          .filter(Boolean),
        notes: orNull(notes),
        ...when,
      }
      return mode === "edit"
        ? updateEvent(event!.id, detail)
        : createEvent(jobId, { ...detail, status: "confirmed" })
    },
    onSuccess: () => {
      toast.success(
        mode === "new"
          ? "Interview added"
          : mode === "edit"
            ? "Interview updated"
            : "Interview rescheduled"
      )
      void qc.invalidateQueries({ queryKey: scheduleKeys.job(jobId) })
      void qc.invalidateQueries({ queryKey: scheduleKeys.upcoming })
      onDone()
    },
    onError: (e) =>
      setError(e instanceof Error ? e.message : "Could not save."),
  })

  const title =
    mode === "new"
      ? "Add interview"
      : mode === "edit"
        ? "Edit interview"
        : "Reschedule interview"
  const full = mode !== "reschedule"

  return (
    <form
      aria-label={title}
      className="grid gap-3 panel p-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (!start) return setError("Enter the start time.")
        if (!validZone(zone))
          return setError("Enter a time zone such as Africa/Lusaka.")
        if (end && end <= start)
          return setError("The end must be after the start.")
        setError(null)
        save.mutate()
      }}
    >
      <label className="grid gap-1 text-sm">
        Starts (their wall time)
        <Input
          type="datetime-local"
          value={start}
          onChange={(e) => setStart(e.target.value)}
        />
      </label>
      <label className="grid gap-1 text-sm">
        Ends (optional)
        <Input
          type="datetime-local"
          value={end}
          onChange={(e) => setEnd(e.target.value)}
        />
      </label>
      <label className="grid gap-1 text-sm sm:col-span-2">
        Time zone of those times
        <Input
          value={zone}
          onChange={(e) => setZone(e.target.value)}
          placeholder="Africa/Johannesburg"
        />
      </label>
      {full && (
        <>
          <label className="grid gap-1 text-sm">
            Type
            <select
              className={SELECT_CLASS}
              value={type}
              onChange={(e) => setType(e.target.value as EventOut["type"])}
            >
              {Object.entries(TYPE_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Round
            <Input
              type="number"
              min={1}
              value={round}
              onChange={(e) => setRound(e.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Location
            <Input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Meeting link
            <Input
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="https://"
            />
          </label>
          <label className="grid gap-1 text-sm sm:col-span-2">
            Interviewers (comma separated)
            <Input value={people} onChange={(e) => setPeople(e.target.value)} />
          </label>
          <label className="grid gap-1 text-sm sm:col-span-2">
            Private notes (never in the feed or Google Calendar)
            <Textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger sm:col-span-2">
          {error}
        </p>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" size="sm" disabled={save.isPending}>
          {mode === "reschedule" ? "Save new time" : "Save interview"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
