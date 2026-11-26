/**
 * The five criteria that decide where you apply. None has a default: each is entered, or the
 * owner chooses "decide later", in which case nothing is saved for it and automation stays off.
 */
import type { CampaignIn } from "./api"
import type { CriterionKey } from "./state"

export type CriteriaDraft = {
  pay_type: string
  pay_amount: string
  pay_currency: string
  pay_period: string
  countries: string
  seniority: string
  work_rights: string
  relocation: string
}

export const EMPTY_DRAFT: CriteriaDraft = {
  pay_type: "",
  pay_amount: "",
  pay_currency: "",
  pay_period: "",
  countries: "",
  seniority: "",
  work_rights: "",
  relocation: "",
}

export const CRITERION_LABEL: Record<CriterionKey, string> = {
  pay_floor: "Pay floor",
  countries: "Countries",
  seniority: "Seniority",
  work_rights: "Work rights",
  relocation: "Relocation",
}

const list = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)

/** "1500.50" becomes 150050 minor units; anything that is not a plain amount is rejected. */
export function toMinor(amount: string): number | null {
  const t = amount.trim().replace(/,/g, "")
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null
  return Math.round(Number(t) * 100)
}

export type PayState = "empty" | "complete" | "partial"
export function payState(d: CriteriaDraft): PayState {
  const parts = [d.pay_type, d.pay_amount, d.pay_currency, d.pay_period]
  const n = parts.filter((p) => p.trim()).length
  if (n === 0) return "empty"
  const ok =
    n === 4 &&
    toMinor(d.pay_amount) !== null &&
    /^[A-Za-z]{3}$/.test(d.pay_currency.trim())
  return ok ? "complete" : "partial"
}

/** Is this criterion properly entered? */
export function isEntered(key: CriterionKey, d: CriteriaDraft): boolean {
  switch (key) {
    case "pay_floor":
      return payState(d) === "complete"
    case "countries":
      return list(d.countries).length > 0
    case "seniority":
      return list(d.seniority).length > 0
    case "work_rights":
      return d.work_rights.trim() !== ""
    case "relocation":
      return d.relocation.trim() !== ""
  }
}

/** The criteria that are neither entered nor marked "decide later". The guide cannot finish while any remain. */
export function unresolved(
  keys: readonly CriterionKey[],
  d: CriteriaDraft,
  decideLater: readonly CriterionKey[]
): CriterionKey[] {
  return keys.filter((k) => !decideLater.includes(k) && !isEntered(k, d))
}

/**
 * The campaign criteria to save. A criterion marked "decide later" contributes nothing, even if
 * something was typed before it was marked.
 */
export function toCriteria(
  d: CriteriaDraft,
  decideLater: readonly CriterionKey[]
): NonNullable<CampaignIn["criteria"]> {
  const out: NonNullable<CampaignIn["criteria"]> = {}
  if (!decideLater.includes("pay_floor") && payState(d) === "complete") {
    out.pay_floors = [
      {
        employment_type: d.pay_type as "permanent",
        amount_minor: toMinor(d.pay_amount) as number,
        currency: d.pay_currency.trim().toUpperCase(),
        period: d.pay_period as "year",
      },
    ]
  }
  if (!decideLater.includes("countries") && list(d.countries).length)
    out.locations = list(d.countries).map((place) => ({
      place,
      kind: "allow" as const,
    }))
  if (!decideLater.includes("seniority") && list(d.seniority).length)
    out.seniority = list(d.seniority)
  return out
}
