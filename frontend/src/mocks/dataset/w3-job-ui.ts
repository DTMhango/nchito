/**
 * Fictional data for the wave 3 job-ui screens (interview pack, compare, posting changes).
 * Everything is invented. Shapes are the temporary ones in `features/jobs/w3-pending-types.ts`.
 */
import type {
  InterviewPack,
  PackItem,
  PackSection,
  PackSectionKey,
  PostingChanges,
} from "@/features/jobs/w3-pending-types"
import { appliedJobId, applicationIdFor } from "./jobs"

const iso = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86_400_000).toISOString()

export const SECTION_TITLES: Record<PackSectionKey, string> = {
  role_brief: "Role brief",
  why_you: "Why you",
  questions: "Likely questions",
  stories: "Stories for the requirements",
  ask: "Questions to ask them",
  gaps: "Your gaps and how to handle them",
  logistics: "Pay and logistics",
  crib: "Crib sheet",
}
export const SECTION_ORDER = Object.keys(SECTION_TITLES) as PackSectionKey[]

const item = (
  id: string,
  text: string,
  extra: Partial<PackItem> = {}
): PackItem => ({
  id,
  text,
  fact_ids: [],
  flag: null,
  owner_claim: false,
  ...extra,
})

/** The items of one section. Fact codes F-101..F-106 are in the mock Kit. */
function itemsFor(
  key: PackSectionKey,
  title: string,
  employer: string,
  { untraced }: { untraced: boolean }
): PackItem[] {
  switch (key) {
    case "role_brief":
      return [
        item(
          "rb1",
          `${title} at ${employer}: owns the reporting and analytics roadmap and leads a small team. Expect questions on stakeholder management and delivery.`
        ),
      ]
    case "why_you":
      return [
        item(
          "wy1",
          "You have led a team of six analysts for four years, which matches the size of this team.",
          { owner_claim: true, fact_ids: ["F-101"] }
        ),
        item(
          "wy2",
          "You replaced 30 spreadsheets with one monthly Power BI KPI pack for the board.",
          { owner_claim: true, fact_ids: ["F-102"] }
        ),
        ...(untraced
          ? [
              item(
                "wy3",
                "You raised forecast accuracy by 40% in your last role.",
                { owner_claim: true, fact_ids: [], flag: "untraced" as const }
              ),
            ]
          : []),
      ]
    case "questions":
      return [
        item(
          "q1",
          "I rebuilt the pipelines in SQL and Python so pricing models ran on one source.",
          {
            owner_claim: true,
            fact_ids: ["F-103"],
            category: "technical",
            question:
              "How would you structure a reporting pipeline from scratch?",
          }
        ),
        item(
          "q2",
          "I led six analysts for four years and set weekly one-to-ones and a shared backlog.",
          {
            owner_claim: true,
            fact_ids: ["F-101"],
            category: "leadership",
            question: "How do you lead a team of analysts?",
          }
        ),
        item(
          "q3",
          "I presented quarterly risk findings to the executive committee.",
          {
            owner_claim: true,
            fact_ids: ["F-106"],
            category: "behavioural",
            question:
              "Tell me about a time you had to explain a hard finding to executives.",
          }
        ),
        item(
          "q4",
          `The ${title} scope and ${employer}'s direction fit where I want to grow.`,
          {
            category: "motivation",
            question: `Why ${employer}?`,
          }
        ),
      ]
    case "stories":
      return [
        item(
          "s1",
          "The board received 30 separate spreadsheets every month. I built one Power BI KPI pack with agreed definitions. 30 spreadsheets became one pack the board reads in minutes.",
          {
            owner_claim: true,
            fact_ids: ["F-102"],
            requirement:
              "Clear written communication with non-technical leaders",
            star: {
              situation:
                "The board received 30 separate spreadsheets every month.",
              action: "I built one Power BI KPI pack with agreed definitions.",
              result:
                "30 spreadsheets became one pack the board reads in minutes.",
            },
          }
        ),
        item(
          "s2",
          "A team of six analysts with no shared priorities. I set a single backlog and weekly reviews. The team delivered on a predictable monthly cycle.",
          {
            owner_claim: true,
            fact_ids: ["F-101"],
            requirement: "Team leadership",
            star: {
              situation: "A team of six analysts with no shared priorities.",
              action: "I set a single backlog and weekly reviews.",
              result: "The team delivered on a predictable monthly cycle.",
            },
          }
        ),
      ]
    case "ask":
      return [
        item("a1", "What does success look like in the first six months?"),
        item(
          "a2",
          "How is the analytics team's work prioritised against requests from other teams?"
        ),
      ]
    case "gaps":
      return [
        item(
          "g1",
          "The posting asks for cloud data platform experience. Your Kit has SQL and Python pipelines but no cloud platform fact: say so, and describe how you learn tools.",
          { owner_claim: true, fact_ids: ["F-103"] }
        ),
      ]
    case "logistics":
      return [
        item("l1", "", {
          label: "Pay you told them",
          value: null,
        }),
        item("l2", "", { label: "Your pay floor", value: null }),
        item("l3", "", {
          label: "Where you live",
          value: "Lusaka, open to relocation within southern Africa",
          owner_claim: true,
          fact_ids: ["F-105"],
        }),
        item("l4", "", { label: "Notice period", value: null }),
      ]
    case "crib":
      return [
        item("c1", "Lead with the board KPI pack story.", {
          owner_claim: true,
          fact_ids: ["F-102"],
        }),
        item("c2", "Ask about the first six months."),
        item(
          "c3",
          "Pay, notice period and floor: decide before the interview."
        ),
      ]
  }
}

export type PackRecord = {
  pack: InterviewPack
  /** Every version of every section, to restore from. */
  history: Record<string, Record<number, PackItem[]>>
  title: string
  employer: string
  untraced: boolean
}

export function makeSection(
  key: PackSectionKey,
  rec: Pick<PackRecord, "title" | "employer" | "untraced">
): PackSection {
  return {
    key,
    title: SECTION_TITLES[key],
    version: 1,
    versions: [{ version: 1, created_at: iso(0), note: "First draft" }],
    notes: "",
    items: itemsFor(key, rec.title, rec.employer, rec),
  }
}

export function newPackRecord(
  applicationId: string,
  title: string,
  employer: string,
  opts: { ready: boolean; untraced: boolean }
): PackRecord {
  const base = { title, employer, untraced: opts.untraced }
  const sections = opts.ready
    ? SECTION_ORDER.map((k) => makeSection(k, base))
    : []
  const history: PackRecord["history"] = {}
  for (const s of sections) history[s.key] = { 1: structuredClone(s.items) }
  return {
    ...base,
    history,
    pack: {
      id: `p${applicationId.slice(-4)}`,
      application_id: applicationId,
      status: opts.ready ? "ready" : "generating",
      progress: {
        done: opts.ready ? SECTION_ORDER.length : 0,
        total: SECTION_ORDER.length,
      },
      based_on: {
        packet_label: "Packet 2, approved",
        cv_version: "CV v3",
        generated_at: iso(0),
      },
      paused: null,
      sections,
    },
  }
}

/** Posting changes for a few seeded roles; every other role has none. */
export function seedChanges(): Record<string, PostingChanges> {
  const none: PostingChanges = { items: [], stale_packet: null }
  void none
  return {
    [appliedJobId(1)]: {
      stale_packet: {
        application_id: applicationIdFor(1),
        changed_at: iso(1),
        reason: "The requirements changed and the role was assessed again.",
      },
      items: [
        {
          id: "c-pay",
          at: iso(1),
          kind: "pay_changed",
          material: true,
          field: "pay",
          before: "ZMW 480,000 to 560,000 a year",
          after: "ZMW 520,000 to 620,000 a year",
          note: null,
        },
        {
          id: "c-deadline",
          at: iso(2),
          kind: "deadline_moved",
          material: false,
          field: "deadline",
          before: "30 Nov 2026",
          after: "14 Dec 2026",
          note: null,
        },
        {
          id: "c-req",
          at: iso(3),
          kind: "requirements_changed",
          material: true,
          field: "requirements",
          before: "Remote worldwide",
          after: "Zambia residents only",
          note: "Where you may live changed.",
        },
        {
          id: "c-method",
          at: iso(5),
          kind: "method_changed",
          material: false,
          field: "apply_method",
          before: "Email",
          after: "Company careers site",
          note: null,
        },
      ],
    },
    [appliedJobId(2)]: {
      stale_packet: null,
      items: [
        {
          id: "c-fail",
          at: iso(0),
          kind: "check_failed",
          material: false,
          field: null,
          before: null,
          after: null,
          note: "The site did not respond.",
        },
      ],
    },
    [appliedJobId(3)]: {
      stale_packet: null,
      items: [
        {
          id: "c-closed",
          at: iso(1),
          kind: "closed",
          material: true,
          field: "availability",
          before: "Open",
          after: "Closed",
          note: "The posting page says applications have closed.",
        },
      ],
    },
  }
}
