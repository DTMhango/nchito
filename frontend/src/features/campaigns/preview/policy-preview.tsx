import { useEffect, useMemo, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Slider as SliderPrimitive } from "radix-ui"
import { AlertTriangle, Moon } from "lucide-react"
import { Chip, type ChipTone } from "@/components/chip"
import { cn } from "@/lib/utils"
import {
  pk,
  previewPolicy,
  type PolicyPreviewIn,
  type PolicyPreviewOut,
  type PreviewThresholds,
} from "./api"
import { ScoreHistogram } from "./score-histogram"
import {
  actionLabel,
  CHANGE_LABEL,
  cappedSentence,
  lineSentence,
  quietSentence,
} from "./words"

export type PolicyPreviewProps = {
  campaignId: string
  /** Unsaved proposal pieces; left out, what is in force is used. */
  automation?: PolicyPreviewIn["automation"]
  criteria?: PolicyPreviewIn["criteria"]
  unknown_data_policy?: PolicyPreviewIn["unknown_data_policy"]
  settings?: Record<string, unknown>
  /** Called as the handles move (tailor and auto-apply; shortlist is unchanged). */
  onThresholdsChange?: (t: PreviewThresholds) => void
  className?: string
}

/** Wait this long after the last change before asking the server again. */
const DEBOUNCE_MS = 250

function useDebounced<T>(value: T, ms: number): T {
  const json = JSON.stringify(value)
  const [out, setOut] = useState(json)
  useEffect(() => {
    const t = setTimeout(() => setOut(json), ms)
    return () => clearTimeout(t)
  }, [json, ms])
  return useMemo(() => JSON.parse(out) as T, [out])
}

/**
 * What a policy change would have done to recent real roles: a score histogram with the tailor
 * and auto-apply handles, the live line, changed roles, caps, quiet hours and unknowns. Writes nothing.
 */
export function PolicyPreview({
  campaignId,
  automation,
  criteria,
  unknown_data_policy,
  settings,
  onThresholdsChange,
  className,
}: PolicyPreviewProps) {
  const [local, setLocal] = useState<{ tailor: number; auto: number } | null>(
    null
  )
  const [shortlistSeen, setShortlistSeen] = useState<number | null>(null)

  const proposal = useDebounced<PolicyPreviewIn>(
    {
      ...(local && shortlistSeen !== null
        ? {
            thresholds: {
              shortlist: shortlistSeen,
              tailor: local.tailor,
              auto_apply: local.auto,
            },
          }
        : {}),
      ...(automation ? { automation } : {}),
      ...(criteria ? { criteria } : {}),
      ...(unknown_data_policy ? { unknown_data_policy } : {}),
      ...(settings && Object.keys(settings).length > 0 ? { settings } : {}),
    },
    DEBOUNCE_MS
  )
  const q = useQuery({
    queryKey: pk.preview(campaignId, proposal),
    queryFn: () => previewPolicy(campaignId, proposal),
    placeholderData: keepPreviousData,
    retry: false,
  })
  const data = q.data
  const shortlist = shortlistSeen ?? data?.thresholds.shortlist ?? null
  const shown =
    local ??
    (data
      ? { tailor: data.thresholds.tailor, auto: data.thresholds.auto_apply }
      : null)

  const move = (a: number[]) => {
    if (shortlist === null) return
    const tailor = Math.max(shortlist, Math.min(a[0], a[1]))
    const auto = Math.max(tailor, a[1])
    setShortlistSeen(shortlist)
    setLocal({ tailor, auto })
    onThresholdsChange?.({ shortlist, tailor, auto_apply: auto })
  }

  return (
    <section
      aria-label="Policy preview"
      className={cn(
        "grid gap-3 rounded-lg border border-border bg-surface p-4",
        className
      )}
    >
      <div>
        <h4 className="text-md">Preview on recent roles</h4>
        <p className="text-sm text-muted-foreground">
          Move the handles to see what would have happened to the roles of the
          last {data?.window_days ?? "few"} days. Nothing is saved or sent from
          here.
        </p>
      </div>

      {!data && q.isPending && (
        <p className="text-sm text-muted-foreground">Loading the preview.</p>
      )}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          {q.error instanceof Error
            ? q.error.message
            : "The preview could not be worked out."}
        </p>
      )}

      {data && shown && shortlist !== null && (
        <>
          <div className="px-[9px]">
            <ScoreHistogram
              bins={data.histogram}
              shortlist={shortlist}
              tailor={shown.tailor}
              auto={shown.auto}
              unscored={data.unscored}
            />
          </div>
          <SliderPrimitive.Root
            value={[shown.tailor, shown.auto]}
            min={0}
            max={100}
            step={1}
            minStepsBetweenThumbs={0}
            onValueChange={move}
            aria-label="Score lines"
            className="relative mx-[9px] flex h-[18px] touch-none items-center select-none"
          >
            <SliderPrimitive.Track className="relative h-2 w-full overflow-hidden rounded-full bg-sunken">
              <SliderPrimitive.Range className="absolute inset-y-0 bg-chart-1 opacity-40" />
            </SliderPrimitive.Track>
            {(["Tailor", "Auto-apply"] as const).map((name, i) => (
              <SliderPrimitive.Thumb
                key={name}
                aria-label={`${name} threshold`}
                aria-valuetext={`${name} at ${i === 0 ? shown.tailor : shown.auto}`}
                className={cn(
                  "block size-[18px] cursor-grab rounded-full border-[3px] bg-surface shadow-sm focus-visible:shadow-[0_0_0_4px_var(--t-ring)] focus-visible:outline-none",
                  i === 0 ? "border-muted-foreground" : "border-foreground"
                )}
              />
            ))}
          </SliderPrimitive.Root>
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>
              Shortlist <b className="num text-foreground">{shortlist}</b>{" "}
              (fixed here)
            </span>
            <span>
              Tailor <b className="num text-foreground">{shown.tailor}</b>
            </span>
            <span>
              Auto-apply <b className="num text-foreground">{shown.auto}</b>
            </span>
          </p>

          <Results data={data} stale={q.isFetching} />
        </>
      )}
    </section>
  )
}

function Results({ data, stale }: { data: PolicyPreviewOut; stale: boolean }) {
  const capped = cappedSentence(data)
  const quiet = quietSentence(data.caps)
  const c = data.caps
  return (
    <div className={cn("grid gap-3", stale && "opacity-70")}>
      <div aria-live="polite" className="grid gap-1">
        <p className="text-[1.02rem]" data-testid="preview-line">
          {lineSentence(data)}
        </p>
        <p className="text-sm text-muted-foreground">
          Before this change: {data.baseline_line.would_apply}. {capped ?? ""}
        </p>
      </div>

      <div className="grid gap-1 text-sm">
        <p>
          Caps: {c.sent_today} of {c.daily_cap} sent today, {c.sent_week} of{" "}
          {c.weekly_cap} this week. A run now would send {c.run_now_would_send}.
        </p>
        {quiet && (
          <p className="flex items-start gap-1.5">
            <Moon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {quiet}
          </p>
        )}
        {c.needs_open_check > 0 && (
          <p className="text-muted-foreground">
            {c.needs_open_check} would first be checked to confirm the posting
            is still open.
          </p>
        )}
      </div>

      {data.unknowns.length > 0 && (
        <ul
          aria-label="Unknowns"
          className="grid gap-1 rounded-md border border-border bg-warn-soft p-2.5 text-sm text-warn"
        >
          {data.unknowns.map((u) => (
            <li key={u.gate} className="flex items-start gap-2">
              <AlertTriangle
                className="mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
              <span>{u.message}</span>
            </li>
          ))}
        </ul>
      )}

      <Changes data={data} />
    </div>
  )
}

const CHANGE_TONE: Record<string, ChipTone> = {
  newly_automatic: "good",
  newly_blocked: "danger",
  changed: "info",
}

function Changes({ data }: { data: PolicyPreviewOut }) {
  if (data.changes.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        No role would be handled differently.
      </p>
    )
  return (
    <div className="grid gap-2">
      <h5 className="eyebrow">
        Roles handled differently ({data.changes_total})
      </h5>
      <ul aria-label="Changed roles" className="grid gap-2">
        {data.changes.map((ch) => (
          <li
            key={ch.job_id}
            className="grid gap-1 rounded-md border border-border px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone={CHANGE_TONE[ch.change] ?? "neutral"}>
                {CHANGE_LABEL[ch.change] ?? ch.change}
              </Chip>
              <span className="font-medium">{ch.title}</span>
              <span className="text-muted-foreground">· {ch.employer}</span>
              {ch.score !== null && (
                <span className="ml-auto num text-sm">{ch.score}</span>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              {actionLabel(ch.before)} → {actionLabel(ch.after)}
            </p>
            {ch.reasons.filter(Boolean).length > 0 && (
              <ul className="list-disc pl-5 text-sm">
                {ch.reasons.filter(Boolean).map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
      {data.changes_total > data.changes.length && (
        <p className="text-sm text-muted-foreground">
          And {data.changes_total - data.changes.length} more.
        </p>
      )}
    </div>
  )
}
