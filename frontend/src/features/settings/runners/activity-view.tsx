import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Chip } from "@/components/chip"
import { Skeleton } from "@/components/ui/skeleton"
import {
  releasesQuery,
  type PendingAction,
  type ReleaseRecord,
} from "@/features/accounts/api"
import {
  BLOCKER_TITLE,
  blockerKind,
  dateText,
  readBlocker,
  roleText,
  waitingOn,
} from "@/features/accounts/logic"
import { pendingQuery } from "@/features/autopilot/api"
import type { RunnerStatus } from "./api"

/** Open blockers this runner raised: the action names it (`runner_id`) or lists one of its tasks. */
export function blockersOf(tokenId: string, actions: PendingAction[]) {
  return actions.filter((a) => {
    if (!blockerKind(a)) return false
    const d = readBlocker(a)
    return (
      d.runnerId === tokenId || d.tasks.some((t) => t.runner_id === tokenId)
    )
  })
}

/** Task ids of this runner named on its blockers. */
const taskIdsOf = (tokenId: string, actions: PendingAction[]) =>
  new Set(
    actions.flatMap((a) => {
      const d = readBlocker(a)
      const own = d.tasks.filter((t) => t.runner_id === tokenId || !t.runner_id)
      return [
        ...own.map((t) => t.task_id),
        ...(a.agent_task_id ? [a.agent_task_id] : []),
      ]
    })
  )

/**
 * What a runner is doing, from what the API offers: its current task (`/api/tokens/runners`),
 * the open blockers it raised (pending actions), and per application what it was given and
 * entered (`/api/applications/{id}/releases`). There is no per-runner task history endpoint.
 */
export function RunnerActivity({ runner }: { runner: RunnerStatus }) {
  const q = useQuery(pendingQuery())
  const blockers = blockersOf(runner.token_id, q.data ?? [])
  const taskIds = taskIdsOf(runner.token_id, blockers)
  const appIds = [
    ...new Set(
      blockers.flatMap((a) => waitingOn(a).map((w) => w.application_id))
    ),
  ]
  const current = runner.current_task_id
  const currentBlocked = !!current && taskIds.has(current)
  return (
    <section
      aria-label={`Recent activity of ${runner.name}`}
      className="grid gap-2"
    >
      <h5 className="eyebrow">Now</h5>
      <p className="text-sm text-muted-foreground">
        {current
          ? currentBlocked
            ? "Its current task is waiting on you (below)."
            : "Working on a task now."
          : "Not holding a task."}{" "}
        Last call {dateText(runner.last_seen_at)}.
      </p>
      <h5 className="eyebrow">Waiting on you</h5>
      {q.isPending && <Skeleton className="h-16 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          Could not load what this runner is waiting on.
        </p>
      )}
      {q.isSuccess && blockers.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Nothing from this runner is waiting on you.
        </p>
      )}
      <ul className="grid gap-2">
        {blockers.map((a) => (
          <BlockerRow key={a.id} action={a} />
        ))}
      </ul>
      {appIds.length > 0 && (
        <>
          <h5 className="eyebrow">Given and entered</h5>
          <ul className="grid gap-2">
            {appIds.map((id) => (
              <Releases key={id} applicationId={id} taskIds={taskIds} />
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function BlockerRow({ action: a }: { action: PendingAction }) {
  const kind = blockerKind(a)
  const waiting = waitingOn(a)
  return (
    <li className="grid gap-1 rounded-md border border-border p-2.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="warn">{kind ? BLOCKER_TITLE[kind] : "Blocked"}</Chip>
        <span className="font-medium">{a.title}</span>
        <span className="text-faint">{dateText(a.created_at)}</span>
        <Link
          to="/accounts/handoff/$actionId"
          params={{ actionId: a.id }}
          className="ml-auto text-primary underline underline-offset-2"
        >
          Open
        </Link>
      </div>
      {waiting.length > 0 && (
        <p className="text-muted-foreground">
          <span className="text-faint">Waiting: </span>
          {waiting.map(roleText).join("; ")}
        </p>
      )}
    </li>
  )
}

const fieldsText = (released: ReleaseRecord["released"]) => {
  const given = Array.isArray(released.given) ? released.given : []
  return given.length
    ? `packet given ${given.length} time${given.length === 1 ? "" : "s"}`
    : "no packet given"
}

function enteredText(entered: ReleaseRecord["entered"]): string | null {
  if (!entered || typeof entered !== "object" || !("at" in entered)) return null
  const answers = Array.isArray(entered.answers) ? entered.answers.length : 0
  const files = Array.isArray(entered.files) ? entered.files.length : 0
  return `asked for a submit permit with ${answers} answer${answers === 1 ? "" : "s"} and ${files} file${files === 1 ? "" : "s"}${typeof entered.at === "string" ? ` (${dateText(entered.at)})` : ""}`
}

function Releases({
  applicationId,
  taskIds,
}: {
  applicationId: string
  taskIds: Set<string>
}) {
  const q = useQuery(releasesQuery(applicationId))
  const mine = (q.data ?? []).filter((r) => taskIds.has(r.agent_task_id))
  if (q.isError)
    return (
      <li className="text-sm text-muted-foreground">
        What was released for one application could not be loaded.
      </li>
    )
  return (
    <>
      {mine.map((r) => {
        const entered = enteredText(r.entered)
        return (
          <li
            key={r.agent_task_id}
            aria-label="Release"
            className="rounded-md bg-sunken px-2 py-1 text-sm text-muted-foreground"
          >
            Task {r.agent_task_id.slice(0, 8)}: {fieldsText(r.released)}
            {entered ? `; ${entered}` : "; nothing entered yet"}.
          </li>
        )
      })}
    </>
  )
}
