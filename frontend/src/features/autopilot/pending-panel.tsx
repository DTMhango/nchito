import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { NativeSelect } from "@/features/campaigns/bits"
import {
  errorText,
  pendingQuery,
  reconcileDispatch,
  resolvePending,
  settingsQuery,
  type PendingAction,
  type ResolveIn,
} from "./api"
import {
  BlockerChoices,
  type ChoiceResult,
} from "@/features/accounts/blocker-choices"
import {
  BLOCKER_KINDS,
  BLOCKER_TITLE,
  STOP_TEXT,
  blockerKind,
  isHandoff,
  mismatchKeys,
  reminderText,
  type BlockerKind,
} from "@/features/accounts/logic"
import { answerOptions, pendingInfo, roleChoices } from "./logic"

type Scope = NonNullable<ResolveIn["answer_scope"]>
const SCOPES: { value: Scope; label: string }[] = [
  { value: "this_application", label: "This application only" },
  { value: "this_employer", label: "This employer" },
  { value: "this_country", label: "This country" },
  { value: "all_matching", label: "Every matching question" },
]

/** A runner blocker with its own owner choices (a question is answered in its row instead). */
const isBlocker = (a: PendingAction) =>
  a.type !== "unknown_question" && isHandoff(a)

/** Everything waiting on the owner, each type with the choices it really has (DESIGN 8.4). */
export function PendingPanel() {
  const [kind, setKind] = useState<BlockerKind | null>(null)
  const q = useQuery(pendingQuery(kind))
  const items = q.data ?? []
  return (
    <section aria-label="Waiting on you" className="grid gap-3">
      <SectionHeader
        title="Waiting on you"
        aside="Each one says what the system is waiting for."
      />
      <label className="flex max-w-sm items-center gap-2 text-sm">
        Show
        <NativeSelect
          aria-label="Show what is waiting"
          value={kind ?? ""}
          onChange={(e) =>
            setKind((e.target.value || null) as BlockerKind | null)
          }
        >
          <option value="">Everything</option>
          {BLOCKER_KINDS.map((k) => (
            <option key={k} value={k}>
              {BLOCKER_TITLE[k]}
            </option>
          ))}
        </NativeSelect>
      </label>
      {q.isSuccess && items.length === 0 && (
        <EmptyState
          title={
            kind ? "None of these is waiting" : "Nothing is waiting on you"
          }
          description="Approvals, sign-ins and new questions show up here."
        />
      )}
      <ul aria-label="Waiting items" className="grid gap-2.5">
        {items.map((a) =>
          isBlocker(a) ? (
            <BlockerRow key={a.id} action={a} />
          ) : (
            <PendingRow key={a.id} action={a} />
          )
        )}
      </ul>
    </section>
  )
}

/** A runner blocker: the server's choices as buttons, its reminders and any differing fields. */
function BlockerRow({ action }: { action: PendingAction }) {
  const qc = useQueryClient()
  const kind = blockerKind(action)
  const info = pendingInfo(action)
  const reminders = reminderText(action)
  const keys = mismatchKeys(action)
  const done = (r: ChoiceResult) => {
    toast.success(
      r.choice === "continue" || r.choice === "continue_acknowledged"
        ? "Thank you. The agent is carrying on."
        : "Done."
    )
    for (const k of [
      ["pending-actions"],
      ["applications"],
      ["autopilot"],
      ["today"],
    ])
      void qc.invalidateQueries({ queryKey: k })
  }
  return (
    <li
      aria-label={action.title}
      className="grid gap-2 rounded-lg border border-border bg-surface p-3.5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="info">{kind ? BLOCKER_TITLE[kind] : info.label}</Chip>
        <h4 className="text-md">{action.title}</h4>
        {action.employer && (
          <span className="text-sm text-faint">{action.employer}</span>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        {(kind && STOP_TEXT[kind]) ?? info.waiting}
      </p>
      {keys.length > 0 && (
        <p className="text-sm">
          <span className="text-faint">Fields that differ: </span>
          {keys.join(", ")}
        </p>
      )}
      {reminders && (
        <p className="text-sm text-faint">Reminders: {reminders}.</p>
      )}
      <div className="flex flex-wrap items-start gap-2">
        <BlockerChoices action={action} onDone={done} />
        <Button asChild type="button" variant="outline">
          <Link
            to="/accounts/handoff/$actionId"
            params={{ actionId: action.id }}
          >
            Details and other choices
          </Link>
        </Button>
      </div>
    </li>
  )
}

function PendingRow({ action }: { action: PendingAction }) {
  const info = pendingInfo(action)
  const qc = useQueryClient()
  const settings = useQuery(settingsQuery())
  const detail = action.detail as Record<string, unknown>
  const material = detail.material === true
  const defaultScope = (settings.data?.[
    material
      ? "answers.material_default_scope"
      : "answers.routine_default_scope"
  ]?.value ?? (material ? "this_application" : "all_matching")) as Scope

  const [answer, setAnswer] = useState("")
  const [scope, setScope] = useState<Scope | null>(null)
  const [chosen, setChosen] = useState("")
  const [reference, setReference] = useState("")
  const [error, setError] = useState<string | null>(null)

  const resolve = useMutation({
    mutationFn: (body: ResolveIn) => resolvePending(action.id, body),
    onSuccess: (_d, body) => {
      toast.success(
        body.resolution === "dismissed" ? "Dismissed." : "Done. Thank you."
      )
      void qc.invalidateQueries({ queryKey: ["pending-actions"] })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      void qc.invalidateQueries({ queryKey: ["autopilot"] })
      void qc.invalidateQueries({ queryKey: ["today"] })
    },
    onError: (e) => setError(errorText(e)),
  })
  // "Did not go out" is the attempt's reconcile with not_sent, not a resolution.
  const notSent = useMutation({
    mutationFn: () =>
      reconcileDispatch(action.application_id!, String(detail.attempt_id), {
        decision: "not_sent",
      }),
    onSuccess: () => {
      toast.success("Recorded: it did not go out.")
      void qc.invalidateQueries({ queryKey: ["pending-actions"] })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      void qc.invalidateQueries({ queryKey: ["autopilot"] })
    },
    onError: (e) => setError(errorText(e)),
  })

  const options = answerOptions(detail)
  const choices = roleChoices(detail)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (info.kind === "answer") {
      if (!answer.trim()) return setError("Give an answer first.")
      return resolve.mutate({
        resolution: "answered",
        answer_value: answer.trim(),
        answer_scope: scope ?? defaultScope,
      })
    }
    if (info.kind === "choose") {
      if (!chosen) return setError("Choose one role first.")
      return resolve.mutate({ resolution: "chosen", chosen_job_id: chosen })
    }
    if (info.kind === "submitted")
      return resolve.mutate({
        resolution: "confirmed",
        reference: reference.trim() || null,
      })
    if (info.resolution) resolve.mutate({ resolution: info.resolution })
  }

  return (
    <li
      aria-label={action.title}
      className="grid gap-2 rounded-lg border border-border bg-surface p-3.5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="info">{info.label}</Chip>
        <h4 className="text-md">{action.title}</h4>
        {action.employer && (
          <span className="text-sm text-faint">{action.employer}</span>
        )}
      </div>
      <p className="text-sm text-muted-foreground">{info.waiting}</p>
      <form onSubmit={submit} className="grid gap-2">
        {info.kind === "answer" && (
          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
            {options.length > 0 ? (
              <NativeSelect
                aria-label="Your answer"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              >
                <option value="">Choose an answer</option>
                {options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </NativeSelect>
            ) : (
              <Input
                aria-label="Your answer"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              />
            )}
            <NativeSelect
              aria-label="Use this answer for"
              value={scope ?? defaultScope}
              onChange={(e) => setScope(e.target.value as Scope)}
            >
              {SCOPES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
        {info.kind === "choose" && (
          <fieldset className="grid gap-1">
            <legend className="sr-only">Which role</legend>
            {choices.map((c) => (
              <label key={c.job_id} className="flex gap-2 text-sm">
                <input
                  type="radio"
                  name={`choice-${action.id}`}
                  value={c.job_id}
                  checked={chosen === c.job_id}
                  onChange={() => setChosen(c.job_id)}
                />
                {c.label}
              </label>
            ))}
            {choices.length === 0 && (
              <p className="text-sm text-muted-foreground">
                The roles to choose between are on the application.
              </p>
            )}
          </fieldset>
        )}
        {info.kind === "submitted" && (
          <label className="grid max-w-sm gap-1 text-sm font-medium">
            Reference or what you saw (optional)
            <Input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Confirmation number or email subject"
            />
          </label>
        )}
        {info.kind === "proposal" &&
          typeof detail.subject === "string" &&
          detail.subject && (
            <p className="text-sm">
              <span className="text-faint">Message: </span>
              {detail.subject}
            </p>
          )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {info.kind === "handoff" ? (
            <Button asChild>
              <Link
                to="/accounts/handoff/$actionId"
                params={{ actionId: action.id }}
              >
                {info.primary}
              </Link>
            </Button>
          ) : info.kind === "changes" ? (
            typeof detail.job_id === "string" ? (
              <Button asChild>
                <Link
                  to="/jobs/$id"
                  params={{ id: detail.job_id }}
                  search={{ tab: "changes" }}
                >
                  {info.primary}
                </Link>
              </Button>
            ) : null
          ) : info.kind === "review" ? (
            action.application_id ? (
              <Button asChild>
                <Link
                  to="/approvals/$applicationId"
                  params={{ applicationId: action.application_id }}
                >
                  {info.primary}
                </Link>
              </Button>
            ) : null
          ) : (
            <Button type="submit" disabled={resolve.isPending}>
              {info.primary}
            </Button>
          )}
          {info.kind === "submitted" &&
            action.application_id &&
            typeof detail.attempt_id === "string" && (
              <Button
                type="button"
                variant="outline"
                disabled={notSent.isPending}
                onClick={() => notSent.mutate()}
              >
                It did not go out
              </Button>
            )}
          {isHandoff(action) && info.kind !== "handoff" && (
            <Button asChild type="button" variant="outline">
              <Link
                to="/accounts/handoff/$actionId"
                params={{ actionId: action.id }}
              >
                Details and other choices
              </Link>
            </Button>
          )}
          <Button
            type="button"
            variant="ghost"
            disabled={resolve.isPending}
            onClick={() => resolve.mutate({ resolution: "dismissed" })}
          >
            Dismiss
          </Button>
        </div>
      </form>
    </li>
  )
}
