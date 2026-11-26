import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { splitJob, type JobDetail } from "../api"
import { dateText } from "../format"
import { errorText, useCorrection } from "./use-correction"

type Props = {
  job: JobDetail
  open: boolean
  onOpenChange: (v: boolean) => void
}

/** "Split a wrong merge": pick the sightings that belong to a different role. */
export function SplitDialog({ job, open, onOpenChange }: Props) {
  const [picked, setPicked] = useState<string[]>([])
  const m = useCorrection(
    () => splitJob(job.id, picked),
    "Split into a separate role",
    () => {
      setPicked([])
      onOpenChange(false)
    }
  )
  const all = picked.length === job.sightings.length
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Split a wrong merge</DialogTitle>
          <DialogDescription>
            Pick the links that belong to a different role. They move to a new
            role of their own; the rest stay here.
          </DialogDescription>
        </DialogHeader>
        {job.sightings.length < 2 ? (
          <p className="text-sm text-muted-foreground">
            This role has only one link, so there is nothing to split off.
          </p>
        ) : (
          <ul className="grid gap-2">
            {job.sightings.map((s) => (
              <li key={s.url}>
                <label className="flex items-start gap-2.5 text-sm">
                  <Checkbox
                    className="mt-0.5"
                    checked={picked.includes(s.url)}
                    onCheckedChange={(v) =>
                      setPicked(
                        v
                          ? [...picked, s.url]
                          : picked.filter((u) => u !== s.url)
                      )
                    }
                  />
                  <span className="min-w-0">
                    <span className="block break-all">{s.url}</span>
                    <span className="text-xs text-faint">
                      First seen {dateText(s.first_seen_at)}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {all && (
          <p className="text-sm text-warn">
            Leave at least one link with this role.
          </p>
        )}
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
            disabled={picked.length === 0 || all || m.isPending}
            onClick={() => m.mutate(undefined)}
          >
            Split off the picked {picked.length === 1 ? "link" : "links"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
