import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Radio } from "lucide-react"
import { Chip } from "@/components/chip"
import { DataTable, type Column } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  sourceKeys,
  sourcesQuery,
  toSourceInput,
  updateSource,
  type Source,
} from "./api"
import { AddSourceDialog } from "./add-source-dialog"
import { SourceDrawer } from "./source-drawer"
import { HealthDot } from "./shared"
import { ACCESS_LABEL, ago, plainError } from "./words"

/** The connector registry with health, last success and last problem in plain words. */
export function SourceList() {
  const qc = useQueryClient()
  const q = useQuery(sourcesQuery())
  const [open, setOpen] = useState<string | null>(null)

  const toggle = useMutation({
    mutationFn: (s: Source) =>
      updateSource(s.id, { ...toSourceInput(s), enabled: !s.enabled }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: sourceKeys.sources })
      toast.success(`${s.name} ${s.enabled ? "turned on" : "turned off"}`)
    },
    onError: (e) => toast.error(e.message),
  })

  if (q.isPending) return <Skeleton className="h-48 w-full" />
  if (q.isError)
    return (
      <EmptyState
        icon={Radio}
        title="Could not load sources"
        description={q.error.message}
      />
    )

  const columns: Column<Source>[] = [
    {
      id: "name",
      header: "Source",
      sortValue: (s) => s.name,
      cell: (s) => (
        <div className="grid gap-0.5">
          <button
            type="button"
            onClick={() => setOpen(s.id)}
            className="w-fit rounded-xs text-left font-medium hover:underline focus-visible:outline-2 focus-visible:outline-primary-ink"
          >
            {s.name}
            <span className="sr-only">: open settings</span>
          </button>
          <span className="text-xs text-muted-foreground">
            {ACCESS_LABEL[s.access]}
          </span>
          {s.health.last_error && (
            <span className="max-w-[46ch] text-xs text-warn md:hidden">
              {plainError(s.health.last_error)}
            </span>
          )}
        </div>
      ),
    },
    {
      id: "health",
      header: "Health",
      sortValue: (s) => s.health.status,
      cell: (s) => <HealthDot status={s.health.status} />,
    },
    {
      id: "last",
      header: "Last success",
      hideBelow: "md",
      sortValue: (s) => s.last_success_at ?? "",
      cell: (s) => (
        <span className="text-muted-foreground">{ago(s.last_success_at)}</span>
      ),
    },
    {
      id: "error",
      header: "Last problem",
      hideBelow: "md",
      cell: (s) =>
        s.health.last_error ? (
          <span className="grid max-w-[44ch] gap-0.5">
            <span>{plainError(s.health.last_error)}</span>
            {s.health.consecutive_failures > 1 && (
              <Chip tone="warn" className="w-fit">
                {s.health.consecutive_failures} failures in a row
              </Chip>
            )}
          </span>
        ) : (
          <span className="text-faint">None</span>
        ),
    },
    {
      id: "enabled",
      header: "On",
      align: "right",
      cell: (s) => (
        <Switch
          checked={s.enabled ?? true}
          onCheckedChange={() => toggle.mutate(s)}
          aria-label={`Use ${s.name}`}
        />
      ),
    },
  ]

  const current = q.data.find((s) => s.id === open) ?? null

  return (
    <>
      <div className="mb-3 flex justify-end">
        <AddSourceDialog />
      </div>
      <DataTable
        columns={columns}
        rows={q.data}
        getRowId={(s) => s.id}
        caption="Sources"
        empty={
          <EmptyState
            icon={Radio}
            title="No sources yet"
            description="Board sources appear as you watch employers. Add a careers page, web search or JobSpy source above."
          />
        }
      />
      <SourceDrawer source={current} onClose={() => setOpen(null)} />
    </>
  )
}
