import { useDeferredValue, useState } from "react"
import { useQueries, useQuery } from "@tanstack/react-query"
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
import { jobQuery, mergeJobs, searchJobsQuery, type JobDetail } from "../api"
import { errorText, useCorrection } from "./use-correction"

type Props = {
  job: JobDetail
  open: boolean
  onOpenChange: (v: boolean) => void
}

/** What stays after a merge, worked out from the roles themselves. */
export function mergePreview(keep: JobDetail, dupes: JobDetail[]) {
  const urls = new Set(keep.sightings.map((s) => s.url))
  dupes.forEach((d) => d.sightings.forEach((s) => urls.add(s.url)))
  const tags = new Set(keep.tags)
  dupes.forEach((d) => d.tags.forEach((t) => tags.add(t)))
  return {
    sightings: urls.size,
    addedSightings: urls.size - keep.sightings.length,
    tags: [...tags],
    addedTags: [...tags].filter((t) => !keep.tags.includes(t)),
  }
}

/** "Merge with another job": search, pick the duplicates, see what is kept, confirm. */
export function MergeDialog({ job, open, onOpenChange }: Props) {
  const [text, setText] = useState("")
  const [picked, setPicked] = useState<string[]>([])
  const deferred = useDeferredValue(text)
  const results = useQuery(searchJobsQuery(deferred, open))
  const details = useQueries({ queries: picked.map((id) => jobQuery(id)) })
  const loaded = details.flatMap((d) => (d.data ? [d.data] : []))
  const preview =
    picked.length > 0 && loaded.length === picked.length
      ? mergePreview(job, loaded)
      : null
  const m = useCorrection(
    () => mergeJobs(job.id, picked),
    "Roles merged",
    () => {
      setPicked([])
      onOpenChange(false)
    }
  )
  const choices = (results.data ?? []).filter((j) => j.id !== job.id)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Merge with another job</DialogTitle>
          <DialogDescription>
            Find the duplicate. Its links and tags join this role, and it stops
            appearing on its own.
          </DialogDescription>
        </DialogHeader>
        <label className="grid gap-1 text-sm">
          Search roles
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Title or employer"
          />
        </label>
        {deferred.trim() && results.isSuccess && choices.length === 0 && (
          <p className="text-sm text-muted-foreground">No other roles match.</p>
        )}
        {choices.length > 0 && (
          <ul
            aria-label="Matching roles"
            className="grid max-h-48 gap-1.5 overflow-y-auto"
          >
            {choices.map((j) => (
              <li key={j.id}>
                <label className="flex items-start gap-2.5 text-sm">
                  <Checkbox
                    className="mt-0.5"
                    checked={picked.includes(j.id)}
                    onCheckedChange={(v) =>
                      setPicked(
                        v ? [...picked, j.id] : picked.filter((p) => p !== j.id)
                      )
                    }
                  />
                  <span>
                    <b>{j.title}</b>, {j.employer}
                    <span className="block text-xs text-faint">
                      {[j.location.city, j.location.country]
                        .filter(Boolean)
                        .join(", ")}
                      {j.best_score != null ? ` · score ${j.best_score}` : ""}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {preview && (
          <section
            aria-label="What will be kept"
            className="grid gap-1 rounded-sm bg-sunken p-3 text-sm"
          >
            <div className="eyebrow">After the merge</div>
            <p>
              <b>{job.title}</b> at {job.employer} stays as the role, with its
              own score and notes.
            </p>
            <p>
              Links: <b className="num">{preview.sightings}</b> in all (
              {preview.addedSightings} added).
            </p>
            <p>
              Tags: {preview.tags.length ? preview.tags.join(", ") : "none"}
              {preview.addedTags.length > 0 &&
                ` (added: ${preview.addedTags.join(", ")})`}
              .
            </p>
          </section>
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
            disabled={picked.length === 0 || m.isPending}
            onClick={() => m.mutate(undefined)}
          >
            Merge into this role
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
