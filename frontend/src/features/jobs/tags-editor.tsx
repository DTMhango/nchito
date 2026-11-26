import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { X } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { jobKeys, patchJob } from "./api"

/** Manual tags on a role: add with Enter, remove with the cross. */
export function TagsEditor({ jobId, tags }: { jobId: string; tags: string[] }) {
  const qc = useQueryClient()
  const [text, setText] = useState("")
  const save = useMutation({
    mutationFn: (next: string[]) => patchJob(jobId, { tags: next }),
    onSuccess: (job) => qc.setQueryData(jobKeys.job(jobId), job),
  })
  const add = () => {
    const t = text.trim()
    if (t && !tags.includes(t)) save.mutate([...tags, t])
    setText("")
  }
  return (
    <div className="grid gap-2">
      <ul aria-label="Tags" className="flex flex-wrap gap-1.5">
        {tags.length === 0 && (
          <li className="text-sm text-muted-foreground">No tags yet.</li>
        )}
        {tags.map((t) => (
          <li key={t}>
            <Chip tone="primary">
              {t}
              <button
                type="button"
                aria-label={`Remove tag ${t}`}
                className="rounded-full hover:bg-surface"
                onClick={() => save.mutate(tags.filter((x) => x !== t))}
              >
                <X aria-hidden="true" />
              </button>
            </Chip>
          </li>
        ))}
      </ul>
      <Input
        aria-label="Add a tag"
        value={text}
        placeholder="Add a tag and press Enter"
        className="max-w-[260px]"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            add()
          }
        }}
      />
    </div>
  )
}
