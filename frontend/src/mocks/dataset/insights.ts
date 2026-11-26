import type { InsightsReport } from "@/features/insights/api"

const step = (
  key: string,
  label: string,
  count: number,
  prev: number,
  found: number
) => ({
  key,
  label,
  count,
  of_previous: prev ? Math.round((count / prev) * 1e4) / 1e4 : null,
  of_found: found ? Math.round((count / found) * 1e4) / 1e4 : null,
})

const counts = [120, 84, 31, 18, 14, 12, 5, 2, 1]
const labels: [string, string][] = [
  ["found", "Found"],
  ["passed_filters", "Passed filters"],
  ["scored_above", "Scored above threshold"],
  ["tailored", "Tailored"],
  ["approved", "Approved"],
  ["sent", "Sent"],
  ["reply", "Reply"],
  ["interview", "Interview"],
  ["offer", "Offer"],
]

/** An invented report: invented names only, with one well-sampled row and several small ones. */
export function insightsDataset(): InsightsReport {
  return {
    since: "2026-08-28",
    until: "2026-11-26",
    filters: {
      since: null,
      until: null,
      campaign_id: null,
      track_id: null,
      source_id: null,
      country: null,
      channel: null,
    },
    notes: [
      "Reply means the employer answered: screening, interview, offer, or a rejection after sending.",
    ],
    funnel: [
      {
        campaign_id: "camp-analytics",
        campaign: "Analytics roles",
        steps: labels.map(([k, l], i) =>
          step(k, l, counts[i], i ? counts[i - 1] : 0, counts[0])
        ),
      },
    ],
    response: {
      min_sample: 10,
      by_track: [
        {
          key: "track-a",
          label: "Analytics",
          sent: 12,
          replies: 5,
          interviews: 2,
          rate: 0.4167,
          too_few: false,
        },
        {
          key: "track-b",
          label: "Operations",
          sent: 2,
          replies: 1,
          interviews: 0,
          rate: 0.5,
          too_few: true,
        },
      ],
      by_source: [
        {
          key: "src-1",
          label: "Example Board",
          sent: 11,
          replies: 4,
          interviews: 2,
          rate: 0.3636,
          too_few: false,
        },
        {
          key: "src-2",
          label: "Sample Jobs",
          sent: 3,
          replies: 1,
          interviews: 0,
          rate: 0.3333,
          too_few: true,
        },
      ],
      by_market: [
        {
          key: "Zambia",
          sent: 10,
          replies: 4,
          interviews: 2,
          label: "Zambia",
          rate: 0.4,
          too_few: false,
        },
        {
          key: "Kenya",
          sent: 2,
          replies: 1,
          interviews: 0,
          label: "Kenya",
          rate: 0.5,
          too_few: true,
        },
        {
          key: "Not stated",
          sent: 2,
          replies: 0,
          interviews: 0,
          label: "Not stated",
          rate: 0,
          too_few: true,
        },
      ],
    },
    time_in_stage: {
      stages: [
        {
          stage: "shortlisted",
          n: 14,
          median_days: 1.5,
          p75_days: 3.2,
          too_few: false,
        },
        {
          stage: "submitted",
          n: 8,
          median_days: 6,
          p75_days: 9.5,
          too_few: true,
        },
      ],
      first_reply: {
        stage: "first_reply",
        n: 5,
        median_days: 7,
        p75_days: 10,
        too_few: true,
      },
    },
    spend: {
      currency: "USD",
      period: "week",
      rows: [
        {
          period: "2026-11-02",
          stage: "assess",
          model: "model-small",
          micros: 1_200_000,
        },
        {
          period: "2026-11-02",
          stage: "tailor",
          model: "model-large",
          micros: 3_400_000,
        },
        {
          period: "2026-11-09",
          stage: "tailor",
          model: "model-large",
          micros: 2_100_000,
        },
      ],
      total_micros: 6_700_000,
      sent: 12,
      interviews: 2,
      per_sent_micros: 558_333,
      per_interview_micros: 3_350_000,
      by_run_kind: [
        { kind: "sweep", runs: 12, micros: 4_100_000 },
        { kind: "tailoring", runs: 3, micros: 2_600_000 },
      ],
    },
    sources: [
      {
        source_id: "src-1",
        name: "Example Board",
        found: 70,
        duplicates: 6,
        passed: 50,
        applied: 11,
        replies: 4,
      },
      {
        source_id: "src-2",
        name: "Sample Jobs",
        found: 50,
        duplicates: 2,
        passed: 34,
        applied: 3,
        replies: 1,
      },
    ],
    automation: {
      auto: 4,
      approved: 6,
      manual: 2,
      uncertain_sends: 1,
      blockers: [
        { key: "captcha", count: 3 },
        { key: "sign_in", count: 2 },
      ],
      permits_denied: [{ key: "outside sending hours", count: 2 }],
    },
    exclusions: [
      { key: "work_rights", count: 20 },
      { key: "pay_floor", count: 9 },
    ],
    messages: {
      sent: 3,
      by_kind: [
        { key: "follow_up", count: 2 },
        { key: "thank_you", count: 1 },
      ],
      uncertain_sends: 0,
    },
  }
}

export const emptyInsights = (): InsightsReport => ({
  ...insightsDataset(),
  funnel: [],
  response: { min_sample: 10, by_track: [], by_source: [], by_market: [] },
  time_in_stage: {
    stages: [],
    first_reply: {
      stage: "first_reply",
      n: 0,
      median_days: null,
      p75_days: null,
      too_few: true,
    },
  },
  spend: {
    currency: "USD",
    period: "week",
    rows: [],
    total_micros: 0,
    sent: 0,
    interviews: 0,
    per_sent_micros: null,
    per_interview_micros: null,
    by_run_kind: [],
  },
  sources: [],
  automation: {
    auto: 0,
    approved: 0,
    manual: 0,
    uncertain_sends: 0,
    blockers: [],
    permits_denied: [],
  },
  exclusions: [],
  messages: { sent: 0, by_kind: [], uncertain_sends: 0 },
})
