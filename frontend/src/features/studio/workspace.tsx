import { useEffect } from "react"
import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import { ScoreRing } from "@/components/score-ring"
import { StagePill } from "@/components/stage-pill"
import { isApiError } from "@/lib/api/client"
import {
  ACTIVE_RUN,
  OPEN_TAILORING,
  applicationQuery,
  runQuery,
  specQuery,
  startTailoring,
  studioKeys,
  type SpecState,
} from "./api"
import { isEmptySpec } from "./draft"
import { Editor } from "./editor"
import {
  BudgetPaused,
  NotTailored,
  TailorFailed,
  TailoringProgress,
  runCost,
} from "./states"
import { useStudioEvents } from "./use-studio-events"

/** How often open tailoring is polled when no event arrives (a UI cadence, not a business value). */
export const RUN_POLL_MS = 1500

/** The newest tailored version: a new one replaces the draft on screen; owner saves do not. */
const tailoredVersion = (s: SpecState) =>
  s.versions
    .filter((v) => v.origin === "tailor")
    .reduce((m, v) => Math.max(m, v.version), 0)

function tailorErrorText(e: Error | null): string | null {
  if (!e) return null
  if (isApiError(e, 409))
    return "This application has already gone out, so it can no longer be tailored."
  if (isApiError(e, 402))
    return "The AI budget is used up. Raise the cap in Settings › AI, or wait for the new month."
  return e.message
}

/** One application in the Studio: whatever state its tailoring is in. */
export function StudioWorkspace({
  applicationId,
  runId,
  onRun,
}: {
  applicationId: string
  runId: string | undefined
  onRun: (runId: string | undefined) => void
}) {
  const qc = useQueryClient()
  const app = useQuery(applicationQuery(applicationId))
  const spec = useQuery(specQuery(applicationId, RUN_POLL_MS))
  const run = useQuery(runQuery(runId, RUN_POLL_MS))
  useStudioEvents(applicationId, runId)

  const tailoring = spec.data?.tailoring ?? undefined
  useEffect(() => {
    if (tailoring === "done")
      void qc.invalidateQueries({
        queryKey: studioKeys.application(applicationId),
      })
  }, [tailoring, applicationId, qc])

  const tailor = useMutation({
    mutationFn: () => startTailoring(applicationId),
    onSuccess: (out) => {
      if (out.run_id) onRun(out.run_id)
      void qc.invalidateQueries({
        queryKey: studioKeys.application(applicationId),
      })
    },
  })
  const tailorError = tailorErrorText(tailor.error)

  if (app.isPending || spec.isPending)
    return (
      <p role="status" className="text-muted-foreground">
        Loading the application...
      </p>
    )
  if (app.isError || spec.isError) {
    const error = app.error ?? spec.error
    const gone = isApiError(error, 404)
    return (
      <section role="alert" className="grid max-w-[560px] gap-3 panel p-5">
        <h2 className="text-lg">
          {gone
            ? "This application doesn't exist"
            : "Could not load the application"}
        </h2>
        <p className="text-muted-foreground">
          {gone ? "It may have been merged or removed." : error?.message}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => {
              void app.refetch()
              void spec.refetch()
            }}
          >
            Try again
          </Button>
          <Button asChild variant="ghost">
            <Link to="/studio" search={{}}>
              Choose another application
            </Link>
          </Button>
        </div>
      </section>
    )
  }

  const a = app.data
  const s = spec.data
  const r = run.data
  const empty = isEmptySpec(s.spec)
  const working = !!tailoring && OPEN_TAILORING.has(tailoring)
  const retry = () => tailor.mutate()
  const error = s.tailoring_error ?? tailorError

  let body
  if (working) body = <TailoringProgress status={tailoring} run={r} />
  else if (tailoring === "paused" && empty)
    body = (
      <BudgetPaused
        run={r}
        error={s.tailoring_error}
        onRetry={retry}
        retrying={tailor.isPending}
      />
    )
  else if (tailoring === "failed" && empty)
    body = (
      <TailorFailed
        run={r}
        error={s.tailoring_error}
        onRetry={retry}
        retrying={tailor.isPending}
      />
    )
  else if (empty)
    body = (
      <NotTailored onTailor={retry} pending={tailor.isPending} error={error} />
    )
  else
    body = (
      <>
        {(tailoring === "paused" || tailoring === "failed" || tailorError) && (
          <p
            role="status"
            className="mb-3 rounded-sm bg-warn-soft px-3 py-2 text-sm text-warn"
          >
            {tailoring === "paused"
              ? "Tailoring again is paused: the AI budget is used up. This draft stays as it is."
              : (error ??
                "Tailoring again did not finish. This draft stays as it is.")}
          </p>
        )}
        <Editor
          key={`${a.id}:${tailoredVersion(s)}`}
          app={a}
          state={s}
          onRetailor={retry}
        />
      </>
    )

  return (
    <div>
      <PageHeader
        eyebrow={<>Studio · {a.employer}</>}
        title={
          <span className="inline-flex items-center gap-3">
            {a.score != null && <ScoreRing score={a.score} size={40} />}
            {a.title}
          </span>
        }
        meta={
          <>
            <StagePill stage={a.stage} />
            {r && !ACTIVE_RUN.has(r.status) && !working && (
              <Chip tone="line" data-testid="tailor-cost-chip">
                Tailoring cost {runCost(r)}
              </Chip>
            )}
          </>
        }
        actions={
          <Button asChild size="sm" variant="ghost">
            <Link
              to="/jobs/$id"
              params={{ id: a.job_id }}
              search={{ tab: "documents" }}
            >
              Job page
            </Link>
          </Button>
        }
      />
      {body}
    </div>
  )
}
