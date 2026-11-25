import { cn } from "@/lib/utils"

export type ScoreLevel = "low" | "mid" | "high"

/** Ring colour bands. Defaults match the scoring thresholds' defaults (DESIGN 16): 60 and 85. */
export type ScoreBands = { mid: number; high: number }
export const DEFAULT_SCORE_BANDS: ScoreBands = { mid: 60, high: 85 }

export function scoreLevel(
  score: number,
  bands: ScoreBands = DEFAULT_SCORE_BANDS
): ScoreLevel {
  if (score >= bands.high) return "high"
  if (score >= bands.mid) return "mid"
  return "low"
}

type ScoreRingProps = {
  score: number
  /** Diameter in px. 36 in lists, 88 on a detail page. */
  size?: number
  bands?: ScoreBands
  className?: string
  /** Override the spoken label (default "Score 88"). */
  label?: string
}

/** A 0 to 100 score as a ring, coloured by the theme's score ramp. */
export function ScoreRing({
  score,
  size = 36,
  bands,
  className,
  label,
}: ScoreRingProps) {
  const value = Math.max(0, Math.min(100, Math.round(score)))
  const level = scoreLevel(value, bands)
  const stroke = size >= 64 ? 2.4 : 3
  return (
    <span
      role="img"
      aria-label={label ?? `Score ${value}`}
      data-level={level}
      className={cn(
        "relative inline-grid shrink-0 place-items-center",
        className
      )}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 36 36"
        aria-hidden="true"
        className="absolute inset-0 size-full -rotate-90"
      >
        <circle
          className="fill-none stroke-border"
          strokeWidth={stroke}
          cx="18"
          cy="18"
          r="15.5"
          pathLength={100}
        />
        <circle
          className={cn(
            "animate-draw fill-none",
            level === "high" && "stroke-score-high",
            level === "mid" && "stroke-score-mid",
            level === "low" && "stroke-score-low"
          )}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={100}
          strokeDashoffset={100 - value}
          cx="18"
          cy="18"
          r="15.5"
          pathLength={100}
        />
      </svg>
      <b
        className="num leading-none font-semibold"
        style={{ fontSize: size * 0.34 }}
        aria-hidden="true"
      >
        {value}
      </b>
    </span>
  )
}
