import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  confirmEvent,
  scheduleKeys,
  type ConfirmIn,
  type EventOut,
} from "./api"
import { validZone } from "./event-form"
import { wallRange } from "./format"

/**
 * A proposal from an email. Nothing is confirmed until the owner clicks Confirm, and Confirm is
 * unavailable until a time is settled: a candidate chosen, and a zone given when the invitation
 * named none.
 */
export function ProposalConfirm({
  event,
  jobId,
}: {
  event: EventOut
  jobId: string
}) {
  const qc = useQueryClient()
  const cands = event.candidates
  const [pick, setPick] = useState<number | null>(null)
  const [zone, setZone] = useState("")
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")
  const [error, setError] = useState<string | null>(null)

  const chosen = pick != null ? cands[pick] : null
  const manual = cands.length === 0 && !event.starts_local
  // A zone is needed when the settled time carries none.
  const baseZone =
    cands.length > 0 ? (chosen?.timezone ?? null) : event.timezone
  const needsZone = !baseZone
  const timeSettled =
    cands.length > 0 ? chosen !== null : manual ? start !== "" : true
  const ready = timeSettled && (!needsZone || validZone(zone))

  const confirm = useMutation({
    mutationFn: () => {
      const body: ConfirmIn = {}
      if (pick != null) body.candidate_index = pick
      if (manual) {
        body.starts_local = start
        body.ends_local = end || null
      }
      if (needsZone) body.timezone = zone.trim()
      return confirmEvent(event.id, body)
    },
    onSuccess: () => {
      toast.success("Interview confirmed")
      void qc.invalidateQueries({ queryKey: scheduleKeys.job(jobId) })
      void qc.invalidateQueries({ queryKey: scheduleKeys.upcoming })
    },
    onError: (e) =>
      setError(e instanceof Error ? e.message : "Could not confirm."),
  })

  return (
    <div className="grid gap-2">
      {cands.length > 0 && (
        <fieldset className="grid gap-1.5">
          <legend className="text-sm font-semibold">
            Which time did they offer you?
          </legend>
          {cands.map((c, i) => (
            <label
              key={`${c.starts_local}-${i}`}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm"
            >
              <input
                type="radio"
                name={`cand-${event.id}`}
                checked={pick === i}
                onChange={() => setPick(i)}
              />
              <span className="num">
                {wallRange(c.starts_local, c.ends_local)}
              </span>
              <span className="text-muted-foreground">
                {c.timezone ? `(${c.timezone})` : "(no time zone given)"}
              </span>
              {c.label && (
                <span className="text-muted-foreground">{c.label}</span>
              )}
            </label>
          ))}
        </fieldset>
      )}
      {manual && (
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="grid gap-1 text-sm">
            Starts
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
        </div>
      )}
      {needsZone && (cands.length === 0 || chosen) && (
        <label className="grid gap-1 text-sm">
          The invitation gave no time zone. Which zone is that time in?
          <Input
            value={zone}
            onChange={(e) => setZone(e.target.value)}
            placeholder="Africa/Johannesburg"
          />
        </label>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div>
        <Button
          size="sm"
          disabled={!ready || confirm.isPending}
          onClick={() => {
            setError(null)
            confirm.mutate()
          }}
        >
          Confirm
        </Button>
      </div>
    </div>
  )
}
