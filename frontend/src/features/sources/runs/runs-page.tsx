import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { toast } from "sonner"
import { FlaskConical, History, Play } from "lucide-react"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { View } from "@/components/view"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { createRun, runsQuery, sourceKeys, type Run } from "../api"
import { formatWhen } from "../cron"
import { useTimezone } from "../shared"
import { cost, KIND_LABEL, triggerLabel } from "../words"
import { Elapsed, RunFunnel, StatusChip } from "./run-bits"
import { useRunEvents } from "./use-run-events"

/** Run history: every sweep, check and backup as a timeline (DESIGN 10.3, Autopilot). */
export function RunsPage() {
  useRunEvents()
  const qc = useQueryClient()
  const tz = useTimezone()
  const q = useQuery(runsQuery())

  const start = useMutation({
    mutationFn: (dry: boolean) => createRun({ kind: "sweep", dry_run: dry }),
    onSuccess: (_d, dry) => {
      qc.invalidateQueries({ queryKey: sourceKeys.runs })
      toast.success(
        dry ? "Dry run started. Nothing will be changed." : "Sweep started"
      )
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <View>
      <PageHeader
        eyebrow="Autopilot"
        title="Run history"
        description="Every sweep and check, newest first, with what it found, what it cost and what went wrong."
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => start.mutate(true)}
              disabled={start.isPending}
            >
              <FlaskConical aria-hidden="true" />
              Dry run
            </Button>
            <Button
              onClick={() => start.mutate(false)}
              disabled={start.isPending}
            >
              <Play aria-hidden="true" />
              Run now
            </Button>
          </>
        }
      />

      {q.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : q.isError ? (
        <EmptyState
          icon={History}
          title="Could not load runs"
          description={q.error.message}
        />
      ) : q.data.length === 0 ? (
        <EmptyState
          icon={History}
          title="No runs yet"
          description="Start a dry run to see what a sweep would do without changing anything."
        />
      ) : (
        <ol aria-label="Runs" className="grid gap-3">
          {q.data.map((r) => (
            <RunCard key={r.id} run={r} tz={tz} />
          ))}
        </ol>
      )}
    </View>
  )
}

function RunCard({ run, tz }: { run: Run; tz: string }) {
  return (
    <li className="grid gap-2 rounded-lg border border-border bg-surface p-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h3 className="text-md font-semibold">
          <Link
            to="/autopilot/runs/$runId"
            params={{ runId: run.id }}
            className="hover:underline focus-visible:outline-2 focus-visible:outline-primary-ink"
          >
            {KIND_LABEL[run.kind]}
            <span className="sr-only">
              , {formatWhen(run.started_at ?? run.created_at, tz)}
            </span>
          </Link>
        </h3>
        <StatusChip run={run} />
        <span className="ml-auto text-sm text-muted-foreground">
          {formatWhen(run.started_at ?? run.created_at, tz)}
        </span>
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-muted-foreground">
        <span>{triggerLabel(run.trigger)}</span>
        <span>
          Took <Elapsed run={run} />
        </span>
        <span>{run.dry_run ? "Nothing changed" : cost(run)}</span>
      </p>
      {run.error && <p className="text-sm text-danger">{run.error}</p>}
      <RunFunnel run={run} />
    </li>
  )
}
