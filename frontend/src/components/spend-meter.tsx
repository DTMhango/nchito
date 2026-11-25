import { Link } from "@tanstack/react-router"
import { cn } from "@/lib/utils"

type SpendMeterProps = {
  /** Month-to-date spend in minor units (cents). */
  spentMinor: number
  /** Monthly cap in minor units, or null when no cap is set (paid work stays off). */
  capMinor: number | null
  currency?: string
  className?: string
}

const fmt = (minor: number, currency: string) =>
  new Intl.NumberFormat("en", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(minor / 100)

/**
 * AI spend this month against the cap (DESIGN 11, budget ledger). Without a cap nothing paid
 * runs, so the meter says so and links to the setting.
 */
export function SpendMeter({
  spentMinor,
  capMinor,
  currency = "USD",
  className,
}: SpendMeterProps) {
  const pct = capMinor ? Math.min(100, (spentMinor / capMinor) * 100) : 0
  const warn = pct >= 80
  return (
    <div className={cn("grid gap-1.5 rounded-sm bg-sunken p-2.5", className)}>
      <span className="eyebrow">AI spend this month</span>
      <div className="flex items-baseline justify-between gap-2 text-[0.86rem]">
        <span className="num font-semibold">{fmt(spentMinor, currency)}</span>
        {capMinor ? (
          <span className="num text-faint">of {fmt(capMinor, currency)}</span>
        ) : (
          <Link to="/settings/ai" className="text-xs">
            Set a cap
          </Link>
        )}
      </div>
      <div
        role="meter"
        aria-label="AI spend against monthly cap"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-valuetext={
          capMinor
            ? `${Math.round(pct)}% of the monthly cap`
            : "No cap set. Paid AI work is off until you set one."
        }
        className="h-[5px] overflow-hidden rounded-full bg-border"
      >
        <i
          className={cn(
            "block h-full rounded-full",
            warn ? "bg-warn" : "bg-primary"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {!capMinor && (
        <span className="text-xs text-faint">
          No cap set, so paid AI work is off.
        </span>
      )}
    </div>
  )
}
