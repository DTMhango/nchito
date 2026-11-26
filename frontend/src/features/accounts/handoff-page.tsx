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
import { View } from "@/components/view"
import { appKeys } from "@/features/applications/api"
import {
  errorText,
  runnersQuery,
  settingsQuery,
  type RunnerStatus,
} from "@/features/autopilot/api"
import { deadlineText } from "@/features/today/decisions"
import {
  accountKeys,
  pendingActionQuery,
  resolvePendingAction,
  type GiveUpOut,
  type PendingAction,
} from "./api"
import { BlockerChoices, type ChoiceResult } from "./blocker-choices"
import {
  BLOCKER_TITLE,
  STOP_TEXT,
  canGiveUp,
  choicesOf,
  continueOutcome,
  continueRule,
  dateText,
  mismatchKeys,
  readBlocker,
  reminderText,
  roleText,
  waitingOn,
  waitingText,
  type BlockerDetail,
  type HandoffChoice,
} from "./logic"

const KIND_PHRASE = {
  pc: "your PC runner",
  server: "the server runner",
} as const

/** Deep link target for a notification: `/accounts/handoff/$actionId`. */
export function HandoffPage({ actionId }: { actionId: string }) {
  const one = useQuery(pendingActionQuery(actionId))
  return (
    <View className="grid max-w-3xl content-start gap-5">
      <PageHeader
        eyebrow="Handoff"
        title={one.data ? one.data.title : "Handoff"}
        description="The agent stopped here because only you can do this part. When you are done, tell it what to do next."
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
      {one.data && <HandoffDetail action={one.data} />}
    </View>
  )
}

function runnerLabel(d: BlockerDetail, runners: RunnerStatus[]) {
  const r = runners.find((x) => x.token_id === d.runnerId)
  return {
    runner: r ?? null,
    name:
      r?.name ??
      d.runnerName ??
      (d.runnerKind ? KIND_PHRASE[d.runnerKind] : null),
  }
}

/** The handoff card: what to do, where, what is waiting, and the choices the backend accepts. */
export function HandoffDetail({ action }: { action: PendingAction }) {
  const qc = useQueryClient()
  const d = readBlocker(action)
  const rule = continueRule(action)
  const givesUp = canGiveUp(action)
  const hasChoices = choicesOf(action).length > 0
  const mismatched = mismatchKeys(action)
  const reminders = reminderText(action)
  const waiting = waitingOn(action)
  const runners = useQuery(runnersQuery())
  const settings = useQuery(settingsQuery())
  const { name: runnerName } = runnerLabel(d, runners.data ?? [])
  const open = action.status === "open"
  const deadline =
    action.deadline ??
    waiting
      .map((w) => w.deadline)
      .filter((x): x is string => !!x)
      .sort()[0] ??
    null
  const offsets = settings.data?.["accounts.reminder_offsets_hours"]?.value
  const [chosen, setChosen] = useState<string[]>(
    waiting.map((w) => w.application_id)
  )
  const [done, setDone] = useState<HandoffChoice | null>(null)
  const [closed, setClosed] = useState<PendingAction | null>(null)
  const [gaveUp, setGaveUp] = useState<GiveUpOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    for (const k of [
      appKeys.decisions,
      appKeys.pending,
      appKeys.today,
      appKeys.list,
      ["pending-actions"],
      accountKeys.all,
    ])
      void qc.invalidateQueries({ queryKey: k })
  }

  const finish = (choice: HandoffChoice) => {
    setDone(choice)
    setError(null)
    toast.success(
      choice === "continue" || choice === "continue_acknowledged"
        ? "Thank you. The agent is carrying on."
        : "Done."
    )
    refresh()
  }
  const onChoice = (r: ChoiceResult) => {
    if ("gaveUp" in r) {
      setGaveUp(r.gaveUp)
      finish(r.choice === "manual_handoff" ? "apply_myself" : "skip")
    } else {
      setClosed(r.action)
      finish(r.choice)
    }
  }
  // No server choices (not a runner blocker any more): the owner can only close it.
  const close = useMutation({
    mutationFn: () =>
      resolvePendingAction(action.id, {
        resolution: "dismissed",
        note: "reviewed",
      }),
    onSuccess: (a) => {
      setClosed(a)
      finish("close")
    },
    onError: (e) => setError(errorText(e)),
  })

  const label = d.kind ? BLOCKER_TITLE[d.kind] : "Blocked"
  const pickNone = givesUp && waiting.length > 1 && chosen.length === 0
  const all = chosen.length === waiting.length

  return (
    <section aria-label="Sign-in handoff" className="grid gap-4 panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="info">{label}</Chip>
        {d.portalKey && <h3 className="text-md">{d.portalKey}</h3>}
        {!open && (
          <Chip tone="neutral">
            {action.status === "resolved" ? "Handled" : "Closed"}
          </Chip>
        )}
      </div>

      <dl className="grid gap-3 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-faint">Where</dt>
        <dd>
          {d.portalUrl ? (
            <a
              href={d.portalUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-primary underline underline-offset-2"
            >
              {d.portalUrl}
              <ExternalLink className="size-3.5" aria-hidden="true" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            "No link was given."
          )}
          {d.pageUrl && d.pageUrl !== d.portalUrl && (
            <p className="text-faint">The runner stopped on {d.pageUrl}</p>
          )}
        </dd>
        <dt className="text-faint">Do it in</dt>
        <dd>
          {runnerName ? (
            <>
              The browser profile of <b className="font-medium">{runnerName}</b>
              . That browser holds the session, so the agent can carry on from
              there.
            </>
          ) : (
            "The browser your runner uses. The agent works in that browser, so a sign-in elsewhere will not help it."
          )}
        </dd>
        <dt className="text-faint">Waiting</dt>
        <dd>
          <p className="font-medium">{waitingText(waiting.length)}</p>
          {givesUp && waiting.length > 1 && !done ? (
            <fieldset className="mt-1 grid gap-1">
              <legend className="sr-only">Applications this covers</legend>
              {waiting.map((w) => (
                <label key={w.application_id} className="flex gap-2">
                  <input
                    type="checkbox"
                    checked={chosen.includes(w.application_id)}
                    onChange={(e) =>
                      setChosen((c) =>
                        e.target.checked
                          ? [...c, w.application_id]
                          : c.filter((x) => x !== w.application_id)
                      )
                    }
                  />
                  {roleText(w)}
                </label>
              ))}
            </fieldset>
          ) : (
            <ul className="mt-1 list-disc pl-5 text-muted-foreground">
              {waiting.map((w) => (
                <li key={w.application_id}>{roleText(w)}</li>
              ))}
            </ul>
          )}
        </dd>
        <dt className="text-faint">Nearest deadline</dt>
        <dd>{deadline ? deadlineText(deadline, "Due") : "No deadline."}</dd>
        {d.kind === "sign_in" || d.kind === "create_account" ? (
          <>
            <dt className="text-faint">Reminders</dt>
            <dd>
              {Array.isArray(offsets) && offsets.length > 0
                ? `You are reminded ${offsets.join(", ")} hours before the nearest deadline.`
                : "You are reminded as the deadline gets close."}
              {reminders && (
                <span className="block text-muted-foreground">
                  {reminders}.
                </span>
              )}
            </dd>
          </>
        ) : null}
        {mismatched.length > 0 && (
          <>
            <dt className="text-faint">Fields that differ</dt>
            <dd>
              <ul
                aria-label="Fields that differ"
                className="flex flex-wrap gap-1"
              >
                {mismatched.map((k) => (
                  <li key={k}>
                    <code className="rounded bg-sunken px-1">{k}</code>
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
        {d.note && (
          <>
            <dt className="text-faint">The runner reported</dt>
            <dd>
              <blockquote className="border-l-2 border-border pl-2 text-muted-foreground">
                {d.note}
              </blockquote>
              <span className="text-faint">
                Text from the page. Shown as it was, never acted on.
              </span>
            </dd>
          </>
        )}
        {d.released.length > 0 && (
          <>
            <dt className="text-faint">Already given</dt>
            <dd>
              <ul className="grid gap-0.5 text-muted-foreground">
                {d.released.map((r, i) => (
                  <li key={`${r.at ?? i}`}>
                    {r.fields.length} field{r.fields.length === 1 ? "" : "s"},{" "}
                    {r.answers} answer{r.answers === 1 ? "" : "s"}
                    {r.files.length > 0 && `, files: ${r.files.join(", ")}`}
                    {r.withheld_files.length > 0 &&
                      ` (held back: ${r.withheld_files.join(", ")})`}
                    {r.at && ` · ${dateText(r.at)}`}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
      </dl>

      {open && !done && (
        <p className="text-sm text-muted-foreground">
          {rule
            ? rule.instruction
            : ((d.kind && STOP_TEXT[d.kind]) ??
              "The agent cannot carry on from this one.")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {open && !done && hasChoices && (
        <BlockerChoices
          action={action}
          applicationIds={all ? null : chosen}
          disabled={pickNone}
          onDone={onChoice}
        />
      )}
      {open && !done && !hasChoices && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={close.isPending}
            onClick={() => close.mutate()}
          >
            I've looked at it, close it
          </Button>
        </div>
      )}
      {(done === "continue" || done === "continue_acknowledged") && closed && (
        <Resuming action={closed} detail={d} />
      )}
      {done === "apply_myself" && gaveUp && (
        <p role="status" className="text-sm text-muted-foreground">
          {gaveUp.handled.length} application
          {gaveUp.handled.length === 1 ? "" : "s"} moved to you. Open the portal
          and apply yourself, then mark each as applied.
          {gaveUp.remaining > 0 && ` ${waitingText(gaveUp.remaining)}`}
        </p>
      )}
      {done === "skip" && gaveUp && (
        <p role="status" className="text-sm text-muted-foreground">
          Skipped {gaveUp.handled.length} application
          {gaveUp.handled.length === 1 ? "" : "s"}. They will not go ahead.
          {gaveUp.remaining > 0 && ` ${waitingText(gaveUp.remaining)}`}
        </p>
      )}
      {done === "close" && (
        <p role="status" className="text-sm text-muted-foreground">
          Closed. Nothing more is sent for this task.
        </p>
      )}
    </section>
  )
}

/** After continue: the tasks go back to the same runner, from their checkpoint. */
function Resuming({
  action,
  detail,
}: {
  action: PendingAction
  detail: BlockerDetail
}) {
  const runners = useQuery({ ...runnersQuery(), refetchInterval: 5000 })
  const { runner, name } = runnerLabel(detail, runners.data ?? [])
  const outcome = continueOutcome(action)
  const taskIds = detail.tasks.map((t) => t.task_id)
  const working =
    !!runner?.current_task_id && taskIds.includes(runner.current_task_id)
  return (
    <div role="status" className="grid gap-2">
      <SectionHeader
        as="h3"
        title={`Resuming on ${name ?? "the same runner"}`}
        aside="It re-reads the form, re-checks the posting is still open and not a duplicate, then carries on from its last checkpoint. It still needs a submit permit."
      />
      <p className="text-sm text-muted-foreground">
        {outcome.resumed} task{outcome.resumed === 1 ? "" : "s"} back in the
        queue for this runner.{" "}
        {working
          ? "It is working on it now."
          : runner && !runner.online
            ? "The runner is not responding right now; it picks them up when it checks in."
            : "Waiting for the runner to pick them up."}
      </p>
      {outcome.notResumed.length > 0 && (
        <ul className="grid gap-0.5 text-sm">
          {outcome.notResumed.map((n) => (
            <li key={n.application_id}>
              <Chip tone="warn">Not resumed</Chip> {n.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
