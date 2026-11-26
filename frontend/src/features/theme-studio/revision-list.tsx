import { useMutation, useQuery } from "@tanstack/react-query"
import { RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { restoreRevision, revisionsQuery, type ThemeOut } from "./api"

/** Saved states of a theme, newest first; any one can be restored (undo walks the edit path). */
export function RevisionList({
  theme,
  dirty,
  onRestored,
}: {
  theme: ThemeOut
  dirty: boolean
  onRestored: (t: ThemeOut) => void
}) {
  const q = useQuery(revisionsQuery(theme.id))
  const restore = useMutation({
    mutationFn: (n: number) => restoreRevision(theme.id, n),
    onSuccess: onRestored,
    onError: (e) => toast.error(e.message),
  })
  return (
    <section
      aria-labelledby="history-title"
      className="rounded-lg border border-border bg-surface p-3"
    >
      <h3 id="history-title" className="mb-2 font-semibold">
        History
      </h3>
      {q.isLoading && (
        <p className="text-[0.86rem] text-muted-foreground">Loading...</p>
      )}
      {q.isError && (
        <p className="text-[0.86rem] text-danger">Couldn't load the history.</p>
      )}
      <ol className="grid gap-px">
        {q.data?.map((r) => (
          <li
            key={r.number}
            className="flex items-center gap-2 rounded-sm px-2 py-1.5 hover:bg-surface-2"
          >
            <span className="w-7 num text-[0.8rem] text-faint">
              #{r.number}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[0.86rem]">{r.note}</span>
              <span className="block text-[0.75rem] text-faint">
                {new Date(r.created_at).toLocaleString()} · {r.body.name}
              </span>
            </span>
            {r.current ? (
              <Chip tone="primary">Current</Chip>
            ) : (
              <Button
                size="xs"
                variant="outline"
                disabled={dirty || restore.isPending}
                title={dirty ? "Save or discard your changes first" : undefined}
                aria-label={`Restore revision ${r.number}`}
                onClick={() => restore.mutate(r.number)}
              >
                <RotateCcw aria-hidden="true" /> Restore
              </Button>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}
