import { describe, expect, it } from "vitest"
import { nextFilterState, type FilterState } from "@/components/chip"
import { evaluate } from "@/mocks/handlers/matches-evaluator"
import {
  chipState,
  matchesSearchSchema,
  setChip,
  setMatch,
  summarise,
  toConditionSet,
  viewBody,
  viewStateFromBody,
  type ValueSels,
} from "./filters"
import type { FacetCatalogEntry, ValueFilter } from "./types"

const RELOC = "facets.relocation_required"

/** Click a chip the way FilterChip does: state -> next state. */
function click(f: ValueSels | undefined, facet: string, value: string) {
  const next: FilterState = nextFilterState(chipState(f, facet, value))
  return setChip(f, facet, value, next)
}

const leaf = (f: ValueSels | undefined) =>
  toConditionSet({ f }).root.conditions[0] as ValueFilter | undefined

describe("three-state chip and the query it produces", () => {
  it("cycles include -> exclude -> off", () => {
    let f = click(undefined, RELOC, "yes")
    expect(chipState(f, RELOC, "yes")).toBe("include")
    expect(leaf(f)).toEqual({
      type: "values",
      facet: RELOC,
      include: ["yes"],
      exclude: [],
      match: "any",
    })
    f = click(f, RELOC, "yes")
    expect(chipState(f, RELOC, "yes")).toBe("exclude")
    expect(leaf(f)).toMatchObject({ include: [], exclude: ["yes"] })
    f = click(f, RELOC, "yes")
    expect(chipState(f, RELOC, "yes")).toBe("off")
    expect(f).toBeUndefined()
    expect(toConditionSet({ f }).root.conditions).toEqual([])
  })

  it("treats not stated as a value of its own", () => {
    const f = click(undefined, RELOC, "not_stated")
    expect(leaf(f)).toMatchObject({ include: ["not_stated"], exclude: [] })
    const g = click(click(undefined, RELOC, "not_stated"), RELOC, "not_stated")
    expect(leaf(g)).toMatchObject({ include: [], exclude: ["not_stated"] })

    const stated = { facets: { relocation_required: { value: "yes" } } }
    const unstated = {
      facets: { relocation_required: { value: "not_stated" } },
    }
    const missing = { facets: {} }
    // Include "not stated" matches only records without a value.
    expect(evaluate(stated, leaf(f)!)).toBe(false)
    expect(evaluate(unstated, leaf(f)!)).toBe(true)
    expect(evaluate(missing, leaf(f)!)).toBe(true)
    // Include "yes" does not match a not-stated record.
    expect(evaluate(missing, leaf(click(undefined, RELOC, "yes"))!)).toBe(false)
    // Exclude "not stated" keeps every stated record.
    expect(evaluate(stated, leaf(g)!)).toBe(true)
    expect(evaluate(missing, leaf(g)!)).toBe(false)
  })

  it("combines values in a facet with any or all", () => {
    const SK = "facets.required_skills"
    let f = click(click(undefined, SK, "python"), SK, "sql")
    expect(leaf(f)).toMatchObject({ include: ["python", "sql"], match: "any" })
    const both = { facets: { required_skills: ["Python", "SQL"] } }
    const one = { facets: { required_skills: ["Python"] } }
    expect(evaluate(one, leaf(f)!)).toBe(true)
    f = setMatch(f, SK, "all")
    expect(leaf(f)).toMatchObject({ match: "all" })
    expect(evaluate(one, leaf(f)!)).toBe(false)
    expect(evaluate(both, leaf(f)!)).toBe(true)
    f = setMatch(f, SK, "any")
    expect(leaf(f)).toMatchObject({ match: "any" })
  })
})

describe("saved view and URL round-trip", () => {
  const state = {
    q: "analytics",
    f: {
      [RELOC]: { i: ["yes"] },
      "facets.visa_sponsorship": { i: ["yes"] },
      "facets.min_education.level": { e: ["masters"] },
      "facets.required_skills": { i: ["python", "sql"], m: "all" as const },
    },
    r: { "facets.years_experience": { min: 3, ns: "include" as const } },
    g: "facets.visa_sponsorship",
    sort: "-posted_at",
  }

  it("a view body reads back to the same state", () => {
    const body = viewBody(state)
    expect(body.group_by).toBe("facets.visa_sponsorship")
    expect(body.sort).toEqual([{ field: "posted_at", direction: "desc" }])
    expect(viewStateFromBody(body)).toEqual(state)
  })

  it("the URL search survives a JSON round trip and validation", () => {
    const url = JSON.parse(
      JSON.stringify({ tab: "held", ...state, view: "v1" })
    )
    expect(matchesSearchSchema.parse(url)).toEqual({
      tab: "held",
      ...state,
      view: "v1",
    })
  })

  it("bad URL values fall back instead of breaking the page", () => {
    expect(matchesSearchSchema.parse({ tab: "nope", f: 3 })).toEqual({
      tab: "new",
    })
  })
})

describe("plain-words summary", () => {
  const catalog: FacetCatalogEntry[] = [
    {
      facet: RELOC,
      label: "Relocation required",
      kind: "values",
      values: [
        { value: "yes", count: 1 },
        { value: "no", count: 1 },
        { value: "not_stated", count: 1 },
      ],
    },
    {
      facet: "facets.visa_sponsorship",
      label: "Sponsorship offered",
      kind: "values",
      values: [
        { value: "yes", count: 1 },
        { value: "no", count: 1 },
        { value: "not_stated", count: 1 },
      ],
    },
    {
      facet: "facets.min_education.level",
      label: "Minimum education",
      kind: "values",
      values: [{ value: "masters", count: 1 }],
    },
  ]
  it("reads like a sentence", () => {
    expect(
      summarise(
        {
          f: {
            [RELOC]: { i: ["yes"] },
            "facets.visa_sponsorship": { i: ["yes"] },
            "facets.min_education.level": { e: ["masters"] },
          },
        },
        catalog
      )
    ).toBe(
      "Relocation required, sponsorship offered, minimum education not master's"
    )
    expect(summarise({ f: { [RELOC]: { i: ["not_stated"] } } }, catalog)).toBe(
      "Relocation required not stated"
    )
  })
})
