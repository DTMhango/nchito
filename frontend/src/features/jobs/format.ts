/** Plain-words formatting of a job's structured fields. No business values live here. */
import type { JobDetail, JobFacets } from "./api"

export const dateText = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "not stated"

export function money(minor: number, currency: string | null | undefined) {
  const major = minor / 100
  const n = major.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return currency ? `${currency} ${n}` : n
}

export function payText(pay: JobDetail["pay"]): string {
  if (pay.state === "not_stated") return "Pay is not stated in the posting."
  const range =
    pay.min_minor != null && pay.max_minor != null && pay.min_minor !== pay.max_minor
      ? `${money(pay.min_minor, pay.currency)} to ${money(pay.max_minor, pay.currency)}`
      : money((pay.min_minor ?? pay.max_minor) as number, pay.currency)
  const per = pay.period ? ` a ${pay.period}` : ""
  if (pay.state === "stated") return `Stated: ${range}${per}.`
  const how = pay.estimate_source ? ` Based on ${pay.estimate_source}.` : ""
  return `Estimated: about ${range}${per}.${how}`
}

export function locationText(l: JobDetail["location"]): string {
  const parts = [l.city, l.region, l.country].filter(Boolean)
  return parts.length ? parts.join(", ") : (l.raw ?? "Location not stated")
}

export function deadlineText(d: JobDetail["deadline"]): string {
  if (d.state === "dated") return dateText(d.on)
  if (d.state === "open_until_filled") return "Open until filled"
  return "No deadline stated"
}

const YNN = { yes: "Yes", no: "No", not_stated: "Not stated" } as const
const WORK_MODEL = {
  on_site: "On site",
  hybrid: "Hybrid",
  remote: "Remote",
  not_stated: "Not stated",
} as const
const REMOTE_SCOPE = {
  worldwide: "Anywhere in the world",
  regions: "Certain regions only",
  country_only: "One country only",
  not_stated: "Not stated",
} as const
const WORK_RIGHTS = {
  existing_right_required: "You need the right to work there already",
  sponsorship_possible: "Sponsorship is possible",
  not_stated: "Not stated",
} as const
const ARRANGEMENT = {
  employee: "Employee",
  contractor: "Contractor",
  eor: "Employer of record",
  not_stated: "Not stated",
} as const
const EMPLOYMENT = {
  permanent: "Permanent",
  fixed_term: "Fixed term",
  contract: "Contract",
  eor: "Employer of record",
} as const

type Shown = { display: string; evidence: string | null | undefined }
export type FacetLine = { key: string; label: string } & Shown

const ev = <T>(
  x: { value: T; evidence?: string | null } | null | undefined,
  map: (v: T) => string
): Shown | null => (x ? { display: map(x.value), evidence: x.evidence } : null)

/** Every single-value facet that has been extracted, with the sentence that supports it. */
export function facetLines(f: JobFacets): FacetLine[] {
  const lines: [string, string, Shown | null][] = [
    ["relocation_required", "Relocation required", ev(f.relocation_required, (v) => YNN[v])],
    ["visa_sponsorship", "Visa sponsorship offered", ev(f.visa_sponsorship, (v) => YNN[v])],
    ["relocation_assistance", "Relocation assistance offered", ev(f.relocation_assistance, (v) => YNN[v])],
    ["needs_account", "Needs an account to apply", ev(f.needs_account, (v) => YNN[v])],
    ["work_model", "Work model", ev(f.work_model, (v) => WORK_MODEL[v])],
    ["remote_scope", "Remote scope", ev(f.remote_scope, (v) => REMOTE_SCOPE[v])],
    [
      "where_must_live",
      "Where you must live",
      ev(f.where_must_live, (v) =>
        v.kind === "places"
          ? (v.places ?? []).join(", ")
          : v.kind === "anywhere"
            ? "Anywhere"
            : "Not stated"
      ),
    ],
    ["work_rights", "Work rights needed", ev(f.work_rights, (v) => WORK_RIGHTS[v])],
    [
      "timezone_overlap",
      "Time-zone overlap",
      ev(f.timezone_overlap, (v) => {
        const t = v as { zone?: string | null; hours?: number | null }
        return [t.hours != null ? `${t.hours} hours` : null, t.zone].filter(Boolean).join(" in ") || "Required"
      }),
    ],
    ["hiring_arrangement", "Hiring arrangement", ev(f.hiring_arrangement, (v) => ARRANGEMENT[v])],
    ["employment_type", "Employment type", ev(f.employment_type, (v) => EMPLOYMENT[v as keyof typeof EMPLOYMENT] ?? "Not stated")],
    ["years_experience", "Years of experience asked", ev(f.years_experience, (v) => (v == null ? "Not stated" : `${v}`))],
    ["travel_percent", "Travel", ev(f.travel_percent, (v) => (v == null ? "Not stated" : `${v}%`))],
  ]
  return lines.flatMap(([key, label, s]) => (s ? [{ key, label, ...s }] : []))
}

/** The pay / location / work-rights picture in sentences (DESIGN 10.3a). */
export function picture(job: JobDetail): { label: string; text: string }[] {
  const f = job.facets
  const out = [
    { label: "Pay", text: payText(job.pay) },
    {
      label: "Location",
      text: `${locationText(job.location)}. ${
        f.work_model ? `${WORK_MODEL[f.work_model.value]}.` : "Work model not stated."
      }${
        f.remote_scope && f.work_model?.value === "remote"
          ? ` Remote scope: ${REMOTE_SCOPE[f.remote_scope.value].toLowerCase()}.`
          : ""
      }`,
    },
  ]
  const rights = f.work_rights ? WORK_RIGHTS[f.work_rights.value] : "Work rights are not stated"
  const visa = f.visa_sponsorship
    ? f.visa_sponsorship.value === "yes"
      ? "They offer visa sponsorship"
      : f.visa_sponsorship.value === "no"
        ? "They do not offer visa sponsorship"
        : "Visa sponsorship is not stated"
    : "Visa sponsorship is not stated"
  const reloc = f.relocation_required
    ? f.relocation_required.value === "yes"
      ? "relocation is required"
      : f.relocation_required.value === "no"
        ? "no relocation is required"
        : "relocation is not stated"
    : "relocation is not stated"
  out.push({ label: "Work rights", text: `${rights}. ${visa}; ${reloc}.` })
  return out
}
