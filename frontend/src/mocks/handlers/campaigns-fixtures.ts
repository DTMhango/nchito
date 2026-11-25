/** Fictional fixtures for the Campaigns screens. Invented names only; example.com domains. */
import type {
  Campaign,
  FacetCatalogEntry,
  JobSummary,
  Rubric,
  Setting,
  Source,
  Track,
  WatchedEmployer,
} from "@/features/campaigns/types"

const T0 = "2026-11-20T08:00:00Z"
const meta = { created_at: T0, updated_at: T0 }

export const IDS = {
  trackActuarial: "00000000-0000-4000-8000-000000000a01",
  trackAnalytics: "00000000-0000-4000-8000-000000000a02",
  camp1: "00000000-0000-4000-8000-000000000c01",
  camp2: "00000000-0000-4000-8000-000000000c02",
  camp3: "00000000-0000-4000-8000-000000000c03",
  rubricActive: "00000000-0000-4000-8000-000000000b01",
  rubricDraft: "00000000-0000-4000-8000-000000000b02",
  rubricFamily: "00000000-0000-4000-8000-000000000bf1",
  src1: "00000000-0000-4000-8000-000000000d01",
  src2: "00000000-0000-4000-8000-000000000d02",
  src3: "00000000-0000-4000-8000-000000000d03",
  src4: "00000000-0000-4000-8000-000000000d04",
}

export const tracks: Track[] = [
  {
    ...meta,
    id: IDS.trackActuarial,
    review_state: "confirmed",
    origin: "owner",
    confirmed_at: T0,
    key: "actuarial",
    name: "Actuarial and risk",
    priority: 1,
    example_titles: ["Senior Actuarial Analyst"],
    lead_fact_codes: [],
    summary_fact_code: null,
    tone_notes: null,
  } as Track,
  {
    ...meta,
    id: IDS.trackAnalytics,
    review_state: "confirmed",
    origin: "owner",
    confirmed_at: T0,
    key: "analytics",
    name: "Analytics and data",
    priority: 2,
    example_titles: ["Data Analyst"],
    lead_fact_codes: [],
    summary_fact_code: null,
    tone_notes: null,
  } as Track,
]

export const facets: FacetCatalogEntry[] = [
  {
    facet: "visa_sponsorship",
    label: "Visa sponsorship offered",
    kind: "values",
    values: [
      { value: "yes", count: 5 },
      { value: "no", count: 3 },
      { value: "not_stated", count: 4 },
    ],
  },
  {
    facet: "relocation_required",
    label: "Relocation required",
    kind: "values",
    values: [
      { value: "yes", count: 3 },
      { value: "no", count: 6 },
      { value: "not_stated", count: 3 },
    ],
  },
  {
    facet: "work_model",
    label: "Work model",
    kind: "values",
    values: [
      { value: "on_site", count: 3 },
      { value: "hybrid", count: 4 },
      { value: "remote", count: 5 },
    ],
  },
  {
    facet: "employment_type",
    label: "Employment type",
    kind: "values",
    values: [
      { value: "permanent", count: 8 },
      { value: "contract", count: 3 },
      { value: "fixed_term", count: 1 },
    ],
  },
  {
    facet: "required_skills",
    label: "Required skills",
    kind: "values",
    values: [
      { value: "Python", count: 6 },
      { value: "Power BI", count: 4 },
      { value: "RMS", count: 2 },
    ],
  },
  {
    facet: "min_education",
    label: "Minimum education",
    kind: "values",
    values: [
      { value: "bachelors", count: 7 },
      { value: "masters", count: 3 },
      { value: "not_stated", count: 2 },
    ],
  },
  {
    facet: "years_experience",
    label: "Years of experience asked",
    kind: "range",
  },
  { facet: "title", label: "Job title", kind: "text" },
]

type MockJob = JobSummary & {
  /** Mock only: facet values the preview evaluator reads. */
  mock: Record<string, string | number | string[]>
}

const loc = (country: string, city: string) => ({
  country,
  city,
  region: null,
  raw: `${city}, ${country}`,
})
const basePay = { stated: false } as unknown as JobSummary["pay"]
const baseDeadline = {} as unknown as JobSummary["deadline"]

function job(
  n: number,
  title: string,
  employer: string,
  country: string,
  city: string,
  score: number | null,
  mock: MockJob["mock"]
): MockJob {
  return {
    ...meta,
    id: `00000000-0000-4000-8000-0000000e${String(n).padStart(4, "0")}`,
    title,
    employer,
    canonical_employer: employer,
    location: loc(country, city),
    triage: score !== null && score >= 60 ? "shortlisted" : "below_threshold",
    best_score: score,
    conflict_state: "none",
    conflict_note: null,
    pay: basePay,
    deadline: baseDeadline,
    availability: "open",
    tags: [],
    pinned: false,
    posted_at: `2026-11-${String(26 - n).padStart(2, "0")}T07:00:00Z`,
    mock,
  } as MockJob
}

export const jobs: MockJob[] = [
  job(1, "Senior Actuarial Analyst", "Kafue Re", "Zambia", "Lusaka", 82, {
    visa_sponsorship: "not_stated",
    relocation_required: "no",
    work_model: "hybrid",
    employment_type: "permanent",
    required_skills: ["Python", "RMS"],
    min_education: "bachelors",
    years_experience: 5,
  }),
  job(
    2,
    "Catastrophe Modeller",
    "Lake Tanganyika Insurance",
    "Kenya",
    "Nairobi",
    77,
    {
      visa_sponsorship: "yes",
      relocation_required: "yes",
      work_model: "on_site",
      employment_type: "permanent",
      required_skills: ["RMS"],
      min_education: "masters",
      years_experience: 4,
    }
  ),
  job(
    3,
    "Pricing Actuary",
    "Zambezi Mutual",
    "South Africa",
    "Johannesburg",
    71,
    {
      visa_sponsorship: "no",
      relocation_required: "yes",
      work_model: "hybrid",
      employment_type: "permanent",
      required_skills: ["Python"],
      min_education: "bachelors",
      years_experience: 6,
    }
  ),
  job(
    4,
    "Risk Analyst (remote)",
    "Northwind Analytics",
    "United Kingdom",
    "London",
    88,
    {
      visa_sponsorship: "not_stated",
      relocation_required: "no",
      work_model: "remote",
      employment_type: "contract",
      required_skills: ["Python", "Power BI"],
      min_education: "not_stated",
      years_experience: 3,
    }
  ),
  job(5, "Data Engineer", "Copperline Digital", "Zambia", "Kitwe", 64, {
    visa_sponsorship: "not_stated",
    relocation_required: "no",
    work_model: "remote",
    employment_type: "permanent",
    required_skills: ["Python"],
    min_education: "bachelors",
    years_experience: 3,
  }),
  job(6, "Reinsurance Analyst", "Baobab Re", "Mauritius", "Port Louis", 69, {
    visa_sponsorship: "yes",
    relocation_required: "yes",
    work_model: "on_site",
    employment_type: "permanent",
    required_skills: ["Power BI"],
    min_education: "bachelors",
    years_experience: 4,
  }),
  job(7, "Head of Actuarial", "Kafue Re", "Zambia", "Lusaka", 58, {
    visa_sponsorship: "not_stated",
    relocation_required: "no",
    work_model: "on_site",
    employment_type: "permanent",
    required_skills: ["Python", "RMS"],
    min_education: "masters",
    years_experience: 12,
  }),
  job(8, "Analytics Lead", "Savanna Labs", "Netherlands", "Amsterdam", 73, {
    visa_sponsorship: "yes",
    relocation_required: "yes",
    work_model: "hybrid",
    employment_type: "permanent",
    required_skills: ["Python", "Power BI"],
    min_education: "masters",
    years_experience: 7,
  }),
  job(9, "Junior Data Analyst", "Copperline Digital", "Zambia", "Ndola", 45, {
    visa_sponsorship: "no",
    relocation_required: "no",
    work_model: "on_site",
    employment_type: "fixed_term",
    required_skills: ["Power BI"],
    min_education: "bachelors",
    years_experience: 1,
  }),
  job(
    10,
    "Capital Modelling Actuary",
    "Northwind Analytics",
    "Ireland",
    "Dublin",
    80,
    {
      visa_sponsorship: "yes",
      relocation_required: "yes",
      work_model: "hybrid",
      employment_type: "permanent",
      required_skills: ["Python", "RMS"],
      min_education: "masters",
      years_experience: 6,
    }
  ),
  job(11, "Risk Manager", "Zambezi Mutual", "Zambia", "Lusaka", 66, {
    visa_sponsorship: "not_stated",
    relocation_required: "not_stated",
    work_model: "hybrid",
    employment_type: "permanent",
    required_skills: [],
    min_education: "bachelors",
    years_experience: 8,
  }),
  job(12, "Senior BI Developer", "Savanna Labs", "Kenya", "Nairobi", 61, {
    visa_sponsorship: "no",
    relocation_required: "not_stated",
    work_model: "remote",
    employment_type: "contract",
    required_skills: ["Power BI"],
    min_education: "not_stated",
    years_experience: 5,
  }),
]

export const sources: Source[] = [
  {
    ...meta,
    id: IDS.src1,
    connector: "greenhouse",
    name: "Greenhouse boards",
    access: "api",
    config: {},
    access_notes: null,
    rate_limit: null,
    permitted_actions: [],
    enabled: true,
    health: { status: "ok", consecutive_failures: 0, last_error: null },
    last_success_at: "2026-11-26T06:02:00Z",
  } as unknown as Source,
  {
    ...meta,
    id: IDS.src2,
    connector: "himalayas",
    name: "Himalayas remote jobs",
    access: "api",
    config: {},
    access_notes: null,
    rate_limit: null,
    permitted_actions: [],
    enabled: true,
    health: { status: "degraded", consecutive_failures: 1, last_error: "Slow" },
    last_success_at: "2026-11-25T06:03:00Z",
  } as unknown as Source,
  {
    ...meta,
    id: IDS.src3,
    connector: "alert_email",
    name: "Job alert emails",
    access: "mail",
    config: {},
    access_notes: null,
    rate_limit: null,
    permitted_actions: [],
    enabled: true,
    health: { status: "ok", consecutive_failures: 0, last_error: null },
    last_success_at: "2026-11-26T06:05:00Z",
  } as unknown as Source,
  {
    ...meta,
    id: IDS.src4,
    connector: "careers_page",
    name: "Kafue Re careers page",
    access: "web",
    config: {},
    access_notes: null,
    rate_limit: null,
    permitted_actions: [],
    enabled: false,
    health: { status: "unknown", consecutive_failures: 0, last_error: null },
    last_success_at: null,
  } as unknown as Source,
]

export const employers: WatchedEmployer[] = [
  {
    ...meta,
    id: "00000000-0000-4000-8000-000000000f01",
    name: "Kafue Re",
    board_type: "greenhouse",
    board_slug: "kafue-re",
    priority: 1,
    cooldown_days: 30,
    always_ask_first: true,
  },
  {
    ...meta,
    id: "00000000-0000-4000-8000-000000000f02",
    name: "Northwind Analytics",
    board_type: "lever",
    board_slug: "northwind",
    priority: 0,
    cooldown_days: null,
    always_ask_first: false,
  },
]

const criterion = (name: string, weight: number, hint: string) => ({
  name,
  weight,
  anchors: {
    "0": `No sign of ${hint}`,
    "3": `Some ${hint}, with gaps`,
    "5": `Clear, strong ${hint}`,
  },
})

export const rubrics: Rubric[] = [
  {
    ...meta,
    id: IDS.rubricActive,
    name: "Actuarial standard",
    body: {
      criteria: [
        criterion("Role fit", 30, "match to the target title"),
        criterion("Skills match", 25, "match on required skills"),
        criterion("Seniority", 15, "match on level"),
        criterion("Pay", 15, "pay at or above the floor"),
        criterion("Location and work model", 15, "a workable location"),
      ],
      penalties: [],
      thresholds: { shortlist: 60, tailor: 70, auto_apply: 85 },
    },
    family: IDS.rubricFamily,
    version: 1,
    status: "active",
  } as unknown as Rubric,
]

export const settings: Setting[] = [
  setting(
    "automation.daily_cap",
    "automation",
    "Daily cap",
    5,
    "integer",
    "Maximum applications sent per day."
  ),
  setting(
    "automation.weekly_cap",
    "automation",
    "Weekly cap",
    20,
    "integer",
    "Maximum applications sent per week."
  ),
  setting(
    "automation.quiet_hours_start",
    "automation",
    "Quiet hours start",
    "21:00",
    "time",
    "No outward action starts after this time."
  ),
  setting(
    "automation.quiet_hours_end",
    "automation",
    "Quiet hours end",
    "07:00",
    "time",
    "Outward actions may resume at this time."
  ),
  setting(
    "matching.employer_cooldown_days",
    "matching",
    "Employer cooldown",
    30,
    "integer",
    "Days to wait after applying."
  ),
  setting(
    "matching.roles_per_employer_scope",
    "matching",
    "Roles per employer",
    "same_department",
    "enum",
    "How wide the one-role rule is.",
    ["same_department", "whole_employer", "off"]
  ),
  setting(
    "matching.max_live_per_employer",
    "matching",
    "Live applications per employer",
    1,
    "integer",
    "Applications that may be live at once."
  ),
  setting(
    "matching.conflict_winner",
    "matching",
    "Winner across campaigns",
    "highest_score",
    "enum",
    "How the winner is chosen.",
    ["highest_score", "campaign_priority_then_score"]
  ),
  setting(
    "scoring.threshold_shortlist",
    "scoring",
    "Shortlist threshold",
    60,
    "integer",
    "Minimum score to shortlist."
  ),
  setting(
    "scoring.threshold_tailor",
    "scoring",
    "Tailor threshold",
    70,
    "integer",
    "Minimum score to tailor."
  ),
  setting(
    "scoring.threshold_auto_apply",
    "scoring",
    "Auto-apply threshold",
    85,
    "integer",
    "Minimum score to auto-apply."
  ),
  setting(
    "schedule.sweep_cron",
    "schedule",
    "Sweep schedule",
    "0 6 * * *",
    "cron",
    "Default sweep."
  ),
  setting(
    "budget.currency",
    "budget",
    "Budget currency",
    "USD",
    "currency",
    "Currency of the spend ledger."
  ),
  setting(
    "budget.monthly_cap_minor",
    "budget",
    "Monthly cap",
    null,
    "integer",
    "Spend cap per month in minor units."
  ),
]

function setting(
  key: string,
  group: string,
  label: string,
  value: unknown,
  kind: string,
  description: string,
  choices?: string[]
): Setting {
  return {
    key,
    group,
    label,
    description,
    kind,
    value,
    default: value,
    is_default: true,
    nullable: value === null,
    choices: choices ?? null,
    version: 1,
  } as Setting
}

export function seedCampaigns(): Campaign[] {
  return [
    {
      ...meta,
      id: IDS.camp1,
      name: "Actuarial and risk, Southern Africa",
      track_id: IDS.trackActuarial,
      priority: 1,
      criteria: {
        titles: [
          "Actuarial Analyst",
          "Pricing Actuary",
          "Catastrophe Modeller",
        ],
        keywords: ["reinsurance", "catastrophe", "capital modelling"],
        rules: [
          {
            effect: "exclude",
            reason: "Needs a master's degree I do not have",
            conditions: {
              version: 1,
              root: {
                type: "group",
                op: "and",
                conditions: [
                  {
                    type: "values",
                    facet: "min_education",
                    include: ["masters"],
                  },
                ],
              },
            },
          },
        ],
        locations: [
          { place: "Zambia", kind: "priority" },
          { place: "South Africa", kind: "allow" },
          { place: "Kenya", kind: "allow" },
        ],
        work_models: ["hybrid", "remote"],
        seniority: ["Senior", "Lead"],
        pay_floors: [
          {
            employment_type: "permanent",
            amount_minor: 4_800_000,
            currency: "ZMW",
            period: "year",
          },
        ],
        deprioritise_themes: ["sales targets"],
      },
      unknown_data_policy: {
        pay: "pass_blocks_auto",
        eligibility: "review",
        deadline: null,
      },
      rubric_id: IDS.rubricActive,
      automation: { mode: "ask_then_apply", per_channel: {} },
      budget: { monthly_cap_minor: 2000, per_run_cap_minor: 300 },
      source_ids: [IDS.src1, IDS.src3],
      schedule_cron: null,
      preferred_seniority: "Senior",
      status: "active",
      review_state: "confirmed",
      confirmed_at: T0,
      paused_until: null,
      last_sweep_checkpoint: "2026-11-26T06:00:00Z",
      mode_ceiling: "auto_apply",
    },
    {
      ...meta,
      id: IDS.camp2,
      name: "Remote analytics, worldwide",
      track_id: IDS.trackAnalytics,
      priority: 2,
      criteria: {
        titles: ["Data Analyst", "Analytics Lead"],
        keywords: ["Power BI", "Python"],
        rules: [],
        locations: [],
        work_models: ["remote"],
        seniority: [],
        pay_floors: [],
        deprioritise_themes: [],
      },
      unknown_data_policy: {},
      rubric_id: null,
      automation: { mode: "prepare", per_channel: {} },
      budget: {},
      source_ids: [IDS.src2],
      schedule_cron: null,
      preferred_seniority: null,
      status: "draft",
      review_state: "needs_review",
      confirmed_at: null,
      paused_until: null,
      last_sweep_checkpoint: null,
      mode_ceiling: "prepare",
    },
    {
      ...meta,
      id: IDS.camp3,
      name: "Data engineering, Europe with relocation",
      track_id: IDS.trackAnalytics,
      priority: 3,
      criteria: {
        titles: ["Data Engineer"],
        keywords: ["dbt", "Airflow"],
        rules: [],
        locations: [{ place: "Netherlands", kind: "allow" }],
        work_models: ["hybrid", "on_site"],
        seniority: ["Mid"],
        pay_floors: [
          {
            employment_type: "permanent",
            amount_minor: 6_000_000,
            currency: "EUR",
            period: "year",
          },
        ],
        deprioritise_themes: [],
      },
      unknown_data_policy: {},
      rubric_id: IDS.rubricActive,
      automation: { mode: "save_only", per_channel: {} },
      budget: {},
      source_ids: [IDS.src1],
      schedule_cron: "30 7 * * 1-5",
      preferred_seniority: null,
      status: "paused",
      review_state: "confirmed",
      confirmed_at: T0,
      paused_until: "2026-12-15",
      last_sweep_checkpoint: "2026-11-18T06:00:00Z",
      mode_ceiling: "auto_apply",
    },
  ] as Campaign[]
}
