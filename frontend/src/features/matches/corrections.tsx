import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
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
import { Textarea } from "@/components/ui/textarea"
import { appliedMyself, invalidateJobs, releaseHeld } from "./api"

export type Correction = "applied" | "release"

const CHANNELS = [
  ["browser", "Online, on a site or portal"],
  ["email", "By email"],
  ["manual", "Another way (in person, through a contact)"],
] as const
type Channel = (typeof CHANNELS)[number][0]

const today = () => new Date().toISOString().slice(0, 10)

/** Corrections from DESIGN 18.4 that Matches offers: "I applied myself" and releasing a held role. */
export function CorrectionDialog({
  kind,
  jobId,
  jobTitle,
  onOpenChange,
}: {
  kind: Correction | null
  jobId: string | null
  jobTitle: string
  onOpenChange: (open: boolean) => void
}) {
  const qc = useQueryClient()
  const id = useId()
  const [date, setDate] = useState(today())
  const [channel, setChannel] = useState<Channel>(CHANNELS[0][0])
  const [reference, setReference] = useState("")
  const [text, setText] = useState("")
  const m = useMutation({
    mutationFn: async () => {
      if (!jobId) return
      if (kind === "applied")
        await appliedMyself(jobId, {
          applied_on: date,
          channel,
          reference: reference.trim() || null,
          note: text.trim() || null,
        })
      else await releaseHeld(jobId, text.trim())
    },
    onSuccess: () => {
      toast.success(
        kind === "applied"
          ? "Recorded. It counts now for duplicates, employer limits and follow-ups."
          : "Released. The reason is in the audit log."
      )
      invalidateJobs(qc, jobId ?? undefined)
      onOpenChange(false)
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "That did not save."),
  })
  const valid = kind === "applied" ? !!date : !!text.trim()
  return (
    <Dialog open={kind !== null} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">
            {kind === "applied" ? "I applied myself" : "Release this held role"}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {kind === "applied"
              ? `${jobTitle}. It counts at once for duplicates, employer limits and follow-ups, with or without documents.`
              : `${jobTitle} was held because a better role at the same employer won. Releasing it lets it go ahead too. Say why; it is kept in the audit log.`}
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (valid) m.mutate()
          }}
        >
          {kind === "applied" && (
            <>
              <div className="grid gap-1.5">
                <label htmlFor={`${id}-d`} className="eyebrow">
                  Applied on
                </label>
                <Input
                  id={`${id}-d`}
                  type="date"
                  value={date}
                  max={today()}
                  onChange={(e) => setDate(e.target.value)}
                  className="w-44"
                />
              </div>
              <div className="grid gap-1.5">
                <label htmlFor={`${id}-c`} className="eyebrow">
                  How
                </label>
                <select
                  id={`${id}-c`}
                  className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value as Channel)}
                >
                  {CHANNELS.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid gap-1.5">
                <label htmlFor={`${id}-r`} className="eyebrow">
                  Reference (optional)
                </label>
                <Input
                  id={`${id}-r`}
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                />
              </div>
            </>
          )}
          <div className="grid gap-1.5">
            <label htmlFor={`${id}-t`} className="eyebrow">
              {kind === "applied" ? "Note (optional)" : "Reason"}
            </label>
            <Textarea
              id={`${id}-t`}
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!valid || m.isPending}>
              {kind === "applied" ? "Record it" : "Release"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
