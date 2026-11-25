import { useState } from "react"
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { History, Undo2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import { EmptyState } from "@/components/empty-state"
import {
  listConfigHistory,
  rollbackRevision,
  settingsKeys,
  type ConfigRevision,
} from "./api"

const KINDS = ["", "rubric", "prompt", "rule", "model_route", "automation_policy"]

/** Renders a revision's diff as old to new lines when it has that shape, else as JSON. */
function Diff({ diff }: { diff: ConfigRevision["diff"] }) {
  if (!diff || Object.keys(diff).length === 0)
    return <p className="text-sm text-muted-foreground">No field changes recorded.</p>
  return (
    <dl className="grid gap-1 rounded-sm bg-sunken p-3 text-sm">
      {Object.entries(diff).map(([field, v]) => {
        const pair =
          v && typeof v === "object" && ("old" in v || "new" in v)
            ? (v as { old?: unknown; new?: unknown })
            : null
        return (
          <div key={field} className="grid gap-0.5">
            <dt className="num font-medium">{field}</dt>
            {pair ? (
              <dd>
                <span className="text-danger line-through">{show(pair.old)}</span>{" "}
                <span className="text-good">{show(pair.new)}</span>
              </dd>
            ) : (
              <dd className="num">{show(v)}</dd>
            )}
          </div>
        )
      })}
    </dl>
  )
}
const show = (v: unknown) =>
  typeof v === "string" ? v : v === undefined ? "none" : JSON.stringify(v)

function RevisionRow({ rev }: { rev: ConfigRevision }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [note, setNote] = useState("")
  const rollback = useMutation({
    mutationFn: () => rollbackRevision(rev.id, note),
    onSuccess: () => {
      setConfirming(false)
      setNote("")
      toast.success(`Rolled back to version ${rev.version}`)
      void qc.invalidateQueries({ queryKey: ["config-history"] })
      void qc.invalidateQueries({ queryKey: settingsKeys.all })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Rollback failed"),
  })
  return (
    <li className="grid gap-2 border-t border-border row-pad first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="line">{rev.kind.replaceAll("_", " ")}</Chip>
        <span className="num font-semibold">v{rev.version}</span>
        {rev.rollback_of && <Chip tone="info">A rollback</Chip>}
        <span className="text-sm text-muted-foreground">
          {rev.author}, {new Date(rev.created_at).toLocaleString()}
        </span>
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          aria-expanded={confirming}
          onClick={() => setConfirming((v) => !v)}
          aria-label={`Roll back to version ${rev.version} of ${rev.kind}`}
        >
          <Undo2 aria-hidden="true" />
          Roll back
        </Button>
      </div>
      {rev.note && <p className="text-sm">{rev.note}</p>}
      <Diff diff={rev.diff} />
      {confirming && (
        <div
          role="group"
          aria-label="Confirm rollback"
          className="grid gap-2 rounded-sm border border-warn bg-warn-soft p-3 text-sm"
        >
          <p>
            Return {rev.kind.replaceAll("_", " ")} to version{" "}
            <b className="num">{rev.version}</b>? This affects future work only.
            Runs already made keep the version they used.
          </p>
          <label className="grid gap-1">
            Reason (optional)
            <Textarea
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={rollback.isPending}
              onClick={() => rollback.mutate()}
            >
              Confirm rollback
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}

/** Settings, Configuration history: revisions with their diff, and rollback with an in-page confirm. */
export function HistoryPage() {
  const [kind, setKind] = useState("")
  const q = useInfiniteQuery({
    queryKey: settingsKeys.config(kind),
    queryFn: ({ pageParam }) => listConfigHistory(kind, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (p) => p.next_cursor ?? undefined,
  })
  const rows = q.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <div>
      <PageHeader
        title="Configuration history"
        description="Rules, prompts, rubrics, model routing and automation policy are versioned. Each run records the versions it used."
        actions={
          <label className="flex items-center gap-2 text-sm">
            Show
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="h-8 rounded-md border border-input bg-surface px-2 text-base field-focus"
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k ? k.replaceAll("_", " ") : "Everything"}
                </option>
              ))}
            </select>
          </label>
        }
      />
      {q.isPending && <p className="text-muted-foreground">Loading...</p>}
      {q.isSuccess && rows.length === 0 && (
        <EmptyState
          icon={History}
          title="No revisions yet"
          description="The first change to a rubric, prompt, rule or policy appears here with its diff."
        />
      )}
      {rows.length > 0 && (
        <ul className="panel p-4">
          {rows.map((r) => (
            <RevisionRow key={r.id} rev={r} />
          ))}
        </ul>
      )}
      {q.hasNextPage && (
        <Button
          className="mt-3"
          variant="outline"
          size="sm"
          onClick={() => q.fetchNextPage()}
        >
          Load older versions
        </Button>
      )}
    </div>
  )
}
