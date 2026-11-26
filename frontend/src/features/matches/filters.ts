/**
 * The Matches filter model (DESIGN 6.1). The URL holds a compact form of the filter so a view
 * is linkable; `toConditionSet` turns it into the one condition schema (CONTRACTS 5) that
 * saved views, rule tags and campaign rules share.
 */
import { z } from "zod"
import type { FilterState } from "@/components/chip"
import type {
  Condition,
  ConditionSet,
  FacetCatalogEntry,
  Group,
  RangeFilter,
  SavedViewIn,
  ValueFilter,
} from "./types"

export const NOT_STATED = "not_stated"

// ---- tabs ---------------------------------------------------------------------------------

export const TABS = [
  { id: "new", label: "New" },
  { id: "shortlisted", label: "Shortlisted" },
  { id: "below", label: "Below threshold" },
  { id: "held", label: "Held" },
  { id: "archived", label: "Archived" },
] as const
export type TabId = (typeof TABS)[number]["id"]
export const TAB_IDS = TABS.map((t) => t.id) as [TabId, ...TabId[]]

const values = (
  facet: string,
  include: string[],
  exclude: string[] = []
): ValueFilter => ({ type: "values", facet, include, exclude, match: "any" })

/** Which jobs each inbox tab holds. Held roles sit in their own tab, with the reason. */
export function tabConditions(tab: TabId): Condition[] {
  const notHeld = values("conflict_state", [], ["held"])
  switch (tab) {
    case "new":
      return [values("triage", ["new"]), notHeld]
    case "shortlisted":
      return [values("triage", ["shortlisted"]), notHeld]
    case "below":
      return [values("triage", ["below_threshold"]), notHeld]
    case "held":
      return [
        values("conflict_state", ["held"]),
        values("triage", [], ["archived", "skipped"]),
      ]
    case "archived":
      return [values("triage", ["archived", "skipped"])]
  }
}

// ---- sort -----------------------------------------------------------------------------------

export const SORTS = [
  { id: "-best_score", label: "Best score" },
  { id: "-posted_at", label: "Newest" },
  { id: "deadline", label: "Deadline soonest" },
  { id: "employer", label: "Employer A to Z" },
] as const
export const DEFAULT_SORT = "-best_score"

// ---- URL state ------------------------------------------------------------------------------

const valueSel = z.object({
  i: z.array(z.string()).optional(),
  e: z.array(z.string()).optional(),
  m: z.literal("all").optional(),
})
const rangeSel = z.object({
  min: z.number().optional(),
  max: z.number().optional(),
  ns: z.literal("include").optional(),
})
export type ValueSel = z.infer<typeof valueSel>
export type RangeSel = z.infer<typeof rangeSel>
export type ValueSels = Record<string, ValueSel>
export type RangeSels = Record<string, RangeSel>

export const matchesSearchSchema = z.object({
  tab: z.enum(TAB_IDS).catch("new").default("new"),
  q: z.string().optional().catch(undefined),
  f: z.record(z.string(), valueSel).optional().catch(undefined),
  r: z.record(z.string(), rangeSel).optional().catch(undefined),
  g: z.string().optional().catch(undefined),
  sort: z.string().optional().catch(undefined),
  view: z.string().optional().catch(undefined),
  job: z.string().optional().catch(undefined),
})
export type MatchesSearch = z.infer<typeof matchesSearchSchema>

/** The part of the URL a saved view stores. */
export type ViewState = Pick<MatchesSearch, "q" | "f" | "r" | "g" | "sort">

// ---- chips ----------------------------------------------------------------------------------

export function chipState(
  f: ValueSels | undefined,
  facet: string,
  value: string
): FilterState {
  const sel = f?.[facet]
  if (sel?.i?.includes(value)) return "include"
  if (sel?.e?.includes(value)) return "exclude"
  return "off"
}

const nonEmpty = (a: string[] | undefined) => (a && a.length ? a : undefined)

function clean(sel: ValueSel): ValueSel | undefined {
  const out: ValueSel = {}
  if (nonEmpty(sel.i)) out.i = sel.i
  if (nonEmpty(sel.e)) out.e = sel.e
  if (!out.i && !out.e) return undefined
  if (sel.m === "all") out.m = "all"
  return out
}

/** Put one facet value into a state (include, exclude or off). */
export function setChip(
  f: ValueSels | undefined,
  facet: string,
  value: string,
  state: FilterState
): ValueSels | undefined {
  const prev = f?.[facet] ?? {}
  const i = (prev.i ?? []).filter((v) => v !== value)
  const e = (prev.e ?? []).filter((v) => v !== value)
  if (state === "include") i.push(value)
  if (state === "exclude") e.push(value)
  return withFacet(f, facet, clean({ i, e, m: prev.m }))
}

/** Values inside one facet: "any" (default) or "all". */
export function setMatch(
  f: ValueSels | undefined,
  facet: string,
  match: "any" | "all"
): ValueSels | undefined {
  const prev = f?.[facet]
  if (!prev) return f
  return withFacet(f, facet, {
    ...prev,
    m: match === "all" ? "all" : undefined,
  })
}

export function setRange(
  r: RangeSels | undefined,
  facet: string,
  sel: RangeSel | undefined
): RangeSels | undefined {
  const next = { ...(r ?? {}) }
  if (
    !sel ||
    (sel.min === undefined && sel.max === undefined && sel.ns === undefined)
  )
    delete next[facet]
  else next[facet] = sel
  return Object.keys(next).length ? next : undefined
}

function withFacet(
  f: ValueSels | undefined,
  facet: string,
  sel: ValueSel | undefined
): ValueSels | undefined {
  const next = { ...(f ?? {}) }
  if (sel) next[facet] = sel
  else delete next[facet]
  return Object.keys(next).length ? next : undefined
}

export function activeCount(s: Pick<MatchesSearch, "f" | "r" | "q">): number {
  let n = s.q?.trim() ? 1 : 0
  for (const sel of Object.values(s.f ?? {}))
    n += (sel.i?.length ?? 0) + (sel.e?.length ?? 0)
  n += Object.keys(s.r ?? {}).length
  return n
}

// ---- conditions -----------------------------------------------------------------------------

export const TEXT_FIELDS = ["title", "employer", "raw_text"]

/** The user's filter as condition leaves (no tab, no text). */
export function filterConditions(
  s: Pick<MatchesSearch, "f" | "r">
): Condition[] {
  const out: Condition[] = []
  for (const [facet, sel] of Object.entries(s.f ?? {})) {
    if (!sel.i?.length && !sel.e?.length) continue
    out.push({
      type: "values",
      facet,
      include: sel.i ?? [],
      exclude: sel.e ?? [],
      match: sel.m ?? "any",
    })
  }
  for (const [facet, sel] of Object.entries(s.r ?? {})) {
    const leaf: RangeFilter = {
      type: "range",
      facet,
      not_stated: sel.ns ?? "exclude",
    }
    if (sel.min !== undefined) leaf.min = sel.min
    if (sel.max !== undefined) leaf.max = sel.max
    out.push(leaf)
  }
  return out
}

export const andGroup = (conditions: Condition[]): Group => ({
  type: "group",
  op: "and",
  negate: false,
  conditions,
})

export const conditionSet = (conditions: Condition[]): ConditionSet => ({
  version: 1,
  root: andGroup(conditions),
})

/**
 * The view's filter as a ConditionSet. `withText` adds the free-text search as a TextFilter
 * (saved views, campaign rules); the list endpoint takes text as `q` instead.
 */
export function toConditionSet(
  s: Pick<MatchesSearch, "f" | "r" | "q">,
  { withText = false }: { withText?: boolean } = {}
): ConditionSet {
  const c = filterConditions(s)
  const q = s.q?.trim()
  if (withText && q) c.push({ type: "text", query: q, fields: TEXT_FIELDS })
  return conditionSet(c)
}

/** Read a stored ConditionSet back into URL form (top-level AND leaves only). */
export function fromConditionSet(
  set: unknown
): Pick<MatchesSearch, "f" | "r" | "q"> {
  const root = (set as { root?: Group } | undefined)?.root
  let f: ValueSels | undefined
  let r: RangeSels | undefined
  let q: string | undefined
  for (const c of root?.conditions ?? []) {
    if (c.type === "values") {
      const sel = clean({
        i: c.include.map(String),
        e: c.exclude.map(String),
        m: c.match === "all" ? "all" : undefined,
      })
      if (sel) f = { ...(f ?? {}), [c.facet]: sel }
    } else if (c.type === "range") {
      const sel: RangeSel = {}
      if (c.min != null) sel.min = c.min
      if (c.max != null) sel.max = c.max
      if (c.not_stated === "include") sel.ns = "include"
      r = { ...(r ?? {}), [c.facet]: sel }
    } else if (c.type === "text") {
      q = c.query
    }
  }
  return { f, r, q }
}

export function sortSpecs(
  sort: string | undefined
): SavedViewIn["body"]["sort"] {
  const s = sort ?? DEFAULT_SORT
  return [
    {
      field: s.replace(/^-/, ""),
      direction: s.startsWith("-") ? "desc" : "asc",
    },
  ]
}

export function sortFromSpecs(
  specs: { field: string; direction?: "asc" | "desc" }[] | undefined
): string | undefined {
  const s = specs?.[0]
  if (!s) return undefined
  const id = (s.direction ?? "desc") === "desc" ? `-${s.field}` : s.field
  return id === DEFAULT_SORT ? undefined : id
}

/** Saved view body from the current URL state. */
export function viewBody(s: ViewState): SavedViewIn["body"] {
  return {
    conditions: toConditionSet(s, { withText: true }),
    group_by: s.g ?? null,
    sort: sortSpecs(s.sort),
    scope: "matches",
  }
}

/** URL state from a saved view body. */
export function viewStateFromBody(body: {
  conditions?: unknown
  group_by?: string | null
  sort?: { field: string; direction?: "asc" | "desc" }[]
}): ViewState {
  return {
    ...fromConditionSet(body.conditions),
    g: body.group_by ?? undefined,
    sort: sortFromSpecs(body.sort),
  }
}

/** Two view states describe the same list (used to show "unsaved changes"). */
export function sameView(a: ViewState, b: ViewState): boolean {
  const norm = (s: ViewState) =>
    JSON.stringify(viewBody({ ...s, q: s.q?.trim() || undefined }))
  return norm(a) === norm(b)
}

// ---- words ----------------------------------------------------------------------------------

const VALUE_WORDS: Record<string, string> = {
  not_stated: "Not stated",
  yes: "Yes",
  no: "No",
  on_site: "On-site",
  hybrid: "Hybrid",
  remote: "Remote",
  worldwide: "Worldwide",
  regions: "Region list",
  country_only: "Country only",
  existing_right_required: "Existing right to work",
  sponsorship_possible: "Sponsorship possible",
  employee: "Employee",
  contractor: "Contractor",
  eor: "Employer of record",
  permanent: "Permanent",
  fixed_term: "Fixed term",
  contract: "Contract",
  none_stated: "None stated",
  bachelors: "Bachelor's",
  masters: "Master's",
  doctorate: "Doctorate",
  stated: "Stated",
  estimated: "Estimated",
  dated: "Dated",
  open_until_filled: "Open until filled",
  below_threshold: "Below threshold",
  places: "Specific places",
  anywhere: "Anywhere",
}

/** Display label for a facet value. Unknown values are shown as written. */
export function valueLabel(value: string): string {
  return VALUE_WORDS[value] ?? value.replace(/_/g, " ")
}

const YES_NO = new Set(["yes", "no", NOT_STATED])
const isYesNo = (entry: FacetCatalogEntry | undefined) =>
  !!entry?.values?.length && entry.values.every((v) => YES_NO.has(v.value))

const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

function valuePhrase(
  entry: FacetCatalogEntry | undefined,
  facet: string,
  value: string,
  negate: boolean
): string {
  const label = entry?.label ?? facet
  if (isYesNo(entry)) {
    const base =
      value === "yes"
        ? lower(label)
        : value === "no"
          ? `no ${lower(label)}`
          : `${lower(label)} not stated`
    return negate ? `not ${base}` : base
  }
  const v = lower(valueLabel(value))
  if (negate) return `${lower(label)} not ${v}`
  return `${lower(label)} ${v}`
}

/**
 * The active filter in plain words, e.g.
 * "Relocation required, sponsorship offered, not requiring a master's".
 */
export function summarise(
  s: Pick<MatchesSearch, "f" | "r" | "q">,
  catalog: FacetCatalogEntry[] = []
): string {
  const byFacet = new Map(catalog.map((c) => [c.facet, c]))
  const parts: string[] = []
  for (const [facet, sel] of Object.entries(s.f ?? {})) {
    const entry = byFacet.get(facet)
    const joiner = sel.m === "all" ? " and " : " or "
    if (sel.i?.length)
      parts.push(
        sel.i.map((v) => valuePhrase(entry, facet, v, false)).join(joiner)
      )
    for (const v of sel.e ?? []) parts.push(valuePhrase(entry, facet, v, true))
  }
  for (const [facet, sel] of Object.entries(s.r ?? {})) {
    const label = lower(byFacet.get(facet)?.label ?? facet)
    const span =
      sel.min !== undefined && sel.max !== undefined
        ? `${label} ${sel.min} to ${sel.max}`
        : sel.min !== undefined
          ? `${label} at least ${sel.min}`
          : sel.max !== undefined
            ? `${label} at most ${sel.max}`
            : label
    parts.push(sel.ns === "include" ? `${span} (or not stated)` : span)
  }
  const q = s.q?.trim()
  if (q) parts.push(`mentioning "${q}"`)
  const text = parts.join(", ")
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : ""
}
