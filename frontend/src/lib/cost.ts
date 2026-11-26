/**
 * AI cost display. The backend stores cost in integer micro-dollars (1 USD = 1,000,000
 * micros); `*_minor` fields are the same amount rounded to cents for display. Read the
 * `*_micros` field when the response has it and fall back to `*_minor`.
 */

const MICROS_PER_MINOR = 10_000
const MICROS_PER_UNIT = 1_000_000

export type CostOptions = {
  currency?: string
  /** Tight spaces (meters, chips): sub-cent amounts read "under $0.01". */
  compact?: boolean
}

function symbolFor(currency: string): string {
  const parts = new Intl.NumberFormat("en", {
    style: "currency",
    currency,
  }).formatToParts(0)
  return parts.find((p) => p.type === "currency")?.value ?? currency
}

/**
 * Format an amount in micros. Whole cents and up show two decimals ("$1.24"); a non-zero
 * amount below one cent shows its first significant digits ("$0.004", "$0.00035"), or
 * "under $0.01" when `compact`. Zero is "$0.00".
 */
export function formatCost(
  micros: number | null | undefined,
  { currency = "USD", compact = false }: CostOptions = {}
): string {
  const m = Math.round(micros ?? 0)
  const sign = m < 0 ? "-" : ""
  const abs = Math.abs(m)
  if (abs > 0 && abs < MICROS_PER_MINOR) {
    if (compact) return `${sign}under ${symbolFor(currency)}0.01`
    // Two significant digits, trailing zeros dropped: $0.004, $0.00035.
    const digits = Math.min(
      6,
      3 + Math.ceil(-Math.log10(abs / MICROS_PER_MINOR))
    )
    const value = (abs / MICROS_PER_UNIT).toFixed(digits).replace(/0+$/, "")
    return `${sign}${symbolFor(currency)}${value}`
  }
  return new Intl.NumberFormat("en", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(m / MICROS_PER_UNIT)
}

/** Convert a cents amount to micros (for responses that only carry `*_minor`). */
export const minorToMicros = (minor: number | null | undefined) =>
  minor == null ? minor : minor * MICROS_PER_MINOR

/**
 * The micros value of cost field `name` on `row`: `${name}_micros` when present, else
 * `${name}_minor` converted. Returns null when neither is set.
 */
export function microsOf(
  row: object | null | undefined,
  name: string
): number | null {
  if (!row) return null
  const r = row as Record<string, unknown>
  const micros = r[`${name}_micros`]
  if (typeof micros === "number") return micros
  const minor = r[`${name}_minor`]
  if (typeof minor === "number") return minor * MICROS_PER_MINOR
  return null
}

/** `formatCost(microsOf(row, name))`; "—" when the field is null. */
export function costOf(
  row: object | null | undefined,
  name: string,
  options?: CostOptions
): string {
  const m = microsOf(row, name)
  return m == null ? "—" : formatCost(m, options)
}
