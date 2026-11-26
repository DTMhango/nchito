/** Fictional roles for the mock backend. Every employer, person and link here is invented. */
import type {
  ApplicationDetail,
  AssessmentOut,
  ContactOut,
  JobDetail,
  PendingAction,
  TimelineEvent,
} from "@/features/jobs/api"

const at = (day: number, h = 9) =>
  new Date(Date.UTC(2026, 10, day, h, 0)).toISOString()

const base = {
  created_at: at(20),
  updated_at: at(25),
  availability: "open" as const,
  pinned: false,
  custom_facets: {},
  apply_method: "website",
  last_checked_at: at(25),
  repost_of_id: null,
  recruiter: null,
  requisition_id: null,
  notes: null,
  tags: [] as string[],
  triage: "shortlisted" as const,
  deadline: { state: "dated" as const, on: "2026-12-12" },
  pay: { state: "not_stated" as const },
  pay_state: "not_stated" as const,
  work_model: "hybrid" as const,
  remote_scope: "not_stated" as const,
  posted_at: at(18),
}

export function buildJobs(): JobDetail[] {
  return [
    {
      ...base,
      id: "job-1",
      title: "Senior Risk Analyst",
      employer: "Lusaka Copper Holdings",
      canonical_employer: "Lusaka Copper Holdings",
      location: { country: "Zambia", region: "Copperbelt", city: "Kitwe", raw: "Kitwe, Zambia" },
      best_score: 88,
      conflict_state: "winner",
      conflict_note: null,
      function: "Risk",
      level: "Senior",
      tags: ["mining", "risk"],
      pay: {
        state: "stated",
        min_minor: 4_500_000,
        max_minor: 6_000_000,
        currency: "ZMW",
        period: "month",
      },
      apply_url: "https://careers.example.com/lch/senior-risk-analyst",
      application_id: "app-1",
      notes: "Spoke to the recruiter on the phone.",
      facets: {
        relocation_required: { value: "no", evidence: "This role is based at our Kitwe office." },
        visa_sponsorship: { value: "not_stated", evidence: null },
        relocation_assistance: { value: "not_stated", evidence: null },
        needs_account: { value: "yes", evidence: "Create a profile on our careers portal to apply." },
        work_model: { value: "hybrid", evidence: "Three days on site, two from home." },
        work_rights: { value: "existing_right_required", evidence: "Candidates must already hold the right to work in Zambia." },
        employment_type: { value: "permanent", evidence: "A permanent position." },
        years_experience: { value: 6, evidence: "At least six years in a risk or actuarial role." },
        required_skills: ["Risk modelling", "Power BI", "SQL"],
        preferred_skills: ["Python"],
        remote_regions: [],
        required_qualifications: ["Actuarial exam progress"],
        languages: ["English"],
      },
      requirements: [
        { text: "Six years in risk or actuarial work", kind: "required", skill: null },
        { text: "Power BI dashboards", kind: "required", skill: "Power BI" },
        { text: "Python for analysis", kind: "preferred", skill: "Python" },
      ],
      raw_text:
        "Senior Risk Analyst, Lusaka Copper Holdings.\n\nYou will own the quarterly risk review for our mining operations on the Copperbelt.\n\nRequirements: six years in a risk or actuarial role; Power BI; SQL. Python is an advantage.\n\nThree days on site in Kitwe, two from home.",
      sightings: [
        { source_id: "s1", url: "https://careers.example.com/lch/senior-risk-analyst", first_seen_at: at(18), last_seen_at: at(25) },
        { source_id: "s2", url: "https://jobs.example.org/listing/48213", first_seen_at: at(19), last_seen_at: at(24) },
      ],
    },
    {
      ...base,
      id: "job-2",
      title: "Risk Analyst",
      employer: "Lusaka Copper Holdings",
      canonical_employer: "Lusaka Copper Holdings",
      location: { country: "Zambia", region: "Copperbelt", city: "Kitwe", raw: "Kitwe" },
      best_score: 74,
      conflict_state: "held",
      conflict_note: "Outranked by Senior Risk Analyst, 88 vs 74.",
      function: "Risk",
      level: "Mid",
      application_id: null,
      apply_url: null,
      facets: {
        relocation_required: { value: "no", evidence: "Based in Kitwe." },
        visa_sponsorship: { value: "no", evidence: "We are unable to sponsor visas." },
        relocation_assistance: { value: "not_stated", evidence: null },
        needs_account: { value: "no", evidence: null },
        work_model: { value: "on_site", evidence: "Full-time on site." },
        required_skills: ["Excel"],
        preferred_skills: [],
        remote_regions: [],
        required_qualifications: [],
        languages: [],
      },
      requirements: [{ text: "Three years of analysis experience", kind: "required", skill: null }],
      raw_text: "Risk Analyst at Lusaka Copper Holdings. Support the senior team.",
      sightings: [{ source_id: "s1", url: "https://careers.example.com/lch/risk-analyst", first_seen_at: at(19), last_seen_at: at(25) }],
    },
    {
      ...base,
      id: "job-3",
      title: "Actuarial Analyst",
      employer: "Zambezi Re Services",
      canonical_employer: "Zambezi Re Services",
      location: { country: "Zambia", region: "Lusaka", city: "Lusaka", raw: "Lusaka" },
      best_score: 69,
      conflict_state: "none",
      conflict_note: null,
      function: "Actuarial",
      level: "Mid",
      tags: ["reinsurance"],
      application_id: null,
      apply_url: null,
      facets: {
        relocation_required: { value: "no", evidence: null },
        visa_sponsorship: { value: "not_stated", evidence: null },
        relocation_assistance: { value: "not_stated", evidence: null },
        needs_account: { value: "no", evidence: null },
        required_skills: ["Reserving"],
        preferred_skills: [],
        remote_regions: [],
        required_qualifications: [],
        languages: [],
      },
      requirements: [],
      raw_text: "Actuarial Analyst, Zambezi Re Services, Lusaka.",
      sightings: [
        { source_id: "s3", url: "https://zambezi-re.example.com/careers/actuarial-analyst", first_seen_at: at(21), last_seen_at: at(25) },
        { source_id: "s4", url: "https://jobs.example.org/listing/50077", first_seen_at: at(22), last_seen_at: at(25) },
      ],
    },
  ]
}

export function buildAssessments(): AssessmentOut[] {
  const common = { created_at: at(24), updated_at: at(24), campaign_id: "camp-1", rubric_id: "rub-1", cost_minor: 0, cost_currency: null, override: null, model: "claude-haiku-5-5", state: "scored" as const }
  return [
    {
      ...common,
      id: "as-1",
      job_id: "job-1",
      rubric_version: 3,
      score: 88,
      is_conflict_winner: true,
      gaps: ["No Python project in your kit is older than two years."],
      filter_results: [
        { name: "Work rights", result: "pass", reason: "You hold the right to work in Zambia.", mandatory: true },
        { name: "Pay floor", result: "pass", reason: "Stated pay is above your floor.", mandatory: true },
        { name: "Commute", result: "unknown", reason: "Hybrid days not confirmed.", mandatory: false },
      ],
      ratings: [
        { criterion: "Sector fit", rating: 5, evidence_fact_ids: ["F-112"], note: "Eight years in mining risk matches the brief." },
        { criterion: "Seniority", rating: 4, evidence_fact_ids: ["F-087", "F-090"], note: "Led a team of four, as the role asks." },
        { criterion: "Tools", rating: 3, evidence_fact_ids: [], note: "Power BI yes, Python is thin." },
      ],
    },
    {
      ...common,
      id: "as-2",
      job_id: "job-2",
      rubric_version: 3,
      score: 74,
      is_conflict_winner: false,
      gaps: [],
      filter_results: [],
      ratings: [{ criterion: "Sector fit", rating: 4, evidence_fact_ids: ["F-112"], note: "Same employer, junior scope." }],
    },
  ]
}

export function buildApplication(): ApplicationDetail {
  return {
    id: "app-1",
    created_at: at(23),
    updated_at: at(25),
    job_id: "job-1",
    campaign_id: "camp-1",
    stage: "ready",
    channel: "browser",
    title: "Senior Risk Analyst",
    employer: "Lusaka Copper Holdings",
    score: 88,
    next_step: "Approve and apply",
    next_due: at(30),
    pinned: false,
    open_pending_actions: 1,
    applied_at: null,
    spec: {
      competencies: [],
      experience: [],
      skills: [],
      letter: [],
      requirement_match: [
        { requirement: "Six years in risk or actuarial work", strength: "strong", evidence_fact_ids: ["F-112"], note: null },
        { requirement: "Power BI dashboards", strength: "strong", evidence_fact_ids: [], note: null },
        { requirement: "Python for analysis", strength: "partial", evidence_fact_ids: [], note: null },
      ],
    },
    check_results: [],
    approved_packet_id: null,
    submitted_snapshot: null,
    confirmation_evidence: [],
    applied_outside: false,
    snoozed: false,
    origin: "system",
    owner_attested: false,
  }
}

export const buildTimeline = (): TimelineEvent[] => [
  { id: "t1", created_at: at(23, 10), kind: "stage_changed", actor: "system", detail: { reason: "Score above the shortlist threshold" } },
  { id: "t2", created_at: at(24, 14), kind: "documents_tailored", actor: "agent", detail: {} },
  { id: "t3", created_at: at(25, 8), kind: "note_edited", actor: "owner", detail: {} },
]

export const buildPending = (): PendingAction[] => [
  {
    id: "pa-1",
    created_at: at(24),
    updated_at: at(24),
    type: "approve",
    application_id: "app-1",
    agent_task_id: null,
    group_key: null,
    title: "Approve the CV and letter for Senior Risk Analyst",
    detail: {},
    checkpoint: null,
    snoozed: false,
    deadline: at(29),
    status: "open",
  },
]

export const buildContacts = (): ContactOut[] => [
  {
    id: "c1",
    created_at: at(21),
    updated_at: at(21),
    job_id: "job-1",
    name: "Mwila Banda",
    role: "Recruiter",
    email: "mwila.banda@example.com",
    link: null,
    notes: "Prefers email before noon.",
    origin: "owner",
  },
]
