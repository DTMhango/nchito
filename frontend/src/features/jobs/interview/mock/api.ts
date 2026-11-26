/** Mock interview endpoints (`backend/app/api/routers/interview.py`, wave 4), typed from the contract. */
import { queryOptions } from "@tanstack/react-query"
import type { components } from "@/lib/api/types"
import { api, ApiError, unwrap } from "@/lib/api/client"

type S = components["schemas"]
export type MockSession = S["MockSessionOut"]
export type MockTurn = S["MockTurnOut"]
export type MockClaim = S["MockClaimOut"]
export type MockSessionIn = S["MockSessionIn"]
export type MockMode = MockSessionIn["mode"]
export type MockEstimate = S["MockEstimateOut"]
export type MockProgress = S["MockProgressOut"]
export type InterviewRound = S["InterviewRoundOut"]

/** A suggested sentence that passed the truth checks, with what it rests on. */
export type KeptClaim = {
  text: string
  fact_ids: string[]
  sources: { code: string; kind: "fact" | "your_words"; text: string }[]
  status: "pass" | "warn"
  warnings?: string[]
}
/** A suggested sentence removed by the truth checks (text withheld when a keep-out fact was involved). */
export type RemovedClaim = {
  text: string | null
  fact_ids: string[]
  reasons: string[]
}
/** Checked feedback on one answer (a coach turn's `feedback`, or one item of the final feedback). */
export type AnswerFeedback = {
  structure: string
  relevance: string
  specificity: string
  strong: string[]
  tighten: string[]
  scores: Record<string, number>
  suggested: KeptClaim[]
  removed: RemovedClaim[]
  withheld?: string
}
export type FinalAnswer = AnswerFeedback & {
  question_index: number
  question: string
  category: string | null
  answer_refs: string[]
}
export type FinalFeedback = {
  summary: string
  overall: Record<string, number>
  answers: FinalAnswer[]
}

export const MOCK_MODES: { value: MockMode; label: string }[] = [
  { value: "behavioural", label: "Behavioural" },
  { value: "technical", label: "Technical (the posting's stack)" },
  { value: "role", label: "Role and domain" },
  { value: "mixed", label: "Mixed" },
  { value: "tough", label: "Tough interviewer" },
]

export const mockKeys = {
  list: (jobId: string) => ["jobs", jobId, "mock-sessions"] as const,
  progress: (jobId: string) => ["jobs", jobId, "mock-progress"] as const,
  session: (id: string) => ["interview-mock", id] as const,
  rounds: (jobId: string) => ["jobs", jobId, "interview-rounds"] as const,
}

const job = (jobId: string) => ({ path: { job_id: jobId } })
const sid = (id: string) => ({ path: { session_id: id } })

export const sessionsQuery = (jobId: string) =>
  queryOptions({
    queryKey: mockKeys.list(jobId),
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/interview-pack/mock-sessions", {
          params: job(jobId),
        })
      ),
  })

export const progressQuery = (jobId: string) =>
  queryOptions({
    queryKey: mockKeys.progress(jobId),
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/interview-pack/mock-progress", {
          params: job(jobId),
        })
      ),
  })

export const sessionQuery = (id: string) =>
  queryOptions({
    queryKey: mockKeys.session(id),
    queryFn: () =>
      unwrap(api.GET("/api/interview-mock/{session_id}", { params: sid(id) })),
  })

export const roundsQuery = (jobId: string) =>
  queryOptions({
    queryKey: mockKeys.rounds(jobId),
    retry: false,
    queryFn: async () => {
      try {
        return await unwrap(
          api.GET("/api/jobs/{job_id}/interview-pack/rounds", {
            params: job(jobId),
          })
        )
      } catch {
        return [] as InterviewRound[]
      }
    },
  })

export const estimateQuery = (
  jobId: string,
  q: {
    mode: MockMode
    length: number
    use_pack_questions: boolean
    round_id: string | null
  }
) =>
  queryOptions({
    queryKey: [...mockKeys.list(jobId), "estimate", q],
    retry: false,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/interview-pack/mock-sessions/estimate", {
          params: { ...job(jobId), query: q },
        })
      ),
  })

export const startSession = (jobId: string, body: MockSessionIn) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/interview-pack/mock-sessions", {
      params: job(jobId),
      body,
    })
  )

export const answer = (
  id: string,
  body: { text: string; skip: boolean; turn_key: string | null }
) =>
  unwrap(
    api.POST("/api/interview-mock/{session_id}/answer", {
      params: sid(id),
      body,
    })
  )

export const finish = (id: string) =>
  unwrap(
    api.POST("/api/interview-mock/{session_id}/finish", { params: sid(id) })
  )

export const resume = (id: string, budgetMicros: number | null) =>
  unwrap(
    api.POST("/api/interview-mock/{session_id}/resume", {
      params: sid(id),
      body: { budget_micros: budgetMicros },
    })
  )

export const removeSession = (id: string) =>
  unwrap(api.DELETE("/api/interview-mock/{session_id}", { params: sid(id) }))

export const resolveClaim = (
  id: string,
  turnId: string,
  claimId: string,
  action: "add_draft" | "dismiss"
) =>
  unwrap(
    api.POST(
      "/api/interview-mock/{session_id}/turns/{turn_id}/claims/{claim_id}",
      {
        params: {
          path: { session_id: id, turn_id: turnId, claim_id: claimId },
        },
        body: { action },
      }
    )
  )

export const saveStory = (id: string, turnId: string) =>
  unwrap(
    api.POST("/api/interview-mock/{session_id}/turns/{turn_id}/story", {
      params: { path: { session_id: id, turn_id: turnId } },
      body: {},
    })
  )

/** Download a session (transcript and feedback) and hand it to the browser. */
export async function exportSession(id: string, fmt: "pdf" | "docx" | "txt") {
  const { data, error, response } = await api.GET(
    "/api/interview-mock/{session_id}/export",
    { params: { ...sid(id), query: { fmt } }, parseAs: "blob" }
  )
  if (!response.ok) throw new ApiError(response.status, error)
  if (typeof URL.createObjectURL === "function") {
    const url = URL.createObjectURL(data as Blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `mock-interview.${fmt}`
    a.click()
    URL.revokeObjectURL(url)
  }
}
