import { useDeferredValue, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { fixEmployer, searchJobsQuery, type JobDetail } from "../api"
import { errorText, useCorrection } from "./use-correction"

type Props = { job: JobDetail; open: boolean; onOpenChange: (v: boolean) => void }

/** "Wrong employer": pick an employer already in your list, or type the right one. */
export function EmployerDialog({ job, open, onOpenChange }: Props) {
  const [name, setName] = useState("")
  const [remember, setRemember] = useState(true)
  const deferred = useDeferredValue(name)
  const peers = useQuery(searchJobsQuery(deferred, open))
  const known = [
    ...new Set((peers.data ?? []).map((j) => j.canonical_employer)),
  ].filter((e) => e !== job.canonical_employer)
  const m = useCorrection(
    () => fixEmployer(job.id, name.trim(), remember),
    "Employer corrected",
    () => onOpenChange(false)
  )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Wrong employer</DialogTitle>
          <DialogDescription>
            Now matched to <b>{job.canonical_employer}</b>. Pick the right
            employer from your list or type its name.
          </DialogDescription>
        </DialogHeader>
        <label className="grid gap-1 text-sm">
          Right employer
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Start typing a name"
          />
        </label>
        {known.length > 0 && (
          <ul
            aria-label="Employers in your list"
            className="flex flex-wrap gap-1.5"
          >
            {known.map((e) => (
              <li key={e}>
                <Button size="sm" variant="outline" onClick={() => setName(e)}>
                  {e}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={remember}
            onCheckedChange={(v) => setRemember(v === true)}
          />
          Remember this for future postings
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
            disabled={!name.trim() || m.isPending}
            onClick={() => m.mutate(undefined)}
          >
            Use this employer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
