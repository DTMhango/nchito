import { useEffect, useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Textarea } from "@/components/ui/textarea"
import { jobKeys, patchJob } from "./api"

/** How long to wait after the last keystroke before saving. */
export const NOTES_AUTOSAVE_MS = 800

/** The owner's notes, saved by themselves after a pause. Says plainly when it has saved. */
export function NotesEditor({
  jobId,
  initial,
  delay = NOTES_AUTOSAVE_MS,
}: {
  jobId: string
  initial?: string | null
  delay?: number
}) {
  const qc = useQueryClient()
  const [text, setText] = useState(initial ?? "")
  const saved = useRef(initial ?? "")
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle")
  const save = useMutation({
    mutationFn: (notes: string) => patchJob(jobId, { notes }),
    onSuccess: (job, notes) => {
      saved.current = notes
      setStatus("saved")
      qc.setQueryData(jobKeys.job(jobId), job)
    },
    onError: () => setStatus("error"),
  })
  const { mutate } = save

  useEffect(() => {
    if (text === saved.current) return
    const t = window.setTimeout(() => {
      setStatus("saving")
      mutate(text)
    }, delay)
    return () => window.clearTimeout(t)
  }, [text, delay, mutate])

  return (
    <div className="grid gap-1.5">
      <Textarea
        aria-label="Your notes"
        rows={5}
        value={text}
        placeholder="Anything worth remembering about this role"
        onChange={(e) => {
          setText(e.target.value)
          setStatus("idle")
        }}
      />
      <p className="text-xs text-faint" role="status" aria-live="polite">
        {status === "saving" && "Saving..."}
        {status === "saved" && "Saved"}
        {status === "error" && "Could not save. It will try again when you type."}
        {status === "idle" && "Saves by itself when you pause."}
      </p>
    </div>
  )
}
