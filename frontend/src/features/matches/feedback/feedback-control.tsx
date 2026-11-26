import { useState, type ReactNode } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ThumbsDown, ThumbsUp } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import {
  feedbackQuery,
  fk,
  putFeedback,
  withdrawFeedback,
  type FeedbackOut,
  type FeedbackReason,
  type Verdict,
} from "./api"
import { FEEDBACK_EXPLAINER, REASONS, reasonLabel } from "./reasons"

type Props = {
  jobId: string
  /** The campaign whose assessment is shown; feedback is kept per campaign. */
  campaignId: string | null
  className?: string
}

/** Thumbs up or down on a role, with optional reasons and a note (kept as evidence only). */
export function FeedbackControl({ jobId, campaignId, className }: Props) {
  const q = useQuery(feedbackQuery(jobId))
  const all = q.data ?? []
  const current =
    all.find((f) => f.campaign_id === campaignId) ??
    (campaignId ? undefined : all[0])
  return (
    <section
      aria-labelledby={`feedback-${jobId}`}
      className={cn("grid min-w-0 content-start gap-2.5", className)}
    >
      <h3 id={`feedback-${jobId}`} className="eyebrow">
        Your feedback
      </h3>
      <p className="text-sm text-muted-foreground">{FEEDBACK_EXPLAINER}</p>
      {q.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading feedback.</p>
      ) : (
        <FeedbackForm
          key={current ? `${current.id}-${current.updated_at}` : "none"}
          jobId={jobId}
          campaignId={campaignId}
          current={current ?? null}
        />
      )}
    </section>
  )
}

function FeedbackForm({
  jobId,
  campaignId,
  current,
}: {
  jobId: string
  campaignId: string | null
  current: FeedbackOut | null
}) {
  const qc = useQueryClient()
  const [verdict, setVerdict] = useState<Verdict | null>(
    current?.verdict ?? null
  )
  const [reasons, setReasons] = useState<FeedbackReason[]>(
    current?.reasons ?? []
  )
  const [note, setNote] = useState(current?.note ?? "")
  const [error, setError] = useState<string | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: fk.job(jobId) })

  const save = useMutation({
    mutationFn: () =>
      putFeedback(jobId, {
        campaign_id: campaignId,
        verdict: verdict!,
        reasons,
        note: note.trim() ? note.trim() : null,
      }),
    onSuccess: async () => {
      setError(null)
      await refresh()
      toast.success("Feedback saved.")
    },
    onError: (e) => setError(e.message),
  })
  const withdraw = useMutation({
    mutationFn: () => withdrawFeedback(jobId, campaignId),
    onSuccess: async () => {
      setError(null)
      await refresh()
      toast.success("Feedback withdrawn.")
    },
    onError: (e) => setError(e.message),
  })

  const dirty =
    verdict !== (current?.verdict ?? null) ||
    note.trim() !== (current?.note ?? "") ||
    [...reasons].sort().join() !== [...(current?.reasons ?? [])].sort().join()
  const toggle = (r: FeedbackReason) =>
    setReasons((rs) =>
      rs.includes(r) ? rs.filter((x) => x !== r) : [...rs, r]
    )
  const busy = save.isPending || withdraw.isPending

  return (
    <div className="grid gap-3">
      <div
        role="group"
        aria-label="Thumbs"
        className="flex flex-wrap items-center gap-1.5"
      >
        <Thumb
          label="Thumbs up"
          pressed={verdict === "up"}
          onClick={() => setVerdict(verdict === "up" ? null : "up")}
        >
          <ThumbsUp aria-hidden="true" />
        </Thumb>
        <Thumb
          label="Thumbs down"
          pressed={verdict === "down"}
          onClick={() => setVerdict(verdict === "down" ? null : "down")}
        >
          <ThumbsDown aria-hidden="true" />
        </Thumb>
        {current && (
          <span className="text-sm text-muted-foreground">
            Saved: thumbs {current.verdict}
            {current.reasons.length > 0 &&
              `, ${current.reasons.map(reasonLabel).join(", ")}`}
            .
          </span>
        )}
      </div>

      <div
        role="group"
        aria-label="Reasons (optional)"
        className="flex flex-wrap gap-1.5"
      >
        {REASONS.map((r) => {
          const on = reasons.includes(r.value)
          return (
            <button
              key={r.value}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(r.value)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[0.82rem] font-medium focus-visible:shadow-[0_0_0_3px_var(--t-ring)] focus-visible:outline-none",
                on
                  ? "border-primary-ink bg-primary-soft text-primary-ink"
                  : "border-border text-muted-foreground hover:text-foreground"
              )}
            >
              {r.label}
            </button>
          )
        })}
      </div>

      <label className="grid gap-1 text-sm">
        <span className="font-medium">Note (optional)</span>
        <Textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder="In your own words, what made this a good or poor match?"
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!verdict || !dirty || busy}
          onClick={() => save.mutate()}
        >
          Save feedback
        </Button>
        {current && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => withdraw.mutate()}
          >
            Withdraw
          </Button>
        )}
        {!verdict && (
          <span className="text-xs text-faint">
            Pick a thumb to save feedback.
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

function Thumb({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string
  pressed: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Button
      type="button"
      size="icon"
      variant={pressed ? "default" : "outline"}
      aria-label={label}
      aria-pressed={pressed}
      onClick={onClick}
    >
      {children}
    </Button>
  )
}
