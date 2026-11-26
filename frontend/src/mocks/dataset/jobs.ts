/**
 * Fictional jobs for the Matches mock: about 40 roles that between them cover every facet
 * state (yes / no / not stated, each work model, each pay state), a conflict group with held
 * roles, and a few tags. Every employer and person here is invented.
 */
import type {
  AssessmentOut,
  CampaignOut,
  CustomFacetOut,
  FactOut,
  JobDetail,
  RubricOut,
  SavedViewOut,
  TagRuleOut,
} from "@/features/matches/types"
import { seedCampaigns } from "./campaigns"

/** A job as the mock stores it: the contract's JobDetail plus the source name. */
export type MockJob = JobDetail & {
  source: string
  snoozed_until?: string | null
}

type ApplyEmail = NonNullable<JobDetail["apply_email"]>

/** Where a role can be applied to, as `app.apply.target` reports it (a mailbox is connected). */
export function channelCandidates(
  email: ApplyEmail | null,
  applyUrl: string | null
): JobDetail["apply_channel_candidates"] {
  return [
    {
      channel: "email",
      available: !!email?.usable,
      reason: !email
        ? "The posting gives no application address."
        : email.usable
          ? `Sends to ${email.address} from your connected mailbox.`
          : `${email.address} is not confirmed yet. Confirm it to send by email.`,
    },
    {
      channel: "browser",
      available: false,
      reason: "No browser runner is set up for this site.",
    },
    {
      channel: "manual",
      available: !!(applyUrl || email),
      reason: applyUrl
        ? "You apply yourself through the posting's link."
        : "You apply yourself.",
    },
  ]
}

/** Every third role asks for applications by email: an address quoted in the posting, unconfirmed. */
function applyTarget(method: string, slug: string) {
  const apply_email: ApplyEmail | null =
    method === "email"
      ? {
          address: `careers@${slug}.example.com`,
          found_in: "posting_text",
          evidence: `Send your CV and a cover letter to careers@${slug}.example.com by the closing date.`,
          confirmed: false,
          confirmed_by: null,
          confirmed_at: null,
          trusted_domain: false,
          usable: false,
        }
      : null
  return {
    apply_email,
    apply_channel_candidates: channelCandidates(
      apply_email,
      `https://careers.example.com/${slug}`
    ),
  }
}

const DAY = 86_400_000
const NOW = Date.parse("2026-11-26T08:00:00Z")
const iso = (daysAgo: number) => new Date(NOW - daysAgo * DAY).toISOString()
const dateIn = (days: number) =>
  new Date(NOW + days * DAY).toISOString().slice(0, 10)

type Row = {
  title: string
  employer: string
  city: string
  country: string
  triage: JobDetail["triage"]
  score: number
  source: string
  age: number
  fn: string
  level: string
  conflict?: { state: JobDetail["conflict_state"]; note?: string }
  tags?: string[]
  pinned?: boolean
}

const R = (
  title: string,
  employer: string,
  city: string,
  country: string,
  triage: Row["triage"],
  score: number,
  source: string,
  age: number,
  fn = "Data",
  level = "Senior",
  extra: Partial<Row> = {}
): Row => ({
  title,
  employer,
  city,
  country,
  triage,
  score,
  source,
  age,
  fn,
  level,
  ...extra,
})

const ROWS: Row[] = [
  R(
    "Head of Data",
    "Copperline Bank",
    "Lusaka",
    "Zambia",
    "shortlisted",
    88,
    "Careers page",
    2,
    "Data",
    "Head",
    {
      conflict: { state: "winner" },
      pinned: true,
      tags: ["leadership"],
    }
  ),
  R(
    "Senior Data Analyst",
    "Copperline Bank",
    "Lusaka",
    "Zambia",
    "new",
    74,
    "BrighterMonday",
    3,
    "Data",
    "Senior",
    {
      conflict: { state: "held", note: "Outranked by Head of Data, 88 vs 74" },
    }
  ),
  R(
    "Data Manager",
    "Copperline Bank",
    "Lusaka",
    "Zambia",
    "new",
    70,
    "LinkedIn",
    5,
    "Data",
    "Manager",
    {
      conflict: { state: "held", note: "Outranked by Head of Data, 88 vs 70" },
    }
  ),
  R(
    "Analytics Lead",
    "Mosi Insurance",
    "Lusaka",
    "Zambia",
    "new",
    91,
    "Careers page",
    1,
    "Analytics",
    "Lead",
    {
      tags: ["actuarial-adjacent"],
    }
  ),
  R(
    "Pricing Analyst",
    "Mosi Insurance",
    "Lusaka",
    "Zambia",
    "new",
    72,
    "Careers page",
    1,
    "Actuarial",
    "Senior",
    {
      conflict: {
        state: "held",
        note: "Outranked by Analytics Lead, 91 vs 72",
      },
    }
  ),
  R(
    "Catastrophe Modelling Analyst",
    "Zambezi Re",
    "Johannesburg",
    "South Africa",
    "new",
    86,
    "Recruiter email",
    4,
    "Risk",
    "Senior",
    {
      tags: ["actuarial-adjacent", "relocation"],
    }
  ),
  R(
    "Senior BI Developer",
    "Kafue Data Works",
    "Lusaka",
    "Zambia",
    "new",
    82,
    "BrighterMonday",
    2
  ),
  R(
    "Data Engineer",
    "Chambishi Mining Analytics",
    "Kitwe",
    "Zambia",
    "new",
    79,
    "LinkedIn",
    6,
    "Engineering"
  ),
  R(
    "Lead Data Scientist",
    "Northstar Remote Ltd",
    "Remote",
    "United Kingdom",
    "new",
    84,
    "We Work Remotely",
    3,
    "Data",
    "Lead",
    {
      tags: ["remote"],
    }
  ),
  R(
    "Analytics Manager",
    "Lusaka Grid Energy",
    "Lusaka",
    "Zambia",
    "new",
    77,
    "Careers page",
    8,
    "Analytics",
    "Manager"
  ),
  R(
    "Insights Analyst",
    "Zambezi Agritech",
    "Chipata",
    "Zambia",
    "new",
    66,
    "BrighterMonday",
    9,
    "Analytics",
    "Mid"
  ),
  R(
    "Risk Data Lead",
    "Sahara Payments",
    "Nairobi",
    "Kenya",
    "new",
    81,
    "LinkedIn",
    4,
    "Risk",
    "Lead",
    {
      tags: ["relocation"],
    }
  ),
  R(
    "Senior Reporting Analyst",
    "Luangwa Health Trust",
    "Lusaka",
    "Zambia",
    "new",
    75,
    "Careers page",
    11,
    "Analytics"
  ),
  R(
    "Head of Analytics",
    "Bluefin Analytics",
    "London",
    "United Kingdom",
    "new",
    80,
    "LinkedIn",
    2,
    "Analytics",
    "Head",
    {
      tags: ["relocation"],
    }
  ),
  R(
    "Data Platform Manager",
    "Mukuba Telecom",
    "Ndola",
    "Zambia",
    "new",
    78,
    "Careers page",
    7,
    "Engineering",
    "Manager"
  ),
  R(
    "Machine Learning Engineer",
    "Kariba Logistics",
    "Remote",
    "South Africa",
    "new",
    69,
    "Remote OK",
    12,
    "Engineering"
  ),
  R(
    "Decision Scientist",
    "Victoria Falls Travel Co",
    "Livingstone",
    "Zambia",
    "new",
    63,
    "BrighterMonday",
    14,
    "Data",
    "Mid"
  ),
  R(
    "Business Intelligence Lead",
    "Copperbelt Breweries",
    "Ndola",
    "Zambia",
    "shortlisted",
    85,
    "Careers page",
    5,
    "Analytics",
    "Lead",
    {
      tags: ["leadership"],
    }
  ),
  R(
    "Senior Actuarial Analyst",
    "Mosi Life",
    "Lusaka",
    "Zambia",
    "shortlisted",
    83,
    "Recruiter email",
    6,
    "Actuarial",
    "Senior",
    {
      tags: ["actuarial-adjacent"],
    }
  ),
  R(
    "Principal Data Analyst",
    "Northstar Remote Ltd",
    "Remote",
    "United Kingdom",
    "shortlisted",
    87,
    "We Work Remotely",
    4,
    "Analytics",
    "Principal",
    {
      tags: ["remote"],
      pinned: true,
    }
  ),
  R(
    "Data Governance Manager",
    "Copperline Insurance",
    "Lusaka",
    "Zambia",
    "shortlisted",
    79,
    "LinkedIn",
    9,
    "Data",
    "Manager"
  ),
  R(
    "Analytics Engineer",
    "Tamarind Fintech",
    "Cape Town",
    "South Africa",
    "shortlisted",
    82,
    "LinkedIn",
    3,
    "Engineering",
    "Senior",
    {
      tags: ["relocation"],
    }
  ),
  R(
    "Senior Data Scientist",
    "Lake Tanganyika Fisheries Board",
    "Mpulungu",
    "Zambia",
    "shortlisted",
    76,
    "Careers page",
    10
  ),
  R(
    "Statistician",
    "Zambia Statistics Partnership",
    "Lusaka",
    "Zambia",
    "below_threshold",
    58,
    "Careers page",
    13,
    "Research",
    "Mid"
  ),
  R(
    "Junior Data Analyst",
    "Kafue Data Works",
    "Lusaka",
    "Zambia",
    "below_threshold",
    41,
    "BrighterMonday",
    15,
    "Data",
    "Junior"
  ),
  R(
    "Credit Risk Modeller",
    "Sahara Payments",
    "Kigali",
    "Rwanda",
    "below_threshold",
    61,
    "LinkedIn",
    9,
    "Risk",
    "Senior"
  ),
  R(
    "Data Entry Supervisor",
    "Chambishi Mining Analytics",
    "Chingola",
    "Zambia",
    "below_threshold",
    34,
    "BrighterMonday",
    20,
    "Operations",
    "Supervisor"
  ),
  R(
    "Product Analyst",
    "Nyanja Mobile",
    "Remote",
    "Zambia",
    "below_threshold",
    64,
    "Remote OK",
    7,
    "Product",
    "Mid"
  ),
  R(
    "Monitoring and Evaluation Officer",
    "Luangwa Health Trust",
    "Mfuwe",
    "Zambia",
    "below_threshold",
    52,
    "Careers page",
    18,
    "Research",
    "Mid"
  ),
  R(
    "Quantitative Analyst",
    "Bluefin Analytics",
    "Dublin",
    "Ireland",
    "below_threshold",
    67,
    "LinkedIn",
    6,
    "Risk",
    "Senior",
    {
      tags: ["relocation"],
    }
  ),
  R(
    "Research Data Manager",
    "Copperbelt University Trust",
    "Kitwe",
    "Zambia",
    "below_threshold",
    59,
    "Careers page",
    16,
    "Research",
    "Manager"
  ),
  R(
    "Data Analyst (Contract)",
    "Kariba Logistics",
    "Lusaka",
    "Zambia",
    "below_threshold",
    55,
    "Recruiter email",
    4,
    "Data",
    "Mid"
  ),
  R(
    "Senior Analyst, Revenue",
    "Mukuba Telecom",
    "Ndola",
    "Zambia",
    "new",
    71,
    "LinkedIn",
    2,
    "Engineering",
    "Senior",
    {
      conflict: {
        state: "held",
        note: "Outranked by Data Platform Manager, 78 vs 71",
      },
    }
  ),
  R(
    "Reporting Manager",
    "Lusaka Grid Energy",
    "Lusaka",
    "Zambia",
    "archived",
    62,
    "Careers page",
    30,
    "Analytics",
    "Manager"
  ),
  R(
    "Data Officer",
    "Zambezi Agritech",
    "Mazabuka",
    "Zambia",
    "archived",
    48,
    "BrighterMonday",
    35,
    "Data",
    "Mid"
  ),
  R(
    "BI Analyst",
    "Victoria Falls Travel Co",
    "Livingstone",
    "Zambia",
    "skipped",
    57,
    "BrighterMonday",
    21,
    "Analytics",
    "Mid"
  ),
  R(
    "Head of Insights",
    "Nyanja Mobile",
    "Lusaka",
    "Zambia",
    "new",
    89,
    "Careers page",
    1,
    "Analytics",
    "Head",
    {
      tags: ["leadership"],
    }
  ),
  R(
    "Senior Data Consultant",
    "Mopane Advisory",
    "Gaborone",
    "Botswana",
    "new",
    73,
    "Recruiter email",
    5,
    "Consulting",
    "Senior"
  ),
  R(
    "Analytics Translator",
    "Tamarind Fintech",
    "Remote",
    "South Africa",
    "new",
    68,
    "We Work Remotely",
    10,
    "Product",
    "Senior",
    {
      tags: ["remote"],
    }
  ),
  R(
    "Data Quality Lead",
    "Mosi Insurance",
    "Lusaka",
    "Zambia",
    "archived",
    70,
    "Careers page",
    40,
    "Data",
    "Lead"
  ),
  // APPLIED_ROWS: roles with an application (Applications, Today, the Job page), in the
  // order of the application seeds. Kept last so the ids above stay stable.
  R(
    "Head of Data",
    "Kafue Analytics",
    "Lusaka",
    "Zambia",
    "shortlisted",
    91,
    "Company site",
    14,
    "Data"
  ),
  R(
    "Analytics Lead",
    "Mulungushi Digital",
    "Ndola",
    "Zambia",
    "shortlisted",
    78,
    "Company site",
    15,
    "Data"
  ),
  R(
    "Pricing Actuary",
    "Luangwa Re",
    "Kitwe",
    "Zambia",
    "shortlisted",
    88,
    "Company site",
    16,
    "Actuarial"
  ),
  R(
    "Risk Data Manager",
    "Copperline Energy",
    "Livingstone",
    "Zambia",
    "shortlisted",
    74,
    "Company site",
    17,
    "Data"
  ),
  R(
    "Data Platform Lead",
    "Zambezi Mining Systems",
    "Lusaka",
    "Zambia",
    "shortlisted",
    86,
    "Company site",
    18,
    "Data"
  ),
  R(
    "Principal Data Engineer",
    "Nyika Labs",
    "Lusaka",
    "Zambia",
    "shortlisted",
    82,
    "Company site",
    19,
    "Data"
  ),
  R(
    "Head of Analytics",
    "Kariba Freight",
    "Kitwe",
    "Zambia",
    "shortlisted",
    80,
    "Company site",
    20,
    "Data"
  ),
  R(
    "Director of Data Science",
    "Lusaka Fintech Co",
    "Lusaka",
    "Zambia",
    "shortlisted",
    90,
    "Company site",
    21,
    "Data"
  ),
  R(
    "Reserving Actuary",
    "Chambeshi Insurance",
    "Lusaka",
    "Zambia",
    "shortlisted",
    76,
    "Company site",
    22,
    "Actuarial"
  ),
  R(
    "BI Manager",
    "Mpongwe Agritech",
    "Kabwe",
    "Zambia",
    "shortlisted",
    72,
    "Company site",
    23,
    "Data"
  ),
  R(
    "Head of Risk Analytics",
    "Kasama Capital",
    "Kasama",
    "Zambia",
    "shortlisted",
    93,
    "Company site",
    24,
    "Data"
  ),
  R(
    "Analytics Director",
    "Livingstone Logistics",
    "Livingstone",
    "Zambia",
    "shortlisted",
    89,
    "Company site",
    25,
    "Data"
  ),
  R(
    "Data Manager",
    "Ndola Brewing",
    "Ndola",
    "Zambia",
    "shortlisted",
    61,
    "Company site",
    26,
    "Data"
  ),
]

// ---- facet values cycle so every state appears ------------------------------------------------

const YN = ["yes", "no", "not_stated"] as const
const cyc = <T>(arr: readonly T[], i: number, k = 1) =>
  arr[(i * k) % arr.length]

const SKILLS = [
  ["SQL", "Power BI", "Python"],
  ["Python", "Spark", "Airflow"],
  ["SQL", "Tableau"],
  ["R", "Statistics"],
  ["Python", "Machine learning", "SQL"],
  ["Excel", "Power BI"],
  ["SQL", "dbt", "Snowflake"],
]
const PAY: {
  state: "stated" | "estimated" | "not_stated"
  min?: number
  max?: number
  cur?: string
}[] = [
  { state: "stated", min: 3_000_000, max: 4_200_000, cur: "ZMW" },
  { state: "not_stated" },
  { state: "estimated", min: 2_600_000, max: 3_400_000, cur: "ZMW" },
  { state: "stated", min: 6_500_000, max: 8_000_000, cur: "GBP" },
  { state: "not_stated" },
]

const EVIDENCE = {
  relocation_required: {
    yes: (c: string) =>
      `The successful candidate will relocate to ${c} within three months.`,
    no: () => "You can do this role from where you live now.",
  },
  visa_sponsorship: {
    yes: () => "We sponsor work permits for the right candidate.",
    no: () => "We are unable to sponsor work permits for this role.",
  },
  relocation_assistance: {
    yes: () =>
      "A relocation package covers flights and the first month's housing.",
    no: () => "No relocation support is offered.",
  },
}

function facetsFor(i: number, row: Row): MockJob["facets"] {
  const remote = row.city === "Remote"
  const abroad = row.country !== "Zambia"
  const reloc = remote ? "no" : abroad ? "yes" : cyc(YN, i, 2)
  const sponsor = abroad ? cyc(YN, i) : "not_stated"
  const assist = cyc(YN, i, 5)
  const wm = remote
    ? "remote"
    : cyc(["on_site", "hybrid", "not_stated"] as const, i)
  const scope = remote
    ? cyc(["worldwide", "regions", "country_only"] as const, i)
    : "not_stated"
  const edu = cyc(
    ["none_stated", "bachelors", "masters", "doctorate"] as const,
    i,
    3
  )
  const ev = <V>(value: V, evidence?: string | null) => ({
    value,
    evidence: value === "not_stated" ? null : (evidence ?? null),
  })
  return {
    relocation_required: ev(
      reloc,
      reloc === "yes"
        ? EVIDENCE.relocation_required.yes(row.city)
        : EVIDENCE.relocation_required.no()
    ),
    visa_sponsorship: ev(
      sponsor,
      sponsor === "yes"
        ? EVIDENCE.visa_sponsorship.yes()
        : EVIDENCE.visa_sponsorship.no()
    ),
    relocation_assistance: ev(
      assist,
      assist === "yes"
        ? EVIDENCE.relocation_assistance.yes()
        : EVIDENCE.relocation_assistance.no()
    ),
    needs_account: ev(cyc(YN, i, 4), "Apply through our candidate portal."),
    work_model: ev(
      wm,
      wm === "remote"
        ? "This is a fully remote role."
        : wm === "hybrid"
          ? "Three days a week in the office, two from home."
          : "Based in our office five days a week."
    ),
    remote_scope: ev(
      scope,
      scope === "worldwide"
        ? "Work from anywhere in the world."
        : scope === "regions"
          ? "Open to candidates in Africa and Europe time zones."
          : "Open to residents of the country only."
    ),
    remote_regions: scope === "regions" ? ["Africa", "Europe"] : [],
    where_must_live: ev(
      remote
        ? { kind: "anywhere" as const, places: [] }
        : { kind: "places" as const, places: [row.country] },
      remote ? "Live anywhere." : `You must live in ${row.country}.`
    ),
    work_rights: ev(
      abroad
        ? cyc(
            [
              "existing_right_required",
              "sponsorship_possible",
              "not_stated",
            ] as const,
            i
          )
        : "not_stated",
      "Candidates must have the right to work in the country."
    ),
    timezone_overlap: null,
    hiring_arrangement: ev(
      cyc(["employee", "contractor", "eor", "not_stated"] as const, i),
      "You will be employed directly."
    ),
    employment_type: ev(
      row.title.includes("Contract")
        ? "contract"
        : cyc(
            ["permanent", "fixed_term", "permanent", "not_stated"] as const,
            i
          ),
      "This is a permanent position."
    ),
    required_skills: cyc(SKILLS, i),
    preferred_skills: cyc(SKILLS, i + 3).slice(0, 1),
    min_education: ev(
      { level: edu, required: i % 2 === 0 },
      edu === "none_stated"
        ? null
        : `A ${edu === "bachelors" ? "bachelor's" : edu === "masters" ? "master's" : "doctoral"} degree in a quantitative field is ${i % 2 === 0 ? "required" : "preferred"}.`
    ),
    required_qualifications:
      row.fn === "Actuarial" ? ["Qualified actuary"] : [],
    years_experience: ev(
      i % 6 === 5 ? null : 2 + (i % 8),
      i % 6 === 5 ? null : `At least ${2 + (i % 8)} years in a similar role.`
    ),
    languages: ["English"],
    travel_percent: ev(
      i % 4 === 0 ? 10 : null,
      "Some travel to regional offices."
    ),
    industry: cyc(
      ["Banking", "Insurance", "Mining", "Energy", "Technology", "Health"],
      i
    ),
  }
}

function rawText(row: Row, f: MockJob["facets"]): string {
  const sentences = [
    `${row.employer} is hiring a ${row.title} to join the ${row.fn.toLowerCase()} team in ${row.city === "Remote" ? "a remote setting" : row.city}.`,
    "You will turn messy operational data into decisions people trust, own reporting end to end and coach analysts.",
    f.relocation_required?.evidence,
    f.visa_sponsorship?.evidence,
    f.relocation_assistance?.evidence,
    f.work_model?.evidence,
    f.min_education?.evidence,
    f.years_experience?.evidence,
    `Skills we need: ${(f.required_skills ?? []).join(", ")}.`,
  ]
  return sentences.filter(Boolean).join("\n\n")
}

/** How many trailing ROWS carry an application (see the APPLIED_ROWS note in ROWS). */
export const APPLIED_ROWS = 13
const FIRST_APPLIED = () => ROWS.length - APPLIED_ROWS
/** The id of the n-th seeded application (1-based); the applications mock uses the same ids. */
export const applicationIdFor = (n: number) =>
  `a0000000-0000-4000-8000-${String(n).padStart(12, "0")}`
/** The job id of the n-th seeded application (1-based). */
export const appliedJobId = (n: number) =>
  `00000000-0000-4000-8000-${String(FIRST_APPLIED() + n).padStart(12, "0")}`

export function makeJobs(): MockJob[] {
  return linkConflicts(buildJobs())
}

/** A held role names the role that outranks it (the winner at the same employer). */
function linkConflicts(jobs: MockJob[]): MockJob[] {
  for (const j of jobs) {
    if (j.conflict_state !== "held" || !j.conflict) continue
    const w = jobs.find(
      (x) =>
        x.canonical_employer === j.canonical_employer &&
        x.conflict_state === "winner"
    )
    if (!w) continue
    j.conflict = {
      ...j.conflict,
      outranked_by_job_id: w.id,
      outranked_by_title: w.title,
      outranked_by_score: w.best_score,
    }
  }
  return jobs
}

function buildJobs(): MockJob[] {
  return ROWS.map((row, i) => {
    const id = `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`
    const facets = facetsFor(i, row)
    const p = cyc(PAY, i)
    const deadlineKind = cyc(
      ["dated", "open_until_filled", "not_stated"] as const,
      i
    )
    const slug = row.employer.toLowerCase().replace(/[^a-z]+/g, "-")
    return {
      id,
      created_at: iso(row.age),
      updated_at: iso(Math.max(0, row.age - 1)),
      title: row.title,
      employer: row.employer,
      canonical_employer: row.employer,
      location: {
        country: row.country,
        city: row.city === "Remote" ? null : row.city,
        region: null,
        raw:
          row.city === "Remote"
            ? `Remote (${row.country})`
            : `${row.city}, ${row.country}`,
      },
      triage: row.triage,
      best_score: row.score,
      conflict_state: row.conflict?.state ?? "none",
      conflict_note: row.conflict?.note ?? null,
      pay: {
        state: p.state,
        min_minor: p.min ?? null,
        max_minor: p.max ?? null,
        currency: p.cur ?? null,
        period: p.state === "not_stated" ? null : "year",
        estimate_source:
          p.state === "estimated" ? "Salary survey, Lusaka, 2026" : null,
        estimate_assumptions:
          p.state === "estimated"
            ? "Similar titles at employers of this size"
            : null,
        estimated_on: p.state === "estimated" ? dateIn(-20) : null,
      },
      deadline: {
        state: deadlineKind,
        on: deadlineKind === "dated" ? dateIn(4 + (i % 20)) : null,
      },
      availability: row.triage === "archived" && i % 2 ? "closed" : "open",
      tags: row.tags ?? [],
      pinned: row.pinned ?? false,
      posted_at: iso(row.age),
      recruiter:
        row.source === "Recruiter email" ? "Talent Partners (fictional)" : null,
      requisition_id: `REQ-${1000 + i}`,
      function: row.fn,
      level: row.level,
      facets,
      custom_facets: {
        cat_modelling_tools:
          row.fn === "Risk" || row.fn === "Actuarial"
            ? {
                value: "yes",
                evidence:
                  "Experience with RMS or Verisk catastrophe models is essential.",
                model: "mock-small",
              }
            : i % 3 === 0
              ? { value: "no", evidence: null, model: "mock-small" }
              : { value: "not_stated", evidence: null, model: "mock-small" },
      },
      apply_url: `https://careers.example.com/${slug}/${i + 1}`,
      apply_method: cyc(["portal", "email", "easy_apply"], i),
      ...applyTarget(cyc(["portal", "email", "easy_apply"], i), slug),
      requirements: [
        ...(facets.required_skills ?? []).map((s) => ({
          text: `Strong ${s}`,
          kind: "required" as const,
          skill: s,
        })),
        ...(facets.preferred_skills ?? []).map((s) => ({
          text: `Experience with ${s}`,
          kind: "preferred" as const,
          skill: s,
        })),
        {
          text: "Clear written communication with non-technical leaders",
          kind: "required" as const,
          skill: null,
        },
      ],
      raw_text: rawText(row, facets),
      sightings: [
        {
          source_id: null,
          url: `https://careers.example.com/${slug}/${i + 1}`,
          first_seen_at: iso(row.age),
          last_seen_at: iso(0),
        },
      ],
      notes: null,
      last_checked_at: iso(0),
      repost_of_id: null,
      application_id:
        i >= FIRST_APPLIED() ? applicationIdFor(i - FIRST_APPLIED() + 1) : null,
      source: row.source,
      pay_state: p.state,
      work_model: facets.work_model?.value ?? "not_stated",
      remote_scope: facets.remote_scope?.value ?? "not_stated",
      conflict:
        row.conflict && row.conflict.state !== "none"
          ? {
              state: row.conflict.state,
              note: row.conflict.note ?? null,
              outranked_by_job_id: null,
              outranked_by_title: null,
              score: row.score,
              outranked_by_score: null,
              reason: row.conflict.state === "held" ? "outranked" : null,
            }
          : null,
    }
  })
}

// ---- assessments, rubric, facts, campaigns ---------------------------------------------------

export const RUBRIC_ID = "10000000-0000-4000-8000-000000000001"
const CRITERIA = [
  { name: "Role fit", weight: 25 },
  { name: "Skills match", weight: 20 },
  { name: "Seniority", weight: 15 },
  { name: "Location and work model", weight: 15 },
  { name: "Pay", weight: 15 },
  { name: "Employer", weight: 10 },
]

export const RUBRIC = {
  id: RUBRIC_ID,
  created_at: iso(60),
  updated_at: iso(10),
  name: "Data leadership rubric",
  family: "data-leadership",
  version: 3,
  status: "active",
  body: {
    criteria: CRITERIA.map((c) => ({ ...c, anchors: {} })),
    penalties: [],
    thresholds: { shortlist: 75, tailor: 80, auto_apply: 90 },
  },
} as unknown as RubricOut

export const FACTS = [
  ["F-101", "Led a team of six analysts at a regional insurer for four years."],
  [
    "F-102",
    "Built the board's monthly KPI pack in Power BI, replacing 30 spreadsheets.",
  ],
  [
    "F-103",
    "Wrote production SQL and Python pipelines feeding pricing models.",
  ],
  ["F-104", "Holds a BSc in Mathematics and Statistics."],
  ["F-105", "Based in Lusaka; open to relocation within southern Africa."],
  ["F-106", "Presented quarterly risk findings to the executive committee."],
].map(
  ([code, text], i) =>
    ({
      id: `20000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
      created_at: iso(90),
      updated_at: iso(30),
      review_state: "confirmed",
      origin: "owner",
      confirmed_at: iso(30),
      code,
      kind: "achievement",
      text,
      canonical_wording: true,
      experience_id: null,
      tags: [],
      tracks: [],
      keep_out_of_prompts: false,
      confidence_note: null,
      status: "approved",
    }) as FactOut
)

/** The shared campaigns (data/campaigns): Zambia-based roles in the first, remote in the second. */
export const CAMPAIGNS: CampaignOut[] = seedCampaigns().slice(0, 2)

/** Integer 0..5 ratings whose weighted points add up to exactly `target`, as even as possible. */
function ratingsFor(target: number, seed: number): number[] {
  const ideal = (target / 100) * 5
  let best: number[] = CRITERIA.map(() => Math.round(ideal))
  let bestCost = Infinity
  const r = new Array<number>(CRITERIA.length).fill(0)
  const walk = (k: number, sum: number) => {
    if (k === CRITERIA.length) {
      if (Math.abs(sum - target) > 1e-9) return
      const cost = r.reduce(
        (c, v, j) => c + (v - ideal) ** 2 + (((seed + j) % 3) - 1) * 0.01 * v,
        0
      )
      if (cost < bestCost) {
        bestCost = cost
        best = [...r]
      }
      return
    }
    for (let v = 0; v <= 5; v++) {
      r[k] = v
      walk(k + 1, sum + (CRITERIA[k].weight * v) / 5)
    }
  }
  walk(0, 0)
  return best
}

/** Ratings that add up to the job's best score, with cited facts. */
export function assessmentFor(job: MockJob, i: number): AssessmentOut {
  const target = job.best_score ?? 0
  const ratings = ratingsFor(target, i).map((rating, k) => {
    const c = CRITERIA[k]
    return {
      criterion: c.name,
      rating,
      evidence_fact_ids:
        rating >= 3
          ? [
              FACTS[(i + k) % FACTS.length].id,
              FACTS[(i + k + 2) % FACTS.length].id,
            ]
          : [],
      note:
        rating >= 4
          ? `${c.name}: strong evidence from your Kit.`
          : rating >= 3
            ? `${c.name}: partly covered.`
            : `${c.name}: little evidence; a rating without evidence is capped at 3.`,
    }
  })
  const score = Math.round(
    ratings.reduce((s, r, k) => s + (CRITERIA[k].weight * r.rating) / 5, 0)
  )
  const f = job.facets
  return {
    id: `40000000-0000-4000-8000-${job.id.slice(-12)}`,
    created_at: job.created_at,
    updated_at: job.updated_at,
    job_id: job.id,
    campaign_id: job.location.city === null ? CAMPAIGNS[1].id : CAMPAIGNS[0].id,
    rubric_id: RUBRIC_ID,
    rubric_version: 3,
    state: "scored",
    base_score: null,
    filter_results: [
      {
        name: "Location",
        result:
          job.location.country === "Zambia" || job.location.city === null
            ? "pass"
            : "unknown",
        reason:
          job.location.country === "Zambia"
            ? "In Zambia, a target country"
            : job.location.city === null
              ? "Remote role"
              : `${job.location.country} is not on the list; relocation answer needed`,
        mandatory: true,
      },
      {
        name: "Work rights",
        result:
          f.work_rights?.value === "existing_right_required"
            ? "fail"
            : f.work_rights?.value === "not_stated" &&
                job.location.country !== "Zambia"
              ? "unknown"
              : "pass",
        reason:
          f.work_rights?.value === "existing_right_required"
            ? "Requires an existing right to work you do not hold"
            : f.work_rights?.value === "not_stated" &&
                job.location.country !== "Zambia"
              ? "The posting does not say"
              : "You can work there",
        mandatory: true,
      },
      {
        name: "Pay floor",
        result: job.pay.state === "stated" ? "pass" : "unknown",
        reason:
          job.pay.state === "stated"
            ? "Stated band clears your floor"
            : job.pay.state === "estimated"
              ? "Only an estimate; blocks auto-apply"
              : "Pay not stated; blocks auto-apply",
        mandatory: false,
      },
      {
        name: "Deadline",
        result: "pass",
        reason:
          job.deadline.state === "dated"
            ? `Closes ${job.deadline.on}`
            : job.deadline.state === "open_until_filled"
              ? "Open until filled"
              : "No deadline stated",
        mandatory: true,
      },
    ],
    ratings,
    score,
    gaps: [
      ...(f.required_qualifications ?? []).map((q) => `${q} is required`),
      ...(f.min_education?.value.level === "masters" &&
      f.min_education.value.required
        ? ["A master's degree is required; your Kit has a bachelor's"]
        : []),
      ...(job.pay.state === "not_stated" ? ["Pay is not stated"] : []),
      "No direct evidence of people management above six reports",
    ],
    model: "mock-scorer",
    cost_minor: 2,
    cost_micros: 20000,
    cost_currency: "USD",
    override: null,
    is_conflict_winner: job.conflict_state === "winner",
  }
}

export function seedViews(): SavedViewOut[] {
  const v = (
    n: number,
    name: string,
    conditions: unknown[],
    group_by: string | null = null
  ) =>
    ({
      id: `50000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
      created_at: iso(10),
      updated_at: iso(10),
      name,
      pinned: true,
      sort_order: n,
      count: null,
      body: {
        conditions: {
          version: 1,
          root: { type: "group", op: "and", negate: false, conditions },
        },
        group_by,
        sort: [{ field: "best_score", direction: "desc" }],
        scope: "matches",
      },
    }) as SavedViewOut
  const vf = (facet: string, include: string[], exclude: string[] = []) => ({
    type: "values",
    facet,
    include,
    exclude,
    match: "any",
  })
  return [
    v(1, "Relocation, sponsorship offered", [
      vf("facets.relocation_required", ["yes"]),
      vf("facets.visa_sponsorship", ["yes"]),
    ]),
    v(2, "Requires Python, no master's required", [
      vf("facets.required_skills", ["python"]),
      vf("facets.min_education.level", [], ["masters", "doctorate"]),
    ]),
    v(3, "Remote worldwide, pay stated", [
      vf("facets.remote_scope", ["worldwide"]),
      vf("pay.state", ["stated"]),
    ]),
    v(
      4,
      "Relocation roles by sponsorship",
      [vf("facets.relocation_required", ["yes"])],
      "facets.visa_sponsorship"
    ),
  ]
}

export function seedTagRules(): TagRuleOut[] {
  return [
    {
      id: "60000000-0000-4000-8000-000000000001",
      created_at: iso(20),
      updated_at: iso(20),
      tag: "relocation",
      enabled: true,
      conditions: {
        version: 1,
        root: {
          type: "group",
          op: "and",
          negate: false,
          conditions: [
            {
              type: "values",
              facet: "facets.relocation_required",
              include: ["yes"],
              exclude: [],
              match: "any",
            },
          ],
        },
      },
    } as TagRuleOut,
  ]
}

export function seedCustomFacets(): CustomFacetOut[] {
  return [
    {
      id: "70000000-0000-4000-8000-000000000001",
      created_at: iso(15),
      updated_at: iso(15),
      key: "cat_modelling_tools",
      question: "Does the role require RMS or Verisk experience?",
      enabled: true,
    },
  ]
}
