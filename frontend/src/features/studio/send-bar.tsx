import { useState } from "react"
import { Link, useNavigate } from "@tanstack/react-router"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, Hand, Send } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { ConfirmAddressNotice } from "@/features/jobs/apply-address"
import type { Explained } from "@/lib/api/refusals"
import { cn } from "@/lib/utils"
import {
  STUDIO_STAGES,
  studioKeys,
  type ApplicationDetail,
  type JobDetail,
  type RenderKind,
} from "./api"
import {
  groupChecks,
  traceSummary,
  type FactIndex,
  type Keyword,
  type ScreeningRow,
} from "./draft"
import { needsOwner } from "./draft"
import { sendError, sendForApproval, type SendChannel } from "./packet"
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

/**
 * The checks summary and "Send for approval": the server prepares the packet (renders, picks
 * the channel, builds, runs the approval policy), then its approval opens. "Apply myself
 * instead" prepares it for a manual hand-off.
 */
export function SendBar({
  app,
  job,
  draft: d,
  index,
  keywords,
  answers,
  templates,
  onOpenAnswers,
}: {
  app: ApplicationDetail
  job: JobDetail | undefined
  draft: DraftApi
  index: FactIndex
  keywords: Keyword[]
  answers: ScreeningRow[]
  templates: Record<RenderKind, string>
  onOpenAnswers: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [refusal, setRefusal] = useState<Explained | null>(null)
  const trace = traceSummary(d.draft, index)
  const groups = groupChecks(d.results)
  const openAnswers = answers.filter(needsOwner).length
  const blockers = sendBlockers(d, openAnswers)
  const canSend = STUDIO_STAGES.includes(app.stage)

  const send = useMutation({
    mutationFn: async (channel: SendChannel) => {
      await d.flush()
      return sendForApproval(app.id, templates, channel)
    },
    onMutate: () => setRefusal(null),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: studioKeys.application(app.id) })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      void qc.invalidateQueries({ queryKey: ["autopilot"] })
      toast.success(
        out.channel === "manual"
          ? "Packet ready. You apply yourself from its approval page."
          : "Sent for approval. It goes by email once you approve."
      )
      void navigate({
        to: "/approvals/$applicationId",
        params: { applicationId: app.id },
      })
    },
    onError: (e) => setRefusal(sendError(e)),
  })
  const disabled = !canSend || blockers.length > 0 || send.isPending

  return (
    <div
      role="region"
      aria-label="Checks summary"
      className="sticky bottom-0 z-10 mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 elev px-4 py-3"
    >
      <ConfirmAddressNotice
        job={job}
        note="Confirm it to send by email; otherwise you apply yourself."
      />
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
          variant="outline"
          disabled={disabled}
          aria-describedby={blockers.length ? "send-blockers" : undefined}
          onClick={() => send.mutate("manual")}
        >
          <Hand aria-hidden="true" />
          Apply myself instead
        </Button>
        <Button
          disabled={disabled}
          aria-describedby={blockers.length ? "send-blockers" : undefined}
          onClick={() => send.mutate("auto")}
        >
          <Send aria-hidden="true" />
          {send.isPending ? "Preparing..." : "Send for approval"}
        </Button>
      </div>
      {refusal && (
        <div
          role="alert"
          data-code={refusal.code}
          className="flex w-full flex-wrap items-center gap-2 rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          <span className="grid gap-0.5">
            <span>{refusal.text}</span>
            {refusal.reason && (
              <span className="text-xs opacity-80">{refusal.reason}</span>
            )}
          </span>
          <RefusalAction
            refusal={refusal}
            app={app}
            rechecking={d.recheck.isPending}
            onRecheck={() => d.recheck.mutate()}
            onOpenAnswers={onOpenAnswers}
            onRetry={() => send.mutate(send.variables ?? "auto")}
          />
        </div>
      )}
    </div>
  )
}

/** The one next step a refusal offers, when the Studio can take it. */
function RefusalAction({
  refusal,
  app,
  rechecking,
  onRecheck,
  onOpenAnswers,
  onRetry,
}: {
  refusal: Explained
  app: ApplicationDetail
  rechecking: boolean
  onRecheck: () => void
  onOpenAnswers: () => void
  onRetry: () => void
}) {
  const props = {
    size: "sm",
    variant: "outline",
    className: "ml-auto",
  } as const
  switch (refusal.action) {
    case "recheck":
      return (
        <Button {...props} disabled={rechecking} onClick={onRecheck}>
          Re-run the checks
        </Button>
      )
    case "open_answers":
      return (
        <Button {...props} onClick={onOpenAnswers}>
          Open the questions
        </Button>
      )
    case "confirm_address":
    case "edit_address":
      return (
        <Button {...props} asChild>
          <Link
            to="/jobs/$id"
            params={{ id: app.job_id }}
            search={{ tab: "overview" }}
          >
            {refusal.action === "confirm_address"
              ? "Confirm the address"
              : "Add the address"}
          </Link>
        </Button>
      )
    case "connect_mailbox":
      return (
        <Button {...props} asChild>
          <Link to="/settings/connections">Connect a mailbox</Link>
        </Button>
      )
    case "resume_autopilot":
      return (
        <Button {...props} asChild>
          <Link to="/autopilot">Open the Autopilot</Link>
        </Button>
      )
    case "prepare_again":
    case "reload":
      return (
        <Button {...props} onClick={onRetry}>
          Prepare again
        </Button>
      )
    default:
      return null
  }
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
