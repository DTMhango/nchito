import { useInfiniteQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Chip, type ChipTone } from "@/components/chip"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BLOCKER_TITLE, dateText } from "@/features/accounts/logic"
import {
  runnerTasks,
  tokenKeys,
  type RunnerStatus,
  type RunnerTask,
} from "./api"
import { currentTaskText, TASK_TYPE_LABEL } from "./logic"

const DECISION: Record<
  RunnerTask["permit_decisions"][number]["decision"],
  { label: string; tone: ChipTone }
> = {
  granted: { label: "Permit granted", tone: "good" },
  wait_for_owner: { label: "Waiting for you", tone: "warn" },
  denied: { label: "Permit refused", tone: "danger" },
}

const kindTitle = (k: string | null) =>
  (k && (BLOCKER_TITLE as Record<string, string>)[k]) ?? k ?? "Blocked"

/**
 * What a runner did, from `GET /api/tokens/{id}/tasks`: each task it claimed (most recent
 * first) with its checkpoint, the blockers it raised, every permit decision and why, and the
 * result with its evidence. Read-only; paged by the server's cursor.
 */
export function RunnerActivity({ runner }: { runner: RunnerStatus }) {
  const q = useInfiniteQuery({
    queryKey: tokenKeys.tasks(runner.token_id),
    queryFn: ({ pageParam }) => runnerTasks(runner.token_id, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
  const tasks = q.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section
      aria-label={`Recent activity of ${runner.name}`}
      className="grid gap-2"
    >
      <h5 className="eyebrow">Now</h5>
      <p className="text-sm text-muted-foreground">
        {currentTaskText(runner)} Last call {dateText(runner.last_seen_at)}.
      </p>
      <h5 className="eyebrow">Tasks it claimed</h5>
      {q.isPending && <Skeleton className="h-16 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          Could not load what this runner did.
        </p>
      )}
      {q.isSuccess && tasks.length === 0 && (
        <p className="text-sm text-muted-foreground">
          It has not claimed a task yet.
        </p>
      )}
      <ul aria-label="Tasks" className="grid gap-2">
        {tasks.map((t) => (
          <TaskRow key={t.task_id} task={t} />
        ))}
      </ul>
      {q.hasNextPage && (
        <div>
          <Button
            size="sm"
            variant="outline"
            disabled={q.isFetchingNextPage}
            onClick={() => void q.fetchNextPage()}
          >
            Show older tasks
          </Button>
        </div>
      )}
    </section>
  )
}

function TaskRow({ task: t }: { task: RunnerTask }) {
  const cp = t.checkpoint
  return (
    <li
      aria-label={t.title}
      className="grid gap-1.5 rounded-md border border-border p-2.5 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t.title}</span>
        <Chip tone="line">
          {TASK_TYPE_LABEL[t.type] ?? t.type.replaceAll("_", " ")}
        </Chip>
        <Chip tone="neutral">{t.status.replaceAll("_", " ")}</Chip>
        {t.dry_run && <Chip tone="info">Dry run</Chip>}
        <span className="text-faint">
          Claimed {dateText(t.claimed_at)} · {t.steps_used} step
          {t.steps_used === 1 ? "" : "s"}
          {t.attempts > 1 && ` · attempt ${t.attempts}`}
        </span>
      </div>
      {cp && (cp.step || cp.url || cp.fields_filled.length > 0) && (
        <p className="text-muted-foreground">
          <span className="text-faint">Last checkpoint: </span>
          {[
            cp.step,
            cp.fields_filled.length
              ? `${cp.fields_filled.length} field${cp.fields_filled.length === 1 ? "" : "s"} filled`
              : null,
            cp.url,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {t.blockers.length > 0 && (
        <ul aria-label="Blockers" className="grid gap-1">
          {t.blockers.map((b) => (
            <li
              key={b.pending_action_id}
              className="flex flex-wrap items-center gap-2"
            >
              <Chip tone="warn">{kindTitle(b.kind)}</Chip>
              <span>{b.title}</span>
              <span className="text-faint">
                {b.status} · {dateText(b.raised_at)}
              </span>
              <Link
                to="/accounts/handoff/$actionId"
                params={{ actionId: b.pending_action_id }}
                className="ml-auto text-primary underline underline-offset-2"
              >
                Open
              </Link>
            </li>
          ))}
        </ul>
      )}
      {t.permit_decisions.length > 0 && (
        <ul aria-label="Permit decisions" className="grid gap-1">
          {t.permit_decisions.map((p, i) => (
            <li key={`${p.at}-${i}`} className="grid gap-0.5">
              <span className="flex flex-wrap items-center gap-2">
                <Chip tone={DECISION[p.decision].tone}>
                  {DECISION[p.decision].label}
                </Chip>
                <span className="text-faint">{dateText(p.at)}</span>
                {p.reason && <span>{p.reason}</span>}
              </span>
              {p.changes.length > 0 && (
                <span className="text-muted-foreground">
                  Changed since approval: {p.changes.join(", ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {t.result && (t.result.outcome || t.result.detail) && (
        <p>
          <span className="text-faint">Result: </span>
          {[
            t.result.outcome?.replaceAll("_", " "),
            t.result.detail,
            t.result.reference ? `reference ${t.result.reference}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {t.evidence_refs.length > 0 && (
        <p className="text-muted-foreground">
          <span className="text-faint">Evidence: </span>
          {t.evidence_refs.join(", ")}
        </p>
      )}
    </li>
  )
}
