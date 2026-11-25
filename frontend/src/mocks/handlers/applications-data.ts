/**
 * Fictional applications, decisions and Today data for the mock backend. Every employer,
 * role and person here is invented. Dates are relative to "now" so the screens always look
 * current.
 */
import type {
  ApplicationSummary,
  DecisionGroup,
  PendingAction,
  TimelineEvent,
  TodayOut,
} from "@/features/applications/api"

const DAY = 86_400_000
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString()
const ahead = (days: number) => new Date(Date.now() + days * DAY).toISOString()
const dateAhead = (days: number) => ahead(days).slice(0, 10)

export const CAMPAIGNS = [
  {
    id: "c1000000-0000-4000-8000-000000000001",
    name: "Data leadership, remote",
  },
  {
    id: "c1000000-0000-4000-8000-000000000002",
    name: "Actuarial, Southern Africa",
  },
]

export type MockApplications = {
  apps: ApplicationSummary[]
  actions: PendingAction[]
  events: Record<string, TimelineEvent[]>
  snoozed: Record<string, string>
}

const id = (n: number, p = "a") =>
  `${p}0000000-0000-4000-8000-${String(n).padStart(12, "0")}`

type Seed = [
  employer: string,
  title: string,
  stage: ApplicationSummary["stage"],
  score: number | null,
  channel: ApplicationSummary["channel"],
  daysInStage: number,
  next: [string, number] | null,
  campaign: 0 | 1,
  appliedDaysAgo?: number,
]

const SEEDS: Seed[] = [
  ["Kafue Analytics", "Head of Data", "shortlisted", 91, "email", 1, null, 0],
  [
    "Mulungushi Digital",
    "Analytics Lead",
    "shortlisted",
    78,
    "browser",
    3,
    null,
    0,
  ],
  [
    "Luangwa Re",
    "Pricing Actuary",
    "tailoring",
    88,
    "email",
    2,
    ["Review tailored CV", 1],
    1,
  ],
  [
    "Copperline Energy",
    "Risk Data Manager",
    "tailoring",
    74,
    "browser",
    1,
    null,
    1,
  ],
  [
    "Zambezi Mining Systems",
    "Data Platform Lead",
    "ready",
    86,
    "browser",
    1,
    ["Approve packet", 0],
    0,
  ],
  [
    "Nyika Labs",
    "Principal Data Engineer",
    "applying",
    82,
    "browser",
    0,
    null,
    0,
  ],
  [
    "Kariba Freight",
    "Head of Analytics",
    "submitted_unconfirmed",
    80,
    "email",
    1,
    ["Confirm it arrived", 1],
    0,
    1,
  ],
  [
    "Lusaka Fintech Co",
    "Director of Data Science",
    "submitted",
    90,
    "email",
    4,
    ["Follow up", 3],
    0,
    4,
  ],
  [
    "Chambeshi Insurance",
    "Reserving Actuary",
    "submitted",
    76,
    "manual",
    6,
    ["Follow up", 8],
    1,
    6,
  ],
  [
    "Mpongwe Agritech",
    "BI Manager",
    "screening",
    72,
    "browser",
    5,
    ["Phone screen", 2],
    0,
    9,
  ],
  [
    "Kasama Capital",
    "Head of Risk Analytics",
    "interview",
    93,
    "email",
    2,
    ["Second interview", 4],
    1,
    12,
  ],
  [
    "Livingstone Logistics",
    "Analytics Director",
    "offer",
    89,
    "email",
    1,
    ["Reply to offer", 3],
    0,
    20,
  ],
  ["Ndola Brewing", "Data Manager", "closed", 61, "browser", 10, null, 0, 14],
]

export function seedApplications(): MockApplications {
  const apps: ApplicationSummary[] = SEEDS.map((s, i) => ({
    id: id(i + 1),
    created_at: ago(s[5] + 7),
    updated_at: ago(s[5]),
    job_id: id(i + 1, "b"),
    campaign_id: CAMPAIGNS[s[7]].id,
    stage: s[2],
    channel: s[4],
    title: s[1],
    employer: s[0],
    score: s[3],
    next_step: s[6] ? s[6][0] : null,
    next_due: s[6] ? dateAhead(s[6][1]) : null,
    pinned: i === 0 || i === 10,
    open_pending_actions: 0,
    applied_at: s[8] !== undefined ? ago(s[8]) : null,
  }))

  const byEmployer = (e: string) => apps.find((a) => a.employer === e)!
  const act = (
    n: number,
    type: PendingAction["type"],
    app: ApplicationSummary | null,
    group_key: string | null,
    title: string,
    detail: Record<string, unknown>,
    deadlineDays: number | null
  ): PendingAction => ({
    id: id(n, "d"),
    created_at: ago(0.2),
    updated_at: ago(0.2),
    type,
    application_id: app?.id ?? null,
    agent_task_id: null,
    group_key,
    title,
    detail,
    checkpoint: null,
    deadline: deadlineDays === null ? null : ahead(deadlineDays),
    status: "open",
  })

  const workRights = [
    ["Kafue Analytics", 2],
    ["Mulungushi Digital", 5],
    ["Luangwa Re", 6],
    ["Copperline Energy", 9],
  ] as const
  const actions: PendingAction[] = [
    ...workRights.map(([e, d], i) =>
      act(
        i + 1,
        "unknown_question",
        byEmployer(e),
        "q:work-rights-kenya",
        "Do you have the right to work in Kenya?",
        {
          question: "Do you have the right to work in Kenya?",
          material: true,
          options: ["Yes", "No", "Yes, with a work permit"],
          employer: e,
          role: byEmployer(e).title,
        },
        d
      )
    ),
    act(
      10,
      "sign_in",
      byEmployer("Zambezi Mining Systems"),
      "portal:careers.zambezi-mining.example",
      "Sign in to the Zambezi Mining careers portal",
      {
        url: "https://careers.zambezi-mining.example/login",
        employer: "Zambezi Mining Systems",
      },
      1.5
    ),
    act(
      11,
      "sign_in",
      byEmployer("Nyika Labs"),
      "portal:careers.zambezi-mining.example",
      "Sign in to the Zambezi Mining careers portal",
      {
        url: "https://careers.zambezi-mining.example/login",
        employer: "Nyika Labs",
      },
      4
    ),
    act(
      12,
      "approve",
      byEmployer("Zambezi Mining Systems"),
      null,
      "Approve the packet for Data Platform Lead",
      { employer: "Zambezi Mining Systems", role: "Data Platform Lead" },
      0.6
    ),
    act(
      13,
      "confirm_submission",
      byEmployer("Kariba Freight"),
      null,
      "Did Kariba Freight receive your application?",
      { employer: "Kariba Freight", role: "Head of Analytics" },
      null
    ),
  ]
  for (const a of actions) {
    const app = apps.find((x) => x.id === a.application_id)
    if (app) app.open_pending_actions += 1
  }

  const events: Record<string, TimelineEvent[]> = {}
  for (const a of apps) {
    events[a.id] = [
      {
        id: id(Number(a.id.slice(-3)), "e"),
        created_at: a.created_at,
        kind: "application.created",
        actor: "system",
        detail: {},
      },
      {
        id: id(Number(a.id.slice(-3)) + 100, "e"),
        created_at: a.updated_at,
        kind: "stage.changed",
        actor: "owner",
        detail: { note: `Moved to ${a.stage.replace(/_/g, " ")}` },
      },
    ]
  }
  return { apps, actions, events, snoozed: {} }
}

/** Group open actions by shared blocker (DESIGN 18.4), nearest deadline first. */
export function groupActions(actions: PendingAction[]): DecisionGroup[] {
  const open = actions.filter((a) => a.status === "open")
  const groups = new Map<string, PendingAction[]>()
  for (const a of open) {
    const key = a.group_key ?? `single:${a.id}`
    groups.set(key, [...(groups.get(key) ?? []), a])
  }
  const out = [...groups.entries()].map(([key, list]) => {
    const deadlines = list
      .map((a) => a.deadline)
      .filter((d): d is string => !!d)
    const nearest = deadlines.sort()[0] ?? null
    const n = list.length
    const words = ["", "one", "two", "three", "four", "five"]
    const count = words[n] ?? String(n)
    const first = list[0]
    let title = first.title
    let consequence = "It waits until you decide."
    if (first.type === "unknown_question") {
      title =
        n > 1 ? `One work-rights answer affects ${count} roles` : first.title
      consequence = `${n > 1 ? "These applications stay" : "This application stays"} paused until you answer.`
    } else if (first.type === "sign_in") {
      title =
        n > 1
          ? `Signing in to this portal unlocks ${count} applications`
          : first.title
      consequence = "The agent can't continue on this portal without you."
    } else if (first.type === "approve") {
      consequence = "Nothing is sent until you approve it."
    } else if (first.type === "confirm_submission") {
      consequence =
        "It stays unconfirmed and blocks other roles at this employer."
    }
    return {
      group_key: key,
      title,
      consequence,
      nearest_deadline: nearest,
      actions: list,
    }
  })
  return out.sort((a, b) =>
    (a.nearest_deadline ?? "9999").localeCompare(b.nearest_deadline ?? "9999")
  )
}

export function buildToday(m: MockApplications): TodayOut {
  return {
    needs_you: groupActions(m.actions).length,
    last_sweep_run_id: "r1000000-0000-4000-8000-000000000001",
    funnel: [
      { stage: "found", count: 214 },
      { stage: "new", count: 41 },
      { stage: "passed_filters", count: 23 },
      { stage: "above_threshold", count: 11 },
      { stage: "tailored", count: 6 },
      { stage: "applied", count: 3 },
    ],
    sources: [
      {
        source_id: "s1",
        name: "Himalayas",
        status: "ok",
        last_success_at: ago(0.1),
      },
      {
        source_id: "s2",
        name: "Remotive",
        status: "ok",
        last_success_at: ago(0.1),
      },
      {
        source_id: "s3",
        name: "Zambia job boards",
        status: "degraded",
        last_success_at: ago(1),
      },
      {
        source_id: "s4",
        name: "Careers RSS",
        status: "ok",
        last_success_at: ago(0.1),
      },
    ],
    top_match_ids: [id(21, "f"), id(22, "f"), id(23, "f")],
    upcoming: [
      {
        kind: "interview",
        at: ahead(4),
        title: "Second interview, Kasama Capital",
        job_id: id(11, "b"),
        application_id: id(11),
      },
      {
        kind: "deadline",
        at: dateAhead(2),
        title: "Closes: Head of Data, Kafue Analytics",
        job_id: id(1, "b"),
        application_id: id(1),
      },
      {
        kind: "follow_up",
        at: dateAhead(3),
        title: "Follow up with Lusaka Fintech Co",
        job_id: id(8, "b"),
        application_id: id(8),
      },
      {
        kind: "deadline",
        at: dateAhead(9),
        title: "Closes: Analytics Lead, Mulungushi Digital",
        job_id: id(2, "b"),
        application_id: id(2),
      },
    ],
    spend: {
      month_to_date_minor: 1840,
      reserved_minor: 120,
      cap_minor: 5000,
      currency: "USD",
      estimated_unbilled_minor: 60,
    },
  }
}

export const NEW_JOBS = [
  ["Okavango Mobile", "Head of Data Science", 92, "Remote, Africa", 12],
  ["Kalahari Risk", "Chief Analytics Officer", 87, "Lusaka, Zambia", 20],
  [
    "Victoria Falls Hospitality",
    "Revenue Analytics Lead",
    81,
    "Livingstone, Zambia",
    6,
  ],
].map(([employer, title, score, city, deadlineDays], i) => ({
  id: id(21 + i, "f"),
  created_at: ago(0.3),
  updated_at: ago(0.3),
  title: title as string,
  employer: employer as string,
  canonical_employer: employer as string,
  location: {
    city: city as string,
    country: null,
    region: null,
    raw: city as string,
  },
  triage: "new",
  best_score: score as number,
  conflict_state: "none",
  conflict_note: null,
  pay: { state: "not_stated" as const },
  deadline: { state: "dated" as const, on: dateAhead(deadlineDays as number) },
  availability: "open",
  tags: [],
  pinned: false,
  posted_at: ago(1),
}))
