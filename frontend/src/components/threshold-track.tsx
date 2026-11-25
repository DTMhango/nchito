import { useMemo, type ReactNode } from "react"
import { Slider as SliderPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"

export type Thresholds = { shortlist: number; tailor: number; auto: number }

type ThresholdTrackProps = {
  /** Recent scores (0 to 100) drawn as a histogram behind the track. */
  scores: number[]
  value: Thresholds
  /** Live updates while dragging. */
  onValueChange: (v: Thresholds) => void
  /** Final value when a thumb is released (persist here). */
  onValueCommit?: (v: Thresholds) => void
  /** Sentence under the track, e.g. "At 85, 4 of this month's 61 roles would have...". */
  summary?: (
    v: Thresholds,
    counts: { auto: number; tailor: number; shortlist: number }
  ) => ReactNode
  className?: string
}

const NAMES = ["Shortlist", "Tailor", "Auto-apply"] as const

/**
 * Three thresholds on one 0-100 track over a histogram of recent scores (DESIGN 10.3,
 * Autopilot). Each thumb is a slider in its own right; they cannot cross.
 */
export function ThresholdTrack({
  scores,
  value,
  onValueChange,
  onValueCommit,
  summary,
  className,
}: ThresholdTrackProps) {
  const bins = useMemo(() => {
    const b = new Array(20).fill(0) as number[]
    for (const s of scores) b[Math.min(19, Math.max(0, Math.floor(s / 5)))]++
    return b
  }, [scores])
  const max = Math.max(1, ...bins)
  const counts = {
    auto: scores.filter((s) => s >= value.auto).length,
    tailor: scores.filter((s) => s >= value.tailor).length,
    shortlist: scores.filter((s) => s >= value.shortlist).length,
  }
  const toArr = (t: Thresholds) => [t.shortlist, t.tailor, t.auto]
  const fromArr = (a: number[]): Thresholds => ({
    shortlist: a[0],
    tailor: a[1],
    auto: a[2],
  })

  return (
    <div className={cn("grid gap-1", className)}>
      <div className="px-[9px]">
        <svg
          viewBox="0 0 400 90"
          preserveAspectRatio="none"
          role="img"
          aria-label={`Histogram of ${scores.length} recent scores`}
          className="block h-[90px] w-full"
        >
          {bins.map((c, i) => {
            const lo = i * 5
            const h = c ? ((90 - 4) * c) / max : 0
            const cls =
              lo >= value.auto
                ? "fill-score-high"
                : lo + 5 > value.tailor
                  ? "fill-score-mid opacity-60"
                  : "fill-score-low"
            return (
              <rect
                key={i}
                x={(i * 20 + 1.5).toFixed(1)}
                y={(90 - h).toFixed(1)}
                width={17}
                height={h.toFixed(1)}
                className={cls}
              >
                <title>{`${lo} to ${lo + 4}: ${c} ${c === 1 ? "role" : "roles"}`}</title>
              </rect>
            )
          })}
        </svg>
      </div>

      <SliderPrimitive.Root
        value={toArr(value)}
        min={0}
        max={100}
        step={1}
        minStepsBetweenThumbs={1}
        onValueChange={(a) => onValueChange(fromArr(a))}
        onValueCommit={(a) => onValueCommit?.(fromArr(a))}
        className="relative mx-[9px] mt-1.5 flex h-[18px] touch-none items-center select-none"
      >
        <SliderPrimitive.Track className="relative h-2.5 w-full overflow-hidden rounded-full bg-sunken">
          <i
            className="absolute inset-y-0 bg-border-strong opacity-60"
            style={{
              left: `${value.shortlist}%`,
              width: `${value.tailor - value.shortlist}%`,
            }}
          />
          <i
            className="absolute inset-y-0 bg-score-mid opacity-45"
            style={{
              left: `${value.tailor}%`,
              width: `${value.auto - value.tailor}%`,
            }}
          />
          <i
            className="absolute inset-y-0 bg-score-high"
            style={{ left: `${value.auto}%`, right: 0 }}
          />
        </SliderPrimitive.Track>
        {NAMES.map((name, i) => (
          <SliderPrimitive.Thumb
            key={name}
            aria-label={`${name} threshold`}
            aria-valuetext={`${name} at ${toArr(value)[i]}`}
            className={cn(
              "block size-[18px] cursor-grab rounded-full border-[3px] bg-surface shadow-sm focus-visible:shadow-[0_0_0_4px_var(--t-ring)] focus-visible:outline-none",
              i === 0 && "border-border-strong",
              i === 1 && "border-score-mid",
              i === 2 && "border-score-high"
            )}
          />
        ))}
      </SliderPrimitive.Root>

      <div
        className="relative mx-[9px] mt-1 h-[42px] text-xs"
        aria-hidden="true"
      >
        {NAMES.map((name, i) => {
          const v = toArr(value)[i]
          return (
            <span
              key={name}
              className={cn(
                "absolute top-0 grid -translate-x-1/2 justify-items-center whitespace-nowrap text-muted-foreground before:mb-0.5 before:w-px before:bg-border-strong",
                i === 1 ? "before:h-[22px]" : "before:h-1.5",
                i === 2 && "font-semibold text-highlight-ink"
              )}
              style={{ left: `${Math.min(v, 92)}%` }}
            >
              <span>
                {name} <b className="num font-semibold text-foreground">{v}</b>
              </span>
            </span>
          )
        })}
      </div>
      {summary && (
        <p className="mt-3 text-[1.02rem]">{summary(value, counts)}</p>
      )}
    </div>
  )
}
