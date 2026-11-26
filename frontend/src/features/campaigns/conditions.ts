/**
 * The condition schema (DESIGN 6.1, 7): one shape shared by Matches filters, campaign
 * rules and rubric penalties. `conditionSetSchema` mirrors the API's ConditionSet so the
 * builder's output can be checked against it in tests.
 */
import { z } from "zod"
import type {
  ConditionGroup,
  ConditionSet,
  FacetCatalogEntry,
  ValueFilter,
} from "./types"

const scalar = z.union([z.string(), z.number(), z.boolean()])

const valueFilterSchema = z
  .object({
    type: z.literal("values"),
    facet: z.string().min(1),
    include: z.array(scalar).optional(),
    exclude: z.array(scalar).optional(),
    match: z.enum(["any", "all"]).optional(),
  })
  .strict()

const rangeFilterSchema = z
  .object({
    type: z.literal("range"),
    facet: z.string().min(1),
    min: z.number().nullable().optional(),
    max: z.number().nullable().optional(),
    not_stated: z.enum(["include", "exclude"]).optional(),
  })
  .strict()

const textFilterSchema = z
  .object({
    type: z.literal("text"),
    query: z.string().min(1),
    fields: z.array(z.string()).optional(),
  })
  .strict()

const groupSchema: z.ZodType<ConditionGroup> = z.lazy(() =>
  z
    .object({
      type: z.literal("group"),
      op: z.enum(["and", "or"]).optional(),
      negate: z.boolean().optional(),
      conditions: z
        .array(
          z.union([
            valueFilterSchema,
            rangeFilterSchema,
            textFilterSchema,
            groupSchema,
          ])
        )
        .optional(),
    })
    .strict()
) as z.ZodType<ConditionGroup>

export const conditionSetSchema = z
  .object({ version: z.literal(1).optional(), root: groupSchema })
  .strict()

export type Condition = NonNullable<ConditionGroup["conditions"]>[number]

export const NOT_STATED = "not_stated"

export function emptyConditionSet(): ConditionSet {
  return { version: 1, root: { type: "group", op: "and", conditions: [] } }
}

export const rootOf = (set: ConditionSet): ConditionGroup =>
  set.root ?? { type: "group", op: "and", conditions: [] }

export const conditionsOf = (set: ConditionSet): Condition[] =>
  rootOf(set).conditions ?? []

export type ChipState = "include" | "exclude" | "off"

export function chipState(
  f: ValueFilter | undefined,
  value: string
): ChipState {
  if (f?.include?.includes(value)) return "include"
  if (f?.exclude?.includes(value)) return "exclude"
  return "off"
}

/** Set one value's state in a value filter; empty lists are dropped. */
export function withChipState(
  f: ValueFilter,
  value: string,
  state: ChipState
): ValueFilter {
  const include = (f.include ?? []).filter((v) => v !== value)
  const exclude = (f.exclude ?? []).filter((v) => v !== value)
  if (state === "include") include.push(value)
  if (state === "exclude") exclude.push(value)
  const next: ValueFilter = { type: "values", facet: f.facet }
  if (include.length) next.include = include
  if (exclude.length) next.exclude = exclude
  if (f.match === "all") next.match = "all"
  return next
}

export function withMatch(f: ValueFilter, match: "any" | "all"): ValueFilter {
  const next: ValueFilter = { ...f }
  if (match === "all") next.match = "all"
  else delete next.match
  return next
}

/** A fresh condition for a facet, by the catalogue's kind. */
export function newCondition(entry: FacetCatalogEntry): Condition {
  if (entry.kind === "range")
    return { type: "range", facet: entry.facet, not_stated: "exclude" }
  if (entry.kind === "text")
    return { type: "text", query: "", fields: [entry.facet] }
  return { type: "values", facet: entry.facet }
}

export function replaceCondition(
  set: ConditionSet,
  index: number,
  next: Condition | null
): ConditionSet {
  const list = [...conditionsOf(set)]
  if (next) list[index] = next
  else list.splice(index, 1)
  return { ...set, version: 1, root: { ...rootOf(set), conditions: list } }
}

export function addCondition(set: ConditionSet, c: Condition): ConditionSet {
  return {
    ...set,
    version: 1,
    root: { ...rootOf(set), conditions: [...conditionsOf(set), c] },
  }
}

export function setRootOp(set: ConditionSet, op: "and" | "or"): ConditionSet {
  return { ...set, version: 1, root: { ...rootOf(set), op } }
}

const filters = (c: Condition): boolean => {
  if (c.type === "values")
    return (c.include?.length ?? 0) + (c.exclude?.length ?? 0) > 0
  if (c.type === "range") return c.min != null || c.max != null
  if (c.type === "text") return c.query.trim().length > 0
  return true
}

/**
 * What is sent to the API: conditions that filter nothing (no chosen values, no bounds,
 * empty text) are dropped so the schema is always satisfied.
 */
export function cleanConditionSet(set: ConditionSet): ConditionSet {
  return {
    version: 1,
    root: { ...rootOf(set), conditions: conditionsOf(set).filter(filters) },
  }
}

export const isEmptyConditionSet = (set: ConditionSet): boolean =>
  conditionsOf(cleanConditionSet(set)).length === 0

export function isValidConditionSet(set: ConditionSet): boolean {
  return conditionSetSchema.safeParse(cleanConditionSet(set)).success
}

export function valueLabel(v: string | number | boolean): string {
  if (v === NOT_STATED) return "not stated"
  if (v === true) return "yes"
  if (v === false) return "no"
  return String(v).replaceAll("_", " ")
}

/** Plain-words summary of one condition, for lists and previews. */
export function describeCondition(
  c: Condition,
  labelOf: (facet: string) => string
): string {
  if (c.type === "values") {
    const bits: string[] = []
    if (c.include?.length)
      bits.push(
        `${labelOf(c.facet)} is ${c.include.map(valueLabel).join(c.match === "all" ? " and " : " or ")}`
      )
    if (c.exclude?.length)
      bits.push(
        `${labelOf(c.facet)} is not ${c.exclude.map(valueLabel).join(" or ")}`
      )
    return bits.join("; ") || `${labelOf(c.facet)} (nothing chosen)`
  }
  if (c.type === "range") {
    const lo = c.min != null ? `at least ${c.min}` : ""
    const hi = c.max != null ? `at most ${c.max}` : ""
    return `${labelOf(c.facet)} ${[lo, hi].filter(Boolean).join(" and ") || "(no limits)"}`
  }
  if (c.type === "text") return `Text contains "${c.query}"`
  return "A group of conditions"
}
