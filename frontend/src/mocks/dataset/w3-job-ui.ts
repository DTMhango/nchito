/**
 * Fictional data for the wave 3 job-page screens (interview pack, posting changes). Everything is
 * invented. Shapes are the generated contract's (`InterviewPackOut`, `InterviewSectionOut`,
 * `JobChangesOut`); section content follows `features/jobs/interview/shapes.ts`.
 */
import type { components } from "@/lib/api/types"
import type {
  Basis,
  SectionContent,
  SectionKey,
} from "@/features/jobs/interview/shapes"
import { appliedJobId, applicationIdFor } from "./jobs"

type S = components["schemas"]
type InterviewPack = S["InterviewPackOut"]
type SectionVersion = S["InterviewSectionOut"]
type JobChanges = S["JobChangesOut"]
type JobChange = S["JobChangeOut"]

const iso = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86_400_000).toISOString()

/** The sections a mock pack has, in order (the server's `interview.sections` default). */
export const MOCK_SECTIONS: SectionKey[] = [
  "role_brief",
  "why_you",
  "questions",
  "stories",
  "questions_to_ask",
  "gaps",
  "pay_sheet",
  "crib_sheet",
]
/** Upper-bound cost per model-built section, micros. */
export const SECTION_ESTIMATE_MICROS = 30_000
export const MODEL_SECTIONS: SectionKey[] = MOCK_SECTIONS.filter(
  (s) => s !== "pay_sheet" && s !== "crib_sheet"
)

const DECIDE = "Decide before the interview"

/** The content of one section. Fact codes F-101..F-106 are in the mock Kit. */
export function contentFor(
  key: SectionKey,
  title: string,
  employer: string,
  { untraced }: { untraced: boolean }
): SectionContent[SectionKey] {
  switch (key) {
    case "role_brief":
      return {
        summary: `${title} at ${employer}: owns the reporting and analytics roadmap and leads a small team.`,
        emphasised: ["Stakeholder management", "Delivery on a monthly cycle"],
        requirements: ["SQL", "Team leadership"],
        level_notes: "Expect questions on how you set priorities for a team.",
        company_notes: [],
        research_note:
          "No web research was done: company notes come only from the posting and your own notes.",
        posting_changed: false,
      }
    case "why_you":
      return {
        points: [
          {
            requirement: "Team leadership",
            point: {
              text: "You have led a team of six analysts for four years.",
              fact_ids: ["F-101"],
            },
          },
          {
            requirement: "Reporting",
            point: {
              text: "You replaced 30 spreadsheets with one monthly Power BI KPI pack for the board.",
              fact_ids: ["F-102"],
            },
          },
          ...(untraced
            ? [
                {
                  requirement: "Forecasting",
                  point: {
                    text: "You raised forecast accuracy by 40% in your last role.",
                    fact_ids: [],
                  },
                },
              ]
            : []),
        ],
      }
    case "questions":
      return {
        items: [
          {
            category: "technical",
            question:
              "How would you structure a reporting pipeline from scratch?",
            why_asked: "The posting stresses one source of truth.",
            answer: {
              text: "I rebuilt the pipelines in SQL and Python so pricing models ran on one source.",
              fact_ids: ["F-103"],
            },
            story_ids: [],
          },
          {
            category: "behavioural",
            question:
              "Tell me about a time you had to explain a hard finding to executives.",
            why_asked: "",
            answer: {
              text: "I presented quarterly risk findings to the executive committee.",
              fact_ids: ["F-106"],
            },
            story_ids: ["s1"],
          },
          {
            category: "motivation",
            question: `Why ${employer}?`,
            why_asked: "",
            answer: {
              text: `The ${title} scope fits where I want to grow.`,
              fact_ids: [],
            },
            story_ids: [],
          },
        ],
      }
    case "stories":
      return {
        items: [
          {
            id: "s1",
            title: "The board KPI pack",
            requirement:
              "Clear written communication with non-technical leaders",
            situation:
              "The board received 30 separate spreadsheets every month.",
            task: "Give the board one view it could read quickly.",
            action: "I built one Power BI KPI pack with agreed definitions.",
            result:
              "30 spreadsheets became one pack the board reads in minutes.",
            fact_ids: ["F-102"],
            favourite: false,
          },
          {
            id: "s2",
            title: "One backlog for the team",
            requirement: "Team leadership",
            situation: "A team of six analysts with no shared priorities.",
            task: "Make delivery predictable.",
            action: "I set a single backlog and weekly reviews.",
            result: "The team delivered on a predictable monthly cycle.",
            fact_ids: ["F-101"],
            favourite: false,
          },
        ],
      }
    case "questions_to_ask":
      return {
        items: [
          {
            question: "What does success look like in the first six months?",
            why: "",
          },
          {
            question: "How is the analytics team's work prioritised?",
            why: "The posting mentions requests from many teams.",
          },
        ],
      }
    case "gaps":
      return {
        items: [
          {
            requirement: "Cloud data platform",
            gap: "Your Kit has SQL and Python pipelines but no cloud platform fact.",
            answer: {
              text: "Say so plainly, and describe the pipelines you rebuilt in SQL and Python.",
              fact_ids: ["F-103"],
            },
          },
        ],
      }
    case "pay_sheet":
      return {
        posting_pay: null,
        lines: [
          {
            topic: "Pay you told them",
            question: "What salary are you expecting?",
            status: "decide",
            kit_answer: null,
            told_them: null,
            note: `${DECIDE}: no confirmed answer in your Kit.`,
          },
          {
            topic: "Notice period",
            question: "When could you start?",
            status: "decide",
            kit_answer: null,
            told_them: null,
            note: `${DECIDE}: no confirmed answer in your Kit.`,
          },
          {
            topic: "Where you live",
            question: "Where are you based?",
            status: "confirmed",
            kit_answer: "Lusaka",
            told_them: null,
            note: "",
          },
        ],
      }
    case "crib_sheet":
      return {
        role: `${title}, ${employer}`,
        points: ["Lead with the board KPI pack story."],
        stories: ["The board KPI pack"],
        questions_to_ask: [
          "What does success look like in the first six months?",
        ],
        pay: ["Pay you told them: decide before the interview"],
        gaps: ["Cloud data platform"],
        flagged: untraced ? ["why_you"] : [],
      }
  }
}

/** A stored version of a section, as the versions endpoint returns it. */
export function makeVersion(
  key: SectionKey,
  version: number,
  content: SectionContent[SectionKey],
  opts: { origin?: SectionVersion["origin"]; flagged?: boolean } = {}
): SectionVersion {
  const flagged = opts.flagged ?? false
  const at = new Date().toISOString()
  return {
    id: `v-${key}-${version}`,
    created_at: at,
    updated_at: at,
    section: key,
    version,
    origin:
      opts.origin ??
      (key === "pay_sheet" || key === "crib_sheet" ? "code" : "generated"),
    content: content as unknown as Record<string, unknown>,
    fact_ids: [],
    check_results: flagged
      ? [
          {
            check: "fact_trace",
            status: "block",
            detail: '"40%" is not in any approved fact',
            guardrail_id: null,
            waived: false,
          },
        ]
      : [
          {
            check: "fact_trace",
            status: "pass",
            detail: null,
            guardrail_id: null,
            waived: false,
          },
        ],
    status: flagged ? "block" : "pass",
    flagged,
    model: key === "pay_sheet" || key === "crib_sheet" ? null : "mock-model",
    created_by: opts.origin === "owner" ? "owner" : "system",
  }
}

/** The pack's mirror entry of a version (`InterviewPackOut.sections[key]`). */
export const mirrorOf = (v: SectionVersion) => ({
  version: v.version,
  origin: v.origin,
  status: v.status,
  flagged: v.flagged,
  fact_ids: v.fact_ids,
  content: v.content,
  check_results: v.check_results,
  model: v.model,
  created_at: v.created_at,
})

export type PackRecord = {
  pack: InterviewPack
  /** Every version of every section, oldest first. */
  versions: Partial<Record<SectionKey, SectionVersion[]>>
  title: string
  employer: string
  untraced: boolean
}

export function newPackRecord(
  jobId: string,
  applicationId: string | null,
  title: string,
  employer: string,
  opts: { ready: boolean; untraced: boolean; basis?: Basis }
): PackRecord {
  const at = iso(0)
  const rec: PackRecord = {
    title,
    employer,
    untraced: opts.untraced,
    versions: {},
    pack: {
      id: `p-${jobId.slice(-6)}`,
      created_at: at,
      updated_at: at,
      job_id: jobId,
      application_id: applicationId,
      sections: {},
      generated_at: opts.ready ? at : null,
      model: "mock-model",
      status: opts.ready ? "done" : "idle",
      generation: opts.ready ? 1 : 0,
      pending_sections: [],
      basis:
        opts.basis ??
        (applicationId
          ? {
              source: "submitted_packet",
              packet_id: "pk-0002",
              packet_hash: "a1b2c3d4e5f60718",
              spec_version: 3,
              posting_changed: false,
              answers: [],
            }
          : { source: "none" }),
      notes: {},
      estimate_micros: null,
      cost_micros: 0,
      error: null,
      offered_at: null,
      flagged: [],
    },
  }
  if (opts.ready) for (const k of MOCK_SECTIONS) buildSection(rec, k)
  return rec
}

/** Build the next version of one section and mirror it on the pack. */
export function buildSection(rec: PackRecord, key: SectionKey) {
  const list = (rec.versions[key] ??= [])
  const content = contentFor(key, rec.title, rec.employer, rec)
  const flagged = key === "why_you" && rec.untraced
  const v = makeVersion(key, list.length + 1, content, { flagged })
  list.push(v)
  mirror(rec)
}

export function mirror(rec: PackRecord) {
  const sections: Record<string, unknown> = {}
  for (const k of MOCK_SECTIONS) {
    const list = rec.versions[k]
    if (list?.length) sections[k] = mirrorOf(list[list.length - 1])
  }
  rec.pack.sections = sections
  rec.pack.flagged = MOCK_SECTIONS.filter(
    (k) => (sections[k] as { flagged?: boolean } | undefined)?.flagged
  )
}

// ---- posting changes ------------------------------------------------------------------------

const change = (
  id: string,
  jobId: string,
  daysAgo: number,
  material: boolean,
  changes: JobChange["changes"],
  extra: Partial<JobChange> = {}
): JobChange => ({
  id,
  job_id: jobId,
  job_title: "",
  employer: "",
  detected_at: iso(daysAgo),
  source: "scan",
  material,
  kinds: changes.map((c) => c.kind),
  changes,
  acknowledged_at: null,
  acknowledged_by: null,
  application_ids: [],
  invalidated_packet_ids: [],
  pending_action_ids: [],
  ...extra,
})

/** Posting changes for a few seeded roles; every other role has none and no watch. */
export function seedChanges(): Record<string, JobChanges> {
  const j1 = appliedJobId(1)
  const j2 = appliedJobId(2)
  const j3 = appliedJobId(3)
  return {
    [j1]: {
      job_id: j1,
      watch: { last_scanned_at: iso(1), last_result: "changed", note: null },
      changes: [
        change(
          "c-pay",
          j1,
          1,
          true,
          [
            {
              kind: "pay_changed",
              field: "pay",
              before: "ZMW 480,000 to 560,000 a year",
              after: "ZMW 520,000 to 620,000 a year",
              material: true,
              summary: "Pay: range raised",
            },
            {
              kind: "wording",
              field: "description",
              before: null,
              after: null,
              material: false,
              summary: "Description reworded",
            },
          ],
          {
            application_ids: [applicationIdFor(1)],
            invalidated_packet_ids: ["pk-0001"],
            pending_action_ids: ["pa-0001"],
          }
        ),
        change("c-word", j1, 4, false, [
          {
            kind: "wording",
            field: "title",
            before: "Data Lead",
            after: "Data Team Lead",
            material: false,
            summary: "Title reworded",
          },
        ]),
      ],
    },
    [j2]: {
      job_id: j2,
      watch: {
        last_scanned_at: iso(0),
        last_result: "unknown",
        note: "The site did not respond.",
      },
      changes: [],
    },
    [j3]: {
      job_id: j3,
      watch: { last_scanned_at: iso(1), last_result: "closed", note: null },
      changes: [
        change("c-closed", j3, 1, true, [
          {
            kind: "closed",
            field: "availability",
            before: "open",
            after: "closed",
            material: true,
            summary: "The posting page says applications have closed.",
          },
        ]),
      ],
    },
  }
}
