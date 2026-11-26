/**
 * Fictional Studio data for the mock backend: tailored specs, check results, packets and
 * tailoring runs for three of the seeded applications. Everyone and everything here is
 * invented. Facts are cited by code (F-101..F-106 from data/jobs, F-112.. from data/kit).
 */
import type { Schemas } from "@/lib/api/types"
import { applicationIdFor } from "./jobs"

type Spec = Schemas["ApplicationSpec-Output"]
type CheckResult = Schemas["CheckResult"]
type PacketOut = Schemas["PacketOut"]
type RunOut = Schemas["RunOut"]
type Requirement = Schemas["Requirement"]

/** A tailoring run. The contract's `RunKind` has no tailoring kind yet; the UI never reads it. */
export type TailorRun = Omit<RunOut, "kind"> & { kind: string }

export type StudioEntry = {
  spec: Spec
  check_results: CheckResult[]
  packets: PacketOut[]
  /** What the next "Tailor" does: draft a spec, or stop at the monthly AI budget. */
  outcome: "draft" | "budget_paused"
}

export type MockStudio = {
  entries: Record<string, StudioEntry>
  runs: TailorRun[]
  /** Polls of each live run; a run finishes on its second poll. */
  polls: Record<string, number>
}

/** Pricing Actuary at Luangwa Re: drafted, with problems to fix. */
export const STUDIO_DRAFTED = applicationIdFor(3)
/** Risk Data Manager at Copperline Energy: tailoring stops at the budget cap. */
export const STUDIO_BUDGET = applicationIdFor(4)
/** Head of Data at Kafue Analytics: not tailored yet; tailoring drafts a spec. */
export const STUDIO_FRESH = applicationIdFor(1)

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

/** The questions on Luangwa Re's form, as the packet holds them. */
function draftedPacket(app: string): PacketOut {
  return {
    id: "b0000000-0000-4000-8000-000000000301",
    created_at: T0,
    updated_at: T0,
    application_id: app,
    version: 1,
    content_hash: "3f".repeat(32),
    approved_at: null,
    approved_by: null,
    invalidated_at: null,
    invalidated_reason: null,
    contents: {
      requisition: "LR-2026-114",
      destination: {
        url: "https://careers.example.com/luangwa-re/apply",
        domain: "careers.example.com",
        verified: true,
        trusted: false,
      },
      sending_identity: "owner@example.com",
      answers: [
        {
          question: "What is your notice period?",
          value: "One month",
          answer_id: "an-1",
          material: false,
        },
        {
          question: "Do you require visa sponsorship?",
          value: "No",
          answer_id: "an-2",
          material: true,
        },
        {
          question: "Are you willing to relocate to Kitwe?",
          value: "Yes",
          answer_id: null,
          material: true,
        },
        {
          question: "What is your gender?",
          value: "Prefer not to say",
          answer_id: "an-3",
          material: false,
        },
        {
          question: "Please sign the declaration below.",
          value: "",
          answer_id: "an-4",
          material: true,
        },
      ],
      email: null,
      files: [],
      link_permissions: [],
    },
  }
}

export function seedStudio(
  reqsFor: (app: string) => Requirement[],
  check: (app: string, spec: Spec) => CheckResult[]
): MockStudio {
  const drafted = draftedSpec(reqsFor(STUDIO_DRAFTED))
  return {
    entries: {
      [STUDIO_DRAFTED]: {
        spec: drafted,
        check_results: check(STUDIO_DRAFTED, drafted),
        packets: [draftedPacket(STUDIO_DRAFTED)],
        outcome: "draft",
      },
      [STUDIO_BUDGET]: {
        spec: empty(),
        check_results: [],
        packets: [],
        outcome: "budget_paused",
      },
      [STUDIO_FRESH]: {
        spec: empty(),
        check_results: [],
        packets: [],
        outcome: "draft",
      },
    },
    runs: [],
    polls: {},
  }
}

export function newTailorRun(id: string, paused: boolean): TailorRun {
  const at = new Date().toISOString()
  return {
    id,
    created_at: at,
    updated_at: at,
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
    started_at: at,
    finished_at: paused ? at : null,
    error: paused
      ? "This month's AI budget is used up, so tailoring stopped before drafting. It resumes when the cap is raised or the month turns."
      : null,
  }
}
