/**
 * Fictional sample data for the dev-only component gallery (/dev/components) and tests.
 * Every organisation, person and figure here is invented.
 */
import type { Stage } from "@/components/stage-pill"

export const SAMPLE_FACTS = {
  "F-104":
    "Led the design and build of an in-house risk modelling platform, 2024 to 2025, used in the annual renewals.",
  "F-107":
    "Line manager for 6 people across analytics, BI and data engineering since 2022.",
  "F-112":
    "Wrote and maintain Python pricing tools used by underwriters in 9 markets.",
}

export const SAMPLE_CARDS: {
  id: string
  employer: string
  role: string
  score: number
  stage: Stage
  next: string
  due?: boolean
}[] = [
  {
    id: "c1",
    employer: "Kafue Analytics",
    role: "Head of Data",
    score: 88,
    stage: "ready",
    next: "Approve today",
    due: true,
  },
  {
    id: "c2",
    employer: "Example Payments",
    role: "Engineering Manager, MLOps",
    score: 82,
    stage: "shortlisted",
    next: "Decide by Fri",
  },
  {
    id: "c3",
    employer: "Sample Re",
    role: "Exposure Manager",
    score: 74,
    stage: "tailoring",
    next: "Draft ready today",
  },
  {
    id: "c4",
    employer: "Zed Logistics",
    role: "Analytics Lead",
    score: 69,
    stage: "submitted",
    next: "Follow up Thu",
    due: true,
  },
]

export const SAMPLE_FUNNEL = [
  { label: "found", value: 214 },
  { label: "new", value: 61 },
  { label: "passed filters", value: 23 },
  { label: "above threshold", value: 12 },
  { label: "tailored", value: 4 },
  { label: "applied", value: 2 },
]

export const SAMPLE_SPARK = [0, 1, 0, 2, 1, 0, 0, 3, 1, 2, 0, 1, 2, 2]

export const SAMPLE_SCORES = [
  91, 88, 86, 85, 82, 81, 80, 79, 77, 75, 75, 73, 72, 71, 70, 68, 67, 66, 64,
  63, 62, 61, 60, 59, 58, 57, 56, 55, 55, 54, 53, 52, 51, 50, 50, 49, 48, 47,
  46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 31, 30, 29, 27, 26,
  24, 22, 19, 15,
]

export const SAMPLE_WHY = [
  {
    rule: "Hard filters",
    value: "4 of 4 passed",
    source: "Campaign: Data leadership",
    version: "criteria v3",
    outcome: "pass" as const,
  },
  {
    rule: "Auto-apply threshold",
    value: "85",
    source: "Settings default",
    version: "v1",
    outcome: "fail" as const,
    detail: "Score 79 is below 85, so it waits for you.",
  },
  {
    rule: "Work rights",
    value: "Not stated",
    source: "Posting",
    outcome: "unknown" as const,
    detail: "Unknown is not yes: it goes to review.",
  },
]
