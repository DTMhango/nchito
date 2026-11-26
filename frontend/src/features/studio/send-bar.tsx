import { useState } from "react"
import { Link, useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, Send } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { cn } from "@/lib/utils"
import {
  STUDIO_STAGES,
  mailConnectionsQuery,
  studioKeys,
  type ApplicationDetail,
  type RenderKind,
  type SpecState,
} from "./api"
import {
  groupChecks,
  traceSummary,
  type FactIndex,
  type Keyword,
  type ScreeningRow,
} from "./draft"
import { needsOwner } from "./draft"
import { sendError, sendForApproval, sendingIdentity } from "./packet"
import type { DraftApi } from "./use-draft"

/** What still stands between the draft and the approval queue, first reason first. */
export function sendBlockers(
  d: Pick<DraftApi, "checkState" | "blocking" | "results">,
  openAnswers: number
): string[] {
  const out: string[] = []
  if (d.checkState === "unchecked") out.push("Run the checks first.")
  if (d.checkState === "stale")
    out.push("Re-check: the results are out of date.")
  const blocking = groupChecks(d.results).block.length
  if (blocking)
    out.push(
      `${blocking} check${blocking === 1 ? "" : "s"} block${blocking === 1 ? "s" : ""} sending.`
    )
  else if (d.blocking) out.push("A check blocks sending.")
  if (openAnswers)
    out.push(
      `${openAnswers} question${openAnswers === 1 ? "" : "s"} need${openAnswers === 1 ? "s" : ""} your answer.`
    )
  return out
}

/** The checks summary and "Send for approval" (builds the packet, then opens its approval). */
export function SendBar({
  app,
  draft: d,
  state,
  index,
  keywords,
  answers,
  templates,
  ownerEmail,
}: {
  app: ApplicationDetail
  draft: DraftApi
  state: SpecState
  index: FactIndex
  keywords: Keyword[]
  answers: ScreeningRow[]
  templates: Record<RenderKind, string>
  ownerEmail: string | undefined
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const connections = useQuery(mailConnectionsQuery())
  const [refusal, setRefusal] = useState<{
    text: string
    recheck: boolean
  } | null>(null)
  const trace = traceSummary(d.draft, index)
  const groups = groupChecks(d.results)
  const openAnswers = answers.filter(needsOwner).length
  const blockers = sendBlockers(d, openAnswers)
  const canSend = STUDIO_STAGES.includes(app.stage)

  const send = useMutation({
    mutationFn: async () => {
      await d.flush()
      const identity = sendingIdentity(connections.data ?? [], ownerEmail)
      if (!identity)
        throw new Error(
          "There is no address to send from. Connect a mailbox in Settings, or add your email to your account."
        )
      return sendForApproval({
        applicationId: app.id,
        applyUrl: app.apply_url,
        identity,
        answers: state.answers,
        templates,
      })
    },
    onMutate: () => setRefusal(null),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: studioKeys.application(app.id) })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      toast.success("Sent for approval.")
      void navigate({
        to: "/approvals/$applicationId",
        params: { applicationId: app.id },
      })
    },
    onError: (e) => setRefusal(sendError(e)),
  })

  return (
    <div
      role="region"
      aria-label="Checks summary"
      className="sticky bottom-0 z-10 mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 elev px-4 py-3"
    >
      <Metric
        label="Facts traced"
        value={`${trace.traced}/${trace.total}`}
        ok={trace.flagged === 0}
      />
      <Metric
        label="Guardrails"
        value={
          groups.block.length
            ? `${groups.block.length} blocking`
            : groups.warn.length
              ? `${groups.warn.length} to review`
              : "Clear"
        }
        ok={groups.block.length === 0}
      />
      <Metric
        label="Keywords"
        value={`${keywords.filter((k) => k.covered).length}/${keywords.length}`}
        ok={keywords.every((k) => k.covered)}
      />
      <Metric
        label="Answers"
        value={openAnswers ? `${openAnswers} need you` : "Ready"}
        ok={openAnswers === 0}
      />
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {app.stage === "ready" && (
          <>
            <Chip tone="primary" icon={CircleCheck}>
              Waiting for your approval
            </Chip>
            <Button asChild size="sm" variant="outline">
              <Link
                to="/approvals/$applicationId"
                params={{ applicationId: app.id }}
              >
                Open the approval
              </Link>
            </Button>
          </>
        )}
        {blockers.length > 0 && (
          <span
            id="send-blockers"
            className="max-w-[36ch] text-sm text-muted-foreground"
          >
            {blockers[0]}
          </span>
        )}
        <Button
          disabled={!canSend || blockers.length > 0 || send.isPending}
          aria-describedby={blockers.length ? "send-blockers" : undefined}
          onClick={() => send.mutate()}
        >
          <Send aria-hidden="true" />
          {send.isPending ? "Sending..." : "Send for approval"}
        </Button>
      </div>
      {refusal && (
        <div
          role="alert"
          className="flex w-full flex-wrap items-center gap-2 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          <span>{refusal.text}</span>
          {refusal.recheck && (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              disabled={d.recheck.isPending}
              onClick={() => d.recheck.mutate()}
            >
              Re-run the checks
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function Metric({
  label,
  value,
  ok,
}: {
  label: string
  value: string
  ok: boolean
}) {
  return (
    <div className="grid gap-px">
      <span className="eyebrow">{label}</span>
      <span
        className={cn(
          "num font-semibold",
          ok ? "text-foreground" : "text-warn"
        )}
      >
        {value}
      </span>
    </div>
  )
}
