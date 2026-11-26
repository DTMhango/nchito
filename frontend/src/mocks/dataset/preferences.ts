/**
 * Fictional fixtures for feedback, preference suggestions and the policy preview.
 * Invented employers ("Example ..."), example.com only. Shapes mirror the generated contract.
 */
import type { Schemas } from "@/lib/api/types"
import { IDS } from "./campaigns"

type Suggestion = Schemas["SuggestionOut"]

/** A recent role the policy preview replays: score, how it would be sent, and what is unknown. */
export type PreviewRole = {
  job_id: string
  title: string
  employer: string
  /** null: not scored yet. */
  score: number | null
  channel: "email" | "browser" | "other"
  /** Roles with pay not stated never go automatically (unknown is not yes). */
  payKnown: boolean
  /** Held as a runner-up at its employer. */
  held: boolean
  /** Days ago it was found (0 = today). */
  day: number
}

const role = (
  n: number,
  title: string,
  employer: string,
  score: number | null,
  channel: PreviewRole["channel"],
  day: number,
  over: Partial<PreviewRole> = {}
): PreviewRole => ({
  job_id: `00000000-0000-4000-8000-0000000f${String(n).padStart(4, "0")}`,
  title,
  employer,
  score,
  channel,
  payKnown: true,
  held: false,
  day,
  ...over,
})

export const PREVIEW_ROLES: PreviewRole[] = [
  role(1, "Pricing Actuary", "Example Re", 92, "email", 0),
  role(2, "Catastrophe Modeller", "Example Risk Partners", 90, "browser", 0),
  role(3, "Senior Actuarial Analyst", "Example Mutual", 88, "email", 1, {
    payKnown: false,
  }),
  role(4, "Capital Modelling Lead", "Example Re", 87, "browser", 1, {
    held: true,
  }),
  role(5, "Reserving Actuary", "Example Life", 86, "email", 1),
  role(6, "Risk Analyst", "Example Insurance Group", 84, "browser", 2),
  role(7, "Actuarial Analyst", "Example Assurance", 82, "email", 2),
  role(8, "Exposure Analyst", "Example Brokers", 80, "other", 3),
  role(9, "Data Scientist, Pricing", "Example Cover", 76, "email", 3),
  role(10, "Analytics Lead", "Example Analytics", 72, "browser", 4),
  role(11, "Junior Pricing Analyst", "Example General", 65, "email", 5),
  role(12, "Underwriting Assistant", "Example Underwriters", 58, "browser", 5),
  role(13, "Claims Analyst", "Example Claims", 45, "email", 6),
  role(14, "Model Validation Analyst", "Example Validation", null, "email", 6),
]

export const PREVIEW_WINDOW_DAYS = 30
export const PREVIEW_BIN_WIDTH = 10
/** Fallback lines when the campaign's rubric sets none (mirrors the settings defaults). */
export const PREVIEW_DEFAULT_THRESHOLDS = {
  shortlist: 60,
  tailor: 70,
  auto_apply: 85,
}
export const PREVIEW_CAPS = {
  daily_cap: 3,
  weekly_cap: 10,
  sent_today: 1,
  sent_week: 4,
  quiet_hours_start: "21:00",
  quiet_hours_end: "07:00",
  /** Fixed so tests do not depend on the clock. */
  quiet_now: true,
}

/** Thumbs given before this session (the summary adds the ones saved in the mock). */
export const BASE_COUNTS = { up: 5, down: 6 }

export const OWNER_ONLY: Schemas["OwnerOnlyNoteOut"][] = [
  {
    area: "seniority",
    down: 3,
    feedback_ids: [],
    message:
      "3 roles marked down as too senior. Seniority is set in the campaign's rules; change it there if you want to.",
  },
]

const T0 = "2026-11-24T08:00:00Z"
type ConditionSetOut = Schemas["ConditionSet-Output"]
const conditions = (facet: string, include: string[]): ConditionSetOut => ({
  version: 1,
  root: {
    type: "group",
    op: "and",
    negate: false,
    conditions: [{ type: "values", facet, include }],
  },
})
const row = (
  r: PreviewRole,
  old_score: number,
  new_score: number,
  old_verdict: string,
  new_verdict: string
) => ({
  job_id: r.job_id,
  title: r.title,
  employer: r.employer,
  old_score,
  new_score,
  old_verdict,
  new_verdict,
})

export const SUGGESTION_IDS = {
  penalty: "00000000-0000-4000-8000-00000000a501",
  reweight: "00000000-0000-4000-8000-00000000a502",
  tag: "00000000-0000-4000-8000-00000000a503",
}

export function seedSuggestions(): Suggestion[] {
  const base = {
    created_at: T0,
    updated_at: T0,
    campaign_id: IDS.camp1,
    rubric_id: IDS.rubricActive,
    status: "open" as const,
    decided_by: null,
    decided_at: null,
    decision_note: null,
    result: {},
  }
  return [
    {
      ...base,
      id: SUGGESTION_IDS.penalty,
      kind: "add_penalty",
      target: "penalties",
      title: "Rank roles that ask for a master's degree lower",
      change: {
        kind: "add_penalty",
        name: "Asks for a master's degree",
        points: 15,
        conditions: conditions("facets.min_education", ["masters"]),
      },
      evidence: {
        up: 0,
        down: 4,
        feedback_ids: ["fb-1", "fb-2", "fb-3", "fb-4"],
        application_ids: [],
        reasons: { too_senior: 3, wrong_stack: 1 },
        notes: ["Wants a master's I do not have."],
        summary:
          "4 roles you marked down asked for a master's degree; none you liked did.",
      },
      backtest: {
        window_days: PREVIEW_WINDOW_DAYS,
        jobs: PREVIEW_ROLES.length,
        matched: 3,
        newly_pass: [],
        newly_drop: [row(PREVIEW_ROLES[8], 76, 61, "tailor", "shortlist")],
        excluded_past_applications: [],
        score_changed: 3,
      },
    },
    {
      ...base,
      id: SUGGESTION_IDS.reweight,
      kind: "reweight_criterion",
      target: "criteria",
      title: "Give Skills match more weight than Role fit",
      change: {
        kind: "reweight_criterion",
        weights: {
          "Role fit": 25,
          "Skills match": 30,
          Seniority: 15,
          Pay: 15,
          "Location and work model": 15,
        },
      },
      evidence: {
        up: 5,
        down: 2,
        feedback_ids: ["fb-5", "fb-6"],
        application_ids: ["app-1"],
        reasons: { more_like_this: 3, wrong_stack: 2 },
        notes: [],
        summary: "Roles you liked rated higher on skills than on title fit.",
      },
      backtest: {
        window_days: PREVIEW_WINDOW_DAYS,
        jobs: PREVIEW_ROLES.length,
        matched: PREVIEW_ROLES.length - 1,
        newly_pass: [row(PREVIEW_ROLES[5], 84, 86, "ask_owner", "auto_apply")],
        newly_drop: [],
        excluded_past_applications: [
          row(PREVIEW_ROLES[10], 65, 58, "shortlist", "below_threshold"),
        ],
        score_changed: 9,
      },
    },
  ]
}

/** What "Analyse now" finds the first time: a tag rule for reinsurers. */
export function analysedSuggestion(): Suggestion {
  const [first] = seedSuggestions()
  return {
    ...first,
    id: SUGGESTION_IDS.tag,
    kind: "add_tag_rule",
    target: "tag_rules",
    title: "Tag roles at reinsurers as reinsurer",
    change: {
      kind: "add_tag_rule",
      tag: "reinsurer",
      conditions: conditions("facets.employer_type", ["reinsurer"]),
    },
    evidence: {
      up: 3,
      down: 0,
      feedback_ids: ["fb-7", "fb-8", "fb-9"],
      application_ids: [],
      reasons: { employer_type: 2, more_like_this: 1 },
      notes: [],
      summary: "3 roles you liked were at reinsurers.",
    },
    backtest: {
      window_days: PREVIEW_WINDOW_DAYS,
      jobs: PREVIEW_ROLES.length,
      matched: 2,
      newly_pass: [],
      newly_drop: [],
      excluded_past_applications: [],
      score_changed: 0,
    },
  }
}
