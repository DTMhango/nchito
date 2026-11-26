import { useState } from "react"
import { useInfiniteQuery } from "@tanstack/react-query"
import { History } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import { EmptyState } from "@/components/empty-state"
import { listConfigHistory, settingsKeys, type ConfigRevision } from "./api"

/** `ConfigKind` on the server, plus `setting` for every settings change. Empty shows everything. */
const KINDS = [
  "",
  "setting",
  "guardrails",
  "prompt",
  "rubric",
  "model_routing",
  "automation_policy",
  "campaign",
  "template",
]

/** Why the rollback control is not offered: the server answers 501 for it today. */
export const ROLLBACK_UNAVAILABLE =
  "Rolling back is not available yet. To undo a change, set the value again."

const show = (v: unknown) =>
  typeof v === "string" ? v : v === undefined ? "none" : JSON.stringify(v)

/** A setting change is one `{key, old, new}`; other revisions map field to value or to old/new. */
function Diff({ rev }: { rev: ConfigRevision }) {
  const diff = rev.diff
  if (!diff || Object.keys(diff).length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        No field changes recorded.
      </p>
    )
  const entries: [string, unknown][] =
    rev.kind === "setting" && typeof diff.key === "string"
      ? [[diff.key, { old: diff.old, new: diff.new }]]
      : Object.entries(diff)
  return (
    <dl className="grid gap-1 rounded-sm bg-sunken p-3 text-sm">
      {entries.map(([field, v]) => {
        const pair =
          v && typeof v === "object" && ("old" in v || "new" in v)
            ? (v as { old?: unknown; new?: unknown })
            : null
        return (
          <div key={field} className="grid gap-0.5">
            <dt className="num font-medium">{field}</dt>
            {pair ? (
              <dd>
                <span className="text-danger line-through">
                  {show(pair.old)}
                </span>{" "}
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

function RevisionRow({ rev }: { rev: ConfigRevision }) {
  return (
    <li className="grid gap-2 border-t border-border row-pad first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="line">{rev.kind.replaceAll("_", " ")}</Chip>
        <span className="num font-semibold">v{rev.version}</span>
        {rev.rollback_of && <Chip tone="info">A rollback</Chip>}
        <span className="text-sm text-muted-foreground">
          {rev.author}, {new Date(rev.created_at).toLocaleString()}
        </span>
      </div>
      {rev.note && <p className="text-sm">{rev.note}</p>}
      <Diff rev={rev} />
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
        description="Every settings change and every version of rules, prompts, rubrics, model routing and automation policy, newest first. Each run records the versions it used."
        actions={
          <label className="flex items-center gap-2 text-sm">
            Show
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="h-8 rounded-md border field-focus border-input bg-surface px-2 text-base"
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
      <p
        className="mb-3 text-sm text-muted-foreground"
        data-testid="rollback-note"
      >
        {ROLLBACK_UNAVAILABLE}
      </p>
      {q.isPending && <p className="text-muted-foreground">Loading...</p>}
      {q.isError && (
        <p role="alert" className="text-danger">
          {q.error.message}
        </p>
      )}
      {q.isSuccess && rows.length === 0 && (
        <EmptyState
          icon={History}
          title="No revisions yet"
          description="The first change to a setting, rubric, prompt, rule or policy appears here with its diff."
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
