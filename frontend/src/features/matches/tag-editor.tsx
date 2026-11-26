import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus, X } from "lucide-react"
import { toast } from "sonner"
import { invalidateJobs, mkeys, patchJob } from "./api"
import type { JobDetail } from "./types"

/** Manual tags on one job: remove with the cross, add with the inline field. */
export function TagEditor({ job }: { job: JobDetail }) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState("")
  const m = useMutation({
    mutationFn: (tags: string[]) => patchJob(job.id, { tags }),
    onSuccess: (data) => {
      qc.setQueryData(mkeys.job(job.id), data)
      invalidateJobs(qc)
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "Could not save the tags."),
  })
  const add = () => {
    const t = text.trim().toLowerCase()
    setText("")
    setAdding(false)
    if (t && !job.tags.includes(t)) m.mutate([...job.tags, t])
  }
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      aria-label="Tags"
      role="group"
    >
      {job.tags.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded-full bg-highlight-soft py-0.5 pr-1 pl-2 text-[0.78rem] font-medium text-highlight-ink"
        >
          {t}
          <button
            type="button"
            aria-label={`Remove tag ${t}`}
            onClick={() => m.mutate(job.tags.filter((x) => x !== t))}
            className="grid size-4 place-items-center rounded-full hover:bg-surface"
          >
            <X className="size-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      {adding ? (
        <input
          autoFocus
          aria-label="New tag"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={add}
          onKeyDown={(e) => {
            if (e.key === "Enter") add()
            if (e.key === "Escape") {
              setText("")
              setAdding(false)
            }
          }}
          className="h-6 w-28 rounded-full border field-focus border-border bg-surface px-2 text-[0.78rem]"
        />
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2 py-0.5 text-[0.78rem] text-muted-foreground hover:border-border-strong hover:text-foreground"
        >
          <Plus className="size-3" aria-hidden="true" />
          Tag
        </button>
      )}
    </div>
  )
}
