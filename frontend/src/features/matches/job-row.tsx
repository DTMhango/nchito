import { memo } from "react"
import { Pin, Scale } from "lucide-react"
import { Chip } from "@/components/chip"
import { ScoreRing } from "@/components/score-ring"
import { cn } from "@/lib/utils"
import {
  age,
  payBand,
  placeLabel,
  workModelLabel,
  type ListJob,
} from "./format"

type JobRowProps = {
  job: ListJob
  selected: boolean
  checked: boolean
  selecting: boolean
  onOpen: (id: string) => void
  onToggle: (id: string, range: boolean) => void
}

/** One role in the Matches list: score, title, employer, place and model, pay, age and source. */
export const JobRow = memo(function JobRow({
  job,
  selected,
  checked,
  selecting,
  onOpen,
  onToggle,
}: JobRowProps) {
  const band = payBand(job.pay)
  const model = workModelLabel(job.work_model)
  const scope =
    job.work_model === "remote" && job.remote_scope !== "not_stated"
      ? REMOTE_SCOPE[job.remote_scope]
      : null
  return (
    <div
      data-job-id={job.id}
      data-selected={selected || undefined}
      className={cn(
        "group/row relative grid grid-cols-[38px_minmax(0,1fr)_auto] gap-3 border-b border-border row-pad pr-3.5 pl-5.5 hover:bg-surface-2",
        selected && "bg-primary-soft hover:bg-primary-soft",
        checked && "bg-highlight-soft hover:bg-highlight-soft"
      )}
    >
      {selected && (
        <span
          aria-hidden="true"
          className="absolute top-1/2 left-2 size-[5px] -translate-y-1/2 rounded-full bg-primary"
        />
      )}
      <div className="relative">
        <ScoreRing
          score={job.best_score ?? 0}
          size={38}
          label={
            job.best_score == null
              ? "Not scored yet"
              : `Score ${job.best_score}`
          }
          className={cn(
            "transition-opacity",
            (selecting || checked) && "opacity-0",
            !selecting && !checked && "group-hover/row:opacity-0"
          )}
        />
        <input
          type="checkbox"
          aria-label={`Select ${job.title}, ${job.employer}`}
          checked={checked}
          onChange={() => undefined}
          onClick={(e) => {
            e.stopPropagation()
            onToggle(job.id, e.shiftKey)
          }}
          className={cn(
            "absolute top-1/2 left-1/2 z-10 size-4 -translate-x-1/2 -translate-y-1/2 cursor-pointer accent-primary",
            !selecting &&
              !checked &&
              "opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100"
          )}
        />
      </div>
      <button
        type="button"
        aria-current={selected ? "true" : undefined}
        onClick={() => onOpen(job.id)}
        className="min-w-0 text-left outline-none after:absolute after:inset-0 focus-visible:after:shadow-[inset_0_0_0_2px_var(--t-ring)]"
      >
        <div className="flex items-center gap-1.5 leading-[1.3] font-semibold">
          {job.pinned && (
            <Pin
              className="size-3.5 shrink-0 text-primary-ink"
              aria-label="Pinned"
            />
          )}
          <span className="truncate">{job.title}</span>
        </div>
        <div className="truncate text-sm text-muted-foreground">
          {job.employer}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-[5px]">
          <Chip tone="line">{placeLabel(job.location)}</Chip>
          {model && (
            <Chip tone="line">{scope ? `${model} · ${scope}` : model}</Chip>
          )}
          {job.conflict_state === "held" && (
            <Chip tone="warn" icon={Scale} className="whitespace-normal">
              Held · {heldWords(job)}
            </Chip>
          )}
          {job.conflict_state === "released" && (
            <Chip tone="info">Released</Chip>
          )}
          {job.tags.map((t) => (
            <Chip key={t} tone="accent">
              {t}
            </Chip>
          ))}
        </div>
      </button>
      <div className="relative grid content-start gap-[3px] text-right text-[0.8rem] whitespace-nowrap text-faint">
        <Pay job={job} band={band} />
        <span>
          {age(job.posted_at)}
          {job.source ? ` · ${job.source}` : ""}
        </span>
      </div>
    </div>
  )
})

const lowerFirst = (s: string | null | undefined) =>
  s ? s.charAt(0).toLowerCase() + s.slice(1) : null

const REMOTE_SCOPE: Record<ListJob["remote_scope"], string> = {
  worldwide: "worldwide",
  regions: "some regions",
  country_only: "in-country",
  not_stated: "",
}

/** Why a role is held: who outranked it and by how much, from the conflict record. */
function heldWords(job: ListJob): string {
  const c = job.conflict
  if (c?.outranked_by_title)
    return c.outranked_by_score != null && c.score != null
      ? `outranked by ${c.outranked_by_title} (${c.outranked_by_score} vs ${c.score})`
      : `outranked by ${c.outranked_by_title}`
  return (
    lowerFirst(c?.note ?? job.conflict_note) ?? "outranked at this employer"
  )
}

function Pay({ job, band }: { job: ListJob; band: string | null }) {
  if (job.pay_state === "stated" && band)
    return <span className="num text-[0.86rem] text-foreground">{band}</span>
  if (job.pay_state === "estimated" && band)
    return (
      <span className="num text-[0.86rem] text-muted-foreground italic">
        ~{band}
        <span className="ml-1 text-2xs not-italic">est.</span>
        <span className="sr-only">, estimated, not from the posting</span>
      </span>
    )
  return <span className="text-[0.8rem]">Pay not stated</span>
}
