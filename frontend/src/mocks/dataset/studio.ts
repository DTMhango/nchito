/**
 * Fictional Studio data for the mock backend: spec versions, check state, draft answers,
 * tailoring requests, rendered documents, packets and mail threads for three of the seeded
 * applications. Everyone and everything here is invented. Facts are cited by code
 * (F-101..F-106 from data/jobs, F-112.. from data/kit).
 */
import type { Schemas } from "@/lib/api/types"
import { applicationIdFor } from "./jobs"

type Spec = Schemas["ApplicationSpec-Output"]
type CheckResult = Schemas["CheckResult"]
type PacketOut = Schemas["PacketOut"]
type RunOut = Schemas["RunOut"]
type Requirement = Schemas["Requirement"]
type DraftAnswer = Schemas["DraftAnswer"]
type DocumentOut = Schemas["DocumentOut"]
type MailThreadOut = Schemas["MailThreadOut"]
type VersionSummary = Schemas["SpecVersionSummary"]
type Tailoring = NonNullable<Schemas["SpecStateOut"]["tailoring"]>

/** A tailoring run. The contract's `RunKind` has no tailoring kind; the UI reads only its cost. */
export type TailorRun = Omit<RunOut, "kind"> & { kind: string }

export type StudioEntry = {
  spec: Spec
  check_results: CheckResult[]
  /** The spec fingerprint the checks last ran on; checked while it matches the spec. */
  checked_print: string | null
  /** Reasons the server gives when cited facts changed after the check (tests set these). */
  stale_reasons: string[]
  versions: VersionSummary[]
  answers: DraftAnswer[]
  tailoring: Tailoring | null
  tailoring_error: string | null
  /** The run of the open tailoring request, advanced on each spec poll. */
  run_id: string | null
  packets: PacketOut[]
  documents: DocumentOut[]
  /** What the next "Tailor" does: draft a spec, or stop at the monthly AI budget. */
  outcome: "draft" | "budget_paused"
}

export type MockStudio = {
  entries: Record<string, StudioEntry>
  runs: TailorRun[]
  mail: MailThreadOut[]
}

/** Pricing Actuary at Luangwa Re: drafted, with problems to fix. */
export const STUDIO_DRAFTED = applicationIdFor(3)
/** Risk Data Manager at Copperline Energy: tailoring stops at the budget cap. */
export const STUDIO_BUDGET = applicationIdFor(4)
/** Head of Data at Kafue Analytics: not tailored yet; tailoring drafts a spec. */
export const STUDIO_FRESH = applicationIdFor(1)

export const BUDGET_ERROR =
  "This month's AI budget is used up, so tailoring stopped before drafting. It resumes when the cap is raised or the month turns."

const T0 = "2026-11-20T08:00:00Z"
const empty = (): Spec => ({
  headline: null,
  summary: null,
  competencies: [],
  experience: [],
  skills: [],
  letter: [],
  requirement_match: [],
})

/** The requirement match the draft step writes, against the posting's own requirements. */
export function matchRequirements(reqs: Requirement[]) {
  const evidence = [["F-103"], ["F-101", "F-106"], ["F-102"]]
  return reqs.map((r, i) => {
    const strength =
      i === reqs.length - 1 ? "partial" : i % 4 === 3 ? "gap" : "strong"
    return {
      requirement: r.text,
      strength: strength as "strong" | "partial" | "gap",
      evidence_fact_ids:
        strength === "gap" ? [] : evidence[i % evidence.length],
      note:
        strength === "gap"
          ? "Not in your Kit. Say so plainly or leave it out."
          : strength === "partial"
            ? "Shown through the executive committee reporting."
            : null,
    }
  })
}

export function draftedSpec(reqs: Requirement[]): Spec {
  return {
    headline: {
      text: "Pricing and data analyst who builds the models and the pipelines behind them",
      fact_ids: ["F-103"],
    },
    summary: {
      text: "Leads a small analytics team, writes production SQL and Python for pricing, and presents risk findings to the executive committee every quarter.",
      fact_ids: ["F-101", "F-103", "F-106"],
    },
    competencies: [
      { text: "Pricing models in SQL and Python", fact_ids: ["F-103"] },
      { text: "Board reporting in Power BI", fact_ids: ["F-102"] },
    ],
    experience: [
      {
        experience_id: "exp-1",
        title: "Head of Finance Operations",
        bullets: [
          {
            text: "Led a team of six analysts at a regional insurer for four years.",
            fact_ids: ["F-101"],
          },
          {
            text: "Built the board's monthly KPI pack in Power BI, replacing 30 spreadsheets.",
            fact_ids: ["F-102"],
          },
          {
            text: "Wrote production SQL and Python pipelines feeding pricing models.",
            fact_ids: ["F-103"],
          },
          {
            text: "Introduced rolling forecasts that cut planning time by 40%.",
            fact_ids: [],
          },
          {
            text: "Managed a ZMW 480 million annual operating budget.",
            fact_ids: ["F-113"],
          },
          {
            text: "Led a team of 14 accountants and analysts across three locations.",
            fact_ids: ["F-114"],
          },
        ],
      },
      {
        experience_id: "exp-2",
        title: "Credit Risk Analyst",
        bullets: [
          {
            text: "Built the scorecard used to approve 300 smallholder loans a year.",
            fact_ids: ["F-121"],
          },
          {
            text: "Presented quarterly risk findings to the executive committee.",
            fact_ids: ["F-106"],
          },
        ],
      },
    ],
    skills: ["SQL", "Python", "Power BI", "Oracle ERP"],
    letter: [
      {
        text: "I am applying for the Pricing Actuary role. I build pricing models and the data pipelines that feed them, and I would like to do that for a reinsurer.",
        fact_ids: ["F-103"],
      },
      {
        text: "For four years I led a team of six analysts at a regional insurer, and I present our risk findings to the executive committee each quarter.",
        fact_ids: ["F-101", "F-106"],
      },
      {
        text: "I rebuilt the board's monthly KPI pack in Power BI in 3 months, replacing 30 spreadsheets.",
        fact_ids: ["F-102"],
      },
      {
        text: "I am based in Lusaka and open to moving within southern Africa. I would be glad to talk.",
        fact_ids: ["F-105"],
      },
    ],
    requirement_match: matchRequirements(reqs),
  }
}

/** The questions on Luangwa Re's form, as the drafter answered them. */
export function draftedAnswers(): DraftAnswer[] {
  const a = (o: Partial<DraftAnswer> & { question: string }): DraftAnswer => ({
    outcome: "ask_owner",
    value: null,
    select: null,
    answer_id: null,
    material: true,
    reason: "Not in your answer bank.",
    pending_action_id: null,
    ...o,
  })
  return [
    a({
      question: "What is your notice period?",
      outcome: "value",
      value: "One month",
      answer_id: "an-1",
      material: false,
      reason: "From your answer bank.",
    }),
    a({
      question: "Do you require visa sponsorship?",
      reason: "Ask first: confirm it for this application.",
      answer_id: "an-2",
      pending_action_id: "c0000000-0000-4000-8000-000000000401",
    }),
    a({
      question: "Are you willing to relocate to Kitwe?",
      pending_action_id: "c0000000-0000-4000-8000-000000000402",
    }),
    a({
      question: "What is your gender?",
      outcome: "do_not_answer",
      select: "Prefer not to say",
      answer_id: "an-3",
      material: false,
      reason: "Never answered, by your rule.",
    }),
  ]
}

const at = (h: number) => new Date(Date.parse(T0) - h * 3_600_000).toISOString()

/** Mail about Luangwa Re's role: the sender and subject are untrusted text. */
function mailFor(app: string): MailThreadOut[] {
  const t = (
    n: number,
    o: Partial<MailThreadOut> & Pick<MailThreadOut, "classification">
  ): MailThreadOut => ({
    id: `d0000000-0000-4000-8000-00000000050${n}`,
    created_at: at(n * 20),
    updated_at: at(n * 20),
    application_id: app,
    subject: null,
    match_confidence: 0.92,
    needs_review: false,
    sender: null,
    last_message_at: at(n * 20),
    ...o,
  })
  return [
    t(1, {
      classification: "information_request",
      subject: "Pricing Actuary: please send your certificates",
      sender: "talent@luangwa-re.example.com",
      needs_review: true,
      match_confidence: 0.71,
    }),
    t(2, {
      classification: "confirmation",
      subject: "We received your application <b>LR-2026-114</b>",
      sender: "no-reply@careers.example.com",
    }),
  ]
}

export function seedStudio(
  reqsFor: (app: string) => Requirement[],
  check: (app: string, spec: Spec) => CheckResult[],
  print: (spec: Spec) => string
): MockStudio {
  const drafted = draftedSpec(reqsFor(STUDIO_DRAFTED))
  const blank = (outcome: StudioEntry["outcome"]): StudioEntry => ({
    spec: empty(),
    check_results: [],
    checked_print: null,
    stale_reasons: [],
    versions: [],
    answers: [],
    tailoring: null,
    tailoring_error: null,
    run_id: null,
    packets: [],
    documents: [],
    outcome,
  })
  const results = check(STUDIO_DRAFTED, drafted)
  return {
    entries: {
      [STUDIO_DRAFTED]: {
        ...blank("draft"),
        spec: drafted,
        check_results: results,
        checked_print: print(drafted),
        versions: [
          {
            version: 1,
            origin: "tailor",
            content_hash: "3f".repeat(32),
            created_at: T0,
            created_by: "system",
            status: results.some((r) => r.status === "block" && !r.waived)
              ? "block"
              : "warn",
          },
        ],
        answers: draftedAnswers(),
        tailoring: "done",
      },
      [STUDIO_BUDGET]: blank("budget_paused"),
      [STUDIO_FRESH]: blank("draft"),
    },
    runs: [],
    mail: mailFor(STUDIO_DRAFTED),
  }
}

export function newTailorRun(id: string, paused: boolean): TailorRun {
  const now = new Date().toISOString()
  return {
    id,
    created_at: now,
    updated_at: now,
    kind: "tailor",
    trigger: "manual",
    campaign_id: null,
    schedule_id: null,
    scheduled_for: null,
    dry_run: false,
    counts: {},
    proposed_actions: [],
    source_results: [],
    cost_minor: 0,
    cost_micros: paused ? 4_200 : 0,
    config_versions: {},
    status: paused ? "paused" : "queued",
    started_at: now,
    finished_at: paused ? now : null,
    error: paused ? BUDGET_ERROR : null,
  }
}
