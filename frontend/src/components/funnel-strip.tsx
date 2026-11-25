import { cn } from "@/lib/utils"

export type FunnelStep = { label: string; value: number }

/**
 * A sweep funnel as a strip of figures with proportional bars (found -> new -> passed
 * filters -> above threshold -> tailored -> applied). The last bar uses the accent.
 */
export function FunnelStrip({
  steps,
  className,
  label = "Last sweep funnel",
}: {
  steps: FunnelStep[]
  className?: string
  label?: string
}) {
  const max = Math.max(1, steps[0]?.value ?? 1)
  return (
    <ol
      aria-label={label}
      className={cn(
        "grid grid-cols-3 border-y border-border md:grid-cols-[repeat(var(--n),minmax(0,1fr))]",
        className
      )}
      style={{ ["--n" as string]: steps.length }}
    >
      {steps.map((s, i) => {
        const pct = Math.max(2, (s.value / max) * 100)
        const last = i === steps.length - 1
        return (
          <li
            key={s.label}
            className={cn(
              "grid min-w-0 gap-1 py-3 pr-3.5",
              i > 0 && "md:border-l md:border-border md:pl-3.5",
              i % 3 !== 0 &&
                "max-md:border-l max-md:border-border max-md:pl-3.5",
              i >= 3 && "max-md:border-t max-md:border-border"
            )}
          >
            <span className="num text-[1.45rem] leading-[1.1] font-semibold">
              {s.value}
            </span>
            <span className="text-[0.82rem] text-muted-foreground">
              {s.label}
            </span>
            <span
              className="h-1 overflow-hidden rounded-full bg-sunken"
              aria-hidden="true"
            >
              <i
                className={cn(
                  "block h-full rounded-full",
                  last ? "bg-highlight" : "bg-primary"
                )}
                style={{ width: `${pct.toFixed(1)}%` }}
              />
            </span>
          </li>
        )
      })}
    </ol>
  )
}
