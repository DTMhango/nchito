/**
 * Fictional mock interview sessions for the MSW backend (shapes of `MockSessionOut`). Each job gets two
 * seeded sessions the first time its list is read: one done, whose feedback has a suggestion removed by
 * the truth checks, and one paused by the budget with an answer waiting for the interviewer.
 */
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type MockSessionRecord = S["MockSessionOut"]
export type MockTurnRecord = S["MockTurnOut"]

export const MOCK_ESTIMATE_MICROS = 42_000
export const UNVERIFIED_PROMPT =
  "Is this accurate? Add it to your library as a draft fact?"
export const MOCK_QUESTIONS = [
  "Tell me about a report you automated.",
  "How would you approach our reporting backlog?",
  "Describe a time you had to explain data to a sceptical manager.",
  "Why this role?",
]

const now = () => new Date().toISOString()
let n = 0
export const mockId = () =>
  `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`

export function turn(
  seq: number,
  over: Partial<MockTurnRecord> &
    Pick<MockTurnRecord, "role" | "kind" | "step_key">
): MockTurnRecord {
  return {
    id: mockId(),
    seq,
    text: "",
    question_index: 0,
    category: "behavioural",
    feedback: null,
    claims: [],
    fact_ids: [],
    created_at: now(),
    ...over,
  }
}

export function session(
  jobId: string,
  over: Partial<MockSessionRecord> = {}
): MockSessionRecord {
  return {
    id: mockId(),
    created_at: now(),
    updated_at: now(),
    pack_id: `pack-${jobId}`,
    round_id: null,
    mode: "behavioural",
    length: 2,
    use_pack_questions: true,
    feedback_each: false,
    timer_seconds: null,
    status: "active",
    pending_step: null,
    expects: "a0.0",
    question_index: 0,
    probes: 0,
    estimate_micros: MOCK_ESTIMATE_MICROS,
    budget_micros: Math.floor((MOCK_ESTIMATE_MICROS * 120) / 100),
    cost_micros: 0,
    feedback: null,
    scores: {},
    error: null,
    finished_at: null,
    turns: [],
    unverified_prompt: UNVERIFIED_PROMPT,
    ...over,
  }
}

/** Checked feedback on one answer, with one suggested sentence the truth checks removed. */
export function answerFeedback(question: string, questionIndex: number) {
  return {
    question_index: questionIndex,
    question,
    category: "behavioural",
    answer_refs: ["A2"],
    structure: "Clear situation; the result comes late.",
    relevance: "Speaks to the reporting automation the posting asks for.",
    specificity: "One figure; name the tools you used.",
    strong: ["Uses a real figure"],
    tighten: ["Lead with the result"],
    scores: { structure: 3, relevance: 4, specificity: 2, delivery: 3 },
    suggested: [
      {
        text: "I cut monthly reporting time by 40% by automating the sales pack.",
        fact_ids: ["F-1"],
        sources: [
          {
            code: "F-1",
            kind: "fact",
            text: "Cut monthly reporting time by 40% by automating the sales pack.",
          },
        ],
        status: "pass",
        warnings: [],
      },
      {
        text: "The team saved a day each month.",
        fact_ids: ["A2"],
        sources: [
          {
            code: "A2",
            kind: "your_words",
            text: "It saved the team a day each month.",
          },
        ],
        status: "pass",
        warnings: [],
      },
    ],
    removed: [
      {
        text: "I led a team of 12 analysts on the sales pack.",
        fact_ids: ["F-1"],
        reasons: ["points[0].point: figure '12' is not in the cited facts"],
      },
    ],
  }
}

export function seedSessions(jobId: string): MockSessionRecord[] {
  const done = session(jobId, {
    length: 1,
    status: "done",
    expects: null,
    cost_micros: 31_000,
    finished_at: now(),
    scores: { structure: 3, relevance: 4, specificity: 2, delivery: 3 },
    turns: [
      turn(1, {
        role: "interviewer",
        kind: "question",
        step_key: "q0",
        text: MOCK_QUESTIONS[0],
      }),
      turn(2, {
        role: "owner",
        kind: "answer",
        step_key: "a0.0",
        text: "I automated the sales pack and cut reporting time by 40%. It saved the team a day each month.",
        fact_ids: ["F-1"],
        claims: [
          {
            id: "c1",
            text: "It saved the team a day each month.",
            status: "unverified",
            fact_code: null,
          },
        ],
      }),
    ],
  })
  done.feedback = {
    summary: "A solid start: lead with the result and name your tools.",
    overall: done.scores,
    answers: [answerFeedback(MOCK_QUESTIONS[0], 0)],
  }
  const paused = session(jobId, {
    mode: "mixed",
    status: "paused",
    expects: null,
    pending_step: "reply",
    error:
      "budget exhausted (session): needs 9000 USD minor units, 0 available",
    cost_micros: 50_400,
    turns: [
      turn(1, {
        role: "interviewer",
        kind: "question",
        step_key: "q0",
        text: MOCK_QUESTIONS[1],
      }),
      turn(2, {
        role: "owner",
        kind: "answer",
        step_key: "a0.0",
        text: "I would start with the sales pack.",
      }),
    ],
  })
  return [paused, done]
}
