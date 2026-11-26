import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  debriefEvent,
  scheduleKeys,
  type DebriefIn,
  type EventOut,
} from "./api"

const SELECT_CLASS =
  "h-8 w-full min-w-0 rounded-md border field-focus border-input bg-surface px-2 text-base text-foreground outline-none"

export const OUTCOME_LABEL: Record<NonNullable<EventOut["outcome"]>, string> = {
  went_well: "Went well",
  mixed: "Mixed",
  went_badly: "Went badly",
  did_not_happen: "Did not happen",
}
const NEXT_LABEL: Record<NonNullable<DebriefIn["next_step"]>, string> = {
  waiting: "Waiting to hear",
  another_round: "Another round",
  offer: "An offer",
  rejected: "Rejected",
  withdrawn: "I withdrew",
}

export function DebriefForm({
  event,
  jobId,
  onDone,
  onCancel,
}: {
  event: EventOut
  jobId: string
  onDone: () => void
  onCancel: () => void
}) {
  const qc = useQueryClient()
  const [outcome, setOutcome] = useState<DebriefIn["outcome"]>("went_well")
  const [next, setNext] =
    useState<NonNullable<DebriefIn["next_step"]>>("waiting")
  const [notes, setNotes] = useState("")
  const save = useMutation({
    mutationFn: () =>
      debriefEvent(event.id, {
        outcome,
        next_step: next,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Thanks, noted")
      void qc.invalidateQueries({ queryKey: scheduleKeys.job(jobId) })
      void qc.invalidateQueries({ queryKey: scheduleKeys.upcoming })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      onDone()
    },
  })
  return (
    <form
      aria-label="How did it go"
      className="grid gap-3 rounded-md border border-border bg-surface p-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <label className="grid gap-1 text-sm">
        Outcome
        <select
          className={SELECT_CLASS}
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as DebriefIn["outcome"])}
        >
          {Object.entries(OUTCOME_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="grid gap-1 text-sm">
        Next step
        <select
          className={SELECT_CLASS}
          value={next}
          onChange={(e) => setNext(e.target.value as typeof next)}
        >
          {Object.entries(NEXT_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="grid gap-1 text-sm sm:col-span-2">
        Notes
        <Textarea
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      {save.isError && (
        <p role="alert" className="text-sm text-danger sm:col-span-2">
          {save.error.message}
        </p>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" size="sm" disabled={save.isPending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
