import { useState } from "react"
import { useInfiniteQuery } from "@tanstack/react-query"
import { ScrollText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PageHeader } from "@/components/page-header"
import { EmptyState } from "@/components/empty-state"
import { listAudit, settingsKeys, type AuditFilters } from "./api"

const SUBJECTS = ["", "job", "application", "setting", "campaign", "session"]

/** Settings, Activity log: the append-only audit trail, filterable by action, actor and subject. */
export function ActivityPage() {
  const [draft, setDraft] = useState<AuditFilters>({})
  const [filters, setFilters] = useState<AuditFilters>({})
  const q = useInfiniteQuery({
    queryKey: settingsKeys.audit(filters),
    queryFn: ({ pageParam }) => listAudit(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (p) => p.next_before ?? undefined,
  })
  const rows = q.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div>
      <PageHeader
        title="Activity log"
        description="The append-only audit trail. Every outward action traces to the facts used, the approval or gates that allowed it, the runner and the evidence."
      />
      <form
        role="search"
        aria-label="Filter the activity log"
        className="mb-4 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          setFilters(draft)
        }}
      >
        <label className="grid gap-1 text-sm">
          Action
          <Input
            value={draft.action ?? ""}
            placeholder="e.g. setting.update"
            onChange={(e) => setDraft({ ...draft, action: e.target.value })}
            className="w-[200px]"
          />
        </label>
        <label className="grid gap-1 text-sm">
          Who
          <Input
            value={draft.actor ?? ""}
            placeholder="owner, system, runner"
            onChange={(e) => setDraft({ ...draft, actor: e.target.value })}
            className="w-[180px]"
          />
        </label>
        <label className="grid gap-1 text-sm">
          About
          <select
            value={draft.subject_type ?? ""}
            onChange={(e) =>
              setDraft({ ...draft, subject_type: e.target.value })
            }
            className="h-8 rounded-md border field-focus border-input bg-surface px-2 text-base"
          >
            {SUBJECTS.map((s) => (
              <option key={s} value={s}>
                {s || "Anything"}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" size="sm">
          Apply filters
        </Button>
        {(filters.action || filters.actor || filters.subject_type) && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              setDraft({})
              setFilters({})
            }}
          >
            Clear
          </Button>
        )}
      </form>

      {q.isPending && <p className="text-muted-foreground">Loading...</p>}
      {q.isError && (
        <EmptyState title="Could not load the log" description="Try again." />
      )}
      {q.isSuccess && rows.length === 0 && (
        <EmptyState
          icon={ScrollText}
          title="No events match"
          description="Change or clear the filters to see more."
        />
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto panel">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-faint">
                <th className="p-2.5 font-medium">When</th>
                <th className="p-2.5 font-medium">Who</th>
                <th className="p-2.5 font-medium">What</th>
                <th className="p-2.5 font-medium">About</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border align-top">
                  <td className="p-2.5 num whitespace-nowrap">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                  <td className="p-2.5">{r.actor}</td>
                  <td className="p-2.5">
                    <span className="num font-medium">{r.action}</span>
                    {typeof r.detail.reason === "string" && (
                      <span className="block text-muted-foreground">
                        {r.detail.reason}
                      </span>
                    )}
                  </td>
                  <td className="p-2.5 text-muted-foreground">
                    {r.subject_type
                      ? `${r.subject_type} ${r.subject_id ?? ""}`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {q.hasNextPage && (
        <Button
          className="mt-3"
          variant="outline"
          size="sm"
          disabled={q.isFetchingNextPage}
          onClick={() => q.fetchNextPage()}
        >
          Load older events
        </Button>
      )}
    </div>
  )
}
