/**
 * A mock of the condition engine (CONTRACTS 5) so filtering genuinely works in mock mode.
 * Semantics follow the contract: missing, null, empty list and "not_stated" are all the value
 * `not_stated`; values compare case-insensitively; an exclude hit always fails; values inside
 * one facet use any/all; groups combine with and/or and may be negated.
 */
import type { Condition, ConditionSet } from "@/features/matches/types"

export const NOT_STATED = "not_stated"

type Rec = Record<string, unknown>

const isObj = (v: unknown): v is Rec =>
  typeof v === "object" && v !== null && !Array.isArray(v)

/** Follow a dotted path, unwrapping `{value, evidence}` wrappers on the way. */
export function resolve(record: unknown, path: string): unknown {
  let cur: unknown = record
  for (const part of path.split(".")) {
    if (isObj(cur) && "value" in cur && !(part in cur)) cur = cur.value
    if (!isObj(cur)) return undefined
    cur = cur[part]
  }
  if (isObj(cur) && "value" in cur) cur = cur.value
  return cur
}

/** The record's values for a facet, lower-cased; not stated becomes ["not_stated"]. */
export function facetValues(record: unknown, path: string): string[] {
  const v = resolve(record, path)
  const list = Array.isArray(v) ? v : [v]
  const out = list
    .filter((x) => x !== null && x !== undefined && x !== "")
    .map((x) => String(isObj(x) && "value" in x ? x.value : x).toLowerCase())
  return out.length ? out : [NOT_STATED]
}

function numberAt(record: unknown, path: string): number | null {
  const v = resolve(record, path)
  if (typeof v === "number") return v
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v)))
    return Number(v)
  return null
}

export function evaluate(record: unknown, c: Condition): boolean {
  switch (c.type) {
    case "group": {
      const results = c.conditions.map((x) => evaluate(record, x))
      const ok =
        c.op === "or"
          ? results.length === 0 || results.some(Boolean)
          : results.every(Boolean)
      return c.negate ? !ok : ok
    }
    case "values": {
      const have = new Set(facetValues(record, c.facet))
      const lc = (xs: unknown[]) => xs.map((x) => String(x).toLowerCase())
      if (lc(c.exclude ?? []).some((x) => have.has(x))) return false
      const inc = lc(c.include ?? [])
      if (!inc.length) return true
      return c.match === "all"
        ? inc.every((x) => have.has(x))
        : inc.some((x) => have.has(x))
    }
    case "range": {
      const n = numberAt(record, c.facet)
      if (n === null) return c.not_stated === "include"
      if (c.min != null && n < c.min) return false
      if (c.max != null && n > c.max) return false
      return true
    }
    case "text": {
      const q = c.query.trim().toLowerCase()
      if (!q) return true
      const fields = c.fields.length
        ? c.fields
        : ["title", "employer", "raw_text"]
      const hay = fields
        .map((f) => resolve(record, f))
        .filter((x) => typeof x === "string")
        .join("\n")
        .toLowerCase()
      return q.split(/\s+/).every((w) => hay.includes(w))
    }
  }
}

export function matches(
  record: unknown,
  set: ConditionSet | undefined
): boolean {
  if (!set?.root) return true
  return evaluate(record, set.root)
}

/** Count jobs per facet value; multi-valued facets count in several groups. */
export function groupCounts(
  records: unknown[],
  path: string
): { value: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const r of records)
    for (const v of new Set(facetValues(r, path)))
      counts.set(v, (counts.get(v) ?? 0) + 1)
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) =>
      a.value === NOT_STATED
        ? 1
        : b.value === NOT_STATED
          ? -1
          : b.count - a.count || a.value.localeCompare(b.value)
    )
}
