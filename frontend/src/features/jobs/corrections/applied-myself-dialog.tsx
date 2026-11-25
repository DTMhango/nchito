import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { appliedMyself } from "../api"
import { errorText, useCorrection } from "./use-correction"

const CHANNELS = [
  { value: "browser", label: "On the employer's website" },
  { value: "email", label: "By email" },
  { value: "manual", label: "Another way (referral, recruiter, in person)" },
] as const
const today = () => new Date().toISOString().slice(0, 10)

type Props = { jobId: string; open: boolean; onOpenChange: (v: boolean) => void }

/** "I applied myself": counts at once for duplicates, employer limits and follow-ups. */
export function AppliedMyselfDialog({ jobId, open, onOpenChange }: Props) {
  const [on, setOn] = useState(today())
  const [channel, setChannel] = useState<(typeof CHANNELS)[number]["value"]>("browser")
  const [reference, setReference] = useState("")
  const [note, setNote] = useState("")
  const m = useCorrection(
    () =>
      appliedMyself(jobId, {
        applied_on: on,
        channel,
        reference: reference.trim() || null,
        note: note.trim() || null,
      }),
    "Marked as applied",
    () => onOpenChange(false)
  )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>I applied myself</DialogTitle>
          <DialogDescription>
            It counts straight away for duplicate protection, employer limits
            and follow-up reminders, with or without documents.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <label className="grid gap-1 text-sm">
            Date you applied
            <Input
              type="date"
              value={on}
              max={today()}
              onChange={(e) => setOn(e.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            How
            <select
              value={channel}
              onChange={(e) =>
                setChannel(e.target.value as typeof channel)
              }
              className="h-8 rounded-md border border-input bg-surface px-2 text-base field-focus"
            >
              {CHANNELS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Reference (optional)
            <Input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Note (optional)
            <Textarea
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
        </div>
        {m.isError && (
          <p role="alert" className="text-sm text-danger">
            {errorText(m.error)}
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!on || m.isPending}
            onClick={() => m.mutate(undefined)}
          >
            Mark as applied
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
