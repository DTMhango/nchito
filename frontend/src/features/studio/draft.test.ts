import { describe, expect, it } from "vitest"
import type {
  AnswerOut,
  CheckResult,
  FactOut,
  GuardrailOut,
  TemplateOut,
} from "./api"
import {
  answerStanding,
  fingerprint,
  figuresIn,
  groupChecks,
  indexFacts,
  keywordCoverage,
  limitWarnings,
  mentions,
  move,
  requirementRows,
  screeningRows,
  toDraft,
  toSpec,
  traceClaim,
  waivability,
  type DraftItem,
} from "./draft"

const fact = (code: string, text: string, status = "approved") =>
  ({ id: `id-${code}`, code, text, status }) as FactOut
const facts = indexFacts([
  fact("F-1", "Cut month-end close from 12 working days to 5."),
  fact("F-2", "Led a team of six analysts.", "draft"),
])
const claim = (text: string, fact_ids: string[] = []): DraftItem => ({
  key: "k",
  text,
  fact_ids,
})

describe("claim tracing", () => {
  it("flags a claim with no facts, or none that exist, as untraced", () => {
    expect(traceClaim(claim("Did great work."), facts).state).toBe("untraced")
    expect(traceClaim(claim("Did great work.", ["F-9"]), facts).state).toBe(
      "untraced"
    )
  })
  it("accepts a fact cited by code or by id", () => {
    expect(traceClaim(claim("Close in 5 days.", ["F-1"]), facts).state).toBe(
      "traced"
    )
    expect(traceClaim(claim("Close in 5 days.", ["id-F-1"]), facts).state).toBe(
      "traced"
    )
  })
  it("marks a claim resting on a draft or missing fact as unapproved", () => {
    expect(traceClaim(claim("Led six.", ["F-2"]), facts).state).toBe(
      "unapproved"
    )
    expect(traceClaim(claim("Close.", ["F-1", "F-9"]), facts).missing).toEqual([
      "F-9",
    ])
  })
  it("catches a figure the cited facts do not contain", () => {
    const t = traceClaim(claim("Cut close from 12 days to 4.", ["F-1"]), facts)
    expect(t.strayFigures).toEqual(["4"])
    expect(figuresIn("ZMW 480,000 and 40%")).toEqual(["480000", "40%"])
  })
})

describe("draft round trip", () => {
  it("keeps the spec's content and its fingerprint", () => {
    const spec = {
      headline: { text: "H", fact_ids: ["F-1"] },
      summary: null,
      competencies: [],
      experience: [
        {
          experience_id: "e",
          title: "T",
          bullets: [{ text: "B", fact_ids: [] }],
        },
      ],
      skills: ["SQL"],
      letter: [],
      requirement_match: [],
    }
    const back = toSpec(toDraft(spec))
    expect(fingerprint(back)).toBe(fingerprint(spec))
    expect(back.experience?.[0].bullets?.[0].text).toBe("B")
  })
  it("moves an item and ignores moves out of range", () => {
    expect(move([1, 2, 3], 0, 2)).toEqual([2, 3, 1])
    expect(move([1, 2, 3], 0, 5)).toEqual([1, 2, 3])
  })
})

describe("the job side", () => {
  const job = {
    requirements: [
      { text: "Strong SQL", kind: "required" as const, skill: "SQL" },
      { text: "Experience with dbt", kind: "preferred" as const, skill: "dbt" },
    ],
    facets: { required_skills: ["SQL"], preferred_skills: ["dbt"] },
  } as never
  it("joins each requirement to its match, and keeps unmatched ones as not assessed", () => {
    const rows = requirementRows(job, [
      {
        requirement: "Strong SQL",
        strength: "strong",
        evidence_fact_ids: ["F-1"],
      },
    ])
    expect(rows.map((r) => r.match?.strength ?? null)).toEqual(["strong", null])
  })
  it("matches whole words only", () => {
    expect(mentions("risk reporting", "r")).toBe(false)
    expect(mentions("Python, R and SQL", "r")).toBe(true)
    expect(mentions("c# and sql", "c#")).toBe(true)
  })
  it("counts a keyword as covered only when the draft says it", () => {
    const d = toDraft({
      headline: null,
      summary: null,
      skills: ["SQL"],
      competencies: [],
      experience: [],
      letter: [],
      requirement_match: [],
    })
    expect(keywordCoverage(job, d)).toEqual([
      { word: "SQL", covered: true },
      { word: "dbt", covered: false },
    ])
  })
})

describe("template limits", () => {
  it("warns when a role has more bullets or the letter more paragraphs than allowed", () => {
    const d = toDraft({
      headline: null,
      summary: null,
      competencies: [],
      skills: [],
      requirement_match: [],
      experience: [
        {
          experience_id: "e",
          title: "Lead",
          bullets: [1, 2, 3].map((n) => ({ text: `b${n}` })),
        },
      ],
      letter: [1, 2].map((n) => ({ text: `p${n}` })),
    })
    const cv = {
      name: "Compact",
      limits: { bullets_per_role: 2 },
    } as TemplateOut
    const letter = { name: "Short", limits: { paragraphs: 1 } } as TemplateOut
    expect(limitWarnings(d, cv, letter).map((w) => w.doc)).toEqual([
      "cv",
      "letter",
    ])
    expect(limitWarnings(d, undefined, undefined)).toEqual([])
  })
})

describe("checks", () => {
  const rule = (id: string, strictness: GuardrailOut["strictness"]) =>
    ({ id, name: id, strictness }) as GuardrailOut
  const rules = [
    rule("g-wa", "block_waivable_once"),
    rule("g-al", "always_block"),
  ]
  const block = (check: string, guardrail_id: string | null, waived = false) =>
    ({ check, status: "block", guardrail_id, waived }) as CheckResult

  it("offers a waiver only for a block-waivable-once rule", () => {
    expect(waivability(block("guardrail", "g-wa"), rules).kind).toBe("waivable")
    expect(waivability(block("guardrail", "g-al"), rules).kind).toBe(
      "always_block"
    )
    expect(waivability(block("fact_tracing", null), rules).kind).toBe(
      "always_block"
    )
    expect(waivability(block("guardrail", "g-wa", true), rules).kind).toBe(
      "none"
    )
  })
  it("keeps waived results apart from what passed", () => {
    const g = groupChecks([
      block("guardrail", "g-wa", true),
      block("guardrail", "g-al"),
      { check: "limit", status: "warn" } as CheckResult,
      { check: "fact_tracing", status: "pass" } as CheckResult,
    ])
    expect([g.block, g.warn, g.waived, g.pass].map((x) => x.length)).toEqual([
      1, 1, 1, 1,
    ])
  })
})

describe("screening answers", () => {
  const answer = (o: Partial<AnswerOut>) =>
    ({
      id: "a",
      value: "Yes",
      answer_class: "auto",
      settled: true,
      review_state: "confirmed",
      review_after: null,
      patterns: { canonical: "Q" },
      ...o,
    }) as AnswerOut
  const today = "2026-11-26"
  const q = (answer_id: string | null) => ({
    question: "Q",
    value: "Yes",
    answer_id,
    material: false,
  })

  it("shows a value only for a confirmed bank answer", () => {
    expect(answerStanding(q("a"), [answer({})], today)).toMatchObject({
      kind: "confirmed",
      value: "Yes",
    })
  })
  it("treats no bank entry as unknown, whatever the packet holds", () => {
    expect(answerStanding(q(null), [], today).kind).toBe("unknown")
    expect(answerStanding(q("gone"), [answer({})], today).kind).toBe("unknown")
  })
  it("asks again for ask-first, imported or overdue answers", () => {
    for (const o of [
      { answer_class: "ask_first" as const, settled: false },
      { review_state: "needs_review" as const },
      { review_after: "2026-11-01" },
    ])
      expect(answerStanding(q("a"), [answer(o)], today).kind).toBe(
        "unconfirmed"
      )
  })
  it("adds an open question from a pending action that the packet lacks", () => {
    const rows = screeningRows(
      [],
      [],
      [
        {
          id: "p",
          type: "unknown_question",
          application_id: "app",
          status: "open",
          title: "New question",
          detail: { question: "Willing to travel 50%?" },
        } as never,
      ],
      "app",
      today
    )
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      question: "Willing to travel 50%?",
      standing: { kind: "unknown" },
    })
  })
})
