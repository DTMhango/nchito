import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { toast } from "sonner"
import { ArrowLeft, History, Square } from "lucide-react"
import { Chip } from "@/components/chip"
import { DataTable, type Column } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
import { PageHeader, SectionHeader } from "@/components/page-header"
import { View } from "@/components/view"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  cancelRun,
  isActive,
  runQuery,
  sourceKeys,
  sourcesQuery,
  type SourceRunResult,
} from "../api"
import { formatWhen } from "../cron"
import { sourceName, useTimezone } from "../shared"
import { cost, KIND_LABEL, plainError, triggerLabel } from "../words"
import { DryRunBanner, Elapsed, RunFunnel, StatusChip } from "./run-bits"
import { useRunEvents } from "./use-run-events"

const RESULT_TONE = {
  ok: "good",
  failed: "danger",
  skipped: "neutral",
} as const
const RESULT_LABEL = {
  ok: "Worked",
  failed: "Failed",
  skipped: "Skipped",
} as const

export function RunDetailPage({ runId }: { runId: string }) {
  useRunEvents()
  const qc = useQueryClient()
  const tz = useTimezone()
  const q = useQuery(runQuery(runId))
  const sources = useQuery(sourcesQuery())

  const cancel = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sourceKeys.run(runId) })
      qc.invalidateQueries({ queryKey: sourceKeys.runs })
      toast.success("Run cancelled")
    },
    onError: (e) => toast.error(e.message),
  })

  const back = (
    <Button asChild variant="ghost" size="sm" className="mb-3">
      <Link to="/autopilot/runs">
        <ArrowLeft aria-hidden="true" />
        Run history
      </Link>
    </Button>
  )

  if (q.isPending)
    return (
      <View>
        {back}
        <Skeleton className="h-64 w-full" />
      </View>
    )
  if (q.isError)
    return (
      <View>
        {back}
        <EmptyState
          icon={History}
          title="Could not load this run"
          description={q.error.message}
        />
      </View>
    )

  const run = q.data
  const active = isActive(run.status)
  const enabledCount = sources.data?.filter((s) => s.enabled).length ?? 0
  const columns: Column<SourceRunResult>[] = [
    {
      id: "source",
      header: "Source",
      cell: (r) => (
        <span className="font-medium">
          {sourceName(sources.data, r.source_id)}
        </span>
      ),
    },
    {
      id: "status",
      header: "Result",
      cell: (r) => (
        <Chip tone={RESULT_TONE[r.status]}>{RESULT_LABEL[r.status]}</Chip>
      ),
    },
    {
      id: "found",
      header: "Found",
      align: "right",
      cell: (r) => <span className="num">{r.found ?? 0}</span>,
    },
    {
      id: "new",
      header: "New",
      align: "right",
      cell: (r) => <span className="num">{r.new ?? 0}</span>,
    },
    {
      id: "error",
      header: "What went wrong",
      cell: (r) =>
        r.error ? (
          <span className="grid max-w-[46ch] gap-0.5">
            <span>{plainError(r.error)}</span>
            <span className="text-xs text-faint">{r.error}</span>
          </span>
        ) : (
          <span className="text-faint">Nothing</span>
        ),
    },
  ]

  return (
    <View>
      {back}
      <PageHeader
        eyebrow={KIND_LABEL[run.kind]}
        title={formatWhen(run.started_at ?? run.created_at, tz)}
        meta={<StatusChip run={run} />}
        description={
          <>
            {triggerLabel(run.trigger)}. Took <Elapsed run={run} />.{" "}
            {run.dry_run ? "No cost." : `Cost ${cost(run)}.`}
          </>
        }
        actions={
          active && (
            <Button
              variant="outline"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
            >
              <Square aria-hidden="true" />
              Cancel run
            </Button>
          )
        }
      />

      {run.status === "paused" && (
        <p
          role="status"
          className="mb-5 rounded-lg border border-warn bg-warn-soft p-4 text-sm"
        >
          Paused: monthly budget reached. It resumes where it stopped when you
          raise the cap or the month turns over.{" "}
          <Link to="/settings/ai">Settings &gt; AI</Link>
        </p>
      )}

      {run.dry_run && <DryRunBanner run={run} />}

      {active && (
        <p
          role="status"
          className="mb-4 flex items-center gap-2 text-sm text-muted-foreground"
        >
          <span
            className="size-2 animate-pulse rounded-full bg-info"
            aria-hidden="true"
          />
          Running now.{" "}
          {enabledCount > 0 &&
            `${run.source_results.length} of ${enabledCount} sources done.`}
        </p>
      )}
      {run.error && (
        <p role="alert" className="mb-4 text-sm text-danger">
          {run.error}
        </p>
      )}

      <div className="mb-6">
        <RunFunnel run={run} />
      </div>

      <SectionHeader
        title="Results by source"
        aside={`${run.source_results.length} reported`}
      />
      <DataTable
        columns={columns}
        rows={run.source_results}
        getRowId={(r) => r.source_id}
        caption="Results by source"
        empty={
          <EmptyState
            title={
              active ? "Waiting for the first source" : "No sources were used"
            }
            description={
              active
                ? "Each source appears here as it finishes."
                : "This kind of run does not read job sources."
            }
          />
        }
      />
    </View>
  )
}
