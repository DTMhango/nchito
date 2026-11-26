/**
 * The JSON shapes inside an interview pack section (`content`) and a practice answer's `feedback`.
 * The contract types these as free objects (`dict[str, Any]`); the shapes are the backend's
 * `app/pipeline/interview/shapes.py`. Every sentence about the owner is a `Claim`.
 */
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type InterviewPack = S["InterviewPackOut"]
export type InterviewEstimate = S["InterviewEstimateOut"]
export type SectionVersion = S["InterviewSectionOut"]
export type PracticeOut = S["PracticeOut"]
export type PracticeIn = S["PracticeIn"]
export type StoryEdit = S["StoryEditIn"]
export type CheckResult = S["CheckResult"]
export type PackStatus = NonNullable<InterviewPack["status"]>
export type QuestionCategory = NonNullable<PracticeIn["category"]>

export type Claim = { text: string; fact_ids: string[] }

export type RoleBrief = {
  summary: string
  emphasised: string[]
  requirements: string[]
  level_notes: string
  company_notes: string[]
  research_note: string
  posting_changed: boolean
}
export type WhyYou = { points: { requirement: string; point: Claim }[] }
export type LikelyQuestion = {
  category: QuestionCategory
  question: string
  why_asked: string
  answer: Claim
  story_ids: string[]
}
export type Questions = { items: LikelyQuestion[] }
export type Story = {
  id: string
  title: string
  requirement: string
  situation: string
  task: string
  action: string
  result: string
  fact_ids: string[]
  favourite: boolean
}
export type Stories = { items: Story[] }
export type QuestionsToAsk = { items: { question: string; why: string }[] }
export type Gaps = {
  items: { requirement: string; gap: string; answer: Claim }[]
}
export type PayLine = {
  topic: string
  question: string
  status: "confirmed" | "told_them" | "not_disclosed" | "decide"
  kit_answer: string | null
  told_them: string | null
  note: string
}
export type PaySheet = { lines: PayLine[]; posting_pay: string | null }
export type CribSheet = {
  role: string
  points: string[]
  stories: string[]
  questions_to_ask: string[]
  pay: string[]
  gaps: string[]
  flagged: string[]
}

export type SectionContent = {
  role_brief: RoleBrief
  why_you: WhyYou
  questions: Questions
  stories: Stories
  questions_to_ask: QuestionsToAsk
  gaps: Gaps
  pay_sheet: PaySheet
  crib_sheet: CribSheet
}
export type SectionKey = keyof SectionContent

/** One section as the pack mirrors it (`InterviewPackOut.sections[key]`). */
export type PackSection = {
  version: number
  origin: SectionVersion["origin"]
  status: SectionVersion["status"]
  flagged: boolean
  fact_ids: string[]
  content: Record<string, unknown>
  check_results: CheckResult[]
  model: string | null
  created_at?: string | null
}

/** `InterviewPackOut.basis` (`app/pipeline/interview/basis.py`). */
export type Basis = {
  source: "submitted_packet" | "latest_checked_spec" | "none"
  packet_id?: string | null
  packet_hash?: string | null
  spec_version?: number | null
  spec_hash?: string | null
  posting_changed?: boolean
  answers?: { question: string; value: string }[]
}

/** `PracticeOut.feedback`. */
export type PracticeFeedback = {
  feedback: string
  strengths: string[]
  improve: string[]
  suggested_answer: Claim | null
}

/** Display order of the sections the UI knows how to show; which exist is the pack's (setting). */
export const SECTION_ORDER: SectionKey[] = [
  "role_brief",
  "why_you",
  "questions",
  "stories",
  "questions_to_ask",
  "gaps",
  "pay_sheet",
  "crib_sheet",
]

export const SECTION_TITLES: Record<string, string> = {
  role_brief: "Role brief",
  why_you: "Why you",
  questions: "Likely questions",
  stories: "Story bank",
  questions_to_ask: "Questions to ask them",
  gaps: "Gaps and how to address them",
  pay_sheet: "Pay and logistics",
  crib_sheet: "Crib sheet",
}

export const sectionTitle = (key: string) =>
  SECTION_TITLES[key] ?? key.replace(/_/g, " ")

/** Sections the model builds (regenerate makes sense); the pay and crib sheets are code. */
export const CODE_SECTIONS = new Set(["pay_sheet", "crib_sheet"])

export const sectionsOf = (pack: InterviewPack) =>
  pack.sections as Record<string, PackSection>

export const basisOf = (pack: InterviewPack) =>
  (pack.basis ?? null) as Basis | null

/** Open: generation queued or running, so poll and hold edits. */
export const isOpen = (s: PackStatus | undefined) =>
  s === "queued" || s === "running"
