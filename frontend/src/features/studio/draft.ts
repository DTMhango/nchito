/**
 * Pure Studio rules: the editable draft of a spec, claim tracing against the Kit, keyword
 * coverage, requirement evidence, template limits, check grouping and answer standing.
 * No React here, so every rule is unit-tested on its own.
 */
import type {
  AnswerOut,
  CheckResult,
  FactOut,
  GuardrailOut,
  JobDetail,
  PacketAnswer,
  PendingAction,
  RequirementMatch,
  Spec,
  SpecInput,
  SpecItem,
  TemplateOut,
} from "./api"

// ---------------------------------------------------------------------------
// The draft: the spec with a stable client key on every item (for editing and dnd-kit).
// ---------------------------------------------------------------------------

export type DraftItem = { key: string; text: string; fact_ids: string[] }
export type DraftExperience = {
  key: string
  experience_id: string
  title: string | null
  bullets: DraftItem[]
}
export type Draft = {
  headline: DraftItem | null
  summary: DraftItem | null
  competencies: DraftItem[]
  experience: DraftExperience[]
  skills: string[]
  letter: DraftItem[]
  requirement_match: RequirementMatch[]
}

let seq = 0
export const newKey = (prefix = "i") => `${prefix}-${++seq}`

const item = (s: SpecItem): DraftItem => ({
  key: newKey(),
  text: s.text,
  fact_ids: [...(s.fact_ids ?? [])],
})
const plain = (d: DraftItem): SpecItem => ({
  text: d.text,
  fact_ids: [...d.fact_ids],
})

export function toDraft(spec: Spec): Draft {
  return {
    headline: spec.headline ? item(spec.headline) : null,
    summary: spec.summary ? item(spec.summary) : null,
    competencies: (spec.competencies ?? []).map(item),
    experience: (spec.experience ?? []).map((e) => ({
      key: newKey("e"),
      experience_id: e.experience_id,
      title: e.title ?? null,
      bullets: (e.bullets ?? []).map(item),
    })),
    skills: [...(spec.skills ?? [])],
    letter: (spec.letter ?? []).map(item),
    requirement_match: structuredClone(spec.requirement_match ?? []),
  }
}

export function toSpec(d: Draft): SpecInput {
  return {
    headline: d.headline ? plain(d.headline) : null,
    summary: d.summary ? plain(d.summary) : null,
    competencies: d.competencies.map(plain),
    experience: d.experience.map((e) => ({
      experience_id: e.experience_id,
      title: e.title,
      bullets: e.bullets.map(plain),
    })),
    skills: [...d.skills],
    letter: d.letter.map(plain),
    requirement_match: structuredClone(d.requirement_match),
  }
}

/** A canonical fingerprint of a spec: equal fingerprints mean the same content. */
export function fingerprint(spec: Spec | SpecInput): string {
  const items = (xs: SpecItem[] | undefined) =>
    (xs ?? []).map((x) => [x.text, x.fact_ids ?? []])
  return JSON.stringify([
    spec.headline ? items([spec.headline]) : null,
    spec.summary ? items([spec.summary]) : null,
    items(spec.competencies),
    (spec.experience ?? []).map((e) => [
      e.experience_id,
      e.title ?? null,
      items(e.bullets),
    ]),
    spec.skills ?? [],
    items(spec.letter),
  ])
}

export const isEmptySpec = (spec: Spec) =>
  !spec.headline &&
  !spec.summary &&
  (spec.competencies ?? []).length === 0 &&
  (spec.experience ?? []).length === 0 &&
  (spec.letter ?? []).length === 0

/** Every claim in the draft, in reading order, with where it sits. */
export type ClaimRef = { item: DraftItem; doc: "cv" | "letter"; where: string }
export function claims(d: Draft): ClaimRef[] {
  const out: ClaimRef[] = []
  if (d.headline) out.push({ item: d.headline, doc: "cv", where: "Headline" })
  if (d.summary) out.push({ item: d.summary, doc: "cv", where: "Summary" })
  d.competencies.forEach((c, i) =>
    out.push({ item: c, doc: "cv", where: `Competency ${i + 1}` })
  )
  d.experience.forEach((e) =>
    e.bullets.forEach((b, i) =>
      out.push({
        item: b,
        doc: "cv",
        where: `${e.title ?? "Experience"}, bullet ${i + 1}`,
      })
    )
  )
  d.letter.forEach((p, i) =>
    out.push({ item: p, doc: "letter", where: `Letter, paragraph ${i + 1}` })
  )
  return out
}

// ---------------------------------------------------------------------------
// Claim tracing (DESIGN 9.3): every claim rests on approved Kit facts.
// ---------------------------------------------------------------------------

export type FactIndex = Map<string, FactOut>
/** Facts are cited by id or by code ("F-112"); index both. */
export function indexFacts(facts: FactOut[]): FactIndex {
  const m: FactIndex = new Map()
  for (const f of facts) {
    m.set(f.id, f)
    m.set(f.code, f)
  }
  return m
}

export type TraceState = "traced" | "untraced" | "unapproved"
export type Trace = {
  state: TraceState
  /** The cited facts that exist. */
  facts: FactOut[]
  /** Cited ids that are not in the Kit. */
  missing: string[]
  /** Figures in the text that none of the cited facts contain. */
  strayFigures: string[]
}

const FIGURE = /\d[\d,.]*\s?%?/g
const normFigure = (s: string) =>
  s.replace(/[,\s]/g, "").replace(/\.$/, "").toLowerCase()

/** Figures written in the text (numbers, amounts, percentages, years). */
export function figuresIn(text: string): string[] {
  return [...new Set((text.match(FIGURE) ?? []).map(normFigure))].filter(
    Boolean
  )
}

export function traceClaim(item: DraftItem, index: FactIndex): Trace {
  const facts: FactOut[] = []
  const missing: string[] = []
  for (const id of item.fact_ids) {
    const f = index.get(id)
    if (f) {
      if (!facts.includes(f)) facts.push(f)
    } else missing.push(id)
  }
  const factFigures = new Set(facts.flatMap((f) => figuresIn(f.text)))
  const strayFigures =
    facts.length > 0
      ? figuresIn(item.text).filter((n) => !factFigures.has(n))
      : []
  let state: TraceState = "traced"
  if (facts.length === 0) state = "untraced"
  else if (missing.length > 0 || facts.some((f) => f.status !== "approved"))
    state = "unapproved"
  return { state, facts, missing, strayFigures }
}

export type TraceSummary = { total: number; traced: number; flagged: number }
export function traceSummary(d: Draft, index: FactIndex): TraceSummary {
  const all = claims(d).filter((c) => c.item.text.trim())
  const traced = all.filter((c) => {
    const t = traceClaim(c.item, index)
    return t.state === "traced" && t.strayFigures.length === 0
  }).length
  return { total: all.length, traced, flagged: all.length - traced }
}

// ---------------------------------------------------------------------------
// The job side: requirements with their evidence, and keyword coverage.
// ---------------------------------------------------------------------------

const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ")

export type RequirementRow = {
  text: string
  kind: "required" | "preferred"
  match: RequirementMatch | null
}

/** The posting's requirements, each with the draft's match (or none: not assessed). */
export function requirementRows(
  job: Pick<JobDetail, "requirements"> | undefined,
  matches: RequirementMatch[]
): RequirementRow[] {
  const used = new Set<RequirementMatch>()
  const rows: RequirementRow[] = (job?.requirements ?? []).map((r) => {
    const m =
      matches.find(
        (x) => !used.has(x) && norm(x.requirement) === norm(r.text)
      ) ??
      (r.skill
        ? matches.find(
            (x) =>
              !used.has(x) &&
              norm(x.requirement).includes(norm(r.skill as string))
          )
        : undefined) ??
      null
    if (m) used.add(m)
    return { text: r.text, kind: r.kind ?? "required", match: m }
  })
  for (const m of matches)
    if (!used.has(m))
      rows.push({ text: m.requirement, kind: "required", match: m })
  return rows
}

/** All the words that will be sent, for keyword coverage. */
export function draftText(d: Draft): string {
  return [
    ...claims(d).map((c) => c.item.text),
    ...d.skills,
    ...d.experience.map((e) => e.title ?? ""),
  ].join("\n")
}

export type Keyword = { word: string; covered: boolean }
export function keywordCoverage(
  job: Pick<JobDetail, "facets" | "requirements"> | undefined,
  d: Draft
): Keyword[] {
  if (!job) return []
  const words = [
    ...(job.facets.required_skills ?? []),
    ...(job.facets.preferred_skills ?? []),
    ...job.requirements.flatMap((r) => (r.skill ? [r.skill] : [])),
  ]
  const seen = new Set<string>()
  const text = norm(draftText(d))
  const out: Keyword[] = []
  for (const w of words) {
    const k = norm(w)
    if (!k || seen.has(k)) continue
    seen.add(k)
    out.push({ word: w, covered: mentions(text, k) })
  }
  return out
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
/** A whole-word mention: "R" is not covered by "reporting", "C#" is by "C# and SQL". */
export function mentions(text: string, keyword: string): boolean {
  return new RegExp(
    `(^|[^\\p{L}\\p{N}])${escapeRe(keyword)}(?=$|[^\\p{L}\\p{N}])`,
    "iu"
  ).test(text)
}

// ---------------------------------------------------------------------------
// Template limits (DESIGN 5.3 `limit`, 9 rendering). Counted exactly where the spec allows.
// ---------------------------------------------------------------------------

export type LimitWarning = { doc: "cv" | "letter"; text: string }
export function limitWarnings(
  d: Draft,
  cv: TemplateOut | undefined,
  letter: TemplateOut | undefined
): LimitWarning[] {
  const out: LimitWarning[] = []
  const perRole = cv?.limits?.bullets_per_role
  if (perRole)
    for (const e of d.experience)
      if (e.bullets.length > perRole)
        out.push({
          doc: "cv",
          text: `${e.title ?? "A role"} has ${e.bullets.length} bullets; ${cv!.name} allows ${perRole}.`,
        })
  const paras = letter?.limits?.paragraphs
  if (paras && d.letter.length > paras)
    out.push({
      doc: "letter",
      text: `The letter has ${d.letter.length} paragraphs; ${letter!.name} allows ${paras}.`,
    })
  return out
}

// ---------------------------------------------------------------------------
// Checks (DESIGN 5.3, 9.3): grouped by severity; waivers only where the rule allows one.
// ---------------------------------------------------------------------------

export type Waivability =
  | { kind: "waivable"; guardrail: GuardrailOut }
  | { kind: "always_block"; reason: string }
  | { kind: "none" }

/** Can this result be waived once? Never for always-block rules or fact tracing. */
export function waivability(
  r: CheckResult,
  guardrails: GuardrailOut[]
): Waivability {
  if (r.status !== "block" || r.waived) return { kind: "none" }
  const g = r.guardrail_id
    ? guardrails.find((x) => x.id === r.guardrail_id)
    : undefined
  if (g?.strictness === "block_waivable_once")
    return { kind: "waivable", guardrail: g }
  if (isFactCheck(r))
    return {
      kind: "always_block",
      reason: "Fact tracing always blocks. Cite a fact or change the wording.",
    }
  return {
    kind: "always_block",
    reason: g
      ? "This rule always blocks. Change the wording to clear it."
      : "This check always blocks. Change the draft to clear it.",
  }
}

export const isFactCheck = (r: CheckResult) => /fact|claim/i.test(r.check)

export function checkLabel(r: CheckResult, guardrails: GuardrailOut[]) {
  const g = r.guardrail_id
    ? guardrails.find((x) => x.id === r.guardrail_id)
    : undefined
  if (g) return g.name
  const words = r.check.replace(/[_.-]+/g, " ").trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export type CheckGroups = {
  block: CheckResult[]
  warn: CheckResult[]
  /** Blocking results let through once for this application: always shown, never hidden. */
  waived: CheckResult[]
  pass: CheckResult[]
}
export function groupChecks(results: CheckResult[]): CheckGroups {
  return {
    block: results.filter((r) => r.status === "block" && !r.waived),
    warn: results.filter((r) => r.status === "warn"),
    waived: results.filter((r) => r.status === "block" && r.waived),
    pass: results.filter((r) => r.status === "pass"),
  }
}

// ---------------------------------------------------------------------------
// Screening answers (DESIGN 5.4). Unknown is not yes: only a confirmed bank answer shows
// a value as the answer.
// ---------------------------------------------------------------------------

export type AnswerStanding =
  | { kind: "confirmed"; value: string; answer: AnswerOut }
  | { kind: "declined"; select: string | null; answer: AnswerOut }
  | { kind: "unconfirmed"; reason: string; answer: AnswerOut }
  | { kind: "owner_only"; answer: AnswerOut }
  | { kind: "unknown" }

export type ScreeningRow = {
  question: string
  material: boolean
  standing: AnswerStanding
  /** The open pending action that asks the owner, when there is one. */
  action?: PendingAction
}

const dueForReview = (a: AnswerOut, today: string) =>
  !!a.review_after && a.review_after <= today

export function answerStanding(
  pa: PacketAnswer,
  bank: AnswerOut[],
  today: string
): AnswerStanding {
  const a = pa.answer_id ? bank.find((x) => x.id === pa.answer_id) : undefined
  if (!a) return { kind: "unknown" }
  if (a.answer_class === "never")
    return { kind: "declined", select: a.forced_choice ?? null, answer: a }
  if (a.answer_class === "owner_only") return { kind: "owner_only", answer: a }
  if (a.review_state === "needs_review")
    return {
      kind: "unconfirmed",
      reason: "Imported, not reviewed yet",
      answer: a,
    }
  if (dueForReview(a, today))
    return { kind: "unconfirmed", reason: "Due for review", answer: a }
  if (a.answer_class === "ask_first" && !a.settled)
    return {
      kind: "unconfirmed",
      reason: "Ask first: confirm it for this application",
      answer: a,
    }
  if (a.value == null || a.value === "") return { kind: "unknown" }
  return { kind: "confirmed", value: a.value, answer: a }
}

const QUESTION_ACTIONS = new Set<PendingAction["type"]>([
  "unknown_question",
  "declaration",
  "assessment",
])
const actionQuestion = (p: PendingAction) =>
  typeof p.detail?.question === "string" ? p.detail.question : p.title

/** The form's questions: the packet's answers plus any question still waiting on the owner. */
export function screeningRows(
  answers: PacketAnswer[],
  bank: AnswerOut[],
  pending: PendingAction[],
  applicationId: string,
  today: string
): ScreeningRow[] {
  const open = pending.filter(
    (p) =>
      p.application_id === applicationId &&
      p.status === "open" &&
      QUESTION_ACTIONS.has(p.type)
  )
  const rows: ScreeningRow[] = answers.map((pa) => ({
    question: pa.question,
    material: !!pa.material,
    standing: answerStanding(pa, bank, today),
    action: open.find((p) => norm(actionQuestion(p)) === norm(pa.question)),
  }))
  for (const p of open)
    if (!rows.some((r) => r.action === p))
      rows.push({
        question: actionQuestion(p),
        material: true,
        standing: { kind: "unknown" },
        action: p,
      })
  return rows
}

export const needsOwner = (r: ScreeningRow) =>
  r.standing.kind === "unknown" ||
  r.standing.kind === "unconfirmed" ||
  r.standing.kind === "owner_only"

// ---------------------------------------------------------------------------
// Moving items.
// ---------------------------------------------------------------------------

export function move<T>(list: T[], from: number, to: number): T[] {
  if (
    from === to ||
    from < 0 ||
    to < 0 ||
    from >= list.length ||
    to >= list.length
  )
    return list
  const next = [...list]
  const [x] = next.splice(from, 1)
  next.splice(to, 0, x)
  return next
}
