/** Fictional fixtures and the in-memory store for the Sources and Runs mock backend. */
import type {
  Employer,
  ProposedAction,
  Run,
  Schedule,
  Source,
} from "@/features/sources/api"
import { nextRuns } from "@/features/sources/cron"

const ago = (minutes: number) =>
  new Date(Date.now() - minutes * 60_000).toISOString()

const rl = { requests_per_minute: 30, burst: 5 }
const base = { created_at: ago(60 * 24 * 30), updated_at: ago(60 * 24) }

export const COUNT_KEYS = [
  "found",
  "new",
  "passed_filters",
  "above_threshold",
  "tailored",
  "applied",
] as const

function sources(): Source[] {
  const mk = (
    id: string,
    connector: string,
    name: string,
    access: Source["access"],
    over: Partial<Source> = {}
  ): Source => ({
    ...base,
    id,
    connector,
    name,
    access,
    config: {},
    access_notes: null,
    rate_limit: rl,
    permitted_actions: ["search", "fetch", "check_open"],
    enabled: true,
    health: { status: "ok", consecutive_failures: 0, last_error: null },
    last_success_at: ago(95),
    ...over,
  })
  return [
    mk("src-gh", "greenhouse", "Greenhouse boards", "api", {
      config: { keywords: ["actuarial", "reinsurance"], max_age_days: 14 },
    }),
    mk("src-lever", "lever", "Lever boards", "api", {
      last_success_at: ago(95),
    }),
    mk("src-ashby", "ashby", "Ashby boards", "api", {
      health: {
        status: "degraded",
        consecutive_failures: 1,
        last_error: "Timed out after 20s reading a board",
      },
      last_success_at: ago(60 * 26),
    }),
    mk("src-workable", "workable", "Workable boards", "api"),
    mk("src-workday", "workday", "Workday career sites", "api", {
      rate_limit: { requests_per_minute: 12, burst: 2 },
      health: {
        status: "failing",
        consecutive_failures: 4,
        last_error: "HTTP 403 Forbidden from kafue-re.example.com",
      },
      last_success_at: ago(60 * 24 * 3),
    }),
    mk("src-himalayas", "himalayas", "Himalayas", "api", {
      access_notes:
        "Remote labels are unreliable, so every posting is re-read.",
    }),
    mk("src-remotive", "remotive", "Remotive", "api", {
      last_success_at: ago(95),
    }),
    mk("src-wwr", "wwr", "We Work Remotely", "feed"),
    mk("src-rss", "rss", "Generic RSS feeds", "feed", {
      enabled: false,
      last_success_at: null,
      health: { status: "unknown", consecutive_failures: 0, last_error: null },
    }),
    mk("src-manual", "manual", "Manual capture", "html", {
      permitted_actions: ["fetch", "check_open"],
    }),
    mk("src-email", "alert_email", "Job-alert emails", "email", {
      enabled: false,
      last_success_at: null,
      health: { status: "unknown", consecutive_failures: 0, last_error: null },
      access_notes: "Needs a connected mailbox (Settings, Connections).",
      permitted_actions: ["search"],
    }),
  ]
}

function employers(): Employer[] {
  const mk = (
    id: string,
    name: string,
    board_type: string,
    board_slug: string,
    priority: number,
    cooldown_days: number | null,
    always_ask_first = false
  ): Employer => ({
    ...base,
    id,
    name,
    board_type,
    board_slug,
    priority,
    cooldown_days,
    always_ask_first,
  })
  return [
    mk(
      "emp-1",
      "Kafue Reinsurance",
      "workday",
      "kafue-re/careers",
      1,
      null,
      true
    ),
    mk(
      "emp-2",
      "Copperline Analytics",
      "greenhouse",
      "copperlineanalytics",
      2,
      60
    ),
    mk("emp-3", "Zambezi Digital", "lever", "zambezidigital", 3, null),
    mk("emp-4", "Mukuba Capital", "ashby", "mukubacapital", 2, 90),
    mk("emp-5", "Lusaka Risk Partners", "workable", "lusaka-risk", 4, null),
  ]
}

function schedules(): Schedule[] {
  const mk = (
    id: string,
    name: string,
    cron: string,
    over: Partial<Schedule> = {}
  ): Schedule => ({
    ...base,
    id,
    name,
    kind: "sweep",
    campaign_id: null,
    cron,
    timezone: null,
    enabled: true,
    dry_run: false,
    next_run_at: null,
    last_enqueued_at: ago(60 * 5),
    last_run_id: "run-1",
    ...over,
  })
  return [
    mk("sch-1", "Morning sweep", "30 7 * * *"),
    mk("sch-2", "Expiry check", "0 */6 * * *", { kind: "expiry_check" }),
    mk("sch-3", "Weekday dry run", "0 18 * * 1-5", {
      dry_run: true,
      enabled: false,
    }),
  ]
}

const funnel = (
  found: number,
  nw: number,
  passed: number,
  above: number,
  tailored: number,
  applied: number
) => ({
  found,
  new: nw,
  passed_filters: passed,
  above_threshold: above,
  tailored,
  applied,
})

function runs(): Run[] {
  const done = (
    id: string,
    minutesAgo: number,
    over: Partial<Run> = {}
  ): Run => ({
    ...base,
    id,
    created_at: ago(minutesAgo),
    updated_at: ago(minutesAgo - 2),
    kind: "sweep",
    trigger: "schedule",
    campaign_id: null,
    schedule_id: "sch-1",
    scheduled_for: ago(minutesAgo),
    dry_run: false,
    proposed_actions: [],
    counts: funnel(212, 38, 21, 9, 5, 2),
    source_results: [
      { source_id: "src-gh", status: "ok", found: 84, new: 15, error: null },
      { source_id: "src-lever", status: "ok", found: 61, new: 11, error: null },
      {
        source_id: "src-himalayas",
        status: "ok",
        found: 52,
        new: 9,
        error: null,
      },
      {
        source_id: "src-workday",
        status: "failed",
        found: 0,
        new: 0,
        error: "HTTP 403 Forbidden from kafue-re.example.com",
      },
      { source_id: "src-ashby", status: "ok", found: 15, new: 3, error: null },
    ],
    cost_minor: 184,
    config_versions: {},
    status: "partial",
    started_at: ago(minutesAgo),
    finished_at: ago(minutesAgo - 2.4),
    error: null,
    ...over,
  })
  return [
    done("run-1", 60 * 5, { counts: funnel(212, 38, 21, 9, 5, 2) }),
    done("run-2", 60 * 29, {
      status: "succeeded",
      counts: funnel(198, 24, 15, 6, 4, 1),
      source_results: [
        { source_id: "src-gh", status: "ok", found: 90, new: 11, error: null },
        {
          source_id: "src-lever",
          status: "ok",
          found: 64,
          new: 8,
          error: null,
        },
        {
          source_id: "src-himalayas",
          status: "ok",
          found: 44,
          new: 5,
          error: null,
        },
      ],
      cost_minor: 121,
    }),
    done("run-3", 60 * 30, {
      kind: "expiry_check",
      schedule_id: "sch-2",
      status: "succeeded",
      counts: { checked: 63, still_open: 58, closed: 4, unknown: 1 },
      source_results: [],
      cost_minor: 0,
    }),
    done("run-4", 60 * 52, {
      dry_run: true,
      trigger: "manual",
      schedule_id: null,
      status: "succeeded",
      counts: funnel(205, 31, 18, 7, 0, 0),
      cost_minor: 0,
      proposed_actions: PROPOSED,
    }),
    done("run-5", 60 * 77, {
      status: "failed",
      counts: funnel(0, 0, 0, 0, 0, 0),
      source_results: [
        {
          source_id: "src-gh",
          status: "failed",
          found: 0,
          new: 0,
          error: "getaddrinfo ENOTFOUND boards-api.greenhouse.io",
        },
        {
          source_id: "src-lever",
          status: "failed",
          found: 0,
          new: 0,
          error: "getaddrinfo ENOTFOUND api.lever.co",
        },
      ],
      error: "Every source failed, so nothing was checked.",
      cost_minor: 0,
    }),
  ]
}

export const PROPOSED: ProposedAction[] = [
  {
    job_id: null,
    title: "Senior Actuarial Analyst",
    employer: "Kafue Reinsurance",
    action: "add_to_matches",
    reason: "new posting, score 84",
    score: 84,
  },
  {
    job_id: null,
    title: "Reinsurance Pricing Lead",
    employer: "Copperline Analytics",
    action: "prepare",
    reason: "above the prepare threshold",
    score: 79,
  },
  {
    job_id: null,
    title: "Head of Catastrophe Modelling",
    employer: "Mukuba Capital",
    action: "ask_owner",
    reason: "campaign rule: always ask first",
    score: 88,
  },
  {
    job_id: null,
    title: "Risk Modelling Lead",
    employer: "Mukuba Capital",
    action: "ask_owner",
    reason:
      "tie with Head of Catastrophe Modelling at the same employer: you choose which one goes ahead",
    score: 88,
  },
  {
    job_id: null,
    title: "Junior Data Clerk",
    employer: "Zambezi Digital",
    action: "skip",
    reason: "below your threshold",
    score: 31,
  },
]

type Store = {
  sources: Source[]
  employers: Employer[]
  schedules: Schedule[]
  runs: Run[]
  /** run id -> epoch ms the mock run started, for simulated progress. */
  live: Map<string, number>
}

export const LIVE_RUN_MS = 9000

function fresh(): Store {
  return {
    sources: sources(),
    employers: employers(),
    schedules: schedules().map(withNext),
    runs: runs(),
    live: new Map(),
  }
}

export function withNext(s: Schedule): Schedule {
  const tz = s.timezone ?? "Africa/Lusaka"
  return {
    ...s,
    next_run_at: s.enabled
      ? (nextRuns(s.cron, tz, 1)[0]?.toISOString() ?? null)
      : null,
  }
}

export const store: Store = fresh()

/** Reset to the fixtures (tests call this; the dev mock resets on reload anyway). */
export function resetSourcesMock() {
  Object.assign(store, fresh())
}

/** Advance a simulated running run according to elapsed time. */
export function tickRun(run: Run): Run {
  const started = store.live.get(run.id)
  if (started === undefined) return run
  const p = Math.min(1, (Date.now() - started) / LIVE_RUN_MS)
  const results = [
    { source_id: "src-gh", found: 84, new: 15 },
    { source_id: "src-lever", found: 61, new: 11 },
    { source_id: "src-himalayas", found: 52, new: 9 },
  ]
  const shown = Math.ceil(p * results.length)
  const target = funnel(
    212,
    38,
    21,
    9,
    run.dry_run ? 0 : 5,
    run.dry_run ? 0 : 2
  )
  const counts = Object.fromEntries(
    Object.entries(target).map(([k, v]) => [k, Math.floor(v * p)])
  )
  const next: Run = {
    ...run,
    counts,
    source_results: results
      .slice(0, p < 1 ? Math.max(0, shown - 1) : shown)
      .map((r) => ({
        ...r,
        status: "ok" as const,
        error: null,
      })),
  }
  if (p >= 1) {
    store.live.delete(run.id)
    next.status = "succeeded"
    next.finished_at = new Date().toISOString()
    next.cost_minor = run.dry_run ? 0 : 96
    if (run.dry_run) next.proposed_actions = PROPOSED
  } else if (run.status === "queued" && p > 0.05) {
    next.status = "running"
  }
  store.runs = store.runs.map((r) => (r.id === run.id ? next : r))
  return next
}
