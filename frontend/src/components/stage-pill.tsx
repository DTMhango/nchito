import { cn } from "@/lib/utils"
import { Chip, type ChipTone } from "./chip"

/** Application stages (DESIGN 4). `awaiting_owner` is not a stage; it is an open pending action. */
export const STAGES = [
  "shortlisted",
  "tailoring",
  "ready",
  "applying",
  "submitted_unconfirmed",
  "submitted",
  "screening",
  "interview",
  "offer",
  "accepted",
  "rejected",
  "withdrawn",
  "closed",
  "skipped",
] as const

export type Stage = (typeof STAGES)[number]

export const STAGE_META: Record<
  Stage,
  { label: string; tone: ChipTone; end?: boolean }
> = {
  shortlisted: { label: "Shortlisted", tone: "line" },
  tailoring: { label: "Tailoring", tone: "info" },
  ready: { label: "Ready to apply", tone: "primary" },
  applying: { label: "Applying", tone: "info" },
  submitted_unconfirmed: { label: "Sent, unconfirmed", tone: "warn" },
  submitted: { label: "Applied", tone: "good" },
  screening: { label: "Screening", tone: "good" },
  interview: { label: "Interview", tone: "good" },
  offer: { label: "Offer", tone: "accent" },
  accepted: { label: "Accepted", tone: "good" },
  rejected: { label: "Not selected", tone: "neutral", end: true },
  withdrawn: { label: "Withdrawn", tone: "neutral", end: true },
  closed: { label: "Closed", tone: "neutral", end: true },
  skipped: { label: "Skipped", tone: "neutral", end: true },
}

export function StagePill({
  stage,
  className,
}: {
  stage: Stage
  className?: string
}) {
  const meta = STAGE_META[stage]
  return (
    <Chip tone={meta.tone} data-stage={stage} className={cn(className)}>
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full bg-current",
          meta.end && "opacity-50"
        )}
      />
      {meta.label}
    </Chip>
  )
}
