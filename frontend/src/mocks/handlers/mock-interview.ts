/**
 * MSW handlers for the wave 4 mock interview endpoints (`routers/interview.py`), typed from the contract.
 * The interviewer is scripted: after each answer it asks the next question, and after the last it writes
 * feedback with one suggestion removed by the truth checks. Errors are `{detail: {code, reason}}`.
 */
import { http, HttpResponse } from "msw"
import type { components } from "@/lib/api/types"
import {
  answerFeedback,
  MOCK_ESTIMATE_MICROS,
  MOCK_QUESTIONS,
  mockId,
  seedSessions,
  session,
  turn,
  type MockSessionRecord,
} from "../dataset/mock-interview"

type S = components["schemas"]

let sessions = new Map<string, MockSessionRecord>()
const seeded = new Set<string>()

export function resetMockInterviewMock() {
  sessions = new Map()
  seeded.clear()
}

export const mockInterviewMock = {
  get: (id: string) => sessions.get(id),
  all: () => [...sessions.values()],
}

function forJob(jobId: string) {
  if (!seeded.has(jobId)) {
    seeded.add(jobId)
    for (const s of seedSessions(jobId)) sessions.set(s.id, s)
  }
  return [...sessions.values()].filter((s) => s.pack_id === `pack-${jobId}`)
}

const refused = (status: number, code: string, reason: string) =>
  HttpResponse.json({ detail: { code, reason } }, { status })

/** The scripted interviewer's reply to the open answer: the next question, or the end and feedback. */
function advance(s: MockSessionRecord) {
  const next = s.question_index + 1
  if (next < s.length) {
    s.question_index = next
    s.turns.push(
      turn(s.turns.length + 1, {
        role: "interviewer",
        kind: "question",
        step_key: `q${next}`,
        question_index: next,
        text: MOCK_QUESTIONS[next % MOCK_QUESTIONS.length],
      })
    )
    s.expects = `a${next}.0`
  } else {
    finishSession(s)
  }
  s.pending_step = null
  s.cost_micros += 9_000
}

function finishSession(s: MockSessionRecord) {
  const answered = [
    ...new Set(
      s.turns
        .filter((t) => t.role === "owner" && t.kind === "answer")
        .map((t) => t.question_index)
    ),
  ]
  const answers = answered.map((qi) =>
    answerFeedback(
      s.turns.find((t) => t.kind === "question" && t.question_index === qi)
        ?.text ?? "",
      qi
    )
  )
  const overall: Record<string, number> = answers.length
    ? { structure: 3, relevance: 4, specificity: 2, delivery: 3 }
    : {}
  s.feedback = {
    summary: answers.length ? "A solid start." : "",
    overall,
    answers,
  }
  s.scores = overall
  s.status = "done"
  s.expects = null
  s.pending_step = null
  s.finished_at = new Date().toISOString()
}

const base = "*/api/jobs/:jobId/interview-pack"
const one = "*/api/interview-mock/:id"

export const mockInterviewHandlers = [
  http.get(`${base}/mock-sessions/estimate`, () =>
    HttpResponse.json<S["MockEstimateOut"]>({
      parts: { ask: 0, replies: MOCK_ESTIMATE_MICROS - 6_000, final: 6_000 },
      total_micros: MOCK_ESTIMATE_MICROS,
      budget_micros: Math.floor((MOCK_ESTIMATE_MICROS * 120) / 100),
      currency: "USD",
    })
  ),
  http.get(`${base}/mock-sessions`, ({ params }) =>
    HttpResponse.json<S["MockSessionOut"][]>(forJob(String(params.jobId)))
  ),
  http.post(`${base}/mock-sessions`, async ({ params, request }) => {
    const body = (await request.json()) as S["MockSessionIn"]
    forJob(String(params.jobId))
    const s = session(String(params.jobId), {
      mode: body.mode,
      length: body.length ?? 5,
      use_pack_questions: body.use_pack_questions ?? true,
      feedback_each: body.feedback_each ?? false,
      timer_seconds: body.timer_seconds ?? null,
      round_id: body.round_id ?? null,
      turns: [
        turn(1, {
          role: "interviewer",
          kind: "question",
          step_key: "q0",
          text: MOCK_QUESTIONS[0],
        }),
      ],
    })
    sessions.set(s.id, s)
    return HttpResponse.json<S["MockSessionOut"]>(s, { status: 201 })
  }),
  http.get(`${base}/mock-progress`, ({ params }) => {
    const done = forJob(String(params.jobId)).filter((s) => s.status === "done")
    return HttpResponse.json<S["MockProgressOut"]>({
      sessions: done.length,
      categories: done.length
        ? [
            {
              category: "behavioural",
              answers: done.length,
              average: 2.8,
              weak: true,
            },
          ]
        : [],
      weak: done.length ? ["behavioural"] : [],
      practise_next: done.length
        ? [
            {
              question: MOCK_QUESTIONS[2],
              category: "behavioural",
              reason: "weak category, not practised",
            },
          ]
        : [],
    })
  }),
  http.get(one, ({ params }) => {
    const s = sessions.get(String(params.id))
    return s
      ? HttpResponse.json<S["MockSessionOut"]>(s)
      : refused(404, "not_found", "mock interview not found")
  }),
  http.delete(one, ({ params }) => {
    sessions.delete(String(params.id))
    return new HttpResponse(null, { status: 204 })
  }),
  http.post(`${one}/answer`, async ({ params, request }) => {
    const s = sessions.get(String(params.id))
    if (!s) return refused(404, "not_found", "mock interview not found")
    const body = (await request.json()) as S["MockAnswerIn"]
    if (!s.expects || (body.turn_key && body.turn_key !== s.expects))
      return refused(
        409,
        "not_your_turn",
        "this session is not waiting for an answer"
      )
    s.turns.push(
      turn(s.turns.length + 1, {
        role: "owner",
        kind: body.skip ? "skip" : "answer",
        step_key: s.expects,
        question_index: s.question_index,
        text: body.skip ? "" : (body.text ?? ""),
      })
    )
    advance(s)
    return HttpResponse.json<S["MockSessionOut"]>(s)
  }),
  http.post(`${one}/finish`, ({ params }) => {
    const s = sessions.get(String(params.id))
    if (!s) return refused(404, "not_found", "mock interview not found")
    if (s.status !== "done") finishSession(s)
    return HttpResponse.json<S["MockSessionOut"]>(s)
  }),
  http.post(`${one}/resume`, async ({ params, request }) => {
    const s = sessions.get(String(params.id))
    if (!s) return refused(404, "not_found", "mock interview not found")
    const body = ((await request.json().catch(() => null)) ??
      {}) as S["MockResumeIn"]
    if (body.budget_micros != null) s.budget_micros = body.budget_micros
    if ((s.status === "paused" || s.status === "failed") && s.pending_step) {
      s.status = "active"
      s.error = null
      advance(s)
    }
    return HttpResponse.json<S["MockSessionOut"]>(s)
  }),
  http.get(
    `${one}/export`,
    () =>
      new HttpResponse("Mock interview", {
        headers: { "Content-Type": "text/plain" },
      })
  ),
  http.post(
    `${one}/turns/:turnId/claims/:claimId`,
    async ({ params, request }) => {
      const s = sessions.get(String(params.id))
      const t = s?.turns.find((x) => x.id === params.turnId)
      const c = t?.claims?.find((x) => x.id === params.claimId)
      if (!t || !c) return refused(404, "not_found", "no such statement")
      const body = (await request.json()) as S["MockClaimIn"]
      if (c.status === "unverified") {
        c.status = body.action === "add_draft" ? "added" : "dismissed"
        c.fact_code = body.action === "add_draft" ? "F-90" : null
      }
      return HttpResponse.json<S["MockTurnOut"]>(t)
    }
  ),
  http.post(`${one}/turns/:turnId/story`, ({ params }) => {
    const s = sessions.get(String(params.id))
    const t = s?.turns.find((x) => x.id === params.turnId)
    if (!s || !t)
      return refused(404, "not_found", "no such answer in this session")
    return HttpResponse.json<S["InterviewSectionOut"]>(
      {
        id: mockId(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        section: "stories",
        version: 1,
        origin: "owner",
        content: {
          items: [
            {
              id: "m1",
              title: "Mock answer",
              requirement: "",
              situation: "",
              task: "",
              action: t.text,
              result: "",
              fact_ids: t.fact_ids,
              favourite: false,
            },
          ],
        },
        fact_ids: t.fact_ids ?? [],
        check_results: [],
        status: "pass",
        flagged: false,
        model: null,
        created_by: "owner",
      },
      { status: 201 }
    )
  }),
]
