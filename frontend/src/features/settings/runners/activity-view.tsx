import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Chip, type ChipTone } from "@/components/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { runnerTasksQuery } from "@/features/accounts/api"
import { BLOCKER_TITLE, dateText } from "@/features/accounts/logic"
import type {
  PermitEvent,
  RunnerTask,
  TaskEvidence,
} from "@/features/accounts/w3-pending-types"

const STATUS: Record<RunnerTask["status"], { label: string; tone: ChipTone }> =
  {
    queued: { label: "Queued", tone: "neutral" },
    running: { label: "Running", tone: "info" },
    blocked: { label: "Waiting on you", tone: "warn" },
    done: { label: "Done", tone: "good" },
    failed: { label: "Failed", tone: "danger" },
  }

const PERMIT: Record<
  PermitEvent["outcome"],
  { label: string; tone: ChipTone }
> = {
  granted: { label: "Permit granted", tone: "good" },
  denied: { label: "Permit denied", tone: "danger" },
  wait_for_owner: { label: "Permit waiting on you", tone: "warn" },
}

const RESULT = {
  submitted: "Submitted",
  uncertain: "Not sure it went",
  failed: "Failed",
} as const

/** Recent tasks of one runner: checkpoints, blockers, permits and results with evidence. */
export function RunnerActivity({
  tokenId,
  name,
}: {
  tokenId: string
  name: string
}) {
  const q = useQuery(runnerTasksQuery(tokenId))
  return (
    <section aria-label={`Recent activity of ${name}`} className="grid gap-2">
      <h5 className="eyebrow">Recent tasks</h5>
      {q.isPending && <Skeleton className="h-16 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          Could not load this runner's tasks.
        </p>
      )}
      {q.isSuccess && q.data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          This runner has not worked on anything yet.
        </p>
      )}
      <ul className="grid gap-2">
        {q.data?.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </ul>
    </section>
  )
}

function TaskRow({ task: t }: { task: RunnerTask }) {
  return (
    <li className="grid gap-1.5 rounded-md border border-border p-2.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={STATUS[t.status].tone}>{STATUS[t.status].label}</Chip>
        <span className="font-medium">{t.title}</span>
        <span className="text-faint">{dateText(t.started_at)}</span>
      </div>
      {t.checkpoints.length > 0 && (
        <p className="text-muted-foreground">
          <span className="text-faint">Checkpoints: </span>
          {t.checkpoints.map((c) => c.step).join(" → ")}
        </p>
      )}
      {t.blockers.length > 0 && (
        <ul className="grid gap-0.5">
          {t.blockers.map((b) => (
            <li key={`${b.at}-${b.kind}`} className="text-muted-foreground">
              <span className="text-faint">Blocker: </span>
              {BLOCKER_TITLE[b.kind]} ({dateText(b.at)})
              {b.action_id && (
                <>
                  {" "}
                  <Link
                    to="/accounts/handoff/$actionId"
                    params={{ actionId: b.action_id }}
                    className="text-primary underline underline-offset-2"
                  >
                    Open
                  </Link>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {t.permits.length > 0 && (
        <ul className="grid gap-0.5">
          {t.permits.map((p) => (
            <li
              key={`${p.at}-${p.outcome}`}
              className="flex flex-wrap items-center gap-1.5"
            >
              <Chip tone={PERMIT[p.outcome].tone}>
                {PERMIT[p.outcome].label}
              </Chip>
              <span className="text-faint">{dateText(p.at)}</span>
              {p.reason && (
                <span className="text-muted-foreground">{p.reason}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {t.result && (
        <div className="grid gap-1">
          <p>
            <span className="text-faint">Result: </span>
            <b className="font-medium">{RESULT[t.result.outcome]}</b>
            {t.result.detail && ` · ${t.result.detail}`}
          </p>
          {t.result.evidence.length > 0 && (
            <ul className="flex flex-wrap gap-2" aria-label="Evidence">
              {t.result.evidence.map((e) => (
                <Evidence key={`${e.kind}-${e.label}`} e={e} />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  )
}

function Evidence({ e }: { e: TaskEvidence }) {
  if (e.kind === "screenshot" && e.url)
    return (
      <li>
        <a
          href={e.url}
          target="_blank"
          rel="noreferrer noopener"
          className="block"
          aria-label={`${e.label} (opens in a new tab)`}
        >
          <img
            src={e.url}
            alt={e.label}
            loading="lazy"
            className="h-16 w-24 rounded-sm border border-border object-cover"
          />
        </a>
      </li>
    )
  if (e.url)
    return (
      <li>
        <a
          href={e.url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-primary underline underline-offset-2"
        >
          {e.label}
        </a>
      </li>
    )
  return (
    <li className="rounded-sm bg-sunken px-2 py-1 text-muted-foreground">
      {e.label}
    </li>
  )
}
