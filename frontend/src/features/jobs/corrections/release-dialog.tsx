import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { releaseJob } from "../api"
import { errorText, useCorrection } from "./use-correction"

type Props = {
  jobId: string
  title: string
  open: boolean
  onOpenChange: (v: boolean) => void
}

/** Release one held role explicitly, with a reason that goes in the audit trail (DESIGN 7.1). */
export function ReleaseDialog({ jobId, title, open, onOpenChange }: Props) {
  const [reason, setReason] = useState("")
  const m = useCorrection(
    (r: string) => releaseJob(jobId, r),
    "Role released",
    () => {
      setReason("")
      onOpenChange(false)
    }
  )
  const ok = reason.trim().length >= 3
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Release this role</DialogTitle>
          <DialogDescription>
            {title} is held because a better role at the same employer outranks
            it. Releasing it lets it be tailored and applied to as well. Say why;
            the reason is kept in the activity log.
          </DialogDescription>
        </DialogHeader>
        <label className="grid gap-1 text-sm">
          Reason
          <Textarea
            value={reason}
            rows={3}
            onChange={(e) => setReason(e.target.value)}
            placeholder="For example: different team, different manager"
          />
        </label>
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
            disabled={!ok || m.isPending}
            onClick={() => m.mutate(reason.trim())}
          >
            Release role
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
