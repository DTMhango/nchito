import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ExternalLink } from "lucide-react"
import { toast } from "sonner"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { PageHeader, SectionHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  appKeys,
  pendingQuery,
  resolveAction,
  type PendingAction,
} from "@/features/applications/api"
import { deadlineText } from "@/features/today/decisions"
import { accountKeys, pendingActionQuery, runnerTasksQuery } from "./api"
import {
  BLOCKER_TITLE,
  blockerKind,
  continueRule,
  dateText,
  nearestDeadline,
  readBlocker,
  resolveBody,
  siblingsOf,
  waitingText,
  type HandoffChoice,
} from "./logic"

const roleLabel = (a: PendingAction) =>
  [a.employer, a.job_title].filter(Boolean).join(", ") || a.title

/** Deep link target for a notification: `/accounts/handoff/$actionId`. */
export function HandoffPage({ actionId }: { actionId: string }) {
  const one = useQuery(pendingActionQuery(actionId))
  const all = useQuery(pendingQuery())
  return (
    <div className="grid max-w-3xl gap-5">
      <PageHeader
        eyebrow="Sign-in handoff"
        title={one.data ? one.data.title : "Sign-in handoff"}
        description="The agent stopped here because only you can do this part. When you are done, tell it to carry on."
      />
      {one.isPending && <Skeleton className="h-48 w-full bg-sunken" />}
      {one.isError && (
        <EmptyState
          title="That request is not available"
          description="It may have been handled already, or the link is wrong."
          actions={
            <Button asChild variant="outline">
              <Link to="/today">Back to Today</Link>
            </Button>
          }
        />
      )}
      {one.data && (
        <HandoffDetail
          action={one.data}
          siblings={siblingsOf(one.data, all.data?.items ?? [])}
        />
      )}
    </div>
  )
}

/** The handoff card: what to do, where, what is waiting, and the choices. */
export function HandoffDetail({
  action,
  siblings,
}: {
  action: PendingAction
  siblings: PendingAction[]
}) {
  const qc = useQueryClient()
  const kind = blockerKind(action)
  const rule = continueRule(kind)
  const d = readBlocker(action)
  const open = action.status === "open"
  const group = siblings.some((s) => s.id === action.id)
    ? siblings
    : [action, ...siblings]
  const deadline = nearestDeadline(group)
  const [done, setDone] = useState<HandoffChoice | null>(null)
  const [error, setError] = useState<string | null>(null)

  const resolve = useMutation({
    mutationFn: async (choice: HandoffChoice) => {
      const body = resolveBody(choice, kind)
      await Promise.all(group.map((a) => resolveAction(a.id, body)))
      return choice
    },
    onSuccess: (choice) => {
      setDone(choice)
      setError(null)
      toast.success(
        choice === "continue" ? "Thank you. The agent is carrying on." : "Done."
      )
      for (const k of [
        appKeys.decisions,
        appKeys.pending,
        appKeys.today,
        appKeys.list,
        accountKeys.action(action.id),
        accountKeys.all,
      ])
        void qc.invalidateQueries({ queryKey: k })
    },
    onError: (e) => setError(e.message),
  })

  return (
    <section aria-label="Sign-in handoff" className="grid gap-4 panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="info">{kind ? BLOCKER_TITLE[kind] : "Blocked"}</Chip>
        {d.portal_name && <h3 className="text-md">{d.portal_name}</h3>}
        {!open && (
          <Chip tone="neutral">
            {action.status === "resolved" ? "Handled" : "Closed"}
          </Chip>
        )}
      </div>

      <dl className="grid gap-3 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-faint">Portal</dt>
        <dd>
          {d.url ? (
            <a
              href={d.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-primary underline underline-offset-2"
            >
              {d.url}
              <ExternalLink className="size-3.5" aria-hidden="true" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            "No link was given."
          )}
        </dd>
        <dt className="text-faint">Do it in</dt>
        <dd>
          {d.runner_name || d.browser_profile ? (
            <>
              <b className="font-medium">{d.runner_name ?? "the runner"}</b>
              {d.browser_profile && <>, {d.browser_profile}</>}. That browser
              holds the session, so the agent can carry on from there.
            </>
          ) : (
            "The browser your runner uses. The agent works in that browser, so a sign-in elsewhere will not help it."
          )}
        </dd>
        <dt className="text-faint">Waiting</dt>
        <dd>
          <p className="font-medium">{waitingText(group.length)}</p>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {group.map((a) => (
              <li key={a.id}>{roleLabel(a)}</li>
            ))}
          </ul>
        </dd>
        <dt className="text-faint">Nearest deadline</dt>
        <dd>{deadline ? deadlineText(deadline, "Due") : "No deadline."}</dd>
        <dt className="text-faint">Reminders</dt>
        <dd>
          {d.reminders
            ? `${d.reminders.sent} sent${
                d.reminders.next_at
                  ? `, next on ${dateText(d.reminders.next_at)}`
                  : ", no more planned"
              }. They come more often as the deadline gets close.`
            : "You will be reminded as the deadline gets close."}
        </dd>
      </dl>

      {rule && open && (
        <p className="text-sm text-muted-foreground">{rule.instruction}</p>
      )}
      {!rule && open && (
        <p className="text-sm text-muted-foreground">
          The agent cannot carry on from this one. You can apply yourself, or
          skip the role.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {open && !done && (
        <div className="flex flex-wrap gap-2">
          {rule && (
            <Button
              disabled={resolve.isPending}
              onClick={() => resolve.mutate("continue")}
            >
              {rule.label}
            </Button>
          )}
          <Button
            variant="outline"
            disabled={resolve.isPending}
            onClick={() => resolve.mutate("apply_myself")}
          >
            Apply myself instead
          </Button>
          <Button
            variant="ghost"
            disabled={resolve.isPending}
            onClick={() => resolve.mutate("skip")}
          >
            Skip
          </Button>
        </div>
      )}
      {done === "continue" && (
        <Resuming
          tokenId={d.runner_token_id ?? null}
          runnerName={d.runner_name}
          applicationIds={group
            .map((a) => a.application_id)
            .filter((x): x is string => !!x)}
        />
      )}
      {done === "apply_myself" && (
        <p role="status" className="text-sm text-muted-foreground">
          The agent will leave this one. Open the portal and apply yourself,
          then mark the application as applied.
        </p>
      )}
      {done === "skip" && (
        <p role="status" className="text-sm text-muted-foreground">
          Skipped. The applications waiting on it will not go ahead.
        </p>
      )}
    </section>
  )
}

/** After continue: the tasks that go back to the same runner, from their checkpoint. */
function Resuming({
  tokenId,
  runnerName,
  applicationIds,
}: {
  tokenId: string | null
  runnerName?: string
  applicationIds: string[]
}) {
  const tasks = useQuery({
    ...runnerTasksQuery(tokenId ?? "none", !!tokenId),
    refetchInterval: 5000,
  })
  const mine = (tasks.data ?? []).filter(
    (t) =>
      t.application_id &&
      applicationIds.includes(t.application_id) &&
      (t.status === "queued" || t.status === "running")
  )
  return (
    <div role="status" className="grid gap-2">
      <SectionHeader
        as="h3"
        title={`Resuming on ${runnerName ?? "the same runner"}`}
        aside="It re-reads the form, re-checks the posting is still open and not a duplicate, then carries on from its last checkpoint. It still needs a submit permit."
      />
      {!tokenId && (
        <p className="text-sm text-muted-foreground">
          The tasks go back to the runner that raised this.
        </p>
      )}
      {tokenId && tasks.isSuccess && mine.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Waiting for the runner to pick them up.
        </p>
      )}
      <ul className="grid gap-1.5">
        {mine.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center gap-2 text-sm">
            <Chip tone={t.status === "running" ? "good" : "info"}>
              {t.status === "running" ? "Running" : "Queued"}
            </Chip>
            <span>{t.title}</span>
            {t.checkpoints.length > 0 && (
              <span className="text-faint">
                from: {t.checkpoints[t.checkpoints.length - 1].step}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
