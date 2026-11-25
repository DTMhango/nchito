import { cn } from "@/lib/utils"

type SparkbarProps = {
  values: number[]
  /** Labels under the first and last bar, e.g. ["12 Nov", "25 Nov"]. */
  edgeLabels?: [string, string]
  /** Accessible description of the whole chart. */
  label: string
  /** Unit for each bar's tooltip ("sent"). */
  unit?: string
  highlightLast?: boolean
  className?: string
}

/** Small daily bar chart with gridlines (mockup "Applications sent"). */
export function Sparkbar({
  values,
  edgeLabels,
  label,
  unit = "",
  highlightLast = true,
  className,
}: SparkbarProps) {
  const W = 300
  const top = 6
  const base = 76
  const n = Math.max(values.length, 1)
  const max = Math.max(1, ...values)
  const ticks = Math.min(max, 3)
  const bw = Math.min(14, (W - 20) / n - 2)
  const gap = n > 1 ? (W - 20 - bw * n) / (n - 1) : 0
  return (
    <svg
      viewBox="0 0 300 96"
      role="img"
      aria-label={label}
      className={cn("block h-24 w-full", className)}
    >
      {Array.from({ length: ticks }, (_, k) => {
        const g = Math.round(((k + 1) * max) / ticks)
        const y = base - ((base - top) * g) / max
        return (
          <g key={g}>
            <line
              x1="20"
              x2={W}
              y1={y}
              y2={y}
              className="stroke-border"
              strokeWidth={1}
              strokeDasharray="2 3"
            />
            <text x="0" y={y + 3} className="fill-faint num text-[10px]">
              {g}
            </text>
          </g>
        )
      })}
      <line
        x1="20"
        x2={W}
        y1={base}
        y2={base}
        className="stroke-border-strong"
      />
      {values.map((v, i) => {
        const h = ((base - top) * v) / max
        const x = 20 + i * (bw + gap)
        const last = highlightLast && i === values.length - 1
        return (
          <rect
            key={i}
            x={x.toFixed(1)}
            y={(base - Math.max(h, 1.5)).toFixed(1)}
            width={bw}
            height={Math.max(h, 1.5).toFixed(1)}
            rx="2"
            className={last ? "fill-highlight" : "fill-primary opacity-55"}
          >
            <title>{`${v} ${unit}`.trim()}</title>
          </rect>
        )
      })}
      {edgeLabels && (
        <>
          <text x="20" y="92" className="fill-faint num text-[10px]">
            {edgeLabels[0]}
          </text>
          <text
            x={W}
            y="92"
            textAnchor="end"
            className="fill-faint num text-[10px]"
          >
            {edgeLabels[1]}
          </text>
        </>
      )}
    </svg>
  )
}
