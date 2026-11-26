import { useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import {
  CheckCircle2,
  ChevronDown,
  FileCheck2,
  FileDiff,
  FileWarning,
  HelpCircle,
  KeyRound,
  MailCheck,
  ShieldQuestion,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"
import { CountBadge } from "@/components/chip"
import { SeverityItem } from "@/components/severity-item"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  appKeys,
  decisionsQuery,
  resolveAction,
  type DecisionGroup,
  type PendingAction,
} from "@/features/applications/api"
import { giveUp } from "@/features/accounts/api"
import { giveUpBody, isHandoff } from "@/features/accounts/logic"
import { AnswerForm, type AnswerSubmit } from "./answer-form"
import {
  actionKit,
  changeJobId,
  changeKind,
  deadlineText,
  readDetail,
  urgency,
  type KitResolution,
} from "./decisions"

const TYPE_ICON: Partial<Record<PendingAction["type"], LucideIcon>> = {
  unknown_question: HelpCircle,
  sign_in: KeyRound,
  create_account: KeyRound,
  captcha: KeyRound,
  approve: FileCheck2,
  confirm_submission: MailCheck,
  declaration: ShieldQuestion,
  unsupported_form: FileWarning,
  redirect_off_domain: ShieldQuestion,
  page_instruction: ShieldQuestion,
}

/** Refetch everything a resolved decision can change. */
export function useRefreshDecisions() {
  const qc = useQueryClient()
  return () => {
    for (const k of [
      appKeys.decisions,
      appKeys.pending,
      appKeys.today,
      appKeys.list,
    ])
      void qc.invalidateQueries({ queryKey: k })
  }
}

/** One decision: actions that share a blocker are resolved together. */
export function DecisionRow({
  group,
  focused = false,
}: {
  group: DecisionGroup
  /** Opened from a deep link (`/today?action=`): scrolled to, and a question opens its answer form. */
  focused?: boolean
}) {
  const refresh = useRefreshDecisions()
  const first = group.actions[0]
  const n = group.actions.length
  const kit = actionKit(first, n)
  const [answering, setAnswering] = useState(
    focused && kit.primary.resolution === "answer"
  )
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView?.({ block: "center" })
  }, [focused])
  const detail = readDetail(first)
  const roles = group.actions.map((a) => {
    const d = readDetail(a)
    return d.employer ? `${d.employer}${d.role ? `, ${d.role}` : ""}` : a.title
  })

  const resolve = useMutation({
    mutationFn: async (
      body: Parameters<typeof resolveAction>[1]
    ): Promise<void> => {
      // One continue closes every action sharing the blocker (the backend does it), so send it once.
      const targets = body.resolution === "continue" ? [first] : group.actions
      await Promise.all(targets.map((a) => resolveAction(a.id, body)))
    },
    onSuccess: () => {
      refresh()
      setAnswering(false)
    },
    onError: (e) => toast.error(e.message),
  })

  // "Skip" on a blocker is the give-up endpoint: every waiting application is skipped and the action closes.
  const skip = useMutation({
    mutationFn: () => giveUp(first.id, giveUpBody("skip", null)),
    onSuccess: refresh,
    onError: (e) => toast.error(e.message),
  })

  const answer = (v: AnswerSubmit) =>
    resolve.mutate({
      resolution: "answered",
      answer_value: v.answer,
      answer_scope: v.scope,
    })

  const run = (r: KitResolution) => {
    if (r === "answer") setAnswering(true)
    else if (r === "skip") skip.mutate()
    else if (r !== "link" && r !== "handoff" && r !== "changes")
      resolve.mutate({ resolution: r })
  }
  const jobId = changeJobId(first)

  const deadline = group.nearest_deadline
  const verb = first.type === "unknown_question" ? "Closes" : "Due"
  const secondary = kit.secondary
  const primaryIsLink = kit.primary.resolution === "link"

  return (
    <div
      ref={ref}
      data-focused={focused || undefined}
      aria-current={focused || undefined}
      className={focused ? "bg-info-soft" : undefined}
    >
      <SeverityItem
        severity={urgency(deadline)}
        icon={
          changeKind(first) ? FileDiff : (TYPE_ICON[first.type] ?? HelpCircle)
        }
        title={group.title}
        meta={
          <>
            {group.consequence}
            {deadline && (
              <>
                {" "}
                <b className="font-semibold text-foreground">
                  {deadlineText(deadline, verb)}.
                </b>
              </>
            )}
          </>
        }
        actions={
          !answering && (
            <>
              {n > 1 && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-expanded={open}
                  onClick={() => setOpen((o) => !o)}
                >
                  {n} roles
                  <ChevronDown
                    className={open ? "rotate-180" : undefined}
                    aria-hidden="true"
                  />
                </Button>
              )}
              {isHandoff(first) && kit.primary.resolution !== "handoff" && (
                <Button asChild variant="ghost" size="sm">
                  <Link
                    to="/accounts/handoff/$actionId"
                    params={{ actionId: first.id }}
                  >
                    Details
                  </Link>
                </Button>
              )}
              {secondary?.resolution === "link" ? (
                detail.url && (
                  <Button asChild variant="outline" size="sm">
                    <a
                      href={detail.url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {secondary.label}
                    </a>
                  </Button>
                )
              ) : secondary ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={resolve.isPending || skip.isPending}
                  onClick={() => run(secondary.resolution)}
                >
                  {secondary.label}
                </Button>
              ) : null}
              {kit.primary.resolution === "changes" && jobId ? (
                <Button asChild size="sm">
                  <Link
                    to="/jobs/$id"
                    params={{ id: jobId }}
                    search={{ tab: "changes" }}
                  >
                    {kit.primary.label}
                  </Link>
                </Button>
              ) : kit.primary.resolution === "changes" ? null : kit.primary
                  .resolution === "handoff" ? (
                <Button asChild size="sm">
                  <Link
                    to="/accounts/handoff/$actionId"
                    params={{ actionId: first.id }}
                  >
                    {kit.primary.label}
                  </Link>
                </Button>
              ) : primaryIsLink &&
                first.type === "approve" &&
                first.application_id ? (
                <Button asChild size="sm">
                  <Link
                    to="/approvals/$applicationId"
                    params={{ applicationId: first.application_id }}
                  >
                    {kit.primary.label}
                  </Link>
                </Button>
              ) : primaryIsLink ? (
                <Button asChild size="sm">
                  <Link
                    to="/studio"
                    search={{ application: first.application_id ?? undefined }}
                  >
                    {kit.primary.label}
                  </Link>
                </Button>
              ) : (
                <Button
                  size="sm"
                  disabled={resolve.isPending}
                  onClick={() => run(kit.primary.resolution)}
                >
                  {kit.primary.label}
                </Button>
              )}
            </>
          )
        }
      >
        {open && !answering && (
          <ul className="w-full list-disc pl-5 text-[0.9rem] text-muted-foreground">
            {group.actions.map((a, i) => (
              <li key={a.id}>
                {roles[i]}
                {a.deadline &&
                  ` (${deadlineText(a.deadline, "closes").toLowerCase()})`}
              </li>
            ))}
          </ul>
        )}
        {answering && (
          <AnswerForm
            action={first}
            affected={roles}
            busy={resolve.isPending}
            onSubmit={answer}
            onCancel={() => setAnswering(false)}
          />
        )}
      </SeverityItem>
    </div>
  )
}

/** "Needs you": the one elevated surface on Today (DESIGN 10.1, 18.4). */
export function NeedsYou({ focusAction }: { focusAction?: string } = {}) {
  const q = useQuery(decisionsQuery())
  const groups = q.data ?? []
  const holds = (g: DecisionGroup) =>
    !!focusAction && g.actions.some((a) => a.id === focusAction)
  const missing = !!focusAction && q.isSuccess && !groups.some(holds)
  // Notifications link blockers to `/today?action=`; their choices live on the handoff page.
  const navigate = useNavigate()
  const blocker = focusAction
    ? groups.flatMap((g) => g.actions).find((a) => a.id === focusAction)
    : undefined
  const toHandoff = blocker && isHandoff(blocker) ? blocker.id : null
  useEffect(() => {
    if (toHandoff)
      void navigate({
        to: "/accounts/handoff/$actionId",
        params: { actionId: toHandoff },
        replace: true,
      })
  }, [toHandoff, navigate])
  return (
    <section aria-labelledby="needs-title" className="elev py-1.5">
      <div className="flex items-center gap-2.5 px-4.5 pt-2.5 pb-2">
        <h2 id="needs-title" className="text-[1.12rem]">
          Needs you
        </h2>
        <CountBadge>{groups.length}</CountBadge>
        <span className="ml-auto text-[0.84rem] text-faint">
          {groups.length === 0
            ? "Nothing is waiting on you"
            : "Everything else is running"}
        </span>
      </div>
      {missing && (
        <p
          role="status"
          className="border-t border-border px-4.5 py-2.5 text-sm text-muted-foreground"
        >
          That question is no longer waiting for you. It may already be
          answered.
        </p>
      )}
      {q.isPending ? (
        <div className="grid gap-2 border-t border-border p-4.5">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : q.isError ? (
        <div
          role="alert"
          className="border-t border-border px-4.5 py-4 text-sm text-danger"
        >
          Couldn't load your decisions. {q.error.message}{" "}
          <Button variant="link" size="xs" onClick={() => void q.refetch()}>
            Try again
          </Button>
        </div>
      ) : groups.length === 0 ? (
        <div className="border-t border-border px-4.5 py-6 text-center text-muted-foreground">
          <CheckCircle2
            className="mx-auto mb-1.5 size-5 text-good"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <p className="font-medium text-foreground">All clear.</p>
          <p className="mx-auto mt-1 max-w-[52ch] text-sm">
            Approvals, sign-in requests, new form questions and unconfirmed
            submissions land here, grouped by the decision they need from you
            and sorted by deadline.
          </p>
        </div>
      ) : (
        <div className="border-t border-border">
          {groups.map((g) => (
            <DecisionRow key={g.group_key} group={g} focused={holds(g)} />
          ))}
        </div>
      )}
    </section>
  )
}
